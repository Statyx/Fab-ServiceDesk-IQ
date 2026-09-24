import { describe, expect, it } from "vitest";
import { validateSpec } from "graphein";

import { groupBySource } from "../servicedesk/app-config";
import {
    AGENTS_QUERY,
    KPI_QUERY,
    SITES_QUERY,
    toAgentRows,
    toKpis,
    toSiteRows,
    toTrendRows,
    toXlaRows,
    TREND_QUERY,
    XLA_QUERY,
} from "../servicedesk/queries";

describe("service desk queries", () => {
    it("every query is a single EVALUATE", () => {
        for (const q of [KPI_QUERY, XLA_QUERY, TREND_QUERY, AGENTS_QUERY, SITES_QUERY]) {
            expect(q.trimStart().startsWith("EVALUATE")).toBe(true);
            expect(q.match(/EVALUATE/g)).toHaveLength(1);
        }
    });

    it("maps the KPI row", () => {
        const k = toKpis([[0.365, -6, 2, 9250, 34, 4.27, 1, "2026-09-14T00:00:00"]]);
        expect(k).toMatchObject({ zeroTouchPct: 0.365, breaches: 2, creditEur: 9250, weekStart: "2026-09-14" });
        expect(toKpis([])).toBeUndefined();
    });

    it("classifies the XLA status per customer", () => {
        const rows = toXlaRows([
            ["Fabrikam Industries", 0.34, 0.4, -12, 150, 1, 9250],
            ["Litware Insurance", 0.34, 0.4, -12, 50, 1, 0],
            ["Contoso Retail", 0.4375, 0.35, -1.25, 32, null, 0],
            ["Woodgrove Bank", 0.42, null, 4.8, 26, null, null],
        ]);
        expect(rows.map((r) => r.status)).toEqual(["Breach + credit", "Breach, no credit", "Met", "No clause"]);
        expect(rows[3].target).toBeNull();
    });

    it("drops blank trend points and trims dates", () => {
        const rows = toTrendRows([
            ["2026-09-14T00:00:00", "Fabrikam Industries", 0.34],
            ["2026-09-14T00:00:00", "Woodgrove Bank", null],
        ]);
        expect(rows).toEqual([{ week: "2026-09-14", customer: "Fabrikam Industries", zeroTouchPct: 0.34 }]);
    });

    it("labels AI agents and human analysts", () => {
        const rows = toAgentRows([["Resolver Agent", "AI", 1185], ["Service Desk Analyst L1-05", "Human", 198]]);
        expect(rows.map((r) => r.kind)).toEqual(["AI agent", "Human analyst"]);
    });

    it("builds valid Graphein specs from mapped rows", () => {
        const sites = toSiteRows([["Fabrikam Industries Lyon", 79.4, 67.8]]);
        const result = validateSpec({
            type: "bar",
            data: sites,
            orientation: "horizontal",
            encoding: {
                x: { field: "site", type: "nominal" },
                y: { field: "vpnLatencyMs", type: "quantitative" },
            },
        });
        expect(result.errors).toEqual([]);
    });

    it("groups demo questions by source, keeping order", () => {
        const groups = groupBySource([
            { source: "Ontology (GQL)", question: "a" },
            { source: "Semantic model (DAX)", question: "b" },
            { source: "Ontology (GQL)", question: "c" },
        ]);
        expect(groups).toEqual([["Ontology (GQL)", ["a", "c"]], ["Semantic model (DAX)", ["b"]]]);
    });
});
