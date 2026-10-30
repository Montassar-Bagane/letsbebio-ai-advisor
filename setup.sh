#!/usr/bin/env bash
#
# One-shot setup. Creates the database user, the virtualenv and the .env file,
# then tells you what (if anything) is left to do.
#
#   bash setup.sh
#
set -uo pipefail
cd "$(dirname "$0")"

GREEN='\033[0;32m'; YELLOW='\033[0;33m'; RED='\033[0;31m'; NC='\033[0m'
ok()   { echo -e "  ${GREEN}OK${NC}   $1"; }
warn() { echo -e "  ${YELLOW}..${NC}   $1"; }
bad()  { echo -e "  ${RED}FAIL${NC} $1"; }

# The database name is whatever the dump was restored into. Rather than
# assuming, find the database that actually contains WordPress tables.
DB_NAME="${DB_NAME:-}"
DB_USER="${DB_USER:-reco_read}"
DB_PASS="${DB_PASS:-reco_local_pw}"

echo
echo "Recommendation engine — setup"
echo "============================="

# ---------------------------------------------------------------- 1. python --
echo
echo "1. Python environment"
if ! command -v python3 >/dev/null; then
  bad "python3 not found. Install it: sudo apt install python3 python3-venv"
  exit 1
fi
ok "python3 $(python3 -V 2>&1 | cut -d' ' -f2)"

if [ ! -d service/.venv ]; then
  warn "creating virtualenv..."
  python3 -m venv service/.venv 2>/dev/null || {
    bad "venv creation failed. Try: sudo apt install python3-venv"; exit 1; }
fi
ok "virtualenv ready"

warn "installing dependencies (this takes a minute)..."
service/.venv/bin/pip install --upgrade pip -q 2>/dev/null

if service/.venv/bin/pip install -r service/requirements.txt -q 2>/tmp/pip_err; then
  ok "dependencies installed"
else
  # Almost always one cause: a package with no prebuilt wheel for this Python
  # version, so pip falls back to compiling and there is no C toolchain.
  if grep -qi "failed building wheel\|Microsoft Visual\|linker .cc. not found\|error: command" /tmp/pip_err; then
    warn "no prebuilt package for Python $(python3 -V | cut -d' ' -f2); installing a build toolchain..."
    if sudo apt-get install -y -qq build-essential python3-dev >/dev/null 2>&1; then
      if service/.venv/bin/pip install -r service/requirements.txt -q 2>/tmp/pip_err; then
        ok "dependencies installed (compiled locally)"
      else
        bad "dependency install still failing:"; tail -8 /tmp/pip_err
        echo
        echo "       Python $(python3 -V | cut -d' ' -f2) is very new and some packages"
        echo "       have no wheels for it yet. Easiest fix — use Python 3.12:"
        echo "         sudo apt install python3.12 python3.12-venv -y"
        echo "         rm -rf service/.venv"
        echo "         python3.12 -m venv service/.venv"
        echo "         bash setup.sh"
        exit 1
      fi
    else
      bad "could not install the build toolchain"; tail -5 /tmp/pip_err; exit 1
    fi
  else
    bad "dependency install failed:"; tail -8 /tmp/pip_err; exit 1
  fi
fi

# -------------------------------------------------------------- 2. database --
echo
echo "2. Database"
if ! command -v mysql >/dev/null; then
  bad "MariaDB/MySQL not installed. Run: sudo apt install mariadb-server -y"
  exit 1
fi

sudo service mariadb start >/dev/null 2>&1 || sudo service mysql start >/dev/null 2>&1 || true
sleep 2

if ! sudo mysql -e "SELECT 1" >/dev/null 2>&1; then
  bad "cannot reach the database server. Try: sudo service mariadb start"
  exit 1
fi
ok "database server running"

