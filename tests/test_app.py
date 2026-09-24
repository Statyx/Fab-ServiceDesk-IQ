"""Offline checks for the phase 3 Rayfin console (``fabric/app`` + ``app-zava-service-desk``).

The app queries SM_ServiceDesk_Analytics in DAX from TypeScript. These tests keep that
TypeScript honest against the Python model definition, and keep every tenant-specific
file the deploy script writes out of the public repo.
"""
import re
import subprocess
import uuid

import pytest

import deploy_all
from fabric._shared.paths import ROOT
from fabric.app import deploy_app as app
from fabric.data.schema import LAKEHOUSE
from fabric.data_agent import deploy_data_agent as da
from fabric.powerbi.deploy_semantic_model import MEASURES, TABLES

WS, MODEL, REPORT = (str(uuid.UUID(int=i)) for i in range(1, 4))
QUERIES_TS = (app.APP_DIR / "src" / "servicedesk" / "queries.ts").read_text(encoding="utf-8")
MEASURE_NAMES = {m[0] for ms in MEASURES.values() for m in ms}
COLUMN_NAMES = {(t, c) for t in TABLES for c, _ in LAKEHOUSE[t]}


def _dax_queries():
    return dict(re.findall(r"export const (\w+_QUERY) = `(.*?)`;", QUERIES_TS, re.S))


def test_queries_ts_declares_every_dax_query():
    assert set(_dax_queries()) == {"KPI_QUERY", "XLA_QUERY", "TREND_QUERY",
                                   "AGENTS_QUERY", "SITES_QUERY"}


@pytest.mark.parametrize("name", sorted(_dax_queries()))
def test_dax_queries_reference_real_columns_and_measures(name):
    dax = _dax_queries()[name]
    for table, column in re.findall(r"\b(\w+)\[([^\]]+)\]", dax):
        assert (table, column) in COLUMN_NAMES, f"{name}: {table}[{column}]"
    # A bare [Name] is a measure, unless it is a column alias defined in the query.
    aliases = set(re.findall(r'"([^"]+)"\s*,', dax))
    for ref in re.findall(r"(?<![\w\]])\[([^\]]+)\]", dax):
        assert ref in MEASURE_NAMES or ref in aliases, f"{name}: [{ref}]"


def test_connection_name_matches_the_typescript():
    assert f'CONNECTION = "{app.CONNECTION}"' in QUERIES_TS


def test_fabric_yaml_points_at_the_semantic_model():
    text = app.fabric_yaml({"workspace_id": WS, "semantic_model_id": MODEL})
    assert "semanticModels:" in text
    assert f"      {app.CONNECTION}:\n        workspaceId: {WS}\n        itemId: {MODEL}\n" in text


def test_portal_links_skip_missing_items_and_end_with_the_workspace():
    links = app.portal_links({"workspace_id": WS, "report_id": REPORT})
    assert [link["key"] for link in links] == ["report", "workspace"]
    assert links[0]["url"] == f"{app.PORTAL}/groups/{WS}/reports/{REPORT}"
    assert links[-1]["url"] == f"{app.PORTAL}/groups/{WS}/list"


def test_portal_items_read_real_state_keys():
    example = (ROOT / "state.example.json").read_text(encoding="utf-8")
    for _, _, _, state_key, _ in app.PORTAL_ITEMS:
        assert f'"{state_key}"' in example, state_key


def test_demo_questions_are_the_data_agent_fewshots():
    questions = [q["question"] for q in app.demo_questions()]
    expected = [q for shots in (da.GQL_FEWSHOTS, da.DAX_FEWSHOTS, da.KQL_FEWSHOTS)
                for q, _ in shots]
    assert questions == expected
    assert len({q["source"] for q in app.demo_questions()}) == 3


def test_rayfin_up_targets_the_workspace_by_id():
    state = {"workspace_id": WS}
    cmd = app.rayfin_up_command({"tenant_id": "<tenant-guid>"}, state)
    assert cmd[1:] == ["rayfin", "up", "--workspace-id", WS, "--yes",
                       "--exclude-services", "staticHosting"]
    cmd = app.rayfin_up_command({"tenant_id": MODEL}, state, dry_run=True)
    assert cmd[-3:] == ["-t", MODEL, "--dry-run"]
    assert app.STATIC_DEPLOY[1:] == ["rayfin", "up", "staticapp", "deploy"]


def test_app_portal_url_needs_the_item_and_carries_the_tenant():
    state = {"workspace_id": WS}
    assert app.app_portal_url({}, state) == ""
    state["app_item_id"] = MODEL
    assert app.app_portal_url({"tenant_id": "<tenant-guid>"}, state) == \
        f"{app.PORTAL}/groups/{WS}/appbackends/{MODEL}"
    assert app.app_portal_url({"tenant_id": WS}, state).endswith(f"/appbackends/{MODEL}?ctid={WS}")


def test_child_env_dedupes_path_keeping_order():
    sep = app.os.pathsep
    env = app.child_env({"Path": sep.join(["/a", "/b", "/a/", "", "/c", "/b"]), "X": "1"})
    assert env["Path"] == sep.join(["/a", "/b", "/c"])
    assert env["X"] == "1" and "PATH" not in env


def test_hosting_url_is_stripped_from_rayfin_yml():
    yml = ("services:\n  auth:\n    allowedRedirectUris:\n      - http://localhost:5173\n"
           "      - https://live-birch-0000-swedencentral.webapp.fabricapps.net\n"
           "  staticHosting:\n    enabled: true\n")
    out = app.strip_hosted_redirect_uris(yml)
    assert "fabricapps.net" not in out
    assert "      - http://localhost:5173\n" in out and "  staticHosting:\n" in out
    assert app.strip_hosted_redirect_uris(out) == out


def test_committed_rayfin_yml_is_tenant_neutral():
    text = app.RAYFIN_YML.read_text(encoding="utf-8")
    assert app.HOSTED_URI_MARKER not in text
    assert text.startswith("id: App-Zava-Service-Desk\n")


def test_deployment_record_is_found_at_any_depth(tmp_path, monkeypatch):
    (tmp_path / "rayfin").mkdir()
    (tmp_path / "rayfin" / ".deployments.json").write_text(
        '{"deployments": [{"env": "prod", "item": {"fabricItemId": "x", "hostingUrl": "u"}}]}',
        encoding="utf-8")
    monkeypatch.setattr(app, "APP_DIR", tmp_path)
    assert app.deployment_record() == {"fabricItemId": "x", "hostingUrl": "u"}


def test_app_is_the_last_deploy_step():
    assert deploy_all.STEP_NAMES[-1] == "app"


@pytest.mark.parametrize("rel", app.GENERATED_FILES + ("rayfin/.project.json",
                                                         "rayfin/.deployments.json",
                                                         "rayfin/.env"))
def test_tenant_specific_app_files_are_git_ignored(rel):
    path = f"app-zava-service-desk/{rel}"
    res = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    assert res.returncode == 0, f"{path} is not git-ignored"


def test_app_sources_are_not_ignored_by_the_python_lib_rule():
    res = subprocess.run(["git", "check-ignore", "-q",
                          "app-zava-service-desk/src/lib/fabric-client.ts"], cwd=ROOT)
    assert res.returncode == 1
