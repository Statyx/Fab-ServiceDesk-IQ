#!/usr/bin/env python3
"""Deploy the ``ONT_ServiceDesk`` ontology (Fabric IQ) over the Lakehouse and Eventhouse.

13 entity types, bound NonTimeSeries to their Lakehouse table, plus two TimeSeries
bindings on the Eventhouse: Device <- ``dem_telemetry`` and Agent <- ``agent_traces``.
Every property comes from ``fabric/data/schema.py`` (name = column, type mapped), so the
ontology can never drift from the Delta tables.

Deploying through REST does NOT populate the child Graph Model: run
``python -m fabric.graph.deploy_graph`` afterwards.

  python -m fabric.ontology.deploy_ontology
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import hashlib
import uuid
from typing import Dict, List, Tuple

from fabric._shared.helpers import (create_fabric_item, deploy_context, find_item_or_none,
                                    part, print_step, require_state, save_state,
                                    update_definition)
from fabric.data.schema import EVENTHOUSE, LAKEHOUSE

VT = {"string": "String", "bigint": "BigInt", "double": "Double",
      "datetime": "DateTime", "boolean": "Boolean"}
KQL_VT = {"string": "String", "long": "BigInt", "real": "Double",
          "datetime": "DateTime", "bool": "Boolean"}

# (entity, lakehouse table, key column). Properties = every column of the table.
ENTITY_TABLES: List[Tuple[str, str, str]] = [
    ("Customer", "dim_customer", "customer_id"),
    ("Site", "dim_site", "site_id"),
    ("User", "dim_user", "user_id"),
    ("Device", "dim_device", "device_id"),
    ("Application", "dim_application", "app_id"),
    ("Service", "dim_service", "service_id"),
    ("Ticket", "fact_ticket", "ticket_id"),
    ("MajorIncident", "fact_major_incident", "major_incident_id"),
    ("KbArticle", "dim_kb_article", "kb_id"),
    ("Agent", "dim_agent", "agent_id"),
    ("McpTool", "dim_mcp_tool", "tool_id"),
    ("Contract", "dim_contract", "contract_id"),
    ("Xla", "dim_xla", "xla_id"),
]

# (name, lakehouse_table, key_cols[], cols=[(col, type)]) — the shape deploy_graph reads.
ENTITIES = [(name, table, [key], list(LAKEHOUSE[table])) for name, table, key in ENTITY_TABLES]

# Default display = first non-key string column; override where that is a foreign key.
DISPLAY_PROPERTY = {
    "Site": "site_name", "Device": "device_id", "Ticket": "ticket_id",
    "MajorIncident": "title", "KbArticle": "title", "Contract": "contract_name",
    "Xla": "metric_label",
}

# (name, source, target, fk_table, source_key_cols[], target_fk_cols[])
# BOTH column lists are columns OF fk_table: the one identifying the source, and the one
# holding the target's key. Getting this backwards yields an empty graph, not an error.
# Nullable foreign keys go through the edge_* tables (schema.LAKEHOUSE_EDGES).
RELATIONSHIPS = [
    ("CustomerHasSite", "Customer", "Site", "dim_site", ["customer_id"], ["site_id"]),
    ("CustomerHasContract", "Customer", "Contract", "dim_contract", ["customer_id"], ["contract_id"]),
    ("ContractDefinesXla", "Contract", "Xla", "dim_xla", ["contract_id"], ["xla_id"]),
    ("SiteHostsUser", "Site", "User", "dim_user", ["site_id"], ["user_id"]),
    ("UserUsesDevice", "User", "Device", "dim_device", ["user_id"], ["device_id"]),
    ("DeviceRunsApplication", "Device", "Application", "bridge_device_application",
     ["device_id"], ["app_id"]),
    ("TicketRaisedBy", "Ticket", "User", "fact_ticket", ["ticket_id"], ["user_id"]),
    ("TicketAboutDevice", "Ticket", "Device", "fact_ticket", ["ticket_id"], ["device_id"]),
    ("TicketForService", "Ticket", "Service", "fact_ticket", ["ticket_id"], ["service_id"]),
    ("TicketForApplication", "Ticket", "Application", "fact_ticket", ["ticket_id"], ["app_id"]),
    ("TicketUsesKb", "Ticket", "KbArticle", "fact_ticket", ["ticket_id"], ["kb_id"]),
    ("TicketForCustomer", "Ticket", "Customer", "fact_ticket", ["ticket_id"], ["customer_id"]),
    ("TicketPartOfIncident", "Ticket", "MajorIncident", "edge_ticket_major_incident",
     ["ticket_id"], ["major_incident_id"]),
    ("TicketResolvedBy", "Ticket", "Agent", "edge_ticket_agent",
     ["ticket_id"], ["resolved_by_agent_id"]),
    ("MajorIncidentForCustomer", "MajorIncident", "Customer", "fact_major_incident",
     ["major_incident_id"], ["customer_id"]),
    ("MajorIncidentAffectsSite", "MajorIncident", "Site", "fact_major_incident",
     ["major_incident_id"], ["site_id"]),
    ("MajorIncidentCausedByApp", "MajorIncident", "Application", "fact_major_incident",
     ["major_incident_id"], ["app_id"]),
    ("KbDocumentsService", "KbArticle", "Service", "dim_kb_article", ["kb_id"], ["service_id"]),
    ("AgentCallsTool", "Agent", "McpTool", "bridge_agent_tool", ["agent_id"], ["tool_id"]),
]

# entity -> (kql_table, timestamp_col, entity_key_col, [metric cols])
TIMESERIES_SPEC = {
    "Device": ("dem_telemetry", "timestamp", "device_id",
               ["experience_score", "vpn_latency_ms", "teams_mos", "app_crash_count"]),
    "Agent": ("agent_traces", "timestamp", "agent_id",
              ["latency_ms", "cost_eur", "input_tokens", "output_tokens"]),
}


def _kql_type(table: str, col: str) -> str:
    return KQL_VT[dict(EVENTHOUSE[table])[col]]


TIMESERIES: Dict[str, Tuple[str, str, str, List[Tuple[str, str]]]] = {
    ent: (tbl, ts, key, [(m, _kql_type(tbl, m)) for m in metrics])
    for ent, (tbl, ts, key, metrics) in TIMESERIES_SPEC.items()
}


def det_guid(seed: str) -> str:
    return str(uuid.UUID(bytes=hashlib.md5(seed.encode("utf-8")).digest()))


def build_parts(workspace_id: str, lakehouse_id: str, ontology_name: str,
                kql_db_id: str, cluster_uri: str, kql_db_name: str) -> List[Dict]:
    et_id, prop_id, key_prop = {}, {}, {}
    for i, (name, _table, keys, cols) in enumerate(ENTITIES):
        eid = str(1001 + i)
        et_id[name] = eid
        base = 10000 + i * 100
        for j, (col, _t) in enumerate(cols):
            prop_id[(name, col)] = str(base + 1 + j)
        key_prop[name] = [prop_id[(name, k)] for k in keys]

    platform = {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/gitIntegration/"
                   "platformProperties/2.0.0/schema.json",
        "metadata": {"type": "Ontology", "displayName": ontology_name,
                     "description": f"Zava Service Desk knowledge graph ({len(ENTITIES)} "
                                    f"entities, {len(RELATIONSHIPS)} relationships)."},
        "config": {"version": "2.0", "logicalId": det_guid("ONT-ZAVA-SERVICEDESK-logicalId")},
    }
    parts = [part(".platform", platform), part("definition.json", {})]

    for name, table, keys, cols in ENTITIES:
        eid = et_id[name]
        i = int(eid) - 1001
        disp_col = DISPLAY_PROPERTY.get(name)
        if not disp_col:
            non_key = [c for c, t in cols if t == "string" and c not in keys]
            disp_col = non_key[0] if non_key else keys[0]
        properties = [{"id": prop_id[(name, c)], "name": c, "redefines": None,
                       "baseTypeNamespaceType": None, "valueType": VT[t]} for c, t in cols]

        ts_props, ts_part = [], None
        if name in TIMESERIES:
            kql_table, ts_col, key_col, metrics = TIMESERIES[name]
            tsb = 40000 + i * 100
            ts_props = [{"id": str(tsb + 1), "name": ts_col, "redefines": None,
                         "baseTypeNamespaceType": None, "valueType": "DateTime"}]
            pbinds = [{"sourceColumnName": key_col, "targetPropertyId": prop_id[(name, key_col)]},
                      {"sourceColumnName": ts_col, "targetPropertyId": str(tsb + 1)}]
            for j, (mcol, vt) in enumerate(metrics):
                pid = str(tsb + 2 + j)
                ts_props.append({"id": pid, "name": mcol, "redefines": None,
                                 "baseTypeNamespaceType": None, "valueType": vt})
                pbinds.append({"sourceColumnName": mcol, "targetPropertyId": pid})
            ts_guid = det_guid(f"TimeSeries-{eid}")
            ts_binding = {"id": ts_guid, "dataBindingConfiguration": {
                "dataBindingType": "TimeSeries", "timestampColumnName": ts_col,
                "propertyBindings": pbinds,
                "sourceTableProperties": {"sourceType": "KustoTable", "workspaceId": workspace_id,
                                          "itemId": kql_db_id, "clusterUri": cluster_uri,
                                          "databaseName": kql_db_name,
                                          "sourceTableName": kql_table}}}
            ts_part = part(f"EntityTypes/{eid}/DataBindings/{ts_guid}.json", ts_binding)

        entity_def = {
            "id": eid, "namespace": "usertypes", "baseEntityTypeId": None, "name": name,
            "entityIdParts": key_prop[name], "displayNamePropertyId": prop_id[(name, disp_col)],
            "namespaceType": "Custom", "visibility": "Visible",
            "properties": properties, "timeseriesProperties": ts_props,
        }
        parts.append(part(f"EntityTypes/{eid}/definition.json", entity_def))

        bind_guid = det_guid(f"NonTimeSeries-{eid}")
        binding = {"id": bind_guid, "dataBindingConfiguration": {
            "dataBindingType": "NonTimeSeries",
            "propertyBindings": [{"sourceColumnName": c, "targetPropertyId": prop_id[(name, c)]}
                                 for c, _t in cols],
            "sourceTableProperties": {"sourceType": "LakehouseTable", "workspaceId": workspace_id,
                                      "itemId": lakehouse_id, "sourceTableName": table,
                                      "sourceSchema": "dbo"}}}
        parts.append(part(f"EntityTypes/{eid}/DataBindings/{bind_guid}.json", binding))
        if ts_part:
            parts.append(ts_part)

    for k, (rname, src, tgt, fk_table, src_keys, tgt_fks) in enumerate(RELATIONSHIPS):
        rid = str(3001 + k)
        rel_def = {"namespace": "usertypes", "id": rid, "name": rname, "namespaceType": "Custom",
                   "source": {"entityTypeId": et_id[src]}, "target": {"entityTypeId": et_id[tgt]}}
        parts.append(part(f"RelationshipTypes/{rid}/definition.json", rel_def))
        ctx_guid = det_guid(f"Ctx-{rid}")
        ctx = {"id": ctx_guid,
               "dataBindingTable": {"workspaceId": workspace_id, "itemId": lakehouse_id,
                                    "sourceTableName": fk_table, "sourceSchema": "dbo",
                                    "sourceType": "LakehouseTable"},
               "sourceKeyRefBindings": [{"sourceColumnName": c, "targetPropertyId": key_prop[src][n]}
                                        for n, c in enumerate(src_keys)],
               "targetKeyRefBindings": [{"sourceColumnName": c, "targetPropertyId": key_prop[tgt][n]}
                                        for n, c in enumerate(tgt_fks)]}
        parts.append(part(f"RelationshipTypes/{rid}/Contextualizations/{ctx_guid}.json", ctx))
    return parts


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    lh = require_state(state, "lakehouse_id")
    kql_db_id = require_state(state, "kql_database_id")
    cluster_uri = require_state(state, "kusto_query_uri")
    kql_db_name = cfg["eventhouse"]["kql_database"]
    name = cfg["ontology"]["name"]
    print(f"Ontology '{name}': {len(ENTITIES)} entities, {len(RELATIONSHIPS)} relationships, "
          f"{len(TIMESERIES)} TimeSeries bindings")

    print_step(1, 4, "Build definition parts")
    parts = build_parts(ws, lh, name, kql_db_id, cluster_uri, kql_db_name)
    print(f"   {len(parts)} parts")

    print_step(2, 4, "Create or find the Ontology item")
    item = find_item_or_none(token, api, ws, name, "Ontology")
    if item is None:
        item = create_fabric_item(token, api, ws, name, "Ontology",
                                  "Zava Service Desk knowledge graph (Fabric IQ)")
        print(f"   created {item['id']}")
    else:
        print(f"   reusing {item['id']}")

    print_step(3, 4, "Push the full definition (updateDefinition)")
    update_definition(token, api, ws, item["id"], {"parts": parts}, f"Ontology '{name}'")
    print("   accepted")

    print_step(4, 4, "Persist state")
    state["ontology_id"] = item["id"]
    save_state(state)
    print("   ontology_id saved. Next: python -m fabric.graph.deploy_graph")
    return 0


if __name__ == "__main__":
    sys.exit(main())
