"""Generate the inline SVG diagrams in docs/*.html.

Usage (from the repository root):
    python3 scripts/gen_diagrams.py

Each figure is wrapped in <!-- fig:ID --> ... <!-- /fig:ID --> markers inside the
target page; re-running replaces the existing block, so edit coordinates here rather
than in the HTML. Pure standard library, no dependencies.
"""
import html
import re
from pathlib import Path

DOCS = Path(__file__).resolve().parents[1] / "docs"


class D:
    def __init__(self, fid, w, h):
        self.fid, self.w, self.h, self.el = fid, w, h, []

    # ---- primitives -------------------------------------------------
    def box(self, x, y, w, h, title, sub=(), cls="", r=8, bold=False):
        self.el.append(f'<rect class="box {cls}" x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"/>')
        n = 1 + len(sub)
        total = 13 + 14 * (n - 1)
        cy = y + h / 2 - total / 2 + 11
        b = ' font-weight="600"' if bold else ""
        self.el.append(f'<text x="{x + w / 2}" y="{cy:.0f}" text-anchor="middle"{b}>{html.escape(title)}</text>')
        for i, s in enumerate(sub):
            self.el.append(f'<text x="{x + w / 2}" y="{cy + 15 + 14 * i:.0f}" text-anchor="middle" class="small">{html.escape(s)}</text>')

    def arrow(self, pts, label=None, dashed=False, hi=False, lx=None, ly=None, anchor="middle", noarrow=False):
        d = "M" + " L".join(f"{x},{y}" for x, y in pts)
        cls = "arrow hi" if hi else "arrow"
        mk = "" if noarrow else f' marker-end="url(#{self.fid}-arr{"h" if hi else ""})"'
        da = ' stroke-dasharray="5 4"' if dashed else ""
        self.el.append(f'<path class="{cls}" d="{d}"{mk}{da}/>')
        if label:
            if lx is None:
                (x1, y1), (x2, y2) = pts[0], pts[-1]
                lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 6
            self.el.append(f'<text x="{lx}" y="{ly}" text-anchor="{anchor}" class="small">{html.escape(label)}</text>')

    def text(self, x, y, t, cls="", anchor="start", bold=False):
        c = f' class="{cls}"' if cls else ""
        b = ' font-weight="600"' if bold else ""
        self.el.append(f'<text x="{x}" y="{y}" text-anchor="{anchor}"{c}{b}>{html.escape(t)}</text>')

    def lane(self, x, y, w, h, label, r=10):
        self.el.append(f'<rect class="lane" x="{x}" y="{y}" width="{w}" height="{h}" rx="{r}"/>')
        self.el.append(f'<text x="{x + 12}" y="{y + 18}" class="lane-label">{html.escape(label)}</text>')

    def band(self, x, y, w, h):
        self.el.append(f'<rect class="band" x="{x}" y="{y}" width="{w}" height="{h}" rx="6"/>')

    def life(self, x, y1, y2):
        self.el.append(f'<line class="life" x1="{x}" y1="{y1}" x2="{x}" y2="{y2}"/>')

    def dot(self, x, y, r=5):
        self.el.append(f'<circle cx="{x}" cy="{y}" r="{r}" style="fill:var(--muted)"/>')

    # ---- output -----------------------------------------------------
    def render(self, caption, aria):
        defs = (
            f'<defs><marker id="{self.fid}-arr" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" style="fill:var(--muted)"/></marker>'
            f'<marker id="{self.fid}-arrh" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" style="fill:var(--accent)"/></marker></defs>'
        )
        body = "\n".join(self.el)
        return (
            f'<!-- fig:{self.fid} -->\n<figure class="svg-diagram">\n'
            f'<svg viewBox="0 0 {self.w} {self.h}" xmlns="http://www.w3.org/2000/svg" role="img" aria-label="{html.escape(aria)}">\n{defs}\n{body}\n</svg>\n'
            f'<figcaption>{caption}</figcaption>\n</figure>\n<!-- /fig:{self.fid} -->'
        )


def seq(fid, lifelines, msgs, phases=(), w=960, caption="", aria=""):
    """Sequence diagram. lifelines: [(title, sub, cls)]; msgs: [(frm, to, label, dashed)]."""
    n = len(lifelines)
    margin = 90
    xs = [margin + i * (w - 2 * margin) / (n - 1) for i in range(n)]
    head_y, head_h, start_y, step = 14, 46, 92, 26
    h = start_y + len(msgs) * step + 16
    d = D(fid, w, h)
    for (label, s0, s1) in phases:
        y0 = start_y + s0 * step - 16
        y1 = start_y + s1 * step + 4
        d.band(8, y0, w - 16, y1 - y0)
        d.text(14, y0 + 13, label, cls="lane-label")
    for i, (t, s, cls) in enumerate(lifelines):
        bw = 150 if i not in (0, n - 1) else 120
        d.life(xs[i], head_y + head_h, h - 8)
        d.box(xs[i] - bw / 2, head_y, bw, head_h, t, (s,) if s else (), cls=cls, bold=True)
    for i, (frm, to, label, dashed) in enumerate(msgs):
        y = start_y + i * step
        x1, x2 = xs[frm], xs[to]
        if frm == to:
            d.arrow([(x1, y - 4), (x1 + 40, y - 4), (x1 + 40, y + 8), (x1 + 4, y + 8)], dashed=dashed)
            d.text(x1 + 48, y + 6, label, cls="small")
        else:
            d.arrow([(x1, y), (x2, y)], dashed=dashed)
            d.text((x1 + x2) / 2, y - 5, label, cls="small", anchor="middle")
    return d.render(caption, aria)


FIGS = {}   # fid -> (file, insert_before_marker, html)


