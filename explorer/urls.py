from django.urls import path
from . import views

urlpatterns = [
    path("",                              views.explorer_ui,   name="explorer_ui"),
    path("tables",                        views.list_tables,   name="explorer_tables"),
    path("filter-options/<str:table>",    views.filter_options, name="explorer_filter_options"),
    path("data/<str:table>",              views.table_data,    name="explorer_data"),
]