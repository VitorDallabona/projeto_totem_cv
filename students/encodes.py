import os
import json
import numpy as np
import cv2 as cv

def carregar_rostos_conhecidos(face_dir, face_app):
    pasta_json = "media/faces"
    caminho_json = os.path.join(pasta_json, "encodes.json")
    
    if not os.path.exists(pasta_json):
        os.makedirs(pasta_json)

    # Dicionário temporário para agrupar embeddings por matrícula
    temp_embeddings = {}

    # 1. Processar todas as fotos recursivamente (pastas dos alunos)
    # A estrutura esperada é: media/faces/MATRICULA/foto_0.jpg
    for root, dirs, files in os.walk(face_dir):
        for file in files:
            if not file.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            
            # Identifica a matrícula: se estiver em subpasta, usa o nome da pasta
            # Se estiver na raiz, usa o nome do arquivo splitado
            rel_path = os.path.relpath(root, face_dir)
            if rel_path == ".":
                matricula = file.split('-')[0]
            else:
                matricula = os.path.basename(root)
            
            caminho_imagem = os.path.join(root, file)
            face_image = cv.imread(caminho_imagem)
            
            if face_image is None:
                continue
            
            # Redução para performance
            h, w = face_image.shape[:2]
            if max(h, w) > 800:
                escala = 800 / max(h, w)
                face_image = cv.resize(face_image, (0, 0), fx=escala, fy=escala)
                
            # Extração
            faces = face_app.get(face_image)
            
            if len(faces) > 0:
                if matricula not in temp_embeddings:
                    temp_embeddings[matricula] = []
                temp_embeddings[matricula].append(faces[0].embedding)
                print(f"✓ Extraído rosto para {matricula} de {file}")

    # 2. Calcular a média dos embeddings e salvar no JSON consolidado
    dados_rostos_finais = {}
    
    for matricula, lista_embs in temp_embeddings.items():
        # Calcula a média aritmética dos vetores (deixa a IA muito mais robusta)
        embedding_medio = np.mean(lista_embs, axis=0)
        dados_rostos_finais[matricula] = embedding_medio.tolist()

    # Salva o arquivo consolidado
    with open(caminho_json, 'w') as arquivo:
        json.dump(dados_rostos_finais, arquivo, indent=4)
        print(f"✅ Cache consolidado com {len(dados_rostos_finais)} alunos processados.")

    # 3. Preparar listas para a IA
    known_encodings = []
    known_names = []
    
    for matricula, encoding_list in dados_rostos_finais.items():
        known_names.append(str(matricula)) # Força string para evitar conflitos
        known_encodings.append(np.array(encoding_list, dtype=np.float32))
        
    print(f"Total de {len(known_names)} assinaturas ArcFace 512D carregadas na memória.")
    
    return known_encodings, known_names