def reg(fid, file, before, svg):
    FIGS[fid] = (file, before, svg)


# =====================================================================
# PRD figures
# =====================================================================

# P1 一个零件的多个身份 ------------------------------------------------
d = D("p1", 900, 430)
d.box(340, 170, 220, 90, "SKU FIT-BRK-00123", ("Brake Pad Set, Front Axle", "分类 · 规格 · 图片 · 包装"), cls="soft", bold=True)
d.box(300, 30, 160, 50, "Volvo FH12 / D12", ("1993–2005",))
d.box(480, 30, 160, 50, "Renault Magnum", ("1997–2005",))
d.arrow([(400, 170), (380, 80)]); d.arrow([(500, 170), (560, 80)])
d.text(450, 128, "适配车型 Fitment", cls="small", anchor="middle")
d.box(40, 120, 200, 50, "Volvo OE 20443906")
d.box(40, 200, 200, 50, "Renault OE 7420443906", ("= 74 + Volvo 号",))
d.arrow([(240, 145), (340, 200)]); d.arrow([(240, 225), (340, 225)])
d.text(290, 128, "原厂号 kind=OE", cls="small", anchor="middle")
d.box(660, 120, 200, 50, "Knorr-Bremse K001234")
d.box(660, 200, 200, 50, "Meritor MDP5090", ("示意编号",))
d.arrow([(560, 200), (660, 145)]); d.arrow([(560, 225), (660, 225)])
d.text(598, 128, "互换号 kind=CROSS", cls="small", anchor="middle")
d.box(300, 340, 180, 60, "供应商甲 HB-2044", ("USD 18.50 · MOQ 50 · 25 天",))
d.box(500, 340, 180, 60, "供应商乙 BP-0931", ("USD 17.90 · MOQ 100 · 30 天",))
d.arrow([(400, 260), (360, 340)]); d.arrow([(500, 260), (620, 340)])
d.text(450, 292, "kind=SUPPLIER", cls="small", anchor="middle")
d.box(40, 330, 200, 60, "客户询价", ("拿着任一编号 / 照片 / 名称",), cls="ext")
d.arrow([(240, 360), (340, 250)], hi=True, label="要在几秒内对上号", lx=300, ly=330, anchor="start")
reg("p1", "prd.html", '<div class="tbl"><table>\n<tr><th>术语</th>',
    d.render("图 P1 · 同一个零件的多个身份。客户拿着任意一个身份来问，系统都要落到同一个 SKU 上，这就是匹配的核心难点。编号为示意。",
             "一个 SKU 与它的 OE 号、互换号、供应商料号、适配车型的关系"))

# P2 询盘处理 before/after ----------------------------------------------
d = D("p2", 900, 380)
d.lane(10, 10, 880, 170, "今天：询盘靠翻表和问人")
d.box(30, 80, 110, 50, "客户", ("发来一个号 / 一张图",), cls="ext")
d.box(180, 80, 110, 50, "销售")
d.arrow([(140, 105), (180, 105)])
d.box(340, 34, 170, 40, "翻多份 Excel", cls="warn2")
d.box(340, 84, 170, 40, "问采购要成本", cls="warn2")
d.box(340, 134, 170, 40, "问产品经理确认适配", cls="warn2")
d.arrow([(290, 100), (340, 54)]); d.arrow([(290, 105), (340, 104)]); d.arrow([(290, 110), (340, 154)])
d.box(560, 80, 150, 50, "回复客户", ("数小时到数天",), cls="bad2")
d.arrow([(510, 54), (560, 100)]); d.arrow([(510, 104), (560, 105)]); d.arrow([(510, 154), (560, 110)])
d.text(760, 100, "信息散在人脑和个人电脑", cls="small", anchor="middle")
d.text(760, 116, "查完不沉淀，下次再查一遍", cls="small", anchor="middle")
d.lane(10, 200, 880, 170, "有了系统：一个搜索框")
d.box(30, 260, 110, 50, "客户", ("发来一个号 / 一张图",), cls="ext")
d.box(180, 260, 140, 50, "一个搜索框", ("编号 / 名称 / 照片",), cls="soft")
d.arrow([(140, 285), (180, 285)])
d.box(370, 260, 190, 50, "产品数据库", ("归一化 · 三级匹配 · 视觉识别",), cls="soft")
d.arrow([(320, 285), (370, 285)], label="自动识别输入类型")
d.box(610, 260, 170, 50, "产品 + 替代件 + 成本 + 售价", ("≤ 5 秒",), cls="good")
d.arrow([(560, 285), (610, 285)])
d.box(820, 260, 60, 50, "回复", cls="good")
d.arrow([(780, 285), (820, 285)])
d.arrow([(455, 310), (455, 345), (250, 345), (250, 310)], dashed=True, label="每次查询自动留痕，未命中进补数榜", lx=352, ly=340)
reg("p2", "prd.html", "<h3>1.3 MVP 目标</h3>",
    d.render("图 P2 · 一条询盘的处理路径：今天要经过三个人和多份表；有了系统后是一个搜索框直达数据库，并且每次查询都沉淀下来。",
             "询盘处理流程在有系统前后的对比"))

# P3a 数据进入与变干净 --------------------------------------------------
d = D("p3a", 960, 380)
for i, t in enumerate(["供应商 Excel / CSV", "供应商 PDF 目录", "供应商图片", "公司现有 Excel"]):
    y = 50 + i * 50
    d.box(20, y, 150, 40, t, cls="ext")
    d.arrow([(170, y + 20), (230, 140)])
