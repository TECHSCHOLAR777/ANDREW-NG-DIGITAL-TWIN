"""
Script 4: deeplearning.ai Blog Post Scraper
=============================================
Crawls the deeplearning.ai blog for posts by Andrew Ng.
Extracts title, date, author, and body text.

Source: https://www.deeplearning.ai/blog/
Key posts: "AI is the New Electricity", "Unbiggen AI", opinion pieces
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
RAW_BLOG_DIR = PROJECT_ROOT / "data" / "raw" / "blog_posts"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"

BLOG_URL = "https://www.deeplearning.ai/blog/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
}

REQUEST_DELAY = 2.0
PAGE_DELAY = 3.0

# Keywords to identify Andrew Ng authored or relevant posts
NG_AUTHOR_PATTERNS = [
    "andrew ng", "andrew", "ng",
    "dear friends",  # His Batch-style editorial opener
]


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


def get_all_blog_post_urls() -> list[dict]:
    """Crawl the blog archive to collect all post URLs."""
    print("  Fetching blog archive...")
    all_posts = []
    seen_urls = set()

    page_num = 1
    max_pages = 50

    while page_num <= max_pages:
        if page_num == 1:
            url = BLOG_URL
        else:
            url = f"{BLOG_URL}page/{page_num}/"

        html = fetch_page(url)
        if not html:
            break

        soup = BeautifulSoup(html, 'lxml')

        found_new = False
        for link in soup.find_all('a', href=True):
            href = link['href']
            full_url = urljoin(BLOG_URL, href)

            # Match blog post URLs
            if '/blog/' in full_url and full_url != BLOG_URL:
                # Filter out pagination, category links
                if any(x in full_url for x in ['/page/', '/category/', '/tag/', '#', '/author/']):
                    continue

                slug_match = re.search(r'/blog/([a-z0-9\-]+)/?$', full_url)
                if slug_match and full_url not in seen_urls:
                    seen_urls.add(full_url)
                    title_text = link.get_text(strip=True)
                    all_posts.append({
                        "url": full_url,
                        "slug": slug_match.group(1),
                        "title_hint": title_text[:100] if title_text else ""
                    })
                    found_new = True

        if not found_new:
            print(f"    No new links on page {page_num}, stopping.")
            break

        print(f"    Page {page_num}: found {len(all_posts)} total posts so far")
        page_num += 1
        time.sleep(PAGE_DELAY)

    # Deduplicate
    unique_posts = []
    seen = set()
    for post in all_posts:
        if post["url"] not in seen:
            seen.add(post["url"])
            unique_posts.append(post)

    print(f"  Total unique blog post URLs found: {len(unique_posts)}")
    return unique_posts


def extract_blog_post(url: str, slug: str) -> dict | None:
    """Extract content from a single blog post page."""
    html = fetch_page(url)
    if not html:
        return None

    soup = BeautifulSoup(html, 'lxml')

    # --- Title ---
    title_tag = soup.find('h1')
    title = title_tag.get_text(strip=True) if title_tag else slug

    # --- Date ---
    date_str = ""
    for meta in soup.find_all('meta'):
        if meta.get('property') in ['article:published_time', 'og:article:published_time']:
            date_str = meta.get('content', '')
            break
    if not date_str:
        time_tag = soup.find('time')
        if time_tag:
            date_str = time_tag.get('datetime', '') or time_tag.get_text(strip=True)

    # --- Author ---
    author = ""
    # Check meta tags
    for meta in soup.find_all('meta'):
        if meta.get('name', '').lower() == 'author':
            author = meta.get('content', '')
            break
    # Check byline elements
    if not author:
        for cls in ['author', 'byline', 'post-author', 'entry-author']:
            author_el = soup.find(class_=re.compile(cls, re.I))
            if author_el:
                author = author_el.get_text(strip=True)
                break

    # --- Content ---
    content_areas = []
    article = soup.find('article')
    if article:
        content_areas.append(article)
    else:
        for cls in ['entry-content', 'post-content', 'article-content', 'blog-content']:
            div = soup.find('div', class_=re.compile(cls, re.I))
            if div:
                content_areas.append(div)
                break
    if not content_areas:
        main = soup.find('main')
        if main:
            content_areas.append(main)

    full_text = ""
    for area in content_areas:
        paragraphs = area.find_all(['p', 'h2', 'h3', 'h4', 'li', 'blockquote'])
        texts = []
        for p in paragraphs:
            text = p.get_text(strip=True)
            if text and len(text) > 10:
                if p.name in ['h2', 'h3', 'h4']:
                    texts.append(f"\n## {text}\n")
                elif p.name == 'blockquote':
                    texts.append(f"> {text}")
                else:
                    texts.append(text)
        full_text = "\n\n".join(texts)

    if not full_text.strip():
        return None

    # --- Determine if likely Andrew Ng authored ---
    is_ng_authored = False
    author_lower = author.lower()
    text_lower = full_text[:500].lower()

    for pattern in NG_AUTHOR_PATTERNS:
        if pattern in author_lower or pattern in text_lower:
            is_ng_authored = True
            break

    # If author is empty but content has Ng's voice markers, still include
    if not author and any(marker in text_lower for marker in ["i think", "i find", "dear friends"]):
        is_ng_authored = True

    return {
        "url": url,
        "slug": slug,
        "title": title,
        "date": date_str,
        "author": author,
        "is_ng_authored": is_ng_authored,
        "full_text": full_text,
        "word_count": len(full_text.split())
    }


def determine_domain_tag(title: str, text: str) -> str:
    """Simple domain classification for blog posts based on keywords."""
    combined = (title + " " + text[:500]).lower()

    if any(w in combined for w in ["agent", "agentic", "workflow", "multi-agent"]):
        return "agentic_ai"
    elif any(w in combined for w in ["career", "job", "hire", "resume", "learning path"]):
        return "career_advice"
    elif any(w in combined for w in ["deep learning", "neural network", "cnn", "rnn", "transformer"]):
        return "deep_learning"
    elif any(w in combined for w in ["strategy", "business", "industry", "company", "startup", "electricity"]):
        return "ai_strategy"
    else:
        return "ai_strategy"  # Default for blog opinion pieces


def save_blog_post(output_dir: Path, post_data: dict) -> str:
    """Save a blog post to a text file."""
    slug = post_data["slug"]
    date_prefix = ""
    if post_data["date"]:
        date_match = re.search(r'(\d{4}[-/]\d{2}[-/]\d{2})', post_data["date"])
        if date_match:
            date_prefix = date_match.group(1).replace('/', '-') + "_"

    domain_tag = determine_domain_tag(post_data["title"], post_data["full_text"])

    filename = f"blog_{date_prefix}{slug}.txt"
    output_path = output_dir / filename

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# Title: {post_data['title']}\n")
        f.write(f"# URL: {post_data['url']}\n")
        f.write(f"# Date: {post_data['date']}\n")
        f.write(f"# Author: {post_data['author']}\n")
        f.write(f"# Is Ng Authored: {post_data['is_ng_authored']}\n")
        f.write(f"# Domain: {domain_tag}\n")
        f.write(f"# Extracted: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"{'='*80}\n\n")
        f.write(post_data["full_text"])
        f.write("\n")

    return filename


def main():
    print("=" * 60)
    print("PHASE 1 - SCRIPT 4: BLOG POST SCRAPER")
    print("=" * 60)
    print()

    RAW_BLOG_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "script": "collect_blog_posts.py",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "base_url": BLOG_URL,
        "posts": [],
        "summary": {}
    }

    # --- Step 1: Get all post URLs ---
    print("[1/2] Crawling blog archive...")
    posts = get_all_blog_post_urls()

    if not posts:
        print("  [ERROR] No blog post URLs found.")
        manifest["summary"] = {"status": "failed", "error": "No post URLs found"}
        manifest_path = METADATA_DIR / "blog_manifest.json"
        with open(manifest_path, 'w', encoding='utf-8') as f:
            json.dump(manifest, f, indent=2, ensure_ascii=False)
        return

    # --- Step 2: Extract content ---
    print()
    print(f"[2/2] Extracting content from {len(posts)} posts...")

    success_count = 0
    fail_count = 0
    ng_authored_count = 0
    total_words = 0

    for i, post in enumerate(posts):
        url = post["url"]
        slug = post["slug"]

        print(f"  [{i+1}/{len(posts)}] {slug[:50]}...", end=" ")

        content = extract_blog_post(url, slug)

        if content:
            filename = save_blog_post(RAW_BLOG_DIR, content)

            meta_entry = {k: v for k, v in content.items() if k != "full_text"}
            meta_entry["output_file"] = filename
            meta_entry["status"] = "success"
            manifest["posts"].append(meta_entry)

            success_count += 1
            total_words += content["word_count"]
            if content["is_ng_authored"]:
                ng_authored_count += 1
            print(f"[OK] ({content['word_count']} words"
                  f"{', Ng authored' if content['is_ng_authored'] else ''})")
        else:
            manifest["posts"].append({
                "url": url,
                "slug": slug,
                "status": "failed"
            })
            fail_count += 1
            print("[FAIL]")

        time.sleep(REQUEST_DELAY)

    # --- Summary ---
    manifest["summary"] = {
        "total_attempted": len(posts),
        "total_success": success_count,
        "total_failed": fail_count,
        "ng_authored_count": ng_authored_count,
        "total_words": total_words,
        "estimated_pages": total_words // 300
    }

    manifest_path = METADATA_DIR / "blog_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print(f"DONE - {success_count} posts collected ({fail_count} failed)")
    print(f"  Ng-authored: {ng_authored_count}")
    print(f"  Total words: {total_words:,}")
    print(f"  Manifest: {manifest_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
