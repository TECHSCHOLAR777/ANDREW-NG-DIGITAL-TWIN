"""
Script 2: YouTube Transcript Extraction
=========================================
Pulls transcripts from all Andrew Ng lecture playlists and individual talks.
Uses youtube-transcript-api for transcripts and yt-dlp for video metadata.

Sources:
  - CS229 2018 Lectures (Stanford playlist)
  - CS230 Deep Learning (Stanford playlist)
  - deeplearning.ai ML Specialization playlist
  - deeplearning.ai Deep Learning Specialization playlist
  - Individual talks: Lex Fridman #73, Sequoia Agentic AI, BUILD 2024,
    Stanford GSB, NIPS 2016 "Nuts and Bolts"
"""

import os
import sys
import json
import time
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path

try:
    from youtube_transcript_api import YouTubeTranscriptApi
except ImportError:
    print("ERROR: youtube-transcript-api not installed. Run: pip install youtube-transcript-api")
    sys.exit(1)


# --- Configuration ---
PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAW_TRANSCRIPTS_DIR = PROJECT_ROOT / "data" / "raw" / "transcripts"
METADATA_DIR = PROJECT_ROOT / "data" / "metadata"

# Delay between requests to avoid rate limiting (seconds)
REQUEST_DELAY = 1.5

# --- Source Definitions ---

# Playlists to pull all videos from
PLAYLISTS = {
    "cs229_2018": {
        "playlist_id": "PLoROMvodv4rMiGQp3WXShtMGgzqpfVfbU",
        "domain_tag": "ml_theory",
        "description": "Stanford CS229 Machine Learning (Autumn 2018) - Andrew Ng"
    },
    "cs230_deep_learning": {
        "playlist_id": "PLoROMvodv4rOABXSygHTsbvUz4G_YQhOb",
        "domain_tag": "deep_learning",
        "description": "Stanford CS230 Deep Learning (Autumn 2018)"
    },
    "dlai_ml_specialization": {
        "playlist_id": "PLkDaE6sCZn6Ec-XTbcX1uRg2_u4xOEky0",
        "domain_tag": "ml_theory",
        "description": "deeplearning.ai Machine Learning Specialization - Andrew Ng"
    },
}

# Individual videos (not part of playlists, or specific high-value talks)
INDIVIDUAL_VIDEOS = {
    "lex_fridman_73": {
        "video_id": "0jspaMLxBig",
        "domain_tag": "career_advice",
        "description": "Lex Fridman Podcast #73 - Andrew Ng: Deep Learning, Education, and Real-World AI"
    },
    "agentic_ai_sequoia_2024": {
        "video_id": "sal78ACtGTc",
        "domain_tag": "agentic_ai",
        "description": "Andrew Ng - What's Next for AI Agentic Workflows (Sequoia AI Ascent 2024)"
    },
    "agentic_ai_build_2024": {
        "video_id": "KrRD7r7y7NY",
        "domain_tag": "agentic_ai",
        "description": "Andrew Ng - The Rise of AI Agents and Agentic Reasoning (BUILD 2024)"
    },
    "stanford_gsb_ai_electricity": {
        "video_id": "21EiKfQYZXc",
        "domain_tag": "ai_strategy",
        "description": "Andrew Ng - AI is the New Electricity (Stanford GSB 2017)"
    },
    "nips_2016_nuts_bolts": {
        "video_id": "F1ka6a13S9I",
        "domain_tag": "ai_strategy",
        "description": "Andrew Ng - Nuts and Bolts of Applying Deep Learning (2016)"
    },
}


def get_playlist_video_ids(playlist_id: str) -> list[dict]:
    """
    Use yt-dlp to get all video IDs and titles from a YouTube playlist.
    Returns list of {video_id, title, index} dicts.
    """
    print(f"    Fetching playlist metadata via yt-dlp...")

    try:
        result = subprocess.run(
            [
                sys.executable, "-m", "yt_dlp",
                "--flat-playlist",
                "--print", "%(id)s|||%(title)s|||%(playlist_index)s",
                "--no-warnings",
                f"https://www.youtube.com/playlist?list={playlist_id}"
            ],
            capture_output=True, text=True, timeout=120
        )

        if result.returncode != 0:
            print(f"    yt-dlp error: {result.stderr[:200]}")
            return []

        videos = []
        for line in result.stdout.strip().split('\n'):
            if not line.strip():
                continue
            parts = line.split('|||')
            if len(parts) >= 2:
                videos.append({
                    "video_id": parts[0].strip(),
                    "title": parts[1].strip(),
                    "index": parts[2].strip() if len(parts) > 2 else str(len(videos) + 1)
                })

        print(f"    Found {len(videos)} videos in playlist")
        return videos

    except FileNotFoundError:
        print("    ERROR: yt-dlp not found. Run: pip install yt-dlp")
        return []
    except subprocess.TimeoutExpired:
        print("    ERROR: yt-dlp timed out fetching playlist")
        return []


