"""
Script 5: Unified Text Cleaning Pipeline
==========================================
Cleans all collected raw text files and outputs to data/cleaned/.
Runs AFTER all collection scripts (1-4).

Operations:
  - Encoding normalization (UTF-8, curly quotes, dashes)
  - PDF artifact removal (page numbers, headers/footers)
  - Transcript cleanup (timestamps, filler words, broken lines)
  - LaTeX cleanup (for CS229 notes)
  - Whitespace normalization
"""

import os
import sys
import json
import re
from datetime import datetime, timezone
from pathlib import Path


# --- Configuration ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = PROJECT_ROOT / "data" / "raw"
CLEANED_DIR = PROJECT_ROOT / "data" / "cleaned"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"

# Subdirectories to process
SUBDIRS = ["pdfs", "transcripts", "the_batch", "blog_posts"]

# Filler words to remove from transcripts (only spoken content)
FILLER_WORDS = [
    r'\bum\b', r'\buh\b', r'\bumm\b', r'\buhh\b',
    r'\byou know\b', r'\blike,\b',  # "like" only when followed by comma (filler usage)
    r'\bkind of like\b',
    r'\bso,\s+so\b',  # Repeated "so, so"
]

# LaTeX symbol replacements (common in CS229 notes)
LATEX_REPLACEMENTS = {
    r'\\theta': 'θ',
    r'\\alpha': 'α',
    r'\\beta': 'β',
    r'\\gamma': 'γ',
    r'\\delta': 'δ',
    r'\\epsilon': 'ε',
    r'\\lambda': 'λ',
    r'\\mu': 'μ',
    r'\\sigma': 'σ',
    r'\\phi': 'φ',
    r'\\psi': 'ψ',
    r'\\omega': 'ω',
    r'\\pi': 'π',
    r'\\nabla': '∇',
    r'\\partial': '∂',
    r'\\infty': '∞',
    r'\\sum': 'Σ',
    r'\\prod': 'Π',
    r'\\int': '∫',
    r'\\sqrt': '√',
    r'\\leq': '≤',
    r'\\geq': '≥',
    r'\\neq': '≠',
    r'\\approx': '≈',
    r'\\rightarrow': '→',
    r'\\leftarrow': '←',
    r'\\Rightarrow': '⇒',
    r'\\in': '∈',
    r'\\notin': '∉',
    r'\\subset': '⊂',
    r'\\forall': '∀',
    r'\\exists': '∃',
    r'\\cdot': '·',
    r'\\times': '×',
    r'\\hat\{([a-zA-Z])\}': r'\1̂',  # hat notation
    r'\\vec\{([a-zA-Z])\}': r'\1⃗',  # vector notation
    r'\\mathbb\{R\}': 'ℝ',
    r'\\mathbb\{E\}': '𝔼',
}


def normalize_encoding(text: str) -> str:
    """Fix encoding issues: curly quotes, dashes, special chars."""
    replacements = {
        '\u2018': "'",   # Left single quote
        '\u2019': "'",   # Right single quote
        '\u201c': '"',   # Left double quote
        '\u201d': '"',   # Right double quote
        '\u2013': '–',   # En dash (keep as-is, it's valid)
        '\u2014': '—',   # Em dash (keep as-is)
        '\u2026': '...',  # Ellipsis
        '\u00a0': ' ',   # Non-breaking space
        '\ufeff': '',    # BOM
        '\u200b': '',    # Zero-width space
        '\u200e': '',    # Left-to-right mark
        '\u200f': '',    # Right-to-left mark
    }
    for old, new in replacements.items():
        text = text.replace(old, new)
    return text


