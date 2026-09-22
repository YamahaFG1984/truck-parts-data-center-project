from pathlib import Path

from django.contrib.auth import get_user_model
from django.core.files import File
from django.core.management.base import BaseCommand, CommandError

from apps.sources.services import ingest, intake
from apps.sources.services.mapping import FIELDS
from apps.sources.services.readers import ReadError
from apps.sources.services.storage import DuplicateFile, UploadRejected, store_upload
from apps.suppliers.models import Supplier


class Command(BaseCommand):
    help = ("非交互导入一份供应商资料：存档原件 → 列映射（该供应商已确认的模板 → 同义词 → AI）"
            " → 预检。默认只预检不入库；确认映射与预检结果后加 --commit 入库。")

    def add_arguments(self, parser):
        parser.add_argument("file", help="xlsx / csv / pdf 文件路径")
        parser.add_argument("--supplier", required=True, help="供应商名称；不存在时新建")
        parser.add_argument("--map", action="append", default=[], metavar="表头=字段",
                            help=f"覆盖某列的映射，可重复；字段取值：{', '.join(FIELDS)}, ignore")
        parser.add_argument("--commit", action="store_true", help="预检通过后入库")
        parser.add_argument("--user", help="操作人用户名（默认第一个超级用户）")

    def handle(self, *args, **options):
        path = Path(options["file"])
        if not path.is_file():
            raise CommandError(f"找不到文件 {path}")
        user = self._user(options["user"])
        supplier, created = Supplier.objects.get_or_create(name=options["supplier"])
        if created:
            self.stdout.write(f"新建供应商：{supplier.name}")
        with path.open("rb") as handle:
            try:
                source = store_upload(File(handle, name=path.name), supplier, user)
            except DuplicateFile as exc:
                source = exc.existing
                self.stdout.write(f"这份文件已存档过（#{source.pk}），沿用该记录。")
            except UploadRejected as exc:
                raise CommandError(str(exc)) from exc
        self.stdout.write(f"原件已存档：#{source.pk} {source.original_name} sha256 "
                          f"{source.sha256[:12]}…")
        if source.status == source.Status.COMMITTED:
            self.stdout.write("这份文件已经入库，无需再次导入。")
            return
        try:
            sheets = intake.inspect(source)
        except ReadError as exc:
            raise CommandError(f"无法解析：{exc}") from exc
        suggestions = intake.suggestions(source, sheets)
        chosen = self._overrides(suggestions, options["map"])
        for i, sheet in enumerate(suggestions):
            self.stdout.write(f"工作表“{sheet['name']}”（表头在第 {sheet['header_row']} 行）")
            for j, column in enumerate(sheet["columns"]):
                field = chosen.get((i, j), column["field"])
                how = "人工指定" if (i, j) in chosen else column["source"]
                self.stdout.write(f"  {column['header']!s:<28} → {field:<14} ({how})")
        errors, warnings = intake.confirm(source, chosen, user)
        for warning in warnings:
            self.stdout.write(f"  注意：{warning}")
        if errors:
            raise CommandError("列映射未通过：" + "；".join(errors)
                               + "。请用 --map 表头=字段 指定后重试。")
        self._preview(source)
        if not options["commit"]:
            self.stdout.write("预检结束，未入库。核对无误后加 --commit 入库。")
            return
        try:
            written = ingest.commit(source, user)
        except ingest.IngestError as exc:
            raise CommandError(str(exc)) from exc
        self.stdout.write(f"已入库 {written} 条；新记录已参与匹配，待确认条目见归一复核。")

    def _preview(self, source):
        plan = ingest.preview(source)
        counts = plan.counts()
        self.stdout.write("预检：" + "，".join(
            f"{label} {counts[change]}" for change, label in ingest.CHANGE_LABELS.items())
            + f"，本次未出现 {counts['absent']}，有警告 {counts['with_warnings']}，"
              f"有缺失 {counts['with_missing']}")
        for row in plan:
            if row.change in ("key_change", "price_update", "info_update"):
                changes = "；".join(f"{c['label']} {c['old'] or '（空）'} → {c['new'] or '（空）'}"
                                   for c in row.diff)
                self.stdout.write(f"  {row.locator} {row.record_key} {row.change_label}：{changes}")
            if row.problem:
                self.stdout.write(f"  ! {row.locator}：{row.problem}")

    def _overrides(self, suggestions, pairs) -> dict:
        wanted = {}
        for pair in pairs:
            header, sep, field = pair.partition("=")
            if not sep or (field not in FIELDS and field != "ignore"):
                raise CommandError(f"--map {pair!r} 格式应为 表头=字段，字段取值见 --help。")
            wanted[header.strip()] = field
        chosen, used = {}, set()
        for i, sheet in enumerate(suggestions):
            for j, column in enumerate(sheet["columns"]):
                if column["header"] in wanted:
                    chosen[(i, j)] = wanted[column["header"]]
                    used.add(column["header"])
        if unknown := set(wanted) - used:
            raise CommandError(f"文件里没有这些表头：{'、'.join(sorted(unknown))}")
        return chosen

    def _user(self, username):
        users = get_user_model().objects
        user = (users.filter(username=username).first() if username
                else users.filter(is_superuser=True).order_by("id").first())
        if user is None:
            raise CommandError("找不到操作人，请用 --user 指定或先创建超级用户。")
        return user
