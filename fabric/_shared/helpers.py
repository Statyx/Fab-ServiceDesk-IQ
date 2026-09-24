#!/usr/bin/env python3
"""Shared helpers for the Zava Service Desk scripts.

Deployment profiles, config/state I/O, Azure CLI tokens and Kusto (Eventhouse) calls.
Reused from the proven sibling-repository pattern — keep them in step.

Config / state resolution
-------------------------
1. ``ZAVA_SD_PROFILE_DIR`` (absolute, or relative to the repo root) — a profile folder;
2. else ``deployments/active-profile.json`` → ``{"profile": "<name>"}`` →
   ``deployments/<name>/``;
3. else the root ``config.yaml`` / ``state.json``.

A selected profile must contain its own ``config.yaml``: there is **no silent fallback**
to the root config, so a typo can never deploy into the wrong tenant.
"""

import base64
import json
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests
import yaml

from fabric._shared.platform_env import AZ_NEEDS_SHELL
from fabric._shared.paths import (ACTIVE_PROFILE_FILE, CONFIG_FILE, ROOT,
                                  STATE_FILE)

PROFILE_ENV = "ZAVA_SD_PROFILE_DIR"

# Tenant / capacity / workspace identifiers are NEVER hard-coded in this repo.
# Resolution order for each of them:  environment variable → config.yaml → error.
CONFIG_ENV_OVERRIDES = {
    "tenant_id":       "ZAVA_SD_TENANT_ID",
    "capacity_id":     "ZAVA_SD_CAPACITY_ID",
    "workspace_name":  "ZAVA_SD_WORKSPACE_NAME",
    "az_subscription": "ZAVA_SD_AZ_SUBSCRIPTION",
    "fabric_api_base": "ZAVA_SD_FABRIC_API_BASE",
}
# Same idea for runtime item IDs: environment variable → state.json → error.
STATE_ENV_OVERRIDES = {
    "workspace_id":       "ZAVA_SD_WORKSPACE_ID",
    "lakehouse_id":       "ZAVA_SD_LAKEHOUSE_ID",
    "eventhouse_id":      "ZAVA_SD_EVENTHOUSE_ID",
    "kql_database_id":    "ZAVA_SD_KQL_DATABASE_ID",
    "kusto_query_uri":    "ZAVA_SD_KUSTO_QUERY_URI",
    "data_agent_id":      "ZAVA_SD_DATA_AGENT_ID",
    "data_agent_mcp_url": "ZAVA_SD_DATA_AGENT_MCP_URL",
}

FABRIC_SCOPE = "https://api.fabric.microsoft.com"

# "<YOUR_TENANT_ID>", "<filled by deploy_workspace>", … are templates, not values.
_PLACEHOLDER = re.compile(r"^\s*<.*>\s*$")


def is_placeholder(value: Any) -> bool:
    return value is None or value == "" or bool(_PLACEHOLDER.match(str(value)))


# ── Deployment profiles ──────────────────────────────────────────
def profile_dir() -> Optional[Path]:
    """The selected deployment profile folder, or ``None`` for the root config."""
    selected = os.environ.get(PROFILE_ENV)
    if selected is not None:
        if not selected.strip():
            raise RuntimeError(f"{PROFILE_ENV} is set but empty")
        path = Path(selected)
        if not path.is_absolute():
            path = ROOT / path
    elif ACTIVE_PROFILE_FILE.exists():
        pointer = json.loads(ACTIVE_PROFILE_FILE.read_text(encoding="utf-8"))
        name = pointer.get("profile") if isinstance(pointer, dict) else None
        if (not isinstance(name, str) or not name.strip()
                or name in (".", "..") or "/" in name or "\\" in name):
            raise RuntimeError("active-profile.json must select one named deployment profile")
        path = ACTIVE_PROFILE_FILE.parent / name
    else:
        return None
    path = path.resolve()
    if path == ROOT.resolve() or not (path / "config.yaml").is_file():
        raise RuntimeError(f"Selected deployment profile has no separate config.yaml: {path}")
    return path


def config_path() -> Path:
    profile = profile_dir()
    return profile / "config.yaml" if profile else CONFIG_FILE


def state_path() -> Path:
    profile = profile_dir()
    return profile / "state.json" if profile else STATE_FILE


