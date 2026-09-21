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
# 智能搜索详细设计 figures (search-design.html)
# =====================================================================

# Q1 业务价值链 --------------------------------------------------------
d = D("q1", 940, 366)
inputs = [
    ("一个编号", "OE · 互换号 · 竞品号"),
    ("一张照片", "铭牌可能磨损"),
    ("一句话", "brake chamber volvo"),
    ("我方 SKU", "内部料号"),
]
for i, (t, s) in enumerate(inputs):
    d.box(20, 36 + i * 72, 170, 54, t, (s,), cls="ext")
d.box(250, 120, 170, 86, "归一化 + 三级匹配", ("全系统唯一实现", "只查自家数据库"), cls="soft", bold=True)
for i in range(4):
    d.arrow([(190, 63 + i * 72), (250, 163)], hi=(i == 0))
outs = [
    ("产品卡", "图 · 规格 · 适配"),
    ("三家成本 → 建议售价", "成本 × (1 + 毛利)"),
    ("替代件", "共享 OE / 互换号"),
    ("询价留痕", "问了什么 · 命中没有"),
]
for i, (t, s) in enumerate(outs):
    d.box(480, 36 + i * 72, 200, 54, t, (s,), cls="good" if i < 3 else "")
    d.arrow([(420, 163), (480, 63 + i * 72)])
d.box(740, 90, 180, 54, "几秒内回复客户", ("是什么 · 能不能配 · 多少钱",), cls="good", bold=True)
d.arrow([(680, 63), (740, 110)], hi=True)
d.arrow([(680, 135), (740, 120)], hi=True)
d.arrow([(680, 207), (740, 130)], hi=True)
d.box(740, 230, 180, 54, "未命中最多的输入", ("下一批该补什么数据",), cls="warn2")
d.arrow([(680, 279), (740, 260)])
d.arrow([(830, 284), (830, 330), (335, 330), (335, 206)], dashed=True,
        label="补数据 → 下次就能命中", lx=560, ly=346)
reg("q1", "search-design.html", "<!-- fig:q1 -->",
    d.render("图 Q1 · 为什么搜索是核心。四种脏输入收敛成一次匹配，匹配成功后产品卡、价格、替代件都是附属品；"
             "没命中的输入本身也是资产，它告诉你下一批该补什么。",
             "四种客户输入经过匹配后产出产品卡、价格、替代件与询价留痕"))

# Q2 业务链路与人工确认点 -----------------------------------------------
d = D("q2", 940, 430)
d.lane(10, 10, 920, 150, "主链路：从询价到报价")
d.box(30, 60, 130, 56, "客户询价", ("编号 / 照片 / 描述",), cls="ext")
d.box(190, 60, 130, 56, "搜索框", ("或照片上传",))
d.arrow([(160, 88), (190, 88)])
d.box(350, 60, 140, 56, "候选列表", ("带匹配类型与分数",), cls="soft")
d.arrow([(320, 88), (350, 88)])
d.box(520, 60, 130, 56, "人工确认①", ("是不是这个件",), cls="dec")
d.arrow([(490, 88), (520, 88)])
d.box(680, 60, 120, 56, "产品详情", ("成本 · 替代件",), cls="good")
d.arrow([(650, 88), (680, 88)])
d.box(830, 60, 90, 56, "报价单", ("xlsx",), cls="good")
d.arrow([(800, 88), (830, 88)])
d.text(585, 134, "机器只排序，不拍板", cls="small", anchor="middle")

d.lane(10, 180, 450, 230, "没命中：数据反哺")
d.box(30, 230, 130, 50, "询价留痕", ("每次查询一条",))
d.arrow([(420, 116), (420, 205), (95, 205), (95, 230)], dashed=True, label="自动写入", lx=250, ly=201)
d.box(30, 310, 130, 50, "未命中榜", ("近 30 天高频",), cls="warn2")
d.arrow([(95, 280), (95, 310)])
d.box(200, 310, 120, 50, "找货源 / 导入", ("供应商报价单",))
d.arrow([(160, 335), (200, 335)])
d.box(200, 230, 120, 50, "人工确认②", ("列映射 · 预检",), cls="dec")
d.arrow([(260, 310), (260, 280)])
d.box(360, 265, 80, 50, "产品库", cls="good", bold=True)
d.arrow([(320, 255), (360, 280)])
d.arrow([(400, 265), (400, 215), (420, 215), (420, 116)], dashed=True, label="下次命中", lx=330, ly=218, anchor="middle")

d.lane(480, 180, 450, 230, "数据不全：AI 补全")
d.box(500, 230, 130, 50, "缺描述 / 缺分类", ("完整度低",), cls="warn2")
d.box(670, 230, 120, 50, "AI 建议", ("只用公开信息",), cls="soft")
d.arrow([(630, 255), (670, 255)])
d.box(670, 320, 120, 50, "人工确认③", ("逐字段勾选",), cls="dec")
d.arrow([(730, 280), (730, 320)])
d.box(830, 265, 90, 50, "写回产品", ("source=ai",), cls="good")
d.arrow([(790, 345), (850, 345), (850, 315)])
d.arrow([(875, 265), (875, 170), (760, 170), (760, 116)], dashed=True, label="完整度上升", lx=700, ly=166, anchor="end")
reg("q2", "search-design.html", "<!-- fig:q2 -->",
    d.render("图 Q2 · 业务链路。主链路只有五步；黄色菱形是三个人工确认点，系统在这三处都停下来等人。"
             "两条虚线是闭环：没命中的输入变成补数据的清单，补完的数据让下一次命中。",
             "从客户询价到报价的主链路，以及未命中反哺与 AI 补全两条闭环"))