d.box(230, 95, 170, 90, "F1 导入向导", ("表头定位 · 列映射", "预检 · 事务导入"), cls="soft", bold=True)
d.box(460, 110, 150, 60, "Part · draft", ("source=import",))
d.arrow([(400, 140), (460, 140)], label="事务写入")
d.box(230, 300, 170, 50, "SupplierOffer", ("成本 · MOQ · 交期",))
d.arrow([(300, 185), (300, 300)], label="报价单同样走导入", lx=308, ly=245, anchor="start")
d.box(460, 220, 150, 60, "F5 AI 补全", ("生成 AISuggestion",), cls="soft")
d.arrow([(535, 170), (535, 220)], label="缺什么补什么", lx=543, ly=200, anchor="start")
d.box(670, 220, 150, 60, "审核台", ("字段级采纳 / 拒绝 · 留痕",), cls="soft")
d.arrow([(610, 250), (670, 250)], label="pending", lx=640, ly=268)
d.box(670, 110, 150, 60, "Part · reviewed", ("AI 字段 source=ai 可追溯",), cls="good")
d.arrow([(745, 220), (745, 170)], label="采纳写回", lx=753, ly=200, anchor="start")
d.arrow([(610, 140), (670, 140)], dashed=True, label="人工审核", lx=640, ly=126)
d.box(860, 110, 90, 60, "F8 导出", ("Alibaba", "Shopify"))
d.arrow([(820, 140), (860, 140)])
d.box(460, 300, 150, 50, "F2 质量看板", ("完整度 · 缺失 · 疑似重复",))
d.arrow([(460, 160), (440, 160), (440, 325), (460, 325)], dashed=True, label="评分", lx=432, ly=250, anchor="end")
d.arrow([(680, 165), (645, 165), (645, 325), (610, 325)], dashed=True, label="评分", lx=653, ly=300, anchor="start")
reg("p3a", "prd.html", '<h2 id="s2">2. 岗位职责与系统功能对照</h2>',
    d.render("图 P3a · 数据怎么进来、怎么变干净：所有来源经导入向导成为 draft，AI 只产生待审核建议，人采纳后才成为 reviewed；看板全程度量。",
             "产品数据从供应商资料到已审核状态的流转"))

# P3b 数据被使用 ---------------------------------------------------------
d = D("p3b", 960, 320)
d.box(20, 100, 150, 70, "客户输入", ("编号 / 名称", "照片"), cls="ext")
d.box(230, 100, 170, 70, "归一化 · 三级匹配", ("F3 智能查询",), cls="soft")
d.arrow([(170, 125), (230, 125)], label="编号 / 名称", lx=200, ly=118)
d.box(230, 210, 170, 60, "视觉识别", ("F4 · 零件类型 · 可见编号",), cls="soft")
d.arrow([(170, 150), (230, 240)], label="照片", lx=190, ly=205, anchor="middle")
d.arrow([(315, 210), (315, 170)], label="识别出的编号再查库", lx=323, ly=195, anchor="start")
d.box(460, 20, 170, 60, "产品数据库", ("Part · PartNumber · Fitment",), cls="ext")
d.arrow([(400, 120), (460, 60)], dashed=True, label="只查库，不让 AI 猜号", lx=472, ly=98, anchor="start")
d.box(460, 100, 170, 70, "候选 + 替代件", ("匹配类型 · 分数 · 完整度",), cls="good")
d.arrow([(400, 135), (460, 135)])
d.box(690, 30, 150, 50, "SupplierOffer", ("三家成本",), cls="ext")
d.box(690, 100, 150, 70, "F6 报价单", ("最低成本 × (1 + 毛利)",), cls="soft")
d.arrow([(630, 135), (690, 135)], label="确认后")
d.arrow([(765, 80), (765, 100)], label="best_offer", lx=773, ly=95, anchor="start")
d.box(880, 110, 60, 50, "xlsx", cls="good")
d.arrow([(840, 135), (880, 135)])
d.box(690, 210, 150, 60, "F7 询价留痕", ("输入 · 命中 · 时间 · 人",))
d.arrow([(545, 170), (545, 240), (690, 240)], label="每次查询自动留痕", lx=555, ly=232, anchor="start")
d.arrow([(765, 270), (765, 295), (95, 295), (95, 170)], dashed=True, label="未命中榜 → 下一步补哪些数据", lx=430, ly=310)
reg("p3b", "prd.html", '<h2 id="s2">2. 岗位职责与系统功能对照</h2>',
    d.render("图 P3b · 数据怎么被使用：文字和照片两种输入都落到同一套匹配上，匹配只查自家数据库；结果直接生成报价单，查询本身又反哺数据补齐。",
             "客户询价从输入到报价单与留痕的流转"))

# P4 角色-功能地图 --------------------------------------------------------
d = D("p4", 900, 340)
roles = [
    ("销售", ["F3 智能查询", "F4 图片询价", "F6 一键报价单", "F7 询价留痕"], "读产品与成本"),
    ("采购", ["F1 导入供应商报价单", "F6 供应商比价", "F0 供应商信息维护"], "写供应商与报价"),
    ("数据运营（本岗位）", ["F1 导入向导 · 数据字典", "F2 质量看板", "F5 AI 补全审核台", "F0 后台维护分类属性"], "写主数据并审核"),
    ("总经理", ["F2 看板：数据健康度", "F7 未命中榜：需求沉淀"], "看指标"),
]
for i, (r, feats, verb) in enumerate(roles):
    x = 20 + i * 220
    d.lane(x, 14, 200, 218, r)
    for j, f in enumerate(feats):
        d.box(x + 12, 46 + j * 44, 176, 34, f, cls="soft" if "F" in f[:2] else "")
    d.arrow([(x + 100, 232), (x + 100, 268)], label=verb, lx=x + 106, ly=254, anchor="start")
