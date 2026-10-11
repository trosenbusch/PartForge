"""Small, deterministic PDFs for offline tests; no manufacturer documents or extra dependencies."""
from __future__ import annotations

import io
from collections.abc import Sequence

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def synthetic_pdf(pages: Sequence[str], *, owner_password: str | None = None) -> bytes:
    """US Letter pages with an optional text layer and empty-user-password encryption."""
    writer = PdfWriter()
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    for text in pages:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            page[NameObject("/Resources")] = DictionaryObject({
                NameObject("/Font"): DictionaryObject({NameObject("/F1"): font}),
            })
            escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 40 740 Td ({escaped}) Tj ET".encode("ascii"))
            page[NameObject("/Contents")] = stream
    if owner_password is not None:
        writer.encrypt(user_password="", owner_password=owner_password)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()
