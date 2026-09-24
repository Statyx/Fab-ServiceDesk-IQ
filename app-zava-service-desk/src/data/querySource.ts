import { createContext, useContext } from 'react';

import { executeDax, type DaxRow } from '@/services/powerbi';

export interface QuerySource {
  preview: boolean;
  execute: (dax: string) => Promise<DaxRow[]>;
}

// Live is the default. Only the development preview route supplies a different source.
export const QuerySourceContext = createContext<QuerySource>({
  preview: false,
  execute: executeDax,
});

export function useQuerySource(): QuerySource {
  return useContext(QuerySourceContext);
}
