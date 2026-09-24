/**
 * Replay of pre-recorded agent answers, for the opening clicks of a demo.
 *
 * A real answer from the Fabric Data Agent costs 40-160 seconds, because the work happens on
 * the data side: the agent picks a source, writes the query, Fabric runs it, and only then is
 * there prose. That is the right trade for a genuine question and the wrong one for the first
 * click in front of a room, where a minute of spinner is a minute of dead air — and the moment
 * an audience decides the console is slow rather than thorough.
 *
 * So the questions the console itself suggests can be answered from a recording.
 *
 * Two rules make that acceptable, and both are load-bearing:
 *
 *  1. **Nothing here is written by hand.** `scripts/capture_frozen_answers.py` asks the live
 *     Data Agent and stores what came back, together with the sources that really fired and the
 *     time it really took. It refuses to record an answer where nothing fired. A hand-written
 *     answer would look exactly as sourced as a real one — same prose, same provenance block,
 *     same route badges — while being a fabrication, and nobody in the room could tell.
 *
 *     That capture script does not exist yet, and until it does this file holds nothing. The
 *     order is deliberate: the recording cannot be written before the chain it records has been
 *     measured, and writing the answers first — by hand, to have something to show — is exactly
 *     the failure this rule forbids. An empty replay is honest; a hand-seeded one is not.
 *
 *  2. **The replay says so.** The wait names it, and the answer carries the capture date and
 *     the duration the agent actually took. An undisclosed cache would break the same contract
 *     the muted trace dot exists to protect: never present something as observed when it was
 *     not.
 *
 * A miss is fail-safe: the question goes to the live agent exactly as before. Missing a
 * recording costs latency, never correctness — which is why a partial capture, or none at all,
 * is still worth shipping.
 */
import raw from '@/data/frozen-answers.generated.json';

export interface FrozenAnswer {
  text: string;
  /** Sources that really fired during the capture. Never edited, never padded. */
  toolsFired: string[];
  /**
   * Grounding Fabric exposed during the capture, and the query it generated.
   *
   * Recorded and replayed for the same reason the prose is: a replay that dropped them would
   * render as an answer with no provenance next to a live one that has it, and the room would
   * read the *recording* as the unsourced case. Empty stays empty — nothing is padded to make
   * the replay look better than the run it stands in for.
   */
  citations: FrozenCitation[];
  generatedQuery?: string;
  /** Seconds the LIVE agent took when this was recorded — never the replay delay. */
  seconds: number;
  capturedAt: string;
}

export interface FrozenCitation {
  label: string;
  detail?: string;
}

/**
 * How long the replay pauses before revealing.
 *
 * Long enough to read the disclosure, short enough to feel instant next to the 40-160s it
 * stands in for. Zero would be worse than either: an answer that appears the instant the
 * button is pressed reads as hardcoded, which is precisely the accusation the disclosure
 * exists to answer.
 */
export const REPLAY_MS = 5000;

const answers = (raw as { answers?: Record<string, FrozenAnswer> })?.answers ?? {};

/**
 * Tolerant on typing, strict on meaning.
 *
 * Case and whitespace are normalised so a re-typed prompt still gets the instant path, but
 * nothing fuzzier. Matching a *different* question would serve a real, sourced, believable
 * answer to the wrong question — the one failure mode worse than being slow.
 */
const norm = (q: string) => q.trim().replace(/\s+/g, ' ').toLowerCase();

const byNorm = new Map<string, FrozenAnswer>(
  Object.entries(answers).map(([q, a]) => [norm(q), a])
);

/** Keyed on the prompt actually sent, not the label shown, because the prompt is what
 *  determines the answer. Free text therefore always goes live, which is correct. */
export function frozenAnswer(prompt: string): FrozenAnswer | null {
  return byNorm.get(norm(prompt)) ?? null;
}

/** Prompts held, in their original wording. Used by the drift test. */
export function frozenPrompts(): string[] {
  return Object.keys(answers);
}

/** "23 June" — short enough for a chip, explicit enough to spot a stale figure. */
export function frozenDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'long' });
}
