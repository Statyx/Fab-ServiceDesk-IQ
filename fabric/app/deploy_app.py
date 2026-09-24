#!/usr/bin/env python3
"""Deploy ``App-Zava-Service-Desk``, the Rayfin console (phase 3), against the backend state.

The console is a React + Vite app in ``app-zava-service-desk/``, hosted by Rayfin inside
Fabric. It signs the user in with its own single-tenant Entra SPA (MSAL, no secret) and
reads, with the user's delegated token:

  SM_ServiceDesk_Analytics   every figure, as a DAX measure (Power BI executeQueries)
  ServiceDesk_Analyst        the assistant rail (Fabric Data Agent, OpenAI-compatible API)

The Foundry supervisor stays simulated: no Foundry resource, scope or variable is used.

Steps, all idempotent:

  1. preflight   tenant, workspace and backend item IDs match state (read-only)
  2. SPA         create or reuse the registration, consent for the deploying user only
  3. bindings    write the VITE_* identifiers to .env.{production,development}.local
                 (git-ignored; public identifiers, never a secret)
  4. rayfin up   item first (no static hosting), then the build and its hosting
  5. redirects   register the hosting origin + /blank.html on the SPA, verify the host

  python -m fabric.app.deploy_app                   # everything
  python -m fabric.app.deploy_app --check           # read-only preflight
  python -m fabric.app.deploy_app --configure-only  # SPA + bindings, then: npm run dev
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

import requests

from fabric._shared.helpers import (is_placeholder, list_items, load_config, load_state,
                                    print_step, require_config, require_state, save_state)
from fabric._shared.paths import ROOT
from fabric._shared.platform_env import AZ_NEEDS_SHELL, find_executable

APP_DIR = Path(ROOT) / "app-zava-service-desk"
PORTAL = "https://app.fabric.microsoft.com"
GRAPH = "https://graph.microsoft.com/v1.0"
FABRIC_RESOURCE = "https://api.fabric.microsoft.com"
REGISTRATION_NAME = "Zava Service Desk Console"
DEV_REDIRECT = "http://localhost:5173/blank.html"
RAYFIN_CLI = Path("node_modules") / "@microsoft" / "rayfin-cli" / "scripts" / "main"
RAYFIN_YML = APP_DIR / "rayfin" / "rayfin.yml"
HOSTED_URI_MARKER = ".fabricapps.net"

# Delegated scopes on the Power BI service (the same principal serves the Fabric API).
PERMISSIONS = {
    "https://analysis.windows.net/powerbi/api": (
        "Dataset.Read.All", "Item.Read.All", "DataAgent.Execute.All",
    ),
}

# Backend items the app binds to; each must exist in the target workspace.
BOUND_ITEMS = ("semantic_model_id", "data_agent_id")

# Files written from state. They hold tenant IDs: git-ignored.
GENERATED_FILES = (".env.production.local", ".env.development.local")


# ------------------------------------------------------------------ Azure CLI / Graph

def az_json(args: List[str]) -> Any:
    result = subprocess.run(["az", *args, "-o", "json"], shell=AZ_NEEDS_SHELL,
                            capture_output=True, text=True, encoding="utf-8", check=False)
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "Azure CLI command failed.")
    return json.loads(result.stdout)


def token_for(resource: str, tenant: str) -> str:
    result = az_json(["account", "get-access-token", "--tenant", tenant, "--resource", resource])
    if result.get("tenant", "").lower() != tenant.lower():
        raise RuntimeError("Azure CLI returned a token for a different tenant.")
    return result["accessToken"]


def graph_call(token: str, method: str, path: str, **kwargs) -> Any:
    response = requests.request(method, f"{GRAPH}/{path}",
                                headers={"Authorization": f"Bearer {token}"},
                                timeout=60, **kwargs)
    if not response.ok:
        raise RuntimeError(f"Microsoft Graph {method} {path}: {response.status_code} {response.text}")
    return response.json() if response.content else None


# ------------------------------------------------------------------ 1. preflight

def preflight(cfg: Dict[str, Any], state: Dict[str, Any]) -> tuple:
    tenant = require_config(cfg, "tenant_id")
    workspace = require_state(state, "workspace_id")
    for key in BOUND_ITEMS:
        require_state(state, key)
    account = az_json(["account", "show"])
    if account["tenantId"].lower() != str(tenant).lower():
        raise RuntimeError("Wrong Azure tenant: sign in to the configured tenant first.")
    if not (APP_DIR / RAYFIN_CLI).exists():
        raise RuntimeError("App dependencies missing: run npm ci in app-zava-service-desk first.")
    if not find_executable("node"):
        raise RuntimeError("Node.js is required to deploy the app.")
    token = token_for(FABRIC_RESOURCE, tenant)
    ids = {item["id"] for item in list_items(token, cfg["fabric_api_base"], workspace)}
    for key in BOUND_ITEMS:
        if state[key] not in ids:
            raise RuntimeError(f"{key} is not an item of the target workspace.")
    print(f"   tenant, workspace and {len(BOUND_ITEMS)} bound items verified")
    return tenant, workspace


# ------------------------------------------------------------------ 2. SPA registration

def discover_permissions(token: str) -> List[tuple]:
    permissions = []
    for uri, scopes in PERMISSIONS.items():
        matches = graph_call(token, "GET", "servicePrincipals", params={
            "$filter": f"servicePrincipalNames/any(n:n eq '{uri}')",
            "$select": "id,appId,oauth2PermissionScopes"})["value"]
        if len(matches) != 1:
            raise RuntimeError(f"Expected one API service principal for {uri}.")
        sp = matches[0]
        available = {p["value"]: p["id"] for p in sp["oauth2PermissionScopes"] if p["isEnabled"]}
        missing = set(scopes) - available.keys()
        if missing:
            raise RuntimeError(f"Delegated scopes unavailable for {uri}: {sorted(missing)}")
        permissions.append((sp, scopes, {
            "resourceAppId": sp["appId"],
            "resourceAccess": [{"id": available[s], "type": "Scope"} for s in scopes]}))
    return permissions


def merge_required_access(current: List[Dict[str, Any]],
                          wanted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Add the wanted scopes to a registration's requiredResourceAccess, keeping the rest."""
    merged = {p["resourceAppId"]: {"resourceAppId": p["resourceAppId"],
                                   "resourceAccess": list(p["resourceAccess"])} for p in current}
    for permission in wanted:
        entry = merged.setdefault(permission["resourceAppId"], {
            "resourceAppId": permission["resourceAppId"], "resourceAccess": []})
        for scope in permission["resourceAccess"]:
            if scope not in entry["resourceAccess"]:
                entry["resourceAccess"].append(scope)
    return list(merged.values())


