"""
image_manager.py
----------------
Simple image library management for flat folder structures.

Reads images directly from category folders (no subdirectories, no manifests).
Provides sorting, filtering, and file operations (delete, rename, move).
"""

from __future__ import annotations

import logging
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from PIL import Image, UnidentifiedImageError

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------------- #
# Constants
# --------------------------------------------------------------------------- #

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #


@dataclass
class ImageAsset:
    """A single image file on disk."""

    id: str
    base_name: str
    category: str
    ext: str
    created_at: str
    width: int
    height: int
    bytes_full: int
    source_url: str = ""

    # Path is stored relative to category folder
    rel_path: str = ""

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "base_name": self.base_name,
            "category": self.category,
            "ext": self.ext,
            "created_at": self.created_at,
            "width": self.width,
            "height": self.height,
            "bytes_full": self.bytes_full,
            "source_url": self.source_url,
            "rel_path": self.rel_path,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ImageAsset":
        return cls(**data)


@dataclass
class ImageRecord:
    """An asset resolved to absolute paths, ready for the UI to render."""

    asset: ImageAsset
    category_dir: Path

    @property
    def id(self) -> str:
        return self.asset.id

    @property
    def category(self) -> str:
        return self.asset.category

    @property
    def created(self) -> datetime:
        try:
            return datetime.fromisoformat(self.asset.created_at)
        except (ValueError, TypeError):
            return datetime.fromtimestamp(0, tz=timezone.utc)

    @property
    def full_path(self) -> Path | None:
        if not self.asset.rel_path:
            return None
        path = self.category_dir / self.asset.rel_path
        return path if path.exists() else None

    @property
    def display_name(self) -> str:
        return f"{self.asset.base_name}.{self.asset.ext}"

    @property
    def size_bytes(self) -> int:
        return self.asset.bytes_full


# --------------------------------------------------------------------------- #
# Library
# --------------------------------------------------------------------------- #


@dataclass
class CategoryStats:
    name: str
    count: int
    bytes: int
    latest: datetime | None = field(default=None)


class ImageLibrary:
    """Reads and manages the image library on disk (flat folders)."""

    def __init__(self, root: Path | str):
        self.root = Path(root)

    # -- discovery -------------------------------------------------------- #

    def categories(self) -> list[str]:
        if not self.root.exists():
            return []
        return sorted(
            p.name for p in self.root.iterdir() if p.is_dir() and not p.name.startswith(".")
        )

    def records(self, category: str | None = None) -> list[ImageRecord]:
        """All image records, optionally scoped to one category."""
        cats = [category] if category else self.categories()
        records: list[ImageRecord] = []
        for cat in cats:
            cat_dir = self.root / cat
            if not cat_dir.is_dir():
                continue
            records.extend(self._scan_category(cat_dir, cat))
        return records

    def _scan_category(self, cat_dir: Path, category: str) -> list[ImageRecord]:
        """Scan a category folder for image files."""
        records: list[ImageRecord] = []
        for path in sorted(cat_dir.iterdir()):
            if path.is_dir() or path.suffix.lower() not in IMAGE_EXTENSIONS:
                continue
            try:
                stat = path.stat()
            except OSError:
                continue
            # NOTE: we deliberately do NOT open the image here (PIL open per
            # file made scanning very slow). Dimensions are read lazily only
            # where needed.
            rel = path.name
            asset = ImageAsset(
                id=f"{category}-{path.name}",
                base_name=path.stem,
                category=category,
                ext=path.suffix.lstrip(".").lower(),
                created_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
                width=0,
                height=0,
                bytes_full=stat.st_size,
                rel_path=rel,
            )
            records.append(ImageRecord(asset, cat_dir))
        return records

    # -- stats ------------------------------------------------------------ #

    def stats(self) -> dict:
        records = self.records()
        total_bytes = sum(r.size_bytes for r in records)
        per_cat: dict[str, CategoryStats] = {}
        for r in records:
            cs = per_cat.setdefault(r.category, CategoryStats(r.category, 0, 0))
            cs.count += 1
            cs.bytes += r.size_bytes
            if cs.latest is None or r.created > cs.latest:
                cs.latest = r.created
        recent = sorted(records, key=lambda r: r.created, reverse=True)[:8]
        return {
            "total_images": len(records),
            "total_bytes": total_bytes,
            "category_count": len(per_cat),
            "categories": sorted(per_cat.values(), key=lambda c: c.count, reverse=True),
            "recent": recent,
        }

    # -- sorting & filtering --------------------------------------------- #

    @staticmethod
    def sort(records: list[ImageRecord], key: str) -> list[ImageRecord]:
        sorters = {
            "Newest": (lambda r: r.created, True),
            "Oldest": (lambda r: r.created, False),
            "Name A–Z": (lambda r: r.display_name.lower(), False),
            "Name Z–A": (lambda r: r.display_name.lower(), True),
            "Largest": (lambda r: r.size_bytes, True),
            "Smallest": (lambda r: r.size_bytes, False),
            "Type": (lambda r: r.asset.ext, False),
        }
        fn, reverse = sorters.get(key, sorters["Newest"])
        return sorted(records, key=fn, reverse=reverse)

    @staticmethod
    def filter(
        records: list[ImageRecord],
        extension: str | None = None,
        query: str | None = None,
    ) -> list[ImageRecord]:
        out = records
        if extension and extension != "All":
            out = [r for r in out if r.asset.ext.lower() == extension.lower()]
        if query:
            q = query.lower().strip()
            out = [
                r for r in out
                if q in r.display_name.lower() or q in r.category.lower()
            ]
        return out

    def extensions(self) -> list[str]:
        exts = {r.asset.ext.lower() for r in self.records()}
        return ["All"] + sorted(exts)

    # -- mutations -------------------------------------------------------- #

    def delete(self, record: ImageRecord) -> None:
        """Delete an image file from disk."""
        if record.full_path and record.full_path.exists():
            record.full_path.unlink(missing_ok=True)

    def delete_category(self, category: str) -> None:
        cat_dir = self.root / category
        if cat_dir.is_dir():
            shutil.rmtree(cat_dir, ignore_errors=True)

    def rename(self, record: ImageRecord, new_base: str) -> bool:
        """Rename an image file."""
        new_base = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "_" for c in (new_base or "")
        ).strip().replace(" ", "_")
        if not new_base:
            return False
        if not record.full_path or not record.full_path.exists():
            return False
        new_path = record.full_path.with_name(f"{new_base}{record.full_path.suffix}")
        record.full_path.rename(new_path)
        # Update asset
        record.asset.base_name = new_base
        record.asset.rel_path = new_path.name
        return True

    def move(self, record: ImageRecord, dest_category: str) -> bool:
        """Move an image to another category folder."""
        dest_category = "".join(
            c if c.isalnum() or c in (" ", "-", "_") else "_" for c in (dest_category or "")
        ).strip().replace(" ", "_")
        if not dest_category or dest_category == record.category:
            return False
        dest_dir = self.root / dest_category
        dest_dir.mkdir(parents=True, exist_ok=True)
        if not record.full_path or not record.full_path.exists():
            return False
        dest_path = dest_dir / record.full_path.name
        shutil.move(str(record.full_path), str(dest_path))
        record.asset.category = dest_category
        record.asset.rel_path = f"{dest_category}/{record.full_path.name}"
        return True


# --------------------------------------------------------------------------- #
# Small utilities (shared with UI)
# --------------------------------------------------------------------------- #


def human_size(num_bytes: int) -> str:
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
