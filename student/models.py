from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone
from teacher.models import Course, Module
import hashlib


class ImmutableLogMixin(models.Model):
    """
    Append-only immutable log with hash chaining:
    - allow create
    - block update
    - block delete
    - save previous_hash and current_hash
    """

    previous_hash = models.CharField(max_length=64, blank=True, editable=False)
    current_hash = models.CharField(max_length=64, blank=True, editable=False)

    class Meta:
        abstract = True

    def build_hash_payload(self):
        raise NotImplementedError("Child class must implement build_hash_payload().")

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Immutable log records cannot be updated.")

        last_log = self.__class__.objects.order_by("-id").first()
        self.previous_hash = last_log.current_hash if last_log and last_log.current_hash else "0"

        payload = f"{self.previous_hash}|{self.build_hash_payload()}"
        self.current_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()

        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Immutable log records cannot be deleted.")


class Student(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        related_name='student_profile',
        null=True,
        blank=True
    )
    username = models.CharField(max_length=150, unique=True)
    email = models.EmailField(unique=True)
    password = models.CharField(max_length=255)
    moodle_user_id = models.IntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def save(self, *args, **kwargs):
        if self.user:
            if not self.username:
                self.username = self.user.username
            if not self.email:
                self.email = self.user.email
        super().save(*args, **kwargs)

    def __str__(self):
        if self.user:
            return f"{self.user.username} - Student"
        return self.username


class Enrollment(models.Model):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='enrollments'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='enrollments'
    )
    is_active = models.BooleanField(default=True)
    enrolled_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'course')
        ordering = ['-enrolled_at']

    def __str__(self):
        status = "Active" if self.is_active else "Inactive"
        return f"{self.student.username} - {self.course.title} - {status}"


class StudentModuleProgress(models.Model):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='student_module_progress'
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='student_progress'
    )
    is_completed = models.BooleanField(default=False)
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('student', 'module')
        ordering = ['-created_at']

    def __str__(self):
        status = "Completed" if self.is_completed else "Pending"
        return f"{self.student.username} - {self.module.title} - {status}"


class QuizAttempt(models.Model):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='quiz_attempts'
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='quiz_attempts'
    )
    total_questions = models.PositiveIntegerField(default=0)
    correct_answers = models.PositiveIntegerField(default=0)
    score_percent = models.PositiveIntegerField(default=0)
    submitted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        return f"{self.student.username} - {self.module.title} - {self.score_percent}%"


