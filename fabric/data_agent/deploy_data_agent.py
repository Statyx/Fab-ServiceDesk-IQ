#!/usr/bin/env python3
"""Deploy the ``ServiceDesk_Analyst`` Fabric Data Agent: the grounding layer of the demo.

Three sources, one routing rule:

  1. ONT_ServiceDesk (Ontology, GQL)          WHO / WHICH: user -> site -> major incident,
                                              contract -> XLA clause, agent -> MCP tool.
  2. SM_ServiceDesk_Analytics (DAX)           HOW MUCH: zero-touch, XLA breaches and
                                              credits (cap applied), CSAT, time lost.
  3. KQL_ServiceDesk (Eventhouse, KQL)        RIGHT NOW: VPN latency, experience score,
                                              AI agent errors, gateway throttling.

Every few-shot is RUN against its source before the upload (GQL executeQuery, DAX
executeQueries, KQL), and the deploy stops if one fails or returns no row, so the agent
never learns from a query that does not work on this tenant.

The agent is published (a draft-only agent is invisible in the portal, over MCP and to
Foundry). The MCP endpoint is saved in state as ``data_agent_mcp_url``; test it with
``python -m fabric.data_agent.mcp_client``.

  python -m fabric.data_agent.deploy_data_agent              # verify + create/update + publish
  python -m fabric.data_agent.deploy_data_agent --skip-verify
  python -m fabric.data_agent.deploy_data_agent --delete
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import argparse
import base64
import json
import time
import uuid
from typing import Dict, List, Tuple

import requests

from fabric._shared.helpers import (b64encode_json, deploy_context, fabric_headers,
                                    find_item_or_none, get_kusto_token, get_token,
                                    kusto_query, print_step, require_state, save_state,
                                    wait_lro)
from fabric.data.generate_data import load_world
from fabric.data.schema import EVENTHOUSE, LAKEHOUSE
from fabric.ontology.deploy_ontology import ENTITIES, RELATIONSHIPS
from fabric.powerbi.deploy_semantic_model import MEASURES, TABLES

SCH = "https://developer.microsoft.com/json-schemas/fabric/item/dataAgent/definition"
PBI_API = "https://api.powerbi.com/v1.0/myorg"
PBI_RESOURCE = "https://analysis.windows.net/powerbi/api"
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/Statyx/Fab-ServiceDesk-IQ/data-agent")

AGENT_DESC = ("Zava Service Desk analyst: impact and contract traversals (ontology, GQL), "
              "zero-touch / XLA / experience figures (semantic model, DAX) and live "
              "telemetry (Eventhouse, KQL).")


def _entity_lines() -> str:
    return "\n".join(f"- {name} ({', '.join(c for c, _ in props)})"
                     for name, _, _, props in ENTITIES)


def _relationship_lines() -> str:
    return "\n".join(f"- {src} -[{rel}]-> {dst}" for rel, src, dst, *_ in RELATIONSHIPS)


def _measure_lines() -> str:
    return "\n".join(f"- {table}: " + ", ".join(f"[{m[0]}]" for m in measures)
                     for table, measures in MEASURES.items())


def _customer_lines() -> str:
    return "; ".join(f"{c['name'].split()[0]} = \"{c['name']}\" ({c['id']})"
                     for c in load_world()["customers"])


AI_INSTRUCTIONS = f"""You are ServiceDesk_Analyst, the data agent of the Zava Service Desk.
Zava runs a managed IT service desk for six enterprise customers; AI agents (supervisor,
triage, knowledge, resolver, chat, voice) resolve most tickets and hand the rest to human
analysts (HITL). Contracts carry Experience Level Agreements (XLAs) with service credits.
ALWAYS answer by querying a source, never from general knowledge. If a query returns
nothing, say so plainly instead of guessing.

## Pick the source
1. ONT_ServiceDesk (Ontology, GQL): RELATIONSHIPS and IMPACT. Who is affected by what:
   which users and VIPs sit on a site hit by a major incident, which application caused
   it, which tickets belong to it, which XLAs a contract defines (with the clause text),
   which MCP tools an AI agent can call.
2. SM_ServiceDesk_Analytics (Semantic Model, DAX): every NUMBER over closed periods.
   Zero-touch rate, tickets, MTTR, CSAT, time lost per seat, experience score, major
   incident counts, XLA breaches and service credits. ALWAYS reuse the measures.
