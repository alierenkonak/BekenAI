from __future__ import annotations

from beken_retrieval.models import ChunkRecord, SearchFilters


def matches_filters(record: ChunkRecord, filters: SearchFilters) -> bool:
    if filters.document_types and record.document_type not in filters.document_types:
        return False
    if filters.authorities and record.authority not in filters.authorities:
        return False
    if filters.chambers and record.chamber not in filters.chambers:
        return False
    if filters.date_from and (
        record.document_date is None or record.document_date < filters.date_from
    ):
        return False
    if filters.date_to and (record.document_date is None or record.document_date > filters.date_to):
        return False
    if filters.legislation_numbers and not set(filters.legislation_numbers).intersection(
        record.legislation_numbers
    ):
        return False
    if filters.article_labels and not set(filters.article_labels).intersection(
        record.article_labels
    ):
        return False
    if filters.section_types and record.section_type not in filters.section_types:
        return False
    return not filters.domain_roles or record.domain_role in filters.domain_roles
