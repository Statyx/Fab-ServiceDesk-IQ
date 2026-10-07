import { describe, expect, it } from 'vitest';
import { render, screen, within } from '@testing-library/react';

import { IqTrace } from '@/features/iq-playground/engine/cards';
import type { SourceRef } from '@/features/iq-playground/types/scenario';

const ref = (system: SourceRef['system'], title: string) => ({ system, title }) as unknown as SourceRef;

describe('IqTrace', () => {
  it('names each IQ layer behind an answer with its source count', () => {
    render(
      <IqTrace
        sources={[
          ref('fabric', 'Semantic model'),
          ref('foundry', 'Fabrikam contract'),
          ref('email', 'Mail'),
          ref('teams', 'Chat'),
          ref('governance', 'Approval policy'),
        ]}
      />,
    );
    const trace = screen.getByRole('list', { name: 'Intelligence used' });
    expect(within(trace).getByText(/Fabric IQ/)).toBeTruthy();
    expect(within(trace).getByText(/Foundry IQ/)).toBeTruthy();
    expect(within(trace).getByText(/Work IQ/)).toBeTruthy();
    expect(within(trace).getByText(/· 2 sources/)).toBeTruthy();
    expect(within(trace).queryByText(/Web IQ/)).toBeNull();
  });

  it('renders nothing when no IQ layer is involved', () => {
    const { container } = render(<IqTrace sources={[ref('governance', 'Approval policy')]} />);
    expect(container.innerHTML).toBe('');
  });
});
