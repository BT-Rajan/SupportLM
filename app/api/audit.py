"""Audit log endpoint (Phase 8 — 1.3)."""
from fastapi import APIRouter, Depends

from app.core.rbac import require_role
from app.services.audit import get_audit_log

router = APIRouter(prefix="/api/tenant/audit-log", tags=["audit-log"])


@router.get("")
def list_audit_log(days: int = 30, tenant_id: int = Depends(require_role("admin"))):
    """admin+ — who-did-what is sensitive, same floor as CSV export."""
    return get_audit_log(tenant_id, days)
