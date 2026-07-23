"""
scraper.py — multi-source image URL collector.

Hard-target design:
  Source chain: DuckDuckGo i.js  ->  Bing Images  ->  Openverse API.
  When one source stops returning NEW unique URLs, the next takes over
  automatically. A per-run global `session_seen` set guarantees the
  downloader only ever receives fresh, unique URLs (across rounds too).
  Rate-limits (403/429) rotate the User-Agent instead of giving up.
  A query that returned nothing new is never retried in the same run.
"""

import logging
import re
import threading
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

import requests

from config import ScraperConfig

logger = logging.getLogger(__name__)

try:
    import playwright  # noqa: F401
    PLAYWRIGHT_OK = True
except ImportError:
    PLAYWRIGHT_OK = False

REGION_CODES = {
    "United States": "us-en", "Pakistan": "pk-en", "India": "in-en",
    "United Kingdom": "uk-en", "Germany": "de-de", "Japan": "jp-jp",
}

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:127.0) Gecko/20100101 Firefox/127.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

MIN_W, MIN_H = 800, 600  # skip low-res images when dimensions are known


@dataclass
class ImageResult:
    keyword: str
    page_url: str
    image_url: str
    provider: str = ""    # which source supplied this image


class GoogleImageScraper:
    """Collects image URLs from multiple providers until the target is met."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.last_block_reason: str | None = None
        self._ua_idx = 0
        self.session = requests.Session()
        self.session.headers.update(self._headers())
        # Without this cookie Google serves a consent page with no image data
        self.session.cookies.set("CONSENT", "YES+cb", domain=".google.com")
        self.session.cookies.set("SOCS", "CAESHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmVuIAEaBgiA_LyaBg", domain=".google.com")
        # Global uniqueness for THIS run (all rounds, all sources).
        self.session_seen: set[str] = set()
        # Queries that produced nothing new — never retried this run.
        self._dead_queries: set[tuple] = set()
        # URLs successfully downloaded in PREVIOUS runs.
        self.history_file = Path(getattr(config, "output_dir", ".")) / ".seen_urls.txt"
        self.seen_history: set[str] = set()
        if self.history_file.exists():
            self.seen_history = set(self.history_file.read_text(encoding="utf-8", errors="ignore").splitlines())

    # ------------------------------------------------------------- helpers
    def _headers(self):
        return {
            "User-Agent": USER_AGENTS[self._ua_idx % len(USER_AGENTS)],
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Referer": "https://duckduckgo.com/",
        }

    def _rotate_ua(self):
        """Rate-limited? Switch identity instead of giving up."""
        self._ua_idx += 1
        self.session.headers.update(self._headers())
        logger.info("Rotated User-Agent (#%d)", self._ua_idx)

    def _get(self, url, **kw):
        resp = self.session.get(url, timeout=10, **kw)
        if resp.status_code in (403, 429):
            self._rotate_ua()
            time.sleep(1.0)
            resp = self.session.get(url, timeout=10, **kw)
        resp.raise_for_status()
        return resp

    def search(self, keyword: str) -> str:
        return f"https://duckduckgo.com/?q={urllib.parse.quote(keyword)}&iax=images&ia=images"

    def _query_variations(self, keyword: str) -> list[str]:
        kw = f'"{keyword}"'
        return [kw, keyword, f"{keyword} hd"]  # was 6 variants — 3 cuts DDG time ~in half

    def _title_ok(self, title: str, keyword: str) -> bool:
        title = (title or "").lower()
        return any(w in title for w in keyword.lower().split())

    def _fresh(self, url: str) -> bool:
        return bool(url) and url not in self.session_seen and url not in self.seen_history

    # ------------------------------------------------- source 1: DuckDuckGo
    def _get_vqd(self, query):
        try:
            resp = self._get("https://duckduckgo.com/",
                             params={"q": query, "iax": "images", "ia": "images"})
            for p in (r'vqd="([^"]+)"', r"vqd=([\d-]+)", r"vqd='([^']+)'"):
                m = re.search(p, resp.text)
                if m:
                    return m.group(1)
        except requests.RequestException as exc:
            logger.warning("vqd fetch failed for %r: %s", query, exc)
        return None

    def _ddg_items(self, keyword, region_code):
        """Yields items from every page of every query variation."""
        for query in self._query_variations(keyword):
            qkey = ("ddg", query, region_code)
            if qkey in self._dead_queries:
                continue
            vqd = self._get_vqd(query)
            if not vqd:
                self._dead_queries.add(qkey)
                continue
            url = "https://duckduckgo.com/i.js"
            params = {"l": region_code, "o": "json", "q": query, "vqd": vqd,
                      "f": ",size:Large,,type:photo,,", "p": "1"}
            got_new = False
            while True:
                try:
                    data = self._get(url, params=params).json()
                except (requests.RequestException, ValueError) as exc:
                    logger.warning("DDG page failed (%r): %s", query, exc)
                    break
                results = data.get("results") or []
                for it in results:
                    w, h = int(it.get("width") or 0), int(it.get("height") or 0)
                    if w and h and (w < MIN_W or h < MIN_H):
                        continue
                    if not self._title_ok(it.get("title"), keyword):
                        continue
                    got_new = True
                    yield it.get("image"), it.get("url")
                nxt = data.get("next")
                if not nxt or not results:
                    break  # every page of this query consumed
                url = "https://duckduckgo.com/" + nxt.lstrip("/")
                params = {"vqd": vqd}
                time.sleep(0.15)
            if not got_new:
                self._dead_queries.add(qkey)

    # ---------------------------------------------- source 1: Google Images
    def _google_items(self, keyword, region_code):
        """Google Images. Fast path: HTML + regex (no browser startup cost).
        If the `playwright` package is installed it is used as a JS fallback."""
        for query in (f'"{keyword}"', f'"{keyword}" photo', keyword):
            qkey = ("google", query)
            if qkey in self._dead_queries:
                continue
            got_new = False
            for start in (0, 20, 40):  # ~3 result pages
                try:
                    resp = self._get(
                        "https://www.google.com/search",
                        params={"q": query, "tbm": "isch", "ijn": start // 20,
                                "start": start, "hl": "en"},
                    )
                except requests.RequestException as exc:
                    logger.warning("Google page failed (%r): %s", query, exc)
                    break
                # full-res URLs appear as ["https://...jpg",height,width]
                found = re.findall(
                    r'\["(https?://[^"]+?\.(?:jpe?g|png|webp))",(\d+),(\d+)\]',
                    resp.text)
                if not found:
                    break
                for u, h, w in found:
                    if int(w) < MIN_W or int(h) < MIN_H:
                        continue
                    got_new = True
                    # only unescape when Google actually escaped it -
                    # blind unicode_escape corrupts non-ASCII URLs
                    if "\\u" in u:
                        u = u.encode().decode("unicode_escape")
                    yield u, None
                time.sleep(0.15)
            if not got_new:
                self._dead_queries.add(qkey)

    # ---------------------------------------------- source 0: Google (Playwright)
    def _google_playwright_items(self, keyword, _region_code=None):
        """Google Images via headless Chromium. Real browser rendering finds
        far more full-res URLs than the HTML-regex fallback. Silently yields
        nothing (never raises) if playwright isn't installed/initialized,
        so collect_parallel's dedup/target logic is unaffected."""
        if not PLAYWRIGHT_OK:
            return
        qkey = ("google-pw", keyword)
        if qkey in self._dead_queries:
            return
        got_new = False
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as pw:
                browser = pw.chromium.launch(headless=True)
                page = browser.new_page(user_agent=USER_AGENTS[0])
                page.goto(
                    f"https://www.google.com/search?q={urllib.parse.quote(keyword)}&tbm=isch",
                    timeout=15000,
                )
                for _ in range(4):  # was 6 — trims ~0.7s browser time
                    page.mouse.wheel(0, 3000)
                    page.wait_for_timeout(350)
                html = page.content()
                browser.close()
            found = re.findall(
                r'\["(https?://[^"]+?\.(?:jpe?g|png|webp))",(\d+),(\d+)\]', html)
            for u, h, w in found:
                if int(w) < MIN_W or int(h) < MIN_H:
                    continue
                got_new = True
                if "\\u" in u:
                    u = u.encode().decode("unicode_escape")
                yield u, None
        except Exception as exc:
            logger.warning("Google-Playwright provider failed: %s", exc)
        if not got_new:
            self._dead_queries.add(qkey)

    # ---------------------------------------------- source 3: Yandex Images
    def _yandex_items(self, keyword, _region_code):
        qkey = ("yandex", keyword)
        if qkey in self._dead_queries:
            return
        got_new = False
        for page in range(0, 3):  # was 5 — 2 pages saved per keyword
            try:
                resp = self._get(
                    "https://yandex.com/images/search",
                    params={"text": keyword, "p": page},
                )
            except requests.RequestException as exc:
                logger.warning("Yandex page failed: %s", exc)
                break
            found = re.findall(r'"img_href":"(.*?)"', resp.text) or                     re.findall(r'img_url=(https?%3A[^&"]+)', resp.text)
            if not found:
                break
            for u in found:
                url = urllib.parse.unquote(u.replace("\\/", "/"))
                got_new = True
                yield url, None
            time.sleep(0.2)
        if not got_new:
            self._dead_queries.add(qkey)

    # ------------------------------------------------- source 2: Bing Images
    def _bing_items(self, keyword, region_code):
        """Bing async endpoint; paginates with `first` offset."""
        for query in (f'"{keyword}"', f'"{keyword}" photo', keyword):
            qkey = ("bing", query)
            if qkey in self._dead_queries:
                continue
            got_new = False
            for first in range(0, 210, 35):  # up to 6 pages/query (was 28) — plenty for target sizes, ~5x faster
                try:
                    resp = self._get(
                        "https://www.bing.com/images/async",
                        params={"q": query, "first": first, "count": 35,
                                "adlt": "moderate", "qft": "+filterui:imagesize-large",
                                "mkt": region_code},
                    )
                except requests.RequestException as exc:
                    logger.warning("Bing page failed (%r): %s", query, exc)
                    break
                murls = re.findall(r'murl&quot;:&quot;(.*?)&quot;', resp.text) or \
                        re.findall(r'"murl":"(.*?)"', resp.text)
                purls = re.findall(r'purl&quot;:&quot;(.*?)&quot;', resp.text) or \
                        re.findall(r'"purl":"(.*?)"', resp.text)
                if not murls:
                    break  # no more pages
                for i, murl in enumerate(murls):
                    got_new = True
                    yield murl.replace("\\/", "/"), (purls[i].replace("\\/", "/") if i < len(purls) else None)
                time.sleep(0.15)
            if not got_new:
                self._dead_queries.add(qkey)

    # ------------------------------------------------ source 3: Openverse API
    def _openverse_items(self, keyword, _region_code):
        qkey = ("openverse", keyword)
        if qkey in self._dead_queries:
            return
        got_new = False
        for page in range(1, 6):  # API allows ~5 anonymous pages
            try:
                data = self._get(
                    "https://api.openverse.org/v1/images/",
                    params={"q": keyword, "page_size": 100, "page": page},
                ).json()
            except (requests.RequestException, ValueError) as exc:
                logger.warning("Openverse page failed: %s", exc)
                break
            results = data.get("results") or []
            if not results:
                break
            for it in results:
                w, h = int(it.get("width") or 0), int(it.get("height") or 0)
                if w and h and (w < MIN_W or h < MIN_H):
                    continue
                got_new = True
                yield it.get("url"), it.get("foreign_landing_url")
            time.sleep(0.15)
        if not got_new:
            self._dead_queries.add(qkey)

    # ------------------------------------------------------------- main API
    def collect_image_urls(self, keyword: str, target_count: int,
                           region: str = "") -> list[ImageResult]:
        results: list[ImageResult] = []
        self.last_block_reason = None
        clean_keyword = keyword.strip()
        if not clean_keyword:
            return results

        collect_target = max(int(target_count * 1.3), target_count + 20)
        region_code = REGION_CODES.get(region)
        # region-first, then global fill (DDG); Bing/Openverse use one market
        ddg_regions = [region_code, "us-en"] if region_code else ["us-en"]

        def sources():
            # Provider manager: next provider starts ONLY if target not reached
            yield "Google", self._google_items(clean_keyword, region_code or "en")
            yield "Bing", self._bing_items(clean_keyword, region_code or "en-US")
            yield "Yandex", self._yandex_items(clean_keyword, region_code or "")
            for rc in ddg_regions:  # DuckDuckGo: existing final fallback
                yield "DuckDuckGo", self._ddg_items(clean_keyword, rc)
            yield "Openverse", self._openverse_items(clean_keyword, region_code or "")

        try:
            for name, items in sources():
                if len(results) >= collect_target:
                    break
                before = len(results)
                for img_url, page_url in items:
                    if not self._fresh(img_url):
                        continue
                    self.session_seen.add(img_url)
                    logger.debug("[%s] %s", name, img_url)
                    results.append(ImageResult(
                        keyword=clean_keyword,
                        page_url=page_url or self.search(clean_keyword),
                        image_url=img_url,
                        provider=name))
                    if len(results) >= collect_target:
                        break
                logger.info("%s contributed %d new URLs (total %d/%d)",
                            name, len(results) - before, len(results), collect_target)
        except Exception as exc:
            self.last_block_reason = f"Search error: {exc}"
            logger.error(self.last_block_reason)

        if not results and not self.last_block_reason:
            self.last_block_reason = "All sources exhausted — no new images available."
        return results

    def collect_parallel(self, keyword: str, target_count: int, region: str = "",
                         url_queue=None, stop_event=None) -> None:
        """ALL providers run simultaneously in threads, streaming fresh unique
        ImageResults into url_queue the moment they are found. A None sentinel
        is pushed when every provider is exhausted. Thread-safe global dedup."""
        clean = keyword.strip()
        region_code = REGION_CODES.get(region)
        collect_cap = max(int(target_count * 1.3), target_count + 20)  # was 1.5x/+30 — stops providers sooner
        lock = threading.Lock()
        counter = {"n": 0}
        google_gen = (self._google_playwright_items(clean, region_code)
                      if PLAYWRIGHT_OK else self._google_items(clean, region_code or "en"))
        providers = [
            ("Google", google_gen),
            ("Bing", self._bing_items(clean, region_code or "en-US")),
            ("Yandex", self._yandex_items(clean, region_code or "")),
        ]
        for rc in ([region_code, "us-en"] if region_code else ["us-en"]):
            providers.append(("DuckDuckGo", self._ddg_items(clean, rc)))
        providers.append(("Openverse", self._openverse_items(clean, region_code or "")))

        def run(name, gen):
            n = 0
            try:
                for img_url, page_url in gen:
                    if stop_event is not None and stop_event.is_set():
                        break
                    with lock:
                        if counter["n"] >= collect_cap:
                            break
                        if not self._fresh(img_url):
                            continue
                        self.session_seen.add(img_url)
                        counter["n"] += 1
                    n += 1
                    url_queue.put(ImageResult(clean, page_url or self.search(clean),
                                              img_url, name))
            except Exception as exc:
                logger.warning("%s provider crashed: %s", name, exc)
            logger.info("%s finished: %d URLs streamed", name, n)

        threads = [threading.Thread(target=run, args=p, daemon=True) for p in providers]
        for t in threads:
            t.start()

        def closer():
            for t in threads:
                t.join()
            url_queue.put(None)  # sentinel: every provider exhausted/cancelled
        threading.Thread(target=closer, daemon=True).start()

    def record_downloaded(self, urls: list[str]) -> None:
        """Only successfully downloaded URLs go into permanent history."""
        if not urls:
            return
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.history_file, "a", encoding="utf-8", errors="ignore") as f:
            for u in urls:
                f.write(u + "\n")
        self.seen_history.update(urls)


# Compatibility layer — app.py imports this name.
OpenverseImageScraper = GoogleImageScraper
