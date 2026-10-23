#!/usr/bin/env python3
"""한국 오퍼 비교 계산기: 총보상 정규화 + 월 실수령액 추정 (표준 라이브러리만, 네트워크 없음).

사용법:
    python scripts/kr_offer.py offers.json            # Markdown 표
    python scripts/kr_offer.py offers.json --json     # 기계 판독용

입력 형식은 templates/offers.example.json 참고. 금액은 모두 원(KRW) 단위 정수.

무엇을 계산하나
- 퇴직금 포함 연봉을 퇴직금 제외 금액(× 12/13)으로 맞춰 '같은 기준'으로 비교한다.
- 퇴직금 상당액(연) ≈ 퇴직금 제외 연봉 / 12 (계속근로 1년에 30일분 평균임금, 근로자퇴직급여 보장법 제8조).
  평균임금은 최근 3개월 임금 기준이라 실제 금액은 다를 수 있다.
- 1년차 보장 총보상 / 1년차 기대 총보상 / 2년차 이후 기대 총보상을 나눠 보여준다.
  성과급은 guaranteed=true일 때만 '보장'에 넣는다. 사이닝은 1년차에만 넣는다.
  RSU는 grant 가치 × 환율 / 베스팅 연수로 연환산하고, cliff가 12개월을 넘으면 1년차에서 뺀다.
  주가 변동, 세금(RSU·성과급·사이닝)은 반영하지 않는다.
- 월 실수령액은 기본 연봉(퇴직금 제외)만으로 추정한다. 4대보험·소득세 계산 로직은
  wing0828/ai-job-search-kr의 salary.py(MIT)를 옮겨 왔고, 요율은 아래 RATES에 출처와 함께 적었다.
  국세청 간이세액표와 월 수천~수만 원 차이가 날 수 있는 추정치다.

종료 코드: 0 성공, 2 입력 오류.
"""
import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional

# --------------------------------------------------------------------------- rates
# Every figure below was checked against the cited source on RATES_VERIFIED_ON.
# Update all of them together, every January and July.
RATES_VERIFIED_ON = "2026-10-23"
RATES = {
    # NPS: 9.5% total from 2026-01 (employee half 4.75%); 기준소득월액 410,000~6,590,000 won
    # for 2026-07 ~ 2027-06. Source: 세계일보 2026-01-11 (NPS announcement coverage).
    "pension": 0.0475, "pension_min": 410_000, "pension_max": 6_590_000,
    # NHIS 2026: health 7.19% (employee 3.595%), long-term care 0.9448% of income
    # = 13.14% of the health premium. Source: nhis.or.kr "2026년 달라지는 건강·장기요양제도".
    "health": 0.03595, "ltc_of_health": 0.1314,
    # Employment insurance, employee share 0.9% (unchanged in 2026).
    "employment": 0.009,
}
# 소득세법 제55조 tax table (unchanged since 2023): (upper bound, rate, progressive deduction).
TAX_BRACKETS = [
    (14_000_000, 0.06, 0), (50_000_000, 0.15, 1_260_000), (88_000_000, 0.24, 5_760_000),
    (150_000_000, 0.35, 15_440_000), (300_000_000, 0.38, 19_940_000),
    (500_000_000, 0.40, 25_940_000), (1_000_000_000, 0.42, 35_940_000),
    (math.inf, 0.45, 65_940_000),
]
PERSONAL_DEDUCTION = 1_500_000        # 기본공제 per person (소득세법 제50조)
DEFAULT_NONTAX_MONTHLY = 200_000      # 식대 비과세 한도 월 20만원
WEEKS_PER_YEAR = 365 / 7              # 52.14
WEEKS_PER_MONTH = WEEKS_PER_YEAR / 12  # 4.345