class StudentCertificate(models.Model):
    STATUS_ISSUED = 'issued'
    STATUS_REVOKED = 'revoked'

    STATUS_CHOICES = [
        (STATUS_ISSUED, 'Issued'),
        (STATUS_REVOKED, 'Revoked'),
    ]

    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='student_certificates'
    )
    course = models.ForeignKey(
        Course,
        on_delete=models.CASCADE,
        related_name='student_certificates'
    )

    certificate_code = models.CharField(max_length=100, unique=True)
    student_name = models.CharField(max_length=255)
    course_title = models.CharField(max_length=255)

    issued_at = models.DateTimeField(default=timezone.now)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default=STATUS_ISSUED)

    moodle_certificate_id = models.CharField(max_length=100, null=True, blank=True)
    moodle_sync_status = models.CharField(max_length=50, default='Not Synced')
    verification_url = models.URLField(max_length=500, blank=True)
    revoke_reason = models.CharField(max_length=255, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('student', 'course')
        ordering = ['-issued_at']

    def __str__(self):
        return f"{self.student.username} - {self.course.title} - {self.certificate_code}"

    @property
    def is_revoked(self):
        return self.status == self.STATUS_REVOKED

    def revoke(self, reason=''):
        self.status = self.STATUS_REVOKED
        self.revoke_reason = reason or ''
        self.revoked_at = timezone.now()
        self.save(update_fields=['status', 'revoke_reason', 'revoked_at'])


class VideoWatchProgress(models.Model):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='video_watch_progress'
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='video_watch_progress'
    )
    total_duration = models.FloatField(default=0)
    watched_seconds = models.FloatField(default=0)
    watched_percent = models.FloatField(default=0)
    last_position = models.FloatField(default=0)
    max_position_reached = models.FloatField(default=0)
    heartbeat_count = models.PositiveIntegerField(default=0)
    started_at = models.DateTimeField(auto_now_add=True)
    last_heartbeat_at = models.DateTimeField(null=True, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    is_completed = models.BooleanField(default=False)

    class Meta:
        unique_together = ('student', 'module')
        ordering = ['-last_heartbeat_at', '-started_at']

    def __str__(self):
        return f"{self.student.username} - {self.module.title} - {round(self.watched_percent, 2)}%"

    def update_progress(self, current_time=0, duration=0, increment_seconds=0):
        current_time = max(float(current_time or 0), 0)
        duration = max(float(duration or 0), 0)
        increment_seconds = max(float(increment_seconds or 0), 0)

        if duration > 0:
            self.total_duration = max(self.total_duration, duration)

        if current_time > self.max_position_reached:
            self.max_position_reached = current_time

        self.last_position = current_time
        self.watched_seconds += increment_seconds
        self.heartbeat_count += 1
        self.last_heartbeat_at = timezone.now()

        effective_duration = self.total_duration if self.total_duration > 0 else duration
        if effective_duration > 0:
            self.watched_percent = min((self.watched_seconds / effective_duration) * 100, 100)

        if self.watched_percent >= 90 and not self.is_completed:
            self.is_completed = True
            self.completed_at = timezone.now()

        self.save()


class VideoWatchEvent(ImmutableLogMixin):
    EVENT_CHOICES = [
        ('play', 'Play'),
        ('pause', 'Pause'),
        ('heartbeat', 'Heartbeat'),
        ('seek', 'Seek'),
        ('ended', 'Ended'),
    ]

    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='video_watch_events'
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='video_watch_events'
    )
    event_type = models.CharField(max_length=20, choices=EVENT_CHOICES, default='heartbeat')
    current_time = models.FloatField(default=0)
    duration = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']

    def build_hash_payload(self):
        return "|".join([
            str(self.student_id or ""),
            str(self.module_id or ""),
            str(self.event_type or ""),
            str(self.current_time or 0),
            str(self.duration or 0),
            str(self.created_at or timezone.now()),
        ])

    def __str__(self):
        return f"{self.student.username} - {self.module.title} - {self.event_type}"


class WebcamSnapshot(ImmutableLogMixin):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='webcam_snapshots'
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='webcam_snapshots'
    )
    image = models.ImageField(upload_to='webcam_snapshots/')
    captured_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-captured_at']

    def build_hash_payload(self):
        return "|".join([
            str(self.student_id or ""),
            str(self.module_id or ""),
            str(getattr(self.image, "name", "") or ""),
            str(self.captured_at or timezone.now()),
        ])

    def __str__(self):
        return f"{self.student.username} - {self.module.title} - Webcam Snapshot"


class TabSwitchLog(ImmutableLogMixin):
    student = models.ForeignKey(
        User,
        on_delete=models.CASCADE,
        related_name='tab_switch_logs'
    )
    module = models.ForeignKey(
        Module,
        on_delete=models.CASCADE,
        related_name='tab_switch_logs'
    )
    switched_at = models.DateTimeField(auto_now_add=True)
    current_time = models.FloatField(default=0)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ['-switched_at']

    def build_hash_payload(self):
        return "|".join([
            str(self.student_id or ""),
            str(self.module_id or ""),
            str(self.current_time or 0),
            str(self.note or ""),
            str(self.switched_at or timezone.now()),
        ])

    def __str__(self):
        return f"{self.student.username} - {self.module.title} - Tab Switch"