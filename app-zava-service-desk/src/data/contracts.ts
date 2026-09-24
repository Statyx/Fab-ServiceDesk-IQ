/**
 * The six managed service contracts, as the app displays them.
 *
 * This file holds **text**, never a measured figure. Every number on every screen comes from a
 * measure at runtime; every clause here is transcribed from `fabric/data/world.yaml`, the same
 * source the ontology binds as `Xla.clause_text`. That split is the boundary rule of the whole
 * demo, applied to the front end: Fabric computes, the contract says what it means, and the app
 * is not allowed to blur the two.
 *
 * The summaries below are captions for the cards. They are **not** the answer: when a user asks
 * what a breach entitles a customer to, the answer must come back from the data agent reading
 * the clause through the ontology, with its own source block. A caption rendered from this file
 * is a caption; a clause retrieved from the graph is evidence, and the app must never let the
 * first pass for the second.
 */

export type Regime = 'credit' | 'remediation' | 'reported';

export interface XlaTerm {
  id: string;
  metric: string;
  /** The threshold as the contract states it, unit included. */
  target: string;
  window: 'weekly' | 'monthly';
  regime: Regime;
  clause: string;
}

export interface Agreement {
  id: string;
  customer: string;
  name: string;
  /** The monthly cap on service credits, as a percentage of the fee. */
  capPct: number;
  xlas: XlaTerm[];
}

/**
 * Two consequences for the same breach.
 *
 * This is the entire point of the demo and it is worth stating plainly: nothing in the weekly
 * figures predicts which consequence applies, and nothing in the contracts predicts which week
 * will trip. Only the two together produce an answer, which is why the first card on the cover
 * is a `mixed` question.
 */
export const REGIME_STYLE: Record<Regime, { label: string; tone: string; note: string }> = {
  credit: {
    label: 'Service credit',
    tone: 'var(--sev-critical)',
    note: 'A share of the monthly fee is credited, within the contract cap.',
  },
  remediation: {
    label: 'Remediation plan',
    tone: 'var(--sev-high)',
    note: 'No credit. A written plan is owed within 10 business days.',
  },
  reported: {
    label: 'Reported only',
    tone: 'var(--sev-low)',
    note: 'Measured and reported against target. No consequence attached.',
  },
};

