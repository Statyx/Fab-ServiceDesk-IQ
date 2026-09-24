import * as queries from '@/data/queries';
import type { QuerySource } from '@/data/querySource';
import type { DaxRow } from '@/services/powerbi';

import fixtures from './fixtures.json';

/**
 * Layout fixtures for the design preview.
 *
 * Rows recorded once from the demo semantic model with the exact queries in `data/queries.ts`,
 * so the preview shows the same story as the live console. They are never used as a fallback
 * when a live query fails, and the preview banner says so.
 */
const rowsByQuery = new Map<string, DaxRow[]>(
  Object.entries(fixtures as Record<string, DaxRow[]>).map(([name, rows]) => {
    const dax = (queries as unknown as Record<string, unknown>)[name];
    if (typeof dax !== 'string') throw new Error(`Unknown preview query ${name}.`);
    return [dax, rows];
  }),
);

export const previewSource: QuerySource = {
  preview: true,
  async execute(dax) {
    const rows = rowsByQuery.get(dax);
    if (!rows) throw new Error('No design-preview data is defined for this query.');
    return rows.map((row) => ({ ...row }));
  },
};
