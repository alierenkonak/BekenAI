from datetime import date

import pytest

from beken_ingestion.models import RawDocument
from beken_ingestion.normalization import normalize_legal_text
from beken_ingestion.parsers import ExtractionError, parse_document


def test_turkish_characters_and_legal_numbering_are_preserved() -> None:
    value = "İşçi\u00a0ücreti\tödenir.\r\n\r\nMADDE 18 – İş güvencesi"

    assert normalize_legal_text(value) == "İşçi ücreti ödenir.\n\nMADDE 18 – İş güvencesi"


def test_legislation_is_chunked_by_article_with_exact_offsets() -> None:
    raw = RawDocument(
        source_name="mevzuat",
        source_document_id="law-4857-test",
        source_url="https://www.mevzuat.gov.tr/example.html",
        media_type="text/html",
        content=(
            "<html><body><h1>4857 SAYILI İŞ KANUNU</h1>"
            "<p>MADDE 18 - İş güvencesine ilişkin hükümler burada yer alır.</p>"
            "<p>MADDE 19 - Fesih bildirimi yazılı yapılır ve sebep açıkça belirtilir.</p>"
            "</body></html>"
        ).encode(),
        metadata={
            "source_kind": "legislation",
            "document_type": "law",
            "title": "4857 sayılı İş Kanunu",
            "related_legislation": ["4857"],
        },
    )

    parsed = parse_document(raw)

    assert parsed.fingerprint == "mevzuat:law-4857-test"
    assert [chunk.section_type for chunk in parsed.chunks] == ["metadata", "article", "article"]
    assert [chunk.metadata.get("label") for chunk in parsed.chunks[1:]] == ["18", "19"]
    full_text = "\n\n".join(chunk.text for chunk in parsed.chunks)
    assert "İş güvencesine" in full_text
    assert all(chunk.char_end > chunk.char_start for chunk in parsed.chunks)


def test_court_decision_variants_receive_the_same_legal_fingerprint() -> None:
    metadata = {
        "source_kind": "court_decision",
        "document_type": "court_decision",
        "authority": "Yargıtay",
        "chamber": "9. Hukuk Dairesi",
        "case_number": "2024/100",
        "decision_number": "2025/200",
        "document_date": "15.01.2025",
    }
    body = (
        "<h1>Yargıtay 9. Hukuk Dairesi</h1>"
        "<p>Esas No: 2024/100 Karar No: 2025/200 Karar Tarihi: 15.01.2025</p>"
        "<h2>GEREKÇE</h2><p>Feshin geçerli nedene dayanıp dayanmadığı incelenmiştir.</p>"
        "<h2>HÜKÜM</h2><p>Temyiz isteminin sonucuna göre karar verilmiştir.</p>"
    )
    first = parse_document(
        RawDocument(
            source_name="yargitay",
            source_document_id="doc-a",
            source_url="https://karararama.yargitay.gov.tr/getDokuman?id=a",
            media_type="text/html",
            content=body.encode(),
            metadata=metadata,
        )
    )
    second = parse_document(
        RawDocument(
            source_name="manual",
            source_document_id="doc-b",
            source_url="file:///tmp/doc-b.html",
            media_type="text/html",
            content=(body + "<p>Biçimsel ek.</p>").encode(),
            metadata=metadata,
        )
    )

    assert first.fingerprint == second.fingerprint
    assert first.fingerprint.startswith("court:yargitay:9-hukuk-dairesi")
    assert {chunk.section_type for chunk in first.chunks} >= {"gerekçe", "hüküm"}


def test_parser_uses_deterministic_paragraph_fallback() -> None:
    raw = RawDocument(
        source_name="manual",
        source_document_id="fallback",
        source_url="file:///tmp/fallback.txt",
        media_type="text/plain",
        content=(
            "Birinci paragraf yeterli uzunlukta bir hukuki açıklama içerir.\n\n"
            "İkinci paragraf da veri kaybetmeden ayrı bir pasaj olarak korunur."
        ).encode(),
        metadata={"source_kind": "court_decision", "document_type": "court_decision"},
    )

    parsed = parse_document(raw)

    assert [chunk.section_type for chunk in parsed.chunks] == ["paragraph", "paragraph"]
    assert "".join(chunk.text for chunk in parsed.chunks).replace(" ", "") in (
        "Birinci paragraf yeterli uzunlukta bir hukuki açıklama içerir."
        "İkinci paragraf da veri kaybetmeden ayrı bir pasaj olarak korunur."
    ).replace(" ", "")


