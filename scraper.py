"""
scraper.py
----------
Fetches image results straight from DuckDuckGo's internal `i.js` endpoint
(the same API the website uses) and follows `next` pagination page by page.

Why not the ddgs package? It caps out around a few hundred results.
Direct pagination keeps going until DuckDuckGo itself runs out of pages,
so 1000-5000 images per keyword are reachable.

Accuracy: light title filter here; real content filtering is CLIP's job
after download. `ddgs` remains as an automatic fallback if i.js is blocked.
"""

import logging
import re
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import requests

from config import ScraperConfig

logger = logging.getLogger(__name__)

REGION_CODES = {
    "United States": "us-en",
    "Pakistan": "pk-en",
    "India": "in-en",
    "United Kingdom": "uk-en",
    "Germany": "de-de",
    "Japan": "jp-jp",
}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"),
    "Accept": "application/json, text/javascript, */*; q=0.01",
    "Referer": "https://duckduckgo.com/",
}


@dataclass
class ImageResult:
    """A single scraped image candidate."""
    keyword: str
    page_url: str
    image_url: str


class GoogleImageScraper:
    """DuckDuckGo image scraper using the site's own i.js pagination API."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.last_block_reason: str | None = None
        self.session = requests.Session()
        self.session.headers.update(HEADERS)
        # Pehle download ho chuke URLs — repeat runs par duplicates skip.
        self.history_file = Path(getattr(config, "output_dir", ".")) / ".seen_urls.txt"
        self.seen_history: set[str] = set()
        if self.history_file.exists():
            self.seen_history = set(self.history_file.read_text().splitlines())

    def search(self, keyword: str) -> str:
        """Public web URL for this search on DuckDuckGo Images."""
        return f"https://duckduckgo.com/?q={urllib.parse.quote(keyword)}&iax=images&ia=images"

    # ------------------------------------------------------------------ #
    # i.js pagination
    # ------------------------------------------------------------------ #

    def _get_vqd(self, query: str) -> str | None:
        """DuckDuckGo requires a per-query `vqd` token from the HTML page."""
        try:
            resp = self.session.get(
                "https://duckduckgo.com/",
                params={"q": query, "iax": "images", "ia": "images"},
                timeout=10,
            )
            resp.raise_for_status()
            for pattern in (r'vqd="([^"]+)"', r"vqd=([\d-]+)", r"vqd='([^']+)'"):
                m = re.search(pattern, resp.text)
                if m:
                    return m.group(1)
        except requests.RequestException as exc:
            logger.warning("vqd fetch failed for %r: %s", query, exc)
        return None

    def _iter_pages(self, query: str, region: str):
        """Yields result lists page by page, following `next` until exhausted."""
        vqd = self._get_vqd(query)
        if not vqd:
            logger.warning("No vqd token for %r — skipping query.", query)
            return
        url = "https://duckduckgo.com/i.js"
        params = {
            "l": region or "us-en",
            "o": "json",
            "q": query,
            "vqd": vqd,
            "f": ",size:Large,,type:photo,,",
            "p": "1",
        }
        page_no = 0
        while True:
            try:
                resp = self.session.get(url, params=params, timeout=10)
                if resp.status_code == 403:
                    # token expired mid-pagination — refresh once
                    vqd = self._get_vqd(query)
                    if not vqd:
                        return
                    params["vqd"] = vqd
                    resp = self.session.get(url, params=params, timeout=10)
                resp.raise_for_status()
                data = resp.json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Page fetch failed for %r: %s", query, exc)
                return
            page_no += 1
            results = data.get("results") or []
            logger.info("Query %r page %d: %d results", query, page_no, len(results))
            if results:
                yield results
            nxt = data.get("next")
            if not nxt or not results:
                return  # all pages consumed
            # `next` is a relative URL like "i.js?q=...&s=100&..."
            url = "https://duckduckgo.com/" + nxt.lstrip("/")
            params = {"vqd": vqd}  # next already carries q/s/o/l
            time.sleep(0.15)  # be polite, avoid rate-limit blocks

    # ------------------------------------------------------------------ #
    # Public collection API (same signature app.py already uses)
    # ------------------------------------------------------------------ #

    def _query_variations(self, keyword: str) -> list[str]:
        kw = f'"{keyword}"'
        return [
            kw,
            f"{kw} photo",
            f"{kw} hd",
            keyword,
            f"{keyword} wallpaper",
            f"{keyword} photography",
        ]

    def _title_ok(self, title: str, keyword: str) -> bool:
        """Loose filter — CLIP does strict content checking after download."""
        title = title.lower()
        return any(w in title for w in keyword.lower().split())

    def collect_image_urls(
        self,
        keyword: str,
        target_count: int,
        region: str = "",
    ) -> list[ImageResult]:
        results: list[ImageResult] = []
        seen: set[str] = set()
        self.last_block_reason = None

        clean_keyword = keyword.strip()
        if not clean_keyword:
            return results

        # 1.3x buffer for CLIP filtering; downloader early-stops anyway.
        collect_target = max(int(target_count * 1.3), target_count + 20)

        # Region-first, global-fill: regional index is a small slice of the
        # global one, so take what the region has, then top up from Global
        # to still hit the full requested count.
        region_code = REGION_CODES.get(region)
        passes = [region_code, "us-en"] if region_code else ["us-en"]

        for pass_region in passes:
            if len(results) >= collect_target:
                break
            for query in self._query_variations(clean_keyword):
                if len(results) >= collect_target:
                    break
                for page in self._iter_pages(query, pass_region):
                    for item in page:
                        img_url = item.get("image")
                        if not img_url or img_url in seen or img_url in self.seen_history:
                            continue
                        # skip small/low-res images - user views these full screen
                        try:
                            if int(item.get("width") or 0) < 800 or int(item.get("height") or 0) < 600:
                                continue
                        except (TypeError, ValueError):
                            pass
                        seen.add(img_url)
                        results.append(ImageResult(
                            keyword=clean_keyword,
                            page_url=item.get("url") or self.search(clean_keyword),
                            image_url=img_url,
                        ))
                        if len(results) >= collect_target:
                            break
                    if len(results) >= collect_target:
                        break
            if region_code and pass_region == region_code and len(results) < collect_target:
                logger.info("Region %r gave %d/%d — filling the rest from Global.",
                            region, len(results), collect_target)

        # Fallback: i.js blocked entirely -> try the ddgs package once.
        if not results:
            results = self._ddgs_fallback(clean_keyword, collect_target)

        if not results and not self.last_block_reason:
            self.last_block_reason = "No results found on DuckDuckGo Images."
        elif results:
            logger.info("Collected %d unique image URLs for %r.", len(results), clean_keyword)
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "a") as f:
                for r in results:
                    f.write(r.image_url + "\n")

        return results

    def _ddgs_fallback(self, keyword: str, collect_target: int) -> list[ImageResult]:
        try:
            from ddgs import DDGS
        except ImportError:
            self.last_block_reason = "DuckDuckGo i.js blocked and ddgs not installed."
            return []
        out: list[ImageResult] = []
        try:
            with DDGS() as ddgs:
                for item in ddgs.images(keyword, safesearch="moderate", max_results=300):
                    img_url = item.get("image")
                    if not img_url or img_url in self.seen_history:
                        continue
                    out.append(ImageResult(
                        keyword=keyword,
                        page_url=item.get("url") or self.search(keyword),
                        image_url=img_url,
                    ))
                    if len(out) >= collect_target:
                        break
        except Exception as exc:
            self.last_block_reason = f"DuckDuckGo search error: {exc}"
        return out


# Compatibility layer — app.py imports this name.
OpenverseImageScraper = GoogleImageScraper
