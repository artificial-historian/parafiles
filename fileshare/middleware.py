from __future__ import annotations

from django.conf import settings
from django.shortcuts import redirect
from django.urls import reverse
from django.utils.http import urlencode

from django_otp import user_has_device


class StaffTwoFactorRequiredMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if not getattr(settings, "PARAFILES_ADMIN_2FA_REQUIRED", False):
            return self.get_response(request)

        user = getattr(request, "user", None)
        if not user or not user.is_authenticated or not user.is_staff:
            return self.get_response(request)

        is_verified = getattr(user, "is_verified", lambda: False)
        if is_verified():
            return self.get_response(request)

        allowed_paths = {
            reverse("staff_2fa_setup"),
            reverse("staff_2fa_verify"),
            reverse("login"),
            reverse("logout"),
        }
        path = request.path_info
        static_url = settings.STATIC_URL
        if not static_url.startswith("/"):
            static_url = "/" + static_url
        if path in allowed_paths or path.startswith(static_url):
            return self.get_response(request)

        target = reverse("staff_2fa_verify") if user_has_device(user) else reverse("staff_2fa_setup")
        query = urlencode({"next": request.get_full_path()})
        return redirect(f"{target}?{query}")


class SecurityHeadersMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        csp = getattr(settings, "PARAFILES_CONTENT_SECURITY_POLICY", "")
        if csp:
            response.setdefault("Content-Security-Policy", csp)
        response.setdefault("Referrer-Policy", "same-origin")
        response.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.setdefault("X-Content-Type-Options", "nosniff")
        return response
