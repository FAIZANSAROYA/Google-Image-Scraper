"""
config.py
---------
Central configuration for the Openverse image downloader.

Keeping all tunables in one place makes the downloader easy to adapt
without touching the search or download logic.
"""

from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class ScraperConfig:
    # --- Search behaviour -------------------------------------------------
    keywords: list[str]
    images_per_keyword: int = 50
    regions: list[str] = field(default_factory=list)
    maximum_scraping: bool = False  # If True, scrape all available images for each keyword

    # --- Output -----------------------------------------------------------
    output_dir: Path = Path("downloaded_images")
    allowed_formats: tuple[str, ...] = ("jpg", "jpeg", "png", "webp")

    # --- Download behaviour ----------------------------------------------
    download_timeout_seconds: int = 15
    max_download_retries: int = 2
    concurrent_downloads: int = 8
    min_image_bytes: int = 1_000

    # --- Misc -------------------------------------------------------------
    request_headers: dict = field(default_factory=lambda: {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    })

    def __post_init__(self):
        self.output_dir = Path(self.output_dir)