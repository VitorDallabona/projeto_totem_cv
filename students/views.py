from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.models import User
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from .forms import StudentRegistrationForm
from .models import Student, Attendance, Classroom
from django.utils import timezone
from django.http import StreamingHttpResponse
import json
from django.http import JsonResponse
from django.conf import settings
import os
from .forms import ClassroomForm
import base64
from django.views.decorators.csrf import csrf_exempt
import cv2
import numpy as np
from datetime import timedelta

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


CACHE_BIOMETRIA = {}
CACHE_LIVENESS_VIEW = {}

def registrar_ponto(student, classroom, modo):
    """
    Máquina de Estados de Presença com Fuso Horário (Brasil) Corrigido.
    """
    agora = timezone.localtime(timezone.now())
    cooldown = agora - timedelta(minutes=2)
    
    ultimo_registro = Attendance.objects.filter(
        student=student,
        classroom=classroom,
        timestamp__date=agora.date()
    ).order_by('-timestamp').first()

    # Bloqueio anti-spam (ignora se leu a mesma pessoa nos últimos 2 minutos)
    if ultimo_registro and ultimo_registro.timestamp > cooldown:
        return False # Não registrou nada novo

    if modo == 'varredura':
        # Na Chamada Panorâmica, só damos ENTRADA.
        if not ultimo_registro or ultimo_registro.direction != 'ENTRADA':
            Attendance.objects.create(
                student=student,
                classroom=classroom,
                direction='ENTRADA',
                liveness_score=1.0
            )
            return True
            
    elif modo == 'totem':
        # No Totem fixo, intercala entre Entrada e Saída
        nova_direcao = 'SAIDA' if (ultimo_registro and ultimo_registro.direction == 'ENTRADA') else 'ENTRADA'
        Attendance.objects.create(
            student=student,
            classroom=classroom,
            direction=nova_direcao,
            liveness_score=1.0
        )
        return True
        
    return False

@csrf_exempt
def processar_frame_camera(request):
    if request.method == 'POST':
        image_data = request.POST.get('image')
        modo_operacao = request.POST.get('modo') 
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
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)
                
                if frame is None:
                    raise ValueError("Falha na decodificação da imagem.")

                # Reduz o tamanho da imagem pela metade 
                small_frame = cv2.resize(frame, (0, 0), fx=0.5, fy=0.5)
                rgb_small_frame = cv2.cvtColor(small_frame, cv2.COLOR_BGR2RGB)

                face_locations = face_recognition.face_locations(rgb_small_frame)
                face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

                rostos_reconhecidos = []
                houve_mudanca = False # Flag para avisar a tela se deve atualizar a tabela
                faces_out = []

                if face_encodings:
                    # Carrega do Cache em vez de consultar o banco de dados toda hora
                    if class_id not in CACHE_BIOMETRIA:
                        alunos = classroom.enrolled_students.all()
                        known_enc = []
                        known_ids = []
                        for aluno in alunos:
                            if aluno.face_encoding:
                                enc_list = json.loads(aluno.face_encoding) if isinstance(aluno.face_encoding, str) else aluno.face_encoding
                                if isinstance(enc_list, list) and len(enc_list) == 128:
                                    known_enc.append(np.array(enc_list))
                                    known_ids.append(aluno)
                        CACHE_BIOMETRIA[class_id] = (known_enc, known_ids)
                    
                    known_encodings, known_students = CACHE_BIOMETRIA[class_id]

                    if known_encodings:
                        for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                            box = {
                                'top': int(top),
                                'right': int(right),
                                'bottom': int(bottom),
                                'left': int(left),
                            }

                            face_distances = face_recognition.face_distance(known_encodings, face_encoding)
                            matches = face_recognition.compare_faces(known_encodings, face_encoding, tolerance=0.55)

                            name = 'Unknown'
                            student = None
                            
                            # 1. Identifica quem é a pessoa
                            if len(face_distances) > 0:
                                best_match_index = int(np.argmin(face_distances))
                                if matches[best_match_index]:
                                    student = known_students[best_match_index]
                                    name = student.user.get_full_name()

                            status = 'N/D'
                            color = '#FFCC00'
                            esta_vivo_final = False

                            # 2. Lógica de Liveness com Cache
                            if name != 'Unknown':
                                # Cria o perfil da pessoa no cache se não existir
                                if name not in CACHE_LIVENESS_VIEW:
                                    CACHE_LIVENESS_VIEW[name] = {
                                        "aprovado": False,
                                        "sucessos": 0
                                    }
                                
                                cache_pessoa = CACHE_LIVENESS_VIEW[name]

                                # Se já foi aprovada antes, não precisa gastar GPU de novo
                                if cache_pessoa["aprovado"]:
                                    esta_vivo_final = True
                                    status = "Aprovado (Vivo)"
                                    color = '#00FF00'
                                else:
                                    # Executa a IA de Liveness pois ainda não atingiu a meta
                                    try:
                                        if 'ia_system' in globals() and ia_system is not None and hasattr(ia_system, 'liveness'):
                                            # Redimensiona a caixa de volta para o frame original
                                            scale = frame.shape[1] / float(rgb_small_frame.shape[1])
                                            left_o = int(left * scale)
                                            top_o = int(top * scale)
                                            right_o = int(right * scale)
                                            bottom_o = int(bottom * scale)
                                            
                                            esta_vivo, msg = ia_system.liveness.avaliar_frame(frame, (left_o, top_o, right_o, bottom_o))
                                            
                                            if esta_vivo:
                                                cache_pessoa["sucessos"] += 1
                                                status = f"Analisando: {cache_pessoa['sucessos']}/5"
                                                color = '#FFCC00' # Laranja/Amarelo enquanto analisa
                                                
                                                # Só aprova se atingir 5 frames consecutivos
                                                if cache_pessoa["sucessos"] >= 5:
                                                    cache_pessoa["aprovado"] = True
                                                    esta_vivo_final = True
                                                    status = "Aprovado (Vivo)"
                                                    color = '#00FF00'
                                            else:
                                                # Se a IA der negativo, zera o contador (exige 5 sucessos seguidos)
                                                cache_pessoa["sucessos"] = 0
                                                status = msg if msg else "FALSO"
                                                color = '#FF0000'
                                    except Exception as e:
                                        status = "Erro Liveness"
                                        color = '#FF0000'

                                # 3. REGISTRO DE PONTO (Agora protegido pelo Liveness)
                                # Só registra a presença se a pessoa passou no teste de liveness!
                                if esta_vivo_final and student:
                                    if registrar_ponto(student, classroom, modo_operacao):
                                        houve_mudanca = True
                                    
                                    rostos_reconhecidos.append(name)

                            faces_out.append({
                                'name': name,
                                'status': status,
                                'color': color,
                                'box': box
                            })

                return JsonResponse({
                    "status": "sucesso", 
                    "rostos_processados": len(face_locations),
                    "reconhecidos": rostos_reconhecidos,
                    "atualizar_tela": houve_mudanca, # Manda o sinal pro Javascript atualizar os números
                    "faces": faces_out,
                    "image_w": rgb_small_frame.shape[1],
                    "image_h": rgb_small_frame.shape[0]
                })

            except Exception as e:
                print(f"ERRO NA IA: {str(e)}")
                return JsonResponse({"status": "erro", "mensagem": str(e)}, status=400)
                
    return JsonResponse({"status": "invalido"}, status=400)