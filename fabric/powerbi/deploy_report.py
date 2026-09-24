#!/usr/bin/env python3
"""Deploy the ``RPT_ServiceDesk`` Power BI report (PBIR) over ``SM_ServiceDesk_Analytics``.

Three pages: Service Desk Overview (zero-touch this week vs last), Experience &
Incidents, XLA & Credits. The PBIR folder is built in memory and never written to the
repo: its connection string carries the semantic model id.

PBIR rules carried over from the sibling demos (a report that validates can still hang
on "Loading your report..."): version.json 2.0.0, report.json with reportSource +
settings + objects, a real built-in base theme shipped with its json, visualContainer
schema 2.9.0 (2.10.0+ return 404), every formatting value a PBIR literal, and every
visual inside the 1280x720 canvas. updateDefinition is a FULL replace.

  python -m fabric.powerbi.deploy_report
"""
import os, sys
from fabric._shared.platform_env import bootstrap
bootstrap()

import json
from typing import Dict, List, Tuple

from fabric._shared.helpers import (create_fabric_item, deploy_context, find_item_or_none,
                                    part, print_step, require_config, require_state,
                                    save_state, update_definition)

S = "https://developer.microsoft.com/json-schemas/fabric/item/report/definition"
SCHEMA_VISUAL = f"{S}/visualContainer/2.9.0/schema.json"
SCHEMA_PAGE = f"{S}/page/2.1.0/schema.json"
SCHEMA_PAGES = f"{S}/pagesMetadata/1.1.0/schema.json"
SCHEMA_REPORT = f"{S}/report/3.3.0/schema.json"
SCHEMA_VERSION = f"{S}/versionMetadata/1.0.0/schema.json"
SCHEMA_PBIR = ("https://developer.microsoft.com/json-schemas/fabric/item/report/"
               "definitionProperties/2.0.0/schema.json")
THEME_NAME = "CY26SU05"
CANVAS_W, CANVAS_H = 1280, 720

INK, CARD_BG, PAGE_BG = "'#1B1F3B'", "'#FFFFFF'", "'#F3F4F8'"
ACCENT, WARN, GOOD = "'#118DFF'", "'#D64550'", "'#1AAB40'"


def s(v): return {"expr": {"Literal": {"Value": f"'{v}'"}}}
def d(v): return {"expr": {"Literal": {"Value": f"{v}D"}}}
def i(v): return {"expr": {"Literal": {"Value": f"{v}L"}}}
def b(v): return {"expr": {"Literal": {"Value": "true" if v else "false"}}}
def color(hex_padded): return {"solid": {"color": {"expr": {"Literal": {"Value": hex_padded}}}}}


def measure(entity, name):
    return {"field": {"Measure": {"Expression": {"SourceRef": {"Entity": entity}},
                                  "Property": name}},
            "queryRef": f"{entity}.{name}", "nativeQueryRef": name}


def column(entity, name):
    return {"field": {"Column": {"Expression": {"SourceRef": {"Entity": entity}},
                                 "Property": name}},
            "queryRef": f"{entity}.{name}", "nativeQueryRef": name}


def _chrome(text, size=11):
    return {
        "title": [{"properties": {"show": b(True), "text": s(text), "fontSize": d(size),
                                  "bold": b(True), "fontColor": color(INK)}}],
        "background": [{"properties": {"show": b(True), "color": color(CARD_BG),
                                       "transparency": i(0)}}],
        "dropShadow": [{"properties": {"show": b(True), "color": color("'#000000'"),
                                       "transparency": i(92), "shadowBlur": i(8),
                                       "preset": s("BottomRight"), "position": s("Outer")}}],
        "border": [{"properties": {"show": b(False)}}],
    }


def _visual(name, x, y, w, h, z, body):
    return {"$schema": SCHEMA_VISUAL, "name": name,
            "position": {"x": x, "y": y, "z": z, "width": w, "height": h, "tabOrder": 0},
            "visual": body}


def card(name, x, y, w, title, entity, m, value_color=INK):
    return _visual(name, x, y, w, 120, 1500, {
        "visualType": "cardVisual",
        "query": {"queryState": {"Data": {"projections": [measure(entity, m)]}},
                  "sortDefinition": {"sort": [], "isDefaultSort": True}},
        "objects": {"value": [{"properties": {"fontSize": d(26), "bold": b(True),
                                              "fontColor": color(value_color)}}]},
        "visualContainerObjects": _chrome(title, 10), "drillFilterOtherVisuals": True})


