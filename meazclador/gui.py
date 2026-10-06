"""Ventana de meazclador: lo mismo que la línea de comandos, con botones."""

from __future__ import annotations

import contextlib
import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from . import __version__
from .cli import main as cli
from .audio import Cancelado
from .gui_retoque import PanelRetoque
from .gui_sesion import PanelSesion
from .mezcla import ESTILOS

ESTILOS_GUI = {
    "Natural (limpio y fuerte)": "natural",
    "Punk (crudo, estilo Ramones)": "punk",
}
GUITARRAS = {
    "Detectar solo": "auto",
    "Por línea / DI (simular el ampli)": "directas",
    "Con ampli microfoneado": "amplificadas",
}
VOLUMENES = {
    "Según el estilo": None,
    "Normal: Spotify / YouTube (-14 LUFS)": -14.0,
    "Fuerte: rock pesado (-10 LUFS)": -10.0,
    "Dinámico: más aire, menos aplastado (-16 LUFS)": -16.0,
}


class _Cola:
    """Archivo falso: lo que el programa imprime va a la ventana."""

    def __init__(self, q: queue.Queue):
        self.q = q

    def write(self, texto: str) -> int:
        self.q.put(texto)
        return len(texto)

    def flush(self) -> None:
        pass


def abrir_carpeta(ruta: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(ruta)  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(ruta)])
    else:
        subprocess.Popen(["xdg-open", str(ruta)])


