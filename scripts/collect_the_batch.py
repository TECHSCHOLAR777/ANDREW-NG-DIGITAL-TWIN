"""
Script 3: The Batch Newsletter Scraper
========================================
Crawls the deeplearning.ai Batch newsletter archive and extracts
Andrew Ng's editorial letters and article summaries from all issues.

Source: https://www.deeplearning.ai/the-batch/
Estimated volume: 300+ weekly issues (since 2019)
"""

import os
import sys
import json
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("ERROR: beautifulsoup4 not installed. Run: pip install beautifulsoup4")
    sys.exit(1)


# --- Configuration ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_BATCH_DIR = PROJECT_ROOT / "data" / "raw" / "the_batch"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"

BASE_URL = "https://www.deeplearning.ai/the-batch/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

# Polite crawling delay (seconds)
REQUEST_DELAY = 2.0
PAGE_DELAY = 3.0


def fetch_page(url: str, retries: int = 3) -> str | None:
    """Fetch a page with retry logic."""
    for attempt in range(1, retries + 1):
        try:
            response = requests.get(url, headers=HEADERS, timeout=30)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            if attempt < retries:
                wait = 2 ** attempt
                print(f"    Retry {attempt}/{retries} in {wait}s: {e}")
                time.sleep(wait)
            else:
                print(f"    [FAILED] {url}: {e}")
                return None


def get_all_issue_urls() -> list[dict]:
    """
    Crawl the Batch archive to collect all issue URLs.
    The Batch archive page may use pagination or infinite scroll.
    We'll try multiple strategies.
    """
    print("  Fetching archive page...")
    all_issues = []
    seen_urls = set()

    # Strategy 1: Try paginated archive
    page_num = 1
    max_pages = 100  # Safety limit

    while page_num <= max_pages:
        if page_num == 1:
            url = BASE_URL
        else:
            url = f"{BASE_URL}page/{page_num}/"

        html = fetch_page(url)
        if not html:
            break

        soup = BeautifulSoup(html, 'lxml')

        # Look for article links - common patterns on The Batch
        found_new = False
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(BASE_URL, href)

            # Match Batch issue URLs (they typically contain /the-batch/ followed by a slug)
            if '/the-batch/' in full_url and full_url != BASE_URL:
                # Filter out pagination, category, and tag links
                if any(x in full_url for x in ['/page/', '/category/', '/tag/', '#']):
                    continue

                # Must be a specific article URL (has a slug after /the-batch/)
                slug_match = re.search(r'/the-batch/([a-z0-9\-]+)/?$', full_url)
                if slug_match and full_url not in seen_urls:
                    seen_urls.add(full_url)
                    title_text = link.get_text(strip=True)
                    all_issues.append({
                        "url": full_url,
                        "slug": slug_match.group(1),
                        "title_hint": title_text[:100] if title_text else ""
                    })
                    found_new = True

        if not found_new:
            print(f"    No new links found on page {page_num}, stopping pagination.")
            break

        print(f"    Page {page_num}: found {len(all_issues)} total issues so far")
        page_num += 1
        time.sleep(PAGE_DELAY)

    # Deduplicate by URL
    unique_issues = []
    seen = set()
    for issue in all_issues:
        if issue["url"] not in seen:
            seen.add(issue["url"])
            unique_issues.append(issue)

    print(f"  Total unique issue URLs found: {len(unique_issues)}")
    return unique_issues


def extract_issue_content(url: str, slug: str) -> dict | None:
    """
    Extract content from a single Batch issue page.
    Focuses on:
    1. Andrew Ng's editorial letter (Dear Friends / top letter)
    2. Article summaries
    """
    html = fetch_page(url)
    if not html:
        return None

    soup = BeautifulSoup(html, 'lxml')

    # --- Extract title ---
    title_tag = soup.find('h1')
    title = title_tag.get_text(strip=True) if title_tag else slug

    # --- Extract date ---
    # Look for date in meta tags, time elements, or text patterns
    date_str = ""

    # Try meta tags
    for meta in soup.find_all('meta'):
        if meta.get('property') in ['article:published_time', 'og:article:published_time']:
            date_str = meta.get('content', '')
            break

    # Try time elements
    if not date_str:
        time_tag = soup.find('time')
        if time_tag:
            date_str = time_tag.get('datetime', '') or time_tag.get_text(strip=True)

    # --- Extract main content ---
    # The Batch typically has the content in article or main content div
    content_areas = []

    # Try article tag first
    article = soup.find('article')
    if article:
        content_areas.append(article)
    else:
        # Try common content div classes
        for cls in ['entry-content', 'post-content', 'article-content', 'content-area']:
            div = soup.find('div', class_=re.compile(cls, re.I))
            if div:
                content_areas.append(div)
                break

    if not content_areas:
        # Fallback: get main content area
        main = soup.find('main')
        if main:
            content_areas.append(main)

    # Extract text from content areas
    editorial_text = ""
    full_text = ""

    for area in content_areas:
        paragraphs = area.find_all(['p', 'h2', 'h3', 'h4', 'li', 'blockquote'])
        texts = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text and len(text) > 10:  # Filter noise
                if p.name in ['h2', 'h3', 'h4']:
                    texts.append(f"\n## {text}\n")
                elif p.name == 'blockquote':
                    texts.append(f"> {text}")
                else:
                    texts.append(text)

        full_text = "\n\n".join(texts)

        # Try to identify Ng's editorial letter
        # It often starts with "Dear friends" or is the first substantial section
        dear_friends_match = re.search(
            r'(Dear [Ff]riends.*?)(?=\n##|\n\n[A-Z][A-Z]|\Z)',
            full_text, re.DOTALL
        )
        if dear_friends_match:
            editorial_text = dear_friends_match.group(1).strip()

    if not full_text.strip():
        return None

    return {
        "url": url,
        "slug": slug,
        "title": title,
        "date": date_str,
        "editorial_text": editorial_text,
        "full_text": full_text,
        "has_editorial": bool(editorial_text),
        "word_count": len(full_text.split()),
        "editorial_word_count": len(editorial_text.split()) if editorial_text else 0
    }