d.box(20, 268, 860, 56, "标准化产品数据", ("Part · PartNumber · Fitment · SupplierOffer · Inquiry · AISuggestion",), cls="ext", bold=True)
reg("p4", "prd.html", '<h2 id="s4">4. 核心概念词典</h2>',
    d.render("图 P4 · 谁用哪些功能：四类角色各自的入口不同，但都读写同一份标准化产品数据，这份数据是系统的中心。",
             "四类用户角色与功能、共享数据的关系"))

# P5 状态机 ----------------------------------------------------------------
d = D("p5", 900, 290)
d.text(20, 30, "Part.status", cls="lane-label")
d.dot(30, 68)
d.box(60, 40, 180, 56, "draft", ("导入 / AI / 手工新建后的初始态",))
d.arrow([(35, 68), (60, 68)])
d.box(330, 40, 180, 56, "reviewed", ("关键字段经人确认",), cls="good")
d.arrow([(240, 68), (330, 68)], label="人工审核")
d.box(600, 40, 180, 56, "published", ("已导出上架",), cls="good")
d.arrow([(510, 68), (600, 68)], label="F8 导出后标记")
d.arrow([(690, 96), (690, 118), (420, 118), (420, 96)], dashed=True, label="关键字段变更需复审", lx=555, ly=132)
d.text(20, 170, "AISuggestion.status", cls="lane-label")
d.dot(30, 208)
d.box(60, 180, 180, 56, "pending", ("AI 生成，等待审核",), cls="warn2")
d.arrow([(35, 208), (60, 208)])
d.box(330, 160, 180, 44, "accepted", ("采纳的字段写回 Part",), cls="good")
d.box(330, 222, 180, 44, "rejected", ("记录原因，用于改提示词",), cls="bad2")
d.arrow([(240, 200), (330, 182)], label="采纳", lx=280, ly=180)
d.arrow([(240, 216), (330, 244)], label="拒绝", lx=280, ly=246)
d.arrow([(420, 160), (420, 138), (150, 138), (150, 96)], hi=True, label="accept()：逐字段写回 · source=ai · 状态不变", lx=275, ly=152)
d.text(560, 200, "唯一一条 AI 内容进入业务字段的路径", cls="small")
reg("p5", "prd.html", '<h2 id="s7">7. 非功能需求</h2>',
    d.render("图 P5 · 两个状态机。Part 从 draft 到 reviewed 必须经人；AISuggestion 只有 accepted 一条路能写回 Part，且不改变 Part 的状态。",
             "Part 与 AISuggestion 的状态转换"))

# =====================================================================
# Architecture figures
# =====================================================================

# A1 app 依赖图 -------------------------------------------------------------
d = D("a1", 900, 400)
d.box(60, 30, 160, 50, "importer", ("导入向导",), bold=True)
d.box(300, 30, 160, 50, "inquiries", ("查询 · 图片 · 报价 · 导出",), bold=True)
d.box(660, 30, 160, 50, "users", ("自定义 User",), cls="ext", bold=True)
d.box(60, 130, 160, 50, "ai", ("LLM 封装 · 建议 · 审计",), bold=True)
d.box(540, 130, 160, 50, "suppliers", ("Supplier · Offer · quoting",), bold=True)
d.box(300, 230, 160, 50, "catalog", ("Part · 编号 · 匹配 · 评分",), cls="soft", bold=True)
d.box(300, 330, 160, 50, "core", ("TimeStampedModel · SourcedModel",), cls="ext", bold=True)
d.arrow([(140, 80), (140, 130)], label="列映射用 LLM", lx=148, ly=110, anchor="start")
d.arrow([(200, 80), (330, 230)], label="写 Part / PartNumber", lx=262, ly=140, anchor="start")
d.arrow([(220, 60), (540, 148)], label="写报价", lx=400, ly=98, anchor="middle")
d.arrow([(300, 60), (220, 140)], label="视觉识别", lx=250, ly=96, anchor="middle")
d.arrow([(380, 80), (380, 230)], label="matcher", lx=388, ly=160, anchor="start")
d.arrow([(460, 60), (580, 130)], label="best_offer", lx=540, ly=90, anchor="middle")
d.arrow([(460, 45), (660, 45)], dashed=True, label="created_by（importer、ai 同）", lx=560, ly=38)
d.arrow([(220, 165), (300, 245)], label="补全 Part", lx=228, ly=232, anchor="end")
d.arrow([(540, 165), (460, 245)], label="Offer → Part", lx=520, ly=225, anchor="middle")
d.arrow([(380, 280), (380, 330)], label="所有 app 的模型继承 core 的抽象基类", lx=388, ly=310, anchor="start")
d.text(720, 250, "箭头方向 = import 方向", cls="small")
d.text(720, 268, "只允许向下依赖，禁止反向与循环", cls="small")
reg("a1", "architecture.html", '<h2 id="s5">5. Django 5.2 实践清单</h2>',
    d.render("图 A1 · app 之间的依赖方向。catalog 是核心，上层 app 依赖它，它不依赖任何业务 app；这条规则是避免循环导入的全部依据。",
             "各 Django app 的依赖方向"))

