import base64
import csv
import json
import os
from datetime import date, datetime, timedelta

import cv2 as cv
import numpy as np
from numpy.linalg import norm
from PIL import Image, ImageDraw, ImageOps

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User
from django.http import HttpResponse, JsonResponse, StreamingHttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt

from .forms import ClassroomForm, StudentRegistrationForm
from .models import Attendance, Classroom, Student

# Importa a IA global e a função de normalização
from .ia import face_app, ia_system, normalizar_iluminacao

# =========================================================================
# VISTAS / ROTAS DO APP STUDENTS
# =========================================================================

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
            return redirect('/') 
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
        selected_student_ids = request.POST.getlist('students_vinc')
        classroom.enrolled_students.set(selected_student_ids)
        messages.success(request, f'Lista de alunos da turma "{classroom.subject}" atualizada!')
        return redirect(f'/?class_id={classroom.id}')
        
    return redirect('/')


def video_feed(request):
    """Endpoint de câmera - retorna stream de vídeo para o HTML"""
    def generate_frames():
        try:
            if ia_system is None:
                img = Image.new('RGB', (640, 480), color='black')
                draw = ImageDraw.Draw(img)
                draw.text((180, 220), "Câmera/IA não disponível", fill='white')
                img_array = np.array(img)
                ret, buffer = cv.imencode('.jpg', img_array)
                frame_bytes = buffer.tobytes()
                while True:
                    yield (b'--frame\r\n'
                           b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
                return
            
            camera = cv.VideoCapture(0)
            while True:
                ret, frame = camera.read()
                if not ret: break
                frame = cv.flip(frame, 1)
                frame_processado = ia_system.run_recognition(frame)
                ret, buffer = cv.imencode('.jpg', frame_processado)
                frame_bytes = buffer.tobytes()
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame_bytes + b'\r\n')
        except Exception as e:
            print(f"Erro no video_feed: {e}")
    
    return StreamingHttpResponse(
        generate_frames(),
        content_type='multipart/x-mixed-replace; boundary=frame'
    )

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
                # Alterado para aceitar múltiplas fotos
                files = request.FILES.getlist('profile_photo')
                if not files:
                    raise ValueError("Nenhuma foto enviada.")

                embeddings_coletados = []
                pesos_coletados = []
                caminhos_salvos = []

                # Prepara o diretório exclusivo do aluno
                diretorio_aluno = os.path.join(settings.MEDIA_ROOT, 'faces', matricula)
                os.makedirs(diretorio_aluno, exist_ok=True)

                for idx, photo in enumerate(files):
                    img = Image.open(photo)
                    img = ImageOps.exif_transpose(img).convert('RGB')
                    img_array = np.array(img)
                    img_bgr = cv.cvtColor(img_array, cv.COLOR_RGB2BGR)
                    
                    # 1. APLICA CLAHE EM CADA FOTO ENVIADA
                    img_bgr_norm = normalizar_iluminacao(img_bgr)
                    faces = face_app.get(img_bgr_norm)
                    
                    if faces:
                        face = faces[0]
                        emb = face.embedding
                        n = norm(emb)
                        emb_norm = emb / n if n > 0 else emb
                        
                        embeddings_coletados.append(emb_norm)
                        pesos_coletados.append(max(float(getattr(face, "det_score", 1.0)), 1e-6))
                        
                        # Define extensão e nome do arquivo (ex: foto_0.jpg)
                        ext = photo.name.split('.')[-1]
                        if ext.lower() not in ['jpg', 'jpeg', 'png']:
                            ext = 'jpg'
                        
                        nome_arquivo = f"foto_{idx}.{ext}"
                        caminho_salvamento = os.path.join(diretorio_aluno, nome_arquivo)
                        
                        # Grava a foto fisicamente no disco
                        img.save(caminho_salvamento, format="JPEG" if ext.lower() in ['jpg', 'jpeg'] else ext.upper())
                        
                        # Armazena o caminho relativo para associar no ImageField do Django
                        caminho_relativo = os.path.join('faces', matricula, nome_arquivo)
                        caminhos_salvos.append(caminho_relativo)

                if embeddings_coletados and caminhos_salvos:
                    # Salva a lista de todos os embeddings coletados para comparação Multi-Template
                    embeddings_salvar = [emb.tolist() for emb in embeddings_coletados]
                    
                    # Define a foto_0 (frontal) como o avatar/profile_photo
                    student.profile_photo = caminhos_salvos[0]
                    student.face_encoding = embeddings_salvar
                    student.save()

                    # Injeta a biometria no cache consolidado
                    caminho_cache = os.path.join(settings.MEDIA_ROOT, 'faces', 'encodes.json')
                    if os.path.exists(caminho_cache):
                        try:
                            with open(caminho_cache, 'r') as f:
                                cache_ia = json.load(f)
                            
                            # Limpa chaves antigas com ou sem extensão
                            chaves_para_remover = [k for k in cache_ia if k == matricula or os.path.splitext(k)[0] == matricula]
                            for k in chaves_para_remover:
                                del cache_ia[k]
                            
                            # Grava usando a matrícula limpa como chave e a lista de embeddings
                            cache_ia[matricula] = embeddings_salvar
                            with open(caminho_cache, 'w') as f:
                                json.dump(cache_ia, f, indent=4)
                                
                            if 'ia_system' in globals() and ia_system is not None and hasattr(ia_system, 'atualizar_banco_rostos'):
                                ia_system.atualizar_banco_rostos()
                        except Exception as e:
                            print(f"Erro ao injetar biometria no cache: {e}")

                    messages.success(request, 'Cadastro realizado com sucesso! Faça login abaixo para continuar.')
                    return redirect('login') 
                else:
                    user.delete()
                    messages.error(request, 'Rosto não detectado nas fotos. Envie fotos nítidas e bem iluminadas.')
                    return render(request, 'students/register.html', {'form': form})
            except Exception as e:
                user.delete()
                messages.error(request, f'Erro ao processar as imagens: {str(e)}')
                return render(request, 'students/register.html', {'form': form})
        else:
            for field, erros in form.errors.items():
                for erro in erros: messages.warning(request, erro)
    else:
        form = StudentRegistrationForm()
        
    return render(request, 'students/register.html', {'form': form})

