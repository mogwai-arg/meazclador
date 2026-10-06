"""Procesos dinámicos que pedalboard no trae hechos: de-esser, expansor y saturación."""

from __future__ import annotations

import numpy as np
from scipy.ndimage import maximum_filter1d, minimum_filter1d, uniform_filter1d
from scipy.signal import butter, sosfilt, sosfiltfilt

from .audio import SR_TRABAJO, db, desde_db_arr


def _envolvente(x: np.ndarray, sr: int, ventana_ms: float) -> np.ndarray:
    n = max(1, int(sr * ventana_ms / 1000))
    return np.sqrt(np.maximum(uniform_filter1d(x**2, size=n, mode="nearest"), 0))


def _suavizar_ganancia(g: np.ndarray, sr: int, ms: float, modo: str = "min") -> np.ndarray:
    """Suaviza una curva de ganancia mirando hacia adelante y hacia atrás.

    modo "min": la reducción nunca llega tarde (el promedio de una ventana de mínimos
    no supera el valor pedido en el centro). modo "max": la apertura nunca llega tarde.
    """
    n = max(1, int(sr * ms / 1000))
    filtro = minimum_filter1d if modo == "min" else maximum_filter1d
    return uniform_filter1d(filtro(g, size=2 * n + 1, mode="nearest"), size=2 * n + 1, mode="nearest")


def de_esser(
    audio: np.ndarray, sr: int = SR_TRABAJO, frec: float = 5500, max_reduccion_db: float = 8
) -> tuple[np.ndarray, float]:
    """Atenúa las 'eses' sólo cuando la banda de sibilancia se dispara.

    Devuelve (audio, reducción media en dB aplicada en los momentos activos).
    """
    sos = butter(4, frec, btype="highpass", fs=sr, output="sos")
    agudos = sosfiltfilt(sos, audio, axis=1)
    resto = audio - agudos  # suma exacta: sin reducción, la señal queda idéntica
    env_a = _envolvente(agudos.mean(axis=0), sr, 5)
    env_t = _envolvente(audio.mean(axis=0), sr, 5)
    # una "ese" es cuando los agudos dominan sobre la señal completa
    proporcion = db(env_a) - db(env_t)
    activo = db(env_t) > -50
    if not np.any(activo):
        return audio, 0.0
    umbral = np.percentile(proporcion[activo], 85)
    exceso = np.clip(proporcion - umbral, 0, None) * activo
    red_db = np.minimum(exceso * 1.5, max_reduccion_db)
    g = _suavizar_ganancia(desde_db_arr(-red_db), sr, 10, "min")
    salida = resto + agudos * g
    media = float(np.mean(red_db[red_db > 0.5])) if np.any(red_db > 0.5) else 0.0
    return salida.astype(np.float32), media


def expansor(
    audio: np.ndarray, sr: int = SR_TRABAJO, rango_db: float = 12, debajo_del_pico_db: float = 30
) -> np.ndarray:
    """Baja suavemente el 'sangrado' entre golpes (toms, bombo), sin cortar como un gate."""
    env = _envolvente(audio.mean(axis=0), sr, 10)
    env_db = db(env)
    umbral = float(env_db.max()) - debajo_del_pico_db
    bajo = np.clip(umbral - env_db, 0, None)
    red_db = np.minimum(bajo * 1.0, rango_db)  # ratio 1:2 hasta el rango máximo
    g = _suavizar_ganancia(desde_db_arr(-red_db), sr, 80, "max")
    return (audio * g).astype(np.float32)


def saturacion(audio: np.ndarray, cantidad: float = 0.2) -> np.ndarray:
    """Saturación suave tipo cinta: agrega armónicos y redondea picos. cantidad 0..1."""
    if cantidad <= 0:
        return audio
    drive = 1 + 4 * cantidad
    pico = np.max(np.abs(audio)) + 1e-12
    x = audio / pico
    sat = np.tanh(drive * x) / np.tanh(drive)
    mezcla = (1 - cantidad) * x + cantidad * sat
    return (mezcla * pico).astype(np.float32)


def filtro_paso_bajo(audio: np.ndarray, frec: float, sr: int = SR_TRABAJO) -> np.ndarray:
    sos = butter(2, frec, btype="lowpass", fs=sr, output="sos")
    return sosfilt(sos, audio, axis=1).astype(np.float32)


def filtro_paso_alto(audio: np.ndarray, frec: float, sr: int = SR_TRABAJO) -> np.ndarray:
    sos = butter(2, frec, btype="highpass", fs=sr, output="sos")
    return sosfilt(sos, audio, axis=1).astype(np.float32)
