import logging
import streamlit as st
from pathlib import Path
from PIL import Image
import shutil
import os
import zipfile
import io
from datetime import datetime
import time
import threading
import sys
# Windows console uses cp1252; unicode in logged image titles crashed with
# 'charmap' codec errors. Force UTF-8 (replace what can't be encoded).
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

# Assuming these are available in your local modules
from config import ScraperConfig
from downloader import ImageDownloader
from scraper import OpenverseImageScraper
from image_manager import ImageLibrary, human_size
import importlib.util
# IMPORTANT: never import verifier at startup - it loads torch/CLIP and
# freezes the app for 1-2 minutes. We only check availability here (fast)
# and import it lazily right before verification actually runs.
VERIFIER_AVAILABLE = importlib.util.find_spec("sentence_transformers") is not None

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("image_frontend")

# ==========================
# Page Config & Theme
# ==========================
st.set_page_config(
    page_title="Image Scraper Dashboard",
    page_icon="🌌",
    layout="wide",
    initial_sidebar_state="expanded",
)

# Premium Dark Theme CSS (Linear / Vercel Deep Indigo Vibe)
st.markdown(
    """
    <style>
    :root {
        --bg-primary: #090D16;       /* Ultra-deep space blue-gray */
        --bg-sidebar: #05070F;       /* Pitch dark sidebar for depth contrast */
        --bg-card: #111827;          /* Sleek charcoal card background */
        --bg-hover: #1F2937;         /* Brightened border/hover state */
        --primary: #3B82F6;          /* Hyper Blue */
        --primary-hover: #2563EB;
        --accent: #6366F1;           /* Deep Indigo accent */
        --success: #10B981;          /* Emerald Success */
        --warning: #F59E0B;
        --error: #EF4444;
        --text-primary: #F8FAFC;     /* Off-white readable text */
        --text-secondary: #CBD5E1;   /* Cool silver subtext */
        --text-muted: #64748B;       /* Dimmed details */
        --border: #1E293B;           /* Crisp dark boundary borders */
        --shadow: 0 4px 20px rgba(0, 0, 0, 0.4);
        --shadow-hover: 0 10px 30px rgba(59, 130, 246, 0.15); /* Accent-tinted hover glow */
        --radius: 14px;
        --radius-sm: 8px;
        --transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
    }

    /* Global Overrides */
    .stApp {
        background: var(--bg-primary);
        color: var(--text-primary);
        font-family: 'Inter', 'Poppins', sans-serif;
    }

    /* Top Fixed Header with Dark Glassmorphism */
    .top-header {
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        height: 60px;
        background: rgba(5, 7, 15, 0.85);
        backdrop-filter: blur(12px);
        border-bottom: 1px solid var(--border);
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 0 2rem;
        z-index: 999999;
        box-shadow: 0 4px 30px rgba(0, 0, 0, 0.25);
    }
    
    .header-center { 
        font-size: 1.25rem; 
        font-weight: 700; 
        letter-spacing: -0.025em;
        background: linear-gradient(135deg, var(--text-primary) 30%, var(--primary) 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
    }
    .header-icons { display: flex; gap: 1.2rem; font-size: 1.2rem; color: var(--text-secondary); cursor: pointer; }
    
    .block-container {
        padding-top: 5.5rem !important; /* Proper breathing room beneath custom header */
        padding-bottom: 3rem;
        max-width: 1400px;
    }

    /* Sidebar Navigation Container */
    [data-testid="stSidebar"] {
        background: var(--bg-sidebar);
        border-right: 1px solid var(--border);
    }
    [data-testid="stSidebar"] [data-testid="stMarkdownContainer"] h3 {
        color: var(--text-primary) !important;
        font-weight: 600;
        margin-bottom: 1.5rem;
    }

    /* Premium Metric Cards */
    .metric-card {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 1.5rem;
        transition: var(--transition);
        box-shadow: var(--shadow);
    }
    .metric-card:hover {
        border-color: var(--accent);
        box-shadow: var(--shadow-hover);
        transform: translateY(-2px);
    }
    .metric-icon {
        width: 3rem; height: 3rem;
        border-radius: var(--radius-sm);
        display: flex; align-items: center; justify-content: center;
        font-size: 1.5rem; margin-bottom: 1rem;
    }
    .metric-icon.primary { background: rgba(59, 130, 246, 0.15); color: var(--primary); }
    .metric-icon.success { background: rgba(16, 185, 129, 0.15); color: var(--success); }
    .metric-icon.warning { background: rgba(245, 158, 11, 0.15); color: var(--warning); }
    .metric-icon.accent { background: rgba(99, 102, 241, 0.15); color: var(--accent); }

    .metric-value { font-size: 2rem; font-weight: 700; color: var(--text-primary); line-height: 1.2; letter-spacing: -0.03em; }
    .metric-label { font-size: 0.875rem; color: var(--text-secondary); margin-top: 0.25rem; font-weight: 500; }

    /* Streamlit Input Overrides for Unified Dark Styling */
    .stTextInput > div > div > input,
    .stNumberInput > div > div > input,
    .stSelectbox > div > div > div {
        background: #0B111E !important;
        border: 1px solid var(--border) !important;
        border-radius: var(--radius-sm) !important;
        color: var(--text-primary) !important;
    }
    .stTextInput > div > div > input::placeholder {
        color: var(--text-muted) !important;
    }

    /* Premium Custom Dark Tab Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: var(--bg-sidebar);
        padding: 6px;
        border-radius: var(--radius);
        border: 1px solid var(--border);
    }
    .stTabs [data-baseweb="tab"] {
        height: 38px;
        background-color: transparent !important;
        border-radius: var(--radius-sm);
        color: var(--text-secondary) !important;
        border: 1px solid transparent !important;
        padding: 0 20px;
        font-weight: 500;
        transition: var(--transition);
    }
    .stTabs [data-baseweb="tab"]:hover {
        background-color: var(--bg-hover) !important;
        color: var(--text-primary) !important;
    }
    .stTabs [aria-selected="true"] {
        background-color: var(--bg-card) !important;
        border-color: var(--border) !important;
        color: var(--primary) !important;
        box-shadow: var(--shadow);
    }

    /* Primary and Secondary Dark Buttons */
    .stButton > button {
        border-radius: var(--radius-sm) !important;
        font-weight: 600 !important;
        transition: var(--transition) !important;
    }
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, var(--primary) 0%, var(--accent) 100%) !important;
        border: none !important;
        color: white !important;
        box-shadow: 0 4px 14px rgba(59, 130, 246, 0.4) !important;
    }
    .stButton > button[kind="primary"]:hover {
        box-shadow: 0 6px 20px rgba(59, 130, 246, 0.6) !important;
        transform: translateY(-1px);
    }
    .stButton > button[kind="secondary"] {
        background: var(--bg-card) !important;
        border: 1px solid var(--border) !important;
        color: var(--text-primary) !important;
    }
    .stButton > button[kind="secondary"]:hover {
        background: var(--bg-hover) !important;
        border-color: var(--text-muted) !important;
    }

    /* Folder Cards HTML styling */
    .folder-card-html {
        background: var(--bg-card);
        border: 1px solid var(--border);
        border-radius: var(--radius);
        padding: 1rem 1.25rem;
        margin-bottom: 0.5rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        box-shadow: var(--shadow);
        transition: var(--transition);
    }
    .folder-card-html:hover {
        border-color: var(--accent);
    }
    .folder-meta { font-size: 0.85rem; color: var(--text-muted); font-weight: 500; }
    
    /* Elegant Dark Footer */
    .dashboard-footer {
        text-align: center; margin-top: 5rem; padding-top: 2rem;
        border-top: 1px solid var(--border); color: var(--text-muted); font-size: 0.85rem;
        letter-spacing: 0.05em;
    }

    /* ===== Gallery: uniform image cards (equal size, no stretch) ===== */
    [data-testid="stMain"] [data-testid="stImage"] img,
    section.main [data-testid="stImage"] img {
        width: 100% !important;
        height: 230px !important;
        object-fit: cover;
        border-radius: 12px;
        border: 1px solid var(--border);
        transition: var(--transition);
    }

    /* ===== Click-on-image selection: the checkbox is stretched invisibly
       over the whole image, so clicking the picture toggles selection.
       The round badge at the top-right shows the selected state. ===== */
    [data-testid="stMain"] [data-testid="stCheckbox"],
    section.main [data-testid="stCheckbox"] {
        margin-top: -246px;
        height: 230px;
        position: relative;
        z-index: 10;
    }
    [data-testid="stMain"] [data-testid="stCheckbox"] label,
    section.main [data-testid="stCheckbox"] label {
        width: 100%;
        height: 100%;
        margin: 0;
        cursor: pointer;
        align-items: flex-start;
        justify-content: flex-end;
    }
    [data-testid="stMain"] [data-testid="stCheckbox"] label > span:first-of-type,
    section.main [data-testid="stCheckbox"] label > span:first-of-type {
        margin: 10px 10px 0 0;
        width: 28px !important;
        height: 28px !important;
        border-radius: 50% !important;
        background-color: rgba(5, 7, 15, 0.6);
        border: 2px solid rgba(255, 255, 255, 0.85);
        backdrop-filter: blur(4px);
        box-shadow: 0 2px 8px rgba(0,0,0,.5);
    }

    /* Hide default Streamlit aesthetic rules */
    #MainMenu { visibility: hidden; }
    header { visibility: hidden; }
    </style>
    
    <!-- Premium Fixed Top Header Layout -->
    <div class="top-header">
        <div class="header-left" style="font-size: 1.5rem; filter: drop-shadow(0 0 8px var(--primary));">🌌</div>
        <div class="header-center">Image Scraper Dashboard</div>
        <div class="header-icons">⚙️ 🌓 👤</div>
    </div>
    """,
    unsafe_allow_html=True,
)

