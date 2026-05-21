from django.db import models
from django.contrib.auth.models import User

class Profile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_teacher = models.BooleanField(default=False)
    
    def __str__(self):
        return self.user.username


class Student(models.Model):
    """ 
        Guarda as informacoes sobre o aluno
        
        - Nome: nome completo do aluno
        - registration_id: matricula do aluno
        - face_encoding: array do face_recognition
        - created_at: data de cadastro do aluno
    """
    
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')
    registration_id = models.CharField(max_length=20, unique=True)
    face_encoding = models.JSONField()
    created_at = models.DateTimeField(auto_now_add=True)
    profile_photo = models.ImageField(upload_to='faces/', null=True, blank=True)
    
    def __str__(self):
        return self.user.get_full_name() or self.user.username
    
class Classroom(models.Model):
    """
        Guarda as informacoes sobre a disciplina
        
        - subject: o nome da disciplina
        - teacher: professor responsavel
        - active_now: disciplina em atividade
        
    """
    subject = models.CharField(max_length=100)
    teacher = models.CharField(max_length=100)
    active_now = models.BooleanField(default=False)
    
    enrolled_students = models.ManyToManyField(Student, blank=True, related_name='my_classes')
    
    def __str__(self):
        return self.subject


class Attendance(models.Model):
    """
        Tabela transacional para conectar aluno a uma turma especifica
        
        student: id do aluno
        classroom: disciplina vinculada
        timestamp: data e hora do reconhecimento pelo totem
        liveness_score: pontuacao do algoritmo de liveness
        is_valid: resultado do liveness
        direction: sentido do movimento (ENTRADA ou SAÍDA)
    """
    
    DIRECTION_CHOICES = [
        ('ENTRADA', 'Entrada (Esquerda para Direita)'),
        ('SAÍDA', 'Saída (Direita para Esquerda)'),
    ]
    
    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name='attendances')
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, related_name='attendance_records')
    timestamp = models.DateTimeField(auto_now_add=True)
    liveness_score = models.FloatField()
    is_valid = models.BooleanField(default=False)
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, default='ENTRADA')
    
    class Meta:
        ordering = ['-timestamp']
    
    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.direction} - {self.timestamp}"