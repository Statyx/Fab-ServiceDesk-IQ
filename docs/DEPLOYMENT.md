# Deployment runbook

How to deploy Zava Service Desk to a Fabric tenant, what each step produces, and what is
left to do by hand. The [README](../README.md) is the short version; the reasoning behind
the wiring is in [ARCHITECTURE.md](ARCHITECTURE.md), and the traps in
[ENGINEERING-NOTES.md](ENGINEERING-NOTES.md).

---

## Prerequisites

- Python 3.12 and `pip install -r requirements.txt`.
- A Fabric capacity (F-SKU or trial), running. A paused capacity answers 404, not a clear error.
- The Azure CLI signed in (`az login`) as `deployment.expected_account`. Every script checks
  the account before its first write.
- For the console: Node.js 20+, `npm ci` in `app-zava-service-desk/`, and the right to
  create an Entra SPA registration.

## Configuration

`config.example.yaml` and `state.example.json` are templates. Two ways to target a tenant:

- copy them to `config.yaml` / `state.json` at the repository root;
- keep one folder per tenant in `deployments/<name>/`, selected by
  `deployments/active-profile.json` or the `ZAVA_SD_PROFILE_DIR` environment variable.

All of these files are git-ignored. Identifiers can also come from `ZAVA_SD_*` environment
variables. The dataset itself is **not** configured here: it lives in
[`fabric/data/world.yaml`](../fabric/data/world.yaml) (seed 42), so it is byte-identical
whatever the configuration says.

## Deploy

```text
python deploy_all.py --list               # the steps, in canonical order
python deploy_all.py                      # every step, then a warm-up
python deploy_all.py --from ontology      # resume after a failure
python deploy_all.py report dashboard     # re-run only some steps
python deploy_all.py --skip app           # everything but the console
python deploy_all.py --warmup             # warm-up only, right before the demo
```

Each step is idempotent: it finds its item by name, updates it and records its ID in
`state.json`. The data is regenerated with `--shift-weeks auto`, so the history always ends
last Sunday and "last closed week" is a real week.

Self-checks run along the way:

- `verify_model` compares the DAX values with the CSVs (Fabrikam 34.0%, 9,250 EUR; Litware
  38.0%, no credit).
- `data_agent` runs every GQL, DAX and KQL few-shot on its live source before publishing.
  A few-shot that fails on its source is never published.

## What gets deployed

| Item | Type | What it shows |
|---|---|---|
| `LH_ServiceDesk` + `NB_Setup_ServiceDesk` | Lakehouse + notebook | the reference and history CSVs as typed Delta tables, including the graph edge tables |
| `EH_ServiceDesk` / `KQL_ServiceDesk` | Eventhouse | six live tables, history preloaded |
| `ONT_ServiceDesk` + graph | Ontology (Fabric IQ) | customers, sites, users, devices, applications, tickets, incidents, contracts, XLAs, agents — TimeSeries on Device and Agent |
| `SM_ServiceDesk_Analytics` | Semantic model (Direct Lake) | zero-touch, XLA breaches and credits, experience, AgentOps |
| `RPT_ServiceDesk` | Report | Service Desk Overview, Experience & Incidents, XLA & Credits |
| `RTD_ServiceDesk_Operations` | RTI dashboard | Operations and AgentOps pages, 30 s refresh |
| `ACT_ServiceDesk_Alerts` | Activator | VPN latency > 200 ms (5-min average) per site → Teams |
| `OA_ServiceDesk_Ops` | Operations Agent | goals and instructions for the live alerts |
| `ServiceDesk_Analyst` | Data Agent | ontology + semantic model + KQL, published, MCP endpoint |
| `App-Zava-Service-Desk` | Rayfin app | the service desk console |

The Foundry plane (supervisor, contracts agent, Foundry IQ knowledge base, Work IQ, Web IQ)
is **staged**: it is not deployed by this repository, and no Foundry resource, scope or
variable is required. See [ARCHITECTURE § 2](ARCHITECTURE.md).

## UI-only steps before the demo

The public APIs cannot do these yet:

1. **Activator** — the rule is deployed stopped (`activator.start: false`). Open
   `ACT_ServiceDesk_Alerts`, check the Teams recipient, then **Start**.
2. **Operations Agent** — open `OA_ServiceDesk_Ops`, add the knowledge source
   `KQL_ServiceDesk`, add a Teams or e-mail action, **Generate playbook**, set the schedule
   and turn it on.
3. **Live data** — stream "now" into the Eventhouse, so the dashboard, the Activator and the
   Operations Agent react:

   ```text
   python -m fabric.eventhouse.inject_event --scenario vpn-lyon --loop --interval 30
   ```

## Ask the Data Agent over MCP

As an external orchestrator would:

```text
python -m fabric.data_agent.mcp_client "Is user USR-FAB-0061 impacted by an open major incident?"
python -m fabric.data_agent.mcp_client "Is Fabrikam in XLA breach on zero-touch this week, and what credit applies?"
python -m fabric.data_agent.mcp_client "What is the VPN latency per site right now?"
```

The MCP endpoint answers from the **published** version only: redeploy the Data Agent after
changing its instructions.

## The console

`App-Zava-Service-Desk` is a Rayfin app hosted in the workspace (React + Vite, in
[`app-zava-service-desk/`](../app-zava-service-desk/)), built on the same shell and patterns
as the Zava Media console:

- **Cover and five screens** — Portfolio, Experience, AI agents, Contracts, XLA & credits.
  Every figure is a measure of `SM_ServiceDesk_Analytics`, evaluated live in DAX with the
  signed-in user's token. Nothing is bundled: without the bindings the app says
  "Not connected" instead of showing a confident zero.
- **Zava IQ** (`/iq-in-practice`) — from the two breaches to the right person: the facts
  (Fabric), the clause (Foundry IQ), who already acts (Work IQ), what was announced (Web IQ),
  then the message to send. Each layer can be switched off to show what it contributes.
- **Assistant Zava** — a rail that asks the `ServiceDesk_Analyst` Data Agent and shows which
  sources fired.
- **Architecture** — the chain, with the Foundry plane and the Real-Time Intelligence path.
- **Diagnostic** (`/diagnostic`, outside the sign-in) — checks the bindings and the tokens.

Deploy it (Node 20+, Azure CLI signed in to the demo tenant, `npm ci` done):

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

Open the app **from the Fabric item** (`app_url`): the hosting URL alone only shows the
launchpad.

## Recorded answers

The live Data Agent takes 40–160 s per answer. Record its answers once; the app then replays
a recorded answer after a short pause when the exact same question is asked, and falls back
to the live agent otherwise:

```text
cd app-zava-service-desk && npx tsx scripts/freeze-questions.ts && cd ..
python -m fabric.data_agent.capture_frozen_answers                          # openers + follow-ups
python -m fabric.data_agent.capture_frozen_answers --only xla-breach --force
```

A missing recording is fail-safe: the question goes to the live agent, costing latency and
never correctness. A 401 during a capture means the token expired: run it again.

## Offline checks

```text
python -m pytest tests -q
python scripts/check_repo_leaks.py          # scans git ls-files: stage new files first
cd app-zava-service-desk
npm test
npm run lint
npm run build                               # works without a tenant
```

`/preview` (development only, `npx vite` in the app folder) renders every screen from
fixtures, without sign-in. `npm run dev` is not offline: it runs `rayfin up` first.
