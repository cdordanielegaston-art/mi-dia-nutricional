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
| Acceso celular | Tailscale `http://100.110.55.41:8793/` |
| Mixed content | Resuelto: el bridge sirve la PWA en `/` → mismo origen |
| Arranque | `python mdn_bridge.py` con `CreateNoWindow` (NO usar `pythonw`, muere mudo) |

**Cómo se usa desde el celular:**
1. Bridge corriendo en la PC (`python mdn_bridge.py`)
2. Celular abre `http://100.110.55.41:8793/` (Tailscale) — la app carga desde el bridge
3. Todo es mismo origen → sin CORS, sin mixed content
4. El chat auto-detecta el bridge y selecciona Haiku gratis

**pythonw NO funciona** — muere antes de que `logging.basicConfig` cree el `StreamHandler(sys.stderr)`,
porque `sys.stderr` es `None`. Usar `python.exe` + `CreateNoWindow` en su lugar.

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
el navegador. **Sin probar:** el celular por Tailscale y el reciclado a los 40 pedidos.

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
