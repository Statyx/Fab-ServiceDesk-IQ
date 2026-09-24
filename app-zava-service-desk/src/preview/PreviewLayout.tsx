import { Outlet } from 'react-router-dom';

import { AssistantProvider } from '@/components/AssistantProvider';
import { QuerySourceContext } from '@/data/querySource';
import { previewSource } from './data';

export default function PreviewLayout() {
  return (
    <QuerySourceContext.Provider value={previewSource}>
      <AssistantProvider>
        <Outlet />
      </AssistantProvider>
    </QuerySourceContext.Provider>
  );
}
