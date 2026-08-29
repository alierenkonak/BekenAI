import json
from pathlib import Path

import httpx
import pytest

from beken_ingestion.adapters import (
    LocalFileAdapter,
    MevzuatAdapter,
    SourceDocumentFailure,
    YargitayAdapter,
)
from beken_ingestion.cli import _merge_reparse_metadata, _validate_manifest, build_parser


def test_official_adapter_rejects_non_allowlisted_hosts() -> None:
    with MevzuatAdapter(rate_limit_seconds=0.5, max_attempts=1) as adapter:
        with pytest.raises(ValueError):
            adapter.request("GET", "https://example.com/document.pdf")


def test_mevzuat_adapter_preserves_raw_bytes_and_metadata() -> None:
    content = b"%PDF-test-immutable"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            content=content,
            headers={"Content-Type": "application/pdf"},
            request=request,
        )

    source = {
        "source_document_id": "law-4857-current",
        "url": "https://www.mevzuat.gov.tr/MevzuatMetin/1.5.4857.pdf",
        "metadata": {"source_kind": "legislation", "title": "4857 sayılı İş Kanunu"},
    }
    with MevzuatAdapter(
        rate_limit_seconds=0.5,
        max_attempts=1,
        transport=httpx.MockTransport(handler),
    ) as adapter:
        raw = adapter.fetch(source)

    assert raw.content == content
    assert raw.media_type == "application/pdf"
    assert raw.metadata["source_kind"] == "legislation"


def test_yargitay_skips_one_failed_document_and_continues() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/":
            return httpx.Response(200, text="ok", request=request)
        if request.url.path == "/arama":
            return httpx.Response(200, text="{}", request=request)
        if request.url.path == "/aramalist":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "data": [
                            {"id": "bad", "daire": "9. Hukuk Dairesi"},
                            {"id": "good", "daire": "9. Hukuk Dairesi"},
                        ]
                    }
                },
                request=request,
            )
        if request.url.params.get("id") == "bad":
            return httpx.Response(500, text="temporary failure", request=request)
        return httpx.Response(
            200,
            json={"data": "<p>GEREKÇE</p><p>İşe iade değerlendirmesi yapılmıştır.</p>"},
            request=request,
        )

    with YargitayAdapter(
        rate_limit_seconds=0,
        max_attempts=1,
        transport=httpx.MockTransport(handler),
    ) as adapter:
        results = list(adapter.search("işe iade", max_documents=2))

    assert isinstance(results[0][0], SourceDocumentFailure)
    assert results[0][0].source_document_id == "bad"
    assert results[0][0].error_detail == "Official source request failed: HTTP 500 at /getDokuman"
    assert results[1][0].source_document_id == "good"


def test_pilot_manifest_has_required_sources_and_decision_target() -> None:
    path = Path(__file__).parents[1] / "manifests/labour-law-pilot-v1.json"
    manifest = json.loads(path.read_text())

    ids = {source["source_document_id"] for source in manifest["sources"]}
    assert {
        "law-4857-current",
        "law-7036-current",
        "law-1475-current",
        "law-6098-service-contract-current",
        "law-6100-procedure-current",
        "law-6325-mediation-current",
    } <= ids
    assert manifest["decision_target_minimum"] == 50
    assert manifest["decision_target_maximum"] == 100

    v2_path = Path(__file__).parents[1] / "manifests/labour-law-pilot-v2.json"
    v2_manifest = json.loads(v2_path.read_text())
    assert v2_manifest["predecessor"] == "labour-law-pilot-v1"
    assert v2_manifest["parser_version"] == "2026.08.2"
    assert {source["source_document_id"] for source in v2_manifest["sources"]} == ids

    v3_path = Path(__file__).parents[1] / "manifests/labour-law-pilot-v3.json"
    v3_manifest = json.loads(v3_path.read_text())
    assert v3_manifest["predecessor"] == "labour-law-pilot-v2"
    assert v3_manifest["parser_version"] == "2026.08.3"
    assert {source["source_document_id"] for source in v3_manifest["sources"]} == ids
    assert all(
        "article_expectations" in source["metadata"]["domain_metadata"]
        for source in v3_manifest["sources"]
    )

    v4_path = Path(__file__).parents[1] / "manifests/labour-law-pilot-v4.json"
    v4_manifest = json.loads(v4_path.read_text())
    assert v4_manifest["predecessor"] == "labour-law-pilot-v3"
    assert v4_manifest["parser_version"] == "2026.08.4"
    assert len(v4_manifest["local_sources"]) == 83
    assert v4_manifest["quality_gates"] == {
        "document_count": 95,
        "legislation_count": 46,
        "decision_count": 49,
    }
    assert all(
        not Path(source["input_path"]).is_absolute()
        and not source["metadata"]["source_url"].startswith("file:")
        for source in v4_manifest["local_sources"]
    )
    assert all(
        source["metadata"]["domain_metadata"].get("article_expectations")
        for source in v4_manifest["local_sources"]
        if source["metadata"]["source_kind"] == "legislation"
    )
    assert all(
        source["metadata"]["domain_metadata"].get("court_metadata_requirements")
        == "complete"
        for source in v4_manifest["local_sources"]
        if source["metadata"]["source_kind"] == "court_decision"
    )


