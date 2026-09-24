/** en-GB display formatting. Values arrive already aggregated by the semantic model. */

const int = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });
const eur = new Intl.NumberFormat('en-GB', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
});

export const fmtInt = (v: number): string => int.format(v);
export const fmtEur = (v: number): string => eur.format(v);

export const fmtPct = (v: number, digits = 1): string =>
  `${new Intl.NumberFormat('en-GB', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(v * 100)}%`;

export const fmtDec = (v: number, digits = 2): string =>
  new Intl.NumberFormat('en-GB', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(v);

/** A change already expressed in percentage points by the model: -12 -> "-12.0 pts". */
export const fmtPts = (v: number, digits = 1): string => {
  const s = new Intl.NumberFormat('en-GB', {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  }).format(Math.abs(v));
  return `${v > 0 ? '+' : v < 0 ? '-' : ''}${s} pts`;
};
