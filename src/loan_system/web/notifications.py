"""Màn hình thông báo trong ứng dụng của người đang đăng nhập (M02, FR03.3).

Cùng tầng nghiệp vụ với `api/notifications.py`: mỗi người chỉ thấy và đánh dấu thông báo của chính
mình (SR04).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse

from loan_system.api.deps import Ctx, Db
from loan_system.services.notification_service import NotificationService
from loan_system.web.pages import PREFIX, Csrf, PageError, PageUser, redirect, render

router = APIRouter(prefix=f"{PREFIX}/notifications", include_in_schema=False)


def _service(db: Db, ctx: Ctx) -> NotificationService:
    return NotificationService(db, ctx.clock, ctx.sms)


Notifications = Annotated[NotificationService, Depends(_service)]


@router.get("", response_class=HTMLResponse)
def notifications_page(
    request: Request, user: PageUser, notifications: Notifications
) -> HTMLResponse:
    return render(
        request, "notifications.html",
        {"notifications": notifications.list_for(user.user_id)}, user=user,
    )


@router.post("/read-all", dependencies=[Csrf])
def mark_all_read(user: PageUser, notifications: Notifications) -> RedirectResponse:
    notifications.mark_all_read(user.user_id)
    return redirect(f"{PREFIX}/notifications")


@router.post("/{notification_id}/read", dependencies=[Csrf])
def mark_read(
    notification_id: uuid.UUID, user: PageUser, notifications: Notifications
) -> RedirectResponse:
    if not notifications.mark_read(user.user_id, notification_id):
        raise PageError(status.HTTP_404_NOT_FOUND)
    return redirect(f"{PREFIX}/notifications")
