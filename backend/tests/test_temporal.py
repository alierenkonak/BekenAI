from __future__ import annotations

from datetime import date

from app.chat.temporal import (
    MAX_AMENDMENT_SEARCHES,
    MAX_ANNOTATION_CHARS,
    MAX_CHECKS,
    CaseDate,
    ProvisionChange,
    amendment_query,
    assess,
    changed_after,
    changes_by_chunk,
    check_text,
    dates_in,
    provision_label,
    temporal_checks,
    verified_case_date,
)

MEDIATION = CaseDate(date(2023, 7, 5), "arabulucu başvurusu")


def change(**overrides) -> ProvisionChange:
    values = {
        "event_id": "e1",
        "event_type": "amended",
        "target_type": "sentence",
        "unit_type": "paragraph",
        "change_date": date(2024, 11, 7),
        "effective_from": None,
        "amending_law": "7531",
        "provision": "m.3, 12. fıkra",
        "annotation": "Değişik ikinci cümle: 7/11/2024-7531/28 md.",
    }
    return ProvisionChange(**{**values, **overrides})


def row(chunk: str, event: str, when: date, path: list[str], annotation: str) -> dict:
    return {
        "chunk_id": chunk,
        "event_id": event,
        "event_type": "added",
        "target_type": "paragraph",
        "unit_type": "article",
        "event_date": when,
        "effective_from": None,
        "source_law_number": "5538",
        "raw_annotation": annotation,
        "unit_path": path,
    }


def test_provision_labels_name_the_article_paragraph_and_item() -> None:
    assert provision_label(["chapter:BİRİNCİ", "article:3", "paragraph:12"]) == "m.3, 12. fıkra"
    assert provision_label(["part:ikinci", "temporary_article:2"]) == "geçici m.2"
    assert provision_label(["article:2", "item:b"]) == "m.2, (b) bendi"
    assert (
        provision_label(["article:25#2", "paragraph:1", "item:b", "subitem:1"])
        == "m.25, 1. fıkra, (b) bendi, (1) alt bendi"
    )
    assert provision_label(["metadata:document"]) == ""


def test_dates_are_read_the_ways_turkish_documents_write_them() -> None:
    text = (
        "Fesih 14.06.2023, başvuru 5/7/2023, tutanak 2023-07-26; DAVA TARİHİ: 4 AĞUSTOS 2023, "
        "duruşma 1 Aralık 2023. Geçersiz: 31.02.2023, sayı 1.234.2023"
    )
    assert set(dates_in(text)) == {
        date(2023, 6, 14),
        date(2023, 7, 5),
        date(2023, 7, 26),
        date(2023, 8, 4),
        date(2023, 12, 1),
    }


def test_a_case_date_counts_only_if_the_file_or_message_states_it() -> None:
    texts = ["Müvekkil 05.07.2023 tarihinde arabulucuya başvurmuştur."]
    assert verified_case_date("05.07.2023", " arabulucu başvurusu. ", texts=texts) == MEDIATION
    assert verified_case_date("2023-07-05", "", texts=texts) == CaseDate(
        date(2023, 7, 5), "olay tarihi"
    )
    # A date the model wrote but the file does not contain is never compared.
    assert verified_case_date("01.03.2023", "fesih tarihi", texts=texts) is None
    assert verified_case_date("", "", texts=texts) is None
    assert verified_case_date("bilinmiyor", "fesih tarihi", texts=texts) is None


def test_a_change_after_the_case_date_warns_and_one_just_before_it_asks_to_check() -> None:
    amended = change()
    assert assess(amended, date(2023, 7, 5)) == "changed_after"
    # The note's date is the adoption date; the law may have taken effect later.
    assert assess(amended, date(2024, 11, 20)) == "near_change"
    assert assess(amended, date(2025, 6, 1)) is None
    # A known effective date replaces the guesswork.
    delayed = change(effective_from=date(2025, 1, 1))
    assert assess(delayed, date(2024, 12, 1)) == "changed_after"
    assert assess(delayed, date(2025, 1, 2)) is None
    # Annulments are often postponed for months.
    annulled = change(event_type="annulled", amending_law=None)
    assert assess(annulled, date(2025, 8, 1)) == "near_change"


