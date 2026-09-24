import { describe, expect, it } from 'vitest';

import * as queries from '@/data/queries';
import { AGREEMENTS } from '@/data/contracts';
import { CHAIN_EDGES, CHAIN_NODES } from '@/domain/chain';
import {
  FOCUS_BY_FAMILY,
  NAV,
  SECTION_BY_FAMILY,
  basePath,
  routeForFamily,
} from '@/domain/nav';
import { HOUSE_STYLE, OPENERS, followUps, selectOpeners, starters } from '@/domain/openers';
import type { OpenerFamily } from '@/domain/openers';
import frozenQuestions from '@/data/frozen-questions.generated.json';
import fixtures from '@/preview/fixtures.json';
import type { DaxRow } from '@/services/powerbi';

/**
 * The 28 measures SM_ServiceDesk_Analytics carries.
 *
 * Pinned here because an invented measure name does not fail loudly: inside a `ROW(...)` it
 * comes back as an empty cell and renders as a confident zero. Transcribed from
 * fabric/semantic_model.
 */
const MEASURES = [
  'Tickets',
  'Zero-Touch Tickets',
  'Zero-Touch %',
  'HITL Escalations',
  'Open Tickets',
  'MTTR (h)',
  'Time Lost (min)',
  'Time Lost per Seat (min)',
  'Last Closed Week Start',
  'Zero-Touch % (Last Closed Week)',
  'Zero-Touch % (Previous Week)',
  'Zero-Touch Change (pts)',
  'Tickets (Last Closed Week)',
  'Zero-Touch Target %',
  'CSAT Avg',
  'CSAT Responses',
  'Experience Score',
  'App Crashes',
  'VPN Latency (ms)',
  'Teams MOS',
  'Major Incidents',
  'Impacted Users',
  'Impacted VIP Users',
  'XLA Evaluations',
  'XLA Breaches',
  'XLA Credit (EUR)',
  'XLA Breaches (Last Closed Week)',
  'XLA Credit (Last Closed Week)',
];

/** Transcribed from RELATIONSHIPS in fabric/ontology/deploy_ontology.py. */
const RELATIONSHIPS = new Set([
  'CustomerHasSite',
  'CustomerHasContract',
  'ContractDefinesXla',
  'SiteHostsUser',
  'UserUsesDevice',
  'DeviceRunsApplication',
  'TicketRaisedBy',
  'TicketAboutDevice',
  'TicketForService',
  'TicketForApplication',
  'TicketUsesKb',
  'TicketForCustomer',
  'TicketPartOfIncident',
  'TicketResolvedBy',
  'MajorIncidentForCustomer',
  'MajorIncidentAffectsSite',
  'MajorIncidentCausedByApp',
  'KbDocumentsService',
  'AgentCallsTool',
]);

/** Every `[Bracketed Name]` in a query that is not a result-column alias. */
function measuresCited(dax: string): string[] {
  const cited = dax.match(/\[[A-Z][A-Za-z0-9 %()/.-]*\]/g) ?? [];
  return [...new Set(cited.map((m) => m.slice(1, -1)))];
}

const DAX_QUERIES = Object.entries(queries).filter(
  ([name, value]) => name.endsWith('_DAX') && typeof value === 'string',
) as [string, string][];

const rows = (name: string) => (fixtures as Record<string, DaxRow[]>)[name];

describe('queries', () => {
  it('cites only measures the model carries', () => {
    expect(DAX_QUERIES.length).toBeGreaterThan(0);
    for (const [name, dax] of DAX_QUERIES) {
      for (const cited of measuresCited(dax)) {
        const isAlias = new RegExp(`"${cited}"\\s*,`).test(dax);
        if (isAlias) continue;
        expect(MEASURES, `${name} cites an unknown measure: ${cited}`).toContain(cited);
      }
    }
  });

  it('has a recorded preview row set for every query, and nothing else', () => {
    expect(Object.keys(fixtures).sort()).toEqual(DAX_QUERIES.map(([n]) => n).sort());
  });

  it('never recomputes the XLA credit in the app', () => {
    // The credit is the model's evaluation. A query that multiplies a fee by a percentage is
    // a second definition of the contract, and it will drift.
    for (const [name, dax] of DAX_QUERIES) {
      expect(dax, `${name} derives a credit`).not.toMatch(/monthly_fee|penalty_pct\s*\*/i);
    }
  });
});

