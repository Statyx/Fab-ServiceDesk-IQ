"""Offline smoke tests — no tenant, no network, no Azure CLI.

What they pin down:

* the dataset: schemas, determinism, key uniqueness, referential integrity;
* the storyline: the Lyon VPN incident, its control group, and the XLA breach the demo
  quotes (Fabrikam zero-touch 46.0% → 34.0% vs 40%, credit 9,250 EUR; Litware same drop,
  no credit; no other breach);
* the live injector (dry-run / file sinks, ingest batch size) and the MCP client payloads;
* profile resolution and repository hygiene (bootstrap prologue, no GUIDs, no literal
  shell=True, no generated data or local config tracked).

Run:  python -m pytest tests -q
"""
import ast
import io
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from contextlib import redirect_stdout
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from fabric._shared import helpers, paths
from fabric.data import generate_data as gd
from fabric.data.schema import EVENTHOUSE, KQL_TYPES, LAKEHOUSE, LAKEHOUSE_TYPES, columns, kql_create_merge
from fabric.data_agent import mcp_client
from fabric.eventhouse import inject_event

ROOT = paths.ROOT
UTC = timezone.utc
FAB, LIT = "CUS-FAB", "CUS-LIT"
BEFORE, INCIDENT_WEEK = date(2026, 6, 1), date(2026, 6, 8)


# ── Fixtures ─────────────────────────────────────────────────────
@pytest.fixture(scope="session")
def world():
    return gd.load_world()


@pytest.fixture(scope="session")
def tables(world):
    return gd.generate(gd.load_world())


@pytest.fixture(scope="session")
def xla(tables, world):
    return gd.evaluate_xla(tables, world)


def index(rows, key):
    return {r[key]: r for r in rows}


# ── Schemas ──────────────────────────────────────────────────────
def test_schema_types_are_bindable():
    for name, schema in LAKEHOUSE.items():
        assert {t for _, t in schema} <= LAKEHOUSE_TYPES, name
        assert len(columns(schema)) == len(set(columns(schema))), name
    for name, schema in EVENTHOUSE.items():
        assert {t for _, t in schema} <= KQL_TYPES, name
        assert schema[0] == ("timestamp", "datetime"), name


def test_every_table_is_generated_with_its_schema(tables):
    assert set(tables) == set(LAKEHOUSE) | set(EVENTHOUSE)
    for name, rows in tables.items():
        assert rows, f"{name} is empty"
        cols = columns(LAKEHOUSE.get(name) or EVENTHOUSE[name])
        for r in rows[:50] + rows[-50:]:
            assert list(r) == cols or set(r) >= set(cols), name


def test_csv_round_trip_types(tables):
    """Every serialised value parses back as its declared type."""
    parsers = {
        "bigint": int, "long": int, "double": float, "real": float,
        "boolean": lambda v: {"true": True, "false": False}[v],
        "bool": lambda v: {"true": True, "false": False}[v],
        "datetime": lambda v: (datetime.strptime(v, "%Y-%m-%dT%H:%M:%SZ") if "T" in v
                               else date.fromisoformat(v)),
        "string": str,
    }
    for name, rows in tables.items():
        schema = LAKEHOUSE.get(name) or EVENTHOUSE[name]
        text = gd.to_csv(name, rows[:200])
        import csv
        reader = csv.reader(io.StringIO(text))
        assert next(reader) == columns(schema)
        for line in reader:
            for (col, kind), value in zip(schema, line):
                if value != "":
                    parsers[kind](value)


def test_kql_create_merge_command():
    cmd = kql_create_merge("agent_traces")
    assert cmd.startswith(".create-merge table agent_traces (")
    assert "['cost_eur']:real" in cmd and "['hitl_escalation']:bool" in cmd


# ── Determinism ──────────────────────────────────────────────────
def test_generation_is_byte_identical(tmp_path, world):
    a = gd.write_tables(gd.generate(gd.load_world()), tmp_path / "a", world)
    b = gd.write_tables(gd.generate(gd.load_world()), tmp_path / "b", world)
    assert a == b
    assert (tmp_path / "a" / "lakehouse" / "fact_ticket.csv").read_bytes() == \
        (tmp_path / "b" / "lakehouse" / "fact_ticket.csv").read_bytes()
    assert set(a["tables"]) == set(LAKEHOUSE) | set(EVENTHOUSE)


