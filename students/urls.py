from django.urls import path
from . import views
from core.views import student_absences

urlpatterns = [
    path('register/', views.register_student, name='register'),
    path('painel/', student_absences, name='student_absences'),
    path('update-photo/<int:student_id>/', views.update_student_photo, name='update_student_photo'),
    path('video_feed/', views.video_feed, name='video_feed'),
    path('nova-turma/', views.create_classroom, name='create_classroom'),
    path('turma/<int:class_id>/alunos/', views.manage_class_students, name='manage_class_students'),
    path('processar-frame/', views.processar_frame_camera, name='process_frame'),
]
