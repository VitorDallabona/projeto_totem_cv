from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import StudentRegistrationForm
from .models import Student, Attendance, Classroom
from django.utils import timezone
from django.http import StreamingHttpResponse, HttpResponse, JsonResponse
import json
from django.conf import settings
import os
import threading
import time
from .forms import ClassroomForm

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


latest_processed_frame = None
latest_frame_lock = threading.Lock()


def get_placeholder_frame_bytes():
    import cv2

    img = np.zeros((480, 640, 3), dtype=np.uint8)
    cv.putText(
        img,
        'Aguardando camera local...',
        (90, 230),
        cv.FONT_HERSHEY_SIMPLEX,
        0.8,
        (255, 255, 255),
        2,
    )
    sucesso, buffer = cv2.imencode('.jpg', img)
    return buffer.tobytes() if sucesso else b''



@login_required
def create_classroom(request):
    # Proteção: Apenas professores ou admins
    is_teacher = (hasattr(request.user, 'profile') and request.user.profile.is_teacher) or request.user.is_superuser
    if not is_teacher:
        messages.error(request, 'Acesso negado. Apenas professores podem criar novas turmas.')
        return redirect('/')

    if request.method == 'POST':
        form = ClassroomForm(request.POST)
        if form.is_valid():
            classroom = form.save(commit=False)
            
            classroom.teacher = request.user 
            
            classroom.save()
            form.save_m2m()
            messages.success(request, f'Turma "{classroom.subject}" cadastrada com sucesso!')
            return redirect('/') # Redireciona para o dashboard
    else:
        form = ClassroomForm(initial={'teacher': request.user})

    return render(request, 'students/create_classroom.html', {'form': form})


@login_required
def manage_class_students(request, class_id):
    classroom = get_object_or_404(Classroom, id=class_id)
    
    is_teacher = (hasattr(request.user, 'profile') and request.user.profile.is_teacher) or request.user.is_superuser
    if not is_teacher:
        messages.error(request, 'Acesso negado.')
        return redirect('/')

    if request.method == 'POST':
        #pega a lista de IDs enviados pelo modal
        selected_student_ids = request.POST.getlist('students_vinc')
        classroom.enrolled_students.set(selected_student_ids)
        
        messages.success(request, f'Lista de alunos da turma "{classroom.subject}" atualizada!')
        return redirect(f'/?class_id={classroom.id}')
        
    return redirect('/')



def video_feed(request):
    """Retorna o stream MJPEG com o último frame processado pela IA."""
    def generate_frames():
        try:
            import cv2
            placeholder_bytes = get_placeholder_frame_bytes()
            while True:
                with latest_frame_lock:
                    frame_bytes = latest_processed_frame or placeholder_bytes

                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                time.sleep(0.08)
        
        except Exception as e:
            print(f"Erro no video_feed: {e}")
    
    # Retorna o vídeo em streaming constante para a tag <img> do HTML
    return StreamingHttpResponse(
        generate_frames(),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )


def process_local_camera_frame(request):
    if request.method != 'POST':
        return JsonResponse({'error': 'Método não permitido.'}, status=405)

    if ia_system is None:
        return JsonResponse({'error': 'IA indisponível no momento.'}, status=503)

    uploaded_frame = request.FILES.get('frame')
    if not uploaded_frame:
        return JsonResponse({'error': 'Nenhum frame recebido.'}, status=400)

    try:
        frame_bytes = np.frombuffer(uploaded_frame.read(), dtype=np.uint8)
        frame = cv.imdecode(frame_bytes, cv.IMREAD_COLOR)

        if frame is None:
            return JsonResponse({'error': 'Não foi possível ler a imagem enviada.'}, status=400)

        frame = cv.flip(frame, 1)
        frame_processado = ia_system.run_recognition(frame)

        sucesso, buffer = cv.imencode('.jpg', frame_processado)
        if not sucesso:
            return JsonResponse({'error': 'Falha ao codificar o frame processado.'}, status=500)

        global latest_processed_frame
        with latest_frame_lock:
            latest_processed_frame = buffer.tobytes()

        return JsonResponse({'ok': True})
    except Exception as e:
        return JsonResponse({'error': f'Falha ao processar frame: {e}'}, status=500)

