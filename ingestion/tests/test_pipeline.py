from beken_ingestion.pipeline import readable_storage_path


def test_legislation_storage_path_is_readable_and_content_addressed() -> None:
    path = readable_storage_path(
        source_name="mevzuat",
        source_document_id="law-4857",
        media_type="application/pdf",
        content_hash="aebf2741ab5cc776444d1ec7c5f1440873c2650929b38e037624e4ebc6f73444",
        metadata={
            "source_kind": "legislation",
            "document_type": "law",
            "title": "4857 sayılı İş Kanunu",
        },
    )

    assert path == "global/kanun/4857-sayili-is-kanunu--aebf2741ab5c.pdf"


def test_regulation_storage_path_uses_readable_category_and_title() -> None:
    path = readable_storage_path(
        source_name="mevzuat",
        source_document_id="regulation-fazla-calisma",
        media_type="application/pdf",
        content_hash="1234567890abcdef",
        metadata={
            "source_kind": "legislation",
            "document_type": "regulation",
            "title": "İş Kanununa İlişkin Fazla Çalışma Yönetmeliği",
        },
    )

    assert path == (
        "global/yonetmelik/is-kanununa-iliskin-fazla-calisma-yonetmeligi"
        "--1234567890ab.pdf"
    )


def test_court_decision_storage_path_uses_legal_identifiers() -> None:
    path = readable_storage_path(
        source_name="yargitay",
        source_document_id="decision-1",
        media_type="text/html",
        content_hash="0123456789abcdef" * 4,
        metadata={
            "source_kind": "court_decision",
            "authority": "Yargıtay",
            "chamber": "22. Hukuk Dairesi",
            "case_number": "2013/31047",
            "decision_number": "2015/4444",
        },
    )

    assert path == (
        "global/yargitay/"
        "yargitay-22-hukuk-dairesi-e-2013-31047-k-2015-4444--0123456789ab.html"
    )
