"""Suggest which standard field each supplier column holds (docs/architecture.html §7.5).

1. The synonym table (docs/data-dictionary.html §11) decides every header it knows:
   source "synonym", confidence 1.0 (0.9 when only a prefix plus a unit matched,
   e.g. "FOB Price(USD)").
2. Only the headers left over go to the LLM, in one call, with three sample rows.
3. Anything still unknown, or everything left over if the LLM call fails, maps to
   "ignore" so a person decides.

Two synonyms appear under two fields in the data dictionary; here "model" means
the vehicle model (not the supplier's part number) and "make" the vehicle make
(not the brand of a number), which is how supplier sheets use them.
"""

import re
import unicodedata

from django.conf import settings

from apps.ai.schemas import STANDARD_FIELDS, MappingResult

SAMPLE_ROWS = 3
PREFIX_CONFIDENCE = 0.9

FIELD_LABELS = {
    "sku": "我方 SKU",
    "oe_number": "OE 号",
    "cross_number": "互换号",
    "supplier_pn": "供应商料号",
    "name_en": "英文品名",
    "name_zh": "中文品名",
    "category": "分类",
    "brand": "编号品牌",
    "make": "适配品牌 / 车型",
    "model": "适配车系",
    "engine": "发动机",
    "year_from": "起始年份 / 年份范围",
    "year_to": "截止年份",
    "unit_cost": "单价",
    "currency": "币种",
    "moq": "起订量",
    "lead_days": "交期",
    "pcs_per_carton": "包装（每箱数量 / 箱规 / 重量）",
    "carton_l_cm": "外箱尺寸",
    "carton_w_cm": "外箱宽",
    "carton_h_cm": "外箱高",
    "gross_weight_kg": "毛重",
    "net_weight_kg": "净重",
    "image_url": "图片链接",
    "description_en": "英文描述 / 备注",
    "ignore": "忽略此列",
}
assert set(FIELD_LABELS) == set(STANDARD_FIELDS)

SYNONYMS = {
    "sku": ["sku", "item no", "item code", "our no", "fit no", "article no", "art no",
            "我方料号", "料号", "货号", "编码"],
    "oe_number": ["oe", "oe no", "oem", "oem no", "oem number", "original no", "original number",
                  "genuine no", "factory no", "原厂号", "原厂编号", "oe号", "原厂件号", "主机厂号"],
    "cross_number": ["cross", "cross ref", "cross reference", "ref", "ref no", "reference",
                     "interchange", "replaces", "replacement", "comp no", "competitor no",
                     "equivalent", "互换号", "替代号", "参考号", "对应号", "通用号"],
    "supplier_pn": ["part no", "part number", "p/n", "pn", "supplier no", "our code", "model no",
                    "型号", "供应商编号", "厂家编号", "产品编号"],
    "name_en": ["description", "desc", "product name", "name", "item", "product", "title",
                "英文品名", "英文名称"],
    "name_zh": ["chinese name", "cn name", "品名", "名称", "中文名", "产品名称"],
    "category": ["category", "cat", "group", "product group", "type", "分类", "类别", "品类"],
    "brand": ["brand", "oem brand", "manufacturer", "品牌", "厂家"],
    "make": ["make", "application", "vehicle", "vehicle make", "truck", "for",
             "适用车型", "车型", "适配", "适用"],
    "model": ["model", "series", "vehicle model", "车系"],
    "engine": ["engine", "engine model", "engine type", "发动机", "机型"],
    "year_from": ["year", "years", "from", "year range", "年份", "年款"],
    "year_to": ["to"],
    "unit_cost": ["price", "unit price", "cost", "fob", "fob price", "exw", "exw price", "usd",
                  "rmb", "quote", "单价", "价格", "报价", "含税价", "不含税价"],
    "currency": ["currency", "cur", "币种"],
    "moq": ["moq", "min order", "minimum order", "min qty", "起订量", "最小起订量"],
    "lead_days": ["lead time", "leadtime", "delivery", "delivery time", "交期", "交货期", "货期"],
    "pcs_per_carton": ["qty/ctn", "pcs/ctn", "packing", "pack qty", "carton qty",
                       "装箱数", "每箱数量", "包装数量", "包装"],
    "carton_l_cm": ["carton size", "ctn size", "dimension", "l*w*h", "size",
                    "箱规", "外箱尺寸", "尺寸"],
    "gross_weight_kg": ["gw", "g.w.", "gross weight", "weight", "毛重", "重量"],
    "net_weight_kg": ["nw", "n.w.", "net weight", "净重"],
    "image_url": ["image", "photo", "picture", "pic", "img", "image url", "图片", "照片"],
    "description_en": ["remarks", "remark", "note", "notes", "detail", "details", "spec",
                       "specification", "备注", "说明", "规格"],
}
# Suffixes that may follow a synonym without changing its meaning: "Price(USD)", "Weight KG".
_UNIT_SUFFIXES = {"usd", "rmb", "cny", "eur", "kg", "kgs", "g", "cm", "mm", "pcs", "pc", "days",
                  "day", "no", "number"}