def register_student(request):
    if request.method == 'POST':
        form = StudentRegistrationForm(request.POST, request.FILES)
        
        if form.is_valid():
            matricula = form.cleaned_data['registration_id']
            
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
                uploaded_file = request.FILES['profile_photo']
                img = Image.open(uploaded_file)
                img = ImageOps.exif_transpose(img)
                img = img.convert('RGB')
                img_array = np.array(img)
                
                encodings = face_recognition.face_encodings(img_array)
                
                if encodings:
                    student.face_encoding = encodings[0].tolist() 
                    student.save()
                    
                    # Mensagem de Sucesso salva na sessão
                    messages.success(request, 'Cadastro realizado com sucesso! Faça login abaixo para continuar.')
                    return redirect('login') 
                else:
                    user.delete()
                    messages.error(request, 'Rosto não detectado. Envie uma foto nítida e bem iluminada.')
                    return render(request, 'students/register.html', {'form': form})
            
            except Exception as e:
                user.delete()
                messages.error(request, f'Erro ao processar a imagem: {str(e)}')
                return render(request, 'students/register.html', {'form': form})
        else:
            # Captura os erros reais do formulário (ex: Matrícula já existe) e exibe como alertas
            for field, erros in form.errors.items():
                for erro in erros:
                    messages.warning(request, erro)
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
        return redirect('student_absences') if hasattr(request.user, 'student_profile') else redirect('/')
        
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
                matricula = student.user.username
                
                #remove qualquer variação antiga (jpg, jpeg, png) da mesma matrícula
                if student.profile_photo:
                    try:
                        diretorio = os.path.dirname(student.profile_photo.path)
                        if os.path.exists(diretorio):
                            for arquivo in os.listdir(diretorio):
                                # Extrai o nome do arquivo sem a extensão e compara com a matrícula
                                nome_arquivo, _ = os.path.splitext(arquivo)
                                if nome_arquivo == matricula:
                                    os.remove(os.path.join(diretorio, arquivo))
                    except Exception as e:
                        print(f"Erro ao limpar arquivos antigos no disco: {e}")
                
                #salva a nova foto e atualiza o banco de dados
                novo_encoding = encodings[0].tolist()
                student.profile_photo = photo
                student.face_encoding = novo_encoding
                student.save()  # Salva primeiro para o Django gerar o nome definitivo do arquivo
                
                #Removendo chaves antigas com outras extensões do JSON
                caminho_cache = os.path.join(settings.MEDIA_ROOT, 'faces', 'encodes.json')
                
                if os.path.exists(caminho_cache):
                    try:
                        with open(caminho_cache, 'r') as f:
                            cache_ia = json.load(f)
                        
                        # Procura e elimina qualquer chave antiga ligada a essa matrícula (ex: 202601.jpeg)
                        chaves_para_remover = [k for k in cache_ia if os.path.splitext(k)[0] == matricula]
                        for k in chaves_para_remover:
                            del cache_ia[k]
                        
                        # Define o novo registro usando o nome exato gerado pelo storage do Django (ex: 202601.jpg)
                        nome_arquivo_salvo = os.path.basename(student.profile_photo.name)
                        cache_ia[nome_arquivo_salvo] = novo_encoding
                        
                        with open(caminho_cache, 'w') as f:
                            json.dump(cache_ia, f)
                            
                        # Se o Totem estiver ativo em memória, recarrega o dicionário limpo
                        if 'ia_system' in globals() and ia_system is not None and hasattr(ia_system, 'atualizar_banco_rostos'):
                            ia_system.atualizar_banco_rostos()
                            
                    except Exception as e:
                        print(f"Erro ao injetar biometria no cache: {e}")
                
                messages.success(request, 'Biometria facial atualizada com sucesso!')
                return redirect('student_absences') if is_own_student else redirect('/')
            else:
                messages.error(request, 'Nenhum rosto detectado na nova foto. Tente uma foto mais iluminada.')
                return render(request, 'students/update_photo.html', {'student': student})
        except Exception as e:
            messages.error(request, f'Erro ao processar: {e}')
            return render(request, 'students/update_photo.html', {'student': student})

    return render(request, 'students/update_photo.html', {'student': student})