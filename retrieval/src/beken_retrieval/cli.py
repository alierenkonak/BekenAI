from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import tempfile
from pathlib import Path

from qdrant_client import QdrantClient

from beken_retrieval.bm25 import BM25LexicalRetriever
from beken_retrieval.config import RetrievalSettings, get_settings
from beken_retrieval.coordinator import DomainSearchCoordinator
from beken_retrieval.dense import create_dense_encoder
from beken_retrieval.evaluation import (
    evaluate,
    load_queries,
    load_report,
    quality_gate,
    write_report,
)
from beken_retrieval.model_catalog import ModelCatalog
from beken_retrieval.models import ChunkRecord, SearchFilters
from beken_retrieval.onnx_export import export_reranker
from beken_retrieval.postgres import PostgresCorpusRepository
from beken_retrieval.profile import RetrievalProfileCatalog
from beken_retrieval.qdrant_store import (
    QdrantDenseRetriever,
    QdrantIndexer,
    active_alias,
    collection_name,
)
from beken_retrieval.registry import FilesystemIndexRegistry, write_active_manifest
from beken_retrieval.remote_inference import RemoteDenseEncoder, RemoteInferenceClient
from beken_retrieval.scope import article_in_allowlist, load_scope
from beken_retrieval.tokenization import normalize_for_lexical_search


def _scope_path(settings: RetrievalSettings, value: Path) -> Path:
    return value if value.is_absolute() else settings.retrieval_scope_root / value


def _channel_root(settings: RetrievalSettings, *, domain: str, channel: str) -> Path:
    domain_root = settings.retrieval_index_root / domain
    return domain_root if channel == "primary" else domain_root / "channels" / channel


def _dense_encoder(settings: RetrievalSettings, spec):
    if settings.model_inference_url and settings.model_inference_token:
        client = RemoteInferenceClient(
            base_url=settings.model_inference_base_url,
            token=settings.model_inference_secret,
            timeout_seconds=settings.model_inference_timeout_seconds,
        )
        return RemoteDenseEncoder(spec, client)
    return create_dense_encoder(spec)


def register_scope(args: argparse.Namespace, settings: RetrievalSettings) -> int:
    scope = load_scope(_scope_path(settings, args.scope))
    PostgresCorpusRepository(settings.corpus_database_url).register_scope(scope)
    print(
        json.dumps(
            {
                "scope": scope.version,
                "status": scope.review_status,
                "manifest_hash": scope.manifest_hash,
            },
            ensure_ascii=False,
        )
    )
    return 0


