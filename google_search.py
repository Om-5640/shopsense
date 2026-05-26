"""
Serper.dev search client.

Replaces Google Custom Search JSON API (which is closed to new customers).

Setup (free, 2500 searches on signup):
1. Go to https://serper.dev
2. Sign up → copy your API key from the dashboard
3. Add to .env:
   SERPER_API_KEY=your_key

If key is missing, all functions return empty lists gracefully.
Agent falls back to Gemini grounding only.
"""

import os
import requests
import cache
from dotenv import load_dotenv

load_dotenv()

SERPER_KEY = os.environ.get("SERPER_API_KEY")
SERPER_URL = "https://google.serper.dev/search"


def is_configured() -> bool:
    return bool(SERPER_KEY)


def search(query: str, num: int = 10) -> list[dict]:
    """
    Search Google via Serper. Returns list of {title, link, snippet}.
    Returns [] on any failure. Cached 7 days.
    """
    if not is_configured():
        print("[serper] not configured, skipping")
        return []

    cache_key = f"{query}|{num}"
    cached = cache.get("serper", cache_key)
    if cached is not None:
        print(f"[serper] cache hit: {query}")
        return cached

    print(f"[serper] searching: {query}")
    try:
        resp = requests.post(
            SERPER_URL,
            headers={
                "X-API-KEY": SERPER_KEY,
                "Content-Type": "application/json",
            },
            json={"q": query, "num": min(num, 10)},
            timeout=30,
        )
        if resp.status_code == 429:
            print("[serper] quota exceeded, skipping")
            return []
        resp.raise_for_status()
        data = resp.json()
        results = [
            {
                "title": item.get("title", ""),
                "link": item.get("link", ""),
                "snippet": item.get("snippet", ""),
            }
            for item in data.get("organic", [])
        ]
        cache.set("serper", cache_key, results)
        return results
    except Exception as e:
        print(f"[serper] error (non-fatal): {e}")
        return []


def search_reddit(query: str, num: int = 10) -> list[str]:
    """Search Reddit threads via Serper. Returns list of URLs."""
    results = search(f"site:reddit.com {query}", num=num)
    return [
        r["link"] for r in results
        if "reddit.com" in r.get("link", "")
        and "/comments/" in r.get("link", "")
    ]


def search_reviews(query: str, num: int = 10) -> list[str]:
    """Search review sites via Serper. Returns list of URLs."""
    results = search(f"{query} best review", num=num)
    return [
        r["link"] for r in results
        if r.get("link")
        and "reddit.com" not in r["link"]
    ]