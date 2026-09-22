from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.api.dependencies import DbSession
from app.core.config import get_settings
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    token_fingerprint,
    verify_password,
)
from app.models import RefreshToken, User
from app.schemas import LoginRequest, RefreshRequest, RegisterRequest, TokenResponse

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(user_id: str) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(user_id), refresh_token=create_refresh_token(user_id)
    )


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(payload: RegisterRequest, db: DbSession) -> TokenResponse:
    existing = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(409, "email already registered")
    user = User(
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
        display_name=payload.display_name,
    )
    db.add(user)
    await db.flush()
    result = _tokens(user.id)
    settings = get_settings()
    db.add(
        RefreshToken(
            user_id=user.id,
            fingerprint=token_fingerprint(result.refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
    )
    await db.commit()
    return result


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, db: DbSession) -> TokenResponse:
    user = await db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(401, "invalid credentials")
    result = _tokens(user.id)
    settings = get_settings()
    db.add(
        RefreshToken(
            user_id=user.id,
            fingerprint=token_fingerprint(result.refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
    )
    await db.commit()
    return result


@router.post("/refresh", response_model=TokenResponse)
async def refresh(payload: RefreshRequest, db: DbSession) -> TokenResponse:
    try:
        decoded = decode_token(payload.refresh_token, "refresh")
    except Exception as exc:
        raise HTTPException(401, "invalid refresh token") from exc
    record = await db.scalar(
        select(RefreshToken).where(
            RefreshToken.fingerprint == token_fingerprint(payload.refresh_token),
            RefreshToken.revoked_at.is_(None),
        )
    )
    if not record or record.expires_at.replace(tzinfo=UTC) <= datetime.now(UTC):
        raise HTTPException(401, "refresh token expired or revoked")
    record.revoked_at = datetime.now(UTC)
    result = _tokens(str(decoded["sub"]))
    settings = get_settings()
    db.add(
        RefreshToken(
            user_id=str(decoded["sub"]),
            fingerprint=token_fingerprint(result.refresh_token),
            expires_at=datetime.now(UTC) + timedelta(days=settings.refresh_token_days),
        )
    )
    await db.commit()
    return result
