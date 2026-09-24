"""Offline consistency checks for the Phase 2 Fabric definitions.

Every deploy script builds its item definition from Python structures. These tests keep
those structures honest against each other, with no tenant: a report visual must point
at a real measure or column, a dashboard tile at a real Eventhouse table, an Activator
reference at an entity of the same payload, and so on.
"""
import base64
import json
import re
import uuid

import pytest

from fabric.data.schema import EVENTHOUSE, LAKEHOUSE, LAKEHOUSE_EDGES
from fabric.data_agent import deploy_data_agent as da
from fabric.ontology.deploy_ontology import ENTITIES, RELATIONSHIPS, TIMESERIES
from fabric.powerbi import deploy_report as rpt
from fabric.powerbi.deploy_semantic_model import MEASURES, RELATIONSHIPS as SM_RELS, TABLES
from fabric.rti import deploy_activator as act
from fabric.rti import deploy_dashboard as rtd

WS, ITEM_A, ITEM_B, ITEM_C = (str(uuid.UUID(int=i)) for i in range(1, 5))
MEASURE_NAMES = {(t, m[0]) for t, ms in MEASURES.items() for m in ms}
COLUMN_NAMES = {(t, c) for t in TABLES for c, _ in LAKEHOUSE[t]}


def _walk(node, kind):
    if isinstance(node, dict):
        if kind in node and isinstance(node[kind], dict) and "Property" in node[kind]:
            yield node[kind]["Expression"]["SourceRef"]["Entity"], node[kind]["Property"]
        for v in node.values():
            yield from _walk(v, kind)
    elif isinstance(node, list):
        for v in node:
            yield from _walk(v, kind)


# --- semantic model -------------------------------------------------------------------

def test_semantic_model_tables_exist_in_lakehouse():
    assert set(TABLES) <= set(LAKEHOUSE)


@pytest.mark.parametrize("rel", SM_RELS, ids=lambda r: f"{r[0]}.{r[1]}")
def test_semantic_model_relationships_use_real_columns(rel):
    src, scol, dst, dcol = rel[:4]
    assert (src, scol) in COLUMN_NAMES and (dst, dcol) in COLUMN_NAMES


def test_measure_names_are_unique():
    names = [m[0] for ms in MEASURES.values() for m in ms]
    assert len(names) == len(set(names))


# --- report ---------------------------------------------------------------------------

def test_report_fields_exist_in_the_model():
    pages = rpt.build_pages()
    visuals = [v for _, vs in pages.values() for v in vs]
    assert len(pages) == 3 and len(visuals) >= 20
    measures = set(_walk(visuals, "Measure"))
    columns = set(_walk(visuals, "Column"))
    assert measures and columns
    assert measures <= MEASURE_NAMES, measures - MEASURE_NAMES
    assert columns <= COLUMN_NAMES, columns - COLUMN_NAMES


def test_report_visuals_fit_their_page():
    assert rpt.check_bounds() == []


# --- RTI dashboard --------------------------------------------------------------------

def test_dashboard_tiles_query_real_eventhouse_tables():
    dash = rtd.build_dashboard("t", ["Operations", "AgentOps"], "https://example", "KQL")
    tiles = dash["tiles"]
    assert len(tiles) >= 20
    page_ids = {p["id"] for p in dash["pages"]}
    ids = [t["id"] for t in tiles]
    assert len(ids) == len(set(ids))
    for t in tiles:
        assert t["pageId"] in page_ids
        tables = set(re.findall(r"toscalar\((\w+)", t["query"])) | set(
            re.findall(r"^(\w+)\s*$", t["query"], re.M))
        assert tables and tables <= set(EVENTHOUSE), (t["title"], tables)


# --- Activator ------------------------------------------------------------------------

