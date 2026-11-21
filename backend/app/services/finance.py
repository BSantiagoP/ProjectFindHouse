"""Deterministic financial model. No LLM involvement.

Three default scenarios: FHA 3.5% down, conventional 5% down, conventional 20% down.
Mortgage-insurance rates are configurable estimates, not quotes.
"""

from dataclasses import dataclass

from app.models.preferences import FinanceScenarioName


@dataclass(frozen=True)
class LoanScenario:
    name: FinanceScenarioName
    down_payment_pct: float
    annual_mortgage_insurance_pct: float  # FHA MIP or conventional PMI, as % of loan per year
    upfront_fee_pct: float = 0.0  # FHA upfront MIP, financed into the loan


DEFAULT_SCENARIOS: tuple[LoanScenario, ...] = (
    LoanScenario(FinanceScenarioName.FHA_3_5, 0.035, 0.0055, upfront_fee_pct=0.0175),
    LoanScenario(FinanceScenarioName.CONVENTIONAL_5, 0.05, 0.0050),
    LoanScenario(FinanceScenarioName.CONVENTIONAL_20, 0.20, 0.0),
)


@dataclass(frozen=True)
class CostInputs:
    price: int
    annual_rate: float  # e.g. 0.0675
    term_years: int = 30
    annual_tax: float = 0.0
    annual_insurance: float = 0.0
    monthly_hoa: float = 0.0
    annual_maintenance_pct: float = 0.01  # of price
    monthly_gross_rent: float = 0.0  # from rented units only
    vacancy_pct: float = 0.05
    rental_opex_pct: float = 0.10  # repairs/management on rental income
    rental_reserve_pct: float = 0.05


@dataclass(frozen=True)
class ScenarioResult:
    scenario: FinanceScenarioName
    down_payment: float
    loan_amount: float
    monthly_principal_interest: float
    monthly_mortgage_insurance: float
    monthly_tax: float
    monthly_insurance: float
    monthly_hoa: float
    monthly_maintenance: float
    monthly_housing_cost: float
    net_rental_contribution: float
    effective_owner_cost: float
    rent_offset_pct: float | None


def monthly_payment(principal: float, annual_rate: float, term_years: int) -> float:
    n = term_years * 12
    if principal <= 0:
        return 0.0
    if annual_rate == 0:
        return principal / n
    r = annual_rate / 12
    return principal * r * (1 + r) ** n / ((1 + r) ** n - 1)


def net_rental_contribution(inputs: CostInputs) -> float:
    gross = inputs.monthly_gross_rent
    return gross * (1 - inputs.vacancy_pct - inputs.rental_opex_pct - inputs.rental_reserve_pct)


# FHA annual MIP for 30-year loans (HUD Mortgagee Letter 2023-05): the rate depends on the base
# loan amount and loan-to-value. All HomeScout FHA scenarios are 3.5% down (LTV 96.5%).
FHA_HIGH_BALANCE = 726_200


def annual_mi_rate(scenario: LoanScenario, base_loan: float, price: float) -> float:
    if scenario.name is not FinanceScenarioName.FHA_3_5:
        return scenario.annual_mortgage_insurance_pct
    ltv = base_loan / price if price else 1.0
    if base_loan > FHA_HIGH_BALANCE:
        return 0.0075 if ltv > 0.95 else 0.0070
    return 0.0055 if ltv > 0.95 else 0.0050


def evaluate_scenario(inputs: CostInputs, scenario: LoanScenario) -> ScenarioResult:
    down = inputs.price * scenario.down_payment_pct
    base_loan = inputs.price - down
    loan = base_loan * (1 + scenario.upfront_fee_pct)
    pi = monthly_payment(loan, inputs.annual_rate, inputs.term_years)
    mi = base_loan * annual_mi_rate(scenario, base_loan, inputs.price) / 12
    tax = inputs.annual_tax / 12
    ins = inputs.annual_insurance / 12
    maint = inputs.price * inputs.annual_maintenance_pct / 12
    housing = pi + mi + tax + ins + inputs.monthly_hoa + maint
    net_rent = net_rental_contribution(inputs)
    return ScenarioResult(
        scenario=scenario.name,
        down_payment=round(down, 2),
        loan_amount=round(loan, 2),
        monthly_principal_interest=round(pi, 2),
        monthly_mortgage_insurance=round(mi, 2),
        monthly_tax=round(tax, 2),
        monthly_insurance=round(ins, 2),
        monthly_hoa=round(inputs.monthly_hoa, 2),
        monthly_maintenance=round(maint, 2),
        monthly_housing_cost=round(housing, 2),
        net_rental_contribution=round(net_rent, 2),
        effective_owner_cost=round(housing - net_rent, 2),
        rent_offset_pct=round(net_rent / housing, 4) if housing > 0 else None,
    )


def evaluate_all(
    inputs: CostInputs, scenarios: tuple[LoanScenario, ...] = DEFAULT_SCENARIOS
) -> dict[FinanceScenarioName, ScenarioResult]:
    return {s.name: evaluate_scenario(inputs, s) for s in scenarios}
