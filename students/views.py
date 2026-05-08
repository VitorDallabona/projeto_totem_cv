from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from .forms import StudentRegistrationForm
import face_recognition
import json
from django.shortcuts import get_object_or_404
from PIL import Image, ImageOps
from .models import Student
import numpy as np

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



@login_required
def update_student_photo(request, student_id):
    # Garante que apenas professores acessem
    if not request.user.profile.is_teacher:
        return redirect('dashboard')
        
    student = get_object_or_404(Student, id=student_id)
    
    if request.method == 'POST' and request.FILES.get('new_photo'):
        try:
            photo = request.FILES['new_photo']
            img = Image.open(photo)
            img = ImageOps.exif_transpose(img)
            img = img.convert('RGB')
            img_array = np.array(img)
            
            encodings = face_recognition.face_encodings(img_array)
            
            if encodings:
                student.profile_photo = photo
                student.face_encoding = encodings[0].tolist()
                student.save()
                return redirect('dashboard')
            else:
                return render(request, 'students/update_photo.html', {
                    'student': student, 
                    'error': 'Nenhum rosto detectado na nova foto.'
                })
        except Exception as e:
            return render(request, 'students/update_photo.html', {
                'student': student, 
                'error': f'Erro ao processar: {e}'
            })

    return render(request, 'students/update_photo.html', {'student': student})
