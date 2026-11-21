import Link from "next/link";
import { notFound } from "next/navigation";

import { FeedbackButtons } from "@/components/FeedbackButtons";
import { CategoryBar, ScoreBadge } from "@/components/Score";
import { AgentSummaryBox } from "@/components/Verdict";
import { getFeedbackMap, getLatestRun, getPriceHistory } from "@/lib/data";
import { FEATURE_LABELS, SCENARIO_LABELS, SOURCE_LABELS, STATUS_LABELS, humanize, pct, shortDate, usd } from "@/lib/format";
import type { FeatureName } from "@/lib/types";

export const dynamic = "force-dynamic";

// "basement_bathroom — Foto 33: ..." -> "Baño en el sótano — Foto 33: ..."
const likelyLabel = (l: string) => {
  const [key, ...rest] = l.split(" — ");
  return [FEATURE_LABELS[key] ?? key, ...rest].join(" — ");
};

const FEATURE_ORDER: FeatureName[] = ["laundry", "garage", "driveway", "finished_basement", "basement_bathroom", "outdoor_space"];

export default async function PropertyPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const [latest, feedback, history] = await Promise.all([getLatestRun(), getFeedbackMap(), getPriceHistory(id)]);
  const r = latest?.results.find((x) => x.property_id === id);
  if (!r) notFound();
  const p = r.property;
  const a = r.analysis;
  const fb = feedback[id];
  const verdict = fb?.rejected ? "rejected" : fb?.liked ? "liked" : "none";
  const scenarios = a ? Object.values(a.finance) : [];

  return (
    <div className="space-y-6">
      <Link href="/" className="text-sm text-stone-500 hover:text-stone-900">← Todas las casas</Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-stone-500">
            {r.rank ? `#${r.rank} · ` : ""}{p.town} · {p.units && p.units > 1 ? `${p.units} unidades` : "Unifamiliar"} · publicada {shortDate(p.listed_date)}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">{p.address.raw}</h1>
          <p className="text-xl font-semibold">{usd(p.price)}</p>
          <p className="mt-1 text-sm text-stone-600">
            {[p.beds && `${p.beds} rec.`, p.baths && `${p.baths} baños`, p.living_area_sqft && `${p.living_area_sqft.toLocaleString("es-US")} pies²`, p.year_built && `construida en ${p.year_built}`]
              .filter(Boolean)
              .join(" · ")}
          </p>
          <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-sm text-blue-700 underline">
            Ver anuncio en Zillow
          </a>
        </div>
        <div className="flex flex-col items-end gap-3">
          {a && <ScoreBadge score={a.score} confidence={a.confidence} />}
          <FeedbackButtons propertyId={id} initial={verdict} />
        </div>
      </header>

      {fb?.rejected && (
        <div className="rounded-lg border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          Descartaste esta casa: no aparece en las listas. Toca &quot;Descartada&quot; para restaurarla.
        </div>
      )}

      {r.filter_status !== "eligible" && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          {r.filter_status === "rejected" ? "Descartada: " + r.rejections.join("; ") : "Por verificar: " + r.unverified.join(", ")}
        </div>
      )}

      {p.agent_summary && <AgentSummaryBox summary={p.agent_summary} />}

      {p.photo_urls.length > 0 && (
        <section className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-2">
          {p.photo_urls.slice(0, 40).map((url, i) => (
            <figure key={url} className="relative shrink-0 snap-start">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url} alt={`Foto ${i + 1}`} loading="lazy" className="h-44 w-64 rounded-lg object-cover" />
              <figcaption className="absolute left-1 top-1 rounded bg-black/60 px-1.5 text-xs text-white">{i + 1}</figcaption>
            </figure>
          ))}
        </section>
      )}

      {a && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Por qué esta puntuación</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-stone-700">
            {a.explanation.map((line) => <li key={line}>{line}</li>)}
          </ul>
          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            {a.categories.map((c) => (
              <CategoryBar key={c.name} name={humanize(c.name)} weight={c.weight} score={c.score} reason={c.reason} />
            ))}
          </div>
        </section>
      )}

      {scenarios.length > 0 && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Financiamiento</h2>
          <p className="text-xs text-stone-500">
            Tasa {(a!.rate * 100).toFixed(2)}% ({a!.rate_source}); ajustada para FHA. Son estimaciones, no cotizaciones.
          </p>
          <div className="mt-3 overflow-x-auto">
            <table className="w-full min-w-[520px] text-sm">
              <thead>
                <tr className="text-left text-stone-500">
                  <th className="py-1 font-normal"></th>
                  {scenarios.map((s) => (
                    <th key={s.scenario} className={`py-1 font-medium ${s.scenario === a!.primary_scenario ? "text-stone-900" : ""}`}>
                      {SCENARIO_LABELS[s.scenario] ?? s.scenario}
                      {s.scenario === a!.primary_scenario && " ★"}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-stone-100">
                <tr>
                  <td className="py-1.5 text-stone-600">Tasa de interés</td>
                  {scenarios.map((s) => (
                    <td key={s.scenario} className="py-1.5">{((s.annual_rate ?? a!.rate) * 100).toFixed(2)}%</td>
                  ))}
                </tr>
                {([
                  ["Enganche", "down_payment"],
                  ["Capital e intereses", "monthly_principal_interest"],
                  ["Seguro hipotecario", "monthly_mortgage_insurance"],
                  ["Impuesto predial", "monthly_tax"],
                  ["Seguro de la casa", "monthly_insurance"],
                  ["Mantenimiento", "monthly_maintenance"],
                  ["Costo mensual de vivienda", "monthly_housing_cost"],
                  ["Renta neta (tras vacancia/costos)", "net_rental_contribution"],
                  ["Pagas al mes", "effective_owner_cost"],
                ] as const).map(([label, key]) => (
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
        </section>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Renta</h2>
          {p.rent_estimate?.status === "estimated" ? (
            <ul className="mt-2 space-y-1 text-sm">
              <li className="text-stone-600">Tú vives en: {p.rent_estimate.owner_unit}</li>
              {p.rent_estimate.rental_units.map((u) => (
                <li key={u.label}>
                  {u.label} ({u.bedrooms} rec.): <b>{usd(u.rent)}</b>/mes
                  <span className="text-stone-500"> (rango {usd(u.range_low)}–{usd(u.range_high)})</span>
                </li>
              ))}
              <li className="pt-1 text-xs text-stone-500">Estimación de RentCast solo para la(s) unidad(es) a alquilar.</li>
            </ul>
          ) : (
            <p className="mt-2 text-sm text-stone-600">{p.rent_estimate?.reason ?? "No estimada"}</p>
          )}
        </section>
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Trayecto</h2>
          {p.commute?.total_minutes != null ? (
            <ul className="mt-2 space-y-1 text-sm">
              <li>
                <b>~{p.commute.total_minutes} min</b> a {p.commute.destination}
              </li>
              <li className="text-stone-600">{p.commute.walk_minutes} min caminando a {p.commute.nearest_stop}</li>
              <li className="text-stone-600">luego {p.commute.route} (~{p.commute.town_minutes} min)</li>
              <li className="pt-1 text-xs text-stone-500">Estimación por pueblo + paradas de NJ Transit; no es una ruta puerta a puerta.</li>
              {p.drives?.map((d) => (
                <li key={d.address} className="pt-2">
                  <b>{d.minutes != null ? `~${d.minutes} min` : "No estimado"}</b> en auto a {d.address}
                  {d.miles != null && <span className="text-stone-500"> ({d.miles} mi, sin tráfico)</span>}
                </li>
              ))}
            </ul>
          ) : (
            <p className="mt-2 text-sm text-stone-600">No estimado</p>
          )}
        </section>
      </div>

      <section className="rounded-xl border bg-white p-4 shadow-sm">
        <h2 className="font-semibold">Características y evidencia</h2>
        <ul className="mt-2 divide-y divide-stone-100">
          {FEATURE_ORDER.map((name) => {
            const f = p.features[name];
            const icon = f.state === "present" ? "✓" : f.state === "absent" ? "✗" : "?";
            const tone = f.state === "present" ? "text-emerald-700" : f.state === "absent" ? "text-red-700" : "text-stone-400";
            return (
              <li key={name} className="py-2 text-sm">
                <span className={`mr-2 font-semibold ${tone}`}>{icon}</span>
                <span className="font-medium">{FEATURE_LABELS[name]}</span>
                {f.source && <span className="ml-2 text-xs text-stone-500">({SOURCE_LABELS[f.source] ?? f.source})</span>}
                {f.evidence && <p className="ml-6 mt-0.5 text-stone-600">“{f.evidence}”</p>}
              </li>
            );
          })}
        </ul>
        {p.photo_analysis?.likely && p.photo_analysis.likely.length > 0 && (
          <div className="mt-3 rounded-md bg-amber-50 p-3 text-sm text-amber-900">
            <p className="font-medium">Probable según fotos — verifícalo en persona:</p>
            <ul className="mt-1 list-disc pl-5">
              {p.photo_analysis.likely.map((l) => <li key={l}>{likelyLabel(l)}</li>)}
            </ul>
          </div>
        )}
        {p.llm_analysis?.red_flags && p.llm_analysis.red_flags.length > 0 && (
          <div className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-900">
            <p className="font-medium">Alertas del anuncio (texto original):</p>
            <ul className="mt-1 list-disc pl-5">
              {p.llm_analysis.red_flags.map((q) => <li key={q}>“{q}”</li>)}
            </ul>
          </div>
        )}
      </section>

      {p.llm_analysis?.units && p.llm_analysis.units.length > 0 && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Unidades</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {p.llm_analysis.units.map((u) => (
              <li key={u.label}>
                <b>{u.label}</b>: {u.bedrooms ?? "?"} rec. / {u.bathrooms ?? "?"} baños <span className="text-stone-500">— “{u.quote}”</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {history.length > 0 && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Historial de precio (visto por HomeScout)</h2>
          <ul className="mt-2 text-sm">
            {history.map((h) => (
              <li key={h.observed_at}>
                {shortDate(h.observed_at)}: {usd(h.price)} <span className="text-stone-500">{h.status ? STATUS_LABELS[h.status] ?? h.status : ""}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {p.description && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Descripción del anuncio (original en inglés)</h2>
          <p className="mt-2 whitespace-pre-line text-sm text-stone-700">{p.description}</p>
        </section>
      )}
    </div>
  );
}
