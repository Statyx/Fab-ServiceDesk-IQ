/**
 * Every DAX query the app runs, in one file.
 *
 * Two rules hold this together:
 *
 * 1. **Bind to the model's measures, never re-derive them.** `[Zero-Touch % (Last Closed Week)]`,
 *    `[XLA Credit (Last Closed Week)]`, `[Experience Score]` and the rest already exist in
 *    SM_ServiceDesk_Analytics and are what the Power BI report and the data agent read. Writing an
 *    equivalent CALCULATE here would create a second definition of the same business rule, free
 *    to drift from the first — and drift only ever shows up as two screens disagreeing in front
 *    of a customer. That is the whole boundary rule of this demo, applied to the UI: Fabric
 *    computes, everything else reads.
 *
 * 2. **Keep the raw column keys here.** SUMMARIZECOLUMNS answers with keys like
 *    `dim_customer[customer_name]` and `[Credit]`. Letting that spelling leak into components
 *    would scatter the coupling to the model across the UI; each query therefore ships with its
 *    own mapper and hands back a plain typed object.
 *
 * Measure names are copied from `fabric/powerbi/deploy_semantic_model.py`. A name invented here
 * does not fail loudly — `SUMMARIZECOLUMNS` errors, but a mistyped name inside a `ROW` comes back
 * as a blank cell that renders as a confident `0`.
 *
 * Units, because they are the easiest thing to get wrong on screen: every `%` measure returns a
 * **ratio** (0.34 for 34%) and is printed through `fmtPct`; `[Zero-Touch Change (pts)]` is
 * already in points; `dim_xla[threshold]` is in the XLA's own unit (40 for a percentage, 3.8 for
 * a CSAT score) and `dim_xla[penalty_pct]` is a percentage of the monthly fee (5 for 5%).
 */
import type { DaxRow, DaxValue } from '@/services/powerbi';

const num = (v: DaxValue): number => (typeof v === 'number' ? v : Number(v ?? 0) || 0);
const str = (v: DaxValue): string => (v === null || v === undefined ? '' : String(v));

/**
 * For measures whose blank is meaningful.
 *
 * `num` folds a DAX blank into `0`, which is right for a total and wrong for a target nobody
 * signed: the screen would then state "0% target" with the same confidence whether the contract
 * sets a weekly zero-touch threshold or does not have one at all. Where that distinction carries
 * a claim, keep the blank and let the component say which of the two it is.
 */
const numOrNull = (v: DaxValue): number | null => {
  if (v === null || v === undefined || v === '') return null;
  return num(v);
};

/** `[Last Closed Week Start]` comes back as an ISO timestamp; the screen only needs the day. */
const day = (v: DaxValue): string => str(v).slice(0, 10);

/* ------------------------------------------------------------------- Cover */

export interface CoverStats {
  tickets: number;
  zeroTouchWeek: number;
  openTickets: number;
  csat: number;
  breachesWeek: number;
  creditWeek: number;
}

/**
 * The cover tiles. Every one comes from the model rather than being typed into the page: a
 * hardcoded "2 breaches" is a caption that keeps its value after the data changes, which is
 * exactly the kind of quiet lie this app exists not to tell.
 */
export const COVER_DAX = `
EVALUATE
ROW(
  "Tickets", [Tickets],
  "ZeroTouchWeek", [Zero-Touch % (Last Closed Week)],
  "OpenTickets", [Open Tickets],
  "Csat", [CSAT Avg],
  "BreachesWeek", [XLA Breaches (Last Closed Week)],
  "CreditWeek", [XLA Credit (Last Closed Week)]
)`;

export function mapCover(rows: DaxRow[]): CoverStats {
  const r = rows[0] ?? {};
  return {
    tickets: num(r['[Tickets]']),
    zeroTouchWeek: num(r['[ZeroTouchWeek]']),
    openTickets: num(r['[OpenTickets]']),
    csat: num(r['[Csat]']),
    breachesWeek: num(r['[BreachesWeek]']),
    creditWeek: num(r['[CreditWeek]']),
  };
}

/* --------------------------------------------------------------- Portfolio */

