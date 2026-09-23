#!/usr/bin/env python3
"""Every filesystem location this repository depends on, resolved once.

Why this module exists
----------------------
Workload scripts sit at different depths (``fabric/data/generate_data.py``,
``fabric/eventhouse/inject_event.py``…). A ``Path(__file__).parent.parent`` chain means
a *different* directory in each of them, and is silently wrong the moment a file moves.
Resolve the root from this module's own location instead and derive everything from it.
This file is the only place in the repository allowed to count directory levels.
"""
from __future__ import annotations

from pathlib import Path

__all__ = [
    "ROOT",
    "ARTIFACTS",
    "LAKEHOUSE_DATA",
    "EVENTHOUSE_DATA",
    "LIVE_OUT",
    "WORLD_SPEC",
    "CONFIG_FILE",
    "STATE_FILE",
    "CONFIG_EXAMPLE",
    "STATE_EXAMPLE",
    "DEPLOYMENTS",
    "ACTIVE_PROFILE_FILE",
]

#: Repository root. This file is ``<root>/fabric/_shared/paths.py``, hence ``parents[2]``.
ROOT = Path(__file__).resolve().parents[2]

#: Generated data. Git-ignored and tenant-independent: regenerate it with
#: ``python -m fabric.data.generate_data`` (seed-deterministic, byte-identical).
ARTIFACTS = ROOT / "artifacts"
#: One CSV per Lakehouse Delta table (reference + 90-day history).
LAKEHOUSE_DATA = ARTIFACTS / "data" / "lakehouse"
#: One CSV per KQL table — the Eventhouse preload (recent history).
EVENTHOUSE_DATA = ARTIFACTS / "data" / "eventhouse"
#: Default target of ``inject_event --out`` when no directory is given.
LIVE_OUT = ARTIFACTS / "live"

#: The synthetic world (customers, sites, contracts, XLAs, scenario). Committed: the
#: dataset must not depend on anybody's local config.
WORLD_SPEC = ROOT / "fabric" / "data" / "world.yaml"

#: Root config/state, used when no deployment profile is selected. Both git-ignored —
#: they carry tenant, capacity and item GUIDs. See the ``*.example`` twins.
CONFIG_FILE = ROOT / "config.yaml"
STATE_FILE = ROOT / "state.json"
CONFIG_EXAMPLE = ROOT / "config.example.yaml"
STATE_EXAMPLE = ROOT / "state.example.json"

#: Per-tenant deployment profiles (``deployments/<name>/config.yaml|state.json``).
DEPLOYMENTS = ROOT / "deployments"
ACTIVE_PROFILE_FILE = DEPLOYMENTS / "active-profile.json"
