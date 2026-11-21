"use client";

import { useActionState } from "react";

import { savePreferences, type PrefsState } from "@/app/actions";
import type { Preferences } from "@/lib/types";

const ALL_TOWNS = ["Cliffside Park", "Lyndhurst", "Fairview", "Elmwood Park", "Saddle Brook"];

const input = "w-full rounded-md border border-stone-300 px-3 py-2 text-sm focus:border-stone-500 focus:outline-none";
const label = "block text-sm font-medium";
const hint = "mt-1 text-xs text-stone-500";

export function PreferencesForm({ prefs }: { prefs: Preferences }) {
  const [state, action, pending] = useActionState<PrefsState, FormData>(savePreferences, null);
  const towns = Array.from(new Set([...ALL_TOWNS, ...prefs.towns]));
  return (
    <form action={action} className="space-y-6 rounded-xl border bg-white p-4 shadow-sm">
      <fieldset className="grid gap-4 sm:grid-cols-2">
        <div>
          <label className={label} htmlFor="max_price">Precio máximo ($)</label>
          <input id="max_price" name="max_price" type="number" step="1000" min={100000} max={5000000} defaultValue={prefs.max_price} className={input} required />
        </div>
        <div>
          <label className={label} htmlFor="target_monthly_cost">Meta mensual después de la renta ($)</label>
          <input id="target_monthly_cost" name="target_monthly_cost" type="number" step="50" min={500} max={50000} defaultValue={prefs.target_monthly_cost ?? ""} className={input} />
          <p className={hint}>Hipoteca + impuestos + seguro + mantenimiento, menos la renta. Vacío = se evalúa por precio.</p>
        </div>
        <div>
          <label className={label} htmlFor="primary_scenario">Financiamiento usado para puntuar</label>
          <select id="primary_scenario" name="primary_scenario" defaultValue={prefs.primary_scenario} className={input}>
            <option value="fha_3_5">FHA 3.5% de enganche</option>
            <option value="conventional_5">Convencional 5% de enganche</option>
            <option value="conventional_20">Convencional 20% de enganche</option>
          </select>
        </div>
        <div>
          <label className={label} htmlFor="owner_unit">Tú vives en la</label>
          <select id="owner_unit" name="owner_unit" defaultValue={prefs.owner_unit} className={input}>
            <option value="largest">Unidad más grande (alquilas las demás)</option>
            <option value="smallest">Unidad más pequeña (alquilas las demás)</option>
          </select>
        </div>
        <div>
          <label className={label} htmlFor="annual_insurance">Seguro de la casa por año ($)</label>
          <input id="annual_insurance" name="annual_insurance" type="number" step="100" min={0} max={50000} defaultValue={prefs.annual_insurance} className={input} required />
        </div>
        <div>
          <label className={label} htmlFor="rate_override_pct">Tasa hipotecaria manual (%)</label>
          <input id="rate_override_pct" name="rate_override_pct" type="number" step="0.01" min={1} max={15} defaultValue={prefs.rate_override != null ? (prefs.rate_override * 100).toFixed(2) : ""} className={input} />
          <p className={hint}>Vacío = promedio semanal de Freddie Mac a 30 años.</p>
        </div>
      </fieldset>

      <fieldset>
        <legend className={label}>Pueblos y tiempo en transporte a 7 WTC</legend>
        <p className={hint}>Minutos desde la parada de autobús a NYC o estación de tren del pueblo hasta 7 WTC; la caminata se suma por casa.</p>
        <div className="mt-2 divide-y divide-stone-100">
          {towns.map((t) => (
            <div key={t} className="flex items-center gap-3 py-2">
              <label className="flex flex-1 items-center gap-2 text-sm">
                <input type="checkbox" name="towns" value={t} defaultChecked={prefs.towns.includes(t)} />
                {t}
              </label>
              {prefs.town_commutes[t] && (
                <label className="flex items-center gap-1 text-sm text-stone-600">
                  <input type="number" name={`commute:${t}`} min={5} max={240} defaultValue={prefs.town_commutes[t].minutes} className="w-20 rounded-md border border-stone-300 px-2 py-1" />
                  min
                </label>
              )}
            </div>
          ))}
        </div>
      </fieldset>

      <div className="flex items-center gap-3">
        <button disabled={pending} className="rounded-md bg-stone-900 px-4 py-2 text-sm font-medium text-white hover:bg-stone-700 disabled:opacity-60">
          {pending ? "Guardando…" : "Guardar preferencias"}
        </button>
        {state && <p className={`text-sm ${state.ok ? "text-emerald-700" : "text-red-700"}`} role="status">{state.message}</p>}
      </div>
    </form>
  );
}
