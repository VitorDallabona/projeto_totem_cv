# 🗂️ ARQUITETURA DO SISTEMA - BANCO DE DADOS

## 📊 Diagrama Relacional

```
┌─────────────────────┐
│   django.auth User  │
│  (auth_user)        │
├─────────────────────┤
│ id (PK)             │
│ username ✓          │
│ first_name          │
│ last_name           │
│ email               │
│ password            │
│ is_staff            │
│ is_active           │
│ last_login ✓        │
│ date_joined         │
└──────────┬──────────┘
           │
           │ OneToOne
           │ (on_delete=CASCADE)
           │
    ┌──────▼──────────────────┐
    │  students.Profile       │
    │  (students_profile)     │
    ├─────────────────────────┤
    │ id (PK)                 │
    │ user_id (FK) ──────────→│ (to User)
    │ is_teacher              │
    └─────────────────────────┘


┌─────────────────────────────────────────────┐
│    django.auth User                         │
│    (auth_user)                              │
│    └─ first_name: "João"                   │
│    └─ last_name: "Silva"                   │
│    └─ username: "prof_joao"                │
└──────────┬────────────────────┬─────────────┘
           │                    │
    OneToOne                OneToOne
           │                    │
    ┌──────▼──────┐    ┌───────▼───────┐
    │ Profile     │    │ Student       │
    │ (teacher)   │    │ (student)     │
    └─────────────┘    ├───────────────┤
                       │ registration_id
                       │ face_encoding
                       │ profile_photo
                       │ created_at
                       └───────┬───────┘
                               │
                        ManyToMany
                               │
                       ┌───────▼──────────┐
                       │ Classroom        │
                       │ (with teachers)  │
                       ├──────────────────┤
                       │ id               │
                       │ subject          │
                       │ teacher          │
                       │ active_now ✓     │
                       │ enrolled_students│
                       └────────┬─────────┘
                                │
                           ForeignKey
                                │
                       ┌────────▼──────────────┐
                       │ Attendance           │
                       │ (students_attendance)│
                       ├──────────────────────┤
                       │ id (PK)              │
                       │ student_id (FK) ────→ Student
                       │ classroom_id (FK) ──→ Classroom
                       │ timestamp ✓ (auto!)  │
                       │ liveness_score       │
                       │ is_valid             │
                       │ direction ✓ (NOVO!)  │
                       └──────────────────────┘
                          └─ ENTRADA ou SAÍDA
                          └─ auto_now_add=True
```

---

## 📋 Detalhamento das Tabelas

### 1️⃣ Tabela: `auth_user` (Django padrão)

```sql
CREATE TABLE auth_user (
    id INTEGER PRIMARY KEY,
    username VARCHAR(150) UNIQUE NOT NULL,
    first_name VARCHAR(150),
    last_name VARCHAR(150),
    email VARCHAR(254),
    password VARCHAR(128) NOT NULL,
    is_staff BOOLEAN,
    is_active BOOLEAN,
    last_login DATETIME,
    date_joined DATETIME
);
```

**Exemplo de dados:**
```
id | username    | first_name | last_name  | is_staff | is_active
1  | prof_joao   | João       | Silva      | False    | True
2  | pedro       | Pedro      | Santos     | False    | True
3  | maria       | Maria      | Oliveira   | False    | True
```

---

### 2️⃣ Tabela: `students_profile` (OneToOne com User)

```sql
CREATE TABLE students_profile (
    id INTEGER PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES auth_user(id),
    is_teacher BOOLEAN DEFAULT False
);
```

**Exemplo de dados:**
```
id | user_id | is_teacher
1  | 1       | True      ← prof_joao é professor
2  | 2       | False     ← pedro é aluno
3  | 3       | False     ← maria é aluno
```

---

### 3️⃣ Tabela: `students_student` (OneToOne com User)

```sql
CREATE TABLE students_student (
    id INTEGER PRIMARY KEY,
    user_id INTEGER UNIQUE NOT NULL REFERENCES auth_user(id),
    registration_id VARCHAR(20) UNIQUE NOT NULL,
    face_encoding JSON NOT NULL,
    profile_photo VARCHAR(100),
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP
);
```

**Exemplo de dados:**
```
id | user_id | registration_id | face_encoding       | created_at
1  | 2       | 2024001         | [0.1, 0.2, 0.3]   | 2026-05-21 19:15:00
2  | 3       | 2024002         | [0.4, 0.5, 0.6]   | 2026-05-21 19:15:15
```

---

### 4️⃣ Tabela: `students_classroom` (Turma/Disciplina)

```sql
CREATE TABLE students_classroom (
    id INTEGER PRIMARY KEY,
    subject VARCHAR(100) NOT NULL,
    teacher VARCHAR(100) NOT NULL,
    active_now BOOLEAN DEFAULT False
);
```

**Exemplo de dados:**
```
id | subject                    | teacher      | active_now
1  | Programação em Python      | João Silva   | True
```

---

### 5️⃣ Tabela: `students_classroom_enrolled_students` (ManyToMany)

```sql
CREATE TABLE students_classroom_enrolled_students (
    id INTEGER PRIMARY KEY,
    classroom_id INTEGER NOT NULL REFERENCES students_classroom(id),
    student_id INTEGER NOT NULL REFERENCES students_student(id),
    UNIQUE(classroom_id, student_id)
);
```

