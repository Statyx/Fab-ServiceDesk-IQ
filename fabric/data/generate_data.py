#!/usr/bin/env python3
"""Generate the Zava Service Desk synthetic dataset — reference, history and scenario.

Pure offline generation: no tenant, no network. The only inputs are
``fabric/data/world.yaml`` and its seed, so the output is byte-identical on every machine.

Outputs (git-ignored, under ``artifacts/data/`` by default):

* ``lakehouse/<table>.csv``  — dimensions + 90-day facts, for ``LH_ServiceDesk``;
* ``eventhouse/<table>.csv`` — recent history of the six KQL tables, the ``EH_ServiceDesk``
  preload (the live tail comes from ``fabric.eventhouse.inject_event``);
* ``manifest.json``          — row count and SHA-256 per file.

The history contains the scripted incident (Corporate VPN client 6.1.0 on the Fabrikam
Lyon pilot ring) and the resulting XLA breach: Fabrikam's weekly zero-touch rate drops
from 46.0% to 34.0% (−12 points) against a 40% threshold, which triggers a 5% service
credit. Litware shows the same drop, but its contract carries no credit.

  python -m fabric.data.generate_data              # writes artifacts/data/
  python -m fabric.data.generate_data --out <dir>  # elsewhere
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import csv
import hashlib
import io
import json
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import yaml

from fabric._shared.paths import ARTIFACTS, WORLD_SPEC
from fabric.data.schema import EVENTHOUSE, LAKEHOUSE, columns

UTC = timezone.utc
Row = Dict[str, Any]
Tables = Dict[str, List[Row]]

AI_CHANNELS = ("chat", "teams", "voice", "portal")
CONVERSATION_CHANNELS = ("chat", "teams", "voice")
CHANNEL_WEIGHTS = {"chat": 0.33, "teams": 0.20, "voice": 0.17, "portal": 0.18, "email": 0.12}
PRIORITY_WEIGHTS = {"P1": 0.02, "P2": 0.13, "P3": 0.60, "P4": 0.25}
HOUR_WEIGHTS = {7: 0.3, 8: 0.8, 9: 1.0, 10: 1.0, 11: 0.9, 12: 0.6, 13: 0.8, 14: 1.0,
                15: 0.9, 16: 0.8, 17: 0.5, 18: 0.3, 19: 0.15}
DEPARTMENTS = ["Finance", "Sales", "Operations", "HR", "IT", "Legal", "Marketing",
               "Production", "Logistics", "Customer Service"]
FIRST_NAMES = {
    "en": ["James", "Olivia", "Liam", "Emma", "Noah", "Ava", "Ethan", "Mia", "Lucas",
           "Grace", "Henry", "Chloe", "Jack", "Ella", "Oscar", "Amelia"],
    "fr": ["Camille", "Lucas", "Léa", "Hugo", "Chloé", "Louis", "Manon", "Jules", "Inès",
           "Arthur", "Sarah", "Paul", "Julie", "Tom", "Emma", "Nathan"],
    "de": ["Lukas", "Anna", "Leon", "Mia", "Felix", "Lena", "Jonas", "Laura", "Paul",
           "Hannah", "Finn", "Lea", "Max", "Sophie", "Elias", "Marie"],
    "es": ["Hugo", "Lucía", "Pablo", "Sofía", "Daniel", "Martina", "Álvaro", "Paula",
           "Diego", "Carmen", "Javier", "Elena", "Adrián", "Laura", "Mario", "Sara"],
}
LAST_NAMES = {
    "en": ["Smith", "Johnson", "Brown", "Taylor", "Wilson", "Clarke", "Walker", "Wright",
           "Hall", "Green", "Baker", "Hill"],
    "fr": ["Martin", "Bernard", "Dubois", "Thomas", "Robert", "Richard", "Petit", "Durand",
           "Leroy", "Moreau", "Simon", "Laurent"],
    "de": ["Müller", "Schmidt", "Schneider", "Fischer", "Weber", "Meyer", "Wagner",
           "Becker", "Schulz", "Hoffmann", "Koch", "Richter"],
    "es": ["García", "Martínez", "López", "Sánchez", "Pérez", "Gómez", "Martín",
           "Jiménez", "Ruiz", "Hernández", "Díaz", "Moreno"],
}
METRIC_LABELS = {
    "zero_touch_rate": ("Zero-touch resolution rate", "%"),
    "csat_avg": ("Average CSAT score", "score 1-5"),
    "experience_score_avg": ("Average device experience score", "score 0-100"),
    "time_lost_min_per_user": ("Time lost per seat", "minutes"),
}
# Tools an AI resolver calls, per ticket reason.
DIAGNOSTIC_TOOL = {
    "password_reset": "identity.reset_password", "account_unlock": "identity.unlock_account",
    "mfa_reenroll": "identity.unlock_account", "vpn_connect": "dem.get_device_health",
    "teams_call_quality": "dem.get_device_health", "outlook_sync": "dem.get_device_health",
    "software_install": "dem.get_device_health", "printer_issue": "dem.run_remediation",
}
REMEDIATED = {"vpn_connect", "teams_call_quality", "outlook_sync", "software_install"}


# ── World & time ─────────────────────────────────────────────────
def load_world(path: Path = WORLD_SPEC) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def parse_ts(value: str) -> datetime:
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=UTC)


def ts(value: datetime) -> str:
    return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Clock:
    """Every date the generator needs, derived from ``reference_date``."""

    def __init__(self, world: Dict[str, Any]):
        self.ref = date.fromisoformat(world["reference_date"])
        self.start = self.ref - timedelta(days=world["history_days"] - 1)
        self.ref_end = datetime.combine(self.ref, datetime.max.time()).replace(
            microsecond=0, tzinfo=UTC)
        self.trace_start = datetime.combine(
            self.ref - timedelta(days=world["trace_history_days"] - 1),
            datetime.min.time()).replace(tzinfo=UTC)
        self.dem_start = self.ref - timedelta(days=world["dem_history_days"] - 1)

    def days(self) -> List[date]:
        return [self.start + timedelta(days=i) for i in range((self.ref - self.start).days + 1)]

    def week_starts(self) -> List[date]:
        first = self.start - timedelta(days=self.start.weekday())
        return [first + timedelta(weeks=i) for i in range((self.ref - first).days // 7 + 1)]


def rng_for(world: Dict[str, Any], name: str) -> random.Random:
    """One independent stream per table, so editing one table never reshuffles another."""
    return random.Random(f"{world['seed']}:{name}")


def weighted(rng: random.Random, weights: Dict[Any, float]):
    keys = list(weights)
    return rng.choices(keys, weights=[weights[k] for k in keys], k=1)[0]


def clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def short_hash(*parts: Any, n: int = 16) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()[:n]


# ── Reference data ───────────────────────────────────────────────
def build_reference(world: Dict[str, Any]) -> Tables:
    """Dimensions: customers, sites, users, devices, applications, catalogues, contracts."""
    rng = rng_for(world, "reference")
    sc = world["scenario"]
    t: Tables = {name: [] for name in LAKEHOUSE if name.startswith(("dim_", "bridge_"))}

    for c in world["customers"]:
        seats = sum(s["users"] for s in c["sites"])
        t["dim_customer"].append({
            "customer_id": c["id"], "customer_name": c["name"], "industry": c["industry"],
            "country": c["country"], "primary_language": c["language"], "seats": seats,
            "monthly_fee_eur": float(c["monthly_fee_eur"])})
        for s in c["sites"]:
            t["dim_site"].append({
                "site_id": s["id"], "customer_id": c["id"],
                "site_name": f"{c['name']} {s['city']}", "city": s["city"],
                "country": s["country"], "site_type": s["type"], "user_count": s["users"]})

    personas = world["persona_mix"]
    for c in world["customers"]:
        lang = c["language"]
        n = 0
        for s in c["sites"]:
            forced_vips = sc["min_vip_impacted"] + 1 if s["id"] == sc["site_id"] else 0
            for i in range(s["users"]):
                n += 1
                persona = "VIP" if i < forced_vips else weighted(rng, personas)
                user_id = f"USR-{c['id'][4:]}-{n:04d}"
                name = f"{rng.choice(FIRST_NAMES[lang])} {rng.choice(LAST_NAMES[lang])}"
                t["dim_user"].append({
                    "user_id": user_id, "customer_id": c["id"], "site_id": s["id"],
                    "display_name": name, "persona": persona, "is_vip": persona == "VIP",
                    "language": lang,
                    "department": "Executive" if persona == "VIP" else rng.choice(DEPARTMENTS)})

    ring = rollout_ring(world, t["dim_user"])
    customers = {c["id"]: c for c in world["customers"]}
    for u in t["dim_user"]:
        device_id = "DEV-" + u["user_id"][4:]
        frontline = u["persona"] == "Frontline"
        version = sc["bad_version"] if u["user_id"] in ring else customers[u["customer_id"]]["vpn_version"]
        t["dim_device"].append({
            "device_id": device_id, "user_id": u["user_id"], "customer_id": u["customer_id"],
            "site_id": u["site_id"],
            "device_type": "Rugged laptop" if frontline else "Laptop",
            "os": "Windows 11" if rng.random() < 0.85 else "Windows 10",
            "model": rng.choice(["Rugged 14 G2", "Rugged 12"] if frontline
                                else ["Laptop 14 G3", "Laptop 13 Pro", "Laptop 15 G2"]),
            "age_months": rng.randint(1, 48), "vpn_client_version": version})

    apps = world["applications"]
    for a in apps:
        t["dim_application"].append({"app_id": a["id"], "app_name": a["name"],
                                     "category": a["category"], "is_critical": bool(a["critical"])})
    versions = {"APP-TEAMS": "25.2.1", "APP-OUTLOOK": "16.0.18", "APP-IDP": "web",
                "APP-ERP": "9.4", "APP-CRM": "web", "APP-HR": "web", "APP-OFFICE": "16.0.18",
                "APP-INTRANET": "web", "APP-PRINT": "3.2"}
    for d in t["dim_device"]:
        for a in apps:
            aid = a["id"]
            if aid in ("APP-ERP", "APP-CRM") and rng.random() < 0.5:
                continue
            if aid == "APP-PRINT" and d["device_type"] == "Rugged laptop":
                continue
            version = d["vpn_client_version"] if aid == "APP-VPN" else versions[aid]
            t["bridge_device_application"].append({
                "device_app_id": f"{d['device_id']}:{aid}", "device_id": d["device_id"],
                "app_id": aid, "app_version": version})

    for s in world["services"]:
        t["dim_service"].append({"service_id": s["id"], "service_name": s["name"],
                                 "service_type": s["type"], "owner_team": s["owner_team"]})
    for i, issue in enumerate(world["issues"], start=1):
        for lang in world["languages"]:
            t["dim_kb_article"].append({
                "kb_id": kb_id(issue["code"], lang, world), "service_id": issue["service"],
                "app_id": issue["app"], "issue_code": issue["code"],
                "title": f"{issue['title']} ({lang})", "language": lang,
                "zero_touch_eligible": bool(issue["zero_touch"])})

    for a in world["agents"]:
        t["dim_agent"].append({"agent_id": a["id"], "agent_name": a["name"],
                               "agent_type": a["type"], "role": a["role"],
                               "tier": a["tier"], "model": a["model"]})
    for tier, count in world["human_agents"].items():
        for i in range(1, count + 1):
            t["dim_agent"].append({"agent_id": f"AGT-{tier}-{i:02d}",
                                   "agent_name": f"Service Desk Analyst {tier}-{i:02d}",
                                   "agent_type": "Human", "role": "analyst",
                                   "tier": tier, "model": ""})
    for tool in world["mcp_tools"]:
        t["dim_mcp_tool"].append({"tool_id": tool["id"], "tool_name": tool["name"],
                                  "system": tool["system"], "description": tool["description"],
                                  "is_write": bool(tool["write"])})

    for ct in world["contracts"]:
        fee = float(customers[ct["customer_id"]]["monthly_fee_eur"])
        t["dim_contract"].append({
            "contract_id": ct["id"], "customer_id": ct["customer_id"],
            "contract_name": ct["name"], "start_date": date.fromisoformat(ct["start"]),
            "end_date": date.fromisoformat(ct["end"]), "monthly_fee_eur": fee,
            "penalty_cap_pct": float(ct["penalty_cap_pct"])})
        for i, x in enumerate(ct["xlas"], start=1):
            label, unit = METRIC_LABELS[x["metric"]]
            t["dim_xla"].append({
                "xla_id": f"XLA-{ct['customer_id'][4:]}-{i:02d}", "contract_id": ct["id"],
                "customer_id": ct["customer_id"], "metric": x["metric"], "metric_label": label,
                "comparator": x["comparator"], "threshold": float(x["threshold"]), "unit": unit,
                "measurement_window": x["window"], "penalty_pct": float(x["penalty_pct"]),
                "clause_text": x["clause"]})

    clock = Clock(world)
    for d in clock.days():
        iso = d.isocalendar()
        t["dim_date"].append({
            "date": d, "week_start": d - timedelta(days=d.weekday()), "iso_year": iso[0],
            "iso_week": iso[1], "month_start": d.replace(day=1),
            "month_name": d.strftime("%B"), "day_of_week": d.isoweekday(),
            "is_weekend": d.weekday() >= 5})
    return t


def kb_id(issue_code: str, lang: str, world: Dict[str, Any]) -> str:
    idx = [i["code"] for i in world["issues"]].index(issue_code) + 1
    return f"KB-{idx:02d}-{lang.upper()}"


def rollout_ring(world: Dict[str, Any], users: List[Row]) -> List[str]:
    """User IDs whose device received the bad VPN client: every VIP of the site, then a
    seeded sample up to ``rollout_share``. The rest of the site stays on the good version."""
    sc = world["scenario"]
    site_users = [u for u in users if u["site_id"] == sc["site_id"]]
    target = round(len(site_users) * sc["rollout_share"])
    vips = [u["user_id"] for u in site_users if u["is_vip"]]
    others = [u["user_id"] for u in site_users if not u["is_vip"]]
    ring = vips[:target] + rng_for(world, "ring").sample(others, target - min(target, len(vips)))
    return sorted(ring)


# ── Tickets ──────────────────────────────────────────────────────
def _random_time(rng: random.Random, day: date, not_before: Optional[datetime] = None) -> datetime:
    hour = weighted(rng, HOUR_WEIGHTS)
    dt = datetime(day.year, day.month, day.day, hour, rng.randint(0, 59), rng.randint(0, 59),
                  tzinfo=UTC)
    if not_before and dt < not_before:
        dt = not_before + timedelta(minutes=rng.randint(0, 90), seconds=rng.randint(0, 59))
    return dt


def _pick_day(rng: random.Random, days: List[date], weights: Optional[List[float]] = None) -> date:
    if weights is None:
        weights = [0.25 if d.weekday() >= 5 else 1.0 for d in days]
    return rng.choices(days, weights=weights, k=1)[0]


def _week_counts(world, clock, customer, week_start, days, rng) -> Tuple[int, int, Dict]:
    override = world["scenario"]["weekly_overrides"].get(customer["id"], {}).get(
        week_start.isoformat())
    if override:
        return override["tickets"], override["zero_touch"], override.get("issue_bias") or {}
    seats = sum(s["users"] for s in customer["sites"])
    n = max(1, round(seats * world["tickets_per_user_per_week"] * len(days) / 7
                     * rng.uniform(0.85, 1.15)))
    lo, hi = customer["zero_touch_band"]
    z = round(n * rng.uniform(lo, hi))
    floor = _weekly_zero_touch_floor(world, customer["id"])
    while floor and z / n < floor:
        z += 1
    return n, z, {}


def _weekly_zero_touch_floor(world, customer_id) -> float:
    """Outside overrides, keep every weekly zero-touch XLA 2 points clear of its threshold."""
    for ct in world["contracts"]:
        if ct["customer_id"] != customer_id:
            continue
        for x in ct["xlas"]:
            if x["metric"] == "zero_touch_rate" and x["window"] == "weekly":
                return x["threshold"] / 100 + 0.02
    return 0.0


def _resolution(rng, world, ticket, zero_touch, incident) -> Tuple[timedelta, str, float]:
    """(time to resolve, resolving agent, productive minutes lost)."""
    if zero_touch:
        return (timedelta(minutes=rng.uniform(10, 30) if incident else rng.uniform(3, 25)),
                "AGT-RESOLVER", round(rng.uniform(6, 20) if incident else rng.uniform(4, 20), 1))
    prio = ticket["priority"]
    issue_code = ticket["issue_code"]
    if incident:
        tier = "L2"
    elif prio in ("P1", "P2"):
        tier = "L2" if rng.random() < 0.7 else "L3"
    elif issue_code in ("erp_access", "crm_error", "hr_portal_access"):
        tier = "L2" if rng.random() < 0.5 else "L1"
    else:
        tier = "L1"
    count = world["human_agents"][tier]
    agent = f"AGT-{tier}-{rng.randint(1, count):02d}"
    hours = {"P1": (1, 4), "P2": (2, 12), "P3": (4, 36), "P4": (8, 72)}[prio]
    lost = {"P1": (120, 480), "P2": (60, 240), "P3": (30, 120), "P4": (15, 45)}[prio]
    if incident:
        hours, lost = (3, 12), (90, 480)
    return (timedelta(hours=rng.uniform(*hours)), agent, round(rng.uniform(*lost), 1))


def build_tickets(world: Dict[str, Any], ref: Tables) -> List[Row]:
    rng = rng_for(world, "tickets")
    clock = Clock(world)
    sc = world["scenario"]
    issues = {i["code"]: i for i in world["issues"]}
    zt_issues = {c: i["weight"] for c, i in issues.items() if i["zero_touch"]}
    all_issues = {c: i["weight"] for c, i in issues.items()}
    users_by_customer: Dict[str, List[Row]] = {}
    for u in ref["dim_user"]:
        users_by_customer.setdefault(u["customer_id"], []).append(u)
    device_of = {d["user_id"]: d for d in ref["dim_device"]}
    ring = set(rollout_ring(world, ref["dim_user"]))
    rollout_at = parse_ts(sc["rollout_at"])
    incident_week = rollout_at.date() - timedelta(days=rollout_at.weekday())
    lang_of = {c["id"]: c["language"] for c in world["customers"]}

    drafts: List[Row] = []
    for customer in world["customers"]:
        cid = customer["id"]
        for ws in clock.week_starts():
            days = [ws + timedelta(days=i) for i in range(7)
                    if clock.start <= ws + timedelta(days=i) <= clock.ref]
            n, z, bias = _week_counts(world, clock, customer, ws, days, rng)
            incident = cid == sc["customer_id"] and ws == incident_week
            n_inc = sc["incident_tickets"] if incident else 0
            z_inc = sc["incident_zero_touch"] if incident else 0
            flags = [True] * (z - z_inc) + [False] * ((n - n_inc) - (z - z_inc))
            rng.shuffle(flags)
            for zt in flags:
                user = rng.choice(users_by_customer[cid])
                if zt:
                    issue = weighted(rng, zt_issues)
                elif bias and rng.random() < sum(bias.values()):
                    issue = weighted(rng, bias)
                else:
                    issue = weighted(rng, all_issues)
                drafts.append(_draft(rng, user, device_of, issues[issue], zt,
                                     _random_time(rng, _pick_day(rng, days)), None, lang_of))
            if incident:
                drafts.extend(_incident_drafts(rng, world, ref, ring, device_of, issues,
                                               days, rollout_at, lang_of))

    drafts.sort(key=lambda r: (r["created_at"], r["user_id"], r["issue_code"]))
    tickets = []
    for i, d in enumerate(drafts, start=1):
        d["ticket_id"] = f"TKT-{i:06d}"
        incident = bool(d["major_incident_id"])
        if not d["zero_touch"] and incident and rng.random() < 0.45:
            delay, agent, lost = (clock.ref_end - d["created_at"] + timedelta(days=1), "",
                                  round(rng.uniform(120, 480), 1))
        else:
            delay, agent, lost = _resolution(rng, world, d, d["zero_touch"], incident)
        resolved_at = d["created_at"] + delay
        if resolved_at > clock.ref_end:
            d.update(status="open", resolved_at=None, resolved_by_agent_id="")
        else:
            d.update(status="resolved", resolved_at=resolved_at.replace(microsecond=0),
                     resolved_by_agent_id=agent)
        d["time_lost_min"] = lost
        tickets.append({col: d[col] for col in columns(LAKEHOUSE["fact_ticket"])})
    return tickets


def _draft(rng, user, device_of, issue, zero_touch, created_at, mi_id, lang_of,
           channels=None) -> Row:
    if zero_touch:
        channel = weighted(rng, {c: CHANNEL_WEIGHTS[c] for c in AI_CHANNELS})
    else:
        channel = weighted(rng, channels or CHANNEL_WEIGHTS)
    priority = "P2" if mi_id else weighted(rng, PRIORITY_WEIGHTS)
    if user["is_vip"]:
        priority = {"P4": "P3", "P3": "P2", "P2": "P1", "P1": "P1"}[priority]
    return {
        "customer_id": user["customer_id"], "site_id": user["site_id"],
        "user_id": user["user_id"], "device_id": device_of[user["user_id"]]["device_id"],
        "service_id": issue["service"], "app_id": issue["app"],
        "kb_id": f"KB-{issue['_idx']:02d}-{lang_of[user['customer_id']].upper()}",
        "major_incident_id": mi_id or "", "issue_code": issue["code"], "channel": channel,
        "priority": priority, "created_at": created_at, "created_date": created_at.date(),
        "zero_touch": zero_touch,
        "escalated_hitl": (not zero_touch) and channel in AI_CHANNELS,
    }


def _incident_drafts(rng, world, ref, ring, device_of, issues, days, rollout_at, lang_of):
    sc = world["scenario"]
    impacted = [u for u in ref["dim_user"] if u["user_id"] in ring]
    vips = [u for u in impacted if u["is_vip"]]
    first_ticket = rollout_at + timedelta(minutes=75)
    day_weights = [0.35, 0.25, 0.15, 0.10, 0.08, 0.03, 0.04]
    weights = [day_weights[d.weekday()] for d in days]
    flags = [True] * sc["incident_zero_touch"] + [False] * (sc["incident_tickets"]
                                                            - sc["incident_zero_touch"])
    rng.shuffle(flags)
    out = []
    for i, zt in enumerate(flags):
        user = vips[i] if i < len(vips) else rng.choice(impacted)
        issue = issues[weighted(rng, sc["incident_issues"])]
        created = _random_time(rng, _pick_day(rng, days, weights), not_before=first_ticket)
        out.append(_draft(rng, user, device_of, issue, zt, created,
                          sc["major_incident"]["id"], lang_of,
                          channels={"chat": 0.4, "teams": 0.35, "voice": 0.25}))
    return out


# ── Other facts ──────────────────────────────────────────────────
def build_csat(world, tickets: List[Row]) -> List[Row]:
    rng = rng_for(world, "csat")
    clock = Clock(world)
    good = {5: 0.62, 4: 0.28, 3: 0.07, 2: 0.02, 1: 0.01}
    human = {5: 0.50, 4: 0.32, 3: 0.10, 2: 0.05, 1: 0.03}
    incident = {5: 0.05, 4: 0.10, 3: 0.25, 2: 0.30, 1: 0.30}
    rows = []
    for t in tickets:
        if t["status"] != "resolved":
            continue
        is_inc = bool(t["major_incident_id"])
        if rng.random() > (0.6 if is_inc else 0.45):
            continue
        submitted = t["resolved_at"] + timedelta(minutes=rng.randint(5, 24 * 60))
        if submitted > clock.ref_end:
            continue
        dist = incident if is_inc else (good if t["zero_touch"] else human)
        rows.append({"csat_id": "CS-" + t["ticket_id"][4:], "ticket_id": t["ticket_id"],
                     "customer_id": t["customer_id"], "user_id": t["user_id"],
                     "channel": t["channel"], "score": weighted(rng, dist),
                     "submitted_at": submitted, "submitted_date": submitted.date()})
    rows.sort(key=lambda r: (r["submitted_at"], r["csat_id"]))
    return rows


def _device_quality(world, devices: List[Row]) -> Dict[str, float]:
    rng = rng_for(world, "device-quality")
    return {d["device_id"]: rng.gauss(83, 3.5) - d["age_months"] * 0.06 for d in devices}


def is_degraded(world, device: Row, at: datetime) -> bool:
    sc = world["scenario"]
    return (device["vpn_client_version"] == sc["bad_version"]
            and at > parse_ts(sc["rollout_at"]))


def build_experience_daily(world, ref: Tables) -> List[Row]:
    rng = rng_for(world, "experience-daily")
    clock = Clock(world)
    quality = _device_quality(world, ref["dim_device"])
    rollout_day = parse_ts(world["scenario"]["rollout_at"]).date()
    rows = []
    for day in clock.days():
        for d in ref["dim_device"]:
            degraded = (d["vpn_client_version"] == world["scenario"]["bad_version"]
                        and day >= rollout_day)
            if degraded:
                score, crashes = rng.gauss(42, 5), rng.randint(2, 6)
                latency, mos = rng.gauss(420, 80), rng.gauss(2.4, 0.3)
            else:
                score = quality[d["device_id"]] + rng.gauss(0, 3)
                r = rng.random()
                crashes = 2 if r < 0.01 else (1 if r < 0.08 else 0)
                latency, mos = rng.gauss(45, 8), rng.gauss(4.2, 0.15)
            rows.append({"date": day, "device_id": d["device_id"], "user_id": d["user_id"],
                         "customer_id": d["customer_id"], "site_id": d["site_id"],
                         "experience_score": round(clamp(score, 0, 100), 1),
                         "crash_count": crashes,
                         "avg_vpn_latency_ms": round(clamp(latency, 5, 2000), 1),
                         "avg_teams_mos": round(clamp(mos, 1, 5), 2)})
    return rows


def build_major_incidents(world, ref: Tables) -> List[Row]:
    sc = world["scenario"]
    mi = sc["major_incident"]
    ring = set(rollout_ring(world, ref["dim_user"]))
    impacted = [u for u in ref["dim_user"] if u["user_id"] in ring]
    service = next(i["service"] for i in world["issues"] if i["app"] == sc["app_id"])
    return [{
        "major_incident_id": mi["id"], "customer_id": sc["customer_id"],
        "site_id": sc["site_id"], "app_id": sc["app_id"], "service_id": service,
        "title": mi["title"], "root_cause": mi["root_cause"], "severity": mi["severity"],
        "status": "open", "started_at": parse_ts(sc["rollout_at"]),
        "declared_at": parse_ts(mi["declared_at"]), "resolved_at": None,
        "impacted_users": len(impacted),
        "impacted_vip_users": sum(1 for u in impacted if u["is_vip"])}]


# ── Eventhouse history ───────────────────────────────────────────
def dem_sample(rng: random.Random, world, device: Row, quality: float, at: datetime,
               intensity: float = 1.0) -> Row:
    """One DEM telemetry row. Shared with the live injector, so history and live agree."""
    degraded = is_degraded(world, device, at) and rng.random() < intensity
    if degraded:
        connected = rng.random() > 0.35
        crashes = rng.randint(1, 4)
        row = {"experience_score": rng.gauss(40, 7), "vpn_connected": connected,
               "vpn_latency_ms": rng.gauss(450, 120) if connected else None,
               "teams_latency_ms": rng.gauss(380, 90), "teams_mos": rng.gauss(2.3, 0.35),
               "app_crash_count": crashes,
               "crash_app_id": "APP-VPN" if rng.random() < 0.7 else "APP-TEAMS",
               "cpu_pct": rng.gauss(55, 15), "memory_pct": rng.gauss(68, 10)}
    else:
        crash = rng.random() < 0.02
        row = {"experience_score": quality + rng.gauss(0, 4),
               "vpn_connected": rng.random() > 0.01,
               "vpn_latency_ms": rng.gauss(45, 10), "teams_latency_ms": rng.gauss(85, 15),
               "teams_mos": rng.gauss(4.25, 0.15), "app_crash_count": 1 if crash else 0,
               "crash_app_id": rng.choice(["APP-OUTLOOK", "APP-OFFICE", "APP-TEAMS"]) if crash else "",
               "cpu_pct": rng.gauss(25, 10), "memory_pct": rng.gauss(55, 10)}
        if not row["vpn_connected"]:
            row["vpn_latency_ms"] = None
    out = {"timestamp": at, "customer_id": device["customer_id"], "site_id": device["site_id"],
           "device_id": device["device_id"], "user_id": device["user_id"],
           "vpn_client_version": device["vpn_client_version"]}
    out["experience_score"] = round(clamp(row["experience_score"], 0, 100), 1)
    out["vpn_connected"] = row["vpn_connected"]
    out["vpn_latency_ms"] = (None if row["vpn_latency_ms"] is None
                             else round(clamp(row["vpn_latency_ms"], 5, 3000), 1))
    out["teams_latency_ms"] = round(clamp(row["teams_latency_ms"], 10, 3000), 1)
    out["teams_mos"] = round(clamp(row["teams_mos"], 1, 5), 2)
    out["app_crash_count"] = row["app_crash_count"]
    out["crash_app_id"] = row["crash_app_id"]
    out["cpu_pct"] = round(clamp(row["cpu_pct"], 1, 100), 1)
    out["memory_pct"] = round(clamp(row["memory_pct"], 5, 100), 1)
    return out


def build_dem_telemetry(world, ref: Tables) -> List[Row]:
    rng = rng_for(world, "dem-telemetry")
    clock = Clock(world)
    quality = _device_quality(world, ref["dim_device"])
    weekend_active = {d["device_id"] for d in ref["dim_device"]
                      if rng_for(world, "weekend:" + d["device_id"]).random() < 0.2}
    rows = []
    day = clock.dem_start
    while day <= clock.ref:
        for hour in range(7, 20):
            at = datetime(day.year, day.month, day.day, hour, tzinfo=UTC)
            for d in ref["dim_device"]:
                if day.weekday() >= 5 and d["device_id"] not in weekend_active:
                    continue
                rows.append(dem_sample(rng, world, d, quality[d["device_id"]], at))
        day += timedelta(days=1)
    return rows


def _span(trace_id, idx, parent, at, operation, row_base, **kw) -> Row:
    row = {"timestamp": at, "trace_id": trace_id, "span_id": short_hash(trace_id, idx),
           "parent_span_id": parent, "operation": operation, "tool_name": "", "model": "",
           "input_tokens": 0, "output_tokens": 0, "latency_ms": 0.0, "cost_eur": 0.0,
           "status": "ok", "error_type": "", "eval_groundedness": None,
           "eval_relevance": None, "content_safety_flag": False, "hitl_escalation": False}
    row.update(row_base)
    row.update(kw)
    return row


def contact_events(world, ticket: Row, rng: random.Random, human_agent: str = "") -> Dict[str, List[Row]]:
    """Conversation turns, agent spans and gateway calls for one AI-handled contact.

    Shared by the history builder and the live injector.
    """
    sc = world["scenario"]
    models = world["models"]
    incident = bool(ticket["major_incident_id"])
    escalated = ticket["escalated_hitl"]
    channel = ticket["channel"]
    start = ticket["created_at"] - timedelta(seconds=rng.randint(60, 240))
    lang = next(c["language"] for c in world["customers"] if c["id"] == ticket["customer_id"])
    out: Dict[str, List[Row]] = {"conversations": [], "agent_traces": [], "gateway_logs": []}
    conv_id = "CNV-" + ticket["ticket_id"][4:] if channel in CONVERSATION_CHANNELS else ""

    if conv_id:
        n_turns = rng.randint(6, 10) if escalated else rng.randint(4, 8)
        base = -0.55 if incident else (-0.15 if escalated else 0.3)
        at = start
        ai_agent = "AGT-VOICE" if channel == "voice" else "AGT-CHAT"
        for i in range(n_turns):
            at += timedelta(seconds=rng.randint(10, 40) if channel == "voice" else rng.randint(15, 60))
            speaker = "user" if i % 2 == 0 else ("human_agent" if escalated and i >= n_turns - 2
                                                  else "ai_agent")
            agent = "" if speaker == "user" else (human_agent or "AGT-L1-01"
                                                  if speaker == "human_agent" else ai_agent)
            drift = -0.1 * i / n_turns if escalated else 0.15 * i / n_turns
            out["conversations"].append({
                "timestamp": at, "conversation_id": conv_id, "turn_index": i,
                "ticket_id": ticket["ticket_id"], "customer_id": ticket["customer_id"],
                "user_id": ticket["user_id"], "channel": channel, "language": lang,
                "speaker": speaker, "agent_id": agent, "intent": ticket["issue_code"],
                "sentiment": round(clamp(base + drift + rng.gauss(0, 0.18), -1, 1), 2),
                "resolved_by_ai": ticket["zero_touch"], "escalated": escalated})

    trace_id = short_hash("trace", ticket["ticket_id"], n=32)
    base = {"customer_id": ticket["customer_id"], "conversation_id": conv_id}
    root = short_hash(trace_id, 0)
    spans: List[Row] = []
    cursor = start + timedelta(seconds=2)
    incident_window = (ticket["customer_id"] == sc["customer_id"]
                       and ticket["created_at"] >= parse_ts(sc["rollout_at"]))

    def chat(agent, model, lo_in, hi_in, lo_out, hi_out, final=False):
        nonlocal cursor
        tin, tout = rng.randint(lo_in, hi_in), rng.randint(lo_out, hi_out)
        lat = rng.uniform(300, 900) if model == "llm-small" else rng.uniform(1200, 4000)
        price = models[model]
        cost = tin / 1000 * price["input_per_1k"] + tout / 1000 * price["output_per_1k"]
        kw = {}
        if final:
            poor = incident and escalated
            kw = {"eval_groundedness": round(clamp(rng.gauss(3.2 if poor else 4.3, 0.45), 1, 5), 2),
                  "eval_relevance": round(clamp(rng.gauss(3.4 if poor else 4.4, 0.4), 1, 5), 2)}
        p429 = 0.10 if incident_window else 0.01
        attempt = 0
        while rng.random() < p429 and attempt < 2:
            out["gateway_logs"].append({
                "timestamp": cursor, "request_id": short_hash("req", trace_id, len(spans), attempt),
                "trace_id": trace_id, "customer_id": ticket["customer_id"], "agent_id": agent,
                "model": model, "prompt_tokens": 0, "completion_tokens": 0, "status_code": 429,
                "latency_ms": round(rng.uniform(30, 80), 1), "retry_attempt": attempt})
            attempt += 1
            cursor += timedelta(seconds=rng.randint(1, 3))
        out["gateway_logs"].append({
            "timestamp": cursor, "request_id": short_hash("req", trace_id, len(spans), attempt),
            "trace_id": trace_id, "customer_id": ticket["customer_id"], "agent_id": agent,
            "model": model, "prompt_tokens": tin, "completion_tokens": tout, "status_code": 200,
            "latency_ms": round(lat, 1), "retry_attempt": attempt})
        spans.append(_span(trace_id, len(spans) + 1, root, cursor, "chat", base,
                           agent_id=agent, model=model, input_tokens=tin, output_tokens=tout,
                           latency_ms=round(lat, 1), cost_eur=round(cost, 6),
                           content_safety_flag=rng.random() < 0.003, **kw))
        cursor += timedelta(milliseconds=int(lat))

    def tool(agent, name, fail_rate=0.0):
        nonlocal cursor
        failed = rng.random() < fail_rate
        if failed:
            error = "timeout" if rng.random() < 0.6 else "upstream_503"
            lat = 30000.0 if error == "timeout" else rng.uniform(150, 400)
        else:
            error, lat = "", rng.uniform(150, 800)
        spans.append(_span(trace_id, len(spans) + 1, root, cursor, "execute_tool", base,
                           agent_id=agent, tool_name=name, latency_ms=round(lat, 1),
                           status="error" if failed else "ok", error_type=error))
        cursor += timedelta(milliseconds=int(lat))
        return not failed

    issue = ticket["issue_code"]
    chat("AGT-TRIAGE", "llm-small", 300, 900, 50, 200)
    tool("AGT-TRIAGE", "itsm.create_ticket")
    tool("AGT-KNOWLEDGE", "kb.search")
    chat("AGT-KNOWLEDGE", "llm-large", 1500, 4000, 200, 600)
    diag = DIAGNOSTIC_TOOL.get(issue)
    if diag:
        if incident and escalated:
            fail = sc["tool_failure_rate"]
        elif incident:
            fail = 0.3
        else:
            fail = 0.06 if escalated else 0.0
        if not tool("AGT-RESOLVER", diag, fail) and diag == "dem.get_device_health":
            tool("AGT-RESOLVER", diag, fail)
    if ticket["zero_touch"] and issue in REMEDIATED:
        tool("AGT-RESOLVER", "dem.run_remediation")
    answer_agent = "AGT-VOICE" if channel == "voice" else "AGT-CHAT"
    chat(answer_agent, "llm-large", 1500, 4000, 200, 600, final=True)
    tool(answer_agent, "itsm.update_ticket")
    total = (cursor - start).total_seconds() * 1000
    out["agent_traces"] = [_span(trace_id, 0, "", start, "invoke_agent", base,
                                 agent_id="AGT-SUPERVISOR", latency_ms=round(total, 1),
                                 hitl_escalation=escalated)] + spans
    return out


def build_eventhouse(world, tickets: List[Row], csat: List[Row], ref: Tables) -> Tables:
    rng = rng_for(world, "eventhouse")
    clock = Clock(world)
    t: Tables = {name: [] for name in EVENTHOUSE}
    t["dem_telemetry"] = build_dem_telemetry(world, ref)
    recent = [x for x in tickets if x["created_at"] >= clock.trace_start]
    for x in recent:
        t["tickets_events"].extend(ticket_events(x, rng))
        if x["channel"] in AI_CHANNELS:
            human = x["resolved_by_agent_id"] if x["resolved_by_agent_id"].startswith("AGT-L") else "AGT-L2-01"
            for name, rows in contact_events(world, x, rng, human).items():
                t[name].extend(rows)
    t["csat_events"] = [{"timestamp": c["submitted_at"], "csat_id": c["csat_id"],
                         "ticket_id": c["ticket_id"], "customer_id": c["customer_id"],
                         "user_id": c["user_id"], "channel": c["channel"], "score": c["score"]}
                        for c in csat if c["submitted_at"] >= clock.trace_start]
    for name in ("tickets_events", "conversations", "agent_traces", "gateway_logs"):
        t[name].sort(key=lambda r: (r["timestamp"], r.get("event_id") or r.get("span_id")
                                    or r.get("request_id") or r.get("conversation_id"),
                                    r.get("turn_index", 0)))
    return t


def ticket_events(ticket: Row, rng: random.Random) -> List[Row]:
    base = {k: ticket[k] for k in ("ticket_id", "customer_id", "site_id", "user_id",
                                   "device_id", "service_id", "app_id", "issue_code",
                                   "channel", "priority", "zero_touch", "escalated_hitl",
                                   "major_incident_id")}

    def ev(kind, at, status):
        return dict(base, timestamp=at, event_id=f"EV-{ticket['ticket_id'][4:]}-{kind[:3]}",
                    event_type=kind, status=status)

    events = [ev("created", ticket["created_at"], "new")]
    if ticket["escalated_hitl"]:
        events.append(ev("updated", ticket["created_at"] + timedelta(minutes=rng.randint(4, 15)),
                         "escalated"))
    if ticket["resolved_at"]:
        events.append(ev("resolved", ticket["resolved_at"], "resolved"))
    return events


# ── Orchestration ────────────────────────────────────────────────
def generate(world: Optional[Dict[str, Any]] = None) -> Tables:
    """Build every table in memory. Deterministic for a given world."""
    world = world or load_world()
    for i, issue in enumerate(world["issues"], start=1):
        issue["_idx"] = i
    ref = build_reference(world)
    tickets = build_tickets(world, ref)
    csat = build_csat(world, tickets)
    tables: Tables = dict(ref)
    tables["fact_ticket"] = tickets
    tables["fact_csat"] = csat
    tables["fact_experience_daily"] = build_experience_daily(world, ref)
    tables["fact_major_incident"] = build_major_incidents(world, ref)
    tables.update(build_eventhouse(world, tickets, csat, ref))
    return tables


def fmt(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return ts(value)
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def to_csv(table: str, rows: List[Row]) -> str:
    schema = LAKEHOUSE.get(table) or EVENTHOUSE[table]
    cols = columns(schema)
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\n")
    writer.writerow(cols)
    for r in rows:
        writer.writerow([fmt(r[c]) for c in cols])
    return buf.getvalue()


def write_tables(tables: Tables, out_dir: Path, world: Dict[str, Any]) -> Dict[str, Any]:
    manifest = {"seed": world["seed"], "reference_date": world["reference_date"], "tables": {}}
    for table, rows in tables.items():
        store = "lakehouse" if table in LAKEHOUSE else "eventhouse"
        target = out_dir / store / f"{table}.csv"
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = to_csv(table, rows).encode("utf-8")
        target.write_bytes(payload)
        manifest["tables"][table] = {"store": store, "rows": len(rows),
                                     "sha256": hashlib.sha256(payload).hexdigest()}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                           encoding="utf-8")
    return manifest


# ── XLA evaluation (the numbers the demo quotes) ─────────────────
def weekly_zero_touch(tables: Tables) -> Dict[Tuple[str, date], Tuple[int, int]]:
    out: Dict[Tuple[str, date], List[int]] = {}
    for t in tables["fact_ticket"]:
        d = t["created_date"]
        key = (t["customer_id"], d - timedelta(days=d.weekday()))
        cell = out.setdefault(key, [0, 0])
        cell[0] += 1
        cell[1] += int(t["zero_touch"])
    return {k: (v[0], v[1]) for k, v in out.items()}


def _metric(tables: Tables, customer_id: str, metric: str, lo: date, hi: date,
            seats: int) -> Optional[float]:
    if metric == "zero_touch_rate":
        rows = [t for t in tables["fact_ticket"]
                if t["customer_id"] == customer_id and lo <= t["created_date"] <= hi]
        return round(100 * sum(t["zero_touch"] for t in rows) / len(rows), 2) if rows else None
    if metric == "csat_avg":
        rows = [c["score"] for c in tables["fact_csat"]
                if c["customer_id"] == customer_id and lo <= c["submitted_date"] <= hi]
        return round(sum(rows) / len(rows), 2) if rows else None
    if metric == "experience_score_avg":
        rows = [e["experience_score"] for e in tables["fact_experience_daily"]
                if e["customer_id"] == customer_id and lo <= e["date"] <= hi]
        return round(sum(rows) / len(rows), 2) if rows else None
    if metric == "time_lost_min_per_user":
        total = sum(t["time_lost_min"] for t in tables["fact_ticket"]
                    if t["customer_id"] == customer_id and lo <= t["created_date"] <= hi)
        return round(total / seats, 2)
    raise ValueError(metric)


def evaluate_xla(tables: Tables, world: Optional[Dict[str, Any]] = None) -> List[Row]:
    """Evaluate every XLA over every CLOSED window of the history.

    Weekly = ISO week (Monday–Sunday) fully inside the history. Monthly = calendar month
    fully inside the history (the current month is not evaluated until it closes).
    A breach credits ``penalty_pct`` of the monthly fee, capped per month at the
    contract's ``penalty_cap_pct``.
    """
    world = world or load_world()
    clock = Clock(world)
    seats = {c["customer_id"]: c["seats"] for c in tables["dim_customer"]}
    fees = {c["contract_id"]: (c["monthly_fee_eur"], c["penalty_cap_pct"])
            for c in tables["dim_contract"]}
    weeks = [w for w in clock.week_starts() if w >= clock.start and w + timedelta(days=6) <= clock.ref]
    months = []
    m = clock.start.replace(day=1)
    while m <= clock.ref:
        nxt = (m.replace(day=28) + timedelta(days=4)).replace(day=1)
        if m >= clock.start and nxt - timedelta(days=1) <= clock.ref:
            months.append((m, nxt - timedelta(days=1)))
        m = nxt
    rows = []
    for x in tables["dim_xla"]:
        windows = ([(w, w + timedelta(days=6)) for w in weeks]
                   if x["measurement_window"] == "weekly" else months)
        fee, _cap = fees[x["contract_id"]]
        for lo, hi in windows:
            value = _metric(tables, x["customer_id"], x["metric"], lo, hi, seats[x["customer_id"]])
            ok = value is None or (value >= x["threshold"] if x["comparator"] == ">="
                                   else value <= x["threshold"])
            rows.append({"xla_id": x["xla_id"], "customer_id": x["customer_id"],
                         "metric": x["metric"], "window": x["measurement_window"],
                         "window_start": lo, "window_end": hi, "value": value,
                         "threshold": x["threshold"], "breached": not ok,
                         "penalty_eur": 0.0 if ok else round(fee * x["penalty_pct"] / 100, 2)})
    # monthly cap, applied to the month that contains each window's end
    by_month: Dict[Tuple[str, date], float] = {}
    caps = {x["xla_id"]: fees[x["contract_id"]] for x in tables["dim_xla"]}
    for r in rows:
        fee, cap_pct = caps[r["xla_id"]]
        key = (r["customer_id"], r["window_end"].replace(day=1))
        room = fee * cap_pct / 100 - by_month.get(key, 0.0)
        r["penalty_eur"] = round(max(0.0, min(r["penalty_eur"], room)), 2)
        by_month[key] = by_month.get(key, 0.0) + r["penalty_eur"]
    return rows


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Generate the Zava Service Desk synthetic dataset.")
    ap.add_argument("--out", type=Path, default=ARTIFACTS / "data",
                    help="Output directory (default: artifacts/data).")
    args = ap.parse_args(argv)
    world = load_world()
    tables = generate(world)
    manifest = write_tables(tables, args.out, world)
    print(f"✓ {len(tables)} tables written to {args.out}")
    for name, info in manifest["tables"].items():
        print(f"  {info['store']:<10} {name:<28} {info['rows']:>8,} rows")
    sc = world["scenario"]
    rollout = parse_ts(sc["rollout_at"]).date()
    week = rollout - timedelta(days=rollout.weekday())
    zt = weekly_zero_touch(tables)
    print("\nZero-touch, scenario customer:")
    for w in (week - timedelta(weeks=1), week):
        n, z = zt[(sc["customer_id"], w)]
        print(f"  week of {w}: {z}/{n} = {100 * z / n:.1f}%")
    breaches = [r for r in evaluate_xla(tables, world) if r["breached"]]
    print("\nXLA breaches (closed windows):")
    for r in breaches:
        print(f"  {r['customer_id']} {r['xla_id']} {r['metric']} {r['window_start']}: "
              f"{r['value']} vs {r['threshold']} → credit {r['penalty_eur']:,.2f} EUR")
    return 0


if __name__ == "__main__":
    sys.exit(main())
