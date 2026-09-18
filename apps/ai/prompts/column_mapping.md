---
description: 把供应商表头映射到标准字段
temperature: 0
---
你是卡车配件数据整理助手。下面是一份供应商表格的表头和前几行样例。
请把每一个表头映射到标准字段之一，无法判断的映射为 "ignore"。
只根据表头和样例判断，不要编造编号或数据。

标准字段及含义：
- sku: 我方内部料号（通常以 {sku_prefix} 开头）
- oe_number: 主机厂原厂号（OE / OEM）
- cross_number: 其他品牌互换号（Cross / Ref / Interchange / Replaces）
- supplier_pn: 供应商自己的料号
- name_en: 英文品名
- name_zh: 中文品名
- category: 分类
- brand: 编号所属品牌（Volvo / Scania / Knorr ...）
- make, model, engine, year_from, year_to: 适配车型
- unit_cost: 单价（数字）
- currency: 币种
- moq: 最小起订量
- lead_days: 交期（天）
- pcs_per_carton, carton_l_cm, carton_w_cm, carton_h_cm, gross_weight_kg, net_weight_kg: 包装
- image_url: 图片链接
- description_en: 英文描述
- ignore: 无法判断或无用

表头：{headers}
样例行（JSON 数组）：{sample_rows}

只输出 JSON，格式：
{{"mapping": [{{"header": "原表头", "field": "标准字段", "confidence": 0.0到1.0, "reason": "一句话"}}]}}
