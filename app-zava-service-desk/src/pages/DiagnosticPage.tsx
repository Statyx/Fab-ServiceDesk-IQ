import { useState } from 'react';

import { liveAvailable } from '@/data/mode';
import { statusChip } from '@/domain/severity';
import { isFramed } from '@/services/authStartup';
import {
  activeAccount,
  decodeJwt,
  ensureMsalReady,
  FABRIC_SCOPES,
  getToken,
  msalConfigured,
  POWERBI_SCOPES,
} from '@/services/msal';
import { executeDax, semanticModelId } from '@/services/powerbi';

/**
 * One screen that checks each link in the chain and names the one that broke.
 *
 * Deliberately mounted **outside the auth guard**: the single most likely thing to be broken
 * is sign-in itself, and a diagnostic that requires sign-in to say "sign-in is broken" is
 * worthless. It is also absent from the nav manifest — reachable by URL only.
 *
 * The last probe evaluates a real measure rather than pinging an endpoint. Reaching the
 * service proves nothing about this app: the failure that matters is a model that answers but
 * does not carry `Tickets`, and only evaluating it finds that.
 */
type State = 'pending' | 'ok' | 'warn' | 'fail' | 'skip';

interface Check {
  id: string;
  label: string;
  state: State;
  detail: string;
}

const STATE_STYLE: Record<State, { chip: string; text: string }> = {
  pending: { chip: statusChip('neutral'), text: 'Running' },
  ok: { chip: statusChip('ok'), text: 'OK' },
  warn: { chip: statusChip('warn'), text: 'Degraded' },
  fail: { chip: statusChip('fail'), text: 'Failed' },
  skip: { chip: statusChip('neutral'), text: 'Skipped' },
};

const ENV_KEYS = [
  'VITE_ENTRA_CLIENT_ID',
  'VITE_ENTRA_TENANT_ID',
  'VITE_SEMANTIC_MODEL_ID',
  'VITE_ZAVA_WORKSPACE_ID',
  'VITE_ZAVA_DATA_AGENT_ID',
] as const;

/** Audience and granted scopes — the difference between "a token came back" and "the right token came back". */
function describeToken(token: string): string {
  const claims = decodeJwt(token);
  if (!claims) return 'token could not be decoded';
  const aud = String(claims.aud ?? '?');
  const scp = String(claims.scp ?? claims.roles ?? '-');
  const exp = typeof claims.exp === 'number' ? new Date(claims.exp * 1000) : null;
  const expires = exp ? ` — expires at ${exp.toLocaleTimeString('en-GB')}` : '';
  return `aud ${aud} — scp ${scp}${expires}`;
}