# ── Keys & referential integrity ─────────────────────────────────
PRIMARY_KEYS = {
    "dim_customer": "customer_id", "dim_site": "site_id", "dim_user": "user_id",
    "dim_device": "device_id", "dim_application": "app_id", "dim_service": "service_id",
    "dim_kb_article": "kb_id", "dim_agent": "agent_id", "dim_mcp_tool": "tool_id",
    "dim_contract": "contract_id", "dim_xla": "xla_id", "dim_date": "date",
    "fact_ticket": "ticket_id", "fact_csat": "csat_id",
    "fact_major_incident": "major_incident_id", "bridge_device_application": "device_app_id",
}


@pytest.mark.parametrize("table,key", sorted(PRIMARY_KEYS.items()))
def test_primary_keys_unique_and_non_empty(tables, table, key):
    values = [r[key] for r in tables[table]]
    assert all(v not in (None, "") for v in values)
    assert len(values) == len(set(values)), f"duplicate {key} in {table}"


def test_entity_keys_are_strings(tables):
    """Ontology entity keys must be string columns."""
    for table, key in PRIMARY_KEYS.items():
        if table == "dim_date":
            continue
        assert dict(LAKEHOUSE[table])[key] == "string"


FOREIGN_KEYS = [
    ("dim_site", "customer_id", "dim_customer"), ("dim_user", "customer_id", "dim_customer"),
    ("dim_user", "site_id", "dim_site"), ("dim_device", "user_id", "dim_user"),
    ("dim_device", "site_id", "dim_site"), ("bridge_device_application", "device_id", "dim_device"),
    ("bridge_device_application", "app_id", "dim_application"),
    ("dim_kb_article", "service_id", "dim_service"), ("dim_kb_article", "app_id", "dim_application"),
    ("dim_contract", "customer_id", "dim_customer"), ("dim_xla", "contract_id", "dim_contract"),
    ("fact_ticket", "customer_id", "dim_customer"), ("fact_ticket", "site_id", "dim_site"),
    ("fact_ticket", "user_id", "dim_user"), ("fact_ticket", "device_id", "dim_device"),
    ("fact_ticket", "service_id", "dim_service"), ("fact_ticket", "app_id", "dim_application"),
    ("fact_ticket", "kb_id", "dim_kb_article"),
    ("fact_ticket", "major_incident_id", "fact_major_incident"),
    ("fact_ticket", "resolved_by_agent_id", "dim_agent"), ("fact_ticket", "created_date", "dim_date"),
    ("fact_csat", "ticket_id", "fact_ticket"), ("fact_experience_daily", "device_id", "dim_device"),
    ("fact_experience_daily", "date", "dim_date"),
    ("fact_major_incident", "site_id", "dim_site"), ("fact_major_incident", "app_id", "dim_application"),
    ("dem_telemetry", "device_id", "dim_device"), ("tickets_events", "ticket_id", "fact_ticket"),
    ("conversations", "ticket_id", "fact_ticket"), ("conversations", "agent_id", "dim_agent"),
    ("agent_traces", "agent_id", "dim_agent"), ("agent_traces", "tool_name", "dim_mcp_tool"),
    ("gateway_logs", "agent_id", "dim_agent"), ("csat_events", "csat_id", "fact_csat"),
]


@pytest.mark.parametrize("child,col,parent", FOREIGN_KEYS, ids=lambda x: str(x))
def test_foreign_keys_resolve(tables, child, col, parent):
    key = "tool_name" if parent == "dim_mcp_tool" else PRIMARY_KEYS[parent]
    valid = {r[key] for r in tables[parent]}
    orphans = {r[col] for r in tables[child] if r[col] not in (None, "")} - valid
    assert not orphans, f"{child}.{col} → {parent}: {sorted(orphans)[:5]}"


