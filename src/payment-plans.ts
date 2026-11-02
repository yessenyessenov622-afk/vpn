// Ruble figures are planning references only, never sent as Stars prices.
export const paymentPlans = [
  {id: "days7", days: 7, referenceRub: 150, priceEnv: "STARS_PRICE_7"},
  {id: "days18", days: 18, referenceRub: 300, priceEnv: "STARS_PRICE_18"},
  {id: "days30", days: 30, referenceRub: 450, priceEnv: "STARS_PRICE_30"},
] as const;

export function starsPrice(value: string | undefined): number | null {
  if (!value || !/^[1-9]\d*$/.test(value)) return null;
  const n = Number(value);
  return Number.isSafeInteger(n) && n <= 1000000 ? n : null;
}
