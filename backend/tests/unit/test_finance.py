"""Expected values are hand-checked: $100,000 at 6% for 30 years = $599.55/month."""

import pytest

from app.models.preferences import FinanceScenarioName as S
from app.services.finance import CostInputs, evaluate_all, monthly_payment


def test_reference_payment():
    assert monthly_payment(100_000, 0.06, 30) == pytest.approx(599.55, abs=0.01)


def test_zero_rate():
    assert monthly_payment(360_000, 0.0, 30) == pytest.approx(1000.0)


def test_three_scenarios_side_by_side():
    r = evaluate_all(CostInputs(price=500_000, annual_rate=0.06, annual_maintenance_pct=0))

    conv20 = r[S.CONVENTIONAL_20]
    assert conv20.down_payment == 100_000
    assert conv20.loan_amount == 400_000
    assert conv20.monthly_principal_interest == pytest.approx(2398.20, abs=0.01)
    assert conv20.monthly_mortgage_insurance == 0

    conv5 = r[S.CONVENTIONAL_5]
    assert conv5.loan_amount == 475_000
    assert conv5.monthly_principal_interest == pytest.approx(2847.86, abs=0.01)
    assert conv5.monthly_mortgage_insurance == pytest.approx(197.92, abs=0.01)  # 0.5%/yr

    fha = r[S.FHA_3_5]
    assert fha.down_payment == 17_500
    assert fha.loan_amount == pytest.approx(490_943.75)  # 482,500 + 1.75% upfront MIP
    assert fha.monthly_principal_interest == pytest.approx(2943.46, abs=0.01)
    assert fha.monthly_mortgage_insurance == pytest.approx(221.15, abs=0.01)  # 0.55% of 482,500


def test_housing_cost_and_rent_offset():
    inputs = CostInputs(
        price=500_000,
        annual_rate=0.06,
        annual_tax=12_000,
        annual_insurance=2_400,
        annual_maintenance_pct=0.01,
        monthly_gross_rent=2_500,
    )
    r = evaluate_all(inputs)[S.CONVENTIONAL_20]
    # 2398.20 P&I + 1000 tax + 200 ins + 416.67 maintenance
    assert r.monthly_housing_cost == pytest.approx(4014.87, abs=0.01)
    # 2500 * (1 - 0.05 vacancy - 0.10 opex - 0.05 reserves)
    assert r.net_rental_contribution == pytest.approx(2000.0)
    assert r.effective_owner_cost == pytest.approx(2014.87, abs=0.01)
    assert r.rent_offset_pct == pytest.approx(2000 / 4014.87, abs=1e-4)
