"""Habillage de l'interface Streamlit aux couleurs de KÔMIAN (charte v1.0, maquette « KÔMIAN Studio »).

Le studio porte la charte KÔMIAN quel que soit le client ; seuls les visuels générés suivent la charte du client.
Le thème de base (couleurs, police, arrondis) est dans .streamlit/config.toml ; ce module ajoute ce que le thème
ne permet pas (boutons en capitales, libellés mono, sidebar, cartes, statuts) et quelques composants HTML.
"""
import base64
from html import escape
from pathlib import Path

import streamlit as st

STATIC = Path(__file__).resolve().parent.parent / "static"
LOGO_WHITE = STATIC / "img" / "komian-logo-white.png"
SYMBOL_WHITE = STATIC / "img" / "komian-symbol-white.png"
FAVICON = STATIC / "img" / "komian-favicon.png"

# Statuts de la base → classe et libellé de la charte (« Envoyé », « Validé »…)
STATUS = {"pending": ("soumis", "En attente"), "approved": ("approuve", "Approuvé"),
          "rejected": ("rejete", "Rejeté")}

CSS = """
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&display=swap');
:root {
  --indigo: #5D63FF; --orange: #FF6A3D; --teal: #0AC2B2; --purple: #6B3FA0; --red: #E63946; --green: #157145;
  --g900: #121212; --g850: #1C1C1C; --g800: #242424; --g700: #333333; --g600: #555555;
  --g500: #888888; --g400: #B3B3B3; --g300: #CCCCCC; --g200: #E6E6E6; --g100: #F2F2F2;
  --mono: "IBM Plex Mono", ui-monospace, Menlo, monospace;
}

/* ——— Cadre général ——— */
header[data-testid="stHeader"] { background: transparent; height: 0; }
[data-testid="stMainMenu"], [data-testid="stDecoration"] { display: none; }
[data-testid="stMainBlockContainer"] { padding: 0 32px 64px; max-width: 1440px; }
h1 { font-size: 34px !important; font-weight: 700 !important; letter-spacing: -0.03em; line-height: 1.05 !important; padding: 0 !important; }
h2 { font-size: 22px !important; font-weight: 600 !important; letter-spacing: -0.02em; }
h3 { font-size: 16px !important; font-weight: 600 !important; letter-spacing: -0.01em; padding: 6px 0 0 !important; }
h4 { font-size: 20px !important; font-weight: 600 !important; letter-spacing: -0.02em; }
[data-testid="stCaptionContainer"] { color: var(--g600); font-size: 13px; }
hr { border-color: var(--g200) !important; margin: 20px 0 !important; }

/* Libellés techniques : mono majuscule, comme dans la charte */
.k-label, [data-testid="stWidgetLabel"] p {
  font-family: var(--mono) !important; font-size: 11px !important; letter-spacing: 0.06em;
  text-transform: uppercase; color: var(--g600);
}
.k-label { display: block; color: var(--g500); }
[data-testid="stCheckbox"] [data-testid="stWidgetLabel"] p {
  font-family: inherit !important; font-size: 14px !important; letter-spacing: 0; text-transform: none; color: #000;
}

/* ——— Barre latérale noire ——— */
[data-testid="stSidebar"] { border-right: 1px solid var(--g850); }
[data-testid="stSidebarHeader"] { padding: 28px 24px 6px; }
[data-testid="stSidebarLogo"] { height: 22px !important; max-width: 160px; }
[data-testid="stSidebarNav"] { padding: 4px 12px 0; }
[data-testid="stNavSectionHeader"] {
  font-family: var(--mono); font-size: 11px; letter-spacing: 0.06em; text-transform: uppercase;
  color: var(--g600) !important; padding: 18px 12px 6px; font-weight: 400;
}
[data-testid="stSidebarNavLink"] {
  padding: 10px 12px; border-radius: 2px; color: var(--g400); position: relative; margin: 1px 0;
}
[data-testid="stSidebarNavLink"] span { color: inherit !important; font-size: 14px; }
[data-testid="stSidebarNavLink"]:hover { background: var(--g850) !important; color: #fff; }
[data-testid="stSidebarNavLink"][aria-current="page"] { background: var(--g800) !important; color: #fff; }
[data-testid="stSidebarNavLink"][aria-current="page"]::before {
  content: ""; position: absolute; left: -12px; top: 8px; bottom: 8px; width: 3px; background: var(--indigo);
}
[data-testid="stSidebarNavSeparator"] { border-color: var(--g850); margin: 14px 12px; }
[data-testid="stSidebarUserContent"] { padding: 8px 24px 24px; }
[data-testid="stSidebar"] [data-testid="stWidgetLabel"] p { color: var(--g600); }
[data-testid="stSidebar"] [data-testid="stCaptionContainer"] { color: var(--g500); }
[data-testid="stSidebar"] hr { border-color: var(--g850) !important; }
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] { padding: 2px 0; background: none; }
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"] p {
  text-transform: none !important; letter-spacing: 0 !important; font-weight: 500 !important;
  font-size: 13px !important; color: var(--g400);
}
[data-testid="stSidebar"] a[data-testid="stPageLink-NavLink"]:hover p { color: #fff; }
.k-sep { height: 1px; background: var(--g850); margin: 18px -24px 16px; }
.k-client { display: flex; flex-direction: column; gap: 10px; margin: 4px 0 6px; }
.k-client .logo { background: #fff; border-radius: 2px; padding: 10px 12px; display: flex; align-items: center; }
.k-client .logo img { max-height: 30px; max-width: 100%; object-fit: contain; }
.k-swatches { display: flex; gap: 6px; flex-wrap: wrap; }
.k-sw { width: 22px; height: 22px; border-radius: 50%; border: 1px solid rgba(255,255,255,.18); }
.k-engine { display: flex; align-items: center; gap: 8px; font-size: 13px; color: var(--g300); margin-top: 6px; }
.k-engine small { display: block; color: var(--g500); font-size: 12px; }
.k-dot { width: 8px; height: 8px; border-radius: 50%; background: var(--g500); flex: none; }
.k-dot.on { background: var(--teal); }
.k-dot.warn { background: var(--orange); }

/* ——— Barre du haut ——— */
.st-key-topbar {
  position: sticky; top: 0; z-index: 20; background: #fff; border-bottom: 1px solid var(--g200);
  margin: 0 -32px 32px; padding: 0 32px; min-height: 64px; justify-content: center;
  width: calc(100% + 64px) !important; max-width: none;
}
.st-key-topbar [data-testid="stHorizontalBlock"] { align-items: center; }
.k-crumbs { font-size: 14px; color: var(--g600); display: flex; gap: 8px; align-items: center; }
.k-crumbs b { color: #000; font-weight: 600; }

/* ——— Titres de page ——— */
.k-head { margin-bottom: 24px; }
.k-head h1 { margin: 6px 0 0; }
.k-head p { margin: 8px 0 0; color: var(--g600); max-width: 64ch; font-size: 15px; }

/* ——— Boutons : Semibold, capitales (règle charte) ——— */
button[data-testid^="stBaseButton"] {
  min-height: 40px; padding: 0 18px; border-radius: 2px; transition: none;
}
button[data-testid^="stBaseButton"] p, a[data-testid="stPageLink-NavLink"] p {
  font-weight: 600 !important; font-size: 12.5px !important; letter-spacing: 0.06em; text-transform: uppercase;
}
button[data-testid^="stBaseButton-secondary"] { background: transparent; border-color: var(--g300); color: #000; }
button[data-testid^="stBaseButton-secondary"]:hover { background: #fff; border-color: #000; color: #000; }
button[data-testid^="stBaseButton-primary"]:hover { background: #4b51f0; border-color: #4b51f0; }
button[data-testid^="stBaseButton"]:disabled { opacity: 0.4; }
.st-key-topbar [data-testid="stPageLink"] { display: flex; justify-content: flex-end; }
.st-key-topbar a[data-testid="stPageLink-NavLink"] {
  background: var(--indigo); color: #fff; height: 32px; padding: 0 12px; border-radius: 2px;
}
.st-key-topbar a[data-testid="stPageLink-NavLink"] p { font-size: 11.5px !important; color: #fff; }
.st-key-topbar a[data-testid="stPageLink-NavLink"]:hover { background: #4b51f0; }

/* ——— Cartes ——— */
[data-testid="stForm"], [class*="st-key-card"] {
  background: #fff; border: 1px solid var(--g200) !important; border-radius: 2px; padding: 24px;
}
[data-testid="stExpander"] details { border: 1px solid var(--g200); border-radius: 2px; background: #fff; }
[data-testid="stExpander"] summary p { font-weight: 600; font-size: 14px; }
[data-testid="stSidebar"] [data-testid="stExpander"] details { background: var(--g850); border-color: var(--g700); }

/* Scène : le visuel sur fond sombre en damier */
[class*="st-key-stage"] {
  background-color: var(--g850); padding: 32px; border-radius: 0; align-items: center;
  background-image: linear-gradient(45deg, #1f1f1f 25%, transparent 25%), linear-gradient(-45deg, #1f1f1f 25%, transparent 25%),
    linear-gradient(45deg, transparent 75%, #1f1f1f 75%), linear-gradient(-45deg, transparent 75%, #1f1f1f 75%);
  background-size: 20px 20px; background-position: 0 0, 0 10px, 10px -10px, -10px 0;
}
[class*="st-key-stage"] img { box-shadow: 0 12px 40px rgba(0,0,0,.45); max-height: min(640px, 72vh); width: auto !important; margin: 0 auto; }
[class*="st-key-stage"] [data-testid="stCaptionContainer"] { color: var(--g400); }

/* ——— Étapes ——— */
.st-key-stepper { gap: 0; margin-bottom: 24px; }
.st-key-stepper [data-testid="stHorizontalBlock"] { gap: 0; border: 1px solid var(--g200); background: #fff; }
.st-key-stepper [data-testid="stColumn"] + [data-testid="stColumn"] { border-left: 1px solid var(--g200); }
.st-key-stepper button {
  width: 100%; justify-content: flex-start; border: none !important; background: none !important;
  min-height: 52px; padding: 0 18px; color: var(--g500); border-radius: 0;
}
.st-key-stepper button p { text-transform: none !important; letter-spacing: 0 !important; font-size: 14px !important; font-weight: 400 !important; }
.st-key-stepper button:hover { color: #000; }
[class*="st-key-stepper_on"] button { color: #000; box-shadow: inset 0 -2px 0 #000; }
[class*="st-key-stepper_on"] button p { font-weight: 600 !important; }
[class*="st-key-stepper_done"] button { color: #000; }

/* ——— Tuiles de choix du client (étape 1) ——— */
[class*="st-key-pick_"] button {
  justify-content: flex-start; gap: 10px; min-height: 52px; padding: 8px 12px; background: #fff;
  border-color: var(--g300);
}
[class*="st-key-pick_"] button::before {
  content: ""; width: 64px; height: 30px; flex: none; background: center / contain no-repeat;
}
[class*="st-key-pick_"] button p {
  text-transform: none !important; letter-spacing: 0 !important; font-size: 14px !important; font-weight: 500 !important;
}
[class*="st-key-pick_on_"] button { border-color: #000 !important; box-shadow: inset 0 0 0 1px #000; }
[class*="st-key-pick_on_"] button p { font-weight: 600 !important; }

/* ——— Choix en puces (radios horizontales, filtres) ——— */
[data-testid="stRadioGroup"][aria-orientation="horizontal"] { gap: 6px !important; flex-wrap: wrap; }
[aria-orientation="horizontal"] [data-testid="stRadioOption"] {
  border: 1px solid var(--g300); background: #fff; border-radius: 16px; padding: 5px 14px; margin: 0 !important;
}
[aria-orientation="horizontal"] [data-testid="stRadioOption"]:hover { border-color: #000; }
[aria-orientation="horizontal"] [data-testid="stRadioOption"] > div > div:first-child { display: none; }
[aria-orientation="horizontal"] [data-testid="stRadioOption"][data-selected="true"] { background: #000; border-color: #000; }
[aria-orientation="horizontal"] [data-testid="stRadioOption"][data-selected="true"] p { color: #fff; }
[aria-orientation="horizontal"] [data-testid="stRadioOption"] p { font-size: 13px; }
[data-testid="stButtonGroup"] button { border-radius: 16px !important; min-height: 32px; margin-right: 6px; }
[data-testid="stButtonGroup"] button p { text-transform: none !important; letter-spacing: 0 !important; font-weight: 400 !important; font-size: 13px !important; }
button[data-testid="stBaseButton-segmented_controlActive"] { background: #000; border-color: #000; }
button[data-testid="stBaseButton-segmented_controlActive"] p { color: #fff; }

/* ——— Messages : barre à gauche, comme les notes de la charte ——— */
[data-testid="stAlertContainer"] { border-radius: 0; border-left: 3px solid #000; background: var(--g100); color: #000; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentInfo"]) { border-left-color: var(--indigo); background: #f3f3ff; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentSuccess"]) { border-left-color: var(--green); background: #f0f8f4; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentWarning"]) { border-left-color: var(--orange); background: #fff6f2; }
[data-testid="stAlertContainer"]:has([data-testid="stAlertContentError"]) { border-left-color: var(--red); background: #fff3f4; }
[data-testid="stAlertContainer"] p { color: #000; font-size: 14px; }
[data-testid="stToast"] { background: #000; color: #fff; border-radius: 0; }
[data-testid="stToast"] p { color: #fff; }

/* Dépôt de fichier */
[data-testid="stFileUploaderDropzone"] { border: 1.5px dashed var(--g400); background: #fff; border-radius: 0; }
[data-testid="stFileUploaderDropzone"]:hover { border-color: var(--indigo); background: #f6f6ff; }

/* ——— Statuts ——— */
.k-status {
  display: inline-flex; align-items: center; gap: 7px; font-family: var(--mono); font-size: 11px;
  letter-spacing: 0.04em; text-transform: uppercase; padding: 3px 9px 3px 8px; border-radius: 20px;
  white-space: nowrap; border: 1px solid currentColor;
}
.k-status::before { content: ""; width: 6px; height: 6px; border-radius: 50%; background: currentColor; }
.k-status.st-soumis { color: var(--indigo); }
.k-status.st-approuve { color: var(--green); }
.k-status.st-rejete { color: var(--red); }

/* ——— Clients ——— */
.k-card-head {
  display: flex; align-items: center; gap: 12px; margin: -24px -24px 8px; padding: 18px 24px;
  border-bottom: 1px solid var(--g200);
}
.k-card-head h3 { flex: 1; margin: 0; padding: 0 !important; }
.k-hero { height: 132px; display: grid; place-items: center; padding: 24px; margin: -24px -24px 0; }
.k-hero img { max-height: 54px; max-width: 70%; object-fit: contain; }
.k-client-body { display: flex; flex-direction: column; gap: 8px; padding-top: 4px; }
.k-client-body h3 { margin: 0; padding: 0 !important; }
.k-muted { color: var(--g600); font-size: 13px; }
.k-row { display: flex; align-items: center; justify-content: space-between; gap: 12px; }
.k-tag {
  white-space: nowrap; font-family: var(--mono); font-size: 10.5px; background: var(--g100);
  border: 1px solid var(--g200); padding: 1px 6px; border-radius: 10px; color: var(--g600);
}
.k-tag.warn { color: #c2410c; border-color: #fed7c3; background: #fff6f2; }
.k-tag.ok { color: var(--green); border-color: #bfe0cf; background: #f0f8f4; }
.k-tags { display: flex; gap: 4px; flex-wrap: wrap; }
.k-sw-sm { display: flex; gap: 6px; }
.k-sw-sm span { width: 22px; height: 22px; border-radius: 50%; border: 1px solid rgba(0,0,0,.12); }
.k-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(150px, 1fr)); gap: 12px; }
.k-swatch { border: 1px solid var(--g200); background: #fff; border-radius: 2px; }
.k-swatch .c { height: 64px; border-bottom: 1px solid var(--g200); }
.k-swatch .m { padding: 8px 10px; display: flex; flex-direction: column; gap: 2px; }
.k-swatch .m b { font-weight: 600; font-size: 14px; }
.k-mono { font-family: var(--mono); font-size: 12px; color: var(--g600); }
.k-asset { border: 1px solid var(--g200); background: #fff; }
.k-asset .pv { aspect-ratio: 4/3; display: grid; place-items: center; overflow: hidden; background: var(--g100); }
.k-asset .pv img { width: 80%; height: 80%; object-fit: contain; }
.k-asset .pv img.cover { width: 100%; height: 100%; max-width: none; max-height: none; object-fit: cover; }
.k-asset .info { padding: 8px 10px; font-size: 12.5px; }
.k-asset .info b { font-weight: 600; display: block; }
.k-setting { display: flex; gap: 16px; align-items: flex-start; padding: 14px 0; border-bottom: 1px solid var(--g200); font-size: 14px; }
.k-setting:last-child { border-bottom: none; }
.k-setting .txt { flex: 1; }
.k-setting .txt b { font-weight: 600; display: block; }
.k-setting .txt span { font-size: 13.5px; color: var(--g600); }
.k-font-sample { font-size: 28px; letter-spacing: -0.02em; line-height: 1.15; margin: 4px 0 10px; }
.st-key-back button { padding: 0; min-height: 0; }
.st-key-back button p { text-transform: none !important; letter-spacing: 0 !important; font-weight: 500 !important; font-size: 13px !important; color: var(--g600); }

[data-testid="stPopoverButton"] p {
  font-weight: 600 !important; font-size: 12.5px !important; letter-spacing: 0.06em; text-transform: uppercase;
}
[data-testid="stPopoverButton"] { min-height: 40px; border-radius: 2px; background: transparent; }

/* Suppression : bouton de confirmation en rouge */
[class*="st-key-del_ok_"] button { background: var(--red); border-color: var(--red); }
[class*="st-key-del_ok_"] button:hover { background: #c92f3b; border-color: #c92f3b; }

/* Vignettes de la galerie */
[class*="st-key-tile"] { padding: 0 !important; gap: 0; overflow: hidden; background: #fff; border-color: var(--g200) !important; }
[class*="st-key-tile"] [data-testid="stImage"] { background: var(--g850); }
[class*="st-key-tile"] > div:not(:first-child) { padding: 0 14px; }
[class*="st-key-tile"] > div:nth-child(2) { padding-top: 12px; }
[class*="st-key-tile"] > div:last-child { padding-bottom: 14px; }
"""


