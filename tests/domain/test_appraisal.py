"""Seam 2: quy tắc tờ trình thẩm định (UC22, SD04, BR03, BR05)."""

from decimal import Decimal

import pytest

from loan_system.domain.appraisal import (
    InvalidProposal,
    NoApprovalTier,
    Proposal,
    Recommendation,
    ApprovalTier,
    required_approvals,
)
from loan_system.domain.scoring import loan_dti

REQUESTED = Decimal(30_000_000)
COMMENT = "Thu nhập ổn định, lịch sử tín dụng tốt."


def proposal(**overrides: object) -> Proposal:
    values: dict[str, object] = {
        "recommendation": Recommendation.APPROVE,
        "amount": Decimal(25_000_000),
        "term_months": 12,
        "comment": COMMENT,
    }
    values.update(overrides)
    return Proposal(**values)  # type: ignore[arg-type]


def reason(p: Proposal) -> str:
    with pytest.raises(InvalidProposal) as exc:
        p.validate_against(REQUESTED)
    return str(exc.value)


def test_approval_proposal_within_the_requested_amount_is_valid() -> None:
    proposal().validate_against(REQUESTED)
    proposal(amount=REQUESTED, term_months=36).validate_against(REQUESTED)


def test_proposed_amount_cannot_exceed_the_requested_amount() -> None:
    assert reason(proposal(amount=REQUESTED + 1)) == "Hạn mức đề xuất vượt số tiền yêu cầu"


def test_proposal_must_stay_within_product_limits() -> None:
    assert reason(proposal(amount=Decimal(4_999_999))) == "Hạn mức đề xuất phải từ 5 triệu đồng"
    assert reason(proposal(term_months=5)) == "Kỳ hạn đề xuất phải từ 6 đến 36 tháng"
    assert reason(proposal(term_months=37)) == "Kỳ hạn đề xuất phải từ 6 đến 36 tháng"


def test_approval_proposal_needs_amount_and_term() -> None:
    assert reason(proposal(amount=None)) == "Đề xuất duyệt phải có hạn mức và kỳ hạn"
    assert reason(proposal(term_months=None)) == "Đề xuất duyệt phải có hạn mức và kỳ hạn"


def test_rejection_proposal_needs_no_amount() -> None:
    proposal(recommendation=Recommendation.REJECT, amount=None, term_months=None).validate_against(
        REQUESTED
    )


def test_comment_needs_at_least_20_characters() -> None:
    assert reason(proposal(comment="Ổn.")) == "Nhận xét phải có ít nhất 20 ký tự"
    assert reason(proposal(comment=" " * 30)) == "Nhận xét phải có ít nhất 20 ký tự"


TIERS = [
    ApprovalTier(Decimal(5_000_000), Decimal(50_000_000), 1),
    ApprovalTier(Decimal(50_000_001), Decimal(100_000_000), 2),
]


def test_loans_above_50_million_need_two_approvals() -> None:
    # BR05: ≤ 50 triệu cần 1 Quản lý phê duyệt, > 50 triệu cần 2.
    assert required_approvals(TIERS, Decimal(50_000_000)) == 1
    assert required_approvals(TIERS, Decimal(50_000_001)) == 2
    assert required_approvals(TIERS, Decimal(5_000_000)) == 1
    assert required_approvals(TIERS, Decimal(100_000_000)) == 2


def test_appraisal_dti_uses_the_rate_of_the_real_grade() -> None:
    # Ví dụ 1.2.8b: thu nhập 12 triệu, đang trả 2 triệu, vay 30 triệu 12 kỳ 24%/năm (hạng B)
    # -> A = 2.836.788đ, DTI ≈ 40,3%.
    dti = loan_dti(
        monthly_income=Decimal(12_000_000), declared_debt=Decimal(2_000_000),
        cic_obligation=None, amount=Decimal(30_000_000), term_months=12,
        annual_rate=Decimal("0.24"),
    )
    assert dti == Decimal(4_836_788) / Decimal(12_000_000)


def test_an_amount_outside_every_tier_is_reported_not_crashed() -> None:
    with pytest.raises(NoApprovalTier):
        required_approvals(TIERS, Decimal(100_000_001))
