#!/usr/bin/env python3
"""Fabric task flow for the workspace: validate the JSON, then print how to import it.

Fabric has no REST API, no ``fab`` command and no item type for task flows: the canvas
is imported from a JSON file in the workspace list view, then each item is assigned to
its task by hand. This step keeps that file correct and always present, checks which
mapped items already exist in the workspace, and prints the import and assignment
steps. It never writes to Fabric, so it is idempotent by construction.

The notebook is the ingestion layer and writes the Lakehouse tables itself, so the
flow has no separate files-to-Delta "prepare data" task.

  python -m fabric.taskflow.deploy_taskflow            # validate + check workspace
  python -m fabric.taskflow.deploy_taskflow --offline  # validate only
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

TASKFLOW_FILE = Path(__file__).with_name("zava_service_desk_taskflow.json")

# Types the portal import accepts; "develop" and "distribute" are avoided on purpose.
KNOWN_TYPES = {"get data", "store data", "prepare data", "track data",
               "analyze and train data", "visualize", "general"}
TASK_KEYS = {"type", "id", "name", "description"}
EDGE_KEYS = {"source", "target"}
ROOT_KEYS = ["tasks", "edges", "name", "description"]

# task id suffix -> config paths of the Fabric items assigned to that task
ASSIGNMENTS: Dict[str, List[Tuple[str, str]]] = {
    "01": [("lakehouse", "setup_notebook")],
    "02": [("lakehouse", "name")],
    "03": [("eventhouse", "name"), ("eventhouse", "kql_database")],
    "04": [("ontology", "name")],
    "05": [("semantic_model", "name")],
    "06": [("semantic_model", "report")],
    "07": [("rti_dashboard", "name")],
    "08": [("activator", "name"), ("operations_agent", "name")],
    "09": [("data_agent", "name")],
    "10": [("app", "name")],
}


def load_taskflow(path: Path = TASKFLOW_FILE) -> Dict[str, Any]:
    raw = path.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        raise ValueError(f"{path.name}: UTF-8 BOM not allowed")
    return json.loads(raw.decode("utf-8"))


def validate(flow: Dict[str, Any], path: Path = TASKFLOW_FILE) -> List[str]:
    """Problems that would make the portal import fail or the canvas wrong (empty = ok)."""
    problems: List[str] = []
    text = path.read_text(encoding="utf-8")
    if not text.isascii():
        problems.append("file must be ASCII only (the import rejects some non-ASCII text)")
    if list(flow) != ROOT_KEYS:
        problems.append(f"root keys must be {ROOT_KEYS}, got {list(flow)}")
    tasks, edges = flow.get("tasks", []), flow.get("edges", [])
    ids = [t.get("id") for t in tasks]
    if len(ids) != len(set(ids)):
        problems.append("task ids must be unique")
    for t in tasks:
        if set(t) != TASK_KEYS:
            problems.append(f"task {t.get('id')}: keys must be {sorted(TASK_KEYS)}")
        if t.get("type") not in KNOWN_TYPES:
            problems.append(f"task {t.get('name')}: unknown type {t.get('type')!r}")
        if not str(t.get("name", "")).strip():
            problems.append(f"task {t.get('id')}: empty name")
    linked = set()
    for e in edges:
        if set(e) != EDGE_KEYS:
            problems.append(f"edge {e}: keys must be {sorted(EDGE_KEYS)}")
        for end in ("source", "target"):
            if e.get(end) not in ids:
                problems.append(f"edge {e}: {end} is not a task id")
            linked.add(e.get(end))
        if e.get("source") == e.get("target"):
            problems.append(f"edge {e}: self loop")
    for t in tasks:
        if t.get("id") not in linked:
            problems.append(f"task {t.get('name')}: not connected to any other task")
    return problems


def assigned_names(cfg: Dict[str, Any]) -> Dict[str, List[str]]:
    """task id suffix -> item display names, read from config.yaml."""
    return {suffix: [str(cfg.get(sec, {}).get(key, "")) for sec, key in paths]
            for suffix, paths in ASSIGNMENTS.items()}


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--offline", action="store_true", help="skip the workspace item check")
    args = p.parse_args()

    from fabric._shared.helpers import print_step
    total = 3
    print_step(1, total, f"Validating {TASKFLOW_FILE.name}")
    flow = load_taskflow()
    problems = validate(flow)
    if problems:
        for msg in problems:
            print(f"  [FAIL] {msg}")
        sys.exit(1)
    print(f"  [OK] {len(flow['tasks'])} tasks, {len(flow['edges'])} edges: {flow['name']}")

    print_step(2, total, "Checking the mapped items in the workspace")
    existing = None
    names: Dict[str, List[str]] = {}
    if args.offline:
        print("  [SKIP] --offline")
    else:
        try:
            from fabric._shared.helpers import deploy_context, list_items
            cfg, _state, api, ws, token = deploy_context(need_workspace=True)
            names = assigned_names(cfg)
            existing = {i.get("displayName") for i in list_items(token, api, ws)}
        except Exception as exc:  # offline, no config or no login: the file is still valid
            print(f"  [SKIP] workspace not reachable ({exc.__class__.__name__}: {exc})")

    print_step(3, total, "Import in the portal (no API exists for task flows)")
    print("  1. Open the workspace in list view, then 'Task flow' > 'Import a task flow'.")
    print(f"  2. Pick fabric/taskflow/{TASKFLOW_FILE.name}")
    print("  3. Assign each item to its task (paper-clip icon on the task card):")
    for t in flow["tasks"]:
        suffix = t["id"][-2:]
        items = names.get(suffix) or [t["name"].split(" - ", 1)[-1]]
        marks = []
        for n in items:
            if existing is None:
                marks.append(n)
            else:
                marks.append(f"{n} [{'OK' if n in existing else 'not found yet'}]")
        print(f"     - {t['name']:<55} <- {', '.join(marks)}")


if __name__ == "__main__":
    main()
