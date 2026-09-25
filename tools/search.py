"""Web search via the Brave Search API."""

import requests

from config import config

SEARCH_URL = "https://api.search.brave.com/res/v1/web/search"


def search_web(query: str, count: int = 5) -> dict:
    if not config.BRAVE_API_KEY:
        return {
            "success": False,
            "error": "Search is not configured. Set BRAVE_API_KEY in .env to enable web search.",
        }

    count = max(1, min(count, 10))
    headers = {
        "Accept": "application/json",
        "Accept-Encoding": "gzip",
        "X-Subscription-Token": config.BRAVE_API_KEY,
    }
    params = {"q": query, "count": count, "text_decorations": False}

    try:
        resp = requests.get(SEARCH_URL, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        data = resp.json()
    except requests.RequestException as exc:
        return {"success": False, "error": str(exc)}

    results = []
    for item in data.get("web", {}).get("results", []):
        results.append(
            {
                "title": item.get("title", ""),
                "url": item.get("url", ""),
                "description": item.get("description", ""),
            }
        )

    return {"success": True, "query": query, "results": results, "count": len(results)}
