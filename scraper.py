"""
scraper.py
----------
Fetches image results via DuckDuckGo (ddgs package).
No API key, no monthly limit.

Volume + accuracy strategy:
- Runs multiple query variations of the keyword to collect far more
  candidates than a single query can return
- Light title filtering removes obviously irrelevant results
- Final accuracy is enforced by CLIP verification after download
"""

import logging
import urllib.parse
from dataclasses import dataclass
from pathlib import Path

from ddgs import DDGS

from config import ScraperConfig

logger = logging.getLogger(__name__)


@dataclass
class ImageResult:
    """A single scraped image candidate."""
    keyword: str
    page_url: str
    image_url: str


class GoogleImageScraper:
    """Fetches images via DuckDuckGo's image search — no API key needed."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self.last_block_reason: str | None = None
        # Pehle download ho chuke URLs — repeat runs par duplicates skip.
        self.history_file = Path(getattr(config, "output_dir", ".")) / ".seen_urls.txt"
        self.seen_history: set[str] = set()
        if self.history_file.exists():
            self.seen_history = set(self.history_file.read_text().splitlines())

    def search(self, keyword: str) -> str:
        """Returns the public web URL for this search on DuckDuckGo Images."""
        return f"https://duckduckgo.com/?q={urllib.parse.quote(keyword)}&iax=images&ia=images"

    def _query_variations(self, keyword: str) -> list[str]:
        """
        Same keyword, different query phrasings — every variation still
        contains the exact quoted phrase, so relevance is preserved,
        but each one surfaces a different slice of the index.
        """
        kw = f'"{keyword}"'
        return [
            kw,
            f"{kw} photo",
            f"{kw} image",
            f"{kw} hd",
            f"{kw} high resolution",
            f"{kw} picture",
            f"{kw} photography",
            f"{kw} close up",
            # Unquoted fallbacks — broader index coverage when exact-phrase runs dry
            keyword,
            f"{keyword} photo",
            f"{keyword} wallpaper",
            f"{keyword} gallery",
        ]

    def _title_ok(self, title: str, keyword: str) -> bool:
        """Loose filter: at least one keyword word must appear in title.
        Strict content checking is CLIP's job after download."""
        title = title.lower()
        return any(w in title for w in keyword.lower().split())

    def collect_image_urls(
        self,
        keyword: str,
        target_count: int,
        region: str = "",
    ) -> list[ImageResult]:
        """
        Collects up to target_count unique image URLs by running several
        query variations of the exact keyword.
        """
        results: list[ImageResult] = []
        seen: set[str] = set()
        self.last_block_reason = None

        clean_keyword = keyword.strip()
        if not clean_keyword:
            return results

        # CLIP baad mein kuch images delete karega, isliye buffer ke saath
        # zyada collect karo taake final count target ke qareeb rahe.
        # Exhaust every query variation & all result pages (ddgs paginates
        # internally up to max_results) before stopping.
        collect_target = max(int(target_count * 1.5), target_count + 20)

        try:
            with DDGS() as ddgs:
                for query in self._query_variations(clean_keyword):
                    if len(results) >= collect_target:
                        break

                    logger.info("Querying DuckDuckGo Images: %r", query)
                    try:
                        raw = list(ddgs.images(
                            query,
                            safesearch="moderate",
                            size="Large",
                            type_image="photo",
                            max_results=200,
                        ))
                    except TypeError:
                        # this ddgs version doesn't support size/type_image kwargs
                        try:
                            raw = list(ddgs.images(query, safesearch="moderate", max_results=300))
                        except Exception as exc:
                            logger.warning("Query %r failed: %s", query, exc)
                            self.last_block_reason = f"Search error: {exc}"
                            continue
                    except Exception as exc:
                        logger.warning("Query %r failed: %s — trying next variation.", query, exc)
                        self.last_block_reason = f"Search error: {exc}"
                        continue

                    new_this_query = 0
                    for item in raw:
                        img_url = item.get("image")
                        page_url = item.get("url") or self.search(clean_keyword)
                        title = item.get("title") or ""

                        if not img_url or img_url in seen or img_url in self.seen_history:
                            continue
                        if not self._title_ok(title, clean_keyword):
                            continue

                        seen.add(img_url)
                        results.append(
                            ImageResult(
                                keyword=clean_keyword,
                                page_url=page_url,
                                image_url=img_url,
                            )
                        )
                        new_this_query += 1
                        if len(results) >= collect_target:
                            break

                    logger.info(
                        "Query %r added %d new URLs (total: %d/%d)",
                        query, new_this_query, len(results), collect_target,
                    )

        except Exception as exc:
            self.last_block_reason = f"DuckDuckGo search error: {exc}"
            logger.error(self.last_block_reason)

        if not results and not self.last_block_reason:
            self.last_block_reason = "No results found on DuckDuckGo Images."
            logger.warning("Empty result set for %r.", clean_keyword)
        elif results:
            logger.info("Collected %d unique image URLs for %r.", len(results), clean_keyword)
            self.history_file.parent.mkdir(parents=True, exist_ok=True)
            with open(self.history_file, "a") as f:
                for r in results:
                    f.write(r.image_url + "\n")

        return results


# Compatibility layer — main.py imports this name.
OpenverseImageScraper = GoogleImageScraper