def bar(name, x, y, w, h, title, cat, measures: List[Tuple[str, str]], vtype="barChart"):
    first = measures[0]
    return _visual(name, x, y, w, h, 1000, {
        "visualType": vtype,
        "query": {"queryState": {"Category": {"projections": [column(*cat)]},
                                 "Y": {"projections": [measure(e, m) for e, m in measures]}},
                  "sortDefinition": {"sort": [{"field": {"Measure": {
                      "Expression": {"SourceRef": {"Entity": first[0]}}, "Property": first[1]}},
                      "direction": "Descending"}], "isDefaultSort": False}},
        "objects": {"legend": [{"properties": {"show": b(len(measures) > 1),
                                               "position": s("Top")}}],
                    "labels": [{"properties": {"show": b(True)}}]},
        "visualContainerObjects": _chrome(title), "drillFilterOtherVisuals": True})


def line(name, x, y, w, h, title, cat, measures: List[Tuple[str, str]]):
    return _visual(name, x, y, w, h, 1000, {
        "visualType": "lineChart",
        "query": {"queryState": {"Category": {"projections": [column(*cat)]},
                                 "Y": {"projections": [measure(e, m) for e, m in measures]}},
                  "sortDefinition": {"sort": [{"field": {"Column": {
                      "Expression": {"SourceRef": {"Entity": cat[0]}}, "Property": cat[1]}},
                      "direction": "Ascending"}], "isDefaultSort": False}},
        "objects": {"legend": [{"properties": {"show": b(len(measures) > 1),
                                               "position": s("Top")}}],
                    "labels": [{"properties": {"show": b(False)}}]},
        "visualContainerObjects": _chrome(title), "drillFilterOtherVisuals": True})


def table(name, x, y, w, h, title, cols, measures=()):
    projections = [column(e, c) for e, c in cols] + [measure(e, m) for e, m in measures]
    return _visual(name, x, y, w, h, 1000, {
        "visualType": "tableEx",
        "query": {"queryState": {"Values": {"projections": projections}},
                  "sortDefinition": {"sort": [], "isDefaultSort": True}},
        "objects": {"grid": [{"properties": {"gridVertical": b(True)}}]},
        "visualContainerObjects": _chrome(title), "drillFilterOtherVisuals": True})


def slicer(name, x, y, w, h, entity, col, title):
    return _visual(name, x, y, w, h, 2000, {
        "visualType": "slicer",
        "query": {"queryState": {"Values": {"projections": [column(entity, col)]}},
                  "sortDefinition": {"sort": [], "isDefaultSort": True}},
        "objects": {"data": [{"properties": {"mode": s("Dropdown")}}]},
        "visualContainerObjects": {
            "title": [{"properties": {"show": b(True), "text": s(title), "fontSize": d(10),
                                      "bold": b(True), "fontColor": color(INK)}}],
            "background": [{"properties": {"show": b(True), "color": color(CARD_BG)}}],
            "border": [{"properties": {"show": b(False)}}]},
        "drillFilterOtherVisuals": True})


def header(key, title, subtitle):
    """A textbox carries no query (a non-data visual with a query is a defect)."""
    paragraphs = [{"textRuns": [{"value": title, "textStyle": {
                      "fontSize": "18pt", "fontWeight": "bold", "color": INK.strip("'")}}]},
                  {"textRuns": [{"value": subtitle, "textStyle": {
                      "fontSize": "10pt", "fontWeight": "normal", "color": "#5A6070"}}]}]
    return _visual(f"hdr_{key}", 24, 16, 900, 56, 500, {
        "visualType": "textbox",
        "objects": {"general": [{"properties": {"paragraphs": paragraphs}}]},
        "visualContainerObjects": {"border": [{"properties": {"show": b(False)}}]}})


def page(page_id, display_name):
    return {"$schema": SCHEMA_PAGE, "name": page_id, "displayName": display_name,
            "displayOption": "FitToPage", "height": CANVAS_H, "width": CANVAS_W,
            "visualInteractions": [],
            "objects": {"background": [{"properties": {"color": color(PAGE_BG),
                                                       "transparency": i(0)}}]}}


CUSTOMER = ("dim_customer", "customer_name")
WEEK = ("dim_date", "week_start")


