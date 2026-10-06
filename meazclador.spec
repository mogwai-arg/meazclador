# Receta de PyInstaller para armar el ejecutable:  pyinstaller meazclador.spec
import sys

from PyInstaller.utils.hooks import collect_all

datas, binaries, hiddenimports = [], [], []
for paquete in ("pedalboard", "pyworld", "pyloudnorm", "soundfile", "_soundfile_data"):
    try:
        d, b, h = collect_all(paquete)
    except Exception:
        continue
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    ["lanzador.py"],
    datas=datas,
    binaries=binaries,
    hiddenimports=hiddenimports,
    excludes=["matplotlib", "pytest", "IPython"],
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    name="Meazclador",
    console=False,
    upx=False,
)
if sys.platform == "darwin":
    app = BUNDLE(exe, name="Meazclador.app", bundle_identifier="ar.mogwai.meazclador")
