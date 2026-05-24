from django.conf import settings
from django.contrib import admin
from django.urls import include, path

if settings.PARAFILES_ADMIN_2FA_REQUIRED:
    try:
        from django_otp.admin import OTPAdminSite

        admin.site.__class__ = OTPAdminSite
    except Exception:
        pass

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/", include("django.contrib.auth.urls")),
    path("", include("fileshare.urls")),
]

handler403 = "fileshare.views.permission_denied"
handler404 = "fileshare.views.page_not_found"
