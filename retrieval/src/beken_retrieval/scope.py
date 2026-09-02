from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from beken_retrieval.models import ChunkRecord


@dataclass(frozen=True)
class RetrievalScope:
    path: Path
    payload: dict[str, Any]
    manifest_hash: str

    @property
    def version(self) -> str:
        return str(self.payload["version"])

    @property
    def domain(self) -> str:
        return str(self.payload["domain"])

    @property
    def corpus_version(self) -> str:
        return str(self.payload["corpus_version"])

    @property
    def channel(self) -> str:
        return str(self.payload.get("channel") or "primary")

    @property
    def review_status(self) -> str:
        return str(self.payload.get("review_status") or "draft")

    def allows(self, record: ChunkRecord) -> bool:
        if record.domain_code != self.domain or record.corpus_version != self.corpus_version:
            return False
        if not record.retrieval_eligible:
            return False
        roles = self.payload.get("roles") or {}
        role_rule = roles.get(record.domain_role) or {}
        if role_rule.get("include") is False:
            return False
        if role_rule.get("mode") == "full_document":
            return True
        if role_rule.get("mode") != "provision_allowlist":
            return False
        return self._supplemental_rule_allows(record)

    def require_reviewed(self) -> None:
        if self.review_status != "reviewed":
            raise ValueError(f"Retrieval scope {self.version!r} needs user review before indexing")

    def _supplemental_rule_allows(self, record: ChunkRecord) -> bool:
        rules = self.payload.get("supplemental_allowlist") or []
        for rule in rules:
            if (
                rule.get("source_document_id")
                and rule["source_document_id"] != record.source_document_id
            ):
                continue
            legislation_number = str(rule.get("legislation_number") or "")
            if legislation_number:
                if record.primary_legislation_number:
                    if legislation_number != record.primary_legislation_number:
                        continue
                elif legislation_number not in record.legislation_numbers:
                    continue
            articles = tuple(str(value) for value in rule.get("articles") or ())
            if "*" in articles:
                return True
            if any(article_in_allowlist(label, articles) for label in record.article_labels):
                return True
        return False


def article_in_allowlist(label: str, entries: tuple[str, ...]) -> bool:
    normalized = label.strip().upper()
    for entry in entries:
        candidate = entry.strip().upper()
        if candidate == normalized:
            return True
        if "-" not in candidate or not normalized.isdigit():
            continue
        start, end = candidate.split("-", 1)
        if start.isdigit() and end.isdigit() and int(start) <= int(normalized) <= int(end):
            return True
    return False


def load_scope(path: Path) -> RetrievalScope:
    raw = path.read_bytes()
    payload = json.loads(raw)
    required = {"version", "domain", "corpus_version", "roles"}
    missing = sorted(required.difference(payload))
    if missing:
        raise ValueError(f"Retrieval scope is missing fields: {missing}")
    return RetrievalScope(
        path=path,
        payload=payload,
        manifest_hash=hashlib.sha256(raw).hexdigest(),
    )