def ensure_spa(token: str, cfg: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, Any]:
    permissions = discover_permissions(token)
    name = (cfg.get("app") or {}).get("registration_name") or REGISTRATION_NAME
    apps = graph_call(token, "GET", "applications", params={
        "$filter": "displayName eq '" + name.replace("'", "''") + "'",
        "$select": "id,appId,displayName,signInAudience,spa,requiredResourceAccess"})["value"]
    if state.get("application_client_id"):
        apps = [a for a in apps if a["appId"] == state["application_client_id"]]
        if not apps:
            raise RuntimeError("The recorded SPA registration is missing; refusing to replace it.")
    if len(apps) > 1:
        raise RuntimeError("Several SPA registrations match: record application_client_id.")
    if apps:
        app = apps[0]
        if app["signInAudience"] != "AzureADMyOrg":
            raise RuntimeError("The SPA must be single-tenant; refusing to modify it.")
    else:
        app = graph_call(token, "POST", "applications", json={
            "displayName": name, "signInAudience": "AzureADMyOrg",
            "spa": {"redirectUris": [DEV_REDIRECT]},
            "requiredResourceAccess": [p[2] for p in permissions]})
    # Saved at once so an interrupted consent or hosting step resumes on the same app.
    state.update(application_client_id=app["appId"], application_object_id=app["id"])
    save_state(state)
    graph_call(token, "PATCH", f"applications/{app['id']}", json={
        "requiredResourceAccess": merge_required_access(
            app.get("requiredResourceAccess", []), [p[2] for p in permissions])})
    principals = graph_call(token, "GET", "servicePrincipals", params={
        "$filter": f"appId eq '{app['appId']}'", "$select": "id"})["value"]
    principal = principals[0] if principals else graph_call(
        token, "POST", "servicePrincipals", json={"appId": app["appId"]})
    user = graph_call(token, "GET", "me", params={"$select": "id"})
    grants = graph_call(token, "GET", "oauth2PermissionGrants", params={
        "$filter": f"clientId eq '{principal['id']}'"})["value"]
    for resource, scopes, _ in permissions:
        covering = [g for g in grants if g["resourceId"] == resource["id"]
                    and (g["consentType"] == "AllPrincipals" or g.get("principalId") == user["id"])]
        granted = set().union(*(set(g["scope"].split()) for g in covering))
        if set(scopes) <= granted:
            continue
        own = next((g for g in covering if g["consentType"] == "Principal"), None)
        scope = " ".join(sorted(set(scopes) | (set(own["scope"].split()) if own else set())))
        if own:
            graph_call(token, "PATCH", f"oauth2PermissionGrants/{own['id']}", json={"scope": scope})
        else:
            graph_call(token, "POST", "oauth2PermissionGrants", json={
                "clientId": principal["id"], "consentType": "Principal",
                "principalId": user["id"], "resourceId": resource["id"], "scope": scope})
    print("   SPA registration ready; delegated access consented for the deploying user only")
    return app


