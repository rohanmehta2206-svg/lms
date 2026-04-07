from django.urls import path
from . import views

app_name = "student"

urlpatterns = [
    path('dashboard/', views.student_dashboard, name='student_dashboard'),
    path('courses/', views.my_courses, name='my_courses'),
    path('progress/', views.progress_tracker, name='progress_tracker'),
    path('certificates/', views.certificates, name='certificates'),
    path('profile/', views.profile_page, name='profile'),

    # Certificate download
    path('certificate/download/<int:course_id>/', views.download_certificate, name='download_certificate'),

    # Enrollment
    path('enroll/<int:course_id>/', views.enroll_course, name='enroll_course'),

    # Course preview + enrolled course detail
    path('view-course/<int:course_id>/', views.view_course, name='view_course'),
    path('course-detail/<int:course_id>/', views.course_detail, name='course_detail'),

    # Dynamic module pages
    path('play-video/<int:module_id>/', views.play_video, name='play_video'),
    path('material/<int:module_id>/', views.material_page, name='material_page'),
    path('take-quiz/<int:module_id>/', views.take_quiz, name='take_quiz'),
    path('read-theory/<int:module_id>/', views.read_theory, name='read_theory'),

    # Video heartbeat
    path('video-heartbeat/<int:module_id>/', views.save_video_heartbeat, name='save_video_heartbeat'),

    # Anti-cheating logs
    path('save-webcam-snapshot/<int:module_id>/', views.save_webcam_snapshot, name='save_webcam_snapshot'),
    path('log-tab-switch/<int:module_id>/', views.log_tab_switch, name='log_tab_switch'),

    # Mark module as completed
    path('mark-complete/<int:module_id>/', views.mark_module_complete, name='mark_module_complete'),

    # Serve material file safely from lms_storage / media
    path('material-file/<int:module_id>/', views.serve_material_file, name='serve_material_file'),
]