export interface PortfolioKpis {
  weekStart: string;
  tickets: number;
  ticketsWeek: number;
  zeroTouchWeek: number;
  zeroTouchPrevious: number;
  changePts: number;
  hitl: number;
  openTickets: number;
  mttr: number;
  csat: number;
  timeLostPerSeat: number;
  majorIncidents: number;
}

export const PORTFOLIO_DAX = `
EVALUATE
ROW(
  "WeekStart", [Last Closed Week Start],
  "Tickets", [Tickets],
  "TicketsWeek", [Tickets (Last Closed Week)],
  "ZeroTouchWeek", [Zero-Touch % (Last Closed Week)],
  "ZeroTouchPrevious", [Zero-Touch % (Previous Week)],
  "ChangePts", [Zero-Touch Change (pts)],
  "Hitl", [HITL Escalations],
  "OpenTickets", [Open Tickets],
  "Mttr", [MTTR (h)],
  "Csat", [CSAT Avg],
  "TimeLostPerSeat", [Time Lost per Seat (min)],
  "MajorIncidents", [Major Incidents]
)`;

export function mapPortfolio(rows: DaxRow[]): PortfolioKpis {
  const r = rows[0] ?? {};
  return {
    weekStart: day(r['[WeekStart]']),
    tickets: num(r['[Tickets]']),
    ticketsWeek: num(r['[TicketsWeek]']),
    zeroTouchWeek: num(r['[ZeroTouchWeek]']),
    zeroTouchPrevious: num(r['[ZeroTouchPrevious]']),
    changePts: num(r['[ChangePts]']),
    hitl: num(r['[Hitl]']),
    openTickets: num(r['[OpenTickets]']),
    mttr: num(r['[Mttr]']),
    csat: num(r['[Csat]']),
    timeLostPerSeat: num(r['[TimeLostPerSeat]']),
    majorIncidents: num(r['[MajorIncidents]']),
  };
}

export interface CustomerWeek {
  customer: string;
  lastWeek: number;
  previousWeek: number;
  changePts: number;
  tickets: number;
  /** Blank when the contract sets no *weekly* zero-touch threshold — not a 0% target. */
  target: number | null;
  csat: number;
}

/**
 * The week, customer by customer — and the one query the demo turns on.
 *
 * No customer is named in it. The two cases that matter have to *emerge* from the same ranking
 * as everything else — naming them here would turn a finding into a lookup, and the room can
 * tell the difference.
 *
 * Sorted by the change, most negative first, because a drop is what a service desk lead looks
 * for on a Monday. The threshold is carried beside it, never used to filter: the reader sees
 * where the line is and judges the gap themselves.
 */
export const CUSTOMERS_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_customer[customer_name],
  "LastWeek", [Zero-Touch % (Last Closed Week)],
  "PreviousWeek", [Zero-Touch % (Previous Week)],
  "ChangePts", [Zero-Touch Change (pts)],
  "Tickets", [Tickets (Last Closed Week)],
  "Target", [Zero-Touch Target %],
  "Csat", [CSAT Avg]
)
ORDER BY [ChangePts] ASC`;

export function mapCustomers(rows: DaxRow[]): CustomerWeek[] {
  return rows
    .map((r) => ({
      customer: str(r['dim_customer[customer_name]']),
      lastWeek: num(r['[LastWeek]']),
      previousWeek: num(r['[PreviousWeek]']),
      changePts: num(r['[ChangePts]']),
      tickets: num(r['[Tickets]']),
      target: numOrNull(r['[Target]']),
      csat: num(r['[Csat]']),
    }))
    .filter((c) => c.customer !== '');
}

/* -------------------------------------------------------------- Experience */

export interface SiteExperience {
  siteId: string;
  site: string;
  customer: string;
  score: number;
  vpnMs: number;
  mos: number;
  crashes: number;
}

/**
 * The digital experience, site by site, worst first.
 *
 * Closed days only: the semantic model reads `fact_experience_daily`. What the devices are
 * reporting right now lives in the Eventhouse, and the page says which is which — a daily
 * average beside a last-hour reading is two windows, not two opinions.
 */
export const SITES_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_site[site_id],
  dim_site[site_name],
  dim_customer[customer_name],
  "Score", [Experience Score],
  "VpnMs", [VPN Latency (ms)],
  "Mos", [Teams MOS],
  "Crashes", [App Crashes]
)
ORDER BY [Score] ASC`;

