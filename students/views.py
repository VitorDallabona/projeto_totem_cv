from django.shortcuts import render, redirect
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from .forms import StudentRegistrationForm
from django.shortcuts import get_object_or_404
from .models import Student
import json

# Imports pesados - comentados para migrations rodarem
try:
    import face_recognition
    import numpy as np
    from PIL import Image, ImageOps
    import cv2 as cv
    from .ia import FaceRecognition
    
    # Inicia a rede neural na memória UMA VEZ
    print("Carregando Modelos de IA na GPU...")
    ia_system = FaceRecognition('media/faces')
except ImportError as e:
    print(f"⚠️  Aviso: Algumas dependências não estão instaladas: {e}")
    print("   Use isso para debugar apenas, migrations funcionam normalmente")
    ia_system = None
from django.http import StreamingHttpResponse

def tela_monitoramento(request):
    """Dashboard de monitoramento de entrada/saída para professores"""
    from .models import Attendance, Classroom, Student
    from django.utils import timezone
    from django.db.models import Count
    
    if ia_system is not None:
        ia_system.atualizar_banco_rostos()
    
    # Data atual
    hoje = timezone.now().date()
    
    # Filtros opcionais
    sala_id = request.GET.get('sala')
    data_filtro = request.GET.get('data', str(hoje))
    
    try:
        data_filtro = timezone.datetime.strptime(data_filtro, '%Y-%m-%d').date()
    except:
        data_filtro = hoje
    
    # Query base
    query = Attendance.objects.filter(timestamp__date=data_filtro)
    
    if sala_id:
        query = query.filter(classroom_id=sala_id)
    
    # Estatísticas básicas
    total_acessos = query.count()
    entradas = query.filter(direction='ENTRADA').count()
    saidas = query.filter(direction='SAÍDA').count()
    
    # Alunos com entrada registrada
    alunos_com_entrada = query.filter(direction='ENTRADA').values_list('student_id', flat=True).distinct()
    alunos_com_saida = query.filter(direction='SAÍDA').values_list('student_id', flat=True).distinct()
    
    # Alunos presentes (entraram mas NÃO saíram)
    alunos_presentes_ids = set(alunos_com_entrada) - set(alunos_com_saida)
    alunos_presentes = Student.objects.filter(id__in=alunos_presentes_ids).order_by('user__first_name')
    
    # Histórico completo do dia (todos os acessos)
    historico = query.order_by('-timestamp')
    
    # Salas disponíveis
    salas = Classroom.objects.all()
    
    context = {
        'historico': historico,
        'total_acessos': total_acessos,
        'entradas': entradas,
        'saidas': saidas,
        'alunos_presentes': alunos_presentes,
        'alunos_presentes_count': len(alunos_presentes),
        'salas': salas,
        'sala_selecionada': sala_id,
        'data_selecionada': data_filtro,
    }
    
    return render(request, 'monitoramento.html', context)

