import csv
import json
import asyncio
import concurrent.futures
from datetime import date, datetime, timedelta

import cv2
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.contrib.auth.decorators import login_required
from django.views.decorators.csrf import csrf_exempt

# --- Modelos ---
from students.models import Attendance, Classroom, Student

# --- IMPORTS DO WEBRTC ---
from aiortc import RTCPeerConnection, RTCSessionDescription

# =========================================================================
# IMPORTAÇÃO DA IA (Singleton Integrado)
# =========================================================================
# Ao importar a variável ia_system, o Python usa a mesma rede neural 
# que já foi alocada na memória da GPU pelo ia.py, evitando conflitos!
from students.ia import ia_system

# Cria um "Túnel Exclusivo" de 1 via para a IA rodar na GPU.
# O max_workers=1 garante que o CUDA nunca quebre por conflito de threads!
ia_executor = concurrent.futures.ThreadPoolExecutor(max_workers=4)

# =========================================================================
# VISTAS DE CONTROLE DE SALA
# =========================================================================

def is_teacher(user):
    return hasattr(user, 'profile') and user.profile.is_teacher

@login_required
def start_class(request, class_id):
    if request.method == 'POST':
        classroom = get_object_or_404(Classroom, id=class_id)
        Classroom.objects.filter(active_now=True).update(active_now=False)
        num_hours = int(request.POST.get('num_hours', 2))
        request.session[f'class_{classroom.id}_hours'] = num_hours
        classroom.active_now = True
        classroom.save()
    return redirect(f"{reverse('dashboard')}?class_id={class_id}")

@login_required
def end_class(request, class_id):
    if request.method == 'POST':
        classroom = get_object_or_404(Classroom, id=class_id)
        if classroom.active_now:
            horas_ministradas = request.session.pop(f'class_{classroom.id}_hours', 2)
            classroom.hours_taught += horas_ministradas
            classroom.active_now = False
            classroom.save()
    return redirect(f"{reverse('dashboard')}?class_id={class_id}")

@login_required
def teacher_dashboard(request):
    if hasattr(request.user, 'student_profile'):
        return redirect('student_absences')
        
    all_classrooms = Classroom.objects.all()
    selected_class_id = request.GET.get('class_id')
    
    if selected_class_id:
        selected_class = get_object_or_404(Classroom, id=selected_class_id)
    else:
        selected_class = Classroom.objects.filter(active_now=True).first()
    
    hoje = date.today()
    filtro_hoje = Q(attendances__timestamp__date=hoje)
    
    if selected_class:
        filtro_hoje &= Q(attendances__classroom=selected_class)
        base_query_alunos = selected_class.enrolled_students.all()
    else:
        base_query_alunos = Student.objects.all()
        
    all_students = base_query_alunos.annotate(
        entradas=Count('attendances', filter=filtro_hoje & Q(attendances__direction='ENTRADA')),
        saidas=Count('attendances', filter=filtro_hoje & Q(attendances__direction='SAÍDA'))
    ).order_by('user__first_name')
    
    for aluno in all_students:
        atendimentos = Attendance.objects.filter(
            student=aluno, classroom=selected_class, timestamp__date=hoje
        ).order_by('timestamp')
        
        tempo_total = timedelta()
        entrada_atual = None
        
        for att in atendimentos:
            if att.direction == 'ENTRADA':
                entrada_atual = att.timestamp
            elif att.direction == 'SAÍDA' and entrada_atual:
                tempo_total += (att.timestamp - entrada_atual)
                entrada_atual = None
                
        if entrada_atual: tempo_total += (timezone.now() - entrada_atual)
        aluno.minutos_presente = int(tempo_total.total_seconds() / 60)
        aluno.status_academico = "Aguardando processamento..."
        aluno.cor_status = "secondary"
        
        if selected_class and selected_class.start_time and selected_class.end_time:
            inicio = datetime.combine(hoje, selected_class.start_time)
            fim = datetime.combine(hoje, selected_class.end_time)
            duracao_total = (fim - inicio).total_seconds() / 60
            tempo_uma_aula = duracao_total / 2
            meta_1_presenca = tempo_uma_aula * 0.75
            meta_2_presencas = duracao_total * 0.75
            
            if aluno.minutos_presente >= meta_2_presencas:
                aluno.status_academico = "2 Presenças Contabilizadas"
                aluno.cor_status = "success"
            elif aluno.minutos_presente >= meta_1_presenca:
                aluno.status_academico = "1 Presença Contabilizada (Parcial)"
                aluno.cor_status = "warning"
            else:
                aluno.status_academico = "Presença Não Contabilizada (Tempo Insuficiente)"
                aluno.cor_status = "danger"

    recent_attendances = []
    if selected_class:
        recent_attendances = list(Attendance.objects.filter(classroom=selected_class, timestamp__date=hoje).order_by('-timestamp'))
        mapa_contagens = {s.id: {'in': s.entradas, 'out': s.saidas} for s in all_students}
        
        for att in recent_attendances:
            counts = mapa_contagens.get(att.student_id, {'in': 0, 'out': 0})
            att.total_entradas = counts['in']
            att.total_saidas = counts['out']
            
        presentes_count = sum(1 for s in all_students if s.entradas > s.saidas)
        stats = {
            'total': selected_class.enrolled_students.count(),
            'presentes': presentes_count,
            'faltando': max(0, selected_class.enrolled_students.count() - presentes_count),
            'total_hours': selected_class.total_hours,
            'hours_taught': selected_class.hours_taught,
        }
    else:
        stats = {'total': 0, 'presentes': 0, 'faltando': 0, 'total_hours': 0, 'hours_taught': 0}

    context = {
        'recent_attendances': recent_attendances,
        'students': all_students,
        'classrooms': all_classrooms,
        'selected_class': selected_class,
        'stats': stats,
        'all_students_global': Student.objects.all().order_by('user__first_name')
    }
    return render(request, 'core/teacher_dashboard.html', context)

