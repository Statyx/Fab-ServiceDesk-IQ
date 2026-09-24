import { useEffect } from 'react';
import { Outlet, useLocation, useSearchParams } from 'react-router-dom';

import { AssistantRail } from '@/components/AssistantRail';
import { useAssistant } from '@/domain/assistant';
import { ALL_NAV, basePath } from '@/domain/nav';
import { OPENERS } from '@/domain/openers';

/**
 * The working shell: a section on the left, the assistant on the right.
 *
 * The grid is `1fr` + a **fixed** rail. A fraction shares growth, so the
 * conversation pane would widen with the window and the app would read as "a
 * chat that happens to have charts". A rail assigns growth, and for a data app
 * the pane allowed to grow is the content.
 *
 * The rail is mounted here rather than inside each page, so switching sections
 * keeps the thread. The cover deliberately sits outside this layout: it is a
 * choice of where to go, not a place to work.
 */
export function WorkspaceLayout() {
  const [params, setParams] = useSearchParams();
  const { pathname } = useLocation();
  const { ask } = useAssistant();

  // ALL_NAV, not NAV: Architecture is a second-rank entry, and looking it up in NAV alone
  // rendered the page with no heading at all.
  const sectionPath = pathname.slice(basePath(pathname).length).replace(/\/+$/, '') || '/';
  const section = ALL_NAV.find((n) => n.to === sectionPath);
  const focus = params.get('focus');

  /**
   * A question named in the URL is asked once, then stripped.
   *
   * Leaving it in place would re-ask on every refresh — a question that costs a
   * minute of agent time and, in front of a room, a minute of silence.
   */
  useEffect(() => {
    const id = params.get('ask');
    if (!id) return;
    const opener = OPENERS.find((o) => o.id === id);
    const keep = params.get('focus');
    setParams(keep ? { focus: keep } : {}, { replace: true });
    if (opener) ask(opener);
  }, [params, setParams, ask]);

  /**
   * Six cards land on three sections, so the section alone would not tell the
   * user which card they clicked. The focus anchor scrolls the panel that
   * answers it into view and marks it for a couple of seconds.
   */
  useEffect(() => {
    if (!focus) return;
    const el = document.getElementById(focus);
    if (!el) return;
    el.scrollIntoView({ behavior: 'smooth', block: 'start' });
    el.setAttribute('data-focused', 'true');
    const t = window.setTimeout(() => el.removeAttribute('data-focused'), 2400);
    return () => window.clearTimeout(t);
  }, [focus, pathname]);

  /**
   * The pane is a **container**, and the pages size themselves against it.
   *
   * Viewport breakpoints lie here: a 1280 px window leaves the working pane
   * around 880 px once the rail and the padding are taken out, so an `xl:`
   * two-column split fires while the columns it creates are half the width the
   * breakpoint assumed. Headlines then set one word per line. Measuring the
   * pane instead of the window is the only way the pages can be honest about
   * the room they actually have.
   */
  return (
    <div className="grid h-[calc(100vh-84px)] grid-cols-[1fr_19rem] xl:grid-cols-[1fr_22rem] 2xl:grid-cols-[1fr_24rem]">
      <div className="@container min-w-0 overflow-y-auto p-4 sm:p-6">
        {section ? (
          <header className="mb-5">
            <h1 className="text-xl font-semibold" style={{ color: 'var(--text-primary)' }}>
              {section.label}
            </h1>
            <p className="mt-1 text-sm" style={{ color: 'var(--text-muted)' }}>
              {section.blurb}
            </p>
          </header>
        ) : null}
        <Outlet />
      </div>

      <AssistantRail />
    </div>
  );
}
