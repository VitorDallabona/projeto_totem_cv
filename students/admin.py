from django.contrib import admin
from .models import Student, Classroom, Attendance

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('name', 'registration_id', 'created_at')
    search_fields = ('name', 'registration_id')
    
@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('subject', 'teacher', 'active_now')
    list_filter = ('active_now',)
    
    
@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'classroom', 'timestamp', 'is_valid', 'liveness_score')
    list_filter = ('is_valid', 'classroom')