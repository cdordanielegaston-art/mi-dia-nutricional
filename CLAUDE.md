# Mi Día Nutricional — notas del proyecto

App PWA de un solo archivo (`index.html`, React por CDN) que corre en la PC y en el celu.
Sincroniza entre dispositivos por un webhook de n8n.

## Piezas

| Pieza | Dónde |
|---|---|
| App | `index.html` (v43) — abrir con doble clic o desde el celu |
| **Bridge** | `mdn_bridge.py` — backend Flask que conecta con la suscripción Max ($0 API) |
| Sync | n8n Cloud: workflow **`Mi Dia Nutricional - Sync`**, ID `TQDi7FTn8YUU1YYR` |
| Webhook | `https://ecddaniele.app.n8n.cloud/webhook/mdn-sync` |
| Payload | `POST {op:"get"\|"set", code:<código de sync>, data:<json>}`, `Content-Type: text/plain` (evita el preflight CORS) |
| Guardián | GitHub Actions `.github/workflows/keepalive.yml`, cada 15 min |
| Repo | `github.com/cdordanielegaston-art/mi-dia-nutricional` |

## Por qué existe el keepalive

n8n Cloud **apaga solo** el workflow cuando su instancia se reinicia por falta de RAM. El sync
queda muerto y Gastón se entera cuando el celu y la PC ya no coinciden. El guardián corre **en
GitHub, afuera de n8n**, así que funciona incluso con la instancia caída.

Diseño en dos niveles:

- **Nivel 1 (sin API key, no gasta cuota de n8n):** un `GET` al webhook alcanza para saber el estado,
  porque n8n responde distinto y **no ejecuta el workflow**:
  - activo → `"This webhook is not registered for GET requests..."`
  - caído → `"The requested webhook ... is not registered"`
- **Nivel 2 (con `N8N_API_KEY`):** si está caído, `POST /api/v1/workflows/<ID>/activate` y **verifica
  de nuevo el estado** — que la API devuelva 200 no prueba que haya quedado activo.

Manda mail **solo** si está caído y no se pudo reactivar. Un n8n lento o un timeout de red es
`::warning::` (sin mail), porque se reintenta solo en 15 minutos.

---

## ⚠️ LECCIÓN (2026-08-07) — un guardián cuyo secret nunca existió reportó ~98 "éxitos" falsos

**ERROR.** El keepalive venía marcando **success ~98 veces seguidas**. No vigilaba nada: el secret
`N8N_API_KEY` **nunca se había creado**, y el script salía con `exit 0` silencioso cuando la variable
estaba vacía. En verde, y decorativo. Se descubrió de casualidad, investigando otra cosa (dos runs
colgados 15 min por `curl` sin `--max-time`, que sí mandaron mail).

**CAUSA RAÍZ.** Dos fallas que se combinan:
1. **La falta de credencial se trató como "nada que hacer" en vez de como falla.** `exit 0` cuando falta
   lo único que te permite actuar convierte al guardián en un adorno.
2. **Nunca se ejercitó el camino de reparación.** El happy path (todo activo → salir) corría 96 veces
   por día; el camino que importa —detectar caído y arreglarlo— **no corrió jamás**. Verde ≠ probado.

**REGLA.**
- **Un guardián sin su credencial es una falla ruidosa, no un no-op.** Si falta lo que necesita para
  reparar, que lo diga.
- **Todo mecanismo de auto-reparación se prueba provocando la falla.** Existe
  `.github/workflows/simulacro-keepalive.yml`: apaga el sync a propósito (manual, hay que escribir
  `APAGAR`) para comprobar que el keepalive lo prende solo. **Correrlo cada vez que se toque el
  keepalive.** Verificado end-to-end el 2026-08-07: apagado → `Sync CAIDO` → `activate HTTP 200` →
  `OK: el sync volvio a estar ACTIVO`, 13 segundos.
