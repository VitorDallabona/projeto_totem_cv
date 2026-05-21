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
from django.shortcuts import render
from django.http import StreamingHttpResponse
import cv2 as cv
from .ia import FaceRecognition

# Inicia a rede neural na memória UMA VEZ
print("Carregando Modelos de IA na GPU...")
ia_system = FaceRecognition('media/faces')

def tela_monitoramento(request):
    """
    View que prepara o sistema para uma nova 
    sessão de monitoramento.
    """
    
    # Sincroniza fotos novas
    ia_system.atualizar_banco_rostos()
    
    # Reseta o estado de liveness (Real/Falso) de todos
    ia_system.resetar_cache_sessao()
    
    return render(
        request, 
        'monitoramento.html'
    )
def consumir_totem():
    """
    Conecta no Totem via rede, processa a IA e devolve para o HTML
    """
    IP_DO_TOTEM = '192.168.1.10'
    link_totem = f'http://{IP_DO_TOTEM}:4747/video'
    
    print(f"Tentando conectar no Totem: {link_totem}...")
    camera_remota = cv.VideoCapture(link_totem)
    
    while True:
        sucesso, frame = camera_remota.read()
        
        if not sucesso:
            # Se a rede oscilar, podemos colocar um print ou sleep aqui
            break
            
        # O frame que viajou pela rede entra na sua IA
        # A IA processa, desenha caixas verdes, checa spoofing, etc.
        frame_processado = ia_system.run_recognition(frame)
        
        # Re-encoda o frame final (já com os desenhos) para a Web
        ret, buffer = cv.imencode('.jpg', frame_processado)
        frame_bytes = buffer.tobytes()
        
        yield (
            b'--frame\r\n'
            b'Content-Type: image/jpeg\r\n\r\n' + 
            frame_bytes + 
            b'\r\n'
        )

def video_feed(request):
    """Endpoint chamado pela tag <img> do HTML"""
    return StreamingHttpResponse(
        consumir_totem(),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )

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
