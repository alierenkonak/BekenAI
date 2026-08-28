from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from beken_ingestion.adapters import (
    LocalFileAdapter,
    MevzuatAdapter,
    SourceAccessBlocked,
    SourceAdapterError,
    SourceDocumentFailure,
    YargitayAdapter,
)
from beken_ingestion.chunking import PARSER_VERSION
from beken_ingestion.config import IngestionSettings, get_settings
from beken_ingestion.database import CorpusRepository
from beken_ingestion.models import RawDocument
from beken_ingestion.normalization import stable_hash
from beken_ingestion.pipeline import IngestionPipeline
from beken_ingestion.storage import FilesystemRawStorage, RawStorage, SupabaseRawStorage


def _manifest(path: Path) -> tuple[dict[str, Any], bytes]:
    payload = path.read_bytes()
    return json.loads(payload), payload


def _validate_manifest(manifest: dict[str, Any]) -> None:
    if manifest.get("parser_version") != PARSER_VERSION:
        raise ValueError(f"Manifest must declare parser_version={PARSER_VERSION!r}")
    for source in manifest.get("sources", []):
        metadata = source.get("metadata") or {}
        if metadata.get("source_kind") != "legislation":
            continue
        expectations = (metadata.get("domain_metadata") or {}).get(
            "article_expectations"
        )
        source_id = source.get("source_document_id") or "<unknown>"
        if not isinstance(expectations, dict):
            raise ValueError(f"Legislation source {source_id!r} needs article_expectations")
        start = expectations.get("required_numeric_start")
        end = expectations.get("required_numeric_end")
        if not isinstance(start, int) or not isinstance(end, int) or start < 1 or end < start:
            raise ValueError(f"Legislation source {source_id!r} has invalid article_expectations")


def _storage(settings: IngestionSettings, backend: str) -> RawStorage:
    if backend == "local":
        return FilesystemRawStorage(settings.local_raw_storage_path)
    project_url, secret_key = settings.require_supabase()
    storage = SupabaseRawStorage(
        project_url,
        secret_key,
        settings.supabase_storage_bucket,
        timeout_seconds=settings.source_timeout_seconds,
    )
    storage.ensure_private_bucket()
    return storage


def _close_storage(storage: RawStorage) -> None:
    close = getattr(storage, "close", None)
    if close:
        close()


