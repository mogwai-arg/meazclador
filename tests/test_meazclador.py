import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from meazclador.afinacion import escala
from meazclador.analisis import polaridad_invertida, rol_por_nombre
from meazclador.audio import lufs, pico_real
from meazclador.dinamica import de_esser
from meazclador.mezcla import Opciones, exportar, mezclar


@pytest.mark.parametrize(
    "nombre,rol",
    [
        ("01_Kick In.wav", "bombo"),
        ("Bombo.wav", "bombo"),
        ("snare_top.wav", "caja"),
        ("OH L.wav", "overheads"),
        ("Bajo DI.wav", "bajo"),
        ("Gtr1.wav", "guitarra"),
        ("guitarra_ritmica.wav", "guitarra"),
        ("Lead Vocal.wav", "voz"),
        ("Backing Vocals.wav", "coros"),
        ("Voz principal.wav", "voz"),
        ("Piano.wav", "teclado"),
        ("Tom 2.wav", "toms"),
        ("pista_rara.wav", None),
    ],
)
def test_rol_por_nombre(nombre, rol):
    assert rol_por_nombre(nombre) == rol


def test_escala():
    assert escala(None) is None
    assert sorted(escala("Am")) == [0, 2, 4, 5, 7, 9, 11]  # mismas notas que Do mayor
    assert sorted(escala("La menor")) == sorted(escala("C"))
    assert 6 in escala("G") and 5 not in escala("G")
    assert 10 in escala("F") and 11 not in escala("F")
    with pytest.raises(ValueError):
        escala("H#z")


def test_polaridad():
    rng = np.random.default_rng(0)
    x = rng.standard_normal((1, 48000)).astype(np.float32)
    retrasado = np.roll(x, 20, axis=1)
    assert polaridad_invertida(-retrasado, x)
    assert not polaridad_invertida(retrasado, x)


def test_de_esser_no_cambia_senal_sin_eses():
    t = np.arange(48000) / 48000
    x = (0.3 * np.sin(2 * np.pi * 220 * t))[None, :].astype(np.float32)
    y, _ = de_esser(x)
    assert np.max(np.abs(y - x)) < 1e-3


def test_mezcla_completa(tmp_path):
    import generar_demo

    generar_demo.main(tmp_path / "pistas")
    res = mezclar(tmp_path / "pistas", Opciones(afinar=0.5, tonalidad="Am"), avisar=lambda _: None)
    assert res.master.shape[0] == 2
    assert np.isfinite(res.master).all()
    assert abs(lufs(res.master) - (-14.0)) < 0.5
    assert pico_real(res.master) <= -0.9
    roles = {p.nombre: p.rol for p in res.pistas}
    assert roles["07_Voz.wav"] == "voz" and roles["01_Kick.wav"] == "bombo"
    guitarras = [p.pan for p in res.pistas if p.rol == "guitarra"]
    assert sorted(guitarras) == [-0.8, 0.8]

    rutas = exportar(res, tmp_path / "salida")
    assert all(r.exists() for r in rutas)
    assert "INFORME DE MEZCLA" in rutas[2].read_text(encoding="utf-8")
