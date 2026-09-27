from __future__ import annotations

import io
import zipfile
from pathlib import Path

import pytest
from file_fixtures import build_docx, build_pdf
from pypdf import PdfReader, PdfWriter

from app.files.chunking import chunk_document
from app.files.extraction import (
    DOCX,
    PDF,
    TEXT,
    ExtractionError,
    detect_media_type,
    extract_document,
    is_heading,
)

REPO_ROOT = Path(__file__).resolve().parents[2]

BODY = [
    "Müvekkil 01.03.2019 tarihinden itibaren davali isyerinde satis temsilcisi olarak",
    "calismistir. Is sözlesmesi 15.06.2023 tarihinde performans düsüklügü gerekcesiyle",
    "feshedilmistir.",
    "Davali isveren fesihten önce savunma almamis, yazili bildirim yapmamistir.",
    "Tanik beyanlari ve bordrolar bu durumu dogrulamaktadir.",
]


def _pages(count: int) -> list[list[str]]:
    return [
        ["ORNEK HUKUK BUROSU", "AÇIKLAMALAR" if page == 1 else f"{page}. BÖLÜM EKI"]
        + [f"{line} (s{page})" for line in BODY]
        + ["", f"Sayfa {page} / {count}"]
        for page in range(1, count + 1)
    ]


def _encrypted(pdf: bytes, *, user_password: str) -> bytes:
    writer = PdfWriter(clone_from=PdfReader(io.BytesIO(pdf)))
    writer.encrypt(user_password=user_password, owner_password="sahip", algorithm="RC4-128")
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


def test_pdf_keeps_pages_and_drops_running_headers_and_page_numbers() -> None:
    document = extract_document(build_pdf(_pages(3)), PDF)

    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert document.page_count == 3
    assert document.unreadable_pages == 0
    assert "ORNEK HUKUK BUROSU" not in text
    assert "Sayfa" not in text
    assert "savunma almamis" in text
    assert {paragraph.page for paragraph in document.paragraphs} == {1, 2, 3}
    assert document.paragraphs[0].text == "AÇIKLAMALAR" and document.paragraphs[0].heading
    assert [p.ordinal for p in document.paragraphs] == list(range(1, len(document.paragraphs) + 1))


def test_pdf_rejoins_hyphenated_words_across_lines() -> None:
    pdf = build_pdf([["Is söz-", "lesmesi feshedilmistir ve bu durum taniklarla sabittir."]])

    document = extract_document(pdf, PDF)

    assert document.paragraphs[0].text.startswith("Is sözlesmesi feshedilmistir")


def test_scanned_pdf_is_rejected_with_a_clear_code() -> None:
    with pytest.raises(ExtractionError, match="scanned_pdf_not_supported"):
        extract_document(build_pdf([[], [], []]), PDF)
    # Mostly image pages: still not a document we can answer from reliably.
    with pytest.raises(ExtractionError, match="scanned_pdf_not_supported"):
        extract_document(build_pdf([BODY, [], [], []]), PDF)


def test_pdf_with_a_few_image_pages_is_indexed_and_reports_them() -> None:
    document = extract_document(build_pdf([BODY, [], BODY, BODY]), PDF)

    assert document.unreadable_pages == 1
    assert 2 not in {paragraph.page for paragraph in document.paragraphs}


def test_password_protected_pdf_is_rejected_but_owner_only_lock_is_opened() -> None:
    pdf = build_pdf([BODY])

    with pytest.raises(ExtractionError, match="encrypted_pdf"):
        extract_document(_encrypted(pdf, user_password="gizli"), PDF)
    document = extract_document(_encrypted(pdf, user_password=""), PDF)
    assert "feshedilmistir" in document.paragraphs[0].text


def test_corrupt_pdf_is_unreadable() -> None:
    with pytest.raises(ExtractionError, match="unreadable_pdf|empty_document"):
        extract_document(b"%PDF-1.7\n" + b"\x00garbage" * 50, PDF)


