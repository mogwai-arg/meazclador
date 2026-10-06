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
    ("sala", ["room", "ambiente", "amb", "sala"]),
    ("overheads", ["oh", "overhead", "overheads", "over", "platos", "cymbal", "cymbals"]),
    ("bajo", ["bass", "bajo", "bajista", "contrabajo", "sub"]),
    ("guitarra", ["guit", "gtr", "gt", "guitar", "guitarra", "guitarras", "viola", "acustica", "electrica"]),
    ("teclado", ["key", "keys", "piano", "synth", "sinte", "teclado", "teclados", "organ", "organo", "rhodes", "pad"]),
    ("voz", ["vox", "voz", "vocal", "vocals", "lead", "cantante", "voice", "canto"]),
]

GRUPO_BATERIA = {"bombo", "caja", "hihat", "toms", "overheads", "sala"}


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
    silenciada: bool = False  # micrófono que en este tema sólo capta lo que se cuela (no canta)
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


def segundos_de_canto(audio: np.ndarray, sr: int = SR_TRABAJO, sobre_fondo_db: float = 8) -> float:
    """Cuántos segundos la pista está claramente (8 dB) por encima de su fondo: lo que se cuela de la
    banda. Sirve aunque alguien cante una sola frase corta en todo el tema."""
    r = rms_corto(audio, sr, 50)
    fondo = np.percentile(r, 10)  # las pausas: sólo lo que se cuela (aunque la voz cante casi todo el tema)
    arriba = np.append(r > fondo + sobre_fondo_db, False)
    # Cantar son frases (tramos seguidos); lo que se cuela de la batería son golpes sueltos y cortos.
    total, inicio = 0, None
    for i, a in enumerate(arriba):
        if a and inicio is None:
            inicio = i
        elif not a and inicio is not None:
            if i - inicio >= 8:  # 0.4 s o más
                total += i - inicio
            inicio = None
    return total * 0.05


def solo_sangrado(audio: np.ndarray, sr: int = SR_TRABAJO, minimo_s: float = 0.5) -> bool:
    """Un micrófono de voz donde nadie canta en este tema: en todo el tema no tiene ni medio segundo
    de frase por encima de lo que se cuela de la banda. Se decide tema por tema: en otro tema puede
    cantar. Si igual se equivoca, se reactiva en la pestaña 3."""
    return segundos_de_canto(audio, sr) < minimo_s


def actividad_de_canto(audio: np.ndarray, sr: int = SR_TRABAJO) -> float:
    """Fracción del tema (0..1) en la que esta pista de voz está cantando.

    Se mide contra el nivel de canto de la propia pista (sus partes más fuertes): el sonido de la
    batería y las guitarras que se cuela en el micrófono queda bastante más abajo y no cuenta.
    """
    r = rms_corto(audio, sr, 50)
    referencia = np.percentile(r, 95)
    if referencia < -60 or solo_sangrado(audio, sr):
        return 0.0  # sin canto: nivel parejo de lo que se cuela, no frases
    canta = (r > referencia - 12).astype(float)
    # Las frases tienen respiraciones y consonantes: se rellenan huecos de hasta ~0.5 s.
    canta = uniform_filter1d(canta, size=10) > 0.25
    return float(np.mean(canta))


ROLES_VOZ = ("voz", "coros")


def elegir_voz_principal(pistas: list[Pista], margen: float = 1.3, diferencia_s: float = 10.0
                         ) -> tuple[bool, str | None]:
    """Detecta si en este tema una pista de coros hace de voz principal (y al revés).

    La voz principal canta más que los coros. Se cuentan los segundos de frases que sobresalen
    claramente de lo que se cuela de la banda (ver `segundos_de_canto`): un micrófono de voz con
    mucha banda colada no parece "cantar todo el tiempo". Si la pista llamada coro canta `margen`
    veces más (y al menos `diferencia_s` segundos más) que la llamada voz, se intercambian los
    papeles. Devuelve (cambió, explicación); la explicación siempre dice cuánto canta cada pista.
    """
    voces = [p for p in pistas if p.rol == "voz" and not p.silenciada]
    coros = [p for p in pistas if p.rol == "coros" and not p.silenciada]
    if not voces or not coros:
        return False, None
    canto = {id(p): segundos_de_canto(p.audio) for p in voces + coros}
    detalle = ", ".join(f"'{p.nombre}' {canto[id(p)]:.0f} s" for p in voces + coros)
    principal = max(voces, key=lambda p: canto[id(p)])
    candidato = max(coros, key=lambda p: canto[id(p)])
    s_voz, s_coro = canto[id(principal)], canto[id(candidato)]
    if s_coro < s_voz * margen or s_coro - s_voz < diferencia_s:
        return False, (f"Cuánto canta cada pista de voz: {detalle}. Voz principal: '{principal.nombre}'. "
                       "Si en este tema canta otra, elegila en la pestaña 3 · Retocar.")
    _poner_voz_principal(pistas, candidato)
    return True, (f"Voz principal detectada: '{candidato.nombre}' (cuánto canta cada pista: {detalle}). "
                  "Si está mal, elegí la correcta en la pestaña 3 · Retocar.")


def _poner_voz_principal(pistas: list[Pista], elegida: Pista) -> None:
    elegida.silenciada = False  # si la eligieron a mano, tiene que sonar
    for p in pistas:
        if p.rol in ROLES_VOZ and p is not elegida and p.rol == "voz":
            p.rol, p.rol_por = "coros", "sonido"
            p.notas.append("En este tema hace coros: se la trata como coro.")
    if elegida.rol != "voz":
        elegida.rol, elegida.rol_por = "voz", "sonido"
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


