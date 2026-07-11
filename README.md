# Openverse Image Downloader

A modular, keyword-based image downloader built on the Openverse API.

## Requirements

- Python 3.10+
- `pip install -r requirements.txt`

## Usage

```bash
python main.py --keywords "red panda" "golden retriever" --count 40
```

Options:

| Flag | Description | Default |
|---|---|---|
| `--keywords` | One or more search terms (space-separated, quote multi-word terms) | required |
| `--count` | Target number of images per keyword | 50 |
| `--output` | Root output directory | `downloaded_images` |
| `--formats` | Allowed image formats | jpg jpeg png webp |
| `--concurrent-downloads` | Parallel download workers | 8 |

## Output structure

```
downloaded_images/
├── red_panda/
│   ├── 3f9c1a2b7d4e5f6a.jpg
│   └── ...
└── golden_retriever/
    ├── 8a1b2c3d4e5f6789.png
    └── ...
```

Files are named by a hash of their content, which is also how duplicates
are detected and skipped (two identical images always map to the same
hash, regardless of which URL they came from).

## How it works

1. **`scraper.py`** queries Openverse for a keyword and returns
  downloadable image URLs from the API response.
2. **`downloader.py`** downloads candidate URLs concurrently, validates
   that the bytes are actually a real image in an allowed format,
   hashes the content to skip duplicates, and writes to
   `<output>/<keyword>/<hash>.<ext>`.
3. **`main.py`** wires it together per keyword and keeps going even if
   one keyword or one image fails.

## Notes and limitations

- **Rate limiting.** Openverse is a shared public API; if requests slow
  down or fail, reduce concurrency or request count.
- **Terms of Service / copyright.** Scraped images may be copyrighted.
  This tool is meant for personal, research, or fair-use scenarios —
  make sure your use case complies with Openverse source licenses and
  applicable copyright law before redistributing or using images
  commercially.
- **Full-resolution extraction is best-effort.** Openverse returns a
  direct image URL and, when available, a foreign landing page URL for
  attribution or inspection.