# ==========================
# Session State Initialization
# ==========================
if "output_dir" not in st.session_state:
    st.session_state.output_dir = "downloaded_images"
if "flash" not in st.session_state:
    st.session_state.flash = None
@st.cache_resource
def _scrape_job():
    return {"running": False, "stop": threading.Event(), "progress": 0,
            "msg": "", "flash": None, "refresh": False}

if "scraper_running" not in st.session_state:
    st.session_state.scraper_running = False
if "gallery_view_folder" not in st.session_state:
    st.session_state.gallery_view_folder = None
if "view_image_path" not in st.session_state:
    st.session_state.view_image_path = None
if "gallery_sort" not in st.session_state:
    st.session_state.gallery_sort = "Newest"
if "gallery_filter_ext" not in st.session_state:
    st.session_state.gallery_filter_ext = "All"
if "gallery_search" not in st.session_state:
    st.session_state.gallery_search = ""

# Initialize ImageLibrary
@st.cache_resource
def get_library():
    return ImageLibrary(st.session_state.output_dir)

library = get_library()

# ==========================
# Helper Functions (using ImageLibrary)
# ==========================
@st.cache_data(ttl=15, show_spinner=False)
def _snapshot(root: str):
    """One cached library scan powering stats + folder list (LCP fix)."""
    lib = ImageLibrary(root)
    recs = lib.records()
    today = datetime.now().date()
    folders = {}
    for r in recs:
        f = folders.setdefault(r.category, {"count": 0, "size": 0})
        f["count"] += 1
        f["size"] += r.size_bytes
    return {
        "total_images": len(recs),
        "storage_bytes": sum(r.size_bytes for r in recs),
        "downloaded_today": sum(1 for r in recs if r.created.astimezone().date() == today),
        "folders": folders,
    }

