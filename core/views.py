from django.shortcuts import render
from students.models import Classroom, Attendance
from django.http import JsonResponse


def dashboard(request):
    active_class = Classroom.objects.filter(active_now=True)
    recent_attendances = Attendance.objects.all().order_by('-timestamp')[:50]
    context ={
        'active_classes':active_class,
        'recent_attendances':recent_attendances,
    }
    
    return render(request, 'core/dashboard.html', context)


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