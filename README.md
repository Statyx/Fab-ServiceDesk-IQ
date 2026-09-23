# Zava Service Desk — the data foundation of an agentic service desk on Microsoft Fabric

AI agents can resolve a password reset on their own. Running a whole **service desk** on
agents, for many customers and under contract, also requires them to share one trusted
context: who the user is, which device and application are failing, whether an outage is
already known, and what was promised to the customer. This demo builds that context on
**Microsoft Fabric**. The ontology, graph and Data Agent come from Fabric IQ; real-time
intelligence, alerts and AgentOps observability come from Fabric RTI.

> **Fully synthetic.** Zava is a fictional managed-service operator. Its customers
> (Contoso, Fabrikam, Litware, Northwind, Tailspin, Woodgrove), users, devices, tickets,
> contracts and clauses are all generated from a seed. Tools are named generically: ITSM,
> DEM, Contact Center, CSAT tool, Corporate VPN.

## The storyline

A Corporate VPN client update breaks remote access and Teams calls for most users at
**Fabrikam Lyon**.

1. **Detect** — Device experience drops, tickets and negative conversations spike, and an Activator alert fires.
2. **Diagnose** — The Operations Agent traverses Device → Application → Site → Tickets → Users (VIPs included) and finds the root cause.
3. **Act** — A major incident is declared, impacted users get a proactive message, and a Teams alert is posted.
4. **Ground** — An external orchestrator asks the Data Agent over **MCP**: *"Is this user impacted?"* The answer lets it resolve the contact with no human (zero-touch).
5. **AgentOps** — Per-customer view of zero-touch, HITL escalations, MCP tool failures, latency, tokens and cost per contact.
6. **Value** — *"Zero-touch dropped 12 points at Fabrikam this week. Are we in XLA breach, and what is the penalty?"* → 46.0% → 34.0% against a 40% XLA, so **9,250 EUR** of service credit. Litware has the same drop, but its contract carries no credit.

An **XLA** (eXperience Level Agreement) commits to the user experience (zero-touch rate,
CSAT, device experience score, time lost), where an SLA only commits to technical targets.

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for the vision, data model, target
ontology, storyboard and deployment order.

## Status

| Phase | Scope | State |
|---|---|---|
| 1 | Scaffold, deterministic synthetic data, live injector, Data Agent MCP client, offline tests, leak guard + CI | ✅ this repo |
| 2 | Lakehouse, Eventhouse, Ontology + Graph, Semantic model + report, RTI dashboard, Activator, Operations Agent, Data Agent (MCP) | planned |
| 3 | Rayfin console app | planned |

## Quickstart (no tenant needed)

Requires Python 3.10+.

```text
pip install -r requirements.txt

# 1. Reference data + 90 days of history -> artifacts/data/{lakehouse,eventhouse}/*.csv
python -m fabric.data.generate_data

# 2. Live streams: one tick of normal traffic, printed as JSON lines
python -m fabric.eventhouse.inject_event --dry-run

#    Replay the Lyon incident, ramping up over 6 ticks, into JSONL files
python -m fabric.eventhouse.inject_event --scenario vpn-lyon --loop --cycles 6 --out artifacts/live

# 3. The MCP messages an orchestrator would send to the Data Agent
python -m fabric.data_agent.mcp_client --dry-run "Is USR-FAB-0061 impacted by an open incident?"

# 4. Tests and leak guard
python -m pytest tests -q
python scripts/check_repo_leaks.py
```

The dataset is byte-identical on every machine. Its only input is
[`fabric/data/world.yaml`](fabric/data/world.yaml) (seed 42).

## Configuration

`config.example.yaml` and `state.example.json` are templates. To target a tenant (phase 2),
you have two options:
- copy them to `config.yaml` / `state.json`;
- keep one folder per tenant in `deployments/<name>/`, selected by
  `deployments/active-profile.json` or the `ZAVA_SD_PROFILE_DIR` environment variable.

All of these files are git-ignored. Identifiers can also come from `ZAVA_SD_*` environment
variables.

## Layout

```text
fabric/_shared/     bootstrap, paths, helpers (profiles, config/state, tokens, KQL)
fabric/data/        world.yaml, schema.py, generate_data.py
fabric/eventhouse/  inject_event.py
fabric/data_agent/  mcp_client.py
scripts/            leak guard
tests/              offline smoke tests
docs/               architecture
```

## License

[MIT](LICENSE)