def test_denormalised_ids_are_consistent(tables):
    users = index(tables["dim_user"], "user_id")
    devices = index(tables["dim_device"], "device_id")
    for t in tables["fact_ticket"]:
        u = users[t["user_id"]]
        assert (u["customer_id"], u["site_id"]) == (t["customer_id"], t["site_id"])
        assert devices[t["device_id"]]["user_id"] == t["user_id"]


def test_eventhouse_history_ends_at_reference_date(tables, world):
    clock = gd.Clock(world)
    for name in EVENTHOUSE:
        stamps = [r["timestamp"] for r in tables[name]]
        assert max(stamps) <= clock.ref_end, name
        assert stamps == sorted(stamps) or name == "dem_telemetry", name


def test_trace_spans_form_trees(tables):
    by_trace = defaultdict(list)
    for s in tables["agent_traces"]:
        by_trace[s["trace_id"]].append(s)
    for spans in list(by_trace.values())[:300]:
        roots = [s for s in spans if not s["parent_span_id"]]
        assert len(roots) == 1 and roots[0]["operation"] == "invoke_agent"
        ids = {s["span_id"] for s in spans}
        assert all(s["parent_span_id"] in ids for s in spans if s["parent_span_id"])


def test_cost_matches_tokens_and_price(tables, world):
    prices = world["models"]
    for s in tables["agent_traces"][:500]:
        if s["model"]:
            p = prices[s["model"]]
            expected = s["input_tokens"] / 1000 * p["input_per_1k"] + \
                s["output_tokens"] / 1000 * p["output_per_1k"]
            assert s["cost_eur"] == pytest.approx(expected, abs=1e-6)


# ── The storyline ────────────────────────────────────────────────
def test_bad_vpn_version_only_on_the_lyon_pilot_ring(tables, world):
    sc = world["scenario"]
    ring = [d for d in tables["dim_device"] if d["vpn_client_version"] == sc["bad_version"]]
    assert ring and {d["site_id"] for d in ring} == {sc["site_id"]}
    controls = [d for d in tables["dim_device"]
                if d["site_id"] == sc["site_id"] and d["vpn_client_version"] == sc["good_version"]]
    assert controls, "Lyon needs a control group on the previous VPN version"


def test_major_incident_row(tables, world):
    (mi,) = tables["fact_major_incident"]
    sc = world["scenario"]
    assert mi["major_incident_id"] == sc["major_incident"]["id"]
    assert (mi["customer_id"], mi["site_id"], mi["app_id"]) == (sc["customer_id"], sc["site_id"], sc["app_id"])
    assert mi["status"] == "open" and mi["resolved_at"] is None
    assert mi["impacted_vip_users"] >= sc["min_vip_impacted"]
    ring = [d for d in tables["dim_device"] if d["vpn_client_version"] == sc["bad_version"]]
    assert mi["impacted_users"] == len(ring)


def test_incident_tickets_come_from_the_ring(tables, world):
    sc = world["scenario"]
    ring_users = {d["user_id"] for d in tables["dim_device"]
                  if d["vpn_client_version"] == sc["bad_version"]}
    linked = [t for t in tables["fact_ticket"] if t["major_incident_id"]]
    assert len(linked) == sc["incident_tickets"]
    assert sum(t["zero_touch"] for t in linked) == sc["incident_zero_touch"]
    assert {t["user_id"] for t in linked} <= ring_users
    assert {t["issue_code"] for t in linked} == set(sc["incident_issues"])
    assert all(t["created_at"] > gd.parse_ts(sc["rollout_at"]) for t in linked)
    vips = {u["user_id"] for u in tables["dim_user"] if u["is_vip"]}
    assert len({t["user_id"] for t in linked} & vips) >= sc["min_vip_impacted"]


def test_dem_degrades_on_the_ring_but_not_on_controls(tables, world):
    sc = world["scenario"]
    rollout = gd.parse_ts(sc["rollout_at"])
    lyon = [r for r in tables["dem_telemetry"] if r["site_id"] == sc["site_id"]]

    def mean(rows):
        return sum(r["experience_score"] for r in rows) / len(rows)
    bad_after = [r for r in lyon if r["vpn_client_version"] == sc["bad_version"] and r["timestamp"] > rollout]
    bad_before = [r for r in lyon if r["vpn_client_version"] == sc["bad_version"] and r["timestamp"] < rollout]
    good_after = [r for r in lyon if r["vpn_client_version"] == sc["good_version"] and r["timestamp"] > rollout]
    assert mean(bad_before) > 75 and mean(good_after) > 75
    assert mean(bad_after) < 55
    disconnected = sum(not r["vpn_connected"] for r in bad_after) / len(bad_after)
    assert disconnected > 0.2


