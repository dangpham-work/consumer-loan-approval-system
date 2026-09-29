"""Seam 2: luật loại trừ và thẻ điểm 7 yếu tố (mục 1.2.7, UC18, UT05)."""

import hashlib
from dataclasses import replace
from decimal import Decimal

import pytest

from loan_system.domain.scoring import (
    MAX_DTI,
    ApplicantFeatures,
    ModelIntegrityError,
    RuleBasedScoringModel,
    bundled_scorecard,
    fraud_suspected,
    loan_dti,
)

CONTENT = bundled_scorecard()

# Thu nhập 25 triệu (180), DTI 19% (200), CIC nhóm 1 (200), làm việc 4 năm (120), trả hóa đơn
# đúng hạn (120), 31 tuổi (80), thuê nhà (30): 930 điểm.
GOOD = ApplicantFeatures(
    age=31,
    monthly_income=Decimal(25_000_000),
    dti=Decimal("0.19"),
    cic_debt_group=1,
    employment_years=4,
    utility_late_payments=0,
    housing_type="RENT",
)


def trusted_model(content: bytes = CONTENT) -> RuleBasedScoringModel:
    return RuleBasedScoringModel(content, hashlib.sha256(content).hexdigest())


def test_ut05_debt_group_3_is_knocked_out_with_reason() -> None:
    result = trusted_model().score(replace(GOOD, cic_debt_group=3))

    assert result.is_rejected
    assert result.knock_out_reason == "Nợ nhóm 3 trở lên"
    assert result.score is None


def points(features: ApplicantFeatures) -> dict[str, int]:
    return {f.code: f.points for f in trusted_model().score(features).factors}


def test_scorecard_sums_seven_factors_and_grades_the_result() -> None:
    result = trusted_model().score(GOOD)

    assert points(GOOD) == {
        "monthly_income": 180,
        "dti": 200,
        "cic_debt_group": 200,
        "employment_years": 120,
        "utility_late_payments": 120,
        "age": 80,
        "housing_type": 30,
    }
    assert (result.score, result.grade, result.knock_out_reason) == (930, "A", None)
    assert result.model_version == "SC-2026.1"
    assert not result.is_rejected


def test_every_factor_at_its_maximum_scores_1000() -> None:
    best = replace(GOOD, monthly_income=Decimal(40_000_000), housing_type="OWN")
    assert sum(f.max_points for f in trusted_model().score(best).factors) == 1000
    assert trusted_model().score(best).score == 1000


def test_band_boundaries_follow_the_scorecard_table() -> None:
    # Thu nhập: < 7 triệu | 7–15 triệu | 15–30 triệu | > 30 triệu
    income = {m: points(replace(GOOD, monthly_income=Decimal(m)))["monthly_income"]
              for m in (6_999_999, 7_000_000, 14_999_999, 15_000_000, 30_000_000, 30_000_001)}
    assert income == {6_999_999: 50, 7_000_000: 120, 14_999_999: 120, 15_000_000: 180,
                      30_000_000: 180, 30_000_001: 220}
    # DTI: ≤ 20% | 20–35% | 35–50%
    dti = {d: points(replace(GOOD, dti=Decimal(d)))["dti"]
           for d in ("0.20", "0.2001", "0.35", "0.3501", "0.50")}
    assert dti == {"0.20": 200, "0.2001": 140, "0.35": 140, "0.3501": 60, "0.50": 60}
    # Thời gian làm việc: < 1 năm | 1–3 năm | > 3 năm
    years = {y: points(replace(GOOD, employment_years=y))["employment_years"] for y in (0, 1, 3, 4)}
    assert years == {0: 30, 1: 80, 3: 80, 4: 120}
    # Tuổi: 20–24 | 25–45 | 46–60
    ages = {a: points(replace(GOOD, age=a))["age"] for a in (20, 24, 25, 45, 46, 60)}
    assert ages == {20: 40, 24: 40, 25: 80, 45: 80, 46: 60, 60: 60}
    # Nhóm nợ CIC: chưa có lịch sử | nhóm 1 | nhóm 2
    groups = {g: points(replace(GOOD, cic_debt_group=g))["cic_debt_group"] for g in (0, 1, 2)}
    assert groups == {0: 100, 1: 200, 2: 60}
    # Hóa đơn điện/nước: đúng hạn | trễ 1–2 lần | trễ ≥ 3 lần
    late = {n: points(replace(GOOD, utility_late_payments=n))["utility_late_payments"]
            for n in (0, 1, 2, 3)}
    assert late == {0: 120, 1: 60, 2: 60, 3: 0}
    housing = {h: points(replace(GOOD, housing_type=h))["housing_type"]
               for h in ("OWN", "FAMILY", "RENT")}
    assert housing == {"OWN": 60, "FAMILY": 40, "RENT": 30}


LOW = replace(GOOD, monthly_income=Decimal(5_000_000), dti=Decimal("0.19"), employment_years=0)


