"use client";

import { useOptimistic, useTransition } from "react";

import { setFeedback } from "@/app/actions";

type Verdict = "liked" | "rejected" | "none";

export function FeedbackButtons({ propertyId, initial }: { propertyId: string; initial: Verdict }) {
  const [verdict, setOptimistic] = useOptimistic<Verdict, Verdict>(initial, (_, v) => v);
  const [pending, start] = useTransition();

  const choose = (v: Verdict) =>
    start(async () => {
      const next = verdict === v ? "none" : v;
      setOptimistic(next);
      await setFeedback(propertyId, next);
    });

  const base = "rounded-md border px-3 py-1.5 text-sm font-medium transition disabled:opacity-60";
  return (
    <div className="flex gap-2" aria-busy={pending}>
      <button
        onClick={() => choose("liked")}
        disabled={pending}
        aria-pressed={verdict === "liked"}
        className={`${base} ${verdict === "liked" ? "border-emerald-600 bg-emerald-600 text-white" : "border-stone-300 bg-white hover:border-emerald-600"}`}
      >
        {verdict === "liked" ? "Liked" : "Like"}
      </button>
      <button
        onClick={() => choose("rejected")}
        disabled={pending}
        aria-pressed={verdict === "rejected"}
        title="Rejected homes are never texted again"
        className={`${base} ${verdict === "rejected" ? "border-red-700 bg-red-700 text-white" : "border-stone-300 bg-white hover:border-red-700"}`}
      >
        {verdict === "rejected" ? "Rejected" : "Reject"}
      </button>
    </div>
  );
}
