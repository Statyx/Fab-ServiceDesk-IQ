import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterAll, beforeAll, beforeEach, describe, expect, it, vi } from 'vitest';

import App from '@/App';
import { AssistantProvider } from '@/components/AssistantProvider';
import { QuerySourceContext } from '@/data/querySource';
import { useAssistant } from '@/domain/assistant';
import { OPENERS, starters } from '@/domain/openers';
import { IQ_NAV, NAV, SECTION_BY_FAMILY, sectionEntryForFamily } from '@/domain/nav';
import { previewSource } from '@/preview/data';
import { COVER_DAX } from '@/data/queries';
import { executeDax } from '@/services/powerbi';
import { askDataAgent } from '@/services/dataAgent';

vi.mock('@/hooks/AuthContext', () => ({
  useAuth: () => ({ isAuthenticated: false, loading: false, user: null, signOut: vi.fn() }),
}));
vi.mock('@/services/powerbi', () => ({
  executeDax: vi.fn().mockRejectedValue(new Error('Power BI must not be called from preview')),
  semanticModelId: 'test-model',
  powerbiConfigured: true,
}));
vi.mock('@/services/dataAgent', () => ({
  askDataAgent: vi.fn(),
  dataAgentConfigured: () => true,
  DataAgentNotConfiguredError: class extends Error {},
}));

const COVER_SECTIONS = NAV.filter((entry) =>
  starters(OPENERS).some((o) => sectionEntryForFamily(o.family) === entry),
).map((entry) => entry.label);

beforeAll(() => {
  // jsdom has no scrolling implementation.
  Element.prototype.scrollIntoView = vi.fn();
});
afterAll(() => {
  Reflect.deleteProperty(Element.prototype, 'scrollIntoView');
});
beforeEach(() => {
  vi.clearAllMocks();
});