# A2 一次搜索请求 ---------------------------------------------------------
d = D("a2", 960, 270)
d.box(20, 70, 130, 80, "浏览器", ("输入框 hx-get", "防抖 300 ms"), cls="ext")
d.box(190, 70, 170, 80, "SearchView", ("GET /search/?q=", "request.htmx 判断整页或局部"), cls="soft")
d.box(400, 70, 190, 80, "matcher.search()", ("normalize → L1 → L2 → L3", "返回 list[Candidate]"), cls="soft")
d.box(630, 70, 160, 80, "PartQuerySet", ("with_related()", "with_min_cost()"))
d.box(830, 70, 110, 80, "PostgreSQL", ("B-tree", "GIN trigram"), cls="ext")
d.arrow([(150, 95), (190, 95)], label="q", lx=170, ly=88)
d.arrow([(360, 95), (400, 95)], label="q", lx=380, ly=88)
d.arrow([(590, 95), (630, 95)], label="ids", lx=610, ly=88)
d.arrow([(790, 95), (830, 95)], label="≤ 8 条 SQL", lx=810, ly=62)
d.arrow([(830, 125), (790, 125)], dashed=True)
d.arrow([(630, 125), (590, 125)], dashed=True, label="Part + 预取", lx=610, ly=166)
d.arrow([(400, 125), (360, 125)], dashed=True, label="Candidate[]", lx=380, ly=166)
d.arrow([(190, 125), (150, 125)], dashed=True, label="局部 HTML", lx=170, ly=166)
d.text(80, 186, "hx-swap 只替换结果区", cls="small", anchor="middle")
d.box(190, 200, 170, 50, "Inquiry.objects.create", ("F7 留痕，一条 INSERT",))
d.arrow([(275, 150), (275, 200)], label="每次非空查询", lx=283, ly=180, anchor="start")
d.text(520, 235, "视图只做三件事：取参数、调服务、渲染模板。", cls="small")
d.text(520, 253, "匹配逻辑全部在 services，后台任务与测试可直接调用。", cls="small")
reg("a2", "architecture.html", '<h2 id="s3">3. 技术选型与取舍</h2>',
    d.render("图 A2 · 一次搜索请求穿过的层。实线是请求方向，虚线是返回；视图很薄，匹配全在服务层。",
             "一次 HTMX 搜索请求从浏览器到数据库再返回的路径"))

# A3 导入向导时序 --------------------------------------------------------
svg = seq("a3",
    [("用户", "", "ext"), ("导入向导视图", "importer.views", "soft"), ("loader", "importer.services", ""),
     ("mapping", "importer.services", ""), ("LLM", "mock 或真实", "ext"), ("数据库", "PostgreSQL", "ext")],
    [
        (0, 1, "① 上传 Excel，选择供应商", False),
        (1, 2, "read_table(file)", False),
        (2, 2, "定位表头 · 全列转字符串 · 去空行", False),
        (2, 1, "DataFrame 预览", True),
        (1, 0, "前 20 行 + 表头列表", True),
        (1, 3, "② suggest_mapping(headers, samples)", False),
        (3, 3, "同义词表命中 → confidence 1.0", False),
        (3, 4, "只送未命中的表头 + 3 行样例", False),
        (4, 3, "JSON 映射 + 置信度", True),
        (3, 1, "建议映射（含来源）", True),
        (1, 0, "映射表，可逐列修改", True),
        (0, 1, "③ 确认映射，点预检", False),
        (1, 2, "dry_run(batch)", False),
        (2, 5, "按 number_norm 查已有编号", False),
        (5, 2, "已有 / 已验证 / 冲突", True),
        (2, 1, "新增 / 更新 / 跳过 / 无效 + 原因", True),
        (1, 0, "预检报告（HTMX 局部）", True),
        (0, 1, "④ 点导入", False),
        (1, 2, "execute(batch)  transaction.atomic", False),
        (2, 5, "写 Part · PartNumber · SupplierOffer · ImportRow", False),
        (2, 2, "quality.recompute(受影响的 Part)", False),
        (2, 1, "ImportReport", True),
        (1, 0, "结果页：统计 · 疑似重复 · 逐行结果", True),
    ],
    phases=[("上传与预览", 0, 4), ("列映射", 5, 10), ("预检", 11, 16), ("导入", 17, 22)],
    caption="图 A3 · 导入向导的四步时序。同义词表先于 AI；预检不写库；导入在一个事务里，任一行异常整批回滚。",
    aria="导入向导从上传到结果页的调用时序")
reg("a3", "architecture.html", "<h3>8.2 图片询价</h3>", svg)

# A4 导入行判定树 ----------------------------------------------------------
d = D("a4", 900, 470)
d.box(20, 40, 120, 44, "读取一行")
d.box(180, 40, 210, 44, "有 sku / OE / 供应商料号？", cls="dec")
d.arrow([(140, 62), (180, 62)])
d.box(180, 120, 210, 44, "无效：记录具体原因", cls="bad2")
d.arrow([(285, 84), (285, 120)], label="否", lx=292, ly=106, anchor="start")
d.box(430, 40, 170, 44, "拆分一格多号 · 归一化")
d.arrow([(390, 62), (430, 62)], label="是", lx=410, ly=55)
d.box(640, 40, 240, 44, "number_norm 已在库中？", cls="dec")
d.arrow([(600, 62), (640, 62)])
d.box(640, 120, 240, 44, "新增 Part(draft) + PartNumber", cls="good")
d.arrow([(760, 84), (760, 120)], label="否", lx=768, ly=106, anchor="start")
d.box(640, 200, 240, 44, "指向同一个 SKU？", cls="dec")
d.arrow([(880, 62), (892, 62), (892, 222), (880, 222)], label="是", lx=897, ly=150, anchor="start")
d.box(400, 200, 200, 44, "标记疑似重复 · 不覆盖", cls="warn2")
d.arrow([(640, 222), (600, 222)], label="否", lx=620, ly=215)
d.box(640, 280, 240, 44, "该字段已 verified？", cls="dec")
d.arrow([(760, 244), (760, 280)], label="是", lx=768, ly=266, anchor="start")
d.box(400, 280, 200, 44, "保留原值，跳过")
d.arrow([(640, 302), (600, 302)], label="是", lx=620, ly=295)
d.box(640, 360, 240, 44, "更新：以新补空 · source=import", cls="good")
d.arrow([(760, 324), (760, 360)], label="否", lx=768, ly=346, anchor="start")
d.box(20, 420, 860, 36, "每条路径都写一条 ImportRow(result, message)；批次结束后对受影响的 Part 调用 quality.recompute", cls="ext", r=6)
reg("a4", "architecture.html", "<h3>7.6 quoting 与 export</h3>",
    d.render("图 A4 · 导入时每一行的判定顺序。黄色是判断，绿色是写入，红色是拒绝；\"疑似重复\"不阻止导入，只是不覆盖并进看板。",
             "导入执行时单行数据的判定流程"))

