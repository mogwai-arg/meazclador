"""Efectos de color para estilos: amplificador de guitarra, bajo con gruñido,
sampler de batería, realce de ataque y eco corto de voz.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
from pedalboard import HighpassFilter, LowpassFilter, PeakFilter, Pedalboard
from scipy.ndimage import maximum_filter1d, uniform_filter1d
from scipy.signal import resample_poly, stft

from .audio import SR_TRABAJO, a_mono, cargar, db, desde_db, nivel_activo

# ---------------------------------------------------------------- guitarras


def factor_cresta(audio: np.ndarray) -> float:
    """Pico vs. nivel promedio (dB). Una guitarra directa (DI) limpia tiene mucho más que una distorsionada."""
    mono = a_mono(audio)
    return float(db(np.max(np.abs(mono)) + 1e-12) - nivel_activo(audio))


def planitud_espectral(audio: np.ndarray, sr: int = SR_TRABAJO) -> float:
    """0 = armónicos limpios con valles profundos; más alto = espectro 'relleno' (distorsión)."""
    f, _, z = stft(a_mono(audio), sr, nperseg=4096)
    banda = (f >= 500) & (f <= 5000)
    p = np.abs(z[banda]) ** 2 + 1e-20
    activos = p.sum(axis=0) > p.sum(axis=0).max() * 1e-3
    if not np.any(activos):
        return 0.0
    p = p[:, activos]
    return float(np.median(np.exp(np.mean(np.log(p), axis=0)) / np.mean(p, axis=0)))


def es_guitarra_directa(audio: np.ndarray) -> bool:
    """¿Grabada por línea (DI, limpia) o con un ampli distorsionado?

    La distorsión rellena los valles entre armónicos (planitud alta) y aplasta los picos de
    la púa (cresta baja). Si falla con tus pistas, forzalo con --guitarras directas/amplificadas.
    """
    return planitud_espectral(audio) < 0.02 or factor_cresta(audio) > 16


def _recortar(x: np.ndarray, drive: float, asimetria: float) -> np.ndarray:
    """Saturación de válvula: suave y asimétrica (agrega armónicos pares, como un ampli real)."""
    return np.tanh(drive * x + asimetria) - np.tanh(asimetria)


def amplificador(audio: np.ndarray, ganancia: float = 0.75, sr: int = SR_TRABAJO) -> np.ndarray:
    """Simulador de ampli británico saturado + gabinete 4x12 (el sonido de pared de los Ramones).

    ganancia 0..1: 0.3 crunch, 0.6 rock, 0.8+ punk/pared de guitarras.
    """
    nivel = nivel_activo(audio)
    x = audio / (np.max(np.abs(audio)) + 1e-12)
    # Antes de saturar: sin graves flojos y con los medios empujados (ataque de púa).
    x = Pedalboard([
        HighpassFilter(cutoff_frequency_hz=110),
        PeakFilter(cutoff_frequency_hz=900, gain_db=6, q=0.7),
    ])(x.astype(np.float32), sr)

    # Sobremuestreo x4: la distorsión digital sin esto suena áspera ("fizz" metálico).
    sobre = resample_poly(x, 4, 1, axis=1)
    drive1 = desde_db(6 + 30 * ganancia)
    sobre = _recortar(sobre, drive1, 0.25)
    sobre = Pedalboard([LowpassFilter(cutoff_frequency_hz=7000)])(sobre.astype(np.float32), sr * 4)
    sobre = _recortar(sobre / (np.max(np.abs(sobre)) + 1e-12), desde_db(6 + 6 * ganancia), 0.1)
    x = resample_poly(sobre, 1, 4, axis=1).astype(np.float32)

    # Ecualizador del ampli (medios presentes, nada de "scoop") y gabinete 4x12.
    x = Pedalboard([
        PeakFilter(cutoff_frequency_hz=500, gain_db=-1.5, q=0.8),
        PeakFilter(cutoff_frequency_hz=1500, gain_db=2.0, q=0.9),
        HighpassFilter(cutoff_frequency_hz=80),
        PeakFilter(cutoff_frequency_hz=110, gain_db=3.0, q=1.2),   # golpe del parlante
        PeakFilter(cutoff_frequency_hz=2600, gain_db=3.0, q=1.5),  # presencia del cono
        LowpassFilter(cutoff_frequency_hz=5500),
        LowpassFilter(cutoff_frequency_hz=5500),                   # caída fuerte, como un parlante real
        PeakFilter(cutoff_frequency_hz=8000, gain_db=-6.0, q=1.0),
    ])(x, sr)
    return (x * desde_db(nivel - nivel_activo(x))).astype(np.float32)


# ---------------------------------------------------------------- bajo


def bajo_gruñon(audio: np.ndarray, cantidad: float = 0.5, sr: int = SR_TRABAJO) -> np.ndarray:
    """Distorsión en paralelo: graves limpios y firmes + medios saturados que se escuchan en la pared de guitarras."""
    nivel = nivel_activo(audio)
    x = audio / (np.max(np.abs(audio)) + 1e-12)
    medios = Pedalboard([HighpassFilter(cutoff_frequency_hz=300)])(x.astype(np.float32), sr)
    medios = np.tanh(medios * desde_db(12 + 12 * cantidad))
    medios = Pedalboard([
        LowpassFilter(cutoff_frequency_hz=3200),
        PeakFilter(cutoff_frequency_hz=1000, gain_db=3, q=1.0),
    ])(medios.astype(np.float32), sr)
    medios *= desde_db(nivel_activo(x) - nivel_activo(medios) - 6 + 6 * cantidad)
    salida = x + medios
    return (salida * desde_db(nivel - nivel_activo(salida))).astype(np.float32)


# ---------------------------------------------------------------- batería


def realzar_ataque(audio: np.ndarray, ataque_db: float = 4.0, sr: int = SR_TRABAJO) -> np.ndarray:
    """Transient shaper: sube el 'golpe' del palo sin subir el cuerpo del tambor."""
    mono = np.abs(a_mono(audio))
    rapida = maximum_filter1d(uniform_filter1d(mono, int(sr * 0.001)), int(sr * 0.002))
    lenta = uniform_filter1d(mono, int(sr * 0.03))
    exceso = np.clip(db(rapida + 1e-9) - db(lenta + 1e-9), 0, 12) / 12  # 0..1 en el ataque
    g = desde_db_arr(ataque_db * uniform_filter1d(exceso, int(sr * 0.003)))
    return (audio * g).astype(np.float32)


def desde_db_arr(d: np.ndarray) -> np.ndarray:
    return 10 ** (d / 20)


def sample_bombo(sr: int = SR_TRABAJO) -> np.ndarray:
    """Bombo seco y con pegada, afinado bajo, con 'click' de parche (estilo punk 70s/80s)."""
    t = np.arange(int(0.45 * sr)) / sr
    frec = 52 + 110 * np.exp(-t * 35)
    cuerpo = np.sin(2 * np.pi * np.cumsum(frec) / sr) * np.exp(-t * 7)
    rng = np.random.default_rng(7)
    click = rng.standard_normal(len(t)) * np.exp(-t * 400) * 0.35
    click = np.diff(click, prepend=0)
    s = cuerpo + click
    return (s / np.max(np.abs(s)))[None, :].astype(np.float32)


def sample_caja(sr: int = SR_TRABAJO) -> np.ndarray:
    """Caja con 'crack': tono de parche + bordonas (ruido) más largas."""
    t = np.arange(int(0.35 * sr)) / sr
    tono = (np.sin(2 * np.pi * 185 * t) + 0.5 * np.sin(2 * np.pi * 330 * t)) * np.exp(-t * 28)
    rng = np.random.default_rng(11)
    ruido = rng.standard_normal(len(t)) * np.exp(-t * 14)
    ruido = Pedalboard([HighpassFilter(cutoff_frequency_hz=1500), LowpassFilter(cutoff_frequency_hz=9000)])(
        ruido[None, :].astype(np.float32), sr)[0]
    s = 0.8 * tono + 0.7 * ruido
    return (s / np.max(np.abs(s)))[None, :].astype(np.float32)


def detectar_golpes(audio: np.ndarray, sr: int = SR_TRABAJO, separacion_ms: float = 60,
                    sensibilidad_db: float = 24) -> tuple[np.ndarray, np.ndarray]:
    """Momento en que arranca cada golpe y su fuerza (0..1).

    Un golpe es un salto brusco (+6 dB) respecto de lo que venía sonando en los 50 ms
    anteriores; así la cola del tambor y el sangrado de otros tambores no disparan el sampler.
    """
    env = uniform_filter1d(np.abs(a_mono(audio)), max(1, int(sr * 0.001)))
    pico = float(np.max(env)) + 1e-12
    ventana = int(sr * 0.05)
    hueco = int(sr * 0.003)
    previo = maximum_filter1d(env, size=ventana, origin=(ventana - 1) // 2)  # máx. de [n-50ms, n]
    previo = np.concatenate([np.full(hueco, previo[0]), previo[:-hueco]])
    candidato = (env > 2 * previo) & (env > pico * desde_db(-sensibilidad_db))
    inicios, fuerza, ultimo = [], [], -10 ** 9
    for i in np.flatnonzero(candidato):
        if i - ultimo < sr * separacion_ms / 1000:
            continue
        ultimo = i
        # El arranque real está un poco antes: donde la señal empieza a subir.
        a = max(0, i - int(sr * 0.005))
        sube = np.flatnonzero(env[a:i + 1] > previo[i] * 1.2)
        inicios.append(a + (sube[0] if len(sube) else 0))
        fuerza.append(float(np.max(env[i:i + int(sr * 0.015)])) / pico)
    return np.array(inicios, dtype=int), np.array(fuerza)


def reforzar_con_sample(audio: np.ndarray, sample: np.ndarray, mezcla: float = 0.5,
                        sr: int = SR_TRABAJO) -> tuple[np.ndarray, int]:
    """Sampler (como Slate Trigger): dispara un sample en cada golpe y lo mezcla con el tambor real.

    mezcla 0..1 = cuánto del sample (0.5 = mitad y mitad). Devuelve (audio, cantidad de golpes).
    """
    inicios, fuerza = detectar_golpes(audio, sr)
    if len(inicios) == 0:
        return audio, 0
    capa = np.zeros(audio.shape[1], dtype=np.float32)
    s = a_mono(sample)
    for i, f in zip(inicios, fuerza):
        n = min(len(s), len(capa) - i)
        capa[i:i + n] += s[:n] * f ** 1.5  # curva de dinámica: los golpes suaves siguen suaves
    capa = np.vstack([capa] * audio.shape[0])
    capa *= desde_db(nivel_activo(audio) - nivel_activo(capa))
    return ((1 - mezcla) * audio + mezcla * capa).astype(np.float32), len(inicios)


def cargar_sample(ruta: Path | None, por_defecto) -> np.ndarray:
    return cargar(ruta) if ruta else por_defecto()


# ---------------------------------------------------------------- voz


def eco_corto(audio: np.ndarray, ms: float = 110, nivel_db: float = -12, sr: int = SR_TRABAJO) -> np.ndarray:
    """Slapback: una sola repetición corta, oscura y filtrada (voz de rock de los 50 a los 70)."""
    n = int(sr * ms / 1000)
    rep = np.pad(audio, ((0, 0), (n, 0)))[:, : audio.shape[1]]
    rep = Pedalboard([HighpassFilter(cutoff_frequency_hz=400), LowpassFilter(cutoff_frequency_hz=3500)])(
        rep.astype(np.float32), sr)
    return (audio + rep * desde_db(nivel_db)).astype(np.float32)
