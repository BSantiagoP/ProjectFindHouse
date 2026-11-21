// Mirrors the JSON the Python backend stores (app/models/*.py, app/services/scoring.py).

export type FeatureState = "present" | "absent" | "unknown";
export type FeatureSource = "provider" | "description" | "llm" | "photos" | "manual" | null;

export interface Feature {
  state: FeatureState;
  source: FeatureSource;
  evidence: string | null;
}

export type FeatureName =
  | "garage"
  | "driveway"
  | "laundry"
  | "finished_basement"
  | "basement_bathroom"
  | "outdoor_space";

export interface UnitLayout {
  label: string;
  bedrooms: number | null;
  bathrooms: number | null;
  quote: string;
}

export interface Property {
  provider: string;
  external_id: string;
  source_url: string;
  address: { raw: string; street: string | null; city: string | null; zip_code: string | null };
  town: string | null;
  price: number | null;
  property_type: string;
  units: number | null;
  beds: number | null;
  baths: number | null;
  living_area_sqft: number | null;
  year_built: number | null;
  listed_date: string | null;
  description: string | null;
  highlights: string[];
  photo_urls: string[];
  annual_tax: number | null;
  features: Record<FeatureName, Feature>;
  llm_analysis: {
    units: UnitLayout[];
    condition: string;
    condition_quote: string | null;
    red_flags: string[];
    summary: string | null;
  } | null;
  photo_analysis: {
    model: string;
    photos_examined: number[];
    likely: string[];
    condition: string;
    condition_note: string | null;
    skipped_reason: string | null;
  } | null;
  rent_estimate: {
    status: "estimated" | "not_estimated";
    reason: string | null;
    owner_unit: string | null;
    rental_units: {
      label: string;
      bedrooms: number | null;
      bathrooms?: number | null;
      rent: number | null;
      range_low: number | null;
      range_high: number | null;
      comparables?: {
        address: string;
        rent: number | null;
        bedrooms: number | null;
        bathrooms: number | null;
        square_feet: number | null;
        distance_mi: number | null;
        days_old: number | null;
      }[];
    }[];
    monthly_rent_total: number | null;
  } | null;
  drives: { destination: string; address: string; minutes: number | null; miles: number | null }[];
  offer?: {
    status: "ok" | "not_enough_comps" | "error";
    reason: string | null;
    opening: number | null;
    target: number | null;
    walk_away: number | null;
    opening_key: string | null;
    target_key: string | null;
    walk_away_key: string | null;
    win_price?: number | null;
    win_key?: string | null;
    win_reason?: string | null;
    win_monthly_cost?: number | null;
    win_over_budget?: boolean | null;
    candidate_labels: Record<string, string>;
    comps_median: number | null;
    comps_low: number | null;
    comps_high: number | null;
    max_affordable_price: number | null;
    rationale: string[];
    risks: string[];
    comps: {
      address: string;
      price: number;
      beds: number | null;
      baths: number | null;
      distance_mi: number | null;
      days_since_sold: number | null;
      url: string | null;
    }[];
  } | null;
  agent_summary: {
    verdict: "recomendada" | "considerar" | "no_recomendada";
    headline: string;
    reasons_for: string[];
    reasons_against: string[];
    next_steps: string[];
    verdict_adjusted: boolean;
    generated_at: string;
  } | null;
  commute: {
    destination: string;
    town_minutes: number;
    route: string;
    nearest_stop: string | null;
    walk_minutes: number | null;
    total_minutes: number | null;
  } | null;
}

export interface ScenarioResult {
  scenario: string;
  annual_rate?: number | null;
  down_payment: number;
  loan_amount: number;
  monthly_principal_interest: number;
  monthly_mortgage_insurance: number;
  monthly_tax: number;
  monthly_insurance: number;
  monthly_hoa: number;
  monthly_maintenance: number;
  monthly_housing_cost: number;
  net_rental_contribution: number;
  effective_owner_cost: number;
  rent_offset_pct: number | null;
}

export interface Analysis {
  score: number;
  confidence: number;
  categories: { name: string; weight: number; score: number | null; reason: string }[];
  finance: Record<string, ScenarioResult>;
  primary_scenario: string;
  rate: number;
  rate_source: string;
  missing: string[];
  explanation: string[];
}

export type FilterStatus = "eligible" | "needs_verification" | "rejected";

export interface RunResult {
  property_id: string;
  filter_status: FilterStatus;
  rejections: string[];
  unverified: string[];
  is_new: boolean;
  previous_price: number | null;
  analysis: Analysis | null;
  rank: number | null;
  property: Property;
}

export interface SearchRun {
  id: string;
  status: string;
  started_at: string;
  completed_at: string | null;
  requests_used: number;
  errors: string[];
  counts: Record<string, number>;
}

export interface Feedback {
  property_id: string;
  liked: boolean;
  rejected: boolean;
  notes: string | null;
}

export interface TownCommute {
  minutes: number;
  route: string;
  access: string;
}

export interface Preferences {
  towns: string[];
  max_price: number;
  target_monthly_cost: number | null;
  primary_scenario: "fha_3_5" | "conventional_5" | "conventional_20";
  owner_unit: "largest" | "smallest";
  annual_insurance: number;
  rate_override: number | null;
  town_commutes: Record<string, TownCommute>;
  [key: string]: unknown;
}
