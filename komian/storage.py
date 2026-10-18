"""Import contrôlé des fichiers images."""
import io
import uuid
from pathlib import Path

from PIL import Image

from .config import (ALLOWED_UPLOAD_EXTENSIONS, ALLOWED_UPLOAD_FORMATS, DIRS, MAX_UPLOAD_BYTES,
                     MAX_UPLOAD_PIXELS, safe_path)


class ImportRejected(ValueError):
    pass


def import_image(content: bytes, filename: str, brand_id: str) -> Path:
    """Valide taille, extension et contenu réel, puis réencode l'image sous un nom unique."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_UPLOAD_EXTENSIONS:
        raise ImportRejected(f"Extension non autorisée : {ext or '(aucune)'}")
    if len(content) > MAX_UPLOAD_BYTES:
        raise ImportRejected(f"Fichier trop lourd ({len(content) // 1024} Ko)")
    try:
        with Image.open(io.BytesIO(content)) as probe:
            probe.verify()
        image = Image.open(io.BytesIO(content))
    except Exception as exc:
        raise ImportRejected(f"Contenu illisible ou corrompu : {exc}") from exc
    if image.format not in ALLOWED_UPLOAD_FORMATS:
        raise ImportRejected(f"Format réel non autorisé : {image.format}")
    if image.width * image.height > MAX_UPLOAD_PIXELS:
        raise ImportRejected("Image trop grande")

    target_dir = safe_path(DIRS["sources"], brand_id, "uploads")
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / f"{uuid.uuid4().hex}.png"
    image.convert("RGB").save(target)
    return target