def test_the_warning_says_what_the_note_changed_and_nothing_more() -> None:
    title = "7036 sayılı İş Mahkemeleri Kanunu"
    assert check_text(title, change(), "changed_after", MEDIATION) == (
        "7036 sayılı İş Mahkemeleri Kanunu m.3, 12. fıkra (Değişik ikinci cümle: "
        "7/11/2024-7531/28 md.): bu değişiklik arabulucu başvurusu olan 05.07.2023 tarihinden "
        "sonra; olay tarihinde hükmün metni bugünkünden farklıydı."
    )
    # A note not tied to an article still reads cleanly.
    loose = check_text("Yönetmelik", change(provision=""), "changed_after", MEDIATION)
    assert loose.startswith("Yönetmelik (Değişik ikinci cümle: 7/11/2024-7531/28 md.): bu ")
    # A paragraph added to a law without numbered paragraphs is tied to its article; the
    # article itself already existed.
    paragraph = change(event_type="added", target_type="paragraph", unit_type="article")
    text = check_text("Kanun", paragraph, "changed_after", MEDIATION)
    assert "metni bugünkünden farklıydı" in text
    article = change(event_type="added", target_type="unit", unit_type="article")
    assert "bu hüküm henüz yoktu" in check_text("Kanun", article, "changed_after", MEDIATION)
    repealed = change(event_type="repealed", target_type="unit")
    assert "henüz yürürlükteydi" in check_text("Kanun", repealed, "changed_after", MEDIATION)

    started = CaseDate(date(2024, 11, 20), "işe giriş tarihi")
    note = check_text("Kanun", change(), "near_change", started)
    assert "işe giriş tarihi (20.11.2024) bu değişiklikten kısa süre sonra" in note
    assert "kabul tarihidir" in note


def test_notes_are_grouped_per_chunk_newest_first_and_listed_once() -> None:
    rows = [
        row("c1", "e1", date(2006, 7, 1), ["article:2"], "Ek fıkra: 1/7/2006-5538/18 md."),
        row("c1", "e2", date(2010, 7, 23), ["article:2"], "Ek fıkra: 23/7/2010-6009/48 md."),
        # The parser recorded the first note twice.
        row("c1", "e3", date(2006, 7, 1), ["article:2"], "Ek fıkra:  1/7/2006-5538/18\nmd."),
        row("c1", "e4", date(2006, 7, 1), ["article:2", "item:b"], "Ek fıkra: 1/7/2006-5538/18"),
        row("c2", "e5", date(2016, 5, 6), ["article:7"], "Anayasa Mahkemesinin " + "x" * 400),
    ]
    grouped = changes_by_chunk(rows)
    assert [(c.event_id, c.provision) for c in grouped["c1"]] == [
        ("e2", "m.2"),
        ("e1", "m.2"),
        ("e4", "m.2, (b) bendi"),
    ]
    [long] = grouped["c2"]
    assert len(long.annotation) == MAX_ANNOTATION_CHARS and long.annotation.endswith("…")


def test_checks_report_each_change_once_and_firm_warnings_first() -> None:
    article_level = change(event_id="article")
    shortly_before = change(event_id="near", change_date=date(2023, 6, 1))
    long_before = change(event_id="old", change_date=date(2017, 10, 12))
    sources = [
        ("P1", "Kanun", [shortly_before, article_level]),
        # Two passages of one article carry the same note; it is reported once.
        ("P2", "Kanun", [article_level, long_before]),
        # No date for this passage: nothing to compare with.
        ("P3", "Kanun", [change(event_id="undated")]),
    ]
    checks = temporal_checks(sources, {"P1": MEDIATION, "P2": MEDIATION})
    assert [(c["source_id"], c["level"]) for c in checks] == [
        ("P1", "changed_after"),
        ("P1", "near_change"),
    ]
    assert checks[0] | {"text": ""} == {
        "source_id": "P1",
        "level": "changed_after",
        "title": "Kanun",
        "event_type": "amended",
        "change_date": "2024-11-07",
        "effective_from": None,
        "amending_law": "7531",
        "provision": "m.3, 12. fıkra",
        "annotation": "Değişik ikinci cümle: 7/11/2024-7531/28 md.",
        "case_date": "2023-07-05",
        "case_date_label": "arabulucu başvurusu",
        "text": "",
    }

    many = [change(event_id=str(number)) for number in range(20)]
    assert len(temporal_checks([("P1", "Kanun", many)], {"P1": MEDIATION})) == MAX_CHECKS


def test_the_old_text_is_searched_by_law_and_provision_only() -> None:
    [check] = temporal_checks([("P1", "7036 sayılı İş Mahkemeleri Kanunu", [change()])],
                              {"P1": MEDIATION})
    query = amendment_query(check)
    assert query == (
        "7036 sayılı İş Mahkemeleri Kanunu m.3, 12. fıkra 7531 sayılı Kanun "
        "değişiklik öncesi eski hali"
    )
    # Nothing the user wrote or the file says reaches the search engine.
    assert "2023" not in query and "arabulucu" not in query
    annulled = check | {"amending_law": None, "event_type": "annulled"}
    assert "Anayasa Mahkemesi iptal kararı" in amendment_query(annulled)


def test_only_firm_warnings_are_searched_and_only_a_few() -> None:
    checks = [{"level": "near_change"}] + [{"level": "changed_after", "n": n} for n in range(5)]
    found = changed_after(checks)
    assert len(found) == MAX_AMENDMENT_SEARCHES
    assert all(check["level"] == "changed_after" for check in found)