def get_download_stats():
    s = _snapshot(st.session_state.output_dir)
    return {
        "total_searches": len(s["folders"]),
        "total_images": s["total_images"],
        "downloaded_today": s["downloaded_today"],
        "storage_bytes": s["storage_bytes"],
    }

def get_folders():
    s = _snapshot(st.session_state.output_dir)
    out = []
    for name, f in s["folders"].items():
        cat_dir = Path(st.session_state.output_dir) / name
        created = datetime.fromtimestamp(cat_dir.stat().st_ctime).strftime("%Y-%m-%d") if cat_dir.exists() else ""
        out.append({"name": name, "path": cat_dir, "count": f["count"], "size": f["size"], "created": created})
    return sorted(out, key=lambda x: x["created"], reverse=True)

def get_images_in_folder(folder_path):
    """Get ImageRecords for a category folder using ImageLibrary."""
    category = folder_path.name
    records = library.records(category=category)
    images = []
    for record in records:
        # Use full_path for gallery display
        display_path = record.full_path
        if display_path and display_path.exists():
            stat = display_path.stat()
            images.append({
                "path": display_path,
                "name": record.display_name,
                "size": record.size_bytes,
                "modified": record.created.timestamp(),
                "record": record  # Keep reference for actions
            })
    return sorted(images, key=lambda x: x["modified"], reverse=True)

