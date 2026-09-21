from django.apps import AppConfig


class ArchiveConfig(AppConfig):
    name = "apps.archive"
    label = "archive"
    verbose_name = "归一档案"

    def ready(self):
        from apps.sources.signals import records_committed

        from .services.pipeline import on_records_committed

        records_committed.connect(on_records_committed, dispatch_uid="archive_enroll_and_match")