def consumir_totem():
    """
    Conecta no Totem via rede, processa a IA e devolve para o HTML
    """
    try:
        import cv2 as cv
        import numpy as np
        from PIL import Image, ImageDraw
    except ImportError:
        # Se cv não está instalado, mostra frame preta com mensagem
        from PIL import Image, ImageDraw
        import numpy as np
        
        img = Image.new('RGB', (640, 480), color='black')
        draw = ImageDraw.Draw(img)
        draw.text((150, 220), "Câmera não disponível", fill='white')
        
        # Converte para o formato esperado pelo cv se possível
        try:
            import cv2 as cv
            img_array = np.array(img)
            ret, buffer = cv.imencode('.jpg', img_array)
            frame_bytes = buffer.tobytes()
        except:
            # Se mesmo isso falhar, usa PIL
            import io
            img_bytes = io.BytesIO()
            img.save(img_bytes, format='JPEG')
            frame_bytes = img_bytes.getvalue()
        
        while True:
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + 
                frame_bytes + 
                b'\r\n'
            )
        return
    
    # Se IA não está disponível, retorna frame de erro
    if ia_system is None:
        img = Image.new('RGB', (640, 480), color='black')
        draw = ImageDraw.Draw(img)
        draw.text((150, 220), "IA não disponível", fill='white')
        
        img_array = np.array(img)
        ret, buffer = cv.imencode('.jpg', img_array)
        frame_bytes = buffer.tobytes()
        
        while True:
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + 
                frame_bytes + 
                b'\r\n'
            )
        return
    
    # Tenta conectar ao Totem
    try:
        IP_DO_TOTEM = '192.168.1.10'
        link_totem = f'http://{IP_DO_TOTEM}:4747/video'
        
        print(f"Tentando conectar no Totem: {link_totem}...")
        camera_remota = cv.VideoCapture(link_totem)
        
        while True:
            sucesso, frame = camera_remota.read()
            
            if not sucesso:
                break
                
            # O frame que viajou pela rede entra na sua IA
            frame_processado = ia_system.run_recognition(frame)
            
            # Re-encoda o frame final para a Web
            ret, buffer = cv.imencode('.jpg', frame_processado)
            frame_bytes = buffer.tobytes()
            
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + 
                frame_bytes + 
                b'\r\n'
            )
    except Exception as e:
        print(f"Erro no feed de vídeo: {e}")
        # Se der erro, retorna frame preta
        img = Image.new('RGB', (640, 480), color='black')
        draw = ImageDraw.Draw(img)
        texto = f"Erro: {str(e)[:40]}"
        draw.text((50, 220), texto, fill='white')
        
        img_array = np.array(img)
        ret, buffer = cv.imencode('.jpg', img_array)
        frame_bytes = buffer.tobytes()
        
        while True:
            yield (
                b'--frame\r\n'
                b'Content-Type: image/jpeg\r\n\r\n' + 
                frame_bytes + 
                b'\r\n'
            )

def video_feed(request):
    """Endpoint de câmera - retorna stream de vídeo"""
    def generate_frames():
        try:
            # Tenta importar OpenCV
            try:
                import cv2
            except ImportError:
                # Se OpenCV não está instalado, retorna imagem preta
                from PIL import Image
                import io
                
                img = Image.new('RGB', (640, 480), color='black')
                img_bytes = io.BytesIO()
                img.save(img_bytes, format='JPEG')
                frame_bytes = img_bytes.getvalue()
                
                while True:
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + 
                        frame_bytes + 
                        b'\r\n'
                    )
                return
            
            # Se ia_system é None, retorna imagem preta com mensagem
            if ia_system is None:
                from PIL import Image, ImageDraw
                import numpy as np
                
                img = Image.new('RGB', (640, 480), color='black')
                draw = ImageDraw.Draw(img)
                draw.text((180, 220), "Câmera não disponível", fill='white')
                
                img_array = np.array(img)
                ret, buffer = cv2.imencode('.jpg', img_array)
                frame_bytes = buffer.tobytes()
                
                while True:
                    yield (
                        b'--frame\r\n'
                        b'Content-Type: image/jpeg\r\n\r\n' + 
                        frame_bytes + 
                        b'\r\n'
                    )
                return
            
            # Tenta conectar ao Totem
            IP_DO_TOTEM = '192.168.1.10'
            link_totem = f'http://{IP_DO_TOTEM}:4747/video'
            
            camera = cv2.VideoCapture(link_totem)
            
            while True:
                ret, frame = camera.read()
                
                if not ret:
                    break
                
                # Processa com IA
                frame_processado = ia_system.run_recognition(frame)
                
                # Codifica frame
                ret, buffer = cv2.imencode('.jpg', frame_processado)
                frame_bytes = buffer.tobytes()
                
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + 
                    frame_bytes + 
                    b'\r\n'
                )
        
        except Exception as e:
            print(f"Erro em video_feed: {e}")
            # Retorna imagem de erro
            from PIL import Image, ImageDraw
            import numpy as np
            import cv2
            
            img = Image.new('RGB', (640, 480), color='black')
            draw = ImageDraw.Draw(img)
            draw.text((100, 220), f"Erro na câmera", fill='white')
            
            img_array = np.array(img)
            ret, buffer = cv2.imencode('.jpg', img_array)
            frame_bytes = buffer.tobytes()
            
            while True:
                yield (
                    b'--frame\r\n'
                    b'Content-Type: image/jpeg\r\n\r\n' + 
                    frame_bytes + 
                    b'\r\n'
                )
    
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
