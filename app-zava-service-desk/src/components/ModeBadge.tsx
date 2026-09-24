import { getMode, MODE_LABEL, modeReason } from '@/data/mode';
import { useQuerySource } from '@/data/querySource';
import { statusChip, statusDot } from '@/domain/severity';

/**
 * Where the numbers come from, always on screen.
 *
 * The development preview has its own sample source; live failures never switch to it.
 * This badge describes the selected source, rather than promising a successful connection.
 */
export function ModeBadge() {
  const { preview } = useQuerySource();
  const mode = getMode();
  const isLive = !preview && mode === 'live';

  return (
    <span
      title={preview ? 'Illustrative figures for design review. No Power BI query is sent.' : modeReason()}
      className={[
        'flex items-center gap-2 rounded-md px-2.5 py-1 text-xs font-medium ring-1',
        isLive ? statusChip('ok') : statusChip('warn'),
      ].join(' ')}
    >
      <span
        aria-hidden="true"
        className={['h-1.5 w-1.5 rounded-full', statusDot(isLive ? 'ok' : 'warn')].join(' ')}
      />
      {preview ? 'Preview data' : MODE_LABEL[mode]}
    </span>
  );
}
