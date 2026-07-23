"""
main.py
-------
Entry point for the keyword image downloader.

Usage:
    python main.py --keywords "red panda" "golden retriever" --count 40
    python main.py --keywords "mount fuji" --count 20 --output ./images

Orchestration (per keyword, all keywords run concurrently too):
    1. Google (Playwright) + Bing + Yandex + DuckDuckGo + Openverse all start
       AT THE SAME TIME via scraper.collect_parallel() (thread-parallel
       provider fan-out, unchanged) and stream URLs into a shared queue.
    2. downloader.download_stream() drains that queue with N concurrent
       worker threads, downloading the instant a URL arrives -- no waiting
       for any provider to finish, no "Round 1 / Round 2" sequencing.
    3. The moment enough images are on disk, download_stream stops itself
       and we immediately flip collect_stop -> every provider thread exits
       on its next loop check.
    4. verifier.keep_top_n() (CLIP) ranks everything downloaded and keeps
       only the top `count` keyword-relevant images -- exact count, no more.
    5. If verification drops below target, one bounded top-up pass runs
       (never a 3rd/4th round) using only the shortfall as target.
This whole per-keyword pipeline is wrapped in asyncio.to_thread() and every
keyword is launched together with asyncio.gather(), so this is the real
top-level parallel entry point requested for the CLI.
"""

import argparse
import asyncio
import logging
import sys
from pathlib import Path

from config import ScraperConfig
from downloader import ImageDownloader
from scraper import OpenverseImageScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("image_downloader")

CLIP_THRESHOLD = 0.27  # 0.25 balanced, 0.27 strict (most accurate)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download images by keyword.")
    parser.add_argument("--keywords", nargs="+", required=True, help="One or more search keywords.")
    parser.add_argument("--count", type=int, default=50, help="Images to download per keyword.")
    parser.add_argument("--output", type=str, default="downloaded_images", help="Output directory.")
    parser.add_argument("--formats", nargs="+", default=["jpg", "jpeg", "png", "webp"],
                         help="Allowed image formats.")
    parser.add_argument("--concurrent-downloads", type=int, default=30,
                         help="Parallel download workers (20-50 recommended).")
    parser.add_argument("--clip-threshold", type=float, default=CLIP_THRESHOLD,
                         help="CLIP similarity cutoff (0.25 balanced, 0.27 strict).")
    parser.add_argument("--no-verify", action="store_true",
                         help="Skip CLIP verification (faster, less accurate).")
    return parser.parse_args()