# Q3 搜索请求时序 -------------------------------------------------------
svg = seq("q3",
    [("销售", "", "ext"), ("浏览器", "HTMX", "soft"), ("SearchView", "catalog.views", ""),
     ("matcher", "catalog.services", ""), ("PostgreSQL", "pg_trgm", "ext"), ("留痕", "inquiries", "")],
    [
        (0, 1, "输入 2044-3906（边打边搜）", False),
        (1, 1, "去抖 300ms，只发最后一次", False),
        (1, 2, "GET /search/?q=2044-3906  HX-Request", False),
        (2, 2, "截断到 200 字符", False),
        (2, 3, "search(q)", False),
        (3, 3, "normalize → 20443906 · 判定为编号", False),
        (3, 4, "L1: number_norm = ?  ①", False),
        (4, 3, "命中 1 个产品 → 不再降级", True),
        (3, 2, "Candidate[]（match_type + score）", True),
        (2, 5, "log_text_search(q, 候选)  ②", False),
        (5, 4, "INSERT：query_key 归一 · 记首个候选", False),
        (2, 3, "prefetch_for_cards(候选)", False),
        (3, 4, "编号 · 适配 · 图片 · 报价  ③④⑤⑥", False),
        (4, 3, "四次批量预取，与结果条数无关", True),
        (2, 1, "只返回结果区 HTML 片段", True),
        (1, 0, "卡片：精确 · $22.90 → $28.63 · 替代件", True),
    ],
    phases=[("匹配", 4, 8), ("留痕", 9, 10), ("渲染", 11, 15)],
    caption="图 Q3 · 一次搜索的时序。① 是唯一必需的匹配查询；② 是一条 INSERT，不读库；③–⑥ 是卡片数据的四次批量预取。"
            "加上会话与用户共 9 条 SQL，测试里有预算断言守着。",
    aria="搜索请求从输入去抖到返回 HTML 片段的调用时序")
reg("q3", "search-design.html", "<!-- fig:q3 -->", svg)

# Q4 归一化流水线 -------------------------------------------------------
d = D("q4", 940, 320)
steps = [
    ("① NFKC 规范化", "全角 → 半角"),
    ("② 去非字母数字", "空格 横杠 点 斜杠"),
    ("③ 转大写", "大小写不敏感"),
    ("④ 空结果 = 非编号", "纯中文落到文本检索"),
]
for i, (t, s) in enumerate(steps):
    x = 20 + i * 232
    d.box(x, 30, 212, 54, t, (s,), cls="soft" if i < 3 else "ext")
    if i < 3:
        d.arrow([(x + 212, 57), (x + 232, 57)])
rows = [
    ("A 000 420 15 20", "A 000 420 15 20", "A0004201520", "A0004201520", "Mercedes 原厂号"),
    ("２０４４-3906", "2044-3906", "20443906", "20443906", "全角 + 横杠"),
    ("wg9100470107", "wg9100470107", "wg9100470107", "WG9100470107", "HOWO 小写"),
    ("刹车片", "刹车片", "（空）", "（空）", "→ 文本检索"),
]
d.text(20, 118, "示例", cls="lane-label")
for i, (a, b, c, e, note) in enumerate(rows):
    y = 164 + i * 38
    d.el.append(f'<rect class="lane" x="20" y="{y - 20}" width="900" height="32" rx="6"/>')
    for x, value in ((32, a), (264, b), (496, c), (700, e)):
        d.text(x, y, value, cls="small")
    d.text(830, y, note, cls="small")
d.text(32, 136, "输入", cls="legend")
d.text(264, 136, "① 之后", cls="legend")
d.text(496, 136, "② 之后", cls="legend")
d.text(700, 136, "③ 结果", cls="legend")
reg("q4", "search-design.html", "<!-- fig:q4 -->",
    d.render("图 Q4 · 归一化的四步与逐步结果。同一个函数被模型 save()、导入服务和搜索三处调用，"
             "写入与查询算出来的值才可能相等。",
             "编号归一化的四个步骤以及四个输入的逐步变化"))

