from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from beken_retrieval.models import SearchHit


def estimate_tokens(text: str) -> int:
    # Conservative Turkish-text estimate. The hard budget must remain below the
    # provider limit even when punctuation and Unicode tokenize densely.
    return max(1, (len(text) + 1) // 2)


@dataclass(frozen=True)
class EvidenceSource:
    source_id: str
    channel: Literal["primary", "doctrine"]
    hit: SearchHit
    index_version: str

    @property
    def prompt_block(self) -> str:
        record = self.hit.record
        metadata = [
            f"source_id={self.source_id}",
            f"channel={self.channel}",
            f"title={record.title}",
            f"document_type={record.document_type}",
            f"authority={record.authority or ''}",
            f"date={record.document_date.isoformat() if record.document_date else ''}",
            f"breadcrumb={' > '.join(record.breadcrumb)}",
            f"page={record.page_number or ''}",
        ]
        return "\n".join(metadata) + f"\n<passage>\n{record.text}\n</passage>"

    def snapshot(self) -> dict:
        record = self.hit.record
        source_url = None
        if record.source_url:
            parts = urlsplit(record.source_url)
            if parts.scheme in {"http", "https"} and parts.netloc:
                source_url = record.source_url
        return {
            "source_id": self.source_id,
            "document_id": record.document_id,
            "parse_id": record.parse_id,
            "chunk_id": record.chunk_id,
            "source_scope": "global",
            "source_channel": self.channel,
            "title": record.title,
            "authority": record.authority,
            "decision_metadata": {
                "chamber": record.chamber,
                "case_number": record.case_number,
                "decision_number": record.decision_number,
                "document_date": record.document_date.isoformat() if record.document_date else None,
            },
            "page_number": record.page_number,
            "breadcrumb": list(record.breadcrumb),
            "exact_passage": record.text,
            "source_url": source_url,
            "corpus_version": record.corpus_version,
            "retrieval_scope_version": record.retrieval_scope_version,
            "index_version": self.index_version,
        }


def select_history(messages: list[dict], *, maximum_tokens: int = 16_000) -> list[dict]:
    selected: list[dict] = []
    used = 0
    for message in reversed(messages[-12:]):
        cost = estimate_tokens(message["content"])
        if used + cost > maximum_tokens:
            continue
        selected.append(message)
        used += cost
    return list(reversed(selected))


def select_sources(
    primary: list[EvidenceSource],
    doctrine: list[EvidenceSource],
    *,
    base_tokens: int,
    target_tokens: int,
    hard_tokens: int,
) -> list[EvidenceSource]:
    selected: list[EvidenceSource] = []
    used = base_tokens
    for source in primary:
        cost = estimate_tokens(source.prompt_block)
        if used + cost > target_tokens:
            continue
        selected.append(source)
        used += cost
    for source in doctrine:
        cost = estimate_tokens(source.prompt_block)
        if used + cost > hard_tokens:
            continue
        selected.append(source)
        used += cost
    return selected
