#!/usr/bin/env python3
"""Inject live Service Desk events into the Eventhouse — normal traffic or the incident.

Each tick emits the six real-time streams for "now":

* ``dem_telemetry``  — one sample per active device (the Lyon 6.1.0 ring degrades);
* ``tickets_events`` — new / escalated / resolved tickets;
* ``conversations``  — chat / Teams / voice turns of the AI-handled contacts;
* ``agent_traces``   — OpenTelemetry-style spans of the multi-agent platform;
* ``gateway_logs``   — AI Gateway calls (tokens, 429s);
* ``csat_events``    — survey answers.

The row builders are the generator's own (``fabric.data.generate_data``), so live rows
share the history's shape, IDs and behaviour. The scenario intensity ramps up over
``--ramp`` ticks: Activator rules see the degradation build up, as in a real incident.

  python -m fabric.eventhouse.inject_event --dry-run                      # one tick to stdout
  python -m fabric.eventhouse.inject_event --scenario vpn-lyon --out artifacts/live --cycles 5 --loop --interval 0
  python -m fabric.eventhouse.inject_event --scenario vpn-lyon --loop     # live, into EH_ServiceDesk (phase 2)

Without ``--dry-run`` / ``--out`` rows go to the KQL database via ``.ingest inline``
(batches kept under 60 KB), which needs a deployed tenant (``kusto_query_uri`` in state).
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import json
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from fabric.data import generate_data as gd
from fabric.data.schema import EVENTHOUSE, columns

UTC = timezone.utc
MAX_BATCH_BYTES = 60_000
SCENARIOS = ("none", "vpn-lyon")
Rows = Dict[str, List[Dict[str, Any]]]


class World:
    """Reference data + world spec, loaded once and reused by every tick."""

    def __init__(self, scenario: str, customer: Optional[str], seed: int):
        self.spec = gd.load_world()
        for i, issue in enumerate(self.spec["issues"], start=1):
            issue["_idx"] = i
        self.scenario = scenario
        self.ref = gd.build_reference(self.spec)
        self.devices = [d for d in self.ref["dim_device"]
                        if customer is None or d["customer_id"] == customer]
        if not self.devices:
            raise SystemExit(f"Unknown customer '{customer}'.")
        self.users = {u["user_id"]: u for u in self.ref["dim_user"]}
        self.device_of = {d["user_id"]: d for d in self.ref["dim_device"]}
        self.quality = gd._device_quality(self.spec, self.ref["dim_device"])
        self.issues = {i["code"]: i for i in self.spec["issues"]}
        self.lang_of = {c["id"]: c["language"] for c in self.spec["customers"]}
        self.rng = random.Random(seed)
        self.counter = 0
        if scenario == "vpn-lyon":
            # Live: the bad version is in place "now", whatever the history date says.
            self.spec["scenario"]["rollout_at"] = "2000-01-01T00:00:00Z"
        else:
            self.spec["scenario"]["bad_version"] = "__none__"
            self.spec["scenario"]["rollout_at"] = "2999-01-01T00:00:00Z"

    def impacted(self, device: Dict[str, Any]) -> bool:
        return device["vpn_client_version"] == self.spec["scenario"]["bad_version"]


def build_tick(world: World, now: datetime, intensity: float) -> Rows:
    """All rows of one tick. Pure function of (world state, now, intensity)."""
    rng = world.rng
    now = now.replace(microsecond=0)
    out: Rows = {name: [] for name in EVENTHOUSE}
    sc = world.spec["scenario"]

    for d in world.devices:
        out["dem_telemetry"].append(
            gd.dem_sample(rng, world.spec, d, world.quality[d["device_id"]], now, intensity))

    # Background load: ~1 new contact per tick per 150 active devices.
    n_contacts = max(1, round(len(world.devices) / 150 * rng.uniform(0.5, 1.5)))
    contacts: List[Tuple[Dict[str, Any], bool]] = []
    for _ in range(n_contacts):
        d = rng.choice(world.devices)
        contacts.append((d, False))
    impacted = [d for d in world.devices if world.impacted(d)]
    if impacted:
        for _ in range(round(len(impacted) * 0.15 * intensity)):
            contacts.append((rng.choice(impacted), True))

    zt_issues = {c: i["weight"] for c, i in world.issues.items() if i["zero_touch"]}
    all_issues = {c: i["weight"] for c, i in world.issues.items()}
    for device, incident in contacts:
        world.counter += 1
        user = world.users[device["user_id"]]
        if incident:
            issue = world.issues[gd.weighted(rng, sc["incident_issues"])]
            zero_touch = rng.random() < 0.28
            mi = sc["major_incident"]["id"]
            channels = {"chat": 0.4, "teams": 0.35, "voice": 0.25}
        else:
            zero_touch = rng.random() < 0.45
            issue = world.issues[gd.weighted(rng, zt_issues if zero_touch else all_issues)]
            mi, channels = None, None
        created = now - timedelta(seconds=rng.randint(0, 50))
        ticket = gd._draft(rng, user, world.device_of, issue, zero_touch, created, mi,
                           world.lang_of, channels)
        ticket["ticket_id"] = f"TKL-{now.strftime('%H%M%S')}-{world.counter:05d}"
        if zero_touch:
            ticket["resolved_at"] = now
            ticket["resolved_by_agent_id"] = "AGT-RESOLVER"
        else:
            ticket["resolved_at"] = None
            ticket["resolved_by_agent_id"] = ""
        out["tickets_events"].extend(gd.ticket_events(ticket, rng))
        if ticket["channel"] in gd.AI_CHANNELS:
            human = f"AGT-L{2 if incident else 1}-0{rng.randint(1, 4)}"
            for name, rows in gd.contact_events(world.spec, ticket, rng, human).items():
                out[name].extend(rows)
        if zero_touch and rng.random() < 0.45:
            dist = ({5: 0.62, 4: 0.28, 3: 0.07, 2: 0.02, 1: 0.01} if not incident
                    else {5: 0.2, 4: 0.3, 3: 0.3, 2: 0.1, 1: 0.1})
            out["csat_events"].append({
                "timestamp": now, "csat_id": "CS-" + ticket["ticket_id"][4:],
                "ticket_id": ticket["ticket_id"], "customer_id": ticket["customer_id"],
                "user_id": ticket["user_id"], "channel": ticket["channel"],
                "score": gd.weighted(rng, dist)})
    # Live timestamps: everything happens within this tick, never in the future.
    for rows in out.values():
        for r in rows:
            if r["timestamp"] > now:
                r["timestamp"] = now
    return out


def csv_lines(table: str, rows: Iterable[Dict[str, Any]]) -> List[str]:
    """Header-less CSV lines in the table's column order (the ``.ingest inline`` format)."""
    text = gd.to_csv(table, list(rows))
    return text.splitlines()[1:]


