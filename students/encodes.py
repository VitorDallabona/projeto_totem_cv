import face_recognition
import os
import json
import numpy as np

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
        
        # O nome do arquivo vira a chave do JSON (Ex: "Joao-lado")
        nome_arquivo = os.path.splitext(person)[0]
        
        if nome_arquivo in dados_rostos:
            continue
            
        print(f"Treinando novo rosto: {nome_arquivo} (Isso pode demorar um pouco...)")
        
        caminho_imagem = os.path.join(face_dir, person)
        face_image = face_recognition.load_image_file(caminho_imagem)
        
        # O parâmetro model="large" com num_jitters=100 (ou até 10) 
        # aumenta drasticamente a precisão da extração.
        # Como você tem GPU, pode usar 100 sem medo.
        encodings = face_recognition.face_encodings(
            face_image, 
            model="large", 
            num_jitters=100
        )
        
        if len(encodings) > 0:
            dados_rostos[nome_arquivo] = encodings[0].tolist()
            houve_atualizacao = True
        else:
            print(f"AVISO: Nenhum rosto achado na foto {person}!")

    if houve_atualizacao:
        with open(caminho_json, 'w') as arquivo:
            json.dump(dados_rostos, arquivo, indent=4)

    known_encodings = []
    known_names = []
    
    for nome_arquivo, encoding_list in dados_rostos.items():
        
        # --- A MÁGICA DOS MÚLTIPLOS ÂNGULOS ACONTECE AQUI ---
        # Pega "Joao-frente" e corta no traço, guardando apenas "Joao"
        # Se não tiver traço, ele guarda o nome original normal.
        nome_real = nome_arquivo.split('-')[0]
        
        known_names.append(nome_real)
        known_encodings.append(np.array(encoding_list))
        
    print(f"Total de {len(known_names)} assinaturas carregadas.")
    
    return known_encodings, known_names