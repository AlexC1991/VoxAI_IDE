"""
Vox IronGate — Secure Web Client
Provides web_search and fetch_url for the VoxAI agent toolchain.

All requests go through rate limiting and URL safety checks.
No data is sent externally beyond the search query / target URL.
"""

import random
import re
import logging
from html import unescape
from urllib.parse import quote_plus, urlparse, urljoin

import requests

from .lib.config import (
    REQUEST_TIMEOUT, MAX_CONTENT_LENGTH, MAX_RESULTS, USER_AGENTS, log
)
from .lib.security import RateLimiter, is_safe_url

_limiter = RateLimiter(max_requests=15, window_seconds=60)


def _get_headers() -> dict:
    return {
        "User-Agent": random.choice(USER_AGENTS),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.9",
        "DNT": "1",
    }


def _strip_tags(html: str) -> str:
    """Remove HTML tags and collapse whitespace."""
    text = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<style[^>]*>.*?</style>', '', text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = unescape(text)
    text = re.sub(r'[ \t]+', ' ', text)
    text = re.sub(r'\n\s*\n', '\n\n', text)
    return text.strip()


class IronGateClient:
    """Singleton-style web client used by the AI tool layer."""

    @staticmethod
    def web_search(query: str, max_results: int = MAX_RESULTS) -> str:
        """Search the web via DuckDuckGo HTML and return formatted results.

        Returns a plain-text summary suitable for LLM consumption.
        """
        if not query or not query.strip():
            return "[Error: Empty search query]"

        if not _limiter.wait(timeout=10):
            return "[Error: Rate limit exceeded. Try again in a moment.]"

        url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"
        log.info("web_search: query=%r url=%s", query, url)

        try:
            resp = requests.get(url, headers=_get_headers(), timeout=REQUEST_TIMEOUT)
            resp.raise_for_status()
        except requests.Timeout:
            log.error("web_search timed out for query=%r", query)
            return "[Error: Search request timed out]"
        except requests.RequestException as e:
            log.error("web_search request failed: %s", e)
            return f"[Error: Search failed — {e}]"

        results = _parse_ddg_results(resp.text, max_results)
        if not results:
            return f"No results found for '{query}'."

        lines = [f"Web Search Results for: {query}\n"]
        for i, r in enumerate(results, 1):
            lines.append(f"{i}. {r['title']}")
            lines.append(f"   URL: {r['url']}")
            if r['snippet']:
                lines.append(f"   {r['snippet']}")
            lines.append("")

        log.info("web_search: %d results returned", len(results))
        return "\n".join(lines)

    @staticmethod
    def fetch_url(url: str) -> str:
        """Fetch a URL and return its text content, stripped of HTML.

        Returns plain text suitable for LLM consumption.
        """
        if not url or not url.strip():
            return "[Error: Empty URL]"

        if not is_safe_url(url):
            return "[Error: URL blocked by security policy (private/local addresses not allowed)]"

        if not _limiter.wait(timeout=10):
            return "[Error: Rate limit exceeded. Try again in a moment.]"

        log.info("fetch_url: %s", url)
        content_type = ""

        try:
            resp = requests.get(
                url,
                headers=_get_headers(),
                timeout=REQUEST_TIMEOUT,
                stream=True,
                allow_redirects=False,
            )

            # Follow redirects manually so each hop is safety-checked
            redirect_limit = 5
            while resp.is_redirect and redirect_limit > 0:
                redirect_limit -= 1
                next_url = resp.headers.get("Location", "")
                if not next_url:
                    break
                next_url = urljoin(url, next_url)
                if not is_safe_url(next_url):
                    return "[Error: Redirect target blocked by security policy]"
                resp.close()
                resp = requests.get(
                    next_url,
                    headers=_get_headers(),
                    timeout=REQUEST_TIMEOUT,
                    stream=True,
                    allow_redirects=False,
                )
                url = next_url

            resp.raise_for_status()

            content_type = resp.headers.get("Content-Type", "")
            if "text" not in content_type and "html" not in content_type and "json" not in content_type:
                resp.close()
                return f"[Error: Non-text content type ({content_type}). Cannot extract text from binary content.]"

            # Stream only up to MAX_CONTENT_LENGTH bytes to avoid OOM
            chunks = []
            downloaded = 0
            for chunk in resp.iter_content(chunk_size=8192, decode_unicode=True):
                if chunk:
                    chunks.append(chunk)
                    downloaded += len(chunk)
                    if downloaded >= MAX_CONTENT_LENGTH:
                        break
            resp.close()
            raw = "".join(chunks)[:MAX_CONTENT_LENGTH]

        except requests.Timeout:
            log.error("fetch_url timed out: %s", url)
            return "[Error: Request timed out]"
        except requests.RequestException as e:
            log.error("fetch_url failed: %s", e)
            return f"[Error: Fetch failed — {e}]"

        if "html" in content_type.lower():
            text = _strip_tags(raw)
        else:
            text = raw

        if len(text) > MAX_CONTENT_LENGTH:
            text = text[:MAX_CONTENT_LENGTH] + "\n...[truncated]"

        if not text.strip():
            return "[Warning: Page returned no extractable text content]"

        log.info("fetch_url: extracted %d chars from %s", len(text), url)
        return f"Content from {url}:\n\n{text}"


def _parse_ddg_results(html: str, max_results: int) -> list[dict]:
    """Parse DuckDuckGo HTML search results page."""
    results = []

    # DuckDuckGo wraps each result in <div class="result ...">
    result_blocks = re.findall(
        r'<div[^>]*class="[^"]*result[^"]*"[^>]*>(.*?)</div>\s*(?=<div[^>]*class="[^"]*result|$)',
        html, re.DOTALL
    )

    if not result_blocks:
        # Fallback: extract links with snippets from the whole page
        result_blocks = re.findall(
            r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>.*?'
            r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )
        for href, title_html, snippet_html in result_blocks[:max_results]:
            title = _strip_tags(title_html).strip()
            snippet = _strip_tags(snippet_html).strip()
            url = _extract_ddg_url(href)
            if title and url:
                results.append({"title": title, "url": url, "snippet": snippet})
        return results

    for block in result_blocks[:max_results * 2]:
        title_match = re.search(r'<a[^>]*class="[^"]*result__a[^"]*"[^>]*href="([^"]*)"[^>]*>(.*?)</a>', block, re.DOTALL)
        snippet_match = re.search(r'<a[^>]*class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</a>', block, re.DOTALL)

        if not title_match:
            continue

        href = title_match.group(1)
        title = _strip_tags(title_match.group(2)).strip()
        snippet = _strip_tags(snippet_match.group(1)).strip() if snippet_match else ""
        url = _extract_ddg_url(href)

        if title and url and url.startswith("http"):
            results.append({"title": title, "url": url, "snippet": snippet})
            if len(results) >= max_results:
                break

    return results


def _extract_ddg_url(href: str) -> str:
    """DuckDuckGo wraps URLs in a redirect; extract the actual target."""
    from urllib.parse import unquote, parse_qs, urlparse
    if "duckduckgo.com" in href and "uddg=" in href:
        parsed = urlparse(href)
        qs = parse_qs(parsed.query)
        targets = qs.get("uddg", [])
        if targets:
            return unquote(targets[0])
    if href.startswith("//"):
        return "https:" + href
    return href
