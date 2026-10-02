from __future__ import annotations

from datetime import date
from uuid import uuid4

import pytest
from beken_retrieval.models import ChunkRecord, SearchHit

from app.chat.context import EvidenceSource, FileEvidenceSource
from app.chat.deadlines import (
    APPROXIMATE_NOTE,
    DEADLINES_HEADING,
    checked_deadline,
    last_day,
    period_pattern,
    with_deadlines,
)
from app.chat.decision_refs import fold
from app.files.retrieval import PrivateHit
from app.llm.models import AnswerBlock, AnswerSentence, CaseDeadline, ChatAnswer

MEDIATION_LAW = (
    "İş sözleşmesi feshedilen işçi, fesih bildiriminde sebep gösterilmediği veya gösterilen "
    "sebebin geçerli bir sebep olmadığı iddiası ile fesih bildiriminin tebliği tarihinden "
    "itibaren bir ay içinde işe iade talebiyle arabulucuya başvurmak zorundadır."
)


def law(text: str, source_id: str = "SOURCE_PRIMARY_01") -> EvidenceSource:
    record = ChunkRecord(
        chunk_id=str(uuid4()),
        parse_id=str(uuid4()),
        document_id=str(uuid4()),
        source_document_id="fixture",
        domain_code="labour_law",
        corpus_version="labour-law-pilot-v4",
        retrieval_scope_version="scope-v1",
        domain_role="core",
        document_type="law",
        title="İş Kanunu",
        text=text,
        section_type="article",
        breadcrumb=("Madde 20",),
        page_number=1,
    )
    return EvidenceSource(source_id, "primary", SearchHit(record=record, score=1.0, rank=1), "v1")


def file(text: str, source_id: str) -> FileEvidenceSource:
    hit = PrivateHit(
        chunk_id=uuid4(),
        file_id=uuid4(),
        file_name="Dava Dilekçesi.pdf",
        chunk_index=0,
        text=text,
        section_title=None,
        page_start=1,
        page_end=1,
        paragraph_start=1,
        paragraph_end=1,
        score=0.0,
    )
    return FileEvidenceSource(source_id=source_id, hit=hit, index_version="files")


FILES = [
    file("Fesih bildirimi davacıya 14.06.2023 tarihinde tebliğ edilmiştir.", "SOURCE_FILE_01"),
    file("Davacı 05.07.2023 tarihinde arabulucuya başvurmuştur.", "SOURCE_FILE_02"),
]
MEDIATION = CaseDeadline(
    amount=1,
    unit="ay",
    start_label="fesih bildiriminin tebliği",
    start_date="14.06.2023",
    act_label="arabulucuya başvuru",
    act_date="05.07.2023",
)


@pytest.mark.parametrize(
    ("start", "amount", "unit", "expected"),
    [
        (date(2023, 6, 14), 1, "ay", date(2023, 7, 14)),
        # A shorter last month ends the limit on its last day.
        (date(2024, 1, 31), 1, "ay", date(2024, 2, 29)),
        (date(2023, 1, 31), 1, "ay", date(2023, 2, 28)),
        (date(2023, 7, 26), 2, "hafta", date(2023, 8, 9)),
        (date(2023, 1, 10), 30, "gün", date(2023, 2, 9)),
        # From a Friday, six working days skip the weekend.
        (date(2023, 7, 28), 6, "iş günü", date(2023, 8, 7)),
        (date(2024, 2, 29), 1, "yıl", date(2025, 2, 28)),
    ],
)
def test_the_last_day_is_counted_as_the_procedure_code_counts_it(
    start: date, amount: int, unit: str, expected: date
) -> None:
    assert last_day(start, amount, unit) == expected


@pytest.mark.parametrize(
    ("text", "amount", "unit", "found"),
    [
        ("tebliğinden itibaren bir ay içinde", 1, "ay", True),
        ("1 ay içinde başvurmak zorundadır", 1, "ay", True),
        ("bir aylık süre içinde", 1, "ay", True),
        ("iki hafta içinde iş mahkemesinde", 2, "hafta", True),
        ("altı iş günü içinde kullanılabilir", 6, "iş günü", True),
        ("on beş gün içinde", 15, "gün", True),
        ("onbeş gün içinde", 15, "gün", True),
        ("bir ayrım yapılmaksızın", 1, "ay", False),
        ("11 ay sonra", 1, "ay", False),
        ("altı iş günü içinde", 6, "gün", False),
        ("iki gün içinde", 2, "hafta", False),
    ],
)
def test_a_limit_is_found_in_the_law_as_it_is_written(
    text: str, amount: int, unit: str, found: bool
) -> None:
    assert bool(period_pattern(amount, unit).search(fold(text))) is found