# A5 图片询价时序 --------------------------------------------------------
svg = seq("a5",
    [("用户", "", "ext"), ("ImageInquiryView", "inquiries.views", "soft"), ("image_inquiry", "inquiries.services", ""),
     ("视觉模型", "qwen-vl / mock", "ext"), ("matcher", "catalog.services", ""), ("数据库", "", "ext")],
    [
        (0, 1, "上传照片", False),
        (1, 2, "prepare_image(file)", False),
        (2, 2, "Pillow 校验 · 压缩到长边 1280", False),
        (2, 5, "创建 Inquiry(input_type=image)", False),
        (2, 3, "describe_image(prompt=image_identify)", False),
        (3, 2, "ImageFinding: 类型 · 可见编号 · 品牌线索", True),
        (2, 2, "写 AITask 审计", False),
        (2, 4, "对每个可见编号 search()", False),
        (4, 5, "三级匹配查询", False),
        (5, 4, "候选", True),
        (4, 2, "Candidate[] 合并去重", True),
        (2, 4, "无编号时：按零件类型 + 品牌线索检索名称", False),
        (2, 1, "识别结果 + 候选（全部待确认）", True),
        (1, 0, "候选列表页", True),
        (0, 1, "点选一个候选", False),
        (1, 5, "Inquiry.matched_part = 选中的 Part", False),
    ],
    caption="图 A5 · 图片询价时序。视觉模型只负责读图，编号一律回到自家数据库匹配；确认之前 matched_part 保持为空。",
    aria="图片询价从上传到确认候选的调用时序")
reg("a5", "architecture.html", "<h3>8.3 AI 补全与审核</h3>", svg)

# A6 AI 补全审核数据流 ------------------------------------------------------
d = D("a6", 960, 320)
d.box(390, 16, 150, 46, "DeepSeek / 千问 / mock", ("OpenAI 兼容接口",), cls="ext")
d.box(20, 110, 140, 70, "Part（有缺失）", ("draft 或 reviewed",))
d.box(200, 110, 150, 70, "build_context()", ("名称 · 编号 · 适配", "同类已审核样例 2 条"))
d.arrow([(160, 145), (200, 145)])
d.box(390, 110, 150, 70, "get_client()", ("extract_json(enrich_part)", "JSON mode + pydantic"), cls="soft")
d.arrow([(350, 145), (390, 145)], label="变量")
d.arrow([(465, 110), (465, 62)], dashed=True, label="HTTPS", lx=472, ly=90, anchor="start")
d.box(390, 230, 150, 50, "AITask", ("model · tokens · latency · status",), cls="ext")
d.arrow([(465, 180), (465, 230)], label="每次调用一条", lx=472, ly=210, anchor="start")
d.box(580, 110, 150, 70, "AISuggestion", ("status=pending", "payload · confidence"), cls="warn2")
d.arrow([(540, 145), (580, 145)], label="EnrichResult")
d.box(770, 110, 170, 70, "审核台 /ai/review/", ("当前值 vs 建议值", "字段级勾选"), cls="soft")
d.arrow([(730, 145), (770, 145)])
d.box(770, 230, 170, 50, "reject：记录原因", ("反馈到提示词优化",), cls="bad2")
d.arrow([(855, 180), (855, 230)], label="拒绝", lx=862, ly=210, anchor="start")
d.arrow([(790, 180), (790, 300), (90, 300), (90, 180)], hi=True, label="accept()：只写勾选字段 · source=ai · confidence · 重算完整度", lx=440, ly=316)
reg("a6", "architecture.html", '<h2 id="s9">9. 安全与数据治理</h2>',
    d.render("图 A6 · AI 补全的数据流。模型输出先落成 AISuggestion，只有审核台的 accept() 这一条蓝色路径能把内容写回 Part。",
             "AI 补全从上下文组装到审核写回的数据流"))

# A7 LLM 封装结构 ------------------------------------------------------------
d = D("a7", 900, 300)
d.box(20, 90, 200, 90, "调用方", ("importer.services.mapping", "ai.services.enrich", "inquiries.services.image_inquiry"))
d.box(280, 20, 160, 50, ".env → settings", ("LLM_PROVIDER · BASE_URL · KEY · MODEL",), cls="ext")
d.box(280, 105, 160, 60, "llm.factory", ("get_client()",), cls="soft")
d.arrow([(220, 135), (280, 135)], label="唯一入口", lx=250, ly=128)
d.arrow([(360, 70), (360, 105)])
d.box(500, 105, 180, 60, "LLMClient（Protocol）", ("extract_json · generate_text", "describe_image"), cls="soft")
d.arrow([(440, 135), (500, 135)], label="返回实例", lx=470, ly=128)
d.box(720, 30, 160, 55, "OpenAICompatClient", ("openai SDK · base_url",))
d.box(720, 110, 160, 50, "DeepSeek / 千问 / Kimi", ("HTTPS",), cls="ext")
d.box(720, 200, 160, 50, "MockClient", ("读 *.example.json · 离线",))
d.arrow([(680, 125), (720, 60)], dashed=True, label="实现", lx=714, ly=110, anchor="start")
d.arrow([(680, 150), (720, 222)], dashed=True, label="实现", lx=668, ly=195, anchor="end")
d.arrow([(800, 85), (800, 110)])
d.box(500, 215, 180, 60, "prompts/loader", ("*.md：front matter + 模板", "str.format_map 填变量"))
d.arrow([(590, 215), (590, 165)], label="渲染提示词", lx=598, ly=195, anchor="start")
d.box(280, 215, 160, 60, "AITask", ("每次调用写一条审计",), cls="ext")
d.arrow([(500, 160), (440, 235)], label="写入", lx=478, ly=210, anchor="start")
reg("a7", "architecture.html", "<ul>\n<li><b>每次调用产生一条 AITask</b>",
    d.render("图 A7 · 大模型封装。业务代码只认识 factory 与 Protocol，换提供商只改 .env；mock 实现让全流程离线可跑。",
             "LLM 客户端抽象、实现与提示词加载的结构"))

