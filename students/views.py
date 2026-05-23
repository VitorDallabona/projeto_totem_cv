from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from .forms import StudentRegistrationForm
from .models import Student, Attendance, Classroom
from django.utils import timezone
from django.http import StreamingHttpResponse
import json
from django.conf import settings
import os

# Imports pesados - comentados para migrations rodarem
try:
    import face_recognition
    import numpy as np
    from PIL import Image, ImageOps, ImageDraw
    import cv2 as cv
    from .ia import FaceRecognition
    
    # Inicia a rede neural na memória UMA VEZ
    print("Carregando Modelos de IA na GPU...")
    ia_system = FaceRecognition('media/faces')
except ImportError as e:
    print(f"⚠️  Aviso: Algumas dependências não estão instaladas: {e}")
    print("   Use isso para debugar apenas, migrations funcionam normalmente")
    ia_system = None



def video_feed(request):
    """Endpoint de câmera - retorna stream de vídeo para o HTML"""
    def generate_frames():
        try:
            import cv2
            
            # Se ia_system é None, retorna imagem preta com mensagem
            if ia_system is None:
                from PIL import Image, ImageDraw
                import numpy as np
                
                img = Image.new('RGB', (640, 480), color='black')
                draw = ImageDraw.Draw(img)
                draw.text((180, 220), "Câmera/IA não disponível", fill='white')
                
                img_array = np.array(img)
                ret, buffer = cv2.imencode('.jpg', img_array)
                frame_bytes = buffer.tobytes()
                
                while True:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                return
            
            # --- AQUI ESTÁ A MÁGICA ---
            # O número 0 diz para o OpenCV usar a câmera embutida do notebook
            camera = cv2.VideoCapture(0)
            
            while True:
                ret, frame = camera.read()
                
                if not ret:
                    break
                
                # Opcional: Espelha a câmera para o movimento ficar natural
                frame = cv2.flip(frame, 1)
                
                # Processa com a IA
                frame_processado = ia_system.run_recognition(frame)
                
                # Codifica o frame final (com as caixas da IA) para JPEG
                ret, buffer = cv2.imencode('.jpg', frame_processado)
                frame_bytes = buffer.tobytes()
                
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        
        except Exception as e:
            print(f"Erro no video_feed: {e}")
    
    # Retorna o vídeo em streaming constante para a tag <img> do HTML
    return StreamingHttpResponse(
        generate_frames(),
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
            
            user = User.objects.create_user(
                username=matricula,
                email=form.cleaned_data['email'],
                password=form.cleaned_data['password'],
                first_name=form.cleaned_data['first_name'],
                last_name=form.cleaned_data['last_name']
            )
            
            student = form.save(commit=False)
            student.user = user
            
            try:
                # --- RECUPERANDO A CORREÇÃO DE EXIF/PILLOW ---
                uploaded_file = request.FILES['profile_photo']
                img = Image.open(uploaded_file)
                img = ImageOps.exif_transpose(img)
                img = img.convert('RGB')
                img_array = np.array(img)
                
                encodings = face_recognition.face_encodings(img_array)
                
                if encodings:
                    student.face_encoding = encodings[0].tolist() 
                    student.save()
                    return redirect('login')
                else:
                    user.delete() 
                    return render(request, 'students/register.html', {'form': form, 'error': 'Nenhum rosto detectado na foto.'})
            
            except Exception as e:
                user.delete() 
                return render(request, 'students/register.html', {
                    'form': form, 
                    'error': f'Erro ao processar a imagem: {str(e)}'
                })
    else:
        form = StudentRegistrationForm()
    return render(request, 'students/register.html', {'form': form})


@login_required
def update_student_photo(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    
    # É professor ou Admin?
    is_teacher_or_admin = (hasattr(request.user, 'profile') and request.user.profile.is_teacher) or request.user.is_superuser
    # É o próprio aluno acessando o próprio perfil?
    is_own_student = hasattr(request.user, 'student_profile') and request.user.student_profile.id == student.id
    
    if not (is_teacher_or_admin or is_own_student):
        # Bloqueia se um aluno tentar alterar a foto de OUTRO aluno
        return redirect('student_absences') if hasattr(request.user, 'student_profile') else redirect('teacher_dashboard')
        
    if request.method == 'POST' and request.FILES.get('new_photo'):
        try:
            photo = request.FILES['new_photo']
            img = Image.open(photo)
            img = ImageOps.exif_transpose(img)
            img = img.convert('RGB')
            img_array = np.array(img)
            
            # Validação rápida de rosto
            encodings = face_recognition.face_encodings(img_array)
            
            if encodings:
                student.profile_photo = photo
                student.face_encoding = encodings[0].tolist()
                student.save()
                
                # integração com o totem
                # Apaga o cache para forçar o encodes.py a rodar com GPU na nova foto
                caminho_cache = os.path.join(settings.MEDIA_ROOT, 'faces', 'encodes.json')
                if os.path.exists(caminho_cache):
                    try:
                        os.remove(caminho_cache)
                    except Exception as e:
                        print(f"Erro ao limpar cache: {e}")
                
                # redirecionamento
                if is_own_student:
                    return redirect('student_absences')
                else:
                    return redirect('teacher_dashboard')
            else:
                return render(request, 'students/update_photo.html', {
                    'student': student, 
                    'error': 'Nenhum rosto detectado na nova foto. Tente uma foto mais iluminada.'
                })
        except Exception as e:
            return render(request, 'students/update_photo.html', {
                'student': student, 
                'error': f'Erro ao processar: {e}'
            })

    return render(request, 'students/update_photo.html', {'student': student})