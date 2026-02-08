#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
echo "[1/8] Checking prerequisites..."
PYTHON_BIN=""
if command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="python"
elif command -v py >/dev/null 2>&1; then
  PYTHON_BIN="py"
else
  echo "Python not found. Please install Python 3.10+."
  exit 1
fi
if ! "${PYTHON_BIN}" -m pip --version >/dev/null 2>&1; then
  echo "pip not found for ${PYTHON_BIN}. Please install pip."
  exit 1
fi
if ! command -v docker >/dev/null 2>&1; then
  echo "docker not found. Please install Docker."
  exit 1
fi

echo "[2/8] Installing backend dependencies..."
"${PYTHON_BIN}" -m pip install -r "${ROOT_DIR}/agent/backend/requirements.txt"

echo "[3/8] Starting required containers (PostgreSQL, Redis, OnlyOffice)..."
if ! docker ps --format '{{.Names}}' | grep -q '^pgsql-container-5618$'; then
  if docker ps -a --format '{{.Names}}' | grep -q '^pgsql-container-5618$'; then
    docker start pgsql-container-5618
  else
    docker run -d \
      --name pgsql-container-5618 \
      -p 5618:5432 \
      -e POSTGRES_PASSWORD=844700 \
      -e POSTGRES_USER=root \
      -e POSTGRES_DB=queen \
      postgres:16.0
  fi
fi

echo "[4/8] Waiting for PostgreSQL to be ready..."
pg_ready=0
pg_timeout="${POSTGRES_READY_TIMEOUT:-30}"
for ((i=1; i<=pg_timeout; i++)); do
  if docker exec pgsql-container-5618 psql -U root -d queen -c "SELECT 1;" >/dev/null 2>&1; then
    pg_ready=1
    break
  fi
  sleep 1
done
if [[ "${pg_ready}" != "1" ]]; then
  echo "PostgreSQL did not become ready in time (waited ${pg_timeout}s)."
  exit 1
fi

echo "[5/8] Ensuring pgvector is installed in PostgreSQL..."
docker exec pgsql-container-5618 bash -lc "apt-get update && apt-get install -y postgresql-16-pgvector"
docker exec pgsql-container-5618 psql -U root -d queen -c "CREATE EXTENSION IF NOT EXISTS vector;"

if ! docker ps --format '{{.Names}}' | grep -q '^redis$'; then
  if docker ps -a --format '{{.Names}}' | grep -q '^redis$'; then
    docker start redis
  else
    docker run -d \
      --name redis \
      -p 6379:6379 \
      --restart=always \
      redis:7
  fi
fi

if ! docker ps --format '{{.Names}}' | grep -q '^onlyoffice-docs$'; then
  if docker ps -a --format '{{.Names}}' | grep -q '^onlyoffice-docs$'; then
    docker start onlyoffice-docs
  else
    docker run -d \
      --name onlyoffice-docs \
      --restart=always \
      -p 8081:80 \
      -e JWT_ENABLED=true \
      -e JWT_SECRET="ULcmK8RZSxySE7oa36ElOdTOGvMLl0VZ" \
      -v /data/onlyoffice/logs:/var/log/onlyoffice \
      -v /data/onlyoffice/data:/var/www/onlyoffice/Data \
      onlyoffice/documentserver:9.2
  fi
fi

echo "[6/8] Optional containers selection (diagram enhancement tools / 画图增强工具)..."
echo "1) Draw.io (diagram export server / 图表导出)"
echo "2) Kroki (diagram rendering / 图表渲染)"
echo "3) Both Draw.io + Kroki (全部安装)"
echo "4) Skip (default / 跳过)"
echo "Choose option within 40s (default: 4) / 40秒内选择，默认跳过："

user_choice="4"
if read -r -t 40 user_choice; then
  if [[ -z "${user_choice}" ]]; then
    user_choice="4"
  fi
else
  user_choice="4"
fi

enable_drawio=0
enable_kroki=0
case "${user_choice}" in
  1) enable_drawio=1 ;;
  2) enable_kroki=1 ;;
  3) enable_drawio=1; enable_kroki=1 ;;
  4) ;;
  *) echo "Invalid option, defaulting to Skip." ;;
esac

if [[ "${enable_drawio}" == "1" ]]; then
  if ! docker ps --format '{{.Names}}' | grep -q '^drawio-export$'; then
    if docker ps -a --format '{{.Names}}' | grep -q '^drawio-export$'; then
      docker start drawio-export
    else
      docker run -d \
        --name drawio-export \
        -p 8025:8000 \
        jgraph/export-server
    fi
  fi
fi

if [[ "${enable_kroki}" == "1" ]]; then
  docker compose -f "${ROOT_DIR}/install/kroki-compose.yml" up -d
fi

echo "[7/8] Ensuring Claude Code is installed..."
if ! command -v claude >/dev/null 2>&1; then
  if ! command -v npm >/dev/null 2>&1; then
    echo "npm not found. Please install Node.js/npm or install claude-code manually."
    exit 1
  fi
  npm install -g @anthropic-ai/claude-code
fi

echo "[8/8] Starting FastAPI server..."
if command -v lsof >/dev/null 2>&1; then
  existing_pid="$(lsof -ti tcp:8001 || true)"
elif command -v ss >/dev/null 2>&1; then
  existing_pid="$(ss -lptn 'sport = :8001' 2>/dev/null | awk -F 'pid=' 'NR>1 {print $2}' | awk -F ',' '{print $1}' | head -n1)"
else
  existing_pid=""
fi
if [[ -n "${existing_pid}" ]]; then
  echo "Port 8001 is in use by PID ${existing_pid}, stopping it..."
  kill "${existing_pid}" || true
  sleep 1
fi
nohup uvicorn agent.backend.main:app --host 0.0.0.0 --port 8001 > /dev/null 2>&1 &

echo "Done."