def inject_theme() -> None:
    st.html(f"<style>{CSS}</style>")


def data_uri(path: Path) -> str:
    return "data:image/png;base64," + base64.b64encode(path.read_bytes()).decode()


def topbar_crumbs(page_title: str) -> str:
    return f"<div class='k-crumbs'><span>KÔMIAN Studio</span><span>/</span><b>{escape(page_title)}</b></div>"


def page_head(eyebrow: str, title: str, text: str = "") -> None:
    st.markdown(f"<div class='k-head'><span class='k-label'>{escape(eyebrow)}</span><h1>{escape(title)}</h1>"
                + (f"<p>{escape(text)}</p>" if text else "") + "</div>", unsafe_allow_html=True)


def label(text: str, container=st) -> None:
    container.markdown(f"<span class='k-label'>{escape(text)}</span>", unsafe_allow_html=True)


def status_html(status: str) -> str:
    cls, text = STATUS.get(status, ("brouillon", status))
    return f"<span class='k-status st-{cls}'>{escape(text)}</span>"


def status_badge(container, status: str) -> None:
    container.markdown(status_html(status), unsafe_allow_html=True)


def client_card(name: str, logo: Path | None, colors: list[str]) -> str:
    """Bloc « client » de la barre latérale : logo du client sur blanc et pastilles de sa charte."""
    logo_html = (f"<div class='logo'><img src='{data_uri(logo)}' alt='{escape(name)}'></div>"
                 if logo and logo.is_file() else f"<b>{escape(name)}</b>")
    swatches = "".join(f"<span class='k-sw' style='background:{c}' title='{c}'></span>" for c in colors)
    return f"<div class='k-client'>{logo_html}<div class='k-swatches'>{swatches}</div></div>"


