from __future__ import annotations

from datetime import date

import pytest

from app.chat.decision_refs import ArticleRef, annotation_paragraph, article_references

LATE = date(2023, 1, 1)


def refs(text: str, decided: date = LATE) -> list[tuple[str, str, int | None]]:
    found = article_references(text, decided=decided)
    return [(ref.law_number, ref.article, ref.paragraph) for ref in found]


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # The ways the corpus's decisions actually cite the law.
        (
            "4857 sayılı İş Kanunu'nun 21 inci maddesinin beşinci fıkrasına göre",
            [("4857", "21", 5)],
        ),
        ("4857 sayılı Yasanın 18. maddesi uyarınca", [("4857", "18", None)]),
        ("İŞ KANUNU (4857) Madde 21", [("4857", "21", None)]),
        (
            "Türk Borçlar Kanunu’nun \"İşçinin sorumluluğu\" kenar başlıklı 400 üncü maddesine",
            [("6098", "400", None)],
        ),
        ("6100 sayılı Hukuk Muhakemeleri Kanunu'nun 369 uncu maddesinin birinci fıkrası",
         [("6100", "369", 1)]),
        ("HMK'nın 369/1. maddesi", [("6100", "369", 1)]),
        ("4857 sayılı Kanun'un 20/1. maddesi", [("4857", "20", 1)]),
        (
            "4857 sayılı Kanun'un 17., 18. ve 19. maddeleri uyarınca",
            [("4857", "17", None), ("4857", "18", None), ("4857", "19", None)],
        ),
        # Once a law is named, "Kanun'un" refers back to it.
        (
            "4857 sayılı İş Kanunu fesih hükümleri incelendiğinde, Kanun'un 25 inci maddesinin "
            "(I) numaralı bendi",
            [("4857", "25", None)],
        ),
    ],
)
def test_decisions_cite_the_law_in_many_ways(text, expected) -> None:
    assert refs(text) == expected


@pytest.mark.parametrize(
    "text",
    [
        # A foreign law whose name ends like ours.
        "Rusya Federasyonu İş Kanunu'nun ... düzenlendiği 392. maddesinde öngörülen süre",
        # The old procedure code is not HMK.
        "Hukuk Usulü Muhakemeleri Kanunu'nun 428. maddesi",
        # A case number is not a law number.
        "Yargıtay 9. HD, K. 2013/13502 sayılı kararı ile 18. maddesi",
        # An article with no law before it.
        "maddesinin 5. fıkrasına göre geçerli bir fesih",
    ],
)
def test_uncertain_references_are_left_out(text) -> None:
    assert refs(text) == []


def test_a_named_law_counts_only_from_its_enactment() -> None:
    # Before 7036 took effect, "İş Mahkemeleri Kanunu" was 5521, which the corpus lacks.
    text = "İş Mahkemeleri Kanunu'nun 8. maddesi"
    assert refs(text, decided=date(2013, 1, 1)) == []
    assert refs(text, decided=date(2022, 1, 1)) == [("7036", "8", None)]


def test_basin_is_kanunu_is_not_the_labour_code() -> None:
    text = "5953 sayılı Basın İş Kanunu'nun 6. maddesi ve Basın İş Kanunu'nun 14. maddesi"
    assert refs(text) == [("5953", "6", None), ("5953", "14", None)]


def test_each_reference_is_listed_once() -> None:
    text = "4857 sayılı Kanun'un 21. maddesi... 4857 sayılı Kanun'un 21. maddesi"
    assert article_references(text, decided=LATE) == [ArticleRef("4857", "21")]


def test_amendment_notes_name_their_paragraph() -> None:
    assert annotation_paragraph("Değişik birinci fıkra: 12/10/2017-7036/11 md.") == 1
    assert annotation_paragraph("İptal dördüncü fıkra: Anayasa Mahkemesinin ...") == 4
    assert annotation_paragraph("DEĞİŞİK ON İKİNCİ FIKRA") == 12
    assert annotation_paragraph("Ek fıkra: 1/7/2006-5538/18 md.") is None
