#!/usr/bin/env bash
# ============================================================
# Restore de backup
# Uso: bash scripts/restore.sh /ruta/a/cryptobot_backup_TIMESTAMP.tar.gz
# ============================================================
set -euo pipefail

BACKUP_FILE="${1:-}"
if [ -z "$BACKUP_FILE" ] || [ ! -f "$BACKUP_FILE" ]; then
    echo "Uso: bash scripts/restore.sh /ruta/al/backup.tar.gz"
    exit 1
fi

echo "=== CryptoBot Restore ==="
echo "Archivo: $BACKUP_FILE"
echo ""
read -p "Esto SOBREESCRIBIRA la DB actual. Continuar? (yes/no) " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    echo "Cancelado"
    exit 0
fi

TMPDIR=$(mktemp -d)
trap "rm -rf $TMPDIR" EXIT

echo "Extrayendo backup..."
tar -xzf "$BACKUP_FILE" -C "$TMPDIR"

DB_FILE=$(find "$TMPDIR" -name "bot_*.db" | head -1)
KEY_FILE=$(find "$TMPDIR" -name "secret_*.key" | head -1)

if [ -z "$DB_FILE" ]; then
    echo "ERROR: no se encontro bot_*.db en el backup"
    exit 1
fi

# Parar bot
echo "Parando bot..."
if [ -f "docker-compose.prod.yml" ]; then
    docker compose -f docker-compose.prod.yml stop bot
else
    docker compose stop bot
fi

# Restaurar
echo "Restaurando DB..."
CONTAINER=$(docker compose ps -q bot 2>/dev/null || docker compose -f docker-compose.prod.yml ps -q bot 2>/dev/null || echo "")
if [ -n "$CONTAINER" ]; then
    # Docker volume: copiamos via run temporal
    docker run --rm -v bot_bot-data:/data -v "$TMPDIR:/backup" alpine:3.19 \
        sh -c "cp /backup/$(basename $DB_FILE) /data/bot.db && \
               [ -f /backup/$(basename $KEY_FILE) ] && cp /backup/$(basename $KEY_FILE) /data/secret.key || true"
else
    # Filesystem local
    mkdir -p data
    cp "$DB_FILE" "data/bot.db"
    [ -n "$KEY_FILE" ] && cp "$KEY_FILE" "data/secret.key" || true
fi

echo "Arrancando bot..."
if [ -f "docker-compose.prod.yml" ]; then
    docker compose -f docker-compose.prod.yml start bot
else
    docker compose start bot
fi

echo ""
echo "✅ Restore completado. Verifica con:"
echo "  docker compose -f docker-compose.prod.yml logs --tail 20 bot"
