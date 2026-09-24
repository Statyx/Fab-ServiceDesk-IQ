import { NavLink, useLocation } from 'react-router-dom';

import { Icon } from '@/components/Icon';
import { ModeBadge } from '@/components/ModeBadge';
import { ThemeToggle } from '@/components/ThemeToggle';
import { IQ_NAV, IQ_ROUTE, NAV, SECONDARY_NAV, basePath } from '@/domain/nav';
import { useAuth } from '@/hooks/AuthContext';

/**
 * Application shell — house design system (glass + animated mesh + `data-theme`).
 *
 * The header stays dark in both themes: it is the one fixed anchor while the page below
 * repaints between light and dark. Everything else draws its colour from the CSS variables in
 * `main.css`, so a single attribute on <html> swaps the whole console.
 *
 * The shell owns the text size for everything inside it. No leaf component hardcodes a scale —
 * a component that sets its own cannot be reused at another one.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const { user, signOut } = useAuth();
  const { pathname } = useLocation();
  const base = basePath(pathname);
  const isIq = pathname.replace(/\/+$/, '') === `${base}${IQ_ROUTE}`;

  return (
    <div
      className="flex min-h-screen flex-col text-base"
      style={{ background: 'var(--bg-secondary)', color: 'var(--text-primary)' }}
    >
      <header
        className="sticky top-0 z-30 border-b border-white/10"
        style={{
          background: 'var(--header-bg)',
          backdropFilter: 'blur(24px)',
          WebkitBackdropFilter: 'blur(24px)',
        }}
      >
        <div className="app-header-inner mx-auto flex min-h-[84px] max-w-[1400px] items-center gap-4 px-6">
          <NavLink to={base || '/'} className="flex shrink-0 items-center gap-3">
            <span
              className="flex h-10 w-10 items-center justify-center rounded-xl text-lg"
              style={{ background: 'var(--accent)', color: '#fff' }}
              aria-hidden
            >
              🎧
            </span>
            <span className="leading-tight">
              <span className="block text-sm font-semibold text-white">Zava Service Desk</span>
              <span className="block text-xs text-slate-400">
                Agentic service desk, grounded in Fabric
              </span>
            </span>
          </NavLink>

          <nav className="app-main-nav ml-auto flex items-center gap-1" aria-label="Main navigation">
            {NAV.map((entry) => (
              <NavLink
                key={entry.to}
                to={`${base}${entry.to}`}
                aria-label={entry.label}
                end
                className={({ isActive }) =>
                  [
                    'flex items-center gap-2 rounded-full px-3 py-2 text-sm font-medium transition',
                    'focus-visible:outline-2 focus-visible:outline-offset-2',
                    isActive ? 'text-white' : 'text-slate-400 hover:bg-white/5 hover:text-white',
                  ].join(' ')
                }
                style={({ isActive }) => (isActive ? { background: 'var(--accent)' } : undefined)}
              >
                <Icon d={entry.icon} className="h-4 w-4" />
                <span className="hidden whitespace-nowrap xl:inline">{entry.label}</span>
              </NavLink>
            ))}

            <NavLink
              to={`${base}${IQ_NAV.to}`}
              className={({ isActive }) =>
                `app-iq-link flex items-center gap-2 rounded-full px-3 py-2 text-sm font-medium ${isActive ? 'text-white' : 'text-slate-300 hover:bg-white/5'}`
              }
              style={({ isActive }) => isActive ? { background: 'var(--accent)' } : undefined}
            >
              <Icon d={IQ_NAV.icon} className="h-4 w-4" />
              <span className="whitespace-nowrap">{IQ_NAV.label}</span>
            </NavLink>

            {/* Second-rank destinations, behind a separator and deliberately smaller: icon only,
                named by its tooltip. Architecture has to be reachable without competing with the
                four questions the console is actually opened to answer — a full-size pill beside
                them claims an equal share of the eye that it has not earned. */}
            <span className="mx-1 h-5 w-px bg-white/10" aria-hidden />
            {SECONDARY_NAV.map((entry) => (
              <NavLink
                key={entry.to}
                to={`${base}${entry.to}`}
                end
                title={entry.label}
                aria-label={entry.label}
                className={({ isActive }) =>
                  [
                    'flex items-center rounded-full p-1.5 transition',
                    'focus-visible:outline-2 focus-visible:outline-offset-2',
                    isActive ? 'text-white' : 'text-slate-600 hover:bg-white/5 hover:text-slate-300',
                  ].join(' ')
                }
                style={({ isActive }) => (isActive ? { background: 'var(--accent)' } : undefined)}
              >
                <Icon d={entry.icon} className="h-3.5 w-3.5" />
              </NavLink>
            ))}
          </nav>

          <div className="app-header-tools flex shrink-0 items-center gap-3 border-l border-white/10 pl-4">
            {isIq
              ? <span className="text-xs text-slate-300" title="The comparison labels its own source; the global data badge does not apply here.">IQ walkthrough</span>
              : <ModeBadge />}
            <ThemeToggle />
            {user ? (
              <div className="hidden text-right leading-tight sm:block">
                <span className="block max-w-[10rem] truncate text-xs text-slate-300">
                  {user.name ?? user.email}
                </span>
                <button
                  onClick={() => void signOut()}
                  className="text-xs text-slate-500 transition-colors hover:text-slate-300 focus-visible:outline-2 focus-visible:outline-offset-2"
                >
                  Sign out
                </button>
              </div>
            ) : null}
          </div>
        </div>
      </header>

      <main className="relative min-h-0 flex-1 overflow-x-hidden">
        {/* Decoration only — `pointer-events: none`, and disabled under prefers-reduced-motion. */}
        <div className="mesh-bg" aria-hidden>
          <span className="mesh-blob" />
          <span className="mesh-blob" />
          <span className="mesh-blob" />
        </div>
        <div className="relative z-10 flex min-h-0 flex-1 flex-col">{children}</div>
      </main>
    </div>
  );
}
