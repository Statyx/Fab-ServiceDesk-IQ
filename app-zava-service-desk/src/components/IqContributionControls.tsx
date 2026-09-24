export interface IqContributions {
  fabric: boolean;
  foundry: boolean;
  work: boolean;
  web: boolean;
}

const CONTRIBUTIONS = [
  { id: 'fabric', label: 'Fabric IQ', detail: 'Figures & ontology scope', effect: 'Which XLA week are we reviewing, and why did it drop?', status: 'Included' },
  { id: 'foundry', label: 'Foundry IQ', detail: 'Contract clause (simulated)', effect: 'What does the agreement make Zava owe?', status: 'Included' },
  { id: 'work', label: 'Work IQ', detail: 'Mail, Teams, meetings, files', effect: 'What is already underway, and who has to act?', status: 'Included' },
  { id: 'web', label: 'Web IQ', detail: 'Public announcements', effect: 'What public news gives the service review more context?', status: 'Included' },
] as const;

export function IqContributionControls({
  value, onChange, busy, contractReady, workReady, webReady,
}: {
  value: IqContributions;
  onChange: (key: keyof IqContributions, checked: boolean) => void;
  busy: boolean;
  contractReady: boolean;
  workReady: boolean;
  webReady: boolean;
}) {
  return (
    <fieldset className="iq-contribution-controls">
      <legend>What each layer contributes</legend>
      <p>Change the context included in both cases.</p>
      <div className="iq-contribution-grid">
        {CONTRIBUTIONS.map((layer) => {
          const ready = layer.id === 'foundry' ? contractReady : layer.id === 'work' ? workReady : layer.id === 'web' ? webReady : true;
          const availableAt = layer.id === 'web' ? 'Web IQ' : layer.id === 'work' ? 'Work IQ' : 'Contract';
          return (
            <label key={layer.id} className={`iq-source-control iq-source-${layer.id} ${ready && value[layer.id] ? 'is-included' : 'is-excluded'}`}>
              <span className="iq-source-control-heading">
                <input type="checkbox" checked={ready && value[layer.id]} disabled={busy || !ready}
                  aria-label={`Include ${layer.label} context`}
                  onChange={(e) => onChange(layer.id, e.target.checked)} />
                <strong>{layer.label}</strong>
              </span>
              <span className="iq-source-control-detail">{layer.detail}</span>
              <small>{layer.effect}</small>
              <span className="iq-source-state">{!ready ? `Available at ${availableAt}` : value[layer.id] ? layer.status : 'Not included'}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
