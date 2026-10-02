from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from uuid import uuid4

import pytest

from beken_retrieval.bm25 import BM25LexicalRetriever
from beken_retrieval.context import build_embedding_context
from beken_retrieval.models import ChunkRecord, SearchFilters
from beken_retrieval.scope import load_scope
from beken_retrieval.tokenization import lexical_tokens, prefix_stem, tokenize_legal_text


def record(
    text: str,
    *,
    role: str = "core",
    document_type: str = "law",
    legislation_numbers: tuple[str, ...] = ("4857",),
    primary_legislation_number: str | None = "4857",
    article_labels: tuple[str, ...] = ("18",),
) -> ChunkRecord:
    return ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id="law-4857-current",
        domain_code="labour_law",
        corpus_version="labour-law-pilot-v4",
        retrieval_scope_version="labour-law-v1",
        domain_role=role,
        document_type=document_type,
        title="4857 sayılı İş Kanunu",
        text=text,
        section_type="article",
        breadcrumb=("4857", "Madde 18"),
        legislation_numbers=legislation_numbers,
        primary_legislation_number=primary_legislation_number,
        article_labels=article_labels,
    )


def test_turkish_tokenizer_preserves_legal_identifiers() -> None:
    tokens = tokenize_legal_text(
        "İŞÇİNİN 35/A maddesi ve Yargıtay E. 2022/9-1222, K. 2024/360 kararı"
    )

    assert "işçinin" in tokens
    assert "35/a" in tokens
    assert "e.2022/9-1222" in tokens
    assert "k.2024/360" in tokens


def test_embedding_context_keeps_exact_passage_unchanged() -> None:
    item = record("İşçinin exact passage metni.")
    context = build_embedding_context(item)

    assert context.exact_passage == item.text
    assert context.text.endswith(item.text)
    assert "4857 > Madde 18" in context.text


def test_scope_excludes_future_and_filters_supplemental_articles(tmp_path: Path) -> None:
    path = tmp_path / "scope.json"
    path.write_text(
        json.dumps(
            {
                "version": "labour-law-v1",
                "domain": "labour_law",
                "corpus_version": "labour-law-pilot-v4",
                "review_status": "reviewed",
                "roles": {
                    "core": {"include": True, "mode": "full_document"},
                    "supplemental": {
                        "include": True,
                        "mode": "provision_allowlist",
                    },
                    "future_domain": {"include": False, "mode": "excluded"},
                },
                "supplemental_allowlist": [{"legislation_number": "6098", "articles": ["393-469"]}],
            }
        ),
        encoding="utf-8",
    )
    scope = load_scope(path)
    core = record("core")
    allowed = record(
        "service",
        role="supplemental",
        legislation_numbers=("6098",),
        primary_legislation_number="6098",
        article_labels=("417",),
    )
    denied = record(
        "unrelated",
        role="supplemental",
        legislation_numbers=("6098",),
        primary_legislation_number="6098",
        article_labels=("600",),
    )
    future = record("future", role="future_domain")

    assert scope.allows(core)
    assert scope.allows(allowed)
    assert not scope.allows(denied)
    assert not scope.allows(future)


def test_scope_uses_primary_law_number_instead_of_cross_references(
    tmp_path: Path,
) -> None:
    path = tmp_path / "scope.json"
    path.write_text(
        json.dumps(
            {
                "version": "labour-law-v1",
                "domain": "labour_law",
                "corpus_version": "labour-law-pilot-v4",
                "review_status": "reviewed",
                "roles": {
                    "supplemental": {
                        "include": True,
                        "mode": "provision_allowlist",
                    }
                },
                "supplemental_allowlist": [
                    {"legislation_number": "5237", "articles": ["85-89"]},
                    {"legislation_number": "6698", "articles": ["4-12"]},
                ],
            }
        ),
        encoding="utf-8",
    )
    scope = load_scope(path)
    kvkk = record(
        "Kişisel verilerin işlenmesi",
        role="supplemental",
        legislation_numbers=("6698", "5237"),
        primary_legislation_number="6698",
        article_labels=("4",),
    )

    assert scope.allows(kvkk)


def test_bm25_roundtrip_and_filters(tmp_path: Path) -> None:
    law = record("Fazla çalışma ücreti ve ispat yükü")
    decision = record(
        "Fazla çalışma bordro ve tanık delili",
        document_type="court_decision",
    )
    index = BM25LexicalRetriever.build([law, decision], tmp_path / "index", scope_hash="a" * 64)

    results = index.search(
        "fazla çalışma",
        filters=SearchFilters(document_types=("law",)),
        limit=10,
    )
    reloaded = BM25LexicalRetriever.load(tmp_path / "index")
    reloaded_results = reloaded.search(
        "fazla çalışma",
        filters=SearchFilters(document_types=("law",)),
        limit=10,
    )

    assert [hit.record.chunk_id for hit in results] == [law.chunk_id]
    assert [hit.record.chunk_id for hit in reloaded_results] == [law.chunk_id]