- **`curl` en CI siempre con `--max-time` y `--connect-timeout`,** y el job con `timeout-minutes`.
  Sin eso, un cuelgue de red = job cancelado a los 15 min = mail de error por un hipo.
- **Verificar el efecto, no la respuesta.** Después del `activate`, volver a preguntar el estado.

**Corolario general:** una racha de verdes no es evidencia de que algo funcione — es evidencia de que
**alguna** rama del código termina en éxito. Preguntar *"¿qué rama corrió?"*, no *"¿pasó?"*.

## Modelos del chat — medido contra la API el 2026-08-08

Nueve modelos, agrupados en el selector por **qué key necesitan** (`GRUPOS` + campo `grupo`).

| Grupo | Modelo | Medido |
|---|---|---|
| 🆓 key gratis | `gemini-3.5-flash-lite` | **~3 s, constante.** Es el default y el que conviene |
| 🆓 key gratis | `gemini-3.6-flash` | **errático: 4 s y 76 s el mismo pedido** |
| 💳 con crédito | `gemini-3.5-flash-lite-p` | el mismo Lite, sin tope diario |
| 💳 con crédito | `gemini-3.6-flash-web` | **el único que busca en Google** y cita fuentes |
| 💳 con crédito | `gemini-pro-latest` | el potente. US$0,006/consulta |
| 🔑 sin key de Google | Haiku · Sonnet · GPT-4o mini · GPT-4o | keys propias; Claude sí busca |

**Lo que hay que saber para no repetir el diagnóstico:**

- **La búsqueda de Google NO existe en el tier gratuito.** Verificado a fondo: 429 (cuota 0) en
  los 7 modelos disponibles, con los dos nombres de la herramienta (`googleSearch` y
  `googleSearchRetrieval`), en `v1beta` y `v1alpha`, y con el permiso `toolConfig` puesto. Los 2.5
  —que según la doc sí la tenían— devuelven 404 *"no longer available to new users"*. Con la key de
  crédito funciona a la primera.
- **`urlContext` SÍ entra en el tier gratuito:** no busca, pero abre cualquier link que le pases.
  Es el reemplazo práctico de la búsqueda.
- **Para combinar herramientas nativas de Google con las nuestras** hace falta
  `toolConfig.includeServerSideToolInvocations: true`. Sin eso, HTTP 400. No estaba en la doc.
- **Gemini 3 firma sus llamadas** con un `thoughtSignature` dentro del `functionCall`: hay que
  reenviar las `parts` del modelo **tal cual vinieron** o responde 400. Por eso el adaptador hace
  `contents.push({role:'model', parts})` sin tocar nada.
- **El "pensamiento" se descuenta de `maxOutputTokens`.** Pensaba 552 tokens para responder 77, y con
  el prompt grande de la app se quedaba sin lugar y **cortaba la respuesta a la mitad**. Fix:
  `maxOutputTokens: 8192` + `thinkingLevel: 'minimal'` en los marcados `rapido`. Ojo: `'low'` todavía
  piensa (190 tokens) y `thinkingBudget: 0` da 400 — **el que apaga de verdad es `'minimal'`**.
- **Timeout de 30 s con un reintento**, porque el Flash gratis se cuelga y la app quedaba
  "pensando…" para siempre.
- Las funciones **sin parámetros** van sin el campo `parameters` (un `properties` vacío da 400).
- Las dos keys viven solo en `localStorage` (`geminiKey` y `geminiKeyPago`) y **no se sincronizan**:
  hay que cargarlas en cada dispositivo. Con la gratis Google entrena con el contenido; con crédito, no.

Todo esto está resumido para el usuario **dentro de la app**: ⚙️ del chat → *"🧭 ¿Cuál conviene?"*,
más un aviso naranja que aparece solo al elegir el Flash errático.

## Datos operativos