MAX_OFFERS = 10
MAX_KRW = 10_000_000_000              # sanity cap: 100억 원
SUPPORTED_CURRENCIES = {"KRW", "USD", "EUR", "JPY", "SGD", "GBP", "CNY", "HKD", "TWD", "AUD", "CAD", "CHF"}


class InputError(Exception):
    """User-facing validation error."""


# ------------------------------------------------------------------ tax engine
# Ported from wing0828/ai-job-search-kr scripts/salary.py (MIT). Behaviour is kept
# identical; tests/test_kr_offer.py checks parity against that file.

def _floor10(x: float) -> int:
    """Truncate below 10 won.

    round(x, 6) first: binary floating point turns 5,800,000 * 0.009 into
    52199.999..., which would otherwise truncate to 52,190 instead of 52,200.
    (This fixes a 10-won drift present in the original salary.py.)
    """
    return int(math.floor(round(x, 6)) // 10 * 10)


def earned_income_deduction(total: float) -> float:
    """근로소득공제 (소득세법 제47조), capped at 20,000,000."""
    if total <= 5_000_000:
        d = total * 0.7
    elif total <= 15_000_000:
        d = 3_500_000 + (total - 5_000_000) * 0.4
    elif total <= 45_000_000:
        d = 7_500_000 + (total - 15_000_000) * 0.15
    elif total <= 100_000_000:
        d = 12_000_000 + (total - 45_000_000) * 0.05
    else:
        d = 14_750_000 + (total - 100_000_000) * 0.02
    return min(d, 20_000_000)


def progressive_tax(base: float) -> float:
    for limit, rate, deduction in TAX_BRACKETS:
        if base <= limit:
            return max(0.0, base * rate - deduction)
    return 0.0  # unreachable: last bracket is +inf


def earned_tax_credit(tax: float, total: float) -> float:
    """근로소득세액공제 (소득세법 제59조) with the salary-dependent cap."""
    credit = tax * 0.55 if tax <= 1_300_000 else 715_000 + (tax - 1_300_000) * 0.30
    if total <= 33_000_000:
        cap = 740_000
    elif total <= 70_000_000:
        cap = max(740_000 - (total - 33_000_000) * 0.008, 660_000)
    elif total <= 120_000_000:
        cap = max(660_000 - (total - 70_000_000) * 0.5, 500_000)
    else:
        cap = max(500_000 - (total - 120_000_000) * 0.5, 200_000)
    return min(credit, cap)


def monthly_net(annual_salary: float, nontax_month: int, dependents: int) -> Dict[str, float]:
    """Estimate one month's deductions and take-home pay for a 'severance-excluded' salary."""
    gross = annual_salary / 12
    taxable = max(0.0, gross - min(nontax_month, gross))
    base = min(max(taxable // 1000 * 1000, RATES["pension_min"]), RATES["pension_max"])
    pension = _floor10(base * RATES["pension"])
    health = _floor10(taxable * RATES["health"])
    ltc = _floor10(health * RATES["ltc_of_health"])
    employment = _floor10(taxable * RATES["employment"])

    total = taxable * 12
    income = total - earned_income_deduction(total)
    tax_base = max(0.0, income - PERSONAL_DEDUCTION * dependents
                   - pension * 12 - (health + ltc + employment) * 12)
    calc = progressive_tax(tax_base)
    determined = max(0.0, calc - earned_tax_credit(calc, total))
    income_tax = _floor10(determined / 12)
    local_tax = _floor10(income_tax * 0.1)
    deductions = pension + health + ltc + employment + income_tax + local_tax
    return {"월세전": gross, "국민연금": pension, "건강보험": health, "장기요양": ltc,
            "고용보험": employment, "소득세": income_tax, "지방소득세": local_tax,
            "공제합계": deductions, "월실수령": gross - deductions}


# ------------------------------------------------------------------ validation

def _num(obj: Dict[str, Any], key: str, where: str, *, default: Optional[float] = None,
         lo: float = 0, hi: float = MAX_KRW, integer: bool = False) -> float:
    """Read a finite number within [lo, hi]; bool is rejected even though it is an int."""
    if key not in obj or obj[key] is None:
        if default is None:
            raise InputError(f"{where}: '{key}' 값이 필요함")
        return default
    val = obj[key]
    if isinstance(val, bool) or not isinstance(val, (int, float)) or not math.isfinite(val):
        raise InputError(f"{where}: '{key}'는 숫자여야 함 (받은 값: {val!r})")
    if not lo <= val <= hi:
        raise InputError(f"{where}: '{key}'는 {lo}~{hi} 범위여야 함 (받은 값: {val})")
    if integer and int(val) != val:
        raise InputError(f"{where}: '{key}'는 정수여야 함")
    return float(val)


def _bool(obj: Dict[str, Any], key: str, where: str, default: bool = False) -> bool:
    val = obj.get(key, default)
    if not isinstance(val, bool):
        raise InputError(f"{where}: '{key}'는 true/false여야 함")
    return val


def _dict(obj: Dict[str, Any], key: str, where: str) -> Dict[str, Any]:
    val = obj.get(key) or {}
    if not isinstance(val, dict):
        raise InputError(f"{where}: '{key}'는 객체여야 함")
    return val


class Offer(NamedTuple):
    label: str
    salary: float               # severance-excluded annual base
    severance_included: bool
    nontax_month: int
    bonus_target: float
    bonus_guaranteed: bool
    sign_on: float
    sign_on_clawback_months: int
    rsu_annual: float
    rsu_cliff_months: int
    rsu_note: str
    probation_months: int
    probation_pay_pct: float
    fixed_ot_hours_month: Optional[float]
    weekly_hours: Optional[float]
    expected_ot_week: float


def parse_offer(raw: Any, idx: int) -> Offer:
    if not isinstance(raw, dict):
        raise InputError(f"offers[{idx}]는 객체여야 함")
    label = raw.get("label")
    if not isinstance(label, str) or not label.strip() or len(label) > 40:
        raise InputError(f"offers[{idx}]: label은 1~40자 문자열")
    where = f"'{label}'"

    base = _num(raw, "base_annual_krw", where, lo=1)
    sev_inc = _bool(raw, "severance_included", where)
    salary = base * 12 / 13 if sev_inc else base
    nontax = int(_num(raw, "nontax_monthly_krw", where, default=DEFAULT_NONTAX_MONTHLY, hi=10_000_000))

    bonus = _dict(raw, "bonus", where)
    if "target_krw" in bonus and "target_pct" in bonus:
        raise InputError(f"{where}: bonus에는 target_krw와 target_pct 중 하나만")
    if "target_pct" in bonus:
        bonus_target = salary * _num(bonus, "target_pct", where, hi=1000) / 100
    else:
        bonus_target = _num(bonus, "target_krw", where, default=0)
    bonus_guaranteed = _bool(bonus, "guaranteed", where)

    sign_on = _num(raw, "sign_on_krw", where, default=0)
    clawback = int(_num(raw, "sign_on_clawback_months", where, default=0, hi=60, integer=True))

    rsu = _dict(raw, "rsu", where)
    rsu_annual, cliff, rsu_note = 0.0, 0, ""
    if rsu:
        grant = _num(rsu, "grant_value", where, lo=0, hi=1e12)
        currency = str(rsu.get("currency", "KRW")).upper()
        if currency not in SUPPORTED_CURRENCIES:
            raise InputError(f"{where}: 지원하지 않는 통화 {currency}")
        if currency == "KRW":
            fx, fx_date = 1.0, ""
        else:
            fx = _num(rsu, "fx_rate", where, lo=0.0001, hi=100_000)
            fx_date = rsu.get("fx_date")
            if not isinstance(fx_date, str) or not fx_date:
                raise InputError(f"{where}: 외화 RSU는 fx_date(환율 기준일)가 필요함")
        years = _num(rsu, "vest_years", where, lo=1, hi=10)
        cliff = int(_num(rsu, "cliff_months", where, default=12, hi=60, integer=True))
        rsu_annual = grant * fx / years
        if rsu_annual > MAX_KRW:
            raise InputError(f"{where}: RSU 연환산이 상한을 넘음. 입력 단위를 확인")
        rsu_note = (f"{currency} {grant:,.0f} × {fx:,.2f}" + (f" ({fx_date} 기준)" if fx_date else "")
                    + f" / {years:g}년")

    prob = _dict(raw, "probation", where)
    prob_months = int(_num(prob, "months", where, default=0, hi=12, integer=True))
    prob_pct = _num(prob, "pay_pct", where, default=100, hi=100)

    fixed_ot = _dict(raw, "fixed_ot", where)
    fixed_ot_hours = _num(fixed_ot, "hours_per_month", where, hi=200) if fixed_ot else None
    weekly = _num(raw, "weekly_hours", where, default=0, hi=80) or None
    expected_ot = _num(raw, "expected_ot_hours_per_week", where, default=0, hi=60)

    return Offer(label.strip(), salary, sev_inc, nontax, bonus_target, bonus_guaranteed, sign_on,
                 clawback, rsu_annual, cliff, rsu_note, prob_months, prob_pct, fixed_ot_hours,
                 weekly, expected_ot)


def load(path: str) -> Dict[str, Any]:
    p = Path(path)
    if not p.is_file():
        raise InputError(f"파일 없음: {path}")
    if p.stat().st_size > 512 * 1024:
        raise InputError("입력 파일이 너무 큼 (512KB 초과)")
    try:
        data = json.loads(p.read_text(encoding="utf-8-sig"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise InputError(f"JSON을 읽을 수 없음: {exc}") from exc
    if not isinstance(data, dict) or not isinstance(data.get("offers"), list) or not data["offers"]:
        raise InputError("최상위에 비어 있지 않은 'offers' 배열이 필요함")
    if len(data["offers"]) > MAX_OFFERS:
        raise InputError(f"오퍼는 최대 {MAX_OFFERS}개")
    return data


# ------------------------------------------------------------------ comparison

def evaluate(offer: Offer, dependents: int) -> Dict[str, Any]:
    """Compute normalised comp rows and human-readable flags for one offer."""
    net = monthly_net(offer.salary, offer.nontax_month, dependents)
    severance = offer.salary / 12
    prob_loss = offer.salary / 12 * offer.probation_months * (1 - offer.probation_pay_pct / 100)
    salary_y1 = offer.salary - prob_loss
    guaranteed_bonus = offer.bonus_target if offer.bonus_guaranteed else 0.0
    rsu_y1 = offer.rsu_annual if offer.rsu_cliff_months <= 12 else 0.0

    rows = {
        "세전 연봉(퇴직금 제외)": offer.salary,
        "퇴직금 상당액(연, 추정)": severance,
        "성과급 목표": offer.bonus_target,
        "사이닝(1년차)": offer.sign_on,
        "RSU 연환산": offer.rsu_annual,
        "1년차 보장 총보상": salary_y1 + severance + offer.sign_on + guaranteed_bonus,
        "1년차 기대 총보상": salary_y1 + severance + offer.sign_on + offer.bonus_target + rsu_y1,
        "2년차~ 기대 총보상": offer.salary + severance + offer.bonus_target + offer.rsu_annual,
        **net,
    }

    flags: List[str] = []
    if offer.severance_included:
        flags.append("퇴직금 포함 연봉 → 12/13으로 환산해 비교함 (같은 숫자의 '별도' 연봉보다 약 7.7% 낮음)")
    if offer.bonus_target and not offer.bonus_guaranteed:
        flags.append("성과급은 비보장 → '보장 총보상'에서 제외. 최근 지급 이력을 확인할 것")
    if offer.sign_on and offer.sign_on_clawback_months:
        flags.append(f"사이닝 반환 조건: {offer.sign_on_clawback_months}개월 내 퇴사 시 반환")
    if offer.rsu_annual:
        flags.append(f"RSU {offer.rsu_note}. 주가·환율 변동과 세금 미반영")
        if offer.rsu_cliff_months > 12:
            flags.append(f"RSU cliff {offer.rsu_cliff_months}개월 → 1년차 기대 총보상에서 제외")
    if offer.probation_months and offer.probation_pay_pct < 100:
        flags.append(f"수습 {offer.probation_months}개월 {offer.probation_pay_pct:g}% 지급 → 1년차 연봉 {prob_loss:,.0f}원 감소")
    if offer.fixed_ot_hours_month is not None:
        expected_month = offer.expected_ot_week * WEEKS_PER_MONTH
        if expected_month > offer.fixed_ot_hours_month:
            flags.append(f"예상 연장근로 월 {expected_month:.0f}시간 > 고정OT {offer.fixed_ot_hours_month:g}시간 "
                         "→ 초과분은 별도 지급 대상 (고용노동부 포괄임금 오남용 방지 지도지침, 2026-04-09 시행)")
        else:
            flags.append(f"고정OT 월 {offer.fixed_ot_hours_month:g}시간 포함. 실제 연장근로 관행을 확인할 것")
    if offer.weekly_hours:
        hours_year = (offer.weekly_hours + offer.expected_ot_week) * WEEKS_PER_YEAR
        rows["실효 시급(추정)"] = offer.salary / hours_year
    return {"label": offer.label, "rows": rows, "flags": flags}


def render_markdown(results: List[Dict[str, Any]]) -> str:
    keys: List[str] = []
    for r in results:
        keys += [k for k in r["rows"] if k not in keys]
    out = ["| 항목 (원) | " + " | ".join(r["label"] for r in results) + " |",
           "|---|" + "---:|" * len(results)]
    for k in keys:
        cells = [f"{r['rows'][k]:,.0f}" if k in r["rows"] else "-" for r in results]
        out.append(f"| {k} | " + " | ".join(cells) + " |")
    if len(results) > 1:
        base = results[0]["rows"]["월실수령"]
        diffs = ["기준" if i == 0 else f"{r['rows']['월실수령'] - base:+,.0f}" for i, r in enumerate(results)]
        out.append("| 월실수령 차이 | " + " | ".join(diffs) + " |")
    out.append("")
    for r in results:
        if r["flags"]:
            out.append(f"**{r['label']}**")
            out += [f"- {f}" for f in r["flags"]]
    out.append("")
    out.append(f"요율 확인일 {RATES_VERIFIED_ON}. 월 실수령은 간이세액표와 다를 수 있는 추정치이고, "
               "총보상의 성과급·RSU는 목표값이다. 판단은 사용자가 한다.")
    return "\n".join(out)


def main(argv: Optional[List[str]] = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, ValueError):
            pass
    ap = argparse.ArgumentParser(description="한국 오퍼 비교: 총보상 정규화 + 월 실수령 추정")
    ap.add_argument("offers_json")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args(argv)
    try:
        data = load(args.offers_json)
        dependents = int(_num(data, "dependents", "최상위", default=1, lo=1, hi=20, integer=True))
        offers = [parse_offer(o, i) for i, o in enumerate(data["offers"])]
        labels = [o.label for o in offers]
        if len(set(labels)) != len(labels):
            raise InputError("label이 중복됨")
    except InputError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2
    results = [evaluate(o, dependents) for o in offers]
    if args.json:
        print(json.dumps({"rates_verified_on": RATES_VERIFIED_ON, "results": results},
                         ensure_ascii=False, indent=2))
    else:
        print(render_markdown(results))
    return 0


if __name__ == "__main__":
    sys.exit(main())