if [ -z "$DB_NAME" ]; then
  DB_NAME=$(sudo mysql -N -B -e \
    "SELECT table_schema FROM information_schema.tables
     WHERE table_name LIKE '%\\_posts'
       AND table_schema NOT IN ('mysql','information_schema','performance_schema','sys')
     GROUP BY table_schema ORDER BY COUNT(*) DESC LIMIT 1;" 2>/dev/null)
fi

if [ -z "$DB_NAME" ]; then
  bad "no WordPress database found on this server."
  echo "       Restore the dump first:"
  echo "         sudo mysql -e \"CREATE DATABASE letsbebio CHARACTER SET utf8mb4;\""
  echo "         sudo mysql letsbebio < /path/to/dump.sql"
  echo "       Or name it explicitly:  DB_NAME=yourdb bash setup.sh"
  exit 1
fi
ok "WordPress database found: '$DB_NAME'"

# read-only user, created idempotently
# Create for both 'localhost' (socket) and '127.0.0.1' (TCP) — MariaDB
# treats them as distinct hosts, and the app connects via TCP.
sudo mysql >/dev/null 2>&1 <<SQL
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASS';
GRANT SELECT ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
CREATE USER IF NOT EXISTS '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASS';
ALTER USER '$DB_USER'@'127.0.0.1' IDENTIFIED BY '$DB_PASS';
GRANT SELECT ON \`$DB_NAME\`.* TO '$DB_USER'@'127.0.0.1';
FLUSH PRIVILEGES;
SQL
if mysql -u "$DB_USER" -p"$DB_PASS" -e "USE \`$DB_NAME\`" >/dev/null 2>&1; then
  ok "read-only user '$DB_USER' works"
else
  bad "could not verify the read-only user"
  exit 1
fi

# Detect the WordPress table prefix.
#
# Matching '%_posts' alone is not enough: plugins create their own tables with
# the same suffix (AIOSEO installs <prefix>aioseo_posts), and picking one of
# those yields a prefix whose other core tables do not exist. So require the
# candidate prefix to carry the full WordPress core set, and prefer the
# shortest match.
PREFIX=$(sudo mysql -N -B "$DB_NAME" -e \
  "SELECT p FROM (
     SELECT SUBSTRING(table_name, 1, LENGTH(table_name)-5) AS p
     FROM information_schema.tables
     WHERE table_schema='$DB_NAME' AND table_name LIKE '%\\_posts'
   ) c
   WHERE EXISTS (SELECT 1 FROM information_schema.tables
                 WHERE table_schema='$DB_NAME'
                   AND table_name = CONCAT(c.p,'postmeta'))
     AND EXISTS (SELECT 1 FROM information_schema.tables
                 WHERE table_schema='$DB_NAME'
                   AND table_name = CONCAT(c.p,'options'))
     AND EXISTS (SELECT 1 FROM information_schema.tables
                 WHERE table_schema='$DB_NAME'
                   AND table_name = CONCAT(c.p,'term_taxonomy'))
   ORDER BY LENGTH(c.p) ASC LIMIT 1;" 2>/dev/null)

if [ -z "$PREFIX" ]; then
  bad "no complete WordPress table set found in '$DB_NAME'"
  echo "       Tables ending in '_posts' present:"
  sudo mysql -N -B "$DB_NAME" -e \
    "SELECT CONCAT('         ', table_name) FROM information_schema.tables
     WHERE table_schema='$DB_NAME' AND table_name LIKE '%\\_posts';" 2>/dev/null
  exit 1
fi

# verify rather than trust: every table the service queries must exist
MISSING=""
for t in posts postmeta options terms term_taxonomy term_relationships; do
  sudo mysql -N -B "$DB_NAME" -e "SELECT 1 FROM \`${PREFIX}${t}\` LIMIT 1" \
    >/dev/null 2>&1 || MISSING="$MISSING ${PREFIX}${t}"
done
if [ -n "$MISSING" ]; then
  bad "prefix '${PREFIX}' is missing tables:$MISSING"
  exit 1
fi
ok "WordPress prefix verified: ${PREFIX}"

COUNT=$(sudo mysql -N -B "$DB_NAME" -e \
  "SELECT COUNT(*) FROM \`${PREFIX}posts\` WHERE post_type='product';" 2>/dev/null)
ok "products in the catalogue: ${COUNT}"

# ------------------------------------------------------------------ 3. .env --
echo
echo "3. Configuration"
if [ -f service/.env ]; then
  warn ".env already exists — left untouched"
else
  cat > service/.env <<ENVFILE
# Written by setup.sh — safe to edit.
CLIENT_NAME=letsbebio

DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=$DB_USER
DB_PASSWORD=$DB_PASS
DB_NAME=$DB_NAME
WP_PREFIX=${PREFIX}

SITE_URL=http://localhost:10004
CORS_ORIGINS=http://localhost:8080,http://127.0.0.1:8080,http://localhost:10004

REBUILD_MINUTES=60
LIVE_STOCK=true

ADMIN_TOKEN=$(head -c 18 /dev/urandom | base64 | tr -d '/+=' 2>/dev/null || echo changeme123)
RATE_LIMIT_PER_MIN=60

# --- optional: conversational agent and free-text understanding -------------
# Leave ENABLE_INTERPRET=false to run without any API key: the questionnaire,
# /recommend and /search all work. Set it to true and paste a key to enable
# /chat and /interpret. Free key: https://console.groq.com
ENABLE_INTERPRET=false
LLM_BASE_URL=https://api.groq.com/openai/v1
LLM_API_KEY=
LLM_MODEL=llama-3.3-70b-versatile
LLM_TIMEOUT=20

# --- optional: semantic search ----------------------------------------------
# Set to "local" after: service/.venv/bin/pip install sentence-transformers numpy
EMBED_BACKEND=off
EMBED_MODEL=paraphrase-multilingual-MiniLM-L12-v2
ENVFILE
  ok "service/.env written (prefix and credentials filled in)"
fi

# ------------------------------------------------------------------- 4. done --
echo
echo "============================="
echo -e "${GREEN}Setup complete.${NC}"
echo
echo "Start the API:      make run"
echo "Then check it:      make test"
echo
echo "Everything works right now except the conversational agent, which needs"
echo "a free API key. When you have one:"
echo "    make enable-agent KEY=gsk_your_key_here"
echo