# ------------------------------------------------------------------ 3. bindings

def app_bindings(cfg: Dict[str, Any], state: Dict[str, Any]) -> Dict[str, str]:
    return {
        "VITE_ENTRA_CLIENT_ID": require_state(state, "application_client_id"),
        "VITE_ENTRA_TENANT_ID": require_config(cfg, "tenant_id"),
        "VITE_SEMANTIC_MODEL_ID": require_state(state, "semantic_model_id"),
        "VITE_ZAVA_WORKSPACE_ID": require_state(state, "workspace_id"),
        "VITE_ZAVA_DATA_AGENT_ID": require_state(state, "data_agent_id"),
    }


def write_bindings(bindings: Dict[str, str], app_root: Path = None) -> None:
    """Write the bindings to the mode-specific env files, which ``rayfin env`` never touches.

    ``.env.local`` belongs to Rayfin (it rewrites it on every ``rayfin up``): the bindings
    are removed from it so a stale copy there cannot shadow the mode files."""
    root = app_root or APP_DIR
    managed = ("VITE_FABRIC_", "VITE_RAYFIN_")  # Rayfin's own values, in .env.local only
    for name in GENERATED_FILES:
        path = root / name
        lines = path.read_text(encoding="utf-8-sig").splitlines() if path.exists() else []
        lines = [l for l in lines if l.split("=", 1)[0].strip() not in bindings
                 and not l.startswith(managed)]
        path.write_text("\n".join([*lines, *(f"{k}={v}" for k, v in bindings.items())]) + "\n",
                        encoding="utf-8")
    local = root / ".env.local"
    if local.exists():
        lines = [l for l in local.read_text(encoding="utf-8-sig").splitlines()
                 if l.split("=", 1)[0].strip() not in bindings]
        local.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ------------------------------------------------------------------ 4. rayfin up

def child_env(environ: Dict[str, str] = None) -> Dict[str, str]:
    """The environment with ``PATH`` de-duplicated (order kept).

    ``bootstrap()`` prepends the registry ``Path`` to the inherited one, so every entry
    appears twice. The build nests npm and npx, and each level prepends one
    ``node_modules\\.bin`` per parent folder. Under this deep repository path the
    result grows past what cmd.exe reads, and the build stops finding ``npx``."""
    env = dict(os.environ if environ is None else environ)
    key = next((k for k in env if k.upper() == "PATH"), "PATH")
    seen, parts = set(), []
    for part in env.get(key, "").split(os.pathsep):
        norm = os.path.normcase(part.rstrip("\\/"))
        if part and norm not in seen:
            seen.add(norm)
            parts.append(part)
    env[key] = os.pathsep.join(parts)
    return env


def rayfin_env(token: str, tenant: str, workspace: str,
               environ: Dict[str, str] = None) -> Dict[str, str]:
    """The Rayfin CLI environment: the Azure CLI token instead of a cached browser login,
    and no inherited VITE_/RAYFIN_ value that could override the bindings."""
    env = {k: v for k, v in child_env(environ).items()
           if not k.startswith(("VITE_", "RAYFIN_", "AZURE_TOKEN_CREDENTIALS"))}
    env.update(RAYFIN_TOKEN=token, RAYFIN_TENANT_ID=tenant, RAYFIN_WORKSPACE_ID=workspace,
               NO_COLOR="1")
    return env


def rayfin_up_args(tenant: str, workspace: str, static_hosting: bool) -> List[str]:
    """``rayfin up`` into the demo workspace, by id: no display-name lookup.

    The first pass (no static hosting) creates or updates the item, so a build failure
    never hides a successful item update; the second builds and publishes ``dist/``."""
    args = ["up", "--tenant", tenant, "--workspace-id", workspace, "--yes"]
    return args if static_hosting else args + ["--exclude-services", "staticHosting"]


def rayfin(args: List[str], env: Dict[str, str]) -> None:
    print("   $ rayfin", " ".join(args))
    # The JS entry point directly: no shell, no cmd length limit, no cached Rayfin login.
    subprocess.run([find_executable("node"), str(APP_DIR / RAYFIN_CLI), *args],
                   cwd=APP_DIR, env=env, check=True)


def strip_hosted_redirect_uris(text: str) -> str:
    """Remove the tenant-specific hosting URL(s) the CLI appends to ``allowedRedirectUris``.
    Each deploy registers it again on the service side, so the committed rayfin.yml stays
    tenant-neutral."""
    lines = text.splitlines(keepends=True)
    return "".join(l for l in lines
                   if not (l.lstrip().startswith("- ") and HOSTED_URI_MARKER in l))