**Exemplo de dados:**
```
id | classroom_id | student_id
1  | 1            | 1          ← Pedro inscrito na sala 1
2  | 1            | 2          ← Maria inscrita na sala 1
```

---

### 6️⃣ Tabela: `students_attendance` ⭐ PRINCIPAL

```sql
CREATE TABLE students_attendance (
    id INTEGER PRIMARY KEY,
    student_id INTEGER NOT NULL REFERENCES students_student(id),
    classroom_id INTEGER NOT NULL REFERENCES students_classroom(id),
    timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,  -- ✅ AUTO!
    liveness_score REAL NOT NULL,
    is_valid BOOLEAN DEFAULT False,
    direction VARCHAR(10) NOT NULL CHECK(direction IN ('ENTRADA', 'SAÍDA')),
    FOREIGN KEY(student_id) REFERENCES students_student(id),
    FOREIGN KEY(classroom_id) REFERENCES students_classroom(id)
);
```

**Exemplo de dados (REAL DO TESTE):**
```
id | student_id | classroom_id | timestamp          | liveness_score | is_valid | direction
1  | 1          | 1            | 2026-05-21 19:18:17| 0.98           | True     | ENTRADA
2  | 2          | 1            | 2026-05-21 19:19:15| 0.95           | True     | SAÍDA
```

---

## 🔄 Fluxo de Dados (Como tudo se conecta)

```
1. CÂMERA detecta aluno
   ↓
2. IA reconhece: "pedro"
   ↓
3. Calcula liveness_score: 0.98
   ↓
4. Detecta movimento: DIREITA (esquerda para direita)
   ↓
5. Chama: salvar_registro_acesso("pedro", "DIREITA", 0.98)
   ↓
6. Função mapeia: DIREITA → ENTRADA
   ↓
7. Busca Student onde user.username = "pedro"
   ├─ Encontra: Student(id=1, user_id=2, registration_id='2024001')
   ↓
8. Busca Classroom onde active_now = True
   ├─ Encontra: Classroom(id=1, subject='Programação em Python')
   ↓
9. Cria Attendance com:
   ├─ student_id = 1
   ├─ classroom_id = 1
   ├─ timestamp = NOW() ✅ AUTOMÁTICO!
   ├─ liveness_score = 0.98
   ├─ is_valid = True
   ├─ direction = 'ENTRADA'
   ↓
10. Salva no banco (INSERT)
    ↓
11. Imprime: ✓ [BANCO] Pedro Santos - ENTRADA - 19:18:17
    ↓
12. Retorna: True
```

---

## 🔍 Exemplos de Queries com Relacionamentos

### Query 1: Ver todos os registros de um aluno
```python
# Django ORM
pedro = Student.objects.get(user__username='pedro')
registros = pedro.attendances.all()  # ← related_name='attendances'

# SQL equivalente
SELECT * FROM students_attendance 
WHERE student_id = (
    SELECT id FROM students_student 
    WHERE user_id = (
        SELECT id FROM auth_user WHERE username = 'pedro'
    )
);
```

### Query 2: Ver todos os registros de uma sala
```python
# Django ORM
sala = Classroom.objects.get(subject='Programação em Python')
registros = sala.attendance_records.all()  # ← related_name='attendance_records'

# SQL equivalente
SELECT * FROM students_attendance 
WHERE classroom_id = 1;
```

### Query 3: Contar entradas vs saídas
```python
# Django ORM
entradas = Attendance.objects.filter(direction='ENTRADA').count()
saidas = Attendance.objects.filter(direction='SAÍDA').count()

# SQL equivalente
SELECT direction, COUNT(*) FROM students_attendance 
GROUP BY direction;
```

### Query 4: Ver score médio de liveness
```python
# Django ORM
from django.db.models import Avg
media = Attendance.objects.aggregate(Avg('liveness_score'))

# SQL equivalente
SELECT AVG(liveness_score) FROM students_attendance;
```

### Query 5: Tempo que cada aluno ficou na sala
```python
# Django Python
for aluno in Attendance.objects.filter(direction='ENTRADA'):
    saida = Attendance.objects.filter(
        student=aluno.student,
        direction='SAÍDA',
        timestamp__gt=aluno.timestamp
    ).first()
    
    if saida:
        duracao = (saida.timestamp - aluno.timestamp).total_seconds()
        print(f"{aluno.student.user.first_name}: {duracao/60:.0f} minutos")
```

---

## 📈 Estatísticas possíveis

Com esta arquitetura você pode fazer:

✅ **Presença diária**
```python
from datetime import date
hoje = Attendance.objects.filter(timestamp__date=date.today()).count()
```

✅ **Alunos mais frequentes**
```python
from django.db.models import Count
top = Student.objects.annotate(
    total=Count('attendances')
).order_by('-total')[:10]
```

✅ **Taxa de liveness (validação)**
```python
total = Attendance.objects.count()
validos = Attendance.objects.filter(is_valid=True).count()
taxa = (validos / total) * 100
```

✅ **Tempo médio em sala**
```python
# Para cada student-day pair, calcular
```

✅ **Horários de pico**
```python
# Agrupar por hora do dia
```

---

## 🚀 Conclusão

A arquitetura está **pronta para:**
- ✅ Escalar para múltiplas salas
- ✅ Múltiplos professores
- ✅ Múltiplas câmeras
- ✅ Análise de tendências
- ✅ Alertas e notificações
- ✅ Integração com sistemas externos

**Banco de dados normalizado, com relacionamentos corretos e pronto para produção!**
