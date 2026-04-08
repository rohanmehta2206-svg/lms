from django.urls import path
from . import views

app_name = "teacher"

urlpatterns = [
    path('dashboard/', views.teacher_dashboard, name='teacher_dashboard'),

    path('courses/', views.course_list, name='course_list'),
    path('courses/create/', views.create_course, name='create_course'),
    path('courses/<int:course_id>/', views.course_detail, name='course_detail'),

    path('module-builder/<int:section_id>/', views.module_builder, name='module_builder'),
    path('play-module/<int:module_id>/', views.play_module, name='play_module'),

    path('section/update/<int:section_id>/', views.update_section, name='update_section'),

    path('stream/<path:path>', views.serve_dash, name='serve_dash'),

    # ✅ NEW: Teacher Profile
    path('profile/', views.profile_page, name='profile'),
]