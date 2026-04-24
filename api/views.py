from django.shortcuts import render
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from students.models import Student, Classroom, Attendance


# View para simular o recebimento dos dados do totem
# Aqui, devemos processar uma imagem, mas para teste do banco vamos usar só a matrícula via POST

@csrf_exempt #desativa a exigência de token CSRF para requisições
def mock_check_presence(request):
    if request.method == 'POST':
        matricula = request.POST.get('registration_id')
        try:
            student = Student.objects.get(registration_id=matricula)
            active_class = Classroom.objects.filter(active_now=True).first()
            if not active_class:
                return JsonResponse({'status': 'erro', 'mensagem': 'Nenhuma aula ativa no momento.'})
            
            Attendance.objects.create(
                student=student, 
                classroom=active_class,
                liveness_score=0.99, #pontução fictícia pra teste
                is_valid=True       
            )
        
            return JsonResponse({'status': 'sucesso', 'nome': student.name})

        except Student.DoesNotExist:
            return JsonResponse({'status': 'erro', 'mensagem': 'Aluno não encontrado.'})
        
    return JsonResponse({'status': 'erro', 'mensagem': 'Método não permitido. Use POST.'})

            
