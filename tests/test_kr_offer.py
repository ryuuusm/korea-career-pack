"""Tests for kr_offer.py: tax-engine parity, comp normalisation, validation, CLI."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "pack" / "scripts"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import kr_offer  # noqa: E402
import reference_salary  # noqa: E402  (vendored from wing0828/ai-job-search-kr, MIT)

EXAMPLE = ROOT / "pack" / "templates" / "offers.example.json"


@pytest.mark.parametrize("annual,nontax,deps", [
    (30_000_000, 200_000, 1), (52_000_000, 200_000, 2), (72_000_000, 200_000, 1),
    (95_000_000, 0, 3), (150_000_000, 200_000, 1), (400_000_000, 200_000, 1),
])
def test_tax_engine_parity_with_reference(annual, nontax, deps):
    """Same inputs -> same deductions as the original, within the 10-won truncation fix."""
    ours = kr_offer.monthly_net(annual, nontax, deps)
    ref = reference_salary.monthly(reference_salary.Offer("x", annual, False, nontax, deps, 0))
    for key in ("국민연금", "건강보험", "장기요양", "고용보험", "소득세", "지방소득세"):
        assert abs(ours[key] - ref[key]) <= 10, key


def test_floor10_float_drift_fixed():
    # 5,800,000 * 0.9% must be 52,200 (the original yields 52,190).
    assert kr_offer._floor10(5_800_000 * 0.009) == 52_200
    assert kr_offer._floor10(1234.5) == 1230


def test_hand_checked_case():
    r = kr_offer.monthly_net(72_000_000, 200_000, 1)
    # taxable 5,800,000: pension 4.75% -> 275,500; health 3.595% -> 208,510;
    # LTC 13.14% of health -> 27,398 -> 27,390; employment 0.9% -> 52,200
    assert (r["국민연금"], r["건강보험"], r["장기요양"], r["고용보험"]) == (275_500, 208_510, 27_390, 52_200)


def test_pension_cap_applies():
    r = kr_offer.monthly_net(200_000_000, 200_000, 1)
    assert r["국민연금"] == kr_offer._floor10(6_590_000 * 0.0475)


def offer(**kw):
    base = {"label": "X", "base_annual_krw": 78_000_000}
    base.update(kw)
    return kr_offer.parse_offer(base, 0)


def test_severance_included_normalised():
    o = offer(base_annual_krw=78_000_000, severance_included=True)
    assert o.salary == pytest.approx(72_000_000)
    rows = kr_offer.evaluate(o, 1)["rows"]
    assert rows["퇴직금 상당액(연, 추정)"] == pytest.approx(6_000_000)


def test_totals_with_rsu_signon_bonus_probation():
    o = offer(base_annual_krw=80_000_000, bonus={"target_pct": 10},
              sign_on_krw=5_000_000, probation={"months": 3, "pay_pct": 90},
              rsu={"grant_value": 40_000, "currency": "USD", "fx_rate": 1400, "fx_date": "2026-10-22",
                   "vest_years": 4, "cliff_months": 12})
    rows = kr_offer.evaluate(o, 1)["rows"]
    prob_loss = 80_000_000 / 12 * 3 * 0.1                     # 2,000,000
    sev = 80_000_000 / 12
    assert rows["RSU 연환산"] == pytest.approx(14_000_000)
    assert rows["1년차 보장 총보상"] == pytest.approx(80_000_000 - prob_loss + sev + 5_000_000)
    assert rows["1년차 기대 총보상"] == pytest.approx(80_000_000 - prob_loss + sev + 5_000_000 + 8_000_000 + 14_000_000)
    assert rows["2년차~ 기대 총보상"] == pytest.approx(80_000_000 + sev + 8_000_000 + 14_000_000)


def test_guaranteed_bonus_counts_as_guaranteed():
    o = offer(bonus={"target_krw": 6_000_000, "guaranteed": True})
    rows = kr_offer.evaluate(o, 1)["rows"]
    assert rows["1년차 보장 총보상"] == pytest.approx(78_000_000 + 78_000_000 / 12 + 6_000_000)


def test_long_cliff_excluded_from_year1():
    o = offer(rsu={"grant_value": 100_000_000, "vest_years": 4, "cliff_months": 18})
    rows = kr_offer.evaluate(o, 1)["rows"]
    assert rows["1년차 기대 총보상"] == pytest.approx(78_000_000 + 78_000_000 / 12)
    assert any("cliff 18" in f for f in kr_offer.evaluate(o, 1)["flags"])


def test_fixed_ot_flag():
    o = offer(fixed_ot={"hours_per_month": 10}, expected_ot_hours_per_week=5)
    flags = kr_offer.evaluate(o, 1)["flags"]
    assert any("초과분은 별도 지급" in f for f in flags)


@pytest.mark.parametrize("bad", [
    {"label": "", "base_annual_krw": 1},
    {"label": "X"},
    {"label": "X", "base_annual_krw": -5},
    {"label": "X", "base_annual_krw": True},
    {"label": "X", "base_annual_krw": float("nan")},
    {"label": "X", "base_annual_krw": 1, "bonus": {"target_krw": 1, "target_pct": 1}},
    {"label": "X", "base_annual_krw": 1, "rsu": {"grant_value": 1, "currency": "USD", "vest_years": 4}},
    {"label": "X", "base_annual_krw": 1, "rsu": {"grant_value": 1, "currency": "XYZ", "vest_years": 4}},
    {"label": "X", "base_annual_krw": 1, "probation": {"months": 3, "pay_pct": 150}},
    {"label": "X", "base_annual_krw": 1, "severance_included": "yes"},
])
def test_invalid_offers_rejected(bad):
    with pytest.raises(kr_offer.InputError):
        kr_offer.parse_offer(bad, 0)


def test_example_file_runs(capsys):
    assert kr_offer.main([str(EXAMPLE)]) == 0
    out = capsys.readouterr().out
    assert "외국계 B사" in out and "월실수령 차이" in out


def test_json_output(capsys):
    assert kr_offer.main([str(EXAMPLE), "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert len(data["results"]) == 3 and data["rates_verified_on"]


def test_cli_errors(tmp_path):
    p = tmp_path / "o.json"
    p.write_text('{"offers": []}', encoding="utf-8")
    assert kr_offer.main([str(p)]) == 2
    p.write_text('{"offers": [{"label": "A", "base_annual_krw": 1}, {"label": "A", "base_annual_krw": 2}]}',
                 encoding="utf-8")
    assert kr_offer.main([str(p)]) == 2   # duplicate label
    p.write_text("not json", encoding="utf-8")
    assert kr_offer.main([str(p)]) == 2
    assert kr_offer.main([str(tmp_path / "missing.json")]) == 2
