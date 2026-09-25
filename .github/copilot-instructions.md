# Copilot instructions — Fab-ServiceDesk-IQ

A Microsoft Fabric + Microsoft Foundry demo: a managed service desk where the Fabric Data
Agent answers *how far zero-touch fell* and a Foundry contracts agent answers *what the
contract makes Zava owe*. Neither answers alone — that split is the demo.

## Repository layout is not negotiable

Deployment code is grouped **one package per Fabric workload**, never flat in `src/`:

```
fabric/{_shared,data,workspace,lakehouse,eventhouse,ontology,graph,powerbi,rti,data_agent,app}/
app-zava-service-desk/     docs/     tests/     scripts/
```

A new deploy script goes in the folder named after the artifact it creates, as
`deploy_<artifact>.py`, and is registered in `deploy_all.py`. Shared plumbing goes in
`fabric/_shared/` — if it knows about a specific artifact, it is not shared.

Scripts run as modules from the repository root: `python -m fabric.ontology.deploy_ontology`.

## Hard rules the test suite enforces

- Every runnable module opens with the three-line prologue calling
  `fabric._shared.platform_env.bootstrap()` **before any third-party import**.
- `import winreg` appears in `platform_env.py` and nowhere else.
- No literal `shell=True`, no hard-coded GUID: identifiers live in the git-ignored
  `config.yaml` / `state.json` or `deployments/<name>/`.
- Every step is idempotent: find the item by name, create only what is missing.
- The dataset is byte-identical from `fabric/data/world.yaml` (seed 42). The storyline
  figures (Fabrikam 34.0%, 9,250 EUR; Litware 38.0%, no credit) are asserted by tests.
- `rayfin/rayfin.yml` stays tenant-neutral.

## The boundary rule

Figures are computed in Fabric only — semantic model, ontology, Eventhouse. The console
evaluates named DAX measures; the Data Agent queries them. Never compute a rate, a credit
or a threshold in a prompt or in TypeScript. Foundry retrieves and cites the clause; Work
IQ and Web IQ add context. None of them produces a figure.

The Foundry plane (supervisor, contracts agent, Foundry IQ knowledge base, Work IQ,
Web IQ) is **staged**: played from `app-zava-service-desk/src/data/iq-*.json`. Do not add a
Foundry resource, scope or environment variable without being asked.

## Demo UI wording

This is a demo and the audience knows it. Screens never label the storyline as
"simulated", "fictional" or "not live", and no page offers a source-mode selector. Staged
effects (loading pauses, the Teams send) read as the real interaction. The presenter owns
the framing — it belongs in `docs/demo/DEMO_SCRIPT.html`, not in the UI. Tests in
`domain.test.ts` and `dossier.test.tsx` enforce it.

## Before proposing a change

```bash
python -m pytest tests -q
python scripts/check_repo_leaks.py            # stage new files first
cd app-zava-service-desk && npx vitest run && npm run lint && npm run build
```

A green suite is the definition of done here.

## Deeper context

- `docs/ARCHITECTURE.md` — why the pieces are wired this way
- `docs/DEPLOYMENT.md` — deploy steps and the UI-only steps
- `docs/ENGINEERING-NOTES.md` — the traps, and the workaround that holds each one
- `docs/demo/DEMO_SCRIPT.html` — what the presenter says, and what is live or staged
