import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { AssistantProvider } from '@/components/AssistantProvider';
import { KpiCard } from '@/components/KpiCard';
import { ContractsPage } from '@/pages/ContractsPage';
import { CoverPage } from '@/pages/CoverPage';
import { DiagnosticPage } from '@/pages/DiagnosticPage';
import { AGREEMENTS } from '@/data/contracts';
import { ALL_NAV, IQ_NAV, NAV, SECONDARY_NAV, sectionEntryForFamily } from '@/domain/nav';
import { FOCUS_BY_FAMILY, SECTION_BY_FAMILY } from '@/domain/nav';
import { OPENERS, starters } from '@/domain/openers';
import { COVER_DAX } from '@/data/queries';
import { executeDax } from '@/services/powerbi';
import { fmtDec, fmtEur, fmtInt, fmtPct } from '@/lib/format';

/**
 * Every figure in this app comes from the semantic model at render time, so a screen test
 * either mocks the transport or tests nothing. The stub returns an empty result set: what is
 * asserted here is that a screen mounts, states its own claim, and degrades honestly when the
 * model has nothing to say — never that it renders a particular number.
 */
vi.mock('@/services/powerbi', () => ({
  executeDax: vi.fn().mockResolvedValue([]),
  executeScalar: vi.fn().mockResolvedValue(null),
  semanticModelId: 'test-model',
  powerbiConfigured: true,
}));

function LocationProbe() {
  const location = useLocation();
  return <output data-testid="location">{location.pathname}{location.search}</output>;
}

function mount(ui: React.ReactElement, path = '/') {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AssistantProvider>{ui}</AssistantProvider>
      <LocationProbe />
    </MemoryRouter>,
  );
}

/** A screen may say it has no data. It may never say `NaN`. */
function expectNoBrokenNumbers(container: HTMLElement) {
  expect(container.textContent ?? '').not.toMatch(/NaN|undefined|Infinity/);
}

describe('the cover', () => {
  beforeEach(() => {
    vi.mocked(executeDax).mockReset().mockResolvedValue([]);
  });

  it('keeps the curated opening questions', async () => {
    const { container } = mount(<CoverPage />);

    const questions = screen.getByRole('region', { name: /Explore/ });
    expect(within(questions).getAllByRole('button')).toHaveLength(starters(OPENERS).length);
    await waitFor(() => expect(screen.queryByText('Loading data…')).not.toBeInTheDocument());

    expectNoBrokenNumbers(container);
  });

  it('shows a question, never an identifier', async () => {
    mount(<CoverPage />);
    for (const o of starters(OPENERS)) {
      expect(screen.getByRole('button', { name: o.label })).toBeInTheDocument();
    }
    await waitFor(() => expect(screen.queryByText('Loading data…')).not.toBeInTheDocument());
    expect(screen.getByRole('heading', { level: 1 })).toHaveTextContent('Your service desk. Connected.');
  });

  it.each(['/', '/preview'])('preserves question, route and panel from %s', async (path) => {
    mount(<CoverPage />, path);
    const user = userEvent.setup();
    await waitFor(() => expect(screen.queryByText('Loading data…')).not.toBeInTheDocument());
    for (const o of starters(OPENERS)) {
      await user.click(screen.getByRole('button', { name: o.label }));
      const prefix = path === '/preview' ? path : '';
      expect(screen.getByTestId('location')).toHaveTextContent(
        `${prefix}${SECTION_BY_FAMILY[o.family]}?ask=${o.id}&focus=${FOCUS_BY_FAMILY[o.family]}`,
      );
    }
    await user.click(screen.getByRole('button', { name: /Architecture/ }));
    expect(screen.getByTestId('location')).toHaveTextContent(
      `${path === '/preview' ? path : ''}/architecture`,
    );
  });

  it.each(['/', '/preview'])('opens section titles without asking a question from %s', async (path) => {
    mount(<CoverPage />, path);
    const user = userEvent.setup();
    const region = screen.getByRole('region', { name: /Explore/ });
    const sections = NAV.filter((entry) => starters(OPENERS).some((o) => sectionEntryForFamily(o.family) === entry));
    expect(within(region).getAllByRole('link').map((link) => link.getAttribute('aria-label')))
      .toEqual(sections.map((entry) => entry.label));
    await waitFor(() => expect(screen.queryByText('Loading data…')).not.toBeInTheDocument());
    for (const entry of sections) {
      const link = within(region).getByRole('link', { name: entry.label });
      expect(link.querySelector('path')).toHaveAttribute('d', entry.icon);
      await user.click(link);
      expect(screen.getByTestId('location').textContent).toBe(`${path === '/preview' ? path : ''}${entry.to}`);
    }
    await user.click(screen.getByRole('button', { name: new RegExp(`^${IQ_NAV.label}`) }));
    expect(screen.getByTestId('location').textContent).toBe(`${path === '/preview' ? path : ''}${IQ_NAV.to}`);
  });

  it('fills the six compact tiles from the semantic model', async () => {
    vi.mocked(executeDax).mockResolvedValueOnce([{
      '[Tickets]': 2770, '[ZeroTouchWeek]': 0.36508, '[OpenTickets]': 34,
      '[Csat]': 4.2722, '[BreachesWeek]': 2, '[CreditWeek]': 9250,
    }]);
    const { container } = mount(<CoverPage />);
    const tiles = await screen.findAllByTitle(/Measure .+ — semantic model/);
    expect(tiles).toHaveLength(6);
    for (const [label, value] of [
      ['Tickets', fmtInt(2770)], ['Zero-touch, last week', fmtPct(0.36508)],
      ['Open tickets', fmtInt(34)], ['CSAT', fmtDec(4.2722)],
      ['XLA breaches, last week', fmtInt(2)], ['Credit owed, last week', fmtEur(9250)],
    ]) {
      const tile = tiles.find((t) => within(t).queryByText(label));
      expect(tile, label).toBeDefined();
      expect(within(tile!).getByText(value)).toBeInTheDocument();
    }
    expect(executeDax).toHaveBeenCalledWith(COVER_DAX);
    expectNoBrokenNumbers(container);
  });
  it('keeps the questions available after a data error and supports retry', async () => {
    vi.mocked(executeDax).mockRejectedValueOnce(new Error('Model unavailable'));
    mount(<CoverPage />);
    expect(await screen.findByText('Model unavailable')).toBeInTheDocument();
    expect(screen.queryAllByTitle(/Measure .+ — semantic model/)).toHaveLength(0);
    expect(screen.getByRole('button', { name: starters(OPENERS)[0].label })).toBeEnabled();
    await userEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findAllByTitle(/Measure .+ — semantic model/)).toHaveLength(6);
    expect(screen.queryByText('Model unavailable')).not.toBeInTheDocument();
  });

  it('leaves workspace KPIs on the default presentation', () => {
    render(<KpiCard label="Tickets" value="81" measure="Tickets" hint="In scope" />);
    const tile = screen.getByTitle('Measure Tickets — semantic model');
    expect(tile).not.toHaveClass('cover-kpi');
    expect(within(tile).getByText('81')).toHaveClass('text-xl');
    expect(within(tile).getByText('In scope')).toBeInTheDocument();
  });
});

