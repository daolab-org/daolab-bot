from __future__ import annotations

from typing import Iterable

from app.settings import settings


def _iter_roles(member: object) -> Iterable[object]:
    return getattr(member, "roles", []) or []


def has_role(member: object, role_id: int) -> bool:
    return any(getattr(role, "id", None) == role_id for role in _iter_roles(member))


def is_admin(member: object) -> bool:
    if getattr(getattr(member, "guild_permissions", None), "administrator", False):
        return True
    return has_role(member, settings.admin_role_id)


def is_generation_7(member: object) -> bool:
    return has_role(member, settings.generation_7_role_id) and not is_official_crew(
        member
    )


def is_official_crew(member: object) -> bool:
    return has_role(member, settings.official_crew_role_id)


def is_friends(member: object) -> bool:
    return (
        has_role(member, settings.friends_role_id)
        and not is_official_crew(member)
        and not has_role(member, settings.generation_7_role_id)
    )


def classify_member(member: object) -> str:
    if is_official_crew(member):
        return "official_crew"
    if has_role(member, settings.generation_7_role_id):
        return "generation_7"
    if has_role(member, settings.friends_role_id):
        return "friends"
    return "unassigned"


def member_generation(member: object) -> int | None:
    if has_role(member, settings.generation_7_role_id):
        return settings.attendance_generation
    return None
