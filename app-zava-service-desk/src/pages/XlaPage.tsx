import { KpiCard } from '@/components/KpiCard';
import { QueryState } from '@/components/QueryState';
import { Section } from '@/components/Section';
import { REGIME_STYLE, zeroTouchTerm } from '@/data/contracts';
import {
  XLA_LEDGER_DAX,
  XLA_TOTALS_DAX,
  XLA_WEEK_DAX,
  mapXlaLedger,
  mapXlaTotals,
  mapXlaWeek,
} from '@/data/queries';
import { useAssistant } from '@/domain/assistant';
import { OPENERS } from '@/domain/openers';
import { fmtEur, fmtInt, fmtPct } from '@/lib/format';
import { useDax } from '@/hooks/useDax';

/**
 * XLA breaches, and the one panel in the app that exists to prevent a misreading.
 *
 * Two customers fell below the same 40% target in the same week: Fabrikam to 34%, Litware to 38%.
 * One of them owes nothing and the other costs Zava 9,250 EUR. The table shows both side by
 * side, each with the consequence its contract attaches, because a screen that lists only the
 * credited breach would teach the room that a breach *is* a credit — and a screen that lists
 * only the count would hide the one that costs money.
 *
 * No credit is computed here. `[XLA Credit (Last Closed Week)]` is the model's own evaluation,
 * monthly cap included; this page only prints it next to the regime that explains it.
 */
