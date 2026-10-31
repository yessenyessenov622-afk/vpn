import { Language } from "./translations";

// Примерные тарифы: здесь можно менять названия и длительность.
// Цены на этом этапе не заданы.
export interface Plan {
  id: string;
  days: number;
  names: Record<Language, string>;
}

export const plans: readonly Plan[] = [
  { id: "one", days: 30, names: { kk:"1 ай", ru:"1 месяц", en:"1 month", tr:"1 ay", uz:"1 oy", ky:"1 ай", de:"1 Monat", es:"1 mes" } },
  { id: "three", days: 90, names: { kk:"3 ай", ru:"3 месяца", en:"3 months", tr:"3 ay", uz:"3 oy", ky:"3 ай", de:"3 Monate", es:"3 meses" } },
  { id: "six", days: 180, names: { kk:"6 ай", ru:"6 месяцев", en:"6 months", tr:"6 ay", uz:"6 oy", ky:"6 ай", de:"6 Monate", es:"6 meses" } }
];
