"""Offline checks for the phase 3 Rayfin console (``fabric/app`` + ``app-zava-service-desk``).

The app queries SM_ServiceDesk_Analytics in DAX from TypeScript. These tests keep that
TypeScript honest against the Python model definition, keep the deploy script's pure
parts correct, and keep every tenant-specific file it writes out of the public repo.
"""
import json
import re
import subprocess
import uuid

import pytest

import deploy_all
from fabric._shared.paths import ROOT
from fabric.app import deploy_app as app
from fabric.data.schema import LAKEHOUSE
from fabric.powerbi.deploy_semantic_model import MEASURES, TABLES

WS, MODEL, AGENT, TENANT, CLIENT = (str(uuid.UUID(int=i)) for i in range(1, 6))
SRC = app.APP_DIR / "src"
QUERIES_TS = (SRC / "data" / "queries.ts").read_text(encoding="utf-8")
MEASURE_NAMES = {m[0] for ms in MEASURES.values() for m in ms}
COLUMN_NAMES = {(t, c) for t in TABLES for c, _ in LAKEHOUSE[t]}


def _dax_queries():
    return dict(re.findall(r"export const (\w+_DAX) = `(.*?)`;", QUERIES_TS, re.S))


def test_queries_ts_declares_the_dax_queries():
    assert {"COVER_DAX", "PORTFOLIO_DAX", "XLA_WEEK_DAX", "AGENTS_DAX"} <= set(_dax_queries())


@pytest.mark.parametrize("name", sorted(_dax_queries()))
def test_dax_queries_reference_real_columns_and_measures(name):
    dax = _dax_queries()[name]
    for table, column in re.findall(r"\b(\w+)\[([^\]]+)\]", dax):
        assert (table, column) in COLUMN_NAMES, f"{name}: {table}[{column}]"
    # A bare [Name] is a measure, unless it is a column alias defined in the query.
    aliases = set(re.findall(r'"([^"]+)"\s*,', dax))
    for ref in re.findall(r"(?<![\w\]])\[([^\]]+)\]", dax):
        assert ref in MEASURE_NAMES or ref in aliases, f"{name}: [{ref}]"


def test_every_vite_binding_is_read_by_the_app():
    used = set()
    for path in SRC.rglob("*.ts*"):
        used |= set(re.findall(r"import\.meta\.env\.(VITE_\w+)", path.read_text(encoding="utf-8")))
    bindings = app.app_bindings({"tenant_id": TENANT}, {
        "application_client_id": CLIENT, "semantic_model_id": MODEL,
        "workspace_id": WS, "data_agent_id": AGENT})
    assert set(bindings) <= used
    assert bindings["VITE_ENTRA_TENANT_ID"] == TENANT and bindings["VITE_ZAVA_DATA_AGENT_ID"] == AGENT


def test_foundry_stays_simulated():
    assert not any("FOUNDRY" in k for k in app.app_bindings({"tenant_id": TENANT}, {
        "application_client_id": CLIENT, "semantic_model_id": MODEL,
        "workspace_id": WS, "data_agent_id": AGENT}))
    assert list(app.PERMISSIONS) == ["https://analysis.windows.net/powerbi/api"]
    assert "DataAgent.Execute.All" in app.PERMISSIONS["https://analysis.windows.net/powerbi/api"]


def test_write_bindings_keeps_other_lines_and_cleans_env_local(tmp_path):
    (tmp_path / ".env.production.local").write_text(
        "KEEP=1\nVITE_SEMANTIC_MODEL_ID=old\nVITE_FABRIC_ITEM_ID=stale\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text("VITE_RAYFIN_API_URL=x\nVITE_SEMANTIC_MODEL_ID=old\n",
                                         encoding="utf-8")
    app.write_bindings({"VITE_SEMANTIC_MODEL_ID": MODEL}, tmp_path)
    for name in app.GENERATED_FILES:
        text = (tmp_path / name).read_text(encoding="utf-8")
        assert f"VITE_SEMANTIC_MODEL_ID={MODEL}\n" in text and "old" not in text
        assert "VITE_FABRIC_" not in text
    assert "KEEP=1" in (tmp_path / ".env.production.local").read_text(encoding="utf-8")
    assert (tmp_path / ".env.local").read_text(encoding="utf-8") == "VITE_RAYFIN_API_URL=x\n"


