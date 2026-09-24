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
| 1 | Scaffold, deterministic synthetic data, live injector, Data Agent MCP client, offline tests, leak guard + CI | ✅ done |
| 2 | Lakehouse, Eventhouse, Ontology + Graph, Semantic model + report, RTI dashboard, Activator, Operations Agent, Data Agent (MCP) | ✅ deployed and verified end to end |
| 3 | Rayfin console app `App-Zava-Service-Desk`: live DAX screens, Zava IQ storyboard, Data Agent assistant | ✅ deployed (`python -m fabric.app.deploy_app`) |

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

## Deploy to Fabric (phase 2)

Requires the Azure CLI signed in (`az login`) as `deployment.expected_account`, and a Fabric
capacity (F-SKU or trial). The scripts check the account before any write.

```text
python deploy_all.py                      # every step, in order, then a warm-up
python deploy_all.py --list               # the 16 steps
python deploy_all.py --from ontology      # resume after a failure
python deploy_all.py report dashboard     # re-run only some steps
```

Each step is idempotent: it finds its item by name, updates it and records its ID in
`state.json`. The data is regenerated with `--shift-weeks auto`, so the history always ends
last Sunday and "last closed week" is a real week. Self-checks run along the way:
- `verify_semantic_model` compares the DAX values with the CSVs (Fabrikam 34.0%, 9,250 EUR).
- `deploy_data_agent` runs every GQL, DAX and KQL few-shot on its live source before publishing.

| Item | Type | What it shows |
|---|---|---|
| `LH_ServiceDesk` + `NB_Setup_ServiceDesk` | Lakehouse + notebook | 19 CSVs -> 21 Delta tables (incl. 2 edge tables), explicit types |
| `EH_ServiceDesk` / `KQL_ServiceDesk` | Eventhouse | 6 live tables, history preloaded |
| `ONT_ServiceDesk` + graph | Ontology (Fabric IQ) | 13 entities, 19 relationships, TimeSeries on Device and Agent |
| `SM_ServiceDesk_Analytics` | Semantic model (Direct Lake) | zero-touch, XLA breaches and credits, experience |
| `RPT_ServiceDesk` | Report | 3 pages: Service Desk Overview, Experience & Incidents, XLA & Credits |
| `RTD_ServiceDesk_Operations` | RTI dashboard | pages Operations and AgentOps, 30 s refresh |
| `ACT_ServiceDesk_Alerts` | Activator | VPN latency > 200 ms (5-min average) per site → Teams |
| `OA_ServiceDesk_Ops` | Operations Agent | goals and instructions for 4 live alerts |
| `ServiceDesk_Analyst` | Data Agent | ontology + semantic model + KQL, published, MCP endpoint |
| `App-Zava-Service-Desk` | Rayfin app | the service desk console (phase 3, below) |

### Before the demo (UI-only steps)

The public APIs cannot do these yet:
1. **Activator**: the rule is deployed stopped (`activator.start: false`). Open
   `ACT_ServiceDesk_Alerts`, check the Teams recipient, then **Start**.
2. **Operations Agent**: open `OA_ServiceDesk_Ops` and add the knowledge source
   `KQL_ServiceDesk`. Then add a Teams or e-mail action, **Generate playbook**, set the
   schedule and turn it on.
3. **Live data**: `python -m fabric.eventhouse.inject_event --scenario vpn-lyon --loop --interval 30`
   streams "now" into the Eventhouse, so the dashboard, the Activator and the Operations Agent react.

Ask the Data Agent over MCP, as an external orchestrator would:

```text
python -m fabric.data_agent.mcp_client "Is user USR-FAB-0061 impacted by an open major incident?"
python -m fabric.data_agent.mcp_client "Is Fabrikam in XLA breach on zero-touch this week, and what credit applies?"
python -m fabric.data_agent.mcp_client "What is the VPN latency per site right now?"
```

## The console app (phase 3)

