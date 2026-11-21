import Link from "next/link";

import { FeedbackButtons } from "@/components/FeedbackButtons";
import { ScoreBadge } from "@/components/Score";
import { usd } from "@/lib/format";
import type { Feedback, RunResult } from "@/lib/types";

export function PropertyCard({ r, feedback }: { r: RunResult; feedback?: Feedback }) {
  const p = r.property;
  const a = r.analysis;
  const primary = a?.finance[a.primary_scenario];
  const rentKnown = p.rent_estimate?.status === "estimated";
  const photo = p.photo_urls[0];
  const verdict = feedback?.rejected ? "rejected" : feedback?.liked ? "liked" : "none";
  return (
    <article className={`overflow-hidden rounded-xl border bg-white shadow-sm ${feedback?.rejected ? "opacity-60" : ""}`}>
      <Link href={`/property/${r.property_id}`} className="block sm:flex">
        {photo && (
          // eslint-disable-next-line @next/next/no-img-element
          <img src={photo} alt="" className="h-40 w-full object-cover sm:h-auto sm:w-56" loading="lazy" />
        )}
        <div className="flex-1 space-y-2 p-4">
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="text-xs uppercase tracking-wide text-stone-500">
                {r.rank ? `#${r.rank} · ` : ""}
                {p.town} · {p.units && p.units > 1 ? `${p.units} unidades` : "Unifamiliar"}
                {r.is_new ? " · Nueva" : ""}
              </p>
              <h2 className="font-semibold">{p.address.street ?? p.address.raw}</h2>
              <p className="text-lg font-semibold">{usd(p.price)}</p>
            </div>
            {a && <ScoreBadge score={a.score} confidence={a.confidence} />}
          </div>
          <dl className="grid grid-cols-2 gap-x-4 gap-y-1 text-sm text-stone-700">
            {primary && (
              <>
                <dt className="text-stone-500">{rentKnown ? "Mensual después de renta" : "Mensual (sin renta est.)"}</dt>
                <dd>{usd(rentKnown ? primary.effective_owner_cost : primary.monthly_housing_cost)}</dd>
              </>
            )}
            {p.commute?.total_minutes != null && (
              <>
                <dt className="text-stone-500">Trayecto a WTC</dt>
                <dd>~{p.commute.total_minutes} min</dd>
              </>
            )}
            {rentKnown && (
              <>
                <dt className="text-stone-500">Ingreso por renta</dt>
                <dd>{usd(p.rent_estimate!.monthly_rent_total)}/mes</dd>
              </>
            )}
          </dl>
          {r.unverified.length > 0 && (
            <p className="text-xs text-amber-700">Por verificar: {r.unverified.join(", ")}</p>
          )}
        </div>
      </Link>
      {r.property_id && (
        <div className="border-t border-stone-100 px-4 py-2">
          <FeedbackButtons propertyId={r.property_id} initial={verdict} />
        </div>
      )}
    </article>
  );
}
