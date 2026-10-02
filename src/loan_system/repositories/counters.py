"""Bộ đếm một dòng thay cho SEQUENCE (MySQL không có), và dòng khóa của chuỗi băm nhật ký."""

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from loan_system.repositories.models import Counter

AUDIT_CHAIN = "audit_chain"
LOAN_APPLICATION_CODE = "loan_application_code"


def lock_audit_chain(db: Session) -> None:
    """Giữ khóa dòng đến hết giao dịch: các giao dịch ghi nhật ký kiểm toán chạy tuần tự."""
    db.execute(select(Counter.value).where(Counter.name == AUDIT_CHAIN).with_for_update()).one()


def next_value(db: Session, name: str) -> int:
    """Số kế tiếp, liên tục không thủng: giao dịch bị hủy thì số cũng được hoàn lại.

    Khóa chuỗi nhật ký trước, vì giao dịch nào cũng ghi nhật ký: mọi giao dịch lấy hai khóa theo
    cùng một thứ tự nên không khóa chéo nhau.
    """
    lock_audit_chain(db)
    db.execute(update(Counter).where(Counter.name == name).values(value=Counter.value + 1))
    return db.execute(select(Counter.value).where(Counter.name == name)).scalar_one()
