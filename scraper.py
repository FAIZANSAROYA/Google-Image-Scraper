"""
Fetches image results from the Openverse API and returns downloadable
image URLs for each keyword.
"""

import logging
import re
import urllib.parse
from dataclasses import dataclass

import requests

from config import ScraperConfig

logger = logging.getLogger(__name__)

OPENVERSE_API_URL = "https://api.openverse.org/v1/images/"
MIN_IMAGE_WIDTH = 400
MIN_IMAGE_HEIGHT = 400
MIN_ASPECT_RATIO = 0.2   # filters out extreme banners/strips
MAX_ASPECT_RATIO = 5.0

# Common filler words dropped when building a broader fallback query.
_STOPWORDS = {
    "the", "a", "an", "of", "in", "on", "at", "for", "and", "or", "with",
}


@dataclass
class ImageResult:
    """A single scraped image candidate."""
    keyword: str
    page_url: str
    image_url: str


class OpenverseImageScraper:
    """Encapsulates Openverse API search and pagination."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.request_headers = dict(config.request_headers)
        self.last_block_reason: str | None = None

    def search(self, keyword: str) -> str:
        """Record the current keyword and reset any previous status."""
        self.last_block_reason = None
        return self._build_search_url(keyword)

    def collect_image_urls(
        self,
        keyword: str,
        target_count: int,
    ) -> list[ImageResult]:

        results: list[ImageResult] = []
        seen_urls: set[str] = set()
        tried_queries: set[str] = set()

        clean_keyword = self._preprocess_query(keyword)
        keyword_terms = self._build_relevance_terms(clean_keyword)

        # Region-aware search
        if self.config.regions:
            search_queries = [
                self._preprocess_query(f"{clean_keyword} {region}")
                for region in self.config.regions
            ]
        else:
            search_queries = [clean_keyword]

        early_stop = self._run_queries(
            search_queries, keyword, target_count, results, seen_urls, tried_queries, keyword_terms
        )
        if early_stop:
            return results

        # Multiple fallback searches: only needed if the region-aware pass
        # came up short (or empty), or we're deliberately maximizing coverage.
        if not results or len(results) < target_count or self.config.maximum_scraping:
            fallback_queries = self._build_fallback_queries(clean_keyword, tried_queries)
            if fallback_queries:
                early_stop = self._run_queries(
                    fallback_queries, keyword, target_count, results, seen_urls, tried_queries, keyword_terms
                )
                if early_stop:
                    return results

        if not results:
            self.last_block_reason = (
                "No Openverse results were returned for this keyword. "
                "Try a different search term."
            )
            logger.warning(
                "No Openverse image URLs found for %r.",
                keyword,
            )

        logger.info(
            "Collected %d image URLs for %r",
            len(results),
            keyword,
        )

        return results

    def _run_queries(
        self,
        search_queries: list[str],
        original_keyword: str,
        target_count: int,
        results: list[ImageResult],
        seen_urls: set[str],
        tried_queries: set[str],
        keyword_terms: list[str],
    ) -> bool:
        """
        Run each query in `search_queries` through pagination, appending
        accepted results in place. Returns True if the caller should stop
        and return immediately (target reached with maximum scraping off).
        """
        for search_query in search_queries:
            if not search_query or search_query in tried_queries:
                continue
            tried_queries.add(search_query)

            page = 1
            page_size = 20

            while True:

                payload = self._fetch_page(
                    search_query,
                    page=page,
                    page_size=page_size,
                )

                if not isinstance(payload, dict):
                    break

                items = payload.get("results", [])

                if not items:
                    break

                for item in items:

                    if not self._passes_quality_filter(item):
                        continue

                    if not self._passes_relevance_filter(item, keyword_terms):
                        continue

                    image_url = (item.get("url") or "").strip()
                    dedup_key = self._normalize_for_dedup(image_url)

                    if not dedup_key or dedup_key in seen_urls:
                        continue

                    seen_urls.add(dedup_key)

                    results.append(
                        ImageResult(
                            keyword=original_keyword,
                            page_url=item.get("foreign_landing_url")
                            or self._build_search_url(search_query),
                            image_url=image_url,
                        )
                    )

                    # Stop only if maximum scraping is disabled
                    if (
                        not self.config.maximum_scraping
                        and len(results) >= target_count
                    ):
                        logger.info(
                            "Collected %d image URLs for %r",
                            len(results),
                            original_keyword,
                        )
                        return True

                page_count = int(payload.get("page_count") or 0)

                if page_count and page >= page_count:
                    break

                page += 1

        return False

    def _passes_quality_filter(self, item: dict) -> bool:
        """Reject mature, undersized, malformed, or oddly-shaped candidates."""
        if item.get("mature"):
            return False

        width = int(item.get("width") or 0)
        height = int(item.get("height") or 0)
        if width < MIN_IMAGE_WIDTH or height < MIN_IMAGE_HEIGHT:
            return False

        aspect_ratio = width / height if height else 0
        if not (MIN_ASPECT_RATIO <= aspect_ratio <= MAX_ASPECT_RATIO):
            return False

        image_url = (item.get("url") or "").strip()
        if not image_url or "/thumb/" in image_url:
            return False

        return True

    @staticmethod
    def _build_relevance_terms(clean_keyword: str) -> list[str]:
        """
        Significant lowercase words from the original keyword, used to check
        that a candidate image is actually about the keyword rather than
        just something a broadened fallback query happened to match.
        """
        stripped = OpenverseImageScraper._strip_stopwords(clean_keyword)
        words = [w.lower() for w in stripped.split()]
        significant = [w for w in words if len(w) > 2]
        return significant or words

    @staticmethod
    def _passes_relevance_filter(item: dict, keyword_terms: list[str]) -> bool:
        """
        Accept an item only if at least one keyword term shows up in its
        title or tags. If no usable keyword terms exist, nothing is filtered
        out on relevance grounds.
        """
        if not keyword_terms:
            return True

        text_parts = [str(item.get("title") or "")]
        for tag in item.get("tags") or []:
            if isinstance(tag, dict):
                text_parts.append(str(tag.get("name") or ""))
            else:
                text_parts.append(str(tag))

        haystack = " ".join(text_parts).lower()
        if not haystack.strip():
            return True  # no metadata to judge by; don't punish the item

        return any(term in haystack for term in keyword_terms)

    def _fetch_page(
        self,
        keyword: str,
        page: int,
        page_size: int,
    ) -> dict:

        params = {
            "q": keyword,
            "page": page,
            "page_size": page_size,
            "size": "large",
            "category": "photograph",
        }

        response = requests.get(
            OPENVERSE_API_URL,
            params=params,
            headers=self.request_headers,
            timeout=self.config.download_timeout_seconds,
        )

        response.raise_for_status()

        return response.json()

    @staticmethod
    def _preprocess_query(raw: str) -> str:
        """Normalize a raw keyword/query into a clean search string."""
        if not raw:
            return ""
        # Collapse whitespace, strip stray punctuation Openverse doesn't need.
        cleaned = re.sub(r"[^\w\s'-]", " ", raw)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _strip_stopwords(query: str) -> str:
        words = [w for w in query.split() if w.lower() not in _STOPWORDS]
        return " ".join(words) if words else query

    def _build_fallback_queries(self, clean_keyword: str, tried_queries: set[str]) -> list[str]:
        """
        Build a small, ordered list of broader query variations to try when
        the primary (region-aware) search comes up empty or short.
        """
        fallbacks: list[str] = []

        # 1) The bare keyword with no region suffix.
        if clean_keyword and clean_keyword not in tried_queries:
            fallbacks.append(clean_keyword)

        # 2) The keyword with common filler words removed.
        stripped = self._strip_stopwords(clean_keyword)
        if stripped and stripped != clean_keyword and stripped not in tried_queries:
            fallbacks.append(stripped)

        # 3) Each significant individual word, as a last-resort broadening.
        words = [w for w in stripped.split() if len(w) > 2]
        if len(words) > 1:
            for word in words:
                if word not in tried_queries and word not in fallbacks:
                    fallbacks.append(word)

        return fallbacks

    @staticmethod
    def _normalize_for_dedup(url: str) -> str:
        """Strip query-string cache-busters so identical images with
        different URL params aren't downloaded twice."""
        if not url:
            return ""
        parsed = urllib.parse.urlsplit(url)
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    @staticmethod
    def _build_search_url(keyword: str) -> str:
        return (
            f"https://openverse.org/search/image?"
            f"q={urllib.parse.quote(keyword)}"
        )