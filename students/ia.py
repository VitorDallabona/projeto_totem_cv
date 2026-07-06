import logging
from collections import deque

import cv2 as cv
import numpy as np
from numpy.linalg import norm

from .encodes import carregar_rostos_conhecidos
from .liveness import AISpoofManager
from .models import Attendance, Classroom, Student

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Illumination normalisation
# ---------------------------------------------------------------------------

def normalizar_iluminacao(img_bgr: np.ndarray) -> np.ndarray:
    """
    Apply CLAHE in the L channel of LAB colour space.

    Why LAB + CLAHE?
    ----------------
    CLAHE (Contrast Limited Adaptive Histogram Equalisation) boosts local
    contrast without oversaturating bright regions (the "limited" part).
    Operating only on the L (lightness) channel leaves hue and saturation
    untouched, so skin tones and clothing colours — features ArcFace also
    encodes — are preserved.  The result is that an embedding extracted from
    a backlit corridor frame lands much closer to the controlled-light
    registration embedding in the 512-D sphere.

    clipLimit=2.0 / tileGridSize=(8,8) are the standard face-recognition
    defaults — aggressive enough to lift shadows, conservative enough to
    avoid introducing JPEG-block artefacts.
    """
    lab = cv.cvtColor(img_bgr, cv.COLOR_BGR2LAB)
    l, a, b = cv.split(lab)
    clahe = cv.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
    l = clahe.apply(l)
    lab = cv.merge((l, a, b))
    return cv.cvtColor(lab, cv.COLOR_LAB2BGR)


# ---------------------------------------------------------------------------
# Per-identity adaptive threshold
# ---------------------------------------------------------------------------

class AdaptiveThreshold:
    """
    Per-student cosine-similarity threshold that relaxes under poor lighting.

    Motivation
    ----------
    A global fixed threshold (e.g. 0.55) is a blunt instrument: it rejects
    valid frames captured in dim corridors where even a perfect match scores
    only 0.58–0.62.  At the same time, lowering it globally opens the door
    to false positives.

    This class tracks a short rolling window of the *best seen scores* for
    each identity and sets the effective threshold as:

        effective = BASE_THRESHOLD - (quality_headroom * RELAX_FACTOR)

    where quality_headroom = BASE_THRESHOLD - mean(recent_best_scores) when
    recent scores are below the base, i.e. lighting is difficult.

    The floor (MIN_THRESHOLD = 0.50) is chosen based on ArcFace benchmarks:
    different-person pairs on LFW rarely exceed 0.45, so 0.50 still provides
    a comfortable separation margin.

    Parameters
    ----------
    base : float   — starting / ideal-conditions threshold
    floor : float  — absolute minimum (security lower bound)
    relax : float  — how aggressively to adapt (0 = never adapt)
    maxlen : int   — rolling window of recent scores
    """

    BASE_THRESHOLD: float  = 0.55
    MIN_THRESHOLD: float   = 0.50
    RELAX_FACTOR: float    = 0.6
    WINDOW: int            = 8

    def __init__(self):
        self._scores: dict[str, deque] = {}

    def update(self, name: str, score: float):
        if name not in self._scores:
            self._scores[name] = deque(maxlen=self.WINDOW)
        self._scores[name].append(score)

    def threshold_for(self, name: str) -> float:
        if name not in self._scores or len(self._scores[name]) < 2:
            return self.BASE_THRESHOLD
        recent = np.mean(self._scores[name])
        if recent >= self.BASE_THRESHOLD:
            return self.BASE_THRESHOLD
        headroom = self.BASE_THRESHOLD - recent
        effective = self.BASE_THRESHOLD - headroom * self.RELAX_FACTOR
        return max(effective, self.MIN_THRESHOLD)

    def clear(self, name: str | None = None):
        if name:
            self._scores.pop(name, None)
        else:
            self._scores.clear()


# ---------------------------------------------------------------------------
# JSON serialization helper
# ---------------------------------------------------------------------------

