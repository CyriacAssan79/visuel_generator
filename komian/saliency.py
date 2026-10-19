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


def _raw_faces(image: Image.Image) -> np.ndarray:
    """Sortie YuNet ramenée aux coordonnées de `image` : x, y, l, h, 5 points (x, y) puis confiance."""
    import cv2
    det = _detector()
    scale = DETECT_SIZE / max(image.size)
    w, h = round(image.width * scale), round(image.height * scale)
    det.setInputSize((w, h))
    _, faces = det.detect(cv2.cvtColor(np.asarray(image.convert("RGB").resize((w, h))), cv2.COLOR_RGB2BGR))
    if faces is None:
        return np.empty((0, 15))
    faces = faces.copy()
    faces[:, :14] /= scale
    return faces


def detect_faces(image: Image.Image) -> list[tuple[int, int, int, int, float]]:
    """Visages (x0, y0, x1, y1, confiance) dans les coordonnées de `image`."""
    return [(round(f[0]), round(f[1]), round(f[0] + f[2]), round(f[1] + f[3]), round(float(f[-1]), 2))
            for f in _raw_faces(image)]


# --- Qualité du visage principal (boucle de contrôle de l'IA) ------------------
FACE_MIN_WIDTH = 48          # px dans l'image générée (~512 px) : en dessous, le visage est forcément flou
FACE_QUALITY_CONFIDENCE = 0.7
SHARPNESS_REFERENCE = 150    # variance du laplacien d'un visage net à cette taille


def face_geometry(width: float, landmarks) -> dict[str, bool]:
    """Cohérence des 5 points du visage : yeux, nez, coins de la bouche (ordre YuNet)."""
    right_eye, left_eye, nose, right_mouth, left_mouth = (np.asarray(p, dtype=float) for p in landmarks)
    eye_dist = float(np.hypot(*(left_eye - right_eye)))
    tilt = abs(float(np.degrees(np.arctan2(left_eye[1] - right_eye[1], left_eye[0] - right_eye[0]))))
    eyes_x = sorted((right_eye[0], left_eye[0]))
    return {
        "yeux à niveau": tilt < 25 or tilt > 155,
        "nez entre les yeux": eyes_x[0] - 0.2 * eye_dist <= nose[0] <= eyes_x[1] + 0.2 * eye_dist,
        "yeux, nez et bouche dans l'ordre": (right_eye[1] + left_eye[1]) / 2 < nose[1]
                                            < (right_mouth[1] + left_mouth[1]) / 2,
        "écart des yeux": 0.25 <= eye_dist / max(width, 1e-9) <= 0.65,
    }


def face_quality(image: Image.Image) -> dict | None:
    """Visage principal : géométrie, taille, netteté, confiance. None si aucun visage n'est détecté.

    Renvoie {"ok", "score" (pour classer des candidates), "width", "sharpness", "confidence", "problems"}.
    """
    import cv2
    faces = _raw_faces(image)
    if not len(faces):
        return None
    f = max(faces, key=lambda r: r[2] * r[3])
    x, y, w, h = (float(v) for v in f[:4])
    landmarks = f[4:14].reshape(5, 2)
    geometry = face_geometry(w, landmarks)
    gray = cv2.cvtColor(np.asarray(image.convert("RGB")), cv2.COLOR_RGB2GRAY)
    crop = gray[max(0, int(y)):int(y + h), max(0, int(x)):int(x + w)]
    sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var()) if crop.size else 0.0
    confidence = float(f[14])
    problems = [name for name, ok in geometry.items() if not ok]
    if w < FACE_MIN_WIDTH:
        problems.append("visage trop petit")
    if confidence < FACE_QUALITY_CONFIDENCE:
        problems.append("visage peu net ou déformé")
    score = confidence * min(1.0, w / 120) * min(1.0, sharpness / SHARPNESS_REFERENCE)
    return {"ok": not problems, "score": round(score, 3), "width": round(w), "sharpness": round(sharpness),
            "confidence": round(confidence, 2), "problems": problems}


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
