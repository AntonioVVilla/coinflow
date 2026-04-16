# Seguridad

## Modelo de amenaza

CryptoBot maneja **credenciales sensibles** (API keys de Coinbase, tokens de Telegram, SMTP passwords) y **ejecuta operaciones con dinero real**. Este documento describe las medidas de seguridad implementadas y las mejores practicas al desplegar y usar el bot.

## Proteccion de credenciales

### 1. Encriptacion at rest

Todas las credenciales se encriptan con **Fernet (AES-128-CBC + HMAC-SHA256)** antes de guardarse en SQLite:

| Credencial | Donde | Como |
|---|---|---|
| API key Coinbase (UUID) | `api_keys.api_key_enc` | Fernet |
| API secret Coinbase (PEM privado EC) | `api_keys.api_secret_enc` | Fernet |
| Telegram bot token | `notification_settings.config_enc` | Fernet (JSON) |
| Telegram chat_id | `notification_settings.config_enc` | Fernet (JSON) |
| SMTP password | `notification_settings.config_enc` | Fernet (JSON) |
| Password del dashboard | `auth_config.password_hash` | PBKDF2-SHA256 (200.000 iter) + salt |

### 2. Clave de encriptacion

La clave Fernet se almacena en `data/secret.key` (auto-generada al primer arranque) o en la variable `ENCRYPTION_KEY`. Esta clave **NO** se incluye en la imagen Docker ni se sube a Git. Hacer backup por separado (fuera del repo).

Si pierdes `secret.key`: no podras descifrar las credenciales guardadas. Tendras que reconfigurar Coinbase, Telegram y Email desde el dashboard.

### 3. Transmision en red

- Las credenciales de Coinbase viajan solo entre el **navegador** y el **backend local**. Nunca se envian a terceros.
- El token de Telegram se envia a `api.telegram.org` via HTTPS (Telegram lo requiere).
- SMTP usa STARTTLS automaticamente (puerto 587).

**Recomendacion**: si accedes al dashboard desde fuera de `localhost`, usa un reverse proxy con HTTPS (nginx/Caddy/Traefik).

### 4. Nunca se devuelven al frontend

El backend **nunca** devuelve al frontend:
- API secret de Coinbase (solo su existencia)
- Token completo de Telegram (solo un hint `123456...ABCD`)
- Password SMTP (solo `has_password: true/false`)
- Password del dashboard (solo su hash, nunca el hash tampoco via API)

## Proteccion del dashboard

### Autenticacion opcional
- Password con PBKDF2-SHA256 (200.000 iteraciones) + salt unico por installation
- Sesiones de 24h con cookies `HttpOnly` + `SameSite=Lax`
- **5 intentos fallidos** -> bloqueo de 15 minutos
- Activable/desactivable desde el dashboard

### Recomendaciones
- **ACTIVA el password** si expones el bot fuera de `localhost`
- Usa un password **unico y fuerte** (no el mismo que Coinbase)
- Cambia el password si sospechas que fue comprometido (desde Config)

## Que NO se guarda en el repositorio

El `.gitignore` excluye:
- `.env` (variables de entorno)
- `data/bot.db` (base de datos con credenciales encriptadas)
- `data/secret.key` (clave de encriptacion)
- `data/logs/` (logs que pueden contener info sensible)
- `trades_*.csv` (exports de trades que pueden revelar posiciones)
- Caches de Python (`__pycache__`, `.pytest_cache`, etc.)

## Antes de subir a GitHub

Ejecuta el script `scripts/check-secrets.sh` para verificar que no hay credenciales en los archivos tracked.

```bash
bash scripts/check-secrets.sh
```

Si el script detecta algo, **arregla antes de hacer commit**.

## Despliegue en produccion

Si despliegas el bot en un servidor (VPS, home server, etc.), sigue estas buenas practicas:

### Obligatorio
1. **Nunca expongas el puerto 8080 directamente a Internet**. Usa un reverse proxy con TLS (nginx/Caddy/Traefik + Let's Encrypt).
2. **Activa el password del dashboard** (Config > Seguridad del Dashboard).
3. **Restringe el origen**: en tu firewall / proxy, solo permite tu IP o una VPN.
4. **Haz backup de `data/secret.key`** en un lugar seguro y fuera del servidor.

### Recomendado
5. Usa un usuario no-root para correr Docker.
6. Mantiene el sistema y las imagenes Docker actualizadas.
7. Monitoriza los logs para detectar accesos inusuales.
8. Configura las reglas de **gestion de riesgo** para limitar perdidas ante bugs o ataques.
9. Configura **notificaciones** (Telegram/Email) para enterarte inmediatamente de trades o errores.
10. Usa API keys de Coinbase con **solo el permiso `Trade`** (nunca `Transfer`).

### Opcional
11. Rota tu token de Coinbase periodicamente (cada 3-6 meses).
12. Monta la DB en un volumen encriptado a nivel de disco (LUKS, FileVault, BitLocker).
13. Usa un gestor de secretos externo (Vault, Doppler) en vez de `.env`.

## Reportar vulnerabilidades

Si descubres una vulnerabilidad, **no la abras como issue publico**. Contactame directamente por email (o el canal que prefieras) con los detalles. Responder e en 7 dias.

## Dependencias

Las dependencias Python se actualizan manualmente. Revisa periodicamente:

```bash
pip list --outdated
```

Y actualiza `requirements.txt` segun CVEs publicados. Las librerias criticas a monitorizar:
- `cryptography` (encriptacion)
- `aiohttp` (HTTP client)
- `fastapi` / `uvicorn` / `starlette` (web)
- `sqlalchemy` (DB)
- `ccxt` (exchange)

## Checklist pre-commit

Antes de hacer `git commit`, verifica:

- [ ] `.env` no esta en staged files (`git status`)
- [ ] `data/` no esta en staged files
- [ ] No hay tokens, passwords o claves privadas en el diff (`git diff --staged`)
- [ ] Corriste `bash scripts/check-secrets.sh` sin errores
- [ ] Si agregaste variables de entorno nuevas, las documentaste en `.env.example` (sin valores reales)