- **API key de n8n:** creada 2026-08-07, nombre `GITHUB KEEPALIVE - Mi Dia Nutricional`, **sin
  vencimiento**, todos los permisos. Vive **solo** en el secret `N8N_API_KEY` de GitHub — no está en
  ningún archivo de la PC. Si n8n la rechaza (HTTP 401/403), el keepalive lo dice en el mail: hay que
  regenerarla en n8n → Settings → API y actualizar el secret.
- **SSL desde Python en esta PC:** falla por Norton (ver regla global). Para hablar con n8n desde acá,
  usar `curl --ssl-no-revoke` (Git Bash usa Schannel, no OpenSSL).
- **El editor de n8n congela el renderer del navegador** al abrir el canvas del workflow. Para operar
  n8n desde automatización, usar la API REST, no la UI.

## MDN Bridge (2026-08-13)

Backend que conecta la app con la **suscripción Claude Max** ($0 API) vía **Agent SDK**.

| Aspecto | Detalle |
|---|---|
| Archivo | `mdn_bridge.py` |
| Puerto | **8793** (8792 ocupado por SPEED) |
| Patrón | MAX BRIDGE obligatorio (ver `apps ECD\MAX BRIDGE\CLAUDE.md`) |
| MCP tools | 11 herramientas (agregar/quitar comida, cargar día típico, gasto, etc.) |
| Modelos | `bridge-haiku` (Haiku 4.5) y `bridge-sonnet` (Sonnet 4.6) |
| **Dónde corre** | **La Intergaláctica** (2026-08-19) — es el servidor y queda prendida, así que la app anda con la PC Normal apagada |
| Ruta allá | `C:\Users\Usuario\apps\mdn_bridge` · tarea `MDN Bridge` · el Python de esa PC |
| Desde casa | `http://192.168.1.251:8793/` |
| Desde el celular | Tailscale `http://100.112.91.4:8793/` |
| En la PC Normal | tarea **deshabilitada**, lista por si hay que volver: `Enable-ScheduledTask -TaskName 'MDN Bridge'` |
| Mixed content | Resuelto: el bridge sirve la PWA en `/` → mismo origen |
| Arranque | `python mdn_bridge.py` con `CreateNoWindow` (NO usar `pythonw`, muere mudo) |

**Cómo se usa desde el celular:**
1. Bridge corriendo en la PC (`python mdn_bridge.py`)
2. Celular abre `http://100.110.55.41:8793/` (Tailscale) — la app carga desde el bridge
3. Todo es mismo origen → sin CORS, sin mixed content
4. El chat auto-detecta el bridge y selecciona Haiku gratis

**Arranca solo** con la tarea programada `MDN Bridge` (`instalar_autostart.ps1`, `-Quitar` la saca).
Corre con **`pythonw`**: sin ventana y **sin conhost**, CPU 0% en reposo, ~78 MB.

⚠️ `pythonw` moría mudo hasta el 2026-08-13: `logging.basicConfig` arma un `StreamHandler(sys.stderr)`
y bajo `pythonw` `sys.stderr` es `None`. El fix es redirigir `stdout`/`stderr` al log **arriba de todo
el módulo, antes de tocar `logging`** — hacerlo dentro de `__main__` es tarde, el import ya explotó.

### De dónde salía la lentitud (medido, no supuesto)

| Componente | Tiempo | ¿Evitable? |
|---|---|---|
| Arrancar el proceso `claude.exe` | **6,81 s** | ✅ sí — `ClaudeSDKClient` lo deja vivo |
| Inferencia | 4,07 s | ❌ no |

`query()` levanta un proceso por pedido → pagaba 6,81 s **siempre**. `ClaudeSDKClient` lo abre una
vez: **11 s → ~5 s sin tocar una sola capacidad**. El proceso además conserva la conversación entre
pedidos (un `session_id` nuevo NO la aísla), así que "no, eso no" entiende a qué se refiere.

`/warmup` lo arranca cuando la app abre, para que el primer mensaje tampoco pague los 6,8 s.
Se recicla si cambia el modelo/catálogo, si el front manda otro `convId`, o cada 40 pedidos.

