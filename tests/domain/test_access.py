"""Seam 2: quy tắc gán vai trò (UC04 2d, ma trận RBAC)."""

import uuid

from loan_system.domain.access import is_self_escalation, mixes_admin_and_lending

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