# Q5 输入分流决策树 -----------------------------------------------------
d = D("q5", 940, 400)
d.box(20, 30, 150, 48, "搜索框输入", cls="ext")
d.box(220, 30, 220, 48, "有 sku: / oe: / name: 前缀？", cls="dec")
d.arrow([(170, 54), (220, 54)])
d.box(500, 30, 170, 48, "按前缀指定的分支", cls="good")
d.arrow([(440, 54), (500, 54)], label="是", lx=468, ly=47)
d.box(220, 110, 220, 48, "归一化后含数字？", cls="dec")
d.arrow([(330, 78), (330, 110)], label="否", lx=338, ly=96, anchor="start")
d.box(500, 110, 170, 48, "text：文本检索", cls="good")
d.arrow([(440, 134), (500, 134)], label="否", lx=468, ly=127)
d.box(220, 190, 220, 48, "以 FIT- 开头？", cls="dec")
d.arrow([(330, 158), (330, 190)], label="是", lx=338, ly=176, anchor="start")
d.box(500, 190, 170, 48, "sku：料号检索", cls="good")
d.arrow([(440, 214), (500, 214)], label="是", lx=468, ly=207)
d.box(220, 270, 220, 62, "长度 ≥ 5 且字母占比 < 50%？", ("A0004201520 → 是", "BRAKE12 → 否"), cls="dec")
d.arrow([(330, 238), (330, 270)], label="否", lx=338, ly=256, anchor="start")
d.box(500, 270, 170, 48, "number：编号匹配", cls="good", bold=True)
d.arrow([(440, 294), (500, 294)], label="是", lx=468, ly=287)
d.arrow([(330, 332), (330, 368), (700, 368), (700, 134), (670, 134)],
        label="否 → 落回 text 分支", lx=470, ly=386)
d.box(710, 150, 210, 110, "oe: 的真实语义", ("= 强制按编号查，", "不限定 kind=OE。", "客户并不知道手里的号", "属于 OE 还是互换号。"), cls="ext")
reg("q5", "search-design.html", "<!-- fig:q5 -->",
    d.render("图 Q5 · 输入分流的判定顺序，从上到下短路。字母占比这一条把 BRAKE12 这类"
             "带数字的英文词挡在编号分支之外。",
             "搜索输入被判定为 sku、number 或 text 的决策树"))

# Q6 三级匹配总流程 -----------------------------------------------------
d = D("q6", 960, 512)
d.box(20, 24, 150, 44, "归一化后的编号", cls="ext")
d.box(220, 20, 260, 52, "L1 精确 / 归一化", ("number_norm = ? 一条索引查询",), cls="soft", bold=True)
d.arrow([(170, 46), (220, 46)])
d.box(540, 20, 200, 52, "命中唯一一个产品？", cls="dec")
d.arrow([(480, 46), (540, 46)])
d.box(790, 20, 150, 52, "直接返回", ("最常见的情形",), cls="good", bold=True)
d.arrow([(740, 46), (790, 46)], label="是", hi=True, lx=762, ly=39)
d.box(220, 130, 260, 62, "L2 前缀 / 包含", ("双向 contains，长度 ≥ 5", "0.8 × 短/长",), cls="soft")
d.arrow([(640, 72), (640, 104), (350, 104), (350, 130)], label="否（0 个或多个）", lx=500, ly=100)
d.box(540, 130, 200, 62, "候选已满 20 条？", cls="dec")
d.arrow([(480, 161), (540, 161)])
d.box(220, 250, 260, 62, "L3 模糊", ("pg_trgm ≥ 0.45", "少于 3 字符直接跳过",), cls="soft")
d.arrow([(640, 192), (640, 224), (350, 224), (350, 250)], label="否", lx=500, ly=220)
d.box(790, 130, 150, 182, "合并", ("① 同一产品", "只留最佳候选", "② 按四层排序键", "③ 截断到 20 条"), cls="good", bold=True)
d.arrow([(740, 161), (790, 190)], label="是", lx=760, ly=152)
d.arrow([(480, 281), (790, 281)])
d.box(20, 326, 900, 36, "命中多个产品时反而要继续降级：说明这个号挂在几个 SKU 上，销售需要更多线索来挑",
      cls="ext", r=6)
d.text(20, 392, "不走三级的两条分支（同样产出 Candidate，走同一套合并与排序）", cls="lane-label")
d.box(20, 402, 260, 62, "text 分支", ("token AND + 品牌别名", "全不中再 trigram 兜错拼写"), cls="")
d.box(320, 402, 220, 62, "sku 分支", ("iexact 命中即返回", "否则 istartswith 列出"), cls="")
d.arrow([(150, 464), (150, 486), (860, 486), (860, 312)], dashed=True)
d.arrow([(430, 464), (430, 486)], dashed=True, noarrow=True)
reg("q6", "search-design.html", "<!-- fig:q6 -->",
    d.render("图 Q6 · 三级匹配的短路与降级。绿色是出口；只有\"候选不够\"才会进入下一级，"
             "所以 90% 的查询只花一条索引查询。",
             "三级匹配的流程、短路条件与合并排序"))

