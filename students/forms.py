from django import forms
from django.contrib.auth.models import User
from .models import Student


class StudentRegistrationForm(forms.ModelForm):
    first_name = forms.CharField(max_length=30)
    last_name = forms.CharField(max_length=30)
    email = forms.EmailField()
    password = forms.CharField(widget=forms.PasswordInput)
    
    class Meta:
        model = Student
        fields = ['registration_id', 'profile_photo']