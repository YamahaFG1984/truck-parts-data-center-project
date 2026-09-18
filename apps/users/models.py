from django.contrib.auth.models import AbstractUser


class User(AbstractUser):
    """Project user model.

    Empty on purpose: Two Scoops recommends a custom user from day one so fields
    (role, phone, ...) can be added later without a painful migration.
    """

    class Meta(AbstractUser.Meta):
        verbose_name = "用户"
        verbose_name_plural = "用户"
