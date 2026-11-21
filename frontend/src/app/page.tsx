import { PropertyCard } from "@/components/PropertyCard";
import { getFeedbackMap, getLatestRun } from "@/lib/data";
import { shortDate } from "@/lib/format";

export const dynamic = "force-dynamic";

export default async function Home() {
  const [latest, feedback] = await Promise.all([getLatestRun(), getFeedbackMap()]);
  if (!latest) return <p className="text-stone-600">No searches yet. The first one runs on the next scheduled day.</p>;
  const { run, results } = latest;
  const ranked = results.filter((r) => r.rank).sort((a, b) => a.rank! - b.rank!);
  const otherEligible = results
    .filter((r) => r.filter_status === "eligible" && !r.rank)
    .sort((a, b) => (b.analysis?.score ?? 0) - (a.analysis?.score ?? 0));

  return (
    <div className="space-y-8">
      <section>
        <h1 className="text-2xl font-semibold tracking-tight">Top matches</h1>
        <p className="mt-1 text-sm text-stone-600">
          Search of {shortDate(run.started_at)} · {run.counts.eligible ?? 0} eligible · {run.counts.needs_verification ?? 0} to verify
          {run.errors.length > 0 && <span className="text-amber-700"> · {run.errors.length} issue(s) in this run</span>}
        </p>
        <div className="mt-4 space-y-4">
          {ranked.length ? (
            ranked.map((r) => <PropertyCard key={r.property_id} r={r} feedback={feedback[r.property_id]} />)
          ) : (
            <p className="text-stone-600">No ranked matches in this search.</p>
          )}
        </div>
      </section>
      {otherEligible.length > 0 && (
        <section>
          <h2 className="text-lg font-semibold">Other eligible homes</h2>
          <div className="mt-3 space-y-4">
            {otherEligible.map((r) => <PropertyCard key={r.property_id} r={r} feedback={feedback[r.property_id]} />)}
          </div>
        </section>
      )}
    </div>
  );
}
