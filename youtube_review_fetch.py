"""
Phase 4: YouTube review intelligence.

Finds expert YouTube reviewer videos for a product query and extracts
transcript summaries as supplementary review evidence.

Priority sources:
  1. YouTube Data API v3 (requires YOUTUBE_API_KEY env var)
  2. Serper/Google search for YouTube URLs (no API key needed)

Transcript extraction via youtube-transcript-api (pip install youtube-transcript-api).
If the package is not installed or transcripts are unavailable, the video is skipped.

Only fetches from known review channels; treats YouTube as supplementary evidence,
not primary truth.  Falls back to [] on any failure.
"""

from __future__ import annotations

import os
import re
import time
from typing import Optional
from urllib.parse import urlparse, parse_qs


YOUTUBE_API_KEY = os.environ.get("YOUTUBE_API_KEY", "")

_MAX_VIDEOS = 5
_MAX_TRANSCRIPT_CHARS = 6_000
_MIN_TRANSCRIPT_CHARS = 200

# Known authoritative review channels (substring match against channel name, case-insensitive)
_TRUSTED_CHANNELS = {
    "mkbhd", "marques brownlee",
    "hardware unboxed",
    "monitors unboxed",
    "dave2d", "dave lee",
    "shortcircuit",
    "linus tech tips",
    "optimum tech",
    "rtings",
    "jarrod's tech",
    "jarrodstechlife",
    "notebookcheck",
    "digital trends",
    "techradar",
    "techgumbo",
    "the tech chap",
    "91mobiles",
    "smartprix",
    "geeky ranjit",
    "technical guruji",
    "beebom",
    "mr mobile",
    "ijtema",
}

_REVIEW_TITLE_KEYWORDS = {
    "review", "hands on", "hands-on", "tested", "test", "analysis",
    "vs ", " versus ", "unboxing", "benchmark", "buying guide",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def fetch_youtube_reviews(query: str) -> list[dict]:
    """
    Find and extract transcript summaries from YouTube review videos.

    Returns list of:
    {
        video_id, video_title, channel, channel_is_trusted,
        trust_score, transcript_snippet, url, source_type
    }

    Returns [] if YouTube is unconfigured, transcript API absent, or any failure.
    """
    try:
        return _fetch(query)
    except Exception as e:
        print(f"[youtube] non-fatal: {e}")
        return []


# ---------------------------------------------------------------------------
# Internal
# ---------------------------------------------------------------------------

def _fetch(query: str) -> list[dict]:
    import cache

    cache_key = f"youtube|{query}"
    cached = cache.get("youtube_reviews", cache_key)
    if cached is not None:
        print(f"[youtube] cache hit: {query}")
        return cached

    candidates = _find_candidates(query)
    if not candidates:
        return []

    results = []
    for vid_id, title, channel in candidates[:_MAX_VIDEOS]:
        snippet = _get_transcript_snippet(vid_id)
        if not snippet:
            continue
        is_trusted = _is_trusted(channel)
        results.append({
            "video_id": vid_id,
            "video_title": title,
            "channel": channel,
            "channel_is_trusted": is_trusted,
            "trust_score": 0.85 if is_trusted else 0.55,
            "transcript_snippet": snippet,
            "url": f"https://www.youtube.com/watch?v={vid_id}",
            "source_type": "youtube",
        })
        time.sleep(0.3)

    print(f"[youtube] {len(results)} videos with transcripts for: {query}")
    if results:
        cache.set("youtube_reviews", cache_key, results)
    return results


def _find_candidates(query: str) -> list[tuple[str, str, str]]:
    """Return (video_id, title, channel) tuples."""
    if YOUTUBE_API_KEY:
        hits = _search_api(query)
        if hits:
            return hits
    return _search_serper(query)


def _search_api(query: str) -> list[tuple[str, str, str]]:
    import requests
    try:
        resp = requests.get(
            "https://www.googleapis.com/youtube/v3/search",
            params={
                "key": YOUTUBE_API_KEY,
                "q": f"{query} review",
                "type": "video",
                "part": "snippet",
                "maxResults": 15,
                "videoDuration": "medium",   # 4–20 min = typical review length
                "relevanceLanguage": "en",
                "safeSearch": "moderate",
            },
            timeout=15,
        )
        resp.raise_for_status()
        results = []
        for item in resp.json().get("items", []):
            vid_id = item["id"]["videoId"]
            title = item["snippet"]["title"]
            channel = item["snippet"]["channelTitle"]
            if _is_review_content(title, channel):
                results.append((vid_id, title, channel))
        return results
    except Exception as e:
        print(f"[youtube] API search failed: {e}")
        return []


def _search_serper(query: str) -> list[tuple[str, str, str]]:
    try:
        import google_search
        if not google_search.is_configured():
            return []
        results = google_search.search(f"{query} review site:youtube.com", num=15)
        hits = []
        seen: set[str] = set()
        for r in results:
            link = r.get("link", "")
            vid_id = _extract_video_id(link)
            if not vid_id or vid_id in seen:
                continue
            title = r.get("title", "")
            channel = r.get("displayLink", "")
            if _is_review_content(title, channel):
                seen.add(vid_id)
                hits.append((vid_id, title, channel))
        return hits
    except Exception:
        return []


def _extract_video_id(url: str) -> Optional[str]:
    try:
        parsed = urlparse(url)
        if "youtube.com" in parsed.netloc:
            ids = parse_qs(parsed.query).get("v", [])
            return ids[0] if ids else None
        if "youtu.be" in parsed.netloc:
            return parsed.path.lstrip("/").split("?")[0] or None
    except Exception:
        pass
    return None


def _is_review_content(title: str, channel: str) -> bool:
    if _is_trusted(channel):
        return True
    title_lower = title.lower()
    return any(kw in title_lower for kw in _REVIEW_TITLE_KEYWORDS)


def _is_trusted(channel: str) -> bool:
    ch = channel.lower()
    return any(name in ch for name in _TRUSTED_CHANNELS)


def _get_transcript_snippet(video_id: str) -> Optional[str]:
    try:
        from youtube_transcript_api import YouTubeTranscriptApi
        entries = YouTubeTranscriptApi.get_transcript(video_id, languages=["en", "en-US", "en-GB"])
        text = " ".join(e["text"] for e in entries)
        # Remove [Music], [Applause], noise
        text = re.sub(r"\[.*?\]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) < _MIN_TRANSCRIPT_CHARS:
            return None
        return text[:_MAX_TRANSCRIPT_CHARS]
    except Exception:
        return None