def engine_status(available: bool, online: tuple[int, int] | None = None) -> str:
    """État des moteurs : IA en ligne (crédits du jour) et IA locale."""
    html = "<span class='k-label' style='color:var(--g600)'>Moteur de création</span>"
    if online:
        left, limit = online
        dot = "on" if left > 0 else "warn"
        sub = f"{left} / {limit} images restantes aujourd'hui" if left else "Quota du jour atteint · renouvelé à minuit"
        html += f"<div class='k-engine'><span class='k-dot {dot}'></span><div>IA en ligne<small>{sub}</small></div></div>"
    dot, sub = ("on", "Disponible sur ce poste") if available else ("warn", "Indisponible sur ce poste")
    return html + f"<div class='k-engine'><span class='k-dot {dot}'></span><div>IA locale<small>{sub}</small></div></div>"


def card_head(title: str, right: str = "") -> str:
    return (f"<div class='k-card-head'><h3>{escape(title)}</h3>"
            + (f"<span class='k-label'>{escape(right)}</span>" if right else "") + "</div>")


def tag(text: str, kind: str = "") -> str:
    return f"<span class='k-tag {kind}'>{escape(text)}</span>"


def client_tile(name: str, hero_bg: str, logo: Path | None, sub: str, colors: list[str], status: str) -> str:
    """Carte d'un client dans la liste : bandeau à sa couleur principale, logo blanc, pastilles de sa palette."""
    logo_html = (f"<img src='{data_uri(logo)}' alt='{escape(name)}'>" if logo and logo.is_file()
                 else f"<b style='color:#fff;font-size:20px'>{escape(name)}</b>")
    dots = "".join(f"<span style='background:{c}' title='{c}'></span>" for c in colors)
    return (f"<div class='k-hero' style='background:{hero_bg}'>{logo_html}</div>"
            f"<div class='k-client-body'><h3>{escape(name)}</h3><div class='k-muted'>{escape(sub)}</div>"
            f"<div class='k-sw-sm'>{dots}</div><div class='k-tags'>{status}</div></div>")


