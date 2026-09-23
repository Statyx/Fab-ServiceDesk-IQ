"""Table schemas — the single source of truth for column names, order and types.

Two type systems, deliberately kept apart:

* Lakehouse (Delta) columns use the five types the Fabric ontology can bind:
  ``string``, ``bigint``, ``double``, ``datetime``, ``boolean``.
  Entity keys are strings; property names equal column names.
* Eventhouse (KQL) columns use ``string``, ``long``, ``real``, ``datetime``, ``bool``.

The generator writes CSV in exactly this column order; the phase-2 deploy scripts build
``.create-merge table`` commands, Delta schemas and ontology bindings from these lists.
"""
from __future__ import annotations

from typing import Dict, List, Tuple

Schema = List[Tuple[str, str]]

LAKEHOUSE_TYPES = {"string", "bigint", "double", "datetime", "boolean"}
KQL_TYPES = {"string", "long", "real", "datetime", "bool"}

LAKEHOUSE: Dict[str, Schema] = {
    "dim_customer": [
        ("customer_id", "string"), ("customer_name", "string"), ("industry", "string"),
        ("country", "string"), ("primary_language", "string"), ("seats", "bigint"),
        ("monthly_fee_eur", "double"),
    ],
    "dim_site": [
        ("site_id", "string"), ("customer_id", "string"), ("site_name", "string"),
        ("city", "string"), ("country", "string"), ("site_type", "string"),
        ("user_count", "bigint"),
    ],
    "dim_user": [
        ("user_id", "string"), ("customer_id", "string"), ("site_id", "string"),
        ("display_name", "string"), ("persona", "string"), ("is_vip", "boolean"),
        ("language", "string"), ("department", "string"),
    ],
    "dim_device": [
        ("device_id", "string"), ("user_id", "string"), ("customer_id", "string"),
        ("site_id", "string"), ("device_type", "string"), ("os", "string"),
        ("model", "string"), ("age_months", "bigint"), ("vpn_client_version", "string"),
    ],
    "dim_application": [
        ("app_id", "string"), ("app_name", "string"), ("category", "string"),
        ("is_critical", "boolean"),
    ],
    "bridge_device_application": [
        ("device_app_id", "string"), ("device_id", "string"), ("app_id", "string"),
        ("app_version", "string"),
    ],
    "dim_service": [
        ("service_id", "string"), ("service_name", "string"), ("service_type", "string"),
        ("owner_team", "string"),
    ],
    "dim_kb_article": [
        ("kb_id", "string"), ("service_id", "string"), ("app_id", "string"),
        ("issue_code", "string"), ("title", "string"), ("language", "string"),
        ("zero_touch_eligible", "boolean"),
    ],
    "dim_agent": [
        ("agent_id", "string"), ("agent_name", "string"), ("agent_type", "string"),
        ("role", "string"), ("tier", "string"), ("model", "string"),
    ],
    "dim_mcp_tool": [
        ("tool_id", "string"), ("tool_name", "string"), ("system", "string"),
        ("description", "string"), ("is_write", "boolean"),
    ],
    "dim_contract": [
        ("contract_id", "string"), ("customer_id", "string"), ("contract_name", "string"),
        ("start_date", "datetime"), ("end_date", "datetime"), ("monthly_fee_eur", "double"),
        ("penalty_cap_pct", "double"),
    ],
    "dim_xla": [
        ("xla_id", "string"), ("contract_id", "string"), ("customer_id", "string"),
        ("metric", "string"), ("metric_label", "string"), ("comparator", "string"),
        ("threshold", "double"), ("unit", "string"), ("measurement_window", "string"),
        ("penalty_pct", "double"), ("clause_text", "string"),
    ],
    "dim_date": [
        ("date", "datetime"), ("week_start", "datetime"), ("iso_year", "bigint"),
        ("iso_week", "bigint"), ("month_start", "datetime"), ("month_name", "string"),
        ("day_of_week", "bigint"), ("is_weekend", "boolean"),
    ],
    "fact_ticket": [
        ("ticket_id", "string"), ("customer_id", "string"), ("site_id", "string"),
        ("user_id", "string"), ("device_id", "string"), ("service_id", "string"),
        ("app_id", "string"), ("kb_id", "string"), ("major_incident_id", "string"),
        ("issue_code", "string"), ("channel", "string"), ("priority", "string"),
        ("status", "string"), ("created_at", "datetime"), ("created_date", "datetime"),
        ("resolved_at", "datetime"), ("zero_touch", "boolean"),
        ("escalated_hitl", "boolean"), ("resolved_by_agent_id", "string"),
        ("time_lost_min", "double"),
    ],
    "fact_csat": [
        ("csat_id", "string"), ("ticket_id", "string"), ("customer_id", "string"),
        ("user_id", "string"), ("channel", "string"), ("score", "bigint"),
        ("submitted_at", "datetime"), ("submitted_date", "datetime"),
    ],
    "fact_experience_daily": [
        ("date", "datetime"), ("device_id", "string"), ("user_id", "string"),
        ("customer_id", "string"), ("site_id", "string"), ("experience_score", "double"),
        ("crash_count", "bigint"), ("avg_vpn_latency_ms", "double"),
        ("avg_teams_mos", "double"),
    ],
    "fact_major_incident": [
        ("major_incident_id", "string"), ("customer_id", "string"), ("site_id", "string"),
        ("app_id", "string"), ("service_id", "string"), ("title", "string"),
        ("root_cause", "string"), ("severity", "string"), ("status", "string"),
        ("started_at", "datetime"), ("declared_at", "datetime"), ("resolved_at", "datetime"),
        ("impacted_users", "bigint"), ("impacted_vip_users", "bigint"),
    ],
}

