/**
 * The "Zava IQ" dossier: two weeks below target, taken from the figure to the message.
 *
 * Two customers fell below the same 40% zero-touch target in the same closed week:
 * Fabrikam from 46% to 34%, Litware from 48% to 38%. The figures alone cannot say what Zava owes; the contract can, and it says two
 * opposite things. Work IQ then shows what is already underway and who has to act, and Web IQ
 * adds public context for the conversation. Each layer is switchable, so the room can watch the
 * conclusion degrade honestly when one of them is removed.
 *
 * These are two reviewed demo cases, not a general-purpose contract engine. Every conclusion
 * below is guarded on the exact case it was written for: if the figures stop matching, the card
 * says "review" rather than applying a clause to numbers it was not written against.
 *
 * The contract layer is labelled "Foundry IQ · contract (simulated)". The clause itself is real
 * — it is the text bound in the ontology as `Xla.clause_text` — but no Foundry agent is called in
 * this demo. Work IQ and Web IQ signals are fictional and flagged `simulated` in their files.
 */
export type DossierStep = 'facts' | 'contract' | 'work' | 'web' | 'action';

export interface ClosedWeek {
  start: string;
  end: string;
  label: string;
}

export interface DossierCase {
  id: string;
  customerId: string;
  customer: string;
  facts: {
    previous: number;
    previousTickets: number;
    previousZeroTouch: number;
    current: number;
    tickets: number;
    zeroTouch: number;
    target: number;
    /** `[XLA Credit (Last Closed Week)]` as the model evaluated it. Never recomputed here. */
    credit: number;
  };
  scope: { chain: string[]; relations: string[]; cause: string; impacted: string };
  contract: {
    reference: string;
    xlaId: string;
    treatment: string;
    penaltyPct: number;
    capPct: number;
    monthlyFeeEur: number;
    clause: string;
  };
}

export interface DossierInput {
  scenarioId: string;
  asOf: string;
  week: ClosedWeek;
  cases: DossierCase[];
}

export interface WorkSignal {
  id: string;
  kind: string;
  date: string;
  who: string;
  title: string;
  detail: string;
}

export interface WorkCase {
  caseId: string;
  customerId: string;
  simulated: boolean;
  impact: string;
  nextStep: string;
  signals: WorkSignal[];
  people: { name: string; role: string }[];
  recipient: { name: string; role: string; channel: string; reasons: string[] };
}

export interface WorkContext {
  scenarioId: string;
  asOf: string;
  simulated: boolean;
  cases: WorkCase[];
}

export interface WebNote {
  id: string;
  caseId: string;
  customerId: string;
  publishedOn: string;
  source: string;
  headline: string;
  summary: string;
  meetingPrompt: string;
  simulated: boolean;
}

export interface WebContext {
  scenarioId: string;
  asOf: string;
  simulated: boolean;
  notes: WebNote[];
}

export type Treatment =
  | 'unqualified'
  | 'prepare-credit'
  | 'remediation-plan'
  | 'follow-validation'
  | 'review';

export interface DossierAction {
  treatment: Treatment;
  title: string;
  next: string;
  reason: string;
  unknowns: string[];
}

export const DOSSIER_STEPS: { id: DossierStep; label: string }[] = [
  { id: 'facts', label: 'Facts' },
  { id: 'contract', label: 'Contract' },
  { id: 'work', label: 'Work IQ' },
  { id: 'web', label: 'Web IQ' },
  { id: 'action', label: 'Send' },
];

export function dossierStepAtLeast(step: DossierStep, minimum: DossierStep): boolean {
  return (
    DOSSIER_STEPS.findIndex((s) => s.id === step) >=
    DOSSIER_STEPS.findIndex((s) => s.id === minimum)
  );
}

function isDateKey(value: string): boolean {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value)) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.getTime()) && parsed.toISOString().slice(0, 10) === value;
}

/** Ten business days from the Monday after the closed week, the clause's deadline. */
export function businessDaysAfter(dateKey: string, days: number): string {
  const d = new Date(`${dateKey}T00:00:00Z`);
  let left = days;
  while (left > 0) {
    d.setUTCDate(d.getUTCDate() + 1);
    const wd = d.getUTCDay();
    if (wd !== 0 && wd !== 6) left -= 1;
  }
  return d.toISOString().slice(0, 10);
}

export function longDate(dateKey: string): string {
  return new Date(`${dateKey}T00:00:00Z`).toLocaleDateString('en-GB', {
    day: 'numeric',
    month: 'long',
    timeZone: 'UTC',
  });
}

const pct = (v: number) => `${Math.round(v * 100)}%`;
const eur = (v: number) =>
  new Intl.NumberFormat('en-GB', { style: 'currency', currency: 'EUR', maximumFractionDigits: 0 }).format(v);

