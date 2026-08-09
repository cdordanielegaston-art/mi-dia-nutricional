# Mi Día Nutricional — notas del proyecto

App PWA de un solo archivo (`index.html`, React por CDN) que corre en la PC y en el celu.
Sincroniza entre dispositivos por un webhook de n8n. **No tiene backend propio.**

## Piezas

| Pieza | Dónde |
|---|---|
| App | `index.html` (v27) — abrir con doble clic o desde el celu |
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
