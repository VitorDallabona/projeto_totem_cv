# 📋 Guia: Integração de IA com Banco de Dados - Projeto Totem CV

## 1️⃣ ESTRUTURA DO BANCO DE DADOS (models.py)

### Model Attendance - Tabela de Presença

```python
class Attendance(models.Model):
    """
    Tabela transacional para registrar quando um aluno passa pela câmera
    """
    
    DIRECTION_CHOICES = [
        ('ENTRADA', 'Entrada (Esquerda para Direita)'),
        ('SAÍDA', 'Saída (Direita para Esquerda)'),
    ]
    
    # Quem passou
    student = models.ForeignKey(Student, on_delete=models.CASCADE, 
                                related_name='attendances')
    
    # Em qual turma
    classroom = models.ForeignKey(Classroom, on_delete=models.CASCADE, 
                                  related_name='attendance_records')
    
    # QUANDO passou (automático)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    # Qualidade do reconhecimento (0.0 a 1.0)
    liveness_score = models.FloatField()
    
    # Se passou na validação de liveness
    is_valid = models.BooleanField(default=False)
    
    # PARA ONDE foi
    direction = models.CharField(max_length=10, choices=DIRECTION_CHOICES, 
                                 default='ENTRADA')
    
    class Meta:
        ordering = ['-timestamp']  # Mais recentes primeiro
    
    def __str__(self):
        return f"{self.student.user.get_full_name()} - {self.direction} - {self.timestamp}"
```

**Campos importantes:**
- ✅ `timestamp`: Auto-preenchido com data/hora atual (não precisa passar)
- ✅ `direction`: 'ENTRADA' ou 'SAÍDA' (defina na chamada)
- ✅ `is_valid`: True se passou no test de liveness
- ✅ `liveness_score`: Score do algoritmo (0.0 a 1.0)

---

## 2️⃣ FUNÇÃO PARA SALVAR NO BANCO (ia.py)

A função `salvar_registro_acesso()` já existe em seu `ia.py`:

```python
def salvar_registro_acesso(nome_aluno, direcao, liveness_score=0.0):
    """
    Salva um registro de acesso quando o sistema detecta um aluno.
    
    Args:
        nome_aluno: Nome do aluno (username do usuário)
        direcao: "DIREITA" ou "ESQUERDA"
        liveness_score: Score do liveness (0.0 a 1.0)
    
    Returns:
        bool: True se salvou com sucesso, False caso contrário
    """
    try:
        # Mapear direção
        attendance_direction = "ENTRADA" if direcao == "DIREITA" else "SAÍDA"
        
        # 1. Buscar o aluno pelo username
        student = Student.objects.filter(user__username=nome_aluno).first()
        if not student:
            logger.warning(f"Aluno {nome_aluno} não encontrado")
            return False
        
        # 2. Buscar sala ativa
        classroom = Classroom.objects.filter(active_now=True).first()
        if not classroom:
            logger.warning("Nenhuma sala ativa")
            return False
        
        # 3. Criar registro (timestamp é automático!)
        attendance = Attendance.objects.create(
            student=student,
            classroom=classroom,
            liveness_score=liveness_score,
            is_valid=True,
            direction=attendance_direction
        )
        
        logger.info(f"Registrado: {student.user.get_full_name()} "
                   f"({attendance_direction})")
        return True
        
    except Exception as e:
        logger.error(f"Erro ao salvar: {str(e)}")
        return False
```

**Chamada no seu código (ia.py):**

```python
# Quando detectar movimento:
if movimento:
    liveness_score = 1.0 - float(cache["msg"].split(": ")[1]) \
        if ":" in cache["msg"] else 0.98
    
    salvar_registro_acesso(
        nome_aluno=nome_limpo,
        direcao=movimento,  # "DIREITA" ou "ESQUERDA"
        liveness_score=liveness_score
    )
```

---

## 3️⃣ IMPORTS CORRETOS (Já estão em seu ia.py)

```python
# No topo do arquivo ia.py
import logging
from .models import Student, Attendance, Classroom

# Configurar logger para debug
logger = logging.getLogger(__name__)
```

**Por que não é necessário fazer django.setup()?**
- ✅ Quando você chama uma view Django → o Django já está inicializado
- ✅ Quando você roda via manage.py shell → já está inicializado
- ✅ Quando você importa models em outro arquivo Django → já está OK

---

## 4️⃣ THREAD-SAFETY (Para Execução Assíncrona)

Se seu script de IA roda em thread separada, use assim:

```python
from threading import Thread
from django.db import connections

def processar_video_em_thread(arquivo_video):
    """Roda em thread separada"""
    try:
        # 1. Garante conexão fresca para essa thread
        connections.ensure_default_db_connection()
        
        # 2. Seu processamento aqui
        face_rec = FaceRecognition(face_dir="...")
        face_rec.run_recognition(frame)
        
        # 3. Salva no banco (thread-safe!)
        salvar_registro_acesso(
            nome_aluno="fulano",
            direcao="DIREITA",
            liveness_score=0.98
        )
        
    except Exception as e:
        logger.error(f"Erro na thread: {e}")
    finally:
        # Fechar conexão ao final
        connections.close_all()

# Usar em sua view ou comando:
thread = Thread(target=processar_video_em_thread, args=("video.mp4",))
thread.daemon = True
thread.start()
```

