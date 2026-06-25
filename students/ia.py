import os
import logging

# Imports pesados - comentados para shells/migrations
try:
    import face_recognition
    import cv2 as cv
    import math
    import numpy as np
    import dlib
    from cv2 import cuda
    from .encodes import carregar_rostos_conhecidos
    from .liveness import AISpoofManager
    print(dlib.DLIB_USE_CUDA)
except ImportError as e:
    print(f"⚠️  Aviso: Importações pesadas indisponíveis: {e}")
    print("   Função salvar_registro_acesso() funcionará normalmente")

from .models import Student, Attendance, Classroom

# Configurar logger para debug
logger = logging.getLogger(__name__)

def salvar_registro_acesso(nome_aluno, direcao, liveness_score=0.0):
    try:
        attendance_direction = "ENTRADA" if direcao == "DIREITA" else "SAÍDA"
        student = Student.objects.filter(user__username=nome_aluno).first()
        
        if not student:
            return False
        
        classroom = Classroom.objects.filter(active_now=True).first()
        
        if not classroom:
            return False
        
        if student not in classroom.enrolled_students.all():
            return False
        
        attendance = Attendance.objects.create(
            student=student,
            classroom=classroom,
            liveness_score=liveness_score,
            is_valid=True,
            direction=attendance_direction
        )
        
        print(f"✓ [BANCO] {student.user.get_full_name()} - {attendance_direction} - {attendance.timestamp.strftime('%H:%M:%S')}")
        return True
        
    except Exception as e:
        print(f"[ERRO] Falha ao salvar registro: {str(e)}")
        return False

