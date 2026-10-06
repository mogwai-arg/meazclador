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


def _guitarra_directa(sr=48000, segundos=4):
    """Guitarra limpia por línea: cuerdas pulsadas (Karplus-Strong simplificado) con ataque de púa."""
    t = np.arange(int(sr * segundos)) / sr
    y = np.zeros_like(t)
    for i, f in enumerate([110, 146.8, 196, 246.9] * 2):
        a = int(i * 0.5 * sr)
        tt = t[: len(t) - a]
        y[a:] += sum(np.sin(2 * np.pi * f * k * tt) / k ** 1.5 for k in range(1, 12)) * np.exp(-tt * 3)
    return (0.3 * y / np.max(np.abs(y)))[None, :].astype(np.float32)


def test_amplificador_distorsiona_y_corta_agudos():
    from meazclador.analisis import energia_bandas
    from meazclador.efectos import amplificador, es_guitarra_directa, planitud_espectral

    di = _guitarra_directa()
    assert es_guitarra_directa(di)
    amp = amplificador(di, 0.8)
    assert np.isfinite(amp).all()
    assert planitud_espectral(amp) > 0.04  # la distorsión rellena el espectro entre armónicos
    assert not es_guitarra_directa(amp)  # una guitarra ya amplificada no se vuelve a amplificar
    assert energia_bandas(amp)["agudos (>6k)"] < -25  # el gabinete corta el 'fizz'


def test_sampler_respeta_cada_golpe():
    from meazclador.efectos import detectar_golpes, reforzar_con_sample, sample_bombo

    sr = 48000
    golpe = sample_bombo(sr)[0][: sr // 4]
    pista = np.zeros(sr * 4, dtype=np.float32)
    tiempos = [0.1, 0.6, 1.1, 1.6, 2.1, 2.6, 3.1]
    for i, t in enumerate(tiempos):
        fuerza = 1.0 if i % 2 == 0 else 0.5
        pista[int(t * sr): int(t * sr) + len(golpe)] += golpe * fuerza
    pista += 0.01 * np.random.default_rng(0).standard_normal(len(pista)).astype(np.float32)  # sangrado
    inicios, fuerzas = detectar_golpes(pista[None, :], sr)
    assert len(inicios) == len(tiempos)
    assert np.all(np.abs(inicios / sr - np.array(tiempos)) < 0.005)
    assert fuerzas[1] < fuerzas[0]
    salida, n = reforzar_con_sample(pista[None, :], sample_bombo(sr), 0.5, sr)
    assert n == len(tiempos) and np.isfinite(salida).all()


def test_afinar_solo_notas_muy_desafinadas():
    from meazclador.afinacion import afinar

    sr = 48000

    def nota(cents):
        t = np.arange(sr) / sr
        f0 = 440 * 2 ** (cents / 1200) * (1 + 0.006 * np.sin(2 * np.pi * 5.5 * t))
        return sum(np.sin(k * 2 * np.pi * np.cumsum(f0) / sr) / k for k in range(1, 10)) * 0.2

    pausa = np.zeros(int(sr * 0.4))
    x = np.concatenate([nota(15), pausa, nota(-20), pausa, nota(45)]).astype(np.float32)
    y, resumen = afinar(x[None, :], 0.85, "A", sr, tolerancia_cents=35)
    assert np.array_equal(y[0][: int(2.4 * sr)], x[: int(2.4 * sr)])  # las afinadas quedan intactas
    assert np.max(np.abs(y[0][int(2.9 * sr):] - x[int(2.9 * sr):])) > 0.1  # la desafinada se corrige
    assert "1 notas acomodadas" in resumen


def test_mezcla_punk(tmp_path):
    import soundfile as sf

    from meazclador import demo

    demo.main(tmp_path / "pistas")
    sf.write(tmp_path / "pistas" / "08_Guitarra_DI.wav", _guitarra_directa(demo.SR, demo.DUR)[0], demo.SR)
    res = mezclar(tmp_path / "pistas", Opciones(estilo="punk"), avisar=lambda _: None)
    assert np.isfinite(res.master).all()
    assert abs(lufs(res.master) - (-10.0)) < 0.5
    assert pico_real(res.master) <= -0.9
    notas = {p.nombre: " ".join(p.notas) for p in res.pistas}
    assert "Sampler" in notas["01_Kick.wav"] and "Sampler" in notas["02_Snare.wav"]
    assert "ampli británico" in notas["08_Guitarra_DI.wav"]
    assert "ya viene de un ampli" in notas["05_Gtr_L.wav"]
    assert "Distorsión en paralelo" in notas["04_Bajo.wav"]
    assert "slapback" in notas["07_Voz.wav"]
