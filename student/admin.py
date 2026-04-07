from django.contrib import admin
from .models import (
    Student,
    Enrollment,
    StudentModuleProgress,
    QuizAttempt,
    VideoWatchProgress,
    VideoWatchEvent,
    WebcamSnapshot,
    TabSwitchLog,
)


class ImmutableLogAdminMixin:
    readonly_fields = ("previous_hash", "current_hash")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ("id", "username", "email", "moodle_user_id", "created_at")
    search_fields = ("username", "email")
    list_filter = ("created_at",)
    ordering = ("-created_at",)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "course", "is_active", "enrolled_at")
    search_fields = ("student__username", "course__title")
    list_filter = ("is_active", "enrolled_at")
    ordering = ("-enrolled_at",)


@admin.register(StudentModuleProgress)
class StudentModuleProgressAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "module", "is_completed", "completed_at", "created_at")
    search_fields = ("student__username", "module__title")
    list_filter = ("is_completed", "completed_at", "created_at")
    ordering = ("-created_at",)


@admin.register(QuizAttempt)
class QuizAttemptAdmin(admin.ModelAdmin):
    list_display = ("id", "student", "module", "total_questions", "correct_answers", "score_percent", "submitted_at")
    search_fields = ("student__username", "module__title")
    list_filter = ("submitted_at",)
    ordering = ("-submitted_at",)


@admin.register(VideoWatchProgress)
class VideoWatchProgressAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "student",
        "module",
        "watched_seconds",
        "watched_percent",
        "max_position_reached",
        "heartbeat_count",
        "is_completed",
        "last_heartbeat_at",
    )
    search_fields = ("student__username", "module__title")
    list_filter = ("is_completed", "last_heartbeat_at", "started_at")
    ordering = ("-last_heartbeat_at", "-started_at")


@admin.register(VideoWatchEvent)
class VideoWatchEventAdmin(ImmutableLogAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "student",
        "module",
        "event_type",
        "current_time",
        "duration",
        "previous_hash",
        "current_hash",
        "created_at",
    )
    search_fields = ("student__username", "module__title", "event_type", "previous_hash", "current_hash")
    list_filter = ("event_type", "created_at")
    ordering = ("-created_at",)


@admin.register(WebcamSnapshot)
class WebcamSnapshotAdmin(ImmutableLogAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "student",
        "module",
        "image",
        "previous_hash",
        "current_hash",
        "captured_at",
    )
    search_fields = ("student__username", "module__title", "previous_hash", "current_hash")
    list_filter = ("captured_at",)
    ordering = ("-captured_at",)


@admin.register(TabSwitchLog)
class TabSwitchLogAdmin(ImmutableLogAdminMixin, admin.ModelAdmin):
    list_display = (
        "id",
        "student",
        "module",
        "current_time",
        "note",
        "previous_hash",
        "current_hash",
        "switched_at",
    )
    search_fields = ("student__username", "module__title", "note", "previous_hash", "current_hash")
    list_filter = ("switched_at",)
    ordering = ("-switched_at",)