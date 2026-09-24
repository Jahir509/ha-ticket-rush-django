from django.db import models


class Order(models.Model):
    """
    Written only by the drain command, in batches, via COPY. No web request
    ever touches this table, so no extra indexes: every index slows COPY
    down. Add reporting indexes after the load test, not before.
    """

    order_id = models.UUIDField(primary_key=True)
    event_id = models.TextField()
    user_id = models.TextField(null=True, blank=True)
    status = models.TextField()
    created_at = models.DateTimeField()

    class Meta:
        db_table = "orders"
