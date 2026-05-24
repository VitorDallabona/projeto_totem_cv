from django import forms
from django.contrib.auth.models import User
from .models import Student
from .models import Classroom


class StudentRegistrationForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30)
    last_name = forms.CharField(max_length=30)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
    
    class Meta:
        model = Student
        fields = ['registration_id', 'profile_photo']
        
        error_messages = {
            'registration_id': {
                'unique': 'Esta matrícula já está cadastrada no sistema. Faça login para acessar seu painel.',
            }
        }
        
        
        def clean_registration_id(self):
            matricula = self.cleaned_data.get('registration_id')
            
            # Verifica na tabela de Login (User) se a matrícula já existe
            if User.objects.filter(username=matricula).exists():
                raise forms.ValidationError("Esta matrícula já está cadastrada no sistema. Faça login para acessar seu painel.")
                
            return matricula
        
        
        
class ClassroomForm(forms.ModelForm):
    class Meta:
        model = Classroom
        fields = ['subject', 'teacher', 'total_hours', 'start_time', 'end_time', 'enrolled_students']
        labels = {
            'subject': 'Nome da Disciplina',
            'teacher': 'Professor Responsável',
            'total_hours': 'Carga Horária Total (horas)',
            'start_time': 'Horário de Início',
            'end_time': 'Horário de Término',
            'enrolled_students': 'Vincular Alunos à Turma',
        }
        widgets = {
            'start_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
            'end_time': forms.TimeInput(format='%H:%M', attrs={'type': 'time'}),
            'enrolled_students': forms.CheckboxSelectMultiple(),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ajusta a exibição da lista de alunos para Nome (Matrícula)
        self.fields['enrolled_students'].queryset = Student.objects.all().order_by('user__first_name')
        self.fields['enrolled_students'].label_from_instance = lambda obj: f"{obj.user.get_full_name()} ({obj.registration_id})"