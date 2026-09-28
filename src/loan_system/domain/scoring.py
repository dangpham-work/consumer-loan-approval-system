"""Chấm điểm tín dụng: luật loại trừ và thẻ điểm 7 yếu tố (mục 1.2.7, UC18, UC20, SR13).

Luật loại trừ là quy tắc nghiệp vụ (BR01, BR03, BR04) nên nằm trong mã; còn mức điểm, khoảng giá
trị và ngưỡng hạng là mô hình, nằm trong file thẻ điểm có checksum để thay được mà không sửa mã
(NFR04, FR04.3). File chỉ được dùng sau khi SHA-256 của nó khớp với checksum đã đăng ký.
"""

import hashlib
import hmac
import json
from dataclasses import dataclass
from decimal import Decimal
from importlib.resources import files
from typing import Any

from loan_system.domain.calculations import (
    annuity_payment,
    calculate_dti,
    existing_monthly_obligation,
)

MIN_AGE = 20  # BR01
MAX_AGE = 60
MIN_MONTHLY_INCOME = Decimal(5_000_000)  # BR01
MAX_DTI = Decimal("0.50")  # BR03
KNOCK_OUT_DEBT_GROUP = 3  # BR04: nhóm 3 trở lên là nợ xấu

BUNDLED_MODEL_FILE = "scorecard-2026.1.json"


@dataclass(frozen=True)
class ApplicantFeatures:
    """Bộ đặc trưng dựng từ Hồ sơ vay, Khách hàng và Báo cáo CIC (UC18 bước 2)."""

    age: int
    monthly_income: Decimal
    dti: Decimal  # tính theo lãi suất trần (ADR 0001)
    cic_debt_group: int | None  # 0 = chưa có lịch sử; None = thiếu dữ liệu CIC
    employment_years: int
    utility_late_payments: int | None  # dữ liệu thay thế (giả lập); None = không có
    housing_type: str


@dataclass(frozen=True)
class FactorScore:
    code: str
    label: str
    points: int
    max_points: int

    @property
    def shortfall(self) -> int:
        return self.max_points - self.points


@dataclass(frozen=True)
class CreditScore:
    """Kết quả chấm điểm; bị loại trừ thì không có điểm và hạng."""

    score: int | None
    grade: str | None
    knock_out_reason: str | None
    factors: tuple[FactorScore, ...]
    model_version: str | None

    @property
    def is_rejected(self) -> bool:
        return self.knock_out_reason is not None or self.grade == "D"

    @property
    def top_factors(self) -> tuple[FactorScore, ...]:
        """Tối đa 3 yếu tố làm giảm điểm nhiều nhất (UC20 bước 3); yếu tố không mất điểm thì bỏ."""
        lost = [f for f in self.factors if f.shortfall > 0]
        ranked = sorted(lost, key=lambda f: f.shortfall, reverse=True)
        return tuple(ranked[:3])


def knock_out(features: ApplicantFeatures) -> str | None:
    """Lý do vi phạm luật loại trừ đầu tiên (UC18 bước 3), hoặc None."""
    if not MIN_AGE <= features.age <= MAX_AGE:
        return "Tuổi ngoài khoảng 20–60"
    if features.monthly_income < MIN_MONTHLY_INCOME:
        return "Thu nhập dưới 5 triệu đồng/tháng"
    if features.cic_debt_group is not None and features.cic_debt_group >= KNOCK_OUT_DEBT_GROUP:
        return "Nợ nhóm 3 trở lên"
    if features.dti > MAX_DTI:
        return "DTI vượt 50%"
    return None


FRAUD_RATIO = Decimal("1.2")  # 1.2.8b: CIC vượt khai báo trên 20%
FRAUD_ABSOLUTE = Decimal(1_000_000)  # hoặc trên 1 triệu đồng


def fraud_suspected(declared_debt: Decimal, cic_obligation: Decimal | None) -> bool:
    """Nghĩa vụ nợ theo CIC vượt số tự khai quá ngưỡng: gắn cờ cho thẩm định (ADR 0002, MUC05)."""
    if cic_obligation is None:
        return False
    return (
        cic_obligation > declared_debt * FRAUD_RATIO
        or cic_obligation - declared_debt > FRAUD_ABSOLUTE
    )


def scoring_dti(
    *,
    monthly_income: Decimal,
    declared_debt: Decimal,
    cic_obligation: Decimal | None,
    amount: Decimal,
    term_months: int,
    ceiling_rate: Decimal,
) -> Decimal:
    """DTI lúc chấm điểm: theo lãi suất trần (lãi suất hạng C của chính sách) vì chưa có Hạng
    (ADR 0001), nghĩa vụ nợ hiện có lấy max(khai báo, CIC) (ADR 0002)."""
    return calculate_dti(
        monthly_income,
        existing_monthly_obligation(declared_debt, cic_obligation),
        annuity_payment(amount, ceiling_rate, term_months),
    )


class ModelIntegrityError(Exception):
    """SHA-256 của file mô hình không khớp checksum đã đăng ký (SR13, ST09)."""


def bundled_scorecard() -> bytes:
    """File thẻ điểm đi kèm mã nguồn."""
    return files("loan_system").joinpath("scoring_models", BUNDLED_MODEL_FILE).read_bytes()


class RuleBasedScoringModel:
    """Mô hình thẻ điểm (ScoringModel trong biểu đồ lớp)."""

    def __init__(self, content: bytes, checksum: str) -> None:
        self._content = content
        self._checksum = checksum

    def verify_integrity(self) -> bool:
        actual = hashlib.sha256(self._content).hexdigest()
        return hmac.compare_digest(actual, self._checksum.lower())

    def score(self, features: ApplicantFeatures) -> CreditScore:
        reason = knock_out(features)
        if reason is not None:
            return CreditScore(None, None, reason, (), None)
        if not self.verify_integrity():
            raise ModelIntegrityError
        card: dict[str, Any] = json.loads(self._content)
        factors = tuple(_factor_score(f, getattr(features, f["code"])) for f in card["factors"])
        total = sum(f.points for f in factors)
        grade = next(g["grade"] for g in card["grades"] if total >= g["min_score"])
        return CreditScore(total, grade, None, factors, card["version"])


def _factor_score(factor: dict[str, Any], value: object) -> FactorScore:
    if "levels" in factor:
        levels: dict[str, int] = factor["levels"]
        points, max_points = levels[str(value)], max(levels.values())
    else:
        bands: list[dict[str, Any]] = factor["bands"]
        max_points = max(b["points"] for b in bands)
        if value is None:
            points = factor["missing"]
        else:
            assert isinstance(value, (int, Decimal))
            points = next(
                b["points"] for b in bands if "max" not in b or value <= Decimal(str(b["max"]))
            )
    return FactorScore(factor["code"], factor["label"], points, max_points)