describe('development preview', () => {
  it('renders labelled cover tiles without an account or a Power BI request', async () => {
    window.history.replaceState({}, '', '/preview');
    render(<App />);

    expect(await screen.findAllByTitle(/^Measure /)).toHaveLength(6);
    expect(screen.queryByText(/preview/i)).not.toBeInTheDocument();
    expect(screen.queryByRole('note')).not.toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Open live app' })).not.toBeInTheDocument();
    expect(screen.queryByText('Live Fabric data')).not.toBeInTheDocument();
    expect(screen.queryByText('The query failed')).not.toBeInTheDocument();
    expect(screen.queryByTitle(/semantic model/)).not.toBeInTheDocument();
    expect(executeDax).not.toHaveBeenCalled();
  });

  it.each(['/preview/portfolio', '/preview/experience', '/preview/agents', '/preview/contracts', '/preview/xla'])(
    'keeps sample data on %s without interactive authentication',
    async (path) => {
      window.history.replaceState({}, '', path);
      render(<App />);
      await screen.findByRole('navigation', { name: 'Main navigation' });
      expect(screen.queryByText(/preview/i)).not.toBeInTheDocument();
      await waitFor(() => expect(screen.queryByText('Loading data…')).not.toBeInTheDocument());
      expect(screen.queryByText('The query failed')).not.toBeInTheDocument();
      expect(screen.getByRole('textbox', { name: 'Ask the Zava assistant a question' })).toBeDisabled();
      expect(executeDax).not.toHaveBeenCalled();
      expect(askDataAgent).not.toHaveBeenCalled();
    },
  );

  it('preserves cover navigation from the cover starters', async () => {
    window.history.replaceState({}, '', '/preview');
    render(<App />);
    await screen.findByRole('navigation', { name: 'Main navigation' });
    await userEvent.click(screen.getByRole('button', { name: starters(OPENERS)[0].label }));
    expect(window.location.pathname).toBe(`/preview${SECTION_BY_FAMILY[starters(OPENERS)[0].family]}`);
    expect(await screen.findByText(/Reading service figures, XLA clauses and ontology relationships/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(executeDax).not.toHaveBeenCalled();
    expect(askDataAgent).not.toHaveBeenCalled();
  });

  it.each(COVER_SECTIONS)(
    'opens the same %s screen from its header link and cover title without starting an answer',
    async (label) => {
      window.history.replaceState({}, '', '/preview');
      render(<App />);
      const user = userEvent.setup();
      await screen.findByRole('navigation', { name: 'Main navigation' });
      const header = within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', { name: label });
      const card = within(screen.getByRole('region', { name: /Explore/ })).getByRole('link', { name: label });
      expect(card).toHaveAttribute('href', header.getAttribute('href'));
      expect(card.querySelector('path')).toHaveAttribute('d', header.querySelector('path')!.getAttribute('d'));
      await user.click(card);
      expect(await screen.findByRole('heading', { level: 1, name: label })).toBeVisible();
      const destination = window.location.pathname;
      expect(window.location.search).toBe('');
      expect(screen.queryByText(/Reading service figures, XLA clauses and ontology relationships/)).not.toBeInTheDocument();
      await user.click(screen.getByRole('link', { name: /Zava Service Desk/ }));
      await user.click(within(screen.getByRole('navigation', { name: 'Main navigation' })).getByRole('link', { name: label }));
      expect(window.location.pathname).toBe(destination);
      expect(window.location.search).toBe('');
      expect(await screen.findByRole('heading', { level: 1, name: label })).toBeVisible();
      expect(askDataAgent).not.toHaveBeenCalled();
    },
  );

  it('uses Zava IQ consistently and preserves the existing URL', async () => {
    window.history.replaceState({}, '', '/preview');
    render(<App />);
    await screen.findByRole('navigation', { name: 'Main navigation' });
    expect(within(screen.getByRole('navigation', { name: 'Main navigation' }))
      .getByRole('link', { name: 'Zava IQ' })).toHaveAttribute('href', `/preview${IQ_NAV.to}`);
    await userEvent.click(screen.getByRole('button', { name: /^Zava IQ/ }));
    expect(await screen.findByRole('heading', { name: 'Which XLA breaches need action?' }, { timeout: 5000 })).toBeVisible();
    expect(document.querySelector('.iq-intro .cover-eyebrow')).toHaveTextContent('Zava IQ');
    expect(screen.queryByText('IQ in practice')).not.toBeInTheDocument();
  });

  it.each(['/preview/portfolio/', '/preview/xla/'])('retains the title on %s', async (path) => {
    window.history.replaceState({}, '', path);
    render(<App />);
    const label = path.includes('portfolio') ? 'Portfolio' : 'XLA & credits';
    expect(await screen.findByRole('heading', { level: 1, name: label })).toBeVisible();
  });

  it('rejects an unknown query instead of using live transport or fake zero rows', async () => {
    await expect(previewSource.execute('EVALUATE an_unknown_query'))
      .rejects.toThrow('No design-preview data is defined');
    expect(executeDax).not.toHaveBeenCalled();
  });

  it('does not let a caller mutate the next set of sample figures', async () => {
    const rows = await previewSource.execute(COVER_DAX);
    const original = rows[0]['[Tickets]'];
    expect(original).toBeGreaterThan(0);
    rows[0]['[Tickets]'] = 999;
    expect((await previewSource.execute(COVER_DAX))[0]['[Tickets]']).toBe(original);
  });
});

function LiveQuestionProbe() {
  const { askText, turns } = useAssistant();
  return (
    <>
      <button onClick={() => askText('A new question with sample context')}>Ask live</button>
      <p>{turns.at(-1)?.error}</p>
    </>
  );
}

it('never forwards sample context to a live agent, including page-triggered questions', async () => {
  render(
    <QuerySourceContext.Provider value={previewSource}>
      <AssistantProvider><LiveQuestionProbe /></AssistantProvider>
    </QuerySourceContext.Provider>,
  );
  await userEvent.click(screen.getByRole('button', { name: 'Ask live' }));
  expect(await screen.findByText(/sign in to ask your own question/)).toBeInTheDocument();
  expect(askDataAgent).not.toHaveBeenCalled();
});
