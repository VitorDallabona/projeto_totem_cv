import json
import cv2
import numpy as np
from channels.generic.websocket import WebsocketConsumer
from .models import Classroom

# Importa a IA que já está rodando na memória
from .views import ia_system

class CameraConsumer(WebsocketConsumer):
    def connect(self):
        # Cria uma variável para lembrar qual é a turma dessa conexão
        self.class_id = None 
        self.accept()

    def disconnect(self, close_code):
        pass

    def receive(self, text_data=None, bytes_data=None):
        # 1. MODO TEXTO: Usado apenas no primeiro segundo para configurar a turma[cite: 6]
        if text_data:
            try:
                dados = json.loads(text_data)
                if dados.get('action') == 'init':
                    self.class_id = dados.get('class_id')
                    print(f"WebSocket Vinculado à Turma {self.class_id}")
            except Exception as e:
                print(f"Erro ao ler texto: {e}")
            return

        # 2. MODO BINÁRIO: Usado no loop infinito para receber as fotos puras[cite: 6]
        if bytes_data:
            if not self.class_id:
                self.send(text_data=json.dumps({"status": "erro", "mensagem": "Turma não configurada."}))
                return

            try:
                classroom = Classroom.objects.get(id=self.class_id)
                if not classroom.active_now:
                    self.send(text_data=json.dumps({"status": "ignorado", "mensagem": "Aula inativa."}))
                    return

                # MÁGICA: Pega os bytes da rede e converte direto para imagem OpenCV! (Sem Base64)[cite: 6]
                np_arr = np.frombuffer(bytes_data, np.uint8)
                frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

                if frame is not None and ia_system is not None:
                    
                    # Corta a linha virtual no meio
                    ia_system.LINHA_VIRTUAL_X = frame.shape[1] // 2
                    
                    # Manda processar na IA
                    faces_out, deve_atualizar_tela = ia_system.run_recognition_get_data(frame)
                    
                    # Acha quem foi reconhecido e aprovado no Liveness
                    rostos_reconhecidos = [f['name'].split(" ")[0] for f in faces_out if "Unknown" not in f['name'] and f['color'] == '#00FF00']

                    # Devolve a resposta
                    self.send(text_data=json.dumps({
                        "status": "sucesso",
                        "rostos_processados": len(faces_out),
                        "reconhecidos": rostos_reconhecidos,
                        "atualizar_tela": deve_atualizar_tela,
                        "faces": faces_out,
                        "image_w": frame.shape[1],
                        "image_h": frame.shape[0]
                    }))

            except Exception as e:
                print(f"ERRO WEBSOCKET: {str(e)}")
                self.send(text_data=json.dumps({"status": "erro", "mensagem": str(e)}))