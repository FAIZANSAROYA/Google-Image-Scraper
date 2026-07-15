"""
verifier.py
-----------
AI-based image verification using CLIP.
Checks whether each downloaded image actually shows the keyword,
and deletes the ones that don't.
"""

import logging
from pathlib import Path

from PIL import Image
from sentence_transformers import SentenceTransformer, util

logger = logging.getLogger(__name__)

# Loaded once, reused for every keyword.
_model: SentenceTransformer | None = None


def _get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        logger.info("Loading CLIP model (first run downloads ~600MB)...")
        _model = SentenceTransformer("clip-ViT-B-32")
    return _model


def verify_folder(folder: str, keyword: str, threshold: float = 0.25) -> dict:
    """
    Scans `folder`, compares every image against `keyword` with CLIP,
    and deletes images below the similarity threshold.

    threshold guide: 0.20 = loose, 0.25 = balanced, 0.30 = strict.
    Returns {"kept": n, "removed": n, "errors": n}.
    """
    model = _get_model()
    text_emb = model.encode(keyword, convert_to_tensor=True)

    summary = {"kept": 0, "removed": 0, "errors": 0}
    folder_path = Path(folder)
    if not folder_path.exists():
        logger.warning("Folder %s does not exist; nothing to verify.", folder)
        return summary

    extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    paths, imgs = [], []
    for img_path in folder_path.iterdir():
        if img_path.suffix.lower() not in extensions:
            continue
        try:
            with Image.open(img_path) as img:
                img.thumbnail((384, 384))  # CLIP resizes to 224 anyway - decode less
                imgs.append(img.convert("RGB").copy())
            paths.append(img_path)
        except Exception as exc:
            summary["errors"] += 1
            logger.warning("Could not open %s: %s", img_path.name, exc)
    if not paths:
        return summary
    # Batch-encode all images at once — 10-20x faster than one-by-one
    embs = model.encode(imgs, convert_to_tensor=True, batch_size=32, show_progress_bar=False)
    scores = util.cos_sim(embs, text_emb).squeeze(-1)
    for img_path, score_t in zip(paths, scores):
        try:
            score = float(score_t)

            if score < threshold:
                img_path.unlink()
                summary["removed"] += 1
                logger.info("Removed %s (similarity %.3f < %.2f)", img_path.name, score, threshold)
            else:
                summary["kept"] += 1
        except Exception as exc:
            summary["errors"] += 1
            logger.warning("Could not verify %s: %s", img_path.name, exc)

    logger.info(
        "Verification for %r: kept=%d removed=%d errors=%d",
        keyword, summary["kept"], summary["removed"], summary["errors"],
    )
    return summary