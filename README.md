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

## Instalación (sin saber programar)

1. Entrá a la página de descargas del repositorio en GitHub (**Releases → "Meazclador - última versión"**).
2. **Windows:** bajá `Meazclador-Windows.exe` y abrilo con doble clic. Si aparece *"Windows protegió
   su PC"*, tocá *Más información* → *Ejecutar de todas formas* (le pasa a todo programa sin firma digital).
   Tarda unos segundos en abrir la primera vez.
3. **Mac (M1/M2/M3/M4):** bajá `Meazclador-macOS.zip`, descomprimilo, arrastrá `Meazclador.app` a
   Aplicaciones y la primera vez abrilo con clic derecho → *Abrir*.

Los ejecutables se arman y se prueban solos en GitHub cada vez que cambia el código
(`.github/workflows/ejecutables.yml`).

## Uso con la ventana

**Pestaña 1 · Cortar la grabación larga.** Si grabaron un ensayo o un show entero (por ejemplo
40 minutos, un WAV por micrófono), elegí esa carpeta y tocá *Buscar temas*. Aparece la lista de
temas con sus tiempos: corregí lo que haga falta, ponele nombre a cada tema (`0:12  3:05  Help`)
y tocá *Cortar temas*. Los archivos se leen de a pedazos, así que no importa que pesen varios GB.
Si junta dos temas, bajá la *sensibilidad*; si deja charla adentro, subila.

**Pestaña 2 · Mezclar y masterizar.** Elegí la carpeta de un tema o la carpeta `temas` para
mezclarlos todos. Elegí el estilo y tocá *Mezclar y masterizar*. Cada tema queda en
`tema/mezcla/master.wav` y además todos juntos en `temas/masters/`.

## Estilos

| | Natural | Punk (Ramones) |
|---|---|---|
| Guitarras | EQ y compresión | Si se grabaron **por línea (DI)**: simulador de ampli británico saturado + gabinete 4x12. Si ya tienen ampli: saturación extra. Abiertas a izquierda y derecha: pared de guitarras. |
| Bajo | Compresión | Distorsión en paralelo: graves limpios + medios con gruñido que se oyen entre las guitarras. |
| Batería | Compresión de bus y paralela | **Sampler**: cada golpe de bombo y caja se refuerza con un sample (incorporado o el tuyo), respetando la fuerza de cada golpe. Realce de ataque y compresión paralela más fuerte. |
| Voz | Afinación opcional | **Sólo se corrigen las notas que se pasan de 35 cents**; el resto queda intacto, con su suciedad. Eco corto (slapback) en vez de reverb larga. |
| Coros | Abiertos, con reverb | Abiertos, comprimidos y saturados (coro de pandilla). |
| Volumen | -14 LUFS | -10 LUFS, con clipper suave antes del limitador. |

Para que el sampler funcione bien, el bombo y la caja tienen que tener su propio micrófono
(`Bombo.wav`, `Caja.wav`). Podés usar tus propios samples (un WAV con un solo golpe).

## Uso desde la consola (opcional)

```bash
pip install -e .

# cortar una sesión larga en temas (deja SESION/temas/ y una lista editable temas.txt)
meazclador cortar sesion_ensayo/
meazclador cortar sesion_ensayo/ --cortes sesion_ensayo/temas/temas.txt   # con tus correcciones

# mezclar todos los temas en estilo punk
meazclador mezclar sesion_ensayo/temas --estilo punk

# un tema, con su tonalidad, samples propios y un tema de referencia
meazclador mezclar temas/03_Help --estilo punk --tonalidad A \
    --sample-bombo mis_samples/bombo.wav --sample-caja mis_samples/caja.wav \
    --referencia "referencias/Blitzkrieg Bop.wav"

# si la detección de guitarras se equivoca
meazclador mezclar temas/03_Help --estilo punk --guitarras directas
```

En la carpeta de cada tema, `mezcla/` contiene:

| Archivo | Para qué |
|---|---|
| `master.wav` | La canción terminada (24 bits, 48 kHz). |
| `premaster.wav` | La mezcla sin masterizar, con margen, por si la querés mandar a un estudio de mastering. |
| `informe.txt` | Qué se hizo en cada pista y por qué. |

¿No tenés pistas a mano? `python -m meazclador.demo demo/pistas` genera una banda sintética de prueba.

## Armar el ejecutable a mano

```bash
pip install . pyinstaller
pyinstaller meazclador.spec     # deja dist/Meazclador(.exe)
dist/Meazclador --prueba        # autoprueba: mezcla una banda sintética
```

## Límites

- No hace magia con grabaciones con problemas: el clipping, la distorsión o una sala muy mala
  se pueden disimular, pero no deshacer.
- Las decisiones salen del análisis de las pistas y de recetas de mezcla habituales, no de
  escuchar. Escuchá el resultado; si algo no te convence (más voz, menos reverb…) se pueden
  ajustar los valores de `BALANCE` en `meazclador/mezcla.py` y `RECETAS` en `meazclador/procesos.py`.
- La afinación funciona con voces solistas o coros por pista; no con varias voces en un mismo archivo.
- El sampler necesita micrófonos cercanos de bombo y caja; con sólo overheads no se aplica.

## Tests

```bash
pip install -e ".[dev]"
pytest
```
