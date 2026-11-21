import Link from "next/link";
import { notFound } from "next/navigation";

import { FeedbackButtons } from "@/components/FeedbackButtons";
import { CategoryBar, ScoreBadge } from "@/components/Score";
import { getFeedbackMap, getLatestRun, getPriceHistory } from "@/lib/data";
import { FEATURE_LABELS, SCENARIO_LABELS, SOURCE_LABELS, humanize, pct, shortDate, usd } from "@/lib/format";
import type { FeatureName } from "@/lib/types";

export const dynamic = "force-dynamic";

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
      <Link href="/" className="text-sm text-stone-500 hover:text-stone-900">← All matches</Link>

      <header className="flex flex-wrap items-start justify-between gap-4">
        <div>
          <p className="text-xs uppercase tracking-wide text-stone-500">
            {r.rank ? `#${r.rank} · ` : ""}{p.town} · {p.units && p.units > 1 ? `${p.units}-family` : "Single-family"} · listed {shortDate(p.listed_date)}
          </p>
          <h1 className="text-2xl font-semibold tracking-tight">{p.address.raw}</h1>
          <p className="text-xl font-semibold">{usd(p.price)}</p>
          <p className="mt-1 text-sm text-stone-600">
            {[p.beds && `${p.beds} bd`, p.baths && `${p.baths} ba`, p.living_area_sqft && `${p.living_area_sqft.toLocaleString()} sqft`, p.year_built && `built ${p.year_built}`]
              .filter(Boolean)
              .join(" · ")}
          </p>
          <a href={p.source_url} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block text-sm text-blue-700 underline">
            View listing on Zillow
          </a>
        </div>
        <div className="flex flex-col items-end gap-3">
          {a && <ScoreBadge score={a.score} confidence={a.confidence} />}
          <FeedbackButtons propertyId={id} initial={verdict} />
        </div>
      </header>

      {r.filter_status !== "eligible" && (
        <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900">
          {r.filter_status === "rejected" ? "Rejected: " + r.rejections.join("; ") : "Needs verification: " + r.unverified.join(", ")}
        </div>
      )}

      {p.photo_urls.length > 0 && (
        <section className="-mx-4 flex snap-x gap-2 overflow-x-auto px-4 pb-2">
          {p.photo_urls.slice(0, 40).map((url, i) => (
            <figure key={url} className="relative shrink-0 snap-start">
              {/* eslint-disable-next-line @next/next/no-img-element */}
              <img src={url} alt={`Photo ${i + 1}`} loading="lazy" className="h-44 w-64 rounded-lg object-cover" />
              <figcaption className="absolute left-1 top-1 rounded bg-black/60 px-1.5 text-xs text-white">{i + 1}</figcaption>
            </figure>
          ))}
        </section>
      )}

      {a && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Why this score</h2>
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
          <h2 className="font-semibold">Financing</h2>
          <p className="text-xs text-stone-500">
            Rate {(a!.rate * 100).toFixed(2)}% ({a!.rate_source}); FHA adjusted. Estimates, not quotes.
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
                {([
                  ["Down payment", "down_payment"],
                  ["Principal & interest", "monthly_principal_interest"],
                  ["Mortgage insurance", "monthly_mortgage_insurance"],
                  ["Property tax", "monthly_tax"],
                  ["Insurance", "monthly_insurance"],
                  ["Maintenance", "monthly_maintenance"],
                  ["Monthly housing cost", "monthly_housing_cost"],
                  ["Net rent (after vacancy/costs)", "net_rental_contribution"],
                  ["You pay per month", "effective_owner_cost"],
                ] as const).map(([label, key]) => (
                  <tr key={key} className={key === "effective_owner_cost" ? "font-semibold" : ""}>
                    <td className="py-1.5 text-stone-600">{label}</td>
                    {scenarios.map((s) => <td key={s.scenario} className="py-1.5">{usd(s[key])}</td>)}
                  </tr>
                ))}
                <tr>
                  <td className="py-1.5 text-stone-600">Rent covers</td>
                  {scenarios.map((s) => <td key={s.scenario} className="py-1.5">{pct(s.rent_offset_pct)}</td>)}
                </tr>
              </tbody>
            </table>
          </div>
        </section>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Rent</h2>
          {p.rent_estimate?.status === "estimated" ? (
            <ul className="mt-2 space-y-1 text-sm">
              <li className="text-stone-600">You live in: {p.rent_estimate.owner_unit}</li>
              {p.rent_estimate.rental_units.map((u) => (
                <li key={u.label}>
                  {u.label} ({u.bedrooms} bd): <b>{usd(u.rent)}</b>/mo
                  <span className="text-stone-500"> (range {usd(u.range_low)}–{usd(u.range_high)})</span>
                </li>
              ))}
              <li className="pt-1 text-xs text-stone-500">RentCast estimate for the rental unit(s) only.</li>
            </ul>
          ) : (
            <p className="mt-2 text-sm text-stone-600">{p.rent_estimate?.reason ?? "Not estimated"}</p>
          )}
        </section>
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Commute</h2>
          {p.commute?.total_minutes != null ? (
            <ul className="mt-2 space-y-1 text-sm">
              <li>
                <b>~{p.commute.total_minutes} min</b> to {p.commute.destination}
              </li>
              <li className="text-stone-600">{p.commute.walk_minutes} min walk to {p.commute.nearest_stop}</li>
              <li className="text-stone-600">then {p.commute.route} (~{p.commute.town_minutes} min)</li>
              <li className="pt-1 text-xs text-stone-500">Town estimate + NJ Transit stop data; not door-to-door routing.</li>
            </ul>
          ) : (
            <p className="mt-2 text-sm text-stone-600">Not estimated</p>
          )}
        </section>
      </div>

      <section className="rounded-xl border bg-white p-4 shadow-sm">
        <h2 className="font-semibold">Features & evidence</h2>
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
            <p className="font-medium">Likely from photos — check in person:</p>
            <ul className="mt-1 list-disc pl-5">
              {p.photo_analysis.likely.map((l) => <li key={l}>{l}</li>)}
            </ul>
          </div>
        )}
        {p.llm_analysis?.red_flags && p.llm_analysis.red_flags.length > 0 && (
          <div className="mt-3 rounded-md bg-red-50 p-3 text-sm text-red-900">
            <p className="font-medium">Red flags from the listing:</p>
            <ul className="mt-1 list-disc pl-5">
              {p.llm_analysis.red_flags.map((q) => <li key={q}>“{q}”</li>)}
            </ul>
          </div>
        )}
      </section>

      {p.llm_analysis?.units && p.llm_analysis.units.length > 0 && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Units</h2>
          <ul className="mt-2 space-y-1 text-sm">
            {p.llm_analysis.units.map((u) => (
              <li key={u.label}>
                <b>{u.label}</b>: {u.bedrooms ?? "?"} bd / {u.bathrooms ?? "?"} ba <span className="text-stone-500">— “{u.quote}”</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {history.length > 0 && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Price history (seen by HomeScout)</h2>
          <ul className="mt-2 text-sm">
            {history.map((h) => (
              <li key={h.observed_at}>
                {shortDate(h.observed_at)}: {usd(h.price)} <span className="text-stone-500">{h.status}</span>
              </li>
            ))}
          </ul>
        </section>
      )}

      {p.description && (
        <section className="rounded-xl border bg-white p-4 shadow-sm">
          <h2 className="font-semibold">Listing description</h2>
          <p className="mt-2 whitespace-pre-line text-sm text-stone-700">{p.description}</p>
        </section>
      )}
    </div>
  );
}
