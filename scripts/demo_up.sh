#!/usr/bin/env bash
# 一条命令把演示环境跑起来：依赖、数据库、迁移、演示数据、演示账号、后台任务、服务器。
# 用法：
#   bash scripts/demo_up.sh              # 已有数据就保留
#   bash scripts/demo_up.sh --reset      # 清空并重建演示数据
#   PORT=8001 bash scripts/demo_up.sh    # 换端口
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-8000}"
DEMO_USER="${DEMO_USER:-demo}"
DEMO_PASSWORD="${DEMO_PASSWORD:-demo12345}"   # 本机演示用，不要用于任何公网部署
RESET=""
[ "${1:-}" = "--reset" ] && RESET="--reset"

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$1"; }

# 1. .env：没有就从模板生成，并换掉占位的 SECRET_KEY
if [ ! -f .env ]; then
  say "生成 .env（照抄 .env.example）"
  cp .env.example .env
  key=$(python3 -c "import secrets; print(secrets.token_urlsafe(50))")
  python3 - "$key" <<'PY'
import pathlib, sys
env = pathlib.Path(".env")
env.write_text(env.read_text().replace("SECRET_KEY=change-me", f"SECRET_KEY={sys.argv[1]}"))
PY
  echo "已写入 .env。默认 LLM_PROVIDER=mock，断网也能完整演示。"
fi
set -a; . ./.env; set +a

# 2. 虚拟环境与依赖
if [ ! -d .venv ]; then
  say "创建虚拟环境并安装依赖"
  python3 -m venv .venv
  .venv/bin/pip install --quiet --upgrade pip
  .venv/bin/pip install --quiet -r requirements/local.txt
fi
PY_BIN=".venv/bin/python"

# 3. 数据库：配了 DATABASE_URL 就起 docker 里的 PostgreSQL，否则用 SQLite
if [ -n "${DATABASE_URL:-}" ]; then
  say "启动 PostgreSQL（docker compose）"
  docker compose up -d db
  for _ in $(seq 1 30); do
    docker compose exec -T db pg_isready -U tpdc -d tpdc >/dev/null 2>&1 && break
    sleep 1
  done
  docker compose exec -T db pg_isready -U tpdc -d tpdc >/dev/null 2>&1 \
    || { echo "数据库没能就绪。端口 ${POSTGRES_PORT:-5432} 可能被占用，改 .env 里的 POSTGRES_PORT 和 DATABASE_URL 后重试。"; exit 1; }
else
  say "未配置 DATABASE_URL，使用 SQLite（db.sqlite3）"
fi

say "执行数据库迁移"
$PY_BIN manage.py migrate --noinput

# 4. 演示数据：已有数据且没加 --reset 就跳过
say "生成演示数据"
if [ -n "$RESET" ] || ! $PY_BIN manage.py shell -c "
from apps.catalog.models import Part
raise SystemExit(0 if Part.objects.exists() else 1)" >/dev/null 2>&1; then
  $PY_BIN manage.py seed_demo $RESET
else
  echo "产品目录已有数据，跳过（要重建请加 --reset）。"
fi

# 5. 演示账号
say "准备演示账号 $DEMO_USER"
DEMO_USER="$DEMO_USER" DEMO_PASSWORD="$DEMO_PASSWORD" $PY_BIN manage.py shell -c "
import os
from django.contrib.auth import get_user_model
User = get_user_model()
user, created = User.objects.get_or_create(
    username=os.environ['DEMO_USER'], defaults={'is_staff': True, 'is_superuser': True})
user.set_password(os.environ['DEMO_PASSWORD'])
user.is_staff = user.is_superuser = True
user.save()
print('已创建' if created else '已重置密码')"

# 6. 后台任务进程，退出时一起收掉
say "启动后台任务进程 qcluster"
$PY_BIN manage.py qcluster >/tmp/tpdc-qcluster.log 2>&1 &
QCLUSTER=$!
trap 'kill $QCLUSTER 2>/dev/null || true' EXIT

cat <<INFO

  演示地址： http://127.0.0.1:$PORT/
  账号 / 密码： $DEMO_USER / $DEMO_PASSWORD
  演示脚本： docs/DEMO_SCRIPT.md
  qcluster 日志： /tmp/tpdc-qcluster.log
  Ctrl-C 结束（会一并关掉 qcluster）。

INFO
$PY_BIN manage.py runserver "$PORT"
