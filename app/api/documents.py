from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile
from pydantic import BaseModel

from app.core.tenant_scope import resolve_tenant_for_admin
from app.db.pool import get_conn
from app.services.ingestion import ingest_document

router = APIRouter(prefix="/api/documents", tags=["documents"], dependencies=[Depends(resolve_tenant_for_admin)])


class DocumentOut(BaseModel):
    id: int
    title: str
    status: str
    error_message: str | None = None


@router.post("/upload", response_model=DocumentOut)
async def upload_document(
    file: UploadFile,
    background_tasks: BackgroundTasks,
    category_id: int | None = None,
    tenant_id: int = Depends(resolve_tenant_for_admin),
):
    raw = (await file.read()).decode("utf-8")
    title = file.filename.rsplit(".", 1)[0]

    with get_conn() as conn:
        cur = conn.cursor()
        if category_id is not None:
            # Reject a category_id belonging to a different tenant —
            # without this check, a document could be filed under
            # another tenant's category by id-guessing.
            cur.execute("SELECT id FROM category WHERE id = %s AND tenant_id = %s", (category_id, tenant_id))
            if cur.fetchone() is None:
                cur.close()
                raise HTTPException(status_code=400, detail="Invalid category")
        cur.execute(
            """INSERT INTO document (tenant_id, category_id, title, filename, raw_markdown, status)
               VALUES (%s, %s, %s, %s, %s, 'pending')""",
            (tenant_id, category_id, title, file.filename, raw),
        )
        document_id = cur.lastrowid
        cur.close()

    background_tasks.add_task(ingest_document, document_id)
    return DocumentOut(id=document_id, title=title, status="pending")


@router.get("", response_model=list[DocumentOut])
def list_documents(tenant_id: int = Depends(resolve_tenant_for_admin)):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            "SELECT id, title, status, error_message FROM document WHERE tenant_id = %s ORDER BY uploaded_at DESC",
            (tenant_id,),
        )
        rows = cur.fetchall()
        cur.close()
    return [DocumentOut(**row) for row in rows]


@router.post("/{document_id}/reindex", response_model=DocumentOut)
def reindex_document(document_id: int, background_tasks: BackgroundTasks, tenant_id: int = Depends(resolve_tenant_for_admin)):
    with get_conn() as conn:
        cur = conn.cursor()
        # Confirm the document belongs to this tenant BEFORE touching
        # anything. Without this, id-guessing document_id could delete
        # another tenant's document_chunk rows via the DELETE below.
        cur.execute("SELECT id FROM document WHERE id = %s AND tenant_id = %s", (document_id, tenant_id))
        if cur.fetchone() is None:
            cur.close()
            raise HTTPException(status_code=404, detail="Document not found")

        cur.execute("DELETE FROM document_chunk WHERE document_id = %s AND tenant_id = %s", (document_id, tenant_id))
        cur.execute(
            "UPDATE document SET status = 'pending', error_message = NULL WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        )
        cur.execute(
            "SELECT id, title, status, error_message FROM document WHERE id = %s AND tenant_id = %s",
            (document_id, tenant_id),
        )
        row = cur.fetchone()
        cur.close()

    background_tasks.add_task(ingest_document, document_id)
    return DocumentOut(**row)


@router.delete("/{document_id}")
def delete_document(document_id: int, tenant_id: int = Depends(resolve_tenant_for_admin)):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document WHERE id = %s AND tenant_id = %s", (document_id, tenant_id))
        deleted = cur.rowcount
        cur.close()
    if deleted == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    return {"ok": True}