def get_transcript(video_id: str) -> tuple[str | None, str]:
    """
    Fetch transcript for a YouTube video.
    Tries manual transcripts first, falls back to auto-generated.
    Returns (transcript_text, transcript_type).
    """
    try:
        # Try to get manually created transcript first
        api = YouTubeTranscriptApi()
        transcript_list = api.list(video_id)

        # Prefer manually created English transcript
        transcript = None
        transcript_type = "unknown"

        try:
            transcript = transcript_list.find_manually_created_transcript(['en'])
            transcript_type = "manual"
        except Exception:
            try:
                transcript = transcript_list.find_generated_transcript(['en'])
                transcript_type = "auto-generated"
            except Exception:
                pass

        if transcript is None:
            return None, "unavailable"

        # Fetch the actual transcript data
        entries = transcript.fetch()

        # Combine all text entries
        full_text = " ".join(entry.text for entry in entries)

        # Clean up the text (basic)
        full_text = full_text.replace('\n', ' ')
        full_text = re.sub(r'\s+', ' ', full_text).strip()

        return full_text, transcript_type

    except Exception as e:
        return None, f"error: {str(e)[:100]}"


def sanitize_filename(title: str) -> str:
    """Convert a video title to a safe filename."""
    # Remove or replace unsafe characters
    safe = re.sub(r'[<>:"/\\|?*]', '', title)
    safe = re.sub(r'\s+', '_', safe)
    safe = safe.strip('_')
    # Truncate to reasonable length
    if len(safe) > 80:
        safe = safe[:80]
    return safe


def save_transcript(
    output_dir: Path,
    key: str,
    video_id: str,
    title: str,
    domain_tag: str,
    description: str,
    transcript_text: str,
    transcript_type: str,
    index: str = ""
) -> dict:
    """Save a transcript to a text file and return metadata."""
    safe_title = sanitize_filename(title)

    if index:
        filename = f"{key}_{index.zfill(2)}_{safe_title}.txt"
    else:
        filename = f"{key}_{safe_title}.txt"

    output_path = output_dir / filename

    with open(output_path, 'w', encoding='utf-8') as f:
        f.write(f"# Title: {title}\n")
        f.write(f"# Video ID: {video_id}\n")
        f.write(f"# URL: https://www.youtube.com/watch?v={video_id}\n")
        f.write(f"# Domain: {domain_tag}\n")
        f.write(f"# Description: {description}\n")
        f.write(f"# Transcript Type: {transcript_type}\n")
        f.write(f"# Extracted: {datetime.now(timezone.utc).isoformat()}\n")
        f.write(f"{'='*80}\n\n")
        f.write(transcript_text)
        f.write("\n")

    word_count = len(transcript_text.split())

    return {
        "video_id": video_id,
        "title": title,
        "domain_tag": domain_tag,
        "transcript_type": transcript_type,
        "word_count": word_count,
        "character_count": len(transcript_text),
        "output_file": filename,
        "status": "success"
    }


