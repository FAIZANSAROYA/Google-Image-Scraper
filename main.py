"""
main.py
-------
Entry point for the keyword image downloader.

Usage:
    python main.py --keywords "red panda" "golden retriever" --count 40
    python main.py --keywords "mount fuji" --count 20 --output ./images

This orchestrates, per keyword:
    1. Query DuckDuckGo Images for matching images (multiple query variations)
    2. Collect downloadable image URLs
    3. Download them concurrently into keyword-named folders,
       skipping duplicates and handling failures
    4. Verify every downloaded image with CLIP and delete the ones
       that don't actually match the keyword (threshold=0.30, strict)
"""

import argparse
import logging
import sys
from pathlib import Path

from config import ScraperConfig
from downloader import ImageDownloader
from scraper import OpenverseImageScraper
from verifier import verify_folder

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("image_downloader")

# CLIP similarity cutoff: 0.25 = balanced, 0.27 = strict (most accurate).
CLIP_THRESHOLD = 0.27

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download images by keyword.")
    parser.add_argument("--keywords", nargs="+", required=True, help="One or more search keywords.")
    parser.add_argument("--count", type=int, default=50, help="Images to download per keyword.")
    parser.add_argument("--output", type=str, default="downloaded_images", help="Output directory.")
    parser.add_argument(
        "--formats", nargs="+", default=["jpg", "jpeg", "png", "webp"], help="Allowed image formats."
    )
    parser.add_argument(
        "--concurrent-downloads", type=int, default=8, help="Number of parallel download workers."
    )
    parser.add_argument(
        "--clip-threshold", type=float, default=CLIP_THRESHOLD,
        help="CLIP similarity cutoff for verification (0.25 balanced, 0.27 strict).",
    )
    parser.add_argument(
        "--no-verify", action="store_true",
        help="Skip CLIP verification (faster, less accurate).",
    )
    return parser.parse_args()


def _find_keyword_folder(output_dir: str, keyword: str) -> Path | None:
    """
    Locate the folder the downloader created for this keyword.
    Handles common naming styles: "red panda", "red_panda", "red-panda".
    """
    base = Path(output_dir)
    candidates = [
        keyword,
        keyword.replace(" ", "_"),
        keyword.replace(" ", "-"),
    ]
    for name in candidates:
        folder = base / name
        if folder.is_dir():
            return folder
    return None


def run(config: ScraperConfig, clip_threshold: float, verify: bool) -> None:
    downloader = ImageDownloader(config)

    overall_summary = {
        "downloaded": 0, "duplicates": 0, "failed": 0,
        "skipped_format": 0, "verified_kept": 0, "verified_removed": 0,
    }

    scraper = OpenverseImageScraper(config)

    for keyword in config.keywords:
        try:
            scraper.search(keyword)
            image_results = scraper.collect_image_urls(keyword, config.images_per_keyword)

            if not image_results:
                logger.warning("No image URLs found for %r; skipping.", keyword)
                continue

            summary = downloader.download_all(image_results)
            for key, value in summary.items():
                overall_summary[key] = overall_summary.get(key, 0) + value

            # CLIP verification: delete downloaded images that don't
            # actually show the keyword.
            if verify:
                keyword_folder = _find_keyword_folder(config.output_dir, keyword)
                if keyword_folder is None:
                    logger.warning(
                        "Could not locate download folder for %r under %s; "
                        "skipping verification.", keyword, config.output_dir,
                    )
                else:
                    v = verify_folder(str(keyword_folder), keyword, threshold=clip_threshold)
                    overall_summary["verified_kept"] += v["kept"]
                    overall_summary["verified_removed"] += v["removed"]

            logger.info(
                "Finished %r -> downloaded=%d duplicates=%d failed=%d skipped_format=%d",
                keyword,
                summary.get("downloaded", 0),
                summary.get("duplicates", 0),
                summary.get("failed", 0),
                summary.get("skipped_format", 0),
            )
        except Exception:
            # A failure on one keyword should never abort the whole run.
            logger.exception("Unexpected error while processing keyword %r; continuing.", keyword)
            continue

    logger.info("All keywords processed. Overall summary: %s", overall_summary)


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
        "Starting scrape: keywords=%s, target=%d/keyword, output=%s, clip_threshold=%.2f",
        config.keywords,
        config.images_per_keyword,
        config.output_dir,
        args.clip_threshold,
    )

    try:
        run(config, clip_threshold=args.clip_threshold, verify=not args.no_verify)
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Exiting.")
        sys.exit(1)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(2)


if __name__ == "__main__":
    main()
