"""
Script 1: PDF Download + Text Extraction
=========================================
Downloads CS229 notes and MLY PDFs, detects local Career in AI ebook,
extracts text page-by-page, and generates a manifest.

Sources:
  1. CS229 Lecture Notes (Stanford 2022) - download from cs229.stanford.edu
  2. Machine Learning Yearning - download from GitHub
  3. How to Build Your Career in AI - local file (already downloaded by user)
"""

import os
import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import fitz  # PyMuPDF
except ImportError:
    print("ERROR: PyMuPDF not installed. Run: pip install PyMuPDF")
    sys.exit(1)

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)


# --- Configuration ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_PDF_DIR = PROJECT_ROOT / "data" / "raw" / "pdfs"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"

# PDF sources to download
DOWNLOAD_SOURCES = {
    "cs229_lecture_notes_2022": {
        "url": "https://cs229.stanford.edu/main_notes.pdf",
        "filename": "cs229_lecture_notes_2022.pdf",
        "domain_tag": "ml_theory",
        "description": "Stanford CS229 Machine Learning Lecture Notes (2022 edition)"
    },
    "machine_learning_yearning": {
        "url": "https://raw.githubusercontent.com/ajaymache/machine-learning-yearning/master/full%20book/machine-learning-yearning.pdf",
        "filename": "machine_learning_yearning.pdf",
        "domain_tag": "ml_theory",
        "description": "Machine Learning Yearning by Andrew Ng (deeplearning.ai, 2018)"
    }
}

# Local PDF (already downloaded by user)
LOCAL_PDFS = {
    "career_in_ai_ebook": {
        "search_patterns": [
            "eBook-How-to-Build-a-Career-in-AI.pdf",
            "How-to-Build-a-Career-in-AI.pdf",
            "career_in_ai.pdf"
        ],
        "domain_tag": "career_advice",
        "description": "How to Build Your Career in AI by Andrew Ng (deeplearning.ai)"
    }
}


