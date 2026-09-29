"""Seam 2: quy tắc gán vai trò (UC04 2d, ma trận RBAC)."""

import uuid

from loan_system.domain.access import (
    admin_role_lending_permission,
    conflicting_permission_pair,
    is_self_escalation,
    mixes_admin_and_lending,
)

ME, OTHER = uuid.uuid4(), uuid.uuid4()


def test_admin_may_keep_only_the_admin_role_on_their_own_account() -> None:
    assert not is_self_escalation(ME, ME, {"ADMIN"})
    assert is_self_escalation(ME, ME, {"ADMIN", "APPROVER"})
    assert is_self_escalation(ME, ME, {"AUDITOR"})
    assert not is_self_escalation(ME, OTHER, {"APPROVER"})


def test_no_account_may_combine_admin_with_a_lending_role() -> None:
    assert mixes_admin_and_lending({"ADMIN", "DISBURSER"})
    assert not mixes_admin_and_lending({"ADMIN"})
    assert not mixes_admin_and_lending({"APPROVER", "CREDIT_OFFICER"})


def test_a_role_cannot_hold_two_permissions_of_the_sod_chain() -> None:
    # UC05 4/4a: thẩm định, phê duyệt, giải ngân của một hồ sơ vay không được cùng một vai trò.
    assert conflicting_permission_pair({"APPRAISAL_SUBMIT", "LOAN_APPROVE"}) == (
        "APPRAISAL_SUBMIT", "LOAN_APPROVE",
    )
    assert conflicting_permission_pair({"LOAN_APPROVE", "DISBURSE"}) == (
        "DISBURSE", "LOAN_APPROVE",
    )
    assert conflicting_permission_pair(
        {"APPRAISAL_SUBMIT", "LOAN_APPROVE", "DISBURSE"}
    ) == ("APPRAISAL_SUBMIT", "DISBURSE")


def test_permissions_outside_the_sod_chain_never_conflict() -> None:
    assert conflicting_permission_pair({"APPRAISAL_SUBMIT"}) is None
    assert conflicting_permission_pair({"APPLICATION_CREATE", "LOAN_APPROVE"}) is None
    assert conflicting_permission_pair(set()) is None


def test_admin_role_cannot_hold_a_lending_permission_even_assigned_directly() -> None:
    # Không được lách mixes_admin_and_lending bằng cách sửa thẳng quyền của vai trò ADMIN.
    assert admin_role_lending_permission("ADMIN", {"USER_MANAGE", "LOAN_APPROVE"}) == "LOAN_APPROVE"
    assert admin_role_lending_permission("ADMIN", {"USER_MANAGE", "ROLE_MANAGE"}) is None
    # Vai trò khác giữ quyền nghiệp vụ cho vay là bình thường.
    assert admin_role_lending_permission("APPROVER", {"LOAN_APPROVE"}) is None
