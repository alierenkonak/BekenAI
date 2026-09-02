from __future__ import annotations

from beken_retrieval.models import ChunkRecord, ContextText

CONTEXT_BUILDER_VERSION = "legal-context-v1"


def build_embedding_context(record: ChunkRecord) -> ContextText:
    breadcrumb = " > ".join(record.breadcrumb) or "Belirtilmemiş"
    header = "\n".join(
        (
            record.title,
            f"Domain: {record.domain_code}",
            f"Belge türü: {record.document_type}",
            f"Breadcrumb: {breadcrumb}",
            f"Section type: {record.section_type}",
        )
    )
    return ContextText(
        text=f"{header}\n\n{record.text}",
        exact_passage=record.text,
        context_builder_version=CONTEXT_BUILDER_VERSION,
    )
