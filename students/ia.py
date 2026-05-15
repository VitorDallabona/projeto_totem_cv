import face_recognition
import os
import cv2 as cv
import math
import numpy as np
import dlib
from .encodes import carregar_rostos_conhecidos
from cv2 import cuda

from .liveness import AISpoofManager 

print(dlib.DLIB_USE_CUDA)

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
        self.LINHA_VIRTUAL_X = 320 
        
        # --- Configurações do Rastreador ---
        self.trackers = {} 
        self.contador_frames = 0
        self.FRAMES_ATUALIZACAO = 10
        self.FATOR_ESCALA = 1
        
        listas = carregar_rostos_conhecidos(
            self.face_dir
        )   
        
        self.knownFaceEncodings = listas[0]
        self.knownFaceNames = listas[1]

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
                    print(f">>> {nome} cruzou para a DIREITA.")
                    
            elif x_passado > self.LINHA_VIRTUAL_X:
                if centro_x <= self.LINHA_VIRTUAL_X:
                    estado_movimento = "ESQUERDA"
                    print(f"<<< {nome} cruzou para a ESQUERDA.")
                    
        self.posicoes_anteriores[nome] = centro_x
        return estado_movimento

    def run_recognition(self, frame):
        self.contador_frames += 1
        
        caixas_desenho = {} 
        
        # ---------------------------------------------------------
        # FASE 1: DETECÇÃO PESADA (A cada 15 frames)
        # ---------------------------------------------------------
        if self.contador_frames % self.FRAMES_ATUALIZACAO == 0 or not self.trackers:
            
            self.trackers.clear()
            
            small_frame = cv.resize(
                frame, 
                (0,0), 
                fx=self.FATOR_ESCALA, 
                fy=self.FATOR_ESCALA
            )
            
            rgb_small_frame = cv.cvtColor(
                small_frame, 
                cv.COLOR_BGR2RGB
            )        

            face_locations = face_recognition.face_locations(
                rgb_small_frame, 
                model="cnn"
            )
            
            face_encodings = face_recognition.face_encodings(
                rgb_small_frame, 
                face_locations
            )

            for (top, right, bottom, left), face_encoding in zip(face_locations, face_encodings):
                
                # --- NOVA TRAVA DE SEGURANÇA ---
                # Só faz a matemática se o banco de rostos não estiver vazio
                if len(self.knownFaceEncodings) > 0:
                    
                    matches = face_recognition.compare_faces(
                        self.knownFaceEncodings, 
                        face_encoding
                    )
                    
                    face_distances = face_recognition.face_distance(
                        self.knownFaceEncodings, 
                        face_encoding
                    )
                    
                    matchIndex = np.argmin(face_distances)

                    if matches[matchIndex]:
                        nome = self.knownFaceNames[matchIndex]
                        confianca = face_conf(
                            face_distances[matchIndex]
                        )
                        nome_exibicao = f'{nome} ({confianca})'
                        
                        mult = int(1 / self.FATOR_ESCALA)
                        top *= mult
                        right *= mult
                        bottom *= mult
                        left *= mult
                        
                        w = right - left
                        h = bottom - top
                        
                        tracker = cv.TrackerCSRT_create()
                        tracker.init(
                            frame, 
                            (left, top, w, h)
                        )
                        
                        self.trackers[nome_exibicao] = tracker
                        caixas_desenho[nome_exibicao] = (left, top, right, bottom)

        # ---------------------------------------------------------
        # FASE 2: RASTREAMENTO LEVE (Nos 14 frames intermediários)
        # ---------------------------------------------------------
        else:
            nomes_perdidos = []
            
            for nome_exibicao, tracker in self.trackers.items():
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
                    
                    if frames_passados >= 10:
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
                        centro_x
                    )
                    
                    if movimento:
                        print(f"[{nome_limpo}] ACESSO LIBERADO: {movimento}.")
            else:
                texto_status = "Buscando..."

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

        return frame


def face_conf(face_distance, face_match_threshold=0.8):
    range_val = (1.0 - face_match_threshold)
    linear_val = (1.0 - face_distance) / (range_val * 2.0)

    if face_distance > face_match_threshold:
        return str(round(linear_val * 100, 2)) + '%'
    else:
        value = (linear_val + ((1.0 - linear_val) * math.pow((linear_val - 0.5) * 2, 0.2 ) )) * 100
        return str(round(value, 2)) + '%'