# Q7 L2 双向包含与打分 --------------------------------------------------
d = D("q7", 940, 280)
d.text(20, 30, "方向一：库里的编号带后缀 / 前缀", cls="lane-label")
d.box(20, 44, 200, 46, "查询 20443906", ("8 位",), cls="ext")
d.box(260, 44, 220, 46, "库里 20443906-1", ("归一化 204439061 · 9 位",), cls="soft")
d.arrow([(220, 67), (260, 67)], label="被包含", lx=240, ly=38)
d.box(520, 44, 180, 46, "0.8 × 8 / 9 = 0.71", cls="good")
d.arrow([(480, 67), (520, 67)])
d.text(20, 130, "方向二：客户把品牌和编号连在一起", cls="lane-label")
d.box(20, 144, 200, 46, "查询 VOLVO20443906", ("13 位",), cls="ext")
d.box(260, 144, 220, 46, "库里 20443906", ("8 位",), cls="soft")
d.arrow([(220, 167), (260, 167)], label="包含它", lx=240, ly=138)
d.box(520, 144, 180, 46, "0.8 × 8 / 13 = 0.49", cls="good")
d.arrow([(480, 167), (520, 167)])
d.box(730, 44, 190, 146, "安全阀", ("MIN_CONTAINED_LEN = 5", "", "库里短于 5 位的编号", "不参与\"被包含\"判断，", "否则一个 123 会命中", "几乎所有查询。"), cls="warn2")
d.box(20, 226, 680, 36, "打分用长度比而不是常数：多一位后缀的候选，一定排在多五位的前面", cls="ext", r=6)
reg("q7", "search-design.html", "<!-- fig:q7 -->",
    d.render("图 Q7 · L2 的双向包含与打分。分数越接近 0.8，说明两个编号长度越接近、越可能是同一个件的变体。",
             "前缀包含匹配的两个方向、打分公式与最小长度安全阀"))

# Q8 两个数据库的模糊实现 ----------------------------------------------
d = D("q8", 940, 300)
d.lane(10, 10, 450, 270, "PostgreSQL：数据库算")
d.box(30, 50, 180, 46, "GIN trigram 索引", ("gin_trgm_ops",), cls="good")
d.box(30, 120, 180, 46, "trigram_similar 预筛", ("索引扫描，筛掉绝大多数",), cls="soft")
d.arrow([(120, 96), (120, 120)])
d.box(30, 190, 180, 46, "similarity ≥ 0.45", ("SQL 内排序",), cls="soft")
d.arrow([(120, 166), (120, 190)])
d.box(250, 120, 190, 116, "为什么是 0.45", ("7–8 位编号：", "错一位 ≈ 0.45–0.55", "错两位 < 0.3", "", "阈值取\"错一位\"的下沿"), cls="ext")
d.arrow([(210, 213), (250, 190)], noarrow=True, dashed=True)
d.lane(480, 10, 450, 270, "SQLite 回退：Python 算")
d.box(500, 50, 190, 46, "首 3 位或末 3 位取池", ("上限 2000 行",), cls="warn2")
d.box(500, 120, 190, 46, "difflib 逐个打分", ("SequenceMatcher",), cls="soft")
d.arrow([(595, 96), (595, 120)])
d.box(500, 190, 190, 46, "ratio ≥ 0.75", ("阈值必须单独量",), cls="soft")
d.arrow([(595, 166), (595, 190)])
d.box(730, 120, 190, 116, "为什么不能共用阈值", ("difflib 与 trigram 的", "分数分布不同：", "同一对编号，difflib", "普遍给得更高。", "两个库都跑同一套测试。"), cls="ext")
d.arrow([(690, 213), (730, 190)], noarrow=True, dashed=True)
reg("q8", "search-design.html", "<!-- fig:q8 -->",
    d.render("图 Q8 · 模糊匹配的两条实现。左边是生产路径，右边是没有 docker 时的演示路径；"
             "两条路径的阈值分别量过，测试在两个库上都跑。",
             "PostgreSQL 与 SQLite 两种模糊匹配实现的对比")) 

# Q9 文本检索两段式 -----------------------------------------------------
d = D("q9", 940, 340)
d.box(20, 30, 200, 46, "brake chamber volvo", ("按空格切成 3 个 token",), cls="ext")
d.box(270, 30, 200, 46, "品牌别名归一", ("沃尔沃 / benz / howo → 标准名",), cls="soft")
d.arrow([(220, 53), (270, 53)])
d.box(520, 20, 400, 66, "每个 token 都必须命中（AND）", ("品名 · 中文名 · 分类名 · 分类英文名 · 车系 · 品牌",), cls="soft", bold=True)
d.arrow([(470, 53), (520, 53)])
d.box(520, 120, 200, 46, "有结果？", cls="dec")
d.arrow([(720, 86), (720, 110), (620, 110), (620, 120)])
d.box(780, 120, 140, 46, "name  0.7", ("字面命中",), cls="good")
d.arrow([(720, 143), (780, 143)], label="是", lx=742, ly=136)
d.box(520, 200, 400, 62, "TrigramWordSimilarity(name_en) ≥ 0.3", ("多半是拼错：brake chambr",), cls="warn2")
d.arrow([(620, 166), (620, 200)], label="否", lx=628, ly=186, anchor="start")
d.box(520, 280, 400, 40, "分数 = 0.6 × 相似度 → 排序上必定落在字面命中之后", cls="ext", r=6)
d.arrow([(720, 262), (720, 280)])
d.box(20, 120, 200, 142, "为什么是 AND", ("三个词都是筛选条件。", "用 OR 会把所有刹车件", "都倒出来，销售还得", "自己翻——那等于没搜。"), cls="ext")
reg("q9", "search-design.html", "<!-- fig:q9 -->",
    d.render("图 Q9 · 没有编号时的两段式文本检索。先字面 AND，全不中才用 trigram 兜错拼写，"
             "并且分数打折，保证它排在确定性结果之后。",
             "文本检索的 token AND 过滤与错拼回退两段流程"))

