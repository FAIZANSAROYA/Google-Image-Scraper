from dataclasses import dataclass, field
from pathlib import Path
from typing import List

@dataclass
class ScraperConfig:
    # --- REQUIRED: Ye wo arguments hain jo app.py se aate hain ---
    keywords: List[str]
    concurrent_downloads: int

    # --- OPTIONAL/SETTINGS: Ye settings fix hain ---
   # serpapi_key: str = "2e5bda6aed110a89dc4d4e98f2e3454634618db216152967c90513e15fddb4c1"
    images_per_keyword: int = 50
    regions: List[str] = field(default_factory=list)
    maximum_scraping: bool = True
    similarity_specificity_margin: float = 0.02
    min_candidates: int = 150
    similarity_relative_margin: float = 0.15
    similarity_threshold: float = 0.22
    max_query_variants: int = 20
    
    # --- Output ---
    output_dir: Path = Path("downloaded_images")
    allowed_formats: tuple = ("jpg", "jpeg", "png", "webp")

    # --- Download behaviour ---
    download_timeout_seconds: int = 15
    max_download_retries: int = 2
    min_image_bytes: int = 1_000

    # --- Misc ---
    request_headers: dict = field(default_factory=lambda: {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
        )
    })

    def __post_init__(self):
        # Path string ko actual Path object mein convert karna
        if isinstance(self.output_dir, str):
            self.output_dir = Path(self.output_dir)