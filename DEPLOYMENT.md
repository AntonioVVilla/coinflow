# Deploy en VPS

Guia completa para desplegar CryptoBot en un VPS con **HTTPS automatico** (Let's Encrypt via Caddy).

## Requisitos previos

| Recurso | Minimo | Recomendado |
|---|---|---|
| VPS | 1 vCPU, 1 GB RAM, 10 GB disco | 2 vCPU, 2 GB RAM, 20 GB SSD |
| Sistema | Ubuntu 22.04+ / Debian 12+ | Ubuntu 24.04 LTS |
| Coste | ~€4/mes (Hetzner CX11) | ~€5-10/mes |
| Dominio | Opcional | Recomendado (HTTPS automatico) |

**Proveedores probados**: Hetzner, Contabo, Digital Ocean, Vultr, OVH, Scaleway.

---

## 🔧 Deploy SIN dominio propio

Si no quieres (o no puedes) registrar un dominio, tienes **4 opciones**. Todas funcionan con un solo comando:

```bash
bash scripts/deploy-nodomain.sh
```

Te pregunta cual usar. Comparativa:

| Opcion | HTTPS | Publico? | Mejor para | Warning browser? |
|---|---|---|---|---|
| **1. sslip.io** ⭐ | ✅ Valido (Let's Encrypt) | Si | Uso general | No |
| **2. Self-signed** | ✅ Cert propio | Si | Testing rapido | Si |
| **3. Tailscale VPN** | Opcional | No (VPN) | Maxima seguridad | No (VPN) |
| **4. HTTP directo** | ❌ | Si | Solo LAN/testing | - |

### Opcion 1: sslip.io (RECOMENDADA)

**Que es**: servicio DNS publico gratis que convierte cualquier IP en un dominio. Tu IP `203.0.113.42` se convierte en `203.0.113.42.sslip.io`. Let's Encrypt emite cert valido para ese subdominio.

**Ventajas**:
- HTTPS real (padlock verde en browser)
- Gratis, sin registro
- Cambias a dominio propio mas tarde con 1 linea
- Compatible con PWA (la app instalable necesita HTTPS)

**Desventajas**:
- URL fea (`203.0.113.42.sslip.io`)
- Si cambias de IP cambia el dominio
- sslip.io es terceros (aunque solo hace DNS, no ve trafico)

**Setup**:
```bash
bash scripts/deploy-nodomain.sh
# Elige opcion 1
```

Listo. URL: `https://<tu-ip>.sslip.io`

### Opcion 2: Self-signed HTTPS

**Que es**: Caddy genera su propio certificado. Encriptacion real pero el browser no confia en la CA interna.

**Ventajas**:
- HTTPS (trafico encriptado)
- No necesitas internet al emitir (offline)
- No depende de terceros

**Desventajas**:
- Browser warning ("conexion no privada") - hay que hacer click en Avanzado > Continuar
- No funciona bien con PWA / service worker

**Setup**:
```bash
bash scripts/deploy-nodomain.sh
# Elige opcion 2
```

Accede a `https://<tu-ip>` y acepta el warning.

**Pro tip**: para evitar warning cada vez, importa la CA de Caddy en tu navegador:
```bash
# Descargar la CA del contenedor Caddy
docker exec -it bot-caddy-1 cat /data/caddy/pki/authorities/local/root.crt > caddy-root.crt
# Importala en Chrome/Firefox como "Autoridad de confianza"
```

### Opcion 3: Tailscale VPN (MAS SEGURO)

**Que es**: una VPN mesh gratuita (hasta 100 devices). Tu VPS y tus dispositivos (laptop, movil) se unen a una red privada. El bot **no se expone a Internet**.

**Ventajas**:
- No hay puertos abiertos al publico (maximo seguridad)
- Acceso desde cualquier lugar via la VPN
- Gratis (plan free)
- HTTPS opcional con `tailscale serve`

**Desventajas**:
- Necesitas instalar Tailscale en cada dispositivo que accede
- Dependes del servicio Tailscale (aunque es open source)

**Setup**:
```bash
# 1. Crea cuenta gratis en https://tailscale.com (GitHub/Google login)
# 2. En el VPS:
bash scripts/deploy-nodomain.sh
# Elige opcion 3
# Autoriza el VPS en https://login.tailscale.com/admin/machines
# 3. Instala Tailscale en tu movil/laptop y login con la misma cuenta
```

Acceso desde tus dispositivos: `http://<tailscale-ip>:8080` o `http://<hostname>:8080`.

### Opcion 4: HTTP directo

**Que es**: bot escuchando en puerto 8080 sin HTTPS.

**Ventajas**:
- Setup mas simple de todos
- Menos dependencias

**Desventajas**:
- ❌ Sin encriptacion - passwords y API keys viajan en claro
- ❌ No PWA (necesita HTTPS)
- ❌ Browsers marcan como "no seguro"

**Usar SOLO en**:
- Red local (tu casa, oficina)
- Detras de VPN
- Testing local

```bash
bash scripts/deploy-nodomain.sh
# Elige opcion 4
```

### Migrar a dominio propio mas tarde

Cuando compres un dominio:

```bash
# 1. Configura DNS A record: bot.tudominio.com -> <ip-vps>
# 2. Edita .env
nano .env  # cambia DOMAIN a bot.tudominio.com
# 3. Reinicia
docker compose -f docker-compose.prod.yml up -d --force-recreate
```

Caddy se encarga del cert nuevo automaticamente.

---

## 🚀 Deploy CON dominio (4 pasos, ~10 minutos)

### Paso 1: Preparar VPS + dominio

1. **Contrata un VPS** en el proveedor de tu eleccion
2. **Compra un dominio** (~€5-10/año en Namecheap, Cloudflare, Google Domains)
3. **Crea un registro DNS A** apuntando al IP del VPS:
   ```
   Tipo: A
   Nombre: bot (o el subdominio que quieras)
   Valor: <IP-de-tu-VPS>
   TTL: 300
   ```
4. Espera 1-5 min a que propague: `dig bot.midominio.com` debe mostrar la IP correcta

### Paso 2: Setup inicial del VPS

Conectate como **root** por SSH y ejecuta el setup automatico:

```bash
ssh root@<IP-VPS>

# Descarga y ejecuta (reemplaza TU-USUARIO por tu usuario de GitHub)
curl -fsSL https://raw.githubusercontent.com/TU-USUARIO/CryptoBot/main/scripts/vps-setup.sh -o vps-setup.sh
bash vps-setup.sh cryptobot
```

Esto instala **en una sola corrida**:
- Docker + Docker Compose
- UFW firewall (solo 22, 80, 443 abiertos)
- fail2ban (bloquea ataques SSH)
- Usuario `cryptobot` no-root con acceso Docker
- Hardening SSH (solo key-based auth)

### Paso 3: Clonar y configurar

```bash
# Reconecta como el usuario nuevo
ssh cryptobot@<IP-VPS>

# Clona tu fork del repo
git clone https://github.com/TU-USUARIO/CryptoBot.git
cd CryptoBot

# Copia el template de produccion
cp .env.production.example .env

# Genera una ENCRYPTION_KEY nueva (GUARDA ESTE VALOR EN LUGAR SEGURO)
docker run --rm python:3.12-slim python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Edita .env:
#   - DOMAIN=bot.midominio.com
#   - ENCRYPTION_KEY=<el valor generado arriba>
nano .env
```

### Paso 4: Deploy

```bash
bash scripts/deploy.sh
```

El script:
- Valida tu `.env`
- Construye la imagen Docker
- Arranca `bot` + `caddy`
- Caddy solicita certificado SSL a Let's Encrypt (tarda ~30-60s la 1ra vez)
- Espera healthcheck OK

Al terminar veras:
```
✅ Deploy completado
Acceso: https://bot.midominio.com
```

Abre en tu navegador -> **HTTPS valido + dashboard listo**.

---

## 🔒 Primera configuracion (obligatoria)

Una vez accedes al dashboard:

### 1. Crea password de dashboard

Al entrar por primera vez, **te obligara a crear un password**. Esto protege el acceso — sin el, cualquiera con tu URL podria usar tu bot.

Usa un password **unico y fuerte** (mín 12 caracteres).

### 2. Conecta Coinbase

Config > Conexion a Coinbase > Wizard paso a paso.

⚠ Usa **solo el permiso "Trade"** en tu API key de Coinbase. NO marques "Transfer".

### 3. Configura notificaciones (Telegram recomendado)

Config > Telegram > Wizard. Asi recibiras alertas en tiempo real desde cualquier sitio.

### 4. Activa Risk Management

Pestaña **Riesgo**:
- Activar reglas
- Limite perdida diaria: tu tolerancia ($5, $10...)
- Max exposicion BTC/ETH: ej 60% cada uno
- Circuit breaker: 5% (pausa si el mercado cae fuerte)

### 5. Prueba con PAPER mode primero

Config > Modo de Trading > asegurate que esta **PAPER** las primeras 24-48h para validar tu estrategia sin riesgo.

---

## 💾 Backups

### Automatico diario (recomendado)

Activa el backup container que viene con la prod compose:

```bash
docker compose -f docker-compose.prod.yml --profile backup up -d
```

Hace backup diario a `./backups/` dentro del VPS y conserva 30 dias. **Pero esto no te protege si el VPS muere.**

### Backup off-VPS (imprescindible)

Agrega a tu crontab un rsync/scp a otro servidor:

```bash
# En tu ordenador local o otro VPS
0 4 * * * rsync -az cryptobot@<IP-VPS>:/home/cryptobot/CryptoBot/backups/ ~/backups/cryptobot/
```

O una vez a la semana:

```bash
# Manual desde local
scp cryptobot@<IP-VPS>:/home/cryptobot/CryptoBot/backups/*.tar.gz ~/Downloads/
```

### Backup manual

```bash
# En el VPS
bash scripts/backup.sh
# Genera: backups/cryptobot_backup_YYYYMMDD_HHMMSS.tar.gz
```

### Restore

```bash
# Desde backup
bash scripts/restore.sh backups/cryptobot_backup_20260416_120000.tar.gz
```

---

## 🔄 Updates

Actualizar el bot cuando saques una version nueva:

```bash
ssh cryptobot@<IP-VPS>
cd CryptoBot
git pull
bash scripts/deploy.sh
```

El script hace build + restart con downtime de ~5-10 segundos.

---

## 📊 Monitoreo

### Ver logs en tiempo real

```bash
# Todos los servicios
docker compose -f docker-compose.prod.yml logs -f

# Solo el bot
docker compose -f docker-compose.prod.yml logs -f bot

# Solo caddy
docker compose -f docker-compose.prod.yml logs -f caddy
```

### Estado de servicios

```bash
docker compose -f docker-compose.prod.yml ps
```

### Metricas de recursos

```bash
docker stats
```

### Caddy access logs

```bash
docker exec -it cryptobot-caddy-1 cat /data/access.log | tail -50
```

---

## 🐛 Troubleshooting

### "Unable to verify" / HTTPS no funciona tras deploy

**Causa**: Let's Encrypt no puede validar el dominio.

**Checklist**:
```bash
# 1. El DNS apunta a tu VPS?
dig bot.midominio.com
# Debe mostrar la IP de tu VPS

# 2. Puerto 80 accesible?
curl -I http://bot.midominio.com
# Debe redirigir a HTTPS

# 3. Logs de Caddy
docker compose -f docker-compose.prod.yml logs caddy | grep -i error
```

**Soluciones comunes**:
- DNS no propago aun -> espera 5-10 min
- UFW bloqueando puerto 80 -> `sudo ufw allow 80/tcp`
- Otro servicio en puerto 80 -> `sudo lsof -i :80` y parar

### El bot no arranca

```bash
docker compose -f docker-compose.prod.yml logs bot
```

Errores comunes:
- `No such file: .env` -> ejecuta deploy.sh
- `ENCRYPTION_KEY` malformada -> regenera
- `database is locked` -> `docker compose -f docker-compose.prod.yml restart bot`

### No puedo acceder tras reiniciar el VPS

Los contenedores tienen `restart: unless-stopped`, asi que deberian arrancar solos. Si no:

```bash
cd /home/cryptobot/CryptoBot
docker compose -f docker-compose.prod.yml up -d
```

### Quiero cambiar el dominio

```bash
# Edita .env con el nuevo DOMAIN
nano .env

# Reinicia solo caddy
docker compose -f docker-compose.prod.yml up -d --force-recreate caddy
```

### Quiero rollback a version anterior

```bash
# Ver commits recientes
git log --oneline -20

# Rollback a un commit especifico
git checkout <commit-hash>
bash scripts/deploy.sh

# Para volver a la ultima version:
git checkout main
bash scripts/deploy.sh
```

---

## 🔐 Seguridad en produccion - checklist

- [ ] Password del dashboard activo y fuerte
- [ ] API key de Coinbase con permiso solo "Trade"
- [ ] `.env` con permisos 600: `chmod 600 .env`
- [ ] Firewall UFW activo y limitado a 22/80/443
- [ ] fail2ban corriendo
- [ ] SSH solo con key (sin password auth)
- [ ] `secret.key` respaldado **fuera** del VPS
- [ ] Backups automaticos + off-site
- [ ] Notificaciones configuradas (Telegram/Email)
- [ ] Risk management activo con limites realistas
- [ ] Testeado en modo PAPER antes de ir LIVE

---

## 💰 Estimacion de costes mensual

| Item | Coste |
|---|---|
| VPS (Hetzner CX11) | €4 |
| Dominio (Namecheap .com) | €1 (~€10/año) |
| Backup remoto | €0 (Hetzner Storage Box €3.9/mes opcional) |
| Certificado SSL | Gratis (Let's Encrypt) |
| **Total** | **~€5/mes** |

---

## 🆘 Ayuda

Si algo no funciona tras seguir esta guia:

1. Revisa logs: `docker compose -f docker-compose.prod.yml logs --tail 100`
2. Verifica DNS: `dig tudominio.com`
3. Verifica firewall: `sudo ufw status`
4. Reinicia: `docker compose -f docker-compose.prod.yml restart`

Como ultimo recurso, full restart:

```bash
docker compose -f docker-compose.prod.yml down
docker compose -f docker-compose.prod.yml up -d --build
```