def build_pages() -> Dict[str, Tuple[Dict, List[Dict]]]:
    """24 px margin, 16 px gutter, 1232 px usable width."""
    ft, xla = "fact_ticket", "fact_xla_evaluation"
    overview = [
        header("ov", "Zava Service Desk - Overview",
               "Zero-touch resolution this (last closed) week vs the week before, per customer."),
        slicer("slc_customer", 1016, 16, 240, 56, *CUSTOMER, "Customer"),
        card("card_tickets", 24, 88, 236, "Tickets (last closed week)", ft,
             "Tickets (Last Closed Week)"),
        card("card_zt", 272, 88, 236, "Zero-touch (last closed week)", ft,
             "Zero-Touch % (Last Closed Week)", ACCENT),
        card("card_zt_delta", 520, 88, 236, "Change vs previous week (pts)", ft,
             "Zero-Touch Change (pts)", WARN),
        card("card_csat", 768, 88, 236, "CSAT (1-5)", "fact_csat", "CSAT Avg"),
        card("card_credit", 1016, 88, 240, "XLA credit, last closed week", xla,
             "XLA Credit (Last Closed Week)", WARN),
        line("line_zt_trend", 24, 228, 608, 268, "Zero-touch % by week vs target", WEEK,
             [(ft, "Zero-Touch %"), (ft, "Zero-Touch Target %")]),
        bar("bar_zt_customer", 648, 228, 608, 268, "Zero-touch %: last closed vs previous week",
            CUSTOMER, [(ft, "Zero-Touch % (Last Closed Week)"),
                       (ft, "Zero-Touch % (Previous Week)")], "clusteredBarChart"),
        table("tbl_customers", 24, 512, 1232, 184, "Customers this week",
              [CUSTOMER],
              [(ft, "Tickets (Last Closed Week)"), (ft, "Zero-Touch % (Last Closed Week)"),
               (ft, "Zero-Touch % (Previous Week)"), (ft, "Zero-Touch Target %"),
               (xla, "XLA Breaches (Last Closed Week)"), (xla, "XLA Credit (Last Closed Week)"),
               ("fact_csat", "CSAT Avg")]),
    ]
    experience = [
        header("exp", "Experience & Incidents",
               "Digital experience (DEM), time lost, and the major incidents behind them."),
        slicer("slc_customer_exp", 1016, 16, 240, 56, *CUSTOMER, "Customer"),
        card("card_exp", 24, 88, 236, "Experience score (0-100)", "fact_experience_daily",
             "Experience Score"),
        card("card_time_lost", 272, 88, 236, "Time lost per seat (min)", ft,
             "Time Lost per Seat (min)"),
        card("card_mttr", 520, 88, 236, "MTTR (h)", ft, "MTTR (h)"),
        card("card_mi", 768, 88, 236, "Major incidents", "fact_major_incident",
             "Major Incidents", WARN),
        card("card_impacted", 1016, 88, 240, "Impacted users", "fact_major_incident",
             "Impacted Users"),
        line("line_exp", 24, 228, 608, 268, "Experience score by day",
             ("dim_date", "date"),
             [("fact_experience_daily", "Experience Score")]),
        bar("bar_app", 648, 228, 608, 268, "Tickets by application",
            ("dim_application", "app_name"), [(ft, "Tickets")]),
        table("tbl_mi", 24, 512, 1232, 184, "Major incidents",
              [("fact_major_incident", "major_incident_id"), ("fact_major_incident", "title"),
               ("fact_major_incident", "severity"), ("fact_major_incident", "status"),
               ("fact_major_incident", "root_cause"), ("fact_major_incident", "started_at"),
               ("fact_major_incident", "impacted_users"),
               ("fact_major_incident", "impacted_vip_users")]),
    ]
    credits = [
        header("xla", "XLA & Credits",
               "Every contractual target over every closed window: value, breach, credit "
               "(monthly cap applied)."),
        card("card_breaches", 24, 88, 400, "XLA breaches (all closed windows)", xla,
             "XLA Breaches", WARN),
        card("card_credit_total", 440, 88, 400, "XLA credit owed (EUR)", xla,
             "XLA Credit (EUR)", WARN),
        card("card_evals", 856, 88, 400, "XLA evaluations", xla, "XLA Evaluations"),
        bar("bar_credit", 24, 228, 608, 268, "Credit owed by customer", CUSTOMER,
            [(xla, "XLA Credit (EUR)")]),
        bar("bar_breach", 648, 228, 608, 268, "Breaches by XLA", ("dim_xla", "metric_label"),
            [(xla, "XLA Breaches")]),
        table("tbl_eval", 24, 512, 1232, 184, "XLA evaluations (closed windows)",
              [CUSTOMER, ("dim_xla", "metric_label"), (xla, "measurement_window"),
               (xla, "window_start"), (xla, "value"), (xla, "threshold"),
               (xla, "breached"), (xla, "penalty_eur")]),
    ]
    return {"overview": (page("overview", "Service Desk Overview"), overview),
            "experience": (page("experience", "Experience & Incidents"), experience),
            "xla_credits": (page("xla_credits", "XLA & Credits"), credits)}