export function DiagnosticPage() {
  const [checks, setChecks] = useState<Check[]>([]);
  const [running, setRunning] = useState(false);

  const run = async () => {
    setRunning(true);
    const out: Check[] = [];
    const push = (c: Check) => {
      out.push(c);
      setChecks([...out]);
    };

    const missing = ENV_KEYS.filter((k) => !import.meta.env[k]);
    push({
      id: 'config',
      label: 'Bundle configuration',
      state: missing.length === 0 ? 'ok' : 'fail',
      detail:
        missing.length === 0
          ? `${ENV_KEYS.length} variables present`
          : `Missing: ${missing.join(', ')}`,
    });

    push({
      id: 'frame',
      label: 'Execution context',
      state: isFramed() ? 'warn' : 'ok',
      detail: isFramed()
        ? 'Running inside an iframe (Fabric portal). The sign-in popup may be blocked — open the hosting URL in a tab.'
        : 'Standalone tab. Interactive sign-in available.',
    });

    if (!msalConfigured) {
      push({
        id: 'msal',
        label: 'Identity',
        state: 'fail',
        detail: 'Entra client or tenant missing: no token can be acquired.',
      });
      setRunning(false);
      return;
    }

    try {
      await ensureMsalReady();
      const acct = activeAccount();
      push({
        id: 'msal',
        label: 'Identity initialised',
        state: acct ? 'ok' : 'warn',
        detail: acct
          ? `Active account: ${acct.username}`
          : 'Initialised, but no account signed in. Silent acquisitions will fail.',
      });
    } catch (err) {
      push({
        id: 'msal',
        label: 'Identity initialised',
        state: 'fail',
        detail: err instanceof Error ? err.message : String(err),
      });
      setRunning(false);
      return;
    }

    const planes: { id: string; label: string; scopes: string[] }[] = [
      { id: 'tok-fabric', label: 'Fabric token (data agent)', scopes: FABRIC_SCOPES },
      { id: 'tok-pbi', label: 'Power BI token (measure evaluation)', scopes: POWERBI_SCOPES },
    ];

    for (const plane of planes) {
      let lastErr = '';
      let done = false;
      for (const scope of plane.scopes) {
        try {
          const token = await getToken([scope], false);
          push({
            id: plane.id,
            label: plane.label,
            state: 'ok',
            detail: `${scope} → ${describeToken(token)}`,
          });
          done = true;
          break;
        } catch (err) {
          lastErr = err instanceof Error ? err.message : String(err);
        }
      }
      if (!done) {
        push({
          id: plane.id,
          label: plane.label,
          state: 'fail',
          detail: `No scope granted silently. Last error: ${lastErr}`,
        });
      }
    }

    if (!semanticModelId) {
      push({
        id: 'model',
        label: 'Semantic model queryable',
        state: 'skip',
        detail: 'Semantic model id missing from the configuration.',
      });
    } else {
      try {
        // A real measure, not a ping: an unknown measure name comes back as an empty cell
        // rather than an error, so only evaluating one proves the model is the right one.
        const rows = await executeDax(
          'EVALUATE ROW("probe", [Tickets])',
        );
        const value = rows[0]?.['[probe]'] ?? rows[0]?.probe;
        push({
          id: 'model',
          label: 'Semantic model queryable',
          state: value === null || value === undefined ? 'warn' : 'ok',
          detail:
            value === null || value === undefined
              ? 'The model answered, but the measure came back empty — check this really is the expected model.'
              : `Measure Tickets evaluated → ${String(value)}`,
        });
      } catch (err) {
        push({
          id: 'model',
          label: 'Semantic model queryable',
          state: 'fail',
          detail: err instanceof Error ? err.message : String(err),
        });
      }
    }

    setRunning(false);
  };

  return (
    <div
      className="min-h-screen p-8"
      style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}
    >
      <div className="mx-auto max-w-4xl">
        <h1 className="text-2xl font-semibold tracking-tight">Diagnostic</h1>
        <p className="mt-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
          Checks every link between the browser and the Fabric data, and names the one that
          gave way. This page is deliberately reachable without being signed in.
        </p>

        <div className="mt-4 flex items-center gap-3">
          <button
            onClick={() => void run()}
            disabled={running}
            className="rounded-md px-3 py-2 text-sm font-medium text-white transition-all hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            style={{ background: 'var(--accent)' }}
          >
            {running ? 'Checking…' : 'Run the diagnostic'}
          </button>
          <span className="text-xs" style={{ color: 'var(--text-muted)' }}>
            Live mode {liveAvailable() ? 'configured' : 'not configured'}
          </span>
        </div>

        <ul className="mt-6 space-y-2">
          {checks.map((c) => (
            <li key={c.id} className="glass rounded-xl p-4">
              <div className="flex items-center gap-3">
                <span
                  className={`rounded px-2 py-0.5 text-xs font-medium ring-1 ${STATE_STYLE[c.state].chip}`}
                >
                  {STATE_STYLE[c.state].text}
                </span>
                <span className="text-sm font-medium" style={{ color: 'var(--text-primary)' }}>
                  {c.label}
                </span>
              </div>
              <p
                className="mt-2 break-words font-mono text-xs"
                style={{ color: 'var(--text-muted)' }}
              >
                {c.detail}
              </p>
            </li>
          ))}
        </ul>

        {checks.length === 0 && !running ? (
          <p className="mt-6 text-sm" style={{ color: 'var(--text-muted)' }}>
            No results yet.
          </p>
        ) : null}
      </div>
    </div>
  );
}
