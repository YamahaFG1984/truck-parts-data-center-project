"""Enable the pg_trgm extension used for fuzzy part-number matching.

Django's CreateExtension operation is a no-op on non-PostgreSQL databases,
so this migration is safe on the SQLite fallback.
"""

from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):
    initial = True
    dependencies = []
    operations = [TrigramExtension()]
