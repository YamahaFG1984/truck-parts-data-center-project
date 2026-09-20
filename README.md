# 卡车配件 AI 产品数据中心

面向卡车配件出口企业的 AI 产品数据库 MVP：把散在 Excel、PDF 和微信里的供应商资料整理成标准字段，
让销售用**一个编号、一句话或一张照片**，在几秒内拿到产品、替代件、成本与建议售价，并把内容一键导到 Alibaba / Shopify。

Python 3.12 · Django 5.2 · PostgreSQL 16（pg_trgm）· HTMX · django-q2 · 国内 OpenAI 兼容大模型（可离线 mock）

> **演示数据声明**：`manage.py seed_demo` 生成的产品、编号、车型与供应商报价全部是合成数据。
> 编号只按各品牌的书写格式随机生成，**不是真实 OE 号**，不能用于采购或报价。

## 截图

| 首页 | 智能查询 |
|---|---|
| ![首页](docs/screenshots/home.png) | ![智能查询](docs/screenshots/search.png) |

| 数据质量看板 | 导入向导：列映射 |
|---|---|
| ![看板](docs/screenshots/quality.png) | ![列映射](docs/screenshots/import-mapping.png) |

| 图片询价 | AI 建议审核台 |
|---|---|
| ![图片询价](docs/screenshots/image-inquiry.png) | ![审核台](docs/screenshots/ai-review.png) |

## 一条命令跑起来

```bash
git clone https://github.com/YamahaFG1984/truck-parts-data-center-project.git
cd truck-parts-data-center-project
bash scripts/demo_up.sh
```

脚本会依次：生成 `.env`（含随机 `SECRET_KEY`）、建虚拟环境装依赖、用 docker 起 PostgreSQL、
迁移、生成演示数据、建演示账号 `demo / demo12345`、启动 `qcluster` 与开发服务器。
打开 http://127.0.0.1:8000/ 登录即可。换端口用 `PORT=8001 bash scripts/demo_up.sh`，
重建数据用 `bash scripts/demo_up.sh --reset`。

演示怎么讲，见 [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)。

## 手动安装

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements/local.txt

cp .env.example .env          # 至少改掉 SECRET_KEY
docker compose up -d db       # PostgreSQL 16；不想用 docker 就把 DATABASE_URL 留空，回落 SQLite

python manage.py migrate
python manage.py seed_demo    # 400 个 SKU + 一份乱格式供应商报价单
python manage.py createsuperuser

python manage.py runserver    # http://127.0.0.1:8000/
python manage.py qcluster     # 另开一个终端：批量 AI 补全等后台任务
```

## 环境变量

`.env` 从 [.env.example](.env.example) 复制，**不进版本库**；CI 用仓库 secrets。

| 变量 | 默认 | 说明 |
|---|---|---|
| `SECRET_KEY` | — | 必填，随便一串随机值 |
| `DEBUG` | `true` | 生产必须 `false` |
| `DATABASE_URL` | 空 → SQLite | `postgres://tpdc:tpdc@localhost:5432/tpdc`；模糊匹配需要 PostgreSQL |
| `POSTGRES_PORT` | `5432` | 宿主机端口被占时改这里，同时改 `DATABASE_URL` |
| `LLM_PROVIDER` | `mock` | `mock` 离线固定示例；`openai_compatible` 接 DashScope / DeepSeek / Kimi |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | DashScope / 空 / `qwen-plus` | 文本模型 |
| `LLM_VISION_*` | 空 → 跟随文本模型 | 视觉模型，默认 `qwen-vl-plus` |
| `DEFAULT_MARGIN` | `0.25` | 建议售价 = 最低成本 × (1 + 毛利率) |
| `COMPANY_SKU_PREFIX` | `FIT-` | SKU 前缀 |

没有 API key 也能完整演示：`LLM_PROVIDER=mock` 时列映射、文案补全、图片识别返回固定示例，
匹配、评分、报价与导出全部是真实计算。

## 测试与检查

```bash
ruff check .                  # 行宽 100
pytest -q                     # 490 个用例；PostgreSQL 下全跑
DATABASE_URL= pytest -q       # SQLite 回落：pg_trgm 相关用例自动跳过
python manage.py makemigrations --check --dry-run
```

CI（[.github/workflows/ci.yml](.github/workflows/ci.yml)）在每次 push 上跑同样的四条命令，带 PostgreSQL 16 service。

## 目录

```
apps/
  core/        TimeStampedModel、SourcedModel、Job；首页与数据质量看板
  users/       自定义 User（第一天就换掉，后面改不动）
  catalog/     Category / Brand / Part / PartNumber / Fitment / PartImage
               services/: normalize 编号归一化、matcher 三级匹配、quality 完整度评分
  suppliers/   Supplier / SupplierOffer；services/quoting 最低成本与建议售价
  importer/    ImportBatch；services/: loader 读表、mapping 列映射、importing 预检与写入
  ai/          AITask / AISuggestion；llm/: base mock openai_compat factory；prompts/*.md
  inquiries/   Inquiry / QuoteLine；图片询价、询价留痕、报价单 xlsx、平台导出 csv
config/settings/   base / local / test / production 分层
docs/          PRD、架构、数据字典、施工进度、面试陈述稿（GitHub Pages）
scripts/       demo_up.sh 一键演示、make_supplier_excel.py 乱格式报价单、gen_diagrams.py 文档配图
```

约定：业务逻辑放 `services/` 与自定义 `QuerySet`，视图保持薄；界面中文、字段英文、USD 单币种；
所有大模型调用经 `apps/ai/llm/factory.get_client()`；**AI 产出只能通过 `AISuggestion.accept()` 写入业务字段**。

## 设计与需求文档

`docs/` 目录是完整规格，也可直接发布到 GitHub Pages（Settings → Pages → `main` / `docs`）：

- [docs/index.html](docs/index.html) — 导航与施工进度表
- [docs/prd.html](docs/prd.html) — 产品需求文档（角色、用户故事、验收标准）
- [docs/architecture.html](docs/architecture.html) — 系统设计（选型取舍、数据模型、核心服务、关键流程、提示词全文）
- [docs/data-dictionary.html](docs/data-dictionary.html) — 标准字段规范与各品牌编号格式
- [docs/schedule.html](docs/schedule.html) — 20 个里程碑的施工进度表与验收命令
- [docs/pitch.html](docs/pitch.html) — 面试陈述稿与预设问答

## 安全与数据边界

- `.env` 不进版本库；`.env.example` 里没有真实值。
- 送进大模型的只有产品公开信息；**成本、供应商与客户信息不进提示词**，`AITask` 只存输入摘要与前 500 字。
- 报价单的成本与供应商在单独的 Internal 表，且只在有成本查看权限时生成；平台导出文件里没有成本与供应商。
- 上传文件用 uuid 命名，图片经 Pillow 校验后重新编码（顺带去掉手机照片的 EXIF / GPS）。
