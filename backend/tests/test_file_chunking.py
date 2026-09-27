from __future__ import annotations

from app.files.chunking import MAX_CHARS, OVERLAP_CHARS, _sentences, chunk_document
from app.files.extraction import ExtractedDocument, Paragraph

SENTENCE = (
    "Davalı işveren fesihten önce işçinin savunmasını almamış ve bildirimi yazılı yapmamıştır."
)


def _document(*items: tuple[str, int | None, bool]) -> ExtractedDocument:
    paragraphs = tuple(
        Paragraph(text, ordinal, page, heading)
        for ordinal, (text, page, heading) in enumerate(items, 1)
    )
    return ExtractedDocument("application/pdf", paragraphs, None, 0)


def test_short_sections_merge_and_keep_their_page_range() -> None:
    document = _document(
        ("KONU", 1, True),
        ("İşe iade talebidir.", 1, False),
        ("AÇIKLAMALAR", 1, True),
        (SENTENCE, 2, False),
    )

    chunks = chunk_document(document)

    assert len(chunks) == 1
    # The tiny "KONU" section rides along; the substantive section names the chunk.
    assert chunks[0].section_title == "AÇIKLAMALAR"
    assert (chunks[0].page_start, chunks[0].page_end) == (1, 2)
    assert chunks[0].location_label == "s. 1–2"
    assert chunks[0].text.startswith("KONU\nİşe iade talebidir.\nAÇIKLAMALAR")


def test_long_sections_split_near_the_target_with_overlap_and_titles() -> None:
    body = [(f"{index}. {SENTENCE}", 1 + index // 10, False) for index in range(1, 40)]
    document = _document(("AÇIKLAMALAR", 1, True), *body, ("DELİLLER", 5, True), *body[:12])

    chunks = chunk_document(document)

    assert len(chunks) > 3
    assert all(len(chunk.text) <= MAX_CHARS for chunk in chunks)
    assert [chunk.index for chunk in chunks] == list(range(len(chunks)))
    first, second = chunks[0], chunks[1]
    carried = [line for line in second.text.split("\n") if line in first.text.split("\n")]
    assert carried and first.text.endswith("\n".join(carried))
    assert len("\n".join(carried)) <= OVERLAP_CHARS
    evidence = [chunk for chunk in chunks if chunk.section_title == "DELİLLER"]
    assert evidence and evidence[0].text.startswith("DELİLLER")
    # The new section starts clean: no overlap carried over from AÇIKLAMALAR.
    assert "39." not in evidence[0].text
    assert all(chunk.page_start <= chunk.page_end for chunk in chunks)


def test_an_oversized_paragraph_is_split_on_sentences() -> None:
    paragraph = " ".join(f"{index}. madde: {SENTENCE}" for index in range(60))
    chunks = chunk_document(_document((paragraph, 3, False)))

    assert len(chunks) > 1
    assert all(len(chunk.text) <= MAX_CHARS for chunk in chunks)
    assert all(chunk.paragraph_start == chunk.paragraph_end == 1 for chunk in chunks)
    assert all(chunk.location_label == "s. 3" for chunk in chunks)


def test_sentence_split_respects_legal_abbreviations_and_initials() -> None:
    text = (
        "Av. Mehmet Kaya dilekçeyi sundu. Yargıtay 9. HD. E. 2019/123 sayılı kararı emsaldir. "
        "Tanık A. Yılmaz beyanda bulundu. İşveren itiraz etti."
    )

    assert _sentences(text) == [
        "Av. Mehmet Kaya dilekçeyi sundu.",
        "Yargıtay 9. HD. E. 2019/123 sayılı kararı emsaldir.",
        "Tanık A. Yılmaz beyanda bulundu.",
        "İşveren itiraz etti.",
    ]


def test_documents_without_pages_are_located_by_paragraph() -> None:
    document = ExtractedDocument(
        "text/plain",
        (
            Paragraph("Birinci.", 1, None, False),
            Paragraph("İkinci.", 2, None, False),
            Paragraph("Üçüncü.", 3, None, False),
        ),
        None,
        0,
    )

    [chunk] = chunk_document(document)

    assert (chunk.page_start, chunk.page_end) == (None, None)
    assert chunk.location_label == "¶ 1–3"


def test_chunk_hashes_are_stable() -> None:
    document = _document((SENTENCE, 1, False))

    assert chunk_document(document)[0].content_hash == chunk_document(document)[0].content_hash
