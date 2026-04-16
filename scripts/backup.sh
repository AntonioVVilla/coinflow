#!/usr/bin/env bash
# ============================================================
# Backup manual de DB + secret.key
# Uso: bash scripts/backup.sh [destino]
# ============================================================
set -euo pipefail

DEST="${1:-./backups}"
mkdir -p "$DEST"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
DB_BACKUP="$DEST/bot_${TIMESTAMP}.db"
KEY_BACKUP="$DEST/secret_${TIMESTAMP}.key"
TARBALL="$DEST/cryptobot_backup_${TIMESTAMP}.tar.gz"

echo "=== CryptoBot Backup ==="

# Find the volume mount (Docker or local)
if docker compose ps bot >/dev/null 2>&1; then
    echo "Detectado Docker compose. Haciendo backup desde el contenedor..."
    CONTAINER=$(docker compose ps -q bot 2>/dev/null || docker compose -f docker-compose.prod.yml ps -q bot 2>/dev/null || echo "")
    if [ -z "$CONTAINER" ]; then
        echo "ERROR: contenedor bot no esta corriendo"
        exit 1
    fi

    # SQLite backup en caliente (no corrupt)
    docker exec "$CONTAINER" sqlite3 /app/data/bot.db ".backup /tmp/bot_backup.db" 2>/dev/null || \
        docker exec "$CONTAINER" cp /app/data/bot.db /tmp/bot_backup.db
    docker cp "$CONTAINER:/tmp/bot_backup.db" "$DB_BACKUP"
    docker exec "$CONTAINER" rm /tmp/bot_backup.db

    # Copy secret.key
    docker cp "$CONTAINER:/app/data/secret.key" "$KEY_BACKUP" 2>/dev/null || \
        echo "⚠ No hay secret.key (usando ENCRYPTION_KEY env var?)"
else
    echo "Backup desde filesystem local..."
    if [ -f "data/bot.db" ]; then
        cp "data/bot.db" "$DB_BACKUP"
    fi
    if [ -f "data/secret.key" ]; then
        cp "data/secret.key" "$KEY_BACKUP"
    fi
fi

# Crear tarball
tar -czf "$TARBALL" -C "$DEST" "$(basename "$DB_BACKUP")" "$(basename "$KEY_BACKUP")" 2>/dev/null || true

# Limpiar archivos intermedios si el tar se creo ok
if [ -f "$TARBALL" ]; then
    rm -f "$DB_BACKUP" "$KEY_BACKUP"
fi

SIZE=$(du -h "$TARBALL" | cut -f1)
echo ""
echo "✅ Backup creado: $TARBALL ($SIZE)"
echo ""
echo "RECOMENDACION: copia este archivo a un lugar seguro FUERA del VPS:"
echo "  scp ${TARBALL} usuario@otra-maquina:/backups/"
echo ""
