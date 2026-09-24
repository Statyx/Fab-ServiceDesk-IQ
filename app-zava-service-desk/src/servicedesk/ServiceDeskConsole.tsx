import { useMemo } from "react";

import {
    ChartCard,
    DashboardGrid,
    PageShell,
    SketchToggle,
    ThemeToggle,
    Tile,
    type ChartSpec,
    type TableSpec,
} from "@/components/dashboard";
import { useSemanticModelQuery } from "@/hooks/use-semantic-model-query";

import { useAppConfig } from "./app-config";
import { Launchpad } from "./Launchpad";
import {
    AGENTS_QUERY,
    CONNECTION,
    KPI_QUERY,
    SITES_QUERY,
    toAgentRows,
    toKpis,
    toSiteRows,
    toTrendRows,
    toXlaRows,
    TREND_QUERY,
    XLA_QUERY,
} from "./queries";

type Rows = ReadonlyArray<ReadonlyArray<string | number | boolean | null>>;

// Literal colors: tables may paint on canvas, where CSS variables do not resolve.
const BAD = "#dc2626";
const WARN = "#d97706";
const GOOD = "#16a34a";
const zeroTo = (values: number[]): [number, number] => [0, Math.max(1, ...values)];
const FLAG_POSITIVE = {
    type: "rules" as const,
    rules: [{ when: "gt" as const, value: 0, background: "rgba(220,38,38,0.16)", color: BAD, weight: "bold" as const }],
};

/** Run one DAX query and expose rows + the loading / error states ChartCard expects. */
function useDax(query: string) {
    const { data, isLoading, error, refetch } = useSemanticModelQuery({ connection: CONNECTION, query });
    const rows: Rows = data?.status === "success" ? (data.table.rows as Rows) : [];
    const failure = error ?? (data?.status === "error" ? new Error(data.error.message) : undefined);
    return { rows, loading: isLoading || (!data && !failure), error: failure, retry: () => void refetch() };
}

