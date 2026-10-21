"""Génération de scènes en ligne (Cloudflare Workers AI, modèles FLUX.2), avec un quota journalier.

L'IA en ligne ne fournit que la scène : jamais de texte ni de logo, posés ensuite par le studio comme pour les
autres sources. La consigne est enrichie automatiquement (contexte local du client, zone à laisser libre pour le
texte, style photo) pour réussir l'image du premier coup.

Identifiants : .streamlit/secrets.toml (CLOUDFLARE_ACCOUNT_ID, CLOUDFLARE_API_TOKEN) ou variables d'environnement.
Réglages : section `online` de data/models.yaml. Le quota est compté en base (table online_usage), par jour UTC,
comme l'allocation gratuite de Cloudflare (remise à zéro à minuit UTC, minuit à Abidjan).
"""
import base64
import io
import json
import os
import tomllib
import urllib.error
import urllib.request
import uuid
from datetime import datetime, timezone

from PIL import Image

from .config import ROOT
from .models_manager import SourceUnavailable, settings

API = "https://api.cloudflare.com/client/v4/accounts/{account}/ai/run/{model}"
SECRETS = ROOT / ".streamlit" / "secrets.toml"
DEFAULTS = {"model": "@cf/black-forest-labs/flux-2-klein-4b", "correction_model": "@cf/black-forest-labs/flux-2-klein-9b",
            "daily_limit": 20, "area": 1024 * 1024, "timeout_s": 120}

# Contexte de scène par marché, ajouté à chaque consigne (sinon le modèle produit un décor et des personnes
# européens par défaut).
MARKET_CONTEXT = {
    "Côte d'Ivoire": "set in Abidjan, Côte d'Ivoire, West Africa; the people are Black African",
}
STYLE = ("realistic professional photograph, natural light, sharp focus, true-to-life colors; "
         "no text, no letters, no logo, no watermark, no signage")

SCHEMA = """
CREATE TABLE IF NOT EXISTS online_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    day TEXT NOT NULL,
    kind TEXT NOT NULL,
    model TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


class QuotaExceeded(SourceUnavailable):
    pass


def config() -> dict:
    try:
        return {**DEFAULTS, **(settings().get("online") or {})}
    except OSError:
        return dict(DEFAULTS)


def credentials() -> tuple[str, str] | None:
    """(identifiant de compte, jeton) ; None si la source en ligne n'est pas configurée sur ce poste."""
    account, token = os.environ.get("CLOUDFLARE_ACCOUNT_ID"), os.environ.get("CLOUDFLARE_API_TOKEN")
    if not (account and token) and SECRETS.is_file():
        try:
            data = tomllib.loads(SECRETS.read_text(encoding="utf-8"))
        except (OSError, tomllib.TOMLDecodeError):
            data = {}
        account, token = data.get("CLOUDFLARE_ACCOUNT_ID"), data.get("CLOUDFLARE_API_TOKEN")
    return (account.strip(), token.strip()) if account and token else None


def configured() -> bool:
    return credentials() is not None


# --- Quota ---------------------------------------------------------------------

def today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def used_today(conn) -> int:
    conn.executescript(SCHEMA)
    return conn.execute("SELECT COUNT(*) FROM online_usage WHERE day = ?", (today(),)).fetchone()[0]


def remaining(conn) -> int:
    return max(0, int(config()["daily_limit"]) - used_today(conn))


def check_quota(conn) -> None:
    if remaining(conn) <= 0:
        raise QuotaExceeded(f"Quota du jour atteint ({config()['daily_limit']} images en ligne). Il se renouvelle "
                            "à minuit ; d'ici là, utilisez l'IA locale, une photo ou les formes de la marque.")


def record_use(conn, kind: str, model: str) -> None:
    conn.executescript(SCHEMA)
    conn.execute("INSERT INTO online_usage (day, kind, model, created_at) VALUES (?, ?, ?, ?)",
                 (today(), kind, model, datetime.now(timezone.utc).isoformat(timespec="seconds")))


# --- Consigne -------------------------------------------------------------------

def generation_size(size, area: int | None = None) -> tuple[int, int]:
    """Taille demandée au modèle : environ un mégapixel au ratio de la zone photo, en multiples de 16."""
    area = area or config()["area"]
    ratio = size[0] / size[1]
    w, h = (area * ratio) ** 0.5, (area / ratio) ** 0.5
    return max(256, round(w / 16) * 16), max(256, round(h / 16) * 16)


def market_context(profile) -> str:
    if getattr(profile, "scene_context", None):
        return profile.scene_context
    market = profile.local_market.market if profile.local_market else None
    return MARKET_CONTEXT.get(market, "")


def build_prompt(scene_en: str, profile, zone_hint: str = "") -> str:
    parts = [scene_en.strip().rstrip("."), market_context(profile), zone_hint, STYLE]
    return ". ".join(p for p in parts if p) + "."


# --- Appel ----------------------------------------------------------------------

def _multipart(fields: dict, files: dict | None = None) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = b""
    for name, value in fields.items():
        body += f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"\r\n\r\n{value}\r\n'.encode()
    for name, data in (files or {}).items():
        body += (f'--{boundary}\r\nContent-Disposition: form-data; name="{name}"; filename="{name}.png"\r\n'
                 "Content-Type: image/png\r\n\r\n").encode() + data + b"\r\n"
    return body + f"--{boundary}--\r\n".encode(), f"multipart/form-data; boundary={boundary}"


def _explain(status: int, body: bytes) -> str:
    try:
        errors = [e.get("message", "") for e in json.loads(body).get("errors", [])]
    except ValueError:
        errors = [body[:200].decode(errors="replace")]
    text = " ; ".join(errors)
    if status in (401, 403):
        return "Identifiants Cloudflare refusés : vérifiez le jeton dans .streamlit/secrets.toml."
    if status == 429 or "neuron" in text.lower() or "allocation" in text.lower():
        return "Allocation gratuite Cloudflare du jour épuisée : elle se renouvelle à minuit."
    return f"Le service de génération en ligne a répondu une erreur (HTTP {status}) : {text}"


def generate_image(prompt: str, size, seed: int, model: str | None = None,
                   reference: Image.Image | None = None) -> Image.Image:
    """Image générée par le modèle en ligne (`reference` : image d'entrée pour une retouche)."""
    creds = credentials()
    if not creds:
        raise SourceUnavailable("Génération en ligne non configurée : identifiants Cloudflare absents de "
                                ".streamlit/secrets.toml.")
    account, token = creds
    model = model or config()["model"]
    fields = {"prompt": prompt, "width": str(size[0]), "height": str(size[1]), "seed": str(seed)}
    files = None
    if reference is not None:
        buf = io.BytesIO()
        reference.convert("RGB").save(buf, "PNG")
        files = {"input_image_0": buf.getvalue()}
    body, ctype = _multipart(fields, files)
    req = urllib.request.Request(API.format(account=account, model=model), data=body,
                                 headers={"Authorization": f"Bearer {token}", "Content-Type": ctype})
    try:
        with urllib.request.urlopen(req, timeout=config()["timeout_s"]) as r:
            payload = json.loads(r.read())
    except urllib.error.HTTPError as exc:
        raise SourceUnavailable(_explain(exc.code, exc.read())) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise SourceUnavailable("Service de génération en ligne injoignable : vérifiez la connexion internet.") from exc
    image = (payload.get("result") or {}).get("image")
    if not payload.get("success", True) or not image:
        raise SourceUnavailable(f"Réponse inattendue du service en ligne : {payload.get('errors')}")
    return Image.open(io.BytesIO(base64.b64decode(image))).convert("RGB")
