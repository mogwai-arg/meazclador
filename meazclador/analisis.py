"""Análisis de pistas: qué instrumento es, cómo suena y qué problemas tiene."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import correlate, stft, welch

from .audio import SR_TRABAJO, a_mono, nivel_activo, rms_corto

# Orden importante: lo más específico primero ("backing vocal" es coro, no voz).
PALABRAS_CLAVE: list[tuple[str, list[str]]] = [
    ("coros", ["coro", "coros", "bv", "bvs", "backing", "choir", "harmony", "armonia", "segunda"]),
    ("bombo", ["kick", "bombo", "bd", "kik", "bassdrum"]),
    ("caja", ["snare", "caja", "sn", "redo", "redoblante", "tambor", "tarola"]),
    ("hihat", ["hihat", "hh", "hat", "charles", "hi"]),
    ("toms", ["tom", "toms", "floor", "chancha", "rack"]),
    ("overheads", ["oh", "overhead", "overheads", "over", "platos", "cymbal", "cymbals", "room", "ambiente", "amb"]),
    ("bajo", ["bass", "bajo", "bajista", "contrabajo", "sub"]),
    ("guitarra", ["guit", "gtr", "gt", "guitar", "guitarra", "guitarras", "viola", "acustica", "electrica"]),
    ("teclado", ["key", "keys", "piano", "synth", "sinte", "teclado", "teclados", "organ", "organo", "rhodes", "pad"]),
    ("voz", ["vox", "voz", "vocal", "vocals", "lead", "cantante", "voice", "canto"]),
]

GRUPO_BATERIA = {"bombo", "caja", "hihat", "toms", "overheads"}


@dataclass
class Pista:
    nombre: str
    audio: np.ndarray
    rol: str = "otros"
    rol_por: str = "nombre"
    notas: list[str] = field(default_factory=list)
    resonancias: list[tuple[float, float]] = field(default_factory=list)  # (Hz, exceso dB)
    pan: float = 0.0
    envio_reverb: float = 0.0
    # Lo que se decide al combinar (se puede retocar sin volver a procesar):
    seco: np.ndarray | None = None  # la misma pista sin la sala de la habitación
    sacar_sala: float = 0.0  # cuánto de la versión seca usar por defecto (0..1)
    eco: tuple[float, float] | None = None  # slapback (ms, dB)

    @property
    def es_estereo(self) -> bool:
        return self.audio.shape[0] == 2


def _tokens(nombre: str) -> list[str]:
    base = Path(nombre).stem.lower()
    base = re.sub(r"([a-z])(\d)", r"\1 \2", base)
    return [t for t in re.split(r"[^a-z0-9áéíóúñ]+", base) if t]


def rol_por_nombre(nombre: str) -> str | None:
    tokens = _tokens(nombre)
    for rol, claves in PALABRAS_CLAVE:
        for t in tokens:
            for c in claves:
                # coincidencia exacta para claves cortas, prefijo para las largas
                if t == c or (len(c) >= 4 and t.startswith(c)):
                    return rol
    return None


def espectro(audio: np.ndarray, sr: int = SR_TRABAJO) -> tuple[np.ndarray, np.ndarray]:
    mono = a_mono(audio)
    f, p = welch(mono, sr, nperseg=8192)
    return f, 10 * np.log10(p + 1e-20)


def centroide(audio: np.ndarray, sr: int = SR_TRABAJO) -> float:
    f, p_db = espectro(audio, sr)
    p = 10 ** (p_db / 10)
    return float(np.sum(f * p) / (np.sum(p) + 1e-20))


def rol_por_sonido(audio: np.ndarray, sr: int = SR_TRABAJO) -> str:
    """Último recurso cuando el nombre del archivo no dice nada."""
    c = centroide(audio, sr)
    if c < 250:
        return "bajo"
    if c > 5000:
        return "hihat"
    return "otros"


def detectar_resonancias(
    audio: np.ndarray, sr: int = SR_TRABAJO, fmin: float = 150, fmax: float = 8000, maximo: int = 3
) -> list[tuple[float, float]]:
    """Busca picos estrechos que sobresalen *todo el tiempo* (zumbidos de sala, 'ring' de un parche).

    Las notas musicales también son picos, pero cambian: por eso se mira el percentil 25
    a lo largo del tiempo, y sólo se marca lo que está presente en ~75 % de los momentos.
    """
    mono = a_mono(audio)
    f, _, Z = stft(mono, sr, nperseg=8192, noverlap=4096)
    pot = 10 * np.log10(np.abs(Z) ** 2 + 1e-20)
    activos = pot.max(axis=0) > pot.max() - 50
    if activos.sum() < 4:
        return []
    pot = pot[:, activos]
    rejilla = np.linspace(np.log2(fmin), np.log2(fmax), 600)
    log_f = np.log2(np.maximum(f, 1))
    curvas = np.stack([np.interp(rejilla, log_f, pot[:, j]) for j in range(pot.shape[1])], axis=1)
    suaves = uniform_filter1d(curvas, size=61, axis=0, mode="nearest")  # ~1/2 octava
    exceso = np.percentile(curvas - suaves, 25, axis=1)
    candidatos = []
    for i in range(2, len(exceso) - 2):
        if exceso[i] > 6 and exceso[i] == exceso[i - 2 : i + 3].max():
            candidatos.append((float(2 ** rejilla[i]), float(exceso[i])))
    candidatos.sort(key=lambda x: -x[1])
    elegidos: list[tuple[float, float]] = []
    for hz, ex in candidatos:
        if all(abs(np.log2(hz / h)) > 1 / 3 for h, _ in elegidos):
            elegidos.append((hz, ex))
        if len(elegidos) == maximo:
            break
    return elegidos


def energia_bandas(audio: np.ndarray, sr: int = SR_TRABAJO) -> dict[str, float]:
    f, p_db = espectro(audio, sr)
    p = 10 ** (p_db / 10)
    bandas = {
        "graves (<120 Hz)": (20, 120),
        "medios-graves (120-500)": (120, 500),
        "medios (500-2k)": (500, 2000),
        "presencia (2k-6k)": (2000, 6000),
        "agudos (>6k)": (6000, 20000),
    }
    total = p.sum() + 1e-20
    return {k: float(10 * np.log10(p[(f >= a) & (f < b)].sum() / total + 1e-20)) for k, (a, b) in bandas.items()}


def polaridad_invertida(pista: np.ndarray, referencia: np.ndarray, sr: int = SR_TRABAJO) -> bool:
    """True si la pista está en contrafase con la referencia (p.ej. bombo vs overheads)."""
    n = min(pista.shape[1], referencia.shape[1], sr * 30)
    a = a_mono(pista)[:n]
    b = a_mono(referencia)[:n]
    if np.std(a) < 1e-6 or np.std(b) < 1e-6:
        return False
    max_lag = int(sr * 0.01)  # micrófonos a menos de ~3 m
    corr = correlate(a, b, mode="full", method="fft")
    centro = len(b) - 1
    ventana = corr[centro - max_lag : centro + max_lag + 1]
    norma = np.sqrt(np.sum(a**2) * np.sum(b**2))
    pos, neg = ventana.max() / norma, -ventana.min() / norma
    return neg > pos * 1.3 and neg > 0.1


def analizar(nombre: str, audio: np.ndarray) -> Pista:
    rol = rol_por_nombre(nombre)
    pista = Pista(nombre=nombre, audio=audio)
    if rol is None:
        pista.rol = rol_por_sonido(audio)
        pista.rol_por = "sonido"
    else:
        pista.rol = rol
    # Bajo, guitarras y teclados sostienen acordes cuyas notas parecerían resonancias;
    # en los tambores el tono propio del parche (debajo de 300 Hz) es parte del sonido.
    if pista.rol not in ("bajo", "guitarra", "teclado"):
        fmin = 300 if pista.rol in ("bombo", "caja", "toms") else 150
        pista.resonancias = detectar_resonancias(audio, fmin=fmin)
    nivel = nivel_activo(audio)
    if nivel < -45:
        pista.notas.append(f"Pista muy baja ({nivel:.0f} dBFS): puede tener ruido de fondo alto al subirla.")
    pico = float(np.max(np.abs(audio)))
    if pico >= 0.999:
        pista.notas.append("Hay recortes (clipping) en la grabación original; no se pueden deshacer del todo.")
    return pista


def actividad_de_canto(audio: np.ndarray, sr: int = SR_TRABAJO) -> float:
    """Fracción del tema (0..1) en la que esta pista de voz está cantando.

    Se mide contra el nivel de canto de la propia pista (sus partes más fuertes): el sonido de la
    batería y las guitarras que se cuela en el micrófono queda bastante más abajo y no cuenta.
    """
    r = rms_corto(audio, sr, 50)
    referencia = np.percentile(r, 95)
    if referencia < -60:
        return 0.0
    canta = (r > referencia - 12).astype(float)
    # Las frases tienen respiraciones y consonantes: se rellenan huecos de hasta ~0.5 s.
    canta = uniform_filter1d(canta, size=10) > 0.25
    return float(np.mean(canta))


ROLES_VOZ = ("voz", "coros")


def elegir_voz_principal(pistas: list[Pista], margen: float = 1.3) -> tuple[bool, str | None]:
    """Detecta si en este tema una pista de coros hace de voz principal (y al revés).

    La voz principal canta casi todo el tema; los coros entran en algunas partes. Si la pista
    llamada coro canta claramente más (`margen` veces) que la llamada voz, se intercambian
    los papeles. Devuelve (cambió, explicación). La explicación siempre dice cuánto canta
    cada pista, así se entiende la decisión.
    """
    voces = [p for p in pistas if p.rol == "voz"]
    coros = [p for p in pistas if p.rol == "coros"]
    if not voces or not coros:
        return False, None
    act = {id(p): actividad_de_canto(p.audio) for p in voces + coros}
    detalle = ", ".join(f"'{p.nombre}' {act[id(p)]:.0%}" for p in voces + coros)
    principal = max(voces, key=lambda p: act[id(p)])
    candidato = max(coros, key=lambda p: act[id(p)])
    a_voz, a_coro = act[id(principal)], act[id(candidato)]
    if a_coro < 0.25 or a_coro < a_voz * margen or a_coro - a_voz < 0.1:
        return False, (f"Cuánto canta cada pista de voz: {detalle}. Voz principal: '{principal.nombre}'. "
                       "Si en este tema canta otra, elegila en la pestaña 3 · Retocar.")
    _poner_voz_principal(pistas, candidato)
    return True, (f"Voz principal detectada: '{candidato.nombre}' (cuánto canta cada pista: {detalle}). "
                  "Si está mal, elegí la correcta en la pestaña 3 · Retocar.")


def _poner_voz_principal(pistas: list[Pista], elegida: Pista) -> None:
    for p in pistas:
        if p.rol in ROLES_VOZ and p is not elegida and p.rol == "voz":
            p.rol = "coros"
            p.notas.append("En este tema hace coros: se la trata como coro.")
    if elegida.rol != "voz":
        elegida.rol = "voz"
        elegida.notas.append("En este tema es la VOZ PRINCIPAL: se la trata como voz.")


def forzar_voz_principal(pistas: list[Pista], nombre: str) -> str:
    """El usuario eligió cuál pista es la voz principal en este tema."""
    vocales = [p for p in pistas if p.rol in ROLES_VOZ]
    elegida = next((p for p in vocales if p.nombre == nombre), None) or next(
        (p for p in vocales if nombre.lower() in p.nombre.lower()), None)
    if elegida is None:
        nombres = ", ".join(p.nombre for p in vocales) or "ninguna"
        raise ValueError(f"No encuentro la pista de voz '{nombre}'. Pistas de voz de este tema: {nombres}")
    _poner_voz_principal(pistas, elegida)
    return f"Voz principal elegida a mano: '{elegida.nombre}'."
