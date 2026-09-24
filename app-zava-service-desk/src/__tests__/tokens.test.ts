import { readFileSync, readdirSync, statSync } from 'node:fs';
import { join } from 'node:path';

import { describe, expect, it } from 'vitest';

const SRC = join(process.cwd(), 'src');
const css = readFileSync(join(SRC, 'main.css'), 'utf8');

function walk(dir: string, out: string[] = []): string[] {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) walk(full, out);
    else if (/\.tsx?$/.test(entry)) out.push(full);
  }
  return out;
}

const sources = walk(SRC).map((f) => ({ file: f, text: readFileSync(f, 'utf8') }));

/** Every declaration block for a selector, concatenated — the ramp is split across several. */
function blocks(selector: string): string {
  const out: string[] = [];
  const needle = `${selector} {`;
  for (let i = css.indexOf(needle); i !== -1; i = css.indexOf(needle, i + 1)) {
    const end = css.indexOf('}', i);
    if (end !== -1) out.push(css.slice(i, end));
  }
  return out.join('\n');
}

const lightVars = blocks("[data-theme='light']");
const darkVars = blocks("[data-theme='dark']");

const readVar = (block: string, name: string) =>
  block.match(new RegExp(`${name}:\\s*([^;]+);`))?.[1].trim();

describe('design tokens', () => {
  it('defines every severity the code can render', () => {
    // A missing token does not fail the build — Tailwind emits nothing and the
    // text renders in the inherited colour, which reads as "not severe".
    for (const s of ['critical', 'high', 'medium', 'low', 'info']) {
      expect(css).toContain(`--color-severity-${s}:`);
    }
  });

  it('keeps a single text-size knob in rem terms', () => {
    // 115%, not the browser default: the console is read off a projector or a wall
    // screen from several metres, where 13.5px body text is unreadable. Every size
    // downstream is in rem, so this one dial moves the whole app.
    expect(css).toMatch(/html\s*\{[^}]*font-size:\s*115%/);
  });

  it('ships dark mode completely, or it is not shipped at all', () => {
    // Half-implemented dark mode is worse than none: it looks broken only for the
    // users who prefer it. The contract is the variant, a full dark ramp, a lifted
    // severity ramp, a persisted toggle and `color-scheme` — together.
    expect(css).toContain('@custom-variant dark');
    expect(css).toContain("data-theme='dark'");

    for (const v of ['--bg-secondary', '--bg-card-solid', '--text-primary', '--text-muted', '--border']) {
      expect(darkVars).toContain(`${v}:`);
    }

    // A light-mode red-600 on a #1e293b card is 3.4:1 — under the AA floor — so an
    // alarm would read as dimmer than the text beside it.
    for (const s of ['critical', 'high', 'medium', 'low', 'info']) {
      expect(darkVars).toContain(`--sev-${s}:`);
    }

    const toggle = sources.find((s) => s.file.includes('useTheme'));
    expect(toggle, 'no theme hook').toBeDefined();
    expect(toggle!.text).toContain('localStorage.setItem');
    expect(toggle!.text).toContain('colorScheme');
    // Storage is partitioned, and sometimes refused outright, inside the Fabric
    // portal iframe. Losing the preference is acceptable; throwing is not.
    expect(toggle!.text).toMatch(/try\s*\{[\s\S]*localStorage[\s\S]*\}\s*catch/);
  });

  it('keeps the page darker than the cards sitting on it', () => {
    // When both were the same value the cards dissolved into the page and only
    // their borders drew them.
    for (const [name, vars] of [
      ['light', lightVars],
      ['dark', darkVars],
    ] as const) {
      const page = readVar(vars, '--bg-secondary');
      const card = readVar(vars, '--bg-card-solid');
      expect(page, `${name}: no --bg-secondary`).toBeTruthy();
      expect(card, `${name}: no --bg-card-solid`).toBeTruthy();
      expect(page, `${name}: page and card are the same colour`).not.toBe(card);
    }
  });

  it('treats the animated backdrop as decoration, never information', () => {
    expect(css).toMatch(/prefers-reduced-motion:\s*reduce/);
    expect(css).toMatch(/\.mesh-bg\s*\{[^}]*pointer-events:\s*none/);
  });
});

describe('presentation discipline', () => {
  it('never inlines severity colours outside the severity module', () => {
    // Two screens that map severity independently drift apart on the day it
    // matters.
    const offenders = sources.filter(
      (s) =>
        !s.file.includes('severity.ts') &&
        !s.file.includes('__tests__') &&
        /\b(?:bg|text|ring)-(?:red|orange|amber|emerald)-\d{2,3}\b/.test(s.text)
    );
    expect(offenders.map((o) => o.file)).toEqual([]);
  });

  it('sizes text in rem, never in px', () => {
    const offenders = sources.filter((s) =>
      /\btext-\[\d+px\]|font-size:\s*\d+px/.test(s.text)
    );
    expect(offenders.map((o) => o.file)).toEqual([]);
  });

  it('uses the house card surface, not a flat white rectangle', () => {
    // `.glass` carries the themed background, border and shadow in one place. A
    // hand-rolled `bg-white` card ignores the theme and stays a light rectangle
    // at night while everything around it repaints.
    const offenders = sources.filter(
      (s) => !s.file.includes('__tests__') && /rounded-lg border bg-white/.test(s.text)
    );
    expect(offenders.map((o) => o.file)).toEqual([]);
  });
});

describe('secrets', () => {
  it('ships no client secret in the bundle', () => {
    // Everything in a Fabric App bundle is public. IDs are fine; a secret is not.
    const offenders = sources.filter((s) =>
      /VITE_[A-Z_]*(SECRET|PASSWORD|PRIVATE_KEY)/.test(s.text)
    );
    expect(offenders.map((o) => o.file)).toEqual([]);
  });
});