# Q10 排序键 ------------------------------------------------------------
d = D("q10", 940, 330)
layers = [
    ("① 匹配类型", "精确 0 < 归一化 1 < 前缀 2 < 模糊 3 < 名称 4", "soft"),
    ("② 分数降序", "同类型内，相似度高的在前", "soft"),
    ("③ 完整度降序", "同样可信时，资料全的销售更愿意直接用", "good"),
    ("④ SKU 升序", "兜底：顺序确定，测试可断言", ""),
]
for i, (t, s, cls) in enumerate(layers):
    w = 560 - i * 60
    d.box(20 + i * 30, 30 + i * 54, w, 44, f"{t}　{s}", cls=cls)
d.text(20, 260, "示例：同一个号挂在三个产品上", cls="lane-label")
d.text(32, 285, "精确 1.00 · 完整度 45　→　归一化 0.95 · 完整度 90　→　模糊 0.62 · 完整度 100", cls="small")
d.text(32, 305, "匹配类型永远优先于完整度：可信度比资料齐全更重要", cls="legend")
d.box(620, 30, 300, 190, "去重在排序之前", ("一个产品可能挂 5 个 OE 号，", "同时被精确和模糊命中。", "", "_best_per_part() 按同一个", "排序键为每个产品只留一条，", "否则列表里会出现 5 次", "同一个 SKU。"), cls="ext")
reg("q10", "search-design.html", "<!-- fig:q10 -->",
    d.render("图 Q10 · 四层排序键。前两层是可信度，第三层是业务判断，第四层保证顺序确定。",
             "候选排序的四层键与按产品去重的说明"))

# Q11 数据流转与查询预算 ------------------------------------------------
d = D("q11", 960, 440)
d.box(20, 40, 140, 56, "浏览器", ("input 去抖 300ms",), cls="ext")
d.box(210, 40, 160, 56, "SearchView", ("截断 200 字符",), cls="soft")
d.arrow([(160, 68), (210, 68)], label="GET ?q=", lx=185, ly=34)
d.box(420, 30, 170, 76, "matcher.search()", ("normalize", "分流", "三级匹配"), cls="soft", bold=True)
d.arrow([(370, 68), (420, 68)])
d.box(650, 20, 130, 46, "PartNumber", ("B-tree + GIN",), cls="ext")
d.box(650, 80, 130, 46, "Part", ("name_en GIN",), cls="ext")
d.arrow([(590, 50), (650, 43)], label="①", lx=620, ly=30)
d.arrow([(590, 86), (650, 103)], label="文本分支", lx=620, ly=120)
d.box(420, 150, 170, 56, "Candidate[]", ("内存对象，最多 20",), cls="good")
d.arrow([(505, 106), (505, 150)])
d.box(650, 150, 270, 56, "prefetch_for_cards()", ("编号 ③· 适配 ④· 图片 ⑤· 报价 ⑥",), cls="soft")
d.arrow([(590, 178), (650, 178)])
d.text(785, 218, "固定 4 条，与结果条数无关", cls="small", anchor="middle")
d.box(210, 250, 170, 56, "log_text_search()", ("一条 INSERT ②",), cls="")
d.arrow([(420, 178), (300, 178), (300, 250)], dashed=True, label="返回前留痕", lx=310, ly=222, anchor="start")
d.box(420, 250, 170, 56, "结果区模板", ("part_card.html",), cls="soft")
d.arrow([(505, 206), (505, 250)])
d.box(20, 250, 140, 56, "HTML 片段", ("只替换 #results",), cls="good", bold=True)
d.arrow([(505, 306), (505, 330), (90, 330), (90, 306)], hi=True)
d.box(20, 350, 900, 66, "查询预算：会话 ⑦ + 用户 ⑧ + 匹配 ①（1–3 条，三级各跑一条）+ 卡片 ③④⑤⑥ + 留痕 ②",
      ("典型 8 条 · 三级全跑 10 条 · 测试断言 with django_assert_max_num_queries(9)",), cls="ext", r=6)
reg("q11", "search-design.html", "<!-- fig:q11 -->",
    d.render("图 Q11 · 数据流转与查询预算。圈号是 SQL；卡片数据靠批量预取保持固定条数，"
             "所以结果从 1 条变成 20 条，查询数不变。",
             "一次搜索请求中数据在视图、服务、数据库与模板之间的流动与 SQL 条数"))

# Q12 匹配能力的复用 ----------------------------------------------------
d = D("q12", 940, 310)
d.box(370, 20, 200, 50, "normalize_number()", ("纯函数，无模型依赖",), cls="soft", bold=True)
consumers = [
    ("模型 save()", "入库即算好"),
    ("导入服务", "一格多号先拆"),
    ("matcher.search()", "三级匹配"),
    ("alternatives()", "详情页 · 报价单替代件列"),
]
for i, (t, sub) in enumerate(consumers):
    x = 20 + i * 230
    cls = "soft" if i == 2 else ("good" if i == 3 else "")
    d.box(x, 110, 200, 50, t, (sub,), cls=cls, bold=(i >= 2))
    d.arrow([(470, 70), (x + 100, 110)], dashed=True)