describe('the mappers, on the recorded model rows', () => {
  it('reads the cover from the model', () => {
    const c = queries.mapCover(rows('COVER_DAX'));
    expect(c.tickets).toBeGreaterThan(0);
    expect(c.breachesWeek).toBe(2);
    expect(c.creditWeek).toBe(9250);
  });

  it('keeps a missing zero-touch target apart from a zero target', () => {
    const customers = queries.mapCustomers(rows('CUSTOMERS_DAX'));
    const fab = customers.find((c) => c.customer === 'Fabrikam Industries')!;
    const lit = customers.find((c) => c.customer === 'Litware Insurance')!;
    expect(fab.lastWeek).toBeCloseTo(0.34, 4);
    expect(lit.lastWeek).toBeCloseTo(0.38, 4);
    expect(fab.target).toBeCloseTo(0.4, 4);
    expect(customers.some((c) => c.target === null)).toBe(true);
  });

  it('shows two different drops below the same target, and different credits', () => {
    const week = queries.mapXlaWeek(rows('XLA_WEEK_DAX'));
    const fab = week.find((w) => w.customer === 'Fabrikam Industries')!;
    const lit = week.find((w) => w.customer === 'Litware Insurance')!;
    expect(fab.zeroTouch).toBeCloseTo(0.34, 4);
    expect(lit.zeroTouch).toBeCloseTo(0.38, 4);
    expect(fab.zeroTouch).not.toBeCloseTo(lit.zeroTouch, 2);
    expect(fab.breaches).toBe(1);
    expect(lit.breaches).toBe(1);
    expect(fab.credit).toBe(9250);
    expect(lit.credit).toBe(0);
  });

  it('finds the Lyon VPN incident with its impact', () => {
    const [mi] = queries.mapIncidents(rows('INCIDENTS_DAX'));
    expect(mi.id).toBe('MI-FAB-0001');
    expect(mi.users).toBe(48);
    expect(mi.vips).toBe(8);
  });

  it('drops rows with no key', () => {
    expect(queries.mapCustomers([{ 'dim_customer[customer_name]': null }])).toEqual([]);
    expect(queries.mapXlaLedger([{ 'dim_xla[xla_id]': '' }])).toEqual([]);
  });
});

describe('the contract register', () => {
  it('names only customers the model carries', () => {
    const inModel = new Set(queries.mapCustomers(rows('CUSTOMERS_DAX')).map((c) => c.customer));
    for (const a of AGREEMENTS) expect(inModel.has(a.customer), a.customer).toBe(true);
  });
});

describe('the architecture chain', () => {
  it('connects only nodes it draws', () => {
    const ids = new Set(CHAIN_NODES.map((n) => n.id));
    for (const e of CHAIN_EDGES) {
      expect(ids.has(e.from), e.from).toBe(true);
      expect(ids.has(e.to), e.to).toBe(true);
    }
  });

  it('says the Foundry hop is simulated', () => {
    const foundry = CHAIN_EDGES.filter((e) => e.from === 'supervisor');
    expect(foundry.length).toBeGreaterThan(0);
    for (const e of foundry) expect(e.short).toMatch(/simulated/i);
  });

  it('draws the real-time path from the analyst through KQL to the reactive items', () => {
    const realtime = CHAIN_NODES.filter((n) => n.plane === 'realtime').map((n) => n.id);
    expect(realtime.length).toBeGreaterThanOrEqual(3);
    const kql = CHAIN_EDGES.filter((e) => e.protocol === 'KQL');
    expect(kql.some((e) => e.from === 'analyst' && realtime.includes(e.to))).toBe(true);
    expect(kql.filter((e) => realtime.includes(e.from)).length).toBeGreaterThanOrEqual(3);
  });
});

