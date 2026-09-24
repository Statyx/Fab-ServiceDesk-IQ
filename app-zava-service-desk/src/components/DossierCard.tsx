import { useEffect, useRef, useState } from 'react';

import {
  dossierDax,
  dossierMessage,
  dossierPrompt,
  dossierStepAtLeast,
  qualifyDossier,
  relevantWebNotes,
  webDraftContext,
  type ClosedWeek,
  type DossierCase,
  type DossierStep,
  type WorkCase,
} from '@/domain/dossier';
import { fmtEur, fmtInt, fmtPct } from '@/lib/format';
import { DOSSIER_REFERENCE, DOSSIER_WEB_CONTEXT } from '@/services/dossier';
import { SEND_MS } from '@/services/stage';

const SIGNAL_LABELS: Record<string, string> = {
  email: 'Outlook · email',
  teams: 'Teams · chat',
  meeting: 'Calendar · meeting',
  file: 'SharePoint · file',
};

const initials = (name: string) =>
  name
    .split(' ')
    .map((part) => part.charAt(0))
    .join('')
    .slice(0, 2)
    .toUpperCase();

interface Props {
  item: DossierCase;
  step: DossierStep;
  week: ClosedWeek;
  includeWork: boolean;
  includeFabric: boolean;
  includeFoundry: boolean;
  includeWeb: boolean;
  asOf: string;
  work?: WorkCase | null;
}