export function mapSites(rows: DaxRow[]): SiteExperience[] {
  return rows
    .map((r) => ({
      siteId: str(r['dim_site[site_id]']),
      site: str(r['dim_site[site_name]']),
      customer: str(r['dim_customer[customer_name]']),
      score: num(r['[Score]']),
      vpnMs: num(r['[VpnMs]']),
      mos: num(r['[Mos]']),
      crashes: num(r['[Crashes]']),
    }))
    .filter((s) => s.site !== '');
}

export interface MajorIncident {
  id: string;
  title: string;
  severity: string;
  status: string;
  rootCause: string;
  customer: string;
  users: number;
  vips: number;
}

/**
 * Major incidents with their blast radius.
 *
 * The counts are the ones recorded on the incident. *Who* those users are is a traversal, not a
 * figure — site hosts user, incident affects site — and it is asked of the ontology from the
 * button beside the table rather than approximated here with a join.
 */
export const INCIDENTS_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  fact_major_incident[major_incident_id],
  fact_major_incident[title],
  fact_major_incident[severity],
  fact_major_incident[status],
  fact_major_incident[root_cause],
  dim_customer[customer_name],
  "Users", [Impacted Users],
  "Vips", [Impacted VIP Users]
)
ORDER BY [Users] DESC`;

export function mapIncidents(rows: DaxRow[]): MajorIncident[] {
  return rows
    .map((r) => ({
      id: str(r['fact_major_incident[major_incident_id]']),
      title: str(r['fact_major_incident[title]']),
      severity: str(r['fact_major_incident[severity]']),
      status: str(r['fact_major_incident[status]']),
      rootCause: str(r['fact_major_incident[root_cause]']),
      customer: str(r['dim_customer[customer_name]']),
      users: num(r['[Users]']),
      vips: num(r['[Vips]']),
    }))
    .filter((m) => m.id !== '');
}

/* --------------------------------------------------------------- AI agents */

export interface AgentRow {
  agent: string;
  type: string;
  role: string;
  tickets: number;
  zeroTouch: number;
  hitl: number;
}

/**
 * Who resolved what, AI and human side by side.
 *
 * Filtered on `[Tickets] > 0` because the agent dimension also lists the supervisor and the
 * tool-only agents that never close a ticket themselves; a row of zeros would read as an agent
 * doing nothing rather than as an agent with another job.
 */
export const AGENTS_DAX = `
EVALUATE
FILTER(
  SUMMARIZECOLUMNS(
    dim_agent[agent_name],
    dim_agent[agent_type],
    dim_agent[role],
    "Tickets", [Tickets],
    "ZeroTouch", [Zero-Touch Tickets],
    "Hitl", [HITL Escalations]
  ),
  [Tickets] > 0
)
ORDER BY [Tickets] DESC`;

export function mapAgents(rows: DaxRow[]): AgentRow[] {
  return rows
    .map((r) => ({
      agent: str(r['dim_agent[agent_name]']),
      type: str(r['dim_agent[agent_type]']),
      role: str(r['dim_agent[role]']),
      tickets: num(r['[Tickets]']),
      zeroTouch: num(r['[ZeroTouch]']),
      hitl: num(r['[Hitl]']),
    }))
    .filter((a) => a.agent !== '');
}

export interface CustomerAutomation {
  customer: string;
  tickets: number;
  zeroTouch: number;
  hitl: number;
  mttr: number;
}

/** The same platform, read per customer: what share the agents close without a human. */
export const AUTOMATION_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_customer[customer_name],
  "Tickets", [Tickets],
  "ZeroTouch", [Zero-Touch %],
  "Hitl", [HITL Escalations],
  "Mttr", [MTTR (h)]
)
ORDER BY [ZeroTouch] ASC`;

export function mapAutomation(rows: DaxRow[]): CustomerAutomation[] {
  return rows
    .map((r) => ({
      customer: str(r['dim_customer[customer_name]']),
      tickets: num(r['[Tickets]']),
      zeroTouch: num(r['[ZeroTouch]']),
      hitl: num(r['[Hitl]']),
      mttr: num(r['[Mttr]']),
    }))
    .filter((c) => c.customer !== '');
}

