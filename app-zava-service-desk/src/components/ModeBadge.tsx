import { getMode, MODE_LABEL, modeReason } from '@/data/mode';
import { useQuerySource } from '@/data/querySource';
import { statusChip, statusDot } from '@/domain/severity';

/**
 * Where the numbers come from, on every live screen.
 *
 * The preview carries no marker: it is shown as the demo itself. Live failures never switch to
 * the preview source, so outside /preview this badge still tells the room what it is reading.
 */
export function ModeBadge() {
  const { preview } = useQuerySource();
  const mode = getMode();
  if (preview) return null;
  const isLive = mode === 'live';

  return (
    <span
      title={modeReason()}
      className={[
        'flex items-center gap-2 rounded-md px-2.5 py-1 text-xs font-medium ring-1',
        isLive ? statusChip('ok') : statusChip('warn'),
      ].join(' ')}
    >
      <span
        aria-hidden="true"
        className={['h-1.5 w-1.5 rounded-full', statusDot(isLive ? 'ok' : 'warn')].join(' ')}
      />
      {MODE_LABEL[mode]}
    </span>
  );
}
