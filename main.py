"""
main.py
-------
Entry point for the Openverse image downloader.

Usage:
    python main.py --keywords "red panda" "golden retriever" --count 40
    python main.py --keywords "mount fuji" --count 20 --output ./images

This orchestrates, per keyword:
    1. Query Openverse for matching images
    2. Collect downloadable image URLs
    3. Download them concurrently into keyword-named folders,
       skipping duplicates and handling failures
"""

import argparse
import logging
import sys

from config import ScraperConfig
from downloader import ImageDownloader
from scraper import OpenverseImageScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("image_downloader")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download images from Openverse by keyword.")
    parser.add_argument("--keywords", nargs="+", required=True, help="One or more search keywords.")
    parser.add_argument("--count", type=int, default=50, help="Images to download per keyword.")
    parser.add_argument("--output", type=str, default="downloaded_images", help="Output directory.")
    parser.add_argument(
        "--formats", nargs="+", default=["jpg", "jpeg", "png", "webp"], help="Allowed image formats."
    )
    parser.add_argument(
        "--concurrent-downloads", type=int, default=8, help="Number of parallel download workers."
    )
    return parser.parse_args()


def run(config: ScraperConfig) -> None:
    downloader = ImageDownloader(config)

    overall_summary = {"downloaded": 0, "duplicates": 0, "failed": 0, "skipped_format": 0}

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
                overall_summary[key] += value

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
        "Starting scrape: keywords=%s, target=%d/keyword, output=%s",
        config.keywords,
        config.images_per_keyword,
        config.output_dir,
    )

    try:
        run(config)
    except KeyboardInterrupt:
        logger.info("Interrupted by user. Exiting.")
        sys.exit(1)
    except RuntimeError as exc:
        logger.error(str(exc))
        sys.exit(2)


if __name__ == "__main__":
    main()
