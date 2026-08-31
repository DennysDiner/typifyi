"""Build the PDF fixtures deterministically, with no third-party dependencies.

Run: python tests/fixtures/build_pdfs.py

Two fixtures are produced:

* ``gazette/sample-gazette.pdf`` — a real text layer, so extraction can be tested;
* ``gazette/scanned-gazette.pdf`` — no text operators at all, standing in for an
  image-only issue, so the "no text layer" failure path can be tested.

They are committed, so the test suite never builds or downloads anything.
"""

from __future__ import annotations

from pathlib import Path

HERE = Path(__file__).resolve().parent

TEXT_PAGES = [
    [
        "TASMANIAN GOVERNMENT GAZETTE",
        "No. 22599   Wednesday 12 August 2026",
        "",
        "NOTICE UNDER THE LAND ACQUISITION ACT 1993",
        "Notice is given that the Crown has acquired land at Lutana adjoining the",
        "Nyrstar Hobart smelter for the purposes of a road realignment.",
        "",
        "APPOINTMENTS",
        "Sustainable Timber Tasmania - appointment of directors.",
    ],
    [
        "TASMANIAN GOVERNMENT GAZETTE - Page 2",
        "",
        "LIQUOR AND GAMING",
        "Notice of application by Federal Group for a venue licence at Wrest Point.",
        "",
        "CONTRACTS",
        "Contract awarded to Group 6 Metals Limited for road maintenance,",
        "value $412,000, Department of State Growth.",
    ],
]


def _escape(text: str) -> str:
    return text.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")


def _text_stream(lines: list[str]) -> bytes:
    parts = ["BT", "/F1 11 Tf", "14 TL", "50 780 Td"]
    for line in lines:
        parts.append(f"({_escape(line)}) Tj" if line else "()Tj")
        parts.append("T*")
    parts.append("ET")
    return "\n".join(parts).encode("latin-1")


def _blank_stream() -> bytes:
    # A filled rectangle only: this is what an image-only (scanned) page looks
    # like to a text extractor.
    return b"0.85 g\n50 60 500 720 re\nf\n"


def build_pdf(pages: list[bytes]) -> bytes:
    objects: list[bytes] = []
    page_object_ids = [4 + 2 * index for index in range(len(pages))]

    kids = " ".join(f"{pid} 0 R" for pid in page_object_ids)
    objects.append(b"<< /Type /Catalog /Pages 2 0 R >>")
    objects.append(
        f"<< /Type /Pages /Kids [{kids}] /Count {len(pages)} >>".encode("latin-1")
    )
    objects.append(b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>")
    for index, stream in enumerate(pages):
        content_id = page_object_ids[index] + 1
        objects.append(
            (
                f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>"
            ).encode("latin-1")
        )
        objects.append(
            b"<< /Length " + str(len(stream)).encode() + b" >>\nstream\n" + stream + b"\nendstream"
        )

    out = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for number, body in enumerate(objects, start=1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode("latin-1") + body + b"\nendobj\n"

    xref_offset = len(out)
    out += f"xref\n0 {len(objects) + 1}\n".encode("latin-1")
    out += b"0000000000 65535 f \n"
    for offset in offsets[1:]:
        out += f"{offset:010d} 00000 n \n".encode("latin-1")
    out += (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    ).encode("latin-1")
    return bytes(out)


def main() -> None:
    (HERE / "gazette").mkdir(parents=True, exist_ok=True)
    (HERE / "gazette" / "sample-gazette.pdf").write_bytes(
        build_pdf([_text_stream(page) for page in TEXT_PAGES])
    )
    (HERE / "gazette" / "scanned-gazette.pdf").write_bytes(build_pdf([_blank_stream()]))
    print("wrote gazette/sample-gazette.pdf and gazette/scanned-gazette.pdf")


if __name__ == "__main__":
    main()
