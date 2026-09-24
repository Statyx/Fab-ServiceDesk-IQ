/**
 * Icons are raw SVG path strings held in the manifests that use them.
 *
 * `stroke="currentColor"` is what makes an icon inherit the nav's active or
 * inactive colour with no extra classes. `aria-hidden` because the label next
 * to it is the accessible name.
 *
 * This holds to roughly 15–20 icons; past that, adopt a real icon set.
 */
export function Icon({
  d,
  className,
  style,
}: {
  d: string;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      className={className ?? 'h-5 w-5'}
      style={style}
      fill="none"
      stroke="currentColor"
      strokeWidth={1.75}
      aria-hidden="true"
    >
      <path d={d} strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}
