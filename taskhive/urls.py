from django.urls import path, include

from django.conf import settings
from django.conf.urls.static import static

from core.admin import taskhive_admin

urlpatterns = [
    path("admin/", taskhive_admin.urls),
    path("", include("core.urls")),
]

handler404 = "core.views.error_404"
handler500 = "core.views.error_500"

# ✅ serve uploaded files in dev
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