export function DossierCard({
  item,
  step,
  week,
  includeWork,
  includeFabric,
  includeFoundry,
  includeWeb,
  asOf,
  work = null,
}: Props) {
  const [panel, setPanel] = useState<'figures' | 'scope' | 'contract' | 'evidence' | null>(null);
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle');
  const [sendState, setSendState] = useState<'idle' | 'sending' | 'sent'>('idle');
  const sendTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (sendTimer.current) clearTimeout(sendTimer.current);
    },
    [],
  );

  const workReady = dossierStepAtLeast(step, 'work');
  const webReady = dossierStepAtLeast(step, 'web');
  const activeWork = includeWork && workReady ? work : null;
  const action = qualifyDossier(item, step, week, { includeFabric, includeFoundry, work: activeWork });
  const webNotes =
    includeWeb && webReady
      ? relevantWebNotes(item, DOSSIER_WEB_CONTEXT, DOSSIER_REFERENCE.scenarioId, asOf)
      : [];
  const facts = item.facts;
  const baseMessage = step === 'action' ? dossierMessage(item, action, activeWork, week) : null;
  const initialMessage =
    baseMessage && webNotes.length ? `${baseMessage}\n\n${webDraftContext(webNotes)}` : baseMessage;
  const [message, setMessage] = useState(initialMessage ?? '');
  const recipient = activeWork?.recipient ?? null;
  const credit = item.contract.treatment === 'credit';

  function togglePanel(next: NonNullable<typeof panel>) {
    setPanel((current) => (current === next ? null : next));
  }

  async function copyMessage() {
    if (!message) return;
    try {
      if (!navigator.clipboard) throw new Error('Clipboard unavailable');
      await navigator.clipboard.writeText(message);
      setCopyState('copied');
    } catch {
      setCopyState('failed');
    }
  }

  function sendMessage() {
    if (!recipient || !message.trim() || sendState !== 'idle') return;
    if (SEND_MS <= 0) {
      setSendState('sent');
      return;
    }
    setSendState('sending');
    sendTimer.current = setTimeout(() => {
      sendTimer.current = null;
      setSendState('sent');
    }, SEND_MS);
  }

  return (
    <article className={`glass dossier-card is-${action.treatment}`} aria-label={`${item.customer} dossier`}>
      <header>
        <span className="dossier-avatar" aria-hidden>
          {item.customer.charAt(0)}
        </span>
        <div>
          <h2>{item.customer}</h2>
          <p>
            {item.contract.xlaId} · {week.label} ({week.start} → {week.end})
          </p>
        </div>
      </header>

      <div className={`dossier-fact iq-source-fabric ${includeFabric ? '' : 'is-source-excluded'}`}>
        <span className="iq-source-badge">Fabric IQ · figures & scope</span>
        <strong>{includeFabric ? fmtPct(facts.current, 0) : '—'}</strong>
        <span>{includeFabric ? `Zero-touch, target ${fmtPct(facts.target, 0)}` : 'Figures and scope not included'}</span>
        {includeFabric ? (
          <small>
            {facts.zeroTouch} of {facts.tickets} tickets · {fmtPct(facts.previous, 0)} the week before
          </small>
        ) : null}
      </div>

      <div className="dossier-treatment" aria-live="polite">
        <span className="iq-eyebrow">
          {step === 'facts' ? 'From the figures alone' : step === 'action' ? 'Next step' : 'Consequence and next step'}
        </span>
        <h3>{action.title}</h3>
        <p>{action.next}</p>
      </div>

      {step !== 'facts' ? (
        <div className={`dossier-source-block iq-source-foundry ${includeFoundry ? '' : 'is-source-excluded'}`}>
          <span className="iq-source-badge">Foundry IQ · contract (simulated)</span>
          <p>
            {!includeFoundry
              ? 'Contract context is not included. The consequence remains unqualified.'
              : credit
                ? `${item.contract.xlaId}: below 40% in an ISO week, Zava credits ${item.contract.penaltyPct}% of the monthly fee, within a ${item.contract.capPct}% monthly cap.`
                : `${item.contract.xlaId}: below 40% in an ISO week, a written remediation plan within 10 business days. No service credit applies.`}
          </p>
          <small>
            {includeFoundry
              ? `Clause read from ONT_ServiceDesk · ${item.contract.reference}`
              : 'Restore this context to qualify the week'}
          </small>
        </div>
      ) : null}

      {workReady ? (
        <div className={`dossier-source-block dossier-work-note iq-source-work ${includeWork ? '' : 'is-source-excluded'}`}>
          <span className="iq-source-badge">Work IQ · simulated</span>
          {activeWork ? (
            <>
              <ul className="dossier-signals" aria-label={`${item.customer} Work IQ signals`}>
                {activeWork.signals.map((signal) => (
                  <li key={signal.id} className={`is-${signal.kind}`}>
                    <span className="dossier-signal-kind">
                      {SIGNAL_LABELS[signal.kind] ?? signal.kind} · {signal.date}
                    </span>
                    <strong>{signal.title}</strong>
                    <small>{signal.who}</small>
                    <p>{signal.detail}</p>
                  </li>
                ))}
              </ul>
              <div className="dossier-people" aria-label="People involved">
                {activeWork.people.map((person) => (
                  <span key={person.name} className="dossier-person">
                    <span aria-hidden>{initials(person.name)}</span>
                    {person.name}
                    <small>{person.role}</small>
                  </span>
                ))}
              </div>
              <div className="dossier-work-impact">
                <span className="iq-eyebrow">What Work IQ changes</span>
                <p>{activeWork.impact}</p>
              </div>
            </>
          ) : null}
          {!includeWork ? (
            <p>Work context is not included. What is already underway, and who owns it, is unknown.</p>
          ) : !activeWork ? (
            <p>No work signal found for this case.</p>
          ) : null}
        </div>
      ) : null}

      {webReady ? (
        <div className={`dossier-source-block iq-source-web ${includeWeb ? '' : 'is-source-excluded'}`}>
          <span className="iq-source-badge">Web IQ · simulated</span>
          {webNotes.map((note) => (
            <div key={note.id} className="dossier-web-story">
              <small>
                {note.source} · {note.publishedOn}
              </small>
              <h4>{note.headline}</h4>
              <p>{note.summary}</p>
              <div className="dossier-web-relevance">
                <span className="iq-eyebrow">For the service review</span>
                <p>{note.meetingPrompt}</p>
              </div>
            </div>
          ))}
          {!includeWeb ? (
            <p>Web context is not included. No public announcement will be added to the message.</p>
          ) : !webNotes.length ? (
            <p>No public announcement found for this case.</p>
          ) : null}
        </div>
      ) : null}

      {step !== 'facts' ? (
        <div className="dossier-unknowns">
          <span className="iq-eyebrow">Still to confirm</span>
          <ul>
            {action.unknowns.map((unknown) => (
              <li key={unknown}>{unknown}</li>
            ))}
          </ul>
        </div>
      ) : null}

      <div className="dossier-proof-buttons" role="group" aria-label={`${item.customer} sources`}>
        <button className="iq-source-fabric" disabled={!includeFabric} aria-expanded={panel === 'figures'} onClick={() => togglePanel('figures')}>
          Figures
        </button>
        <button className="iq-source-fabric" disabled={!includeFabric} aria-expanded={panel === 'scope'} onClick={() => togglePanel('scope')}>
          Why this cause?
        </button>
        {step !== 'facts' && includeFoundry ? (
          <button className="iq-source-foundry" aria-expanded={panel === 'contract'} onClick={() => togglePanel('contract')}>
            Contract clause
          </button>
        ) : null}
        <button aria-expanded={panel === 'evidence'} onClick={() => togglePanel('evidence')}>
          All evidence
        </button>
      </div>

      {panel ? (
        <section
          className={`dossier-proof ${panel === 'contract' ? 'iq-source-foundry' : panel === 'figures' || panel === 'scope' ? 'iq-source-fabric' : ''}`}
          aria-label={`${item.customer} ${panel} evidence`}
        >
          <div className="dossier-proof-heading">
            <strong>
              {panel === 'scope' ? 'Why this cause?' : panel === 'contract' ? item.contract.reference : panel === 'figures' ? 'Figures' : 'Evidence'}
            </strong>
            <button aria-label="Close evidence" onClick={() => setPanel(null)}>
              ×
            </button>
          </div>
          {panel === 'figures' ? (
            <>
              <dl>
                <dt>Zero-touch, previous week</dt>
                <dd>
                  {fmtPct(facts.previous)} ({facts.previousZeroTouch} of {facts.previousTickets})
                </dd>
                <dt>Zero-touch, {week.label}</dt>
                <dd>
                  {fmtPct(facts.current)} ({facts.zeroTouch} of {fmtInt(facts.tickets)})
                </dd>
                <dt>Weekly target</dt>
                <dd>{fmtPct(facts.target, 0)}</dd>
                <dt>XLA credit, last closed week</dt>
                <dd>{fmtEur(facts.credit)}</dd>
              </dl>
              <p>Same customer, same closed week. The credit is the model's own evaluation.</p>
              <details className="iq-query">
                <summary>DAX query</summary>
                <pre>{dossierDax(item)}</pre>
              </details>
            </>
          ) : null}

          {panel === 'scope' ? (
            <>
              <div className="dossier-scope-chain">
                {item.scope.chain.map((link, i) => (
                  <span key={link} style={{ display: 'contents' }}>
                    {i > 0 ? <span aria-hidden>↓</span> : null}
                    {i === 0 || i === item.scope.chain.length - 1 ? <strong>{link}</strong> : <span>{link}</span>}
                  </span>
                ))}
              </div>
              <p>{item.scope.cause}</p>
              <p>{item.scope.impacted}.</p>
              <p>Relations: {item.scope.relations.join(', ')}.</p>
            </>
          ) : null}

          {panel === 'contract' ? (
            <>
              <p>
                {item.contract.xlaId} clause text, as bound in the ontology (
                <code>Xla.clause_text</code>):
              </p>
              <blockquote className="dossier-article">{item.contract.clause}</blockquote>
              <p className="iq-fingerprint">
                The Foundry IQ contract layer is simulated in this demo: the clause is read from Fabric.
              </p>
            </>
          ) : null}

          {panel === 'evidence' ? (
            <>
              <p>
                Scenario date: {asOf}. Figures from the semantic model, cause from the ontology graph,
                consequence from {item.contract.reference}. Work IQ and Web IQ signals are fictional.
              </p>
              <details className="iq-query">
                <summary>Agent question</summary>
                <p>{dossierPrompt(item, week)}</p>
              </details>
            </>
          ) : null}
        </section>
      ) : null}

      {step === 'action' ? (
        <div className="dossier-draft dossier-send">
          <h4>Send to the right person</h4>
          {initialMessage ? (
            <>
              {recipient ? (
                <div className="dossier-recipient iq-source-work">
                  <span className="dossier-recipient-avatar" aria-hidden>
                    {initials(recipient.name)}
                  </span>
                  <div>
                    <strong>{recipient.name}</strong>
                    <small>{recipient.role}</small>
                    <span className="iq-source-badge">Found by Work IQ</span>
                  </div>
                  <ul aria-label={`Why ${recipient.name}`}>
                    {recipient.reasons.map((reason) => (
                      <li key={reason}>{reason}</li>
                    ))}
                  </ul>
                </div>
              ) : (
                <p className="dossier-recipient is-unknown">
                  Recipient unknown. Include Work IQ to find who owns the next step.
                </p>
              )}
              <div className="dossier-draft-sources" aria-label="Context included in this message">
                <span className="iq-source-badge iq-source-fabric">Fabric IQ · facts</span>
                <span className="iq-source-badge iq-source-foundry">Foundry IQ · clause</span>
                {activeWork ? <span className="iq-source-badge iq-source-work">Work IQ · recipient & context</span> : null}
                {webNotes.length ? <span className="iq-source-badge iq-source-web">Web IQ · announcement</span> : null}
              </div>
              <textarea
                value={message}
                onChange={(e) => setMessage(e.target.value)}
                readOnly={sendState !== 'idle'}
                aria-label={`${item.customer} message`}
                rows={webNotes.length ? 10 : 6}
              />
              <div className="dossier-send-actions">
                <button
                  className="iq-button is-primary"
                  disabled={!recipient || !message.trim() || sendState !== 'idle'}
                  onClick={sendMessage}
                >
                  {sendState === 'sending' ? (
                    <>
                      <span className="iq-spinner" aria-hidden />
                      Sending…
                    </>
                  ) : sendState === 'sent' ? (
                    'Sent'
                  ) : (
                    `Send in ${recipient?.channel ?? 'Teams'}`
                  )}
                </button>
                <button className="iq-button" onClick={() => void copyMessage()}>
                  Copy message
                </button>
              </div>
              {sendState === 'sent' && recipient ? (
                <p role="status" className="dossier-sent">
                  Sent to {recipient.name} in {recipient.channel} (simulated).
                </p>
              ) : null}
              {copyState === 'copied' ? <span role="status">Copied.</span> : null}
              {copyState === 'failed' ? (
                <p role="alert">Clipboard access failed. Select and copy the message above manually.</p>
              ) : null}
            </>
          ) : (
            <p className="iq-footnote">
              A definitive message is withheld until the figures and the contract clause are included and consistent.
            </p>
          )}
        </div>
      ) : null}
    </article>
  );
}
