"""Tempo de cada tema, dónde se va de tempo la banda y un click para volver a grabarlo.

Todo con numpy/scipy (sin librerías de análisis pesadas, para que entre en el ejecutable):
envolvente de ataques -> tempo por autocorrelación -> golpes por programación dinámica (Ellis 2007)
-> tempo local cada 2 compases.
"""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass, field
from math import gcd
from pathlib import Path

import numpy as np
from scipy.ndimage import uniform_filter1d
from scipy.signal import resample_poly, stft

from .audio import Cancelado

SR = 22050
HOP = 128
FPS = SR / HOP
SR_CLICK = 44100
EXTENSIONES = {".mp3", ".wav", ".flac", ".aif", ".aiff", ".m4a", ".ogg"}
CARPETA_CLICKS = "clicks"
ARCHIVO_TEMPOS = "tempos.json"
VENTANA = 8  # golpes (2 compases) para medir el tempo local
DESVIO_PCT = 3.0  # a partir de cuánto se considera que se fue de tempo
DESVIO_MIN_GOLPES = 8  # y durante cuántos golpes seguidos
MAXIMO_PCT = 10.0  # más que esto en 2 compases no es el baterista: es que no se pudo seguir el tema ahí
JUNTAR_S = 2.0  # dos desvíos para el mismo lado separados por menos que esto son uno solo


@dataclass
class Desvio:
    inicio: float
    fin: float
    bpm: float  # el más lejano del tempo del tema
    porcentaje: float  # + más rápido, - más lento
    despues_de_corte: bool = False

    @property
    def mas_rapido(self) -> bool:
        return self.porcentaje > 0


@dataclass
class Analisis:
    archivo: str
    duracion: float
    bpm: float  # tempo del tema (mediana del tempo local, sin el arranque gradual)
    bpm_inicial: float  # tempo de los primeros compases
    golpes_rampa: int  # golpes que tarda en llegar al tempo (0 = arranca a tempo)
    cortes: list[tuple[float, int]] = field(default_factory=list)  # (segundo, golpes) en que la batería para
    desvios: list[Desvio] = field(default_factory=list)
    golpes: list[float] = field(default_factory=list)

    @property
    def gradual(self) -> bool:
        return self.golpes_rampa > 0

    def a_dict(self) -> dict:
        d = asdict(self)
        d.pop("golpes")
        return d


# ---------------------------------------------------------------- audio

