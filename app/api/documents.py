from fastapi import APIRouter, BackgroundTasks, UploadFile
from pydantic import BaseModel

from app.db.pool import get_conn
from app.services.ingestion import ingest_document

router = APIRouter(prefix="/api/documents", tags=["documents"])


class DocumentOut(BaseModel):
    id: int
    title: str
    status: str


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
        cur.execute("SELECT id, title, status FROM document ORDER BY uploaded_at DESC")
        rows = cur.fetchall()
        cur.close()
    return [DocumentOut(**row) for row in rows]
