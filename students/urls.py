from django.urls import path
from . import views
from core.views import student_absences

urlpatterns = [
    path('register/', views.register_student, name='register'),
    path('painel/', student_absences, name='student_absences'),
    path('update-photo/<int:student_id>/', views.update_student_photo, name='update_student_photo'),
]
