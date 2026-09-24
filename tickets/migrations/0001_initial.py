from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = []

    operations = [
        migrations.CreateModel(
            name="Order",
            fields=[
                ("order_id", models.UUIDField(primary_key=True, serialize=False)),
                ("event_id", models.TextField()),
                ("user_id", models.TextField(blank=True, null=True)),
                ("status", models.TextField()),
                ("created_at", models.DateTimeField()),
            ],
            options={"db_table": "orders"},
        ),
    ]