def theme_json() -> Dict:
    return {"name": THEME_NAME,
            "dataColors": ["#118DFF", "#12239E", "#E66C37", "#6B007B", "#E044A7", "#744EC2",
                           "#D9B300", "#D64550", "#197278", "#1AAB40"],
            "foreground": "#1B1F3B", "background": "#FFFFFF", "backgroundLight": "#F3F4F8",
            "tableAccent": "#118DFF", "good": "#1AAB40", "neutral": "#D9B300",
            "bad": "#D64550"}


def report_json() -> Dict:
    return {
        "$schema": SCHEMA_REPORT,
        "themeCollection": {"baseTheme": {
            "name": THEME_NAME,
            "reportVersionAtImport": {"visual": "2.9.0", "report": "3.3.0", "page": "2.3.1"},
            "type": "SharedResources"}},
        "objects": {"section": [{"properties": {"verticalAlignment": s("Top")}}],
                    "outspacePane": [{"properties": {"expanded": b(False)}}]},
        "reportSource": "QuickCreate",
        "resourcePackages": [{"name": "SharedResources", "type": "SharedResources",
                              "items": [{"name": THEME_NAME,
                                         "path": f"BaseThemes/{THEME_NAME}.json",
                                         "type": "BaseTheme"}]}],
        "settings": {"useStylableVisualContainerHeader": True,
                     "exportDataMode": "AllowSummarized",
                     "defaultDrillFilterOtherVisuals": True, "allowChangeFilterTypes": True,
                     "useEnhancedTooltips": True, "useDefaultAggregateDisplayName": True},
        "publicCustomVisuals": [],
    }


def build_parts(workspace_name: str, model_name: str, model_id: str) -> List[Dict]:
    conn = (f'Data Source="powerbi://api.powerbi.com/v1.0/myorg/{workspace_name}";'
            f"initial catalog={model_name};integrated security=ClaimsToken;"
            f"semanticmodelid={model_id}")
    files: Dict[str, Dict] = {
        "definition.pbir": {"$schema": SCHEMA_PBIR, "version": "4.0",
                            "datasetReference": {"byConnection": {"connectionString": conn}}},
        "definition/report.json": report_json(),
        "definition/version.json": {"$schema": SCHEMA_VERSION, "version": "2.0.0"},
        f"StaticResources/SharedResources/BaseThemes/{THEME_NAME}.json": theme_json(),
    }
    pages = build_pages()
    for pid, (page_obj, visuals) in pages.items():
        files[f"definition/pages/{pid}/page.json"] = page_obj
        for v in visuals:
            files[f"definition/pages/{pid}/visuals/{v['name']}/visual.json"] = v
    files["definition/pages/pages.json"] = {"$schema": SCHEMA_PAGES,
                                            "activePageName": next(iter(pages)),
                                            "pageOrder": list(pages)}
    return [part(path, obj) for path, obj in files.items()]


def check_bounds() -> List[str]:
    problems = []
    for _pid, (_p, visuals) in build_pages().items():
        for v in visuals:
            p = v["position"]
            if p["x"] + p["width"] > CANVAS_W or p["y"] + p["height"] > CANVAS_H:
                problems.append(v["name"])
    return problems


def main() -> int:
    cfg, state, api, ws, token = deploy_context()
    model_id = require_state(state, "semantic_model_id")
    model_name = cfg["semantic_model"]["name"]
    report_name = cfg["semantic_model"]["report"]

    print_step(1, 3, "Check layout bounds")
    problems = check_bounds()
    if problems:
        raise RuntimeError(f"visuals outside {CANVAS_W}x{CANVAS_H}: {problems}")
    parts = build_parts(require_config(cfg, "workspace_name"), model_name, model_id)
    print(f"   {len(parts)} parts, all visuals inside the canvas")

    print_step(2, 3, f"Create or update report '{report_name}'")
    definition = {"parts": parts}
    item = find_item_or_none(token, api, ws, report_name, "Report")
    if item:
        update_definition(token, api, ws, item["id"], definition, f"Report '{report_name}'")
        print(f"   updated {item['id']}")
    else:
        item = create_fabric_item(token, api, ws, report_name, "Report",
                                  "Zava Service Desk: zero-touch, experience and XLA credits",
                                  definition=definition)
        print(f"   created {item['id']}")

    print_step(3, 3, "Persist state")
    state["report_id"] = item["id"]
    save_state(state)
    print("   report_id saved")
    return 0


if __name__ == "__main__":
    sys.exit(main())
