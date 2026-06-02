from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

urlpatterns = [
    path('admin/', admin.site.urls),
    path('accounts/', include('accounts.urls')),
    path('exams/', include('exams.urls')),
    path('slips/', include('slips.urls')),
    path('system/', include('dashboard.admin_urls', namespace='system')),
    path('api/v1/', include('dashboard.api_urls')),
    path('', include('dashboard.urls')),
]

if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
