"""Chargement des profils de marque et accès aux ressources."""
import hashlib
from pathlib import Path

import yaml
from PIL import Image

from .config import DIRS, safe_path
from .models import BrandProfile


def list_brands() -> list[str]:
    return sorted(p.parent.name for p in DIRS["brands"].glob("*/profile.yaml"))


def load_profile(brand_id: str) -> BrandProfile:
    path = safe_path(DIRS["brands"], brand_id, "profile.yaml")
    with path.open(encoding="utf-8") as f:
        profile = BrandProfile.model_validate(yaml.safe_load(f))
    ensure_derived_assets(profile)
    return profile


def asset_path(profile: BrandProfile, relative: str) -> Path:
    return safe_path(DIRS["brands"], profile.brand_id, relative)


def file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def missing_assets(profile: BrandProfile) -> list[str]:
    files = [logo.file for logo in profile.logos] + list(profile.fonts.values())
    return [f for f in files if not asset_path(profile, f).is_file()]


def derive_white_logo(source: Path, target: Path) -> None:
    """Passe en blanc les pixels à dominante rouge ; conserve le point vert."""
    logo = Image.open(source).convert("RGBA")
    pixels = logo.load()
    for y in range(logo.height):
        for x in range(logo.width):
            r, g, b, a = pixels[x, y]
            if a and r > g:
                pixels[x, y] = (255, 255, 255, a)
    logo.save(target)


def ensure_derived_assets(profile: BrandProfile) -> None:
    if profile.brand_id != "mr_bricolage":
        return
    white = asset_path(profile, profile.logo("blanc_derive").file)
    red = asset_path(profile, profile.logo("officiel_rouge").file)
    if not white.exists() and red.exists():
        derive_white_logo(red, white)
