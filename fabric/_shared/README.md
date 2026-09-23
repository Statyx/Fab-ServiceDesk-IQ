# `fabric/_shared/` — plumbing every workload depends on

Nothing here talks to a specific Fabric artifact. If a module in this folder starts
knowing about ontologies or dashboards, it belongs in that workload's package instead.

| Module | Owns |
|---|---|
| `paths.py` | every filesystem location in the repository, resolved once from the root |
| `platform_env.py` | `PATH` repair from the Windows registry + UTF-8 stdout; the `bootstrap()` every script calls first |
| `helpers.py` | deployment profiles, config/state I/O, Azure CLI tokens, Kusto calls |

## Canonical prologue

Every runnable module starts with exactly these three lines, right after its docstring,
before any third-party import:

```python
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()
```

Run modules from the repository root: `python -m fabric.data.generate_data`.

## `platform_env.py` is duplicated verbatim across sibling repositories

Change it there and copy it over — do not edit one side only. `import winreg` must
appear nowhere else in the repository; a test asserts that, and CI runs it on Linux.

## Deployment profiles

`helpers.profile_dir()` selects the tenant: `ZAVA_SD_PROFILE_DIR`, else
`deployments/active-profile.json`, else the root `config.yaml`. A selected profile
without its own `config.yaml` is an error, never a silent fallback.
