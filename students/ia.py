import os
import logging

import face_recognition
import cv2 as cv
import math
import numpy as np
import dlib
from cv2 import cuda
import torch
from .encodes import carregar_rostos_conhecidos
from .liveness import AISpoofManager
print(dlib.DLIB_USE_CUDA)
from .models import Student, Attendance, Classroom

# Configurar logger para debug
logger = logging.getLogger(__name__)


def salvar_registro_acesso(nome_aluno, direcao, liveness_score=0.0):
    """
    Salva um registro de acesso no banco de dados.
    Chamado quando o sistema detecta um aluno passando pela linha virtual.
    
    Args:
        nome_aluno: Nome do aluno (como está em Student.user.username ou no face_encoding)
        direcao: "DIREITA" ou "ESQUERDA"
        liveness_score: Score do algoritmo de liveness (padrão 0.0)
    """
    try:
        # Mapear direção para Entrada/Saída
        # DIREITA = ENTRADA (esquerda para direita)
        # ESQUERDA = SAÍDA (direita para esquerda)
        attendance_direction = "ENTRADA" if direcao == "DIREITA" else "SAÍDA"
        
        # Buscar o aluno pelo username (ajuste conforme sua lógica de naming)
        student = Student.objects.filter(user__username=nome_aluno).first()
        
        if not student:
            logger.warning(f"Aluno {nome_aluno} não encontrado no banco de dados")
            print(f"[AVISO] {nome_aluno} não encontrado no banco")
            return False
        
        # Buscar a sala de aula ativa
        classroom = Classroom.objects.filter(active_now=True).first()
        
        if not classroom:
            logger.warning("Nenhuma sala de aula marcada como ativa")
            print(f"[AVISO] Nenhuma sala ativa para registrar {nome_aluno}")
            return False
        
        #trava de segurança caso alguém não matriculado entre na sala de aula
        if student not in classroom.enrolled_students.all():
            print(f"[BLOQUEADO] {student.user.first_name} não está matriculado em {classroom.subject}.")
            return False
        
        # Criar o registro de presença
        attendance = Attendance.objects.create(
            student=student,
            classroom=classroom,
            liveness_score=liveness_score,
            is_valid=True,
            direction=attendance_direction
        )
        
        logger.info(
            f"Acesso registrado: {student.user.get_full_name()} "
            f"({attendance_direction}) em {attendance.timestamp}"
        )
        print(
            f"✓ [BANCO] {student.user.get_full_name()} - {attendance_direction} "
            f"- {attendance.timestamp.strftime('%H:%M:%S')}"
        )
        
        return True
        
    except Exception as e:
        logger.error(f"Erro ao salvar registro de acesso: {str(e)}")
        print(f"[ERRO] Falha ao salvar registro: {str(e)}")
        return False