def test_an_application_before_the_last_day_is_in_time() -> None:
    """Regression: a report said 05.07.2023 missed a limit ending on 14.07.2023."""
    deadline = checked_deadline(
        "Arabuluculuk başvuru süresi", MEDIATION, law=[law(MEDIATION_LAW)], files=FILES
    )

    assert deadline is not None
    assert deadline.last == date(2023, 7, 14) and deadline.in_time is True
    assert deadline.facts() == {
        "kural": "1 ay",
        "baslangic": "fesih bildiriminin tebliği: 14.06.2023",
        "son_gun": "yaklaşık 14.07.2023",
        "islem": "arabulucuya başvuru: 05.07.2023",
        "sonuc": "süre içinde",
    }
    sentence = deadline.sentence()
    assert sentence.text == (
        "**Arabuluculuk başvuru süresi:** fesih bildiriminin tebliği (14.06.2023) tarihinden "
        "itibaren 1 ay; son gün yaklaşık 14.07.2023. Arabulucuya başvuru: 05.07.2023, süre "
        "içinde."
    )
    assert sentence.source_ids == ["SOURCE_PRIMARY_01", "SOURCE_FILE_01", "SOURCE_FILE_02"]


def test_an_act_after_the_last_day_is_late_and_a_weekend_end_is_named() -> None:
    files = [
        file("Son tutanak 22.07.2023 tarihinde düzenlenmiştir.", "SOURCE_FILE_01"),
        file("Dava 07.08.2023 tarihinde açılmıştır.", "SOURCE_FILE_02"),
    ]
    filing = CaseDeadline(
        amount=2,
        unit="hafta",
        start_label="son tutanağın düzenlenmesi",
        start_date="22.07.2023",
        act_label="dava açılması",
        act_date="07.08.2023",
    )
    deadline = checked_deadline(
        "Dava açma süresi",
        filing,
        law=[law("son tutanağın düzenlendiği tarihten itibaren iki hafta içinde dava açılabilir")],
        files=files,
    )

    assert deadline is not None and deadline.in_time is False
    # 05.08.2023 is a Saturday.
    assert deadline.sentence().text == (
        "**Dava açma süresi:** son tutanağın düzenlenmesi (22.07.2023) tarihinden itibaren "
        "2 hafta; son gün yaklaşık 05.08.2023 (hafta sonuna denk geliyor; süre ilk iş gününe "
        "uzayabilir). Dava açılması: 07.08.2023, süre dolduktan sonra."
    )


def test_a_deadline_needs_its_dates_in_the_file_and_its_limit_in_the_law() -> None:
    issue = "Arabuluculuk başvuru süresi"
    # The file does not state the start date.
    moved = MEDIATION.model_copy(update={"start_date": "15.06.2023"})
    assert checked_deadline(issue, moved, law=[law(MEDIATION_LAW)], files=FILES) is None
    # The law found for the issue does not state a limit of one month.
    other = law("Fesih bildirimi yazılı yapılır.")
    assert checked_deadline(issue, MEDIATION, law=[other], files=FILES) is None
    assert checked_deadline(issue, None, law=[law(MEDIATION_LAW)], files=FILES) is None
    # An act the file does not state, or one before the limit starts, is left out.
    for act_date in ("06.07.2023", "01.06.2023"):
        unstated = MEDIATION.model_copy(update={"act_date": act_date})
        files = [*FILES, file("İşe giriş 01.06.2023 tarihindedir.", "SOURCE_FILE_03")]
        deadline = checked_deadline(issue, unstated, law=[law(MEDIATION_LAW)], files=files)
        assert deadline is not None and deadline.act is None and deadline.in_time is None
        assert "islem" not in deadline.facts()


def test_the_computed_deadlines_replace_the_ones_the_model_wrote() -> None:
    deadline = checked_deadline(
        "Arabuluculuk başvuru süresi", MEDIATION, law=[law(MEDIATION_LAW)], files=FILES
    )
    assert deadline is not None

    def heading(text: str) -> AnswerBlock:
        return AnswerBlock(kind="heading", sentences=[AnswerSentence(text=text)])

    def bullets(text: str) -> AnswerBlock:
        return AnswerBlock(kind="bullets", sentences=[AnswerSentence(text=text)])

    answer = ChatAnswer(
        answer_status="answered",
        blocks=[
            AnswerBlock(kind="paragraph", sentences=[AnswerSentence(text="Özet.")]),
            heading("**Kritik Süreler:**"),
            bullets("Süre 05.07.2023 başvurusu ile aşılmıştır."),
            heading("Eksik belgeler ve deliller"),
            bullets("Performans kayıtları dosyaya eklenmelidir."),
        ],
    )

    shaped = with_deadlines(answer, [deadline])

    texts = [[sentence.text for sentence in block.sentences] for block in shaped.blocks]
    assert texts == [
        ["Özet."],
        ["Eksik belgeler ve deliller"],
        ["Performans kayıtları dosyaya eklenmelidir."],
        [DEADLINES_HEADING],
        [deadline.sentence().text, APPROXIMATE_NOTE],
    ]
    # Without a checked deadline the section is left out altogether.
    assert [block.kind for block in with_deadlines(answer, []).blocks] == [
        "paragraph",
        "heading",
        "bullets",
    ]
