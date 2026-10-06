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
40 minutos, un WAV por micrófono), elegí esa carpeta y tocá *Analizar*. Aparece un **mapa de la
sesión**: cada franja celeste es un tema. **Hacé clic en cualquier punto del mapa para escucharlo.**
Si junta o parte temas, mové la *sensibilidad*: el mapa se actualiza al instante. Para cada tema
podés escuchar el inicio y el final, correr cada borde de a 1 segundo o llevarlo a la marca ◆
(el último clic en el mapa), dividir, unir, borrar y ponerle nombre. Después tocá *Cortar temas*.
Los archivos se leen de a pedazos, así que no importa que pesen varios GB.

**Pestaña 2 · Mezclar y masterizar.** Elegí la carpeta de un tema o la carpeta `temas` para
mezclarlos todos. Elegí el estilo y tocá *Mezclar y masterizar*. Cada tema queda en
`tema/mezcla/master.wav` y además todos juntos en `temas/masters/`.

**Pestaña 3 · Retocar.** Después de mezclar, subí o bajá voz, coros, guitarras, bajo y batería,
la cantidad de reverb, **sacar sala** (0 % = la habitación original, 150 % = más seco) y la
**presencia** del máster (cuánto trae todo adelante), y tocá *Aplicar*. Si en un tema canta otro
integrante, elegí ahí la **voz principal**: se vuelven a procesar sólo las voces.
No vuelve a procesar las pistas, así que tarda segundos. Escuchá *Mezcla actual* y *Versión anterior*
desde el mismo punto para comparar. Los retoques se guardan: si volvés a mezclar el tema, se mantienen.

Cualquier trabajo largo se puede frenar con **✖ Cancelar**.

## Estilos

| | Natural | Punk (Ramones) |
|---|---|---|
| Guitarras | EQ y compresión | Si se grabaron **por línea (DI)**: simulador de ampli británico saturado + gabinete 4x12. Si ya tienen ampli: saturación extra. Abiertas a izquierda y derecha: pared de guitarras. |
| Bajo | Compresión | Distorsión en paralelo: graves limpios + medios con gruñido que se oyen entre las guitarras. |
| Batería | Compresión de bus y paralela | **Sampler**: cada golpe de bombo y caja se refuerza con un sample (incorporado o el tuyo), respetando la fuerza de cada golpe. Realce de ataque y compresión paralela más fuerte. |
| Voz | Afinación opcional | **Sólo se corrigen las notas que se pasan de 35 cents**; el resto queda intacto, con su suciedad. Eco corto (slapback) en vez de reverb larga. |
| Coros | Abiertos, con reverb | Abiertos, comprimidos y saturados (coro de pandilla). |
| Sala | Se saca un poco de habitación a voces y coros | Se saca la habitación de voces, coros, guitarras y tambores, sin tocar los graves (retocable en la pestaña 3) |
| Máster | EQ por octavas hacia la curva de un disco, presencia 30 % | Igual, presencia 60 %: compresión paralela suave, cuerpo en graves y aire arriba |
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

# retocar una mezcla ya hecha (segundos): más voz, menos reverb, más adelante
meazclador retocar temas/03_Help --voz +2 --reverb 50 --presencia 0.8

# si la detección de guitarras se equivoca
meazclador mezclar temas/03_Help --estilo punk --guitarras directas
```

En la carpeta de cada tema, `mezcla/` contiene:

| Archivo | Para qué |
|---|---|
| `master.wav` | La canción terminada (24 bits, 48 kHz). |
| `premaster.wav` | La mezcla sin masterizar, con margen, por si la querés mandar a un estudio de mastering. |
| `informe.txt` | Qué se hizo en cada pista y por qué. |
| `master_anterior.wav` | La versión antes del último retoque, para comparar. |
| `pistas_procesadas/` | Las pistas ya procesadas, para poder retocar rápido. Se pueden borrar si necesitás espacio (después no se puede retocar sin volver a mezclar). |

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
- **Verificación por contenido:** los nombres de los canales no siempre coinciden con lo que capta
  cada micrófono (pasa mucho en consolas en vivo). Antes de mezclar se comprueba:
  - qué pista es de verdad el redoblante (la que golpea entre los golpes del bombo);
  - si algún overhead casi no tiene platillos (se trata como micrófono de sala, más bajo y sin graves);
  - si algún micrófono de voz no canta en el tema (nivel parejo de lo que se cuela): se silencia.
  Todo queda anotado en el informe. Los toms llevan compuerta para no sumar la banda entre golpes.
- **Voz principal automática:** en cada tema se mide cuánto canta cada pista de voz. Si una pista
  llamada "coro" canta claramente más que la "voz" (por ejemplo, un tema donde canta otro integrante),
  se intercambian los papeles y queda anotado en el informe. Si las dos cantan parecido no se toca nada;
  en ese caso, renombrá los archivos de ese tema.

## Tests

```bash
pip install -e ".[dev]"
pytest
```
