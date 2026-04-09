from django.urls import path
from . import views

app_name = "teacher"

urlpatterns = [

    # Dashboard
    path('dashboard/', views.teacher_dashboard, name='teacher_dashboard'),

    # Courses
    path('courses/', views.course_list, name='course_list'),
    path('courses/create/', views.create_course, name='create_course'),
    path('courses/<int:course_id>/', views.course_detail, name='course_detail'),

    # ✅ NEW: Toggle Course Publish
    path('course/toggle/<int:course_id>/', views.toggle_course_publish, name='toggle_course'),

    # Modules
    path('module-builder/<int:section_id>/', views.module_builder, name='module_builder'),
    path('play-module/<int:module_id>/', views.play_module, name='play_module'),

    # ✅ NEW: Toggle Module Publish
    path('module/toggle/<int:module_id>/', views.toggle_module_publish, name='toggle_module'),

    # Sections
    path('section/update/<int:section_id>/', views.update_section, name='update_section'),

    # Streaming
    path('stream/<path:path>', views.serve_dash, name='serve_dash'),

    # Profile
    path('profile/', views.profile_page, name='profile'),

    # ✅ NEW: Draft / Hidden Content Page
    path('drafts/', views.draft_content, name='draft_content'),
]