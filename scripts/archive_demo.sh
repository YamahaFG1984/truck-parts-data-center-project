#!/usr/bin/env bash
# 第二阶段一条命令演示：空库 → 导入两份供应商资料 → 自动匹配 → 导出三份结果。
# 用独立的 SQLite 空库（放在输出目录里），不碰日常使用的数据库。
#
# 用法：
#   bash scripts/archive_demo.sh                 # extra/ 里有公司样例就用它，结果写到 extra/output/
#                                                # 否则用合成样例，结果写到 demo-output/
#   bash scripts/archive_demo.sh --synthetic     # 强制用合成样例
#   OUT=/path/to/dir bash scripts/archive_demo.sh
#   LLM_PROVIDER=openai_compatible bash scripts/archive_demo.sh   # 列名认不出时请真实模型建议
set -euo pipefail
cd "$(dirname "$0")/.."

say() { printf "\n\033[1;34m==> %s\033[0m\n" "$1"; }
PY="${PYTHON:-.venv/bin/python}"
[ -x "$PY" ] || PY=python3

A="extra/候选人材料_供应商A报价表.xlsx"
B="extra/候选人材料_供应商B报价表.xlsx"
if [ "${1:-}" != "--synthetic" ] && [ -f "$A" ] && [ -f "$B" ]; then
  OUT="${OUT:-extra/output}"
  FILES=("$A" "$B"); SUPPLIERS=("供应商A" "供应商B")
  say "使用公司样例（extra/，不进仓库），结果写到 $OUT"
else
  OUT="${OUT:-demo-output}"
  say "使用合成样例，结果写到 $OUT"
  "$PY" scripts/make_archive_samples.py "$OUT/samples" >/dev/null
  FILES=("$OUT/samples/01_supplier_x.xlsx" "$OUT/samples/02_supplier_y.xlsx")
  SUPPLIERS=("Supplier X" "Supplier Y")
fi
mkdir -p "$OUT"

# 空库：每次重建；原件存到 media/（已在 .gitignore）
DB="$(cd "$OUT" && pwd)/archive_demo.sqlite3"
rm -f "$DB"
export DATABASE_URL="sqlite:///$DB"
export LLM_PROVIDER="${LLM_PROVIDER:-mock}"
export DJANGO_SETTINGS_MODULE="${DJANGO_SETTINGS_MODULE:-config.settings.local}"

say "建空库并迁移"
"$PY" manage.py migrate -v0
"$PY" manage.py shell -c "
from django.contrib.auth import get_user_model
get_user_model().objects.create_superuser('archive_demo', password='archive-demo-local')" \
  2>&1 | grep -v 'objects imported' || true

for i in 0 1; do
  say "导入 ${SUPPLIERS[$i]}：${FILES[$i]}"
  "$PY" manage.py archive_import "${FILES[$i]}" --supplier "${SUPPLIERS[$i]}" --commit \
    --user archive_demo
done

say "匹配结果（入库时已自动运行；这里再跑一次确认结果稳定）"
"$PY" manage.py archive_rematch

say "导出三份结果"
"$PY" manage.py archive_export --out "$OUT"

say "完成"
echo "结果目录：$OUT（主数据.xlsx、供应商报价.xlsx、待人工确认清单.xlsx）"
echo "要在页面上复核这批数据：DATABASE_URL=sqlite:///$DB $PY manage.py runserver"
echo "  登录 archive_demo / archive-demo-local（仅本机演示账号）"
