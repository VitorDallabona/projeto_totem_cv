import os
import cv2 as cv
import django

# 1. Inicializa o ambiente do Django para permitir que as tabelas funcionem neste script
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'totem_project.settings')
django.setup()

# 2. Importa a instância da IA que já está carregada no seu views.py
# (O script tenta puxar de 'students.views', se não achar, tenta de 'core.views')
try:
    from students.views import ia_system
    MODO_IA_DISPONIVEL = ia_system is not None
except Exception:
    try:
        from core.views import ia_system
        MODO_IA_DISPONIVEL = ia_system is not None
    except Exception:
        MODO_IA_DISPONIVEL = False

# URL do DroidCam para os seus testes em casa (mude para o RTSP do totem no laboratório)
URL_CAMERA_IP = "http://192.168.1.29:4747/video"

def iniciar_totem_core():
    cap = cv.VideoCapture(URL_CAMERA_IP)
    
    if not MODO_IA_DISPONIVEL:
        print("\n⚠️  MODO SIMULAÇÃO ATIVO: Executando apenas teste de vídeo local.")
        print("-> A IA real está desligada porque as bibliotecas pesadas não estão instaladas neste PC.")
    else:
        print("\n✅ MODO IA ATIVO: Sistema conectado com sucesso!")
        print("-> A IA processará os rostos e gravará no banco automaticamente ao cruzar a linha virtual.\n")

    while True:
        sucesso, frame = cap.read()
        if not sucesso:
            print("Aguardando transmissão da câmera por IP...")
            cv.waitKey(1000)
            continue

        # Inverte o frame horizontalmente para gerar o efeito de espelho natural no Totem
        frame = cv.flip(frame, 1)

        if MODO_IA_DISPONIVEL:
            # Como a sua IA já faz TUDO por dentro (detecta, rastreia e SALVA no banco),
            # basta passar o frame. A gravação no banco acontece por gravidade lá dentro!
            frame_processado = ia_system.run_recognition(frame)
        else:
            # Comportamento de simulação para os seus testes em casa
            frame_processado = frame.copy()
            altura_frame = frame_processado.shape[0]
            
            # Desenha a linha virtual vermelha idêntica à da IA para você visualizar em casa
            cv.line(frame_processado, (320, 0), (320, altura_frame), (0, 0, 255), 2)
            cv.putText(frame_processado, "SINAL CAMERA - SIMULACAO CASA", (20, 40), 
                       cv.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2)

        # Exibe a janela de monitoramento na tela do computador/servidor
        cv.imshow("Servidor Principal - Monitoramento", frame_processado)

        # Fecha o script imediatamente ao pressionar 'q' com a janela focada
        if cv.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    cv.destroyAllWindows()

if __name__ == "__main__":
    iniciar_totem_core()