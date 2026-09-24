import { lazy, Suspense, useEffect, useState } from 'react';
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom';

import { AppShell } from '@/components/AppShell';
import { AssistantProvider } from '@/components/AssistantProvider';
import { AuthPage } from '@/components/AuthPage';
import { ARCHITECTURE_ROUTE, DIAGNOSTIC_ROUTE, IQ_NAV, IQ_ROUTE } from '@/domain/nav';
import { useAuth } from '@/hooks/AuthContext';
import { WorkspaceLayout } from '@/layouts/WorkspaceLayout';
import { ArchitecturePage } from '@/pages/ArchitecturePage';
import { ContractsPage } from '@/pages/ContractsPage';
import { CoverPage } from '@/pages/CoverPage';
import { AgentsPage } from '@/pages/AgentsPage';
import { DiagnosticPage } from '@/pages/DiagnosticPage';
import { ExperiencePage } from '@/pages/ExperiencePage';
import { PortfolioPage } from '@/pages/PortfolioPage';
import { XlaPage } from '@/pages/XlaPage';
import { isFramed, STARTUP_TIMEOUT_MS } from '@/services/authStartup';

const PreviewLayout = import.meta.env.DEV
  ? lazy(() => import('@/preview/PreviewLayout'))
  : null;

const IqInPracticePage = lazy(() => import('@/pages/IqInPracticePage').then((m) => ({ default: m.IqInPracticePage })));

function IqPage() {
  return <Suspense fallback={<p className="p-6">Loading {IQ_NAV.label}…</p>}><IqInPracticePage /></Suspense>;
}

/**
 * A spinner with no exit is the failure this guard exists to avoid.
 *
 * Startup can stall for reasons the app cannot fix from inside — most often a silent-SSO
 * iframe that never settles inside the Fabric portal. Once the startup budget has elapsed we
 * stop pretending to load and offer the two things that actually help: the diagnostic screen,
 * and opening the app in a real tab.
 */
function StartupStalled() {
  return (
    <div
      className="flex min-h-screen items-center justify-center p-8"
      style={{ background: 'var(--bg-secondary)' }}
    >
      <div className="glass max-w-md rounded-xl p-6">
        <h1 className="text-base font-semibold" style={{ color: 'var(--text-primary)' }}>
          Sign-in did not complete
        </h1>
        <p className="mt-2 text-sm" style={{ color: 'var(--text-secondary)' }}>
          {isFramed()
            ? 'This page is running inside a Fabric portal iframe, where silent sign-in and sign-in popups are often blocked.'
            : 'Session startup took longer than the allotted budget.'}
        </p>
        <div className="mt-4 flex flex-wrap gap-3">
          <a
            href={window.location.origin}
            target="_blank"
            rel="noreferrer"
            className="rounded-md px-3 py-2 text-sm font-medium text-white focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{ background: 'var(--accent)' }}
          >
            Open in a new tab
          </a>
          <a
            href={DIAGNOSTIC_ROUTE}
            className="rounded-md border px-3 py-2 text-sm font-medium focus-visible:outline-2 focus-visible:outline-offset-2"
            style={{ borderColor: 'var(--border)', color: 'var(--text-secondary)' }}
          >
            Diagnostic
          </a>
        </div>
      </div>
    </div>
  );
}

function AuthGuard({
  children,
  requireAuth,
}: {
  children: React.ReactNode;
  requireAuth: boolean;
}) {
  const { isAuthenticated, loading } = useAuth();
  const [stalled, setStalled] = useState(false);

  useEffect(() => {
    if (!loading) {
      setStalled(false);
      return;
    }
    // Slightly longer than the startup budget: this is the backstop for when that budget
    // itself fails to fire.
    const id = window.setTimeout(() => setStalled(true), STARTUP_TIMEOUT_MS + 2000);
    return () => window.clearTimeout(id);
  }, [loading]);

  if (loading) {
    return stalled ? (
      <StartupStalled />
    ) : (
      <div
        className="flex min-h-screen items-center justify-center"
        style={{ background: 'var(--bg-secondary)' }}
      >
        <div className="text-sm" style={{ color: 'var(--text-muted)' }}>
          Signing in…
        </div>
      </div>
    );
  }

  if (requireAuth && !isAuthenticated) return <Navigate to="/auth" replace />;
  if (!requireAuth && isAuthenticated) return <Navigate to="/" replace />;

  return <>{children}</>;
}

function Guarded({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard requireAuth={true}>
      <AppShell>{children}</AppShell>
    </AuthGuard>
  );
}

function App() {
  return (
    <BrowserRouter>
      <AssistantProvider>
        <Routes>
          <Route
            path="/auth"
            element={
              <AuthGuard requireAuth={false}>
                <AuthPage />
              </AuthGuard>
            }
          />

          {/* Outside the guard on purpose: sign-in is the most likely broken link, and a
              diagnostic that needs sign-in cannot report on sign-in. */}
          <Route path={DIAGNOSTIC_ROUTE} element={<DiagnosticPage />} />

          {/* Design preview, development only.
              `import.meta.env.DEV` is statically false in a production build, so this subtree
              is dropped at bundle time rather than merely hidden — the screens can be iterated
              on without a tenant, and cannot be reached once shipped. */}
          {import.meta.env.DEV && PreviewLayout ? (
            <Route
              path="/preview"
              element={
                <Suspense fallback={<p className="p-6">Loading preview…</p>}>
                  <PreviewLayout />
                </Suspense>
              }
            >
              <Route
                index
                element={
                  <AppShell>
                    <CoverPage />
                  </AppShell>
                }
              />
              <Route
                path="iq-in-practice"
                element={<AppShell><IqPage /></AppShell>}
              />
              <Route
                element={
                  <AppShell>
                    <WorkspaceLayout />
                  </AppShell>
                }
              >
                <Route path="portfolio" element={<PortfolioPage />} />
                <Route path="experience" element={<ExperiencePage />} />
                <Route path="agents" element={<AgentsPage />} />
                <Route path="contracts" element={<ContractsPage />} />
                <Route path="xla" element={<XlaPage />} />
                <Route path="architecture" element={<ArchitecturePage />} />
              </Route>
            </Route>
          ) : null}

          {/* The cover sits outside the workspace chrome, and that is the whole point of it: a
              title page with a nav rail and a chat panel beside it is just another screen.
              Passing through it and *then* seeing the chrome appear is what makes the console
              feel entered rather than merely loaded. */}
          <Route
            path="/"
            element={
              <Guarded>
                <CoverPage />
              </Guarded>
            }
          />

          {/* The layout route carries no path, so each section keeps its own URL and the
              assistant panel is mounted once for all of them rather than per screen. */}
          <Route
            path={IQ_ROUTE}
            element={<Guarded><IqPage /></Guarded>}
          />

          <Route
            element={
              <Guarded>
                <WorkspaceLayout />
              </Guarded>
            }
          >
            <Route path="/portfolio" element={<PortfolioPage />} />
            <Route path="/experience" element={<ExperiencePage />} />
            <Route path="/agents" element={<AgentsPage />} />
            <Route path="/contracts" element={<ContractsPage />} />
            <Route path="/xla" element={<XlaPage />} />
            <Route path={ARCHITECTURE_ROUTE} element={<ArchitecturePage />} />
          </Route>

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AssistantProvider>
    </BrowserRouter>
  );
}

export default App;