def format_bytes(bytes_val):
    return human_size(bytes_val)

@st.cache_data(show_spinner=False, max_entries=32)
def _zip_folder_bytes(folder_str: str, signature: tuple) -> bytes:
    folder = Path(folder_str)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for file_path in folder.rglob('*'):
            if file_path.is_file():
                arcname = file_path.relative_to(folder.parent)
                zip_file.write(file_path, arcname)
    return zip_buffer.getvalue()


def _folder_signature(folder_path: Path) -> tuple:
    count, mix = 0, 0.0
    for p in folder_path.rglob('*'):
        if p.is_file():
            s = p.stat()
            count += 1
            mix += s.st_mtime + s.st_size
    return (count, mix)


def create_zip_download(folder_path):
    # Cached: only re-zips when folder contents actually change.
    return _zip_folder_bytes(str(folder_path), _folder_signature(folder_path))


@st.cache_data(show_spinner=False, max_entries=2000)
def _thumb_bytes(path_str: str, mtime: float) -> bytes:
    # Cached thumbnails: gallery no longer re-opens full images every render.
    with Image.open(path_str) as im:
        im.thumbnail((320, 320))
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        buf = io.BytesIO()
        im.save(buf, "JPEG", quality=82)
        return buf.getvalue()

def delete_folder(folder_path):
    if folder_path.exists():
        shutil.rmtree(folder_path)
        _snapshot.clear()
        st.session_state.flash = f"Deleted folder: {folder_path.name}"

# ==========================
# Sidebar: Scraper Controls (Dark Sidebar Layout)
# ==========================
with st.sidebar:
    st.markdown("### 🛠️ Scraper Settings")
    
    keyword = st.text_input("Search Keyword", placeholder="Enter keyword...", key="sidebar_keyword")
    total_images = st.number_input("Total Images", min_value=1, value=100, key="sidebar_total_images")
    
    region = st.selectbox("Region", ["Global", "United States", "Pakistan", "India", "United Kingdom", "Germany", "Japan"], key="sidebar_region")
    
    
    auto_folder = f"{keyword.replace(' ', '_')}_{datetime.now().strftime('%Y')}" if keyword else ""
    folder_name = st.text_input("Folder Name", value=auto_folder, placeholder="Auto-generated if empty", key="sidebar_folder_name")
    
    st.markdown("<br/>", unsafe_allow_html=True)
    
    def _run_scrape_job(job, config, keyword, total_images, region, output_path, final_folder_name):
        """Runs in a background thread - the UI stays fully usable."""
        try:
            downloader = ImageDownloader(config)
            scraper = OpenverseImageScraper(config)
            job["msg"] = "Finding matching images..."; job["progress"] = 15
            scraper.search(keyword)
            image_results = scraper.collect_image_urls(
                keyword, total_images, region=region if region != "Global" else "")
            if job["stop"].is_set():
                job["flash"] = "Scraping stopped."; return
            job["progress"] = 45
            if not image_results:
                job["flash"] = getattr(scraper, "last_block_reason", None) or "No images found."
                return
            job["msg"] = f"Downloading {len(image_results)} files..."
            summary = downloader.download_all(
                image_results, stop_event=job["stop"],
                progress_cb=lambda d, t: job.update(
                    progress=45 + int(35 * d / max(t, 1)), msg=f"Downloading {d}/{t}..."))
            job["progress"] = 80
            job["refresh"] = True
            if job["stop"].is_set():
                job["flash"] = f"Stopped safely. {summary.get('downloaded', 0)} images saved."
                return
            if VERIFIER_AVAILABLE:
                from verifier import verify_folder  # lazy: heavy torch import
                job["msg"] = "Filtering results (threshold 0.25)..."
                v = verify_folder(str(output_path), keyword, threshold=0.25)  # primary
                kept = v["kept"]
                if kept > total_images:  # still too many -> stricter secondary pass
                    job["msg"] = "Refining results (threshold 0.27)..."
                    v = verify_folder(str(output_path), keyword, threshold=0.27)
                    kept = v["kept"]
                job["flash"] = (f"Scraped into {final_folder_name}: "
                                f"{kept} images kept after filtering.")
            else:
                job["flash"] = f"Successfully scraped {summary.get('downloaded', 0)} images into {final_folder_name}!"
            job["progress"] = 100
        except Exception as e:
            job["flash"] = f"Error: {e}"
        finally:
            job["running"] = False

    job = _scrape_job()
    if st.button("🚀 Start Scraping", type="primary", width='stretch',
                 disabled=job["running"]):
        if not keyword:
            st.error("Please enter a keyword.")
        elif not job["running"]:
            final_folder_name = folder_name if folder_name else auto_folder
            safe_folder_name = "".join(c if c.isalnum() or c in (" ", "-", "_") else "_" for c in final_folder_name).strip().replace(" ", "_")
            output_path = Path(st.session_state.output_dir) / safe_folder_name
            config = ScraperConfig(
                keywords=[keyword],
                images_per_keyword=total_images,
                regions=[region] if region != "Global" else [],
                output_dir=str(output_path),
                concurrent_downloads=24,
            )
            job.update(running=True, progress=5, msg="Starting...", flash=None)
            job["stop"] = threading.Event()
            threading.Thread(
                target=_run_scrape_job,
                args=(job, config, keyword, total_images, region, output_path, final_folder_name),
                daemon=True,
            ).start()
            st.rerun()

    @st.fragment(run_every=2)
    def _scrape_status():
        job = _scrape_job()
        if job["running"]:
            st.progress(min(int(job.get("progress", 0)), 100))
            st.caption(job.get("msg") or "Working...")
            if st.button("🛑 Stop Scraping", width='stretch', key="stop_scrape_btn"):
                job["stop"].set()
                st.caption("Stopping safely — finishing current files...")
        else:
            if job.get("refresh"):
                job["refresh"] = False
                _snapshot.clear()
                # full-app rerun so the new folder shows up instantly
                st.rerun(scope="app")
            if job.get("flash"):
                st.success(job["flash"])
            st.caption("Status: **Ready**")

    _scrape_status()

