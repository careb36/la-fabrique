"""Opt-in authentication and company membership policy."""

from auth_deps import bearer, get_current_user
from config import settings
from database import get_session
from fastapi import Depends, HTTPException, Request
from models import CompanyMember, User
from sqlmodel import Session, select

ROLE_RANK = {"Viewer": 1, "Manager": 2, "Owner": 3}


async def current_user_if_required(
    request: Request,
    session: Session = Depends(get_session),  # noqa: B008 - FastAPI dependency marker.
) -> User | None:
    if not settings.AUTH_REQUIRED:
        # Even when auth is not required, resolve the user from the token
        # if one is provided, so company ownership and memberships work.
        try:
            creds = await bearer(request)
            if creds is not None and creds.credentials:
                return get_current_user(credentials=creds, session=session)
        except Exception:  # noqa: BLE001, S110 - Optional identity is ignored when auth is disabled.
            pass
        return None
    return get_current_user(credentials=await bearer(request), session=session)


def require_company_role(
    session: Session, user: User | None, company_id: int, minimum: str
) -> None:
    if user is None:
        return
    member = session.exec(
        select(CompanyMember).where(
            CompanyMember.user_id == user.id,
            CompanyMember.company_id == company_id,
        )
    ).first()
    if member is None:
        raise HTTPException(status_code=403, detail="Not a member of this company")
    if ROLE_RANK.get(member.human_role, 0) < ROLE_RANK[minimum]:
        raise HTTPException(status_code=403, detail=f"Requires {minimum} role")


def require_authenticated(user: User | None) -> None:
    if settings.AUTH_REQUIRED and user is None:
        raise HTTPException(
            status_code=401,
            detail="Not authenticated",
            headers={"WWW-Authenticate": "Bearer"},
        )


def viewer_company_ids(session: Session, user: User) -> list[int]:
    return list(
        session.exec(
            select(CompanyMember.company_id).where(
                CompanyMember.user_id == user.id,
                CompanyMember.human_role.in_(ROLE_RANK),
            )
        ).all()
    )


def is_support_admin(user: User | None) -> bool:
    """Whether *user* is listed in ``SUPPORT_ADMIN_EMAILS``.

    With authentication disabled and no token, every caller acts as an admin,
    as on the other routes of a local demo.
    """
    if user is None:
        return not settings.AUTH_REQUIRED
    admins = {
        email.strip().lower()
        for email in settings.SUPPORT_ADMIN_EMAILS.split(",")
        if email.strip()
    }
    return (user.email or "").lower() in admins


def require_support_admin(user: User | None) -> None:
    require_authenticated(user)
    if not is_support_admin(user):
        raise HTTPException(status_code=403, detail="Requires support admin")
