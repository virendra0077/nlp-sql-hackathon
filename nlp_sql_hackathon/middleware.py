"""
re_insight/middleware.py — Global login guard.
Redirects unauthenticated users to /login/ for every request
except login, logout, health, and the Django admin.
"""

from django.shortcuts import redirect
from django.conf import settings


class LoginRequiredMiddleware:
    # Use plain path strings — never call reverse() here.
    # reverse() triggers URL resolution before Django's app registry
    # is fully loaded, which causes ImproperlyConfigured errors.
    EXEMPT_PREFIXES = ("/admin/", "/login/", "/logout/")
    EXEMPT_EXACT    = {"/health"}

    def __init__(self, get_response):
        self.get_response = get_response

    def _is_exempt(self, path: str) -> bool:
        if path in self.EXEMPT_EXACT:
            return True
        return any(path.startswith(p) for p in self.EXEMPT_PREFIXES)

    def __call__(self, request):
        if not request.user.is_authenticated and not self._is_exempt(request.path):
            login_url = getattr(settings, "LOGIN_URL", "/login/")
            return redirect(f"{login_url}?next={request.path}")
        return self.get_response(request)