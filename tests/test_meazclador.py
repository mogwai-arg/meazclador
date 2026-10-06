from pathlib import Path

import numpy as np
import pytest


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
    from meazclador import demo as generar_demo

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


def _sesion_simulada(carpeta: Path, tmp: Path) -> list[tuple[float, float]]:
    """Tres temas (las pistas de la demo) separados por charla en el micrófono de voz y ruido de sala."""
    from meazclador import demo as generar_demo
    import soundfile as sf

    generar_demo.main(tmp / "demo")
    sr = generar_demo.SR
    rng = np.random.default_rng(3)
    pausas = [6.0, 9.0, 7.0, 5.0]  # antes del 1º tema, entre temas y al final
    carpeta.mkdir(parents=True)
    tiempos, t = [], pausas[0]
    for i in range(3):
        tiempos.append((t, t + generar_demo.DUR))
        t += generar_demo.DUR + pausas[i + 1]
    for archivo in sorted((tmp / "demo").glob("*.wav")):
        tema, _ = sf.read(archivo)
        partes = []
        for i, pausa in enumerate(pausas):
            ruido = 0.002 * rng.standard_normal(int(pausa * sr))
            if "Voz" in archivo.name:  # alguien hablando entre temas
                ruido += 0.03 * np.sin(2 * np.pi * 180 * np.arange(len(ruido)) / sr) * (rng.random(len(ruido)) > 0.5)
            partes.append(ruido)
            if i < 3:
                partes.append(tema)
        sf.write(carpeta / archivo.name, np.concatenate(partes), sr, subtype="PCM_24")
    return tiempos


def test_detectar_y_cortar_sesion(tmp_path):
    import soundfile as sf

    from meazclador.mezcla import listar_pistas
    from meazclador.sesion import cortar, detectar_temas, energia

    sesion = tmp_path / "sesion"
    reales = _sesion_simulada(sesion, tmp_path)
    archivos = listar_pistas(sesion)
    temas, _ = detectar_temas(energia(archivos, avisar=lambda _: None), min_tema_s=10)
    assert len(temas) == 3
    for tema, (ini, fin) in zip(temas, reales):
        assert ini - 2.5 <= tema.inicio <= ini + 0.5
        assert fin - 0.5 <= tema.fin <= fin + 4

    carpetas = cortar(archivos, temas, tmp_path / "temas", avisar=lambda _: None)
    assert len(carpetas) == 3
    for carpeta, tema in zip(carpetas, temas):
        cortadas = sorted(carpeta.glob("*.wav"))
        assert [c.name for c in cortadas] == [a.name for a in archivos]
        info = sf.info(str(cortadas[0]))
        assert info.subtype == "PCM_24" and abs(info.frames / info.samplerate - tema.duracion) < 0.01


def test_leer_cortes():
    from meazclador.sesion import de_reloj, leer_cortes

    assert de_reloj("1:02:30") == 3750
    temas = leer_cortes("# comentario\n0:12  4:05  La primera\n4:40 8:55\n")
    assert [(t.inicio, t.fin, t.nombre) for t in temas] == [(12, 245, "La primera"), (280, 535, "tema_02")]
    assert len(leer_cortes("0:12-4:05, 4:40-8:55")) == 2
    with pytest.raises(ValueError):
        leer_cortes("5:00 4:00")


def test_lista_de_temas_ida_y_vuelta(tmp_path):
    from meazclador.sesion import Tema, escribir_lista, leer_cortes

    ruta = tmp_path / "temas.txt"
    escribir_lista([Tema(5, 245, "Help"), Tema(250.4, 400, "tema_02")], ruta)
    temas = leer_cortes(ruta.read_text(encoding="utf-8"))
    assert [(t.inicio, t.fin, t.nombre) for t in temas] == [(5, 245, "Help"), (250, 400, "tema_02")]


def test_cli_cortar_y_mezclar(tmp_path):
    from meazclador.cli import main

    sesion = tmp_path / "sesion"
    _sesion_simulada(sesion, tmp_path)
    assert main(["cortar", str(sesion), "--min-tema", "10", "--mezclar"]) == 0
    masters = sorted((sesion / "temas" / "masters").glob("*.wav"))
    assert [m.name for m in masters] == ["tema_01.wav", "tema_02.wav", "tema_03.wav"]
    assert (sesion / "temas" / "temas.txt").exists()
