import { afterEach, describe, expect, it, vi } from 'vitest';

import { executeDax } from '@/services/powerbi';

vi.mock('@/services/msal', () => ({ getToken: vi.fn().mockResolvedValue('test-token'), POWERBI_SCOPES: [] }));
afterEach(() => vi.unstubAllGlobals());

describe('Power BI query errors', () => {
  it.each([
    { error: { message: 'Root query failure' } },
    { results: [{ error: { message: 'DAX error' } }] },
    { results: [{ tables: [{ error: { message: 'Truncated result' }, rows: [{ '[planned]': 123 }] }] }] },
  ])('rejects an embedded error even with HTTP 200', async (payload) => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, text: async () => JSON.stringify(payload) }));
    await expect(executeDax('EVALUATE test', 'test-model')).rejects.toThrow('Power BI query error');
  });
  it('preserves valid query rows', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({
      ok: true, text: async () => JSON.stringify({ results: [{ tables: [{ rows: [{ '[x]': 4 }] }] }] }),
    }));
    await expect(executeDax('EVALUATE test', 'test-model')).resolves.toEqual([{ '[x]': 4 }]);
  });
});
