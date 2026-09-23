from __future__ import annotations

from fastapi import APIRouter

from app.api.dependencies import CurrentUser, DbSession
from app.schemas import UserSettingsUpdate, UserSettingsView

router = APIRouter(prefix="/users", tags=["users"])


@router.get("/me/settings", response_model=UserSettingsView)
async def read_settings(user: CurrentUser) -> UserSettingsView:
    return UserSettingsView(approval_mode=user.approval_mode)


@router.put("/me/settings", response_model=UserSettingsView)
async def update_settings(
    payload: UserSettingsUpdate, db: DbSession, user: CurrentUser
) -> UserSettingsView:
    user.approval_mode = payload.approval_mode
    await db.commit()
    return UserSettingsView(approval_mode=user.approval_mode)
