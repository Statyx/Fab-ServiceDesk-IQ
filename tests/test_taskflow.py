"""The Fabric task flow file: valid for the portal import and in step with the deployment."""
import json
from pathlib import Path

import yaml

import deploy_all
from fabric.taskflow import deploy_taskflow as tf

ROOT = Path(__file__).resolve().parents[1]
FLOW = tf.load_taskflow()
CFG = yaml.safe_load((ROOT / "config.example.yaml").read_text(encoding="utf-8"))


def test_taskflow_validates():
    assert tf.validate(FLOW) == []


def test_taskflow_file_is_ascii_without_bom():
    raw = tf.TASKFLOW_FILE.read_bytes()
    assert not raw.startswith(b"\xef\xbb\xbf")
    assert raw.decode("utf-8").isascii()


def test_taskflow_schema_is_exact():
    assert list(FLOW) == tf.ROOT_KEYS
    assert all(set(t) == tf.TASK_KEYS for t in FLOW["tasks"])
    assert all(set(e) == tf.EDGE_KEYS for e in FLOW["edges"])
    assert all(t["type"] in tf.KNOWN_TYPES for t in FLOW["tasks"])


def test_validate_catches_broken_flows(tmp_path):
    bad = json.loads(json.dumps(FLOW))
    bad["tasks"].append({"type": "develop", "id": bad["tasks"][0]["id"],
                         "name": "Orphan", "description": "x"})
    bad["edges"].append({"source": "missing", "target": bad["tasks"][0]["id"]})
    path = tmp_path / "flow.json"
    path.write_text(json.dumps(bad), encoding="utf-8")
    problems = " | ".join(tf.validate(bad, path))
    assert "unique" in problems
    assert "unknown type" in problems
    assert "source is not a task id" in problems


def test_every_task_is_connected():
    linked = {e["source"] for e in FLOW["edges"]} | {e["target"] for e in FLOW["edges"]}
    assert {t["id"] for t in FLOW["tasks"]} == linked


def test_notebook_is_the_ingestion_layer():
    types = [t["type"] for t in FLOW["tasks"]]
    assert "prepare data" not in types
    first = [t for t in FLOW["tasks"] if t["type"] == "get data"]
    assert len(first) == 1 and CFG["lakehouse"]["setup_notebook"] in first[0]["name"]


def test_every_deployed_item_is_mapped_to_a_task():
    text = json.dumps(FLOW)
    names = tf.assigned_names(CFG)
    assert set(names) == {t["id"][-2:] for t in FLOW["tasks"]}
    for items in names.values():
        for name in items:
            assert name and name in text, name


def test_staged_plane_is_not_in_the_flow():
    for t in FLOW["tasks"]:
        for word in ("Foundry", "Work IQ", "Web IQ"):
            assert word not in t["name"]


def test_taskflow_step_runs_before_the_app():
    names = deploy_all.STEP_NAMES
    assert "taskflow" in names
    assert names.index("taskflow") == len(names) - 2
    assert dict((s[0], s[1]) for s in deploy_all.STEPS)["taskflow"] == "fabric.taskflow.deploy_taskflow"