def download_pdf(url: str, save_path: Path, description: str) -> bool:
    """Download a PDF from a URL with retry logic."""
    if save_path.exists():
        print(f"  [SKIP] Already exists: {save_path.name}")
        return True

    print(f"  [DOWNLOAD] {description}")
    print(f"    URL: {url}")

    max_retries = 3
    for attempt in range(1, max_retries + 1):
        try:
            response = requests.get(url, timeout=60, stream=True)
            response.raise_for_status()

            total_size = int(response.headers.get('content-length', 0))
            downloaded = 0

            with open(save_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
                    downloaded += len(chunk)

            file_size = save_path.stat().st_size
            print(f"    Saved: {save_path.name} ({file_size / 1024:.1f} KB)")
            return True

        except requests.RequestException as e:
            print(f"    Attempt {attempt}/{max_retries} failed: {e}")
            if attempt < max_retries:
                wait = 2 ** attempt
                print(f"    Retrying in {wait}s...")
                time.sleep(wait)
            else:
                print(f"    [FAILED] Could not download after {max_retries} attempts")
                return False


def find_local_pdf(search_patterns: list[str]) -> Path | None:
    """Search project root for a local PDF matching any of the patterns."""
    for pattern in search_patterns:
        candidate = PROJECT_ROOT / pattern
        if candidate.exists():
            return candidate

    # Also search data/raw/pdfs/ in case it was moved there
    for pattern in search_patterns:
        candidate = RAW_PDF_DIR / pattern
        if candidate.exists():
            return candidate

    return None


def extract_text_from_pdf(pdf_path: Path, output_dir: Path, source_key: str, domain_tag: str) -> dict:
    """
    Extract text from a PDF page-by-page using PyMuPDF.
    Returns metadata about the extraction.
    """
    print(f"  [EXTRACT] {pdf_path.name}")

    doc = fitz.open(str(pdf_path))
    total_pages = len(doc)
    total_chars = 0

    # Output as single file with page markers
    output_filename = f"{source_key}.txt"
    output_path = output_dir / output_filename

    with open(output_path, 'w', encoding='utf-8') as f:
        # Write header metadata
        f.write(f"# Source: {pdf_path.name}\n")
        f.write(f"# Domain: {domain_tag}\n")
        f.write(f"# Pages: {total_pages}\n")
        f.write(f"# Extracted: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"{'='*80}\n\n")

        for page_num in range(total_pages):
            page = doc[page_num]
            text = page.get_text("text")

            if text.strip():
                f.write(f"\n--- PAGE {page_num + 1} ---\n\n")
                f.write(text)
                f.write("\n")
                total_chars += len(text)

    doc.close()

    print(f"    Pages: {total_pages} | Characters: {total_chars:,} | Output: {output_filename}")

    return {
        "source_key": source_key,
        "source_file": pdf_path.name,
        "domain_tag": domain_tag,
        "total_pages": total_pages,
        "total_characters": total_chars,
        "output_file": output_filename,
        "extracted_at": datetime.now(timezone.utc).isoformat()
    }


def main():
    print("=" * 60)
    print("PHASE 1 — SCRIPT 1: PDF COLLECTION & EXTRACTION")
    print("=" * 60)
    print()

    # Ensure directories exist
    RAW_PDF_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "script": "collect_pdfs.py",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "sources": []
    }

    # --- Step 1: Download remote PDFs ---
    print("[1/3] Downloading remote PDFs...")
    for key, source in DOWNLOAD_SOURCES.items():
        save_path = RAW_PDF_DIR / source["filename"]
        success = download_pdf(source["url"], save_path, source["description"])

        if success:
            # Extract text
            meta = extract_text_from_pdf(
                save_path, RAW_PDF_DIR, key, source["domain_tag"]
            )
            meta["url"] = source["url"]
            meta["description"] = source["description"]
            meta["status"] = "success"
            manifest["sources"].append(meta)
        else:
            manifest["sources"].append({
                "source_key": key,
                "url": source["url"],
                "description": source["description"],
                "status": "failed",
                "error": "Download failed after retries"
            })
        print()

    # --- Step 2: Find and process local PDFs ---
    print("[2/3] Looking for local PDFs...")
    for key, source in LOCAL_PDFS.items():
        local_path = find_local_pdf(source["search_patterns"])

        if local_path:
            print(f"  [FOUND] {local_path.name}")

            # Copy to raw/pdfs/ if not already there
            dest_path = RAW_PDF_DIR / local_path.name
            if not dest_path.exists() and local_path != dest_path:
                import shutil
                shutil.copy2(local_path, dest_path)
                print(f"  [COPY] Copied to {dest_path}")
            elif local_path == dest_path:
                dest_path = local_path

            # Extract text
            meta = extract_text_from_pdf(
                dest_path, RAW_PDF_DIR, key, source["domain_tag"]
            )
            meta["original_location"] = str(local_path)
            meta["description"] = source["description"]
            meta["status"] = "success"
            manifest["sources"].append(meta)
        else:
            patterns = ", ".join(source["search_patterns"])
            print(f"  [NOT FOUND] Searched for: {patterns}")
            print(f"    Please place the Career in AI ebook PDF in the project root")
            manifest["sources"].append({
                "source_key": key,
                "description": source["description"],
                "status": "not_found",
                "searched_patterns": source["search_patterns"]
            })
        print()

    # --- Step 3: Save manifest ---
    print("[3/3] Saving manifest...")
    manifest_path = METADATA_DIR / "pdfs_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)
    print(f"  Manifest saved: {manifest_path}")

    # --- Summary ---
    success_count = sum(1 for s in manifest["sources"] if s.get("status") == "success")
    total_count = len(manifest["sources"])
    print()
    print("=" * 60)
    print(f"DONE — {success_count}/{total_count} PDFs collected and extracted")
    print("=" * 60)


if __name__ == "__main__":
    main()
