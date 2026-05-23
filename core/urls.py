from django.urls import path
from . import views

urlpatterns = [
    path('', views.teacher_dashboard, name='dashboard'),
    path('dados-recentes/', views.recent_attendances_api, name='recent_attendances_api'),
    path('exportar-chamada/<int:class_id>/', views.export_attendance_csv, name='export_csv'),
    path('terminal-totem/', views.totem_display, name='totem_display'),
    path('class/<int:class_id>/start/', views.start_class, name='start_class'),
    path('class/<int:class_id>/end/', views.end_class, name='end_class'),
]
