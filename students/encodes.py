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
    # A estrutura esperada é: media/faces/MATRICULA/foto_0.jpg ou media/faces/MATRICULA.jpg
    for root, dirs, files in os.walk(face_dir):
        for file in files:
            if not file.lower().endswith(('.png', '.jpg', '.jpeg')):
                continue
            
            # Identifica a matrícula sem extensão
            rel_path = os.path.relpath(root, face_dir)
            if rel_path == ".":
                # Remove extensão e pega a matrícula (ex: 2023510088.jpg -> 2023510088)
                matricula = os.path.splitext(file)[0].split('-')[0]
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

    # 2. Salvar todos os embeddings agregados no JSON consolidado (Multi-Template)
    dados_rostos_finais = {}
    
    for matricula, lista_embs in temp_embeddings.items():
        # Salvamos todos os embeddings obtidos (lista de listas de floats)
        # Cada embedding é normalizado individualmente
        dados_rostos_finais[matricula] = [emb.tolist() for emb in lista_embs]

    # Salva o arquivo consolidado
    with open(caminho_json, 'w') as arquivo:
        json.dump(dados_rostos_finais, arquivo, indent=4)
        print(f"✅ Cache consolidado com {len(dados_rostos_finais)} alunos processados.")

    # 3. Preparar listas para a IA (converte 1D/2D para o formato linear de comparação do ArcFace)
    known_encodings = []
    known_names = []
    
    for matricula, encoding_list in dados_rostos_finais.items():
        # Limpa qualquer extensão residual se houver
        matricula_limpa = os.path.splitext(str(matricula))[0]
        
        if len(encoding_list) > 0 and isinstance(encoding_list[0], list):
            # Formato novo: lista de listas (Multi-Template)
            for single_emb in encoding_list:
                known_names.append(matricula_limpa)
                known_encodings.append(np.array(single_emb, dtype=np.float32))
        else:
            # Formato antigo: lista de floats (Single-Template)
            known_names.append(matricula_limpa)
            known_encodings.append(np.array(encoding_list, dtype=np.float32))
        
    print(f"Total de {len(known_names)} assinaturas biométricas ArcFace carregadas na memória.")
    
    return known_encodings, known_names