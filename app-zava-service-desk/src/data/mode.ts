/**
 * Where the numbers come from, stated in one place.
 *
 * The sister console shipped a bundled data set beside the live one, so this module was a
 * genuine switch. The production app has no bundled figures — every figure on every screen is a
 * measure evaluated against the semantic model at render time. That is deliberate: there is a
 * governed model here, so an app that could quietly diverge from `RPT_ServiceDesk` would be
 * demonstrating the opposite of what it claims. The development-only `/preview` route is
 * separate: its query-source provider supplies labelled layout fixtures, never a fallback
 * for a failed live request. ModeBadge reports that provider before consulting this module.
 *
 * So `demo` no longer means "bundled data". It means **not connected**, and the badge has to
 * say so plainly. A console showing a confident zero because its configuration is missing is
 * the single worst thing this app could do in front of a room.
 */
export type DataMode = 'demo' | 'live';

/** Live needs an identity to get a token with, and a model to point it at. */
export function liveAvailable(): boolean {
  return Boolean(
    import.meta.env.VITE_ENTRA_CLIENT_ID &&
      import.meta.env.VITE_ENTRA_TENANT_ID &&
      import.meta.env.VITE_SEMANTIC_MODEL_ID,
  );
}

export function getMode(): DataMode {
  return liveAvailable() ? 'live' : 'demo';
}

/**
 * Kept so the badge keeps its shape, but there is nothing to switch to: with no bundled data,
 * offering a toggle would promise a fallback that does not exist.
 */
export function setMode(_mode: DataMode): void {
  /* no-op: this build has a single source of numbers */
}

export const MODE_LABEL: Record<DataMode, string> = {
  demo: 'Not connected',
  live: 'Live Fabric data',
};

export function modeReason(): string {
  return liveAvailable()
    ? 'Every figure is a measure evaluated against the semantic model.'
    : 'Semantic model or Entra registration missing: no figure is displayed.';
}