d.box(330, 215, 200, 50, "搜索页", ("文字查询",), cls="good")
d.box(560, 215, 260, 50, "图片询价", ("把读到的编号拼成 oe:<号> 再查",), cls="good")
d.arrow([(430, 215), (560, 160)])
d.arrow([(690, 215), (620, 160)], hi=True)
d.text(470, 292, "视觉模型读出的编号一律回到 search() 检索：库里没有的号，匹配不出任何候选",
       cls="small", anchor="middle")
reg("q12", "search-design.html", "<!-- fig:q12 -->",
    d.render("图 Q12 · 写成纯服务的回报。归一化被四处共用（写入两处、查询两处），"
             "匹配又被搜索页与图片询价共用，替代件复用同一套编号关系。",
             "归一化与匹配服务在系统中的复用关系"))

# =====================================================================
# 可追溯归档与归一化 figures (archive-design.html)
# =====================================================================

# R1 三层数据模型 ------------------------------------------------------
d = D("r1", 960, 430)
d.lane(10, 10, 220, 340, "原件（只读）")
d.lane(245, 10, 320, 340, "资料层 apps/sources · 只增不改")
d.lane(580, 10, 370, 340, "归一层 apps/archive · 每次变化都来自人")
d.box(30, 80, 180, 96, "SourceFile", ("sha256 · 原文件名", "xlsx / csv / pdf", "解析失败也保留原件"), cls="ext", bold=True)
d.box(30, 230, 180, 50, "Supplier", ("第一阶段已有",), cls="ext")
d.box(265, 60, 280, 124, "SourceRecord", ("record_key · version · previous（版本链）", "定位 sheet / row / page / table",
      "raw · cells · fields（字段出处）", "品类 位置 适配 尺寸 价格 币种…"), cls="soft", bold=True)
d.arrow([(210, 128), (265, 128)], label="1 : N", lx=237, ly=120)
d.arrow([(545, 88), (558, 88), (558, 150), (545, 150)], dashed=True)
d.box(265, 220, 130, 60, "RecordNumber", ("料号 · OE · 源 ID", "number_norm"))
d.arrow([(330, 184), (330, 220)])
d.box(415, 220, 130, 60, "MappingTemplate", ("供应商列映射模板",))
d.arrow([(120, 280), (120, 310), (480, 310), (480, 280)], label="确认一次，下次复用", lx=300, ly=326)
d.box(600, 60, 170, 72, "Product", ("P-00001", "待核 / 已确认归一 / 已确认独立"), cls="good", bold=True)
d.box(600, 168, 170, 66, "Membership", ("供应商 + record_key", "current_record → 最新版本", "有效 / 暂停"), cls="good")
d.arrow([(685, 168), (685, 132)])
d.arrow([(600, 201), (545, 160)])
d.box(790, 60, 150, 124, "ReviewItem", ("record_a / record_b", "触发原因 · 冲突 · 缺失", "建议动作", "evidence_hash"), cls="dec", bold=True)
d.arrow([(865, 60), (865, 44), (405, 44), (405, 60)])
d.box(790, 220, 150, 62, "DecisionLog", ("谁 · 何时 · 为什么", "只增不删"))
d.arrow([(865, 220), (865, 184)])
d.box(600, 268, 170, 50, "FieldChoice", ("冲突字段由人选值",))
d.arrow([(770, 293), (780, 293), (780, 96), (770, 96)], dashed=True)
d.box(10, 366, 555, 40, "左边：资料说了什么——写入后不再修改，更新即新版本", cls="ext", r=6)
d.box(580, 366, 370, 40, "右边：我们认为它是什么——只因人的决定而变", cls="ext", r=6)
reg("r1", "archive-design.html", "<!-- fig:r1 -->",
    d.render("图 R1 · 三层数据模型。原件与资料层只增不改；归一层的每一次变化都能在 DecisionLog 里找到是谁、为什么。"
             "成员关系挂在\"供应商 + 记录身份\"上，所以供应商更新报价不会打散已确认的归一。",
             "原件、资料层、归一层三层数据模型及其关系"))

# R2 处理流程 ----------------------------------------------------------
d = D("r2", 960, 330)
row1 = [("① 上传留存", "sha256 · uuid 路径"), ("② 解析定位", "Excel 单元格 · PDF 页表行"),
        ("③ 列映射", "模板 → 同义词 → AI → 人"), ("④ 标准化", "每个字段带出处与警告"),
        ("⑤ 预检", "版本对比，不写库")]
human = {2}
for i, (t, s) in enumerate(row1):
    x = 20 + i * 188
    d.box(x, 40, 168, 60, t, (s,), cls="dec" if i in human else "soft", bold=True)
    if i < 4:
        d.arrow([(x + 168, 70), (x + 188, 70)])
row2 = [("⑥ 入库", "人确认后一个事务"), ("⑦ 匹配", "召回 · 比对 · 不改产品"),
        ("⑧ 人工复核", "合并 · 判不同 · 待补充 · 移出"), ("⑨ 查询与导出", "产品页带出处 · 三份 xlsx")]
for i, (t, s) in enumerate(row2):
    x = 20 + i * 236
    d.box(x, 190, 212, 60, t, (s,), cls="dec" if i in (0, 2) else ("good" if i == 3 else "soft"), bold=True)
    if i < 3:
        d.arrow([(x + 212, 220), (x + 236, 220)])
