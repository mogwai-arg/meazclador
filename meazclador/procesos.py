"""Cadena de procesamiento por instrumento: limpieza, ecualización y compresión.

Cada pista llega ya nivelada a -18 dBFS RMS (en sus partes activas), así los umbrales
de compresión son comparables entre pistas y entre canciones.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from pathlib import Path

import numpy as np
from pedalboard import (
    Compressor,
    HighpassFilter,
    HighShelfFilter,
    LowpassFilter,
    PeakFilter,
    Pedalboard,
)

from .analisis import Pista
from .audio import SR_TRABAJO, desde_db, nivel_activo, rms_corto
from .dinamica import de_esser, expansor, saturacion
from .efectos import (amplificador, bajo_gruñon, cargar_sample, eco_corto, es_guitarra_directa,
                      realzar_ataque, reforzar_con_sample, sample_bombo, sample_caja)

NIVEL_TRABAJO_DB = -18.0


@dataclass
class Receta:
    """Decisiones de mezcla típicas para un instrumento (punto de partida de un ingeniero)."""

    paso_alto: float
    paso_bajo: float | None = None
    eq: list[tuple[str, float, float, float]] = field(default_factory=list)  # (tipo, Hz, dB, Q)
    compresion: list[tuple[float, float, float, float]] = field(default_factory=list)  # (dB bajo picos, ratio, at, rel)
    de_esser: bool = False
    expansor: bool = False
    saturacion: float = 0.0
    reverb: float = 0.0
    # Color de estilo (0 / None = no se usa)
    amplificador: float = 0.0  # ganancia del ampli simulado para guitarras directas
    gruñido: float = 0.0  # distorsión en paralelo del bajo
    sample: str | None = None  # "bombo" o "caja": refuerzo con sampler
    mezcla_sample: float = 0.0
    ataque_db: float = 0.0  # realce del golpe
    eco: tuple[float, float] | None = None  # (ms, dB) de slapback
    de_esser_max_db: float = 8.0


RECETAS: dict[str, Receta] = {
    "bombo": Receta(
        paso_alto=30,
        eq=[("pico", 60, 2.0, 1.0), ("pico", 380, -4.0, 1.4), ("pico", 4000, 3.0, 1.0)],
        compresion=[(6, 4.0, 15, 90)],
        expansor=True,
        saturacion=0.15,
    ),
    "caja": Receta(
        paso_alto=80,
        eq=[("pico", 200, 2.0, 1.2), ("pico", 900, -2.5, 1.5), ("agudos", 6000, 2.5, 0.7)],
        compresion=[(6, 4.0, 8, 120)],
        saturacion=0.15,
        reverb=0.16,
    ),
    "hihat": Receta(paso_alto=300, eq=[("pico", 600, -2.0, 1.0), ("agudos", 10000, 1.5, 0.7)], compresion=[(4, 2.0, 5, 80)]),
    "toms": Receta(
        paso_alto=60,
        eq=[("pico", 100, 2.0, 1.0), ("pico", 450, -4.0, 1.2), ("pico", 4000, 2.0, 1.0)],
        compresion=[(6, 4.0, 10, 150)],
        expansor=True,
        reverb=0.10,
    ),
    "overheads": Receta(
        paso_alto=120,
        eq=[("pico", 400, -2.5, 1.0), ("agudos", 10000, 2.0, 0.7)],
        compresion=[(4, 2.0, 20, 200)],
        reverb=0.05,
    ),
    "bajo": Receta(
        paso_alto=35,
        paso_bajo=9000,
        eq=[("pico", 250, -2.5, 1.2), ("pico", 800, 2.0, 1.2)],
        compresion=[(8, 4.0, 20, 160), (4, 2.0, 5, 80)],
        saturacion=0.3,
    ),
    "guitarra": Receta(
        paso_alto=90,
        paso_bajo=12000,
        eq=[("pico", 300, -2.5, 1.0), ("pico", 3000, 1.0, 1.0)],
        compresion=[(5, 2.5, 20, 150)],
        reverb=0.08,
    ),
    "teclado": Receta(
        paso_alto=70,
        eq=[("pico", 300, -2.0, 1.0)],
        compresion=[(4, 2.0, 20, 200)],
        reverb=0.10,
    ),
    "voz": Receta(
        paso_alto=85,
        eq=[("pico", 250, -2.5, 1.0), ("pico", 3000, 2.0, 0.9), ("agudos", 10000, 2.5, 0.7)],
        compresion=[(8, 3.0, 8, 90), (4, 2.0, 2, 60)],
        de_esser=True,
        saturacion=0.1,
        reverb=0.18,
    ),
    "coros": Receta(
        paso_alto=150,
        eq=[("pico", 300, -3.5, 1.0), ("agudos", 10000, 2.0, 0.7)],
        compresion=[(10, 4.0, 5, 100)],
        de_esser=True,
        reverb=0.28,
    ),
    "otros": Receta(paso_alto=40, eq=[("pico", 300, -1.5, 1.0)], compresion=[(4, 2.0, 20, 150)], reverb=0.08),
}


def _con(rol: str, **cambios) -> Receta:
    return replace(RECETAS[rol], **cambios)


# Estilo punk (Ramones): crudo, medios al frente, pared de guitarras, batería que pega.
RECETAS_PUNK: dict[str, Receta] = {
    **RECETAS,
    "bombo": _con("bombo", eq=[("pico", 60, 3.0, 1.0), ("pico", 380, -5.0, 1.4), ("pico", 3500, 4.0, 1.0)],
                  compresion=[(8, 5.0, 10, 80)], sample="bombo", mezcla_sample=0.45, ataque_db=4.0, saturacion=0.25),
    "caja": _con("caja", eq=[("pico", 200, 3.0, 1.2), ("pico", 900, -2.0, 1.5), ("agudos", 5000, 3.0, 0.7)],
                 compresion=[(8, 5.0, 5, 100)], sample="caja", mezcla_sample=0.4, ataque_db=4.0,
                 saturacion=0.3, reverb=0.12),
    "toms": _con("toms", ataque_db=3.0, saturacion=0.2),
    "overheads": _con("overheads", compresion=[(8, 4.0, 10, 150)], saturacion=0.2),
    "bajo": _con("bajo", eq=[("pico", 250, -2.0, 1.2), ("pico", 900, 3.0, 1.0)],
                 compresion=[(10, 5.0, 10, 120), (4, 2.0, 5, 80)], gruñido=0.6, saturacion=0.2),
    "guitarra": _con("guitarra", paso_alto=100, paso_bajo=9000,
                     eq=[("pico", 400, -1.5, 1.0), ("pico", 1800, 1.5, 1.0)],
                     compresion=[(4, 2.0, 30, 150)], amplificador=0.8, reverb=0.03),
    "voz": _con("voz", paso_alto=100, eq=[("pico", 250, -3.0, 1.0), ("pico", 2500, 3.0, 0.9), ("agudos", 9000, 1.5, 0.7)],
                compresion=[(10, 4.0, 5, 80), (5, 3.0, 1, 50)], de_esser_max_db=4.0, saturacion=0.3,
                eco=(110, -11.0), reverb=0.07),
    "coros": _con("coros", compresion=[(12, 6.0, 3, 80)], saturacion=0.3, de_esser_max_db=4.0,
                  eco=(110, -14.0), reverb=0.12),
}


def nivelar(audio: np.ndarray, objetivo_db: float = NIVEL_TRABAJO_DB) -> tuple[np.ndarray, float]:
    ganancia_db = objetivo_db - nivel_activo(audio)
    return (audio * desde_db(ganancia_db)).astype(np.float32), ganancia_db


def _nivel_picos(audio: np.ndarray) -> float:
    """Nivel de las partes fuertes (percentil 90 del RMS corto activo)."""
    r = rms_corto(audio)
    activos = r[r > -50]
    return float(np.percentile(activos, 90)) if len(activos) else NIVEL_TRABAJO_DB


def procesar_pista(
    pista: Pista,
    recortes_extra: list[tuple[float, float, float]] | None = None,
    recetas: dict[str, Receta] | None = None,
    samples: dict[str, Path | None] | None = None,
    guitarras: str = "auto",
) -> np.ndarray:
    """Aplica la receta del instrumento + correcciones detectadas. Anota todo en pista.notas."""
    recetas = recetas or RECETAS
    receta = recetas.get(pista.rol, recetas["otros"])
    audio, g = nivelar(pista.audio)
    pista.notas.append(f"Nivel de entrada ajustado {g:+.1f} dB para trabajar con margen.")

    if receta.expansor:
        audio = expansor(audio)
        pista.notas.append("Expansor suave: baja el sonido de otros tambores que se cuela en este micrófono.")

    if receta.sample:
        propio = (samples or {}).get(receta.sample)
        sample = cargar_sample(propio, sample_bombo if receta.sample == "bombo" else sample_caja)
        audio, golpes = reforzar_con_sample(audio, sample, receta.mezcla_sample)
        if golpes:
            origen = f"tu sample '{propio.name}'" if propio else "un sample incorporado"
            pista.notas.append(f"Sampler: {golpes} golpes reforzados con {origen} "
                               f"({receta.mezcla_sample:.0%} sample, respetando la fuerza de cada golpe).")

    if receta.amplificador:
        directa = es_guitarra_directa(audio) if guitarras == "auto" else guitarras == "directas"
        if directa:
            audio = amplificador(audio, receta.amplificador)
            pista.notas.append(f"Guitarra directa (DI): pasada por un ampli británico saturado "
                               f"+ gabinete 4x12 (ganancia {receta.amplificador:.0%}).")
        else:
            audio = saturacion(audio, 0.35)
            pista.notas.append("La guitarra ya viene de un ampli: sólo se le suma saturación para endurecerla.")

    filtros = [HighpassFilter(cutoff_frequency_hz=receta.paso_alto)]
    pista.notas.append(f"Filtro paso alto en {receta.paso_alto:.0f} Hz: quita retumbe y graves inútiles.")
    if receta.paso_bajo:
        filtros.append(LowpassFilter(cutoff_frequency_hz=receta.paso_bajo))

    # Primero cortar lo que molesta (resonancias), después dar color.
    for hz, exceso in pista.resonancias:
        corte = -min(exceso * 0.5, 4.0)
        filtros.append(PeakFilter(cutoff_frequency_hz=hz, gain_db=corte, q=5.0))
        pista.notas.append(f"Resonancia en {hz:.0f} Hz ({exceso:.1f} dB de más): recorte estrecho de {corte:.1f} dB.")

    for tipo, hz, ganancia, q in receta.eq:
        if tipo == "agudos":
            filtros.append(HighShelfFilter(cutoff_frequency_hz=hz, gain_db=ganancia, q=q))
        else:
            filtros.append(PeakFilter(cutoff_frequency_hz=hz, gain_db=ganancia, q=q))

    for hz, ganancia, q in recortes_extra or []:
        filtros.append(PeakFilter(cutoff_frequency_hz=hz, gain_db=ganancia, q=q))

    audio = Pedalboard(filtros)(audio, SR_TRABAJO)

    for i, (debajo, ratio, ataque, liberacion) in enumerate(receta.compresion):
        umbral = _nivel_picos(audio) - debajo
        audio = Pedalboard(
            [Compressor(threshold_db=umbral, ratio=ratio, attack_ms=ataque, release_ms=liberacion)]
        )(audio, SR_TRABAJO)
        etapa = "Compresión" if i == 0 else "Segunda compresión (más rápida, controla picos)"
        pista.notas.append(f"{etapa}: {ratio:.1f}:1 desde {umbral:.1f} dBFS, ataque {ataque:.0f} ms.")

    if receta.gruñido:
        audio = bajo_gruñon(audio, receta.gruñido)
        pista.notas.append("Distorsión en paralelo: graves limpios + medios saturados que se escuchan entre las guitarras.")

    if receta.ataque_db:
        audio = realzar_ataque(audio, receta.ataque_db)
        pista.notas.append(f"Realce de ataque +{receta.ataque_db:.0f} dB: más golpe del palo, mismo cuerpo.")

    if receta.de_esser:
        audio, red = de_esser(audio, max_reduccion_db=receta.de_esser_max_db)
        if red > 0:
            pista.notas.append(f"De-esser: suaviza las 'eses' ({red:.1f} dB de reducción media cuando actúa).")

    if receta.saturacion:
        audio = saturacion(audio, receta.saturacion)
        pista.notas.append("Saturación suave: más cuerpo y presencia sin subir el volumen.")

    if receta.eco:
        audio = eco_corto(audio, *receta.eco)
        pista.notas.append(f"Eco corto (slapback) de {receta.eco[0]:.0f} ms: la voz suena grande sin reverb lavada.")

    pista.envio_reverb = receta.reverb
    audio, _ = nivelar(audio)
    return audio
