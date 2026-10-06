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
    assert [(t.inicio, t.fin, t.nombre) for t in temas] == [(5, 245, "Help"), (250.4, 400, "tema_02")]


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
    voz = next(p for p in res.pistas if p.nombre == "07_Voz.wav")
    assert voz.eco and voz.seco is not None and voz.sacar_sala > 0
    assert any("slapback" in n for n in res.notas_generales)
    assert any(n.startswith("Sacar sala") for n in res.notas_generales)


def test_fragmento_de_sesion(tmp_path):
    from meazclador.mezcla import listar_pistas
    from meazclador.sesion import fragmento

    sesion = tmp_path / "sesion"
    reales = _sesion_simulada(sesion, tmp_path)
    archivos = listar_pistas(sesion)
    audio, sr = fragmento(archivos, reales[0][0], reales[0][0] + 5)
    assert audio.shape == (2, 5 * sr)
    assert 0.85 < np.max(np.abs(audio)) <= 0.9 + 1e-6
    final, _ = fragmento(archivos, reales[-1][1] + 3, reales[-1][1] + 60)  # pasado el final: se corta
    assert final.shape[0] == 2 and np.isfinite(final).all()


def test_reproductor_sabe_por_donde_va(monkeypatch):
    import sys
    import types

    from meazclador import reproductor

    tocado = {}
    falso = types.SimpleNamespace(play=lambda datos, sr: tocado.update(n=len(datos), sr=sr),
                                  stop=lambda: tocado.update(parado=True))
    monkeypatch.setitem(sys.modules, "sounddevice", falso)
    r = reproductor.Reproductor()
    assert r.reproducir(np.zeros((2, 48000 * 3), dtype=np.float32), 48000, desde_s=100.0) is None
    assert tocado["n"] == 48000 * 3 and tocado["sr"] == 48000
    assert 100.0 <= r.posicion() < 101.0
    r.parar()
    assert r.posicion() is None and tocado["parado"]


