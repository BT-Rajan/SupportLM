import json

from app.core.llm_client import embed_text
from app.db.pool import get_conn
from app.services.chunking import chunk_markdown


def ingest_document(document_id: int) -> None:
    """Chunk a document's markdown, embed each chunk, store both. Marks
    the document 'ready' on success or 'error' with a message on failure."""
    with get_conn() as conn:
        cur = conn.cursor()
        cur.execute("SELECT raw_markdown FROM document WHERE id = %s", (document_id,))
        row = cur.fetchone()
        if not row:
            cur.close()
            return

        cur.execute(
            "UPDATE document SET status = 'processing' WHERE id = %s", (document_id,)
        )

        try:
            chunks = chunk_markdown(row["raw_markdown"])
            for idx, chunk in enumerate(chunks):
                cur.execute(
                    """INSERT INTO document_chunk
                       (document_id, chunk_index, heading_path, content, token_count)
                       VALUES (%s, %s, %s, %s, %s)""",
                    (document_id, idx, chunk.heading_path, chunk.content, len(chunk.content) // 4),
                )
                chunk_id = cur.lastrowid

                vector = embed_text(chunk.content)
                cur.execute(
                    """INSERT INTO embedding (chunk_id, model, dims, embedding_vector)
                       VALUES (%s, %s, %s, %s)""",
                    (chunk_id, "text-embedding-3-small", len(vector), json.dumps(vector)),
                )

            cur.execute(
                "UPDATE document SET status = 'ready', processed_at = NOW() WHERE id = %s",
                (document_id,),
            )
        except Exception as exc:
            cur.execute(
                "UPDATE document SET status = 'error', error_message = %s WHERE id = %s",
                (str(exc), document_id),
            )
            raise
        finally:
            cur.close()
