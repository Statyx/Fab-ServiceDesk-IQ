import { KpiCard } from '@/components/KpiCard';
import { QueryState } from '@/components/QueryState';
import { Section } from '@/components/Section';
import { CUSTOMERS_DAX, PORTFOLIO_DAX, mapCustomers, mapPortfolio } from '@/data/queries';
import { useAssistant } from '@/domain/assistant';
import { fmtDec, fmtInt, fmtPct, fmtPts } from '@/lib/format';
import { useDax } from '@/hooks/useDax';

/**
 * Where the service desk stands, and where to start looking.
 *
 * Two panels, and they answer two different kinds of question — hence the two focus anchors
 * the cover links to. `measures` is the desk in figures; `relationships` is the shape of the
 * estate, which is the only capability in this demo that a table cannot show.
 *
 * The weekly table is sorted by change, worst first, and deliberately not filtered: the two
 * customers that fell below the same 40% target sit side by side, and nothing on this screen
 * says that one of them costs money and the other does not. That is a contract question, and
 * the contract lives on another layer.
 */
export function PortfolioPage() {
  const { askText } = useAssistant();
  const kpis = useDax(PORTFOLIO_DAX, mapPortfolio);
  const customers = useDax(CUSTOMERS_DAX, mapCustomers);
  const data = kpis.data;

  return (
    <>
      <Section
        id="measures"
        title="The service desk over the period"
        provenance="SM_ServiceDesk_Analytics semantic model — Direct Lake"
      >
        <QueryState loading={kpis.loading} error={kpis.error} onRetry={kpis.reload}>
          {data ? (
            <div className="grid grid-cols-2 gap-3 @3xl:grid-cols-3 @6xl:grid-cols-5">
              <KpiCard
                label="Tickets"
                value={fmtInt(data.tickets)}
                measure="Tickets"
                hint={`${fmtInt(data.ticketsWeek)} in the week of ${data.weekStart}`}
              />
              <KpiCard
                label="Zero-touch, last week"
                value={fmtPct(data.zeroTouchWeek)}
                measure="Zero-Touch % (Last Closed Week)"
                hint={`${fmtPts(data.changePts)} vs ${fmtPct(data.zeroTouchPrevious)} the week before`}
                tone={data.changePts < 0 ? 'alert' : 'good'}
              />
              <KpiCard
                label="Escalated to a human"
                value={fmtInt(data.hitl)}
                measure="HITL Escalations"
              />
              <KpiCard
                label="Open tickets"
                value={fmtInt(data.openTickets)}
                measure="Open Tickets"
              />
              <KpiCard
                label="MTTR"
                value={`${fmtDec(data.mttr, 1)} h`}
                measure="MTTR (h)"
              />
              <KpiCard label="CSAT" value={fmtDec(data.csat)} measure="CSAT Avg" hint="out of 5" />
              <KpiCard
                label="Time lost per seat"
                value={`${fmtDec(data.timeLostPerSeat, 0)} min`}
                measure="Time Lost per Seat (min)"
              />
              <KpiCard
                label="Major incidents"
                value={fmtInt(data.majorIncidents)}
                measure="Major Incidents"
                tone={data.majorIncidents > 0 ? 'alert' : 'default'}
              />
            </div>
          ) : null}
        </QueryState>

        <QueryState
          loading={customers.loading}
          error={customers.error}
          empty={!customers.loading && (customers.data ?? []).length === 0}
          onRetry={customers.reload}
        >
          <h3 className="mt-5 mb-2 text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            Zero-touch by customer, last closed week
          </h3>
          <table className="w-full text-sm">
            <thead>
              <tr style={{ color: 'var(--text-muted)' }}>
                <th className="pb-2 text-left text-xs font-medium">Customer</th>
                <th className="pb-2 text-right text-xs font-medium">Previous</th>
                <th className="pb-2 text-right text-xs font-medium">Last week</th>
                <th className="pb-2 text-right text-xs font-medium">Change</th>
                <th className="pb-2 text-right text-xs font-medium">Target</th>
                <th className="pb-2 text-right text-xs font-medium">CSAT</th>
              </tr>
            </thead>
            <tbody>
              {(customers.data ?? []).map((c) => {
                const below = c.target !== null && c.lastWeek < c.target;
                return (
                  <tr key={c.customer} style={{ color: 'var(--text-secondary)' }}>
                    <td className="py-1.5">
                      <button
                        onClick={() =>
                          askText(
                            `Why did the zero-touch resolution rate of ${c.customer} move from ` +
                              `${fmtPct(c.previousWeek)} to ${fmtPct(c.lastWeek)} in the last ` +
                              `closed week? Use [Zero-Touch % (Last Closed Week)] and look at ` +
                              `what changed in its tickets.`,
                          )
                        }
                        className="text-left font-medium hover:underline"
                        style={{ color: 'var(--text-primary)' }}
                      >
                        {c.customer}
                      </button>
                      <span className="ml-2 text-xs" style={{ color: 'var(--text-muted)' }}>
                        {fmtInt(c.tickets)} tickets
                      </span>
                    </td>
                    <td className="py-1.5 text-right tabular-nums">{fmtPct(c.previousWeek)}</td>
                    <td
                      className="py-1.5 text-right font-semibold tabular-nums"
                      style={{ color: below ? 'var(--sev-critical)' : undefined }}
                    >
                      {fmtPct(c.lastWeek)}
                    </td>
                    <td className="py-1.5 text-right tabular-nums">{fmtPts(c.changePts)}</td>
                    <td className="py-1.5 text-right tabular-nums">
                      {c.target === null ? '—' : `≥ ${fmtPct(c.target, 0)}`}
                    </td>
                    <td className="py-1.5 text-right tabular-nums">{fmtDec(c.csat)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
            A dash means the customer has no weekly zero-touch target. The same fall below target
            can carry different consequences: that is written in the contract, not in the figure.
          </p>
        </QueryState>
      </Section>

      <Section
        id="relationships"
        title="How the service desk is connected"
        provenance="ONT_ServiceDesk ontology — 13 entities, 23 relationships"
      >
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          A ticket is reached <strong>through the user who raised it</strong>: Customer → Site →
          User → Ticket. The same graph ties a major incident to the site it hits and the
          application that caused it, and a contract to the XLAs it defines — which is what lets a
          single question go from a degraded Teams call to the clause it breaks.
        </p>

        <ul className="mt-3 grid gap-2 text-sm @3xl:grid-cols-2">
          {[
            'Customer → Site → User → Device',
            'Ticket → User, Device, Application',
            'Ticket → Major incident',
            'Major incident → Site, Application',
            'Customer → Contract → XLA',
            'Ticket → Agent → MCP tool',
          ].map((path) => (
            <li
              key={path}
              className="rounded-lg px-3 py-2"
              style={{ background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}
            >
              {path}
            </li>
          ))}
        </ul>

        <p className="mt-3 text-xs" style={{ color: 'var(--text-muted)' }}>
          Live telemetry is attached to the Device, Site and Agent entities, which puts what was
          measured, what was promised and what is happening now in the same layer.
        </p>
      </Section>
    </>
  );
}
