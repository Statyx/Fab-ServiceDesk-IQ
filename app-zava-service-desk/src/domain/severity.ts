import type { Severity } from '@/data/types';

/**
 * The single mapping from a domain severity to its presentation.
 * Never inline these classes in a component — two screens would drift apart.
 * Severity is always rendered with its label: colour alone is not a signal.
 */
const MAP: Record<Severity, { text: string; chip: string; label: string }> = {
  critical: {
    text: 'text-severity-critical',
    chip: 'bg-red-50 text-severity-critical ring-red-200',
    label: 'Critical',
  },
  high: {
    text: 'text-severity-high',
    chip: 'bg-orange-50 text-severity-high ring-orange-200',
    label: 'Major',
  },
  medium: {
    text: 'text-severity-medium',
    chip: 'bg-amber-50 text-severity-medium ring-amber-200',
    label: 'Medium',
  },
  low: {
    text: 'text-severity-low',
    chip: 'bg-emerald-50 text-severity-low ring-emerald-200',
    label: 'Minor',
  },
  info: {
    text: 'text-severity-info',
    chip: 'bg-slate-50 text-severity-info ring-slate-200',
    label: 'Info',
  },
};

export const severityText = (s: Severity) => MAP[s].text;
export const severityChip = (s: Severity) => MAP[s].chip;
export const severityLabel = (s: Severity) => MAP[s].label;

/**
 * Operational states reuse the severity ramp rather than growing a second one.
 *
 * A diagnostic "Failed" and a critical alarm mean the same thing to the eye, so
 * they must not be allowed to drift to different reds. Every screen that shows
 * a status — diagnostic checks, the demo/live badge, embed errors — resolves
 * its colours through here.
 */
export type Status = 'ok' | 'warn' | 'fail' | 'neutral';

const STATUS_SEVERITY: Record<Status, Severity> = {
  ok: 'low',
  warn: 'medium',
  fail: 'critical',
  neutral: 'info',
};

export const statusChip = (s: Status) => severityChip(STATUS_SEVERITY[s]);
export const statusText = (s: Status) => severityText(STATUS_SEVERITY[s]);

/** Background-only tint, for panels that carry their own body text. */
const TINT: Record<Status, string> = {
  ok: 'bg-emerald-50',
  warn: 'bg-amber-50',
  fail: 'bg-red-50',
  neutral: 'bg-slate-50',
};

export const statusTint = (s: Status) => TINT[s];

/** Solid fill, for the one case a dot carries the signal alongside a label. */
const DOT: Record<Status, string> = {
  ok: 'bg-emerald-500',
  warn: 'bg-amber-500',
  fail: 'bg-red-500',
  neutral: 'bg-slate-400',
};

export const statusDot = (s: Status) => DOT[s];

const ORDER: Severity[] = ['critical', 'high', 'medium', 'low', 'info'];

export const compareSeverity = (a: Severity, b: Severity) =>
  ORDER.indexOf(a) - ORDER.indexOf(b);
