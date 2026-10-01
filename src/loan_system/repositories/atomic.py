"""Cập nhật nguyên tử không dùng UPDATE ... RETURNING (MySQL không hỗ trợ)."""

from typing import Any, cast

from sqlalchemy import ColumnElement, CursorResult, Update, select, update
from sqlalchemy.orm import InstrumentedAttribute, Session


def increment(db: Session, counter: InstrumentedAttribute[int], row: ColumnElement[bool]) -> int:
    """Tăng bộ đếm của một dòng rồi trả về giá trị mới.

    Câu UPDATE giữ khóa dòng đến hết giao dịch, nên giá trị đọc lại là của chính giao dịch này:
    các yêu cầu song song lần lượt nhận 1, 2, 3...
    """
    db.execute(update(counter.class_).where(row).values({counter: counter + 1}))
    return db.execute(select(counter).where(row)).scalar_one()


def update_matched(db: Session, statement: Update) -> bool:
    """Chạy một câu UPDATE có điều kiện; True nếu có dòng khớp điều kiện.

    Hai yêu cầu song song cùng một điều kiện thì chỉ một yêu cầu thấy dòng còn khớp.
    """
    return cast(CursorResult[Any], db.execute(statement)).rowcount > 0