describe('the contract section', () => {
  it('names every agreement', () => {
    mount(<ContractsPage />);
    for (const a of AGREEMENTS) {
      expect(screen.getAllByText(new RegExp(a.customer)).length).toBeGreaterThan(0);
    }
  });

  /**
   * The load-bearing test of the whole demo.
   *
   * This screen exists to show that the obligation is set by the contract, not by the figure. The moment someone
   * adds a KPI strip here to make the page look balanced, the argument collapses — and it would
   * collapse silently, because a page with numbers on it looks *better*.
   *
   * The assertion is structural rather than visual on purpose. The page does render digits —
   * "40%", "10 business days", "5%" — but those are quoted clause terms, transcribed from the
   * XLA clauses, not results. A regex over the rendered text cannot tell a quoted term from
   * a measurement, so it would either pass on a page full of KPIs or fail on faithful contract
   * language. What actually matters is the wiring: this module must never reach the semantic
   * model. If it does not import the query layer, it cannot display a measured figure.
   */
  it('never reaches the semantic model', () => {
    const src = readFileSync(
      join(process.cwd(), 'src', 'pages', 'ContractsPage.tsx'),
      'utf8',
    );
    expect(src).not.toMatch(/useDax|@\/data\/queries|executeDax|_DAX\b/);
  });
});

describe('the diagnostic', () => {
  /**
   * Rendered with no auth context on purpose: sign-in is the most likely broken link, and a
   * diagnostic that needs sign-in cannot report on sign-in. If this ever starts requiring the
   * auth provider, it has stopped being a diagnostic.
   */
  it('mounts outside the guard', () => {
    const { container } = render(
      <MemoryRouter>
        <DiagnosticPage />
      </MemoryRouter>,
    );
    expect(screen.getByText(/Run the diagnostic/)).toBeTruthy();
    expectNoBrokenNumbers(container);
  });

  it('is absent from the navigation', () => {
    // Reachable by URL, never advertised: it is a repair tool, not a screen.
    expect(ALL_NAV.some((n) => n.to.includes('diagnostic'))).toBe(false);
  });
});

/**
 * Architecture was routed twice and linked from nowhere, and `WorkspaceLayout` — which titles
 * a page by looking it up in the nav manifest — rendered it with no heading at all. Both
 * failures were silent: the route resolved, the page mounted, and nothing said it was
 * unreachable. These two pin the fix rather than the symptom.
 */
describe('second-rank destinations', () => {
  it('are titled, so a page cannot render headless', () => {
    for (const entry of SECONDARY_NAV) {
      expect(ALL_NAV.find((n) => n.to === entry.to)?.label).toBeTruthy();
      expect(ALL_NAV.find((n) => n.to === entry.to)?.blurb).toBeTruthy();
    }
  });

  it('stay out of the four questions the console answers', () => {
    // Kept out of NAV so "every family lands on a listed section" keeps meaning what it says.
    const primary = new Set(NAV.map((n) => n.to));
    for (const entry of SECONDARY_NAV) expect(primary.has(entry.to)).toBe(false);
    for (const to of Object.values(SECTION_BY_FAMILY)) expect(primary.has(to)).toBe(true);
  });
});

/**
 * A focus anchor that matches no `Section id` scrolls nowhere and fails nothing. Pinned
 * against the ids the pages actually declare, read from source: the alternative is a typo
 * that only shows up as a card that quietly does not scroll.
 */
describe('focus anchors', () => {
  it('point at a section id that exists on the page they land on', () => {
    const fileFor: Record<string, string> = {
      '/portfolio': 'PortfolioPage.tsx',
      '/experience': 'ExperiencePage.tsx',
      '/agents': 'AgentsPage.tsx',
      '/contracts': 'ContractsPage.tsx',
      '/xla': 'XlaPage.tsx',
    };

    for (const [family, anchor] of Object.entries(FOCUS_BY_FAMILY)) {
      const route = SECTION_BY_FAMILY[family as keyof typeof SECTION_BY_FAMILY];
      const src = readFileSync(join(process.cwd(), 'src', 'pages', fileFor[route]), 'utf8');
      expect(src).toMatch(new RegExp(`id="${anchor}"`));
    }
  });
});
