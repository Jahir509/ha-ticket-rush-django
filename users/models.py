from django.core.validators import validate_email
from django.db import models
from django.utils import timezone


class User(models.Model):
    """
    Mirrors the users table exactly: TEXT columns, not VARCHAR, so email is a
    TextField with the email validator rather than an EmailField (which would
    become varchar(254)). The validator only runs in full_clean(), it does
    not touch the schema.
    """

    id = models.BigAutoField(primary_key=True)
    email = models.TextField(validators=[validate_email])
    first_name = models.TextField()
    last_name = models.TextField()
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        db_table = "users"

    def to_dict(self):
        return {
            "id": self.id,
            "email": self.email,
            "first_name": self.first_name,
            "last_name": self.last_name,
            "created_at": self.created_at.isoformat(),
        }
