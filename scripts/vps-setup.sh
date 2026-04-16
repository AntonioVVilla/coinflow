#!/usr/bin/env bash
# ============================================================
# VPS Setup Script
# Ejecutar UNA SOLA VEZ como root en un VPS fresco (Ubuntu/Debian)
#
# Instala:
#   - Docker + Docker Compose
#   - UFW firewall (22, 80, 443)
#   - fail2ban (proteccion SSH)
#   - Creacion de usuario no-root
#   - Hardening SSH basico
#
# Usage:
#   curl -fsSL https://raw.githubusercontent.com/USER/CryptoBot/main/scripts/vps-setup.sh -o vps-setup.sh
#   sudo bash vps-setup.sh <username>
# ============================================================

set -euo pipefail

USER_NAME="${1:-cryptobot}"

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: ejecuta como root o con sudo"
    exit 1
fi

echo "=== Actualizando sistema ==="
apt-get update -qq
apt-get upgrade -yq

echo "=== Instalando dependencias basicas ==="
apt-get install -yq ca-certificates curl gnupg lsb-release ufw fail2ban git

echo "=== Instalando Docker ==="
if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" \
        | tee /etc/apt/sources.list.d/docker.list > /dev/null
    apt-get update -qq
    apt-get install -yq docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable --now docker
    echo "✓ Docker instalado: $(docker --version)"
else
    echo "✓ Docker ya instalado"
fi

echo "=== Creando usuario '$USER_NAME' ==="
if ! id "$USER_NAME" >/dev/null 2>&1; then
    adduser --disabled-password --gecos "" "$USER_NAME"
    usermod -aG docker "$USER_NAME"
    # Copy SSH keys from root if any
    if [ -d /root/.ssh ]; then
        mkdir -p "/home/$USER_NAME/.ssh"
        cp /root/.ssh/authorized_keys "/home/$USER_NAME/.ssh/" 2>/dev/null || true
        chown -R "$USER_NAME:$USER_NAME" "/home/$USER_NAME/.ssh"
        chmod 700 "/home/$USER_NAME/.ssh"
        chmod 600 "/home/$USER_NAME/.ssh/authorized_keys" 2>/dev/null || true
    fi
    echo "✓ Usuario '$USER_NAME' creado y agregado al grupo docker"
else
    echo "✓ Usuario '$USER_NAME' ya existe"
    usermod -aG docker "$USER_NAME" || true
fi

echo "=== Configurando UFW firewall ==="
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp comment "SSH"
ufw allow 80/tcp comment "HTTP"
ufw allow 443/tcp comment "HTTPS"
ufw allow 443/udp comment "HTTPS (QUIC/HTTP3)"
ufw --force enable
echo "✓ UFW activo:"
ufw status numbered

echo "=== Configurando fail2ban para SSH ==="
systemctl enable --now fail2ban
echo "✓ fail2ban activo"

echo "=== Hardening SSH ==="
SSH_CONFIG=/etc/ssh/sshd_config
if grep -q "^PermitRootLogin yes" "$SSH_CONFIG" 2>/dev/null; then
    sed -i 's/^PermitRootLogin yes/PermitRootLogin prohibit-password/' "$SSH_CONFIG"
fi
if ! grep -q "^PasswordAuthentication no" "$SSH_CONFIG" 2>/dev/null; then
    echo "" >> "$SSH_CONFIG"
    echo "# Hardened by CryptoBot setup" >> "$SSH_CONFIG"
    echo "PasswordAuthentication no" >> "$SSH_CONFIG"
fi
systemctl restart ssh
echo "✓ SSH: login solo con key, root con key-only"

echo ""
echo "============================================================"
echo "  ✅ VPS setup completo"
echo "============================================================"
echo ""
echo "Siguiente pasos:"
echo "  1. Conecta como el usuario nuevo:"
echo "     ssh $USER_NAME@<ip-vps>"
echo ""
echo "  2. Clona el repo:"
echo "     git clone https://github.com/TU-USUARIO/CryptoBot.git"
echo "     cd CryptoBot"
echo ""
echo "  3. Apunta tu dominio al VPS (DNS A record)"
echo ""
echo "  4. Deploy:"
echo "     bash scripts/deploy.sh"
echo ""
