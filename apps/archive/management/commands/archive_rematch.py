from django.core.management.base import BaseCommand

from apps.archive.models import ReviewItem
from apps.archive.services.matching import rematch, rules


class Command(BaseCommand):
    help = ("按当前规则重新生成未决的待确认条目。已决条目在证据不变时保持原决定；"
            "证据变化的会重新打开。不会合并或拆分任何产品。")

    def handle(self, *args, **options):
        counts = rematch()
        labels = dict(ReviewItem.Category.choices)
        self.stdout.write(f"规则版本 {rules()['version']}")
        for key, value in sorted(counts.items()):
            self.stdout.write(f"  {labels.get(key, key)}：{value}")