class FaceRecognition:
    def __init__(self, face_dir):
        self.face_dir = face_dir
        
        # --- Instancia a IA Silenciosa na GPU ---
        self.liveness = AISpoofManager(
            device_id=0
        )
        self.liveness_cache = {}
        # --- Configurações da Linha Virtual ---
        self.posicoes_anteriores = {}
        self.LINHA_VIRTUAL_X = 640 
        
        # --- Configurações do Rastreador ---
        self.trackers = {} 
        self.contador_frames = 0
        self.FRAMES_ATUALIZACAO = 1
        self.FATOR_ESCALA = 1
        self.last_faces_data = []
        
        listas = carregar_rostos_conhecidos(
            self.face_dir
        )   
        
        self.knownFaceEncodings = listas[0]
        self.knownFaceNames = listas[1]


    @staticmethod
    def _bgr_to_hex(cor_bgr):
        b, g, r = cor_bgr
        return f"#{int(r):02X}{int(g):02X}{int(b):02X}"

    def atualizar_banco_rostos(self):
        """
        Lê a pasta novamente. Como o encodes.py tem cache, 
        ele só vai gastar processamento se achar uma foto inédita.
        """
        print("Sincronizando banco de rostos...")
        
        listas = carregar_rostos_conhecidos(
            self.face_dir
        )   
        
        self.knownFaceEncodings = listas[0]
        self.knownFaceNames = listas[1]
        
        print("Sincronização concluída!")
        
    def verificar_sentido(self, nome, centro_x):
        estado_movimento = None
        
        if nome in self.posicoes_anteriores:
            x_passado = self.posicoes_anteriores[nome]
            
            if x_passado < self.LINHA_VIRTUAL_X:
                if centro_x >= self.LINHA_VIRTUAL_X:
                    estado_movimento = "DIREITA"
                    logger.debug(f"Movimento detectado: {nome} cruzou para a DIREITA")
                    
            elif x_passado > self.LINHA_VIRTUAL_X:
                if centro_x <= self.LINHA_VIRTUAL_X:
                    estado_movimento = "ESQUERDA"
                    logger.debug(f"Movimento detectado: {nome} cruzou para a ESQUERDA")
                    
        self.posicoes_anteriores[nome] = centro_x
        return estado_movimento

    def run_recognition(self, frame, frame_offset=(0, 0)):
        self.contador_frames += 1
        offset_x, offset_y = frame_offset
        
        caixas_desenho = {} 
        faces_data = []
        
        # ---------------------------------------------------------
        # FASE 1: DETECÇÃO PESADA (A cada 15 frames)
        # ---------------------------------------------------------
        if self.contador_frames % self.FRAMES_ATUALIZACAO == 0 or not self.trackers:
            
            self.trackers.clear()
            
            small_frame = cv.resize(frame, (0,0), fx=self.FATOR_ESCALA, fy=self.FATOR_ESCALA)
            rgb_small_frame = cv.cvtColor(small_frame, cv.COLOR_BGR2RGB)        

            face_locations = face_recognition.face_locations(rgb_small_frame, model="cnn")
            face_encodings = face_recognition.face_encodings(rgb_small_frame, face_locations)

            contador_desconhecidos = 0

            for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                
                nome = "Unknown"
                nome_exibicao = "Buscando..."
                
                if len(self.knownFaceEncodings) > 0:
                    
                    # TOLERÂNCIA ESTRITA (0.50): Reduz drasticamente falsos positivos (pessoas confundidas)
                    matches = face_recognition.compare_faces(self.knownFaceEncodings, face_encoding, tolerance=0.60)
                    face_distances = face_recognition.face_distance(self.knownFaceEncodings, face_encoding)
                    
                    matchIndex = np.argmin(face_distances)

                    if matches[matchIndex]:
                        nome = self.knownFaceNames[matchIndex]
                        confianca = face_conf(face_distances[matchIndex])
                        nome_exibicao = f'{nome} ({confianca})'
                    else:
                        contador_desconhecidos += 1
                        nome_exibicao = f'Unknown {contador_desconhecidos}'
                else:
                    contador_desconhecidos += 1
                    nome_exibicao = f'Unknown {contador_desconhecidos}'

                mult = int(1 / self.FATOR_ESCALA)
                top *= mult
                right *= mult
                bottom *= mult
                left *= mult
                
                w = right - left
                h = bottom - top
                
                tracker = cv.TrackerKCF_create()
                tracker.init(frame, (left, top, w, h))
                
                self.trackers[nome_exibicao] = tracker
                caixas_desenho[nome_exibicao] = (left, top, right, bottom)

        # ---------------------------------------------------------
        # FASE 2: RASTREAMENTO LEVE (Nos 14 frames intermediários)
        # ---------------------------------------------------------
        else:
            nomes_perdidos = []
            
            for nome_exibicao, tracker in list(self.trackers.items()):
                sucesso, bbox = tracker.update(frame)
                
                if sucesso:
                    x, y, w, h = [int(v) for v in bbox]
                    left, top = x, y
                    right, bottom = x + w, y + h
                    
                    caixas_desenho[nome_exibicao] = (left, top, right, bottom)
                else:
                    nomes_perdidos.append(nome_exibicao)
                    
            # Remove os rastreadores e o cache que falharam
            for nome_exibicao in nomes_perdidos:
                del self.trackers[nome_exibicao]
                
                nome_limpo = nome_exibicao.split(" ")[0]
                if nome_limpo in self.liveness_cache:
                    del self.liveness_cache[nome_limpo]

        # ---------------------------------------------------------
        # FASE 3: LÓGICA DE LIVENESS (SILENT) E DESENHO
        # ---------------------------------------------------------
        
        # --- NOVO: Definindo a quantidade de acertos necessarios ---
        TESTES_NECESSARIOS = 5
        
        for nome_exibicao, (left, top, right, bottom) in caixas_desenho.items():
            nome_limpo = nome_exibicao.split(" ")[0]
            
            cor_caixa = (0, 0, 255) 
            
            if nome_limpo != "Unknown":
                
                # 1. Cria o perfil da pessoa no cache se não existir
                if nome_limpo not in self.liveness_cache:
                    self.liveness_cache[nome_limpo] = {
                        "aprovado": False,
                        "sucessos": 0,          
                        "msg": "Analisando...",
                        "ultimo_teste": 0
                    }
                    
                cache = self.liveness_cache[nome_limpo]
                bbox_atual = (left, top, right, bottom)
                
                # 2. SÓ RODA A IA SE AINDA NÃO FOI APROVADO
                if not cache["aprovado"]:
                    
                    # Roda apenas a cada 10 frames para evitar travamentos
                    frames_passados = self.contador_frames - cache["ultimo_teste"]
                    
                    if frames_passados >= 1:
                        esta_vivo, msg = self.liveness.avaliar_frame(
                            frame, 
                            bbox_atual
                        )
                        
                        cache["ultimo_teste"] = self.contador_frames
                        
                        # --- NOVA LÓGICA DE CONSENSO ---
                        if esta_vivo:
                            cache["sucessos"] += 1
                            
                            # Atualiza a interface visualizando o progresso
                            cache["msg"] = f"Analisando: {cache['sucessos']}/{TESTES_NECESSARIOS}"
                            
                            # So aprova definitivamente se bater a meta
                            if cache["sucessos"] >= TESTES_NECESSARIOS:
                                cache["aprovado"] = True
                                cache["msg"] = msg # Exibe o "REAL: 0.98"
                                
                        else:
                            # Se o modelo disser que e falso, zera o contador
                            # Isso exige que os acertos sejam CONSECUTIVOS
                            cache["sucessos"] = 0
                            cache["msg"] = msg # Exibe o "FALSO" ou "APROXIME-SE"
                        # -------------------------------
                
                # 3. Recupera os dados (da IA agora, ou da memória)
                esta_vivo = cache["aprovado"]
                texto_status = cache["msg"]
                
                if esta_vivo:
                    cor_caixa = (0, 255, 0) # Verde = Genuíno
                    
                    centro_x = int((left + right) / 2)
                    movimento = self.verificar_sentido(
                        nome_limpo,
                        centro_x + offset_x
                    )
                    
                    if movimento:
                        # Salvar no banco em vez de apenas fazer print
                        liveness_score = 1.0 - float(cache["msg"].split(": ")[1]) if ":" in cache["msg"] else 0.98
                        salvar_registro_acesso(
                            nome_aluno=nome_limpo,
                            direcao=movimento,
                            liveness_score=liveness_score
                        )
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

            # --- Desenho da Interface no Vídeo ---
            cv.rectangle(
                frame, 
                (left, top), 
                (right, bottom), 
                cor_caixa, 
                2
            )
            
            cv.rectangle(
                frame, 
                (left, bottom - 35), 
                (right, bottom), 
                cor_caixa, 
                -1
            )
            
            cv.putText(
                frame, 
                nome_exibicao, 
                (left + 6, bottom - 6), 
                cv.FONT_HERSHEY_COMPLEX, 
                0.6, 
                (255, 255, 255), 
                2
            )
            
            cv.putText(
                frame, 
                texto_status, 
                (left, top - 10), 
                cv.FONT_HERSHEY_SIMPLEX, 
                0.7, 
                cor_caixa, 
                2
            )
            
        # --- Desenha a Linha Virtual (Catraca) ---
        altura_frame = frame.shape[0]
        
        cv.line(
            frame, 
            (self.LINHA_VIRTUAL_X, 0), 
            (self.LINHA_VIRTUAL_X, altura_frame), 
            (0, 0, 255), 
            2
        )

        self.last_faces_data = faces_data

        return frame

    def run_recognition_get_data(self, frame, frame_offset=(0, 0)):
        self.run_recognition(frame, frame_offset=frame_offset)
        return self.last_faces_data


def face_conf(face_distance, face_match_threshold=0.65):
    range_val = (1.0 - face_match_threshold)
    linear_val = (1.0 - face_distance) / (range_val * 2.0)

    if face_distance > face_match_threshold:
        return str(round(linear_val * 100, 2)) + '%'
    else:
        value = (linear_val + ((1.0 - linear_val) * math.pow((linear_val - 0.5) * 2, 0.2 ) )) * 100
        return str(round(value, 2)) + '%'