def test_weekly_zero_touch_drop_is_twelve_points(tables):
    zt = gd.weekly_zero_touch(tables)
    for cust in (FAB, LIT):
        n0, z0 = zt[(cust, BEFORE)]
        n1, z1 = zt[(cust, INCIDENT_WEEK)]
        assert round(100 * z0 / n0, 1) == 46.0
        assert round(100 * z1 / n1, 1) == 34.0
    assert zt[(FAB, INCIDENT_WEEK)] == (150, 51)


def test_expected_xla_breaches_and_credit(xla):
    breaches = [r for r in xla if r["breached"]]
    assert {(r["customer_id"], r["xla_id"], r["window_start"]) for r in breaches} == {
        (FAB, "XLA-FAB-01", INCIDENT_WEEK), (LIT, "XLA-LIT-01", INCIDENT_WEEK)}
    fab = next(r for r in breaches if r["customer_id"] == FAB)
    lit = next(r for r in breaches if r["customer_id"] == LIT)
    assert (fab["value"], fab["threshold"], fab["penalty_eur"]) == (34.0, 40.0, 9250.0)
    assert (lit["value"], lit["penalty_eur"]) == (34.0, 0.0)


def test_only_closed_windows_are_evaluated(xla, world):
    clock = gd.Clock(world)
    assert all(r["window_end"] <= clock.ref for r in xla)
    months = {r["window_start"] for r in xla if r["window"] == "monthly"}
    assert months == {date(2026, 4, 1), date(2026, 5, 1)}


def test_contracts_diverge_between_customers(tables):
    xlas = tables["dim_xla"]
    fab = next(x for x in xlas if x["xla_id"] == "XLA-FAB-01")
    lit = next(x for x in xlas if x["xla_id"] == "XLA-LIT-01")
    assert (fab["metric"], fab["threshold"]) == (lit["metric"], lit["threshold"])
    assert fab["penalty_pct"] > 0 and lit["penalty_pct"] == 0
    assert "5%" in fab["clause_text"] and "No service credit" in lit["clause_text"]


def test_agentops_signals_spike_during_the_incident(tables, world):
    rollout = gd.parse_ts(world["scenario"]["rollout_at"])

    def rate(rows, pred):
        rows = list(rows)
        return sum(map(pred, rows)) / max(1, len(rows))
    health = [s for s in tables["agent_traces"] if s["tool_name"] == "dem.get_device_health"]
    fab_inc = rate((s for s in health if s["customer_id"] == FAB and s["timestamp"] > rollout),
                   lambda s: s["status"] == "error")
    elsewhere = rate((s for s in health if s["customer_id"] != FAB or s["timestamp"] < rollout),
                     lambda s: s["status"] == "error")
    assert fab_inc > 0.4 and elsewhere < 0.1
    gw = tables["gateway_logs"]
    fab_429 = rate((g for g in gw if g["customer_id"] == FAB and g["timestamp"] > rollout),
                   lambda g: g["status_code"] == 429)
    other_429 = rate((g for g in gw if g["customer_id"] != FAB), lambda g: g["status_code"] == 429)
    assert fab_429 > 3 * other_429
    conv = tables["conversations"]
    fab_sent = rate((c for c in conv if c["customer_id"] == FAB and c["timestamp"] > rollout),
                    lambda c: c["sentiment"])
    assert fab_sent < -0.2


def test_csat_story(tables):
    tickets = index(tables["fact_ticket"], "ticket_id")
    groups = defaultdict(list)
    for c in tables["fact_csat"]:
        t = tickets[c["ticket_id"]]
        key = "incident" if t["major_incident_id"] else ("zt" if t["zero_touch"] else "human")
        groups[key].append(c["score"])
    avg = {k: sum(v) / len(v) for k, v in groups.items()}
    assert avg["zt"] > avg["human"] > 4.0 > 3.0 > avg["incident"]