def inspect_scope(args: argparse.Namespace, settings: RetrievalSettings) -> int:
    scope = load_scope(_scope_path(settings, args.scope))
    records = PostgresCorpusRepository(settings.corpus_database_url).load_scope_records(
        scope, require_reviewed=False
    )
    roles: dict[str, int] = {}
    for record in records:
        roles[record.domain_role] = roles.get(record.domain_role, 0) + 1
    print(
        json.dumps(
            {
                "scope": scope.version,
                "review_status": scope.review_status,
                "records": len(records),
                "roles": roles,
                "manifest_hash": scope.manifest_hash,
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_bm25(args: argparse.Namespace, settings: RetrievalSettings) -> int:
    scope_path = _scope_path(settings, args.scope).resolve()
    scope = load_scope(scope_path)
    scope.require_reviewed()
    repository = PostgresCorpusRepository(settings.corpus_database_url)
    repository.register_scope(scope)
    records = repository.load_scope_records(scope)
    # The records' content, not only their number: a metadata fix such as the article
    # labels gives a new index next to the active one instead of failing on it.
    digest = BM25LexicalRetriever.records_digest(records)
    version_seed = f"{scope.manifest_hash}:{digest}:bm25s:tr-legal-v1"
    index_version = hashlib.sha256(version_seed.encode()).hexdigest()[:16]
    channel_root = _channel_root(
        settings, domain=scope.domain, channel=scope.channel
    ).resolve()
    index_dir = channel_root / "bm25" / index_version
    retriever = BM25LexicalRetriever.build(records, index_dir, scope_hash=scope.manifest_hash)
    repository.register_index(
        scope=scope,
        backend="bm25s",
        model_id="bm25s",
        model_revision=str(retriever.manifest["backend_version"]),
        index_version=index_version,
        manifest=retriever.manifest,
    )
    active_path = write_active_manifest(
        settings.retrieval_index_root,
        domain=scope.domain,
        channel=scope.channel,
        updates={
            "domain": scope.domain,
            "channel": scope.channel,
            "scope_version": scope.version,
            "corpus_version": scope.corpus_version,
            "scope_path": os.path.relpath(scope_path, channel_root),
            "scope_hash": scope.manifest_hash,
            "index_version": index_version,
            "bm25_path": os.path.relpath(index_dir.resolve(), channel_root),
            "hybrid_candidate_limit": 25,
        },
    )
    print(
        json.dumps(
            {
                "index": str(index_dir),
                "active_manifest": str(active_path),
                "manifest": retriever.manifest,
            },
            ensure_ascii=False,
        )
    )
    return 0


def build_dense(args: argparse.Namespace, settings: RetrievalSettings) -> int:
    scope_path = _scope_path(settings, args.scope).resolve()
    scope = load_scope(scope_path)
    scope.require_reviewed()
    repository = PostgresCorpusRepository(settings.corpus_database_url)
    repository.register_scope(scope)
    records = repository.load_scope_records(scope)
    models = ModelCatalog.load(settings.retrieval_model_catalog)
    spec = models.get(args.model)
    if args.activate:
        RetrievalProfileCatalog.load(
            settings.retrieval_profile_catalog, models=models
        ).get(scope.domain).validate_selection(
            dense_model=args.model,
            reranker_model=args.reranker,
            candidate_limit=args.candidate_limit,
        )
    encoder = _dense_encoder(settings, spec)
    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_secret,
        timeout=60,
    )
    version_seed = f"{scope.manifest_hash}:{spec.revision}:{len(records)}"
    index_version = hashlib.sha256(version_seed.encode()).hexdigest()[:16]
    collection = collection_name(
        domain=scope.domain,
        corpus_version=scope.corpus_version,
        model_key=spec.key,
        index_version=index_version,
        channel=scope.channel,
    )
    indexer = QdrantIndexer(qdrant)
    summary = indexer.build_immutable(
        collection=collection,
        records=records,
        encoder=encoder,
        batch_size=args.batch_size,
    )
    # Alias is part of the immutable index metadata, but moving it is an explicit action.
    alias = active_alias(scope.domain, scope.channel)
    if args.activate:
        indexer.activate(collection=collection, alias=alias)
    repository.register_index(
        scope=scope,
        backend="qdrant_dense",
        model_id=spec.model_id,
        model_revision=spec.revision,
        index_version=index_version,
        manifest={
            "collection": collection,
            "alias": alias,
            "scope_hash": scope.manifest_hash,
            "model_key": spec.key,
            "model_revision": spec.revision,
            **summary,
        },
        activate=args.activate,
    )
    active_path = None
    if args.activate:
        active_path = write_active_manifest(
            settings.retrieval_index_root,
            domain=scope.domain,
            channel=scope.channel,
            updates={
                "domain": scope.domain,
                "channel": scope.channel,
                "scope_version": scope.version,
                "corpus_version": scope.corpus_version,
                "scope_path": os.path.relpath(
                    scope_path,
                    _channel_root(
                        settings, domain=scope.domain, channel=scope.channel
                    ).resolve(),
                ),
                "scope_hash": scope.manifest_hash,
                "index_version": index_version,
                "dense": {"collection": alias, "model_key": spec.key},
                "reranker_model_key": args.reranker,
                "hybrid_candidate_limit": args.candidate_limit,
            },
        )
    print(
        json.dumps(
            {
                "collection": collection,
                "alias": alias,
                "activated": args.activate,
                "active_manifest": str(active_path) if active_path else None,
                **summary,
            },
            ensure_ascii=False,
        )
    )
    return 0


def activate_dense(args: argparse.Namespace, settings: RetrievalSettings) -> int:
    scope_path = _scope_path(settings, args.scope).resolve()
    scope = load_scope(scope_path)
    scope.require_reviewed()
    repository = PostgresCorpusRepository(settings.corpus_database_url)
    records = repository.load_scope_records(scope)
    models = ModelCatalog.load(settings.retrieval_model_catalog)
    spec = models.get(args.model)
    RetrievalProfileCatalog.load(
        settings.retrieval_profile_catalog, models=models
    ).get(scope.domain).validate_selection(
        dense_model=args.model,
        reranker_model=args.reranker,
        candidate_limit=args.candidate_limit,
    )
    version_seed = f"{scope.manifest_hash}:{spec.revision}:{len(records)}"
    index_version = hashlib.sha256(version_seed.encode()).hexdigest()[:16]
    collection = collection_name(
        domain=scope.domain,
        corpus_version=scope.corpus_version,
        model_key=spec.key,
        index_version=index_version,
        channel=scope.channel,
    )
    qdrant = QdrantClient(
        url=settings.qdrant_url,
        api_key=settings.qdrant_secret,
        timeout=60,
    )
    if not qdrant.collection_exists(collection):
        raise ValueError(f"Dense collection is not built: {collection}")
    alias = active_alias(scope.domain, scope.channel)
    QdrantIndexer(qdrant).activate(collection=collection, alias=alias)
    repository.activate_index(
        domain=scope.domain,
        channel=scope.channel,
        backend="qdrant_dense",
        index_version=index_version,
    )
    active_path = write_active_manifest(
        settings.retrieval_index_root,
        domain=scope.domain,
        channel=scope.channel,
        updates={
            "domain": scope.domain,
            "channel": scope.channel,
            "scope_version": scope.version,
            "corpus_version": scope.corpus_version,
            "scope_path": os.path.relpath(
                scope_path,
                _channel_root(
                    settings, domain=scope.domain, channel=scope.channel
                ).resolve(),
            ),
            "scope_hash": scope.manifest_hash,
            "index_version": index_version,
            "dense": {"collection": alias, "model_key": spec.key},
            "reranker_model_key": args.reranker,
            "hybrid_candidate_limit": args.candidate_limit,
        },
    )
    print(
        json.dumps(
            {
                "collection": collection,
                "alias": alias,
                "active_manifest": str(active_path),
            },
            ensure_ascii=False,
        )
    )
    return 0


def _draft_relevance(expected_refs: list[str], record: ChunkRecord) -> int:
    """Reference-match hint, not semantic review; generated labels remain pending."""
    best = 0
    title = normalize_for_lexical_search(record.title)
    for reference in expected_refs:
        source, _, article_expression = reference.partition(":")
        source = source.strip()
        article_expression = article_expression.strip()
        if not source:
            continue
        folded_source = normalize_for_lexical_search(source)
        if folded_source == "yargıtay" and record.document_type == "court_decision":
            best = max(best, 1)
        elif folded_source == "yönetmelik" and record.document_type == "regulation":
            best = max(best, 1)
        elif source.isdigit():
            # Numbers in titles or related_legislation may only be citations.
            # Require the actual source identity before checking its provisions.
            if source != record.primary_legislation_number:
                continue
            if not article_expression or not record.article_labels:
                best = max(best, 1)
                continue
            expected_articles = tuple(
                value.strip().upper() for value in article_expression.split(",") if value.strip()
            )
            if any(
                article_in_allowlist(label, expected_articles) for label in record.article_labels
            ):
                return 2
        elif folded_source in title:
            # A matching document name alone cannot establish passage relevance.
            best = max(best, 1)
    return best


def _dense_collection(scope, spec, record_count: int) -> str:
    version_seed = f"{scope.manifest_hash}:{spec.revision}:{record_count}"
    index_version = hashlib.sha256(version_seed.encode()).hexdigest()[:16]
    return collection_name(
        domain=scope.domain,
        corpus_version=scope.corpus_version,
        model_key=spec.key,
        index_version=index_version,
        channel=scope.channel,
    )


def _pool_hits(system_hits: dict[str, list], *, rrf_k: int = 60) -> list[dict]:
    pooled: dict[str, dict] = {}
    for system_name, hits in system_hits.items():
        for rank, hit in enumerate(hits, start=1):
            item = pooled.setdefault(
                hit.record.chunk_id,
                {"record": hit.record, "pool_score": 0.0, "sources": []},
            )
            item["pool_score"] += 1.0 / (rrf_k + rank)
            item["sources"].append(
                {"system": system_name, "rank": rank, "score": float(hit.score)}
            )
    return sorted(
        pooled.values(),
        key=lambda item: (-item["pool_score"], item["record"].chunk_id),
    )


def draft_labels(args: argparse.Namespace, settings: RetrievalSettings) -> int:
    scope = load_scope(_scope_path(settings, args.scope))
    repository = PostgresCorpusRepository(settings.corpus_database_url)
    records = repository.load_scope_records(scope, require_reviewed=False)
    queries = [
        json.loads(line)
        for line in args.queries.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    with tempfile.TemporaryDirectory(prefix="beken-eval-draft-") as temporary:
        retriever = BM25LexicalRetriever.build(
            records,
            Path(temporary) / "bm25",
            scope_hash=scope.manifest_hash,
        )
        query_hits = [
            {
                "bm25": retriever.search(
                    str(query["query"]), filters=SearchFilters(), limit=args.candidates
                )
            }
            for query in queries
        ]
        dense_models = tuple(dict.fromkeys(args.dense_model or ()))
        if dense_models:
            catalog = ModelCatalog.load(settings.retrieval_model_catalog)
            qdrant = QdrantClient(
                url=settings.qdrant_url,
                api_key=settings.qdrant_secret,
                timeout=60,
            )
            for model_key in dense_models:
                spec = catalog.get(model_key)
                collection = _dense_collection(scope, spec, len(records))
                if not qdrant.collection_exists(collection):
                    raise ValueError(f"Dense collection is not built: {collection}")
                dense_retriever = QdrantDenseRetriever(
                    client=qdrant,
                    collection=collection,
                    encoder=create_dense_encoder(spec),
                    repository=repository,
                    scope=scope,
                )
                for query, system_hits in zip(queries, query_hits, strict=True):
                    system_hits[model_key] = dense_retriever.search(
                        str(query["query"]),
                        filters=SearchFilters(),
                        limit=args.candidates,
                    )
                del dense_retriever
                gc.collect()

        output: list[dict] = []
        for query, system_hits in zip(queries, query_hits, strict=True):
            pooled = _pool_hits(system_hits)
            expected_refs = [str(value) for value in query.get("expected_refs") or ()]
            query["labels"] = [
                {
                    "chunk_id": item["record"].chunk_id,
                    "relevance": _draft_relevance(expected_refs, item["record"]),
                    "review_status": "pending",
                    "candidate_rank": rank,
                    "candidate_score": item["pool_score"],
                    "candidate_sources": item["sources"],
                    "document_id": item["record"].document_id,
                    "parse_id": item["record"].parse_id,
                    "title": item["record"].title,
                    "document_type": item["record"].document_type,
                    "breadcrumb": list(item["record"].breadcrumb),
                    "article_labels": list(item["record"].article_labels),
                    "page_number": item["record"].page_number,
                    "exact_passage": item["record"].text,
                    "source_url": item["record"].source_url,
                }
                for rank, item in enumerate(pooled, start=1)
            ]
            has_exact_reference_candidate = any(
                label["relevance"] == 2 for label in query["labels"]
            )
            # A missing automatic reference match is not proof of a corpus gap. The
            # reviewer sets coverage_gap only after assessing the semantic candidates.
            query["coverage_gap"] = False
            query["coverage_review_status"] = (
                "candidate_match" if has_exact_reference_candidate else "needs_review"
            )
            query["candidate_systems"] = list(system_hits)
            output.append(query)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "".join(json.dumps(item, ensure_ascii=False, sort_keys=True) + "\n" for item in output),
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "queries": len(output),
                "output": str(args.output),
                "review_status": "pending",
            },
            ensure_ascii=False,
        )
    )
    return 0


