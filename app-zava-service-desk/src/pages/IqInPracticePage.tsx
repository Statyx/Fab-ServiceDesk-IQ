import PlaygroundShell from '@/features/iq-playground/engine/PlaygroundShell';
import serviceDesk from '@/features/iq-playground/scenarios/service-desk/scenario.json';
import type { Scenario } from '@/features/iq-playground/types/scenario';

const scenario = serviceDesk as unknown as Scenario;

export function IqInPracticePage() {
  return (
    <div className="iq-playground min-h-full flex-1">
      <PlaygroundShell scenario={scenario} />
    </div>
  );
}
