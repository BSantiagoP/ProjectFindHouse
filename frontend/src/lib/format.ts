export const usd = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const pct = (n: number | null | undefined) => (n == null ? "—" : `${Math.round(n * 100)}%`);

export const humanize = (s: string) => s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const SCENARIO_LABELS: Record<string, string> = {
  fha_3_5: "FHA 3.5% down",
  conventional_5: "Conventional 5% down",
  conventional_20: "Conventional 20% down",
};

export const FEATURE_LABELS: Record<string, string> = {
  garage: "Garage",
  driveway: "Driveway",
  laundry: "Laundry",
  finished_basement: "Finished basement",
  basement_bathroom: "Basement bathroom",
  outdoor_space: "Yard / outdoor space",
};

export const SOURCE_LABELS: Record<string, string> = {
  provider: "MLS data",
  description: "Listing text",
  llm: "Listing text (AI, quoted)",
  photos: "Photos (AI)",
  manual: "Verified by you",
};

export const shortDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", timeZone: "America/New_York" }) : "—";
