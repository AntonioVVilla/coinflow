# CryptoBot

> **AVISO: Este proyecto fue generado con asistencia de IA (vibecoded).** El codigo es funcional pero puede contener bugs sutiles o patrones de seguridad no revisados por un humano experto. **No lo uses con dinero real sin auditarlo antes.** Contribuciones y revisiones son bienvenidas.

Bot de trading de criptomonedas personal, inspirado en [OctoBot](https://github.com/Drakkar-Software/OctoBot). Corre en Docker, se conecta a Coinbase Advanced Trade, expone un dashboard web moderno con graficas en tiempo real y gestion de riesgo integrada.

---

## Tabla de contenidos

1. [Caracteristicas](#caracteristicas)
2. [Arquitectura](#arquitectura)
3. [Stack tecnologico](#stack-tecnologico)
4. [Requisitos previos](#requisitos-previos)
5. [Instalacion rapida](#instalacion-rapida)
6. [Configuracion](#configuracion)
7. [Conexion a Coinbase](#conexion-a-coinbase)
8. [Estrategias disponibles](#estrategias-disponibles)
9. [Gestion de riesgo](#gestion-de-riesgo)
10. [Dashboard](#dashboard)
11. [Seguridad](#seguridad)
12. [Notificaciones](#notificaciones)
13. [API REST](#api-rest)
14. [WebSocket](#websocket)
15. [Estructura del proyecto](#estructura-del-proyecto)
16. [Desarrollo local](#desarrollo-local)
17. [Troubleshooting](#troubleshooting)
18. [Roadmap](#roadmap)
19. [Descargo](#descargo)

---

## Caracteristicas

- **3 estrategias de trading**: Grid Trading, Dollar Cost Averaging (DCA), y ejecucion de senales via webhook (TradingView).
- **Paper trading**: simula trades con precios reales sin arriesgar dinero.
- **Dashboard web completo**: portfolio, P&L, graficas candlestick con tus trades marcados, historial, estadisticas.
- **Multi-moneda**: visualizacion en USD o EUR (tasa del BCE actualizada cada hora).
- **Gestion de riesgo**:
  - Stop-loss diario (limite de perdida en USD)
  - Drawdown maximo (% desde el pico de 30 dias)
  - Exposicion maxima por activo (% del portfolio)
  - Circuit breaker (pausa automatica si el precio cae X% en 1h)
  - Kill switch de emergencia (detiene todo y cancela ordenes abiertas)
- **Tiempo real via WebSockets**: precios y trades actualizandose sin refresh.
- **Autenticacion**: password para proteger el dashboard, bloqueo tras intentos fallidos.
- **Notificaciones**: Email (SMTP) y Telegram.
- **Snapshots automaticos**: portfolio historico cada 5 min para la grafica de evolucion.
- **Export a CSV**: historial de trades con filtros para uso fiscal/contable.
- **Encriptacion at rest**: API keys de Coinbase encriptadas con Fernet.
- **Docker-first**: un solo `docker compose up` y listo.

---

## Arquitectura

```
┌─────────────────────────────────────────────────────────┐
│                     DASHBOARD WEB                        │
│   Alpine.js + Chart.js (candlestick) + WebSocket        │
└──────────────┬──────────────────────┬───────────────────┘
               │ HTTP / WS            │
               ▼                      ▼
┌──────────────────────────────────────────────────────────┐
│                    FASTAPI (Python)                      │
│  ┌──────────┬──────────┬──────────┬──────────┬────────┐ │
│  │ /auth    │/dashboard│/strategies│ /trades │ /risk  │ │
│  │ /settings│ /webhook │  /ws      │         │        │ │
│  └──────────┴──────────┴──────────┴──────────┴────────┘ │
└─────┬─────────────┬──────────────┬────────────┬─────────┘
      │             │              │            │
      ▼             ▼              ▼            ▼
┌──────────┐ ┌───────────┐  ┌──────────┐ ┌──────────┐
│ Engine   │ │ Exchange  │  │   Risk   │ │  Notifs  │
│          │ │           │  │          │ │          │
│Scheduler │ │ Coinbase  │  │Pre-trade │ │ Telegram │
│ Runner   │ │  (ccxt)   │  │  checks  │ │  Email   │
│Snapshots │ │ Paper mode│  │  Circuit │ │          │
│          │ │  Forex    │  │  breaker │ │          │
└────┬─────┘ └─────┬─────┘  └────┬─────┘ └────┬─────┘
     │             │              │            │
     ▼             ▼              ▼            ▼
┌────────────────────────────────────────────────────┐
│              STRATEGIES                             │
│   Grid     │      DCA       │    Webhook           │
└────────────────────────────────────────────────────┘
              │
              ▼
┌────────────────────────────────────────────────────┐
│      SQLite (aiosqlite + SQLAlchemy)               │
│  api_keys | strategy_configs | trades              │
│  portfolio_snapshots | grid_orders | auth_config   │
│  risk_config | notification_settings               │
└────────────────────────────────────────────────────┘
```

### Flujo de un trade

1. El **scheduler** dispara un tick de estrategia (cada 30s para Grid, cada X horas para DCA).
2. La estrategia consulta el **ticker** via ccxt y decide si emite ordenes.
3. Cada orden pasa por **risk check** (exposicion, drawdown, loss diario, pause).
4. Si es aprobada, se envia al **exchange client** (Coinbase live o Paper).
5. El resultado se guarda en `trades`, se dispara **broadcast WS** y **notificacion** (email/telegram).
6. El dashboard actualiza KPIs en tiempo real.

---

## Stack tecnologico

| Componente | Tecnologia | Razon |
|---|---|---|
| Lenguaje | Python 3.12 | Mejor ecosistema para trading |
| Framework web | FastAPI 0.115 | Async nativo, validacion con Pydantic |
| ORM / DB | SQLAlchemy 2 async + aiosqlite | Zero-config, file-based |
| Exchange | ccxt 4.5 | Soporte unificado para 100+ exchanges |
| Scheduler | APScheduler 3 | Cron / intervalos async |
| Encriptacion | cryptography.fernet | Simetrica, stdlib-grade |
| Server | Uvicorn | ASGI performante |
| Frontend | Alpine.js 3 + Chart.js 4 + financial plugin | Sin build step |
| Forex | frankfurter.app (BCE) | Free, sin API key |
| Notifs | aiosmtplib + aiohttp | Async, ligero |
| Container | Docker multi-stage | Deploy portable |

---

## Requisitos previos

- **Docker** + **Docker Compose** (v2 plugin)
- Una cuenta de **Coinbase Advanced Trade** con API Key (permiso "Trade")
- Opcional: bot de **Telegram** o cuenta SMTP para notificaciones

---

## Instalacion rapida

```bash
# 1. Clonar/copiar el proyecto
cd /ruta/a/CryptoBot

# 2. Crear archivo .env (usa .env.example como plantilla)
cp .env.example .env

# 3. Construir y levantar
docker compose up -d --build

# 4. Abrir el dashboard
# http://localhost:8080
```

Por defecto arranca en **modo PAPER** (simulado, $10,000 virtuales). Al guardar tus API keys de Coinbase, cambia automaticamente a **modo LIVE**.

---

## Configuracion

Todas las variables viven en `.env`:

```env
# App
PAPER_MODE=true          # false para live trading por defecto
LOG_LEVEL=INFO
HOST=0.0.0.0
PORT=8080

# Encriptacion (opcional - se genera automaticamente si no se define)
ENCRYPTION_KEY=

# Telegram (opcional)
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=

# Email SMTP (opcional)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=tu@email.com
SMTP_PASS=app_password
EMAIL_TO=tu@email.com
```

El resto (API keys de Coinbase, password del dashboard, reglas de riesgo, estrategias) se configura desde la **UI web**.

---

## Conexion a Coinbase

Coinbase Advanced Trade usa el formato **CDP (Cloud Developer Platform)** con claves ECDSA:

1. Ve a [portal.cdp.coinbase.com/access/api](https://portal.cdp.coinbase.com/access/api)
2. Click en **"Create API Key"**
3. Selecciona permiso **"Trade"** (NO actives "Transfer")
4. Coinbase te da un **JSON con dos campos**:
   - `name`: un UUID como `xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx`
   - `privateKey`: una clave EC en formato PEM multi-linea
5. En el dashboard, ve a **Config > Conexion a Coinbase**
6. Pega el UUID en "API Key" y la clave PEM completa (con `-----BEGIN-----` / `-----END-----`) en "API Secret"
7. Click en **Validar** -> si es valido, aparece tu balance
8. Click en **Guardar** -> se encripta y guarda, el bot cambia a modo LIVE

Las keys se almacenan encriptadas con **Fernet** en SQLite. La clave de encriptacion se auto-genera en `data/secret.key` (o se puede fijar via `ENCRYPTION_KEY`).

---

## Estrategias disponibles

### 1. Grid Trading

Crea una malla de niveles de precio entre `lower_price` y `upper_price`. Compra cuando el precio cruza un nivel hacia abajo, vende cuando lo cruza hacia arriba. Cada nivel se resetea cuando el precio se aleja, permitiendo re-trigger.

**Parametros:**
| Campo | Tipo | Ejemplo | Descripcion |
|---|---|---|---|
| `symbol` | string | `BTC/USD` | Par a tradear |
| `lower_price` | float | `60000` | Limite inferior del grid |
| `upper_price` | float | `70000` | Limite superior del grid |
| `num_grids` | int | `10` | Numero de divisiones |
| `amount_per_grid` | float | `0.001` | Cantidad base por ejecucion |

**Intervalo de tick**: 30 segundos (configurable en `settings.grid_tick_seconds`).

**Cuando usar**: mercados laterales o con rangos predecibles. **No usar** si el precio esta en tendencia fuerte (puede romper el rango y quedarte comprado arriba).

### 2. DCA (Dollar Cost Averaging)

Compra `amount_usd` cada `interval_hours`, sin importar el precio. Estrategia clasica de acumulacion.

**Parametros:**
| Campo | Tipo | Ejemplo | Descripcion |
|---|---|---|---|
| `symbol` | string | `BTC/USD` | Par a tradear |
| `amount_usd` | float | `50` | USD por compra |
| `interval_hours` | int | `24` | Cada cuantas horas |

**Ventaja**: simple, bajos fees, ideal para acumular con poco capital. Reduce el riesgo de timing.

### 3. Webhook (TradingView)

Ejecuta trades al recibir alertas HTTP de TradingView (u otro sistema externo).

**Parametros:**
| Campo | Tipo | Descripcion |
|---|---|---|
| `passphrase` | string | Clave secreta para validar el webhook |
| `default_amount_usd` | float | Monto USD si la alerta no especifica |

**URL del webhook**: `http://tu-bot:8080/api/webhook/tradingview`

**Ejemplo de body que TradingView debe enviar:**
```json
{
  "action": "buy",
  "passphrase": "tu_clave_secreta",
  "symbol": "BTC/USD",
  "amount_usd": 100
}
```

**Requisito**: cuenta TradingView Pro o superior (los webhooks son feature paga).

---

## Gestion de riesgo

Pestana **Riesgo** del dashboard. Cuando esta activada, cada orden pasa por pre-checks antes de enviarse al exchange.

| Regla | Descripcion |
|---|---|
| **Limite perdida diaria** | Si el portfolio cae X$ desde el inicio del dia, bloquea nuevos trades |
| **Drawdown maximo %** | Si el portfolio cae X% del pico de los ultimos 30 dias, bloquea |
| **Max exposicion BTC %** | No compra mas BTC si supera el % del portfolio |
| **Max exposicion ETH %** | Idem para ETH |
| **Circuit breaker %** | Si el precio cae X% en 1h, pausa todo trading 1 hora |

**Kill switch**: boton rojo siempre visible en el header. Detiene TODAS las estrategias y cancela TODAS las ordenes abiertas en Coinbase. Util ante imprevistos.

---

## Dashboard

### Pestana Dashboard
- 4 KPIs: portfolio total, precio BTC, precio ETH, # estrategias activas
- **Grafica de portfolio** (line + area) con rangos 24h/7d/30d
- **Donut de asset allocation** con porcentajes
- **Grafica candlestick** BTC o ETH con tus **compras (verde)** y **ventas (rojo)** marcadas
- Panel de estrategias activas con metricas en vivo
- Lista de trades recientes

### Pestana Estrategias
- Configuracion visual de cada estrategia
- Botones Start/Stop por estrategia
- Estado en vivo (status dot animado cuando corre)

### Pestana Operaciones
- 4 KPIs: # trades, volumen total, fees pagados (con % del volumen), ratio buy/sell
- **Grafica de volumen por estrategia** (bar)
- **Grafica de actividad diaria** (trades + volumen, dual-axis)
- Filtros: periodo (24h/7d/30d/1ano), estrategia, par, lado
- **Click en fila** -> modal con detalle completo del trade
- **Boton Exportar CSV** (respeta filtros)
- Paginacion

### Pestana Riesgo
- Toggle para activar/desactivar reglas
- Formulario con todos los limites
- Boton "Kill Switch" destacado en rojo

### Pestana Config
- Seguridad: crear/cambiar/eliminar password
- Conexion a Coinbase: wizard paso a paso
- Toggle modo PAPER <-> LIVE
- Estado de notificaciones (Telegram / Email)

### Cambio de moneda
Toggle **USD / EUR** arriba a la derecha. Todos los valores, graficas y tooltips se recalculan al instante usando la tasa del BCE (actualizada cada hora).

---

## Seguridad

### Autenticacion
- Password con hash **PBKDF2-SHA256** + salt unico (200.000 iteraciones)
- Sesiones de 24h con cookie `httpOnly` + `samesite=lax`
- **5 intentos fallidos** -> bloqueo de 15 minutos
- Desactivable desde Config (requiere password actual)

### Encriptacion de keys
- API keys de Coinbase **encriptadas con Fernet (AES-128-CBC + HMAC)** antes de guardarse en SQLite
- Clave de encriptacion en `data/secret.key` (persistida en el volumen Docker) o variable de entorno

### Recomendaciones
- Activa el password si tu dashboard es accesible fuera de `localhost`
- Usa un **reverse proxy con HTTPS** (nginx/Caddy/Traefik) si lo expones a Internet
- **NUNCA** expongas directamente el puerto 8080 al internet sin TLS

---

## Notificaciones

Los eventos notificados:
- `trade_executed`: orden ejecutada exitosamente
- `strategy_started` / `strategy_stopped`
- `strategy_error`: error en un tick
- `risk_blocked`: trade bloqueado por gestion de riesgo
- `kill_switch`: activacion del kill switch

Las credenciales de Telegram y Email se configuran **desde el dashboard** (pestana Config) y se guardan **encriptadas con Fernet** en la base de datos. **No hace falta tocar `.env`** ni reiniciar el contenedor.

### Telegram (wizard en 4 pasos desde Config > Telegram)

1. **Crear bot**: abre [@BotFather](https://t.me/BotFather) en Telegram, envia `/newbot` y sigue las instrucciones. Te dara un token como `123456:ABC-DEF...`
2. **Validar token**: pega el token en el dashboard y click "Validar". El bot llama a Telegram API (`getMe`) para confirmar que es real. Si es valido, muestra `@tubot_username`.
3. **Detectar Chat ID**: envia `/start` al bot desde tu app de Telegram. Click "Detectar" - el dashboard llama `getUpdates` para encontrar automaticamente tu `chat_id`. Si hay multiples chats (tu usuario, grupos, etc.), puedes elegir cual.
4. **Probar y guardar**: "Enviar prueba" te manda un mensaje; "Guardar y activar" lo encripta y lo deja corriendo.

Una vez guardado veras la card con:
- Toggle **Activo/Inactivo** (sin eliminar la config)
- Boton **Enviar prueba** (usa las creds guardadas)
- Boton **Ver comandos** (lista completa desplegable)
- Boton **Eliminar** (wipe completo)

### Comandos del bot de Telegram

Tu bot no solo recibe notificaciones: tambien puedes **controlarlo** enviandole comandos desde Telegram. El listener usa **long polling** y solo acepta comandos del `chat_id` configurado (cualquier otro recibe "no autorizado").

**Consulta:**
| Comando | Que hace |
|---|---|
| `/start` | Bienvenida |
| `/help` | Lista de todos los comandos |
| `/status` | Resumen del portfolio (total, modo, estrategias activas) |
| `/balance` | Balances por activo |
| `/prices` | Precios actuales BTC y ETH |
| `/trades` | Ultimos 5 trades |
| `/strategies` | Estado de cada estrategia (configurada / corriendo) |
| `/mode` | Modo actual (PAPER o LIVE) |

**Control:**
| Comando | Que hace |
|---|---|
| `/start_strategy <nombre>` | Iniciar estrategia (`grid`, `dca`, `webhook`) |
| `/stop_strategy <nombre>` | Detener una estrategia |
| `/pause` | Pausar todo el trading 1 hora (circuit breaker manual) |
| `/resume` | Reanudar trading tras pausa |

**Emergencia:**
| Comando | Que hace |
|---|---|
| `/stop_all` o `/killswitch` | Kill switch: detiene todo + cancela todas las ordenes abiertas |

El listener arranca automaticamente al iniciar el bot (si Telegram esta configurado y activo) y se reinicia cada vez que cambias la config.

### Email (SMTP)

Config > Email. Rellena:
- SMTP Host (`smtp.gmail.com`)
- Puerto (`587`)
- Usuario (`tu@gmail.com`)
- Password (**App Password**, no tu password normal)
- Destinatario

Click "Probar" para verificar que llega. "Guardar y activar" lo deja corriendo. Igual que Telegram, se encripta en DB.

> **Gmail**: crea un App Password en [myaccount.google.com/apppasswords](https://myaccount.google.com/apppasswords). Requiere 2FA activado.

---

## API REST

Todas las rutas bajo `/api/`. Cuando la autenticacion esta activa, requieren cookie `session_token` (excepto `/api/health`, `/api/auth/*` y `/api/webhook/*`).

### Auth
| Metodo | Ruta | Body | Descripcion |
|---|---|---|---|
| GET | `/api/auth/status` | - | `{enabled, authenticated}` |
| POST | `/api/auth/setup` | `{password, current_password?}` | Crear/cambiar password |
| POST | `/api/auth/login` | `{password}` | Inicia sesion (cookie) |
| POST | `/api/auth/logout` | - | Cierra sesion |
| POST | `/api/auth/disable` | `{password}` | Desactiva auth |

### Dashboard
| Metodo | Ruta | Descripcion |
|---|---|---|
| GET | `/api/dashboard` | Balances, precios, KPIs, allocation, trades recientes |
| GET | `/api/dashboard/forex` | Tasa USD -> EUR actual |
| GET | `/api/dashboard/portfolio-history?hours=N` | Snapshots historicos |
| GET | `/api/dashboard/price-history?symbol=&timeframe=&limit=` | OHLCV del exchange |

### Estrategias
| Metodo | Ruta | Descripcion |
|---|---|---|
| GET | `/api/strategies` | Lista todas con estado |
| GET | `/api/strategies/{name}` | Detalle de una |
| PUT | `/api/strategies/{name}` | Actualizar params |
| POST | `/api/strategies/{name}/start` | Iniciar |
| POST | `/api/strategies/{name}/stop` | Detener |

### Trades
| Metodo | Ruta | Descripcion |
|---|---|---|
| GET | `/api/trades` | Paginado con filtros (`strategy`, `symbol`, `side`, `since_hours`) |
| GET | `/api/trades/stats?since_hours=N` | Agregados por estrategia/dia/lado |
| GET | `/api/trades/export.csv` | Descarga CSV |

### Settings
| Metodo | Ruta | Descripcion |
|---|---|---|
| GET/DELETE | `/api/settings/exchange` | Estado / eliminar keys |
| POST | `/api/settings/exchange/validate` | Probar keys (no guarda) |
| POST | `/api/settings/exchange/save` | Guarda keys y activa LIVE |
| GET/POST | `/api/settings/mode` | Toggle PAPER/LIVE |
| GET | `/api/settings/notifications` | Estado de canales |

### Notifications
| Metodo | Ruta | Descripcion |
|---|---|---|
| GET | `/api/notifications/telegram` | Estado (configured, enabled, token_hint) |
| POST | `/api/notifications/telegram/validate` | Valida token via `getMe` |
| POST | `/api/notifications/telegram/detect-chat` | Auto-detect chat_id via `getUpdates` |
| POST | `/api/notifications/telegram/test` | Prueba con creds nuevos |
| POST | `/api/notifications/telegram/test-saved` | Prueba con creds guardados |
| POST | `/api/notifications/telegram/save` | Valida + test + guarda encriptado |
| POST | `/api/notifications/telegram/toggle` | Activar/desactivar |
| DELETE | `/api/notifications/telegram` | Eliminar config |
| GET | `/api/notifications/email` | Estado SMTP |
| POST | `/api/notifications/email/test` | Prueba envio |
| POST | `/api/notifications/email/save` | Prueba + guarda encriptado |
| POST | `/api/notifications/email/toggle` | Activar/desactivar |
| DELETE | `/api/notifications/email` | Eliminar config |

### Risk
| Metodo | Ruta | Descripcion |
|---|---|---|
| GET | `/api/risk` | Config actual |
| PUT | `/api/risk` | Actualiza reglas |
| POST | `/api/risk/resume` | Reanuda tras circuit breaker |
| POST | `/api/risk/kill-switch` | Para todo + cancela ordenes |

### Webhook (publico)
| Metodo | Ruta | Descripcion |
|---|---|---|
| POST | `/api/webhook/tradingview` | Recibe alertas (protegido por passphrase) |

### Health
| GET | `/api/health` | `{status: "ok"}` |

---

## WebSocket

Endpoint: `ws://localhost:8080/ws`

El cliente no necesita enviar nada. El servidor emite:

```json
// Precios (cada 3 segundos)
{"type": "prices", "data": {"prices": {"BTC/USD": 74000, "ETH/USD": 2300}, "strategies": {...}}}

// Trade ejecutado (en el momento)
{"type": "trade", "data": {"strategy": "dca", "side": "buy", "amount": 0.001, "symbol": "BTC/USD", "price": 74000, "cost": 74, "is_paper": false}}
```

El frontend se reconecta automaticamente si se cae (cada 3s).

---

## Estructura del proyecto

```
Bot/
├── docker-compose.yml          # Orquestacion (healthcheck, volumen)
├── Dockerfile                  # Multi-stage (builder + runtime slim)
├── requirements.txt            # Dependencias Python
├── .env / .env.example         # Config
├── README.md                   # Este archivo
│
├── bot/
│   ├── main.py                 # Entry point: FastAPI + scheduler
│   ├── config.py               # Pydantic BaseSettings
│   ├── database.py             # SQLAlchemy async engine
│   ├── models.py               # 8 tablas ORM
│   ├── security.py             # Fernet encrypt/decrypt
│   ├── auth.py                 # Password hashing + sesiones
│   │
│   ├── exchange/
│   │   ├── client.py           # ccxt async wrapper (Coinbase)
│   │   ├── paper.py            # Paper trading (misma interfaz)
│   │   ├── forex.py            # USD/EUR rate (frankfurter.app)
│   │   └── schemas.py          # Pydantic: Ticker, Balance, Order
│   │
│   ├── strategies/
│   │   ├── base.py             # BaseStrategy abstracta
│   │   ├── grid.py             # Grid Trading
│   │   ├── dca.py              # Dollar Cost Averaging
│   │   └── webhook.py          # TradingView signals
│   │
│   ├── engine/
│   │   ├── scheduler.py        # APScheduler async
│   │   ├── runner.py           # Start/stop/kill_switch, recovery
│   │   ├── snapshots.py        # Snapshot de portfolio
│   │   └── risk.py             # Pre-trade checks + circuit breaker
│   │
│   ├── notifications/
│   │   ├── dispatcher.py       # Routing a canales activos
│   │   ├── email_notify.py     # aiosmtplib
│   │   └── telegram_notify.py  # Telegram Bot API
│   │
│   └── web/
│       ├── app.py              # FastAPI factory
│       ├── deps.py              # DB session
│       ├── routes/
│       │   ├── dashboard.py    # KPIs, history, prices
│       │   ├── strategies.py   # CRUD + start/stop
│       │   ├── trades.py       # List, stats, CSV export
│       │   ├── settings.py     # Exchange keys, mode, notifs
│       │   ├── risk.py         # Risk config + kill switch
│       │   ├── webhook.py      # Endpoint TradingView
│       │   ├── auth.py         # Login / logout / setup
│       │   └── websocket.py    # WS + price streamer
│       │
│       └── static/
│           ├── index.html      # SPA (Alpine.js + Chart.js)
│           ├── css/style.css   # Tema oscuro + animaciones
│           └── js/app.js       # Logica del frontend
│
└── data/                       # Volumen Docker (persistencia)
    ├── bot.db                  # SQLite
    ├── secret.key              # Clave Fernet (auto-generada)
    └── logs/bot.log
```

### Esquema de la base de datos

| Tabla | Proposito |
|---|---|
| `api_keys` | Credenciales Coinbase encriptadas |
| `strategy_configs` | Configuracion por estrategia (symbol, params JSON, is_active) |
| `trades` | Historial completo de operaciones |
| `portfolio_snapshots` | Fotos del portfolio cada 5 min (para graficas) |
| `notification_settings` | Config de canales de notificaciones |
| `grid_orders` | Estado de niveles del Grid Trading |
| `auth_config` | Password hash, intentos fallidos, bloqueo |
| `risk_config` | Reglas de gestion de riesgo |

Todos los campos con credenciales (`api_secret_enc`, `config_enc`, etc.) estan **encriptados con Fernet** antes de guardarse. El `password_hash` usa **PBKDF2-SHA256 con 200.000 iteraciones + salt**.

---

## Desarrollo local

### Sin Docker (para desarrollar)

```bash
# 1. Crea entorno virtual
python -m venv venv
source venv/bin/activate  # o venv\Scripts\activate en Windows

# 2. Instala dependencias
pip install -r requirements.txt

# 3. Arranca
python -m bot.main
```

### Comandos utiles Docker

```bash
# Logs en tiempo real
docker compose logs -f

# Reiniciar
docker compose restart

# Ver estado
docker compose ps

# Parar y eliminar (conserva el volumen)
docker compose down

# Rebuild tras cambios de codigo
docker compose up -d --build

# Entrar al contenedor
docker compose exec bot bash

# Ver la DB
docker compose exec bot python -c "from bot.database import engine; import asyncio; asyncio.run(engine.dispose())"

# Borrar TODO (incluyendo datos) - CUIDADO
docker compose down -v
```

### Logs

Los logs van a stdout del contenedor + `data/logs/bot.log`. El nivel se controla con `LOG_LEVEL` (`DEBUG`, `INFO`, `WARNING`, `ERROR`).

---

## Desplegar en un VPS (con HTTPS automatico)

Ver guia completa paso a paso en **[DEPLOYMENT.md](./DEPLOYMENT.md)**.

Resumen en 4 pasos:

```bash
# 1. En tu VPS (como root)
curl -fsSL https://raw.githubusercontent.com/TU-USUARIO/CryptoBot/main/scripts/vps-setup.sh | bash -s cryptobot

# 2. Reconecta como el usuario nuevo
ssh cryptobot@<IP-VPS>

# 3. Clona y configura
git clone https://github.com/TU-USUARIO/CryptoBot.git && cd CryptoBot
cp .env.production.example .env
nano .env  # edita DOMAIN + ENCRYPTION_KEY

# 4. Deploy
bash scripts/deploy.sh
```

Resultado: bot corriendo en `https://bot.tudominio.com` con certificado valido de Let's Encrypt.

**Sin dominio propio?** Usa `bash scripts/deploy-nodomain.sh` - te pregunta entre 4 opciones:
1. **sslip.io** (recomendado) - HTTPS valido via `<tu-ip>.sslip.io`
2. **Self-signed** - HTTPS interno (browser warning)
3. **Tailscale VPN** - acceso privado, sin exponer a Internet
4. **HTTP directo** - solo red local/testing

---

## Subir a GitHub (con maxima seguridad)

El repo esta pre-configurado para evitar que subas credenciales por accidente. Sigue estos pasos:

### 1. Verifica que no hay secretos en los archivos

Ejecuta el script de verificacion:

```bash
bash scripts/check-secrets.sh --all
```

Debe terminar con `✓ No se detectaron credenciales ni archivos sensibles`. Si encuentra algo, ARREGLALO antes de continuar.

### 2. Inicializa el repo

```bash
cd /ruta/a/CryptoBot
git init
git branch -M main
```

### 3. Instala el hook pre-commit

```bash
bash scripts/setup-git-hooks.sh
```

Esto hace que cada `git commit` ejecute `check-secrets.sh` automaticamente. Si se detecta algun secreto, el commit **se cancela**.

### 4. Primer commit

```bash
# Verifica que .env y data/ NO estan en la lista
git status

# Agrega archivos
git add .

# Verifica otra vez que no hay nada sensible
git status --cached

# Commit
git commit -m "Initial commit: CryptoBot v1.0"
```

### 5. Crea repo en GitHub y pushea

```bash
# Crea el repo via gh CLI (o hazlo manual en github.com)
gh repo create CryptoBot --private --source=. --remote=origin

# Push
git push -u origin main
```

> **Recomendacion**: hazlo **privado**. Tu estrategia de trading y patrones de uso son informacion sensible.

### 6. Verifica despues de push

Entra al repo en GitHub y confirma:
- [ ] **NO** aparece `.env`
- [ ] **NO** aparece `data/`
- [ ] **NO** aparece `secret.key`
- [ ] **NO** aparece ningun `.db`
- [ ] `README.md`, `SECURITY.md`, `LICENSE`, `CONTRIBUTING.md` estan presentes
- [ ] El codigo fuente esta completo

### Si accidentalmente subiste un secreto

**ACCION INMEDIATA:**

1. **Rota la credencial**: ve al servicio (Coinbase, Telegram, Gmail) y genera una clave nueva. La vieja **debe considerarse comprometida** aunque borres el commit.
2. **Limpia el historial de Git**:
   ```bash
   # Opcion recomendada: BFG Repo-Cleaner (rapido)
   # https://rtyley.github.io/bfg-repo-cleaner/
   bfg --delete-files secret.key
   bfg --replace-text passwords.txt  # con los strings a redactar

   # O usa git-filter-repo
   pip install git-filter-repo
   git filter-repo --path .env --invert-paths
   ```
3. **Force push**: `git push --force origin main`
4. Avisa a GitHub Support si el repo fue publico (para purgar caches).

### Archivos que SI se suben a GitHub

```
✓ bot/                  (codigo fuente)
✓ scripts/              (check-secrets, setup-hooks)
✓ docker-compose.yml
✓ Dockerfile
✓ requirements.txt
✓ .env.example          (SIN valores reales)
✓ .gitignore
✓ .dockerignore
✓ README.md
✓ SECURITY.md
✓ LICENSE
✓ CONTRIBUTING.md
```

### Archivos que NO se suben (bloqueados por .gitignore)

```
✗ .env                  (credenciales de entorno)
✗ data/                 (DB, secret.key, logs)
✗ *.db                  (bases de datos)
✗ *.key                 (claves criptograficas)
✗ *.log                 (logs pueden contener info sensible)
✗ trades_*.csv          (exports con historial personal)
✗ __pycache__/          (caches)
✗ venv/, .venv/         (entornos virtuales)
✗ .vscode/, .idea/      (configs de IDE)
✗ .claude/              (configs de asistentes AI)
```

---

## Troubleshooting

### "Invalid API key or secret" al conectar a Coinbase
Tu secret **no** es una password corta. Es una clave EC en PEM multi-linea. Mira la seccion [Conexion a Coinbase](#conexion-a-coinbase).

### No veo mi balance real
Probablemente estas en **modo PAPER**. Ve a Config y cambia a LIVE (o simplemente guarda tus API keys - activa LIVE automaticamente).

### El dashboard no refresca precios
Mira el **indicador WS** en el header (punto verde = conectado, gris = desconectado). Si esta gris, recarga la pagina. Si persiste, revisa los logs.

### "database is locked"
SQLite no permite multiples writers concurrentes. Si tienes estrategias muy agresivas ejecutando trades al mismo tiempo, considera migrar a PostgreSQL (cambia `DATABASE_URL` en `.env`).

### La grafica candlestick no carga
Verifica que el CDN de `chartjs-chart-financial` cargo bien (revisa la consola del navegador). Si estas offline, tendrias que hostear los scripts localmente.

### El bot no arranca
```bash
docker compose logs --tail 50
```
Busca el primer ERROR. Los mas comunes:
- `requirements.txt` tiene una version que no existe -> edita y rebuild
- `.env` con sintaxis invalida -> revisa comillas
- Puerto 8080 ocupado -> cambia `PORT` en `.env`

---

## Roadmap

### Implementado ✅
- 3 estrategias (Grid, DCA, Webhook)
- Dashboard completo con graficas
- Paper trading
- Multi-moneda (USD/EUR)
- Seguridad (password, encriptacion)
- Gestion de riesgo + kill switch
- WebSocket en tiempo real
- Candlestick con marcadores
- Notificaciones Email + Telegram
- Snapshots automaticos
- Export CSV

### Proximamente (ideas)
- [ ] Estrategias con indicadores: RSI, MACD, Bollinger Bands
- [ ] Trailing stop-loss y take-profit
- [ ] Rebalancing automatico
- [ ] Estrategia con LLM (Claude/GPT)
- [ ] Mas pares: SOL, LINK, MATIC, DOT, ADA
- [ ] Backtesting con datos historicos
- [ ] Sharpe ratio, Calmar ratio, win rate
- [ ] Comparacion vs HODL
- [ ] Reporte fiscal (FIFO cost basis)
- [ ] Push notifications del navegador
- [ ] Discord webhook
- [ ] Dark/Light theme
- [ ] Multi-exchange (Kraken, Binance)
- [ ] Tests unitarios
- [ ] Migracion a PostgreSQL opcional

---

## Descargo

> **Este software fue generado con asistencia de IA (vibecoded / AI-generated).**
>
> El codigo es funcional pero no ha sido auditado por profesionales de seguridad. Puede contener bugs sutiles, vulnerabilidades o patrones inseguros. **Revisa el codigo antes de usarlo con dinero real.**
>
> ---
>
> **Este software se proporciona "tal cual", sin garantias de ningun tipo.**
>
> Operar con criptomonedas conlleva riesgo de perdida total del capital.
> El autor de este bot **no es responsable** de perdidas economicas derivadas de su uso.
>
> Este proyecto es una herramienta personal, **no constituye asesoramiento financiero**.
> Pruebalo primero en **modo PAPER** durante suficiente tiempo. Empieza con **capital que puedas permitirte perder**.
>
> Los bots de trading pueden fallar por muchas razones: bugs, caidas de internet, problemas del exchange, cambios en APIs, condiciones extremas de mercado. **Configura reglas de gestion de riesgo** y usa el kill switch si algo va mal.

---

## Licencia

Proyecto personal de uso privado. Inspirado en [OctoBot](https://github.com/Drakkar-Software/OctoBot).

---

## Dudas o mejoras

El proyecto es modular y pensado para extenderse. Para agregar una estrategia nueva:

1. Crea `bot/strategies/mi_estrategia.py` heredando de `BaseStrategy`
2. Implementa `setup()`, `tick()`, `teardown()`
3. Registra la clase en `STRATEGY_CLASSES` en `bot/engine/runner.py`
4. Agrega su formulario al frontend en `index.html`

Para agregar una nueva pestana: nuevo `<div class="page">` en `index.html`, nuevo metodo en `app.js`, nueva ruta en `bot/web/routes/`.
