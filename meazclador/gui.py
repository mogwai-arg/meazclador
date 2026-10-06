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

VOLUMENES = {
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
        raiz.minsize(720, 640)
        self.grid(sticky="nsew")
        raiz.columnconfigure(0, weight=1)
        raiz.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.rowconfigure(2, weight=1)

        self.pestanas = ttk.Notebook(self)
        self.pestanas.grid(row=0, column=0, sticky="nsew")
        self.pestanas.add(self._pestana_cortar(), text="  1 · Cortar la grabación larga  ")
        self.pestanas.add(self._pestana_mezclar(), text="  2 · Mezclar y masterizar  ")

        self.progreso = ttk.Progressbar(self, mode="indeterminate")
        self.progreso.grid(row=1, column=0, sticky="ew", pady=(10, 4))
        self.registro = tk.Text(self, height=12, state="disabled", wrap="word", font=("TkFixedFont", 9))
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
        f = ttk.Frame(self.pestanas, padding=10)
        f.columnconfigure(1, weight=1)
        f.rowconfigure(5, weight=1)
        ttk.Label(f, wraplength=640, justify="left", text=(
            "Elegí la carpeta con las pistas de la grabación completa (un WAV por micrófono). "
            "El programa encuentra dónde empieza y termina cada tema. Revisá la lista: podés "
            "corregir tiempos, borrar líneas o ponerles nombre a los temas antes de cortar."
        )).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 8))

        self.sesion = tk.StringVar()
        self._fila_carpeta(f, 1, "Carpeta de la sesión:", self.sesion)

        ttk.Label(f, text="Sensibilidad:").grid(row=2, column=0, sticky="w", pady=4)
        self.sensibilidad = tk.DoubleVar(value=0.45)
        ttk.Scale(f, from_=0.2, to=0.8, variable=self.sensibilidad).grid(row=2, column=1, sticky="ew", padx=6)
        ttk.Label(f, text="← junta temas / deja charla →", foreground="gray").grid(row=2, column=2)

        ttk.Label(f, text="Tema más corto (seg):").grid(row=3, column=0, sticky="w", pady=4)
        self.min_tema = tk.IntVar(value=60)
        ttk.Spinbox(f, from_=10, to=600, increment=10, textvariable=self.min_tema, width=6).grid(
            row=3, column=1, sticky="w", padx=6)

        self.btn_buscar = ttk.Button(f, text="🔍  Buscar temas", command=self.buscar_temas)
        self.btn_buscar.grid(row=4, column=0, columnspan=3, sticky="w", pady=6)
        self.lista = tk.Text(f, height=8, font=("TkFixedFont", 10))
        self.lista.grid(row=5, column=0, columnspan=3, sticky="nsew")
        self.btn_cortar = ttk.Button(f, text="✂  Cortar temas", command=self.cortar_temas)
        self.btn_cortar.grid(row=6, column=0, columnspan=3, sticky="w", pady=(8, 0))
        return f

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

        ttk.Label(f, text="Afinar voces:").grid(row=2, column=0, sticky="w", pady=4)
        self.afinar = tk.DoubleVar(value=0.0)
        ttk.Scale(f, from_=0, to=1, variable=self.afinar,
                  command=lambda _: self.txt_afinar.set(self._texto_afinar())).grid(row=2, column=1, sticky="ew", padx=6)
        self.txt_afinar = tk.StringVar(value=self._texto_afinar())
        ttk.Label(f, textvariable=self.txt_afinar, width=14).grid(row=2, column=2)

        ttk.Label(f, text="Tonalidad (opcional):").grid(row=3, column=0, sticky="w", pady=4)
        self.tonalidad = tk.StringVar()
        ttk.Entry(f, textvariable=self.tonalidad, width=12).grid(row=3, column=1, sticky="w", padx=6)
        ttk.Label(f, text="ej: Am, E, La menor", foreground="gray").grid(row=3, column=2)

        ttk.Label(f, text="Volumen final:").grid(row=4, column=0, sticky="w", pady=4)
        self.volumen = tk.StringVar(value=next(iter(VOLUMENES)))
        ttk.Combobox(f, textvariable=self.volumen, values=list(VOLUMENES), state="readonly").grid(
            row=4, column=1, sticky="ew", padx=6)

        self.referencia = tk.StringVar()
        self._fila_carpeta(f, 5, "Tema de referencia (opcional):", self.referencia, archivo=True)

        botones = ttk.Frame(f)
        botones.grid(row=6, column=0, columnspan=3, sticky="w", pady=(12, 0))
        self.btn_mezclar = ttk.Button(botones, text="🎚  Mezclar y masterizar", command=self.mezclar)
        self.btn_mezclar.pack(side="left")
        self.btn_abrir = ttk.Button(botones, text="📂  Abrir resultados", state="disabled",
                                    command=lambda: self.ultima_salida and abrir_carpeta(self.ultima_salida))
        self.btn_abrir.pack(side="left", padx=8)
        return f

    def _texto_afinar(self) -> str:
        v = self.afinar.get()
        return "no tocar" if v < 0.05 else f"{v:.0%}" + (" (natural)" if v <= 0.6 else " (marcado)")

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

    def _correr(self, args: list[str], al_terminar=None) -> None:
        if self.trabajando:
            return
        self.trabajando = True
        for b in (self.btn_buscar, self.btn_cortar, self.btn_mezclar):
            b.configure(state="disabled")
        self.progreso.start(12)
        self._log("\n▶ " + " ".join(args) + "\n")

        def trabajo():
            salida = _Cola(self.cola)
            try:
                with contextlib.redirect_stdout(salida), contextlib.redirect_stderr(salida):
                    codigo = cli(args)
            except Exception as e:  # que un error nunca cuelgue la ventana
                self.cola.put(f"Error inesperado: {e}\n")
                codigo = 1
            self.cola.put(("fin", codigo, al_terminar))  # tkinter sólo se toca desde el hilo principal

        threading.Thread(target=trabajo, daemon=True).start()

    def _fin(self, codigo: int, al_terminar) -> None:
        self.trabajando = False
        self.progreso.stop()
        for b in (self.btn_buscar, self.btn_cortar, self.btn_mezclar):
            b.configure(state="normal")
        if codigo == 0:
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

    def buscar_temas(self) -> None:
        sesion = self._carpeta_valida(self.sesion)
        if not sesion:
            return

        def mostrar():
            lista = sesion / "temas" / "temas.txt"
            self.lista.delete("1.0", "end")
            self.lista.insert("1.0", lista.read_text(encoding="utf-8"))

        self._correr(["cortar", str(sesion), "--solo-mostrar",
                      "--sensibilidad", f"{self.sensibilidad.get():.2f}",
                      "--min-tema", str(self.min_tema.get())], mostrar)

    def cortar_temas(self) -> None:
        sesion = self._carpeta_valida(self.sesion)
        if not sesion:
            return
        texto = self.lista.get("1.0", "end").strip()
        if not texto:
            messagebox.showinfo("Meazclador", "Primero tocá 'Buscar temas' (o escribí los tiempos en la lista).")
            return
        destino = sesion / "temas"
        destino.mkdir(exist_ok=True)
        lista = destino / "temas.txt"
        lista.write_text(texto + "\n", encoding="utf-8")

        def listo():
            self.carpeta.set(str(destino))
            self.pestanas.select(1)
            messagebox.showinfo("Meazclador", "Temas cortados. Ahora podés mezclarlos en la pestaña 2.")

        self._correr(["cortar", str(sesion), "--cortes", str(lista)], listo)

    def mezclar(self) -> None:
        carpeta = self._carpeta_valida(self.carpeta)
        if not carpeta:
            return
        args = ["mezclar", str(carpeta), "--afinar", f"{self.afinar.get():.2f}",
                "--lufs", str(VOLUMENES[self.volumen.get()])]
        if self.tonalidad.get().strip():
            args += ["--tonalidad", self.tonalidad.get().strip()]
        if self.referencia.get().strip():
            args += ["--referencia", self.referencia.get().strip()]

        def listo():
            mezcla = carpeta / "mezcla"
            self.ultima_salida = mezcla if mezcla.is_dir() else carpeta / "masters"
            self.btn_abrir.configure(state="normal")
            messagebox.showinfo("Meazclador", f"¡Listo! Los resultados están en:\n{self.ultima_salida}")

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
