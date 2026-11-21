import { usd } from "@/lib/format";
import type { Property } from "@/lib/types";

type Offer = NonNullable<Property["offer"]>;

export function OfferBox({ offer, listPrice }: { offer: Offer; listPrice: number | null }) {
  if (offer.status !== "ok") {
    return (
      <section className="rounded-xl border bg-white p-4 shadow-sm">
        <h2 className="font-semibold">Oferta sugerida</h2>
        <p className="mt-2 text-sm text-stone-600">{offer.reason ?? "No disponible."}</p>
      </section>
    );
  }
  const label = (k: string | null) => (k ? offer.candidate_labels[k] ?? k : "");
  const vsList = (x: number | null) =>
    x != null && listPrice ? `${x <= listPrice ? "−" : "+"}${Math.abs(Math.round((1 - x / listPrice) * 100))}% vs. lista` : "";
  const rows: [string, number | null, string | null, string][] = [
    ["Oferta inicial", offer.opening, offer.opening_key, "text-stone-900"],
    ["Precio objetivo", offer.target, offer.target_key, "text-emerald-700"],
    ["Máximo (retirarse si se supera)", offer.walk_away, offer.walk_away_key, "text-red-700"],
  ];
  return (
    <section className="rounded-xl border-2 border-emerald-700 bg-white p-4 shadow-sm">
      <h2 className="font-semibold">Oferta sugerida</h2>
      <div className="mt-3 grid gap-3 sm:grid-cols-3">
        {rows.map(([name, value, key, tone]) => (
          <div key={name} className="rounded-lg bg-stone-50 p-3">
            <p className="text-xs text-stone-500">{name}</p>
            <p className={`text-xl font-semibold ${tone}`}>{usd(value)}</p>
            <p className="text-xs text-stone-500">{label(key)} {vsList(value) && `· ${vsList(value)}`}</p>
          </div>
        ))}
      </div>
      {offer.win_price != null && (
        <div className="mt-3 rounded-lg border border-amber-400 bg-amber-50 p-3">
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <p className="text-sm font-semibold text-amber-900">Para ganarla (precio competitivo)</p>
            <p className="text-xl font-semibold text-amber-900">{usd(offer.win_price)}</p>
          </div>
          <p className="text-xs text-amber-900">
            {label(offer.win_key ?? null)} {vsList(offer.win_price) && `· ${vsList(offer.win_price)}`}
            {offer.win_monthly_cost != null && ` · pagarías ~${usd(offer.win_monthly_cost)}/mes`}
          </p>
          {offer.win_over_budget && (
            <p className="mt-1 text-xs font-medium text-red-700">
              Supera tu precio máximo para la meta mensual ({usd(offer.max_affordable_price)}).
            </p>
          )}
          {offer.win_reason && <p className="mt-1 text-sm text-amber-950">{offer.win_reason}</p>}
          <p className="mt-1 text-xs text-amber-800">
            Estimación basada en comparables y días en el mercado; no sabemos cuántas ofertas hay ni a cuánto sobre la
            lista se venden las casas aquí. Pregúntale a tu agente.
          </p>
        </div>
      )}
      <dl className="mt-3 grid grid-cols-2 gap-x-4 gap-y-1 text-sm">
        <dt className="text-stone-500">Ventas comparables (rango)</dt>
        <dd>{usd(offer.comps_low)} – {usd(offer.comps_high)} (mediana {usd(offer.comps_median)})</dd>
        <dt className="text-stone-500">Tu máximo para la meta mensual</dt>
        <dd>{offer.max_affordable_price != null ? usd(offer.max_affordable_price) : "—"}</dd>
      </dl>
      <div className="mt-3 grid gap-4 sm:grid-cols-2">
        <div>
          <h3 className="text-sm font-semibold">Por qué</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-stone-700">{offer.rationale.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
        <div>
          <h3 className="text-sm font-semibold">Riesgos</h3>
          <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-stone-700">{offer.risks.map((r) => <li key={r}>{r}</li>)}</ul>
        </div>
      </div>
      {offer.comps.length > 0 && (
        <details className="mt-3">
          <summary className="cursor-pointer text-sm text-blue-700">Ver {offer.comps.length} ventas comparables</summary>
          <ul className="mt-2 space-y-1 text-sm text-stone-700">
            {offer.comps.map((c) => (
              <li key={c.address}>
                <b>{usd(c.price)}</b> · {c.beds ?? "?"} rec./{c.baths ?? "?"} baños
                {c.distance_mi != null && ` · ${c.distance_mi} mi`}
                {c.days_since_sold != null && ` · vendida hace ~${c.days_since_sold} días`} —{" "}
                {c.url ? <a href={c.url} target="_blank" rel="noopener noreferrer" className="underline">{c.address}</a> : c.address}
              </li>
            ))}
          </ul>
        </details>
      )}
      <p className="mt-3 text-xs text-stone-500">
        Precios calculados con ventas recientes de Zillow (vía HasData) y tu meta mensual; la IA solo elige entre ellos y explica.
        Es una guía para hablar con un agente, no una tasación. La fecha de venta es aproximada.
      </p>
    </section>
  );
}