def test_manual_directory_fallback_is_available() -> None:
    args = build_parser().parse_args(
        [
            "import-directory",
            "/tmp/yargitay",
            "--metadata",
            '{"source_kind":"court_decision"}',
            "--storage",
            "local",
        ]
    )

    assert args.command == "import-directory"
    assert args.corpus_version == "labour-law-pilot-v1"


def test_local_manifest_command_is_dry_run_by_default() -> None:
    args = build_parser().parse_args(
        [
            "import-local-manifest",
            "ingestion/manifests/labour-law-pilot-v4.json",
            "--input-root",
            "/tmp/intake",
        ]
    )

    assert args.command == "import-local-manifest"
    assert args.execute is False


def test_local_file_adapter_does_not_persist_local_path_when_source_url_is_supplied(
    tmp_path: Path,
) -> None:
    document = tmp_path / "decision.txt"
    document.write_text("Karar metni")

    raw = LocalFileAdapter().fetch(
        document,
        {
            "source_document_id": "decision-1",
            "source_url": "https://karararama.yargitay.gov.tr/",
        },
    )

    assert raw.source_url == "https://karararama.yargitay.gov.tr/"


def test_reparse_command_requires_distinct_source_and_target_inputs() -> None:
    args = build_parser().parse_args(
        [
            "reparse-corpus",
            "--from-version",
            "labour-law-pilot-v1",
            "--to-manifest",
            "ingestion/manifests/labour-law-pilot-v2.json",
        ]
    )

    assert args.command == "reparse-corpus"
    assert args.from_version == "labour-law-pilot-v1"


def test_reparse_uses_target_manifest_metadata_without_losing_existing_values() -> None:
    artifact = {
        "source_kind": "legislation",
        "document_type": "law",
        "domain": "labour_law",
        "title": "Eski başlık",
        "domain_metadata": {"pilot_focus": "service_contract"},
    }
    target = {
        "title": "Güncel başlık",
        "domain_metadata": {
            "article_expectations": {
                "required_numeric_start": 1,
                "required_numeric_end": 649,
            }
        },
    }

    merged = _merge_reparse_metadata(artifact, target)

    assert merged["title"] == "Güncel başlık"
    assert merged["domain_metadata"]["pilot_focus"] == "service_contract"
    assert merged["domain_metadata"]["article_expectations"]["required_numeric_end"] == 649


def test_current_manifest_requires_article_expectations_for_every_legislation_source() -> None:
    manifest = {
        "parser_version": "2026.08.4",
        "sources": [
            {
                "source_document_id": "law-without-expectations",
                "metadata": {"source_kind": "legislation"},
            }
        ],
    }

    with pytest.raises(ValueError, match="needs article_expectations"):
        _validate_manifest(manifest)
