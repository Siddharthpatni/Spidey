"""Shared real web search — the common substrate under every research task.

One function, :func:`search`, aggregates free, key-less sources into a single
ranked result list:

  * DuckDuckGo (HTML endpoint) — general web results
  * arXiv                      — papers, with abstracts (great for eng/ML topics)
  * Wikipedia                  — an authoritative summary
  * Knowledge Nexus           — anything Spidey has already crawled/indexed

Every module that "researches" (the agent's web_search tool, the research
module's deep mode, Nexus seed-crawling, the IEEE paper's reference engine) calls
this, so improving retrieval here lifts the whole pipeline at once. No API keys,
fully replaceable — each source fails soft.
"""

from __future__ import annotations

import re
from html import unescape
from typing import Any, Dict, List
from urllib.parse import quote_plus, urlparse, parse_qs, unquote

UA = "Mozilla/5.0 (compatible; SpideyPlatform/1.0)"


def _ddg(query: str, limit: int) -> List[Dict[str, str]]:
    """DuckDuckGo's no-JS HTML endpoint — general web results, no key."""
    import requests
    out: List[Dict[str, str]] = []
    try:
        r = requests.post("https://html.duckduckgo.com/html/",
                          data={"q": query}, headers={"User-Agent": UA}, timeout=15)
        for m in re.finditer(r'(?s)<a[^>]+class="result__a"[^>]+href="([^"]+)".*?>(.*?)</a>',
                             r.text):
            href, title = m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()
            # DDG wraps targets in a redirect: /l/?uddg=<encoded>
            if "uddg=" in href:
                href = unquote(parse_qs(urlparse(href).query).get("uddg", [href])[0])
            if href.startswith("http"):
                out.append({"title": unescape(title)[:200], "url": href,
                            "snippet": "", "source": "web"})
            if len(out) >= limit:
                break
    except Exception:
        pass
    # snippets live in a sibling element — best-effort attach
    try:
        snips = re.findall(r'(?s)<a[^>]+class="result__snippet"[^>]*>(.*?)</a>', r.text)
        for i, s in enumerate(snips[:len(out)]):
            out[i]["snippet"] = unescape(re.sub(r"<[^>]+>", "", s)).strip()[:300]
    except Exception:
        pass
    return out


def _arxiv(query: str, limit: int) -> List[Dict[str, str]]:
    import requests
    out: List[Dict[str, str]] = []
    try:
        r = requests.get("http://export.arxiv.org/api/query",
                         params={"search_query": f"all:{query}", "max_results": limit,
                                 "sortBy": "relevance"}, timeout=15)
        for entry in re.findall(r"(?s)<entry>(.*?)</entry>", r.text):
            title = re.search(r"<title>(.*?)</title>", entry, re.S)
            summ = re.search(r"<summary>(.*?)</summary>", entry, re.S)
            url = re.search(r"<id>(.*?)</id>", entry)
            if title and url:
                out.append({"title": " ".join(title.group(1).split())[:200],
                            "url": url.group(1).strip(),
                            "snippet": (" ".join(summ.group(1).split())[:400]) if summ else "",
                            "source": "arxiv"})
    except Exception:
        pass
    return out


def _wikipedia(query: str) -> List[Dict[str, str]]:
    import requests
    try:
        r = requests.get("https://en.wikipedia.org/api/rest_v1/page/summary/"
                         + quote_plus(query.replace(" ", "_")), timeout=10,
                         headers={"User-Agent": UA})
        if r.ok and r.json().get("extract"):
            j = r.json()
            return [{"title": j.get("title", query),
                     "url": j.get("content_urls", {}).get("desktop", {}).get("page",
                            "https://en.wikipedia.org/wiki/" + quote_plus(query)),
                     "snippet": j["extract"][:400], "source": "wikipedia"}]
    except Exception:
        pass
    return []


def _nexus(query: str, limit: int) -> List[Dict[str, str]]:
    try:
        from ..modules.nexus import hybrid_search
        return [{"title": h["title"] or h["url"], "url": h["url"],
                 "snippet": h["snippet"], "source": "nexus"}
                for h in hybrid_search(query, k=limit)]
    except Exception:
        return []


def search(query: str, limit: int = 10, scholarly: bool = False) -> List[Dict[str, Any]]:
    """Aggregate + de-duplicate results across sources. ``scholarly`` weights
    arXiv/Wikipedia first (for papers); otherwise general web leads."""
    results: List[Dict[str, str]] = []
    results += _nexus(query, 3)  # what we already know ranks first
    if scholarly:
        results += _arxiv(query, 6) + _wikipedia(query) + _ddg(query, 6)
    else:
        results += _ddg(query, 8) + _wikipedia(query) + _arxiv(query, 3)
    seen, deduped = set(), []
    for r in results:
        key = r["url"].split("#")[0].rstrip("/")
        if key in seen or not r.get("url"):
            continue
        seen.add(key)
        deduped.append(r)
    return deduped[:limit]