def clean_pdf_artifacts(text: str) -> str:
    """Remove common PDF extraction artifacts."""
    lines = text.split('\n')
    cleaned_lines = []

    for line in lines:
        stripped = line.strip()

        # Skip standalone page numbers
        if re.match(r'^\d{1,4}$', stripped):
            continue

        # Skip repeated headers/footers (common in lecture notes)
        if re.match(r'^(CS\s*229|Machine Learning|Andrew Ng|Stanford University)\s*$',
                    stripped, re.I):
            continue

        # Skip lines that are just underscores or dashes (formatting artifacts)
        if re.match(r'^[_\-=]{10,}$', stripped):
            continue

        # Keep the --- PAGE markers (our own metadata)
        if stripped.startswith('--- PAGE'):
            cleaned_lines.append(line)
            continue

        # Keep header lines (our metadata)
        if stripped.startswith('#'):
            cleaned_lines.append(line)
            continue

        cleaned_lines.append(line)

    return '\n'.join(cleaned_lines)


def clean_transcript(text: str) -> str:
    """Clean YouTube transcript-specific artifacts."""
    # Remove timestamp markers like [00:12:34] or (00:12:34)
    text = re.sub(r'[\[\(]\d{1,2}:\d{2}(?::\d{2})?[\]\)]', '', text)

    # Remove standalone timestamps
    text = re.sub(r'^\d{1,2}:\d{2}(?::\d{2})?\s*$', '', text, flags=re.MULTILINE)

    # Remove filler words (case-insensitive)
    for pattern in FILLER_WORDS:
        text = re.sub(pattern, '', text, flags=re.IGNORECASE)

    # Merge broken lines (YouTube transcripts often split mid-sentence)
    # If a line doesn't end with sentence-ending punctuation and the next line
    # starts with lowercase, merge them
    lines = text.split('\n')
    merged_lines = []
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if not line:
            merged_lines.append('')
            i += 1
            continue

        # Look ahead to merge with next line if needed
        while (i + 1 < len(lines) and
               line and
               not line[-1] in '.!?:' and
               lines[i + 1].strip() and
               lines[i + 1].strip()[0].islower()):
            i += 1
            line = line + ' ' + lines[i].strip()

        merged_lines.append(line)
        i += 1

    return '\n'.join(merged_lines)


def clean_latex(text: str) -> str:
    """Replace LaTeX notation with Unicode equivalents."""
    for latex_pattern, unicode_char in LATEX_REPLACEMENTS.items():
        text = re.sub(latex_pattern, unicode_char, text)

    # Remove remaining simple LaTeX commands that didn't match
    # e.g., \text{something} -> something
    text = re.sub(r'\\text\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\mathrm\{([^}]+)\}', r'\1', text)
    text = re.sub(r'\\mathbf\{([^}]+)\}', r'\1', text)

    # Remove \begin{} and \end{} blocks (keep content between)
    text = re.sub(r'\\begin\{[^}]+\}', '', text)
    text = re.sub(r'\\end\{[^}]+\}', '', text)

    # Remove remaining backslash-commands that are just noise
    # But be careful not to remove actual backslashes in text
    text = re.sub(r'\\[a-zA-Z]+(?:\{[^}]*\})?', '', text)

    return text


def normalize_whitespace(text: str) -> str:
    """Clean up excessive whitespace."""
    # Collapse multiple blank lines into at most 2
    text = re.sub(r'\n{4,}', '\n\n\n', text)

    # Remove trailing whitespace on each line
    lines = [line.rstrip() for line in text.split('\n')]
    text = '\n'.join(lines)

    # Remove leading/trailing whitespace from entire text
    text = text.strip()

    # Ensure file ends with a newline
    text += '\n'

    return text


