"""UC06 Cấu hình chính sách phê duyệt: khoảng hạn mức, lãi suất theo hạng, phí trả trước hạn.

Lưu thành phiên bản mới, không ghi đè bản cũ (ADR 0001); Hồ sơ vay đã chốt `policy_id` giữ đúng
phiên bản của nó (BR05), chỉ hồ sơ vào "Chờ phê duyệt" sau thời điểm lưu mới dùng bản mới.
"""

import uuid
from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from loan_system.clock import Clock
from loan_system.domain.appraisal import ApprovalTier, validate_tiers
from loan_system.repositories.models import ApprovalPolicy, ApprovalPolicyTier
from loan_system.services.audit_service import AuditService
from loan_system.services.auth_service import CurrentUser


@dataclass(frozen=True)
class TierInput:
    min_amount: Decimal
    max_amount: Decimal
    required_approvals: int


@dataclass(frozen=True)
class NewPolicy:
    rate_grade_a: Decimal
    rate_grade_b: Decimal
    rate_grade_c: Decimal
    prepayment_fee_rate: Decimal
    tiers: list[TierInput]


@dataclass(frozen=True)
class PolicyView:
    version: int
    rate_grade_a: Decimal
    rate_grade_b: Decimal
    rate_grade_c: Decimal
    prepayment_fee_rate: Decimal
    is_active: bool
    tiers: list[TierInput]


class PolicyService:
    def __init__(self, db: Session, clock: Clock, ip: str | None) -> None:
        self._db = db
        self._clock = clock
        self._audit = AuditService(db, clock)
        self._ip = ip

    def list_versions(self) -> list[PolicyView]:
        policies = self._db.scalars(
            select(ApprovalPolicy).order_by(ApprovalPolicy.version.desc())
        ).all()
        return [self._view(policy) for policy in policies]

    def create_version(self, actor: CurrentUser, data: NewPolicy) -> PolicyView:
        """UC06 bước 2–4: kiểm tra các khoảng hạn mức rồi lưu thành phiên bản mới."""
        validate_tiers(
            [ApprovalTier(t.min_amount, t.max_amount, t.required_approvals) for t in data.tiers]
        )
        next_version = (self._db.scalar(select(func.max(ApprovalPolicy.version))) or 0) + 1
        # Chỉ một phiên bản hiệu lực tại một thời điểm (chỉ mục lọc is_active).
        self._db.execute(update(ApprovalPolicy).values(is_active=False))
        policy = ApprovalPolicy(
            id=uuid.uuid4(), version=next_version, rate_grade_a=data.rate_grade_a,
            rate_grade_b=data.rate_grade_b, rate_grade_c=data.rate_grade_c,
            prepayment_fee_rate=data.prepayment_fee_rate, is_active=True,
            created_at=self._clock.now(),
        )
        self._db.add(policy)
        self._db.flush()
        self._db.add_all(
            ApprovalPolicyTier(
                id=uuid.uuid4(), policy_id=policy.id, min_amount=t.min_amount,
                max_amount=t.max_amount, required_approvals=t.required_approvals,
            )
            for t in data.tiers
        )
        self._audit.log(
            "POLICY_VERSION_CREATE", actor_id=actor.user_id, target_type="APPROVAL_POLICY",
            target_id=policy.id, ip_address=self._ip, detail=f"version {next_version}",
        )
        self._db.commit()
        return PolicyView(
            version=next_version, rate_grade_a=data.rate_grade_a, rate_grade_b=data.rate_grade_b,
            rate_grade_c=data.rate_grade_c, prepayment_fee_rate=data.prepayment_fee_rate,
            is_active=True, tiers=data.tiers,
        )

    def _view(self, policy: ApprovalPolicy) -> PolicyView:
        tiers = self._db.scalars(
            select(ApprovalPolicyTier)
            .where(ApprovalPolicyTier.policy_id == policy.id)
            .order_by(ApprovalPolicyTier.min_amount)
        ).all()
        return PolicyView(
            version=policy.version, rate_grade_a=policy.rate_grade_a,
            rate_grade_b=policy.rate_grade_b, rate_grade_c=policy.rate_grade_c,
            prepayment_fee_rate=policy.prepayment_fee_rate, is_active=policy.is_active,
            tiers=[
                TierInput(t.min_amount, t.max_amount, t.required_approvals) for t in tiers
            ],
        )
