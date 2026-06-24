import json
import cv2
import numpy as np
import base64
from channels.generic.websocket import WebsocketConsumer
from .models import Classroom

# Importa a IA que já está rodando na memória (definida no views.py ou apps.py)
from .views import ia_system

class CameraConsumer(WebsocketConsumer):
    def connect(self):
        # Aceita a conexão do navegador
        self.accept()

    def disconnect(self, close_code):
        pass

    def receive(self, text_data):
        # Recebe os dados do JavaScript
        dados = json.loads(text_data)
        image_data = dados.get('image')
        class_id = dados.get('class_id')
        
        if not class_id or not image_data:
            self.send(text_data=json.dumps({"status": "erro", "mensagem": "Dados incompletos."}))
            return

        try:
            classroom = Classroom.objects.get(id=class_id)
            if not classroom.active_now:
                self.send(text_data=json.dumps({"status": "ignorado", "mensagem": "Aula inativa."}))
                return

            # Decodifica a imagem
            format, imgstr = image_data.split(';base64,')
            img_bytes = base64.b64decode(imgstr)
            np_arr = np.frombuffer(img_bytes, np.uint8)
            frame = cv2.imdecode(np_arr, cv2.IMREAD_COLOR)

            if frame is not None and ia_system is not None:
                
                # Corta a linha virtual no meio
                ia_system.LINHA_VIRTUAL_X = frame.shape[1] // 2
                
                # Manda processar na IA
                faces_out, deve_atualizar_tela = ia_system.run_recognition_get_data(frame)
                
                # Acha quem foi reconhecido e aprovado no Liveness
                rostos_reconhecidos = [f['name'].split(" ")[0] for f in faces_out if "Unknown" not in f['name'] and f['color'] == '#00FF00']

                # Devolve a resposta em tempo real pelo WebSocket
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