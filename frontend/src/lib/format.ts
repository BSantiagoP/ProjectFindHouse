export const usd = (n: number | null | undefined) =>
  n == null ? "—" : n.toLocaleString("es-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });

export const pct = (n: number | null | undefined) => (n == null ? "—" : `${Math.round(n * 100)}%`);

export const CATEGORY_LABELS: Record<string, string> = {
  affordability: "Asequibilidad",
  location_commute: "Ubicación y trayecto",
  condition: "Estado",
  rental_potential: "Potencial de renta",
  preferences: "Preferencias",
};

export const humanize = (s: string) =>
  CATEGORY_LABELS[s] ?? s.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());

export const SCENARIO_LABELS: Record<string, string> = {
  fha_3_5: "FHA 3.5% de enganche",
  conventional_5: "Convencional 5% de enganche",
  conventional_20: "Convencional 20% de enganche",
};

export const FEATURE_LABELS: Record<string, string> = {
  garage: "Garaje",
  driveway: "Entrada para autos",
  laundry: "Lavandería",
  finished_basement: "Sótano terminado",
  basement_bathroom: "Baño en el sótano",
  outdoor_space: "Patio / espacio exterior",
};

export const SOURCE_LABELS: Record<string, string> = {
  provider: "Datos MLS",
  description: "Texto del anuncio",
  llm: "Texto del anuncio (IA, citado)",
  photos: "Fotos (IA)",
  manual: "Verificado por ti",
};

export const shortDate = (iso: string | null) =>
  iso ? new Date(iso).toLocaleDateString("es-US", { month: "short", day: "numeric", timeZone: "America/New_York" }) : "—";

export const STATUS_LABELS: Record<string, string> = {
  FOR_SALE: "En venta",
  PENDING: "Pendiente",
  SOLD: "Vendida",
};
