from django.core.management.base import BaseCommand

from apps.archive.services import export


class Command(BaseCommand):
    help = "导出主数据、供应商报价、待人工确认清单三份 xlsx 到指定目录。"

    def add_arguments(self, parser):
        parser.add_argument("--out", required=True, help="输出目录（不存在会创建）")

    def handle(self, *args, **options):
        for path in export.write_all(options["out"]):
            self.stdout.write(f"已写出 {path}")
