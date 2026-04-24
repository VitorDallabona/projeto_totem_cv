from django.shortcuts import render
from students.models import Classroom, Attendance


def dashboard(request):
    active_class = Classroom.objects.filter(active_now=True)
    recent_attendances = Attendance.objects.all().order_by('-timestamp')[:50]
    context ={
        'active_classes':active_class,
        'recent_attendances':recent_attendances,
    }
    
    return render(request, 'core/dashboard.html', context)
    