"""Thông báo trong ứng dụng của người đang đăng nhập (M02, FR03.3)."""

import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ConfigDict

from loan_system.api.access import User
from loan_system.api.deps import Ctx, Db
from loan_system.services.notification_service import NotificationService

router = APIRouter(prefix="/notifications", tags=["Thông báo"])


def _service(db: Db, ctx: Ctx) -> NotificationService:
    return NotificationService(db, ctx.clock, ctx.sms)


Notifications = Annotated[NotificationService, Depends(_service)]


class NotificationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    type: str
    content: str
    is_read: bool
    created_at: datetime


@router.get("", response_model=list[NotificationResponse])
def list_notifications(user: User, notifications: Notifications) -> list[NotificationResponse]:
    return [NotificationResponse.model_validate(n) for n in notifications.list_for(user.user_id)]


@router.post("/{notification_id}/read", status_code=status.HTTP_204_NO_CONTENT)
def mark_read(notification_id: uuid.UUID, user: User, notifications: Notifications) -> None:
    if not notifications.mark_read(user.user_id, notification_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Không tìm thấy thông báo")