def test_legislation_parser_preserves_hierarchy_special_articles_and_events() -> None:
    raw = RawDocument(
        source_name="mevzuat",
        source_document_id="structured-law",
        source_url="https://www.mevzuat.gov.tr/example.html",
        media_type="text/html",
        content=(
            "<h1>BİRİNCİ BÖLÜM</h1><p>Ücrete İlişkin Hükümler</p>"
            "<p>MADDE 35/A - Ücretin korunmasına ilişkin hükümler uygulanır.</p>"
            "<p>(1) İşçinin ücreti zamanında ödenir.</p>"
            "<p>a) Birinci bent hükmü.</p><p>1) Alt bent hükmü.</p>"
            "<p>(Değişik ibare: 13/2/2011-6111/78 md.) ücret ibaresi</p>"
            "<p>(İptal dördüncü fıkra: Anayasa Mahkemesinin 12/1/2023 tarihli "
            "ve E.: 2022/15, K.: 2023/8 sayılı Kararı ile.)</p>"
            "<p>Anayasa Mahkemesi’nin 10/2/2016 tarihli ve E.: 2015/96, "
            "K.: 2016/9 sayılı Kararı ile bu ibare iptal edilmiş olup, kararın "
            "Resmi Gazete’de yayımlandığı 23/2/2016 tarihinden başlayarak dokuz ay "
            "sonra yürürlüğe girmesi hüküm altına alınmıştır.</p>"
            "<p>(Değişik: 8/8/2011-650/33 md.; İptal: Anayasa<br>Mahkemesinin "
            "18/7/2012 tarihli ve E.: 2011/113, K.: 2012/108 sayılı Kararı ile.; "
            "Yeniden düzenleme: 27/6/2013-6494/30 md.)</p>"
            "<p>Anayasa Mahkemesinin 8/10/2025 tarihli ve E.: 2025/124, "
            "K.: 2025/203 sayılı Kararı ile bu bent yönünden ipta l edilmiştir. "
            "Bu Karar Resmî Gazete’de yayımlanmasından başlayarak dokuz ay sonra "
            "(20/10/2026) yürürlüğe girer.</p>"
            "<p>EK MADDE 1 - Ek hüküm.</p>"
            "<p>GEÇİCİ MADDE 1 - Geçiş hükmü.</p>"
            "<p>EK GEÇİCİ MADDE 2 - Ek geçiş hükmü.</p>"
            "<p>MÜKERRER MADDE 3 - Mükerrer hüküm.</p>"
            "<p>(I) SAYILI CETVEL</p><table><tr><td>Tutar</td><td>100</td></tr></table>"
        ).encode(),
        metadata={
            "source_kind": "legislation",
            "document_type": "law",
            "title": "Test Kanunu",
        },
    )

    parsed = parse_document(raw)
    unit_types = {unit.unit_type for unit in parsed.legal_units}

    assert parsed.parser_version == "2026.08.3"
    assert {
        "chapter",
        "article",
        "additional_article",
        "temporary_article",
        "additional_temporary_article",
        "repeated_article",
        "paragraph",
        "item",
        "subitem",
        "annex",
    } <= unit_types
    article = next(unit for unit in parsed.legal_units if unit.label == "35/A")
    item = next(unit for unit in parsed.legal_units if unit.unit_type == "item")
    subitem = next(unit for unit in parsed.legal_units if unit.unit_type == "subitem")
    assert item.parent_key is not None and article.unit_key in item.parent_key
    assert subitem.parent_key == item.unit_key
    assert {event.event_type for event in parsed.provision_events} >= {"amended", "annulled"}
    annulment = next(
        event for event in parsed.provision_events if event.event_type == "annulled"
    )
    assert annulment.authority == "Anayasa Mahkemesi"
    assert annulment.case_number == "2022/15"
    assert annulment.decision_number == "2023/8"
    assert annulment.metadata["partial_or_delayed_effect_requires_review"] is True
    delayed = next(
        event for event in parsed.provision_events if event.decision_number == "2016/9"
    )
    assert delayed.official_gazette_date == date(2016, 2, 23)
    assert delayed.effective_from == date(2016, 11, 23)
    compound_annulment = next(
        event for event in parsed.provision_events if event.decision_number == "2012/108"
    )
    assert compound_annulment.event_type == "annulled"
    explicit_future = next(
        event for event in parsed.provision_events if event.decision_number == "2025/203"
    )
    assert explicit_future.official_gazette_date is None
    assert explicit_future.effective_from == date(2026, 10, 20)
    annex = next(unit for unit in parsed.legal_units if unit.unit_type == "annex")
    assert annex.metadata["table_parse_status"] == "unparsed"
    breadcrumbs = [chunk.metadata.get("breadcrumb", []) for chunk in parsed.chunks]
    assert any("Test Kanunu" in breadcrumb for breadcrumb in breadcrumbs)
    assert any("Ücrete İlişkin Hükümler" in breadcrumb for breadcrumb in breadcrumbs)
    assert any("Madde 35/A" in breadcrumb for breadcrumb in breadcrumbs)
    assert all(len(chunk.text) <= 3_000 for chunk in parsed.chunks)


def test_numbered_lines_are_not_subitems_without_an_item_parent() -> None:
    raw = RawDocument(
        source_name="mevzuat",
        source_document_id="numbering-context",
        source_url="https://www.mevzuat.gov.tr/example.txt",
        media_type="text/plain",
        content=(
            "MADDE 1 - Tarihler aşağıda yer alır.\n"
            "1) Bu satır bent üst bağlamı olmadan yazılmıştır.\n"
            "13/2/2011 tarihinde yürürlüğe girer."
        ).encode(),
        metadata={"source_kind": "legislation", "document_type": "law"},
    )

    parsed = parse_document(raw)

    assert not any(unit.unit_type == "subitem" for unit in parsed.legal_units)


