/**
 * A panel inside a section.
 *
 * Every panel carries an `id` because the cover links straight to them: a card
 * about root cause opens the Incident section scrolled to the interface table,
 * not to the top of a page the user then has to search.
 *
 * `provenance` is not decoration. The console mixes a live Eventhouse with
 * topology that ships in the bundle, and a panel that does not say which one it
 * is reading invites the room to assume the flattering answer.
 */
export function Section({
  id,
  title,
  provenance,
  action,
  children,
}: {
  id: string;
  title: string;
  provenance?: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section id={id} className="glass mt-4 scroll-mt-4 rounded-xl p-4 first:mt-0">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold" style={{ color: 'var(--text-primary)' }}>
            {title}
          </h2>
          {provenance ? (
            <p className="mt-0.5 text-xs" style={{ color: 'var(--text-muted)' }}>
              {provenance}
            </p>
          ) : null}
        </div>
        {action ? <div className="shrink-0">{action}</div> : null}
      </div>
      <div className="mt-3">{children}</div>
    </section>
  );
}