def test_zero_touch_tickets_are_ai_resolved(tables):
    for t in tables["fact_ticket"]:
        if t["zero_touch"]:
            assert t["channel"] in gd.AI_CHANNELS and not t["escalated_hitl"]
            assert t["resolved_by_agent_id"] in ("AGT-RESOLVER", "")
        elif t["channel"] == "email":
            assert not t["escalated_hitl"]


# ── Live injector ────────────────────────────────────────────────
NOW = "2026-06-15T09:00:00Z"


def test_injector_dry_run_emits_all_streams_with_schema():
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert inject_event.main(["--dry-run", "--seed", "3", "--now", NOW,
                                  "--scenario", "vpn-lyon"]) == 0
    lines = [json.loads(line) for line in buf.getvalue().splitlines()]
    seen = Counter(line["table"] for line in lines)
    assert set(seen) == set(EVENTHOUSE)
    for line in lines:
        table = line.pop("table")
        assert list(line) == columns(EVENTHOUSE[table])
        assert line["timestamp"] <= NOW


def test_injector_file_sink_and_ramp(tmp_path):
    out = tmp_path / "live"
    assert inject_event.main(["--scenario", "vpn-lyon", "--loop", "--cycles", "4",
                              "--ramp", "4", "--interval", "30", "--seed", "5",
                              "--now", NOW, "--out", str(out)]) == 0
    files = {p.stem for p in out.glob("*.jsonl")}
    assert files == set(EVENTHOUSE)
    dem = [json.loads(line) for line in (out / "dem_telemetry.jsonl").read_text(encoding="utf-8").splitlines()]
    ring = defaultdict(list)
    for r in dem:
        if r["vpn_client_version"] == "6.1.0":
            ring[r["timestamp"]].append(r["experience_score"])
    means = [sum(v) / len(v) for _, v in sorted(ring.items())]
    assert len(means) == 4 and means[-1] < means[0] - 15


def test_injector_normal_traffic_has_no_incident():
    world = inject_event.World("none", None, 11)
    rows = inject_event.build_tick(world, gd.parse_ts(NOW), 1.0)
    assert not any(r["major_incident_id"] for r in rows["tickets_events"])
    lyon = [r["experience_score"] for r in rows["dem_telemetry"] if r["vpn_client_version"] == "6.1.0"]
    assert sum(lyon) / len(lyon) > 70


def test_injector_is_reproducible_with_a_seed():
    def run():
        world = inject_event.World("vpn-lyon", FAB, 21)
        rows = inject_event.build_tick(world, gd.parse_ts(NOW), 1.0)
        return {k: gd.to_csv(k, v) for k, v in rows.items()}
    assert run() == run()


def test_ingest_batches_stay_under_limit(tables):
    rows = tables["dem_telemetry"][:3000]
    commands = inject_event.batches("dem_telemetry", rows)
    assert len(commands) > 1
    assert all(len(c.encode("utf-8")) <= inject_event.MAX_BATCH_BYTES for c in commands)
    assert sum(len(c.splitlines()) - 1 for c in commands) == len(rows)
    assert all(c.startswith(".ingest inline into table dem_telemetry <|\n") for c in commands)


# ── MCP client ───────────────────────────────────────────────────
def test_mcp_handshake_messages():
    msgs = mcp_client.handshake_messages("Is USR-FAB-0061 impacted?")
    assert [m["method"] for m in msgs] == ["initialize", "notifications/initialized",
                                           "tools/list", "tools/call"]
    assert all(m["jsonrpc"] == "2.0" for m in msgs)
    assert "id" not in msgs[1] and [m.get("id") for m in (msgs[0], msgs[2], msgs[3])] == [1, 2, 3]
    assert msgs[0]["params"]["protocolVersion"] == mcp_client.PROTOCOL_VERSION
    assert msgs[3]["params"]["arguments"] == {"userQuestion": "Is USR-FAB-0061 impacted?"}


