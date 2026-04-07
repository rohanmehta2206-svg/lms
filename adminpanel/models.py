from django.db import models


class SystemSettings(models.Model):
    video_host = models.CharField(max_length=255, default="http://127.0.0.1:8000")
    token_expiry_seconds = models.PositiveIntegerField(default=300)

    certificate_signer = models.CharField(max_length=255, default="Authorized Signature")
    signer_role = models.CharField(max_length=255, default="Instructor")
    verification_label = models.CharField(max_length=255, default="Verify via LMS QR record")

    qr_verification_enabled = models.BooleanField(default=True)
    secure_streaming_enabled = models.BooleanField(default=True)
    watch_validation_percent = models.PositiveIntegerField(default=90)
    quiz_completion_enabled = models.BooleanField(default=True)

    moodle_base_url = models.CharField(max_length=255, default="http://127.0.0.1/moodle")
    moodle_token = models.CharField(max_length=255, default="", blank=True)
    moodle_admin_id = models.PositiveIntegerField(default=2)
    moodle_teacher_role = models.PositiveIntegerField(default=3)
    moodle_student_role = models.PositiveIntegerField(default=5)

    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "System Settings"
        verbose_name_plural = "System Settings"

    def __str__(self):
        return "System Settings"