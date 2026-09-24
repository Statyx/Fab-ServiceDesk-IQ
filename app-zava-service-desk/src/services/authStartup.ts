/**
 * Guards for the one auth step that runs with no user gesture behind it: startup.
 *
 * The Fabric portal opens this app inside a cross-origin iframe. In that host a promise that
 * never settles pins the whole UI on a spinner with nothing on screen saying which step
 * stalled — and the host cannot be reproduced on a dev machine, so "this call always settles"
 * is an assumption rather than something observed.
 *
 * The fix is not to identify the culprit promise but to make it impossible for any of them to
 * hang the app: bound every startup wait, then say on screen how far it got.
 */

/** Startup must never out-wait a demo audience's patience. */
export const STARTUP_TIMEOUT_MS = 8000;

/**
 * True when the app is running inside an iframe — which is exactly how the Fabric portal
 * opens it.
 *
 * Reading `window.top` across origins throws; that throw is itself proof of being framed by a
 * different origin, so it resolves to `true` rather than being swallowed as unknown.
 */
export function isFramed(): boolean {
  try {
    return window.self !== window.top;
  } catch {
    return true;
  }
}

export class StartupTimeoutError extends Error {
  constructor(
    public readonly step: string,
    public readonly ms: number
  ) {
    super(`${step} did not settle within ${ms} ms`);
    this.name = 'StartupTimeoutError';
  }
}

/**
 * Resolve `promise`, or reject with {@link StartupTimeoutError} once `ms` has passed.
 *
 * The underlying promise is not cancelled — it cannot be — it is only stopped from being the
 * thing the UI waits on.
 */
export function withTimeout<T>(
  promise: Promise<T>,
  step: string,
  ms: number = STARTUP_TIMEOUT_MS
): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new StartupTimeoutError(step, ms)), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (err) => {
        clearTimeout(timer);
        reject(err);
      }
    );
  });
}
