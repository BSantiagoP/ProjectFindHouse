export function ScoreBadge({ score, confidence }: { score: number; confidence: number }) {
  const tone = score >= 60 ? "bg-emerald-600" : score >= 40 ? "bg-amber-500" : "bg-stone-400";
  return (
    <div className="flex items-center gap-2">
      <span className={`rounded-md px-2 py-1 text-sm font-semibold text-white ${tone}`}>{Math.round(score)}</span>
      <span className="text-xs text-stone-500">{Math.round(confidence * 100)}% data</span>
    </div>
  );
}

export function CategoryBar({ name, weight, score, reason }: { name: string; weight: number; score: number | null; reason: string }) {
  return (
    <div className="space-y-1">
      <div className="flex justify-between text-sm">
        <span className="font-medium">
          {name} <span className="font-normal text-stone-500">({weight}%)</span>
        </span>
        <span className={score == null ? "text-stone-400" : ""}>{score == null ? "not scored" : `${score.toFixed(1)}/10`}</span>
      </div>
      <div className="h-2 rounded-full bg-stone-200">
        <div className="h-2 rounded-full bg-stone-800" style={{ width: `${((score ?? 0) / 10) * 100}%` }} />
      </div>
      <p className="text-xs text-stone-600">{reason}</p>
    </div>
  );
}