def cargar(ruta: Path) -> np.ndarray:
    from pedalboard.io import AudioFile

    with AudioFile(str(ruta)) as f:
        x = f.read(f.frames)
        sr = int(f.samplerate)
    x = x.mean(0)
    g = gcd(sr, SR)
    return resample_poly(x, SR // g, sr // g).astype(np.float32)


def _espectro(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    _, _, X = stft(y, fs=SR, nperseg=1024, noverlap=1024 - HOP, boundary=None, padded=False)
    return np.abs(X), np.fft.rfftfreq(1024, 1 / SR)


def _flujo(A: np.ndarray, f: np.ndarray, desde: float, hasta: float) -> np.ndarray:
    M = np.log1p(100 * A[(f > desde) & (f < hasta)])
    return np.maximum(0, np.diff(M, axis=1)).sum(0)


def envolvente(A: np.ndarray, f: np.ndarray) -> np.ndarray:
    """Cuánto 'golpe' hay en cada instante (flujo espectral)."""
    flujo = _flujo(A, f, 30, 8000)
    flujo = np.maximum(flujo - uniform_filter1d(flujo, int(FPS)), 0)
    return flujo / (flujo.std() + 1e-9)


# ---------------------------------------------------------------- tempo y golpes

def tempo_global(env: np.ndarray, centro: float = 160) -> float:
    n = len(env)
    e = env - env.mean()
    ac = np.fft.irfft(np.abs(np.fft.rfft(e, 2 * n)) ** 2)[:n]
    lags = np.arange(int(FPS * 60 / 260), int(FPS * 60 / 50))
    bpm = 60 * FPS / lags
    v = ac[lags] * np.exp(-0.5 * np.log2(bpm / centro) ** 2)
    L = lags[int(np.argmax(v))]
    a, b, c = ac[L - 1], ac[L], ac[L + 1]
    if a - 2 * b + c != 0:
        L = L + 0.5 * (a - c) / (a - 2 * b + c)
    return 60 * FPS / L


def seguir_golpes(env: np.ndarray, bpm: float, firmeza: float = 100) -> np.ndarray:
    """Dónde cae cada golpe (segundos): programación dinámica que premia caer en ataques y
    castiga cambiar el tempo (Ellis 2007)."""
    P = 60 * FPS / bpm
    n = len(env)
    nucleo = np.exp(-0.5 * (np.arange(-int(P), int(P) + 1) * 32 / P) ** 2)
    local = np.convolve(env, nucleo, "same")
    puntaje = local.copy()
    previo = np.full(n, -1)
    rango = np.arange(-int(round(2 * P)), -int(round(P / 2)) + 1)
    castigo = -firmeza * np.log(-rango / P) ** 2
    for t in range(-rango[-1], n):
        z = t + rango
        ok = z >= 0
        candidatos = puntaje[z[ok]] + castigo[ok]
        k = int(np.argmax(candidatos))
        puntaje[t] = local[t] + candidatos[k]
        previo[t] = z[ok][k]
    cola = int(2 * P)
    t = n - cola + int(np.argmax(puntaje[-cola:]))
    golpes = []
    while t >= 0:
        golpes.append(t)
        t = previo[t]
    golpes = np.array(golpes[::-1])
    fuerza = local[golpes]
    ok = np.where(fuerza > 0.5 * np.median(fuerza))[0]  # sin los golpes 'en el aire' del principio y el final
    return golpes[ok[0]:ok[-1] + 1] / FPS


def _alternancia(golpes: np.ndarray, bombo: np.ndarray, caja: np.ndarray) -> float:
    """Ritmo de rock: bombo en 1 y 3, caja en 2 y 4. Positivo si a este tempo se cumple."""
    fr = np.round(golpes * FPS).astype(int)
    fr = fr[(fr > 2) & (fr < len(bombo) - 3)]
    if len(fr) < 16:
        return 0.0
    kv = np.array([bombo[i - 2:i + 3].max() for i in fr])
    cv = np.array([caja[i - 2:i + 3].max() for i in fr])
    n = len(kv) // 2 * 2
    kp, cp = kv[:n].reshape(-1, 2).mean(0), cv[:n].reshape(-1, 2).mean(0)
    if kp[1] > kp[0]:  # que el golpe 0 sea el del bombo
        kp, cp = kp[::-1], cp[::-1]
    return (kp[0] - kp[1]) / (kp.mean() + 1e-9) + (cp[1] - cp[0]) / (cp.mean() + 1e-9)


def elegir_octava(env, bombo, caja, bpm: float) -> float:
    """El tempo puede leerse al doble o a la mitad. Se elige aquel en el que el bombo y la caja
    alternan más claro (bombo en 1 y 3, caja en 2 y 4): a la mitad caen todos los golpes sobre el
    bombo, y al doble la caja deja de alternar. Si en ninguno alternan claro (bombo en todos los
    tiempos, por ejemplo), se queda con el más cercano a un tempo de rock (160)."""
    candidatos = [c for c in (bpm / 2, bpm, bpm * 2) if 60 <= c <= 260]
    puntajes = [_alternancia(seguir_golpes(env, c), bombo, caja) for c in candidatos]
    if max(puntajes) < 0.8:
        return min(candidatos, key=lambda c: abs(math.log2(c / 160)))
    return candidatos[int(np.argmax(puntajes))]


def tempo_local(golpes: np.ndarray, ventana: int = VENTANA) -> tuple[np.ndarray, np.ndarray]:
    """(centro de cada ventana en segundos, bpm). NaN donde los golpes no son confiables."""
    ibi = np.diff(golpes)
    P = np.median(ibi)
    centros, bpms = [], []
    for i in range(len(golpes) - ventana):
        g = golpes[i:i + ventana]
        d = np.diff(g)
        centros.append(g.mean())
        if d.min() < 0.8 * P or d.max() > 1.25 * P:
            bpms.append(np.nan)
        else:
            bpms.append(60 / np.polyfit(np.arange(ventana), g, 1)[0])
    return np.array(centros), np.array(bpms)


def _cortes(golpes: np.ndarray, bombo: np.ndarray, caja: np.ndarray) -> list[tuple[int, int]]:
    """Tramos (índice del primer golpe, cantidad) en los que la batería deja de tocar."""
    fr = np.round(golpes * FPS).astype(int).clip(2, len(bombo) - 3)
    act = np.array([bombo[i - 2:i + 3].max() + caja[i - 2:i + 3].max() for i in fr])
    act = np.convolve(act, np.ones(2) / 2, "same")
    bajo = act < 0.35 * np.median(act)
    tramos, i = [], 0
    while i < len(bajo):
        if bajo[i]:
            j = i
            while j < len(bajo) and bajo[j]:
                j += 1
            if j - i >= 2 and i > 4 and j < len(bajo) - 4:
                tramos.append((i, j - i))
            i = j
        else:
            i += 1
    return tramos


def analizar(ruta: Path, bpm: float | None = None, gradual: bool = False) -> Analisis:
    """bpm: forzar el tempo del tema (por ejemplo si se leyó al doble). gradual: el tema arranca
    más lento y acelera hasta tomar el tempo (el click hace lo mismo y después queda fijo)."""
    y = cargar(ruta)
    A, f = _espectro(y)
    env = envolvente(A, f)
    bombo = _flujo(A, f, 35, 110)
    caja = _flujo(A, f, 1500, 6000)
    bombo, caja = bombo / (np.median(bombo) + 1e-9), caja / (np.median(caja) + 1e-9)
    estimado = elegir_octava(env, bombo, caja, tempo_global(env)) if bpm is None else bpm
    golpes = seguir_golpes(env, estimado)
    tramos_corte = _cortes(golpes, bombo, caja)
    en_corte = np.zeros(len(golpes), bool)
    for i, n in tramos_corte:
        en_corte[max(0, i - 1):i + n + 1] = True

    centros, local = tempo_local(golpes)
    cerca_de_corte = np.array([en_corte[i:i + VENTANA].any() for i in range(len(centros))], bool)
    valido = ~np.isnan(local) & ~cerca_de_corte
    valido[:VENTANA] = False  # los primeros y últimos compases: intro y final sueltos
    valido[len(valido) - VENTANA:] = False
    medido = float(np.median(local[valido])) if valido.any() else estimado

    # Arranque gradual: los primeros compases más lentos y subiendo hasta el tempo del tema.
    validos_inicio = local[:2 * VENTANA][np.isfinite(local[:2 * VENTANA])]
    inicial = float(np.median(validos_inicio[:4])) if len(validos_inicio) else medido
    rampa = 0
    if gradual:
        valido[:VENTANA] = np.isfinite(local[:VENTANA])
        tempo_tema = float(np.nanmedian(local[valido][len(local[valido]) // 3:]))
        suave = _suavizar(local, valido)
        llega = np.where(suave >= tempo_tema * 0.985)[0]
        rampa = int(llega[0]) + VENTANA // 2 if len(llega) else len(golpes) // 4
        rampa = max(rampa, 4)
        resto = valido.copy()
        resto[:rampa] = False
        medido = float(np.median(local[resto])) if resto.any() else tempo_tema
    if bpm is not None:
        medido = bpm
    # lo que se aleja demasiado no es el baterista: el seguimiento se perdió (otro ritmo, un solo...)
    fuera_de_escala = np.abs(local / medido - 1) * 100 > MAXIMO_PCT
    fuera_de_escala[:rampa] = False
    valido &= ~fuera_de_escala
    suave = _suavizar(local, valido)

    desvios = _desvios(centros, suave, valido, medido, rampa, golpes, tramos_corte)
    return Analisis(archivo=Path(ruta).name, duracion=len(y) / SR, bpm=round(medido, 1),
                    bpm_inicial=round(inicial, 1), golpes_rampa=rampa,
                    cortes=[(round(float(golpes[i]), 2), n) for i, n in tramos_corte],
                    desvios=desvios, golpes=[float(g) for g in golpes])


def _suavizar(local: np.ndarray, valido: np.ndarray, n: int = 5) -> np.ndarray:
    x = np.where(valido, local, np.nan)
    out = np.full_like(x, np.nan)
    for i in range(len(x)):
        tramo = x[max(0, i - n // 2):i + n // 2 + 1]
        if np.isfinite(tramo).sum() >= 2:
            out[i] = np.nanmedian(tramo)
    return out


def _desvios(centros, suave, valido, objetivo, rampa, golpes, tramos_corte) -> list[Desvio]:
    dev = 100 * (suave / objetivo - 1)
    signo = np.where(np.isfinite(dev) & (np.abs(dev) >= DESVIO_PCT), np.sign(np.nan_to_num(dev)), 0)
    signo[:rampa] = 0
    # un par de ventanas dudosas en el medio no cortan un mismo desvío
    for i in range(1, len(signo) - 3):
        if signo[i] == 0 and signo[i - 1] != 0:
            for k in (1, 2):
                if signo[i + k] == signo[i - 1]:
                    signo[i:i + k] = signo[i - 1]
                    break
    reentradas = [i + n for i, n in tramos_corte]
    desvios, i = [], 0
    while i < len(signo):
        if signo[i] == 0:
            i += 1
            continue
        j = i
        while j < len(signo) and signo[j] == signo[i]:
            j += 1
        if j - i + VENTANA - 1 >= DESVIO_MIN_GOLPES:
            k = i + int(np.nanargmax(np.abs(np.where(np.isfinite(dev[i:j]), dev[i:j], 0))))
            desvios.append(Desvio(inicio=round(float(golpes[i]), 1),
                                  fin=round(float(golpes[min(len(golpes) - 1, j + VENTANA - 2)]), 1),
                                  bpm=round(float(suave[k]), 1), porcentaje=round(float(dev[k]), 1),
                                  despues_de_corte=any(0 <= i - r <= VENTANA for r in reentradas)))
        i = j
    # Después de un corte: ¿volvió al mismo tempo? (los primeros 2 compases)
    for r in reentradas:
        if r >= len(centros) or any(d.despues_de_corte and abs(d.inicio - golpes[r]) < 4 for d in desvios):
            continue
        v = suave[r:r + 2]
        v = v[np.isfinite(v)]
        if len(v) and abs(100 * (v.mean() / objetivo - 1)) >= DESVIO_PCT:
            desvios.append(Desvio(inicio=round(float(golpes[r]), 1),
                                  fin=round(float(golpes[min(len(golpes) - 1, r + VENTANA)]), 1),
                                  bpm=round(float(v.mean()), 1),
                                  porcentaje=round(float(100 * (v.mean() / objetivo - 1)), 1), despues_de_corte=True))
    desvios.sort(key=lambda d: d.inicio)
    juntos: list[Desvio] = []
    for d in desvios:
        ant = juntos[-1] if juntos else None
        if ant and ant.mas_rapido == d.mas_rapido and d.inicio - ant.fin <= JUNTAR_S:
            if abs(d.porcentaje) > abs(ant.porcentaje):
                ant.bpm, ant.porcentaje = d.bpm, d.porcentaje
            ant.fin = max(ant.fin, d.fin)
            ant.despues_de_corte = ant.despues_de_corte or d.despues_de_corte
        else:
            juntos.append(d)
    return juntos


# ---------------------------------------------------------------- click

def _golpe(frecuencia: float, amplitud: float, ms: float = 35) -> np.ndarray:
    t = np.arange(int(SR_CLICK * ms / 1000)) / SR_CLICK
    return amplitud * np.sin(2 * np.pi * frecuencia * t) * np.exp(-t / 0.008) * np.minimum(1, t / 0.0005)


FUERTE = _golpe(1800, 0.9)  # el 1 de cada compás
DEBIL = _golpe(1100, 0.6)


def tiempos_click(an: Analisis, bpm: float | None = None, cuenta: int = 8, por_compas: int = 4,
                  margen_compases: int = 2) -> np.ndarray:
    """Dónde suena cada golpe del click: la cuenta, el arranque gradual (si lo hay) y después
    el tempo fijo hasta el final, también a través de los cortes."""
    bpm = bpm or an.bpm
    golpes_tema = max(len(an.golpes), 1)
    total = cuenta + math.ceil(golpes_tema / por_compas) * por_compas + margen_compases * por_compas
    inicial = an.bpm_inicial if an.gradual else bpm
    rampa = min(an.golpes_rampa, golpes_tema) if an.gradual else 0
    t, tiempos = 0.0, []
    for i in range(total):
        tiempos.append(t)
        k = i - cuenta  # golpe del tema (negativo = cuenta)
        if k < 0:
            actual = inicial
        elif k < rampa:
            actual = inicial + (bpm - inicial) * (k + 1) / rampa
        else:
            actual = bpm
        t += 60 / actual
    return np.array(tiempos)


def armar_click(an: Analisis, bpm: float | None = None, cuenta: int = 8, por_compas: int = 4) -> np.ndarray:
    tiempos = tiempos_click(an, bpm, cuenta, por_compas)
    y = np.zeros(int((tiempos[-1] + 1) * SR_CLICK), np.float32)
    for i, t in enumerate(tiempos):
        g = FUERTE if i % por_compas == 0 else DEBIL
        p = int(round(t * SR_CLICK))
        y[p:p + len(g)] += g
    return y


def guardar_click(y: np.ndarray, destino: Path, formato: str = "mp3") -> Path:
    from pedalboard.io import AudioFile

    destino = destino.with_suffix("." + formato)
    destino.parent.mkdir(parents=True, exist_ok=True)
    if formato == "wav":
        import soundfile as sf

        sf.write(destino, y, SR_CLICK, subtype="PCM_16")
    else:
        with AudioFile(str(destino), "w", SR_CLICK, 1, quality=320) as f:
            f.write(y[np.newaxis, :])
    return destino


# ---------------------------------------------------------------- textos

def reloj(s: float) -> str:
    return f"{int(s // 60)}:{int(s % 60):02d}"


def bpm_click(an: Analisis, forzado: float | None = None) -> float:
    """El tempo del click: el que se eligió a mano, o el medido redondeado a un número entero."""
    return float(forzado) if forzado else float(math.floor(an.bpm + 0.5))


def describir_desvios(an: Analisis) -> list[str]:
    lineas = []
    for d in an.desvios:
        hacia = "se apura" if d.mas_rapido else "se atrasa"
        donde = "después del corte, " if d.despues_de_corte else ""
        lineas.append(f"{reloj(d.inicio)}-{reloj(d.fin)}  {donde}{hacia}: llega a {d.bpm:.0f} "
                      f"({d.porcentaje:+.0f} %)")
    return lineas


def resumen_desvios(an: Analisis) -> str:
    rapido = sum(d.mas_rapido for d in an.desvios)
    lento = len(an.desvios) - rapido
    if not an.desvios:
        return "Estable"
    partes = []
    if rapido:
        partes.append(f"{rapido} ↑")
    if lento:
        partes.append(f"{lento} ↓")
    return "  ".join(partes)


def informe(analisis: list[tuple[str, Analisis, float]], cuenta: int) -> str:
    """analisis: (título, análisis, bpm del click)."""
    lineas = [f"TEMPOS Y CLICKS (cada click: {cuenta} golpes de cuenta, el 1 de cada compás acentuado)", ""]
    lineas.append(f"{'#':>2}  {'Tema':36s} {'Click':>7}  {'Arranque':20s} {'Cortes':>6}  Se va de tempo")
    for i, (titulo, an, bpm) in enumerate(analisis, 1):
        arranque = f"gradual desde {an.bpm_inicial:.0f}" if an.gradual else "a tempo"
        lineas.append(f"{i:>2}  {titulo[:36]:36s} {bpm:>7g}  {arranque:20s} {len(an.cortes):>6}  "
                      f"{resumen_desvios(an)}")
    lineas += ["", f"DÓNDE SE VA DE TEMPO (más de {DESVIO_PCT:g} % durante 2 compases o más; tiempos del tema original)", ""]
    for titulo, an, bpm in analisis:
        detalle = describir_desvios(an)
        lineas.append(f"{titulo}  ({bpm:g} BPM){'  -> estable, sin desvíos' if not detalle else ''}")
        lineas += [f"    {d}" for d in detalle]
        if an.cortes:
            lineas.append("    cortes de batería en " + ", ".join(reloj(t) for t, _ in an.cortes) +
                          "  (el click sigue al mismo tempo)")
    return "\n".join(lineas) + "\n"


# ---------------------------------------------------------------- todo junto

def archivos_en(carpeta: Path) -> list[Path]:
    if not carpeta.is_dir():
        return []
    return sorted(p for p in carpeta.iterdir() if p.is_file() and p.suffix.lower() in EXTENSIONES
                  and not p.name.startswith("."))


def medir_y_armar(carpeta: Path, destino: Path | None = None, formato: str = "mp3", cuenta: int = 8,
                  bpms: dict[str, float] | None = None, arranques: dict[str, bool] | None = None,
                  clicks: bool = True, avisar=print, cancelar=lambda: False) -> list[dict]:
    from .convertir import titulo_y_orden

    archivos = archivos_en(carpeta)
    if not archivos:
        raise ValueError(f"No hay temas (MP3 o WAV) en {carpeta}")
    destino = destino or carpeta / CARPETA_CLICKS
    bpms, arranques = bpms or {}, arranques or {}
    filas, para_informe = [], []
    for i, ruta in enumerate(archivos, 1):
        if cancelar():
            raise Cancelado()
        avisar(f"=== {ruta.name} ({i}/{len(archivos)}) ===")
        forzado = bpms.get(ruta.name) or bpms.get(ruta.stem)
        gradual = bool(arranques.get(ruta.name, arranques.get(ruta.stem, False)))
        an = analizar(ruta, forzado, gradual)
        bpm = bpm_click(an, forzado)
        titulo, _ = titulo_y_orden(ruta.stem)
        fila = {**an.a_dict(), "titulo": titulo, "bpm_click": bpm, "click": None}
        if clicks:
            salida = guardar_click(armar_click(an, bpm, cuenta), destino / f"{ruta.stem}_click_{bpm:g}bpm", formato)
            fila["click"] = salida.name
            avisar(f"✔ {salida}")
        avisar(f"   {bpm:g} BPM · " + ("arranque gradual desde " + f"{an.bpm_inicial:.0f} · " if an.gradual else "")
               + f"se va de tempo: {resumen_desvios(an)}")
        filas.append(fila)
        para_informe.append((titulo, an, bpm))
    destino.mkdir(parents=True, exist_ok=True)
    (destino / "tempos.txt").write_text(informe(para_informe, cuenta), encoding="utf-8")
    (destino / ARCHIVO_TEMPOS).write_text(json.dumps({"cuenta": cuenta, "formato": formato, "temas": filas},
                                                     ensure_ascii=False, indent=1), encoding="utf-8")
    return filas
