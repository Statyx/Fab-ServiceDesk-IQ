import { describe, expect, it } from 'vitest';
import scenarioJson from '@/features/iq-playground/scenarios/service-desk/scenario.json';
import { validateScenario } from '@/features/iq-playground/engine/validateScenario';
import type { Scenario } from '@/features/iq-playground/types/scenario';

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

  it('keeps tenant and user identities out of the scenario', () => {
    expect(text).not.toMatch(/@microsoft\.com|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i);
  });
});
