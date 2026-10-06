"""Genera pistas sintéticas de una 'banda' para probar meazclador sin grabaciones reales.

    python -m meazclador.demo demo/pistas
    python -m meazclador mezclar demo/pistas --afinar 0.5 --tonalidad Am
"""

import sys
from pathlib import Path

import numpy as np
import soundfile as sf

SR = 44100
BPM = 110
DUR = 16.0
rng = np.random.default_rng(1)
n = int(SR * DUR)
t = np.arange(n) / SR
negra = 60 / BPM


def golpes(tiempos, sonido):
    y = np.zeros(n)
    for s in tiempos:
        i = int(s * SR)
        k = min(len(sonido), n - i)
        y[i:i + k] += sonido[:k]
    return y


def bombo():
    tt = np.arange(int(0.4 * SR)) / SR
    f = 50 + 120 * np.exp(-tt * 40)
    return np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-tt * 9)


def caja():
    tt = np.arange(int(0.3 * SR)) / SR
    return (0.6 * rng.standard_normal(len(tt)) * np.exp(-tt * 18)
            + 0.5 * np.sin(2 * np.pi * 190 * tt) * np.exp(-tt * 25))


def hihat():
    tt = np.arange(int(0.08 * SR)) / SR
    ruido = np.diff(rng.standard_normal(len(tt) + 1))
    return 0.3 * ruido * np.exp(-tt * 60)


def nota(f, dur, onda="saw"):
    tt = np.arange(int(dur * SR)) / SR
    fase = 2 * np.pi * f * tt
    y = 2 * ((f * tt) % 1) - 1 if onda == "saw" else np.sin(fase)
    env = np.minimum(1, tt / 0.01) * np.exp(-tt * 1.5)
    return y * env


def main(destino: Path):
    destino.mkdir(parents=True, exist_ok=True)
    pulsos = np.arange(0, DUR - 0.5, negra)
    sf.write(destino / "01_Kick.wav", 0.5 * golpes(pulsos[::2], bombo()), SR)
    sf.write(destino / "02_Snare.wav", 0.4 * golpes(pulsos[1::2], caja()) + 0.02 * golpes(pulsos[::2], bombo()), SR)
    sf.write(destino / "03_HH.wav", golpes(np.arange(0, DUR - 0.5, negra / 2), hihat()), SR)

    acordes = [(110.0, [220.0, 261.6, 329.6]), (87.3, [174.6, 220.0, 261.6]),
               (130.8, [261.6, 329.6, 392.0]), (98.0, [196.0, 246.9, 293.7])]
    bajo = np.zeros(n)
    gtr_l, gtr_r = np.zeros(n), np.zeros(n)
    compas = 4 * negra
    for c in range(int(DUR / compas)):
        raiz, acorde = acordes[c % 4]
        for b in range(8):
            i = int((c * compas + b * negra / 2) * SR)
            s = nota(raiz, negra / 2)
            bajo[i:i + len(s)] += s[: n - i]
        i = int(c * compas * SR)
        for desafino, gtr in ((1.0, gtr_l), (1.003, gtr_r)):
            s = sum(nota(f * desafino, compas) for f in acorde)
            s = np.tanh(3 * s)
            gtr[i:i + len(s)] += s[: n - i]
    sf.write(destino / "04_Bajo.wav", 0.4 * bajo, SR)
    sf.write(destino / "05_Gtr_L.wav", 0.2 * gtr_l, SR)
    sf.write(destino / "06_Gtr_R.wav", 0.2 * gtr_r, SR)

    # Voz: armónicos con formantes, vibrato y algo desafinada (+30/-40 cents).
    melodia = [(440.0, 0.3), (392.0, -0.4), (329.6, 0.25), (440.0, -0.3)]
    voz = np.zeros(n)
    for c in range(1, int(DUR / compas)):
        f, cents = melodia[c % 4]
        tt = np.arange(int(compas * 0.85 * SR)) / SR
        f0 = f * 2 ** (cents / 12) * (1 + 0.006 * np.sin(2 * np.pi * 5.5 * tt))
        fase = 2 * np.pi * np.cumsum(f0) / SR
        s = sum(np.sin(k * fase) / k * np.exp(-((k * f - 700) / 900) ** 2) for k in range(1, 20))
        s *= np.minimum(1, tt / 0.05) * np.minimum(1, (tt[-1] - tt) / 0.1)
        ese = rng.standard_normal(int(0.12 * SR))
        ese = np.diff(np.diff(ese, prepend=0), prepend=0) * 0.3
        i = int(c * compas * SR)
        voz[i:i + len(s)] += s[: n - i]
        voz[i:i + len(ese)] += ese[: n - i]
    sf.write(destino / "07_Voz.wav", 0.3 * voz / np.max(np.abs(voz)), SR)
    print(f"Pistas de prueba en {destino}")


if __name__ == "__main__":
    main(Path(sys.argv[1] if len(sys.argv) > 1 else "demo/pistas"))