`App-Zava-Service-Desk` is a Rayfin app hosted in the workspace (React + Vite, in
[`app-zava-service-desk/`](app-zava-service-desk/)), built on the same shell, style and
patterns as the Zava Media console:

- **Cover and five screens**: Portfolio, Experience, AI agents, Contracts and XLA & credits.
  Every figure is a measure of `SM_ServiceDesk_Analytics`, evaluated live in DAX with the
  signed-in user's token (Power BI `executeQueries`). Nothing is bundled: without the
  bindings the app says "Not connected" instead of showing a confident zero.
- **Zava IQ** (`/iq-in-practice`): the storyboard. Fabrikam and Litware both fell to 34%
  zero-touch against a 40% target. Step by step, the dossier adds the contract clause
  (Fabrikam is owed a 9,250 EUR credit, Litware a remediation plan), Work IQ context (who
  already acts), Web IQ context (public news), and finally drafts the message to the right
  person. Each layer can be switched off to show what it contributes.
- **Assistant Zava**: a rail that asks the `ServiceDesk_Analyst` Data Agent (semantic model,
  ontology, Eventhouse) and shows which sources fired.
- **Architecture** and **Diagnostic** (`/diagnostic`, outside the sign-in, checks the bindings
  and the tokens).

Foundry, Work IQ and Web IQ are **simulated**: labelled on screen, read from
`src/data/iq-*.json`. No Foundry resource, scope or variable is used.

The live Data Agent takes 40–160 s per answer. For a smooth demo, record its answers once;
the app then replays a recorded answer when the exact same question is asked, and falls back
to the live agent otherwise:

```text
cd app-zava-service-desk && npx tsx scripts/freeze-questions.ts && cd ..
python -m fabric.data_agent.capture_frozen_answers            # openers + follow-ups
python -m fabric.data_agent.capture_frozen_answers --only xla-breach --force
```

Deploy (Node 20+, the Azure CLI signed in to the demo tenant, `npm ci` done in the app folder):

```text
python -m fabric.app.deploy_app --check           # read-only preflight
python -m fabric.app.deploy_app                   # SPA + bindings + rayfin up + redirects
python -m fabric.app.deploy_app --configure-only  # SPA + bindings only, then: npm run dev
```

The script creates (or reuses) a single-tenant Entra SPA registration with delegated
`Dataset.Read.All`, `Item.Read.All` and `DataAgent.Execute.All`, consented for the deploying
user only; no secret. It writes the public identifiers to the git-ignored
`.env.production.local` / `.env.development.local`, runs `rayfin up` with the Azure CLI token
(item first, then the build), registers the hosting origin as a redirect URI and checks
`/`, `/blank.html` and `/diagnostic`. `app_url` (the item in the portal) and
`app_hosting_url` land in `state.json`.

`/preview` (development only) renders every screen from labelled fixtures, without sign-in.
In the app folder, `npm test` and `npm run lint` run offline; `npm run build` works without a
tenant.

## Layout

```text
deploy_all.py       phase-2 orchestrator (one python -m process per step)
fabric/_shared/     bootstrap, paths, helpers (profiles, config/state, tokens, KQL)
fabric/data/        world.yaml, schema.py, generate_data.py
fabric/workspace/   workspace + capacity
fabric/lakehouse/   CSV upload, setup notebook (CSV -> Delta)
fabric/eventhouse/  Eventhouse + KQL tables, history preload, live injector
fabric/ontology/    ontology definition (entities, relationships, TimeSeries)
fabric/graph/       graph model build + refresh
fabric/powerbi/     semantic model, DAX verification, report
fabric/rti/         RTI dashboard, Activator, Operations Agent
fabric/data_agent/  Data Agent (verified few-shots), MCP client
fabric/app/         console app: SPA registration, bindings, rayfin up (phase 3)
app-zava-service-desk/  Rayfin console app (React + Vite, DAX + Data Agent, Zava IQ)
scripts/            leak guard
tests/              offline tests (data, definitions, hygiene)
docs/               architecture
```

## License

[MIT](LICENSE)
