import pytest

from app.api.files import _safe_storage_name
from app.worker import detect_file


def test_storage_name_is_safe_and_keeps_expected_extension() -> None:
    assert _safe_storage_name("İşe İade / Karar?.PDF".replace("/", "-"), "application/pdf") == (
        "Ise-Iade-Karar.pdf"
    )


def test_file_signature_validation() -> None:
    assert detect_file(b"%PDF-1.7\nfixture", "application/pdf") == "application/pdf"
    assert detect_file("Türkçe metin".encode(), "text/plain") == "text/plain"
    with pytest.raises(ValueError, match="invalid_pdf_signature"):
        detect_file(b"not a pdf", "application/pdf")
    with pytest.raises(ValueError, match="invalid_text_file"):
        detect_file(b"bad\x00text", "text/plain")
