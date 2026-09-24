#!/usr/bin/env python3
"""Deploy ``SM_ServiceDesk_Analytics``: Direct Lake over the Lakehouse SQL endpoint.

Columns come from ``fabric/data/schema.py``. The measures are deliberately narrow and
auditable: every number the Data Agent quotes must be reproducible from two columns, and
the contractual numbers (breaches, credits) come from ``fact_xla_evaluation``, the
materialised output of ``generate_data.evaluate_xla``, never re-derived in DAX.

"This week" means the LAST CLOSED ISO week of the data (Monday to Sunday), which is
what an XLA evaluates. The live, still-open week lives in the Eventhouse.

  python -m fabric.powerbi.deploy_semantic_model
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import json
import uuid
from typing import Dict, List

import requests

from fabric._shared.helpers import (b64encode_json, create_fabric_item, deploy_context,
                                    fabric_headers, find_item_or_none, print_step,
                                    require_state, save_state, update_definition)
from fabric.data.schema import LAKEHOUSE

TMSL_TYPES = {"string": "string", "bigint": "int64", "double": "double",
              "datetime": "dateTime", "boolean": "boolean"}
PCT = "0.0%;-0.0%;0.0%"
EUR = "#,0 \"EUR\""
NUM = "#,0"
DEC = "#,0.0"

TABLES: Dict[str, str] = {
    "dim_customer": "Customers of the Zava managed service desk",
    "dim_site": "Customer sites (offices, plants, stores)",
    "dim_user": "End users supported by the service desk",
    "dim_device": "Managed end-user devices",
    "dim_application": "Business applications",
    "dim_service": "IT services in the catalogue",
    "dim_kb_article": "Knowledge base articles used to resolve tickets",
    "dim_agent": "AI and human agents that resolve tickets",
    "dim_contract": "Managed service contracts (one per customer)",
    "dim_xla": "Experience Level Agreements: the contractual targets",
    "dim_date": "Calendar (UTC days); week_start is the ISO Monday",
    "fact_ticket": "One row per ticket",
    "fact_csat": "Customer satisfaction survey responses (1 to 5)",
    "fact_experience_daily": "Daily digital experience per device (DEM)",
    "fact_major_incident": "Major incidents",
    "fact_xla_evaluation": "XLA evaluation per closed window: value, breach and credit "
                           "(monthly cap already applied)",
}

# (from table, from column, to table, to column). A flat star: dimensions are not chained,
# so every fact reaches a dimension through exactly one path.
RELATIONSHIPS = [
    ("fact_ticket", "customer_id", "dim_customer", "customer_id"),
    ("fact_ticket", "site_id", "dim_site", "site_id"),
    ("fact_ticket", "user_id", "dim_user", "user_id"),
    ("fact_ticket", "device_id", "dim_device", "device_id"),
    ("fact_ticket", "service_id", "dim_service", "service_id"),
    ("fact_ticket", "app_id", "dim_application", "app_id"),
    ("fact_ticket", "kb_id", "dim_kb_article", "kb_id"),
    ("fact_ticket", "resolved_by_agent_id", "dim_agent", "agent_id"),
    ("fact_ticket", "created_date", "dim_date", "date"),
    ("fact_csat", "customer_id", "dim_customer", "customer_id"),
    ("fact_csat", "submitted_date", "dim_date", "date"),
    ("fact_experience_daily", "customer_id", "dim_customer", "customer_id"),
    ("fact_experience_daily", "site_id", "dim_site", "site_id"),
    ("fact_experience_daily", "device_id", "dim_device", "device_id"),
    ("fact_experience_daily", "date", "dim_date", "date"),
    ("fact_major_incident", "customer_id", "dim_customer", "customer_id"),
    ("fact_xla_evaluation", "customer_id", "dim_customer", "customer_id"),
    ("fact_xla_evaluation", "xla_id", "dim_xla", "xla_id"),
    ("fact_xla_evaluation", "window_start", "dim_date", "date"),
    ("dim_contract", "customer_id", "dim_customer", "customer_id"),
]

LAST_WEEK = """VAR maxd = CALCULATE ( MAX ( dim_date[date] ), REMOVEFILTERS () )
VAR wd = WEEKDAY ( maxd, 2 )
VAR ws = maxd - wd + 1
RETURN IF ( wd = 7, ws, ws - 7 )"""


def _in_week(measure: str, offset_weeks: int = 0) -> str:
    return (f"VAR w = [Last Closed Week Start] - {7 * offset_weeks}\n"
            f"RETURN CALCULATE ( {measure}, REMOVEFILTERS ( dim_date ), dim_date[week_start] = w )")


# table -> [(name, expression, format, folder, description)]
MEASURES: Dict[str, List[tuple]] = {
    "fact_ticket": [
        ("Tickets", "COUNTROWS ( fact_ticket )", NUM, "Tickets", "Number of tickets"),
        ("Zero-Touch Tickets", "CALCULATE ( [Tickets], fact_ticket[zero_touch] = TRUE () )",
         NUM, "Tickets", "Tickets resolved end-to-end by AI agents, no human touch"),
        ("Zero-Touch %", "DIVIDE ( [Zero-Touch Tickets], [Tickets] )", PCT, "Tickets",
         "Zero-touch resolution rate (the XLA zero_touch_rate, as a ratio)"),
        ("HITL Escalations", "CALCULATE ( [Tickets], fact_ticket[escalated_hitl] = TRUE () )",
         NUM, "Tickets", "AI-channel tickets escalated to a human (human in the loop)"),
        ("Open Tickets", "CALCULATE ( [Tickets], ISBLANK ( fact_ticket[resolved_at] ) )",
         NUM, "Tickets", "Tickets not resolved yet"),
        ("MTTR (h)", "AVERAGEX ( FILTER ( fact_ticket, NOT ISBLANK ( fact_ticket[resolved_at] ) ), "
         "DATEDIFF ( fact_ticket[created_at], fact_ticket[resolved_at], MINUTE ) ) / 60",
         DEC, "Tickets", "Mean time to resolve, in hours"),
        ("Time Lost (min)", "SUM ( fact_ticket[time_lost_min] )", NUM, "Experience",
         "User productive time lost to IT issues, in minutes"),
        ("Time Lost per Seat (min)", "DIVIDE ( [Time Lost (min)], SUM ( dim_customer[seats] ) )",
         DEC, "Experience", "Time lost divided by contracted seats (the XLA metric)"),
        ("Last Closed Week Start", LAST_WEEK, "yyyy-mm-dd", "This week",
         "Monday of the last closed ISO week in the data"),
        ("Zero-Touch % (Last Closed Week)", _in_week("[Zero-Touch %]"), PCT, "This week",
         "Zero-touch rate over the last closed ISO week"),
        ("Zero-Touch % (Previous Week)", _in_week("[Zero-Touch %]", 1), PCT, "This week",
         "Zero-touch rate over the week before the last closed week"),
        ("Zero-Touch Change (pts)",
         "( [Zero-Touch % (Last Closed Week)] - [Zero-Touch % (Previous Week)] ) * 100",
         "+0.0;-0.0;0.0", "This week", "Week-on-week change of the zero-touch rate, in points"),
        ("Tickets (Last Closed Week)", _in_week("[Tickets]"), NUM, "This week",
         "Tickets created in the last closed ISO week"),
        ("Zero-Touch Target %",
         "CALCULATE ( MIN ( dim_xla[threshold] ), TREATAS ( VALUES ( dim_customer[customer_id] ), "
         "dim_xla[customer_id] ), dim_xla[metric] = \"zero_touch_rate\", "
         "dim_xla[measurement_window] = \"weekly\" ) / 100",
         PCT, "XLA", "Contractual weekly zero-touch target of the customer(s) in context"),
    ],
    "fact_csat": [
        ("CSAT Avg", "AVERAGE ( fact_csat[score] )", "0.00", "Experience",
         "Average CSAT score (1 to 5)"),
        ("CSAT Responses", "COUNTROWS ( fact_csat )", NUM, "Experience", "Survey responses"),
    ],
    "fact_experience_daily": [
        ("Experience Score", "AVERAGE ( fact_experience_daily[experience_score] )", DEC,
         "Experience", "Average digital experience score (0 to 100)"),
        ("App Crashes", "SUM ( fact_experience_daily[crash_count] )", NUM, "Experience",
         "Application crashes"),
        ("VPN Latency (ms)", "AVERAGE ( fact_experience_daily[avg_vpn_latency_ms] )", NUM,
         "Experience", "Average VPN latency"),
        ("Teams MOS", "AVERAGE ( fact_experience_daily[avg_teams_mos] )", "0.00", "Experience",
         "Average Teams call quality (mean opinion score)"),
    ],
    "fact_major_incident": [
        ("Major Incidents", "COUNTROWS ( fact_major_incident )", NUM, "Incidents",
         "Number of major incidents"),
        ("Impacted Users", "SUM ( fact_major_incident[impacted_users] )", NUM, "Incidents",
         "Users impacted by major incidents"),
        ("Impacted VIP Users", "SUM ( fact_major_incident[impacted_vip_users] )", NUM,
         "Incidents", "VIP users impacted by major incidents"),
    ],
    "fact_xla_evaluation": [
        ("XLA Evaluations", "COUNTROWS ( fact_xla_evaluation )", NUM, "XLA",
         "XLA evaluations over closed windows"),
        ("XLA Breaches", "CALCULATE ( [XLA Evaluations], fact_xla_evaluation[breached] = TRUE () )",
         NUM, "XLA", "Closed windows where the XLA target was missed"),
        ("XLA Credit (EUR)", "SUM ( fact_xla_evaluation[penalty_eur] )", EUR, "XLA",
         "Service credit owed to the customer (monthly cap already applied)"),
        ("XLA Breaches (Last Closed Week)",
         "VAR w = [Last Closed Week Start]\nRETURN CALCULATE ( [XLA Breaches], "
         "REMOVEFILTERS ( dim_date ), fact_xla_evaluation[window_start] = w, "
         "fact_xla_evaluation[measurement_window] = \"weekly\" )",
         NUM, "This week", "Weekly XLA breaches of the last closed ISO week"),
        ("XLA Credit (Last Closed Week)",
         "VAR w = [Last Closed Week Start]\nRETURN CALCULATE ( [XLA Credit (EUR)], "
         "REMOVEFILTERS ( dim_date ), fact_xla_evaluation[window_start] = w, "
         "fact_xla_evaluation[measurement_window] = \"weekly\" )",
         EUR, "This week", "Credit owed for the weekly XLAs of the last closed ISO week"),
    ],
}

COPILOT_INSTRUCTIONS = (
    "This model measures a managed IT service desk run by Zava for its customers, with AI "
    "agents resolving tickets. Always use the existing measures. "
    "Zero-touch: [Zero-Touch %] (ratio; multiply by 100 for percent), [Zero-Touch Tickets], "
    "[Tickets]. 'This week' means the last closed ISO week: use [Zero-Touch % (Last Closed "
    "Week)], [Zero-Touch % (Previous Week)], [Zero-Touch Change (pts)], [Tickets (Last Closed "
    "Week)], [Last Closed Week Start]. Contract numbers: [XLA Breaches], [XLA Credit (EUR)], "
    "[XLA Credit (Last Closed Week)], [XLA Breaches (Last Closed Week)], [Zero-Touch Target %]; "
    "credits already include the monthly cap, never recompute them. Experience: [CSAT Avg], "
    "[Experience Score], [Time Lost per Seat (min)], [VPN Latency (ms)], [App Crashes]. "
    "Incidents: [Major Incidents], [Impacted Users]. Name customers with "
    "dim_customer[customer_name] and sites with dim_site[site_name]."
)

VERIFIED_ANSWERS = [
    ("What was the zero-touch rate per customer last week?",
     'EVALUATE SUMMARIZECOLUMNS ( dim_customer[customer_name], "Zero-touch last week", '
     '[Zero-Touch % (Last Closed Week)], "Previous week", [Zero-Touch % (Previous Week)] )'),
    ("Which customers breached an XLA last week and what credit is owed?",
     'EVALUATE FILTER ( SUMMARIZECOLUMNS ( dim_customer[customer_name], "Breaches", '
     '[XLA Breaches (Last Closed Week)], "Credit EUR", [XLA Credit (Last Closed Week)] ), '
     '[Breaches] > 0 )'),
    ("What is the CSAT per customer?",
     'EVALUATE SUMMARIZECOLUMNS ( dim_customer[customer_name], "CSAT", [CSAT Avg] )'),
]


def _tag() -> str:
    return str(uuid.uuid4())


def _column(table: str, col: str, kind: str) -> Dict:
    c = {"name": col, "dataType": TMSL_TYPES[kind], "sourceColumn": col, "lineageTag": _tag()}
    if kind == "datetime":
        c["formatString"] = "yyyy-mm-dd" if col.endswith(("date", "_start", "_end")) \
            else "yyyy-mm-dd hh:nn"
    if kind != "double" or col in ("threshold", "penalty_pct", "penalty_cap_pct",
                                   "monthly_fee_eur", "value"):
        c["summarizeBy"] = "none"
    if table == "dim_date" and col == "date":
        c["isKey"] = True
    return c


def build_model_bim(lh_name: str, sql_endpoint: str) -> Dict:
    tables = []
    for name, desc in TABLES.items():
        t = {"name": name, "lineageTag": _tag(), "description": desc,
             "columns": [_column(name, c, k) for c, k in LAKEHOUSE[name]],
             "partitions": [{"name": name, "mode": "directLake",
                             "source": {"type": "entity", "entityName": name,
                                        "expressionSource": "DatabaseQuery"}}]}
        if name == "dim_date":
            t["dataCategory"] = "Time"
        measures = [{"name": m, "expression": expr.split("\n"), "formatString": fmt,
                     "displayFolder": folder, "description": d, "lineageTag": _tag()}
                    for m, expr, fmt, folder, d in MEASURES.get(name, [])]
        if measures:
            t["measures"] = measures
        tables.append(t)

    rels = [{"name": f"rel_{ft}_{fc}", "fromTable": ft, "fromColumn": fc, "toTable": tt,
             "toColumn": tc, "crossFilteringBehavior": "oneDirection"}
            for ft, fc, tt, tc in RELATIONSHIPS]
    expressions = [{"name": "DatabaseQuery", "kind": "m", "lineageTag": _tag(),
                    "expression": ["let",
                                   f'    database = Sql.Database("{sql_endpoint}", "{lh_name}")',
                                   "in", "    database"]}]
    return {
        "compatibilityLevel": 1604,
        "model": {
            "defaultPowerBIDataSourceVersion": "PowerBI_V3",
            "defaultMode": "directLake",
            "discourageImplicitMeasures": True,
            "culture": "en-US",
            "tables": tables,
            "relationships": rels,
            "expressions": expressions,
            "annotations": [
                {"name": "__PBI_CopilotInstructions", "value": COPILOT_INSTRUCTIONS},
                {"name": "__PBI_TimeIntelligenceEnabled", "value": "0"},
                {"name": "PBI_QueryOrder", "value": json.dumps(["DatabaseQuery"])},
                {"name": "__PBI_VerifiedAnswers", "value": json.dumps(
                    [{"Question": q, "Answer": {"Query": dax, "Description": q}}
                     for q, dax in VERIFIED_ANSWERS])},
            ],
        },
    }


def sql_endpoint_of(token: str, api: str, ws: str, lh_id: str, state: Dict) -> str:
    if state.get("lakehouse_sql_endpoint"):
        return state["lakehouse_sql_endpoint"]
    r = requests.get(f"{api}/workspaces/{ws}/lakehouses/{lh_id}", headers=fabric_headers(token),
                     timeout=60)
    r.raise_for_status()
    return r.json()["properties"]["sqlEndpointProperties"]["connectionString"]


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    lh_id = require_state(state, "lakehouse_id")
    lh_name = cfg["lakehouse"]["name"]
    sm_name = cfg["semantic_model"]["name"]

    print_step(1, 3, f"Build model.bim for '{sm_name}'")
    bim = build_model_bim(lh_name, sql_endpoint_of(token, api, ws, lh_id, state))
    n_measures = sum(len(t.get("measures", [])) for t in bim["model"]["tables"])
    print(f"   {len(bim['model']['tables'])} tables, {n_measures} measures, "
          f"{len(bim['model']['relationships'])} relationships")
    definition = {"parts": [
        {"path": "definition.pbism", "payload": b64encode_json({"version": "1.0"}),
         "payloadType": "InlineBase64"},
        {"path": "model.bim", "payload": b64encode_json(bim), "payloadType": "InlineBase64"},
    ]}

    print_step(2, 3, "Create or update the semantic model")
    item = find_item_or_none(token, api, ws, sm_name, "SemanticModel")
    if item:
        update_definition(token, api, ws, item["id"], definition, f"SemanticModel '{sm_name}'")
        print(f"   updated {item['id']}")
    else:
        item = create_fabric_item(token, api, ws, sm_name, "SemanticModel",
                                  "Zava Service Desk: tickets, experience and XLA (Direct Lake)",
                                  definition=definition)
        print(f"   created {item['id']}")

    print_step(3, 3, "Persist state")
    state["semantic_model_id"] = item["id"]
    save_state(state)
    print("   semantic_model_id saved. Check: python -m fabric.powerbi.verify_semantic_model")
    return 0


if __name__ == "__main__":
    sys.exit(main())