def clean_file(input_path: Path, output_path: Path, file_type: str) -> dict:
    """
    Clean a single file based on its type.
    Returns a report of what was changed.
    """
    with open(input_path, 'r', encoding='utf-8', errors='replace') as f:
        original_text = f.read()

    text = original_text
    changes = []

    # Step 1: Encoding normalization (all file types)
    cleaned = normalize_encoding(text)
    if cleaned != text:
        changes.append("encoding_normalized")
    text = cleaned

    # Step 2: Type-specific cleaning
    if file_type == "pdfs":
        cleaned = clean_pdf_artifacts(text)
        if cleaned != text:
            changes.append("pdf_artifacts_removed")
        text = cleaned

        cleaned = clean_latex(text)
        if cleaned != text:
            changes.append("latex_cleaned")
        text = cleaned

    elif file_type == "transcripts":
        cleaned = clean_transcript(text)
        if cleaned != text:
            changes.append("transcript_cleaned")
        text = cleaned

    elif file_type in ["the_batch", "blog_posts"]:
        # Light cleaning only — these are already web-extracted text
        pass

    # Step 3: Whitespace normalization (all file types)
    cleaned = normalize_whitespace(text)
    if cleaned != text:
        changes.append("whitespace_normalized")
    text = cleaned

    # Save cleaned file
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(text)

    # Calculate stats
    original_chars = len(original_text)
    cleaned_chars = len(text)
    original_words = len(original_text.split())
    cleaned_words = len(text.split())

    return {
        "input_file": input_path.name,
        "output_file": output_path.name,
        "original_chars": original_chars,
        "cleaned_chars": cleaned_chars,
        "chars_removed": original_chars - cleaned_chars,
        "original_words": original_words,
        "cleaned_words": cleaned_words,
        "changes_applied": changes
    }


def main():
    print("=" * 60)
    print("PHASE 1 — SCRIPT 5: TEXT CLEANING PIPELINE")
    print("=" * 60)
    print()

    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    report = {
        "script": "clean_text.py",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "by_type": {},
        "summary": {}
    }

    total_files = 0
    total_original_words = 0
    total_cleaned_words = 0

    for subdir in SUBDIRS:
        raw_subdir = RAW_DIR / subdir
        clean_subdir = CLEANED_DIR / subdir

        if not raw_subdir.exists():
            print(f"[SKIP] {subdir}/ — directory not found")
            continue

        # Find all .txt files in the raw subdirectory
        txt_files = sorted(raw_subdir.glob("*.txt"))
        if not txt_files:
            print(f"[SKIP] {subdir}/ — no .txt files found")
            continue

        print(f"[{subdir.upper()}] Processing {len(txt_files)} files...")
        clean_subdir.mkdir(parents=True, exist_ok=True)

        type_results = []
        for i, input_path in enumerate(txt_files):
            output_path = clean_subdir / input_path.name

            result = clean_file(input_path, output_path, subdir)
            type_results.append(result)

            changes_str = ", ".join(result["changes_applied"]) if result["changes_applied"] else "no changes"
            chars_diff = result["chars_removed"]
            print(f"  [{i+1}/{len(txt_files)}] {input_path.name[:50]} "
                  f"({chars_diff:+d} chars) [{changes_str}]")

            total_files += 1
            total_original_words += result["original_words"]
            total_cleaned_words += result["cleaned_words"]

        report["by_type"][subdir] = {
            "files_processed": len(type_results),
            "details": type_results
        }
        print()

    # --- Summary ---
    report["summary"] = {
        "total_files_processed": total_files,
        "total_original_words": total_original_words,
        "total_cleaned_words": total_cleaned_words,
        "words_removed": total_original_words - total_cleaned_words,
        "reduction_percent": round(
            (1 - total_cleaned_words / total_original_words) * 100, 1
        ) if total_original_words > 0 else 0
    }

    report_path = METADATA_DIR / "cleaning_report.json"
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, indent=2, ensure_ascii=False)

    print("=" * 60)
    print(f"DONE — {total_files} files cleaned")
    print(f"  Original words: {total_original_words:,}")
    print(f"  Cleaned words:  {total_cleaned_words:,}")
    print(f"  Words removed:  {total_original_words - total_cleaned_words:,} "
          f"({report['summary']['reduction_percent']}%)")
    print(f"  Report: {report_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