def test_merge_required_access_adds_without_dropping():
    current = [{"resourceAppId": "a", "resourceAccess": [{"id": "1", "type": "Scope"}]}]
    wanted = [{"resourceAppId": "a", "resourceAccess": [{"id": "1", "type": "Scope"},
                                                         {"id": "2", "type": "Scope"}]},
              {"resourceAppId": "b", "resourceAccess": [{"id": "3", "type": "Scope"}]}]
    merged = {p["resourceAppId"]: [s["id"] for s in p["resourceAccess"]]
              for p in app.merge_required_access(current, wanted)}
    assert merged == {"a": ["1", "2"], "b": ["3"]}
    assert current[0]["resourceAccess"] == [{"id": "1", "type": "Scope"}]


def test_rayfin_up_targets_the_workspace_by_id_in_two_passes():
    item = app.rayfin_up_args(TENANT, WS, static_hosting=False)
    assert item == ["up", "--tenant", TENANT, "--workspace-id", WS, "--yes",
                    "--exclude-services", "staticHosting"]
    assert app.rayfin_up_args(TENANT, WS, static_hosting=True) == item[:-2]


def test_rayfin_env_uses_the_cli_token_and_drops_inherited_overrides():
    env = app.rayfin_env("tok", TENANT, WS, {"Path": "/a", "VITE_SEMANTIC_MODEL_ID": "x",
                                              "RAYFIN_TOKEN": "old", "X": "1"})
    assert env["RAYFIN_TOKEN"] == "tok" and env["RAYFIN_WORKSPACE_ID"] == WS
    assert "VITE_SEMANTIC_MODEL_ID" not in env and env["X"] == "1"


def test_child_env_dedupes_path_keeping_order():
    sep = app.os.pathsep
    env = app.child_env({"Path": sep.join(["/a", "/b", "/a/", "", "/c", "/b"]), "X": "1"})
    assert env["Path"] == sep.join(["/a", "/b", "/c"])
    assert env["X"] == "1" and "PATH" not in env


def test_target_deployment_refuses_another_workspace(tmp_path):
    path = tmp_path / ".deployments.json"
    record = {"fabricItemId": "i", "fabricTenantId": TENANT, "fabricWorkspaceId": WS,
              "hostingUrl": "https://x.webapp.fabricapps.net"}
    path.write_text(json.dumps({"deployments": {"k": record}, "active": "k"}), encoding="utf-8")
    assert app.target_deployment(TENANT.upper(), WS, path) == record
    with pytest.raises(RuntimeError):
        app.target_deployment(TENANT, MODEL, path)


def test_hosting_origin_and_redirects():
    origin = app.hosting_origin("https://live-birch-0000-swedencentral.webapp.fabricapps.net/")
    assert origin.endswith(".webapp.fabricapps.net")
    with pytest.raises(RuntimeError):
        app.hosting_origin("http://evil.example.net")
    uris = app.redirect_uris(["https://old.example"], origin)
    assert uris == sorted({"https://old.example", app.DEV_REDIRECT, origin, f"{origin}/blank.html"})
    assert app.redirect_uris([], None) == [app.DEV_REDIRECT]


def test_app_portal_url_needs_the_item_and_carries_the_tenant():
    state = {"workspace_id": WS}
    assert app.app_portal_url({}, state) == ""
    state["app_item_id"] = MODEL
    assert app.app_portal_url({"tenant_id": "<tenant-guid>"}, state) == \
        f"{app.PORTAL}/groups/{WS}/appbackends/{MODEL}"
    assert app.app_portal_url({"tenant_id": WS}, state).endswith(f"/appbackends/{MODEL}?ctid={WS}")


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


def test_state_template_lists_the_app_keys():
    example = (ROOT / "state.example.json").read_text(encoding="utf-8")
    for key in ("application_client_id", "application_object_id", "app_item_id",
                "app_url", "app_hosting_url", *app.BOUND_ITEMS):
        assert f'"{key}"' in example, key


def test_app_is_the_last_deploy_step():
    assert deploy_all.STEP_NAMES[-1] == "app"


@pytest.mark.parametrize("rel", app.GENERATED_FILES + (".env.local",
                                                         "rayfin/.project.json",
                                                         "rayfin/.deployments.json",
                                                         "rayfin/.env"))
def test_tenant_specific_app_files_are_git_ignored(rel):
    path = f"app-zava-service-desk/{rel}"
    res = subprocess.run(["git", "check-ignore", "-q", path], cwd=ROOT)
    assert res.returncode == 0, f"{path} is not git-ignored"


def test_frozen_answers_carry_no_identifiers():
    path = SRC / "data" / "frozen-answers.generated.json"
    text = path.read_text(encoding="utf-8")
    assert not re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", text, re.I)
    assert "onmicrosoft" not in text and HOSTED not in text


HOSTED = app.HOSTED_URI_MARKER
