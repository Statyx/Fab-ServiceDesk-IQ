/**
 * Emit the capture list from the question registry.
 *
 *     cd app && npx tsx scripts/freeze-questions.ts
 *
 * The list exists as a file because the recorder is Python and the registry is TypeScript, and
 * the alternative — retyping the prompts on the Python side — is the one thing that must not
 * happen here. A prompt that drifts by a word stops matching at replay: `frozenAnswer()` keys on
 * the exact prompt sent, so a stale copy does not fail loudly, it simply never hits, and the
 * demo quietly goes back to waiting 40-160 seconds with nobody able to say why.
 *
 * That is why this is generated, and why the drift test compares the file against OPENERS on
 * every run: the divergence is caught at build time rather than in front of a room.
 */
import { writeFileSync, mkdirSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { OPENERS } from '../src/domain/openers.ts';

const here = dirname(fileURLToPath(import.meta.url));
const out = join(here, '..', 'src', 'data', 'frozen-questions.generated.json');

const payload = {
  generatedBy: 'app/scripts/freeze-questions.ts',
  // Keyed on `prompt`, not `label`: the prompt is what is sent, and therefore what determines
  // both the answer and the replay lookup.
  entries: OPENERS.map((o) => ({
    id: o.id,
    family: o.family,
    kind: o.kind,
    // Every question goes to the Fabric data agent (`fabric`): the contract clauses are bound in
    // the ontology, so no supervisor is needed. Kept so the recorder can filter on it.
    backend: o.backend,
    depth: o.depth,
    ...(o.parent ? { parent: o.parent } : {}),
    label: o.label,
    prompt: o.prompt,
  })),
};

mkdirSync(dirname(out), { recursive: true });
writeFileSync(out, `${JSON.stringify(payload, null, 2)}\n`, 'utf-8');

const count = (pick: (e: (typeof payload.entries)[number]) => string | number) =>
  payload.entries.reduce<Record<string, number>>((acc, e) => {
    const k = String(pick(e));
    acc[k] = (acc[k] ?? 0) + 1;
    return acc;
  }, {});

const byDepth = count((e) => e.depth);
const byBackend = count((e) => e.backend);
console.log(
  `wrote ${payload.entries.length} questions ` +
    `(depth 1: ${byDepth['1'] ?? 0}, depth 2: ${byDepth['2'] ?? 0}) ` +
    `(fabric: ${byBackend.fabric ?? 0}, foundry: ${byBackend.foundry ?? 0}) -> ${out}`
);