export const AGREEMENTS: Agreement[] = [
  {
    id: 'CTR-FAB-2026',
    customer: 'Fabrikam Industries',
    name: 'Fabrikam Digital Workplace Services',
    capPct: 15,
    xlas: [
      {
        id: 'XLA-FAB-01',
        metric: 'Zero-touch resolution rate',
        target: '≥ 40%',
        window: 'weekly',
        regime: 'credit',
        clause:
          'If the zero-touch resolution rate falls below 40.0% in any ISO week, Zava credits 5% ' +
          'of the monthly service fee for the month containing that week, within the monthly ' +
          'cap of 15%.',
      },
      {
        id: 'XLA-FAB-02',
        metric: 'Average CSAT score',
        target: '≥ 3.8 / 5',
        window: 'monthly',
        regime: 'credit',
        clause:
          "If the average CSAT score of a calendar month is below 3.8 out of 5, Zava credits 2% " +
          "of that month's service fee.",
      },
      {
        id: 'XLA-FAB-03',
        metric: 'Time lost per seat',
        target: '≤ 120 min',
        window: 'monthly',
        regime: 'credit',
        clause:
          'If the time lost to IT incidents exceeds 120 minutes per seat in a calendar month, ' +
          "Zava credits 2% of that month's service fee.",
      },
    ],
  },
  {
    id: 'CTR-LIT-2026',
    customer: 'Litware Insurance',
    name: 'Litware Service Desk Agreement',
    capPct: 0,
    xlas: [
      {
        id: 'XLA-LIT-01',
        metric: 'Zero-touch resolution rate',
        target: '≥ 40%',
        window: 'weekly',
        regime: 'remediation',
        clause:
          'If the zero-touch resolution rate falls below 40.0% in any ISO week, Zava delivers a ' +
          'written remediation plan within 10 business days. No service credit applies.',
      },
      {
        id: 'XLA-LIT-02',
        metric: 'Average CSAT score',
        target: '≥ 3.8 / 5',
        window: 'monthly',
        regime: 'reported',
        clause:
          'The monthly average CSAT score is reported against a 3.8 target. No service credit ' +
          'applies.',
      },
    ],
  },
  {
    id: 'CTR-CON-2026',
    customer: 'Contoso Retail',
    name: 'Contoso Store Support Services',
    capPct: 10,
    xlas: [
      {
        id: 'XLA-CON-01',
        metric: 'Zero-touch resolution rate',
        target: '≥ 35%',
        window: 'weekly',
        regime: 'credit',
        clause:
          'If the zero-touch resolution rate falls below 35.0% in any ISO week, Zava credits 3% ' +
          'of the monthly service fee, within the monthly cap of 10%.',
      },
      {
        id: 'XLA-CON-02',
        metric: 'Average CSAT score',
        target: '≥ 3.6 / 5',
        window: 'monthly',
        regime: 'credit',
        clause:
          "If the monthly average CSAT score is below 3.6 out of 5, Zava credits 1% of that " +
          "month's service fee.",
      },
    ],
  },
  {
    id: 'CTR-NOR-2026',
    customer: 'Northwind Logistics',
    name: 'Northwind Workplace Operations',
    capPct: 8,
    xlas: [
      {
        id: 'XLA-NOR-01',
        metric: 'Average CSAT score',
        target: '≥ 3.8 / 5',
        window: 'monthly',
        regime: 'credit',
        clause:
          "If the monthly average CSAT score is below 3.8 out of 5, Zava credits 3% of that " +
          "month's service fee.",
      },
      {
        id: 'XLA-NOR-02',
        metric: 'Average device experience score',
        target: '≥ 70 / 100',
        window: 'monthly',
        regime: 'credit',
        clause:
          'If the average device experience score of a calendar month is below 70 out of 100, ' +
          "Zava credits 2% of that month's service fee.",
      },
    ],
  },
  {
    id: 'CTR-TAI-2026',
    customer: 'Tailspin Airlines',
    name: 'Tailspin Operations Support',
    capPct: 6,
    xlas: [
      {
        id: 'XLA-TAI-01',
        metric: 'Average device experience score',
        target: '≥ 72 / 100',
        window: 'weekly',
        regime: 'credit',
        clause:
          'If the average device experience score of any ISO week is below 72 out of 100, Zava ' +
          'credits 2% of the monthly service fee.',
      },
      {
        id: 'XLA-TAI-02',
        metric: 'Zero-touch resolution rate',
        target: '≥ 30%',
        window: 'monthly',
        regime: 'credit',
        clause:
          'If the zero-touch resolution rate of a calendar month is below 30.0%, Zava credits 2% ' +
          "of that month's service fee.",
      },
    ],
  },
  {
    id: 'CTR-WOO-2026',
    customer: 'Woodgrove Bank',
    name: 'Woodgrove Managed Workplace',
    capPct: 12,
    xlas: [
      {
        id: 'XLA-WOO-01',
        metric: 'Zero-touch resolution rate',
        target: '≥ 30%',
        window: 'monthly',
        regime: 'credit',
        clause:
          'If the zero-touch resolution rate of a calendar month is below 30.0%, Zava credits 3% ' +
          "of that month's service fee.",
      },
      {
        id: 'XLA-WOO-02',
        metric: 'Time lost per seat',
        target: '≤ 120 min',
        window: 'monthly',
        regime: 'credit',
        clause:
          'If the time lost to IT incidents exceeds 120 minutes per seat in a calendar month, ' +
          "Zava credits 4% of that month's service fee.",
      },
      {
        id: 'XLA-WOO-03',
        metric: 'Average CSAT score',
        target: '≥ 3.7 / 5',
        window: 'monthly',
        regime: 'credit',
        clause:
          "If the monthly average CSAT score is below 3.7 out of 5, Zava credits 2% of that " +
          "month's service fee.",
      },
    ],
  },
];

export function agreementFor(customer: string): Agreement | undefined {
  return AGREEMENTS.find((a) => a.customer === customer);
}

/** The consequence of the customer's zero-touch XLA, the one the weekly table is judged on. */
export function zeroTouchTerm(customer: string): XlaTerm | undefined {
  return agreementFor(customer)?.xlas.find((x) => x.metric === 'Zero-touch resolution rate');
}
