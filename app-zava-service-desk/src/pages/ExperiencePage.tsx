import { QueryState } from '@/components/QueryState';
import { Section } from '@/components/Section';
import { INCIDENTS_DAX, SITES_DAX, mapIncidents, mapSites } from '@/data/queries';
import type { SiteExperience } from '@/data/queries';
import { useAssistant } from '@/domain/assistant';
import { OPENERS } from '@/domain/openers';
import { fmtDec, fmtInt } from '@/lib/format';
import { useDax } from '@/hooks/useDax';

/**
 * The score below which a site is worth a question.
 *
 * Drawn as a line on the chart rather than used to filter the query: the reader sees where the
 * threshold sits and judges the gap themselves. A table pre-filtered to "the bad ones" asks the
 * room to trust the filter. It is an app-side reading aid, not a contractual threshold — no XLA
 * in this demo is written on the experience score.
 */
const WATCH = 80;

/** The chart's floor and ceiling, so every row is drawn on the same scale. */
function range(rows: SiteExperience[]): [number, number] {
  const lo = Math.min(WATCH - 1, ...rows.map((r) => r.score));
  const hi = Math.max(WATCH + 1, ...rows.map((r) => r.score));
  return [Math.floor(lo) - 1, Math.ceil(hi)];
}

/**
 * What the users actually live through, site by site.
 *
 * The chart is the way into the question: every row is a button, and clicking it asks a
 * `mixed` question about that site rather than opening a drill-down. A row that only sorts is a
 * row that teaches the room nothing.
 *
 * The site that matters is never named in this file. It has to emerge from the same ranking as
 * every other site — naming it here would turn a finding into a lookup.
 */