def _target_source_metadata(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {
        str(source["source_document_id"]): dict(source.get("metadata") or {})
        for source in manifest.get("sources", [])
        if source.get("source_document_id")
    }


def _merge_reparse_metadata(
    artifact: dict[str, Any], target_metadata: dict[str, Any] | None
) -> dict[str, Any]:
    metadata = {
        key: artifact[key]
        for key in (
            "source_kind",
            "document_type",
            "domain",
            "title",
            "authority",
            "chamber",
            "case_number",
            "decision_number",
            "document_date",
            "effective_from",
            "effective_to",
            "related_legislation",
            "domain_metadata",
        )
        if artifact.get(key) is not None
    }
    if not target_metadata:
        return metadata
    merged = {**metadata, **target_metadata}
    merged["domain_metadata"] = {
        **dict(metadata.get("domain_metadata") or {}),
        **dict(target_metadata.get("domain_metadata") or {}),
    }
    return merged


def bootstrap_storage(args: argparse.Namespace, settings: IngestionSettings) -> int:
    del args
    project_url, secret_key = settings.require_supabase()
    with SupabaseRawStorage(
        project_url,
        secret_key,
        settings.supabase_storage_bucket,
        timeout_seconds=settings.source_timeout_seconds,
    ) as storage:
        storage.ensure_private_bucket()
    print(f"Private bucket ready: {settings.supabase_storage_bucket}")
    return 0


def import_manifest(args: argparse.Namespace, settings: IngestionSettings) -> int:
    manifest, raw_manifest = _manifest(args.manifest)
    _validate_manifest(manifest)
    repository = CorpusRepository(settings.metadata_database_url)
    version = str(manifest["version"])
    repository.upsert_corpus_version(version, stable_hash(raw_manifest), manifest)
    run_id = repository.start_run("mevzuat", version)
    storage = _storage(settings, args.storage)
    pipeline = IngestionPipeline(repository, storage)
    failures = 0
    try:
        with MevzuatAdapter(
            timeout_seconds=settings.source_timeout_seconds,
            rate_limit_seconds=settings.source_rate_limit_seconds,
            max_attempts=settings.source_max_attempts,
        ) as adapter:
            for index, source in enumerate(manifest.get("sources", []), start=1):
                if source.get("adapter") != "mevzuat":
                    continue
                try:
                    raw = adapter.fetch(source)
                    outcome = pipeline.ingest(raw, version)
                    repository.checkpoint_run(
                        run_id,
                        {"source_index": index, "source_document_id": raw.source_document_id},
                        discovered_delta=1,
                        duplicate_delta=int(outcome.duplicate_document),
                        imported_delta=int(not outcome.duplicate_document),
                    )
                except Exception as exc:
                    failures += 1
                    repository.record_error(
                        run_id,
                        None,
                        type(exc).__name__,
                        str(exc),
                        retryable=True,
                        attempt=settings.source_max_attempts,
                        source_url=str(source.get("url") or "") or None,
                        source_document_id=str(source.get("source_document_id") or "") or None,
                    )
                    repository.checkpoint_run(
                        run_id,
                        {"source_index": index},
                        discovered_delta=1,
                        failed_delta=1,
                    )
        repository.finish_run(run_id, "failed" if failures else "completed")
    except Exception as exc:
        repository.finish_run(
            run_id, "failed", error_code=type(exc).__name__, error_detail=str(exc)
        )
        raise
    finally:
        _close_storage(storage)
    if failures:
        print(f"Manifest import failed for {failures} source(s): run={run_id}", file=sys.stderr)
        return 1
    print(f"Manifest import completed: run={run_id} corpus={version}")
    return 0


def import_yargitay(args: argparse.Namespace, settings: IngestionSettings) -> int:
    repository = CorpusRepository(settings.metadata_database_url)
    run_id = args.resume_run or repository.start_run("yargitay", args.corpus_version)
    checkpoint = repository.get_checkpoint(run_id) if args.resume_run else {}
    start_page = int(checkpoint.get("page", 1))
    storage = _storage(settings, args.storage)
    pipeline = IngestionPipeline(repository, storage)
    failures = 0
    try:
        with YargitayAdapter(
            timeout_seconds=settings.source_timeout_seconds,
            rate_limit_seconds=settings.source_rate_limit_seconds,
            max_attempts=settings.source_max_attempts,
        ) as adapter:
            for item, next_checkpoint in adapter.search(
                args.query,
                page_size=args.page_size,
                start_page=start_page,
                max_documents=args.max_documents,
            ):
                if isinstance(item, SourceDocumentFailure):
                    failures += 1
                    repository.record_error(
                        run_id,
                        None,
                        item.error_code,
                        item.error_detail,
                        retryable=item.retryable,
                        attempt=settings.source_max_attempts,
                        source_url=item.source_url,
                        source_document_id=item.source_document_id,
                    )
                    repository.checkpoint_run(
                        run_id,
                        next_checkpoint,
                        discovered_delta=1,
                        failed_delta=1,
                    )
                    continue
                raw = item
                try:
                    outcome = pipeline.ingest(raw, args.corpus_version)
                    repository.checkpoint_run(
                        run_id,
                        next_checkpoint,
                        discovered_delta=1,
                        duplicate_delta=int(outcome.duplicate_document),
                        imported_delta=int(not outcome.duplicate_document),
                    )
                except Exception as exc:
                    failures += 1
                    repository.record_error(
                        run_id,
                        raw,
                        type(exc).__name__,
                        str(exc),
                        retryable=False,
                        attempt=1,
                    )
                    repository.checkpoint_run(run_id, next_checkpoint, failed_delta=1)
        repository.finish_run(run_id, "failed" if failures else "completed")
    except SourceAccessBlocked as exc:
        repository.finish_run(
            run_id, "blocked", error_code=type(exc).__name__, error_detail=str(exc)
        )
        print(str(exc), file=sys.stderr)
        return 2
    except SourceAdapterError as exc:
        repository.record_error(
            run_id,
            None,
            type(exc).__name__,
            str(exc),
            retryable=True,
            attempt=settings.source_max_attempts,
            source_url="https://karararama.yargitay.gov.tr/",
            source_document_id=args.query,
        )
        repository.finish_run(
            run_id, "failed", error_code=type(exc).__name__, error_detail=str(exc)
        )
        print(str(exc), file=sys.stderr)
        return 1
    except Exception as exc:
        repository.finish_run(
            run_id, "failed", error_code=type(exc).__name__, error_detail=str(exc)
        )
        raise
    finally:
        _close_storage(storage)
    print(f"Yargıtay import completed: run={run_id} failures={failures}")
    return 1 if failures else 0


def import_file(args: argparse.Namespace, settings: IngestionSettings) -> int:
    metadata = json.loads(args.metadata)
    raw = LocalFileAdapter().fetch(args.path, metadata)
    repository = CorpusRepository(settings.metadata_database_url)
    storage = _storage(settings, args.storage)
    try:
        outcome = IngestionPipeline(repository, storage).ingest(raw, args.corpus_version)
    finally:
        _close_storage(storage)
    print(json.dumps(outcome.__dict__, ensure_ascii=False))
    return 0


def import_directory(args: argparse.Namespace, settings: IngestionSettings) -> int:
    metadata = json.loads(args.metadata)
    paths = sorted(
        path
        for path in args.directory.rglob("*")
        if path.is_file() and path.suffix.casefold() in {".pdf", ".html", ".htm", ".txt"}
    )
    if not paths:
        raise ValueError("No supported PDF, HTML or text files found")

    repository = CorpusRepository(settings.metadata_database_url)
    run_id = repository.start_run("manual_directory", args.corpus_version)
    storage = _storage(settings, args.storage)
    pipeline = IngestionPipeline(repository, storage)
    adapter = LocalFileAdapter()
    failures = 0
    try:
        for index, path in enumerate(paths, start=1):
            raw = None
            try:
                raw = adapter.fetch(path, metadata)
                outcome = pipeline.ingest(raw, args.corpus_version)
                repository.checkpoint_run(
                    run_id,
                    {"file_index": index, "file_name": path.name},
                    discovered_delta=1,
                    duplicate_delta=int(outcome.duplicate_document),
                    imported_delta=int(not outcome.duplicate_document),
                )
            except Exception as exc:
                failures += 1
                repository.record_error(
                    run_id,
                    raw,
                    type(exc).__name__,
                    str(exc),
                    retryable=False,
                    attempt=1,
                    source_url=path.resolve().as_uri(),
                    source_document_id=path.stem,
                )
                repository.checkpoint_run(
                    run_id,
                    {"file_index": index, "file_name": path.name},
                    discovered_delta=1,
                    failed_delta=1,
                )
        repository.finish_run(run_id, "failed" if failures else "completed")
    except Exception as exc:
        repository.finish_run(
            run_id, "failed", error_code=type(exc).__name__, error_detail=str(exc)
        )
        raise
    finally:
        _close_storage(storage)

    print(
        json.dumps(
            {"run_id": run_id, "files": len(paths), "failures": failures},
            ensure_ascii=False,
        )
    )
    return 1 if failures else 0


def reparse_corpus(args: argparse.Namespace, settings: IngestionSettings) -> int:
    manifest, raw_manifest = _manifest(args.to_manifest)
    _validate_manifest(manifest)
    target_version = str(manifest["version"])
    if target_version == args.from_version:
        raise ValueError("Reparse target corpus version must differ from the source version")
    repository = CorpusRepository(settings.metadata_database_url)
    repository.upsert_corpus_version(target_version, stable_hash(raw_manifest), manifest)
    target_metadata_by_id = _target_source_metadata(manifest)
    artifacts = repository.corpus_artifacts(args.from_version)
    if not artifacts:
        raise ValueError(f"Source corpus {args.from_version!r} has no pinned artifacts")

    run_id = repository.start_run("reparse", target_version)
    storage = _storage(settings, args.storage)
    pipeline = IngestionPipeline(repository, storage)
    failures = 0
    try:
        for index, artifact in enumerate(artifacts, start=1):
            raw = None
            try:
                content = storage.get(str(artifact["storage_path"]))
                if len(content) != int(artifact["byte_length"]):
                    raise ValueError("Stored artifact byte length does not match metadata")
                if stable_hash(content) != artifact["content_hash"]:
                    raise ValueError("Stored artifact hash does not match metadata")
                source_document_id = artifact.get("source_document_id")
                metadata = _merge_reparse_metadata(
                    artifact,
                    target_metadata_by_id.get(str(source_document_id)),
                )
                raw = RawDocument(
                    source_name=str(artifact["source_name"]),
                    source_document_id=artifact.get("source_document_id"),
                    source_url=artifact.get("source_url"),
                    media_type=str(artifact["media_type"]),
                    content=content,
                    retrieved_at=artifact["retrieved_at"],
                    metadata=metadata,
                )
                outcome = pipeline.reparse(
                    raw,
                    str(artifact["storage_path"]),
                    target_version,
                )
                repository.checkpoint_run(
                    run_id,
                    {
                        "artifact_index": index,
                        "source_document_id": raw.source_document_id,
                        "parser_version": PARSER_VERSION,
                    },
                    discovered_delta=1,
                    imported_delta=int(outcome.chunk_count > 0),
                    duplicate_delta=int(outcome.chunk_count == 0),
                )
            except Exception as exc:
                failures += 1
                repository.record_error(
                    run_id,
                    raw,
                    type(exc).__name__,
                    str(exc),
                    retryable=False,
                    attempt=1,
                    source_url=artifact.get("source_url"),
                    source_document_id=artifact.get("source_document_id"),
                )
                repository.checkpoint_run(
                    run_id,
                    {"artifact_index": index},
                    discovered_delta=1,
                    failed_delta=1,
                )
        repository.finish_run(run_id, "failed" if failures else "completed")
    except Exception as exc:
        repository.finish_run(
            run_id, "failed", error_code=type(exc).__name__, error_detail=str(exc)
        )
        raise
    finally:
        _close_storage(storage)

    print(
        json.dumps(
            {
                "run_id": run_id,
                "source_corpus": args.from_version,
                "target_corpus": target_version,
                "artifacts": len(artifacts),
                "failures": failures,
            },
            ensure_ascii=False,
        )
    )
    return 1 if failures else 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="beken-ingest")
    subparsers = parser.add_subparsers(dest="command", required=True)

    bootstrap = subparsers.add_parser("bootstrap-storage")
    bootstrap.set_defaults(handler=bootstrap_storage)

    manifest = subparsers.add_parser("import-manifest")
    manifest.add_argument("manifest", type=Path)
    manifest.add_argument("--storage", choices=("supabase", "local"), default="supabase")
    manifest.set_defaults(handler=import_manifest)

    yargitay = subparsers.add_parser("import-yargitay")
    yargitay.add_argument("query")
    yargitay.add_argument("--corpus-version", default="labour-law-pilot-v1")
    yargitay.add_argument("--page-size", type=int, default=10)
    yargitay.add_argument("--max-documents", type=int, default=100)
    yargitay.add_argument("--resume-run")
    yargitay.add_argument("--storage", choices=("supabase", "local"), default="supabase")
    yargitay.set_defaults(handler=import_yargitay)

    local_file = subparsers.add_parser("import-file")
    local_file.add_argument("path", type=Path)
    local_file.add_argument("--metadata", required=True)
    local_file.add_argument("--corpus-version")
    local_file.add_argument("--storage", choices=("supabase", "local"), default="supabase")
    local_file.set_defaults(handler=import_file)

    directory = subparsers.add_parser("import-directory")
    directory.add_argument("directory", type=Path)
    directory.add_argument("--metadata", required=True)
    directory.add_argument("--corpus-version", default="labour-law-pilot-v1")
    directory.add_argument("--storage", choices=("supabase", "local"), default="supabase")
    directory.set_defaults(handler=import_directory)

    reparse = subparsers.add_parser("reparse-corpus")
    reparse.add_argument("--from-version", required=True)
    reparse.add_argument("--to-manifest", required=True, type=Path)
    reparse.add_argument("--storage", choices=("supabase", "local"), default="supabase")
    reparse.set_defaults(handler=reparse_corpus)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    try:
        return int(args.handler(args, get_settings()))
    except ValueError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