def swatch(name: str, hex_: str, details: str = "") -> str:
    return (f"<div class='k-swatch'><div class='c' style='background:{hex_}'></div><div class='m'>"
            f"<b>{escape(name)}</b><span class='k-mono'>{hex_}</span>"
            + (f"<span class='k-mono'>{escape(details)}</span>" if details else "") + "</div></div>")


def asset(image: Path, title: str, sub: str = "", bg: str = "var(--g100)", cover: bool = False) -> str:
    img = (f"<img class='{'cover' if cover else ''}' src='{data_uri(image)}' alt='{escape(title)}'>"
           if image.is_file() else "<span class='k-muted'>Fichier manquant</span>")
    return (f"<div class='k-asset'><div class='pv' style='background:{bg}'>{img}</div>"
            f"<div class='info'><b>{escape(title)}</b>{f'<span class=k-muted>{escape(sub)}</span>' if sub else ''}"
            "</div></div>")


def setting(title: str, text: str, right: str = "") -> str:
    return (f"<div class='k-setting'><div class='txt'><b>{escape(title)}</b><span>{escape(text)}</span></div>"
            f"{right}</div>")


def font_face(family: str, path: Path, weight: int = 400, style: str = "normal") -> str:
    """Déclare une police du client (embarquée) pour en montrer un aperçu dans sa fiche."""
    if not path.is_file():
        return ""
    data = base64.b64encode(path.read_bytes()).decode()
    mime, fmt = ("font/otf", "opentype") if path.suffix.lower() == ".otf" else ("font/ttf", "truetype")
    return (f"@font-face {{ font-family: '{family}'; src: url(data:{mime};base64,{data}) format('{fmt}'); "
            f"font-weight: {weight}; font-style: {style}; }}")


def stepper(labels: list[str], current: int, key: str = "stepper") -> int | None:
    """Étapes cliquables, à la manière de la maquette. Renvoie l'index de l'étape cliquée."""
    clicked = None
    with st.container(key=key):
        cols = st.columns(len(labels))
        for i, (col, text) in enumerate(zip(cols, labels)):
            state = "on" if i == current else ("done" if i < current else "todo")
            if col.button(f"{i + 1}. {text}", key=f"{key}_{state}_{i}", type="tertiary",
                          icon=":material/check:" if state == "done" else None):
                clicked = i
    return clicked
