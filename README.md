# meazclador

Mezcla y masterización automática de las pistas de tu banda. Le das una carpeta con un
WAV por instrumento/voz y te devuelve un máster listo para Spotify/YouTube, más un
informe en castellano que explica cada decisión (para que también aprendas a mezclar).

## Qué hace

Por cada pista, lo que haría un ingeniero de mezcla:

1. **Reconoce el instrumento** por el nombre del archivo (bombo, caja, bajo, guitarra, voz, coros…).
2. **Corrige la fase** de los micrófonos de batería respecto de los overheads.
3. **Afina voces y coros** (opcional) sin efecto robot: corrige el centro de cada nota y
   conserva el vibrato y la expresión.
4. **Limpia**: filtro paso alto, expansor para el sangrado de los tambores y recorte de
   resonancias que suenan todo el tiempo (zumbidos de sala, "ring" de parches).
5. **Ecualiza** según el instrumento (saca barro, agrega presencia y aire).
6. **Comprime** en una o dos etapas con umbrales calculados según cada pista, y aplica de-esser a las voces.
7. **Hace lugar entre instrumentos**: hueco para la voz en las guitarras y para el bombo en el bajo.
8. **Balancea y panea**: niveles relativos a la voz, guitarras dobladas abiertas, coros a los costados.
9. **Arma buses**: compresión de bus y compresión paralela en la batería, y una reverb
   compartida con pre-delay.

Después masteriza: graves en mono, balance tonal comparado con una curva de discos de
rock/pop (o con **un tema de referencia tuyo**), compresión de "pegamento", saturación
suave y limitador true-peak hasta el volumen elegido (-14 LUFS por defecto).

## Instalación

Necesitás Python 3.10 o más nuevo.

```bash
pip install -e .
```

## Cómo preparar las pistas

- Exportá **todas las pistas desde el mismo punto de inicio** (el compás 1), así quedan sincronizadas.
- Una pista por archivo, **sin efectos** (ni reverb ni compresión), y con picos por debajo de -6 dBFS.
- Ponele a cada archivo **un nombre que diga qué es**: `Bombo.wav`, `Caja.wav`, `OH L.wav`,
  `Bajo.wav`, `Guitarra 1.wav`, `Guitarra 2.wav`, `Voz.wav`, `Coros.wav`, `Piano.wav`…
  (en inglés también sirve: `Kick`, `Snare`, `Gtr`, `Lead Vox`, `BV`…).
  Si no reconoce un nombre, lo trata como "otros" y lo aclara en el informe.

## Uso

```bash
# mezcla básica
meazclador pistas/mi_tema

# con afinación de voces (0 = nada, 1 = máxima) y la tonalidad del tema
meazclador pistas/mi_tema --afinar 0.5 --tonalidad Am

# imitando el sonido y el volumen de un disco que te guste
meazclador pistas/mi_tema --referencia "referencias/tema_favorito.wav"

# más fuerte (rock pesado) o más dinámico
meazclador pistas/mi_tema --lufs -10
meazclador pistas/mi_tema --lufs -16
```

En `pistas/mi_tema/mezcla/` quedan:

| Archivo | Para qué |
|---|---|
| `master.wav` | La canción terminada (24 bits, 48 kHz). |
| `premaster.wav` | La mezcla sin masterizar, con margen, por si la querés mandar a un estudio de mastering. |
| `informe.txt` | Qué se hizo en cada pista y por qué. |

¿No tenés pistas a mano? Generá una banda de prueba sintética:

```bash
python scripts/generar_demo.py demo/pistas
meazclador demo/pistas --afinar 0.5 --tonalidad Am
```

## Límites

- No hace magia con grabaciones con problemas: el clipping, la distorsión o una sala muy mala
  se pueden disimular, pero no deshacer.
- Las decisiones salen del análisis de las pistas y de recetas de mezcla habituales, no de
  escuchar. Escuchá el resultado; si algo no te convence (más voz, menos reverb…) se pueden
  ajustar los valores de `BALANCE` en `meazclador/mezcla.py` y `RECETAS` en `meazclador/procesos.py`.
- La afinación funciona con voces solistas o coros por pista; no con varias voces en un mismo archivo.

## Tests

```bash
pip install -e ".[dev]"
pytest
```
