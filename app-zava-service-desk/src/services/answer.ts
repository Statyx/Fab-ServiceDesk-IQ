/**
 * Split an agent reply into what an operator reads and what an engineer asks for.
 *
 * ── Why this exists ─────────────────────────────────────────────────────────────────────
 * The Data Agent is instructed to travel with its provenance, and it obeys literally: the
 * lead sentence comes back built out of `telemetry_pfc | where pause_duration_ms > 0` and
 * friends, followed by a bulleted form restating the same fields. True, sourced, and
 * unreadable on a wall screen in front of a customer.
 *
 * Deleting the provenance was never an option — it is what separates this console from a
 * chatbot that sounds confident. So the block is emitted behind a fixed marker and this
 * function moves it out of the prose. The rail puts it behind a button.
 *
 * ── The one rule that governs the parsing ───────────────────────────────────────────────
 * **A marker that fails to match must never hide content.** Everything the splitter does not
 * recognise stays in `body`, visible. The match is therefore deliberately asymmetric:
 *
 *  - The instruction is STRICT: the block opens with exactly `### SOURCE`, in capitals.
 *  - The parser is TOLERANT: heading hashes, bold markers, a trailing colon and the
 *    non-breaking space some models emit before it are stripped before comparison, and the
 *    match is case-insensitive. A model that emits `**Source:**` still gets its detail filed
 *    correctly rather than printed as prose.
 *
 * It splits on the LAST marker line, not the first. "source" is an ordinary English word and
 * can legitimately appear mid-answer ("according to the source table…"); splitting on the
 * first match would swallow the rest of the answer into a collapsed panel — exactly the
 * failure this rule exists to prevent. The block is always last, so the last match is it.
 */

/**
 * Is this line nothing but the word SOURCE, however it was dressed?
 *
 * Written as normalise-then-compare rather than one regex on purpose. A single pattern misses
 * `**Source :**` — the colon sits INSIDE the bold markers and the pattern expects it outside.
 * That class of near-miss is invisible in review and silent at runtime, so the decoration is
 * stripped rather than enumerated in an order that has to be guessed right.
 *
 * `\s` covers the non-breaking space that precedes a colon in French typography, which the
 * agent still emits occasionally even when answering in English.
 */
const DECORATION = /[#*_\s:\u2014-]/g;

function isMarkerLine(line: string): boolean {
  const bare = line.replace(DECORATION, '').toLowerCase();
  return bare === 'source' || bare === 'sources';
}

export interface SplitAnswer {
  /** The prose. Always non-empty when the input was non-empty. */
  body: string;
  /** The provenance block, marker line excluded. `null` when the model emitted none. */
  source: string | null;
}

export function splitAnswer(text: string): SplitAnswer {
  const raw = text ?? '';
  const lines = raw.split('\n');

  let at = -1;
  for (let i = 0; i < lines.length; i += 1) if (isMarkerLine(lines[i])) at = i;

  if (at === -1) return { body: raw.trim(), source: null };

  const body = lines.slice(0, at).join('\n').trim();
  const source = lines.slice(at + 1).join('\n').trim();

  // A marker with nothing under it, or with nothing above it, is a malformed reply. In both
  // cases the safe read is "this was not the block": show the text as written rather than
  // render an empty panel or, worse, an empty answer.
  if (!source || !body) return { body: raw.trim(), source: null };

  return { body, source };
}