def evaluate_index(args: argparse.Namespace, settings: RetrievalSettings) -> int:
    queries = load_queries(args.queries)
    coordinator = DomainSearchCoordinator(FilesystemIndexRegistry(settings))
    report = evaluate(
        coordinator,
        queries,
        mode=args.mode,
        limit=10,
    )
    report["system_name"] = args.system_name
    write_report(args.output, report)
    print(
        json.dumps(
            {
                "system_name": args.system_name,
                "eligible_queries": report["eligible_queries"],
                "recall_at_10": report["recall_at_10"],
                "ndcg_at_10": report["ndcg_at_10"],
                "output": str(args.output),
            },
            ensure_ascii=False,
        )
    )
    return 0


def check_quality_gate(args: argparse.Namespace, settings: RetrievalSettings) -> int:
    del settings
    reports: dict[str, dict] = {}
    for value in args.report:
        name, separator, path = value.partition("=")
        if not separator or not name or not path:
            raise ValueError("Report arguments must use NAME=PATH")
        reports[name] = load_report(Path(path))
    result = quality_gate(reports)
    if args.output:
        write_report(args.output, result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result["passed"] else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beken-retrieval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    register = subparsers.add_parser("register-scope")
    register.add_argument("scope", type=Path)
    register.set_defaults(handler=register_scope)

    inspect = subparsers.add_parser("inspect-scope")
    inspect.add_argument("scope", type=Path)
    inspect.set_defaults(handler=inspect_scope)

    bm25 = subparsers.add_parser("build-bm25")
    bm25.add_argument("scope", type=Path)
    bm25.set_defaults(handler=build_bm25)

    dense = subparsers.add_parser("build-dense")
    dense.add_argument("scope", type=Path)
    dense.add_argument("--model", choices=("multilingual-e5-base", "bge-m3"), required=True)
    dense.add_argument("--reranker", default="mmarco-minilm")
    dense.add_argument("--batch-size", type=int, default=8)
    dense.add_argument("--candidate-limit", type=int, choices=(20, 25, 30, 50), default=25)
    dense.add_argument(
        "--activate",
        action="store_true",
        help="Activate only if this build matches the tracked domain retrieval profile",
    )
    dense.set_defaults(handler=build_dense)

    activate = subparsers.add_parser("activate-dense")
    activate.add_argument("scope", type=Path)
    activate.add_argument("--model", choices=("multilingual-e5-base", "bge-m3"), required=True)
    activate.add_argument("--reranker", default="mmarco-minilm")
    activate.add_argument("--candidate-limit", type=int, choices=(20, 25, 30, 50), default=25)
    activate.set_defaults(handler=activate_dense)

    labels = subparsers.add_parser("draft-labels")
    labels.add_argument("scope", type=Path)
    labels.add_argument("queries", type=Path)
    labels.add_argument("output", type=Path)
    labels.add_argument("--candidates", type=int, choices=range(5, 21), default=10)
    labels.add_argument(
        "--dense-model",
        action="append",
        choices=("multilingual-e5-base", "bge-m3"),
        help="Add the top candidates from an already-built immutable dense collection",
    )
    labels.set_defaults(handler=draft_labels)

    benchmark = subparsers.add_parser("evaluate-index")
    benchmark.add_argument("queries", type=Path)
    benchmark.add_argument("output", type=Path)
    benchmark.add_argument("--system-name", required=True)
    benchmark.add_argument(
        "--mode", choices=("bm25", "vector", "hybrid", "hybrid_rerank"), required=True
    )
    benchmark.set_defaults(handler=evaluate_index)

    export = subparsers.add_parser(
        "export-reranker-onnx",
        help="Convert the pinned reranker to int8 ONNX for the model service",
    )
    export.add_argument("--model", default="bge-reranker-v2-m3")
    export.add_argument("--out", type=Path, required=True)
    export.set_defaults(handler=export_reranker_onnx)

    gate = subparsers.add_parser("quality-gate")
    gate.add_argument("--report", action="append", required=True)
    gate.add_argument("--output", type=Path)
    gate.set_defaults(handler=check_quality_gate)
    return parser


def export_reranker_onnx(args: argparse.Namespace, settings: RetrievalSettings) -> int:
    spec = ModelCatalog.load(settings.retrieval_model_catalog).get(args.model)
    path, digest = export_reranker(spec, args.out)
    # The catalog pins this path (relative to the artifact directory) and hash.
    print(json.dumps({"safe_artifact": path.relative_to(args.out).as_posix(), "sha256": digest}))
    return 0


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args, get_settings()))
    except Exception as exc:
        # Provider/driver messages can contain headers, signed URLs or credentials.
        print(
            f"Retrieval failed ({type(exc).__name__}); "
            "check configuration and service availability"
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