def test_grades_follow_score_ranges() -> None:
    cases = {
        750: replace(LOW, cic_debt_group=1, employment_years=2, utility_late_payments=0, age=22,
                     housing_type="OWN"),
        740: replace(LOW, cic_debt_group=1, utility_late_payments=0, age=31, housing_type="OWN"),
        600: replace(LOW, cic_debt_group=0, utility_late_payments=0, age=22, housing_type="OWN"),
        590: replace(LOW, cic_debt_group=0, utility_late_payments=0, age=50, housing_type="RENT"),
        450: replace(LOW, cic_debt_group=0, utility_late_payments=3, age=22, housing_type="RENT"),
        440: replace(LOW, cic_debt_group=2, utility_late_payments=3, age=22, housing_type="OWN"),
    }
    graded = {s: (r.score, r.grade) for s, r in
              ((s, trusted_model().score(f)) for s, f in cases.items())}
    assert graded == {750: (750, "A"), 740: (740, "B"), 600: (600, "B"), 590: (590, "C"),
                      450: (450, "C"), 440: (440, "D")}
    assert trusted_model().score(cases[440]).is_rejected  # hạng D bị từ chối tự động


def test_missing_cic_scores_as_no_credit_history() -> None:
    # Thiếu dữ liệu CIC vẫn chấm: yếu tố CIC như "chưa có lịch sử", hóa đơn như trễ 1–2 lần.
    scored = points(replace(GOOD, cic_debt_group=None, utility_late_payments=None))
    assert (scored["cic_debt_group"], scored["utility_late_payments"]) == (100, 60)


def test_top_factors_are_the_three_that_lost_the_most_points() -> None:
    result = trusted_model().score(replace(GOOD, employment_years=0, dti=Decimal("0.40")))
    # Thiếu hụt: DTI 140, làm việc 90, nhà ở 30, thu nhập 40, còn lại 0 hoặc 20
    assert [f.code for f in result.top_factors] == ["dti", "employment_years", "monthly_income"]


def test_factors_that_lost_no_points_are_not_top_factors() -> None:
    # Hồ sơ vay tốt chỉ mất điểm ở thu nhập (40) và nhà ở (30).
    assert [f.code for f in trusted_model().score(GOOD).top_factors] == [
        "monthly_income", "housing_type"
    ]


def test_other_knock_out_rules() -> None:
    reasons = {
        "age 19": replace(GOOD, age=19),
        "age 61": replace(GOOD, age=61),
        "income": replace(GOOD, monthly_income=Decimal(4_999_999)),
        "group 5": replace(GOOD, cic_debt_group=5),
        "dti": replace(GOOD, dti=Decimal("0.5001")),
    }
    assert {k: trusted_model().score(f).knock_out_reason for k, f in reasons.items()} == {
        "age 19": "Tuổi ngoài khoảng 20–60",
        "age 61": "Tuổi ngoài khoảng 20–60",
        "income": "Thu nhập dưới 5 triệu đồng/tháng",
        "group 5": "Nợ nhóm 3 trở lên",
        "dti": "DTI vượt 50%",
    }
    assert trusted_model().score(replace(GOOD, dti=MAX_DTI)).knock_out_reason is None


def test_st09_tampered_model_file_fails_integrity_check() -> None:
    tampered = CONTENT.replace(b'"points": 30}', b'"points": 300}')
    model = RuleBasedScoringModel(tampered, hashlib.sha256(CONTENT).hexdigest())

    assert not model.verify_integrity()
    with pytest.raises(ModelIntegrityError):
        model.score(GOOD)
    assert trusted_model().verify_integrity()


def test_fraud_is_suspected_when_cic_exceeds_declared_debt_by_20_percent_or_1_million() -> None:
    m = Decimal(1_000_000)
    assert not fraud_suspected(Decimal(2) * m, Decimal("2.4") * m)  # đúng 20%
    assert fraud_suspected(Decimal(2) * m, Decimal(2_400_001))
    assert not fraud_suspected(Decimal(10) * m, Decimal(11) * m)  # đúng 1 triệu, dưới 20%
    assert fraud_suspected(Decimal(10) * m, Decimal(11_000_001))
    assert fraud_suspected(Decimal(0), Decimal(1))  # khai không có nợ nhưng CIC có
    assert not fraud_suspected(Decimal(3) * m, Decimal(1) * m)  # khai cao hơn CIC
    assert not fraud_suspected(Decimal(3) * m, None)  # thiếu CIC


def test_loan_dti_uses_ceiling_rate_and_the_larger_obligation() -> None:
    # 30 triệu, 12 kỳ, lãi suất trần 28%/năm -> 2.895.180đ mỗi kỳ (ADR 0001)
    declared_only = loan_dti(
        monthly_income=Decimal(12_000_000), declared_debt=Decimal(2_000_000),
        cic_obligation=None, amount=Decimal(30_000_000), term_months=12,
        annual_rate=Decimal("0.28"),
    )
    cic_higher = loan_dti(
        monthly_income=Decimal(12_000_000), declared_debt=Decimal(2_000_000),
        cic_obligation=Decimal(3_000_000), amount=Decimal(30_000_000), term_months=12,
        annual_rate=Decimal("0.28"),
    )
    assert declared_only == Decimal(4_895_180) / Decimal(12_000_000)
    assert cic_higher == Decimal(5_895_180) / Decimal(12_000_000)