_SEPARATORS = re.compile(r"[\s._\-/()（）:：#&+*,，]+")


def header_key(text: str) -> str:
    """"FOB Price(USD)" -> "fobpriceusd"; "OE号" -> "oe号"."""
    return _SEPARATORS.sub("", unicodedata.normalize("NFKC", text).casefold())


_EXACT = {header_key(s): f for f, synonyms in SYNONYMS.items() for s in synonyms}
_BY_LENGTH = sorted(_EXACT.items(), key=lambda kv: -len(kv[0]))


def match_synonym(header: str) -> tuple[str, float] | None:
    key = header_key(header)
    if not key:
        return None
    if key in _EXACT:
        return _EXACT[key], 1.0
    for synonym, field in _BY_LENGTH:  # longest synonym first
        if len(synonym) >= 3 and key.startswith(synonym) and key[len(synonym):] in _UNIT_SUFFIXES:
            return field, PREFIX_CONFIDENCE
    return None


def suggest_mapping(headers: list[str], sample_rows: list[dict], *, client=None) -> list[dict]:
    """One suggestion per header, in header order:
    {"header", "field", "source": synonym|ai|none, "confidence", "reason"}."""
    suggestions: dict[str, dict] = {}
    unknown = []
    for header in headers:
        hit = match_synonym(header)
        if hit:
            field, confidence = hit
            suggestions[header] = _suggestion(header, field, "synonym", confidence, "同义词表")
        else:
            unknown.append(header)

    if unknown:
        suggestions |= _ask_llm(unknown, sample_rows, client)
    return [suggestions[h] for h in headers]


def _ask_llm(headers: list[str], sample_rows: list[dict], client) -> dict[str, dict]:
    from apps.ai.llm.base import LLMError

    fallback = {h: _suggestion(h, "ignore", "none", 0.0, "未能识别") for h in headers}
    if client is None:
        from apps.ai.llm.factory import get_client

        client = get_client()
    samples = [{h: row.get(h, "") for h in headers} for row in sample_rows[:SAMPLE_ROWS]]
    try:
        result, _task = client.extract_json(
            prompt_name="column_mapping",
            variables={"sku_prefix": settings.COMPANY_SKU_PREFIX, "headers": headers,
                       "sample_rows": samples},
            schema=MappingResult,
        )
    except LLMError as exc:
        return {h: _suggestion(h, "ignore", "none", 0.0, f"AI 调用失败：{exc}") for h in headers}

    for item in result.mapping:  # accept answers only for the headers we asked about
        if item.header in fallback:
            fallback[item.header] = _suggestion(
                item.header, item.field, "ai", round(item.confidence, 2), item.reason
            )
    return fallback


def _suggestion(header, field, source, confidence, reason):
    return {"header": header, "field": field, "source": source, "confidence": confidence,
            "reason": reason}
