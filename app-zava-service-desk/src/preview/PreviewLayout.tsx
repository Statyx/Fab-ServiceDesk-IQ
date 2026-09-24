import { Link, Outlet } from 'react-router-dom';

import { AssistantProvider } from '@/components/AssistantProvider';
import { QuerySourceContext } from '@/data/querySource';
import { previewSource } from './data';

export default function PreviewLayout() {
  return (
    <QuerySourceContext.Provider value={previewSource}>
      <div
        role="note"
        className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 px-4 py-2 text-xs"
        style={{ background: 'var(--bg-card-solid)', color: 'var(--text-secondary)' }}
      >
        <Link to="/" className="underline underline-offset-2">
          Open live app
        </Link>
      </div>
      <AssistantProvider>
        <Outlet />
      </AssistantProvider>
    </QuerySourceContext.Provider>
  );
}