def test_panel_de_sesion(tmp_path, monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        raiz = tk.Tk()
    except tk.TclError:
        pytest.skip("sin pantalla")
    import time

    from meazclador import gui, gui_sesion

    sesion = tmp_path / "sesion"
    reales = _sesion_simulada(sesion, tmp_path)
    avisos = []
    for nombre in ("showinfo", "showwarning", "showerror"):
        monkeypatch.setattr(gui.messagebox, nombre, lambda *a, n=nombre: avisos.append((n, a[1])))
        monkeypatch.setattr(gui_sesion.messagebox, nombre, lambda *a, n=nombre: avisos.append((n, a[1])))
    monkeypatch.setattr(gui_sesion.messagebox, "askyesno", lambda *a: True)
    monkeypatch.setattr(gui_sesion.simpledialog, "askstring", lambda *a, **k: "Help")

    app = gui.App(raiz)
    raiz.geometry("900x900")
    p = app.panel_sesion
    escuchado = []
    p.reproductor.reproducir = lambda audio, sr, desde: escuchado.append((desde, audio.shape[1] / sr))

    def esperar():
        raiz.update()
        while app.trabajando:
            raiz.update()
            time.sleep(0.02)
        raiz.update()

    try:
        p.sesion.set(str(sesion))
        p.min_tema.set(10)
        p.analizar()
        esperar()
        assert len(p.temas) == 3 and p.mapa.find_all()  # el mapa se dibujó

        # Sensibilidad muy alta: los temas se recalculan al instante (sin volver a leer los archivos).
        p.sensibilidad.set(0.95)
        p._redetectar()
        assert len(p.temas) != 3 or p.temas[0].inicio > reales[0][0]
        p.sensibilidad.set(0.45)
        p._redetectar()
        assert len(p.temas) == 3

        # Clic en el mapa en el medio del tema 2: marca, lo selecciona y suena desde ahí.
        medio = (reales[1][0] + reales[1][1]) / 2
        p._clic_mapa(type("E", (), {"x": p._x(medio)})())
        assert p._elegido() == 1 and abs(escuchado[-1][0] - medio) < 1

        # Ajustes a mano.
        inicio = p.temas[1].inicio
        p.mover("inicio", 1)
        assert p.temas[1].inicio == pytest.approx(inicio + 1)
        assert escuchado[-1][0] == pytest.approx(p.temas[1].inicio - 2)  # escucha el nuevo inicio
        p.renombrar()
        assert p.temas[1].nombre == "Help"
        p.dividir()
        assert len(p.temas) == 4 and p.temas[2].inicio == pytest.approx(p.marca)
        p.unir()
        assert len(p.temas) == 3 and p.temas[1].fin == pytest.approx(reales[1][1], abs=4)

        p.cortar()
        esperar()
        carpetas = sorted(d.name for d in (sesion / "temas").iterdir() if d.is_dir())
        assert carpetas == ["02_Help", "tema_01", "tema_03"]
        assert ("showinfo", "Temas cortados. Ahora podés mezclarlos en la pestaña 2.") in avisos
    finally:
        raiz.destroy()


def test_sacar_sala_baja_la_cola_y_no_el_directo():
    from scipy.signal import fftconvolve

    from meazclador.efectos import desreverberar

    sr = 48000
    rng = np.random.default_rng(0)
    seco = np.zeros(sr * 6, dtype=np.float32)
    for k in range(6):
        n = int(0.2 * sr)
        seco[k * sr: k * sr + n] = rng.standard_normal(n) * np.hanning(n) * 0.3
    cola = rng.standard_normal(2 * sr) * np.exp(-np.arange(2 * sr) / sr * 3 * np.log(10) / 0.8) * 0.03
    sala = (seco + fftconvolve(seco, cola)[: len(seco)]).astype(np.float32)[None, :]
    seca = desreverberar(sala, 1.0)

    def nivel(x, a, b):
        return 10 * np.log10(np.mean(x[0][int(a * sr): int(b * sr)] ** 2))

    def graves(x):
        espectro = np.abs(np.fft.rfft(x[0][2 * sr: int(2.2 * sr)])) ** 2
        f = np.fft.rfftfreq(int(0.2 * sr), 1 / sr)
        return 10 * np.log10(espectro[(f > 50) & (f < 200)].sum())

    assert seca.shape == sala.shape and np.isfinite(seca).all()
    assert nivel(seca, 2.0, 2.2) - nivel(sala, 2.0, 2.2) > -1.5  # el sonido directo casi no cambia
    assert nivel(seca, 2.3, 2.8) - nivel(sala, 2.3, 2.8) < -3.5  # la habitación baja
    assert abs(graves(seca) - graves(sala)) < 0.5  # el cuerpo (graves) no se toca: no queda 'latoso'


def test_retoques_mueven_el_balance():
    from meazclador.analisis import Pista
    from meazclador.mezcla import Proyecto, Retoques, combinar

    sr = 48000
    t = np.arange(sr * 4) / sr
    voz = (0.1 * np.sin(2 * np.pi * 1000 * t))[None, :].astype(np.float32)
    gtr = (0.1 * np.sin(2 * np.pi * 300 * t))[None, :].astype(np.float32)

    def proporcion(retoques):
        proyecto = Proyecto([Pista("Voz.wav", voz.copy(), rol="voz"), Pista("Gtr.wav", gtr.copy(), rol="guitarra")],
                            "natural", None, None)
        res = combinar(proyecto, retoques, avisar=lambda _: None)
        espectro = np.abs(np.fft.rfft(res.premaster[0]))
        f = np.fft.rfftfreq(res.premaster.shape[1], 1 / sr)
        return 20 * np.log10(espectro[np.argmin(np.abs(f - 1000))] / espectro[np.argmin(np.abs(f - 300))])

    assert proporcion(Retoques(voz=6)) - proporcion(Retoques()) == pytest.approx(6, abs=0.3)
    assert proporcion(Retoques(guitarras=-3)) - proporcion(Retoques()) == pytest.approx(3, abs=0.3)


def test_retocar_una_mezcla_guardada(tmp_path):
    from meazclador import demo
    from meazclador.cli import main as cli
    from meazclador.mezcla import Retoques

    demo.main(tmp_path / "tema")
    assert cli(["mezclar", str(tmp_path / "tema"), "--estilo", "punk"]) == 0
    mezcla = tmp_path / "tema" / "mezcla"
    procesadas = [f for f in (mezcla / "pistas_procesadas").glob("*.flac") if not f.stem.endswith("_seca")]
    assert (mezcla / "proyecto.json").is_file() and len(procesadas) == 7
    antes = (mezcla / "master.wav").read_bytes()

    assert cli(["retocar", str(tmp_path / "tema"), "--voz", "3", "--reverb", "0", "--presencia", "0.9"]) == 0
    assert (mezcla / "master_anterior.wav").read_bytes() == antes
    assert (mezcla / "master.wav").read_bytes() != antes
    r = Retoques.cargar(mezcla / "retoques.json")
    assert (r.voz, r.reverb, r.presencia) == (3.0, 0.0, 0.9)
    informe = (mezcla / "informe.txt").read_text(encoding="utf-8")
    assert "Retoques: voz +3.0 dB, reverb 0%, presencia 90%" in informe and "Presencia 90%" in informe

    # Un segundo retoque parte del anterior; volver a mezclar conserva los retoques.
    assert cli(["retocar", str(tmp_path / "tema"), "--coros", "-1"]) == 0
    r = Retoques.cargar(mezcla / "retoques.json")
    assert (r.voz, r.coros) == (3.0, -1.0)
    assert cli(["mezclar", str(tmp_path / "tema"), "--estilo", "punk"]) == 0
    assert "Retoques: voz +3.0 dB" in (mezcla / "informe.txt").read_text(encoding="utf-8")


def _app_de_prueba(monkeypatch):
    tk = pytest.importorskip("tkinter")
    try:
        raiz = tk.Tk()
    except tk.TclError:
        pytest.skip("sin pantalla")
    from meazclador import gui, gui_retoque, gui_sesion

    avisos = []
    for modulo in (gui, gui_sesion, gui_retoque):
        for nombre in ("showinfo", "showwarning", "showerror"):
            monkeypatch.setattr(modulo.messagebox, nombre, lambda *a, n=nombre: avisos.append((n, a[1])))
    app = gui.App(raiz)
    return raiz, app, avisos


def _esperar(raiz, app, limite=120):
    import time

    fin = time.monotonic() + limite
    raiz.update()
    while app.trabajando and time.monotonic() < fin:
        raiz.update()
        time.sleep(0.02)
    raiz.update()
    assert not app.trabajando, "el trabajo no terminó a tiempo"


def test_boton_cancelar_corta_la_mezcla(tmp_path, monkeypatch):
    import time

    from meazclador import demo

    raiz, app, avisos = _app_de_prueba(monkeypatch)
    try:
        demo.main(tmp_path / "tema")
        app._correr(["mezclar", str(tmp_path / "tema"), "--estilo", "punk"])
        inicio = time.monotonic()
        while app.proceso is None or app.proceso.poll() is not None and time.monotonic() - inicio < 10:
            raiz.update()
            time.sleep(0.02)
        assert str(app.btn_cancelar["state"]) == "normal"
        app.cancelar()
        _esperar(raiz, app, limite=10)
        registro = app.registro.get("1.0", "end")
        assert "Cancelado" in registro
        assert not (tmp_path / "tema" / "mezcla" / "master.wav").exists()
        assert str(app.btn_cancelar["state"]) == "disabled"
        assert not [a for a in avisos if a[0] == "showerror"]
    finally:
        raiz.destroy()


def test_pestana_retocar(tmp_path, monkeypatch):
    from meazclador import demo
    from meazclador.cli import main as cli
    from meazclador.mezcla import Retoques

    demo.main(tmp_path / "temas" / "01_Help")
    assert cli(["mezclar", str(tmp_path / "temas" / "01_Help"), "--estilo", "punk"]) == 0
    raiz, app, avisos = _app_de_prueba(monkeypatch)
    try:
        p = app.panel_retoque
        escuchado = []
        p.reproductor.reproducir = lambda audio, sr, desde: escuchado.append((desde, audio.shape))
        p.carpeta.set(str(tmp_path / "temas"))
        p.buscar_mezclas()
        assert p.tema.get() == "01_Help"
        assert p.vars["presencia"].get() == pytest.approx(0.6)  # la del estilo punk
        assert p.vars["sala"].get() == pytest.approx(1.0)
        assert list(p.combo_voz["values"]) == ["07_Voz.wav"] and p.voz_principal.get() == "07_Voz.wav"
        p.vars["voz"].set(2.5)
        p.vars["reverb"].set(0.5)
        p.aplicar()
        _esperar(raiz, app)
        r = Retoques.cargar(tmp_path / "temas" / "01_Help" / "mezcla" / "retoques.json")
        assert (r.voz, r.reverb) == (2.5, 0.5)
        assert escuchado and escuchado[-1][0] == 0.0  # tema de 16 s: 0:30 no existe, arranca desde el principio
        assert escuchado[-1][1] == (2, 16 * 48000)
        p.escuchar("master_anterior.wav")
        assert len(escuchado) == 2
        assert not [a for a in avisos if a[0] == "showerror"]
    finally:
        raiz.destroy()


def _voces_de_banda(sr=48000, segundos=40):
    """Principal: canta frases en todo el tema. Coros: sólo en los estribillos.
    Todas con la batería colándose en el micrófono (~25 dB abajo)."""
    rng = np.random.default_rng(5)
    n = sr * segundos
    t = np.arange(n) / sr
    bateria = np.zeros(n)
    for golpe in np.arange(0, segundos, 0.25):
        i = int(golpe * sr)
        k = min(n - i, int(0.1 * sr))
        bateria[i:i + k] += rng.standard_normal(k) * np.exp(-np.arange(k) / sr * 40)
    bateria *= 0.3 * 10 ** (-25 / 20)

    def cantar(tramos):
        y = np.zeros(n)
        for a, b in tramos:
            for frase in np.arange(a, b, 3.0):  # frases de 2.5 s con respiración de 0.5 s
                i, j = int(frase * sr), int(min(frase + 2.5, b) * sr)
                f0 = 220 * (1 + 0.01 * np.sin(2 * np.pi * 5 * t[i:j]))
                y[i:j] = 0.3 * sum(np.sin(2 * np.pi * k * np.cumsum(f0) / sr) / k for k in range(1, 8))
        return (y + bateria)[None, :].astype(np.float32)

    estribillos = [(10, 18), (28, 36)]
    return cantar([(2, 38)]), cantar(estribillos), cantar(estribillos)


def test_detecta_voz_principal_cuando_cambia_en_un_tema():
    from meazclador.analisis import Pista, actividad_de_canto, elegir_voz_principal

    principal, coro1, coro2 = _voces_de_banda()
    assert actividad_de_canto(principal) > 0.8 and actividad_de_canto(coro1) < 0.5

    # Tema normal: los nombres coinciden con lo que se canta, no se toca nada.
    pistas = [Pista("Voz.wav", principal, rol="voz"), Pista("Coro 1.wav", coro1, rol="coros"),
              Pista("Coro 2.wav", coro2, rol="coros")]
    cambio, explicacion = elegir_voz_principal(pistas)
    assert not cambio and "Cuánto canta cada pista" in explicacion  # siempre explica la decisión
    assert [p.rol for p in pistas] == ["voz", "coros", "coros"]

    # Tema 10: el que canta todo está en la pista 'Coro 1' y la 'Voz' hace los coros.
    pistas = [Pista("Voz.wav", coro2, rol="voz"), Pista("Coro 1.wav", principal, rol="coros"),
              Pista("Coro 2.wav", coro1, rol="coros")]
    cambio, explicacion = elegir_voz_principal(pistas)
    assert cambio and "Coro 1.wav" in explicacion
    assert [p.rol for p in pistas] == ["coros", "voz", "coros"]
    assert "VOZ PRINCIPAL" in " ".join(pistas[1].notas)


def test_mezcla_con_voces_intercambiadas(tmp_path):
    import soundfile as sf

    from meazclador.mezcla import Opciones, mezclar

    principal, coro1, coro2 = _voces_de_banda()
    carpeta = tmp_path / "10_Help"
    carpeta.mkdir()
    for nombre, audio in (("Voz.wav", coro2), ("Coro 1.wav", principal), ("Coro 2.wav", coro1)):
        sf.write(carpeta / nombre, audio[0], 48000)
    res = mezclar(carpeta, Opciones(estilo="punk", afinar=0), avisar=lambda _: None)
    roles = {p.nombre: (p.rol, p.pan) for p in res.pistas}
    assert roles["Coro 1.wav"] == ("voz", 0.0)  # la principal va al centro
    assert roles["Voz.wav"][0] == "coros" and roles["Voz.wav"][1] != 0.0  # el coro, a un costado
    assert any("Voz principal detectada" in n for n in res.notas_generales)


def test_elegir_voz_principal_a_mano(tmp_path):
    import json

    import soundfile as sf

    from meazclador.cli import main as cli

    principal, coro1, coro2 = _voces_de_banda()
    # Un poco de canto en los coros también: la detección automática no se anima a cambiar.
    coro2 = coro2.copy()
    coro2[:, : 48000 * 30] += principal[:, : 48000 * 30] * 0.9
    tema = tmp_path / "10_Help"
    tema.mkdir()
    for nombre, audio in (("Voz.wav", coro2), ("Coro 1.wav", principal), ("Coro 2.wav", coro1)):
        sf.write(tema / nombre, audio[0], 48000)
    assert cli(["mezclar", str(tema), "--estilo", "punk", "--afinar", "0"]) == 0

    def roles():
        datos = json.loads((tema / "mezcla" / "proyecto.json").read_text(encoding="utf-8"))
        return {d["nombre"]: (d["rol"], d["pan"]) for d in datos["pistas"]}, datos["notas"]

    antes, notas = roles()
    assert antes["Voz.wav"][0] == "voz"
    assert any("Cuánto canta cada pista" in n for n in notas)  # el informe explica por qué

    assert cli(["retocar", str(tema), "--voz-principal", "Coro 1"]) == 0
    despues, notas = roles()
    assert despues["Coro 1.wav"] == ("voz", 0.0)
    assert despues["Voz.wav"][0] == "coros" and despues["Voz.wav"][1] != 0.0
    assert "Voz principal elegida a mano: 'Coro 1.wav'." in notas
    assert "voz principal 'Coro 1'" in (tema / "mezcla" / "informe.txt").read_text(encoding="utf-8")

    # Volver a mezclar respeta la elección.
    assert cli(["mezclar", str(tema), "--estilo", "punk", "--afinar", "0"]) == 0
    assert roles()[0]["Coro 1.wav"][0] == "voz"


def test_control_de_sala(tmp_path):
    from meazclador import demo
    from meazclador.cli import main as cli

    demo.main(tmp_path / "tema")
    assert cli(["mezclar", str(tmp_path / "tema"), "--estilo", "punk"]) == 0
    mezcla = tmp_path / "tema" / "mezcla"
    assert list((mezcla / "pistas_procesadas").glob("*_seca.flac"))
    assert cli(["retocar", str(tmp_path / "tema"), "--sala", "0"]) == 0
    original = (mezcla / "master.wav").read_bytes()
    informe = (mezcla / "informe.txt").read_text(encoding="utf-8")
    assert "sacar sala 0%" in informe and "07_Voz 0%" in informe  # la habitación original
    assert cli(["retocar", str(tmp_path / "tema"), "--sala", "150"]) == 0
    assert (mezcla / "master.wav").read_bytes() != original
    assert "sacar sala 150%" in (mezcla / "informe.txt").read_text(encoding="utf-8")


def test_eq_de_master_corrige_sonido_latoso():
    from pedalboard import HighShelfFilter, PeakFilter, Pedalboard

    from meazclador.master import balance_tonal, perfil_objetivo

    sr = 48000
    rng = np.random.default_rng(2)
    # Ruido con la pendiente de un disco típico (-4.5 dB/oct) ...
    espectro = np.fft.rfft(rng.standard_normal(sr * 10))
    f = np.fft.rfftfreq(sr * 10, 1 / sr)
    espectro *= 10 ** (-4.5 * np.log2(np.maximum(f, 20) / 1000) / 20)
    disco = np.fft.irfft(espectro)[None, :].astype(np.float32)
    disco /= np.max(np.abs(disco)) * 4
    # ... arruinado como el máster 'latoso': +4 dB en 2-5 kHz y sin aire arriba de 8 kHz.
    latoso = Pedalboard([PeakFilter(cutoff_frequency_hz=3500, gain_db=4, q=1.0),
                         HighShelfFilter(cutoff_frequency_hz=8000, gain_db=-6, q=0.7)])(disco, sr)
    objetivo, _ = perfil_objetivo(None)
    _, notas = balance_tonal(latoso, objetivo)
    texto = " ".join(notas)
    assert "presencia (4000 Hz) -" in texto  # baja la lata
    assert "brillo (8000 Hz) +" in texto and "aire (16000 Hz) +" in texto  # devuelve el aire
    _, notas_disco = balance_tonal(disco, objetivo)
    assert len(notas_disco) <= 2  # un disco ya equilibrado casi no se toca
