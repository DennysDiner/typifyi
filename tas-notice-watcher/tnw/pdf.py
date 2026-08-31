"""PDF text extraction.

Deterministic extraction only — text is taken from the PDF's own text layer.
There is no OCR here: if a document turns out to be image-only, that is reported
as a parser condition (and a decision for a human), never guessed at (§1, §9.2).
"""

from __future__ import annotations

import io
import logging
from dataclasses import dataclass

LOG = logging.getLogger(__name__)

# Below this, a "text layer" is really page furniture: treat as image-only.
MIN_TEXT_LAYER_CHARS = 200


class PdfExtractionError(RuntimeError):
    """The PDF could not be opened or read."""


@dataclass
class PdfText:
    text: str
    page_count: int
    pages_read: int
    truncated: bool

    @property
    def has_text_layer(self) -> bool:
        return len(self.text) >= MIN_TEXT_LAYER_CHARS


def extract_pdf_text(data: bytes, *, max_pages: int = 400) -> PdfText:
    """Extract the text layer from a PDF, reading at most ``max_pages`` pages."""
    import pdfplumber  # imported here so the module stays importable without it

    chunks: list[str] = []
    try:
        with pdfplumber.open(io.BytesIO(data)) as pdf:
            page_count = len(pdf.pages)
            pages_read = min(page_count, max_pages)
            for index in range(pages_read):
                try:
                    chunks.append(pdf.pages[index].extract_text() or "")
                except Exception as exc:  # one bad page must not lose the rest
                    LOG.warning("page %s could not be read: %s", index + 1, exc)
                    chunks.append("")
                finally:
                    pdf.pages[index].flush_cache()
    except PdfExtractionError:
        raise
    except Exception as exc:
        raise PdfExtractionError(f"could not read PDF: {type(exc).__name__}: {exc}") from exc

    from .normalise import normalise_text

    return PdfText(
        text=normalise_text("\n".join(chunks)),
        page_count=page_count,
        pages_read=pages_read,
        truncated=pages_read < page_count,
    )