@login_required
def update_student_photo(request, student_id):
    student = get_object_or_404(Student, id=student_id)
    
    is_teacher_or_admin = (hasattr(request.user, 'profile') and request.user.profile.is_teacher) or request.user.is_superuser
    is_own_student = hasattr(request.user, 'student_profile') and request.user.student_profile.id == student.id
    
    if not (is_teacher_or_admin or is_own_student):
        return redirect('student_absences') if hasattr(request.user, 'student_profile') else redirect('/')
        
    if request.method == 'POST':
        # getlist garante compatibilidade quer o usuário envie 1 ou 5 fotos
        files = request.FILES.getlist('new_photo')
        
        if not files:
            messages.error(request, 'Nenhuma foto enviada.')
            return render(request, 'students/update_photo.html', {'student': student})

        try:
            matricula = student.user.username
            embeddings_coletados = []
            pesos_coletados = []
            caminhos_salvos = []

            # Prepara o diretório exclusivo do aluno
            diretorio_aluno = os.path.join(settings.MEDIA_ROOT, 'faces', matricula)
            
            # Limpeza de fotos antigas na pasta do aluno
            if os.path.exists(diretorio_aluno):
                try:
                    for arquivo in os.listdir(diretorio_aluno):
                        if arquivo.lower().endswith(('.png', '.jpg', '.jpeg')):
                            os.remove(os.path.join(diretorio_aluno, arquivo))
                except Exception as e:
                    print(f"Erro ao limpar arquivos antigos na pasta do aluno: {e}")
            else:
                os.makedirs(diretorio_aluno, exist_ok=True)
            
            for idx, photo in enumerate(files):
                img = Image.open(photo)
                img = ImageOps.exif_transpose(img).convert('RGB')
                img_array = np.array(img)
                img_bgr = cv.cvtColor(img_array, cv.COLOR_RGB2BGR)
                
                # 1. APLICA CLAHE EM CADA FOTO ENVIADA
                img_bgr_norm = normalizar_iluminacao(img_bgr)
                faces = face_app.get(img_bgr_norm)
                
                if faces:
                    face = faces[0]
                    emb = face.embedding
                    n = norm(emb)
                    emb_norm = emb / n if n > 0 else emb
                    
                    embeddings_coletados.append(emb_norm)
                    pesos_coletados.append(max(float(getattr(face, "det_score", 1.0)), 1e-6))
                    
                    # Define extensão e nome do arquivo (ex: foto_0.jpg)
                    ext = photo.name.split('.')[-1]
                    if ext.lower() not in ['jpg', 'jpeg', 'png']:
                        ext = 'jpg'
                    
                    nome_arquivo = f"foto_{idx}.{ext}"
                    caminho_salvamento = os.path.join(diretorio_aluno, nome_arquivo)
                    
                    # Grava a foto fisicamente no disco
                    img.save(caminho_salvamento, format="JPEG" if ext.lower() in ['jpg', 'jpeg'] else ext.upper())
                    
                    caminho_relativo = os.path.join('faces', matricula, nome_arquivo)
                    caminhos_salvos.append(caminho_relativo)
            
            if embeddings_coletados and caminhos_salvos:
                # Salva a lista de todos os embeddings coletados para comparação Multi-Template
                embeddings_salvar = [emb.tolist() for emb in embeddings_coletados]
                
                # Remove também qualquer arquivo de imagem avulso na raiz de faces/ que represente a matrícula
                for ext_antiga in ['jpg', 'jpeg', 'png']:
                    caminho_raiz_antigo = os.path.join(settings.MEDIA_ROOT, 'faces', f"{matricula}.{ext_antiga}")
                    if os.path.exists(caminho_raiz_antigo):
                        try: os.remove(caminho_raiz_antigo)
                        except Exception: pass
                
                # Define a foto_0 (frontal) como o avatar/profile_photo
                student.profile_photo = caminhos_salvos[0]
                student.face_encoding = embeddings_salvar
                student.save() 
                
                caminho_cache = os.path.join(settings.MEDIA_ROOT, 'faces', 'encodes.json')
                if os.path.exists(caminho_cache):
                    try:
                        with open(caminho_cache, 'r') as f:
                            cache_ia = json.load(f)
                        
                        # Limpa chaves antigas com ou sem extensão
                        chaves_para_remover = [k for k in cache_ia if k == matricula or os.path.splitext(k)[0] == matricula]
                        for k in chaves_para_remover: del cache_ia[k]
                        
                        # Grava usando a matrícula limpa como chave e a lista de embeddings
                        cache_ia[matricula] = embeddings_salvar
                        with open(caminho_cache, 'w') as f: json.dump(cache_ia, f, indent=4)
                            
                        if 'ia_system' in globals() and ia_system is not None and hasattr(ia_system, 'atualizar_banco_rostos'):
                            ia_system.atualizar_banco_rostos()
                    except Exception as e:
                        print(f"Erro ao injetar biometria no cache: {e}")
                
                messages.success(request, f'Biometria facial atualizada com sucesso utilizando {len(embeddings_coletados)} amostra(s)!')
                return redirect('student_absences') if is_own_student else redirect('/')
            else:
                messages.error(request, 'Nenhum rosto detectado nas novas fotos. Tente fotos mais iluminadas.')
                return render(request, 'students/update_photo.html', {'student': student})
        except Exception as e:
            messages.error(request, f'Erro ao processar: {e}')
            return render(request, 'students/update_photo.html', {'student': student})

    return render(request, 'students/update_photo.html', {'student': student})