class App(ttk.Frame):
    def __init__(self, raiz: tk.Tk):
        super().__init__(raiz, padding=12)
        self.raiz = raiz
        self.cola: queue.Queue = queue.Queue()
        self.trabajando = False
        self.ultima_salida: Path | None = None
        raiz.title(f"Meazclador {__version__}")
        raiz.minsize(820, 860)
        self.grid(sticky="nsew")
        raiz.columnconfigure(0, weight=1)
        raiz.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self.pestanas = ttk.Notebook(self)
        self.pestanas.grid(row=0, column=0, sticky="nsew")
        self.pestanas.add(self._pestana_cortar(), text="  1 · Cortar la grabación larga  ")
        self.pestanas.add(self._pestana_mezclar(), text="  2 · Mezclar y masterizar  ")
        self.panel_retoque = PanelRetoque(self.pestanas, self)
        self.pestanas.add(self.panel_retoque, text="  3 · Retocar  ")

        estado = ttk.Frame(self)
        estado.grid(row=1, column=0, sticky="ew", pady=(10, 4))
        estado.columnconfigure(0, weight=1)
        self.progreso = ttk.Progressbar(estado, mode="indeterminate")
        self.progreso.grid(row=0, column=0, sticky="ew")
        self.btn_cancelar = ttk.Button(estado, text="✖ Cancelar", state="disabled", command=self.cancelar)
        self.btn_cancelar.grid(row=0, column=1, padx=(8, 0))
        self.proceso: subprocess.Popen | None = None
        self.cancelacion = threading.Event()
        self.registro = tk.Text(self, height=8, state="disabled", wrap="word", font=("TkFixedFont", 9))
        self.registro.grid(row=2, column=0, sticky="nsew")
        self._leer_cola()

    # ---------- construcción ----------

    def _fila_carpeta(self, padre, fila: int, texto: str, var: tk.StringVar, archivo: bool = False) -> None:
        ttk.Label(padre, text=texto).grid(row=fila, column=0, sticky="w", pady=4)
        ttk.Entry(padre, textvariable=var).grid(row=fila, column=1, sticky="ew", padx=6)

        def elegir():
            if archivo:
                r = filedialog.askopenfilename(filetypes=[("Audio", "*.wav *.flac *.aif *.aiff"), ("Todos", "*.*")])
            else:
                r = filedialog.askdirectory()
            if r:
                var.set(r)

        ttk.Button(padre, text="Elegir…", command=elegir).grid(row=fila, column=2)

    def _pestana_cortar(self) -> ttk.Frame:
        self.panel_sesion = PanelSesion(self.pestanas, self)
        return self.panel_sesion

    def _pestana_mezclar(self) -> ttk.Frame:
        f = ttk.Frame(self.pestanas, padding=10)
        f.columnconfigure(1, weight=1)
        ttk.Label(f, wraplength=640, justify="left", text=(
            "Elegí la carpeta de UN tema (con sus pistas) o la carpeta 'temas' que crea el paso 1 "
            "para mezclar todos. Los nombres de los archivos tienen que decir qué instrumento es "
            "(Bombo, Caja, Bajo, Guitarra, Voz, Coros…)."
        )).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.carpeta = tk.StringVar()
        self._fila_carpeta(f, 1, "Carpeta:", self.carpeta)

        ttk.Label(f, text="Estilo:").grid(row=2, column=0, sticky="w", pady=4)
        self.estilo = tk.StringVar(value=next(iter(ESTILOS_GUI)))
        combo = ttk.Combobox(f, textvariable=self.estilo, values=list(ESTILOS_GUI), state="readonly")
        combo.grid(row=2, column=1, sticky="ew", padx=6)
        combo.bind("<<ComboboxSelected>>", lambda _: self._estilo_elegido())

        ttk.Label(f, text="Guitarras grabadas:").grid(row=3, column=0, sticky="w", pady=4)
        self.guitarras = tk.StringVar(value=next(iter(GUITARRAS)))
        ttk.Combobox(f, textvariable=self.guitarras, values=list(GUITARRAS), state="readonly").grid(
            row=3, column=1, sticky="ew", padx=6)

        ttk.Label(f, text="Afinar voces:").grid(row=4, column=0, sticky="w", pady=4)
        self.afinar = tk.DoubleVar(value=ESTILOS[next(iter(ESTILOS_GUI.values()))].afinar)
        ttk.Scale(f, from_=0, to=1, variable=self.afinar,
                  command=lambda _: self.txt_afinar.set(self._texto_afinar())).grid(row=4, column=1, sticky="ew", padx=6)
        self.txt_afinar = tk.StringVar(value=self._texto_afinar())
        ttk.Label(f, textvariable=self.txt_afinar, width=18).grid(row=4, column=2)

        ttk.Label(f, text="Tonalidad (opcional):").grid(row=5, column=0, sticky="w", pady=4)
        self.tonalidad = tk.StringVar()
        ttk.Entry(f, textvariable=self.tonalidad, width=12).grid(row=5, column=1, sticky="w", padx=6)
        ttk.Label(f, text="ej: Am, E, La menor", foreground="gray").grid(row=5, column=2)

        ttk.Label(f, text="Volumen final:").grid(row=6, column=0, sticky="w", pady=4)
        self.volumen = tk.StringVar(value=next(iter(VOLUMENES)))
        ttk.Combobox(f, textvariable=self.volumen, values=list(VOLUMENES), state="readonly").grid(
            row=6, column=1, sticky="ew", padx=6)

        self.referencia = tk.StringVar()
        self._fila_carpeta(f, 7, "Tema de referencia (opcional):", self.referencia, archivo=True)
        self.sample_bombo = tk.StringVar()
        self._fila_carpeta(f, 8, "Sample de bombo (opcional):", self.sample_bombo, archivo=True)
        self.sample_caja = tk.StringVar()
        self._fila_carpeta(f, 9, "Sample de caja (opcional):", self.sample_caja, archivo=True)

        botones = ttk.Frame(f)
        botones.grid(row=10, column=0, columnspan=3, sticky="w", pady=(12, 0))
        self.btn_mezclar = ttk.Button(botones, text="🎚  Mezclar y masterizar", command=self.mezclar)
        self.btn_mezclar.pack(side="left")
        self.btn_abrir = ttk.Button(botones, text="📂  Abrir resultados", state="disabled",
                                    command=lambda: self.ultima_salida and abrir_carpeta(self.ultima_salida))
        self.btn_abrir.pack(side="left", padx=8)
        return f

    def _texto_afinar(self) -> str:
        v = self.afinar.get()
        if v < 0.05:
            return "no tocar"
        if ESTILOS_GUI.get(self.estilo.get()) == "punk":
            return f"{v:.0%} (sólo desafinadas)"
        return f"{v:.0%}" + (" (natural)" if v <= 0.6 else " (marcado)")

    def _estilo_elegido(self) -> None:
        estilo = ESTILOS[ESTILOS_GUI[self.estilo.get()]]
        self.afinar.set(estilo.afinar if estilo.afinar else 0.0)
        self.txt_afinar.set(self._texto_afinar())

    # ---------- trabajos ----------

    def _log(self, texto: str) -> None:
        self.registro.configure(state="normal")
        self.registro.insert("end", texto)
        self.registro.see("end")
        self.registro.configure(state="disabled")

    def _leer_cola(self) -> None:
        try:
            while True:
                item = self.cola.get_nowait()
                if isinstance(item, tuple):  # ("fin", código, callback) desde el hilo de trabajo
                    self._fin(item[1], item[2])
                else:
                    self._log(item)
        except queue.Empty:
            pass
        self.after(100, self._leer_cola)

    def _botones_trabajo(self) -> list:
        p = self.panel_sesion
        return [p.btn_analizar, p.btn_cortar, self.btn_mezclar, self.panel_retoque.btn_aplicar]

    @staticmethod
    def _comando(args: list[str]) -> list[str]:
        """Cómo lanzarse a sí mismo como proceso aparte (en el ejecutable o desde Python)."""
        if getattr(sys, "frozen", False):
            return [sys.executable, *args]
        return [sys.executable, "-m", "meazclador.app", *args]

    def _correr(self, tarea, al_terminar=None) -> None:
        """Corre un trabajo en segundo plano sin congelar la ventana.

        - Lista de argumentos: se lanza como proceso aparte (así 'Cancelar' lo corta en el acto).
        - Función: corre en un hilo; recibe un callback `cancelar()` si lo acepta, y al_terminar
          recibe lo que devolvió.
        """
        if self.trabajando:
            return
        self.trabajando = True
        self.cancelacion.clear()
        for b in self._botones_trabajo():
            b.configure(state="disabled")
        self.btn_cancelar.configure(state="normal")
        self.progreso.start(12)
        if not callable(tarea):
            self._log("\n▶ " + " ".join(tarea) + "\n")

        def en_proceso() -> int:
            opciones = {}
            if sys.platform.startswith("win"):
                opciones["creationflags"] = subprocess.CREATE_NO_WINDOW  # type: ignore[attr-defined]
            self.proceso = subprocess.Popen(
                self._comando(tarea), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                text=True, encoding="utf-8", errors="replace", bufsize=1,
                env={**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUNBUFFERED": "1"}, **opciones)
            for linea in self.proceso.stdout:
                self.cola.put(linea)
            return self.proceso.wait()

        def trabajo():
            resultado, codigo = None, 1
            try:
                if callable(tarea):
                    with contextlib.redirect_stdout(_Cola(self.cola)), contextlib.redirect_stderr(_Cola(self.cola)):
                        resultado, codigo = tarea(self.cancelacion.is_set), 0
                else:
                    codigo = en_proceso()
            except Cancelado:
                pass
            except Exception as e:  # que un error nunca cuelgue la ventana
                self.cola.put(f"Error: {e}\n")
            if self.cancelacion.is_set():
                codigo = -1
            listo = (lambda: al_terminar(resultado)) if (al_terminar and callable(tarea)) else al_terminar
            self.cola.put(("fin", codigo, listo))  # tkinter sólo se toca desde el hilo principal

        threading.Thread(target=trabajo, daemon=True).start()

    def cancelar(self) -> None:
        self.cancelacion.set()
        if self.proceso and self.proceso.poll() is None:
            self.proceso.kill()
        self._log("\n✖ Cancelando...\n")

    def _fin(self, codigo: int, al_terminar) -> None:
        self.trabajando = False
        self.proceso = None
        self.progreso.stop()
        self.btn_cancelar.configure(state="disabled")
        for b in self._botones_trabajo():
            b.configure(state="normal")
        if codigo == -1:
            self._log("✖ Cancelado. Lo que se estaba haciendo quedó a medias; podés volver a empezar.\n")
        elif codigo == 0:
            if al_terminar:
                al_terminar()
        else:
            messagebox.showerror("Meazclador", "Algo salió mal. Mirá el mensaje en el registro de abajo.")

    def _carpeta_valida(self, var: tk.StringVar) -> Path | None:
        ruta = Path(var.get().strip())
        if not var.get().strip() or not ruta.is_dir():
            messagebox.showwarning("Meazclador", "Elegí primero una carpeta.")
            return None
        return ruta

    def mezclar(self) -> None:
        carpeta = self._carpeta_valida(self.carpeta)
        if not carpeta:
            return
        args = ["mezclar", str(carpeta), "--afinar", f"{self.afinar.get():.2f}",
                "--estilo", ESTILOS_GUI[self.estilo.get()], "--guitarras", GUITARRAS[self.guitarras.get()]]
        if VOLUMENES[self.volumen.get()] is not None:
            args += ["--lufs", str(VOLUMENES[self.volumen.get()])]
        for opcion, var in (("--tonalidad", self.tonalidad), ("--referencia", self.referencia),
                            ("--sample-bombo", self.sample_bombo), ("--sample-caja", self.sample_caja)):
            if var.get().strip():
                args += [opcion, var.get().strip()]

        def listo():
            mezcla = carpeta / "mezcla"
            self.ultima_salida = mezcla if mezcla.is_dir() else carpeta / "masters"
            self.btn_abrir.configure(state="normal")
            self.panel_retoque.carpeta.set(str(carpeta))
            messagebox.showinfo("Meazclador", f"¡Listo! Los resultados están en:\n{self.ultima_salida}\n\n"
                                "Si algo no te convence (voz, reverb, presencia), ajustalo en la pestaña 3 · Retocar.")

        self._correr(args, listo)


def main() -> int:
    raiz = tk.Tk()
    try:
        ttk.Style(raiz).theme_use("vista" if sys.platform.startswith("win") else "clam")
    except tk.TclError:
        pass
    App(raiz)
    raiz.mainloop()
    return 0
