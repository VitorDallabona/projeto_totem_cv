from django.shortcuts import render, redirect
from students.models import Classroom, Attendance
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required, user_passes_test


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
    
    context = {
        'active_classes': active_classes,
        'recent_attendances': recent_attendances,
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
            'aluno_nome': att.student.name,
            'matricula':att.student.registration_id,
            'is_valid': att.is_valid,
            'liveness_score': att.liveness_score
        })
    
    return JsonResponse(data, safe=False)