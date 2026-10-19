"""Chemins contrôlés et paramètres globaux."""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DATA = ROOT / "data"

DIRS = {
    "sources": DATA / "sources",            # chartes et fichiers importés
    "brands": DATA / "brands",              # profils et ressources de marque
    "tmp": DATA / "renders" / "tmp",        # rendus en cours
    "scenes": DATA / "renders" / "scenes",  # scènes IA à la taille générée (départ du passage en qualité)
    "pending": DATA / "renders" / "pending",  # rendus en attente de validation
    "approved": DATA / "exports" / "approved",  # exports approuvés
    "db": DATA / "db",
}
DB_PATH = DIRS["db"] / "komian.sqlite3"

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
MAX_UPLOAD_PIXELS = 8000 * 8000
ALLOWED_UPLOAD_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp"}
ALLOWED_UPLOAD_FORMATS = {"JPEG", "PNG", "WEBP"}

# Formats de sortie disponibles (largeur, hauteur)
FORMATS = {
    "post_carre": (1440, 1440),
    "post_portrait": (1080, 1350),
    "story": (1080, 1920),
}


def ensure_dirs() -> None:
    for d in DIRS.values():
        d.mkdir(parents=True, exist_ok=True)


PROJECT_MARKER = "generation_de_visuel/"
# Cache de compilation OpenVINO : propre à chaque système (Windows / WSL), donc hors du projet partagé.
OV_CACHE = Path.home() / ".cache" / "komian" / "ov_cache"


def to_stored(path) -> str:
    """Chemin enregistré en base : relatif au projet, pour fonctionner sous Windows comme sous WSL."""
    path = Path(path).resolve()
    try:
        return path.relative_to(ROOT.resolve()).as_posix()
    except ValueError:  # hors du projet (ex. répertoires temporaires des tests)
        return path.as_posix()


def from_stored(value) -> Path | None:
    """Chemin réel à partir de la base, y compris les anciens chemins absolus Windows (C:\...)."""
    if not value:
        return None
    text = str(value).replace("\\", "/")
    is_absolute = text.startswith("/") or (len(text) > 1 and text[1] == ":")
    if not is_absolute:
        return ROOT / text
    if PROJECT_MARKER in text:  # ancien chemin absolu vers ce projet, sur une autre plateforme
        return ROOT / text.split(PROJECT_MARKER, 1)[1]
    return Path(text)


def safe_path(base: Path, *parts: str) -> Path:
    """Résout un chemin et refuse toute sortie du répertoire autorisé."""
    base = base.resolve()
    target = base.joinpath(*parts).resolve()
    if not target.is_relative_to(base):
        raise ValueError(f"Chemin refusé hors de {base.name}: {'/'.join(parts)}")
    return target