def process_playlist(
    playlist_key: str,
    playlist_config: dict,
    output_dir: Path
) -> list[dict]:
    """Process all videos in a playlist."""
    playlist_id = playlist_config["playlist_id"]
    domain_tag = playlist_config["domain_tag"]
    description = playlist_config["description"]

    print(f"\n  [PLAYLIST] {description}")
    print(f"    Playlist ID: {playlist_id}")

    # Get video list
    videos = get_playlist_video_ids(playlist_id)
    if not videos:
        print("    [SKIP] No videos found or yt-dlp failed")
        return [{
            "playlist_key": playlist_key,
            "status": "failed",
            "error": "Could not fetch playlist videos"
        }]

    results = []
    success_count = 0
    fail_count = 0

    for i, video in enumerate(videos):
        video_id = video["video_id"]
        title = video["title"]
        index = video.get("index", str(i + 1))

        print(f"    [{i+1}/{len(videos)}] {title[:60]}...", end=" ")

        # Fetch transcript
        transcript_text, transcript_type = get_transcript(video_id)

        if transcript_text:
            meta = save_transcript(
                output_dir, playlist_key, video_id, title,
                domain_tag, description, transcript_text, transcript_type, index
            )
            meta["playlist_key"] = playlist_key
            results.append(meta)
            success_count += 1
            print(f"[OK] ({transcript_type}, {meta['word_count']} words)")
        else:
            results.append({
                "video_id": video_id,
                "title": title,
                "playlist_key": playlist_key,
                "status": "failed",
                "error": transcript_type
            })
            fail_count += 1
            print(f"[FAIL] ({transcript_type})")

        # Rate limiting
        time.sleep(REQUEST_DELAY)

    print(f"    Summary: {success_count} success, {fail_count} failed out of {len(videos)}")
    return results


def process_individual_videos(
    videos_config: dict,
    output_dir: Path
) -> list[dict]:
    """Process individual (non-playlist) videos."""
    results = []

    for key, config in videos_config.items():
        video_id = config["video_id"]
        domain_tag = config["domain_tag"]
        description = config["description"]

        print(f"  [{key}] {description[:70]}...", end=" ")

        transcript_text, transcript_type = get_transcript(video_id)

        if transcript_text:
            meta = save_transcript(
                output_dir, key, video_id, description,
                domain_tag, description, transcript_text, transcript_type
            )
            results.append(meta)
            print(f"[OK] ({transcript_type}, {meta['word_count']} words)")
        else:
            results.append({
                "source_key": key,
                "video_id": video_id,
                "description": description,
                "status": "failed",
                "error": transcript_type
            })
            print(f"[FAIL] ({transcript_type})")

        time.sleep(REQUEST_DELAY)

    return results


def main():
    print("=" * 60)
    print("PHASE 1 - SCRIPT 2: YOUTUBE TRANSCRIPT COLLECTION")
    print("=" * 60)
    print()

    # Ensure directories exist
    RAW_TRANSCRIPTS_DIR.mkdir(parents=True, exist_ok=True)
    METADATA_DIR.mkdir(parents=True, exist_ok=True)

    manifest = {
        "script": "collect_transcripts.py",
        "run_at": datetime.now(timezone.utc).isoformat(),
        "playlists": {},
        "individual_videos": [],
        "summary": {}
    }

    total_success = 0
    total_failed = 0
    total_words = 0

    # --- Step 1: Process Playlists ---
    print("[1/2] Processing Playlists...")
    for key, config in PLAYLISTS.items():
        results = process_playlist(key, config, RAW_TRANSCRIPTS_DIR)
        manifest["playlists"][key] = {
            "description": config["description"],
            "playlist_id": config["playlist_id"],
            "domain_tag": config["domain_tag"],
            "videos": results
        }
        for r in results:
            if r.get("status") == "success":
                total_success += 1
                total_words += r.get("word_count", 0)
            else:
                total_failed += 1

    # --- Step 2: Process Individual Videos ---
    print()
    print("[2/2] Processing Individual Videos...")
    individual_results = process_individual_videos(INDIVIDUAL_VIDEOS, RAW_TRANSCRIPTS_DIR)
    manifest["individual_videos"] = individual_results
    for r in individual_results:
        if r.get("status") == "success":
            total_success += 1
            total_words += r.get("word_count", 0)
        else:
            total_failed += 1

    # --- Summary ---
    manifest["summary"] = {
        "total_videos_attempted": total_success + total_failed,
        "total_success": total_success,
        "total_failed": total_failed,
        "total_words": total_words,
        "estimated_pages": total_words // 300  # rough estimate
    }

    # Save manifest
    manifest_path = METADATA_DIR / "transcripts_manifest.json"
    with open(manifest_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, indent=2, ensure_ascii=False)

    print()
    print("=" * 60)
    print(f"DONE - {total_success} transcripts collected ({total_failed} failed)")
    print(f"  Total words: {total_words:,}")
    print(f"  Estimated pages: ~{total_words // 300}")
    print(f"  Manifest: {manifest_path}")
    print("=" * 60)


if __name__ == "__main__":
    main()