### Streaming (`/chat/stream`, SSE) — qué mejora y qué no

Los ~4 s de inferencia no bajan. Lo que baja es **la espera en blanco**, y solo donde había mucha:

| Caso | Espera en blanco que se ahorra |
|---|---|
| Análisis largo (~3.400 caracteres) | **12,0 s** (47 deltas) |
| Con búsqueda web | 2,8 s |
| Confirmación de una línea | 0 s — se genera en ~200 ms, no hay nada que ver escribirse |
| El **día** en pantalla (cualquier caso) | **1,5–2,0 s** — la herramienta corre antes de que redacte |

Necesita `include_partial_messages=True`: sin eso el SDK entrega bloques ya cerrados y el texto
aparece de golpe igual. Llegan **deltas** (pintar) y **bloques cerrados** (texto definitivo): el front
*reemplaza* con el bloque en vez de sumarlo, si no duplica todo. `/chat` queda como respaldo y el
front cae solo si el stream falla.

**Estado de verificación** (2026-08-13): probado Haiku y Sonnet, imágenes con el payload real del
front, muerte del proceso `claude` a mano (se rearma solo), instancia única, y streaming medido en
el navegador. **Sin probar:** el reciclado a los 40 pedidos.

### Por qué la app tardaba una eternidad en abrir desde el celular

No era el bridge (responde en 100 ms por Tailscale) ni el firewall: era **el peso de la página**.

| | Antes | Ahora |
|---|---|---|
| Librerías (React, ReactDOM, **Babel**, jsPDF) | 3,3 MB **de internet** | 757 KB por Tailscale, gzip |
| index.html | 189 KB | 49 KB (gzip) |
| Segunda carga | **igual, 3,5 MB** | **0 KB** (todo del caché) |

**Babel solo son 2,78 MB** — el 85%. Y el agravante: por **HTTP contra una IP no hay contexto
seguro**, así que el **service worker NO se registra** y no hay caché de PWA — el celular se bajaba
los 3,5 MB **en cada carga**. Por eso se sentía peor cada vez, no mejor.

Arreglo: `bajar_vendor.ps1` las deja en `vendor/` y el bridge las sirve con gzip y
`Cache-Control: immutable` (eso da caché HTTP aunque no haya service worker). El `index.html`
**sigue apuntando al CDN** —así GitHub Pages funciona sin bridge— y el bridge **reescribe las URLs
al servirlo** (`VENDOR_LOCAL`): un solo archivo, sin duplicar. Si falta un vendor, esa librería
queda en el CDN y el log lo avisa. `vendor/` no va al repo: correr `bajar_vendor.ps1` en cada PC.

## ⚠️ CONVENCIONES DE GASTÓN (no están en el código: solo las sabe él)

| Escribe | Significa |
|---|---|
| **`;` al final** | **guardar el día** — `"700, desayuno típico, media mañana: 20 almendras;"` |
| lista separada por comas | varias acciones en un mensaje (así carga el día entero) |

Viven en `_RE_PIDE_GUARDAR` y en `_atajo_compuesto`. **Si aparece otra, va acá y a la auto-memoria
`feedback-convenciones-del-usuario`.**

## ⚠️ LECCIÓN (2026-08-14) — di por error algo que era una convención suya

**ERROR.** El asistente llamaba `guardar_dia` con `"700, desayuno típico, ...;"`. Como el prompt dice
"NUNCA guardes sin pedido explícito", lo declaré desobediencia y puse un gate que lo bloqueaba.
Gastón: *"; significa guardar día"*. **El modelo hacía lo correcto y yo le rompí algo que usa a diario.**

**CAUSA RAÍZ.** Vi un comportamiento que no encajaba con MI modelo del sistema y asumí que el
sistema estaba mal. No se me ocurrió que respondiera a una regla del usuario que yo no conocía.

