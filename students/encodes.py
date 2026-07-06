import face_recognition
import os
import json
import numpy as np
import cv2 as cv

def carregar_rostos_conhecidos(face_dir):
    pasta_json = "media/faces"
    caminho_json = os.path.join(pasta_json, "encodes.json")
    
    if not os.path.exists(pasta_json):
        os.makedirs(pasta_json)

    dados_rostos = {}

    if os.path.exists(caminho_json):
        print(f"Carregando cache de rostos de {caminho_json}...")
        with open(caminho_json, 'r') as arquivo:
            dados_rostos = json.load(arquivo)
    else:
        print("Nenhum cache encontrado.")

    houve_atualizacao = False

    for person in os.listdir(face_dir):
        if not person.lower().endswith(('.png', '.jpg', '.jpeg')):
            continue
        
        nome_arquivo = os.path.splitext(person)[0]
        
        if nome_arquivo in dados_rostos:
            continue
            
        print(f"Treinando novo rosto: {nome_arquivo} (Isso pode demorar um pouco...)")
        
        caminho_imagem = os.path.join(face_dir, person)
        face_image = face_recognition.load_image_file(caminho_imagem)
        
        # ====================================================================
        # PASSO 1: REDUÇÃO DE FOTOS GIGANTES (Evita OOM e lentidão extrema)
        # ====================================================================
        h, w = face_image.shape[:2]
        tamanho_maximo = 800
        
        if max(h, w) > tamanho_maximo:
            escala = tamanho_maximo / max(h, w)
            # Redimensiona mantendo a proporção
            face_image = cv.resize(face_image, (0, 0), fx=escala, fy=escala)
            
        # ====================================================================
        # PASSO 2: BUSCA COM HOG + UPSAMPLE (Foge do bug do cuDNN)
        # ====================================================================
        # O upsample=2 estica a imagem na memória (RAM normal) e acha os rostos 
        # que o HOG padrão costuma ignorar, sem acionar a GPU.
        locs = face_recognition.face_locations(face_image, model="hog", number_of_times_to_upsample=2)
        
        if len(locs) > 0:
            # PASSO 3: Extrair o código do rosto
            encodings = face_recognition.face_encodings(
                face_image, 
                known_face_locations=locs,
                model="large", 
                num_jitters=10
            )
            
            if len(encodings) > 0:
                dados_rostos[nome_arquivo] = encodings[0].tolist()
                houve_atualizacao = True
                print(f"✓ Sucesso: Rosto de {nome_arquivo} extraído!")
            else:
                print(f"AVISO: Rosto detectado, mas falhou ao codificar na foto {person}!")
        else:
            print(f"AVISO: Nenhum rosto achado na foto {person}! DICA: Tente recortar a foto deixando só o rosto.")

    if houve_atualizacao:
        with open(caminho_json, 'w') as arquivo:
            json.dump(dados_rostos, arquivo, indent=4)

    known_encodings = []
    known_names = []
    
    for nome_arquivo, encoding_list in dados_rostos.items():
        
        nome_real = nome_arquivo.split('-')[0]
        
        known_names.append(nome_real)
        known_encodings.append(np.array(encoding_list))
        
    print(f"Total de {len(known_names)} assinaturas carregadas.")
    
    return known_encodings, known_names