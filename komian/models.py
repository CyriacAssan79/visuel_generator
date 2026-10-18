"""Modèles Pydantic : profil de marque et brief."""
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Status = Literal["confirmé", "à confirmer", "dérivé"]


class Color(BaseModel):
    name: str
    hex: str
    rgb: tuple[int, int, int]
    pantone: str | None = None
    cmyk: tuple[int, int, int, int] | None = None
    status: Status = "confirmé"

    @field_validator("hex")
    @classmethod
    def _hex_matches(cls, v: str) -> str:
        if not (v.startswith("#") and len(v) == 7):
            raise ValueError(f"Couleur hexadécimale invalide : {v}")
        return v.upper()


class LogoAsset(BaseModel):
    id: str
    file: str
    description: str
    status: Status
    on_dark_background: bool = False


class LocalMarket(BaseModel):
    market: str
    tagline: str | None = None
    handle: str | None = None
    address: str | None = None
    status: Status = "à confirmer"
    source: str


class BrandProfile(BaseModel):
    brand_id: str
    brand_name: str
    source_document: str
    source_version_status: Status
    official_spelling: str
    forbidden_spellings: list[str]
    internal_only_abbreviations: list[str]
    logos: list[LogoAsset]
    fonts: dict[str, str]
    primary_colors: dict[str, Color]
    primary_color_rule: str
    neutral_colors: dict[str, Color] = {}
    series_tags: dict[str, list[str]] = {}
    secondary_colors: list[Color]
    secondary_colors_status: Status
    local_market: LocalMarket | None = None
    iconography_themes: list[str]
    unknowns: list[str]

    def logo(self, logo_id: str) -> LogoAsset:
        for logo in self.logos:
            if logo.id == logo_id:
                return logo
        raise KeyError(f"Logo inconnu : {logo_id}")

    @property
    def allowed_system_colors(self) -> dict[str, tuple[int, int, int]]:
        colors = {c.name: c.rgb for c in self.primary_colors.values()}
        colors.update({c.name: c.rgb for c in self.neutral_colors.values()})
        colors["blanc"] = (255, 255, 255)
        return colors

    def series_tag(self, series: str | None) -> list[str] | None:
        """Étiquette de série (ex. « Lundi » / « MOTIVATION »), si la série est connue du profil."""
        if not series:
            return None
        return next((lines for name, lines in self.series_tags.items() if name.casefold() == series.casefold()),
                    None)


class Brief(BaseModel):
    brand_id: str
    series: str | None = Field(None, description="Série récurrente, ex. « Lundi motivation »")
    objective: Literal["informer", "promouvoir", "recruter", "sensibiliser", "motiver", "autre"]
    channel: str
    format_id: str
    target_audience: str | None = None
    headline: str = Field(description="Accroche")
    exact_visual_text: str = Field(description="Texte exact à afficher, conservé tel quel")
    visual_direction: str
    logo_position: Literal["bas à droite", "bas à gauche", "haut à droite", "haut à gauche"] = "bas à droite"
    icons: list[Literal["calendrier", "coche"]] = []
    show_series_tag: bool = True
    headline_on_visual: bool = Field(True, description="Sinon, l'accroche sert au texte de la publication")
    constraints: list[str] = []
    legal_mentions: list[str] = []

    @field_validator("headline", "exact_visual_text", "visual_direction", "channel")
    @classmethod
    def _required(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Champ obligatoire")
        return v
