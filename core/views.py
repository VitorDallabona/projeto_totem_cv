from django.shortcuts import render, redirect, get_object_or_404
from students.models import Classroom, Attendance, Student
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test
from django.http import HttpResponse
from django.db.models import Count
import datetime
import csv

def is_teacher(user):
    return hasattr(user, 'profile') and user.profile.is_teacher


@login_required
def teacher_dashboard(request):
    #verifica se quem logou foi um aluno
    if hasattr(request.user, 'student_profile'):
        # Se for aluno, redireciona para a tela de faltas dele
        return redirect('student_absences')
        
    #Professor ou Admin ->carrega o dashboard
    active_classes = Classroom.objects.filter(active_now=True)
    recent_attendances = Attendance.objects.all().order_by('-timestamp')[:50]
    
    #busca todos os alunos para a gestão
    all_students = Student.objects.all().order_by('user__first_name')
    
    # busca todas as turmas
    all_classrooms = Classroom.objects.all()
    
    selected_class_id = request.GET.get('class_id')
    if selected_class_id:
        selected_class = get_object_or_404(Classroom, id=selected_class_id)
    else:
        selected_class = Classroom.objects.filter(active_now=True).first()
    
    
    stats = {
        'total': 0,
        'presentes': 0,
        'faltando': 0,
        'taxa_presenca': 0
    }
    
    recent_attendances = []
    
    if selected_class:
        # Total de matriculados
        stats['total'] = selected_class.enrolled_students.count()
        
        # Alunos que tiveram pelo menos uma presença validada nesta turma hoje
        present_ids = Attendance.objects.filter(
            classroom=selected_class,
            is_valid=True,
            timestamp__date=datetime.date.today()
        ).values_list('student_id', flat=True).distinct()
        
        stats['presentes'] = len(present_ids)
        stats['faltando'] = stats['total'] - stats['presentes']
        
        if stats['total'] > 0:
            stats['taxa_presenca'] = (stats['presentes'] / stats['total']) * 100
            
        recent_attendances = Attendance.objects.filter(classroom=selected_class).order_by('-timestamp')
    
    
    context = {
        'active_classes': active_classes,
        'recent_attendances': recent_attendances,
        'students': all_students, # envia para o HTML
        'classrooms' : all_classrooms,
        'selected_class' : selected_class,
        'stats' : stats,
    }
    
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
            'horario': att.timestamp.strftime("%H:%M:%S"),
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
            att.timestamp.strftime('%d/%m/%Y %H:%M'),
            'Validado' if att.is_valid else 'Suspeito'
        ])
        
    return response