from django.shortcuts import render, redirect, get_object_or_404
from students.models import Classroom, Attendance, Student
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.db.models import Count
import csv
from django.utils import timezone
from datetime import timedelta, datetime, date
from django.db.models import Count, Q
from django.urls import reverse

def is_teacher(user):
    return hasattr(user, 'profile') and user.profile.is_teacher


@login_required
def start_class(request, class_id):
    if request.method == 'POST':
        classroom = get_object_or_404(Classroom, id=class_id)
        
        # Garante a desativação de qualquer outra aula ativa para não confundir o totem
        Classroom.objects.filter(active_now=True).update(active_now=False)
        
        # Obtém a quantidade de aulas em sequência (padrão de 2 horas)
        num_hours = int(request.POST.get('num_hours', 2))
        
        # SALVA A CARGA HORÁRIA NA MEMÓRIA TEMPORÁRIA DO PROFESSOR (Sem mexer na grade fixa do banco)
        request.session[f'class_{classroom.id}_hours'] = num_hours
        
        # Apenas ativa a aula (start_time e end_time permanecem intactos com o horário oficial!)
        classroom.active_now = True
        classroom.save()
        
    return redirect(f"{reverse('dashboard')}?class_id={class_id}")

@login_required
def end_class(request, class_id):
    if request.method == 'POST':
        classroom = get_object_or_404(Classroom, id=class_id)
        
        if classroom.active_now:
            # Resgata a quantidade de horas que guardamos no início da aula (e já apaga da memória)
            # Se por acaso o professor mudou de computador, o .pop assume 2 horas como fallback de segurança
            horas_ministradas = request.session.pop(f'class_{classroom.id}_hours', 2)
            
            # Adiciona ao histórico de horas dadas na disciplina
            classroom.hours_taught += horas_ministradas
            
            # Encerra a aula no totem
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
        
    # Anotação de Entradas e Saídas mapeando o relacionamento reverso (attendances)
    all_students = base_query_alunos.annotate(
        entradas=Count('attendances', filter=filtro_hoje & Q(attendances__direction='ENTRADA')),
        saidas=Count('attendances', filter=filtro_hoje & Q(attendances__direction='SAÍDA'))
    ).order_by('user__first_name')
    
    # Cálculo detalhado de permanência em minutos por aluno
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
                
        # Se a aula ainda está em andamento e o aluno não registrou saída, contabiliza até o momento atual
        if entrada_atual:
            tempo_total += (timezone.now() - entrada_atual)
            
        aluno.minutos_presente = int(tempo_total.total_seconds() / 60)
        
        # Definição padrão do status antes da validação de horários planejados
        aluno.status_academico = "Aguardando processamento..."
        aluno.cor_status = "secondary"
        
        if selected_class and selected_class.start_time and selected_class.end_time:
            # Converte os horários para calcular a duração exata planejada em minutos
            inicio = datetime.combine(hoje, selected_class.start_time)
            fim = datetime.combine(hoje, selected_class.end_time)
            duracao_total = (fim - inicio).total_seconds() / 60
            
            # Divide o bloco duplo em frações de uma hora de aula isolada
            tempo_uma_aula = duracao_total / 2
            
            meta_1_presenca = tempo_uma_aula * 0.75
            meta_2_presencas = duracao_total * 0.75
            
            # Verificação progressiva das metas de minutos em sala de aula
            if aluno.minutos_presente >= meta_2_presencas:
                aluno.status_academico = "2 Presenças Contabilizadas"
                aluno.cor_status = "success"
            elif aluno.minutos_presente >= meta_1_presenca:
                aluno.status_academico = "1 Presença Contabilizada (Parcial)"
                aluno.cor_status = "warning"
            else:
                aluno.status_academico = "Presença Não Contabilizada (Tempo Insuficiente)"
                aluno.cor_status = "danger"

    # Mapeamento do fluxo transacional para a tabela de logs da interface
    recent_attendances = []
    if selected_class:
        recent_attendances = list(Attendance.objects.filter(classroom=selected_class, timestamp__date=hoje).order_by('-timestamp'))
        
        mapa_contagens = {s.id: {'in': s.entradas, 'out': s.saidas} for s in all_students}
        
        for att in recent_attendances:
            counts = mapa_contagens.get(att.student_id, {'in': 0, 'out': 0})
            att.total_entradas = counts['in']
            att.total_saidas = counts['out']
            
        presentes_count = sum(1 for s in all_students if s.entradas > s.saidas)
        
        # Consolidação métrica para preenchimento do widget vertical unificado
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
    }
    context['all_students_global'] = Student.objects.all().order_by('user__first_name')
    return render(request, 'core/teacher_dashboard.html', context)


@login_required
def student_absences(request):
    if not hasattr(request.user, 'student_profile'):
        return redirect('dashboard')
    
    # filtragem das presenças dos alunos
    student = request.user.student_profile
    my_attendances = Attendance.objects.filter(student=student)
    return render(request, 'students/my_absences.html', {'attendances': my_attendances})


# função para retornar em JSON as últimas presenças cadastradas
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
    
    # Cria o objeto de resposta com o cabeçalho de arquivo CSV
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


@login_required #depende de como o totem será logado
def totem_display(request):
    """Renderiza a interface gráfica exclusiva do terminal biométrico (sem barras de navegação)"""
    return render(request, 'core/totem_display.html')