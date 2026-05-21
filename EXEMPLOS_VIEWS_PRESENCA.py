"""
Exemplos práticos de como usar Attendance no seu projeto

Use esses exemplos em suas views.py para:
- Consultar presença
- Gerar relatórios
- Criar APIs em tempo real
"""

from django.shortcuts import render
from django.http import JsonResponse
from django.utils import timezone
from datetime import date, timedelta
from .models import Attendance, Classroom, Student
import json


# ============================================================================
# EXEMPLO 1: Dashboard de Presença em Tempo Real
# ============================================================================

def presenca_tempo_real(request):
    """
    View para exibir presença do dia em tempo real
    Mostrar os últimos 20 registros na ordem inversa (mais recentes primeiro)
    """
    
    # Pegar sala ativa
    classroom = Classroom.objects.filter(active_now=True).first()
    
    if not classroom:
        return render(request, 'error.html', 
                     {'message': 'Nenhuma sala ativa no momento'})
    
    # Registros de hoje
    hoje = date.today()
    registros = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date=hoje
    ).select_related('student__user').order_by('-timestamp')[:20]
    
    # Estatísticas
    total_entradas = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date=hoje,
        direction='ENTRADA'
    ).count()
    
    total_saidas = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date=hoje,
        direction='SAÍDA'
    ).count()
    
    contexto = {
        'classroom': classroom,
        'registros': registros,
        'total_entradas': total_entradas,
        'total_saidas': total_saidas,
        'data': hoje,
    }
    
    return render(request, 'presenca_tempo_real.html', contexto)


# ============================================================================
# EXEMPLO 2: API JSON para Dashboard em Tempo Real (WebSocket-ready)
# ============================================================================

def api_presenca_json(request):
    """
    API que retorna dados de presença em JSON
    Ideal para AJAX/Frontend atualizar sem recarregar
    """
    
    classroom = Classroom.objects.filter(active_now=True).first()
    
    if not classroom:
        return JsonResponse({
            'success': False,
            'error': 'Nenhuma sala ativa'
        })
    
    hoje = date.today()
    
    # Últimos 30 registros
    registros = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date=hoje
    ).select_related(
        'student__user'
    ).values(
        'id',
        'student__user__first_name',
        'student__user__last_name',
        'student__registration_id',
        'direction',
        'timestamp',
        'is_valid',
        'liveness_score'
    ).order_by('-timestamp')[:30]
    
    # Converter queryset para lista
    registros_list = []
    for reg in registros:
        registros_list.append({
            'id': reg['id'],
            'nome_completo': f"{reg['student__user__first_name']} {reg['student__user__last_name']}",
            'matricula': reg['student__registration_id'],
            'direcao': '↗ ENTRADA' if reg['direction'] == 'ENTRADA' else '↙ SAÍDA',
            'hora': reg['timestamp'].strftime('%H:%M:%S'),
            'data': reg['timestamp'].strftime('%d/%m/%Y'),
            'liveness': round(float(reg['liveness_score']), 2),
            'valido': 'Sim' if reg['is_valid'] else 'Não'
        })
    
    # Contar totalizações
    entradas = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date=hoje,
        direction='ENTRADA'
    ).count()
    
    saidas = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date=hoje,
        direction='SAÍDA'
    ).count()
    
    return JsonResponse({
        'success': True,
        'sala': classroom.subject,
        'data': str(hoje),
        'total_entradas': entradas,
        'total_saidas': saidas,
        'registros': registros_list,
        'timestamp_servidor': timezone.now().isoformat()
    })


# ============================================================================
# EXEMPLO 3: Relatório por Aluno (Quantas vezes entrou/saiu)
# ============================================================================

def relatorio_aluno(request, student_id):
    """
    Relatório completo de um aluno específico
    Mostra todas as entradas/saídas do dia
    """
    
    try:
        student = Student.objects.get(id=student_id)
    except Student.DoesNotExist:
        return render(request, 'error.html', 
                     {'message': 'Aluno não encontrado'})
    
    hoje = date.today()
    
    # Todos os registros do aluno hoje
    registros = Attendance.objects.filter(
        student=student,
        timestamp__date=hoje
    ).select_related('classroom').order_by('timestamp')
    
    # Agrupar por entrada/saída
    entradas = registros.filter(direction='ENTRADA')
    saidas = registros.filter(direction='SAÍDA')
    
    # Calcular tempo na sala (se houver pairing entrada-saída)
    duracao_sessoes = []
    for entrada in entradas:
        # Buscar próxima saída
        proxima_saida = registros.filter(
            direction='SAÍDA',
            timestamp__gte=entrada.timestamp
        ).first()
        
        if proxima_saida:
            duracao = (proxima_saida.timestamp - entrada.timestamp).total_seconds()
            duracao_min = int(duracao / 60)
            duracao_sessoes.append({
                'entrada': entrada.timestamp,
                'saida': proxima_saida.timestamp,
                'duracao_minutos': duracao_min
            })
    
    contexto = {
        'student': student,
        'data': hoje,
        'registros': registros,
        'total_entradas': entradas.count(),
        'total_saidas': saidas.count(),
        'sessoes': duracao_sessoes,
    }
    
    return render(request, 'relatorio_aluno.html', contexto)


