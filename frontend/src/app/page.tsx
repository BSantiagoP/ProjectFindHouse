import { PropertyCard } from "@/components/PropertyCard";
import { getFeedbackMap, getLatestRun } from "@/lib/data";
import { shortDate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [latest, feedback] = await Promise.all([getLatestRun(), getFeedbackMap()]);
  if (!latest) return <p className="text-stone-600">Aún no hay búsquedas. La primera se ejecuta el próximo día programado.</p>;
  const { run, results } = latest;
  const isDiscarded = (r: (typeof results)[number]) => feedback[r.property_id]?.rejected === true;
  // Discarded homes leave the lists right away; the top 5 refills with the next best eligible home.
  const eligible = results
    .filter((r) => r.filter_status === "eligible" && r.analysis && !isDiscarded(r))
    .sort((a, b) => b.analysis!.score - a.analysis!.score || (a.rank ?? 99) - (b.rank ?? 99));
  const ranked = eligible.slice(0, 5).map((r, i) => ({ ...r, rank: i + 1 }));
  const otherEligible = eligible.slice(5).map((r) => ({ ...r, rank: null }));
  const discarded = results.filter(isDiscarded);

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">Mejores opciones</h1>
        <p className="mt-1 text-sm text-stone-600">
          Búsqueda del {shortDate(run.started_at)} · {run.counts.eligible ?? 0} elegibles · {run.counts.needs_verification ?? 0} por verificar
          {run.errors.length > 0 && <span className="text-amber-700"> · {run.errors.length} problema(s) en esta búsqueda</span>}
        </p>
        <div className="mt-4 space-y-4">
          {ranked.length ? (
            ranked.map((r) => <PropertyCard key={r.property_id} r={r} feedback={feedback[r.property_id]} />)
          ) : (
            <p className="text-stone-600">No hay opciones clasificadas en esta búsqueda.</p>
          )}
        </div>
      </section>
      {otherEligible.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold">Otras casas elegibles</h2>
          <div className="mt-3 space-y-4">
            {otherEligible.map((r) => <PropertyCard key={r.property_id} r={r} feedback={feedback[r.property_id]} />)}
          </div>
        </section>
      )}
      {discarded.length > 0 && (
        <details className="rounded-lg border border-stone-200 bg-white p-3">
          <summary className="cursor-pointer text-sm text-stone-600">Ver descartadas ({discarded.length})</summary>
          <p className="mt-2 text-xs text-stone-500">Toca &quot;Descartada&quot; para restaurar una casa.</p>
          <div className="mt-3 space-y-4">
            {discarded.map((r) => <PropertyCard key={r.property_id} r={{ ...r, rank: null }} feedback={feedback[r.property_id]} />)}
          </div>
        </details>
      )}
    </div>
  );
}