# ==========================
# Main Dashboard Panel
# ==========================
if st.session_state.flash:
    st.toast(st.session_state.flash, icon="⚡")
    st.session_state.flash = None

if st.session_state.pop("_goto_gallery", False):
    st.session_state.active_view = "🖼️ Gallery View"
_view = st.radio("View", ["📊 Main Dashboard", "🖼️ Gallery View"],
                 horizontal=True, label_visibility="collapsed", key="active_view")
class _V:
    def __init__(self, name): self.name = name
    def __enter__(self): return self
    def __exit__(self, *a): return False
tab1, tab2 = _V("📊 Main Dashboard"), _V("🖼️ Gallery View")

# --- TAB 1: DASHBOARD ---
if _view == tab1.name:
    stats = get_download_stats()
    
    # Top Stats Row
    col1, col2, col3, col4 = st.columns(4)
    with col1:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-icon primary">🔍</div>
            <div class="metric-value">{stats['total_searches']}</div>
            <div class="metric-label">Total Searches</div>
        </div>
        """, unsafe_allow_html=True)
    with col2:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-icon accent">🖼️</div>
            <div class="metric-value">{stats['total_images']}</div>
            <div class="metric-label">Total Images</div>
        </div>
        """, unsafe_allow_html=True)
    with col3:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-icon success">📥</div>
            <div class="metric-value">{stats['downloaded_today']}</div>
            <div class="metric-label">Downloaded Today</div>
        </div>
        """, unsafe_allow_html=True)
    with col4:
        st.markdown(f"""
        <div class="metric-card">
            <div class="metric-icon warning">💾</div>
            <div class="metric-value">{format_bytes(stats['storage_bytes'])}</div>
            <div class="metric-label">Storage Used</div>
        </div>
        """, unsafe_allow_html=True)

    st.markdown("<br/><h3>📁 Folder Management Area</h3>", unsafe_allow_html=True)
    
    folders = get_folders()
    
    if not folders:
        st.markdown("""
        <div style="text-align: center; padding: 5rem 0; color: var(--text-muted); background: var(--bg-card); border-radius: var(--radius); border: 1px solid var(--border);">
            <div style="font-size: 4rem; opacity: 0.3; filter: drop-shadow(0 0 10px var(--border));">📭</div>
            <h3 style="color: var(--text-secondary); margin-top: 1rem;">No scraped images yet.</h3>
            <p style="font-size: 0.9rem;">Fill in the sidebar properties on the left and run your first scraper.</p>
        </div>
        """, unsafe_allow_html=True)
    else:
        # Loop over discovered Image Folders
        for folder in folders:
            with st.container():
                st.markdown(f"""
                <div class="folder-card-html">
                    <div style="display: flex; align-items: center; gap: 1rem;">
                        <div style="font-size: 2rem; background: rgba(59, 130, 246, 0.1); padding: 0.5rem; border-radius: var(--radius-sm); border: 1px solid rgba(59, 130, 246, 0.2);">📂</div>
                        <div>
                            <div style="font-weight: 600; font-size: 1.1rem; color: var(--text-primary);">{folder['name']}</div>
                            <div class="folder-meta">{folder['count']} Images • Created: {folder['created']} • size: {format_bytes(folder['size'])}</div>
                        </div>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Interactive Native Column Control buttons beneath the design template
                btn_col1, btn_col2, btn_col3, _ = st.columns([2, 2, 2, 8])
                with btn_col1:
                    if st.button("👁️ View Folder", key=f"view_{folder['name']}", width='stretch'):
                        st.session_state.gallery_view_folder = folder['path']
                        st.session_state._goto_gallery = True
                        st.session_state.pop("gallery_page", None)
                        st.rerun()
                with btn_col2:
                    # Lazy ZIP: building every folder's ZIP on page load froze
                    # startup. Now it's built only after the user asks for it.
                    zip_flag = f"zip_ready_{folder['name']}"
                    if st.session_state.get(zip_flag):
                        st.download_button(
                            label="💾 Save ZIP",
                            data=create_zip_download(folder['path']),
                            file_name=f"{folder['name']}.zip",
                            mime="application/zip",
                            key=f"dl_{folder['name']}",
                            width='stretch'
                        )
                    elif st.button("📦 Download ZIP", key=f"zip_prep_{folder['name']}", width='stretch'):
                        with st.spinner("Preparing ZIP..."):
                            create_zip_download(folder['path'])  # warms the cache
                        st.session_state[zip_flag] = True
                        st.rerun()
                with btn_col3:
                    if st.button("🗑️ Delete Folder", key=f"del_{folder['name']}", type="secondary", width='stretch'):
                        delete_folder(folder['path'])
                        st.rerun()
            st.markdown("<hr style='margin: 0.25rem 0; opacity: 0.1; border-color: var(--border);'/>", unsafe_allow_html=True)