def batches(table: str, rows: List[Dict[str, Any]],
            max_bytes: int = MAX_BATCH_BYTES) -> List[str]:
    """Split rows into ``.ingest inline`` commands that each stay under ``max_bytes``."""
    head = f".ingest inline into table {table} <|\n"
    out, cur, size = [], [], len(head)
    for line in csv_lines(table, rows):
        n = len(line.encode("utf-8")) + 1
        if cur and size + n > max_bytes:
            out.append(head + "\n".join(cur))
            cur, size = [], len(head)
        cur.append(line)
        size += n
    if cur:
        out.append(head + "\n".join(cur))
    return out


def to_json(value: Any) -> Any:
    return gd.ts(value) if isinstance(value, datetime) else value


class Sink:
    def emit(self, rows: Rows) -> None:  # pragma: no cover - interface
        raise NotImplementedError


class StdoutSink(Sink):
    def emit(self, rows: Rows) -> None:
        for table in EVENTHOUSE:
            for r in rows[table]:
                print(json.dumps({"table": table, **{c: to_json(r[c]) for c in
                                                     columns(EVENTHOUSE[table])}},
                                 ensure_ascii=False))


class FileSink(Sink):
    """One JSONL file per table, appended tick after tick."""

    def __init__(self, out_dir: Path):
        self.out_dir = out_dir
        out_dir.mkdir(parents=True, exist_ok=True)

    def emit(self, rows: Rows) -> None:
        for table in EVENTHOUSE:
            if not rows[table]:
                continue
            with open(self.out_dir / f"{table}.jsonl", "a", encoding="utf-8") as f:
                for r in rows[table]:
                    f.write(json.dumps({c: to_json(r[c]) for c in columns(EVENTHOUSE[table])},
                                       ensure_ascii=False) + "\n")


