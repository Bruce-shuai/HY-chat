from __future__ import annotations

import hashlib
from pathlib import Path

from langchain_text_splitters import RecursiveCharacterTextSplitter
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.cache.service import cache
from app.core.config import get_settings
from app.core.constants import FILE_IO_CHUNK_BYTES
from app.core.types import JsonObject
from app.db.models import KnowledgeChunk, KnowledgeDocument
from app.rag.embeddings import EmbeddingService
from app.rag.loaders import load_document

settings = get_settings()


class RagService:
    def __init__(self, db: Session, user_id: str | None = None):
        self.db = db
        self.user_id = user_id
        self.embeddings = EmbeddingService()
        self.splitter = RecursiveCharacterTextSplitter(
            chunk_size=settings.rag_chunk_size,
            chunk_overlap=settings.rag_chunk_overlap,
            separators=["\n\n", "\n", "。", "！", "？", ". ", " ", ""],
        )

    @staticmethod
    def _sha256(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as file:
            for block in iter(lambda: file.read(FILE_IO_CHUNK_BYTES), b""):
                digest.update(block)
        return digest.hexdigest()

    def ingest_file(
        self,
        path: str | Path,
        filename: str,
        content_type: str | None = None,
        metadata: JsonObject | None = None,
        stored_file_id: str | None = None,
    ) -> KnowledgeDocument:
        file_path = Path(path)
        sha256 = self._sha256(file_path)
        existing = self.db.scalar(
            select(KnowledgeDocument).where(
                KnowledgeDocument.sha256 == sha256,
                KnowledgeDocument.user_id == self.user_id,
            )
        )
        if existing and existing.status != "failed":
            if file_path != Path(existing.file_path):
                file_path.unlink(missing_ok=True)
            return existing
        if existing:
            self.db.delete(existing)
            self.db.commit()

        document = KnowledgeDocument(
            user_id=self.user_id,
            stored_file_id=stored_file_id,
            filename=filename,
            content_type=content_type,
            file_path=str(file_path),
            sha256=sha256,
            status="processing",
            extra_metadata=metadata or {},
        )
        self.db.add(document)
        self.db.commit()
        self.db.refresh(document)

        try:
            sections = load_document(file_path)
            chunks: list[tuple[str, JsonObject]] = []
            for section in sections:
                for text in self.splitter.split_text(section.text):
                    if text.strip():
                        chunks.append(
                            (
                                text,
                                {
                                    **(metadata or {}),
                                    **section.metadata,
                                    "source": filename,
                                },
                            )
                        )

            vectors = self.embeddings.embed_documents([text for text, _ in chunks])
            for index, ((text, chunk_metadata), vector) in enumerate(
                zip(chunks, vectors, strict=True)
            ):
                self.db.add(
                    KnowledgeChunk(
                        document_id=document.id,
                        chunk_index=index,
                        content=text,
                        extra_metadata=chunk_metadata,
                        embedding=vector,
                    )
                )
            document.status = "ready"
            document.chunk_count = len(chunks)
            self.db.commit()
            cache.delete_pattern("rag:query:*")
            return document
        except Exception as exc:
            document.status = "failed"
            document.error_message = str(exc)
            self.db.commit()
            raise

    def search(
        self,
        query: str,
        top_k: int | None = None,
        document_ids: list[str] | None = None,
    ) -> list[JsonObject]:
        limit = max(1, min(top_k or settings.rag_top_k, 20))
        cache_key = (
            f"rag:query:{cache.digest(self.user_id, query, limit, document_ids or [])}"
        )
        cached = cache.get_json(cache_key)
        if cached is not None:
            return cached

        query_vector = self.embeddings.embed_query(query)
        distance = KnowledgeChunk.embedding.cosine_distance(query_vector).label(
            "distance"
        )
        statement = (
            select(KnowledgeChunk, KnowledgeDocument, distance)
            .join(KnowledgeDocument, KnowledgeChunk.document_id == KnowledgeDocument.id)
            .where(KnowledgeDocument.status == "ready")
            .order_by(distance)
            .limit(limit)
        )
        if self.user_id:
            statement = statement.where(KnowledgeDocument.user_id == self.user_id)
        if document_ids:
            statement = statement.where(KnowledgeChunk.document_id.in_(document_ids))

        rows = self.db.execute(statement).all()
        results = [
            {
                "chunk_id": chunk.id,
                "document_id": document.id,
                "filename": document.filename,
                "content": chunk.content,
                "metadata": chunk.extra_metadata,
                "score": round(max(0.0, 1.0 - float(row_distance)), 6),
            }
            for chunk, document, row_distance in rows
        ]
        cache.set_json(cache_key, results, ttl=300)
        return results

    def list_documents(self) -> list[KnowledgeDocument]:
        return list(
            self.db.scalars(
                select(KnowledgeDocument)
                .where(KnowledgeDocument.user_id == self.user_id)
                .order_by(KnowledgeDocument.created_at.desc())
            ).all()
        )

    def delete_document(self, document_id: str) -> bool:
        document = self.db.get(KnowledgeDocument, document_id)
        if not document or document.user_id != self.user_id:
            return False
        file_path = Path(document.file_path)
        self.db.delete(document)
        self.db.commit()
        file_path.unlink(missing_ok=True)
        cache.delete_pattern("rag:query:*")
        return True
