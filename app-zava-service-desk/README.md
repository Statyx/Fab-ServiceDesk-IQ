# App-Zava-Service-Desk — the console

The Rayfin Fabric App of the Zava Service Desk demo: React 19 + Vite 7, hosted in the
Fabric workspace. The repository [README](../README.md) tells the story; the
[deployment runbook](../docs/DEPLOYMENT.md) deploys it.

| Screen | Route | Source |
|---|---|---|
| Cover | `/` | the questions to start with |
| Portfolio, Experience, AI agents, Contracts, XLA & credits | `/portfolio`, … | live DAX on `SM_ServiceDesk_Analytics` |
| Zava IQ | `/iq-in-practice` | Fabric facts + the staged Foundry IQ, Work IQ and Web IQ layers |
| Architecture | `/architecture` | the chain, from `src/domain/chain.ts` |
| Assistant Zava | side rail | the `ServiceDesk_Analyst` Data Agent, or a recorded answer |
| Diagnostic | `/diagnostic` | bindings and tokens, outside the sign-in |

## Layout

| Path | What lives there |
|---|---|
| `src/pages/` | one component per screen |
| `src/domain/` | pure logic — navigation, the chain, openers, the Zava IQ dossier |
| `src/services/` | Power BI `executeQueries`, the Data Agent, recorded answers, auth |
| `src/data/` | DAX queries, contracts, recorded answers, the staged `iq-*.json` context |
| `src/preview/` | fixtures behind `/preview` |
| `scripts/freeze-questions.ts` | lists the prepared questions for `capture_frozen_answers` |
| `rayfin/rayfin.yml` | Fabric service configuration — kept tenant-neutral |

## Commands

```text
npm ci
npx vite                  # offline dev server, open /preview (no sign-in)
npm test                  # vitest, offline
npm run lint
npm run build             # works without a tenant
```

`npm run dev` and `npm run rayfin:up` talk to Fabric. Deploy through
`python -m fabric.app.deploy_app` from the repository root instead: it also configures the
Entra SPA, the bindings and the redirect URIs.

The screen never labels its own staging (no "simulated" or "fictional" text); tests
enforce it. The presenter's framing lives in the
[demo script](../docs/demo/DEMO_SCRIPT.html).
