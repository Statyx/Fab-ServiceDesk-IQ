import { act, fireEvent, render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { MemoryRouter } from 'react-router-dom';

import App from '@/App';
import { IqInPracticePage } from '@/pages/IqInPracticePage';
import {
  businessDaysAfter,
  dossierDax,
  dossierMessage,
  dossierPrompt,
  qualifyDossier,
  relevantWebNotes,
  relevantWorkCase,
  type DossierCase,
} from '@/domain/dossier';
import { DOSSIER_REFERENCE, DOSSIER_WEB_CONTEXT, DOSSIER_WORK_CONTEXT } from '@/services/dossier';

const stage = vi.hoisted(() => ({ STAGE_MS: 0, SEND_MS: 0 }));
vi.mock('@/services/stage', () => ({
  get STAGE_MS() { return stage.STAGE_MS; },
  get SEND_MS() { return stage.SEND_MS; },
}));
const auth = vi.hoisted(() => ({ isAuthenticated: true, loading: false, user: null, signOut: vi.fn() }));
vi.mock('@/hooks/AuthContext', () => ({ useAuth: () => auth }));
vi.mock('@/services/dataAgent', () => ({
  askDataAgent: vi.fn(), dataAgentConfigured: () => true,
  DataAgentNotConfiguredError: class extends Error {},
}));
vi.mock('@/services/powerbi', () => ({
  executeDax: vi.fn().mockRejectedValue(new Error('Unexpected live query')),
  semanticModelId: 'test-model', powerbiConfigured: true,
}));

const { scenarioId, asOf, week } = DOSSIER_REFERENCE;
const [fabrikam, litware] = DOSSIER_REFERENCE.cases;
const workFor = (item: DossierCase) => relevantWorkCase(item, DOSSIER_WORK_CONTEXT, scenarioId, asOf, week);

beforeEach(() => {
  stage.STAGE_MS = 0;
  stage.SEND_MS = 0;
  auth.isAuthenticated = true;
  Element.prototype.scrollIntoView = vi.fn();
});
afterEach(() => {
  vi.useRealTimers();
});

describe('dossier scenario', () => {
  it('holds two identical drops against the same target', () => {
    expect(fabrikam.id).toBe('fabrikam-zt');
    expect(litware.id).toBe('litware-zt');
    for (const item of [fabrikam, litware]) {
      expect(item.facts.zeroTouch / item.facts.tickets).toBeCloseTo(item.facts.current, 3);
      expect(item.facts.current).toBeLessThan(item.facts.target);
      expect(item.facts.target).toBe(0.4);
    }
    expect(fabrikam.facts.current).toBeCloseTo(litware.facts.current, 3);
    expect(fabrikam.facts.previous).toBeCloseTo(litware.facts.previous, 3);
    expect(fabrikam.facts.credit).toBe(9250);
    expect(litware.facts.credit).toBe(0);
  });

  it('counts ten business days after the closed week for the remediation deadline', () => {
    expect(week.end).toBe('2026-09-20');
    expect(businessDaysAfter(week.end, 10)).toBe('2026-10-02');
    expect(businessDaysAfter('2026-09-25', 1)).toBe('2026-09-28');
  });
});

describe('dossier qualification', () => {
  it('does not infer a consequence from the figures alone', () => {
    for (const item of [fabrikam, litware]) {
      const action = qualifyDossier(item, 'facts', week);
      expect(action.treatment).toBe('unqualified');
      expect(action.title).toBe('Consequence not yet qualified');
      expect(dossierMessage(item, action, null, week)).toBeNull();
    }
  });

  it('qualifies identical drops differently using the applicable XLA clause', () => {
    const credit = qualifyDossier(fabrikam, 'contract', week);
    const plan = qualifyDossier(litware, 'contract', week);
    expect(credit.treatment).toBe('prepare-credit');
    expect(credit.title).toMatch(/9,250/);
    expect(plan.treatment).toBe('remediation-plan');
    expect(plan.title).toBe('Remediation plan due, no credit');
    expect(plan.next).toMatch(/2 October/);
  });

  it('withholds the consequence when the figures or the contract are excluded', () => {
    expect(qualifyDossier(fabrikam, 'contract', week, { includeFabric: false }).title).toBe('Figures not included');
    const noContract = qualifyDossier(litware, 'action', week, { includeFoundry: false });
    expect(noContract.treatment).toBe('unqualified');
    expect(noContract.next).toMatch(/contract clause is not included/);
  });

  it('lets Work IQ change the next step, never the contractual consequence', () => {
    const fw = workFor(fabrikam);
    const lw = workFor(litware);
    expect(fw?.recipient.name).toBe('Camille Laurent');
    expect(lw?.recipient.name).toBe('Priya Shah');

    const followed = qualifyDossier(fabrikam, 'work', week, { work: fw });
    expect(followed.treatment).toBe('follow-validation');
    expect(followed.next).toBe(fw!.nextStep);
    const planned = qualifyDossier(litware, 'work', week, { work: lw });
    expect(planned.treatment).toBe('remediation-plan');
    expect(planned.title).toBe('Remediation plan due, no credit');
    expect(planned.next).toBe(lw!.nextStep);

    // Work context is ignored before its step.
    expect(qualifyDossier(fabrikam, 'contract', week, { work: fw }).treatment).toBe('prepare-credit');
  });

  it('sends a review, not a clause, when the figures stop matching the reviewed case', () => {
    const drifted = { ...fabrikam, facts: { ...fabrikam.facts, zeroTouch: 90 } };
    expect(qualifyDossier(drifted, 'contract', week).treatment).toBe('review');
    const aboveTarget = { ...litware, facts: { ...litware.facts, current: 0.45, zeroTouch: 22.5 } };
    expect(qualifyDossier(aboveTarget, 'contract', week).treatment).toBe('review');
    const other = { ...fabrikam, id: 'contoso-zt' };
    expect(qualifyDossier(other, 'contract', week).treatment).toBe('review');
    expect(dossierMessage(other, qualifyDossier(other, 'contract', week), null, week)).toBeNull();
  });

  it('writes a message that carries the figures, the clause and the Work IQ context', () => {
    const fw = workFor(fabrikam)!;
    const text = dossierMessage(fabrikam, qualifyDossier(fabrikam, 'action', week, { work: fw }), fw, week)!;
    expect(text).toMatch(/^Hi Camille,/);
    expect(text).toMatch(/34%/);
    expect(text).toMatch(fabrikam.contract.xlaId);
    expect(text).toMatch(/€9,250/);
    expect(text).toMatch(/29 September/);

    const lw = workFor(litware)!;
    const plan = dossierMessage(litware, qualifyDossier(litware, 'action', week, { work: lw }), lw, week)!;
    expect(plan).toMatch(/^Hi Priya,/);
    expect(plan).toMatch(/no service credit applies/);
    expect(plan).toMatch(/2 October/);
  });

  it('asks the agent for model measures and the ontology clause, never a recomputation', () => {
    const prompt = dossierPrompt(litware, week);
    expect(prompt).toMatch(litware.customerId);
    expect(prompt).toMatch(/\[XLA Credit \(Last Closed Week\)\]/);
    expect(prompt).toMatch(/do not recompute/);
    expect(dossierDax(fabrikam)).toMatch(/dim_customer\[customer_id\] = "CUS-FAB"/);
    expect(() => dossierDax({ ...fabrikam, customerId: 'CUS-FAB") || TRUE() || ("' })).toThrow('Invalid customer identifier.');
  });
});

describe('Work IQ and Web IQ context', () => {
  it('drops context from another scenario, date or a non-simulated source', () => {
    expect(relevantWorkCase(fabrikam, DOSSIER_WORK_CONTEXT, 'another', asOf, week)).toBeNull();
    expect(relevantWorkCase(fabrikam, DOSSIER_WORK_CONTEXT, scenarioId, '2026-09-24', week)).toBeNull();
    expect(relevantWorkCase(fabrikam, { ...DOSSIER_WORK_CONTEXT, simulated: false }, scenarioId, asOf, week)).toBeNull();
    const foreign = { ...fabrikam, customerId: 'CUS-LIT' };
    expect(relevantWorkCase(foreign, DOSSIER_WORK_CONTEXT, scenarioId, asOf, week)).toBeNull();
  });

  it('keeps only signals after the closed week, except a scheduled meeting', () => {
    const fw = workFor(fabrikam)!;
    for (const signal of fw.signals) {
      expect(signal.date > week.end).toBe(true);
      if (signal.kind !== 'meeting') expect(signal.date <= asOf).toBe(true);
    }
    expect(fw.signals.some((s) => s.kind === 'meeting')).toBe(true);
  });

  it('matches each public note to its customer and scenario date', () => {
    const fNotes = relevantWebNotes(fabrikam, DOSSIER_WEB_CONTEXT, scenarioId, asOf);
    const lNotes = relevantWebNotes(litware, DOSSIER_WEB_CONTEXT, scenarioId, asOf);
    expect(fNotes.map((n) => n.id)).toEqual(['SIM-WEB-FAB-01']);
    expect(lNotes.map((n) => n.id)).toEqual(['SIM-WEB-LIT-01']);
    expect(relevantWebNotes(fabrikam, DOSSIER_WEB_CONTEXT, scenarioId, '2026-01-01')).toEqual([]);
    const future = { ...DOSSIER_WEB_CONTEXT, notes: DOSSIER_WEB_CONTEXT.notes.map((n) => ({ ...n, publishedOn: '2026-12-01' })) };
    expect(relevantWebNotes(fabrikam, future, scenarioId, asOf)).toEqual([]);
  });
});

function mount() {
  return render(<MemoryRouter><IqInPracticePage /></MemoryRouter>);
}
const card = (name: string) => screen.getByRole('article', { name: `${name} dossier` });
const f = () => card('Fabrikam Industries');
const l = () => card('Litware Insurance');
const stepButton = (name: RegExp) => within(screen.getByRole('navigation', { name: 'Dossier context' })).getByRole('button', { name });

async function walkToSend(user = userEvent.setup()) {
  await user.click(screen.getByRole('button', { name: /Read the contracts/ }));
  await user.click(screen.getByRole('button', { name: /Add Work IQ/ }));
  await user.click(screen.getByRole('button', { name: /Add Web IQ/ }));
  await user.click(screen.getByRole('button', { name: /Find who to tell/ }));
  return user;
}

describe('dossier storyboard', () => {
  it('opens on two identical drops whose consequence is still unknown', () => {
    mount();
    expect(screen.getByRole('heading', { level: 1, name: 'Which XLA breaches need action?' })).toBeVisible();
    expect(screen.getByText('Two identical drops. Consequence still unknown.')).toBeVisible();
    expect(within(f()).getByText('Consequence not yet qualified')).toBeVisible();
    expect(within(l()).getByText('Consequence not yet qualified')).toBeVisible();
    expect(stepButton(/Send/)).toBeDisabled();
  });

  it('walks through the two treatments, work context, message and reset', async () => {
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Read the contracts/ }));
    expect(screen.getByText('Same figures. Different obligations.')).toBeVisible();
    expect(within(f()).getByRole('heading', { name: /Service credit of €9,250/ })).toBeVisible();
    expect(within(l()).getByRole('heading', { name: 'Remediation plan due, no credit' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: /Add Work IQ/ }));
    expect(within(f()).getByRole('heading', { name: 'Follow up on validation' })).toBeVisible();
    expect(within(l()).getByRole('heading', { name: 'Remediation plan due, no credit' })).toBeVisible();
    expect(within(f()).getByRole('list', { name: 'Fabrikam Industries Work IQ signals' })).toBeVisible();

    await user.click(screen.getByRole('button', { name: /Add Web IQ/ }));
    await user.click(screen.getByRole('button', { name: /Find who to tell/ }));
    const message = within(f()).getByRole('textbox', { name: 'Fabrikam Industries message' });
    expect((message as HTMLTextAreaElement).value).toMatch(/^Hi Camille,/);
    expect((message as HTMLTextAreaElement).value).toMatch(/Public context/);

    await user.click(screen.getByRole('button', { name: 'Reset' }));
    expect(within(f()).getByText('Consequence not yet qualified')).toBeVisible();
    expect(within(f()).queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('sends each message to the person Work IQ found', async () => {
    mount();
    await walkToSend();
    fireEvent.click(within(f()).getByRole('button', { name: 'Send in Teams' }));
    expect(within(f()).getByRole('status')).toHaveTextContent('Sent to Camille Laurent in Teams (simulated).');
    fireEvent.click(within(l()).getByRole('button', { name: 'Send in Teams' }));
    expect(within(l()).getByRole('status')).toHaveTextContent('Sent to Priya Shah in Teams (simulated).');
  });

  it('shows the contribution of Fabric and Foundry by withholding both drafts when either is excluded', async () => {
    mount();
    const user = await walkToSend();
    await user.click(screen.getByRole('checkbox', { name: 'Include Foundry IQ context' }));
    expect(screen.getByText('The contractual treatment is not established.')).toBeVisible();
    for (const c of [f(), l()]) {
      expect(within(c).queryByRole('textbox')).not.toBeInTheDocument();
      expect(within(c).getByText(/A definitive message is withheld/)).toBeVisible();
    }
    await user.click(screen.getByRole('checkbox', { name: 'Include Foundry IQ context' }));
    await user.click(screen.getByRole('checkbox', { name: 'Include Fabric IQ context' }));
    expect(within(f()).getByText('Figures not included')).toBeVisible();
    expect(within(f()).queryByRole('textbox')).not.toBeInTheDocument();
  });

  it('keeps a generic draft without a recipient when Work IQ is excluded', async () => {
    mount();
    const user = await walkToSend();
    await user.click(screen.getByRole('checkbox', { name: 'Include Work IQ context' }));
    expect(within(f()).getByRole('heading', { name: /Service credit of €9,250/ })).toBeVisible();
    expect(within(l()).getByText(/Recipient unknown/)).toBeVisible();
    expect(within(l()).getByRole('button', { name: 'Send in Teams' })).toBeDisabled();
  });

  it('reveals the model figures, the ontology chain and the clause on demand', async () => {
    mount();
    const user = userEvent.setup();
    await user.click(screen.getByRole('button', { name: /Read the contracts/ }));
    await user.click(within(f()).getByRole('button', { name: 'Figures' }));
    expect(within(f()).getByRole('region', { name: 'Fabrikam Industries figures evidence' })).toHaveTextContent('CUS-FAB');
    await user.click(within(l()).getByRole('button', { name: 'Contract clause' }));
    expect(within(l()).getByText(litware.contract.clause)).toBeVisible();
    await user.click(within(l()).getByRole('button', { name: 'Why this cause?' }));
    expect(within(l()).getByRole('region', { name: 'Litware Insurance scope evidence' })).toHaveTextContent(litware.scope.relations[0]);
  });

  it('does not claim copying succeeded if clipboard access fails', async () => {
    mount();
    await walkToSend();
    Object.defineProperty(navigator, 'clipboard', {
      configurable: true, value: { writeText: vi.fn().mockRejectedValue(new Error('denied')) },
    });
    await act(async () => { fireEvent.click(within(f()).getByRole('button', { name: 'Copy message' })); });
    expect(within(f()).getByRole('alert')).toHaveTextContent('Clipboard access failed');
    expect(within(f()).queryByText('Copied.')).not.toBeInTheDocument();
  });

  it('marks each added layer with a pause, and goes back immediately', async () => {
    vi.useFakeTimers();
    stage.STAGE_MS = 2000;
    mount();
    fireEvent.click(screen.getByRole('button', { name: /Read the contracts/ }));
    expect(screen.getByRole('status')).toHaveTextContent('Foundry IQ is reading the two XLA clauses');
    expect(within(f()).getByText('Consequence not yet qualified')).toBeInTheDocument();
    act(() => { vi.advanceTimersByTime(2000); });
    expect(within(f()).getByRole('heading', { name: /Service credit/ })).toBeInTheDocument();
    fireEvent.click(stepButton(/Facts/));
    expect(within(f()).getByText('Consequence not yet qualified')).toBeInTheDocument();
  });
});

describe('dossier navigation', () => {
  it.each(['/preview/iq-in-practice', '/preview/iq-in-practice/', '/iq-in-practice/'])(
    'opens the storyboard on %s',
    async (path) => {
      window.history.replaceState({}, '', path);
      render(<App />);
      expect(await screen.findByRole('heading', { level: 1, name: 'Which XLA breaches need action?' }, { timeout: 5000 })).toBeVisible();
    },
  );

  it('keeps the real route behind authentication', () => {
    auth.isAuthenticated = false;
    window.history.replaceState({}, '', '/iq-in-practice');
    render(<App />);
    expect(window.location.pathname).toBe('/auth');
  });
});