def test_split_article_numbers_and_article_ranges_are_canonicalized() -> None:
    raw = RawDocument(
        source_name="mevzuat",
        source_document_id="article-number-repair",
        source_url="https://www.mevzuat.gov.tr/example.txt",
        media_type="text/plain",
        content=(
            "MADDE 221- Birinci hüküm yeterli açıklamayı içerir.\n"
            "MADDE 2 22- PDF satır çıkarımıyla bölünen numara düzeltilir.\n"
            "MADDE 223- Üçüncü hüküm yeterli açıklamayı içerir.\n"
            "MADDE 224 ila 226- Bu aralıktaki hükümler birlikte kaldırılmıştır.\n"
            "MADDE 227- Son hüküm yeterli açıklamayı içerir.\n"
            "MADDE 228 PDF metninde ayraç bulunmayan hüküm de algılanır."
        ).encode(),
        metadata={
            "source_kind": "legislation",
            "document_type": "law",
            "domain_metadata": {
                "article_expectations": {
                    "required_numeric_start": 221,
                    "required_numeric_end": 228,
                    "required_labels": [],
                }
            },
        },
    )

    parsed = parse_document(raw)
    articles = [unit for unit in parsed.legal_units if unit.unit_type == "article"]

    assert [unit.label for unit in articles] == [
        "221",
        "222",
        "223",
        "224-226",
        "227",
        "228",
    ]
    repaired = next(unit for unit in articles if unit.label == "222")
    ranged = next(unit for unit in articles if unit.label == "224-226")
    assert repaired.metadata["number_repaired"] is True
    assert repaired.metadata["source_label"] == "2 22"
    assert ranged.metadata["represented_article_labels"] == ["224", "225", "226"]
    assert parsed.parse_metadata["article_structure_audit"]["status"] == "passed"
    linked_unit_keys = {key for chunk in parsed.chunks for key in chunk.unit_keys}
    assert all(unit.unit_key in linked_unit_keys for unit in parsed.legal_units)


def test_terminal_supplement_is_preserved_without_creating_false_articles() -> None:
    raw = RawDocument(
        source_name="mevzuat",
        source_document_id="supplement-boundary",
        source_url="https://www.mevzuat.gov.tr/example.txt",
        media_type="text/plain",
        content=(
            "MADDE 1- Birinci asıl hüküm burada yer alır.\n"
            "MADDE 2- İkinci asıl hüküm burada yer alır.\n"
            "6098 SAYILI KANUNA İŞLENEMEYEN HÜKÜMLER\n"
            "MADDE 1- Başka bir kanunun işlenemeyen ve kayıpsız saklanan hükmüdür."
        ).encode(),
        metadata={
            "source_kind": "legislation",
            "document_type": "law",
            "domain_metadata": {
                "article_expectations": {
                    "required_numeric_start": 1,
                    "required_numeric_end": 2,
                    "required_labels": [],
                }
            },
        },
    )

    parsed = parse_document(raw)
    articles = [unit for unit in parsed.legal_units if unit.unit_type == "article"]
    supplement = next(
        unit
        for unit in parsed.legal_units
        if unit.metadata.get("supplement_type") == "islenemeyen-hukumler"
    )

    assert [unit.label for unit in articles] == ["1", "2"]
    assert "Başka bir kanunun" in supplement.text
    assert supplement.metadata["table_parse_status"] == "unparsed"
    assert parsed.parse_metadata["article_structure_audit"]["status"] == "passed"


def test_article_quality_gate_rejects_missing_or_duplicate_core_labels() -> None:
    raw = RawDocument(
        source_name="mevzuat",
        source_document_id="invalid-articles",
        source_url="https://www.mevzuat.gov.tr/example.txt",
        media_type="text/plain",
        content=(
            "MADDE 1- Birinci hüküm burada yer alır.\n"
            "MADDE 1- Yanlışlıkla yinelenen hüküm burada yer alır.\n"
            "MADDE 3- Üçüncü hüküm burada yer alır."
        ).encode(),
        metadata={
            "source_kind": "legislation",
            "document_type": "law",
            "domain_metadata": {
                "article_expectations": {
                    "required_numeric_start": 1,
                    "required_numeric_end": 3,
                    "required_labels": [],
                }
            },
        },
    )

    with pytest.raises(ExtractionError, match="Article structure validation failed"):
        parse_document(raw)


def test_unrecognized_article_like_heading_fails_instead_of_silent_fallback() -> None:
    raw = RawDocument(
        source_name="mevzuat",
        source_document_id="unsupported-heading",
        source_url="https://www.mevzuat.gov.tr/example.txt",
        media_type="text/plain",
        content=(
            "MADDE 1- Birinci hüküm yeterli uzunlukta bir açıklama içerir.\n"
            "GEÇİCİ MADDE – Numarasız başlık sessizce atlanmamalıdır."
        ).encode(),
        metadata={"source_kind": "legislation", "document_type": "law"},
    )

    with pytest.raises(ExtractionError, match="Unrecognized article-like heading"):
        parse_document(raw)
