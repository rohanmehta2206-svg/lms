from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

urlpatterns = [
    # Django default admin (do not remove)
    path('admin/', admin.site.urls),

    # Accounts App
    path('accounts/', include('accounts.urls')),

    # Teacher Panel (MAIN LANDING)
    path('', include(('teacher.urls', 'teacher'), namespace='teacher')),

    # Student Panel
    path('student/', include(('student.urls', 'student'), namespace='student')),

    # ✅ NEW: Admin Panel (CUSTOM)
    path('adminpanel/', include(('adminpanel.urls', 'adminpanel'), namespace='adminpanel')),
]

# Serve media files in development
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)