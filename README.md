# 🎞️ Image Studio

A keyword image scraper with a premium Streamlit UI, an automatic
image-processing pipeline, and a full library manager (browse, sort,
filter, preview, rename, move, delete).

## Requirements

- Python 3.10+
- `pip install -r requirements.txt`

## Run the app

```bash
streamlit run app.py
```

Then use the sidebar to set keywords, image count, regions, and workers,
and press **Run scraper**. Browse everything in the **Dashboard** and
**Gallery** tabs.

## What happens to each image

Every downloaded image is validated and processed into a derivative set,
recorded in a per-category `_manifest.json`:

```
downloaded_images/
└── red_car/
    ├── _manifest.json
    ├── originals/   <uuid>_<timestamp>.jpg   (untouched backup)
    ├── full/        <uuid>_<timestamp>.jpg   (optimized, <=2560px)
    ├── medium/      <uuid>_<timestamp>.jpg   (<=800px, gallery/preview)
    ├── thumbs/      <uuid>_<timestamp>.jpg   (200x200 cover-cropped)
    └── webp/        <uuid>_<timestamp>.webp  (WebP of the full image)
```

- **Unique names** — `uuid + timestamp`, collision-free and sortable.
- **Deduplication** — identical bytes (SHA-256) are skipped per keyword.
- **Format safety** — JPEG targets flatten transparency; PNG/WebP keep alpha.
- **EXIF orientation** honored so nothing shows up sideways.

## Modules

| File | Responsibility |
|---|---|
| `app.py` | Streamlit UI: dashboard, gallery, scrape flow, preview modal |
| `ui_components.py` | Theme (exact palette), CSS, reusable render helpers |
| `image_manager.py` | `ImageProcessor` (pipeline) + `ImageLibrary` (scan/sort/filter/rename/move/delete) |
| `downloader.py` | Concurrent download + dedup, runs each image through the pipeline |
| `scraper.py` | DuckDuckGo image search (no API key) |
| `config.py` | `ScraperConfig` — scrape + pipeline settings |
| `main.py` | Optional CLI entry point |
| `verifier.py` | Optional CLIP-based relevance verification (CLI only) |

## UI features

- **Dashboard** — total images, storage used, category count, recent uploads.
- **Gallery** — responsive equal-size cards (`object-fit: cover`, lazy-loaded),
  sort by newest/oldest/name/size/type, filter by category and extension, search.
- **Preview modal** — zoom in/out, download, open source, copy paths,
  rename, move to another category, delete.
- **Theme** — premium dark palette (#2563EB / #7C3AED / #06B6D4 on #0F172A),
  soft shadows, hover motion, skeleton loaders, empty states, responsive down
  to mobile, reduced-motion respected.

## Notes & limitations

- **Legacy folders.** Older loose-image folders (no manifest) are still shown
  in the gallery via a filesystem fallback, but rename/move are disabled for them.
- **CLI verification.** `main.py --verify` uses CLIP on the *top level* of a
  category folder. Since processed images now live in subfolders, verification
  is effectively a no-op for new runs; use the app for management instead.
- **Copyright.** Scraped images may be copyrighted — use for personal,
  research, or fair-use scenarios and respect source licenses.
