import { useEffect, useRef, useState } from 'react';

import { DossierCard } from '@/components/DossierCard';
import { IqContributionControls, type IqContributions } from '@/components/IqContributionControls';
import { DOSSIER_STEPS, dossierStepAtLeast, relevantWorkCase, type DossierStep } from '@/domain/dossier';
import { IQ_NAV } from '@/domain/nav';
import { DOSSIER_REFERENCE, DOSSIER_WORK_CONTEXT } from '@/services/dossier';
import { STAGE_MS } from '@/services/stage';
import './IqInPracticePage.css';

const STAGE_MESSAGES: Record<DossierStep, string> = {
  facts: '',
  contract: 'Foundry IQ is reading the two XLA clauses…',
  work: 'Work IQ is searching mail, Teams chats, meetings and files…',
  web: 'Web IQ is checking public customer announcements…',
  action: 'Work IQ is finding who needs to act on each case…',
};

export function IqInPracticePage() {
  const [step, setStep] = useState<DossierStep>('facts');
  const [includeWork, setIncludeWork] = useState(true);
  const [includeFabric, setIncludeFabric] = useState(true);
  const [includeFoundry, setIncludeFoundry] = useState(true);
  const [includeWeb, setIncludeWeb] = useState(true);
  const [webReviewed, setWebReviewed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState('');
  const [revision, setRevision] = useState(0);
  const generation = useRef(0);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  function clearPending() {
    generation.current += 1;
    if (timer.current) clearTimeout(timer.current);
    timer.current = null;
  }
  useEffect(() => () => {
    generation.current += 1;
    if (timer.current) clearTimeout(timer.current);
  }, []);

  function reset() {
    clearPending();
    setStep('facts');
    setIncludeWork(true);
    setIncludeFabric(true);
    setIncludeFoundry(true);
    setIncludeWeb(true);
    setWebReviewed(false);
    setBusy(false);
    setProgress('');
    setRevision((v) => v + 1);
  }

  function reveal(target: DossierStep) {
    setStep(target);
    if (target === 'web') setWebReviewed(true);
    setRevision((v) => v + 1);
  }

  /** A short pause marks each layer being added; going back is immediate. */
  function advance(target: DossierStep) {
    if (busy || (target === 'action' && !webReviewed)) return;
    if (target === 'facts') { reset(); return; }
    if (STAGE_MS <= 0 || dossierStepAtLeast(step, target)) { reveal(target); return; }
    clearPending();
    const current = generation.current;
    setBusy(true);
    setProgress(STAGE_MESSAGES[target]);
    timer.current = setTimeout(() => {
      if (generation.current !== current) return;
      timer.current = null;
      setBusy(false);
      reveal(target);
    }, STAGE_MS);
  }

  function changeContribution(key: keyof IqContributions, checked: boolean) {
    if (key === 'fabric') setIncludeFabric(checked);
    if (key === 'foundry') setIncludeFoundry(checked);
    if (key === 'work') setIncludeWork(checked);
    if (key === 'web') setIncludeWeb(checked);
    setRevision((v) => v + 1);
  }

  const next = DOSSIER_STEPS[DOSSIER_STEPS.findIndex((s) => s.id === step) + 1]?.id;
  const nextLabel = step === 'facts' ? 'Read the contracts' : step === 'contract' ? 'Add Work IQ'
    : step === 'work' ? 'Add Web IQ' : 'Find who to tell';

  return (
    <div className="iq-page dossier-page">
      <header className="iq-intro">
        <div>
          <span className="cover-eyebrow glass">{IQ_NAV.label}</span>
          <h1>Which XLA breaches need action?</h1>
          <p>Two customers missed the same 40% zero-touch target in the same week. Start with the figures, read the contract, then see what is already underway.</p>
        </div>
      </header>

      <div className="glass dossier-toolbar">
        <div><strong>Week 38 close scenario</strong><span>{new Date(`${DOSSIER_REFERENCE.asOf}T00:00:00Z`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' })}</span></div>
        <button className="iq-button" onClick={() => reset()}>Reset</button>
      </div>

      <nav className="dossier-steps" aria-label="Dossier context">
        {DOSSIER_STEPS.map((s, index) => (
          <button key={s.id} aria-current={step === s.id ? 'step' : undefined}
            disabled={busy || (s.id === 'action' && !webReviewed)}
            title={s.id === 'action' && !webReviewed ? 'Review the Web IQ step before sending.' : undefined}
            onClick={() => advance(s.id)}>
            <span>{index + 1}</span>{s.label}
          </button>
        ))}
      </nav>

      <div className="dossier-stage-copy" aria-live="polite">
        {!includeFabric ? <><strong>The measured gap is not included.</strong><span>Other context cannot establish the measured rate or the ontology scope.</span></>
          : step !== 'facts' && !includeFoundry ? <><strong>The contractual treatment is not established.</strong><span>Figures and work context do not replace the applicable XLA clause.</span></>
          : step === 'facts' ? <><strong>Two breaches. Consequence still unknown.</strong><span>Fabrikam fell to 34%, Litware to 38%, both under a 40% target. The figures do not say what Zava owes.</span></>
          : step === 'contract' ? <><strong>Same target. Different obligations.</strong><span>One contract owes a 9,250 EUR service credit, the other a written remediation plan and no credit.</span></>
          : step === 'work' ? <><strong>Work IQ shows what is already underway, and who owns it.</strong><span>Mail, Teams chats, meetings and files change who acts next, not what the contract says.</span></>
          : step === 'web' ? <><strong>Public news adds context to the service review.</strong><span>Include it in the message or leave it out; it does not change what the contract says.</span></>
          : <><strong>The right person, with the full context.</strong><span>Work IQ identifies who has to act, and the message carries every source.</span></>}
      </div>

      <IqContributionControls
        value={{ fabric: includeFabric, foundry: includeFoundry, work: includeWork, web: includeWeb }}
        onChange={changeContribution} busy={busy}
        contractReady={dossierStepAtLeast(step, 'contract')}
        workReady={dossierStepAtLeast(step, 'work')} webReady={dossierStepAtLeast(step, 'web')}
      />

      {busy ? <p role="status" className="dossier-progress"><span className="iq-spinner" aria-hidden />{progress}</p> : null}

      <div className={`dossier-cards${busy ? ' is-loading' : ''}`} aria-busy={busy}>
        {DOSSIER_REFERENCE.cases.map((item) => (
          <DossierCard
            key={`${item.id}:${revision}`} item={item} step={step}
            includeFabric={includeFabric} includeFoundry={includeFoundry} includeWeb={includeWeb}
            includeWork={includeWork}
            asOf={DOSSIER_REFERENCE.asOf} week={DOSSIER_REFERENCE.week}
            work={relevantWorkCase(item, DOSSIER_WORK_CONTEXT, DOSSIER_REFERENCE.scenarioId, DOSSIER_REFERENCE.asOf, DOSSIER_REFERENCE.week)}
          />
        ))}
      </div>

      {next ? (
        <div className="dossier-next"><button className="iq-button is-primary" disabled={busy} onClick={() => advance(next)}>
          {busy ? <><span className="iq-spinner" aria-hidden />Working…</> : <>{nextLabel}<span aria-hidden> →</span></>}
        </button></div>
      ) : null}

      <footer className="glass dossier-explanation">
        <details>
          <summary>How IQ contributes</summary>
          <div className="dossier-contributions">
            <div><strong>Business data</strong><p>Tickets, telemetry, contracts and XLA evaluations landed in OneLake and the Eventhouse.</p></div>
            <div className="iq-source-fabric"><strong>Fabric IQ</strong><p>The semantic model computes the zero-touch rates and the XLA credit. The ontology and its graph link the customer to its sites, incidents, applications and XLA clauses.</p></div>
            <div className="iq-source-foundry"><strong>Foundry IQ</strong><p>The Zava-SD-Contracts agent retrieves the applicable clause from the Service agreements knowledge base, cites the signed agreement and computes nothing.</p></div>
            <div className="iq-source-work"><strong>Work IQ</strong><p>Mail, Teams chats, meetings and files show what is already underway and who owns each case. That decides who receives the message.</p></div>
            <div className="iq-source-web"><strong>Web IQ</strong><p>Public customer announcements add context for the service review, without changing contractual conclusions.</p><a href="https://www.microsoft.com/en-us/WebIQ" target="_blank" rel="noreferrer">Web IQ overview</a></div>
          </div>
          <p className="iq-footnote">The extra context qualifies the next step. The Service Delivery Manager retains the decision.</p>
        </details>
      </footer>
    </div>
  );
}