export function ExperiencePage() {
  const { ask, askText } = useAssistant();
  const sites = useDax(SITES_DAX, mapSites);
  const incidents = useDax(INCIDENTS_DAX, mapIncidents);

  const rows = sites.data ?? [];
  const [lo, hi] = range(rows);
  const watched = rows.filter((r) => r.score < WATCH);

  return (
    <>
      <Section
        id="sites"
        title="Digital experience by site"
        provenance="Semantic model — Experience Score, VPN Latency (ms), Teams MOS, App Crashes"
        action={
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            watch line {WATCH}
          </span>
        }
      >
        <QueryState
          loading={sites.loading}
          error={sites.error}
          empty={!sites.loading && rows.length === 0}
          onRetry={sites.reload}
        >
          <p className="mb-3 text-sm" style={{ color: 'var(--text-secondary)' }}>
            {watched.length} {watched.length === 1 ? 'site' : 'sites'} under the watch line. Click a row to ask what is degrading the
            experience there, and which users it reaches.
          </p>

          <div className="space-y-1">
            {rows.slice(0, 12).map((r) => {
              const width = ((r.score - lo) / (hi - lo)) * 100;
              const flag = r.score < WATCH;
              return (
                <button
                  key={r.siteId}
                  onClick={() =>
                    askText(
                      `The site ${r.site} (${r.siteId}) of ${r.customer} has an [Experience Score] ` +
                        `of ${fmtDec(r.score, 1)}, with a [VPN Latency (ms)] of ` +
                        `${fmtDec(r.vpnMs, 1)} ms and a [Teams MOS] of ${fmtDec(r.mos, 2)}. What ` +
                        `is degrading the experience at this site, is a major incident linked ` +
                        `to it, and how many users and VIPs does it reach?`,
                    )
                  }
                  className="grid w-full grid-cols-[1fr_auto] items-center gap-3 rounded-lg px-3 py-2 text-left transition hover:bg-[var(--bg-secondary)] focus-visible:outline-2 focus-visible:outline-offset-2"
                >
                  <div className="min-w-0">
                    <div className="flex items-baseline gap-2">
                      <span
                        className="truncate text-sm font-medium"
                        style={{ color: 'var(--text-primary)' }}
                      >
                        {r.site}
                      </span>
                      <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
                        {r.siteId}
                      </span>
                    </div>

                    <div
                      className="relative mt-1.5 h-2 rounded"
                      style={{ background: 'var(--bg-secondary)' }}
                    >
                      <span
                        className="absolute inset-y-0 block rounded"
                        style={{
                          left: 0,
                          width: `${width}%`,
                          background: flag ? 'var(--sev-critical)' : 'var(--sev-low)',
                        }}
                      />
                      <span
                        className="absolute inset-y-0 w-px"
                        style={{
                          left: `${((WATCH - lo) / (hi - lo)) * 100}%`,
                          background: 'var(--border-strong)',
                        }}
                      />
                    </div>

                    <span className="mt-1 block text-xs" style={{ color: 'var(--text-muted)' }}>
                      VPN {fmtDec(r.vpnMs, 1)} ms · Teams MOS {fmtDec(r.mos, 2)} ·{' '}
                      {fmtInt(r.crashes)} app crashes
                    </span>
                  </div>

                  <span
                    className="text-sm font-semibold tabular-nums"
                    style={{ color: flag ? 'var(--sev-critical)' : 'var(--text-secondary)' }}
                    title="Experience Score measure — semantic model"
                  >
                    {fmtDec(r.score, 1)}
                  </span>
                </button>
              );
            })}
          </div>
        </QueryState>

        <QueryState
          loading={incidents.loading}
          error={incidents.error}
          onRetry={incidents.reload}
        >
          <div className="mt-4 grid gap-2 @3xl:grid-cols-2">
            {(incidents.data ?? []).map((i) => (
              <div
                key={i.id}
                className="rounded-lg p-3"
                style={{ background: 'var(--bg-secondary)', borderLeft: '3px solid var(--sev-critical)' }}
              >
                <p className="text-xs font-semibold" style={{ color: 'var(--sev-critical)' }}>
                  {i.id} · {i.severity} · {i.status}
                </p>
                <p className="mt-1 text-sm" style={{ color: 'var(--text-primary)' }}>
                  {i.title}
                </p>
                <p className="mt-1 text-xs" style={{ color: 'var(--text-secondary)' }}>
                  Root cause: {i.rootCause}
                </p>
                <p className="mt-1 text-[0.6875rem]" style={{ color: 'var(--text-muted)' }}>
                  {i.customer} · {fmtInt(i.users)} users impacted, {fmtInt(i.vips)} VIP
                </p>
              </div>
            ))}
          </div>
        </QueryState>
      </Section>

      <Section
        id="live"
        title="What is happening now"
        provenance="EH_ServiceDesk Eventhouse — device telemetry, agent traces, surveys"
        action={
          <button
            onClick={() => {
              const o = OPENERS.find((x) => x.id === 'live-vpn');
              if (o) ask(o);
            }}
            className="rounded-md px-2.5 py-1 text-xs font-medium"
            style={{ background: 'var(--accent-soft)', color: 'var(--accent)' }}
          >
            Ask the live stream
          </button>
        }
      >
        <p className="text-sm leading-relaxed" style={{ color: 'var(--text-secondary)' }}>
          The figures above are closed days, read from the Lakehouse. The Eventhouse carries the
          same devices and sites as they report, minute by minute: VPN round-trips, Teams call
          quality, agent tool calls and survey answers.
        </p>
        <ul className="mt-3 grid gap-2 text-sm @3xl:grid-cols-3">
          {[
            ['Device telemetry', 'VPN latency, Teams MOS, crashes'],
            ['Agent traces', 'tool calls, retries, throttling'],
            ['Surveys', 'CSAT answers as they arrive'],
          ].map(([name, what]) => (
            <li
              key={name}
              className="rounded-lg px-3 py-2"
              style={{ background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}
            >
              <span className="font-medium" style={{ color: 'var(--text-primary)' }}>
                {name}
              </span>
              <span className="block text-xs">{what}</span>
            </li>
          ))}
        </ul>
        <p className="mt-3 text-xs leading-relaxed" style={{ color: 'var(--text-muted)' }}>
          A live reading is an observation, not a closed figure: it never feeds a service credit.
          Credits are evaluated on closed weeks and months only, in the semantic model.
        </p>
      </Section>
    </>
  );
}
