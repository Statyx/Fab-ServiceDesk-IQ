import { Section } from '@/components/Section';
import { AGREEMENTS, REGIME_STYLE } from '@/data/contracts';
import { useAssistant } from '@/domain/assistant';

/**
 * The contracts, and deliberately not a single figure.
 *
 * This is the one section that produces no measure, and that emptiness is the argument: the
 * consequence of a breach is not in the fact tables. Adding a KPI strip here to make the page
 * look balanced would undo the whole demonstration.
 *
 * The clauses below are captions, not answers. Clicking one asks the data agent to read the
 * clause through the ontology, and what comes back carries its own source. The app must never
 * let a caption pass for evidence.
 */
export function ContractsPage() {
  const { askText } = useAssistant();

  return (
    <>
      <Section
        id="regimes"
        title="Six contracts, three consequences"
        provenance="Signed contracts CTR-*-2026 — clause text bound in ONT_ServiceDesk as Xla.clause_text"
      >
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          The same fall below the same target can produce three different outcomes, depending on
          the contract the customer signed: a service credit, a remediation plan with no credit,
          or nothing beyond the report. The contract is what decides.
        </p>

        <div className="mt-4 space-y-3">
          {AGREEMENTS.map((a) => (
            <div key={a.id} className="rounded-lg p-3" style={{ background: 'var(--bg-secondary)' }}>
              <div className="flex flex-wrap items-baseline gap-2">
                <span className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
                  {a.customer}
                </span>
                <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                  {a.id} · {a.name}
                  {a.capPct > 0 ? ` · credits capped at ${a.capPct}% of the monthly fee` : ''}
                </span>
              </div>

              <div className="mt-2 space-y-1">
                {a.xlas.map((x) => {
                  const style = REGIME_STYLE[x.regime];
                  return (
                    <button
                      key={x.id}
                      onClick={() =>
                        askText(
                          `In the ${a.customer} contract, what exactly does ${x.id} ` +
                            `(${x.metric}) provide for? Read the clause from the ontology, quote ` +
                            `it, and say in one sentence what Zava owes if the target is missed. ` +
                            `Use no measured figures: this question is about the text alone.`,
                        )
                      }
                      className="block w-full rounded-md px-3 py-2 text-left transition hover:bg-[var(--bg-primary)] focus-visible:outline-2 focus-visible:outline-offset-2"
                      style={{ borderLeft: `3px solid ${style.tone}` }}
                    >
                      <div className="flex flex-wrap items-baseline gap-2">
                        <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                          {x.metric} {x.target}
                        </span>
                        <span
                          className="rounded px-1.5 py-0.5 text-[0.625rem] font-semibold"
                          style={{ color: style.tone }}
                        >
                          {style.label}
                        </span>
                        <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                          {x.id} · {x.window}
                        </span>
                      </div>
                      <p className="mt-1 text-xs leading-snug" style={{ color: 'var(--text-secondary)' }}>
                        {x.clause}
                      </p>
                    </button>
                  );
                })}
              </div>
            </div>
          ))}
        </div>
      </Section>

      <Section id="boundary" title="Where a consequence is decided">
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          A zero-touch rate is a fact. Whether a week below target costs Zava a service credit,
          a written remediation plan, or nothing at all is decided by the contract — and the
          terms differ by customer. That is why the figure alone never settles the question.
        </p>
        <p className="mt-2 text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          It also has to hold up in a service review: the credit on the invoice must be traceable
          to the week that tripped it and to the clause that prices it. The semantic model
          computes the first, the ontology carries the second, and the answer cites both.
        </p>
      </Section>
    </>
  );
}
