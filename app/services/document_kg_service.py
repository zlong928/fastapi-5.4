from __future__ import annotations

import re
from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.orm import Session, sessionmaker

from app.db.session import SessionLocal
from app.models import DocumentChunk, KgEntity, KgRelation


@dataclass(slots=True)
class KgExtractionResult:
    entity_count: int
    relation_count: int


@dataclass(slots=True)
class ExtractedTriple:
    subject: str
    predicate: str
    object: str
    evidence: str


class RuleBasedKgExtractor:
    _triple_pattern = re.compile(
        r"^\s*([A-Z][A-Za-z0-9_-]{1,80})\s+(created|supports|uses|contains|requires|extends|includes|produces)\s+([A-Za-z0-9_-]{1,80})\s*$"
    )

    def extract(self, text: str) -> list[ExtractedTriple]:
        triples: list[ExtractedTriple] = []
        for sentence in re.split(r"[.;]\s*", text):
            if not sentence.strip():
                continue
            match = self._triple_pattern.match(sentence.strip())
            if not match:
                continue
            subject = match.group(1).strip()
            predicate = match.group(2).strip().lower()
            object_text = match.group(3).strip()
            evidence = sentence.strip()
            if subject and object_text:
                triples.append(ExtractedTriple(subject, predicate, object_text, evidence))
        return triples


class DocumentKgService:
    def __init__(
        self,
        session_factory: sessionmaker[Session] = SessionLocal,
        extractor: RuleBasedKgExtractor | None = None,
    ) -> None:
        self.session_factory = session_factory
        self.extractor = extractor or RuleBasedKgExtractor()

    def extract_document(self, document_id: int) -> KgExtractionResult:
        with self.session_factory() as db:
            chunks = db.scalars(
                select(DocumentChunk)
                .where(DocumentChunk.document_id == document_id)
                .order_by(DocumentChunk.chunk_index)
            ).all()
            db.execute(delete(KgRelation).where(KgRelation.document_id == document_id))
            db.execute(delete(KgEntity).where(KgEntity.document_id == document_id))

            entities_by_name: dict[str, KgEntity] = {}
            relation_count = 0
            for chunk in chunks:
                for triple in self.extractor.extract(chunk.cleaned_text):
                    subject = self._entity_for(db, entities_by_name, document_id, chunk.id, triple.subject)
                    object_entity = self._entity_for(db, entities_by_name, document_id, chunk.id, triple.object)
                    db.add(
                        KgRelation(
                            document_id=document_id,
                            chunk_id=chunk.id,
                            subject_entity=subject,
                            object_entity=object_entity,
                            subject_text=triple.subject,
                            predicate=triple.predicate,
                            object_text=triple.object,
                            evidence_text=triple.evidence,
                            confidence=100,
                        )
                    )
                    relation_count += 1

            db.commit()
            return KgExtractionResult(entity_count=len(entities_by_name), relation_count=relation_count)

    def _entity_for(
        self,
        db: Session,
        entities_by_name: dict[str, KgEntity],
        document_id: int,
        chunk_id: int,
        name: str,
    ) -> KgEntity:
        normalized = name.strip().lower()
        existing = entities_by_name.get(normalized)
        if existing is not None:
            return existing
        entity = KgEntity(
            document_id=document_id,
            chunk_id=chunk_id,
            name=name.strip(),
            normalized_name=normalized,
            entity_type="term",
        )
        db.add(entity)
        entities_by_name[normalized] = entity
        return entity
