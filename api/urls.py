from django.urls import path
from . import views

urlpatterns = [
    path('check-presence/', views.mock_check_presence, name='mock_check_presence')
]