# ============================================================================
# EXEMPLO 4: Filtrar por Data Range
# ============================================================================

def presenca_periodo(request, dias=7):
    """
    Relatório de presença nos últimos N dias
    Útil para análises e gráficos
    """
    
    classroom = Classroom.objects.filter(active_now=True).first()
    
    if not classroom:
        return JsonResponse({'error': 'Sem sala ativa'})
    
    # Data inicial
    data_inicio = date.today() - timedelta(days=dias)
    data_final = date.today()
    
    # Contar por dia
    registros_por_dia = {}
    registros = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date__gte=data_inicio,
        timestamp__date__lte=data_final
    )
    
    for data in range(dias):
        d = data_inicio + timedelta(days=data)
        count = registros.filter(timestamp__date=d).count()
        registros_por_dia[str(d)] = count
    
    # Contar por aluno (quem mais frequentou)
    top_alunos = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date__gte=data_inicio,
        timestamp__date__lte=data_final
    ).values(
        'student__user__first_name',
        'student__user__last_name'
    ).annotate(
        count=models.Count('id')
    ).order_by('-count')[:10]
    
    return JsonResponse({
        'periodo_dias': dias,
        'data_inicio': str(data_inicio),
        'data_final': str(data_final),
        'registros_por_dia': registros_por_dia,
        'top_alunos': list(top_alunos),
    })


# ============================================================================
# EXEMPLO 5: Exportar para CSV
# ============================================================================

def exportar_presenca_csv(request):
    """
    Exportar dados de presença para arquivo CSV
    Pronto para abrir em Excel
    """
    import csv
    from django.http import HttpResponse
    
    classroom = Classroom.objects.filter(active_now=True).first()
    hoje = date.today()
    
    # Headers
    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="presenca_{hoje}.csv"'
    
    writer = csv.writer(response, delimiter=';')
    writer.writerow([
        'Matrícula',
        'Nome Completo',
        'Data',
        'Hora',
        'Direção',
        'Liveness Score',
        'Válido'
    ])
    
    # Dados
    registros = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date=hoje
    ).select_related('student__user').order_by('-timestamp')
    
    for reg in registros:
        writer.writerow([
            reg.student.registration_id,
            reg.student.user.get_full_name(),
            reg.timestamp.strftime('%d/%m/%Y'),
            reg.timestamp.strftime('%H:%M:%S'),
            reg.direction,
            f"{reg.liveness_score:.2f}",
            'Sim' if reg.is_valid else 'Não'
        ])
    
    return response


# ============================================================================
# EXEMPLO 6: Webhook para Notificações em Tempo Real
# ============================================================================

def webhook_presenca(request):
    """
    Recebe POST quando alguém passa pela câmera
    Ideal para integração com sistemas externos
    (Slack, Discord, email, etc)
    """
    
    if request.method != 'POST':
        return JsonResponse({'error': 'Apenas POST'}, status=400)
    
    try:
        data = json.loads(request.body)
        
        # Dados esperados
        nome_aluno = data.get('nome_aluno')
        direcao = data.get('direcao')
        
        # Salvar no banco
        from .ia import salvar_registro_acesso
        sucesso = salvar_registro_acesso(
            nome_aluno=nome_aluno,
            direcao=direcao,
            liveness_score=data.get('liveness_score', 0.98)
        )
        
        if sucesso:
            # AQUI você pode integrar:
            # - Enviar email
            # - Postar no Slack
            # - Atualizar WebSocket
            # - Salvar em cache Redis
            
            return JsonResponse({
                'success': True,
                'message': f'{nome_aluno} registrado como {direcao}'
            })
        else:
            return JsonResponse({
                'success': False,
                'message': 'Falha ao registrar'
            }, status=400)
            
    except Exception as e:
        return JsonResponse({
            'success': False,
            'error': str(e)
        }, status=500)


# ============================================================================
# USAR NAS URLs (urls.py)
# ============================================================================

"""
# Adicione essas rotas ao seu students/urls.py:

from django.urls import path
from . import views

urlpatterns = [
    path('presenca/tempo-real/', views.presenca_tempo_real, name='presenca_tempo_real'),
    path('api/presenca/json/', views.api_presenca_json, name='api_presenca_json'),
    path('relatorio/aluno/<int:student_id>/', views.relatorio_aluno, name='relatorio_aluno'),
    path('api/presenca/periodo/', views.presenca_periodo, name='presenca_periodo'),
    path('presenca/exportar-csv/', views.exportar_presenca_csv, name='exportar_csv'),
    path('webhook/presenca/', views.webhook_presenca, name='webhook_presenca'),
]
"""
