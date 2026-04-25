from django.contrib import admin
from .models import Student, Classroom, Attendance, Profile

@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = ('get_name', 'registration_id', 'created_at')
    search_fields = ('user__first_name', 'user__last_name', 'registration_id')
    
    def get_name(self, obj):
        return obj.user.get_full_name() or obj.user.username
    get_name.short_description = "Nome do Aluno"
    
@admin.register(Classroom)
class ClassroomAdmin(admin.ModelAdmin):
    list_display = ('subject', 'teacher', 'active_now')
    list_filter = ('active_now',)
    
    
@admin.register(Attendance)
class AttendanceAdmin(admin.ModelAdmin):
    list_display = ('student', 'classroom', 'timestamp', 'is_valid', 'liveness_score')
    list_filter = ('is_valid', 'classroom')
    
    
@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ('user', 'is_teacher')
    list_filter = ('is_teacher',)