# --- TAB 2: GALLERY VIEW ---
if _view == tab2.name:
    if not st.session_state.gallery_view_folder:
        st.info("💡 Go back to the **Main Dashboard** tab and click 'View Folder' to visualize the images in this space.")
    else:
        folder_path = st.session_state.gallery_view_folder
        if not folder_path.exists():
            st.session_state.gallery_view_folder = None
            st.rerun()
            
        st.markdown(f"### 📂 Gallery Explorer: `{folder_path.name}`")
        if st.button("⬅️ Back to Folders", key="back_to_folders"):
            st.session_state.gallery_view_folder = None
            st.rerun()
        
        # Sort & Filter Controls
        filter_col1, filter_col2, filter_col3, filter_col4 = st.columns([2, 2, 2, 6])
        with filter_col1:
            sort_by = st.selectbox("Sort by", ["Newest", "Oldest", "Name A–Z", "Name Z–A", "Largest", "Smallest", "Type"], key="gallery_sort_select")
        with filter_col2:
            ext_filter = st.selectbox("Format", ["All", "jpg", "jpeg", "png", "webp", "gif"], key="gallery_ext_filter")
        with filter_col3:
            search_query = st.text_input("Search", placeholder="Filter by name...", key="gallery_search_input")
        
        images = get_images_in_folder(folder_path)
        
        # Apply filters
        if ext_filter != "All":
            images = [img for img in images if img['path'].suffix.lower().lstrip('.') == ext_filter.lower()]
        if search_query:
            q = search_query.lower().strip()
            images = [img for img in images if q in img['name'].lower()]
        
        # Apply sort
        def sort_key(img):
            if sort_by == "Newest":
                return -img['modified']
            elif sort_by == "Oldest":
                return img['modified']
            elif sort_by == "Name A–Z":
                return img['name'].lower()
            elif sort_by == "Name Z–A":
                return img['name'].lower()
            elif sort_by == "Largest":
                return -img['size']
            elif sort_by == "Smallest":
                return img['size']
            elif sort_by == "Type":
                return img['path'].suffix.lower()
            return -img['modified']
        
        reverse = sort_by in ["Name Z–A", "Largest"]
        images.sort(key=sort_key, reverse=reverse)
        
        if not images:
            st.warning("This folder is currently empty or no images match your filters.")
        else:
            PAGE = 40
            total = len(images)
            pages = max(1, (total + PAGE - 1) // PAGE)
            pg = min(int(st.session_state.get("gallery_page", 1)), pages)
            images = images[(pg - 1) * PAGE: pg * PAGE]
            st.caption(f"Showing {len(images)} of {total} image(s) — page {pg}/{pages}")

            # --- Selection toolbar: pick images and download them in the browser ---
            selected_paths = [
                img['path'] for img in images
                if st.session_state.get(f"sel_{img['path']}")
            ]
            tb1, tb2, tb3, _tb4 = st.columns([2, 2, 4, 4])
            with tb1:
                if st.button("☑️ Select All", key="sel_all_btn", width='stretch'):
                    for img in images:
                        st.session_state[f"sel_{img['path']}"] = True
                    st.rerun()
            with tb2:
                if st.button("✖️ Clear", key="sel_clear_btn", width='stretch'):
                    for img in images:
                        st.session_state[f"sel_{img['path']}"] = False
                    st.rerun()
            with tb3:
                if selected_paths:
                    _sel_buf = io.BytesIO()
                    with zipfile.ZipFile(_sel_buf, 'w', zipfile.ZIP_DEFLATED) as _zf:
                        for _p in selected_paths:
                            if _p.exists():
                                _zf.write(_p, _p.name)
                    st.download_button(
                        f"⬇️ Download Selected ({len(selected_paths)})",
                        data=_sel_buf.getvalue(),
                        file_name=f"{folder_path.name}_selected.zip",
                        mime="application/zip",
                        key="dl_selected",
                        type="primary",
                        width='stretch',
                    )
                else:
                    st.caption("Click on a picture to select it, then download or delete together.")
            with _tb4:
                if selected_paths and st.button(
                    f"🗑️ Delete Selected ({len(selected_paths)})",
                    key="del_selected_btn",
                    width='stretch',
                ):
                    _rec_by_path = {img['path']: img.get('record') for img in images}
                    for _p in selected_paths:
                        _rec = _rec_by_path.get(_p)
                        if _rec:
                            library.delete(_rec)
                        elif _p.exists():
                            _p.unlink()
                        st.session_state.pop(f"sel_{_p}", None)
                    st.toast(f"Deleted {len(selected_paths)} image(s)")
                    st.rerun()
            # 4-Column Photo Grid
            cols = st.columns(4)
            for idx, img in enumerate(images):
                with cols[idx % 4]:
                    try:
                        st.image(_thumb_bytes(str(img['path']), img['path'].stat().st_mtime), width='stretch')
                        st.checkbox("select", key=f"sel_{img['path']}", label_visibility="collapsed")
                        st.caption(f"**{img['name']}**")
                        st.caption(f"Size: {format_bytes(img['size'])}")
                    except Exception as e:
                        st.warning(f"Could not display {img['name']}: {str(e)}")
            if pages > 1:
                st.divider()
                _pg1, _pg2, _ = st.columns([2, 3, 7])
                with _pg1:
                    st.number_input("Page", 1, pages, pg, key="gallery_page")
                with _pg2:
                    st.caption(f"Page {pg} of {pages} — {total} images total")


# ==========================
# Footer (Dark Styling)
# ==========================
st.markdown("""
<div class="dashboard-footer">
    <strong>Image Scraper Dashboard</strong> - Version 1.0 <br/>
    System Status: Operational • Database Instance: Local SQLite
</div>
""", unsafe_allow_html=True)