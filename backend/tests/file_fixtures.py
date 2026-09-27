"""Tiny, dependency-free builders for PDF and DOCX test documents."""

from __future__ import annotations

import io
import zipfile
from xml.sax.saxutils import escape


def build_pdf(pages: list[list[str]]) -> bytes:
    """A text PDF with one Helvetica line per entry; an empty page mimics a scan."""
    objects: list[bytes] = []
    page_ids = [4 + index * 2 for index in range(len(pages))]
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    kids = " ".join(f"{page_id} 0 R" for page_id in page_ids)
    objects.append(f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode())
    objects.append(
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )
    for page_id, lines in zip(page_ids, pages, strict=True):
        objects.append(
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
            f"/Resources << /Font << /F1 3 0 R >> >> /Contents {page_id + 1} 0 R >>".encode()
        )
        operations = ["BT", "/F1 11 Tf", "14 TL", "56 800 Td"]
        for line in lines:
            escaped = line.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            operations.append(f"({escaped}) Tj T*")
        operations.append("ET")
        stream = "\n".join(operations).encode("cp1252")
        objects.append(
            b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"
        )

    output = io.BytesIO()
    output.write(b"%PDF-1.4\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(output.tell())
        output.write(b"%d 0 obj\n" % number + body + b"\nendobj\n")
    xref = output.tell()
    output.write(b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1))
    for offset in offsets:
        output.write(b"%010d 00000 n \n" % offset)
    output.write(
        b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n"
        % (len(objects) + 1, xref)
    )
    return output.getvalue()


def build_docx(blocks: list[tuple[str, object]]) -> bytes:
    """blocks: ("heading", text), ("p", text) or ("table", [[cell, …], …])."""
    namespace = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"
    body: list[str] = []
    for kind, value in blocks:
        if kind == "table":
            rows = "".join(
                "<w:tr>"
                + "".join(
                    f"<w:tc><w:p><w:r><w:t>{escape(cell)}</w:t></w:r></w:p></w:tc>"
                    for cell in row
                )
                + "</w:tr>"
                for row in value  # type: ignore[union-attr]
            )
            body.append(f"<w:tbl>{rows}</w:tbl>")
            continue
        style = '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>' if kind == "heading" else ""
        body.append(f"<w:p>{style}<w:r><w:t>{escape(str(value))}</w:t></w:r></w:p>")
    document = (
        f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        f'<w:document xmlns:w="{namespace}"><w:body>{"".join(body)}</w:body></w:document>'
    )
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr("word/document.xml", document)
    return output.getvalue()