/** The figures must be the ones the case was reviewed against, and internally consistent. */
function factsHold(item: DossierCase): boolean {
  const f = item.facts;
  const finite = [f.previous, f.current, f.tickets, f.zeroTouch, f.target, f.credit].every(Number.isFinite);
  return (
    finite &&
    f.tickets > 0 &&
    f.previousTickets > 0 &&
    Math.abs(f.zeroTouch / f.tickets - f.current) < 0.0005 &&
    Math.abs(f.previousZeroTouch / f.previousTickets - f.previous) < 0.0005 &&
    f.current < f.target
  );
}

/**
 * What the combined context supports, layer by layer.
 *
 * Work IQ can change who acts next and whether a step is already done. It never changes the
 * consequence, which only the contract sets.
 */
export function qualifyDossier(
  item: DossierCase,
  step: DossierStep,
  week: ClosedWeek,
  options: { includeFabric?: boolean; includeFoundry?: boolean; work?: WorkCase | null } = {},
): DossierAction {
  const { includeFabric = true, includeFoundry = true, work = null } = options;
  const base: DossierAction = {
    treatment: 'unqualified',
    title: 'Consequence not yet qualified',
    next: 'Read the contract before announcing a credit.',
    reason: 'A week below target does not, on its own, establish what Zava owes.',
    unknowns: ['Contractual consequence', 'Work already underway'],
  };
  if (!includeFabric) {
    return {
      ...base,
      title: 'Figures not included',
      next: 'Include the measured figures before applying a contract to this week.',
      reason: 'The contract and the work context alone do not establish the measured rate.',
      unknowns: ['Measured zero-touch rate and ticket volume', 'Contractual consequence'],
    };
  }
  if (step === 'facts') return base;
  if (!includeFoundry) {
    return { ...base, next: 'The contract clause is not included. Restore it to qualify this week.' };
  }
  if (!factsHold(item)) {
    return {
      ...base,
      treatment: 'review',
      title: 'Evidence needs review',
      next: 'The figures do not match the reviewed case. Confirm the closed week and the measures.',
    };
  }

  if (item.id === 'litware-zt' && item.contract.treatment === 'remediation' && item.facts.credit === 0) {
    const due = businessDaysAfter(week.end, 10);
    const action: DossierAction = {
      treatment: 'remediation-plan',
      title: 'Remediation plan due, no credit',
      next: `Write the remediation plan and send it to the customer by ${longDate(due)}.`,
      reason: `${item.contract.xlaId} attaches no service credit to this breach: a written plan within 10 business days.`,
      unknowns: ['Content of the remediation plan', 'Who answers the customer'],
    };
    if (!work || !dossierStepAtLeast(step, 'work')) return action;
    return { ...action, next: work.nextStep, unknowns: ['Content of the remediation plan'] };
  }

  if (
    item.id === 'fabrikam-zt' &&
    item.contract.treatment === 'credit' &&
    item.facts.credit > 0 &&
    item.contract.penaltyPct > 0
  ) {
    const action: DossierAction = {
      treatment: 'prepare-credit',
      title: `Service credit of ${eur(item.facts.credit)} under ${item.contract.xlaId}`,
      next: 'Prepare the credit note on the September invoice and explain the cause to the customer.',
      reason: `${item.contract.penaltyPct}% of the monthly fee, within the ${item.contract.capPct}% monthly cap, as evaluated by the semantic model.`,
      unknowns: ['Finance validation of the credit note', 'Work already underway'],
    };
    if (!work || !dossierStepAtLeast(step, 'work')) return action;
    return {
      ...action,
      treatment: 'follow-validation',
      title: 'Follow up on validation',
      next: work.nextStep,
      unknowns: ['Validation and issuance of the credit note'],
    };
  }

  return {
    ...base,
    treatment: 'review',
    title: 'Review the applicable consequence',
    next: 'The contract on file does not support the prepared conclusion for these figures.',
  };
}

export function relevantWorkCase(
  item: DossierCase,
  context: WorkContext,
  scenarioId: string,
  asOf: string,
  week: ClosedWeek,
): WorkCase | null {
  if (!context.simulated || context.scenarioId !== scenarioId || context.asOf !== asOf || !isDateKey(asOf)) {
    return null;
  }
  const found = context.cases.find(
    (c) => c.simulated === true && c.caseId === item.id && c.customerId === item.customerId,
  );
  if (!found || !found.recipient?.name?.trim()) return null;
  // Nothing from before the week closed, and nothing from the future except a scheduled meeting.
  const signals = found.signals.filter(
    (s) => isDateKey(s.date) && s.date > week.end && (s.kind === 'meeting' || s.date <= asOf),
  );
  return signals.length ? { ...found, signals } : null;
}

export function relevantWebNotes(
  item: DossierCase,
  context: WebContext,
  scenarioId: string,
  asOf: string,
): WebNote[] {
  if (!context.simulated || context.scenarioId !== scenarioId || context.asOf !== asOf || !isDateKey(asOf)) {
    return [];
  }
  return context.notes.filter(
    (n) =>
      n.simulated === true &&
      n.caseId === item.id &&
      n.customerId === item.customerId &&
      isDateKey(n.publishedOn) &&
      n.publishedOn <= asOf,
  );
}