EVENTHOUSE: Dict[str, Schema] = {
    "dem_telemetry": [
        ("timestamp", "datetime"), ("customer_id", "string"), ("site_id", "string"),
        ("device_id", "string"), ("user_id", "string"), ("vpn_client_version", "string"),
        ("experience_score", "real"), ("vpn_connected", "bool"), ("vpn_latency_ms", "real"),
        ("teams_latency_ms", "real"), ("teams_mos", "real"), ("app_crash_count", "long"),
        ("crash_app_id", "string"), ("cpu_pct", "real"), ("memory_pct", "real"),
    ],
    "tickets_events": [
        ("timestamp", "datetime"), ("event_id", "string"), ("ticket_id", "string"),
        ("event_type", "string"), ("customer_id", "string"), ("site_id", "string"),
        ("user_id", "string"), ("device_id", "string"), ("service_id", "string"),
        ("app_id", "string"), ("issue_code", "string"), ("channel", "string"),
        ("priority", "string"), ("status", "string"), ("zero_touch", "bool"),
        ("escalated_hitl", "bool"), ("major_incident_id", "string"),
    ],
    "conversations": [
        ("timestamp", "datetime"), ("conversation_id", "string"), ("turn_index", "long"),
        ("ticket_id", "string"), ("customer_id", "string"), ("user_id", "string"),
        ("channel", "string"), ("language", "string"), ("speaker", "string"),
        ("agent_id", "string"), ("intent", "string"), ("sentiment", "real"),
        ("resolved_by_ai", "bool"), ("escalated", "bool"),
    ],
    "agent_traces": [
        ("timestamp", "datetime"), ("trace_id", "string"), ("span_id", "string"),
        ("parent_span_id", "string"), ("operation", "string"), ("customer_id", "string"),
        ("conversation_id", "string"), ("agent_id", "string"), ("tool_name", "string"),
        ("model", "string"), ("input_tokens", "long"), ("output_tokens", "long"),
        ("latency_ms", "real"), ("cost_eur", "real"), ("status", "string"),
        ("error_type", "string"), ("eval_groundedness", "real"), ("eval_relevance", "real"),
        ("content_safety_flag", "bool"), ("hitl_escalation", "bool"),
    ],
    "gateway_logs": [
        ("timestamp", "datetime"), ("request_id", "string"), ("trace_id", "string"),
        ("customer_id", "string"), ("agent_id", "string"), ("model", "string"),
        ("prompt_tokens", "long"), ("completion_tokens", "long"), ("status_code", "long"),
        ("latency_ms", "real"), ("retry_attempt", "long"),
    ],
    "csat_events": [
        ("timestamp", "datetime"), ("csat_id", "string"), ("ticket_id", "string"),
        ("customer_id", "string"), ("user_id", "string"), ("channel", "string"),
        ("score", "long"),
    ],
}


def columns(schema: Schema) -> List[str]:
    return [name for name, _ in schema]


def kql_create_merge(table: str) -> str:
    """``.create-merge table`` command for one Eventhouse table (idempotent)."""
    cols = ", ".join(f"['{name}']:{kind}" for name, kind in EVENTHOUSE[table])
    return f".create-merge table {table} ({cols})"