def target_deployment(tenant: str, workspace: str, path: Path = None) -> Dict[str, Any]:
    """The active Rayfin deployment record, refused unless it is this tenant and workspace."""
    path = path or APP_DIR / "rayfin" / ".deployments.json"
    registry = json.loads(path.read_text(encoding="utf-8-sig"))
    record = registry.get("deployments", {}).get(registry.get("active"), {})
    if (str(record.get("fabricTenantId", "")).lower() != str(tenant).lower()
            or record.get("fabricWorkspaceId") != workspace):
        raise RuntimeError("Rayfin's active deployment is not the configured tenant/workspace.")
    return record


def app_portal_url(cfg: Dict[str, Any], state: Dict[str, Any]) -> str:
    """The app item in the Fabric portal. Empty until the item exists."""
    item = state.get("app_item_id")
    if not item:
        return ""
    url = f"{PORTAL}/groups/{require_state(state, 'workspace_id')}/appbackends/{item}"
    tenant = cfg.get("tenant_id")
    return url if is_placeholder(tenant) else f"{url}?ctid={tenant}"


# ------------------------------------------------------------------ 5. redirects + host

def hosting_origin(hosting_url: str) -> str:
    origin = hosting_url.rstrip("/")
    parsed = urlparse(origin)
    if (parsed.scheme != "https" or not parsed.hostname
            or not parsed.hostname.endswith(".webapp.fabricapps.net")):
        raise RuntimeError("Unexpected hosting origin; refusing to register it as a redirect.")
    return origin


def redirect_uris(current: List[str], origin: Optional[str]) -> List[str]:
    uris = set(current) | {DEV_REDIRECT}
    if origin:
        uris |= {origin, f"{origin}/blank.html"}
    return sorted(uris)


def update_redirects(token: str, app: Dict[str, Any], origin: str) -> None:
    current = graph_call(token, "GET", f"applications/{app['id']}", params={"$select": "spa"})
    uris = redirect_uris(current.get("spa", {}).get("redirectUris", []), origin)
    graph_call(token, "PATCH", f"applications/{app['id']}", json={"spa": {"redirectUris": uris}})


def verify_host(origin: str) -> None:
    for route in ("/", "/blank.html", "/diagnostic"):
        response = requests.get(f"{origin}{route}", timeout=90)
        response.raise_for_status()
        if "<html" not in response.text.lower():
            raise RuntimeError(f"{route} is not the deployed application HTML.")


# ------------------------------------------------------------------ main

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="read-only preflight")
    ap.add_argument("--configure-only", action="store_true",
                    help="SPA registration + env bindings only (for npm run dev)")
    args = ap.parse_args()
    cfg, state = load_config(), load_state()
    total = 2 if args.configure_only else 5

    print_step(1, total, "Preflight: tenant, workspace and bound items")
    tenant, workspace = preflight(cfg, state)
    if args.check:
        print("   preflight passed; nothing deployed")
        return 0

    print_step(2, total, "SPA registration and bindings")
    graph_token = token_for("https://graph.microsoft.com", tenant)
    app = ensure_spa(graph_token, cfg, state)
    write_bindings(app_bindings(cfg, state))
    print(f"   bindings written to {', '.join(GENERATED_FILES)}")
    if args.configure_only:
        update_redirects(graph_token, app, None)
        return 0

    print_step(3, total, "Create or update the Rayfin item")
    env = rayfin_env(token_for(FABRIC_RESOURCE, tenant), tenant, workspace)
    try:
        rayfin(rayfin_up_args(tenant, workspace, static_hosting=False), env)
        record = target_deployment(tenant, workspace)
        state["app_item_id"] = record["fabricItemId"]
        state["app_url"] = app_portal_url(cfg, state)
        save_state(state)

        print_step(4, total, "Build and publish the static app")
        rayfin(rayfin_up_args(tenant, workspace, static_hosting=True), env)
    finally:
        if RAYFIN_YML.exists():
            RAYFIN_YML.write_text(strip_hosted_redirect_uris(
                RAYFIN_YML.read_text(encoding="utf-8")), encoding="utf-8")

    print_step(5, total, "Register the hosting redirect and verify the host")
    origin = hosting_origin(target_deployment(tenant, workspace)["hostingUrl"])
    update_redirects(graph_token, app, origin)
    verify_host(origin)
    state["app_hosting_url"] = origin
    save_state(state)
    print("   app_item_id, app_url and app_hosting_url saved to state")
    return 0


if __name__ == "__main__":
    sys.exit(main())
