from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from functools import partial
from pathlib import Path

import bm25s
from bm25s.tokenization import Tokenizer

from beken_retrieval.filters import matches_filters
from beken_retrieval.models import ChunkRecord, SearchFilters, SearchHit
from beken_retrieval.tokenization import (
    TOKENIZER_VERSION,
    canonical_token_string,
    lexical_tokens,
    tokenize_legal_text,
)

_RECORDS_FILE = "records.jsonl"
_MANIFEST_FILE = "manifest.json"


def _splitter(value: str) -> list[str]:
    return tokenize_legal_text(value)


def _splitter_for(stemming: str | None) -> Callable[[str], list[str]]:
    """The index's own tokenizer: a query must be stemmed as its index was built."""
    if not stemming:
        return _splitter
    lexical_tokens("", stemming)  # rejects an unknown method before anything is built
    return partial(lexical_tokens, stemming=stemming)


class BM25LexicalRetriever:
    def __init__(
        self,
        retriever: bm25s.BM25,
        tokenizer: Tokenizer,
        records: list[ChunkRecord],
        manifest: dict,
    ) -> None:
        self.retriever = retriever
        self.tokenizer = tokenizer
        self.records = records
        self.manifest = manifest

    @staticmethod
    def records_digest(records: list[ChunkRecord]) -> str:
        """The SHA-256 of the records file a build writes, before it is written."""
        digest = hashlib.sha256()
        for record in records:
            digest.update(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True).encode())
            digest.update(b"\n")
        return digest.hexdigest()

    @classmethod
    def build(
        cls,
        records: list[ChunkRecord],
        index_dir: Path,
        *,
        scope_hash: str,
        stemming: str | None = None,
    ) -> BM25LexicalRetriever:
        if not records:
            raise ValueError("Cannot build a BM25 index from an empty corpus")
        if index_dir.exists() and any(index_dir.iterdir()):
            raise FileExistsError(f"Immutable BM25 index already exists: {index_dir}")
        index_dir.mkdir(parents=True, exist_ok=True)

        tokenizer = Tokenizer(
            lower=False, stemmer=None, stopwords=[], splitter=_splitter_for(stemming)
        )
        tokenized = tokenizer.tokenize([record.text for record in records])
        retriever = bm25s.BM25(method="lucene", k1=1.2, b=0.75)
        retriever.index(tokenized, show_progress=False)
        retriever.save(index_dir)
        tokenizer.save_vocab(index_dir)
        tokenizer.save_stopwords(index_dir)

        records_path = index_dir / _RECORDS_FILE
        with records_path.open("w", encoding="utf-8") as handle:
            for record in records:
                handle.write(json.dumps(record.to_dict(), ensure_ascii=False, sort_keys=True))
                handle.write("\n")
        corpus_hash = hashlib.sha256(records_path.read_bytes()).hexdigest()
        manifest = {
            "backend": "bm25s",
            "backend_version": getattr(bm25s, "__version__", "unknown"),
            "tokenizer_version": TOKENIZER_VERSION,
            "stemming": stemming or False,
            "stopwords": False,
            "record_count": len(records),
            "domain": records[0].domain_code,
            "corpus_version": records[0].corpus_version,
            "retrieval_scope_version": records[0].retrieval_scope_version,
            "scope_hash": scope_hash,
            "corpus_hash": corpus_hash,
        }
        manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True).encode()
        manifest["index_hash"] = hashlib.sha256(manifest_bytes).hexdigest()
        (index_dir / _MANIFEST_FILE).write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return cls(retriever, tokenizer, records, manifest)

    @classmethod
    def load(cls, index_dir: Path, *, mmap: bool = True) -> BM25LexicalRetriever:
        manifest = json.loads((index_dir / _MANIFEST_FILE).read_text(encoding="utf-8"))
        records = [
            ChunkRecord.from_dict(json.loads(line))
            for line in (index_dir / _RECORDS_FILE).read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        expected_hash = hashlib.sha256((index_dir / _RECORDS_FILE).read_bytes()).hexdigest()
        if expected_hash != manifest["corpus_hash"]:
            raise ValueError("BM25 corpus hash does not match its manifest")
        tokenizer = Tokenizer(
            lower=False,
            stemmer=None,
            stopwords=[],
            splitter=_splitter_for(manifest.get("stemming") or None),
        )
        tokenizer.load_vocab(index_dir)
        tokenizer.load_stopwords(index_dir)
        retriever = bm25s.BM25.load(index_dir, mmap=mmap, load_corpus=False)
        return cls(retriever, tokenizer, records, manifest)

    def article_records(
        self, legislation_number: str, article_label: str, *, filters: SearchFilters, limit: int
    ) -> list[ChunkRecord]:
        """The chunks of one article of one law, in reading order: a lookup, not a search.

        The law is the chunk's own; `legislation_numbers` also lists the laws it refers to.
        """
        found: list[ChunkRecord] = []
        for record in self.records:
            if (
                record.primary_legislation_number == legislation_number
                and article_label in record.article_labels
                and matches_filters(record, filters)
            ):
                found.append(record)
                if len(found) == limit:
                    break
        return found

    def search(self, query: str, *, filters: SearchFilters, limit: int) -> list[SearchHit]:
        if not query.strip() or limit <= 0:
            return []
        candidate_limit = min(len(self.records), max(200, limit * 20))
        tokenized = self.tokenizer.tokenize([canonical_token_string(query)], update_vocab=False)
        indices, scores = self.retriever.retrieve(
            tokenized,
            k=candidate_limit,
            show_progress=False,
        )
        hits: list[SearchHit] = []
        for position, raw_index in enumerate(indices[0]):
            record = self.records[int(raw_index)]
            score = float(scores[0][position])
            if score <= 0:
                continue
            if not matches_filters(record, filters):
                continue
            hits.append(
                SearchHit(
                    record=record,
                    score=score,
                    rank=len(hits) + 1,
                    score_breakdown={"bm25": score},
                )
            )
            if len(hits) == limit:
                break
        return hits
