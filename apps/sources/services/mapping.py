"""Column mapping for source files (docs/archive-design.html §5 step 3).

Order of evidence: the supplier's confirmed template, the synonym table, then
a model suggestion for headers nothing else recognised. A person confirms every
mapping before any record is extracted.
"""

import hashlib
import re
import unicodedata

from pydantic import BaseModel, Field, field_validator

from ..models import MappingTemplate

FIELDS = {
    "record_id": "源记录 ID",
    "supplier_sku": "供应商料号 / 品牌号",
    "brand": "零件品牌",
    "oe_numbers": "OE / 互换号",
    "name": "产品名称",
    "category": "品类",
    "fitment": "适配车型（整句）",
    "make": "适配品牌",
    "model": "适配车型",
    "years": "适配年份",
    "position": "安装位置",
    "dims": "尺寸 / 包装尺寸",
    "spec": "其他规格",
    "price": "单价",
    "currency": "币种",
    "moq": "起订量",
    "quote_date": "报价日期",
    "note": "备注",
    "ignore": "忽略此列",
}
MULTI_COLUMN = {"oe_numbers", "spec", "note", "ignore"}  # may be chosen for several columns
IDENTITY_FIELDS = ("record_id", "supplier_sku")  # what lets a re-sent file be recognised
SAMPLE_ROWS = 3  # rows shown to the model: headers plus three sample rows, nothing else

SYNONYMS = {
    "record_id": ["source record id", "source ref", "source id", "record id", "record no",
                  "line no", "row id", "序号", "记录号", "行号"],
    "supplier_sku": ["supplier sku", "sku", "brand number", "brand no", "part no", "part number",
                     "p/n", "pn", "item no", "item number", "vendor part no", "vendor part number",
                     "supplier part no", "mfr part no", "manufacturer part number", "catalog no",
                     "catalog number", "model no", "货号", "料号", "供应商料号", "产品编号"],
    "brand": ["brand", "part brand", "manufacturer", "mfr", "mfg", "品牌", "生产商", "厂家"],
    "oe_numbers": ["oe", "oe no", "oe number", "oem", "oem no", "oem number", "oe reference",
                   "oe ref", "cross ref", "cross reference", "cross", "reference", "ref", "ref no",
                   "interchange", "interchange no", "replaces", "original no", "genuine no",
                   "原厂号", "oe号", "互换号", "替代号", "参考号"],
    "name": ["product description", "description", "desc", "english name", "product name",
             "name", "item description", "part name", "part description", "title",
             "品名", "名称", "英文品名", "产品名称", "描述"],
    "category": ["category", "product category", "type", "product type", "group",
                 "product line", "分类", "类别", "品类"],
    "fitment": ["truck application", "application", "applications", "fitment", "fits",
                "vehicle", "vehicle application", "compatible models", "适用车型", "适配车型",
                "适配", "适用", "车型"],
    "make": ["make", "vehicle make", "truck make", "整车品牌", "车辆品牌"],
    "model": ["model", "vehicle model", "truck model", "series", "车系"],
    "years": ["year", "years", "year range", "model year", "model years", "年份", "年款"],
    "position": ["position", "install side", "side", "location", "mounting position",
                 "placement", "安装位置", "位置", "左右"],
    "dims": ["package size", "package", "package dimensions", "pkg size", "dimensions",
             "dimension", "size", "l x w x h", "carton size", "box size", "尺寸", "包装尺寸",
             "外箱尺寸"],
    "spec": ["specification", "specifications", "spec", "specs", "material", "color", "colour",
             "finish", "weight", "规格", "材质", "颜色"],
    "price": ["unit price", "price", "offer price", "cost", "unit cost", "fob", "fob price",
              "exw price", "net price", "list price", "quote price", "单价", "价格", "报价"],
    "currency": ["currency", "curr", "cur", "ccy", "币种", "货币"],
    "moq": ["moq", "min order", "minimum order", "min qty", "min order qty",
            "minimum order quantity", "起订量", "最小起订量"],
    "quote_date": ["quote date", "quoted on", "quotation date", "date", "price date",
                   "valid from", "报价日期", "日期"],
    "note": ["note", "notes", "remark", "remarks", "comment", "comments", "备注", "说明"],
}
# Units or currencies that may trail a synonym without changing it: "Unit Price (EUR)".
_UNIT_SUFFIXES = {"usd", "eur", "gbp", "cny", "rmb", "kg", "kgs", "lb", "lbs", "cm", "mm",
                  "in", "inch", "pcs", "pc"}
_SEPARATORS = re.compile(r"[\s._\-/()（）:：&+*,，]+")


def header_key(text: str) -> str:
    """"Part #" -> "partno"; "Unit Price (EUR)" -> "unitpriceeur"; "OE / Ref" -> "oeref"."""
    text = unicodedata.normalize("NFKC", text).casefold().replace("#", " no ")
    return _SEPARATORS.sub("", text)