def _convert_numpy(obj):
    """
    Recursively convert NumPy scalars/arrays to native Python types so that
    json.dumps never raises "Object of type int64 is not JSON serializable".
    """
    if isinstance(obj, dict):
        return {k: _convert_numpy(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_convert_numpy(v) for v in obj]
    if isinstance(obj, np.integer):
        return int(obj)
    if isinstance(obj, np.floating):
        return float(obj)
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if isinstance(obj, np.bool_):
        return bool(obj)
    return obj


# ---------------------------------------------------------------------------
# Embedding buffer — motion robustness core
# ---------------------------------------------------------------------------

class EmbeddingBuffer:
    """
    Keeps a short rolling window of ArcFace embeddings for a single tracked
    face and exposes a *weighted average* embedding for identification.

    Why a weighted average instead of a simple mean?
    ------------------------------------------------
    Frames captured during fast movement carry motion blur, which degrades the
    embedding quality.  InsightFace's detection score (det_score, 0–1) is a
    reliable proxy for image sharpness: a blurry frame gets a lower detection
    confidence.  By weighting each embedding by its det_score we naturally
    down-weight blurry frames and up-weight sharp ones, giving a more stable
    identity vector without any explicit blur detection step.

    If det_score is unavailable (older InsightFace versions), the buffer falls
    back to a uniform mean.

    Parameters
    ----------
    maxlen : int
        Rolling window size.  4–6 frames is the sweet spot:
        * Too small → doesn't smooth enough movement noise.
        * Too large → slow to react when a different person steps in front.
    min_frames : int
        Minimum frames required before the weighted average is trusted for
        identification.  Until then, the raw last embedding is used so there
        is no initial delay in recognition.
    """

    def __init__(self, maxlen: int = 5, min_frames: int = 2):
        self._embeddings: deque[np.ndarray] = deque(maxlen=maxlen)
        self._weights: deque[float] = deque(maxlen=maxlen)
        self.min_frames = min_frames

    def push(self, embedding: np.ndarray, det_score: float = 1.0):
        """Add a new embedding observation."""
        # Normalise each embedding as it enters so the weighted mean is also
        # unit-normalised (required for cosine similarity to be meaningful).
        n = norm(embedding)
        self._embeddings.append(embedding / n if n > 0 else embedding)
        self._weights.append(max(det_score, 1e-6))  # guard against zero weight

    def get_average(self) -> np.ndarray | None:
        """
        Return the weighted mean embedding, or None if the buffer is empty.
        Falls back to last embedding when below min_frames.
        """
        if not self._embeddings:
            return None
        if len(self._embeddings) < self.min_frames:
            return self._embeddings[-1]  # not enough history yet, use latest
        weights = np.array(self._weights, dtype=np.float32)
        weights /= weights.sum()
        avg = np.average(np.stack(self._embeddings), axis=0, weights=weights)
        n = norm(avg)
        return avg / n if n > 0 else avg  # keep unit norm

    def clear(self):
        self._embeddings.clear()
        self._weights.clear()

    @property
    def is_stable(self) -> bool:
        """True once the buffer has enough frames to be trustworthy."""
        return len(self._embeddings) >= self.min_frames


# ---------------------------------------------------------------------------
# Database helper
# ---------------------------------------------------------------------------

def salvar_registro_acesso(nome_aluno: str, direcao: str, liveness_score: float = 0.0) -> bool:
    """Persist an entry/exit attendance record. Returns True on success."""
    try:
        attendance_direction = "ENTRADA" if direcao == "DIREITA" else "SAÍDA"
        student = Student.objects.filter(user__username=nome_aluno).first()
        if not student:
            return False
        classroom = Classroom.objects.filter(active_now=True).first()
        if not classroom or student not in classroom.enrolled_students.all():
            return False
        Attendance.objects.create(
            student=student,
            classroom=classroom,
            liveness_score=liveness_score,
            is_valid=True,
            direction=attendance_direction,
        )
        logger.info("✓ [DB] %s — %s", student.user.get_full_name(), attendance_direction)
        return True
    except Exception:
        logger.exception("[ERRO] Falha ao salvar registro de acesso")
        return False


# ---------------------------------------------------------------------------
# Main recognition class
# ---------------------------------------------------------------------------

class FaceRecognition:
    """
    Biometric-first face recognition pipeline with motion robustness.

    Key design decisions
    --------------------
    Biometry is sovereign
        Identity is established on every frame via cosine similarity.  No
        position-based stickiness exists: a face whose score drops below
        SIMILARIDADE_MINIMA is immediately reclassified as Unknown.

    EmbeddingBuffer per tracked position
        Each detected bbox is matched to an ongoing EmbeddingBuffer by IoU.
        The buffer accumulates the last BUFFER_MAXLEN embeddings, weighted by
        InsightFace detection score (a proxy for image sharpness).  The
        weighted average embedding is what gets compared against the known face
        bank, making identification stable during fast movement.

    Buffer ↔ identity separation
        The buffer tracks *position* (bounding-box continuity via IoU), while
        identity is always recomputed from the averaged embedding.  This means
        a new person stepping into the same spatial slot gets a fresh
        identification — there is no identity inheritance from prior occupants.

    4-frame liveness gate
        After identification, a name only reaches "Aprovado" after
        AISpoofManager returns True on 4 consecutive frames.  Any failed
        frame resets the counter, preventing photo-flicker attacks.

    verified_cache
        Once liveness is confirmed, the name enters a set so the GPU-heavy
        anti-spoof model is skipped on subsequent frames.

    Instant cache eviction
        Names absent from the current frame have their liveness and position
        caches cleared immediately.

    NumPy-safe serialisation
        All outbound dicts go through _convert_numpy() before leaving this
        class.
    """

    SIMILARIDADE_MINIMA: float = 0.55
    LIVENESS_FRAMES_REQUIRED: int = 4

    # EmbeddingBuffer tunables
    BUFFER_MAXLEN: int = 7      # rolling window size (frames)
    BUFFER_MIN_FRAMES: int = 3  # frames before averaged embedding is trusted

    # IoU threshold to consider two bboxes the "same" face across frames
    IOU_THRESHOLD: float = 0.35

    # BGR colours
    _COR_APROVADO   = (0, 255, 0)
    _COR_AGUARDANDO = (0, 255, 255)
    _COR_FRAUDE     = (0, 0, 255)
    _COR_UNKNOWN    = (128, 128, 128)

    def __init__(self, face_dir: str, face_app):
        self.face_dir = face_dir
        self.face_app = face_app
        self.liveness = AISpoofManager(device_id=0)

        # position-keyed embedding buffers: list of (bbox, EmbeddingBuffer)
        # bbox stored as (left, top, right, bottom) plain Python ints
        self._buffers: list[tuple[tuple, EmbeddingBuffer]] = []

        # identity caches — keyed by username / matricula
        self.liveness_cache: dict[str, dict] = {}
        self.verified_cache: set[str] = set()
        self.posicoes_anteriores: dict[str, int] = {}

        self.teve_mudanca_banco: bool = False
        self.last_faces_data: list[dict] = []

        # Per-identity adaptive threshold
        self.adaptive_threshold = AdaptiveThreshold()

        # Load known embeddings
        self._reload_encodings()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def atualizar_banco_rostos(self):
        """Reload known embeddings from disk without restarting the server."""
        self._reload_encodings()
        self.liveness_cache.clear()
        self.verified_cache.clear()
        self.posicoes_anteriores.clear()
        self._buffers.clear()
        self.adaptive_threshold.clear()
        logger.info("[IA] Banco de rostos atualizado: %d identidades", len(self.knownFaceNames))

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reload_encodings(self):
        listas = carregar_rostos_conhecidos(self.face_dir, self.face_app)
        self.knownFaceEncodings = (
            np.array(listas[0], dtype=np.float32) if listas[0] else np.array([])
        )
        self.knownFaceNames: list[str] = listas[1]

    @staticmethod
    def _iou(a: tuple, b: tuple) -> float:
        """Intersection-over-Union for two (left, top, right, bottom) boxes."""
        ax1, ay1, ax2, ay2 = a
        bx1, by1, bx2, by2 = b
        ix1, iy1 = max(ax1, bx1), max(ay1, by1)
        ix2, iy2 = min(ax2, bx2), min(ay2, by2)
        inter = max(0, ix2 - ix1) * max(0, iy2 - iy1)
        if inter == 0:
            return 0.0
        area_a = (ax2 - ax1) * (ay2 - ay1)
        area_b = (bx2 - bx1) * (by2 - by1)
        return inter / (area_a + area_b - inter)

    def _get_or_create_buffer(self, bbox: tuple) -> EmbeddingBuffer:
        """
        Find the existing EmbeddingBuffer whose last bbox overlaps with the
        current bbox (IoU ≥ IOU_THRESHOLD), or create a new one.

        This gives each physical face its own rolling history regardless of
        small positional jitter, while correctly starting fresh when a new
        person steps into the frame.
        """
        best_iou, best_idx = 0.0, -1
        for i, (prev_bbox, _) in enumerate(self._buffers):
            iou = self._iou(prev_bbox, bbox)
            if iou > best_iou:
                best_iou, best_idx = iou, i

        if best_iou >= self.IOU_THRESHOLD:
            # Update stored bbox and return existing buffer
            buf = self._buffers[best_idx][1]
            self._buffers[best_idx] = (bbox, buf)
            return buf

        # New face slot
        buf = EmbeddingBuffer(maxlen=self.BUFFER_MAXLEN, min_frames=self.BUFFER_MIN_FRAMES)
        self._buffers.append((bbox, buf))
        return buf

    def _prune_buffers(self, active_bboxes: list[tuple]):
        """
        Remove buffers that no longer correspond to any detected face.
        Uses IoU: a buffer is kept only if at least one active bbox overlaps it.
        """
        kept = []
        for prev_bbox, buf in self._buffers:
            if any(self._iou(prev_bbox, ab) >= self.IOU_THRESHOLD for ab in active_bboxes):
                kept.append((prev_bbox, buf))
            else:
                buf.clear()  # GC help
        self._buffers = kept

    @staticmethod
    def cosine_similarity(a: np.ndarray, b: np.ndarray) -> float:
        denom = norm(a) * norm(b)
        return float(np.dot(a, b) / denom) if denom > 0 else 0.0

    @staticmethod
    def _bgr_to_hex(cor_bgr: tuple) -> str:
        b, g, r = cor_bgr
        return f"#{int(r):02X}{int(g):02X}{int(b):02X}"

    def _identificar(self, embedding: np.ndarray) -> tuple[str, float]:
        """
        Return (name, score).  Name is 'Unknown' when score < adaptive threshold.

        The best-candidate score is fed back into AdaptiveThreshold so the
        per-identity threshold tracks recent lighting conditions.
        """
        if len(self.knownFaceEncodings) == 0:
            return "Unknown", 0.0
        scores = np.array(
            [self.cosine_similarity(embedding, emb) for emb in self.knownFaceEncodings],
            dtype=np.float32,
        )
        idx = int(np.argmax(scores))
        score = float(scores[idx])
        candidate = self.knownFaceNames[idx]
        # Update rolling window even before accepting, so the threshold adapts
        self.adaptive_threshold.update(candidate, score)
        threshold = self.adaptive_threshold.threshold_for(candidate)
        return (candidate, score) if score >= threshold else ("Unknown", score)

    def _verificar_cruzamento(self, nome: str, centro_x: int, linha_x: int) -> str | None:
        movimento = None
        if nome in self.posicoes_anteriores:
            x_ant = self.posicoes_anteriores[nome]
            if x_ant < linha_x <= centro_x:
                movimento = "DIREITA"
            elif x_ant > linha_x >= centro_x:
                movimento = "ESQUERDA"
        self.posicoes_anteriores[nome] = centro_x
        return movimento

    def _evict_absent_names(self, names_visible: set[str]):
        absent = set(self.liveness_cache) - names_visible
        for name in absent:
            self.liveness_cache.pop(name, None)
            self.posicoes_anteriores.pop(name, None)
            # verified_cache is intentionally NOT cleared here — a confirmed
            # identity that briefly exits (head turn, blink) should not be
            # forced through 4-frame liveness again on return.

    # ------------------------------------------------------------------
    # Core processing
    # ------------------------------------------------------------------

    def run_recognition(self, frame: np.ndarray, frame_offset: tuple = (0, 0)) -> np.ndarray:
        h, w = frame.shape[:2]
        linha_x = w // 2

        # Normalise illumination before detection & embedding extraction.
        # The original frame is kept for drawing so the displayed image is
        # not over-processed visually.
        frame_norm = normalizar_iluminacao(frame)
        faces_raw = self.face_app.get(frame_norm)

        # ── Step 1: collect bboxes + push embeddings into buffers ──────────
        active_bboxes: list[tuple] = []
        detections: list[tuple[str, float, tuple, bool]] = []
        # detections → (name, score, bbox_tuple, buffer_is_stable)

        for face in faces_raw:
            raw_bbox = face.bbox.astype(int)
            bbox = (int(raw_bbox[0]), int(raw_bbox[1]), int(raw_bbox[2]), int(raw_bbox[3]))
            active_bboxes.append(bbox)

            det_score = float(getattr(face, "det_score", 1.0))
            buf = self._get_or_create_buffer(bbox)
            buf.push(face.embedding, det_score)

            avg_emb = buf.get_average()
            nome, score = self._identificar(avg_emb)
            detections.append((nome, score, bbox, buf.is_stable))

        # ── Step 2: remove stale buffers and absent identity caches ────────
        self._prune_buffers(active_bboxes)
        names_visible = {n for n, _, _, _ in detections if n != "Unknown"}
        self._evict_absent_names(names_visible)

        # ── Step 3: liveness gate + drawing ────────────────────────────────
        faces_data: list[dict] = []

        for nome, score, bbox, is_stable in detections:
            left, top, right, bottom = bbox
            centro_x = (left + right) // 2

            if nome == "Unknown":
                cor   = self._COR_UNKNOWN
                texto = f"Desconhecido ({score:.2f})"
            else:
                if nome in self.verified_cache:
                    cor   = self._COR_APROVADO
                    texto = "Aprovado"
                    movimento = self._verificar_cruzamento(nome, centro_x, linha_x)
                    if movimento:
                        if salvar_registro_acesso(nome, movimento, liveness_score=0.95):
                            self.teve_mudanca_banco = True
                else:
                    cache = self.liveness_cache.setdefault(nome, {"sucessos": 0})

                    # Only run liveness when the embedding buffer is stable;
                    # this avoids burning GPU cycles on blurry motion frames.
                    if is_stable:
                        esta_vivo, _conf = self.liveness.avaliar_frame(frame, np.array(bbox))
                        if esta_vivo:
                            cache["sucessos"] += 1
                            if cache["sucessos"] >= self.LIVENESS_FRAMES_REQUIRED:
                                self.verified_cache.add(nome)
                                cor   = self._COR_APROVADO
                                texto = "Aprovado"
                                movimento = self._verificar_cruzamento(nome, centro_x, linha_x)
                                if movimento:
                                    if salvar_registro_acesso(nome, movimento, liveness_score=0.95):
                                        self.teve_mudanca_banco = True
                            else:
                                cor   = self._COR_AGUARDANDO
                                texto = f"Confirme: {cache['sucessos']}/{self.LIVENESS_FRAMES_REQUIRED}"
                        else:
                            cache["sucessos"] = 0
                            cor   = self._COR_FRAUDE
                            texto = "Fraude!"
                    else:
                        # Buffer warming up — show name but hold liveness
                        cor   = self._COR_AGUARDANDO
                        texto = f"Identificando… ({score:.2f})"

            face_record = {
                "name":   nome,
                "status": texto,
                "score":  round(score, 4),
                "color":  self._bgr_to_hex(cor),
                "box":    {"top": top, "right": right, "bottom": bottom, "left": left},
            }
            faces_data.append(_convert_numpy(face_record))

            cv.rectangle(frame, (left, top), (right, bottom), cor, 2)
            cv.putText(
                frame, f"{nome} | {texto}",
                (left, top - 10),
                cv.FONT_HERSHEY_SIMPLEX, 0.6, cor, 2,
            )

        self.last_faces_data = faces_data
        return frame

    def run_recognition_get_data(
        self, frame: np.ndarray, frame_offset: tuple = (0, 0)
    ) -> tuple[list[dict], bool]:
        """
        Entry point for the WebRTC / REST pipeline.

        Returns
        -------
        faces_data   : list of dicts, fully JSON-serialisable
        teve_mudanca : True if at least one attendance record was written
        """
        self.teve_mudanca_banco = False
        self.run_recognition(frame, frame_offset=frame_offset)
        return self.last_faces_data, self.teve_mudanca_banco


# ---------------------------------------------------------------------------
# Module-level singleton (imported by views.py)
# ---------------------------------------------------------------------------

try:
    from insightface.app import FaceAnalysis

    face_app = FaceAnalysis(
        name="buffalo_l",
        providers=["CUDAExecutionProvider", "CPUExecutionProvider"],
    )
    face_app.prepare(ctx_id=0, det_size=(320, 320))
    ia_system = FaceRecognition("media/faces", face_app)
    logger.info("✓ Sistema de IA inicializado com sucesso.")
except Exception as exc:
    logger.error("❌ Falha ao inicializar IA: %s", exc)
    face_app = None   # type: ignore[assignment]
    ia_system = None  # type: ignore[assignment]