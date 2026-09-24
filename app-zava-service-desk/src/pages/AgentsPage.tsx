import { KpiCard } from '@/components/KpiCard';
import { QueryState } from '@/components/QueryState';
import { Section } from '@/components/Section';
import { AGENTS_DAX, AUTOMATION_DAX, mapAgents, mapAutomation } from '@/data/queries';
import { useAssistant } from '@/domain/assistant';
import { OPENERS } from '@/domain/openers';
import { fmtDec, fmtInt, fmtPct } from '@/lib/format';
import { useDax } from '@/hooks/useDax';

/**
 * Who resolves the tickets: the AI agent, the analysts, and the hand-over between them.
 *
 * Two tables because they answer two questions. The first is by agent — how much the resolver
 * agent closes on its own, and how much each analyst picks up. The second is by customer, which
 * is the grain the contracts are written at: an automation rate means nothing to a customer
 * until it is their automation rate.
 *
 * The agent's own tool calls and throttling are live telemetry, not closed figures. They are
 * asked, never tabulated here, because a snapshot of a stream presented as a table reads as
 * a closed number.
 */
export function AgentsPage() {
  const { ask, askText } = useAssistant();
  const agents = useDax(AGENTS_DAX, mapAgents);
  const automation = useDax(AUTOMATION_DAX, mapAutomation);

  const rows = agents.data ?? [];
  const ai = rows.filter((r) => r.type === 'AI');
  const humans = rows.filter((r) => r.type !== 'AI');
  const aiTickets = ai.reduce((s, r) => s + r.tickets, 0);
  const humanTickets = humans.reduce((s, r) => s + r.tickets, 0);
  const hitl = humans.reduce((s, r) => s + r.hitl, 0);

  return (
    <>
      <Section
        id="agents"
        title="AI agent and analysts"
        provenance="Semantic model — Tickets, Zero-Touch Tickets, HITL Escalations by dim_agent"
        action={
          <button
            onClick={() => {
              const o = OPENERS.find((x) => x.id === 'agentops-tool-failures');
              if (o) ask(o);
            }}
            className="rounded-md px-2.5 py-1 text-xs font-medium"
            style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
          >
            Ask the agent traces
          </button>
        }
      >
        <QueryState
          loading={agents.loading}
          error={agents.error}
          empty={!agents.loading && rows.length === 0}
          onRetry={agents.reload}
        >
          <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-3">
            <KpiCard
              label="Resolved by the AI agent"
              value={fmtInt(aiTickets)}
              measure="Zero-Touch Tickets"
              hint={`${ai.length} ${ai.length === 1 ? 'agent' : 'agents'}`}
            />
            <KpiCard
              label="Handled by analysts"
              value={fmtInt(humanTickets)}
              measure="Tickets"
              hint={`${humans.length} analysts`}
            />
            <KpiCard
              label="Escalated to a human"
              value={fmtInt(hitl)}
              measure="HITL Escalations"
            />
          </div>

          <table className="mt-4 w-full text-sm">
            <thead>
              <tr style={{ color: 'var(--text-muted)' }}>
                <th className="pb-2 text-left text-xs font-medium">Agent</th>
                <th className="pb-2 text-left text-xs font-medium">Role</th>
                <th className="pb-2 text-right text-xs font-medium">Tickets</th>
                <th className="pb-2 text-right text-xs font-medium">Zero-touch</th>
                <th className="pb-2 text-right text-xs font-medium">Escalations</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.agent} style={{ color: 'var(--text-secondary)' }}>
                  <td className="py-1.5">
                    <span className="font-medium" style={{ color: 'var(--text-primary)' }}>
                      {r.agent}
                    </span>
                    <span
                      className="ml-2 rounded px-1.5 py-0.5 text-[0.625rem] font-semibold"
                      style={{
                        color: r.type === 'AI' ? 'var(--accent)' : 'var(--text-muted)',
                      }}
                    >
                      {r.type}
                    </span>
                  </td>
                  <td className="py-1.5 text-xs">{r.role}</td>
                  <td className="py-1.5 text-right tabular-nums">{fmtInt(r.tickets)}</td>
                  <td className="py-1.5 text-right tabular-nums">{fmtInt(r.zeroTouch)}</td>
                  <td className="py-1.5 text-right tabular-nums">{fmtInt(r.hitl)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </QueryState>

        <QueryState
          loading={automation.loading}
          error={automation.error}
          empty={!automation.loading && (automation.data ?? []).length === 0}
          onRetry={automation.reload}
        >
          <h3 className="mt-5 mb-2 text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Automation by customer, over the period
          </h3>
          <div className="space-y-1">
            {(automation.data ?? []).map((c) => (
              <button
                key={c.customer}
                onClick={() =>
                  askText(
                    `Over the period, ${c.customer} has a [Zero-Touch %] of ` +
                      `${fmtPct(c.zeroTouch)} on ${fmtInt(c.tickets)} tickets, with ` +
                      `${fmtInt(c.hitl)} [HITL Escalations]. Which categories of ticket does the ` +
                      `resolver agent hand over to an analyst most often for this customer, and why?`,
                  )
                }
                className="grid w-full grid-cols-[1fr_auto] items-center gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-[var(--bg-secondary)] focus-visible:outline-2 focus-visible:outline-offset-2"
              >
                <div className="min-w-0">
                  <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                    {c.customer}
                  </span>
                  <div
                    className="relative mt-1.5 h-2 rounded"
                    style={{ background: 'var(--bg-secondary)' }}
                  >
                    <span
                      className="absolute inset-y-0 block rounded"
                      style={{ left: 0, width: `${c.zeroTouch * 100}%`, background: 'var(--accent)' }}
                    />
                  </div>
                  <span className="mt-1 block text-xs" style={{ color: 'var(--text-muted)' }}>
                    {fmtInt(c.tickets)} tickets · {fmtInt(c.hitl)} escalations · MTTR{' '}
                    {fmtDec(c.mttr, 1)} h
                  </span>
                </div>
                <span className="text-sm font-semibold tabular-nums" style={{ color: 'var(--text-secondary)' }}>
                  {fmtPct(c.zeroTouch)}
                </span>
              </button>
            ))}
          </div>
          <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            These rates cover the whole period. The XLAs are judged week by week, which is why a
            customer can look healthy here and still be in breach on the XLA screen.
          </p>
        </QueryState>
      </Section>
    </>
  );
}
