import cv2 as cv
import numpy as np
import os

# Importando os módulos da Minivision (Você precisa ter 
# as pastas 'src' e 'resources' no seu projeto)
from .src.anti_spoof_predict import AntiSpoofPredict
from .src.generate_patches import CropImage

class AISpoofManager:
    def __init__(self, device_id=0):
        
        self.predictor = AntiSpoofPredict(
            device_id=device_id
        )
        
        self.cropper = CropImage()
        
        pasta_atual = os.path.dirname(os.path.abspath(__file__))
        
        # 2. Junta essa pasta com o caminho até os modelos
        self.model_dir = os.path.join(
            pasta_atual, 
            "resources", 
            "anti_spoof_models"
        )
        
    def parse_model_name(self, model_name):
        """Decodifica as dimensões direto do nome do arquivo .pth"""
        
        info = model_name.split('_')[0:-1]
        
        if len(info) == 2:
            h_input, w_input = info[1].split('x')
            return int(h_input), int(w_input), info[0], None
        else:
            # --- CORREÇÃO AQUI ---
            # Usa [-1] para sempre pegar o bloco de dimensões '80x80',
            # não importando quantos números vieram antes.
            h_input, w_input = info[-1].split('x')
            
            return int(h_input), int(w_input), info[-2], float(info[0])

    def avaliar_frame(self, frame_bgr, bbox):
        left, top, right, bottom = bbox
        
        largura = right - left
        altura = bottom - top
        caixa_formatada = [left, top, largura, altura]
        
        # Aumentamos o tamanho mínimo porque em 320px, 30px não tem textura nenhuma
        TAMANHO_MINIMO = 50 
        
        if largura < TAMANHO_MINIMO or altura < TAMANHO_MINIMO:
            return False, "APROXIME-SE"

        previsao_total = np.zeros((1, 3))
        
        # Conta dinamicamente quantos modelos existem na pasta
        modelos_disponiveis = [m for m in os.listdir(self.model_dir) if m.endswith('.pth')]
        num_modelos = len(modelos_disponiveis)
        
        if num_modelos == 0:
            return False, "ERRO: Modelos Liveness ausentes"
        
        for model_name in modelos_disponiveis:
            h_input, w_input, model_type, scale = self.parse_model_name(model_name)
            
            param = {
                "org_img": frame_bgr,
                "bbox": caixa_formatada,
                "scale": scale,
                "out_w": w_input,
                "out_h": h_input,
                "crop": True,
            }
            
            if scale is None:
                param["crop"] = False
                
            img_cortada = self.cropper.crop(**param)
            caminho_modelo = os.path.join(self.model_dir, model_name)
            
            previsao = self.predictor.predict(img_cortada, caminho_modelo)
            previsao_total += previsao
            
        label_vencedor = np.argmax(previsao_total)
        
        # Divide corretamente pela quantidade de modelos encontrados
        confianca = previsao_total[0][label_vencedor] / num_modelos
        
        # Limite reduzido: 80% já garante alta precisão contra fraudes de celular/papel
        LIMITE_CONFIANCA = 0.80 
        
        if label_vencedor == 1 and confianca >= LIMITE_CONFIANCA:
            return True, f"REAL: {confianca:.2f}"
        else:
            return False, f"FALSO: {confianca:.2f}"