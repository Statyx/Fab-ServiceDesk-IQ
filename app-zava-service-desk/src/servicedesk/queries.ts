/**
 * DAX queries over SM_ServiceDesk_Analytics and the mappers that turn the positional
 * result rows into plain objects for the Graphein specs.
 *
 * Every measure used here exists in the semantic model (fabric/powerbi). The "last
 * closed week" measures follow the XLA contract: a week is judged once it is closed.
 */

export const CONNECTION = "serviceDesk";

export const KPI_QUERY = `EVALUATE
ROW(
    "ZeroTouchPct", [Zero-Touch % (Last Closed Week)],
    "ZeroTouchChangePts", [Zero-Touch Change (pts)],
    "Breaches", [XLA Breaches (Last Closed Week)],
    "CreditEur", [XLA Credit (Last Closed Week)],
    "OpenTickets", [Open Tickets],
    "Csat", [CSAT Avg],
    "MajorIncidents", [Major Incidents],
    "WeekStart", [Last Closed Week Start]
)`;

export const XLA_QUERY = `EVALUATE
SUMMARIZECOLUMNS(
    dim_customer[customer_name],
    "ZeroTouchPct", [Zero-Touch % (Last Closed Week)],
    "ZeroTouchTarget", [Zero-Touch Target %],
    "ChangePts", [Zero-Touch Change (pts)],
    "Tickets", [Tickets (Last Closed Week)],
    "Breaches", [XLA Breaches (Last Closed Week)],
    "CreditEur", [XLA Credit (Last Closed Week)]
)
ORDER BY dim_customer[customer_name]`;

export const TREND_QUERY = `EVALUATE
SUMMARIZECOLUMNS(
    dim_date[week_start],
    dim_customer[customer_name],
    FILTER(ALL(dim_date[week_start]), dim_date[week_start] <= [Last Closed Week Start]),
    "ZeroTouchPct", [Zero-Touch %]
)
ORDER BY dim_date[week_start], dim_customer[customer_name]`;

export const AGENTS_QUERY = `EVALUATE
TOPN(8,
    SUMMARIZECOLUMNS(
        dim_agent[agent_name],
        dim_agent[agent_type],
        "Tickets", [Tickets]
    ), [Tickets], DESC)
ORDER BY [Tickets] DESC`;

export const SITES_QUERY = `EVALUATE
TOPN(8,
    SUMMARIZECOLUMNS(
        dim_site[site_name],
        "ExperienceScore", [Experience Score],
        "VpnLatencyMs", [VPN Latency (ms)]
    ), [ExperienceScore], ASC)
ORDER BY [ExperienceScore] ASC`;

type Cell = string | number | boolean | null | undefined;
type Rows = ReadonlyArray<ReadonlyArray<Cell>>;

const num = (v: Cell): number => (typeof v === "number" ? v : Number(v ?? 0) || 0);
const str = (v: Cell): string => (v == null ? "" : String(v));
const day = (v: Cell): string => str(v).slice(0, 10);

export type Kpis = {
    zeroTouchPct: number;
    zeroTouchChangePts: number;
    breaches: number;
    creditEur: number;
    openTickets: number;
    csat: number;
    majorIncidents: number;
    weekStart: string;
};

export function toKpis(rows: Rows): Kpis | undefined {
    const r = rows[0];
    if (!r) return undefined;
    return {
        zeroTouchPct: num(r[0]),
        zeroTouchChangePts: num(r[1]),
        breaches: num(r[2]),
        creditEur: num(r[3]),
        openTickets: num(r[4]),
        csat: num(r[5]),
        majorIncidents: num(r[6]),
        weekStart: day(r[7]),
    };
}

export type XlaStatus = "Breach + credit" | "Breach, no credit" | "Met" | "No clause";

export type XlaRow = {
    customer: string;
    zeroTouchPct: number;
    /** null when the customer's contract has no zero-touch clause. */
    target: number | null;
    changePts: number;
    tickets: number;
    breaches: number;
    creditEur: number;
    status: XlaStatus;
};

export function toXlaRows(rows: Rows): XlaRow[] {
    return rows.map((r) => {
        const target = r[2] == null ? null : num(r[2]);
        const breaches = num(r[5]);
        const creditEur = num(r[6]);
        const status: XlaStatus =
            breaches > 0 ? (creditEur > 0 ? "Breach + credit" : "Breach, no credit")
                : target == null ? "No clause" : "Met";
        return {
            customer: str(r[0]),
            zeroTouchPct: num(r[1]),
            target,
            changePts: num(r[3]),
            tickets: num(r[4]),
            breaches,
            creditEur,
            status,
        };
    });
}

export type TrendRow = {
    week: string;
    customer: string;
    zeroTouchPct: number;
};

export function toTrendRows(rows: Rows): TrendRow[] {
    return rows
        .filter((r) => r[2] != null)
        .map((r) => ({ week: day(r[0]), customer: str(r[1]), zeroTouchPct: num(r[2]) }));
}

export type AgentRow = {
    agent: string;
    kind: string;
    tickets: number;
};

export function toAgentRows(rows: Rows): AgentRow[] {
    return rows.map((r) => ({
        agent: str(r[0]),
        kind: str(r[1]) === "AI" ? "AI agent" : "Human analyst",
        tickets: num(r[2]),
    }));
}

export type SiteRow = {
    site: string;
    experienceScore: number;
    vpnLatencyMs: number;
};

export function toSiteRows(rows: Rows): SiteRow[] {
    return rows.map((r) => ({
        site: str(r[0]),
        experienceScore: num(r[1]),
        vpnLatencyMs: num(r[2]),
    }));
}