@csrf_exempt
def processar_frame_camera(request):
    if request.method == 'POST':
        image_data = request.POST.get('image')
        class_id = request.POST.get('class_id')

        if not class_id:
            return JsonResponse({"status": "erro", "mensagem": "Turma não informada."}, status=400)
        try:
            classroom = Classroom.objects.get(id=class_id)
        except Classroom.DoesNotExist:
            return JsonResponse({"status": "erro", "mensagem": "Turma não encontrada."}, status=400)
        if not classroom.active_now:
            return JsonResponse({"status": "ignorado", "mensagem": "Aula inativa."})

        if image_data:
            try:
                format, imgstr = image_data.split(';base64,')
                img_bytes = base64.b64decode(imgstr)
                np_arr = np.frombuffer(img_bytes, np.uint8)
                frame = cv.imdecode(np_arr, cv.IMREAD_COLOR)
                
                if frame is None: raise ValueError("Falha na decodificação da imagem.")

                if 'ia_system' in globals() and ia_system is not None:
                    ia_system.LINHA_VIRTUAL_X = frame.shape[1] // 2
                    faces_out, deve_atualizar_tela = ia_system.run_recognition_get_data(frame)
                    rostos_reconhecidos = [f['name'].split(" ")[0] for f in faces_out if "Unknown" not in f['name'] and f['color'] == '#00FF00']

                    return JsonResponse({
                        "status": "sucesso", 
                        "rostos_processados": len(faces_out),
                        "reconhecidos": rostos_reconhecidos,
                        "atualizar_tela": deve_atualizar_tela, 
                        "faces": faces_out,
                        "image_w": frame.shape[1],
                        "image_h": frame.shape[0]
                    })
                else:
                    return JsonResponse({"status": "erro", "mensagem": "Sistema de IA não carregado."}, status=500)
            except Exception as e:
                print(f"ERRO NA IA: {str(e)}")
                return JsonResponse({"status": "erro", "mensagem": str(e)}, status=400)
                
    return JsonResponse({"status": "invalido"}, status=400)