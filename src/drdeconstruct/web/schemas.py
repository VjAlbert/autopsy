"""Output strutturato del modulo Web."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Confidence = Literal["high", "medium", "low"]


class PageSection(BaseModel):
    name: str = Field(description="Nome generico della sezione, es. 'hero', 'griglia prodotti'.")
    role: str = Field(description="A cosa serve per l'utente del sito.")
    layout: str = Field(description="Come è disposta, es. 'griglia 3 colonne, 1 su mobile'.")
    components: list[str] = Field(description="Nomi dei componenti che contiene.")


class UIComponent(BaseModel):
    name: str = Field(description="Nome generico e riutilizzabile, es. 'ProductCard'.")
    purpose: str
    structure: str = Field(description="Schema degli elementi, es. 'article > img + h3 + p + a'.")
    variants: list[str] = Field(description="Varianti osservate o probabili.")


class DesignSystem(BaseModel):
    colors_observed: list[str] = Field(description="Ruolo di ogni colore, es. '#1a1a1a testo'.")
    typography: str
    spacing_and_grid: str
    breakpoints: list[str]
    notes: str


class TechAssessment(BaseModel):
    name: str
    role: str
    evidence: str
    confidence: Confidence


class WebAnalysis(BaseModel):
    page_purpose: str = Field(description="Che tipo di pagina è e a chi si rivolge.")
    layout_summary: str = Field(description="Organizzazione complessiva del layout.")
    sections: list[PageSection]
    components: list[UIComponent]
    design_system: DesignSystem
    tech_stack: list[TechAssessment]
    interactions: list[str] = Field(description="Comportamenti dinamici probabili.")
    accessibility: list[str] = Field(description="Punti di forza e problemi di accessibilità.")
    rebuild_plan: list[str] = Field(
        description="Passi per costruire una PROPRIA versione, con contenuti propri."
    )
    do_not_reuse: list[str] = Field(
        description="Elementi da non copiare: testi, immagini, loghi, marchi, tratti distintivi."
    )
    open_questions: list[str] = Field(description="Cosa non si deduce dalla sola struttura.")
