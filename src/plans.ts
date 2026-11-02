import { Language } from "./translations";

// Примерные тарифы: здесь можно менять названия и длительность.
// Цены на этом этапе не заданы.
export interface Plan {
  id: string;
  days: number;
  names: Record<Language, string>;
}

export const plans: readonly Plan[] = [
  { id: "one", days: 7, names: { kk:"7 күн", ru:"7 дней", en:"7 days", tr:"7 gün", uz:"7 kun", ky:"7 күн", de:"7 Tage", es:"7 días" } },
  { id: "three", days: 18, names: { kk:"18 күн", ru:"18 дней", en:"18 days", tr:"18 gün", uz:"18 kun", ky:"18 күн", de:"18 Tage", es:"18 días" } },
  { id: "six", days: 30, names: { kk:"30 күн", ru:"30 дней", en:"30 days", tr:"30 gün", uz:"30 kun", ky:"30 күн", de:"30 Tage", es:"30 días" } }
];