d.arrow([(846, 100), (846, 140), (126, 140), (126, 190)])
d.arrow([(682, 250), (682, 280), (362, 280), (362, 250)], dashed=True, label="证据变化 / 规则调整 → 重新匹配", lx=522, ly=298)
d.el.append('<rect class="box dec" x="20" y="306" width="14" height="14" rx="3"/>')
d.text(40, 317, "黄色：需要人参与的步骤", cls="legend")
d.text(260, 317, "失败不丢原件：解析失败的文件保留原件与原因", cls="legend")
reg("r2", "archive-design.html", "<!-- fig:r2 -->",
    d.render("图 R2 · 处理流程。系统负责留存、解析、标准化、对比和把证据摆清楚；映射确认、入库确认、归一决定都要人来做。",
             "从上传到导出的九步处理流程，标出人工参与的步骤"))

# R3 匹配判定 ----------------------------------------------------------
d = D("r3", 960, 470)
d.box(20, 30, 160, 48, "候选对", ("共享 OE · 同品类同车型 · 同源",), cls="ext")
d.box(230, 30, 150, 48, "品类相同？", cls="dec")
d.arrow([(180, 54), (230, 54)])
d.box(230, 120, 150, 48, "共享 OE？", cls="dec")
d.arrow([(305, 78), (305, 120)], label="否", lx=312, ly=103, anchor="start")
d.box(20, 120, 160, 48, "编号冲突", ("OE 录错或一号多品",), cls="bad2", bold=True)
d.arrow([(230, 144), (180, 144)], label="是", lx=205, ly=137)
d.box(230, 210, 150, 48, "不成对", ("只在记录页提示",), cls="ext")
d.arrow([(305, 168), (305, 210)], label="否", lx=312, ly=193, anchor="start")
d.box(440, 30, 150, 48, "左右相同？", cls="dec")
d.arrow([(380, 54), (440, 54)], label="是", lx=410, ly=47)
d.box(440, 120, 150, 48, "位置冲突", ("仅在共享 OE 时；否则不成对",), cls="bad2", bold=True)
d.arrow([(515, 78), (515, 120)], label="否", lx=522, ly=103, anchor="start")
d.box(650, 30, 150, 48, "关键字段有缺失？", cls="dec")
d.arrow([(590, 54), (650, 54)], label="是", lx=620, ly=47)
d.box(820, 30, 120, 48, "信息不足", ("补充后重配",), cls="warn2", bold=True)
d.arrow([(800, 54), (820, 54)], label="是", lx=810, ly=47)
d.box(650, 120, 150, 48, "适配与尺寸一致？", cls="dec")
d.arrow([(725, 78), (725, 120)], label="否", lx=732, ly=103, anchor="start")
d.box(820, 120, 120, 48, "不同产品", ("共享 OE 时为冲突",), cls="bad2")
d.arrow([(800, 144), (820, 144)], label="否", lx=810, ly=137)
d.box(650, 210, 150, 48, "共享 OE？", cls="dec")
d.arrow([(725, 168), (725, 210)], label="是", lx=732, ly=193, anchor="start")
d.box(820, 210, 120, 48, "强证据", ("疑似同一产品",), cls="good", bold=True)
d.arrow([(800, 234), (820, 234)], label="是", lx=810, ly=227)
d.box(650, 300, 150, 48, "同一供应商？", cls="dec")
d.arrow([(725, 258), (725, 300)], label="否", lx=732, ly=283, anchor="start")
d.box(820, 300, 120, 48, "同源重复", ("问供应商",), cls="warn2", bold=True)
d.arrow([(800, 324), (820, 324)], label="是", lx=810, ly=317)
d.box(440, 300, 150, 48, "无编号佐证", ("索取 OE / 图片",), cls="soft", bold=True)
d.arrow([(650, 324), (590, 324)], label="否", lx=620, ly=317)
d.box(20, 382, 920, 66, "所有类别 → 待确认条目：写明触发原因、一致字段、冲突字段（两边取值与出处）、缺失字段、建议动作。没有任何分支会自动合并。",
      ("另：左右一致之后先看编号——两边都带 OE 号但没有一个相同，视为不同产品，不成对。",), cls="ext", r=6)
reg("r3", "archive-design.html", "<!-- fig:r3 -->",
    d.render("图 R3 · 一对候选记录的判定顺序。品类与左右是硬冲突，最先判断；缺失字段排在\"是否一致\"之前，"
             "因为信息不全时下\"一致\"或\"不一致\"的结论都不可靠。",
             "候选记录对按品类、位置、缺失、适配尺寸、编号依次判定的决策树"))

# R4 复核状态与回写 ----------------------------------------------------
d = D("r4", 960, 350)
d.lane(10, 10, 940, 150, "待确认条目 ReviewItem")
d.box(30, 60, 130, 50, "未决", ("open",), cls="dec", bold=True)
outs = [("确认同一", "same"), ("判为不同", "different"), ("确认独立", "independent"), ("待补充", "needs_info")]
for i, (t, s) in enumerate(outs):
    x = 230 + i * 150
    d.box(x, 60, 130, 50, t, (s,), cls="good" if i == 0 else "")
    d.arrow([(160, 85), (x, 85)] if i == 0 else [(160, 85), (195, 85), (195, 130), (x + 65, 130), (x + 65, 110)])
