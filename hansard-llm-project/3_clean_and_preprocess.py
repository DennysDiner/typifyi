#!/usr/bin/env python3
"""
Tasmania Parliament Hansard Text Cleaning and Preprocessing

This script cleans and preprocesses extracted Hansard text for LLM training.
Handles headers, footers, OCR errors, formatting issues, and creates
training-ready datasets.

Usage:
    python 3_clean_and_preprocess.py --input-dir ./extracted_text --output-dir ./cleaned_data
"""

import argparse
import json
import re
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Tuple
from collections import Counter


class HansardCleaner:
    def __init__(self, input_dir="./extracted_text", output_dir="./cleaned_data"):
        """
        Initialize the text cleaner.

        Args:
            input_dir: Directory containing extracted text
            output_dir: Directory to save cleaned data
        """
        self.input_dir = Path(input_dir)
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)

        # Create subdirectories
        (self.output_dir / "cleaned_text").mkdir(exist_ok=True)
        (self.output_dir / "training_data").mkdir(exist_ok=True)

        # Common parliamentary header/footer patterns
        self.header_patterns = [
            r'HOUSE OF ASSEMBLY',
            r'LEGISLATIVE COUNCIL',
            r'PARLIAMENT OF TASMANIA',
            r'DRAFT HANSARD',
            r'UNCORRECTED PROOF',
            r'Page \d+',
            r'\d+ [A-Z][a-z]+ \d{4}',  # Dates
        ]

        # Common procedural text to remove or simplify
        self.procedural_patterns = [
            r'\[.*?interruption.*?\]',
            r'\[.*?laughter.*?\]',
            r'\[.*?applause.*?\]',
            r'\[.*?interjection.*?\]',
        ]

        # Speaker title patterns
        self.speaker_titles = [
            'Mr', 'Ms', 'Mrs', 'Dr', 'Hon', 'Honorable', 'Minister'
        ]

    def remove_headers_footers(self, text: str) -> str:
        """
        Remove common headers and footers from Hansard text.

        Args:
            text: Raw text

        Returns:
            Text with headers/footers removed
        """
        lines = text.split('\n')
        cleaned_lines = []

        for line in lines:
            # Skip if line matches header/footer patterns
            is_header = False
            for pattern in self.header_patterns:
                if re.search(pattern, line, re.IGNORECASE):
                    is_header = True
                    break

            # Skip very short lines (likely page numbers or artifacts)
            if len(line.strip()) < 3:
                continue

            if not is_header:
                cleaned_lines.append(line)

        return '\n'.join(cleaned_lines)

    def fix_ocr_errors(self, text: str) -> str:
        """
        Fix common OCR errors in scanned documents.

        Args:
            text: Text with potential OCR errors

        Returns:
            Text with common OCR errors fixed
        """
        # Common OCR substitutions
        ocr_fixes = {
            r'\bl\b': 'I',  # lowercase l mistaken for I
            r'\bO\b': '0',  # O mistaken for 0
            r'rn': 'm',     # rn mistaken for m (context-dependent)
            r'vv': 'w',     # vv mistaken for w
            r'[''`]': "'",  # Various apostrophes
            r'["""]': '"',  # Various quotes
            r'—': '-',      # Em dash
            r'–': '-',      # En dash
        }

        cleaned = text
        for pattern, replacement in ocr_fixes.items():
            cleaned = re.sub(pattern, replacement, cleaned)

        return cleaned

    def normalize_speaker_labels(self, text: str) -> str:
        """
        Normalize speaker labels to consistent format: [Speaker Name]:

        Args:
            text: Text with inconsistent speaker labels

        Returns:
            Text with normalized speaker labels
        """
        # Pattern: Title + Name(s) followed by colon or dash
        # Examples: "Mr SMITH:", "Hon. Dr. JONES -", "MS BROWN:"

        # Normalize to: [SPEAKER NAME]:
        pattern = r'\n([A-Z][a-z]+\.?\s+(?:[A-Z][a-z]+\.?\s+)*[A-Z]+)\s*[:\-]\s*'

        def replace_speaker(match):
            speaker = match.group(1).strip()
            # Remove periods from titles
            speaker = speaker.replace('.', '')
            return f"\n[{speaker}]: "

        normalized = re.sub(pattern, replace_speaker, text)

        return normalized

    def remove_procedural_text(self, text: str, keep_annotations: bool = False) -> str:
        """
        Remove or simplify procedural annotations.

        Args:
            text: Text with procedural annotations
            keep_annotations: If True, keep simplified versions

        Returns:
            Cleaned text
        """
        if keep_annotations:
            # Keep but simplify
            for pattern in self.procedural_patterns:
                text = re.sub(pattern, lambda m: m.group(0).lower(), text)
        else:
            # Remove completely
            for pattern in self.procedural_patterns:
                text = re.sub(pattern, '', text)

        return text

    def normalize_whitespace(self, text: str) -> str:
        """
        Normalize whitespace and line breaks.

        Args:
            text: Text with irregular whitespace

        Returns:
            Text with normalized whitespace
        """
        # Replace multiple spaces with single space
        text = re.sub(r' +', ' ', text)

        # Replace multiple newlines with double newline (paragraph break)
        text = re.sub(r'\n\n+', '\n\n', text)

        # Remove trailing whitespace from lines
        lines = [line.rstrip() for line in text.split('\n')]
        text = '\n'.join(lines)

        return text.strip()

    def extract_metadata(self, text: str, filename: str) -> Dict:
        """
        Extract metadata from Hansard text.

        Args:
            text: Hansard text
            filename: Source filename

        Returns:
            Metadata dict
        """
        metadata = {
            "filename": filename,
            "char_count": len(text),
            "word_count": len(text.split()),
        }

        # Extract date
        date_match = re.search(r'(\d{1,2})\s+(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{4})', text)
        if date_match:
            metadata["date"] = f"{date_match.group(3)}-{date_match.group(2)}-{date_match.group(1)}"

        # Extract house
        if 'HOUSE OF ASSEMBLY' in text[:1000]:
            metadata["house"] = "House of Assembly"
        elif 'LEGISLATIVE COUNCIL' in text[:1000]:
            metadata["house"] = "Legislative Council"

        # Count speakers
        speaker_matches = re.findall(r'\[([A-Z\s\.]+)\]:', text)
        metadata["speaker_count"] = len(set(speaker_matches))
        metadata["speakers"] = list(set(speaker_matches))

        return metadata

    def clean_text(self, text: str, filename: str) -> Tuple[str, Dict]:
        """
        Apply all cleaning steps to text.

        Args:
            text: Raw text
            filename: Source filename

        Returns:
            Tuple of (cleaned_text, metadata)
        """
        # Step 1: Remove headers and footers
        text = self.remove_headers_footers(text)

        # Step 2: Fix OCR errors
        text = self.fix_ocr_errors(text)

        # Step 3: Normalize speaker labels
        text = self.normalize_speaker_labels(text)

        # Step 4: Remove procedural text
        text = self.remove_procedural_text(text, keep_annotations=False)

        # Step 5: Normalize whitespace
        text = self.normalize_whitespace(text)

        # Extract metadata
        metadata = self.extract_metadata(text, filename)

        return text, metadata

    def clean_all(self, input_format: str = "raw_text"):
        """
        Clean all extracted text files.

        Args:
            input_format: Subdirectory containing text files ('raw_text' or 'structured_json')
        """
        if input_format == "raw_text":
            input_dir = self.input_dir / "raw_text"
            text_files = list(input_dir.glob("*.txt"))
        else:
            input_dir = self.input_dir / "structured_json"
            text_files = list(input_dir.glob("*.json"))

        print(f"Found {len(text_files)} files to clean")

        all_metadata = []

        for i, text_file in enumerate(text_files, 1):
            print(f"[{i}/{len(text_files)}] Cleaning: {text_file.name}")

            # Read text
            if input_format == "raw_text":
                with open(text_file, 'r', encoding='utf-8') as f:
                    text = f.read()
            else:
                with open(text_file, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    text = data.get('full_text', '')

            # Clean text
            cleaned_text, metadata = self.clean_text(text, text_file.stem)

            # Save cleaned text
            output_path = self.output_dir / "cleaned_text" / (text_file.stem + ".txt")
            with open(output_path, 'w', encoding='utf-8') as f:
                f.write(cleaned_text)

            all_metadata.append(metadata)

            print(f"  Original: {len(text):,} chars -> Cleaned: {len(cleaned_text):,} chars")

        # Save aggregated metadata
        metadata_path = self.output_dir / "cleaning_metadata.json"
        with open(metadata_path, 'w', encoding='utf-8') as f:
            json.dump(all_metadata, f, indent=2)

        print(f"\nCleaning complete!")
        print(f"Total documents: {len(all_metadata)}")
        print(f"Total characters: {sum(m['char_count'] for m in all_metadata):,}")
        print(f"Total words: {sum(m['word_count'] for m in all_metadata):,}")

    def create_training_dataset(self, format: str = "jsonl"):
        """
        Create training dataset in specified format for LLM fine-tuning.

        Args:
            format: Output format ('jsonl', 'txt', 'parquet')
        """
        print(f"Creating training dataset in {format} format...")

        cleaned_dir = self.output_dir / "cleaned_text"
        text_files = list(cleaned_dir.glob("*.txt"))

        if format == "jsonl":
            output_file = self.output_dir / "training_data" / "hansard_training.jsonl"

            with open(output_file, 'w', encoding='utf-8') as out:
                for text_file in text_files:
                    with open(text_file, 'r', encoding='utf-8') as f:
                        text = f.read()

                    # Create training example
                    # Format for instruction following: system + user prompt + assistant response
                    example = {
                        "text": text,
                        "source": "Tasmania Parliament Hansard",
                        "filename": text_file.name
                    }

                    out.write(json.dumps(example, ensure_ascii=False) + '\n')

            print(f"Created {output_file}")

        elif format == "txt":
            # Simple concatenated text file with document separators
            output_file = self.output_dir / "training_data" / "hansard_training.txt"

            with open(output_file, 'w', encoding='utf-8') as out:
                for i, text_file in enumerate(text_files):
                    with open(text_file, 'r', encoding='utf-8') as f:
                        text = f.read()

                    out.write(text)
                    out.write('\n\n' + '='*80 + '\n\n')  # Document separator

            print(f"Created {output_file}")

        # Calculate dataset statistics
        total_chars = sum(len(open(f, 'r', encoding='utf-8').read()) for f in text_files)
        total_words = sum(len(open(f, 'r', encoding='utf-8').read().split()) for f in text_files)
        estimated_tokens = total_words * 1.3  # Rough estimate

        print(f"\nDataset statistics:")
        print(f"  Documents: {len(text_files)}")
        print(f"  Total characters: {total_chars:,}")
        print(f"  Total words: {total_words:,}")
        print(f"  Estimated tokens: {estimated_tokens:,.0f}")

    def create_instruction_dataset(self):
        """
        Create instruction-following dataset for supervised fine-tuning.

        Generates Q&A pairs, summarization tasks, etc. from Hansard text.
        """
        print("Creating instruction-following dataset...")

        cleaned_dir = self.output_dir / "cleaned_text"
        text_files = list(cleaned_dir.glob("*.txt"))

        output_file = self.output_dir / "training_data" / "hansard_instructions.jsonl"

        with open(output_file, 'w', encoding='utf-8') as out:
            for text_file in text_files:
                with open(text_file, 'r', encoding='utf-8') as f:
                    text = f.read()

                # Extract speaker segments
                segments = re.split(r'\[([A-Z\s\.]+)\]:', text)

                speakers_content = []
                for i in range(1, len(segments), 2):
                    if i+1 < len(segments):
                        speaker = segments[i].strip()
                        content = segments[i+1].strip()
                        if content:
                            speakers_content.append((speaker, content))

                # Create various instruction types

                # Type 1: "What did [Speaker] say about...?"
                if speakers_content:
                    for speaker, content in speakers_content[:3]:  # Sample a few
                        # Extract first few sentences as summary
                        sentences = content.split('.')[:2]
                        summary = '. '.join(sentences).strip() + '.'

                        example = {
                            "instruction": f"What did {speaker} discuss in the Tasmania Parliament?",
                            "input": "",
                            "output": summary,
                            "source": text_file.name
                        }
                        out.write(json.dumps(example, ensure_ascii=False) + '\n')

                # Type 2: "Summarize this debate"
                if len(text) > 500:
                    example = {
                        "instruction": "Summarize the key points from this parliamentary debate.",
                        "input": text[:2000] + "...",  # First portion
                        "output": "This parliamentary session discussed various legislative matters...",
                        "source": text_file.name
                    }
                    out.write(json.dumps(example, ensure_ascii=False) + '\n')

        print(f"Created {output_file}")


def main():
    parser = argparse.ArgumentParser(description='Clean and preprocess Hansard text')
    parser.add_argument('--input-dir', type=str, default='./extracted_text',
                       help='Directory containing extracted text')
    parser.add_argument('--output-dir', type=str, default='./cleaned_data',
                       help='Output directory')
    parser.add_argument('--input-format', type=str, default='raw_text',
                       choices=['raw_text', 'structured_json'],
                       help='Input format to process')
    parser.add_argument('--create-training', action='store_true',
                       help='Create training dataset after cleaning')
    parser.add_argument('--format', type=str, default='jsonl',
                       choices=['jsonl', 'txt', 'parquet'],
                       help='Training dataset format')
    parser.add_argument('--instruction-dataset', action='store_true',
                       help='Create instruction-following dataset')

    args = parser.parse_args()

    cleaner = HansardCleaner(input_dir=args.input_dir, output_dir=args.output_dir)

    # Clean all text files
    cleaner.clean_all(input_format=args.input_format)

    # Optionally create training dataset
    if args.create_training:
        cleaner.create_training_dataset(format=args.format)

    # Optionally create instruction dataset
    if args.instruction_dataset:
        cleaner.create_instruction_dataset()


if __name__ == '__main__':
    main()