export function XlaPage() {
  const { ask, askText } = useAssistant();
  const totals = useDax(XLA_TOTALS_DAX, mapXlaTotals);
  const week = useDax(XLA_WEEK_DAX, mapXlaWeek);
  const ledger = useDax(XLA_LEDGER_DAX, mapXlaLedger);

  return (
    <>
      <Section
        id="breaches"
        title="Breaches of the last closed week"
        provenance="Semantic model — fact_xla_evaluation, evaluated per ISO week and month"
        action={
          <button
            onClick={() => {
              const o = OPENERS.find((x) => x.id === 'xla-litware-contrast');
              if (o) ask(o);
            }}
            className="rounded-md px-2.5 py-1 text-xs font-medium"
            style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
          >
            Ask why only one costs money
          </button>
        }
      >
        <QueryState loading={totals.loading} error={totals.error} onRetry={totals.reload}>
          {totals.data ? (
            <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-4">
              <KpiCard
                label="Breaches, last week"
                value={fmtInt(totals.data.breachesWeek)}
                measure="XLA Breaches (Last Closed Week)"
                hint={`week of ${totals.data.weekStart}`}
                tone={totals.data.breachesWeek > 0 ? 'alert' : 'default'}
              />
              <KpiCard
                label="Credit owed, last week"
                value={fmtEur(totals.data.creditWeek)}
                measure="XLA Credit (Last Closed Week)"
                tone={totals.data.creditWeek > 0 ? 'alert' : 'default'}
              />
              <KpiCard
                label="Evaluations, period"
                value={fmtInt(totals.data.evaluations)}
                measure="XLA Evaluations"
                hint={`${fmtInt(totals.data.breaches)} ${totals.data.breaches === 1 ? 'breach' : 'breaches'}`}
              />
              <KpiCard
                label="Credit, period"
                value={fmtEur(totals.data.credit)}
                measure="XLA Credit (EUR)"
              />
            </div>
          ) : null}
        </QueryState>

        <QueryState
          loading={week.loading}
          error={week.error}
          empty={!week.loading && (week.data ?? []).length === 0}
          onRetry={week.reload}
        >
          <div className="mt-4 grid gap-3 @3xl:grid-cols-2">
            {(week.data ?? []).map((w) => {
              const zt = zeroTouchTerm(w.customer);
              // Only a weekly zero-touch XLA is judged on this week; a monthly one waits for the month.
              const term = zt?.window === 'weekly' ? zt : undefined;
              const style = term ? REGIME_STYLE[term.regime] : undefined;
              return (
                <button
                  key={w.customer}
                  onClick={() =>
                    askText(
                      `In the last closed week, ${w.customer} had a [Zero-Touch % (Last Closed ` +
                        `Week)] of ${fmtPct(w.zeroTouch)} against a target of ` +
                        `${w.target === null ? 'none' : fmtPct(w.target, 0)}. What does its ` +
                        `contract provide for in that case, and what does Zava owe? Quote the ` +
                        `clause and give [XLA Credit (Last Closed Week)].`,
                    )
                  }
                  className="rounded-lg p-4 text-left transition hover:brightness-105 focus-visible:outline-2 focus-visible:outline-offset-2"
                  style={{
                    background: 'var(--bg-secondary)',
                    borderLeft: `3px solid ${style && w.breaches > 0 ? style.tone : 'var(--border-strong)'}`,
                  }}
                >
                  <p
                    className="text-[0.625rem] font-semibold uppercase tracking-wide"
                    style={{ color: 'var(--text-muted)' }}
                  >
                    {w.customer}
                  </p>
                  <p
                    className="mt-1 text-2xl font-bold tabular-nums"
                    style={{ color: 'var(--text-primary)' }}
                  >
                    {fmtPct(w.zeroTouch)}
                    <span className="ml-2 text-xs font-normal" style={{ color: 'var(--text-muted)' }}>
                      target {w.target === null ? '—' : `≥ ${fmtPct(w.target, 0)}`}
                    </span>
                  </p>
                  <p className="mt-1 text-sm" style={{ color: 'var(--text-secondary)' }}>
                    {fmtInt(w.breaches)} {w.breaches === 1 ? 'breach' : 'breaches'} · credit {fmtEur(w.credit)}
                  </p>
                  {style && w.breaches > 0 ? (
                    <p className="mt-1 text-xs" style={{ color: style.tone }}>
                      {style.label} — {style.note}
                    </p>
                  ) : style ? (
                    <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                      Within target. If missed: {style.label.toLowerCase()}.
                    </p>
                  ) : zt ? (
                    <p className="mt-1 text-xs" style={{ color: 'var(--text-muted)' }}>
                      Zero-touch is judged monthly under {zt.id} ({zt.target}), not weekly.
                    </p>
                  ) : null}
                </button>
              );
            })}
          </div>

          <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            Same metric, same target, same fall. The difference is not in the data: it is in the
            clause each customer signed, which the ontology carries as text next to the XLA.
          </p>
        </QueryState>
      </Section>

      <Section
        id="ledger"
        title="Every XLA, over the period"
        provenance="Semantic model — XLA Evaluations, XLA Breaches, XLA Credit (EUR) by dim_xla"
      >
        <QueryState
          loading={ledger.loading}
          error={ledger.error}
          empty={!ledger.loading && (ledger.data ?? []).length === 0}
          onRetry={ledger.reload}
        >
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: 'var(--text-muted)' }}>
                <th className="pb-2 text-left text-xs font-medium">XLA</th>
                <th className="pb-2 text-left text-xs font-medium">Metric</th>
                <th className="pb-2 text-right text-xs font-medium">Penalty</th>
                <th className="pb-2 text-right text-xs font-medium">Evaluations</th>
                <th className="pb-2 text-right text-xs font-medium">Breaches</th>
                <th className="pb-2 text-right text-xs font-medium">Credit</th>
              </tr>
            </thead>
            <tbody>
              {(ledger.data ?? []).map((l) => (
                <tr key={l.xlaId} style={{ color: 'var(--text-secondary)' }}>
                  <td className="py-1.5">
                    <span className="font-medium" style={{ color: 'var(--text-primary)' }}>
                      {l.xlaId}
                    </span>
                    <span className="ml-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                      {l.customer}
                    </span>
                  </td>
                  <td className="py-1.5 text-xs">
                    {l.metric} · {l.window}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">
                    {l.penaltyPct > 0 ? `${fmtInt(l.penaltyPct)}%` : '—'}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{fmtInt(l.evaluations)}</td>
                  <td
                    className="py-1.5 text-right tabular-nums"
                    style={{ color: l.breaches > 0 ? 'var(--sev-critical)' : undefined }}
                  >
                    {fmtInt(l.breaches)}
                  </td>
                  <td className="py-1.5 text-right tabular-nums">{fmtEur(l.credit)}</td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            A dash in the penalty column means the XLA carries no credit: a breach there is a
            remediation obligation or a reported figure, never an amount owed.
          </p>
        </QueryState>
      </Section>
    </>
  );
}
