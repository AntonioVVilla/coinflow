#!/usr/bin/env bash
# Instala el hook pre-commit que ejecuta check-secrets.sh
# Uso: bash scripts/setup-git-hooks.sh

set -eu

HOOK_DIR=".git/hooks"
HOOK_FILE="$HOOK_DIR/pre-commit"

if [ ! -d ".git" ]; then
    echo "ERROR: no es un repo git. Ejecuta 'git init' primero."
    exit 1
fi

mkdir -p "$HOOK_DIR"
cat > "$HOOK_FILE" <<'EOF'
#!/usr/bin/env bash
# Auto-generated pre-commit hook by CryptoBot
set -e
echo "==> Pre-commit: verificando secretos..."
bash scripts/check-secrets.sh
EOF

chmod +x "$HOOK_FILE"
echo "✓ Hook pre-commit instalado en $HOOK_FILE"
echo ""
echo "Cada 'git commit' ahora ejecutara scripts/check-secrets.sh automaticamente."
echo "Para saltar el check (NO recomendado): git commit --no-verify"
