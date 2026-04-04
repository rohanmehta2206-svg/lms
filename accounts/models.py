from django.db import models
from django.contrib.auth.models import User


class UserProfile(models.Model):

    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name="profile"
    )

    # Moodle User ID
    moodle_user_id = models.IntegerField(
        null=True,
        blank=True
    )

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.user.username


# =====================================
# NEW MODEL: Pending Teacher Request
# =====================================
class PendingTeacher(models.Model):
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField()

    first_name = models.CharField(max_length=150)
    last_name = models.CharField(max_length=150)

    # ⚠️ Temporary password (will be deleted after approval)
    password = models.CharField(max_length=255)

    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Pending: {self.username}"