/* ------------------------------------------------------------ XLA & credits */

export interface XlaTotals {
  weekStart: string;
  evaluations: number;
  breaches: number;
  credit: number;
  breachesWeek: number;
  creditWeek: number;
}

/** The XLA header. Credits already carry the monthly cap: the model applied it, never us. */
export const XLA_TOTALS_DAX = `
EVALUATE
ROW(
  "WeekStart", [Last Closed Week Start],
  "Evaluations", [XLA Evaluations],
  "Breaches", [XLA Breaches],
  "Credit", [XLA Credit (EUR)],
  "BreachesWeek", [XLA Breaches (Last Closed Week)],
  "CreditWeek", [XLA Credit (Last Closed Week)]
)`;

export function mapXlaTotals(rows: DaxRow[]): XlaTotals {
  const r = rows[0] ?? {};
  return {
    weekStart: day(r['[WeekStart]']),
    evaluations: num(r['[Evaluations]']),
    breaches: num(r['[Breaches]']),
    credit: num(r['[Credit]']),
    breachesWeek: num(r['[BreachesWeek]']),
    creditWeek: num(r['[CreditWeek]']),
  };
}

export interface WeekBreach {
  customer: string;
  zeroTouch: number;
  /** Blank when the contract sets no weekly zero-touch threshold. */
  target: number | null;
  breaches: number;
  credit: number;
}

/**
 * The last closed week, customer by customer — the table the whole demo turns on.
 *
 * Two customers sit below the same 40% line. One is owed a credit, the other is not, and
 * nothing in this table explains why: the credit column comes from the contract evaluation, but
 * the *reason* is a clause. That is why the row button asks a `mixed` question.
 */
export const XLA_WEEK_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_customer[customer_name],
  "ZeroTouch", [Zero-Touch % (Last Closed Week)],
  "Target", [Zero-Touch Target %],
  "Breaches", [XLA Breaches (Last Closed Week)],
  "Credit", [XLA Credit (Last Closed Week)]
)
ORDER BY [ZeroTouch] ASC`;

export function mapXlaWeek(rows: DaxRow[]): WeekBreach[] {
  return rows
    .map((r) => ({
      customer: str(r['dim_customer[customer_name]']),
      zeroTouch: num(r['[ZeroTouch]']),
      target: numOrNull(r['[Target]']),
      breaches: num(r['[Breaches]']),
      credit: num(r['[Credit]']),
    }))
    .filter((b) => b.customer !== '');
}

export interface XlaLedgerRow {
  customer: string;
  xlaId: string;
  metric: string;
  window: string;
  penaltyPct: number;
  evaluations: number;
  breaches: number;
  credit: number;
}

/**
 * Every XLA over every closed window evaluated so far.
 *
 * `penalty_pct` is a column of the XLA, not a measure: it says what one breached window costs as
 * a share of the monthly fee. The credit beside it is what the evaluation actually booked, cap
 * included — the two are allowed to disagree, and the cap is exactly where they do.
 */
export const XLA_LEDGER_DAX = `
EVALUATE
SUMMARIZECOLUMNS(
  dim_customer[customer_name],
  dim_xla[xla_id],
  dim_xla[metric_label],
  dim_xla[measurement_window],
  dim_xla[penalty_pct],
  "Evaluations", [XLA Evaluations],
  "Breaches", [XLA Breaches],
  "Credit", [XLA Credit (EUR)]
)
ORDER BY [Credit] DESC`;

export function mapXlaLedger(rows: DaxRow[]): XlaLedgerRow[] {
  return rows
    .map((r) => ({
      customer: str(r['dim_customer[customer_name]']),
      xlaId: str(r['dim_xla[xla_id]']),
      metric: str(r['dim_xla[metric_label]']),
      window: str(r['dim_xla[measurement_window]']),
      penaltyPct: num(r['dim_xla[penalty_pct]']),
      evaluations: num(r['[Evaluations]']),
      breaches: num(r['[Breaches]']),
      credit: num(r['[Credit]']),
    }))
    .filter((x) => x.xlaId !== '');
}
