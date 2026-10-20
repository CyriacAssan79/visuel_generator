"""Modèles d'IA chargés en mémoire, partagés par tout le processus (une seule application Streamlit).

Sous WSL, la puce graphique Intel puise dans la mémoire de WSL (~8 Go) : le modèle rapide (LCM), le modèle
qualité (Realistic Vision) et le vérificateur (Qwen3-VL) ne tiennent pas ensemble. Deux états alternent :
  « creation » = modèle rapide + vérificateur ; « quality » = modèle qualité + vérificateur.
Un échange coûte 40 à 100 s : il est lancé en arrière-plan (`preload`) dès que l'état suivant est prévisible,
par exemple pendant que l'utilisateur regarde le visuel qu'il vient de créer.
"""
import gc
import threading
from contextlib import contextmanager
from functools import lru_cache
from pathlib import Path

import yaml

from .config import DIRS, OV_CACHE


class SourceUnavailable(RuntimeError):
    """La source ne peut pas produire d'image sur cette machine (erreur visible, jamais masquée)."""


def settings() -> dict:
    with (DIRS["brands"].parent / "models.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f)


def model_spec(role: str) -> tuple[str, dict]:
    """Modèle tenant un rôle de la boucle : « fast », « quality » ou « verifier »."""
    data = settings()
    key = data.get("loop", {}).get(role)
    if not key or key not in data.get("models", {}):
        raise SourceUnavailable(f"Moteur IA non configuré : rôle « {role} » absent de data/models.yaml.")
    return key, data["models"][key]


@lru_cache(maxsize=1)
def openvino_devices() -> tuple[str, ...]:
    import openvino
    return tuple(openvino.Core().available_devices)


def resolve_device(requested: str) -> str:
    """Support demandé s'il est disponible ; sinon repli sur le processeur (ex. WSL sans pilote Intel)."""
    requested = requested.upper()
    return requested if requested in openvino_devices() else "CPU"


def model_dir(spec: dict) -> Path:
    """Dossier du modèle : converti sur la machine (`path`), sinon téléchargé depuis Hugging Face (`repo`)."""
    if spec.get("path"):
        path = Path(spec["path"]).expanduser()
        if not (path / "model_index.json").is_file():
            raise SourceUnavailable(f"Modèle non converti sur cette machine ({path}) : lancer "
                                    f"{spec.get('convert_script', 'le script de conversion')} sous WSL.")
        return path
    from huggingface_hub import snapshot_download
    return Path(snapshot_download(spec["repo"]))


def _genai():
    try:
        import openvino_genai
    except ImportError as exc:
        raise SourceUnavailable("OpenVINO GenAI n'est pas installé.") from exc
    return openvino_genai


def _scheduler(g, spec: dict, folder: Path, name: str | None = None):
    name = name or spec.get("scheduler")
    if not name:
        return None
    return g.Scheduler.from_config(str(folder / "scheduler" / "scheduler_config.json"),
                                   getattr(g.Scheduler.Type, name))


GPU_MEMORY_ERRORS = ("Exceeded max size of memory allocation", "ProgramBuilder build failed", "out of memory")


def is_memory_error(exc: Exception) -> bool:
    return isinstance(exc, (RuntimeError, MemoryError)) and any(m in str(exc) for m in GPU_MEMORY_ERRORS)


class ModelManager:
    """Un état chargé à la fois ; le verrou empêche un échange pendant qu'une génération l'utilise."""

    def __init__(self):
        self._lock = threading.RLock()
        self._state = None          # ("creation" | "quality", (largeur, hauteur))
        self._pipes: dict = {}
        self._verifier = None

    # --- Chargements -----------------------------------------------------------
    def _release(self):
        self._pipes.clear()
        self._state = None
        gc.collect()

    def _load_creation(self, size):
        g = _genai()
        _, spec = model_spec("fast")
        folder = model_dir(spec)
        inpaint = g.InpaintingPipeline(str(folder))
        inpaint.reshape(1, size[1], size[0], spec.get("guidance_scale", 8.0))  # formes fixes : plus rapide
        OV_CACHE.mkdir(parents=True, exist_ok=True)
        inpaint.compile(resolve_device(spec.get("device", "CPU")), CACHE_DIR=str(OV_CACHE))
        text2image = g.Text2ImagePipeline(inpaint)  # mêmes poids, déjà compilés
        self._pipes = {"inpaint": inpaint, "text2image": text2image}

    def _load_quality(self, size):
        g = _genai()
        _, spec = model_spec("quality")
        folder = model_dir(spec)
        pipe = g.Image2ImagePipeline(str(folder))
        scheduler = _scheduler(g, spec, folder)
        if scheduler:
            pipe.set_scheduler(scheduler)
        pipe.reshape(1, size[1], size[0], spec.get("guidance_scale", 7.5))
        OV_CACHE.mkdir(parents=True, exist_ok=True)
        pipe.compile(resolve_device(spec.get("device", "CPU")), CACHE_DIR=str(OV_CACHE))
        self._pipes = {"image2image": pipe}

    def _ensure(self, state: str, size):
        if self._state == (state, tuple(size)):
            return
        self._release()  # l'état précédent est libéré AVANT de charger le suivant (mémoire limitée)
        (self._load_creation if state == "creation" else self._load_quality)(tuple(size))
        self._state = (state, tuple(size))

    def _ensure_verifier(self):
        if self._verifier is None:
            g = _genai()
            _, spec = model_spec("verifier")
            OV_CACHE.mkdir(parents=True, exist_ok=True)
            self._verifier = g.VLMPipeline(str(model_dir(spec)), resolve_device(spec.get("device", "CPU")),
                                           CACHE_DIR=str(OV_CACHE))
        return self._verifier

    # --- Utilisation -------------------------------------------------------------
    @contextmanager
    def use(self, state: str, size):
        """Pipelines de l'état demandé (et le vérificateur), réservés pendant le bloc `with`."""
        with self._lock:
            try:
                verifier = self._ensure_verifier()
                self._ensure(state, size)
            except Exception as exc:
                if not is_memory_error(exc):
                    raise
                # Mémoire de la puce graphique saturée (modèles d'anciens formats non libérés) :
                # on libère tout, y compris le vérificateur, puis une seule nouvelle tentative.
                self.release_all()
                try:
                    verifier = self._ensure_verifier()
                    self._ensure(state, size)
                except Exception as retry_exc:
                    if is_memory_error(retry_exc):
                        self.release_all()
                        raise SourceUnavailable(
                            "Mémoire de la puce graphique saturée : fermez les applications gourmandes "
                            "(navigateur, Docker…) ou redémarrez le studio, puis relancez la création.") from retry_exc
                    raise
            yield {**self._pipes, "verifier": verifier}

    def preload(self, state: str, size) -> threading.Thread:
        """Prépare l'état suivant en arrière-plan ; une génération en cours garde la priorité (verrou)."""
        def work():
            try:
                with self._lock:
                    self._ensure_verifier()
                    self._ensure(state, size)
            except Exception:  # un échec de préchargement ressortira, visible, au prochain usage réel
                pass
        thread = threading.Thread(target=work, name=f"preload-{state}", daemon=True)
        thread.start()
        return thread

    def release_all(self):
        with self._lock:
            self._release()
            self._verifier = None
            gc.collect()


MANAGER = ModelManager()
