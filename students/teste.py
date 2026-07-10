import onnxruntime as ort
from insightface.app import FaceAnalysis

# 1. Cria o objeto (como você fez no primeiro comando)
face_app = FaceAnalysis(name="buffalo_s", providers=["CUDAExecutionProvider", "CPUExecutionProvider"])
face_app.prepare(ctx_id=0, det_size=(640, 640))

# 2. Verifica quais provedores o InsightFace realmente ativou para os modelos internos
print("\n--- RESULTADOS DO DIAGNÓSTICO ---")
print("Provedores ativos no InsightFace:", face_app.models['detection'].session.get_providers())

# 3. Verifica se o seu ambiente Python consegue enxergar a GPU
print("Provedores disponíveis no sistema:", ort.get_available_providers())
print("---------------------------------\n")