3. KQL_ServiceDesk (Eventhouse, KQL): what is happening RIGHT NOW. Live end-user
   telemetry (VPN latency, experience score), AI agent spans (errors, latency, cost),
   AI gateway requests (HTTP 429 throttling), live ticket and CSAT events.

Routing: "right now", "live", "currently", "last hour" -> Eventhouse. A number, a rate, a
ranking or a credit -> Semantic Model. "Who", "which", "is X affected", "what does the
contract say" -> Ontology. For "find then explain" questions, get the figure from the
Semantic Model, then traverse the Ontology for the context, and say which source gave what.

## Business rules
- "This week" / "last week" means the LAST CLOSED ISO week: use the (Last Closed Week)
  measures. The current week is still open and is never used for an XLA verdict.
- [Zero-Touch %] is a ratio: show it as a percentage (0.34 -> 34.0%).
- Service credits come from [XLA Credit (EUR)] / [XLA Credit (Last Closed Week)]; the
  monthly cap is already applied. Never recompute a credit from penalty_pct.
- An XLA breach verdict ALWAYS comes from [XLA Breaches (Last Closed Week)] (a count:
  above 0 means in breach) together with [XLA Credit (Last Closed Week)]. There is no
  boolean "in breach" measure. Only use measures that exist in the model; never invent
  a measure name. A breach answer must state the measured value, the target and the credit.
- The contractual wording of an XLA is Xla.clause_text in the ontology. Quote it when asked
  what the contract says, together with the measured value from the Semantic Model.
- Eventhouse figures cover a short live window; Semantic Model figures cover closed days
  and weeks. Never compare them without saying so.
- Customers are often named by their short name. Always map it to the full
  dim_customer[customer_name] before filtering: {_customer_lines()}.
- If a Semantic Model query comes back blank, check the customer filter uses the full
  name and that you used the (Last Closed Week) measures, then retry once before
  concluding there is no data.

## Ontology entities (node label (properties))
{_entity_lines()}

## Ontology relationships (edge label, direction matters)
{_relationship_lines()}
Node label = entity name, edge label = relationship name. Traverse in reverse with
<-[:Name]-. Booleans are true/false literals (u.is_vip = true). Quote reserved
words with backticks: x.`unit`.

## Semantic model measures
{_measure_lines()}
Name customers with dim_customer[customer_name], sites with dim_site[site_name], agents
with dim_agent[agent_name], XLAs with dim_xla[metric_label].

