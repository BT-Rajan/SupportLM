from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile
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
async def upload_document(file: UploadFile, background_tasks: BackgroundTasks, category_id: int | None = None):
    raw = (await file.read()).decode("utf-8")
    title = file.filename.rsplit(".", 1)[0]

    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute(
            """INSERT INTO document (category_id, title, filename, raw_markdown, status)
               VALUES (%s, %s, %s, %s, 'pending')""",
            (category_id, title, file.filename, raw),
        )
        document_id = cur.lastrowid
        cur.close()

    background_tasks.add_task(ingest_document, document_id)
    return DocumentOut(id=document_id, title=title, status="pending")


@router.get("", response_model=list[DocumentOut])
def list_documents():
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT id, title, status, error_message FROM document ORDER BY uploaded_at DESC")
        rows = cur.fetchall()
        cur.close()
    return [DocumentOut(**row) for row in rows]


@router.post("/{document_id}/reindex", response_model=DocumentOut)
def reindex_document(document_id: int, background_tasks: BackgroundTasks):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document_chunk WHERE document_id = %s", (document_id,))
        cur.execute(
            "UPDATE document SET status = 'pending', error_message = NULL WHERE id = %s",
            (document_id,),
        )
        cur.execute("SELECT id, title, status, error_message FROM document WHERE id = %s", (document_id,))
        row = cur.fetchone()
        cur.close()

    background_tasks.add_task(ingest_document, document_id)
    return DocumentOut(**row)


@router.delete("/{document_id}")
def delete_document(document_id: int):
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("DELETE FROM document WHERE id = %s", (document_id,))
        cur.close()
    return {"ok": True}
