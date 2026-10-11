from django.core.validators import validate_email
from django.db import migrations, models

class Migration(migrations.Migration):
    atomic = False

    dependencies = [
        ('users', '0001_initial'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            # The index was built by hand with CONCURRENTLY. IF NOT EXISTS
            # makes this a no-op here, and builds it on a fresh database.
            database_operations=[
                migrations.RunSQL(
                    sql=[
                        "SET statement_timeout = 0",
                        "CREATE UNIQUE INDEX CONCURRENTLY IF NOT EXISTS "
                        "users_email_key ON users (email)",
                    ],
                    reverse_sql="DROP INDEX CONCURRENTLY IF EXISTS users_email_key",
                ),
            ],
            # Tell Django the field is unique, without touching the table.
            state_operations=[
                migrations.AlterField(
                    model_name="user",
                    name="email",
                    field=models.TextField(unique=True, validators=[validate_email]),
                ),
            ],
        ),
    ]
