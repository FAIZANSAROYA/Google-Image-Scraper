import logging
import streamlit as st
from pathlib import Path
from PIL import Image
import shutil

from config import ScraperConfig
from downloader import ImageDownloader
from scraper import OpenverseImageScraper

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("image_frontend")

st.set_page_config(
    page_title="Image Scraper",
    page_icon="🖼️",
    layout="wide",
)

st.markdown(
    """
    <style>
      .block-container {
          padding-top: 2rem;
          padding-bottom: 2rem;
      }

      .hero {
          padding: 2rem;
          border-radius: 24px;
          background: linear-gradient(135deg, #0f172a 0%, #1e293b 55%, #334155 100%);
          color: white;
          box-shadow: 0 20px 60px rgba(15, 23, 42, 0.28);
          margin-bottom: 1.5rem;
      }

      .hero h1 {
          margin: 0;
          font-size: 2.3rem;
      }

      .hero p {
          margin: 0.5rem 0 0;
          opacity: 0.85;
      }

      .card {
          padding: 1rem 1.2rem;
          border: 1px solid rgba(148, 163, 184, 0.25);
          border-radius: 18px;
          background: white;
          box-shadow: 0 10px 30px rgba(15, 23, 42, 0.06);
      }

      .muted {
          color: #64748b;
          font-size: 0.95rem;
      }
    </style>
    """,
    unsafe_allow_html=True,
)

st.markdown(
    """
    <div class="hero">
        <h1>Image Scraper</h1>
        <p>Search keywords, collect image URLs, and download results into folders.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

# ==========================
# Sidebar
# ==========================
with st.sidebar:
    st.header("Controls")

    keywords_text = st.text_input(
        "Keywords",
        value="BMW CAR"
    )

    count = st.slider(
        "Images per keyword",
        min_value=1,
        max_value=50,
        value=4,
    )

    output_dir = st.text_input(
        "Output folder",
        value="downloaded_images",
    )

    # NEW : Multiple Region Filter
    regions = st.multiselect(
        "Regions",
        [
            "USA",
            "Pakistan",
            "Africa",
            "India",
            "UK",
            "Canada",
            "Australia",
            "Germany",
            "France",
            "Italy",
            "Spain",
            "Japan",
            "China",
            "Brazil",
            "Mexico",
            "Russia",
            "Turkey",
            "UAE",
            "Saudi Arabia",
        ],
    )

    concurrent_downloads = st.slider(
        "Download workers",
        min_value=1,
        max_value=16,
        value=8,
    )

    
    run_button = st.button(
        "Run scraper",
        type="primary",
    )

# ==========================
# Main Area
# ==========================

st.markdown('<div class="card">', unsafe_allow_html=True)

st.subheader("Run Status")

status_placeholder = st.empty()
results_placeholder = st.empty()

st.markdown("</div>", unsafe_allow_html=True)

# ==========================
# Run
# ==========================

if run_button:

    keywords = [
        item.strip()
        for item in keywords_text.split(",")
        if item.strip()
    ]

    if not keywords:
        st.error("Enter at least one keyword.")
        st.stop()

    config = ScraperConfig(
        keywords=keywords,
        images_per_keyword=count,
        regions=regions,              # NEW
        output_dir=output_dir,
        concurrent_downloads=concurrent_downloads,
    )

    downloader = ImageDownloader(config)
    scraper = OpenverseImageScraper(config)
    

    overall_summary = {
        "downloaded": 0,
        "duplicates": 0,
        "failed": 0,
        "skipped_format": 0,
    }

    keyword_rows = []

    for keyword in config.keywords:

        status_placeholder.info(f"Scraping '{keyword}'...")

        scraper.search(keyword)

        image_results = scraper.collect_image_urls(
            keyword,
            config.images_per_keyword,
        )

        summary = (
            downloader.download_all(image_results)
            if image_results
            else {
                "downloaded": 0,
                "duplicates": 0,
                "failed": 0,
                "skipped_format": 0,
            }
        )

        for key, value in summary.items():
            overall_summary[key] += value

        keyword_rows.append(
            {
                "Keyword": keyword,
                "Regions": ", ".join(regions) if regions else "All",
                "Found": len(image_results),
                "Downloaded": summary["downloaded"],
                "Duplicates": summary["duplicates"],
                "Failed": summary["failed"],
                "Skipped": summary["skipped_format"],
            }
        )

        block_reason = getattr(scraper, "last_block_reason", None)

        if not image_results and block_reason:
            st.warning(block_reason)

    status_placeholder.success("Done")

    results_placeholder.write(
        {
            "output_dir": str(config.output_dir),
            "regions": regions if regions else "All",
            "summary": overall_summary,
        }
    )

    st.dataframe(
        keyword_rows,
        use_container_width=True,
    )

st.caption("Tip: Enter multiple keywords separated by commas.")

# ==========================================
# Downloaded Images Viewer
# ==========================================

st.markdown("---")

if "show_downloads" not in st.session_state:
    st.session_state.show_downloads = False

if "flash" not in st.session_state:
    st.session_state.flash = None

if st.button("📁 Downloaded Images"):
    st.session_state.show_downloads = not st.session_state.show_downloads

if st.session_state.flash:
    st.toast(st.session_state.flash)
    st.session_state.flash = None

if st.session_state.show_downloads:

    root_folder = Path(output_dir)

    if not root_folder.exists():
        st.error("Download folder not found.")

    else:

        category_folders = [
            folder
            for folder in root_folder.iterdir()
            if folder.is_dir()
        ]

        if not category_folders:
            st.info("No downloaded images found.")

        else:

            st.success(f"{len(category_folders)} Categories Found")

            for folder in sorted(category_folders):

                image_files = []

                for ext in ("*.jpg", "*.jpeg", "*.png", "*.webp"):
                    image_files.extend(folder.glob(ext))

                header_col, delete_col = st.columns([4, 1])

                with header_col:
                    st.subheader(f"📂 {folder.name} ({len(image_files)})")

                with delete_col:
                    if image_files and st.button("🗑️ Delete all", key=f"del_cat_{folder.name}"):
                        shutil.rmtree(folder)
                        st.session_state.flash = f"Deleted category '{folder.name}'."
                        st.rerun()

                if not image_files:
                    st.write("No images found.")
                    st.markdown("---")
                    continue

                cols = st.columns(4)

                for index, image in enumerate(image_files):

                    with cols[index % 4]:
                        st.image(
                            str(image),
                            caption=image.name,
                            use_container_width=True,
                        )

                        if st.button("🗑️ Delete", key=f"del_{folder.name}_{image.name}"):
                            image.unlink(missing_ok=True)
                            st.session_state.flash = f"Deleted '{image.name}'."
                            st.rerun()

                st.markdown("---")