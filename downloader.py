"""
downloader.py
-------------
Downloads image URLs to disk with:
  - content-hash based duplicate detection
  - real byte-level format validation (jpg/png/webp) via Pillow
  - retries on transient failures
  - concurrent downloads with per-thread connection pooling (fast)
  - flat file storage: <output_dir>/<uuid>_<timestamp>.<ext>
"""

import hashlib
import io
import logging
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path

import requests
from PIL import Image, UnidentifiedImageError

from config import ScraperConfig
from scraper import ImageResult

logger = logging.getLogger(__name__)

# Pillow's reported format -> canonical file extension.
FORMAT_TO_EXTENSION = {"JPEG": "jpg", "PNG": "png", "WEBP": "webp", "GIF": "gif"}

# One requests.Session per worker thread = TCP connection reuse = much faster.
_thread_local = threading.local()


class ImageDownloader:
    """Downloads images and saves them directly (flat folder, no pipeline)."""

    def __init__(self, config: ScraperConfig):
        self.config = config
        self._seen_hashes: dict[str, set[str]] = {}  # keyword -> content hashes
        self._lock = threading.Lock()

    def download_all(self, results: list[ImageResult], stop_event=None, progress_cb=None) -> dict:
        """
        Download a batch of ImageResult objects concurrently.
        Returns a summary dict with counts of successes/failures/duplicates.
        """
        summary = {"downloaded": 0, "duplicates": 0, "failed": 0, "skipped_format": 0, "stopped": 0}
        failed_results = []
        # Stop early once we have enough (target + 20% buffer for CLIP filtering)
        enough = max(int(self.config.images_per_keyword * 1.2), self.config.images_per_keyword + 5)

        with ThreadPoolExecutor(max_workers=self.config.concurrent_downloads) as pool:
            futures = {pool.submit(self._download_one, r, stop_event): r for r in results}
            done = 0
            for future in as_completed(futures):
                outcome = future.result()
                if outcome == "failed":
                    failed_results.append(futures[future])
                summary[outcome] = summary.get(outcome, 0) + 1
                done += 1
                if progress_cb:
                    try:
                        progress_cb(done, len(results))
                    except Exception:
                        pass
                if summary["downloaded"] >= enough:
                    for f in futures:
                        f.cancel()  # skip everything still queued
                    break

        # Recovery pass: retry every failed download once more, longer timeout.
        if failed_results and summary["downloaded"] < enough and not (stop_event is not None and stop_event.is_set()):
            logger.info("Retrying %d failed downloads...", len(failed_results))
            old_timeout = self.config.download_timeout_seconds
            self.config.download_timeout_seconds = old_timeout * 2
            try:
                with ThreadPoolExecutor(max_workers=max(4, self.config.concurrent_downloads // 3)) as pool:
                    futures = {pool.submit(self._download_one, r, stop_event): r for r in failed_results}
                    for future in as_completed(futures):
                        outcome = future.result()
                        if outcome != "failed":
                            summary["failed"] -= 1
                            summary[outcome] = summary.get(outcome, 0) + 1
            finally:
                self.config.download_timeout_seconds = old_timeout

        logger.info("Download summary: %s", summary)
        return summary

    # ------------------------------------------------------------------ #
    # Internal
    # ------------------------------------------------------------------ #

    def _download_one(self, result: ImageResult, stop_event=None):
        """
        Download and save a single image.
        Returns outcome: 'downloaded', 'duplicates', 'failed', 'skipped_format' or 'stopped'.
        """
        if stop_event is not None and stop_event.is_set():
            return "stopped"
        keyword_dir = self._keyword_dir(result.keyword)
        keyword_dir.mkdir(parents=True, exist_ok=True)

        content = self._fetch_with_retries(result.image_url)
        if content is None:
            return "failed"

        if len(content) < self.config.min_image_bytes:
            logger.debug("Discarding too-small image (%d bytes)", len(content))
            return "failed"

        # Content-hash dedup - identical bytes are skipped regardless of URL.
        content_hash = hashlib.sha256(content).hexdigest()
        with self._lock:
            keyword_hashes = self._seen_hashes.setdefault(result.keyword, set())
            if content_hash in keyword_hashes:
                return "duplicates"
            keyword_hashes.add(content_hash)

        # Validate REAL bytes with Pillow (accuracy: never trust the URL extension).
        ext = self._detect_format(content)
        if ext is None or ext not in self.config.allowed_formats:
            with self._lock:
                keyword_hashes.discard(content_hash)
            return "skipped_format"

        # Unique, sortable filename.
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S")
        filename = f"{uuid.uuid4().hex[:12]}_{timestamp}.{ext}"
        filepath = keyword_dir / filename

        try:
            filepath.write_bytes(content)
            logger.debug("Saved %s -> %s", result.image_url, filename)
            return "downloaded"
        except Exception as exc:
            logger.warning("Failed to save %s: %s", result.image_url, exc)
            with self._lock:
                keyword_hashes.discard(content_hash)
            return "failed"

    @staticmethod
    def _detect_format(content: bytes):
        """Return the canonical extension for real image bytes, or None."""
        try:
            with Image.open(io.BytesIO(content)) as img:
                return FORMAT_TO_EXTENSION.get(img.format)
        except (UnidentifiedImageError, OSError, ValueError):
            return None

    def _session(self) -> requests.Session:
        """Per-thread session: connection pooling gives a big speed boost."""
        session = getattr(_thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self.config.request_headers)
            _thread_local.session = session
        return session

    def _fetch_with_retries(self, url):
        attempts = self.config.max_download_retries + 1
        session = self._session()
        for attempt in range(1, attempts + 1):
            try:
                response = session.get(url, timeout=self.config.download_timeout_seconds, stream=True)
                response.raise_for_status()
                size = response.headers.get("Content-Length")
                if size and int(size) > 15 * 1024 * 1024:  # >15MB: slow, not worth it
                    logger.debug("Skipping huge file (%s bytes): %s", size, url)
                    return None
                return response.content
            except requests.RequestException as exc:
                logger.debug("Download attempt %d/%d failed for %s: %s", attempt, attempts, url, exc)
        logger.warning("Giving up on %s after %d attempts", url, attempts)
        return None

    def _keyword_dir(self, keyword: str) -> Path:
        # Use output_dir directly (already includes the category folder)
        return self.config.output_dir