---

## 5️⃣ RODAR AS MIGRATIONS

### Passo 1: Criar as migrações
```bash
# No terminal, na pasta do projeto:
cd c:\Users\rech_\Documents\GitHub\projeto_totem_cv

# Ativar virtualenv (se não estiver)
.venv\Scripts\activate

# Gerar migrações pendentes
python manage.py makemigrations
```

**Esperado:**
```
Migrations for 'students':
  students/migrations/0003_attendance_direction.py
    - Add field direction to attendance
```

### Passo 2: Aplicar as migrações
```bash
python manage.py migrate students
```

**Esperado:**
```
Operations to perform:
  Apply all migrations: students
Running migrations:
  Applying students.0003_attendance_direction... OK
```

### Passo 3: Verificar no banco
```bash
# Abrir Django shell
python manage.py shell

# Testando:
>>> from students.models import Attendance
>>> Attendance.objects.all()
<QuerySet []>  # Vazio no início

# Listar todos os registros de presença de um dia
>>> from datetime import date, timedelta
>>> hoje = date.today()
>>> Attendance.objects.filter(timestamp__date=hoje)
```

---

## 6️⃣ EXEMPLO COMPLETO DE USO

### Em uma view Django (views.py):

```python
from django.shortcuts import render
from django.http import JsonResponse
from .models import Attendance, Classroom
from datetime import date

def dashboard_professor(request):
    """Mostra presença do dia"""
    
    # Sala ativa
    classroom = Classroom.objects.filter(active_now=True).first()
    
    # Presença de hoje
    hoje = date.today()
    registros = Attendance.objects.filter(
        classroom=classroom,
        timestamp__date=hoje
    ).order_by('-timestamp')
    
    # Contar por aluno
    entrada = registros.filter(direction='ENTRADA').count()
    saida = registros.filter(direction='SAÍDA').count()
    
    context = {
        'registros': registros,
        'total_entrada': entrada,
        'total_saida': saida,
        'classroom': classroom,
    }
    
    return render(request, 'monitoramento.html', context)

def api_presenca(request):
    """API JSON com dados de presença em tempo real"""
    
    classroom = Classroom.objects.filter(active_now=True).first()
    
    registros = Attendance.objects.filter(
        classroom=classroom
    ).select_related('student__user').values(
        'id',
        'student__user__first_name',
        'student__user__last_name',
        'direction',
        'timestamp',
        'is_valid',
        'liveness_score'
    )[:50]  # Últimos 50
    
    return JsonResponse({
        'success': True,
        'registros': list(registros),
        'classroom': classroom.subject if classroom else None
    })
```

### Em template (monitoramento.html):

```html
<table>
    <thead>
        <tr>
            <th>Aluno</th>
            <th>Direção</th>
            <th>Hora</th>
            <th>Liveness Score</th>
        </tr>
    </thead>
    <tbody>
        {% for registro in registros %}
        <tr>
            <td>{{ registro.student.user.get_full_name }}</td>
            <td>
                {% if registro.direction == 'ENTRADA' %}
                    <span class="badge-green">↗ ENTRADA</span>
                {% else %}
                    <span class="badge-red">↙ SAÍDA</span>
                {% endif %}
            </td>
            <td>{{ registro.timestamp|time:"H:i:s" }}</td>
            <td>
                <progress max="1.0" value="{{ registro.liveness_score }}"></progress>
                {{ registro.liveness_score|floatformat:2 }}
            </td>
        </tr>
        {% endfor %}
    </tbody>
</table>
```

---

## 7️⃣ TROUBLESHOOTING

| Erro | Causa | Solução |
|------|-------|--------|
| `Student matching query does not exist` | Aluno não existe no banco | Verificar se `username` está correto |
| `Nenhuma sala de aula marcada como ativa` | Nenhuma `Classroom.active_now=True` | Ativar uma sala no admin do Django |
| `ModuleNotFoundError: No module named 'django'` | Virtualenv não ativado | Rodar `.venv\Scripts\activate` |
| Timestamp está NULL | Campo não foi migrado | Rodar `python manage.py migrate` |

---

## 8️⃣ CHECKLIST FINAL

- [x] ✅ Modelo `Attendance` existe em `models.py`
- [ ] ⭕ Migração criada (`0003_attendance_direction.py`)
- [ ] ⭕ Migração aplicada (`python manage.py migrate students`)
- [ ] ⭕ Função `salvar_registro_acesso()` importada em `ia.py`
- [ ] ⭕ Chamar função quando movimento detectado
- [ ] ⭕ Testar em Django shell

---

**Dúvidas? Teste no Django Shell:**

```bash
python manage.py shell

>>> from students.models import Attendance, Student, Classroom
>>> from datetime import date

# Ver último registro
>>> Attendance.objects.latest('timestamp')

# Ver estatísticas do dia
>>> Attendance.objects.filter(timestamp__date=date.today()).count()

# Ver apenas entradas
>>> Attendance.objects.filter(direction='ENTRADA').count()
```
