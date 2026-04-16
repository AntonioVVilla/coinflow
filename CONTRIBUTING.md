# Contribuir a CryptoBot

¡Gracias por interesarte en contribuir! Este documento explica como ayudar.

## Antes de empezar

1. Lee [SECURITY.md](./SECURITY.md) - nunca subas credenciales reales
2. Lee [README.md](./README.md) - entiende la arquitectura del proyecto
3. Asegurate de tener Docker y Python 3.12 instalados

## Como proponer un cambio

### Bugs

1. Busca en los issues si ya esta reportado
2. Si no, abre un issue con:
   - Que pasaba vs que esperabas
   - Pasos para reproducir
   - Version del bot (commit hash o tag)
   - Logs relevantes (sin credenciales)

### Features

1. Abre un issue con la propuesta **antes** de empezar a codear
2. Discute el enfoque con los mantenedores
3. Una vez acordado, envia un PR

## Desarrollo local

```bash
# Fork el repo y clona tu fork
git clone https://github.com/TU-USUARIO/CryptoBot.git
cd CryptoBot

# Crea rama feature
git checkout -b feature/mi-feature

# Arranca en desarrollo
cp .env.example .env
docker compose up -d --build

# O sin Docker
python -m venv venv
source venv/bin/activate  # o venv\Scripts\activate en Windows
pip install -r requirements.txt
python -m bot.main
```

## Guias de estilo

### Python
- Usa `type hints` en funciones publicas
- Nombres `snake_case` para funciones/variables, `PascalCase` para clases
- Max linea 100 caracteres
- Imports ordenados: stdlib, terceros, propios
- Usa `async` para todo lo que toque red o DB

### JavaScript
- Indentacion 4 espacios
- Prefiere `const` sobre `let`
- Funciones arrow para callbacks cortos
- Sin dependencias npm (mantener el stack sin build step)

### Commits
Usa mensajes claros en imperativo. Ejemplos:

```
feat: agregar estrategia MACD
fix: corregir calculo de drawdown
docs: actualizar README con seccion de riesgo
refactor: extraer risk check a modulo separado
test: agregar tests para grid strategy
```

Prefijos:
- `feat:` nueva funcionalidad
- `fix:` correccion de bug
- `docs:` documentacion
- `refactor:` refactor sin cambio funcional
- `test:` tests
- `chore:` tareas mantenimiento (deps, ci, etc.)

## Pre-commit checklist

Antes de hacer push:

```bash
# 1. Verifica que no hay secretos
bash scripts/check-secrets.sh

# 2. Revisa que el bot arranca sin errores
docker compose up -d --build
docker compose logs --tail 30

# 3. Prueba tu cambio manualmente en el dashboard
# Abre http://localhost:8080
```

## Agregar una estrategia nueva

1. Crea `bot/strategies/mi_estrategia.py` heredando de `BaseStrategy`:
   ```python
   from bot.strategies.base import BaseStrategy
   from bot.exchange.schemas import Ticker, OrderRequest

   class MiEstrategia(BaseStrategy):
       name = "mi_estrategia"

       async def setup(self, params: dict) -> None: ...
       async def tick(self, ticker: Ticker) -> list[OrderRequest]: ...
       async def teardown(self) -> None: ...
       def get_status(self) -> dict: ...
   ```

2. Registrala en `bot/engine/runner.py`:
   ```python
   STRATEGY_CLASSES = {
       ...
       "mi_estrategia": MiEstrategia,
   }
   ```

3. Agrega el formulario UI en `bot/web/static/index.html` en la seccion Strategies.

4. Documentala en el README.

## Agregar un canal de notificaciones

1. Crea `bot/notifications/mi_canal.py` con una funcion `send_mi_canal(message: str)`.
2. Registra en `bot/notifications/dispatcher.py` la condicion para activarlo.
3. Agrega endpoints CRUD en `bot/web/routes/notifications.py`.
4. Agrega wizard UI en Settings.

## Preguntas

Si algo no esta claro, abre un issue con la etiqueta `question`.

Gracias por contribuir ♥