# ── Config / state ───────────────────────────────────────────────
def load_config() -> Dict[str, Any]:
    path = config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Copy config.example.yaml to config.yaml (or select a "
            f"deployment profile) and fill in your own IDs — never commit them."
        )
    with open(path, "r", encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    if not isinstance(cfg, dict):
        raise RuntimeError("Deployment configuration must be a YAML mapping")
    for key, env_var in CONFIG_ENV_OVERRIDES.items():
        env_value = os.getenv(env_var)
        if env_value:
            cfg[key] = env_value
    return cfg


def require_config(cfg: Dict[str, Any], key: str) -> Any:
    """Return cfg[key], or raise an explicit error naming the env var to set."""
    value = cfg.get(key)
    if is_placeholder(value):
        env_var = CONFIG_ENV_OVERRIDES.get(key)
        hint = f" or export {env_var}" if env_var else ""
        raise RuntimeError(f"Missing '{key}': set it in {config_path().name}{hint}. "
                           f"This repo ships no real tenant/capacity identifiers.")
    return value


def load_state() -> Dict[str, Any]:
    """Load deployment state (IDs created so far), with env-var overrides."""
    state: Dict[str, Any] = {}
    path = state_path()
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
        if not isinstance(state, dict):
            raise RuntimeError("Deployment state must be a JSON object")
    for key, env_var in STATE_ENV_OVERRIDES.items():
        env_value = os.getenv(env_var)
        if env_value:
            state[key] = env_value
    return state


def require_state(state: Dict[str, Any], key: str) -> Any:
    value = state.get(key)
    if is_placeholder(value):
        env_var = STATE_ENV_OVERRIDES.get(key)
        hint = f" or export {env_var}" if env_var else ""
        raise RuntimeError(f"Missing '{key}' in {state_path().name}{hint}. "
                           f"Run the deploy step that produces it (see docs/ARCHITECTURE.md).")
    return value


def save_state(state: Dict[str, Any]) -> None:
    """Persist deployment state atomically."""
    path = state_path()
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, indent=2), encoding="utf-8")
    tmp.replace(path)


def configure_profile_cli(cfg: Dict[str, Any]) -> None:
    """Point the Azure CLI at the profile's isolated token cache, if one is configured."""
    configured = (cfg.get("deployment") or {}).get("azure_config_dir")
    if is_placeholder(configured):
        return
    cache = Path(os.path.expandvars(str(configured))).expanduser()
    if not cache.is_dir():
        raise RuntimeError(f"deployment.azure_config_dir does not exist: {cache}")
    active = os.environ.get("AZURE_CONFIG_DIR")
    if active and Path(active).expanduser().resolve() != cache.resolve():
        raise RuntimeError("AZURE_CONFIG_DIR differs from the selected profile's cache")
    os.environ["AZURE_CONFIG_DIR"] = str(cache.resolve())


# ── Tokens (Azure CLI) ───────────────────────────────────────────
# On Windows `az` is a .cmd shim, which CreateProcess cannot launch directly — hence
# AZ_NEEDS_SHELL. On POSIX, shell=True with an argv list would drop every argument.
def get_token(resource: str) -> str:
    result = subprocess.check_output(
        ["az", "account", "get-access-token", "--resource", resource,
         "--query", "accessToken", "-o", "tsv"],
        shell=AZ_NEEDS_SHELL,
    )
    return result.decode().strip()


def get_fabric_token() -> str:
    return get_token(FABRIC_SCOPE)


def get_kusto_token(query_service_uri: str) -> str:
    """Kusto token — the query URI audience first, then the generic ones."""
    for scope in (query_service_uri, "https://kusto.kusto.windows.net", FABRIC_SCOPE):
        try:
            token = get_token(scope)
            if token:
                return token
        except subprocess.CalledProcessError:
            continue
    raise RuntimeError("Could not acquire a Kusto token with any scope")


def fabric_headers(token: str) -> Dict[str, str]:
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


def get_storage_token() -> str:
    """OneLake (DFS) token — a different audience from the Fabric API one."""
    return get_token("https://storage.azure.com")


def check_account(cfg: Dict[str, Any]) -> str:
    """Refuse to deploy as anyone but ``deployment.expected_account``."""
    expected = (cfg.get("deployment") or {}).get("expected_account")
    actual = subprocess.check_output(
        ["az", "account", "show", "--query", "user.name", "-o", "tsv"],
        shell=AZ_NEEDS_SHELL).decode().strip()
    if not is_placeholder(expected) and actual.lower() != str(expected).lower():
        raise RuntimeError(f"Signed in as {actual}, profile expects {expected}. "
                           f"Run `az login` with the right account (AZURE_CONFIG_DIR).")
    return actual


