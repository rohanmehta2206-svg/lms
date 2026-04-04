from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [
    # Dashboard
    path('', views.admin_dashboard, name='dashboard'),

    # User Management
    path('users/', views.user_management, name='users'),

    # ✅ Approve Teacher
    path('users/approve/<int:user_id>/', views.approve_teacher, name='approve_teacher'),

    # ❌ Reject Teacher
    path('users/reject/<int:user_id>/', views.reject_teacher, name='reject_teacher'),

    # Audit Reports
    path('reports/', views.audit_reports, name='reports'),

    # Courses Overview
    path('courses/', views.course_management, name='courses'),

    # Certificate Control
    path('certificates/', views.certificate_control, name='certificates'),

    # Settings / Compliance
    path('settings/', views.settings_compliance, name='settings'),
]