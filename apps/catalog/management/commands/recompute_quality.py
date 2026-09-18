from django.core.management.base import BaseCommand

from apps.catalog.models import Part
from apps.catalog.services.quality import recompute


class Command(BaseCommand):
    help = "重新计算全部产品的数据完整度评分（导入或批量修改之后运行）。"

    def handle(self, *args, **options):
        changed = recompute()
        total = Part.objects.count()
        message = f"recomputed {total} parts ({changed} scores changed)"
        self.stdout.write(self.style.SUCCESS(message))
