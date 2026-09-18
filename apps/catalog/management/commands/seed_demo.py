from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from apps.catalog.demo import DEFAULT_SEED, reset_catalog, seed_catalog
from apps.catalog.models import Part
from scripts.make_supplier_excel import write_supplier_excel


class Command(BaseCommand):
    help = (
        "生成合成演示数据（约 400 个 SKU，含故意的脏数据）和一份乱格式供应商报价单 "
        "media/demo/supplier_quote_messy.xlsx。编号均为按品牌格式随机生成，不是真实 OE 号。"
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--reset",
            action="store_true",
            help="先清空全部产品目录数据（产品、编号、适配、图片、分类、品牌）再生成。",
        )
        parser.add_argument("--parts", type=int, default=400, help="产品数量，默认 400。")
        parser.add_argument(
            "--seed", type=int, default=DEFAULT_SEED, help="随机种子，相同种子数据相同。"
        )

    def handle(self, *args, **options):
        if Part.objects.exists() and not options["reset"]:
            raise CommandError("产品目录已有数据。确认要清空重建请加 --reset。")

        with transaction.atomic():
            if options["reset"]:
                reset_catalog()
                self.stdout.write("已清空产品目录。")
            result = seed_catalog(parts=options["parts"], seed=options["seed"])

        excel = write_supplier_excel(
            Path(settings.MEDIA_ROOT) / "demo" / "supplier_quote_messy.xlsx",
            samples=result.samples,
            taken=result.taken_norms,
            seed=options["seed"],
        )
        self.stdout.write(
            self.style.SUCCESS(
                f"生成 {result.parts} 个产品、{result.numbers + result.duplicate_groups} 条编号"
                f"（含 {result.duplicate_groups} 组疑似重复）、{result.fitments} 条适配、"
                f"{result.images} 张图片。"
            )
        )
        self.stdout.write(f"乱格式供应商报价单：{excel}")
        self.stdout.write("提示：以上均为合成演示数据，编号不代表真实 OE 号。")
