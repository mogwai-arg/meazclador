"""Cortar una sesión larga (ensayo o show grabado en multipista) en canciones.

Los archivos de una sesión de 40 minutos pesan varios GB, así que nunca se cargan
enteros: se leen de a bloques, tanto para encontrar los temas como para cortarlos.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import soundfile as sf
from scipy.ndimage import uniform_filter1d

from .audio import Cancelado

PASO_S = 0.1  # resolución del análisis: 100 ms
BLOQUE_S = 30  # se lee de a 30 segundos por pista


@dataclass
class Tema:
    inicio: float  # segundos
    fin: float
    nombre: str = ""

    @property
    def duracion(self) -> float:
        return self.fin - self.inicio


def a_reloj(seg: float) -> str:
    m, s = divmod(int(round(seg)), 60)
    return f"{m}:{s:02d}"


def a_reloj_preciso(seg: float) -> str:
    """Con décimas, para que la lista conserve los bordes ajustados a mano: 3:05.4"""
    m, s = divmod(round(seg, 1), 60)
    return f"{int(m)}:{s:04.1f}"


def de_reloj(txt: str) -> float:
    """'3:45', '1:02:30' o '225' (segundos) -> segundos."""
    partes = [float(p) for p in txt.strip().split(":")]
    seg = 0.0
    for p in partes:
        seg = seg * 60 + p
    return seg


def info_pistas(archivos: list[Path]) -> tuple[int, float, list[str]]:
    """Devuelve (sample rate, duración en s, avisos) verificando que las pistas sean compatibles."""
    infos = [sf.info(str(a)) for a in archivos]
    avisos = []
    tasas = {i.samplerate for i in infos}
    if len(tasas) > 1:
        raise ValueError(f"Las pistas tienen distintas frecuencias de muestreo ({sorted(tasas)}); "
                         "exportalas todas igual desde la grabadora o el programa.")
    duraciones = [i.frames / i.samplerate for i in infos]
    if max(duraciones) - min(duraciones) > 1:
        avisos.append("Ojo: las pistas no duran lo mismo (diferencia de "
                      f"{max(duraciones) - min(duraciones):.1f} s). Si no arrancan todas juntas, "
                      "los cortes van a quedar desfasados.")
    return tasas.pop(), max(duraciones), avisos


def energia(archivos: list[Path], avisar=print, cancelar=lambda: False) -> np.ndarray:
    """Nivel (dB) de toda la banda junta, cada 100 ms, leyendo los archivos de a bloques.

    Se suman energías (no señales) para que dos micrófonos en contrafase no se anulen.
    """
    sr, duracion, _ = info_pistas(archivos)
    paso = int(sr * PASO_S)
    total = np.zeros(int(np.ceil(duracion / PASO_S)) + 1)
    for n, archivo in enumerate(archivos, 1):
        avisar(f"  Escuchando {archivo.name} ({n}/{len(archivos)})...")
        pos = 0
        with sf.SoundFile(str(archivo)) as f:
            for bloque in f.blocks(blocksize=paso * int(BLOQUE_S / PASO_S), dtype="float32", always_2d=True):
                if cancelar():
                    raise Cancelado()
                mono = bloque.mean(axis=1)
                ventanas = len(mono) // paso
                if ventanas == 0:
                    break
                e = np.mean(mono[: ventanas * paso].reshape(ventanas, paso) ** 2, axis=1)
                total[pos : pos + ventanas] += e
                pos += ventanas
    return 10 * np.log10(total + 1e-12)


def detectar_temas(
    nivel_db: np.ndarray,
    min_tema_s: float = 60,
    min_pausa_s: float = 4,
    sensibilidad: float = 0.45,
    previo_s: float = 1.0,
    cola_s: float = 3.0,
) -> tuple[list[Tema], float]:
    """Encuentra dónde toca la banda entera.

    Entre temas casi nunca hay silencio (se habla, se afina), pero el nivel baja mucho
    respecto de cuando suenan todos. El umbral se ubica entre el "ruido de fondo" y el
    nivel típico de la banda tocando; sensibilidad más baja = umbral más bajo.
    Devuelve (temas, umbral en dB).
    """
    suave = uniform_filter1d(nivel_db, size=int(3 / PASO_S), mode="nearest")
    piso, banda = np.percentile(suave, 15), np.percentile(suave, 90)
    umbral = piso + sensibilidad * (banda - piso)
    tocando = suave > umbral

    # Regiones donde se toca, uniendo cortes breves (un break, un final de estrofa).
    regiones: list[list[int]] = []
    inicio = None
    for i, t in enumerate(np.append(tocando, False)):
        if t and inicio is None:
            inicio = i
        elif not t and inicio is not None:
            regiones.append([inicio, i])
            inicio = None
    unidas: list[list[int]] = []
    for r in regiones:
        if unidas and (r[0] - unidas[-1][1]) * PASO_S < min_pausa_s:
            unidas[-1][1] = r[1]
        else:
            unidas.append(r)
    largas = [r for r in unidas if (r[1] - r[0]) * PASO_S >= min_tema_s]

    total = len(nivel_db) * PASO_S
    temas = []
    for i, (a, b) in enumerate(largas):
        ini, fin = a * PASO_S - previo_s, b * PASO_S + cola_s
        # el margen nunca invade la mitad de la pausa hacia el tema vecino
        if i > 0:
            ini = max(ini, (largas[i - 1][1] + a) / 2 * PASO_S)
        if i + 1 < len(largas):
            fin = min(fin, (b + largas[i + 1][0]) / 2 * PASO_S)
        temas.append(Tema(max(0.0, ini), min(total, fin), f"tema_{i + 1:02d}"))
    return temas, float(umbral)


def leer_cortes(texto: str) -> list[Tema]:
    """Lee una lista de cortes: una línea por tema, 'inicio fin [nombre]'.

    Ejemplo:
        0:12   4:05   Intro y primer tema
        4:40   8:55   La balada
    También acepta todo en una línea separado por comas: '0:12-4:05, 4:40-8:55'.
    Las líneas que empiezan con # se ignoran.
    """
    temas = []
    sin_comentarios = [linea.split("#", 1)[0] for linea in texto.splitlines()]
    lineas = ",".join(sin_comentarios).split(",")
    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue
        m = re.match(r"^([\d:.]+)\s*(?:-|\s)\s*([\d:.]+)\s*(.*)$", linea)
        if not m:
            raise ValueError(f"No entiendo la línea de cortes: '{linea}' (formato: 3:10 7:45 Nombre)")
        ini, fin = de_reloj(m.group(1)), de_reloj(m.group(2))
        if fin <= ini:
            raise ValueError(f"El tema '{linea}' termina antes de empezar.")
        temas.append(Tema(ini, fin, m.group(3).strip() or f"tema_{len(temas) + 1:02d}"))
    return temas


def escribir_lista(temas: list[Tema], ruta: Path) -> None:
    lineas = [
        "# Temas detectados. Podés corregir los tiempos, borrar líneas o cambiar los nombres,",
        "# y volver a cortar con:  meazclador cortar CARPETA --cortes este_archivo.txt",
        "# inicio  fin  nombre",
    ]
    lineas += [f"{a_reloj_preciso(t.inicio):>8}  {a_reloj_preciso(t.fin):>8}  {t.nombre}" for t in temas]
    ruta.write_text("\n".join(lineas) + "\n", encoding="utf-8")


def _nombre_carpeta(i: int, tema: Tema) -> str:
    limpio = re.sub(r"[^\w\- ]+", "", tema.nombre, flags=re.UNICODE).strip().replace(" ", "_")
    return f"{i:02d}_{limpio}" if limpio and not limpio.startswith("tema_") else f"tema_{i:02d}"


def cortar(archivos: list[Path], temas: list[Tema], destino: Path, avisar=print) -> list[Path]:
    """Escribe cada tema en su carpeta, con las pistas cortadas en los mismos puntos.

    Conserva el formato original (frecuencia de muestreo y bits) y agrega fundidos de
    10 ms en los bordes para que no haya clics.
    """
    carpetas = []
    for i, tema in enumerate(temas, 1):
        carpeta = destino / _nombre_carpeta(i, tema)
        carpeta.mkdir(parents=True, exist_ok=True)
        avisar(f"  {carpeta.name}: {a_reloj(tema.inicio)} a {a_reloj(tema.fin)} ({a_reloj(tema.duracion)})")
        for archivo in archivos:
            with sf.SoundFile(str(archivo)) as f:
                a = int(tema.inicio * f.samplerate)
                b = min(int(tema.fin * f.samplerate), f.frames)
                f.seek(min(a, f.frames))
                datos = f.read(max(0, b - a), dtype="float32", always_2d=True)
                n_fundido = min(len(datos) // 2, int(0.01 * f.samplerate))
                if n_fundido:
                    rampa = np.linspace(0, 1, n_fundido, dtype=np.float32)[:, None]
                    datos[:n_fundido] *= rampa
                    datos[-n_fundido:] *= rampa[::-1]
                sf.write(str(carpeta / archivo.name), datos, f.samplerate,
                         subtype=f.subtype, format=f.format)
        carpetas.append(carpeta)
    return carpetas


def fragmento(archivos: list[Path], desde_s: float, hasta_s: float) -> tuple[np.ndarray, int]:
    """Mezcla de monitoreo (todas las pistas sumadas) de un tramo, para escuchar antes de cortar.

    Lee sólo ese tramo de cada archivo. Devuelve (audio estéreo (2, n), sample rate).
    """
    sr = sf.info(str(archivos[0])).samplerate
    desde_s = max(0.0, desde_s)
    n = max(1, int((hasta_s - desde_s) * sr))
    mezcla = np.zeros((2, n), dtype=np.float32)
    for archivo in archivos:
        with sf.SoundFile(str(archivo)) as f:
            inicio = min(int(desde_s * f.samplerate), f.frames)
            f.seek(inicio)
            datos = f.read(min(n, f.frames - inicio), dtype="float32", always_2d=True).T
        if datos.shape[0] == 1:
            datos = np.vstack([datos, datos])
        mezcla[:, : datos.shape[1]] += datos[:2]
    pico = float(np.max(np.abs(mezcla)))
    if pico > 0:
        mezcla *= 0.9 / pico
    return mezcla, sr
