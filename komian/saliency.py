"""Carte de saillance (méthode « spectral residual », Hou & Zhang 2007).

Repère ce qui attire l'œil (visage, sujet principal) pour éviter d'y poser le message.
Heuristique : elle classe les dispositions, elle ne garantit pas que le sujet est dégagé.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np
from PIL import Image, ImageFilter

WORK_SIZE = 64


def saliency_map(image: Image.Image, size: tuple[int, int]) -> np.ndarray:
    """Saillance normalisée [0, 1] à la taille `size` (largeur, hauteur)."""
    small = np.asarray(image.convert("L").resize((WORK_SIZE, WORK_SIZE), Image.Resampling.BILINEAR), dtype=float)
    spectrum = np.fft.fft2(small)
    log_amp = np.log(np.abs(spectrum) + 1e-9)
    phase = np.angle(spectrum)
    k = 3
    kernel = np.ones((k, k)) / (k * k)
    padded = np.pad(log_amp, k // 2, mode="edge")
    avg = sum(padded[i:i + WORK_SIZE, j:j + WORK_SIZE] * kernel[i, j] for i in range(k) for j in range(k))
    sal = np.abs(np.fft.ifft2(np.exp(log_amp - avg + 1j * phase))) ** 2
    img = Image.fromarray((sal / sal.max() * 255).astype(np.uint8)).filter(ImageFilter.GaussianBlur(2.5))
    out = np.asarray(img.resize(size, Image.Resampling.BILINEAR), dtype=float)
    return out / max(out.max(), 1e-9)


def covered_saliency(sal: np.ndarray, box) -> float:
    """Part de la saillance totale recouverte par la zone `box` (x0, y0, x1, y1)."""
    x0, y0, x1, y1 = (int(v) for v in box)
    return float(sal[max(y0, 0):y1, max(x0, 0):x1].sum() / max(sal.sum(), 1e-9))


# --- Visages (YuNet, OpenCV) --------------------------------------------------
FACE_MODEL = Path(__file__).resolve().parent.parent / "data" / "models" / "face_detection_yunet_2023mar.onnx"
FACE_MIN_CONFIDENCE = 0.6
DETECT_SIZE = 720


class FaceDetectionUnavailable(RuntimeError):
    pass


@lru_cache(maxsize=1)
def _detector():
    try:
        import cv2
    except ImportError as exc:
        raise FaceDetectionUnavailable("OpenCV n'est pas installé.") from exc
    if not FACE_MODEL.is_file():
        raise FaceDetectionUnavailable(f"Modèle de détection absent : {FACE_MODEL.name}")
    return cv2.FaceDetectorYN.create(str(FACE_MODEL), "", (DETECT_SIZE, DETECT_SIZE), FACE_MIN_CONFIDENCE)


def detect_faces(image: Image.Image) -> list[tuple[int, int, int, int, float]]:
    """Visages (x0, y0, x1, y1, confiance) dans les coordonnées de `image`."""
    import cv2
    det = _detector()
    scale = DETECT_SIZE / max(image.size)
    w, h = round(image.width * scale), round(image.height * scale)
    det.setInputSize((w, h))
    _, faces = det.detect(cv2.cvtColor(np.asarray(image.convert("RGB").resize((w, h))), cv2.COLOR_RGB2BGR))
    if faces is None:
        return []
    return [(round(f[0] / scale), round(f[1] / scale), round((f[0] + f[2]) / scale), round((f[1] + f[3]) / scale),
             round(float(f[-1]), 2)) for f in faces]


def faces_on_canvas(background: Image.Image, layers: list[dict]) -> list[tuple[int, int, int, int, float]]:
    """Ramène les visages du fond dans les coordonnées du visuel (le fond peut être décalé, ex. titre en haut)."""
    box = next((l["box"] for l in layers if l.get("kind") == "background"), [0, 0, *background.size])
    sx, sy = box[2] / background.width, box[3] / background.height
    return [(round(x0 * sx + box[0]), round(y0 * sy + box[1]), round(x1 * sx + box[0]), round(y1 * sy + box[1]), c)
            for x0, y0, x1, y1, c in detect_faces(background)]


def face_overlap(face, box) -> float:
    """Part de la surface du visage recouverte par `box`."""
    ix = max(0, min(face[2], box[2]) - max(face[0], box[0]))
    iy = max(0, min(face[3], box[3]) - max(face[1], box[1]))
    return ix * iy / max(1, (face[2] - face[0]) * (face[3] - face[1]))