async def scrape_keyword_async(config: ScraperConfig, keyword: str, verify: bool,
                                clip_threshold: float) -> dict:
    """One keyword's full parallel pipeline: fan-out -> stream-download ->
    verify -> (bounded) top-up. Every blocking call is off-loaded with
    asyncio.to_thread so multiple keywords can genuinely run together
    under asyncio.gather() without blocking each other."""
    from queue import Queue
    import threading

    keyword_dir = Path(config.output_dir) / keyword.replace(" ", "_")
    keyword_dir.mkdir(parents=True, exist_ok=True)
    kw_config = ScraperConfig(
        keywords=[keyword],
        images_per_keyword=config.images_per_keyword,
        output_dir=str(keyword_dir),
        allowed_formats=config.allowed_formats,
        concurrent_downloads=config.concurrent_downloads,
    )
    downloader = ImageDownloader(kw_config)
    scraper = OpenverseImageScraper(kw_config)

    verify_fn = None
    if verify:
        try:
            from verifier import keep_top_n
            verify_fn = keep_top_n
        except ImportError:
            logger.warning("sentence-transformers not installed; skipping verification.")
            verify_fn = None

    need = config.images_per_keyword
    total_downloaded = 0
    valid = 0
    summary = {}

    for attempt in (1, 2):  # bounded: initial pass + at most one top-up
        buffer_need = max(int(need * 1.25), need + 8) if verify_fn else need
        url_q = Queue()
        collect_stop = threading.Event()

        # Step 1: launch ALL providers simultaneously (non-blocking call --
        # it starts daemon threads and returns immediately).
        scraper.collect_parallel(keyword, need, url_queue=url_q, stop_event=collect_stop)

        # Step 2: stream-download with N concurrent workers, off the event
        # loop so this keyword doesn't block others running concurrently.
        s = await asyncio.to_thread(
            downloader.download_stream, url_q, buffer_need, None, None
        )

        # Step 3: target reached (or queue exhausted) -> cancel every
        # remaining provider thread immediately.
        collect_stop.set()

        exhausted = s.get("downloaded", 0) < buffer_need
        scraper.record_downloaded(s.pop("ok_urls", []))
        total_downloaded += s.get("downloaded", 0)
        summary = s

        # Step 4: verify concurrently (CLIP batch-encodes all images in one
        # pass already) and keep only the exact target count.
        if verify_fn:
            v = await asyncio.to_thread(
                verify_fn, str(keyword_dir), keyword, config.images_per_keyword, 0.25
            )
            valid = v["kept"]
        else:
            files = sorted(
                p for p in keyword_dir.iterdir()
                if p.suffix.lower().lstrip(".") in config.allowed_formats
            )
            for extra in files[config.images_per_keyword:]:
                extra.unlink(missing_ok=True)
            valid = min(len(files), config.images_per_keyword)

        need = config.images_per_keyword - valid
        if need <= 0 or exhausted:
            break
        logger.info("%r: %d/%d valid after pass %d, topping up %d more.",
                    keyword, valid, config.images_per_keyword, attempt, need)

    logger.info(
        "Finished %r -> downloaded=%d duplicates=%d failed=%d skipped_format=%d valid=%d/%d",
        keyword, total_downloaded, summary.get("duplicates", 0), summary.get("failed", 0),
        summary.get("skipped_format", 0), valid, config.images_per_keyword,
    )
    return {"keyword": keyword, "downloaded": total_downloaded, "valid": valid,
            "duplicates": summary.get("duplicates", 0), "failed": summary.get("failed", 0),
            "skipped_format": summary.get("skipped_format", 0)}


async def run_async(config: ScraperConfig, verify: bool, clip_threshold: float) -> None:
    """Top-level asyncio.gather(): every keyword's full parallel pipeline
    runs concurrently with every other keyword's."""
    tasks = [
        asyncio.create_task(scrape_keyword_async(config, kw, verify, clip_threshold))
        for kw in config.keywords
    ]
    try:
        results = await asyncio.gather(*tasks, return_exceptions=True)
    except asyncio.CancelledError:
        for t in tasks:
            t.cancel()
        raise

    overall = {"downloaded": 0, "valid": 0, "duplicates": 0, "failed": 0, "skipped_format": 0}
    for kw, res in zip(config.keywords, results):
        if isinstance(res, Exception):
            logger.error("Keyword %r failed: %s", kw, res)
            continue
        for k in overall:
            overall[k] += res.get(k, 0)
    logger.info("All keywords processed. Overall summary: %s", overall)


def main() -> None:
    args = parse_args()

    config = ScraperConfig(
        keywords=args.keywords,
        images_per_keyword=args.count,
        output_dir=args.output,
        allowed_formats=tuple(f.lower() for f in args.formats),
        concurrent_downloads=args.concurrent_downloads,
    )

    logger.info(
        "Starting scrape: keywords=%s, target=%d/keyword, output=%s, clip_threshold=%.2f, workers=%d",
        config.keywords, config.images_per_keyword, config.output_dir,
        args.clip_threshold, args.concurrent_downloads,
    )

    try:
        asyncio.run(run_async(config, verify=not args.no_verify, clip_threshold=args.clip_threshold))
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Exiting.")
        sys.exit(1)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(2)


if __name__ == "__main__":
    main()
