"""Reproducción de fragmentos para escuchar antes de cortar."""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import numpy as np
import soundfile as sf


def _abrir_con_el_sistema(ruta: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(ruta)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    else:
        subprocess.Popen(["xdg-open", str(ruta)])


class Reproductor:
    """Toca un fragmento por la placa de sonido y sabe por dónde va.

    Si no hay forma de tocar directo (falta la placa o la librería), guarda el fragmento
    en un WAV temporal y lo abre con el reproductor del sistema.
    """

    def __init__(self) -> None:
        try:
            import sounddevice

            self._sd = sounddevice
        except Exception:  # sin PortAudio o sin placa de sonido
            self._sd = None
        self._desde = 0.0
        self._duracion = 0.0
        self._t0: float | None = None

    def reproducir(self, audio: np.ndarray, sr: int, desde_s: float) -> str | None:
        """audio (canales, n). Devuelve un aviso si tuvo que usar el reproductor del sistema."""
        self.parar()
        if self._sd is not None:
            try:
                self._sd.play(np.ascontiguousarray(audio.T), sr)
                self._desde, self._duracion, self._t0 = desde_s, audio.shape[1] / sr, time.monotonic()
                return None
            except Exception as e:
                aviso = f"No pude usar la placa de sonido ({e}); lo abro con el reproductor del sistema."
        else:
            aviso = "Abriendo el fragmento con el reproductor del sistema."
        ruta = Path(tempfile.gettempdir()) / "meazclador_escucha.wav"
        sf.write(str(ruta), audio.T, sr, subtype="PCM_16")
        _abrir_con_el_sistema(ruta)
        return aviso

    def parar(self) -> None:
        self._t0 = None
        if self._sd is not None:
            try:
                self._sd.stop()
            except Exception:
                pass

    def posicion(self) -> float | None:
        """Segundo de la sesión que está sonando, o None si no suena nada."""
        if self._t0 is None:
            return None
        transcurrido = time.monotonic() - self._t0
        if transcurrido >= self._duracion:
            self._t0 = None
            return None
        return self._desde + transcurrido
