from django.core.management.base import BaseCommand, CommandError

from apps.archive.models import ReviewItem
from apps.archive.services.matching import rematch, rules
from apps.sources.services import restandardize, versions
from apps.suppliers.models import Supplier


class Command(BaseCommand):
    help = ("按当前规则重新生成未决的待确认条目。已决条目在证据不变时保持原决定；"
            "证据变化的会重新打开。不会合并或拆分任何产品。"
            "加 --restandardize 先按当前词表从原件重新推导字段"
            "（默认只预演，--commit 才写入新版本）。")

    def add_arguments(self, parser):
        parser.add_argument("--restandardize", action="store_true",
                            help="从留存的原件按当前词表与规则重新推导字段")
        parser.add_argument("--commit", action="store_true",
                            help="与 --restandardize 一起用：把有变化的记录写成新版本")
        parser.add_argument("--supplier", help="只重算这个供应商（名称）")

    def handle(self, *args, **options):
        if options["commit"] and not options["restandardize"]:
            raise CommandError("--commit 只能与 --restandardize 一起使用。")
        if options["restandardize"]:
            self._restandardize(options)
            if not options["commit"]:
                return
        counts = rematch()
        labels = dict(ReviewItem.Category.choices)
        self.stdout.write(f"规则版本 {rules()['version']}")
        for key, value in sorted(counts.items()):
            self.stdout.write(f"  {labels.get(key, key)}：{value}")

    def _restandardize(self, options):
        supplier = None
        if options["supplier"]:
            supplier = Supplier.objects.filter(name=options["supplier"]).first()
            if supplier is None:
                raise CommandError(f"找不到供应商“{options['supplier']}”。")
        reruns, problems = restandardize.plan(supplier)
        for problem in problems:
            self.stderr.write(f"  ! {problem}")
        self.stdout.write(f"规则重算：{len(reruns)} 条记录的推导结果会变化")
        for rerun in reruns:
            record = rerun.record
            kinds = {c["kind"] for c in rerun.changes}
            flag = "［关键字段］" if "key" in kinds else ""
            summary = versions.summary(rerun.changes) or "字段出处或警告变化"
            self.stdout.write(f"  {record.supplier.name} {record.record_key} "
                              f"v{record.version} {record.locator}：{flag}{summary}")
        if not options["commit"]:
            self.stdout.write("预演结束，未写入。确认后加 --commit 写入新版本。")
            return
        written = restandardize.commit(reruns)
        self.stdout.write(f"已写入 {len(written)} 个新版本；关键字段变化的成员关系已暂停，"
                          "请到归一复核处理。")
