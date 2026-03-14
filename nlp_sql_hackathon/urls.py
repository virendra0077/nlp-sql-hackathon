"""re_insight/urls.py — root URL configuration."""

from django.contrib import admin
from django.urls import path, include
from django.contrib.auth import views as auth_views
from agent import views as agent_views

urlpatterns = [
    # ── Admin ─────────────────────────────────────────────────────────────────
    path("admin/", admin.site.urls),

    # ── Auth ──────────────────────────────────────────────────────────────────
    path("login/",  auth_views.LoginView.as_view(template_name="login.html"),  name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),

    # ── Main chat UI ──────────────────────────────────────────────────────────
    path("", agent_views.index, name="index"),

    # ── Agent API ─────────────────────────────────────────────────────────────
    path("ask",     agent_views.ask,     name="ask"),
    path("run-sql", agent_views.run_sql, name="run_sql"),

    # ── Debug endpoints ───────────────────────────────────────────────────────
    path("debug/assets",         agent_views.debug_assets,        name="debug_assets"),
    path("debug/price-headers",  agent_views.debug_price_headers, name="debug_price_headers"),
    path("debug/sales-check",    agent_views.debug_sales_check,   name="debug_sales_check"),

    # ── Health ────────────────────────────────────────────────────────────────
    path("health", agent_views.health, name="health"),

    # ── Explorer ──────────────────────────────────────────────────────────────
    path("explorer/", include("explorer.urls")),
]