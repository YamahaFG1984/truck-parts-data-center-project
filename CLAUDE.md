# 施工约定

本仓库按里程碑施工，每个里程碑一次提交、一次人工审核。开始任何工作前：

1. 阅读 docs/schedule.html，找到用户指定的里程碑（未指定时取 docs/index.html 进度表中第一个"未开始"）。
2. 阅读 docs/architecture.html 与 docs/data-dictionary.html 中与该里程碑相关的章节；验收标准见 docs/prd.html。
3. 只实现该里程碑列出的文件与要求。不提前做后续里程碑的内容，不引入清单外的依赖，不重构无关代码。
4. 发现文档遗漏、冲突或与已有代码不一致时，先在回复中说明并给出建议，等用户确认后再动手。
5. 完成后运行该里程碑的全部验收命令，输出原样贴给用户。任何一条失败都不得提交。
6. 通过后按 Conventional Commits 提交（信息含里程碑编号），打轻量标签 M<编号>，并更新 docs/index.html 进度表该行的状态与 commit 短哈希。
7. 停下，向用户报告：改动文件清单、验收输出、建议重点审核的地方。不要继续下一个里程碑。

技术约定：Python 3.12，Django 5.2，PostgreSQL 16（DATABASE_URL 未设时 SQLite），ruff，pytest。
settings 在 config/settings/ 分层；业务逻辑放 services 与 QuerySet，视图保持薄；
所有 AI 调用经 apps/ai/llm/factory.get_client()；AI 产出只能通过 AISuggestion.accept() 写入业务字段。
界面中文，字段英文，USD 单币种。演示数据均为合成，页脚保留声明。

第二阶段（M21–M29，可追溯归档与归一化）另读 docs/archive-design.html，并遵守：
新功能只放在 apps/sources 与 apps/archive，不改第一阶段代码（可调用，不修改）；
来源记录写入后不可修改，更新即新版本；报价保留原币种，不换算、不默认 USD；
匹配只生成待确认条目，归一关系只能经 apps/archive/services/review.py 写入；
extra/ 是公司提供的资料，不进仓库，测试用合成数据。