# ── Fabric items ─────────────────────────────────────────────────
def poll_operation(token: str, api_base: str, operation_id: str,
                   max_wait: int = 600) -> Dict:
    """Poll a Fabric long-running operation until it succeeds (or raise)."""
    headers = fabric_headers(token)
    deadline = time.time() + max_wait
    while time.time() < deadline:
        time.sleep(5)
        resp = requests.get(f"{api_base}/operations/{operation_id}", headers=headers,
                            timeout=60)
        resp.raise_for_status()
        op = resp.json()
        status = op.get("status", "")
        if status == "Succeeded":
            return op
        if status in ("Failed", "Cancelled"):
            raise RuntimeError(f"Operation {status}: {json.dumps(op.get('error', {}))[:1500]}")
    raise TimeoutError(f"Operation {operation_id} did not complete in {max_wait}s")


def wait_lro(token: str, api_base: str, resp: requests.Response,
             what: str, max_wait: int = 600) -> Optional[Dict]:
    """Handle a 200/201/202 Fabric response; return the result body when there is one."""
    if resp.status_code in (200, 201):
        return resp.json() if resp.content else None
    if resp.status_code == 202:
        op_id = resp.headers.get("x-ms-operation-id")
        if not op_id:
            return None
        poll_operation(token, api_base, op_id, max_wait)
        result = requests.get(f"{api_base}/operations/{op_id}/result",
                              headers=fabric_headers(token), timeout=60)
        return result.json() if result.status_code == 200 and result.content else None
    raise RuntimeError(f"{what} failed ({resp.status_code}): {resp.text[:1500]}")


def list_items(token: str, api_base: str, workspace_id: str) -> List[Dict]:
    """All items of a workspace (no ``?type=`` filter — it 404s in some workspaces)."""
    headers = fabric_headers(token)
    url: Optional[str] = f"{api_base}/workspaces/{workspace_id}/items"
    items: List[Dict] = []
    while url:
        resp = requests.get(url, headers=headers, timeout=60)
        resp.raise_for_status()
        body = resp.json()
        items.extend(body.get("value", []))
        url = body.get("continuationUri")
    return items


def find_item(token: str, api_base: str, workspace_id: str,
              display_name: str, item_type: str) -> Dict:
    for item in list_items(token, api_base, workspace_id):
        if item.get("displayName") == display_name and item.get("type") == item_type:
            return item
    raise RuntimeError(f"{item_type} '{display_name}' not found")


def find_item_or_none(token: str, api_base: str, workspace_id: str,
                      display_name: str, item_type: str) -> Optional[Dict]:
    try:
        return find_item(token, api_base, workspace_id, display_name, item_type)
    except RuntimeError:
        return None


def create_fabric_item(token: str, api_base: str, workspace_id: str,
                       display_name: str, item_type: str, description: str = "",
                       definition: Optional[Dict] = None,
                       creation_payload: Optional[Dict] = None) -> Dict:
    """Create a Fabric item (waiting for the LRO) and return it."""
    body: Dict[str, Any] = {"displayName": display_name, "type": item_type}
    if description:
        body["description"] = description
    if definition:
        body["definition"] = definition
    if creation_payload:
        body["creationPayload"] = creation_payload
    resp = requests.post(f"{api_base}/workspaces/{workspace_id}/items",
                         headers=fabric_headers(token), json=body, timeout=120)
    result = wait_lro(token, api_base, resp, f"Create {item_type} '{display_name}'")
    if result and result.get("id"):
        return result
    return find_item(token, api_base, workspace_id, display_name, item_type)


def update_definition(token: str, api_base: str, workspace_id: str, item_id: str,
                      definition: Dict, what: str, update_metadata: bool = False) -> None:
    url = f"{api_base}/workspaces/{workspace_id}/items/{item_id}/updateDefinition"
    if update_metadata:
        url += "?updateMetadata=True"
    resp = requests.post(url, headers=fabric_headers(token),
                         json={"definition": definition}, timeout=120)
    wait_lro(token, api_base, resp, f"updateDefinition {what}")


def get_definition(token: str, api_base: str, workspace_id: str, item_id: str,
                   fmt: Optional[str] = None) -> Dict[str, str]:
    """Return ``{path: decoded payload}`` of an item definition."""
    url = f"{api_base}/workspaces/{workspace_id}/items/{item_id}/getDefinition"
    if fmt:
        url += f"?format={fmt}"
    resp = requests.post(url, headers=fabric_headers(token), timeout=120)
    result = wait_lro(token, api_base, resp, "getDefinition") or {}
    parts = (result.get("definition") or {}).get("parts", [])
    return {p["path"]: base64.b64decode(p["payload"]).decode("utf-8") for p in parts}


