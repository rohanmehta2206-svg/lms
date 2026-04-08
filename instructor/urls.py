from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static
from teacher import views as teacher_views

urlpatterns = [
    path('admin/', admin.site.urls),

    path('', include(('core.urls', 'core'), namespace='core')),
    path('accounts/', include('accounts.urls')),
    path('teacher/', include(('teacher.urls', 'teacher'), namespace='teacher')),
    path('student/', include(('student.urls', 'student'), namespace='student')),
    path('adminpanel/', include(('adminpanel.urls', 'adminpanel'), namespace='adminpanel')),

    # Root-level aliases for Moodle
    path('play-module/<int:module_id>/', teacher_views.play_module, name='play_module_root'),
    path('stream/<path:path>', teacher_views.serve_dash, name='serve_dash_root'),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)