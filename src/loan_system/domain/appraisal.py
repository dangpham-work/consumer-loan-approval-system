"""Tờ trình thẩm định (UC22, SD04) và số lượt phê duyệt theo hạn mức (BR05)."""

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum

from loan_system.domain.applications import (
    MAX_AMOUNT,
    MAX_TERM_MONTHS,
    MIN_AMOUNT,
    MIN_TERM_MONTHS,
)

MIN_COMMENT_LENGTH = 20  # M06: nhận xét bắt buộc ≥ 20 ký tự


class Recommendation(StrEnum):
    APPROVE = "APPROVE"
    REJECT = "REJECT"


class InvalidProposal(Exception):
    """Tờ trình không hợp lệ; thông điệp an toàn để hiển thị cho chuyên viên."""


@dataclass(frozen=True)
class Proposal:
    """Đề xuất của chuyên viên thẩm định. Đề xuất từ chối không cần hạn mức, kỳ hạn (UC22 4b)."""

    recommendation: Recommendation
    amount: Decimal | None
    term_months: int | None
    comment: str

    def validate_against(self, requested_amount: Decimal) -> None:
        """AppraisalReport.validateAgainst (SD04 bước 13)."""
        if len(self.comment.strip()) < MIN_COMMENT_LENGTH:
            raise InvalidProposal("Nhận xét phải có ít nhất 20 ký tự")
        if self.recommendation == Recommendation.REJECT:
            return
        if self.amount is None or self.term_months is None:
            raise InvalidProposal("Đề xuất duyệt phải có hạn mức và kỳ hạn")
        if self.amount > requested_amount:  # UC22 bước 4
            raise InvalidProposal("Hạn mức đề xuất vượt số tiền yêu cầu")
        if self.amount < MIN_AMOUNT:
            raise InvalidProposal("Hạn mức đề xuất phải từ 5 triệu đồng")
        if not MIN_TERM_MONTHS <= self.term_months <= MAX_TERM_MONTHS:
            raise InvalidProposal("Kỳ hạn đề xuất phải từ 6 đến 36 tháng")


@dataclass(frozen=True)
class ApprovalTier:
    """Một khoảng hạn mức của Chính sách phê duyệt và số lượt phê duyệt cần có."""

    min_amount: Decimal
    max_amount: Decimal
    approvals: int


class NoApprovalTier(Exception):
    """Chính sách phê duyệt không có khoảng hạn mức nào chứa số tiền này."""


def required_approvals(tiers: Sequence[ApprovalTier], amount: Decimal) -> int:
    for tier in tiers:
        if tier.min_amount <= amount <= tier.max_amount:
            return tier.approvals
    raise NoApprovalTier


class InvalidPolicyTiers(Exception):
    """UC06 3a: khoảng hạn mức chồng lấn hoặc bị hở, thông điệp an toàn để hiển thị."""


def validate_tiers(tiers: Sequence[ApprovalTier]) -> None:
    """UC06 bước 3: các khoảng phải phủ kín 5–100 triệu (BR05), không chồng lấn, không bị hở."""
    if not tiers:
        raise InvalidPolicyTiers("Chính sách phải có ít nhất một khoảng hạn mức")
    ordered = sorted(tiers, key=lambda t: t.min_amount)
    for tier in ordered:
        if tier.min_amount > tier.max_amount:
            raise InvalidPolicyTiers("Khoảng hạn mức không hợp lệ")
    if ordered[0].min_amount != MIN_AMOUNT or ordered[-1].max_amount != MAX_AMOUNT:
        raise InvalidPolicyTiers(f"Các khoảng hạn mức phải phủ kín {MIN_AMOUNT:,.0f}–{MAX_AMOUNT:,.0f} đồng")
    for prev, nxt in zip(ordered, ordered[1:]):
        if nxt.min_amount != prev.max_amount + 1:
            raise InvalidPolicyTiers("Các khoảng hạn mức chồng lấn hoặc bị hở")