def test_activator_references_resolve_and_rule_starts_stopped():
    entities = act.build_entities(WS, ITEM_A, "someone@example.com", False)
    act.check_references(entities)
    kinds = [e["type"] for e in entities]
    assert kinds.count("timeSeriesView-v1") >= 5
    blob = json.dumps(entities)
    assert '"shouldRun": false' in blob
    assert "dem_telemetry" in act.SOURCE_QUERY
    assert all(col in {c for c, _ in EVENTHOUSE["dem_telemetry"]}
               for col in ("timestamp", "site_id", "customer_id", "vpn_latency_ms"))


# --- ontology -------------------------------------------------------------------------

def _lakehouse_columns(table):
    if table in LAKEHOUSE_EDGES:
        _, key, fk = LAKEHOUSE_EDGES[table]
        return {key, fk}
    return {c for c, _ in LAKEHOUSE[table]}


@pytest.mark.parametrize("rel", RELATIONSHIPS, ids=lambda r: r[0])
def test_ontology_relationships_bind_real_columns(rel):
    name, src, dst, table, skeys, dkeys = rel
    entity_names = {e[0] for e in ENTITIES}
    assert src in entity_names and dst in entity_names
    cols = _lakehouse_columns(table)
    assert set(skeys) <= cols and set(dkeys) <= cols


def test_ontology_timeseries_bind_eventhouse_columns():
    for entity, (table, ts, key, *_) in TIMESERIES.items():
        cols = {c for c, _ in EVENTHOUSE[table]}
        assert ts in cols and key in cols, entity


@pytest.mark.parametrize("edge", sorted(LAKEHOUSE_EDGES))
def test_lakehouse_edges_derive_from_real_columns(edge):
    source, key, fk = LAKEHOUSE_EDGES[edge]
    assert edge not in LAKEHOUSE
    assert {key, fk} <= {c for c, _ in LAKEHOUSE[source]}


# --- Data Agent -----------------------------------------------------------------------

def _parts():
    return da.build_parts(WS, "ServiceDesk_Analyst", (ITEM_A, "ONT_ServiceDesk"),
                          (ITEM_B, "SM_ServiceDesk_Analytics"), (ITEM_C, "KQL_ServiceDesk"))


def test_data_agent_publishes_three_sources():
    parts = _parts()
    paths = [p["path"] for p in parts]
    assert len(paths) == len(set(paths))
    for tree in ("draft", "published"):
        sources = [p for p in paths if p.startswith(f"Files/Config/{tree}/")
                   and p.endswith("datasource.json")]
        assert len(sources) == 3, (tree, sources)
    types = {json.loads(base64.b64decode(p["payload"]))["type"]
             for p in parts if p["path"].endswith("datasource.json")}
    assert types == {"ontology", "semantic_model", "kusto"}


def test_data_agent_fewshots_reference_real_objects():
    labels = {e[0] for e in ENTITIES} | {r[0] for r in RELATIONSHIPS}
    for _, q in da.GQL_FEWSHOTS:
        for label in re.findall(r"[(\[]\w*:(\w+)", q):
            assert label in labels, (label, q)
    measure_names = {m for _, m in MEASURE_NAMES}
    for _, q in da.DAX_FEWSHOTS:
        for m in re.findall(r"(?<![\w'])\[([^\]]+)\]", q):
            if not m[0].isupper() or " " in m or "(" in m or "%" in m:
                assert m in measure_names or m in {"Breaches"}, (m, q)
    for _, q in da.KQL_FEWSHOTS:
        assert any(t in q for t in EVENTHOUSE), q


def test_data_agent_customer_mapping_covers_every_customer():
    lines = da._customer_lines()
    assert "Fabrikam = \"Fabrikam Industries\" (CUS-FAB)" in lines
    assert lines.count("CUS-") == 6


def test_data_agent_breach_rule_names_real_measures():
    measures = {m[0] for ms in da.MEASURES.values() for m in ms}
    for name in ("XLA Breaches (Last Closed Week)", "XLA Credit (Last Closed Week)"):
        assert name in measures
        assert f"[{name}]" in da.AI_INSTRUCTIONS
    assert "never invent" in da.AI_INSTRUCTIONS