**REGLA.** Antes de bloquear algo que parece un error, preguntarse **si es una convención del
usuario** — sobre todo si el modelo lo hace de forma consistente. Y todo gate determinístico sobre
acciones con consecuencias tiene que **dejar puerta a lo que el usuario definió**: `guardar_dia`
acepta el `;`, las palabras explícitas, y se corre solo si la memoria del asistente menciona una
convención de guardado (ahí el que sabe interpretarla es el modelo, no mi regex).

## ⚠️ LECCIÓN (2026-08-14) — "está lento" era el modelo haciendo trabajo de más, y mal

**ERROR.** Un pedido tardó **44,2 s** y Gastón lo reportó como lentitud. Tres hipótesis mías
—Sonnet es lento, la charla acumulada pesa, el prompt es grande— **las tres dieron NO** al medirlas
(Sonnet 12,8 s, degradación 0,90×, Haiku 13,3 s con el prompt real). La respuesta estaba en el log:

```
[stream] 44.2s | Sonnet | tools=['poner_gasto', 'cargar_comida_tipica',
                  'seleccionar_opcion', 'agregar_comida_libre', 'guardar_dia']
```

**5 herramientas, y 2 sobraban:** `guardar_dia` —que el prompt PROHÍBE sin pedido explícito— le
archivó el día solo, y `agregar_comida_libre` cargó la manzana **de nuevo** cuando
`seleccionar_opcion` ya había puesto "20g almendras + 1 fruta". Cada herramienta es una ida y vuelta
al modelo: **el trabajo de más ERA la lentitud**, y encima ensuciaba el día.

**CAUSA RAÍZ.** La instrucción estaba escrita en el system prompt y el modelo la desobedeció igual.
**Una acción que toca el historial no puede depender de que el modelo obedezca una frase.**

**REGLA.**
- **Gate determinístico sobre toda acción con consecuencias** (archivar, borrar, plata). `guardar_dia`
  ahora verifica contra `_state["_mensaje"]` —lo que el usuario escribió textualmente— y si no lo
  pidió, **devuelve error y le dice al modelo que siga con lo demás**. El prompt pide; el código
  garantiza. Es el mismo criterio que la regla global de determinismo.
- **Cuando el usuario dice "está lento", mirar QUÉ HIZO, no solo cuánto tardó.** El log con la lista
  de herramientas resolvió en 30 segundos lo que tres tandas de mediciones no habían encontrado.
  Por eso `[chat]`/`[stream]` loguean siempre las tools.
- **Un tiempo alto suele ser trabajo de más, no lentitud del modelo.**

**Resultado:** 44,2 s → **9,8 s** y **1 herramienta en vez de 5**, sin duplicar la fruta (y sí
guardando, porque el `;` lo pedía). Comprobado con el pedido textual de la captura:
`tests/test_gate_guardar.py`.

### Pedidos compuestos: resolver local y molestar al modelo solo con lo que sobra

Gastón carga el día con una lista: `"700, desayuno típico, media mañana: 20 almendras y 1 fruta;"`.
Mandarlo entero cuesta **una vuelta al modelo por cada herramienta**. `_atajo_compuesto` corta por
comas (sin romper paréntesis), resuelve local cada parte que reconoce sin ambigüedad, y le manda al
modelo **solo el resto**:

| Pedido | Antes | Ahora |
|---|---|---|
| `700, desayuno típico, media mañana: 20 almendras y 1 fruta;` | 44,2 s · 5 tools | **9,8 s · 1 tool** |
| `2400, desayuno típico, almuerzo típico, cena típica;` | ~15 s · 4 tools | **0,00 s · sin modelo** |

Un número suelto solo cuenta como gasto **si es el primer ítem de una lista** (aislado sería
ambiguo: podrían ser las kcal de algo). Y la respuesta del modelo se prefija con lo hecho localmente
(`_sumar_lo_hecho`): si no, el usuario pide cuatro cosas y lee la confirmación de una sola.

