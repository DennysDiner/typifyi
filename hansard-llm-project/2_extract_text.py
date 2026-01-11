#!/usr/bin/env python3
"""
Tasmania Parliament Hansard PDF Text Extractor

This script extracts text from downloaded Hansard PDFs, handling both
modern digital PDFs and older OCR-scanned documents (1979-1991).

Usage:
    python 2_extract_text.py --pdf-dir ./pdfs --output-dir ./extracted_text
"""

import argparse
import json
import re
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

import pdfplumber
import PyPDF2
from pdf2image import convert_from_path
import pytesseract
from PIL import Image


class HansardTextExtractor:
    def __init__(self, pdf_dir="./pdfs", output_dir="./extracted_text"):
        """
        Initialize the text extractor.

        Args:
            pdf_dir: Directory containing PDF files
            output_dir: Directory to save extracted text
        """
        self.pdf_dir = Path(pdf_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories for different output formats
        (self.output_dir / "raw_text").mkdir(exist_ok=True)
        (self.output_dir / "structured_json").mkdir(exist_ok=True)

        self.metadata_file = self.output_dir / "extraction_metadata.json"
        self.metadata = self._load_metadata()

    def _load_metadata(self):
        """Load existing extraction metadata."""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r') as f:
                return json.load(f)
        return {"extracted": [], "failed": [], "last_run": None}

    def _save_metadata(self):
        """Save extraction metadata."""
        self.metadata["last_run"] = datetime.now().isoformat()
        with open(self.metadata_file, 'w') as f:
            json.dump(self.metadata, f, indent=2)

    def extract_with_pdfplumber(self, pdf_path: Path) -> Optional[str]:
        """
        Extract text using pdfplumber (best for modern PDFs).

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted text or None if failed
        """
        try:
            text_pages = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    text = page.extract_text()
                    if text:
                        text_pages.append(text)

            full_text = "\n\n".join(text_pages)
            return full_text if full_text.strip() else None

        except Exception as e:
            print(f"pdfplumber failed for {pdf_path.name}: {e}")
            return None

    def extract_with_pypdf2(self, pdf_path: Path) -> Optional[str]:
        """
        Extract text using PyPDF2 (fallback method).

        Args:
            pdf_path: Path to PDF file

        Returns:
            Extracted text or None if failed
        """
        try:
            text_pages = []
            with open(pdf_path, 'rb') as file:
                reader = PyPDF2.PdfReader(file)
                for page in reader.pages:
                    text = page.extract_text()
                    if text:
                        text_pages.append(text)

            full_text = "\n\n".join(text_pages)
            return full_text if full_text.strip() else None

        except Exception as e:
            print(f"PyPDF2 failed for {pdf_path.name}: {e}")
            return None

    def extract_with_ocr(self, pdf_path: Path, max_pages: int = None) -> Optional[str]:
        """
        Extract text using OCR (for scanned/old PDFs from 1979-1991).

        Args:
            pdf_path: Path to PDF file
            max_pages: Maximum number of pages to OCR (None for all)

        Returns:
            Extracted text or None if failed
        """
        try:
            print(f"  Using OCR (this may take a while)...")

            # Convert PDF to images
            images = convert_from_path(pdf_path, dpi=300)

            if max_pages:
                images = images[:max_pages]

            # OCR each page
            text_pages = []
            for i, image in enumerate(images, 1):
                print(f"    OCR page {i}/{len(images)}...", end='\r')
                text = pytesseract.image_to_string(image, lang='eng')
                text_pages.append(text)

            print()  # New line after progress

            full_text = "\n\n".join(text_pages)
            return full_text if full_text.strip() else None

        except Exception as e:
            print(f"OCR failed for {pdf_path.name}: {e}")
            return None

    def detect_pdf_type(self, pdf_path: Path) -> str:
        """
        Detect if PDF is digital or scanned based on text extractability.

        Args:
            pdf_path: Path to PDF file

        Returns:
            'digital' or 'scanned'
        """
        try:
            with pdfplumber.open(pdf_path) as pdf:
                # Check first page
                first_page_text = pdf.pages[0].extract_text()

                # If first page has substantial text, it's likely digital
                if first_page_text and len(first_page_text.strip()) > 100:
                    return 'digital'
                else:
                    return 'scanned'

        except Exception:
            return 'scanned'  # Assume scanned if we can't extract

    def extract_pdf(self, pdf_path: Path, force_ocr: bool = False) -> Dict:
        """
        Extract text from a single PDF, choosing the best method.

        Args:
            pdf_path: Path to PDF file
            force_ocr: Force OCR even for digital PDFs

        Returns:
            Dict with extraction results
        """
        print(f"Processing: {pdf_path.name}")

        result = {
            "filename": pdf_path.name,
            "path": str(pdf_path),
            "timestamp": datetime.now().isoformat(),
            "success": False,
            "method": None,
            "text_length": 0,
            "page_count": 0
        }

        # Detect PDF type
        pdf_type = self.detect_pdf_type(pdf_path)
        print(f"  Detected type: {pdf_type}")

        text = None

        # Try extraction methods in order of preference
        if not force_ocr and pdf_type == 'digital':
            # Try pdfplumber first
            text = self.extract_with_pdfplumber(pdf_path)
            if text:
                result["method"] = "pdfplumber"

            # Fallback to PyPDF2
            if not text:
                text = self.extract_with_pypdf2(pdf_path)
                if text:
                    result["method"] = "pypdf2"

        # Use OCR for scanned PDFs or if digital extraction failed
        if not text or force_ocr:
            text = self.extract_with_ocr(pdf_path)
            if text:
                result["method"] = "ocr"

        if text:
            result["success"] = True
            result["text_length"] = len(text)
            result["text"] = text

            # Save raw text
            output_filename = pdf_path.stem + ".txt"
            output_path = self.output_dir / "raw_text" / output_filename

            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(text)

            result["output_file"] = str(output_path)
            print(f"  ✓ Extracted {len(text):,} characters using {result['method']}")

        else:
            print(f"  ✗ Failed to extract text")

        return result

    def extract_all(self, pattern: str = "*.pdf", force_ocr: bool = False):
        """
        Extract text from all PDFs in the directory.

        Args:
            pattern: Glob pattern for PDF files
            force_ocr: Force OCR for all files
        """
        pdf_files = list(self.pdf_dir.glob(pattern))
        print(f"Found {len(pdf_files)} PDF files")

        successful = 0
        failed = 0

        for i, pdf_path in enumerate(pdf_files, 1):
            print(f"\n[{i}/{len(pdf_files)}]")

            result = self.extract_pdf(pdf_path, force_ocr=force_ocr)

            if result["success"]:
                self.metadata["extracted"].append(result)
                successful += 1
            else:
                self.metadata["failed"].append(result)
                failed += 1

            # Save metadata periodically
            if i % 10 == 0:
                self._save_metadata()

        # Final save
        self._save_metadata()

        print(f"\n{'='*60}")
        print(f"Extraction complete!")
        print(f"Successful: {successful}")
        print(f"Failed: {failed}")
        print(f"Total characters extracted: {sum(r.get('text_length', 0) for r in self.metadata['extracted']):,}")

    def parse_hansard_structure(self, text: str, filename: str) -> Dict:
        """
        Parse Hansard text into structured format with speakers, topics, etc.

        Args:
            text: Raw extracted text
            filename: Original filename for metadata

        Returns:
            Structured dict with parsed Hansard data
        """
        # Extract date from filename (pattern may vary)
        date_match = re.search(r'(\d{4})-(\d{2})-(\d{2})', filename)
        date = date_match.group(0) if date_match else None

        # Determine house (Assembly or Council)
        house = None
        if 'HA' in filename or 'Assembly' in text[:500]:
            house = "House of Assembly"
        elif 'LC' in filename or 'Council' in text[:500]:
            house = "Legislative Council"

        # Split into speaker turns
        # Common patterns: "Mr MEMBER:", "Ms MEMBER:", "Member Name:"
        speaker_pattern = r'\n([A-Z][a-z]+\.?\s+[A-Z\s]+):\s*'
        segments = re.split(speaker_pattern, text)

        speakers = []
        current_speaker = None

        for i, segment in enumerate(segments):
            if i % 2 == 1:  # Odd indices are speaker names
                current_speaker = segment.strip()
            elif i % 2 == 0 and current_speaker and segment.strip():
                # Even indices are speech content
                speakers.append({
                    "name": current_speaker,
                    "text": segment.strip()
                })

        structured_data = {
            "filename": filename,
            "date": date,
            "house": house,
            "speakers": speakers,
            "full_text": text,
            "metadata": {
                "char_count": len(text),
                "speaker_count": len(speakers),
                "parsed_timestamp": datetime.now().isoformat()
            }
        }

        return structured_data

    def create_structured_dataset(self):
        """
        Convert all extracted raw text into structured JSON format.
        """
        print("Creating structured dataset from raw text...")

        raw_text_dir = self.output_dir / "raw_text"
        structured_dir = self.output_dir / "structured_json"

        text_files = list(raw_text_dir.glob("*.txt"))
        print(f"Found {len(text_files)} text files to structure")

        for i, text_file in enumerate(text_files, 1):
            print(f"[{i}/{len(text_files)}] Structuring: {text_file.name}")

            with open(text_file, 'r', encoding='utf-8') as f:
                text = f.read()

            structured = self.parse_hansard_structure(text, text_file.stem)

            # Save as JSON
            json_path = structured_dir / (text_file.stem + ".json")
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(structured, f, indent=2, ensure_ascii=False)

        print(f"Structured dataset created in {structured_dir}")


def main():
    parser = argparse.ArgumentParser(description='Extract text from Hansard PDFs')
    parser.add_argument('--pdf-dir', type=str, default='./pdfs', help='Directory containing PDFs')
    parser.add_argument('--output-dir', type=str, default='./extracted_text', help='Output directory')
    parser.add_argument('--force-ocr', action='store_true', help='Force OCR for all PDFs')
    parser.add_argument('--pattern', type=str, default='*.pdf', help='Glob pattern for PDF files')
    parser.add_argument('--structure', action='store_true', help='Create structured dataset after extraction')

    args = parser.parse_args()

    extractor = HansardTextExtractor(pdf_dir=args.pdf_dir, output_dir=args.output_dir)

    # Extract text from PDFs
    extractor.extract_all(pattern=args.pattern, force_ocr=args.force_ocr)

    # Optionally create structured dataset
    if args.structure:
        extractor.create_structured_dataset()


if __name__ == '__main__':
    main()