d.box(830, 60, 110, 50, "证据已变化", ("重新打开",), cls="warn2")
d.arrow([(885, 60), (885, 34), (95, 34), (95, 60)], dashed=True, label="evidence_hash 改变 → 回到未决", lx=490, ly=28)
d.lane(10, 180, 940, 150, "归一产品 Product")
d.box(30, 230, 150, 56, "待核", ("每条新记录自成一个",), cls="soft", bold=True)
d.box(330, 230, 170, 56, "已确认归一", ("≥ 2 条成员",), cls="good", bold=True)
d.box(640, 230, 150, 56, "已确认独立", cls="good")
d.arrow([(180, 250), (330, 250)], label="确认同一：合并", lx=255, ly=243)
d.arrow([(330, 270), (180, 270)], dashed=True, label="移出：撤销合并", lx=255, ly=290)
d.arrow([(180, 300), (180, 316), (715, 316), (715, 286)], label="确认独立", lx=450, ly=312)
d.arrow([(295, 110), (295, 160), (415, 160), (415, 230)], dashed=True, noarrow=True)
d.box(820, 225, 120, 66, "DecisionLog", ("每个动作一条", "只增不删"), cls="ext")
reg("r4", "archive-design.html", "<!-- fig:r4 -->",
    d.render("图 R4 · 条目状态与产品状态。上排是人对一个条目的决定，下排是它对产品的影响；合并可以撤销，"
             "证据变化会把已决条目重新打开。",
             "待确认条目的状态流转与归一产品状态的对应关系"))

# R5 增量导入 ----------------------------------------------------------
d = D("r5", 960, 330)
d.box(20, 40, 170, 56, "新文件的一行", ("供应商 + record_key",), cls="ext")
d.box(240, 40, 170, 56, "这个身份见过？", cls="dec")
d.arrow([(190, 68), (240, 68)])
d.box(240, 150, 170, 56, "新增", ("自成待核产品 · 参与匹配",), cls="good", bold=True)
d.arrow([(325, 96), (325, 150)], label="否", lx=333, ly=128, anchor="start")
d.box(460, 40, 170, 56, "内容哈希相同？", cls="dec")
d.arrow([(410, 68), (460, 68)], label="是", lx=435, ly=61)
d.box(460, 150, 170, 56, "未变", ("不建新版本",), cls="")
d.arrow([(545, 96), (545, 150)], label="是", lx=553, ly=128, anchor="start")
d.box(680, 40, 260, 56, "只有价格 / 币种 / MOQ / 日期变了？", cls="dec")
d.arrow([(630, 68), (680, 68)], label="否", lx=655, ly=61)
d.box(680, 150, 120, 56, "报价更新", ("新版本 · 成员延续",), cls="good", bold=True)
d.arrow([(740, 96), (740, 150)], label="是", lx=748, ly=128, anchor="start")
d.box(820, 150, 120, 56, "关键字段变化", ("暂停成员 · 复核",), cls="bad2", bold=True)
d.arrow([(880, 96), (880, 150)], label="否", lx=888, ly=128, anchor="start")
d.box(20, 250, 390, 50, "上一版文件有、这次没有 → 本次未出现（只提示，不删除）", cls="ext", r=6)
d.box(460, 250, 480, 50, "预检逐行列出结果与字段差异（旧值 → 新值），人确认后才入库", cls="ext", r=6)
reg("r5", "archive-design.html", "<!-- fig:r5 -->",
    d.render("图 R5 · 增量导入的版本对比。\"更新\"分两种：只动报价的延续原有归一，动了关键字段的必须重新交人确认。",
             "新资料中每一行按身份、内容哈希、变化字段判定为新增、未变、报价更新或关键字段变化"))

# R6 字段出处链 --------------------------------------------------------
d = D("r6", 960, 250)
chain = [
    ("产品页上的一个值", ("尺寸 122 × 75 × 7 cm",), "good"),
    ("Membership", ("供应商 A · 记录 A-xxx",), ""),
    ("SourceRecord v2", ("fields.dims", "规则 dims_lxwxh"), "soft"),
    ("单元格", ("工作表 Sheet1 · G2", "原文 \"122 x 75 x 7 cm\""), "soft"),
    ("SourceFile", ("原件下载 · sha256",), "ext"),
]
for i, (t, sub, cls) in enumerate(chain):
    x = 20 + i * 188
    d.box(x, 40, 168, 70, t, sub, cls=cls, bold=True)
    if i < 4:
        d.arrow([(x + 168, 75), (x + 188, 75)], hi=True)
d.box(584, 150, 168, 56, "PDF 时", ("第 3 页 · 表 1 · 第 5 行",), cls="soft")
d.arrow([(668, 110), (668, 150)], dashed=True)
d.box(20, 150, 540, 56, "成员之间取值不同时",
      ("各个值带出处并排展示、冲突标红；由人选定展示值（FieldChoice）并写明依据",), cls="warn2", r=6)
reg("r6", "archive-design.html", "<!-- fig:r6 -->",
    d.render("图 R6 · 从产品页的一个值，一路点回原件的那个单元格。大模型不参与取值，所以每个值都有确定的出处。",
             "产品页的字段值经成员关系、来源记录、单元格追溯到原始文件"))

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
