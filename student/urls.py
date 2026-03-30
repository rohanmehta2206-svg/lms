from django.urls import path
from . import views
app_name = "student"
urlpatterns = [
    path('dashboard/', views.student_dashboard, name='student_dashboard'),
    path('courses/', views.my_courses, name='my_courses'),
    path('progress/', views.progress_tracker, name='progress_tracker'),
    path('certificates/', views.certificates, name='certificates'),
    path('course-detail/', views.course_detail, name='course_detail'),
    path('play-video/', views.play_video, name='play_video'),
    path('material/', views.material_page, name='material_page'),
    path('take-quiz/', views.take_quiz, name='take_quiz'),
    path('read-theory/', views.read_theory, name='read_theory'),
]