def save_issue(output_dir: Path, issue_data: dict) -> str:
    """Save a Batch issue to a text file."""
    slug = issue_data["slug"]
    date_prefix = ""
    if issue_data["date"]:
        # Try to extract YYYY-MM-DD from date string
        date_match = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2})', issue_data["date"])
        if date_match:
            date_prefix = date_match.group(1).replace('/', '-') + "_"

    filename = f"batch_{date_prefix}{slug}.txt"
    output_path = output_dir / filename

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# Title: {issue_data['title']}\n")
        f.write(f"# URL: {issue_data['url']}\n")
        f.write(f"# Date: {issue_data['date']}\n")
        f.write(f"# Domain: ai_strategy\n")
        f.write(f"# Has Editorial: {issue_data['has_editorial']}\n")
        f.write(f"# Extracted: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"{'='*80}\n\n")

        if issue_data["editorial_text"]:
            f.write("## ANDREW NG EDITORIAL\n\n")
            f.write(issue_data["editorial_text"])
            f.write("\n\n")
            f.write(f"{'─'*40}\n\n")

        f.write("## FULL ISSUE CONTENT\n\n")
        f.write(issue_data["full_text"])
        f.write("\n")

    return filename


def main():
    print("=" * 60)
    print("PHASE 1 - SCRIPT 3: THE BATCH NEWSLETTER SCRAPER")
    print("=" * 60)
    print()

    # Ensure directories exist
    RAW_BATCH_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "script": "collect_the_batch.py",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BASE_URL,
        "issues": [],
        "summary": {}
    }

    # --- Step 1: Get all issue URLs ---
    print("[1/2] Crawling archive for issue URLs...")
    issues = get_all_issue_urls()

    if not issues:
        print("  [ERROR] No issue URLs found. The website structure may have changed.")
        print("  Try manually inspecting the page source or using Selenium.")
        manifest["summary"] = {"status": "failed", "error": "No issue URLs found"}
        manifest_path = METADATA_DIR / "batch_manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        return

    # --- Step 2: Extract content from each issue ---
    print()
    print(f"[2/2] Extracting content from {len(issues)} issues...")
    success_count = 0
    fail_count = 0
    editorial_count = 0
    total_words = 0

    for i, issue in enumerate(issues):
        url = issue["url"]
        slug = issue["slug"]

        print(f"  [{i+1}/{len(issues)}] {slug[:50]}...", end=" ")

        content = extract_issue_content(url, slug)

        if content:
            filename = save_issue(RAW_BATCH_DIR, content)
            content["output_file"] = filename
            content["status"] = "success"
            # Remove large text fields from manifest (keep metadata only)
            meta_entry = {k: v for k, v in content.items()
                         if k not in ["editorial_text", "full_text"]}
            manifest["issues"].append(meta_entry)
            success_count += 1
            total_words += content["word_count"]
            if content["has_editorial"]:
                editorial_count += 1
            print(f"[OK] ({content['word_count']} words"
                  f"{', has editorial' if content['has_editorial'] else ''})")
        else:
            manifest["issues"].append({
                "url": url,
                "slug": slug,
                "status": "failed"
            })
            fail_count += 1
            print("[FAIL]")

        time.sleep(REQUEST_DELAY)

    # --- Summary ---
    manifest["summary"] = {
        "total_attempted": len(issues),
        "total_success": success_count,
        "total_failed": fail_count,
        "editorial_count": editorial_count,
        "total_words": total_words,
        "estimated_pages": total_words // 300
    }

    manifest_path = METADATA_DIR / "batch_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print(f"DONE - {success_count} issues collected ({fail_count} failed)")
    print(f"  Editorials found: {editorial_count}")
    print(f"  Total words: {total_words:,}")
    print(f"  Manifest: {manifest_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