export function webDraftContext(notes: WebNote[]): string {
  return notes
    .map((n) => `Public context — ${n.source}, ${n.publishedOn}: ${n.summary} ${n.meetingPrompt}`)
    .join('\n\n');
}

const firstName = (who: string) => who.split(' · ')[0].split(' ')[0];

function gapSentence(item: DossierCase, week: ClosedWeek): string {
  const f = item.facts;
  return (
    `${item.customer}'s zero-touch resolution rate fell to ${pct(f.current)} in the week of ` +
    `${longDate(week.start)} (${f.zeroTouch} of ${f.tickets} tickets), against a weekly target of ` +
    `${pct(f.target)} and ${pct(f.previous)} the week before.`
  );
}

/** The message to the person Work IQ identifies. Without Work IQ, a generic draft. */
export function dossierMessage(
  item: DossierCase,
  action: DossierAction,
  work: WorkCase | null,
  week: ClosedWeek,
): string | null {
  const gap = gapSentence(item, week);
  const c = item.contract;
  const meeting = work?.signals.find((s) => s.kind === 'meeting');
  const beforeMeeting = meeting ? ` before the ${meeting.title.split(' · ').pop()} on ${longDate(meeting.date)}` : '';

  if (action.treatment === 'prepare-credit') {
    return (
      `${gap} Under ${c.xlaId} of ${c.reference}, Zava owes a service credit of ${c.penaltyPct}% of the ` +
      `monthly fee: ${eur(item.facts.credit)} on the September invoice, within the ${c.capPct}% cap. ` +
      `Please prepare the credit note for validation. Cause: ${item.scope.cause}`
    );
  }
  if (action.treatment === 'follow-validation' && work) {
    const email = work.signals.find((s) => s.kind === 'email');
    const file = work.signals.find((s) => s.kind === 'file');
    const preparer = email ? firstName(email.who) : 'Finance';
    return (
      `Hi ${firstName(work.recipient.name)}, ${gap} Under ${c.xlaId} of ${c.reference}, Zava owes ` +
      `${c.penaltyPct}% of the monthly fee: ${eur(item.facts.credit)} on the September invoice, within ` +
      `the ${c.capPct}% cap. ${preparer} has already drafted the credit note` +
      `${file ? ` (${file.title})` : ''} and is waiting for your validation. The cause is known: ` +
      `${item.scope.cause} (${item.scope.impacted}). Could you validate it${beforeMeeting}?`
    );
  }
  if (action.treatment === 'remediation-plan') {
    const due = longDate(businessDaysAfter(week.end, 10));
    if (!work) {
      return (
        `${gap} Under ${c.xlaId} of ${c.reference}, no service credit applies, but a written ` +
        `remediation plan is due within 10 business days, by ${due}. Cause: ${item.scope.cause}`
      );
    }
    const chat = work.signals.find((s) => s.kind === 'teams');
    const about = chat ? `on ${firstName(chat.who)}'s question from ${longDate(chat.date)}` : 'on the customer question';
    return (
      `Hi ${firstName(work.recipient.name)}, ${about}: ${gap} Under ${c.xlaId} of ${c.reference}, no ` +
      `service credit applies, but a written remediation plan is due within 10 business days, by ` +
      `${due}. The drop comes from ${item.scope.cause.charAt(0).toLowerCase()}${item.scope.cause.slice(1)} ` +
      `Could you send the plan${beforeMeeting}?`
    );
  }
  return null;
}

/** The question the data agent would be asked for this case, shown under "All evidence". */
export function dossierPrompt(item: DossierCase, week: ClosedWeek): string {
  return (
    `For ${item.customer} (${item.customerId}) in the closed week ${week.start} to ${week.end}, read ` +
    `[Zero-Touch % (Last Closed Week)], [Zero-Touch % (Previous Week)], [Tickets (Last Closed Week)], ` +
    `[Zero-Touch Target %] and [XLA Credit (Last Closed Week)] from the semantic model. Through the ` +
    `ontology, read the clause_text of ${item.contract.xlaId} in ${item.contract.reference} and the ` +
    `major incidents or applications linked to this week's tickets. Say what the contract makes Zava ` +
    `owe, quote the clause, and do not recompute the credit.`
  );
}

export function dossierDax(item: DossierCase): string {
  if (!/^[A-Z]{3}-[A-Z]{3}$/.test(item.customerId)) throw new Error('Invalid customer identifier.');
  return `EVALUATE CALCULATETABLE(
  ROW(
    "previous", [Zero-Touch % (Previous Week)],
    "current", [Zero-Touch % (Last Closed Week)],
    "tickets", [Tickets (Last Closed Week)],
    "target", [Zero-Touch Target %],
    "credit", [XLA Credit (Last Closed Week)]
  ),
  dim_customer[customer_id] = "${item.customerId}"
)`;
}
