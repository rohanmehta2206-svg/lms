from django.urls import path
from . import views

app_name = 'adminpanel'

urlpatterns = [

    # =======================
    # Dashboard
    # =======================
    path('', views.admin_dashboard, name='dashboard'),

    # =======================
    # User Management
    # =======================
    path('users/', views.user_management, name='users'),

    # Approve Teacher
    path('users/approve/<int:user_id>/', views.approve_teacher, name='approve_teacher'),

    # Reject Teacher
    path('users/reject/<int:user_id>/', views.reject_teacher, name='reject_teacher'),

    # =======================
    # Reports / Audit
    # =======================
    path('reports/', views.audit_reports, name='reports'),

    # =======================
    # Course Management
    # =======================
    path('courses/', views.course_management, name='courses'),

    # =======================
    # Certificate Control
    # =======================
    path('certificates/', views.certificate_control, name='certificates'),

    # =======================
    # System Settings
    # =======================
    path('settings/', views.settings_compliance, name='settings'),
    path('certificates/revoke/<int:cert_id>/', views.revoke_certificate, name='revoke_certificate'),
]