#!/usr/bin/env bash
# ============================================================
# Deploy script - ejecutar en el VPS
# ============================================================
#
# Uso:
#   cd /ruta/a/CryptoBot
#   bash scripts/deploy.sh
# ============================================================
set -euo pipefail

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}=== CryptoBot Deploy ===${NC}"

# 1. Check Docker
if ! command -v docker >/dev/null 2>&1; then
    echo -e "${RED}ERROR: Docker no esta instalado. Ejecuta primero scripts/vps-setup.sh${NC}"
    exit 1
fi

# 2. Check .env
if [ ! -f ".env" ]; then
    echo -e "${YELLOW}.env no existe. Creando desde .env.production.example...${NC}"
    cp .env.production.example .env
    echo -e "${RED}⚠ IMPORTANTE: edita .env con tu DOMAIN y ENCRYPTION_KEY antes de continuar.${NC}"
    echo "Genera la ENCRYPTION_KEY con:"
    echo "  docker run --rm python:3.12-slim python -c \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
    exit 1
fi

# 3. Validate required env vars
source .env
if [ -z "${DOMAIN:-}" ] || [ "$DOMAIN" = "bot.midominio.com" ]; then
    echo -e "${RED}ERROR: edita DOMAIN en .env${NC}"
    exit 1
fi
if [ -z "${ENCRYPTION_KEY:-}" ]; then
    echo -e "${YELLOW}⚠ ENCRYPTION_KEY vacia - se auto-generara en data/secret.key. HAZ BACKUP de ese archivo.${NC}"
fi

# 4. Run secret check if tracked files exist
if [ -d .git ]; then
    echo "Verificando que no hay secretos en el repo..."
    bash scripts/check-secrets.sh --all || echo -e "${YELLOW}⚠ Revisa warnings arriba${NC}"
fi

# 5. Pull latest code (if git repo)
if [ -d .git ]; then
    echo "Pulling ultima version..."
    git pull --ff-only || echo -e "${YELLOW}No se pudo pull (puede ser OK si estas en rama no-rastreada)${NC}"
fi

# 6. Build y arrancar
echo -e "${GREEN}Building imagen Docker...${NC}"
docker compose -f docker-compose.prod.yml build

echo -e "${GREEN}Arrancando servicios (bot + caddy)...${NC}"
docker compose -f docker-compose.prod.yml up -d

# 7. Esperar healthcheck
echo "Esperando a que el bot este sano..."
for i in {1..30}; do
    if docker compose -f docker-compose.prod.yml ps bot | grep -q "healthy"; then
        echo -e "${GREEN}✓ Bot healthy${NC}"
        break
    fi
    sleep 2
done

# 8. Mostrar logs finales
echo ""
echo -e "${GREEN}=== Ultimas lineas de log ===${NC}"
docker compose -f docker-compose.prod.yml logs --tail 15 bot

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  ✅ Deploy completado${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo "Acceso:"
echo -e "  ${GREEN}https://${DOMAIN}${NC}  (Caddy tramita Let's Encrypt automaticamente, puede tardar 30-60s la primera vez)"
echo ""
echo "Comandos utiles:"
echo "  Ver logs:       docker compose -f docker-compose.prod.yml logs -f"
echo "  Reiniciar:      docker compose -f docker-compose.prod.yml restart"
echo "  Parar:          docker compose -f docker-compose.prod.yml down"
echo "  Update:         git pull && bash scripts/deploy.sh"
echo "  Backup manual:  bash scripts/backup.sh"
echo ""