_EXACT = {header_key(s): f for f, synonyms in SYNONYMS.items() for s in synonyms}
_BY_LENGTH = sorted(_EXACT.items(), key=lambda kv: -len(kv[0]))


def match_synonym(header: str) -> tuple[str, float] | None:
    key = header_key(header)
    if key in _EXACT:
        return _EXACT[key], 1.0
    for synonym, field in _BY_LENGTH:
        if len(synonym) >= 3 and key.startswith(synonym) and key[len(synonym):] in _UNIT_SUFFIXES:
            return field, 0.9
    return None


def header_signature(headers: list[str]) -> str:
    """Same headers in any order give the same signature."""
    keys = sorted(header_key(h) for h in headers)
    return hashlib.sha256("\x1f".join(keys).encode()).hexdigest()


def suggest(headers: list[str], sample_rows: list[dict], supplier, *, client=None) -> list[dict]:
    """One suggestion per header, in header order:
    {"header", "field", "source": template|synonym|ai|none, "confidence", "reason"}."""
    template = MappingTemplate.objects.filter(
        supplier=supplier, header_signature=header_signature(headers)
    ).first()
    if template:
        by_header = {c["header"]: c["field"] for c in template.columns}
        reason = f"沿用 {template.updated_at:%Y-%m-%d} 人工确认的映射"
        return [_item(h, by_header.get(h, "ignore"), "template", 1.0, reason) for h in headers]

    found, unknown = {}, []
    for header in headers:
        hit = match_synonym(header)
        if hit:
            found[header] = _item(header, hit[0], "synonym", hit[1], "同义词表")
        else:
            unknown.append(header)
    if unknown:
        found |= _ask_model(unknown, sample_rows, client)
    return [found[h] for h in headers]


def validate(columns: list[dict]) -> tuple[list[str], list[str]]:
    """(errors, warnings) for a mapping a person is about to confirm."""
    errors, warnings = [], []
    used: dict[str, list[str]] = {}
    for column in columns:
        used.setdefault(column["field"], []).append(column["header"])
    for field, headers in used.items():
        if field not in FIELDS:
            errors.append(f"未知字段：{field}")
        elif field not in MULTI_COLUMN and len(headers) > 1:
            errors.append(f"“{FIELDS[field]}”只能对应一列，现在有：{'、'.join(headers)}")
    if not any(f in used for f in ("supplier_sku", "oe_numbers", "name")):
        errors.append("至少要有一列能识别产品：供应商料号、OE / 互换号或产品名称。")
    if not any(f in used for f in IDENTITY_FIELDS):
        warnings.append("没有源记录 ID 或供应商料号列：同一供应商再发资料时，"
                        "无法识别哪条是更新。")
    return errors, warnings


def save_template(supplier, headers: list[str], columns: list[dict], user) -> MappingTemplate:
    template, _ = MappingTemplate.objects.update_or_create(
        supplier=supplier, header_signature=header_signature(headers),
        defaults={"headers": headers, "confirmed_by": user,
                  "columns": [{"header": c["header"], "field": c["field"]} for c in columns]},
    )
    return template


class _ModelItem(BaseModel):
    header: str
    field: str
    confidence: float = Field(ge=0, le=1)
    reason: str = ""

    @field_validator("field")
    @classmethod
    def _known(cls, value):
        if value not in FIELDS:
            raise ValueError(f"unknown field {value!r}; use one of {list(FIELDS)}")
        return value


class _ModelResult(BaseModel):
    mapping: list[_ModelItem]


def _ask_model(headers: list[str], sample_rows: list[dict], client) -> dict[str, dict]:
    from apps.ai.llm.base import LLMError
    from apps.ai.llm.factory import get_client

    answers = {h: _item(h, "ignore", "none", 0.0, "未能识别，请人工选择") for h in headers}
    samples = [{h: row.get(h, "") for h in headers} for row in sample_rows[:SAMPLE_ROWS]]
    try:
        result, _task = (client or get_client()).extract_json(
            prompt_name="archive_column_mapping",
            variables={"fields": FIELDS, "headers": headers, "sample_rows": samples},
            schema=_ModelResult,
        )
    except Exception as exc:  # LLMError, or the provider is not configured at all
        reason = f"AI 调用失败：{exc}" if isinstance(exc, LLMError) else f"AI 不可用：{exc}"
        return {h: _item(h, "ignore", "none", 0.0, reason) for h in headers}
    for item in result.mapping:  # only answers for headers we actually asked about
        if item.header in answers:
            answers[item.header] = _item(item.header, item.field, "ai",
                                         round(item.confidence, 2), item.reason)
    return answers


def _item(header, field, source, confidence, reason) -> dict:
    return {"header": header, "field": field, "source": source, "confidence": confidence,
            "reason": reason}