class FaceRecognition:
    def __init__(self, face_dir):
        self.face_dir = face_dir
        self.liveness = AISpoofManager(device_id=0)
        self.liveness_cache = {}
        self.posicoes_anteriores = {}
        
        self.trackers = {} 
        self.contador_frames = 0
        self.FATOR_ESCALA = 1
        self.last_faces_data = [] 
        
        # --- OTIMIZAÇÃO VARIÁVEL DO LIVENESS ---
        self.FRAMES_ATUALIZACAO = 5
        
        # O Liveness agora roda proporcionalmente à IA de reconhecimento.
        # Exemplo: 15 // 3 = Roda a cada 5 frames. É dinâmico!
        self.INTERVALO_LIVENESS = max(1, self.FRAMES_ATUALIZACAO // 3)
        # ---------------------------------------
        
        # A BANDEIRA DE ATUALIZAÇÃO DO BANCO
        self.teve_mudanca_banco = False
        
        listas = carregar_rostos_conhecidos(self.face_dir)   
        self.knownFaceEncodings = listas[0]
        self.knownFaceNames = listas[1]

    @staticmethod
    def _bgr_to_hex(cor_bgr):
        b, g, r = cor_bgr
        return f"#{int(r):02X}{int(g):02X}{int(b):02X}"

    def atualizar_banco_rostos(self):
        print("Sincronizando banco de rostos...")
        listas = carregar_rostos_conhecidos(self.face_dir)   
        self.knownFaceEncodings = listas[0]
        self.knownFaceNames = listas[1]
        print("Sincronização concluída!")
        
    def verificar_sentido(self, nome, centro_x, linha_virtual_x):
        estado_movimento = None
        if nome in self.posicoes_anteriores:
            x_passado = self.posicoes_anteriores[nome]
            if x_passado < linha_virtual_x:
                if centro_x >= linha_virtual_x:
                    estado_movimento = "DIREITA"
            elif x_passado > linha_virtual_x:
                if centro_x <= linha_virtual_x:
                    estado_movimento = "ESQUERDA"
                    
        self.posicoes_anteriores[nome] = centro_x
        return estado_movimento

    def run_recognition(self, frame, frame_offset=(0, 0)):
        self.contador_frames += 1
        offset_x, offset_y = frame_offset
        altura_frame, largura_frame = frame.shape[:2]
        linha_virtual_x = largura_frame // 2 
        
        caixas_desenho = {} 
        faces_data = [] 
        
        if self.contador_frames % self.FRAMES_ATUALIZACAO == 0 or not self.trackers:
            self.trackers.clear()
            small_frame = cv.resize(frame, (0,0), fx=self.FATOR_ESCALA, fy=self.FATOR_ESCALA)
            rgb_small_frame = cv.cvtColor(small_frame, cv.COLOR_BGR2RGB)        

            face_locations = face_recognition.face_locations(rgb_small_frame, model="SCRFD")
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

            contador_desconhecidos = 0

            for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                nome = "Unknown"
                nome_exibicao = "Buscando..."
                
                if len(self.knownFaceEncodings) > 0:
                    matches = face_recognition.compare_faces(self.knownFaceEncodings, face_encoding, tolerance=0.55)
                    face_distances = face_recognition.face_distance(self.knownFaceEncodings, face_encoding)
                    matchIndex = np.argmin(face_distances)

                    if matches[matchIndex]:
                        nome = self.knownFaceNames[matchIndex]
                        confianca = face_conf(face_distances[matchIndex], 0.55)
                        nome_exibicao = f'{nome} ({confianca})'
                    else:
                        contador_desconhecidos += 1
                        nome_exibicao = f'Unknown {contador_desconhecidos}'
                else:
                    contador_desconhecidos += 1
                    nome_exibicao = f'Unknown {contador_desconhecidos}'

                mult = int(1 / self.FATOR_ESCALA)
                top *= mult; right *= mult; bottom *= mult; left *= mult
                w = right - left; h = bottom - top
                
                tracker = cv.TrackerCSRT_create()
                tracker.init(frame, (left, top, w, h))
                
                self.trackers[nome_exibicao] = tracker
                caixas_desenho[nome_exibicao] = (left, top, right, bottom)

        else:
            nomes_perdidos = []
            for nome_exibicao, tracker in list(self.trackers.items()):
                sucesso, bbox = tracker.update(frame)
                if sucesso:
                    x, y, w, h = [int(v) for v in bbox]
                    caixas_desenho[nome_exibicao] = (x, y, x + w, y + h)
                else:
                    nomes_perdidos.append(nome_exibicao)
                    
            for nome_exibicao in nomes_perdidos:
                del self.trackers[nome_exibicao]

        # ---------------------------------------------------------
        # FASE 3: LÓGICA DE LIVENESS (SILENT)
        # ---------------------------------------------------------
        TESTES_NECESSARIOS = 4
        
        for nome_exibicao, (left, top, right, bottom) in caixas_desenho.items():
            
            # === TRAVA DE SEGURANÇA (CLIPPING) ===
            # Impede que as coordenadas vazem da tela e quebrem o OpenCV
            left = max(0, int(left))
            top = max(0, int(top))
            right = min(largura_frame, int(right))
            bottom = min(altura_frame, int(bottom))
            
            # Se o rosto estiver tão na borda que a caixa sumiu, ignora este frame
            if right <= left or bottom <= top:
                continue
            # =====================================

            nome_limpo = nome_exibicao.split(" ")[0]
            cor_caixa = (0, 0, 255) 
            
            if "Unknown" not in nome_limpo:
                if nome_limpo not in self.liveness_cache:
                    self.liveness_cache[nome_limpo] = {
                        "aprovado": False, "sucessos": 0, "msg": "Analisando...", "ultimo_teste": 0
                    }
                    
                cache = self.liveness_cache[nome_limpo]
                bbox_atual = (left, top, right, bottom)
                
                if not cache["aprovado"]:
                    frames_passados = self.contador_frames - cache["ultimo_teste"]
                    
                    # --- AQUI ESTÁ A VARIÁVEL ---
                    if frames_passados >= self.INTERVALO_LIVENESS: 
                        esta_vivo, msg = self.liveness.avaliar_frame(frame, bbox_atual)
                        cache["ultimo_teste"] = self.contador_frames
                        
                        if esta_vivo:
                            cache["sucessos"] += 1
                            cache["msg"] = f"Analisando: {cache['sucessos']}/{TESTES_NECESSARIOS}"
                            if cache["sucessos"] >= TESTES_NECESSARIOS:
                                cache["aprovado"] = True
                                cache["msg"] = msg 
                        else:
                            cache["sucessos"] = 0
                            cache["msg"] = msg 
                
                esta_vivo = cache["aprovado"]
                texto_status = cache["msg"]
                
                if esta_vivo:
                    cor_caixa = (0, 255, 0) # Verde = Genuíno
                    centro_x = int((left + right) / 2)
                    movimento = self.verificar_sentido(nome_limpo, centro_x + offset_x, linha_virtual_x)
                    
                    if movimento:
                        liveness_score = 1.0 - float(cache["msg"].split(": ")[1]) if ":" in cache["msg"] else 0.98
                        salvou = salvar_registro_acesso(nome_aluno=nome_limpo, direcao=movimento, liveness_score=liveness_score)
                        if salvou:
                            self.teve_mudanca_banco = True # AVISA O SISTEMA PRA RECARREGAR A TELA
            else:
                texto_status = "Buscando..."

            faces_data.append({
                "name": nome_exibicao,
                "status": texto_status,
                "color": self._bgr_to_hex(cor_caixa),
                "box": {
                    "top": int(top + offset_y),
                    "right": int(right + offset_x),
                    "bottom": int(bottom + offset_y),
                    "left": int(left + offset_x),
                }
            })

            cv.rectangle(frame, (left, top), (right, bottom), cor_caixa, 2)
            cv.rectangle(frame, (left, bottom - 35), (right, bottom), cor_caixa, -1)
            cv.putText(frame, nome_exibicao, (left + 6, bottom - 6), cv.FONT_HERSHEY_COMPLEX, 0.6, (255, 255, 255), 2)
            cv.putText(frame, texto_status, (left, top - 10), cv.FONT_HERSHEY_SIMPLEX, 0.7, cor_caixa, 2)
            
        cv.line(frame, (linha_virtual_x, 0), (linha_virtual_x, altura_frame), (0, 0, 255), 2)

        self.last_faces_data = faces_data
        return frame

    def run_recognition_get_data(self, frame, frame_offset=(0, 0)):
        self.teve_mudanca_banco = False # Zera a bandeira antes de analisar
        self.run_recognition(frame, frame_offset=frame_offset)
        # Devolve as 2 informações corretamente para o views.py
        return self.last_faces_data, self.teve_mudanca_banco

def face_conf(face_distance, face_match_threshold=0.55):
    range_val = (1.0 - face_match_threshold)
    linear_val = (1.0 - face_distance) / (range_val * 2.0)
    if face_distance > face_match_threshold:
        return str(round(linear_val * 100, 2)) + '%'
    else:
        value = (linear_val + ((1.0 - linear_val) * math.pow((linear_val - 0.5) * 2, 0.2 ) )) * 100
        return str(round(value, 2)) + '%'