def b64encode_json(obj: Any) -> str:
    """Base64-encode a JSON object for a Fabric definition part."""
    return base64.b64encode(json.dumps(obj).encode("utf-8")).decode("ascii")


def b64encode_text(text: str) -> str:
    return base64.b64encode(text.encode("utf-8")).decode("ascii")


def part(path: str, payload: Any) -> Dict[str, str]:
    """One inline-base64 definition part; dicts/lists are JSON-encoded, text kept as-is."""
    data = (b64encode_json(payload) if isinstance(payload, (dict, list))
            else b64encode_text(payload))
    return {"path": path, "payload": data, "payloadType": "InlineBase64"}


def deploy_context(need_workspace: bool = True
                   ) -> Tuple[Dict[str, Any], Dict[str, Any], str, str, str]:
    """(cfg, state, api, workspace_id, fabric token) with the profile's CLI cache set."""
    cfg, state = load_config(), load_state()
    configure_profile_cli(cfg)
    api = require_config(cfg, "fabric_api_base")
    ws = require_state(state, "workspace_id") if need_workspace else ""
    return cfg, state, api, ws, get_fabric_token()


# ── Kusto (Eventhouse) ───────────────────────────────────────────
def kusto_mgmt(query_service_uri: str, kusto_token: str, db_name: str,
               command: str) -> Dict:
    """Execute a Kusto management command (``.create-merge table``, ``.ingest inline``…)."""
    headers = {"Authorization": f"Bearer {kusto_token}",
               "Content-Type": "application/json; charset=utf-8"}
    resp = None
    for attempt in range(4):
        try:
            resp = requests.post(f"{query_service_uri}/v1/rest/mgmt", headers=headers,
                                 json={"db": db_name, "csl": command}, timeout=180)
        except requests.exceptions.RequestException:
            if attempt == 3:
                raise
            time.sleep(15)
            continue
        if resp.status_code < 500 and resp.status_code != 429:
            break
        time.sleep(15)
    if resp.status_code >= 400:
        raise RuntimeError(f"Kusto mgmt failed: HTTP {resp.status_code}\n{resp.text[:1000]}")
    return resp.json()


def kusto_query(query_service_uri: str, kusto_token: str, db_name: str,
                query: str, max_attempts: int = 6) -> List[List[Any]]:
    """Run a KQL query and return the rows of the primary result (retrying 5xx/429)."""
    headers = {"Authorization": "Bearer " + kusto_token,
               "Content-Type": "application/json; charset=utf-8"}
    for attempt in range(max_attempts):
        resp = requests.post(f"{query_service_uri}/v1/rest/query", headers=headers,
                             json={"db": db_name, "csl": query}, timeout=120)
        if resp.status_code < 400:
            return resp.json()["Tables"][0]["Rows"]
        if (resp.status_code < 500 and resp.status_code != 429) or attempt == max_attempts - 1:
            raise RuntimeError(f"Kusto query failed: HTTP {resp.status_code}\n{resp.text[:1000]}")
        time.sleep(min(60, 5 * 2 ** attempt))
    return []


def kusto_streaming_ingest(query_service_uri: str, kusto_token: str, db_name: str,
                           table_name: str, csv_payload: str,
                           max_attempts: int = 6) -> None:
    """Ingest CSV via the streaming REST API, retrying 5xx/429.

    Enabling the streaming policy is not synchronous: a cold Eventhouse answers
    520 with an empty body for a few minutes, then accepts the identical payload.
    """
    headers = {"Authorization": f"Bearer {kusto_token}",
               "Content-Type": "text/csv; charset=utf-8"}
    url = f"{query_service_uri}/v1/rest/ingest/{db_name}/{table_name}?streamFormat=Csv"
    payload = csv_payload.encode("utf-8")
    for attempt in range(max_attempts):
        resp = requests.post(url, headers=headers, data=payload, timeout=120)
        if resp.status_code < 400:
            return
        retryable = resp.status_code >= 500 or resp.status_code == 429
        if not retryable or attempt == max_attempts - 1:
            raise RuntimeError(f"Kusto streaming ingest failed: HTTP {resp.status_code} on "
                               f"'{table_name}' after {attempt + 1} attempt(s).\n"
                               f"Response body: {resp.text[:1000] or '(empty)'}")
        wait = min(60, 10 * 2 ** attempt)
        print(f"   HTTP {resp.status_code} on {table_name}, retrying in {wait}s")
        time.sleep(wait)


def print_step(step: int, total: int, msg: str) -> None:
    print(f"\n[{step}/{total}] {msg}")
    print("-" * 60)