def test_mcp_argument_mapping_follows_the_tool_schema():
    schema = {"type": "object", "properties": {"query": {"type": "string"}}}
    assert mcp_client.question_arguments("q", schema) == {"query": "q"}
    schema = {"type": "object", "properties": {"ask": {"type": "string"}}}
    assert mcp_client.question_arguments("q", schema) == {"ask": "q"}


def test_mcp_sse_parsing():
    text = ("event: message\ndata: {\"jsonrpc\":\"2.0\",\"method\":\"notifications/progress\"}\n\n"
            "event: message\ndata: {\"jsonrpc\":\"2.0\",\"id\":3,\"result\":"
            "{\"content\":[{\"type\":\"text\",\"text\":\"Yes\"}]}}\n\n")
    assert mcp_client.parse_sse(text)["result"]["content"][0]["text"] == "Yes"


def test_mcp_dry_run_needs_no_tenant(capsys):
    assert mcp_client.main(["--dry-run", "Is Fabrikam in XLA breach?"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["messages"][3]["params"]["arguments"]["userQuestion"] == "Is Fabrikam in XLA breach?"


# ── Profile resolution ───────────────────────────────────────────
@pytest.fixture
def isolated_profiles(tmp_path, monkeypatch):
    monkeypatch.delenv(helpers.PROFILE_ENV, raising=False)
    monkeypatch.setattr(helpers, "ROOT", tmp_path)
    monkeypatch.setattr(helpers, "ACTIVE_PROFILE_FILE", tmp_path / "deployments" / "active-profile.json")
    monkeypatch.setattr(helpers, "CONFIG_FILE", tmp_path / "config.yaml")
    monkeypatch.setattr(helpers, "STATE_FILE", tmp_path / "state.json")
    return tmp_path


def test_root_config_without_profile(isolated_profiles):
    assert helpers.profile_dir() is None
    assert helpers.config_path() == isolated_profiles / "config.yaml"


def test_active_profile_pointer(isolated_profiles):
    prof = isolated_profiles / "deployments" / "demo"
    prof.mkdir(parents=True)
    (prof / "config.yaml").write_text("workspace_name: x\n", encoding="utf-8")
    (isolated_profiles / "deployments" / "active-profile.json").write_text('{"profile": "demo"}')
    assert helpers.profile_dir() == prof.resolve()
    assert helpers.state_path() == prof.resolve() / "state.json"


def test_profile_without_config_fails_loudly(isolated_profiles, monkeypatch):
    (isolated_profiles / "deployments" / "ghost").mkdir(parents=True)
    monkeypatch.setenv(helpers.PROFILE_ENV, "deployments/ghost")
    with pytest.raises(RuntimeError, match="no separate config.yaml"):
        helpers.profile_dir()


@pytest.mark.parametrize("bad", ['{"profile": ".."}', '{"profile": "a/b"}', '{"profile": ""}', "[]"])
def test_active_profile_rejects_escapes(isolated_profiles, bad):
    (isolated_profiles / "deployments").mkdir()
    (isolated_profiles / "deployments" / "active-profile.json").write_text(bad)
    with pytest.raises(RuntimeError):
        helpers.profile_dir()


def test_placeholders_are_not_values(isolated_profiles, monkeypatch):
    monkeypatch.delenv("ZAVA_SD_TENANT_ID", raising=False)
    with pytest.raises(RuntimeError, match="ZAVA_SD_TENANT_ID"):
        helpers.require_config({"tenant_id": "<YOUR_TENANT_ID>"}, "tenant_id")
    monkeypatch.setenv("ZAVA_SD_TENANT_ID", "from-env")
    (isolated_profiles / "config.yaml").write_text("tenant_id: '<YOUR_TENANT_ID>'\n", encoding="utf-8")
    assert helpers.load_config()["tenant_id"] == "from-env"


def test_config_example_ships_only_placeholders():
    import yaml
    cfg = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))
    for key in ("tenant_id", "az_subscription", "capacity_id"):
        assert helpers.is_placeholder(cfg[key]), key
    assert cfg["eventhouse"]["tables"] == list(EVENTHOUSE)
    state = json.loads((ROOT / "state.example.json").read_text(encoding="utf-8"))
    assert all(v == "" for k, v in state.items() if not k.startswith("_"))
    assert set(helpers.STATE_ENV_OVERRIDES) <= set(state)