def test_an_annex_article_is_not_taken_for_the_plain_article(tmp_path: Path) -> None:
    """Regression: "Ek Madde 3" (time limits) was labelled "3", like Madde 3."""
    plain = record("İşyerini bildirme yükümlülüğü", article_labels=("3",))
    annex = record("Kıdem tazminatı beş yıllık zamanaşımına tabidir.", article_labels=("Ek3",))
    temporary = record("Geçiş dönemi hükmü", article_labels=("Geçici3",))
    index = BM25LexicalRetriever.build(
        [plain, annex, temporary], tmp_path / "index", scope_hash="a" * 64
    )

    def lookup(article: str) -> list[str]:
        found = index.article_records("4857", article, filters=SearchFilters(), limit=5)
        return [item.chunk_id for item in found]

    assert lookup("3") == [plain.chunk_id]
    assert lookup("Ek3") == [annex.chunk_id]
    assert lookup("Geçici3") == [temporary.chunk_id]


def test_the_records_digest_is_the_corpus_hash_a_build_writes(tmp_path: Path) -> None:
    law = record("Fazla çalışma ücreti", article_labels=("41",))
    index = BM25LexicalRetriever.build([law], tmp_path / "index", scope_hash="a" * 64)

    assert BM25LexicalRetriever.records_digest([law]) == index.manifest["corpus_hash"]
    # A metadata change alone gives a new digest, and so a new index version.
    relabelled = replace(law, article_labels=("Ek41",))
    assert BM25LexicalRetriever.records_digest([relabelled]) != index.manifest["corpus_hash"]


def test_a_supplemental_allowlist_of_numbers_leaves_out_annex_articles(tmp_path: Path) -> None:
    path = tmp_path / "scope.json"
    path.write_text(
        json.dumps(
            {
                "version": "labour-law-v1",
                "domain": "labour_law",
                "corpus_version": "labour-law-pilot-v4",
                "review_status": "reviewed",
                "roles": {"supplemental": {"include": True, "mode": "provision_allowlist"}},
                "supplemental_allowlist": [{"legislation_number": "6098", "articles": ["1-5"]}],
            }
        ),
        encoding="utf-8",
    )
    scope = load_scope(path)

    def supplemental(label: str) -> ChunkRecord:
        return record(
            "TBK",
            role="supplemental",
            legislation_numbers=("6098",),
            primary_legislation_number="6098",
            article_labels=(label,),
        )

    assert scope.allows(supplemental("3"))
    assert not scope.allows(supplemental("Geçici3"))


def test_prefix_stemming_keeps_numbers_and_case_numbers_whole() -> None:
    assert prefix_stem("savunmasını", 5) == "savun"
    assert prefix_stem("kanun'un", 5) == "kanun"
    assert prefix_stem("iş", 5) == "iş"
    assert lexical_tokens("Savunmam alınmadan, E.2022/123 ve 18/A", "prefix5") == [
        "savun", "alınm", "e.2022/123", "ve", "18/a",
    ]
    assert lexical_tokens("Savunmam", None) == ["savunmam"]


def test_a_stemmed_index_matches_other_word_forms_and_loads_as_built(tmp_path: Path) -> None:
    """Regression: "savunmam alınmadan" did not match the Labour Act's "savunmasını almadan"."""
    statute = record(
        "Hakkındaki iddialara karşı savunmasını almadan bir işçinin sözleşmesi feshedilemez.",
        article_labels=("19",),
    )
    other = record("Yıllık ücretli izin süreleri kıdeme göre belirlenir.", article_labels=("53",))
    query = "Savunmam alınmadan işten çıkarılabilir miyim?"
    filters = SearchFilters()

    plain = BM25LexicalRetriever.build([statute, other], tmp_path / "plain", scope_hash="a" * 64)
    stemmed = BM25LexicalRetriever.build(
        [statute, other], tmp_path / "stemmed", scope_hash="a" * 64, stemming="prefix5"
    )

    assert plain.search(query, filters=filters, limit=5) == []
    assert [hit.record.chunk_id for hit in stemmed.search(query, filters=filters, limit=5)] == [
        statute.chunk_id
    ]
    assert stemmed.manifest["stemming"] == "prefix5" and plain.manifest["stemming"] is False
    reloaded = BM25LexicalRetriever.load(tmp_path / "stemmed")
    assert [hit.record.chunk_id for hit in reloaded.search(query, filters=filters, limit=5)] == [
        statute.chunk_id
    ]


def test_an_unknown_stemming_method_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="Unknown lexical stemming"):
        BM25LexicalRetriever.build([record("metin")], tmp_path / "index", scope_hash="a" * 64,
                                   stemming="snowball")
