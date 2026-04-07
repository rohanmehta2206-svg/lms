from django.contrib import admin
from .models import Course, Section, Category, Module, CertificateSettings


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "position", "moodle_category_id")
    search_fields = ("name",)
    ordering = ("position",)


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "short_name",
        "category",
        "moodle_course_id",
        "is_published",
        "created_at",
    )
    search_fields = ("title", "short_name")
    list_filter = ("is_published", "category")
    ordering = ("-created_at",)


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "course",
        "order",
        "moodle_section_id",
        "moodle_section_number",
    )
    search_fields = ("title", "course__title")
    list_filter = ("course",)
    ordering = ("course", "order")


@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "type",
        "section",
        "order",
        "moodle_cmid",
        "moodle_instance_id",
        "video_mpd",
        "created_at",
    )
    search_fields = ("title", "section__title", "section__course__title")
    list_filter = ("type", "section__course")
    ordering = ("section", "order", "id")


@admin.register(CertificateSettings)
class CertificateSettingsAdmin(admin.ModelAdmin):
    list_display = (
        "id",
        "title",
        "organization_name",
        "issuer_name",
        "signer_name",
        "signer_role",
        "is_active",
        "updated_at",
    )
    search_fields = (
        "title",
        "organization_name",
        "issuer_name",
        "signer_name",
        "signer_role",
    )
    list_filter = ("is_active", "updated_at", "created_at")
    ordering = ("-is_active", "-updated_at")