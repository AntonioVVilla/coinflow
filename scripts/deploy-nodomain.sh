#!/usr/bin/env bash
# ============================================================
# Deploy sin dominio: te pregunta cual de las 4 opciones usar
# ============================================================
set -euo pipefail

GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m'

echo -e "${GREEN}=== CryptoBot Deploy sin dominio ===${NC}"
echo ""
echo "Elige el modo de despliegue:"
echo ""
echo -e "  ${BLUE}1)${NC} sslip.io        ${YELLOW}[RECOMENDADO]${NC} - HTTPS valido automatico (usa IP.sslip.io)"
echo -e "  ${BLUE}2)${NC} Self-signed     - HTTPS con cert interno (browser warning pero encriptado)"
echo -e "  ${BLUE}3)${NC} Tailscale VPN   - Acceso privado solo para tus dispositivos"
echo -e "  ${BLUE}4)${NC} HTTP (LAN)      - Solo red local, sin encriptacion"
echo ""
read -p "Opcion (1-4): " MODE

# Detect public IP
PUBLIC_IP=$(curl -fsSL -4 ifconfig.me 2>/dev/null || curl -fsSL -4 icanhazip.com 2>/dev/null || echo "")
if [ -z "$PUBLIC_IP" ]; then
    echo -e "${RED}No se pudo detectar IP publica${NC}"
    read -p "Ingresa IP manualmente: " PUBLIC_IP
fi
echo ""
echo -e "IP detectada: ${GREEN}$PUBLIC_IP${NC}"
echo ""

# Ensure .env exists
if [ ! -f ".env" ]; then
    cp .env.production.example .env
fi

case "$MODE" in
    1)
        echo -e "${GREEN}Modo: sslip.io${NC}"
        SSLIP_DOMAIN="${PUBLIC_IP}.sslip.io"
        echo "Tu URL sera: ${GREEN}https://$SSLIP_DOMAIN${NC}"
        echo ""

        # Update .env DOMAIN
        if grep -q "^DOMAIN=" .env; then
            sed -i.bak "s|^DOMAIN=.*|DOMAIN=$SSLIP_DOMAIN|" .env
        else
            echo "DOMAIN=$SSLIP_DOMAIN" >> .env
        fi

        # Ensure ENCRYPTION_KEY is set
        if ! grep -q "^ENCRYPTION_KEY=.\+" .env; then
            NEW_KEY=$(docker run --rm python:3.12-slim python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
            if grep -q "^ENCRYPTION_KEY=" .env; then
                sed -i.bak "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$NEW_KEY|" .env
            else
                echo "ENCRYPTION_KEY=$NEW_KEY" >> .env
            fi
            echo -e "${YELLOW}⚠ ENCRYPTION_KEY generada. HAZ BACKUP del archivo .env${NC}"
        fi

        docker compose -f docker-compose.prod.yml up -d --build
        echo ""
        echo -e "${GREEN}✅ Deploy completado${NC}"
        echo -e "Acceso: ${GREEN}https://$SSLIP_DOMAIN${NC}"
        echo "(el cert puede tardar 30-60s la primera vez)"
        ;;

    2)
        echo -e "${GREEN}Modo: Self-signed HTTPS${NC}"
        echo ""

        # Use Caddyfile.selfsigned
        cp docker-compose.prod.yml docker-compose.selfsigned.yml

        # Replace Caddyfile mount to use selfsigned version
        sed -i.bak 's|./Caddyfile:|./Caddyfile.selfsigned:|' docker-compose.selfsigned.yml

        # Set a dummy DOMAIN in env (not used)
        if ! grep -q "^DOMAIN=" .env; then
            echo "DOMAIN=bot.local" >> .env
        fi

        # Ensure ENCRYPTION_KEY
        if ! grep -q "^ENCRYPTION_KEY=.\+" .env; then
            NEW_KEY=$(docker run --rm python:3.12-slim python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
            if grep -q "^ENCRYPTION_KEY=" .env; then
                sed -i.bak "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$NEW_KEY|" .env
            else
                echo "ENCRYPTION_KEY=$NEW_KEY" >> .env
            fi
        fi

        docker compose -f docker-compose.selfsigned.yml up -d --build
        echo ""
        echo -e "${GREEN}✅ Deploy completado${NC}"
        echo -e "Acceso: ${GREEN}https://$PUBLIC_IP${NC}"
        echo -e "${YELLOW}El navegador mostrara warning - click en 'Avanzado' > 'Continuar'${NC}"
        ;;

    3)
        echo -e "${GREEN}Modo: Tailscale VPN${NC}"
        echo ""
        if ! command -v tailscale >/dev/null 2>&1; then
            echo "Tailscale no esta instalado. Instalando..."
            curl -fsSL https://tailscale.com/install.sh | sh
            sudo tailscale up
            echo ""
            echo -e "${YELLOW}Autoriza este dispositivo en: https://login.tailscale.com/admin/machines${NC}"
            read -p "Presiona Enter cuando hayas autorizado..."
        fi

        # Get Tailscale IP + hostname
        TS_IP=$(tailscale ip -4 2>/dev/null | head -1 || echo "")
        TS_HOSTNAME=$(tailscale status --json 2>/dev/null | grep -m1 '"HostName"' | cut -d'"' -f4 || echo "")

        echo "Tailscale IP: ${TS_IP}"
        echo "Tailscale hostname: ${TS_HOSTNAME}"
        echo ""

        # Deploy in LAN mode (Tailscale provides the secure network)
        docker compose -f docker-compose.lan.yml up -d --build
        echo ""
        echo -e "${GREEN}✅ Deploy completado${NC}"
        echo -e "Acceso (solo tus dispositivos Tailscale):"
        echo -e "  ${GREEN}http://$TS_IP:8080${NC}"
        if [ -n "$TS_HOSTNAME" ]; then
            echo -e "  ${GREEN}http://$TS_HOSTNAME:8080${NC}"
        fi
        echo ""
        echo "Instala Tailscale en tu movil/laptop y apareceras en la misma red."
        ;;

    4)
        echo -e "${GREEN}Modo: HTTP directo (LAN)${NC}"
        echo -e "${RED}⚠ ADVERTENCIA: sin HTTPS. Solo usar en red local confiable.${NC}"
        echo ""
        read -p "Confirmar? (yes/no) " CONFIRM
        if [ "$CONFIRM" != "yes" ]; then exit 0; fi

        # Ensure ENCRYPTION_KEY
        if ! grep -q "^ENCRYPTION_KEY=.\+" .env; then
            NEW_KEY=$(docker run --rm python:3.12-slim python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())")
            if grep -q "^ENCRYPTION_KEY=" .env; then
                sed -i.bak "s|^ENCRYPTION_KEY=.*|ENCRYPTION_KEY=$NEW_KEY|" .env
            else
                echo "ENCRYPTION_KEY=$NEW_KEY" >> .env
            fi
        fi

        docker compose -f docker-compose.lan.yml up -d --build
        echo ""
        echo -e "${GREEN}✅ Deploy completado${NC}"
        echo -e "Acceso: ${GREEN}http://$PUBLIC_IP:8080${NC}"
        echo -e "${RED}⚠ Considera agregar firewall rule que solo permita tu IP${NC}"
        ;;

    *)
        echo "Opcion invalida"
        exit 1
        ;;
esac

echo ""
echo "Comandos utiles:"
echo "  Logs:     docker compose ps"
echo "  Restart:  docker compose restart"
echo "  Parar:    docker compose down"