def test_text_file_accepts_cp1254_and_uses_form_feeds_as_pages() -> None:
    raw = (
        "OLAYLAR\nİşçi 2019'da işe başladı.\n\nİşveren fesih bildirimi gönderdi."
        "\fSONUÇ VE İSTEM\nİşe iade."
    )
    document = extract_document(raw.encode("cp1254"), TEXT)

    assert document.page_count == 2
    assert [(p.text, p.heading, p.page) for p in document.paragraphs] == [
        ("OLAYLAR", True, 1),
        ("İşçi 2019'da işe başladı.", False, 1),
        ("İşveren fesih bildirimi gönderdi.", False, 1),
        ("SONUÇ VE İSTEM", True, 2),
        ("İşe iade.", False, 2),
    ]


def test_text_without_form_feeds_has_no_page_numbers() -> None:
    document = extract_document("Birinci paragraf.\n\nİkinci paragraf.".encode(), TEXT)

    assert [paragraph.page for paragraph in document.paragraphs] == [None, None]
    assert document.page_count is None


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b"bad\x00text", "invalid_text_file"),
        (b"  \n\n ... \n", "empty_document"),
    ],
)
def test_text_rejections(data: bytes, code: str) -> None:
    with pytest.raises(ExtractionError, match=code):
        extract_document(data, TEXT)


def test_docx_reads_styled_headings_paragraphs_and_tables() -> None:
    docx = build_docx(
        [
            ("heading", "Olaylar"),
            ("p", "Davacı 01.03.2019 tarihinde işe başlamıştır."),
            ("table", [["Tarih", "Olay"], ["15.06.2023", "Fesih bildirimi"]]),
            ("p", "DAVACI : AHMET YILMAZ"),
        ]
    )

    document = extract_document(docx, DOCX)

    assert [(p.text, p.heading, p.page) for p in document.paragraphs] == [
        ("Olaylar", True, None),
        ("Davacı 01.03.2019 tarihinde işe başlamıştır.", False, None),
        ("Tarih | Olay", False, None),
        ("15.06.2023 | Fesih bildirimi", False, None),
        ("DAVACI : AHMET YILMAZ", False, None),
    ]


def test_docx_with_a_dtd_is_refused() -> None:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<?xml version="1.0"?><!DOCTYPE x [<!ENTITY a "aaaa">]><x>&a;</x>',
        )

    with pytest.raises(ExtractionError, match="invalid_docx"):
        extract_document(output.getvalue(), DOCX)


def test_media_type_detection_checks_the_actual_bytes() -> None:
    assert detect_media_type(build_pdf([BODY]), PDF) == PDF
    assert detect_media_type(build_docx([("p", "Metin")]), DOCX) == DOCX
    assert detect_media_type("Türkçe".encode("cp1254"), TEXT) == TEXT
    with pytest.raises(ExtractionError, match="invalid_docx"):
        detect_media_type(build_pdf([BODY]), DOCX)
    empty_zip = io.BytesIO()
    with zipfile.ZipFile(empty_zip, "w") as archive:
        archive.writestr("other.xml", "<x/>")
    with pytest.raises(ExtractionError, match="invalid_docx"):
        detect_media_type(empty_zip.getvalue(), DOCX)
    with pytest.raises(ExtractionError, match="unsupported_media_type"):
        detect_media_type(b"data", "application/msword")


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("AÇIKLAMALAR", True),
        ("Hukuki Sebepler:", True),
        ("II. SONUÇ VE İSTEM", True),
        ("İSTANBUL ANADOLU 5. İŞ MAHKEMESİ", True),
        ("DAVACI : AHMET YILMAZ", False),
        ("T.C.", False),
        ("Davacı işe iade talep etmektedir.", False),
    ],
)
def test_heading_detection(line: str, expected: bool) -> None:
    assert is_heading(line) is expected


def test_the_public_sample_case_file_extracts_cleanly() -> None:
    """The demo file visitors download must keep working with the real pipeline."""
    sample = REPO_ROOT / "frontend/public/ornek/ornek-ise-iade-dosyasi.pdf"
    document = extract_document(sample.read_bytes(), PDF)

    assert (document.page_count, document.unreadable_pages) == (9, 0)
    text = "\n".join(paragraph.text for paragraph in document.paragraphs)
    assert "KURGUSAL DAVA DOSYASI" not in text and "Sayfa 4 / 9" not in text
    chunks = chunk_document(document)
    notice = next(chunk for chunk in chunks if chunk.section_title == "EK-1 · FESİH BİLDİRİMİ")
    assert notice.location_label == "s. 4" and "yüzde 62" in notice.text
