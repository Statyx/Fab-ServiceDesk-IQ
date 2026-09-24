#!/usr/bin/env python3
"""Deploy the ``RTD_ServiceDesk_Operations`` Real-Time Dashboard over ``KQL_ServiceDesk``.

Two pages (``rti_dashboard.pages`` in config):

* **Operations** - what end users feel right now: devices reporting, VPN latency, the
  worst sites, experience score by customer, the ticket stream and the incident tickets.
* **AgentOps** - what the AI agents are doing: calls, errors, latency, cost, HITL
  escalations, tool mix and gateway throttling.

Every tile is anchored on the latest timestamp in its table (``toscalar(max(timestamp))``)
rather than ``now()``: the preload ends on the last closed Sunday, so ``ago(1h)`` would be
empty until the injector runs; with the injector running, the anchor IS now.

RealTimeDashboard.json schema v20, 24-column grid, 30 s auto-refresh. Tile and page ids
are uuid5 of stable names, so a redeploy is a no-op diff.

  python -m fabric.rti.deploy_dashboard
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import uuid
from typing import Dict, List

from fabric._shared.helpers import (create_fabric_item, deploy_context, find_item_or_none,
                                    get_kusto_token, kusto_query, part, print_step,
                                    require_state, save_state, update_definition)

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/Statyx/Fab-ServiceDesk-IQ/rtd")


def sid(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def anchored(table: str, window: str, body: str) -> str:
    """Rows of ``table`` in the last ``window`` before its latest timestamp."""
    return (f"let anchor = toscalar({table} | summarize max(timestamp));\n"
            f"{table}\n| where timestamp > anchor - {window}\n{body}")


def stat(key, title, query, x, y, w, h, page, ds) -> Dict:
    return {"id": sid(key), "title": title, "query": query,
            "layout": {"x": x, "y": y, "width": w, "height": h},
            "pageId": page, "dataSourceId": ds, "visualType": "card",
            "visualOptions": {"multiStat__textSize": "auto",
                              "multiStat__valueColumn": {"type": "infer"}},
            "usedParamVariables": []}


def viz(key, title, query, vtype, x, y, w, h, page, ds, series=False) -> Dict:
    vo: Dict = {"xColumn": {"type": "infer"}, "yColumns": {"type": "infer"},
                "hideTileTitle": False}
    if vtype == "line":
        vo.update({"yAxisMinimumValue": {"type": "infer"},
                   "yAxisMaximumValue": {"type": "infer"}, "hideLegend": False,
                   "multipleYAxes": {"base": {"id": "-1", "columns": [], "label": "",
                                              "yAxisMinimumValue": None,
                                              "yAxisMaximumValue": None,
                                              "yAxisScale": "linear",
                                              "horizontalLines": []},
                                     "additional": []}})
    if series:
        vo["seriesColumns"] = {"type": "infer"}
    return {"id": sid(key), "title": title, "query": query,
            "layout": {"x": x, "y": y, "width": w, "height": h},
            "pageId": page, "dataSourceId": ds, "visualType": vtype,
            "visualOptions": vo, "usedParamVariables": []}


def operations_tiles(p: str, ds: str) -> List[Dict]:
    dem, tev = "dem_telemetry", "tickets_events"
    return [
        stat("ops.devices", "Devices reporting (last hour)",
             anchored(dem, "1h", "| summarize Devices = dcount(device_id)"), 0, 0, 5, 4, p, ds),
        stat("ops.vpn_p95", "VPN latency p95, ms (last hour)",
             anchored(dem, "1h", "| summarize P95 = round(percentile(vpn_latency_ms, 95), 0)"),
             5, 0, 5, 4, p, ds),
        stat("ops.vpn_down", "Devices with VPN down (last hour)",
             anchored(dem, "1h", "| where vpn_connected == false\n"
                                 "| summarize Devices = dcount(device_id)"), 10, 0, 5, 4, p, ds),
        stat("ops.tickets", "Tickets opened (last 24h)",
             anchored(tev, "24h", "| where event_type == 'created'\n| count"), 15, 0, 4, 4, p, ds),
        stat("ops.zt", "Zero-touch % (last 24h)",
             anchored(tev, "24h", "| where event_type == 'resolved'\n"
                                  "| summarize ZeroTouchPct = round(100.0 * countif(zero_touch)"
                                  " / count(), 1)"), 19, 0, 5, 4, p, ds),
        viz("ops.vpn_trend", "VPN latency by site (ms, hourly avg, last 7 days)",
            anchored(dem, "7d", "| summarize LatencyMs = round(avg(vpn_latency_ms), 0)"
                                " by bin(timestamp, 1h), site_id\n| order by timestamp asc"),
            "line", 0, 4, 14, 8, p, ds, series=True),
        viz("ops.worst_sites", "Worst sites: VPN latency p95 (last 24h)",
            anchored(dem, "24h", "| summarize P95Ms = round(percentile(vpn_latency_ms, 95), 0)"
                                 " by site_id\n| top 10 by P95Ms desc"),
            "bar", 14, 4, 10, 8, p, ds),
        viz("ops.exp_trend", "Experience score by customer (hourly, last 7 days)",
            anchored(dem, "7d", "| summarize Score = round(avg(experience_score), 1)"
                                " by bin(timestamp, 1h), customer_id\n| order by timestamp asc"),
            "line", 0, 12, 14, 8, p, ds, series=True),
        viz("ops.issues", "Tickets opened by issue (last 24h)",
            anchored(tev, "24h", "| where event_type == 'created'\n"
                                 "| summarize Tickets = count() by issue_code\n"
                                 "| top 10 by Tickets desc"),
            "bar", 14, 12, 10, 8, p, ds),
        viz("ops.incident_tickets", "Latest tickets linked to a major incident",
            anchored(tev, "7d", "| where isnotempty(major_incident_id)\n"
                                "| project timestamp, ticket_id, event_type, customer_id, "
                                "site_id, issue_code, priority, status, major_incident_id\n"
                                "| order by timestamp desc\n| take 25"),
            "table", 0, 20, 24, 8, p, ds),
    ]


def agentops_tiles(p: str, ds: str) -> List[Dict]:
    at, gw = "agent_traces", "gateway_logs"
    return [
        stat("ag.calls", "Agent spans (last 24h)", anchored(at, "24h", "| count"),
             0, 0, 4, 4, p, ds),
        stat("ag.err", "Error rate % (last 24h)",
             anchored(at, "24h", "| summarize ErrorPct = round(100.0 * countif(status != 'ok')"
                                 " / count(), 2)"), 4, 0, 5, 4, p, ds),
        stat("ag.p95", "Latency p95, ms (last 24h)",
             anchored(at, "24h", "| summarize P95 = round(percentile(latency_ms, 95), 0)"),
             9, 0, 5, 4, p, ds),
        stat("ag.cost", "Model cost EUR (last 24h)",
             anchored(at, "24h", "| summarize CostEur = round(sum(cost_eur), 2)"),
             14, 0, 5, 4, p, ds),
        stat("ag.hitl", "HITL escalations (last 24h)",
             anchored(at, "24h", "| where hitl_escalation\n| count"), 19, 0, 5, 4, p, ds),
        viz("ag.latency_trend", "Latency p95 by agent (ms, hourly, last 7 days)",
            anchored(at, "7d", "| summarize P95Ms = round(percentile(latency_ms, 95), 0)"
                               " by bin(timestamp, 1h), agent_id\n| order by timestamp asc"),
            "line", 0, 4, 14, 8, p, ds, series=True),
        viz("ag.errors_by_agent", "Errors by agent and type (last 7 days)",
            anchored(at, "7d", "| where status != 'ok'\n"
                               "| summarize Errors = count() by agent_id, error_type\n"
                               "| order by Errors desc"),
            "bar", 14, 4, 10, 8, p, ds, series=True),
        viz("ag.tools", "MCP tool calls (last 7 days)",
            anchored(at, "7d", "| where isnotempty(tool_name)\n"
                               "| summarize Calls = count() by tool_name\n"
                               "| order by Calls desc"),
            "bar", 0, 12, 8, 8, p, ds),
        viz("ag.gateway", "AI gateway: requests by status (hourly, last 7 days)",
            anchored(gw, "7d", "| summarize Requests = count()"
                               " by bin(timestamp, 1h), Status = tostring(status_code)\n"
                               "| order by timestamp asc"),
            "line", 8, 12, 8, 8, p, ds, series=True),
        viz("ag.quality", "Groundedness and relevance (hourly avg, last 7 days)",
            anchored(at, "7d", "| where isnotnull(eval_groundedness)\n"
                               "| summarize Groundedness = round(avg(eval_groundedness), 3),"
                               " Relevance = round(avg(eval_relevance), 3)"
                               " by bin(timestamp, 1h)\n| order by timestamp asc"),
            "line", 16, 12, 8, 8, p, ds),
        viz("ag.latest_errors", "Latest agent errors",
            anchored(at, "7d", "| where status != 'ok'\n"
                               "| project timestamp, agent_id, operation, tool_name, "
                               "error_type, latency_ms, customer_id, trace_id\n"
                               "| order by timestamp desc\n| take 25"),
            "table", 0, 20, 24, 8, p, ds),
    ]


def build_dashboard(title: str, pages: List[str], cluster_uri: str, db: str) -> Dict:
    ds = sid("datasource")
    ops_page, agent_page = sid("page.operations"), sid("page.agentops")
    return {
        "$schema": "https://dataexplorer.azure.com/static/d/schema/20/dashboard.json",
        "schema_version": "20", "title": title,
        "autoRefresh": {"enabled": True, "defaultInterval": "30s", "minInterval": "30s"},
        "dataSources": [{"id": ds, "name": db, "clusterUri": cluster_uri, "database": db,
                         "kind": "manual-kusto", "scopeId": "KustoDatabaseResource"}],
        "pages": [{"id": ops_page, "name": pages[0]}, {"id": agent_page, "name": pages[1]}],
        "tiles": operations_tiles(ops_page, ds) + agentops_tiles(agent_page, ds),
        "parameters": [],
    }


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    name = cfg["rti_dashboard"]["name"]
    pages = cfg["rti_dashboard"].get("pages") or ["Operations", "AgentOps"]
    db = cfg["eventhouse"]["kql_database"]
    cluster = require_state(state, "kusto_query_uri")

    print_step(1, 3, "Build RealTimeDashboard.json and run every tile query")
    dash = build_dashboard(name, pages, cluster, db)
    print(f"   {len(dash['pages'])} pages, {len(dash['tiles'])} tiles on {db}")
    kusto_token = get_kusto_token(cluster)
    empty = []
    for tile in dash["tiles"]:
        rows = kusto_query(cluster, kusto_token, db, tile["query"])
        if not rows:
            empty.append(tile["title"])
    print(f"   all {len(dash['tiles'])} queries ran; empty: {empty or 'none'}")

    print_step(2, 3, f"Create or update KQL dashboard '{name}'")
    definition = {"parts": [part("RealTimeDashboard.json", dash)]}
    item = find_item_or_none(token, api, ws, name, "KQLDashboard")
    if item:
        update_definition(token, api, ws, item["id"], definition, f"KQLDashboard '{name}'")
        print(f"   updated {item['id']}")
    else:
        item = create_fabric_item(token, api, ws, name, "KQLDashboard",
                                  "Zava Service Desk: live operations and agent operations",
                                  definition=definition)
        print(f"   created {item['id']}")

    print_step(3, 3, "Persist state")
    state["rti_dashboard_id"] = item["id"]
    save_state(state)
    print("   rti_dashboard_id saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
