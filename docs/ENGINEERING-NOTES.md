# Engineering notes

The failure modes this repository is built to prevent, and the workaround that holds each
one. The [README](../README.md) stays a reader's page; this file is for whoever
**maintains** the demo. Read it before changing a deploy script, a measure, an ontology
binding, an agent prompt or the console. Every item below was a real failure, and most of
them deployed cleanly first.

---

## The testing gate

```bash
python -m pytest tests -q
python scripts/check_repo_leaks.py
cd app-zava-service-desk && npx vitest run && npm run lint && npm run build
```

The same checks run in CI. The leak guard scans `git ls-files` only: **stage a new file
before trusting a green result**.

## Boundary and wording

- **The figures stay in Fabric.** No rate, credit or threshold is computed in a prompt or
  in the console. The console evaluates named measures in DAX; the Data Agent queries the
  semantic model, the ontology and the Eventhouse. A second definition of zero-touch
  anywhere else is a bug even when it returns the same number.
- **The Foundry plane is staged.** The supervisor, the contracts agent, the Foundry IQ
  knowledge base, Work IQ and Web IQ are played from `src/data/iq-*.json`. No Foundry
  resource, scope or environment variable exists, and none should be added quietly.
- **The screen does not narrate its own staging.** No "simulated", "fictional" or
  "not live" wording on screen: the presenter carries that framing, from
  [the demo script](demo/DEMO_SCRIPT.html). Tests in `domain.test.ts` and
  `dossier.test.tsx` enforce it on the chain and on the whole Zava IQ walkthrough.
- **The chain diagram must not cross.** Two hops between the same pair of layers cross
  when their rows are in opposite order; a test fails on it. Keep edge labels short
  (about 26 characters) or they overflow the SVG.

## Fabric REST

- **Finding an item by name**: list all the workspace items and filter locally. The
  `?type=` query parameter answers 404 on some item types.
- **A 404 is not always "not found"**: a paused capacity, or a permission that has not
  propagated yet, answers 404 too. Check the capacity before debugging a script.
- **OneLake upload** uses `http.client` in three calls (create, append, flush). `requests`
  hangs on the append for large files.
- **Report definition**: pin `visualContainer` to schema 2.9.0. Version 2.10 and later
  answer 404 at import.

## Data and ontology

- **`--shift-weeks auto`** makes the synthetic history end last Sunday, so "last closed
  week" is a real ISO week on stage. Without it, every relative measure drifts.
- **Edge tables carry no null key.** A null source or target key silently drops the edge
  from the graph; the generator guarantees both keys.
- **GQL**: `unit` is a reserved word and needs backticks. A GQL error comes back as HTTP 200
  with `status.code` 42000 in the body — check the body, not the status.

## Data Agent and MCP

- **Every few-shot is validated on its live source before publishing.** A GQL, DAX or KQL
  example that fails on its source teaches the agent a broken query.
- **MCP answers from the published version only.** After changing instructions or
  few-shots, redeploy (which republishes), or the MCP endpoint keeps the old behaviour.
- **Latency is 40–160 s per answer**, occasionally much more on a cold start. The console
  replays recorded answers for the prepared questions; free questions go live.
- **A 401 during `capture_frozen_answers`** means the Azure CLI token expired mid-run: run
  it again with `--only <id> --force`.
- **Bearer headers**: build them as `"Bearer " + token`. Some tool displays mangle an
  f-string that interpolates a token.

## RTI

- **Operations Agent**: the API push cannot bind the knowledge source, the destination or the
  playbook. Do it in the UI ([DEPLOYMENT](DEPLOYMENT.md)).
- **Activator** is deployed stopped, on purpose, so that a deployment never sends a Teams
  message on its own.

## Console and Rayfin

- **`rayfin.yml` stays tenant-neutral.** The deploy script strips the hosting URL after
  `rayfin up`, and a test enforces it. `.deployments.json` is git-ignored.
- **Environment files** are `.env.production.local` and `.env.development.local`, both
  git-ignored. Never `.env.local`, and never a secret in a `VITE_*` variable: it ships to
  the browser.
- **Open the app from the Fabric item.** The hosting URL alone only shows the launchpad.
- **Expired Rayfin login**: the CLI honours `$BROWSER` for the sign-in page.
- **Deep repository path on Windows**: nested `npx` calls can duplicate `PATH` entries until
  the command line overflows; the deploy script de-duplicates `PATH` before spawning.
- **Vitest** is narrowed to `src/**`, so it never picks up the Python tree. On a slow
  machine, run it with `--testTimeout=30000`: the Zava IQ walkthrough tests take several
  seconds each.
