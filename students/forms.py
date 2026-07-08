from django import forms
from django.contrib.auth.models import User
from .models import Student
from .models import Classroom


class MultipleFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class StudentRegistrationForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30)
    last_name = forms.CharField(max_length=30)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
    
    class Meta:
        model = Student
        fields = ['registration_id']
        
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
        
        # ajusta a lista de professores (Mostra apenas usuários com profile.is_teacher=True)
        self.fields['teacher'].queryset = User.objects.filter(profile__is_teacher=True).order_by('first_name')
        self.fields['teacher'].label_from_instance = lambda obj: f"Prof. {obj.get_full_name()}"
        
        # ajusta a exibição da lista de alunos
        self.fields['enrolled_students'].queryset = Student.objects.all().order_by('user__first_name')
        self.fields['enrolled_students'].label_from_instance = lambda obj: f"{obj.user.get_full_name()} ({obj.registration_id})"