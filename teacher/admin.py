from django.contrib import admin
from .models import Course, Section, Category, Module


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("id", "name", "position")


@admin.register(Course)
class CourseAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "category", "is_published", "created_at")
    search_fields = ("title",)
    list_filter = ("is_published",)


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "course", "order")


# ✅ ADD THIS (VERY IMPORTANT)
@admin.register(Module)
class ModuleAdmin(admin.ModelAdmin):
    list_display = ("id", "title", "section", "video_mpd", "created_at")
    search_fields = ("title",)
    list_filter = ("section",)