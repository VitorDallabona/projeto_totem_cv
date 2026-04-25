from django.urls import path
from . import views

urlpatterns = [
    path('', views.teacher_dashboard, name='dashboard'),
    path('dados-recentes/', views.recent_attendances_api, name='recent_attendances_api')
]

