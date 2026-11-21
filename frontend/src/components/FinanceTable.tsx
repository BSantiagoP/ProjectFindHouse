import { SCENARIO_LABELS, pct, usd } from "@/lib/format";
import type { ScenarioResult } from "@/lib/types";

const ROWS = [
  ["Enganche", "down_payment"],
  ["Capital e intereses", "monthly_principal_interest"],
  ["Seguro hipotecario", "monthly_mortgage_insurance"],
  ["Impuesto predial", "monthly_tax"],
  ["Seguro de la casa", "monthly_insurance"],
  ["Mantenimiento", "monthly_maintenance"],
  ["Costo mensual de vivienda", "monthly_housing_cost"],
  ["Renta neta (tras vacancia/costos)", "net_rental_contribution"],
  ["Pagas al mes", "effective_owner_cost"],
] as const;

export function FinanceTable({ scenarios, primary, fallbackRate }: { scenarios: ScenarioResult[]; primary: string; fallbackRate: number }) {
  return (
    <div className="overflow-x-auto">
      <table className="w-full min-w-[520px] text-sm">
        <thead>
          <tr className="text-left text-stone-500">
            <th className="py-1 font-normal"></th>
            {scenarios.map((s) => (
              <th key={s.scenario} className={`py-1 font-medium ${s.scenario === primary ? "text-stone-900" : ""}`}>
                {SCENARIO_LABELS[s.scenario] ?? s.scenario}
                {s.scenario === primary && " ★"}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-stone-100">
          <tr>
            <td className="py-1.5 text-stone-600">Tasa de interés</td>
            {scenarios.map((s) => (
              <td key={s.scenario} className="py-1.5">{((s.annual_rate ?? fallbackRate) * 100).toFixed(2)}%</td>
            ))}
          </tr>
          {ROWS.map(([label, key]) => (
            <tr key={key} className={key === "effective_owner_cost" ? "font-semibold" : ""}>
              <td className="py-1.5 text-stone-600">{label}</td>
              {scenarios.map((s) => <td key={s.scenario} className="py-1.5">{usd(s[key])}</td>)}
            </tr>
          ))}
          <tr>
            <td className="py-1.5 text-stone-600">La renta cubre</td>
            {scenarios.map((s) => <td key={s.scenario} className="py-1.5">{pct(s.rent_offset_pct)}</td>)}
          </tr>
        </tbody>
      </table>
    </div>
  );
}