# A8 部署拓扑 ------------------------------------------------------------------
d = D("a8", 900, 300)
d.box(20, 110, 150, 60, "销售 / 采购的浏览器", ("办公网",), cls="ext")
d.lane(220, 14, 530, 272, "演示机（一台）")
d.box(250, 60, 200, 60, "gunicorn · Django", ("whitenoise 服务静态文件",), cls="soft")
d.arrow([(170, 140), (250, 90)], label=":8000 HTTP", lx=180, ly=110, anchor="start")
d.box(250, 150, 200, 60, "qcluster", ("django-q2 worker · 批量任务",), cls="soft")
d.box(490, 60, 230, 60, "docker: postgres:16", ("卷 pgdata · pg_trgm · 任务表",), cls="ext")
d.box(490, 150, 230, 50, "media/", ("上传文件 · 图片 · 生成的 Excel",), cls="ext")
d.box(250, 232, 470, 40, ".env：密钥、DATABASE_URL、模型配置（不入 git）", cls="ext", r=6)
d.arrow([(450, 80), (490, 80)], label="SQL", lx=470, ly=73)
d.arrow([(450, 165), (470, 165), (470, 100), (490, 100)], label="任务表", lx=474, ly=147, anchor="start")
d.arrow([(400, 120), (400, 135), (560, 135), (560, 150)], label="读写", lx=480, ly=131, anchor="middle")
d.arrow([(450, 190), (490, 190)], label="读写", lx=470, ly=205)
d.box(780, 60, 110, 60, "大模型接口", ("互联网",), cls="ext")
d.arrow([(350, 60), (350, 40), (835, 40), (835, 60)], dashed=True, label="HTTPS，仅送产品公开属性与照片", lx=590, ly=34)
d.arrow([(350, 210), (350, 220), (760, 220), (760, 100), (780, 100)], dashed=True)
reg("a8", "architecture.html", '<h2 id="s13">13. 演进路线</h2>',
    d.render("图 A8 · 演示部署：一台机器上两个 Python 进程加一个 docker 里的 PostgreSQL；只有大模型调用出互联网。",
             "演示环境的进程与网络拓扑"))

# A9 报价数据流 -------------------------------------------------------------
d = D("a9", 900, 200)
d.box(20, 20, 170, 40, "供应商甲 18.50 · MOQ 50", cls="ext")
d.box(20, 80, 170, 40, "供应商乙 17.90 · MOQ 100", cls="ext")
d.box(20, 140, 170, 40, "供应商丙 17.90 · 交期 45 天", cls="ext")
d.box(260, 70, 160, 60, "best_offer(part)", ("单价最低，同价取交期短",), cls="soft")
d.arrow([(190, 40), (260, 90)]); d.arrow([(190, 100), (260, 100)]); d.arrow([(190, 160), (260, 110)])
d.box(470, 70, 160, 60, "× (1 + 0.25)", ("Decimal，四舍五入两位",), cls="soft")
d.arrow([(420, 100), (470, 100)], label="17.90（乙）", lx=445, ly=92)
d.box(680, 70, 200, 60, "QuoteLine 22.38 USD", ("qty · margin · offer · 备注",), cls="good")
d.arrow([(630, 100), (680, 100)])
d.text(780, 155, "qty < MOQ 时在备注提示，不阻止", cls="small", anchor="middle")
d.text(780, 172, "导出 xlsx 含图片 · 描述 · 规格 · 包装 · 替代件", cls="small", anchor="middle")
reg("a9", "architecture.html", '<h2 id="s8">8. 关键流程</h2>',
    d.render("图 A9 · 报价怎么算出来：三家报价里选最低成本，乘以目标毛利，得到一条可导出的报价行。",
             "从供应商报价到报价单行的计算流"))

# =====================================================================
# Data dictionary figure
# =====================================================================
d = D("d1", 900, 210)
rows = [("A 000 420 15 20", "A0004201520", "Mercedes 空格分组"), ("81.50201-6229", "81502016229", "MAN 点与横杠"), ("２０４４-3906", "20443906", "全角 + 横杠")]
for i, (raw, norm, note) in enumerate(rows):
    y = 20 + i * 60
    d.box(20, y, 190, 40, raw, cls="ext")
    d.text(115, y + 54, note, cls="small", anchor="middle")
    d.arrow([(210, y + 20), (300, 100)])
    d.arrow([(460, 100), (540, y + 20)])
    d.box(540, y, 170, 40, norm, cls="good")
d.box(300, 70, 160, 60, "normalize_number()", ("NFKC · 去非字母数字 · 大写",), cls="soft")
d.box(760, 70, 120, 60, "number_norm", ("唯一索引 · GIN trigram",))
for i in range(3):
    d.arrow([(710, 40 + i * 60), (760, 100)])