## Response format
- One-line direct answer first, figures as digits ("34.0% vs a 40.0% target", "9,250 EUR").
- Then the entities involved with their IDs, and the source(s) you queried.
- Be concise: the reader is a service desk lead about to call the customer."""

GQL_FEWSHOTS: List[Tuple[str, str]] = [
    ("Is user USR-FAB-0061 impacted by an open major incident?",
     "MATCH (u:User {user_id:'USR-FAB-0061'})<-[:SiteHostsUser]-(s:Site)"
     "<-[:MajorIncidentAffectsSite]-(m:MajorIncident) WHERE m.status = 'open' "
     "RETURN u.display_name, s.site_name, m.major_incident_id, m.title, m.severity"),
    ("Which VIP users are impacted by major incident MI-FAB-0001?",
     "MATCH (m:MajorIncident {major_incident_id:'MI-FAB-0001'})-[:MajorIncidentAffectsSite]->"
     "(s:Site)-[:SiteHostsUser]->(u:User) WHERE u.is_vip = true "
     "RETURN u.user_id, u.display_name, u.department, s.site_name"),
    ("Which application caused major incident MI-FAB-0001 and what is the root cause?",
     "MATCH (m:MajorIncident {major_incident_id:'MI-FAB-0001'})-[:MajorIncidentCausedByApp]->"
     "(a:Application) RETURN a.app_name, a.is_critical, m.root_cause, m.impacted_users"),
    ("How many tickets are linked to major incident MI-FAB-0001?",
     "MATCH (t:Ticket)-[:TicketPartOfIncident]->(m:MajorIncident {major_incident_id:'MI-FAB-0001'}) "
     "RETURN count(t) AS tickets"),
    ("What does the Fabrikam contract say about zero-touch?",
     "MATCH (c:Customer {customer_name:'Fabrikam Industries'})-[:CustomerHasContract]->"
     "(k:Contract)-[:ContractDefinesXla]->(x:Xla) WHERE x.metric = 'zero_touch_rate' "
     "RETURN k.contract_id, x.xla_id, x.comparator, x.threshold, x.`unit` AS xla_unit, "
     "x.measurement_window, x.penalty_pct, x.clause_text"),
    ("List the XLAs of every customer contract.",
     "MATCH (c:Customer)-[:CustomerHasContract]->(k:Contract)-[:ContractDefinesXla]->(x:Xla) "
     "RETURN c.customer_name, x.xla_id, x.metric_label, x.comparator, x.threshold, x.`unit` AS xla_unit"),
    ("Which MCP tools can the Resolver Agent call, and which of them write?",
     "MATCH (a:Agent {agent_id:'AGT-RESOLVER'})-[:AgentCallsTool]->(t:McpTool) "
     "RETURN t.tool_name, t.system, t.is_write"),
    ("Which sites does Fabrikam Industries have?",
     "MATCH (c:Customer {customer_name:'Fabrikam Industries'})-[:CustomerHasSite]->(s:Site) "
     "RETURN s.site_id, s.site_name, s.city, s.site_type, s.user_count"),
    ("Which knowledge articles document the network service?",
     "MATCH (k:KbArticle)-[:KbDocumentsService]->(s:Service {service_id:'SVC-NETWORK'}) "
     "RETURN k.kb_id, k.title, k.zero_touch_eligible"),
]

DAX_FEWSHOTS: List[Tuple[str, str]] = [
    ("Is Fabrikam in XLA breach on zero-touch this week, and what credit applies?",
     'EVALUATE SUMMARIZECOLUMNS ( dim_customer[customer_name],\n'
     '    FILTER ( ALL ( dim_customer[customer_name] ), '
     'dim_customer[customer_name] = "Fabrikam Industries" ),\n'
     '    "Week start", [Last Closed Week Start],\n'
     '    "Zero-touch", [Zero-Touch % (Last Closed Week)],\n'
     '    "Target", [Zero-Touch Target %],\n'
     '    "Breaches", [XLA Breaches (Last Closed Week)],\n'
     '    "Credit EUR", [XLA Credit (Last Closed Week)] )'),
    ("What was the zero-touch rate per customer last week, versus the week before?",
     'EVALUATE SUMMARIZECOLUMNS ( dim_customer[customer_name],\n'
     '    "Last week", [Zero-Touch % (Last Closed Week)],\n'
     '    "Previous week", [Zero-Touch % (Previous Week)],\n'
     '    "Change pts", [Zero-Touch Change (pts)] )'),
    ("Which customers breached an XLA last week and what credit is owed?",
     'EVALUATE FILTER ( SUMMARIZECOLUMNS ( dim_customer[customer_name],\n'
     '    "Breaches", [XLA Breaches (Last Closed Week)],\n'
     '    "Credit EUR", [XLA Credit (Last Closed Week)] ), [Breaches] > 0 )'),
    ("Which site has the worst digital experience score?",
     'EVALUATE TOPN ( 3, ADDCOLUMNS ( VALUES ( dim_site[site_name] ),\n'
     '    "Experience", [Experience Score], "VPN ms", [VPN Latency (ms)] ), [Experience], ASC )'),
    ("How many tickets did each AI agent resolve, and how many with zero touch?",
     'EVALUATE FILTER ( SUMMARIZECOLUMNS ( dim_agent[agent_name], dim_agent[agent_type],\n'
     '    "Tickets", [Tickets], "Zero-touch", [Zero-Touch Tickets] ), [Tickets] > 0 )'),
    ("What are CSAT and time lost per seat by customer?",
     'EVALUATE SUMMARIZECOLUMNS ( dim_customer[customer_name],\n'
     '    "CSAT", [CSAT Avg], "Time lost per seat (min)", [Time Lost per Seat (min)] )'),
]

KQL_FEWSHOTS: List[Tuple[str, str]] = [
    ("What is the VPN latency per site right now?",
     "let anchor = toscalar(dem_telemetry | summarize max(timestamp));\n"
     "dem_telemetry\n| where timestamp > anchor - 1h\n"
     "| summarize p50 = percentile(vpn_latency_ms, 50), p95 = percentile(vpn_latency_ms, 95),\n"
     "            experience = avg(experience_score), devices = dcount(device_id)\n"
     "         by site_id, customer_id\n| order by p95 desc"),
    ("Which AI agents are failing right now and why?",
     "let anchor = toscalar(agent_traces | summarize max(timestamp));\n"
     "agent_traces\n| where timestamp > anchor - 24h and status == \"error\"\n"
     "| summarize errors = count() by agent_id, error_type\n| order by errors desc"),
    ("Is the AI gateway throttling requests?",
     "let anchor = toscalar(gateway_logs | summarize max(timestamp));\n"
     "gateway_logs\n| where timestamp > anchor - 24h\n"
     "| summarize throttled = countif(status_code == 429), requests = count() by agent_id, model\n"
     "| where throttled > 0\n| order by throttled desc"),
    ("How has the experience score moved at FAB-LYO over the last hours?",
     "let anchor = toscalar(dem_telemetry | summarize max(timestamp));\n"
     "dem_telemetry\n| where timestamp > anchor - 6h and site_id == \"FAB-LYO\"\n"
     "| summarize experience = avg(experience_score), vpn_ms = avg(vpn_latency_ms)\n"
     "         by bin(timestamp, 15m)\n| order by timestamp asc"),
]

KQL_TABLE_DESC = {
    "dem_telemetry": "Live end-user device telemetry (DEM): one row per device per sample.",
    "tickets_events": "Live ticket lifecycle events (created, updated, resolved).",
    "conversations": "Live conversation turns between users and chat / voice agents.",
    "agent_traces": "AI agent spans (OpenTelemetry style): status, latency, tokens, cost.",
    "gateway_logs": "AI gateway requests to the models; status_code 429 = throttled.",
    "csat_events": "Live CSAT survey responses (score 1 to 5).",
}


def sid(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def kusto_elements() -> List[Dict]:
    return [{"id": None, "display_name": table, "type": "kusto.table", "is_selected": True,
             "description": KQL_TABLE_DESC.get(table, table),
             "children": [{"id": None, "display_name": c, "type": "kusto.column",
                           "is_selected": True, "description": f"{c} ({t})", "children": []}
                          for c, t in cols]}
            for table, cols in EVENTHOUSE.items()]


def sm_elements() -> List[Dict]:
    out = []
    for table, desc in TABLES.items():
        children = [{"id": None, "display_name": c, "type": "semantic_model.column",
                     "is_selected": True, "description": c.replace("_", " "), "children": []}
                    for c, _ in LAKEHOUSE[table]]
        children += [{"id": None, "display_name": m[0], "type": "semantic_model.measure",
                      "is_selected": True, "description": m[4], "children": []}
                     for m in MEASURES.get(table, [])]
        out.append({"id": None, "display_name": table, "type": "semantic_model.table",
                    "is_selected": True, "description": desc, "children": children})
    return out


def fewshots(key: str, pairs: List[Tuple[str, str]]) -> Dict:
    return {"$schema": f"{SCH}/fewShots/1.0.0/schema.json",
            "fewShots": [{"id": sid(f"{key}.{i}"), "question": q, "query": query}
                         for i, (q, query) in enumerate(pairs)]}


def build_parts(ws: str, name: str, ont: Tuple[str, str], sm: Tuple[str, str],
                kql: Tuple[str, str]) -> List[Dict]:
    sources = [
        (f"ontology-{ont[1]}", {
            "$schema": f"{SCH}/dataSource/1.0.0/schema.json",
            "artifactId": ont[0], "workspaceId": ws, "displayName": ont[1], "type": "ontology",
            "userDescription": ("Service desk knowledge graph: customers, sites, users, devices, "
                                "applications, services, tickets, major incidents, KB articles, "
                                "agents, MCP tools, contracts and XLAs."),
            "dataSourceInstructions": (
                "Use for RELATIONSHIPS, IMPACT and CONTRACT WORDING (GQL). Node label = entity "
                "name, edge label = relationship name. A user is reached from a major incident "
                "through the site: (m:MajorIncident)-[:MajorIncidentAffectsSite]->(s:Site)"
                "-[:SiteHostsUser]->(u:User). An XLA is reached through the contract: "
                "(c:Customer)-[:CustomerHasContract]->(k:Contract)-[:ContractDefinesXla]->(x:Xla). "
                "Do NOT use this source for rates, credits or any aggregate over time: those "
                "come from the semantic model.")},
         fewshots("gql", GQL_FEWSHOTS)),
        (f"semantic-model-{sm[1]}", {
            "$schema": f"{SCH}/dataSource/1.0.0/schema.json",
            "artifactId": sm[0], "workspaceId": ws, "displayName": sm[1],
            "type": "semantic_model",
            "dataSourceInstructions": (
                "Use for ALL numbers over closed periods. Always reuse the existing measures, "
                "never recompute from raw columns. 'This week' = the last closed ISO week: use "
                "the (Last Closed Week) measures. [Zero-Touch %] is a ratio. Credits already "
                "include the monthly cap. XLA breach = [XLA Breaches (Last Closed Week)] > 0, "
                "with [XLA Credit (Last Closed Week)] for the credit; no boolean breach "
                "measure exists, never invent a measure name. Filter a customer with FILTER ( ALL ( "
                "dim_customer[customer_name] ), dim_customer[customer_name] = \"Fabrikam "
                "Industries\" ). Short names map to full names: " + _customer_lines() + "."),
            "elements": sm_elements()},
         fewshots("dax", DAX_FEWSHOTS)),
        (f"kusto-{kql[1]}", {
            "$schema": f"{SCH}/dataSource/1.0.0/schema.json",
            "artifactId": kql[0], "workspaceId": ws, "displayName": kql[1], "type": "kusto",
            "userDescription": ("Live service desk telemetry: end-user experience, AI agent "
                                "traces, AI gateway logs, ticket, conversation and CSAT events."),
            "dataSourceInstructions": (
                "Use for anything LIVE, RIGHT NOW or in the last hours, and only for that. "
                "Anchor windows on the latest data, not on now(): let anchor = toscalar(T | "
                "summarize max(timestamp)); then where timestamp > anchor - 1h. Always report "
                "the window you read. These tables carry CODES only (site_id, customer_id, "
                "agent_id): there are no names and the dim_* tables do not exist here, so "
                "resolve names with a separate query on the semantic model or the ontology. "
                "Keep each query simple: one filter, one summarize, one order; no self-join. "
                "High VPN latency is above 200 ms; a low experience score is below 60; a failed "
                "span has status == \"error\"; throttling is status_code == 429."),
            "elements": kusto_elements()},
         fewshots("kql", KQL_FEWSHOTS)),
    ]
    stage = b64encode_json({"$schema": f"{SCH}/stageConfiguration/1.0.0/schema.json",
                            "aiInstructions": AI_INSTRUCTIONS})

    def p(path: str, payload: str) -> Dict:
        return {"path": path, "payload": payload, "payloadType": "InlineBase64"}

    parts = [p("Files/Config/data_agent.json",
               b64encode_json({"$schema": f"{SCH}/dataAgent/2.1.0/schema.json"})),
             p("Files/Config/publish_info.json", b64encode_json({
                 "$schema": f"{SCH}/publishInfo/1.0.0/schema.json",
                 "description": f"{name}: ontology + semantic model + Eventhouse"}))]
    for tree in ("draft", "published"):
        parts.append(p(f"Files/Config/{tree}/stage_config.json", stage))
        for folder, ds, fs in sources:
            parts.append(p(f"Files/Config/{tree}/{folder}/datasource.json", b64encode_json(ds)))
            parts.append(p(f"Files/Config/{tree}/{folder}/fewshots.json", b64encode_json(fs)))
    return parts


def _post_with_retry(url: str, attempts: int = 4, **kwargs) -> requests.Response:
    """POST that tolerates a cold graph right after a refresh (slow first reads)."""
    for i in range(attempts):
        try:
            return requests.post(url, **kwargs)
        except requests.RequestException as e:
            if i == attempts - 1:
                raise
            print(f"   {type(e).__name__}, retrying in 30s")
            time.sleep(30)
    raise AssertionError("unreachable")


def verify_fewshots(api: str, ws: str, token: str, state: Dict, kql_db: str) -> None:
    """Run every few-shot on its source; raise on an error or an empty result."""
    headers = fabric_headers(token)
    graph = require_state(state, "graph_model_id")
    for q, gql in GQL_FEWSHOTS:
        r = _post_with_retry(f"{api}/workspaces/{ws}/graphModels/{graph}/executeQuery?beta=true",
                             headers=headers, json={"query": gql}, timeout=300)
        rows = r.json().get("result", {}).get("data", []) if r.status_code == 200 else None
        if not rows:
            raise RuntimeError(f"GQL few-shot failed ({r.status_code}): {q}\n{r.text[:600]}")
        print(f"   GQL ok ({len(rows):>3} rows)  {q}")

    pbi = get_token(PBI_RESOURCE)
    sm = require_state(state, "semantic_model_id")
    for q, dax in DAX_FEWSHOTS:
        r = requests.post(f"{PBI_API}/groups/{ws}/datasets/{sm}/executeQueries",
                          headers={"Authorization": "Bearer " + pbi,
                                   "Content-Type": "application/json"},
                          json={"queries": [{"query": dax}]}, timeout=120)
        rows = (r.json()["results"][0]["tables"][0].get("rows", [])
                if r.status_code == 200 else None)
        if not rows:
            raise RuntimeError(f"DAX few-shot failed ({r.status_code}): {q}\n{r.text[:600]}")
        print(f"   DAX ok ({len(rows):>3} rows)  {q}")

    uri = require_state(state, "kusto_query_uri")
    ktoken = get_kusto_token(uri)
    for q, kql in KQL_FEWSHOTS:
        rows = kusto_query(uri, ktoken, kql_db, kql)
        if not rows:
            raise RuntimeError(f"KQL few-shot returned no row: {q}")
        print(f"   KQL ok ({len(rows):>3} rows)  {q}")


def readback(api: str, ws: str, token: str, aid: str) -> None:
    resp = requests.post(f"{api}/workspaces/{ws}/items/{aid}/getDefinition",
                         headers=fabric_headers(token), timeout=60)
    body = wait_lro(token, api, resp, "getDefinition DataAgent") or {}
    parts = body.get("definition", {}).get("parts", [])
    published = [x for x in parts if "/published/" in x["path"]]
    print(f"   {len(parts)} parts, {len(published)} under published/")
    for x in parts:
        if x["path"].endswith("datasource.json") and "/published/" in x["path"]:
            ds = json.loads(base64.b64decode(x["payload"]).decode("utf-8"))
            print(f"   published source: {ds.get('type'):<15} {ds.get('displayName')}")
    if not published:
        raise RuntimeError("No published/ parts came back: the agent is not reachable over MCP")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--delete", action="store_true")
    ap.add_argument("--skip-verify", action="store_true")
    args = ap.parse_args()

    cfg, state, api, ws, token = deploy_context()
    da = cfg.get("data_agent") or {}
    name = da.get("name", "ServiceDesk_Analyst")
    headers = fabric_headers(token)
    item = find_item_or_none(token, api, ws, name, "DataAgent")

    if args.delete:
        if item:
            requests.delete(f"{api}/workspaces/{ws}/items/{item['id']}", headers=headers,
                            timeout=60).raise_for_status()
            state.pop("data_agent_id", None)
            state.pop("data_agent_mcp_url", None)
            save_state(state)
            print(f"deleted {item['id']}")
        else:
            print("no Data Agent to delete")
        return 0

    ont = (require_state(state, "ontology_id"), cfg["ontology"]["name"])
    sm = (require_state(state, "semantic_model_id"), cfg["semantic_model"]["name"])
    kql = (require_state(state, "kql_database_id"), cfg["eventhouse"]["kql_database"])

    print_step(1, 4, "Verify every few-shot on its live source")
    if args.skip_verify:
        print("   skipped")
    else:
        verify_fewshots(api, ws, token, state, kql[1])

    print_step(2, 4, f"Create or update Data Agent '{name}' (published)")
    parts = build_parts(ws, name, ont, sm, kql)
    if item:
        resp = requests.post(f"{api}/workspaces/{ws}/items/{item['id']}/updateDefinition",
                             headers=headers, json={"definition": {"parts": parts}}, timeout=120)
        wait_lro(token, api, resp, f"updateDefinition DataAgent '{name}'")
        aid = item["id"]
        print(f"   updated {aid} ({len(parts)} parts)")
    else:
        resp = requests.post(f"{api}/workspaces/{ws}/items", headers=headers, timeout=120,
                             json={"displayName": name, "description": AGENT_DESC,
                                   "type": "DataAgent", "definition": {"parts": parts}})
        body = wait_lro(token, api, resp, f"Create DataAgent '{name}'")
        aid = (body or {}).get("id")
        for _ in range(6):
            if aid:
                break
            time.sleep(5)
            found = find_item_or_none(token, api, ws, name, "DataAgent")
            aid = found["id"] if found else None
        if not aid:
            raise RuntimeError(f"Data Agent '{name}' not found after create")
        print(f"   created {aid} ({len(parts)} parts)")

    print_step(3, 4, "Readback")
    readback(api, ws, token, aid)

    print_step(4, 4, "Persist state")
    state["data_agent_id"] = aid
    state["data_agent_mcp_url"] = da["mcp_endpoint_template"].format(workspace_id=ws,
                                                                    data_agent_id=aid)
    save_state(state)
    print("   data_agent_id, data_agent_mcp_url saved")
    print("\n   Test: python -m fabric.data_agent.mcp_client")
    return 0


if __name__ == "__main__":
    sys.exit(main())