## ⚠️ LECCIÓN (2026-08-13) — optimicé por el camino fácil y le saqué la mitad de la app

**ERROR.** Ante "está muy lento", metí atajos con regex para saltear a Claude. Bajó a 0,3 s y
**rompió cuatro cosas a la vez**. Gastón lo resumió: *"perdió funcionalidad, velocidad, rendimiento
y hasta inteligencia"*. Un test de 22 mensajes reales dio **6 falsos positivos**:

| Le decías | Hacía |
|---|---|
| "poné pechuga 200g en el almuerzo" | cargaba el **almuerzo típico entero**, pisándole el pedido |
| "poneme 2400 de gasto y cargame el desayuno" | solo el gasto — **perdía la mitad** |
| "gasté 2400 hoy, ¿cuánto déficit tengo?" | **ni ponía el gasto** y contestaba el resumen viejo |
| "¿cómo voy con la proteína?" | plantilla fija en vez de análisis |

Y arrastraba otras tres pérdidas que **no eran de los atajos sino del bridge desde el día uno**:
`tools=[]` (sin WebSearch/WebFetch, con un prompt que le pide buscar datos oficiales), sin historial
(mandaba solo el último mensaje) y las **imágenes descartadas en silencio**.

**CAUSA RAÍZ.** Los atajos hacían *matching por substring sobre lenguaje natural* — exactamente el
trabajo que un LLM hace bien y una regex no. Y yo **nunca medí de dónde venían los 11 s**: si lo
hubiera hecho, habría visto que el 65% era arrancar el proceso, no la inteligencia. **Optimicé lo que
era fácil de recortar en vez de lo que estaba costando el tiempo.**

**REGLA.**
- **Medir antes de optimizar.** Un spike de 30 líneas (`arranque` vs `inferencia`) mostró que el
  problema no era el modelo. Toda la mejora real salió de ahí; los atajos solo hicieron daño.
- **Un atajo se ancla con `^...$` y cubre el mensaje COMPLETO.** Si sobra una palabra, va a Claude.
  Un atajo de más cuesta un día mal cargado; uno de menos cuesta 4 segundos. **La asimetría manda.**
- **Sin atajo para lo que pide matiz** ("cómo voy", "guardá"): una plantilla fija ahí se lee como que
  el asistente se volvió tonto.
- **Todo atajo tiene que dejar rastro para el modelo.** Segundo bug, encontrado por el mismo test:
  "cargame el almuerzo típico" (atajo) → "no, pechuga de 200 mejor" → Claude, que **nunca se enteró
  del almuerzo**, la puso en el desayuno. El atajo no estaba mal escrito: **faltaba contarle lo que
  había hecho**. Ahora cada atajo apila su acción en `_acciones_atajo` y el próximo pedido la lleva.
- **La prueba es una CONVERSACIÓN, no un mensaje.** Los dos bugs peores solo aparecen en el
  mensaje N+1. `scratchpad/test_conversacion.py` corre un guión de 7 vueltas encadenadas y verifica
  el `state` resultante, no el texto de la respuesta.

**Corolario:** mis bugs no fueron líneas equivocadas — fueron **líneas ausentes** (el rastro del
atajo, las tools, el historial, las imágenes). Ninguna falla ruidosa: la app arrancaba, contestaba
y se veía bien. Por eso hay que ejercitarla, no leerla.

## Resumen del día (2026-08-18) — tabla por comida, reasignable con el mouse

Abajo de todo, justo antes del chat: una fila por alimento cargado, con sus macros en la
columna de la comida a la que cuenta (`6 carb, 0 pro 0 gra = 80 calorías`), y una fila final de
calorías por comida más el total. El formato salió de una planilla que usa Gastón.

