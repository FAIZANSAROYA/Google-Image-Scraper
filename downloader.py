"""
downloader.py
-------------
Downloads image URLs to disk with:
  - content-hash based duplicate detection
  - format validation (jpg/png/webp)
  - retries on transient failures
  - concurrent downloads for throughput
"""

import hashlib
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests
from PIL import Image, UnidentifiedImageError

from config import ScraperConfig
from scraper import ImageResult

logger = logging.getLogger(__name__)

# Maps Pillow's reported format to a canonical file extension.
FORMAT_TO_EXTENSION = {
    "JPEG": "jpg",
    "PNG": "png",
    "WEBP": "webp",
}


class ImageDownloader:
    """Downloads and organizes images collected by the scraper."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self._seen_hashes: dict[str, set[str]] = {}  # keyword -> set of content hashes

    def download_all(self, results: list[ImageResult]) -> dict:
        """
        Download a batch of ImageResult objects concurrently.
        Returns a summary dict with counts of successes/failures/duplicates.
        """
        summary = {"downloaded": 0, "duplicates": 0, "failed": 0, "skipped_format": 0}

        with ThreadPoolExecutor(max_workers=self.config.concurrent_downloads) as pool:
            futures = {pool.submit(self._download_one, r): r for r in results}
            for future in as_completed(futures):
                outcome = future.result()
                summary[outcome] = summary.get(outcome, 0) + 1

        logger.info("Download summary: %s", summary)
        return summary

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _download_one(self, result: ImageResult) -> str:
        """
        Download a single image. Returns one of:
        'downloaded', 'duplicates', 'failed', 'skipped_format'
        """
        keyword_dir = self._keyword_dir(result.keyword)
        keyword_dir.mkdir(parents=True, exist_ok=True)

        content = self._fetch_with_retries(result.image_url)
        if content is None:
            return "failed"

        if len(content) < self.config.min_image_bytes:
            logger.debug("Discarding too-small image (%d bytes): %s", len(content), result.image_url)
            return "failed"

        file_format = self._detect_format(content)
        if file_format is None or file_format.lower() not in self.config.allowed_formats:
            return "skipped_format"

        content_hash = hashlib.sha256(content).hexdigest()
        keyword_hashes = self._seen_hashes.setdefault(result.keyword, set())
        if content_hash in keyword_hashes:
            return "duplicates"
        keyword_hashes.add(content_hash)

        filename = f"{content_hash[:16]}.{file_format}"
        filepath = keyword_dir / filename
        try:
            filepath.write_bytes(content)
        except OSError as exc:
            logger.warning("Could not write file %s: %s", filepath, exc)
            return "failed"

        logger.debug("Saved %s", filepath)
        return "downloaded"

    def _fetch_with_retries(self, url: str) -> bytes | None:
        attempts = self.config.max_download_retries + 1
        for attempt in range(1, attempts + 1):
            try:
                response = requests.get(
                    url,
                    headers=self.config.request_headers,
                    timeout=self.config.download_timeout_seconds,
                )
                response.raise_for_status()
                return response.content
            except requests.RequestException as exc:
                logger.debug(
                    "Download attempt %d/%d failed for %s: %s", attempt, attempts, url, exc
                )
        logger.warning("Giving up on %s after %d attempts", url, attempts)
        return None

    @staticmethod
    def _detect_format(content: bytes) -> str | None:
        """Validate actual image bytes (not just trusting the URL extension)."""
        try:
            from io import BytesIO
            with Image.open(BytesIO(content)) as img:
                return FORMAT_TO_EXTENSION.get(img.format)
        except UnidentifiedImageError:
            return None
        except Exception:
            return None

    def _keyword_dir(self, keyword: str) -> Path:
        safe_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in keyword).strip()
        safe_name = safe_name.replace(" ", "_")
        return self.config.output_dir / safe_name
