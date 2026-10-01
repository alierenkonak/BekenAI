from __future__ import annotations

from dataclasses import dataclass
from typing import Literal
from urllib.parse import urlsplit

from beken_retrieval.models import SearchHit

from app.chat.temporal import ProvisionChange
from app.files.retrieval import PrivateHit
from app.web.search import WebHit

# File passages go in first, but may take at most this share of the context so the
# law they are compared against always fits too.
FILE_CONTEXT_TOKENS = 24_000


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
    # Official amendment notes of the articles this passage covers, newest first.
    changes: tuple[ProvisionChange, ...] = ()
    # A decision only: changes, after it was decided, to the articles it rests on.
    cited_changes: tuple[ProvisionChange, ...] = ()

    @property
    def is_decision(self) -> bool:
        record = self.hit.record
        return bool(record.case_number or record.decision_number)

    @property
    def amendments(self) -> str:
        return "\n".join(change.prompt_line for change in self.changes)

    @property
    def cited_amendments(self) -> str:
        return "\n".join(change.prompt_line for change in self.cited_changes)

    @property
    def passage(self) -> str:
        # The verifier sees the notes too, so "this paragraph changed in 2024" can be checked.
        text = self.hit.record.text
        if self.changes:
            text += f"\n\nResmî değişiklik notları:\n{self.amendments}"
        if self.cited_changes:
            text += (
                "\n\nKararın dayandığı maddelerde karardan sonra yapılan değişiklikler:\n"
                + self.cited_amendments
            )
        return text

    def citation_reference(self) -> dict:
        record = self.hit.record
        return {
            "source_scope": "global",
            "document_id": record.document_id,
            "parse_id": record.parse_id,
            "chunk_id": record.chunk_id,
            "file_id": None,
            "file_chunk_id": None,
        }

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
        block = "\n".join(metadata) + f"\n<passage>\n{record.text}\n</passage>"
        if self.changes:
            block += f"\n<amendments>\n{self.amendments}\n</amendments>"
        if self.cited_changes:
            tag = "cited_provision_changes"
            block += f"\n<{tag}>\n{self.cited_amendments}\n</{tag}>"
        return block

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
        } | (
            {"provision_changes": [change.snapshot() for change in self.changes]}
            if self.changes
            else {}
        ) | (
            {"cited_provision_changes": [change.snapshot() for change in self.cited_changes]}
            if self.cited_changes
            else {}
        )


@dataclass(frozen=True)
class FileEvidenceSource:
    """A passage of the user's own case file: evidence of what the file says, not of law."""

    source_id: str
    hit: PrivateHit
    index_version: str
    channel: Literal["file"] = "file"

    @property
    def passage(self) -> str:
        return self.hit.text

    def citation_reference(self) -> dict:
        return {
            "source_scope": "private",
            "document_id": None,
            "parse_id": None,
            "chunk_id": None,
            "file_id": str(self.hit.file_id),
            "file_chunk_id": str(self.hit.chunk_id),
        }

    @property
    def prompt_block(self) -> str:
        hit = self.hit
        metadata = [
            f"source_id={self.source_id}",
            "channel=file",
            # File names are user input; keep them on one metadata line.
            f"file_name={' '.join(hit.file_name.split())}",
            f"location={hit.location_label}",
            f"section={' '.join((hit.section_title or '').split())}",
        ]
        return "\n".join(metadata) + f"\n<case_file_passage>\n{hit.text}\n</case_file_passage>"

    def snapshot(self) -> dict:
        hit = self.hit
        return {
            "source_id": self.source_id,
            "source_scope": "private",
            "source_channel": "file",
            "file_id": str(hit.file_id),
            "file_chunk_id": str(hit.chunk_id),
            "title": hit.file_name,
            "section_title": hit.section_title,
            "page_start": hit.page_start,
            "page_end": hit.page_end,
            "paragraph_start": hit.paragraph_start,
            "paragraph_end": hit.paragraph_end,
            "location_label": hit.location_label,
            "exact_passage": hit.text,
            "index_version": self.index_version,
            # Shape shared with global snapshots so every client can render either.
            "document_id": None,
            "parse_id": None,
            "chunk_id": None,
            "authority": None,
            "decision_metadata": {
                "chamber": None,
                "case_number": None,
                "decision_number": None,
                "document_date": None,
            },
            "page_number": hit.page_start,
            "breadcrumb": [hit.section_title] if hit.section_title else [],
            "source_url": None,
            "corpus_version": None,
            "retrieval_scope_version": None,
        }


@dataclass(frozen=True)
class WebEvidenceSource:
    """Excerpts of a web page the user asked for: evidence of what the page says, not law."""

    source_id: str
    hit: WebHit
    index_version: str
    channel: Literal["web"] = "web"

    @property
    def passage(self) -> str:
        return self.hit.text

    def citation_reference(self) -> dict:
        return {
            "source_scope": "web",
            "document_id": None,
            "parse_id": None,
            "chunk_id": None,
            "file_id": None,
            "file_chunk_id": None,
        }

    @property
    def prompt_block(self) -> str:
        hit = self.hit
        metadata = [
            f"source_id={self.source_id}",
            "channel=web",
            f"site={hit.site}",
            # Page titles are third-party text; keep them on one metadata line.
            f"title={' '.join(hit.title.split())}",
            f"published={hit.published_date or ''}",
        ]
        return "\n".join(metadata) + f"\n<web_passage>\n{hit.text}\n</web_passage>"

    def snapshot(self) -> dict:
        hit = self.hit
        return {
            "source_id": self.source_id,
            "source_scope": "web",
            "source_channel": "web",
            "title": hit.title,
            "site": hit.site,
            "source_url": hit.url,
            "published_date": hit.published_date,
            "retrieved_on": hit.retrieved_on,
            "exact_passage": hit.text,
            "index_version": self.index_version,
            # Shape shared with corpus snapshots so every client can render either.
            "document_id": None,
            "parse_id": None,
            "chunk_id": None,
            "authority": None,
            "decision_metadata": {
                "chamber": None,
                "case_number": None,
                "decision_number": None,
                "document_date": None,
            },
            "page_number": None,
            "breadcrumb": [],
            "corpus_version": None,
            "retrieval_scope_version": None,
        }


def select_history(messages: list[dict], *, maximum_tokens: int = 24_000) -> list[dict]:
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
    files: list[FileEvidenceSource] | None = None,
    file_tokens: int = FILE_CONTEXT_TOKENS,
    web: list[WebEvidenceSource] | None = None,
) -> list[EvidenceSource | FileEvidenceSource | WebEvidenceSource]:
    selected: list[EvidenceSource | FileEvidenceSource | WebEvidenceSource] = []
    used = base_tokens
    file_limit = min(target_tokens, base_tokens + file_tokens)
    for source in files or []:
        cost = estimate_tokens(source.prompt_block)
        if used + cost > file_limit:
            continue
        selected.append(source)
        used += cost
    for source in [*primary, *(web or [])]:
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
