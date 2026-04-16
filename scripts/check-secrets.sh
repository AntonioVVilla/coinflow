#!/usr/bin/env bash
# ============================================================
# check-secrets.sh
#
# Escanea los archivos que seran commiteados (staged) o todos
# los archivos tracked del repo buscando posibles credenciales
# filtradas.
#
# Uso:
#   bash scripts/check-secrets.sh         # escanea staged (pre-commit)
#   bash scripts/check-secrets.sh --all   # escanea todo el repo
# ============================================================

set -eu

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

MODE="staged"
if [ "${1:-}" = "--all" ]; then
    MODE="all"
fi

echo "==> Escaneando ($MODE)..."

# Get list of files to scan
if [ "$MODE" = "staged" ]; then
    FILES=$(git diff --cached --name-only --diff-filter=ACM 2>/dev/null || true)
else
    FILES=$(git ls-files 2>/dev/null || find . -type f -not -path "./.git/*" -not -path "./data/*" -not -path "./__pycache__/*")
fi

if [ -z "$FILES" ]; then
    echo "(No hay archivos para escanear)"
    exit 0
fi

FOUND=0
ISSUES=""

check() {
    local pattern="$1"
    local description="$2"
    local severity="$3"

    for f in $FILES; do
        # Skip binary files, .env.example, this script, and docs
        case "$f" in
            *.env.example|*check-secrets.sh|*SECURITY.md|*README.md|*CONTRIBUTING.md) continue ;;
        esac
        [ -f "$f" ] || continue

        # Check if file is binary
        if file "$f" 2>/dev/null | grep -q "binary"; then continue; fi

        matches=$(grep -nE "$pattern" "$f" 2>/dev/null || true)
        if [ -n "$matches" ]; then
            echo ""
            if [ "$severity" = "ERROR" ]; then
                echo -e "${RED}[ERROR]${NC} $description"
                FOUND=$((FOUND + 1))
            else
                echo -e "${YELLOW}[WARN]${NC} $description"
            fi
            echo "        Archivo: $f"
            echo "$matches" | while read -r line; do
                echo "        $line"
            done
        fi
    done
}

# Critical patterns (ERROR)
check '-----BEGIN (EC|RSA|OPENSSH|PRIVATE) (PRIVATE )?KEY-----' "Clave privada PEM detectada" "ERROR"
check 'AKIA[0-9A-Z]{16}' "AWS Access Key ID detectado" "ERROR"
check 'sk-[a-zA-Z0-9]{20,}' "OpenAI / Anthropic API key detectado" "ERROR"
check 'sk_live_[0-9a-zA-Z]{24,}' "Stripe live secret key detectado" "ERROR"
check 'ghp_[a-zA-Z0-9]{36}' "GitHub Personal Access Token detectado" "ERROR"
check 'gho_[a-zA-Z0-9]{36}' "GitHub OAuth token detectado" "ERROR"
check 'xox[baprs]-[0-9a-zA-Z]{10,}' "Slack token detectado" "ERROR"
check '[0-9]{9,10}:[a-zA-Z0-9_-]{35}' "Telegram bot token detectado" "ERROR"

# Env variable assignments with values (warn)
check '^(COINBASE_API_KEY|COINBASE_API_SECRET)\s*=\s*[^[:space:]].+' "Variable sensible con valor" "ERROR"
check '^(TELEGRAM_BOT_TOKEN)\s*=\s*[0-9]+:[a-zA-Z0-9_-]+' "Telegram token en env var con valor" "ERROR"
check '^(SMTP_PASS|SMTP_PASSWORD|PASSWORD)\s*=\s*[^[:space:]"]+.+' "Password en env var con valor" "ERROR"

# Only flag tracked/staged sensitive files (ignore untracked working tree files)
if [ -d .git ]; then
    TRACKED=$(git ls-files 2>/dev/null || true)
else
    TRACKED=""
fi

is_tracked() {
    local f="$1"
    case "$TRACKED" in
        *"$f"*) return 0 ;;
        *) return 1 ;;
    esac
}

for f in $FILES; do
    base=$(basename "$f")

    # .env files (not .env.example)
    if { [ "$base" = ".env" ] || echo "$base" | grep -qE '^\.env\..+' ; } && [ "$base" != ".env.example" ]; then
        if [ "$MODE" = "staged" ] || is_tracked "$f"; then
            echo ""
            echo -e "${RED}[ERROR]${NC} Archivo .env en commit: $f"
            echo "        NUNCA subas archivos .env con valores reales."
            FOUND=$((FOUND + 1))
        fi
    fi

    # DB / secret.key / data dir
    case "$f" in
        *.db|*.sqlite|*.sqlite3|*secret.key|./data/*|data/*)
            if [ "$MODE" = "staged" ] || is_tracked "$f"; then
                echo ""
                echo -e "${RED}[ERROR]${NC} Archivo sensible en commit: $f"
                FOUND=$((FOUND + 1))
            fi
            ;;
    esac
done

echo ""
if [ "$FOUND" -eq 0 ]; then
    echo -e "${GREEN}✓ No se detectaron credenciales ni archivos sensibles.${NC}"
    exit 0
else
    echo -e "${RED}✗ Se detectaron $FOUND problema(s). NO hagas commit hasta resolverlo.${NC}"
    echo ""
    echo "Como arreglarlo:"
    echo "  1. Retira el archivo del stage: git reset HEAD <archivo>"
    echo "  2. Agrega el archivo a .gitignore"
    echo "  3. Si ya fue commiteado: usa 'git filter-repo' o BFG Repo-Cleaner"
    echo "  4. Rota las credenciales comprometidas inmediatamente"
    exit 1
fi