**Lo que se puede mover.** El catálogo fija a qué comida pertenece cada sección, pero la vida no:
la banana está en la sección del desayuno y se la comió de postre del almuerzo. Cada alimento se
**arrastra** a otra columna (mouse) o se **toca** para elegir destino de una lista (celular —
el drag & drop de HTML5 no funciona con el dedo). Los movidos quedan con un punto `•` y hay un
`↺ deshacer los N movidos` que devuelve todo a su lugar de catálogo.

- Estado: `reasign` = `{ 'sec:des_carb': 'almuerzo', 'lib:x123': 'cena' }`. Volver un ítem a su
  comida de origen **borra** la entrada en vez de guardar "está donde ya estaba".
- Solo afecta a esta tabla; la vista de arriba y `¿Cómo voy?` siguen mostrando las secciones donde
  están. El **total del día no cambia** al mover: es reasignar, no sumar.
- Viaja en el sync (`canonBlob` + blob `_v: 29`), se guarda con el día (`saveDay`/`loadDay`) y se
  limpia con `resetAll`.
- La columna **OTROS** solo aparece si tiene algo: es el cajón de lo que no cae en ninguna comida
  (extras del día, leche, huevos sueltos y las comidas libres), para reubicar desde ahí.

## Optimización del pedido (2026-08-19) — y por qué la Intergaláctica parecía lenta

Gastón pidió mudar el bridge a la Intergaláctica "solo si no lo hace ni 1% más lento". La primera
medición dio **+26%** y casi lo descarto. Era un **artefacto de la comparación**:

| Se comparaba | PC Normal | Intergaláctica |
|---|---|---|
| bridge con días de uso (prompt cacheado) | 4,4 s | — |
| bridge recién arrancado (caché frío) | — | 5,6 s |

Reiniciando el de la PC Normal para dejar a las dos parejas, la brecha se desplomó a **+0,44 s**, y
el tramo "hasta el primer evento" quedó en **+0,02 s**. Con el **SDK puro** (sin bridge, sin red) las
dos máquinas rinden igual: **4,47 s contra 4,55 s, +1,8%**.

**Lección: nunca comparar un proceso caliente contra uno recién levantado.** El proceso persistente
acumula estado que lo hace ver mejor de lo que es. Igualar el punto de partida antes de medir.

### Lo que sí bajó el tiempo, en las dos máquinas

1. **`include_partial_messages=False`** (`DELTAS_DE_TEXTO`, se enciende con `MDN_DELTAS=1`).
   Ver la respuesta escribirse letra por letra cuesta **~0,6 s por pedido (14%)**: son ~50 mensajes
   por el pipe en vez de ~15. Y las respuestas de esta app son de una línea — no hay nada que ver
   escribirse. **No saca el streaming**: los `AssistantMessage` siguen llegando, así que el día se
   actualiza apenas corre cada herramienta, que es la parte que de verdad se nota.
2. **El warmup ahora precalienta el prompt**, no solo arranca el proceso: manda un pedido trivial
   para que el catálogo (~3.000 tokens) quede procesado. El primer pedido real ya no lo paga.

**Resultado:** PC Normal 4,4 → **3,6 s**. Intergaláctica 5,6 → **4,4 s**. Las dos ~20% más rápidas.

### Lo que se descartó midiendo (no suponiendo)

- **Antivirus**: exclusiones de Defender acotadas al bridge y su runtime → **sin efecto** (+1,17 s
  contra +1,20 s). **Revertidas**, para no dejar la protección bajada a cambio de nada.
- **Plan de energía**: las dos en Equilibrado. **Carga de CPU**: la Intergaláctica está *menos*
  cargada (5% contra 56%). **DNS/proxy/exit node**: iguales. **CLI**: las dos usan el bundled.
- **Internet**: la Intergaláctica es *mejor* (29 ms contra 101 ms a la API).

Queda un ~20% de diferencia que no se explicó: con el SDK puro empatan, pero a través del bridge la
Intergaláctica va 0,8 s atrás. La causa no se encontró.
