import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.core.tenant_scope import resolve_tenant, resolve_tenant_for_admin
from app.db.pool import get_conn

router = APIRouter(prefix="/api/categories", tags=["categories"])


class CategoryIn(BaseModel):
    name: str


class CategoryOut(BaseModel):
    id: int
    name: str
    slug: str


def _slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "category"


@router.get("", response_model=list[CategoryOut], dependencies=[Depends(resolve_tenant)])
def list_categories(tenant_id: int = Depends(resolve_tenant)):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, name, slug FROM category WHERE tenant_id = %s ORDER BY name", (tenant_id,))
        rows = cur.fetchall()
        cur.close()
    return [CategoryOut(**row) for row in rows]


@router.post("", response_model=CategoryOut, dependencies=[Depends(resolve_tenant_for_admin)])
def create_category(req: CategoryIn, tenant_id: int = Depends(resolve_tenant_for_admin)):
    slug = _slugify(req.name)
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO category (tenant_id, name, slug) VALUES (%s, %s, %s)",
            (tenant_id, req.name, slug),
        )
        category_id = cur.lastrowid
        cur.close()
    return CategoryOut(id=category_id, name=req.name, slug=slug)


@router.delete("/{category_id}", dependencies=[Depends(resolve_tenant_for_admin)])
def delete_category(category_id: int, tenant_id: int = Depends(resolve_tenant_for_admin)):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM category WHERE id = %s AND tenant_id = %s", (category_id, tenant_id))
        deleted = cur.rowcount
        cur.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Category not found")
    return {"ok": True}
