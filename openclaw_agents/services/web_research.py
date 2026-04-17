"""Web research helpers for executive runtime agents."""

from __future__ import annotations

import html
import re
import time
from typing import Any
from urllib import error, parse, request


_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_TITLE_RE = re.compile(r"<title[^>]*>(?P<title>.*?)</title>", re.IGNORECASE | re.DOTALL)
_SEARCH_RESULT_RE = re.compile(
    r'<a[^>]+class="result__a"[^>]+href="(?P<href>[^"]+)"[^>]*>(?P<title>.*?)</a>',
    re.IGNORECASE | re.DOTALL,
)
_SEARCH_SNIPPET_RE = re.compile(
    r'<a[^>]+class="result__snippet"[^>]*>(?P<snippet>.*?)</a>|<div[^>]+class="result__snippet"[^>]*>(?P<div_snippet>.*?)</div>',
    re.IGNORECASE | re.DOTALL,
)


def _clean_html(text: str) -> str:
    without_scripts = _SCRIPT_STYLE_RE.sub(" ", text)
    cleaned = _TAG_RE.sub(" ", without_scripts)
    cleaned = html.unescape(cleaned).replace("\xa0", " ")
    return re.sub(r"\s+", " ", cleaned).strip()


def _extract_title(text: str) -> str:
    match = _TITLE_RE.search(text)
    if not match:
        return ""
    return _clean_html(match.group("title"))


def _normalize_result_url(url: str) -> str:
    cleaned = html.unescape(url).strip()
    if cleaned.startswith("//"):
        cleaned = "https:" + cleaned
    parsed = parse.urlparse(cleaned)
    if "duckduckgo.com" in parsed.netloc and parsed.path == "/l/":
        query = parse.parse_qs(parsed.query)
        redirect = query.get("uddg")
        if redirect:
            return parse.unquote(redirect[0])
    return cleaned


def _domain_for(url: str) -> str:
    netloc = parse.urlparse(url).netloc.lower()
    return netloc[4:] if netloc.startswith("www.") else netloc


class WebResearchService:
    def __init__(
        self,
        user_agent: str = "OpenClawAgents/1.0",
        *,
        max_retries: int = 2,
        retry_backoff_seconds: float = 0.5,
    ) -> None:
        self.user_agent = user_agent
        self.max_retries = max(0, int(max_retries))
        self.retry_backoff_seconds = max(0.0, float(retry_backoff_seconds))

    def _get(self, url: str, *, timeout_seconds: int = 20) -> tuple[str, str, str]:
        req = request.Request(url, headers={"User-Agent": self.user_agent})
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            try:
                with request.urlopen(req, timeout=timeout_seconds) as response:
                    body = response.read().decode("utf-8", errors="replace")
                    final_url = response.geturl()
                    content_type = response.headers.get("Content-Type", "")
                return body, final_url, content_type
            except (error.URLError, TimeoutError, OSError) as exc:
                last_error = exc
                if attempt >= self.max_retries:
                    break
                if self.retry_backoff_seconds > 0:
                    time.sleep(self.retry_backoff_seconds * (attempt + 1))
        assert last_error is not None
        raise last_error

    def search(self, query: str, *, limit: int = 5, timeout_seconds: int = 20) -> dict[str, Any]:
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("Search query is required.")
        url = "https://html.duckduckgo.com/html/?" + parse.urlencode({"q": cleaned})
        body, _, _ = self._get(url, timeout_seconds=timeout_seconds)
        snippets = [
            _clean_html(match.group("snippet") or match.group("div_snippet") or "")
            for match in _SEARCH_SNIPPET_RE.finditer(body)
        ]

        results: list[dict[str, Any]] = []
        for index, match in enumerate(_SEARCH_RESULT_RE.finditer(body), start=1):
            title = _clean_html(match.group("title"))
            raw_url = match.group("href")
            normalized_url = _normalize_result_url(raw_url)
            if not title or not normalized_url:
                continue
            results.append(
                {
                    "rank": len(results) + 1,
                    "title": title,
                    "url": normalized_url,
                    "domain": _domain_for(normalized_url),
                    "search_snippet": snippets[index - 1] if index - 1 < len(snippets) else "",
                    "source_engine": "duckduckgo_html",
                }
            )
            if len(results) >= max(1, min(limit, 10)):
                break
        return {"query": cleaned, "results": results}

    def fetch_url(self, url: str, *, timeout_seconds: int = 20, max_chars: int = 4000) -> dict[str, Any]:
        cleaned = _normalize_result_url(url)
        if not cleaned.startswith(("http://", "https://")):
            raise ValueError("Only http and https URLs are supported.")
        body, final_url, content_type = self._get(cleaned, timeout_seconds=timeout_seconds)
        text = _clean_html(body)
        title = _extract_title(body)
        excerpt = text[: max(200, min(max_chars, 12000))]
        return {
            "url": cleaned,
            "final_url": final_url,
            "domain": _domain_for(final_url or cleaned),
            "title": title,
            "content_type": content_type,
            "content": excerpt,
        }

    def research(
        self,
        query: str,
        *,
        search_limit: int = 5,
        fetch_limit: int = 3,
        max_chars: int = 1600,
        timeout_seconds: int = 20,
    ) -> dict[str, Any]:
        search_result = self.search(query, limit=search_limit, timeout_seconds=timeout_seconds)
        sources: list[dict[str, Any]] = []
        failures: list[dict[str, str]] = []
        for row in search_result["results"][: max(1, min(fetch_limit, search_limit, 5))]:
            citation_index = len(sources) + 1
            try:
                fetched = self.fetch_url(row["url"], timeout_seconds=timeout_seconds, max_chars=max_chars)
            except Exception as exc:
                failures.append({"url": row["url"], "error": str(exc)})
                snippet = row.get("search_snippet", "")
                if snippet:
                    sources.append(
                        {
                            "citation_index": citation_index,
                            "title": row.get("title") or row["url"],
                            "url": row["url"],
                            "domain": row.get("domain"),
                            "search_snippet": snippet,
                            "content_excerpt": snippet[: max(200, min(max_chars, 12000))],
                            "content_type": "search_result_snippet",
                            "fetch_error": str(exc),
                        }
                    )
                continue
            sources.append(
                {
                    "citation_index": citation_index,
                    "title": fetched.get("title") or row.get("title"),
                    "url": fetched.get("final_url") or row["url"],
                    "domain": fetched.get("domain") or row.get("domain"),
                    "search_snippet": row.get("search_snippet", ""),
                    "content_excerpt": fetched.get("content", ""),
                    "content_type": fetched.get("content_type", ""),
                }
            )

        if not sources:
            for row in search_result["results"][: max(1, min(fetch_limit, search_limit, 5))]:
                snippet = row.get("search_snippet", "")
                if not snippet:
                    continue
                sources.append(
                    {
                        "citation_index": len(sources) + 1,
                        "title": row.get("title") or row["url"],
                        "url": row["url"],
                        "domain": row.get("domain"),
                        "search_snippet": snippet,
                        "content_excerpt": snippet[: max(200, min(max_chars, 12000))],
                        "content_type": "search_result_snippet",
                    }
                )
        citations = [
            f"[{source['citation_index']}] {source['title']} ({source['domain']}) - {source['url']}"
            for source in sources
        ]
        return {
            "query": search_result["query"],
            "results": search_result["results"],
            "sources": sources,
            "citations": citations,
            "failures": failures,
        }