class KustoSink(Sink):
    def __init__(self):
        from fabric._shared.helpers import (get_kusto_token, load_config, load_state,
                                            require_config, require_state)
        cfg, state = load_config(), load_state()
        self.quri = require_state(state, "kusto_query_uri")
        self.db = require_config(cfg, "eventhouse")["kql_database"]
        self.token = get_kusto_token(self.quri)

    def emit(self, rows: Rows) -> None:
        from fabric._shared.helpers import kusto_mgmt
        for table in EVENTHOUSE:
            for command in batches(table, rows[table]):
                kusto_mgmt(self.quri, self.token, self.db, command)


def summary(rows: Rows, world: World) -> str:
    dem = rows["dem_telemetry"]
    ring = [r for r in dem if r["vpn_client_version"] == world.spec["scenario"]["bad_version"]]
    ring_score = (sum(r["experience_score"] for r in ring) / len(ring)) if ring else None
    failed = sum(1 for r in rows["agent_traces"] if r["status"] == "error")
    parts = [f"{len(dem)} DEM", f"{len(rows['tickets_events'])} ticket ev",
             f"{len(rows['agent_traces'])} spans ({failed} failed)",
             f"{sum(1 for g in rows['gateway_logs'] if g['status_code'] == 429)}×429"]
    if ring_score is not None:
        parts.append(f"Lyon 6.1.0 experience {ring_score:.0f}")
    return " · ".join(parts)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Inject live Service Desk events.")
    ap.add_argument("--scenario", choices=SCENARIOS, default="none",
                    help="none = normal traffic; vpn-lyon = the Fabrikam Lyon VPN incident.")
    ap.add_argument("--customer", help="Restrict DEM + contacts to one customer (e.g. CUS-FAB).")
    ap.add_argument("--loop", action="store_true", help="Keep injecting every --interval seconds.")
    ap.add_argument("--interval", type=float, default=30.0, help="Seconds between ticks.")
    ap.add_argument("--cycles", type=int, default=0, help="Ticks in loop mode (0 = infinite).")
    ap.add_argument("--ramp", type=int, default=6, help="Ticks to reach full incident intensity.")
    ap.add_argument("--seed", type=int, default=None, help="Seed for reproducible live runs.")
    ap.add_argument("--now", help="Override 'now' (YYYY-MM-DDTHH:MM:SSZ), for tests / replays.")
    ap.add_argument("--dry-run", action="store_true", help="Print JSON lines, ingest nothing.")
    ap.add_argument("--out", type=Path, help="Append JSONL files to this directory instead of ingesting.")
    args = ap.parse_args(argv)

    world = World(args.scenario, args.customer, args.seed if args.seed is not None
                  else random.SystemRandom().randint(0, 2**31))
    if args.dry_run:
        sink: Sink = StdoutSink()
    elif args.out:
        sink = FileSink(args.out)
    else:
        sink = KustoSink()
    quiet = args.dry_run
    log = (lambda msg: print(msg, file=sys.stderr)) if quiet else print

    fixed_now = gd.parse_ts(args.now) if args.now else None
    step = timedelta(seconds=args.interval)
    tick = 0
    total = args.cycles if args.loop else 1
    log(f"Injector · scenario={args.scenario} · {len(world.devices)} devices · "
        f"{'infinite' if args.loop and not total else total} tick(s)")
    try:
        while True:
            tick += 1
            now = (fixed_now + step * (tick - 1)) if fixed_now else datetime.now(UTC)
            intensity = min(1.0, tick / max(1, args.ramp)) if args.loop else 1.0
            rows = build_tick(world, now, intensity)
            sink.emit(rows)
            bar = "█" * int(intensity * 10) + "·" * (10 - int(intensity * 10))
            log(f"[tick {tick:>3}] {gd.ts(now)} {bar} {summary(rows, world)}")
            if not args.loop or (total and tick >= total):
                break
            if not fixed_now:
                time.sleep(args.interval)
    except KeyboardInterrupt:
        log("\nStopped.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
