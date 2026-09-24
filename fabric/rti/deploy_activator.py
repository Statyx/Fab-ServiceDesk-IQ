#!/usr/bin/env python3
"""Deploy the ``ACT_ServiceDesk_Alerts`` Activator (Reflex) over ``KQL_ServiceDesk``.

One alert, the one the story needs: *a site's VPN latency crosses 200 ms*. The graph
(Fabric REST "Reflex definition" + microsoft/skills-for-fabric activator-cli shapes):

  Container (kqlQueries)
  +- kqlSource      dem_telemetry every 60 s, time-axis mode (startTime/endTime params)
  +- SourceEvent    the source's rows
  +- Object "Site"  + SplitEvent keyed on site_id
     +- IdentityPartAttribute  site_id
     +- BasicEventAttribute    vpn_latency_ms, customer_id
     +- AttributeTrigger rule  avg(vpn_latency_ms) over 5 min BECOMES > 200 -> Teams

The KQL returns all rows in the window; the rule does the detection (Activator rule 7).
The rule is deployed STOPPED (``shouldRun: false``) unless ``activator.start: true`` in
config: a running rule polls the Eventhouse every minute on a shared capacity. Start it
in the Fabric UI (or set the flag and redeploy) just before the live demo.

The recipient is ``activator.teams_recipient``, falling back to
``deployment.expected_account`` while the former is still a placeholder.

  python -m fabric.rti.deploy_activator
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List

import requests

from fabric._shared.helpers import (deploy_context, fabric_headers, find_item_or_none,
                                    is_placeholder, part, print_step, require_state,
                                    save_state, wait_lro)

NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "https://github.com/Statyx/Fab-ServiceDesk-IQ/activator")
TEMPLATE_VERSION = "1.2.4"
LATENCY_THRESHOLD_MS = 200.0
WINDOW_MS = 5 * 60 * 1000.0

SOURCE_QUERY = ("declare query_parameters(startTime:datetime, endTime:datetime);\n"
                "dem_telemetry\n"
                "| where timestamp between (startTime .. endTime)\n"
                "| project timestamp, site_id, customer_id, device_id, vpn_latency_ms, "
                "experience_score")


def sid(key: str) -> str:
    return str(uuid.uuid5(NAMESPACE, key))


def ref(kind: str, entity_id: str, name: str) -> Dict:
    return {"kind": kind, "type": "complex", "name": name,
            "arguments": [{"name": "entityId", "type": "string", "value": entity_id}]}


def instance(template_id: str, steps: List[Dict]) -> str:
    """``definition.instance`` is a JSON *string*, never a nested object."""
    return json.dumps({"templateId": template_id, "templateVersion": TEMPLATE_VERSION,
                       "steps": steps}, separators=(",", ":"))


def view(key: str, name: str, container: str, vtype: str, inst: str = None,
         parent_object: str = None, settings: Dict = None) -> Dict:
    definition: Dict = {"type": vtype}
    if inst is not None:
        definition["instance"] = inst
    if settings is not None:
        definition["settings"] = settings
    payload: Dict = {"name": name, "parentContainer": {"targetUniqueIdentifier": container},
                     "definition": definition}
    if parent_object:
        payload["parentObject"] = {"targetUniqueIdentifier": parent_object}
    return {"uniqueIdentifier": sid(key), "payload": payload, "type": "timeSeriesView-v1"}


def type_assertion(op: str) -> Dict:
    return {"name": "TypeAssertion", "kind": "TypeAssertion",
            "arguments": [{"name": "op", "type": "string", "value": op},
                          {"name": "format", "type": "string", "value": ""}]}


def event_attribute(key: str, name: str, container: str, obj: str, event: str,
                    field: str, op: str) -> Dict:
    return view(key, name, container, "Attribute", instance("BasicEventAttribute", [
        {"name": "EventSelectStep", "id": sid(key + ".select"), "rows": [
            {"name": "EventSelector", "kind": "Event",
             "arguments": [ref("EventReference", event, "event")]},
            {"name": "EventFieldSelector", "kind": "EventField",
             "arguments": [{"name": "fieldName", "type": "string", "value": field}]}]},
        {"name": "EventComputeStep", "id": sid(key + ".compute"),
         "rows": [type_assertion(op)]}]), parent_object=obj)


def text(value: str) -> Dict:
    return {"type": "string", "value": value}


def build_entities(ws: str, kql_db_id: str, recipient: str, should_run: bool) -> List[Dict]:
    container, source, event = sid("container"), sid("source"), sid("event")
    obj, split = sid("object.site"), sid("split.site")
    site_attr, latency_attr, customer_attr = sid("attr.site"), sid("attr.latency"), sid("attr.customer")
    start = (datetime.now(timezone.utc) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    end = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    rule = view("rule.vpn", "Site VPN latency above 200 ms", container, "Rule", instance(
        "AttributeTrigger", [
            {"name": "ScalarSelectStep", "id": sid("rule.vpn.select"), "rows": [
                {"name": "AttributeSelector", "kind": "Attribute",
                 "arguments": [ref("AttributeReference", latency_attr, "attribute")]},
                {"name": "NumberSummary", "kind": "NumberSummary", "arguments": [
                    {"name": "op", "type": "string", "value": "Average"},
                    {"kind": "TimeDrivenWindowSpec", "type": "complex", "name": "window",
                     "arguments": [{"name": "width", "type": "timeSpan", "value": WINDOW_MS},
                                   {"name": "hop", "type": "timeSpan", "value": WINDOW_MS}]}]}]},
            {"name": "ScalarDetectStep", "id": sid("rule.vpn.detect"), "rows": [
                {"name": "NumberBecomes", "kind": "NumberBecomes", "arguments": [
                    {"name": "op", "type": "string", "value": "BecomesGreaterThan"},
                    {"name": "value", "type": "number", "value": LATENCY_THRESHOLD_MS}]},
                {"name": "OccurrenceOption", "kind": "EachTime", "arguments": []}]},
            {"name": "ActStep", "id": sid("rule.vpn.act"), "rows": [
                {"name": "TeamsBinding", "kind": "TeamsMessage", "arguments": [
                    {"name": "messageLocale", "type": "string", "value": ""},
                    {"name": "recipients", "type": "array", "values": [text(recipient)]},
                    {"name": "headline", "type": "array", "values": [
                        text("Zava Service Desk: VPN latency above 200 ms at a customer site")]},
                    {"name": "optionalMessage", "type": "array", "values": [
                        text("Average VPN latency over the last 5 minutes crossed 200 ms. "
                             "Check the RTD_ServiceDesk_Operations dashboard and ask the "
                             "ServiceDesk_Analyst agent which contract and XLA are at risk.")]},
                    {"name": "additionalInformation", "type": "array", "values": [
                        {"kind": "NameReferencePair", "type": "complex", "arguments": [
                            {"name": "name", "type": "string", "value": "Customer"},
                            {"name": "reference", "kind": "AttributeReference",
                             "type": "complexReference",
                             "arguments": [{"name": "entityId", "type": "string",
                                            "value": customer_attr}]}]}]}]}]}]),
        parent_object=obj, settings={"shouldRun": should_run, "shouldApplyRuleOnUpdate": False})

    return [
        {"uniqueIdentifier": container, "type": "container-v1",
         "payload": {"name": "Service desk telemetry", "type": "kqlQueries"}},
        {"uniqueIdentifier": source, "type": "kqlSource-v1", "payload": {
            "name": "dem_telemetry (KQL_ServiceDesk)",
            "runSettings": {"executionIntervalInSeconds": 60},
            "query": {"queryString": SOURCE_QUERY},
            "eventhouseItem": {"itemId": kql_db_id, "workspaceId": ws,
                               "itemType": "KustoDatabase"},
            "queryParameters": [{"name": "startTime", "type": "DURATION_START", "value": start},
                                {"name": "endTime", "type": "DURATION_END", "value": end}],
            "eventTimeSettings": {"timeFieldName": "timestamp", "ingestionDelayInSeconds": 60,
                                  "timeZone": "UTC"},
            "metadata": {"workspaceId": ws, "measureName": "", "querySetId": "", "queryId": ""},
            "parentContainer": {"targetUniqueIdentifier": container}}},
        view("event", "DEM telemetry", container, "Event", instance("SourceEvent", [
            {"name": "SourceEventStep", "id": sid("event.step"), "rows": [
                {"name": "SourceSelector", "kind": "SourceReference",
                 "arguments": [{"name": "entityId", "type": "string", "value": source}]}]}])),
        view("object.site", "Site", container, "Object"),
        view("split.site", "Site events", container, "Event", instance("SplitEvent", [
            {"name": "SplitEventStep", "id": sid("split.step"), "rows": [
                {"name": "EventSelector", "kind": "Event",
                 "arguments": [ref("EventReference", event, "event")]},
                {"name": "FieldIdMapping", "kind": "FieldIdMapping", "arguments": [
                    {"name": "fieldName", "type": "string", "value": "site_id"},
                    ref("AttributeReference", site_attr, "idPart")]},
                {"name": "SplitEventOptions", "kind": "EventOptions", "arguments": [
                    {"name": "isAuthoritative", "type": "boolean", "value": True}]}]}]),
             parent_object=obj),
        view("attr.site", "site_id", container, "Attribute", instance("IdentityPartAttribute", [
            {"name": "IdPartStep", "id": sid("attr.site.step"),
             "rows": [type_assertion("Text")]}]), parent_object=obj),
        event_attribute("attr.latency", "VPN latency (ms)", container, obj, split,
                        "vpn_latency_ms", "Number"),
        event_attribute("attr.customer", "customer_id", container, obj, split,
                        "customer_id", "Text"),
        rule,
    ]


def check_references(entities: List[Dict]) -> None:
    """Every GUID an entity points at must be in the same payload (FailedToResolveEntity)."""
    ids = {e["uniqueIdentifier"] for e in entities}
    for e in entities:
        p = e["payload"]
        for key in ("parentContainer", "parentObject"):
            if key in p and p[key]["targetUniqueIdentifier"] not in ids:
                raise RuntimeError(f"{p['name']}: dangling {key}")
    for e in entities:
        inst = e["payload"].get("definition", {}).get("instance")
        if not inst:
            continue
        for chunk in inst.split('"entityId","type":"string","value":"')[1:]:
            target = chunk.split('"', 1)[0]
            if target not in ids:
                raise RuntimeError(f"{e['payload']['name']}: dangling entityId {target}")


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    act = cfg.get("activator") or {}
    name = act.get("name", "ACT_ServiceDesk_Alerts")
    recipient = act.get("teams_recipient")
    if is_placeholder(recipient):
        recipient = cfg["deployment"]["expected_account"]
    should_run = bool(act.get("start", False))
    kql_db_id = require_state(state, "kql_database_id")

    print_step(1, 3, "Build ReflexEntities.json")
    entities = build_entities(ws, kql_db_id, recipient, should_run)
    check_references(entities)
    print(f"   {len(entities)} entities, rule "
          f"{'RUNNING' if should_run else 'STOPPED'}, recipient {recipient.split('@')[0]}@...")

    print_step(2, 3, f"Create or update Activator '{name}'")
    headers = fabric_headers(token)
    definition = {"parts": [part("ReflexEntities.json", entities)]}
    item = find_item_or_none(token, api, ws, name, "Reflex")
    if item:
        resp = requests.post(f"{api}/workspaces/{ws}/reflexes/{item['id']}/updateDefinition",
                             headers=headers, json={"definition": definition}, timeout=120)
        wait_lro(token, api, resp, f"updateDefinition Reflex '{name}'")
        print(f"   updated {item['id']}")
    else:
        resp = requests.post(f"{api}/workspaces/{ws}/reflexes", headers=headers, timeout=120,
                             json={"displayName": name,
                                   "description": "Zava Service Desk alerts: site VPN latency",
                                   "definition": definition})
        wait_lro(token, api, resp, f"Create Reflex '{name}'")
        item = find_item_or_none(token, api, ws, name, "Reflex")
        if not item:
            raise RuntimeError(f"Reflex '{name}' not found after create")
        print(f"   created {item['id']}")

    print_step(3, 3, "Persist state")
    state["activator_id"] = item["id"]
    save_state(state)
    print("   activator_id saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