describe('the question registry', () => {
  it('covers every family before it caps the list', () => {
    const families = new Set(OPENERS.map((o) => o.family));
    const selected = new Set(selectOpeners(OPENERS).map((o) => o.family));
    expect(selected).toEqual(families);
  });

  it('keeps a crossing question in the opening three', () => {
    expect(starters(OPENERS).some((o) => o.kind === 'mixed')).toBe(true);
  });

  it('never shows an identifier in a label', () => {
    for (const o of OPENERS) {
      expect(o.label, `${o.id} names a table`).not.toMatch(/\b(?:dim|fact)_[a-z_]+\b/);
      expect(o.label, `${o.id} contains a bracketed identifier`).not.toMatch(/\[.+\]/);
    }
  });

  it('shares one house style rather than copies of it', () => {
    for (const o of OPENERS) {
      expect(o.prompt, `${o.id} does not carry the house style`).toContain(HOUSE_STYLE.trim());
    }
  });

  it('drops questions already asked from the follow-ups', () => {
    const first = OPENERS[0];
    const rest = followUps([first.id]);
    expect(rest.some((o) => o.id === first.id)).toBe(false);
    expect(rest.length).toBeLessThanOrEqual(3);
  });

  it('routes every question to the Fabric data agent, since Foundry is simulated', () => {
    for (const o of OPENERS) expect(o.backend, o.id).toBe('fabric');
  });

  it('gives every opener exactly two follow-ups, one of which crosses', () => {
    const entries = OPENERS.filter((o) => o.depth === 1);
    expect(entries.length).toBeGreaterThan(0);
    for (const parent of entries) {
      const children = OPENERS.filter((o) => o.depth === 2 && o.parent === parent.id);
      expect(children.length, `${parent.id} has ${children.length} follow-ups`).toBe(2);
      expect(
        children.some((c) => c.kind === 'mixed'),
        `neither follow-up of ${parent.id} crosses a second source`,
      ).toBe(true);
    }
  });

  it('leaves no depth-2 question orphaned', () => {
    const ids = new Set(OPENERS.map((o) => o.id));
    for (const o of OPENERS) {
      if (o.depth === 1) {
        expect(o.parent, `${o.id} is an entry point but names a parent`).toBeUndefined();
        continue;
      }
      expect(o.parent, `${o.id} has no parent`).toBeTruthy();
      expect(ids.has(o.parent!), `${o.id} points at a parent that does not exist`).toBe(true);
      expect(OPENERS.find((p) => p.id === o.parent)?.depth).toBe(1);
    }
  });

  const graphEdge = /<?-\[:?([A-Za-z]+)\]->?/g;

  it('cites only measures the semantic model carries', () => {
    const known = new Set(MEASURES);
    for (const o of OPENERS) {
      for (const cited of measuresCited(o.prompt.replace(graphEdge, ' '))) {
        expect(known.has(cited), `${o.id} cites an unknown measure [${cited}]`).toBe(true);
      }
    }
  });

  it('traverses only relationships the ontology declares', () => {
    const seen = new Set<string>();
    for (const o of OPENERS) {
      for (const [, name] of o.prompt.matchAll(graphEdge)) {
        seen.add(name);
        expect(RELATIONSHIPS.has(name), `${o.id} follows an edge the graph has no [${name}]`).toBe(true);
      }
    }
    expect(seen.size, 'no question walks the graph at all').toBeGreaterThan(0);
  });
});

describe('the frozen capture list', () => {
  it('matches the question registry exactly', () => {
    expect(
      frozenQuestions.entries.length,
      'run `npx tsx scripts/freeze-questions.ts`',
    ).toBe(OPENERS.length);
    const generated = new Map(frozenQuestions.entries.map((e) => [e.id, e]));
    for (const o of OPENERS) {
      const e = generated.get(o.id);
      expect(e, `${o.id} is missing from the generated list`).toBeTruthy();
      expect(e!.prompt, `${o.id} has drifted from the generated list`).toBe(o.prompt);
      expect(e!.backend).toBe(o.backend);
      expect(e!.depth).toBe(o.depth);
    }
  });
});

describe('the route manifest', () => {
  it('lists each section exactly once', () => {
    const paths = NAV.map((n) => n.to);
    expect(new Set(paths).size).toBe(paths.length);
  });

  it('sends every family to a listed section', () => {
    for (const family of Object.keys(SECTION_BY_FAMILY) as OpenerFamily[]) {
      expect(NAV.map((n) => n.to)).toContain(routeForFamily(family));
    }
  });

  it('gives every family a focus anchor', () => {
    for (const family of Object.keys(SECTION_BY_FAMILY) as OpenerFamily[]) {
      expect(FOCUS_BY_FAMILY[family]).toBeTruthy();
    }
  });

  it('keeps preview navigation inside the preview mount', () => {
    expect(basePath('/preview/xla')).toBe('/preview');
    expect(basePath('/xla')).toBe('');
  });
});