d.text(450, 195, "入库与查询输入走同一个函数，所以客户怎么写都能对上", cls="small", anchor="middle")
reg("d1", "data-dictionary.html", '<div class="tbl"><table>\n<tr><th>#</th><th>脏数据形态</th>',
    d.render("图 D1 · 归一化把不同书写习惯收敛到同一个 number_norm；原文保留在 number 字段供展示。",
             "三种脏编号经归一化后落到同一索引字段"))

# =====================================================================
# Schedule figures
# =====================================================================
# S1 里程碑依赖 DAG
deps = {
    "M01": [], "M02": ["M01"], "M03": ["M01"], "M13": ["M01"],
    "M04": ["M02", "M03"], "M05": ["M04"], "M06": ["M04"], "M09": ["M04"],
    "M07": ["M04", "M06"], "M10": ["M09"], "M12": ["M09"],
    "M08": ["M07"], "M11": ["M10"], "M14": ["M12", "M13", "M10"], "M15": ["M13", "M10"], "M17": ["M13", "M07"],
    "M16": ["M14", "M15"], "M18": ["M08", "M09", "M17"], "M19": ["M15"], "M20": ["M16", "M18", "M19", "M11", "M05"],
}
names = {"M01": "骨架", "M02": "DB · User · CI", "M03": "归一化", "M04": "catalog 模型", "M05": "Admin", "M06": "seed",
         "M07": "匹配", "M08": "搜索页", "M09": "suppliers", "M10": "评分", "M11": "看板", "M12": "上传预览",
         "M13": "LLM 封装", "M14": "映射导入", "M15": "AI 审核", "M16": "批量任务", "M17": "图片询价",
         "M18": "留痕报价", "M19": "导出", "M20": "首页 README"}
opus = {"M03", "M07", "M13", "M14", "M15", "M17"}
depth = {}
def dep_of(m):
    if m in depth: return depth[m]
    depth[m] = 0 if not deps[m] else 1 + max(dep_of(p) for p in deps[m])
    return depth[m]
for m in deps: dep_of(m)
cols = {}
for m in sorted(deps): cols.setdefault(depth[m], []).append(m)
W, H = 980, 360
bw, bh = 96, 40
colx = lambda c: 20 + c * 122
pos = {}
for c, ms in cols.items():
    n = len(ms)
    top = H / 2 - (n * 54) / 2 + 7
    for i, m in enumerate(ms):
        pos[m] = (colx(c), top + i * 54)
d = D("s1", W, H)
for m, ps in deps.items():
    x2, y2 = pos[m]
    for p in ps:
        x1, y1 = pos[p]
        d.arrow([(x1 + bw, y1 + bh / 2), (x2, y2 + bh / 2)])
for m, (x, y) in pos.items():
    d.box(x, y, bw, bh, m, (names[m],), cls="soft" if m in opus else "good", r=6, bold=True)
d.el.append('<rect class="box soft" x="20" y="326" width="14" height="14" rx="3"/>')
d.text(40, 337, "Opus（判断密集）", cls="legend")
d.el.append('<rect class="box good" x="160" y="326" width="14" height="14" rx="3"/>')
d.text(180, 337, "Codex / Sonnet（规格已定）", cls="legend")
d.text(400, 337, "同一列的里程碑互不依赖，可并行或任意顺序", cls="legend")
reg("s1", "schedule.html", '<h2 id="milestones">里程碑明细</h2>',
    d.render("图 S1 · 里程碑依赖图。箭头指向依赖它的里程碑；M13 大模型封装只依赖骨架，可以随时插进来做。",
             "20 个里程碑的依赖关系与推荐模型"))

# S2 里程碑工作循环
d = D("s2", 900, 200)
steps = ["读清单 Mxx", "实现（不越界）", "跑验收命令", "commit + tag + 进度", "停下等审核", "下一个里程碑"]
for i, s in enumerate(steps):
    x = 20 + i * 146
    cls = "soft" if i in (1, 2) else ("good" if i == 5 else "")
    d.box(x, 60, 136, 50, s, cls=cls)
    if i < 5:
        d.arrow([(x + 136, 85), (x + 146, 85)])
d.arrow([(380, 110), (380, 140), (234, 140), (234, 110)], dashed=True, label="失败：修到通过", lx=307, ly=156)
d.arrow([(672, 110), (672, 150), (250, 150), (250, 112)], dashed=True, label="审核有问题：fix(...) 独立提交，不改写历史", lx=465, ly=170)
d.text(760, 40, "每次新增 ≤ 300 行", cls="small", anchor="middle")
reg("s2", "schedule.html", '<h2 id="overview">里程碑总览</h2>',
    d.render("图 S2 · 每个里程碑的工作循环。验收不过不能提交；审核不过用独立的修复提交，历史永远可追溯。",
             "单个里程碑从读清单到审核通过的循环"))


# =====================================================================
# insert
# =====================================================================
def insert_all():
    byfile = {}
    for fid, (file, before, svg) in FIGS.items():
        byfile.setdefault(file, []).append((fid, before, svg))
    for file, items in byfile.items():
        p = DOCS / file
        s = p.read_text(encoding="utf-8")
        for fid, before, svg in items:
            s = re.sub(rf"<!-- fig:{fid} -->.*?<!-- /fig:{fid} -->\n?", "", s, flags=re.S)
        for fid, before, svg in items:
            assert s.count(before) >= 1, (file, fid, before[:40])
            idx = s.index(before)
            s = s[:idx] + svg + "\n" + s[idx:]
        p.write_text(s, encoding="utf-8")
        print(file, [f for f, _, _ in items])


insert_all()