export function ServiceDeskConsole() {
    const config = useAppConfig();
    const kpiQ = useDax(KPI_QUERY);
    const xlaQ = useDax(XLA_QUERY);
    const trendQ = useDax(TREND_QUERY);
    const agentsQ = useDax(AGENTS_QUERY);
    const sitesQ = useDax(SITES_QUERY);

    const kpis = useMemo(() => toKpis(kpiQ.rows), [kpiQ.rows]);
    const xla = useMemo(() => toXlaRows(xlaQ.rows), [xlaQ.rows]);
    const trend = useMemo(() => toTrendRows(trendQ.rows), [trendQ.rows]);
    const agents = useMemo(() => toAgentRows(agentsQ.rows), [agentsQ.rows]);
    const sites = useMemo(() => toSiteRows(sitesQ.rows), [sitesQ.rows]);

    const kpiSpecs = useMemo<ChartSpec[]>(() => {
        if (!kpis) return [];
        return [
            {
                type: "kpi", label: "Zero-touch, last closed week", value: kpis.zeroTouchPct,
                format: ".1%", align: "start",
                comparisons: [{ label: "pts vs previous week", delta: kpis.zeroTouchChangePts, format: ".1f" }],
            },
            {
                type: "kpi", label: "XLA breaches, last closed week", value: kpis.breaches,
                format: ",.0f", align: "start",
                color: kpis.breaches > 0 ? "var(--color-destructive)" : undefined,
            },
            {
                type: "kpi", label: "Service credits owed", value: kpis.creditEur,
                format: ",.0f", unit: " EUR", align: "start",
                color: kpis.creditEur > 0 ? "var(--color-destructive)" : undefined,
            },
            { type: "kpi", label: "Open tickets", value: kpis.openTickets, format: ",.0f", align: "start" },
            { type: "kpi", label: "CSAT (1-5)", value: kpis.csat, format: ".2f", align: "start" },
            { type: "kpi", label: "Major incidents", value: kpis.majorIncidents, format: ",.0f", align: "start" },
        ];
    }, [kpis]);

    const xlaSpec = useMemo<TableSpec>(() => ({
        type: "table",
        data: xla.map((r) => ({ ...r, target: r.target ?? undefined })),
        columns: [
            { field: "customer", title: "Customer" },
            { field: "zeroTouchPct", title: "Zero-touch", format: ".1%", align: "right" },
            { field: "target", title: "XLA target", format: ".0%", align: "right" },
            {
                field: "changePts", title: "vs prev. week (pts)", format: ".1f", align: "right",
                conditionalFormat: {
                    type: "icon",
                    rules: [
                        { when: "lte", value: -5, icon: "▼", color: BAD },
                        { when: "lt", value: 0, icon: "▼", color: WARN },
                        { when: "gte", value: 0, icon: "▲", color: GOOD },
                    ],
                },
            },
            { field: "tickets", title: "Tickets", format: ",.0f", align: "right" },
            { field: "breaches", title: "Breaches", format: ",.0f", align: "right", conditionalFormat: FLAG_POSITIVE },
            { field: "creditEur", title: "Credit (EUR)", format: ",.0f", align: "right", conditionalFormat: FLAG_POSITIVE },
            { field: "status", title: "Status" },
        ],
    }), [xla]);

    const trendSpec = useMemo<ChartSpec>(() => {
        // Only the customers whose contract carries a zero-touch clause, against their targets.
        const contracted = new Set(xla.filter((r) => r.target != null).map((r) => r.customer));
        const targets = [...new Set(xla.map((r) => r.target).filter((t): t is number => t != null))];
        return {
            type: "line",
            data: trend.filter((r) => contracted.has(r.customer)),
            points: true,
            encoding: {
                x: { field: "week", type: "temporal", title: "Week" },
                y: { field: "zeroTouchPct", type: "quantitative", title: "Zero-touch", format: ".0%" },
                series: { field: "customer" },
            },
            annotations: targets.map((t) => ({ type: "line" as const, value: t, label: `XLA target ${Math.round(t * 100)}%` })),
            legend: true,
            description: "Weekly zero-touch rate of the customers with a zero-touch XLA, closed weeks only",
        };
    }, [trend, xla]);
    // Tables with inline bars rather than horizontal bar charts: long category
    // names stay readable at any tile width.
    const agentsSpec = useMemo<TableSpec>(() => ({
        type: "table",
        data: agents,
        columns: [
            { field: "agent", title: "Resolver" },
            { field: "kind", title: "Type" },
            {
                field: "tickets", title: "Tickets resolved", format: ",.0f", align: "right",
                conditionalFormat: { type: "bar", domain: zeroTo(agents.map((r) => r.tickets)), showValue: true },
            },
        ],
    }), [agents]);

    const sitesSpec = useMemo<TableSpec>(() => ({
        type: "table",
        data: sites,
        columns: [
            { field: "site", title: "Site" },
            {
                field: "experienceScore", title: "Experience score", format: ".1f", align: "right",
                conditionalFormat: {
                    type: "rules",
                    rules: [
                        { when: "lt", value: 80, background: "rgba(220,38,38,0.16)", color: BAD, weight: "bold" },
                    ],
                },
            },
            {
                field: "vpnLatencyMs", title: "VPN latency (ms)", format: ",.0f", align: "right",
                conditionalFormat: { type: "bar", domain: zeroTo(sites.map((r) => r.vpnLatencyMs)), showValue: true },
            },
        ],
    }), [sites]);
    const week = kpis?.weekStart ? `Week of ${kpis.weekStart}` : "Last closed week";

    return (
        <PageShell
            eyebrow="Zava Service Desk · Fabric IQ"
            title="Service desk console"
            subtitle={`${week} · XLA, zero-touch and digital experience from SM_ServiceDesk_Analytics`}
            actions={
                <>
                    <SketchToggle />
                    <ThemeToggle />
                </>
            }
        >
            <DashboardGrid>
                {(kpiSpecs.length ? kpiSpecs : Array.from({ length: 6 }, () => undefined)).map((spec, i) => (
                    <Tile key={i} size="sm">
                        <ChartCard
                            spec={spec}
                            height={116}
                            className="p-4"
                            loading={kpiQ.loading}
                            error={kpiQ.error}
                            onRetry={kpiQ.retry}
                        />
                    </Tile>
                ))}
            </DashboardGrid>

            <DashboardGrid>
                <Tile size="full">
                    <ChartCard
                        eyebrow="Contract"
                        title="Zero-touch XLA by customer"
                        subtitle="Last closed week · Fabrikam carries a service credit clause, Litware the same drop without one"
                        accent="destructive"
                        spec={xlaSpec}
                        loading={xlaQ.loading}
                        error={xlaQ.error}
                        onRetry={xlaQ.retry}
                    />
                </Tile>
            </DashboardGrid>

            <DashboardGrid>
                <Tile size="full">
                    <ChartCard
                        title="Zero-touch trend"
                        subtitle="Customers with a zero-touch clause, against their contractual targets"
                        accent="chart-1"
                        spec={trendSpec}
                        height={340}
                        loading={trendQ.loading}
                        error={trendQ.error}
                        onRetry={trendQ.retry}
                    />
                </Tile>
            </DashboardGrid>

            <DashboardGrid>
                <Tile size="wide">
                    <ChartCard
                        title="Who resolves the tickets"
                        subtitle="Top 8 resolvers, AI agents and human analysts"
                        spec={agentsSpec}
                        loading={agentsQ.loading}
                        error={agentsQ.error}
                        onRetry={agentsQ.retry}
                    />
                </Tile>
                <Tile size="md">
                    <ChartCard
                        title="Digital experience hot spots"
                        subtitle="Lowest experience score sites · VPN latency"
                        spec={sitesSpec}
                        loading={sitesQ.loading}
                        error={sitesQ.error}
                        onRetry={sitesQ.retry}
                    />
                </Tile>
            </DashboardGrid>

            <Launchpad state={config} />
        </PageShell>
    );
}