@login_required
def student_absences(request):
    if not hasattr(request.user, 'student_profile'): return redirect('dashboard')
    student = request.user.student_profile
    my_attendances = Attendance.objects.filter(student=student)
    return render(request, 'students/my_absences.html', {'attendances': my_attendances})

def recent_attendances_api(request):
    recent = Attendance.objects.all().order_by('-timestamp')[:50]
    data = []
    for att in recent:
        data.append({
            'horario': timezone.localtime(att.timestamp).strftime("%H:%M:%S"),
            'aluno_nome': att.student.user.get_full_name() or att.student.user.username,
            'matricula':att.student.registration_id,
            'is_valid': att.is_valid,
            'liveness_score': att.liveness_score
        })
    return JsonResponse(data, safe=False)

def export_attendance_csv(request, class_id):
    classroom = get_object_or_404(Classroom, id=class_id)
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="presenca_{classroom.subject}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Nome', 'Matricula', 'Data/Hora', 'Status'])
    attendances = Attendance.objects.filter(classroom=classroom).order_by('student__user__first_name')
    for att in attendances:
        writer.writerow([
            att.student.user.get_full_name(),
            att.student.registration_id,
            timezone.localtime(att.timestamp).strftime('%d/%m/%Y %H:%M'),
            'Validado' if att.is_valid else 'Suspeito'
        ])
    return response

@login_required 
def totem_display(request):
    return render(request, 'core/totem_display.html')

# =========================================================================================
# ==============================  MÓDULO WEBRTC (NÍVEL DEUS) ==============================
# =========================================================================================

pcs = set()

@csrf_exempt
async def webrtc_offer(request):
    if request.method == "POST":
        corpo = json.loads(request.body)
        
        offer = RTCSessionDescription(sdp=corpo["sdp"], type=corpo["type"])
        class_id = corpo.get("class_id")

        pc = RTCPeerConnection()
        pcs.add(pc)

        dc_ref = {"channel": None}

        @pc.on("datachannel")
        def on_datachannel(channel):
            dc_ref["channel"] = channel
            print(f"📡 Data Channel WebRTC aberto para turma {class_id}!")

        @pc.on("track")
        def on_track(track):
            if track.kind == "video":
                print("📹 Vídeo nativo recebido! Extraindo frames em tempo real...")
                
                latest_frame = None
                correndo = True 

                async def leitor_continuo():
                    nonlocal latest_frame, correndo
                    while correndo:
                        try:
                            frame = await track.recv()
                            latest_frame = frame 
                        except Exception:
                            correndo = False
                            break

                # 2. A IA: Processa com a placa de vídeo usando um executor de via única
                async def processador_ia():
                    nonlocal latest_frame, correndo
                    loop = asyncio.get_event_loop()
                    
                    while correndo:
                        try:
                            # SE O FRAME ESTIVER NULLO, SÓ ESPERA UM POUCO E CONTINUA
                            if latest_frame is None:
                                await asyncio.sleep(0.005)
                                continue

                            # PEGA O FRAME MAIS RECENTE E LIMPA O BUFFER IMEDIATAMENTE
                            frame_para_processar = latest_frame
                            latest_frame = None 
                            
                            img = frame_para_processar.to_ndarray(format="bgr24")
                            
                            if ia_system is not None:
                                ia_system.LINHA_VIRTUAL_X = img.shape[1] // 2
                                
                                # A mágica: processamos o frame. Se demorar, o leitor_continuo 
                                # vai ter colocado um frame mais novo em 'latest_frame' enquanto isso.
                                resultado = await loop.run_in_executor(
                                    ia_executor, 
                                    ia_system.run_recognition_get_data, 
                                    img
                                )
                                faces_out, deve_atualizar_tela = resultado

                                channel = dc_ref.get("channel")
                                if channel and channel.readyState == "open":
                                    resposta = {
                                        "status": "sucesso",
                                        "faces": faces_out,
                                        "image_w": img.shape[1],
                                        "image_h": img.shape[0],
                                        "atualizar_tela": deve_atualizar_tela,
                                        "timestamp": int(datetime.now().timestamp() * 1000) # ADICIONE ISSO
                                    }
                                    channel.send(json.dumps(resposta))
                            else:
                                await asyncio.sleep(0.5)
                        except Exception as e:
                            print(f"❌ Erro na IA: {e}")
                            correndo = False
                            break
                        
                asyncio.create_task(leitor_continuo())
                asyncio.create_task(processador_ia())

        @pc.on("connectionstatechange")
        async def on_connectionstatechange():
            print("Status WebRTC:", pc.connectionState)
            if pc.connectionState in ["failed", "closed"]:
                pcs.discard(pc)

        await pc.setRemoteDescription(offer)
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)

        return JsonResponse({
            "sdp": pc.localDescription.sdp,
            "type": pc.localDescription.type
        })
    
    return JsonResponse({"erro": "Apenas POST permitido"})