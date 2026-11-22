from dataclasses import dataclass
from uuid import UUID


@dataclass(frozen=True)
class Principal:
    user_id: UUID
    tenant_id: UUID
    membership_id: UUID
    session_id: UUID
    role: str  # base role (owner/admin/member) — informational; authorization uses roles/permissions tables


@dataclass(frozen=True)
class StaffPrincipal:
    staff_id: UUID
    role: str
