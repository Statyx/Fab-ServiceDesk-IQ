import { describe, expect, it } from 'vitest';
import scenarioJson from '@/features/iq-playground/scenarios/service-desk/scenario.json';
import { validateScenario } from '@/features/iq-playground/engine/validateScenario';
import type { Scenario } from '@/features/iq-playground/types/scenario';
import { iqLayersOf } from '@/features/iq-playground/engine/cards';

const scenario = scenarioJson as unknown as Scenario;
const text = JSON.stringify(scenarioJson);

describe('Zava IQ service desk scenario', () => {
  it('passes the playground validator', () => {
    expect(validateScenario(scenarioJson)).toEqual([]);
  });

  it('carries the storyline figures computed in Fabric', () => {
    expect(text).toContain('34.0%');
    expect(text).toContain('9,250');
    expect(text).toContain('38.0%');
  });

  it('opens on both customers with different figures', () => {
    const tracks = scenario.tracks.map((t) => t.id);
    expect(tracks).toEqual(['week-38-close', 'litware-remediation']);
  });

  it('never labels the storyline as staged', () => {
    expect(text).not.toMatch(/simulat|fictional|not live|\bdemo\b|\breset\b|preview data/i);
  });

  it('names the intelligence behind every answer that carries a figure', () => {
    for (const track of scenario.tracks) {
      for (const scene of track.scenes) {
        for (const choice of scene.choices) {
          const refs = [...(choice.sources ?? []), ...(choice.emailDraft?.references ?? [])];
          if (/\d/.test(choice.assistant)) {
            expect(iqLayersOf(refs).length, `${track.id}: ${choice.label}`).toBeGreaterThan(0);
          }
        }
      }
    }
  });

  it('plans the week 38 close across all four IQ layers', () => {
    const plan = scenario.tracks[0].scenes
      .flatMap((s) => s.choices)
      .find((c) => (c.sources ?? []).some((s) => s.system === 'web') && (c.sources ?? []).some((s) => s.system === 'fabric'));
    expect(plan).toBeDefined();
    expect(iqLayersOf(plan!.sources ?? []).sort()).toEqual(['fabric', 'foundry', 'web', 'work']);
  });

  it('grounds the Litware remediation in Work IQ from the first answer', () => {
    const first = scenario.tracks[1].scenes[0].choices.flatMap((c) => c.sources ?? []);
    expect(iqLayersOf(first)).toContain('work');
  });

  it('keeps tenant and user identities out of the scenario', () => {
    expect(text).not.toMatch(/@microsoft\.com|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  });
});
