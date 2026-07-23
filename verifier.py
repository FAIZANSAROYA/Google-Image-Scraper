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
    # Prompt ensemble: CLIP was trained on caption-style text, so a bare
    # keyword under-scores valid images by 0.03-0.06. Take the best match
    # across templates - relevant images score higher, junk stays low.
    _prompts = [f"a photo of {keyword}", f"a close-up photo of {keyword}", keyword]
    text_emb = model.encode(_prompts, convert_to_tensor=True)

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
    scores = util.cos_sim(embs, text_emb).max(dim=1).values
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

def keep_top_n(folder: str, keyword: str, n: int, min_score: float = 0.25) -> dict:
    """
    Exact-count mode: rank every image by CLIP relevance to `keyword`,
    KEEP the top-n most relevant (score >= min_score), delete the rest.
    Guarantees the folder never holds more than n images, and the n kept
    are the MOST relevant ones available.
    Returns {"kept": x, "removed": y, "errors": z}.
    """
    from pathlib import Path
    model = _get_model()
    # Prompt ensemble: CLIP was trained on caption-style text, so a bare
    # keyword under-scores valid images by 0.03-0.06. Take the best match
    # across templates - relevant images score higher, junk stays low.
    _prompts = [f"a photo of {keyword}", f"a close-up photo of {keyword}", keyword]
    text_emb = model.encode(_prompts, convert_to_tensor=True)
    summary = {"kept": 0, "removed": 0, "errors": 0}
    folder_path = Path(folder)
    if not folder_path.exists():
        return summary
    extensions = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
    paths, imgs = [], []
    for img_path in folder_path.iterdir():
        if img_path.suffix.lower() not in extensions:
            continue
        try:
            with Image.open(img_path) as img:
                img.thumbnail((384, 384))
                imgs.append(img.convert("RGB").copy())
            paths.append(img_path)
        except Exception as exc:
            summary["errors"] += 1
            logger.warning("Could not open %s: %s", img_path.name, exc)
    if not paths:
        return summary
    embs = model.encode(imgs, convert_to_tensor=True, batch_size=32, show_progress_bar=False)
    scores = util.cos_sim(embs, text_emb).max(dim=1).values
    ranked = sorted(zip(paths, (float(x) for x in scores)), key=lambda t: t[1], reverse=True)
    # Safety net: if the threshold would delete EVERYTHING, relax it -
    # deleting all downloads helps nobody (target: never 0 results).
    if ranked and ranked[0][1] < min_score:
        logger.warning("All %d images below %.2f (best %.3f) - relaxing floor to 0.18",
                       len(ranked), min_score, ranked[0][1])
        min_score = 0.18
    for rank, (path, score) in enumerate(ranked):
        if rank < n and score >= min_score:
            summary["kept"] += 1
            # Prefix with rank so a plain filename/"Name A-Z" sort in the
            # gallery shows the most relevant image first, then 2nd, etc.
            new_name = f"{rank + 1:03d}_{path.name}"
            try:
                path.rename(path.with_name(new_name))
            except OSError as exc:
                logger.warning("Could not rank-rename %s: %s", path.name, exc)
        else:
            try:
                path.unlink()
                summary["removed"] += 1
                logger.info("Removed %s (rank %d, score %.3f)", path.name, rank + 1, score)
            except OSError:
                summary["errors"] += 1
    logger.info("keep_top_n(%r, n=%d): kept=%d removed=%d",
                keyword, n, summary["kept"], summary["removed"])
    return summary
