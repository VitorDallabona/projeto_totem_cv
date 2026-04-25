from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from .forms import StudentRegistrationForm
import face_recognition
import json

def register_student(request):
    if request.method == 'POST':
        form  = StudentRegistrationForm(request.POST, request.FILES)
        if form.is_valid():
            
            matricula = form.cleaned_data['registration_id']
            if User.objects.filter(username=matricula).exists():
                return render(request, 'students/register.html', {
                    'form': form, 
                    'error': 'Esta matrícula já está cadastrada no sistema.'
                })
            
            #cria o usuário base
            user = User.objects.create_user(
                username=matricula,
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name']
            )
            
            #cria o aluno e processa a imagem
            student = form.save(commit=False)
            student.user = user
            
            try:
                image = face_recognition.load_image_file(request.FILES['profile_photo'])
                encodings = face_recognition.face_encodings(image)
                
                if encodings:
                    student.face_encoding = encodings[0].tolist() #converte pra lista JSON
                    student.save()
                    return redirect('login')
                else:
                    user.delete() #remove o user se a fato não tiver rosto
                    return render(request, 'students/register.html', {'form': form, 'error': 'Nenhum rosto detectado na foto.'})
            
            except Exception as e:
                user.delete() #se der erro na leitura do arquivo, apaga o usuário gerado
                return render(request, 'students/register.html', {
                    'form': form, 
                    'error': f'Erro ao processar a imagem: {str(e)}'
                })
    else:
        form = StudentRegistrationForm()
    return render(request, 'students/register.html', {'form': form})