# ── Repository hygiene ───────────────────────────────────────────
PROLOGUE = ["import os, sys",
            "from fabric._shared.platform_env import bootstrap",
            "bootstrap()"]
BOOTSTRAP_MODULE = "fabric._shared.platform_env"


def _py_files():
    return sorted(p for p in ROOT.rglob("*.py")
                  if not {".git", "artifacts", "deployments", ".venv", "__pycache__"} & set(p.parts))


def _entry_points():
    return [p for p in _py_files()
            if p.parts[len(ROOT.parts)] == "fabric" and 'if __name__ == "__main__"' in p.read_text(encoding="utf-8")]


def test_entry_points_exist():
    names = {p.name for p in _entry_points()}
    assert {"generate_data.py", "inject_event.py", "mcp_client.py"} <= names


@pytest.mark.parametrize("py", _entry_points(), ids=lambda p: p.name)
def test_identical_prologue(py):
    """Every runnable module opens with the same three lines, right after its docstring."""
    tree = ast.parse(py.read_text(encoding="utf-8"))
    start = tree.body[1].lineno if isinstance(tree.body[0], ast.Expr) else tree.body[0].lineno
    lines = py.read_text(encoding="utf-8").splitlines()[start - 1:start + 2]
    assert lines == PROLOGUE, f"{py.name}: prologue differs"


@pytest.mark.parametrize("py", _entry_points(), ids=lambda p: p.name)
def test_bootstrap_runs_before_third_party_imports(py):
    tree = ast.parse(py.read_text(encoding="utf-8"))
    stdlib = set(sys.stdlib_module_names)
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Call) \
                and getattr(node.value.func, "id", None) == "bootstrap":
            return
        if isinstance(node, ast.Import):
            assert all(a.name.split(".")[0] in stdlib for a in node.names), py.name
        elif isinstance(node, ast.ImportFrom) and node.module != BOOTSTRAP_MODULE:
            assert (node.module or "").split(".")[0] in stdlib, py.name
    pytest.fail(f"{py.name} never calls bootstrap()")


@pytest.mark.parametrize("py", _py_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_hardcoded_guids(py):
    found = re.findall(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                       r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b", py.read_text(encoding="utf-8"))
    real = [g for g in found
            if not re.fullmatch(r"[a0-]+|a1000000-0000-4000-a000-[0-9a-f]{12}", g.lower())]
    assert not real, f"{py.name}: hard-coded GUID(s) {real}"


@pytest.mark.parametrize("py", _py_files(), ids=lambda p: str(p.relative_to(ROOT)))
def test_no_literal_shell_true(py):
    for node in ast.walk(ast.parse(py.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                if kw.arg == "shell" and isinstance(kw.value, ast.Constant) and kw.value.value is True:
                    pytest.fail(f"{py.name}:{node.lineno} use shell=AZ_NEEDS_SHELL")


def test_platform_specifics_live_in_platform_env():
    for py in _py_files():
        if py.name in ("platform_env.py", "test_smoke.py"):
            continue
        text = py.read_text(encoding="utf-8")
        assert "import winreg" not in text, py.name
        assert not re.search(r"^\s*AZ_NEEDS_SHELL\s*=", text, re.M), py.name


def _tracked():
    out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True)
    if out.returncode != 0:
        pytest.skip("not a git checkout")
    return out.stdout.splitlines()


def test_no_windows_only_scripts_tracked():
    assert not [f for f in _tracked() if f.lower().endswith((".ps1", ".cmd", ".bat"))]


def test_no_local_or_generated_files_tracked():
    bad = [f for f in _tracked() if f in ("config.yaml", "state.json", ".clientdeny")
           or f.startswith(("artifacts/", "deployments/"))]
    assert not bad, bad


def test_local_files_are_git_ignored():
    for rel in ("config.yaml", "state.json", ".clientdeny", "artifacts/data/x.csv",
                "deployments/new-tenant/config.yaml"):
        res = subprocess.run(["git", "check-ignore", "-q", rel], cwd=ROOT)
        assert res.returncode == 0, f"{rel} is not git-ignored"