# ---------------------------------------------------------------- verificación por contenido


def silenciar_voces_vacias(pistas: list[Pista]) -> list[str]:
    """Micrófonos de voz o coro que en este tema no cantan: se silencian (sólo sumarían ruido y banda)."""
    notas = []
    for p in pistas:
        if p.rol in ROLES_VOZ and solo_sangrado(p.audio):
            p.silenciada = True
            p.notas.append(f"En este tema no canta (en ningún momento sobresale de lo que se cuela de la banda). "
                           "Silenciada sólo en este tema; se puede reactivar en la pestaña 3.")
            notas.append(f"'{p.nombre}' no canta en este tema: silenciada (se puede reactivar en la pestaña 3).")
    return notas


def _golpes(audio: np.ndarray, sr: int = SR_TRABAJO) -> np.ndarray:
    from scipy.signal import find_peaks

    env = uniform_filter1d(np.abs(a_mono(audio)), max(1, int(sr * 0.003)))
    picos, _ = find_peaks(env, height=float(np.max(env)) * 10 ** (-15 / 20), distance=int(sr * 0.08))
    return picos


def _perfil_tambor(audio: np.ndarray, bombo: np.ndarray, sr: int = SR_TRABAJO) -> tuple[float, float, float]:
    """(golpes por segundo, fracción que coincide con el bombo, centroide en los golpes)."""
    picos = _golpes(audio, sr)
    if len(picos) < 4:
        return 0.0, 1.0, 0.0
    duracion = audio.shape[1] / sr
    coinciden = float(np.mean([np.min(np.abs(bombo - p)) < sr * 0.015 for p in picos])) if len(bombo) else 0.0
    mono = a_mono(audio)
    tramos = np.concatenate([mono[p:p + int(0.06 * sr)] for p in picos[:300]])
    f, pot = welch(tramos, sr, nperseg=2048)
    return len(picos) / duracion, coinciden, float(np.sum(f * pot) / (np.sum(pot) + 1e-20))


def _parece_redoblante(golpes_s: float, con_bombo: float, centroide: float) -> bool:
    # El redoblante marca el ritmo (golpes regulares) y cae entre los golpes del bombo. Su sonido
    # se centra entre ~150 Hz (micrófono opaco, mucho cuerpo) y ~4 kHz (mucho 'crack'); un hi-hat
    # real está más arriba y acompaña al bombo.
    return 0.5 <= golpes_s <= 5 and con_bombo < 0.25 and 120 <= centroide <= 4000


def verificar_redoblante(pistas: list[Pista]) -> str | None:
    """Comprueba que la pista tratada como caja sea de verdad el redoblante.

    En consolas en vivo los canales a veces quedan con otro nombre (por ejemplo, el redoblante
    grabado en el canal 'hi hat'). Si la 'caja' no se comporta como redoblante y otra pista de
    batería sí, se corrigen los papeles.
    """
    bombos = [p for p in pistas if p.rol == "bombo"]
    if not bombos:
        return None
    golpes_bombo = _golpes(bombos[0].audio)
    candidatas = [p for p in pistas if p.rol in ("caja", "hihat", "toms")]
    perfiles = {id(p): _perfil_tambor(p.audio, golpes_bombo) for p in candidatas}
    cajas = [p for p in candidatas if p.rol == "caja"]
    if any(_parece_redoblante(*perfiles[id(p)]) for p in cajas):
        return None
    otras = [p for p in candidatas if p.rol != "caja" and _parece_redoblante(*perfiles[id(p)])]
    if not otras:
        return None
    redoblante = max(otras, key=lambda p: perfiles[id(p)][0])
    g, c, cent = perfiles[id(redoblante)]
    for p in cajas:
        p.rol = "toms" if perfiles[id(p)][0] < 0.5 else "otros"
        p.rol_por = "sonido"
        p.notas.append(f"Se llama como redoblante pero casi no golpea ({perfiles[id(p)][0]:.1f} golpes/s): "
                       f"se la trata como {p.rol}.")
    anterior = redoblante.rol
    redoblante.rol, redoblante.rol_por = "caja", "sonido"
    redoblante.notas.append(f"Por cómo suena es el REDOBLANTE ({g:.1f} golpes/s, {c:.0%} junto al bombo, "
                            f"cuerpo en {cent:.0f} Hz), no {anterior}: se la trata como caja.")
    return (f"Redoblante detectado en '{redoblante.nombre}' (golpea entre los golpes del bombo); "
            "los nombres de los canales no coincidían.")


def separar_sala(pistas: list[Pista]) -> str | None:
    """Si hay dos overheads y uno casi no tiene platillos (sólo graves de la sala), es un micrófono
    de ambiente: se lo trata como 'sala' (más bajo y sin graves) para que no embarre."""
    overs = [p for p in pistas if p.rol == "overheads"]
    if len(overs) < 2:
        return None
    centros = {id(p): centroide(p.audio) for p in overs}
    brillante = max(centros.values())
    cambiadas = []
    for p in overs:
        if centros[id(p)] < 0.6 * brillante:
            p.rol, p.rol_por = "sala", "sonido"
            p.notas.append(f"Casi no capta platillos (centro de su sonido en {centros[id(p)]:.0f} Hz contra "
                           f"{brillante:.0f} Hz del otro overhead): se la trata como micrófono de sala.")
            cambiadas.append(p.nombre)
    return f"Tratadas como micrófono de sala: {', '.join(cambiadas)}." if cambiadas else None
