import json

from app.core.llm_client import embed_text
from app.db.pool import get_conn
from app.services.chunking import chunk_markdown
from app.core.config import settings


def ingest_document(document_id: int) -> None:
    """Chunk a document's markdown, embed each chunk, store both. Marks
    the document 'ready' on success or 'error' with a message on failure.

    tenant_id isn't passed in — it's read from the document row itself
    (documents already have it, set at creation in app/api/documents.py)
    and threaded onto every document_chunk/embedding row this writes,
    since those columns are NOT NULL as of the 1.3 backfill.

    Note on transaction handling: get_conn() rolls back the whole
    transaction on any exception. If we let an ingestion failure
    propagate without committing first, the 'error' status update
    itself would get rolled back too — leaving the document stuck at
    whatever status it had before (e.g. 'pending' forever, with no
    visible error). So each status transition below commits explicitly
    before any further work that might fail.
    """
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT tenant_id, raw_markdown FROM document WHERE id = %s", (document_id,))
        row = cur.fetchone()
        if not row:
            cur.close()
            return
        tenant_id = row["tenant_id"]

        cur.execute("UPDATE document SET status = 'processing' WHERE id = %s", (document_id,))
        conn.commit()  # persist 'processing' immediately, independent of what follows

        try:
            chunks = chunk_markdown(row["raw_markdown"])
            for idx, chunk in enumerate(chunks):
                cur.execute(
                    """INSERT INTO document_chunk
                       (tenant_id, document_id, chunk_index, heading_path, content, token_count)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (tenant_id, document_id, idx, chunk.heading_path, chunk.content, len(chunk.content) // 4),
                )
                chunk_id = cur.lastrowid

                vector = embed_text(chunk.content)
                cur.execute(
                    """INSERT INTO embedding (tenant_id, chunk_id, model, dims, embedding_vector)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (tenant_id, chunk_id, settings.embedding_model_name, len(vector), json.dumps(vector)),
                )

            cur.execute(
                "UPDATE document SET status = 'ready', processed_at = NOW() WHERE id = %s",
                (document_id,),
            )
            conn.commit()
        except Exception as exc:
            conn.rollback()  # discard any partial chunk/embedding inserts from this attempt
            cur.execute(
                "UPDATE document SET status = 'error', error_message = %s WHERE id = %s",
                (str(exc)[:1000], document_id),
            )
            conn.commit()  # persist the error status durably
            raise
        finally:
            cur.close()
