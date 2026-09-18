"""Custom migration operations."""

from django.db import migrations


class PostgresOnlyAddIndex(migrations.AddIndex):
    """AddIndex that only touches the database on PostgreSQL.

    Migration state is identical to AddIndex, so makemigrations stays clean, but
    PostgreSQL-only index types (GIN trigram) are skipped on the SQLite fallback.
    Keep such indexes out of CreateModel options and add them with this instead.
    """

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_forwards(app_label, schema_editor, from_state, to_state)

    def database_backwards(self, app_label, schema_editor, from_state, to_state):
        if schema_editor.connection.vendor == "postgresql":
            super().database_backwards(app_label, schema_editor, from_state, to_state)
