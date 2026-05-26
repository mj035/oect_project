"""
PDF figure extraction + Gemini classification pipeline.

Flow:
  1. PyMuPDF로 PDF에서 모든 임베디드 이미지 + 위치 추출
  2. 크기/비율 필터로 아이콘/로고 제거
  3. Gemini에 썸네일 일괄 전송 → 카테고리별 분류 + 캡션
  4. 카테고리별 base64 이미지 + 캡션 반환

Categories:
  - circuit             : 회로 측정도 / 바이어스 setup
  - device_schematic    : 디바이스 구조도 / 단면도
  - performance_curve   : 전달특성 / 센싱 그래프
  - mechanism           : 동작 원리 도식
  - device_photo        : 실제 소자 사진 (optical/SEM)
  - other               : 그 외
"""

import io
import json
import base64
from typing import Iterable

import fitz  # PyMuPDF
from PIL import Image


FIGURE_CATEGORIES = [
    "circuit",
    "device_schematic",
    "performance_curve",
    "mechanism",
    "device_photo",
    "other",
]

# 아이콘/로고 필터 기준
MIN_IMAGE_WIDTH = 180
MIN_IMAGE_HEIGHT = 140
MAX_ASPECT_RATIO = 6.0   # 너무 길쭉한 배너 제외


def extract_images_from_pdf(pdf_bytes: bytes) -> list[dict]:
    """PDF bytes에서 모든 임베디드 이미지 추출. 필터링 후 반환.

    Returns:
        [{"id": "fig_1", "page": 2, "width": 800, "height": 600,
          "bytes": <raw PNG bytes>, "thumb_b64": "iVBOR..."}]
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    figures = []
    seen_hashes = set()  # 중복 제거

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        images = page.get_images(full=True)

        for img_info in images:
            xref = img_info[0]
            try:
                base = doc.extract_image(xref)
            except Exception:
                continue

            img_bytes = base.get("image")
            if not img_bytes:
                continue

            # 중복 제거
            h = hash(img_bytes)
            if h in seen_hashes:
                continue
            seen_hashes.add(h)

            # PIL로 크기/포맷 확인
            try:
                pil = Image.open(io.BytesIO(img_bytes))
                pil.load()
            except Exception:
                continue

            w, h_px = pil.size
            if w < MIN_IMAGE_WIDTH or h_px < MIN_IMAGE_HEIGHT:
                continue
            ratio = max(w / h_px, h_px / w)
            if ratio > MAX_ASPECT_RATIO:
                continue

            # 썸네일 (400px 이내, JPEG로 압축하여 토큰 절약)
            # CMYK/RGBA/P/LA/I/F 등 PNG에 직저장 불가능한 모드는 모두 RGB로 변환
            pil_rgb = pil if pil.mode in ("RGB", "L") else pil.convert("RGB")
            thumb = pil_rgb.copy()
            thumb.thumbnail((400, 400), Image.Resampling.LANCZOS)
            thumb_buf = io.BytesIO()
            thumb.save(thumb_buf, format="JPEG", quality=80)
            thumb_b64 = base64.standard_b64encode(thumb_buf.getvalue()).decode()

            # 원본 PNG 인코딩 (프론트에 전달용)
            full_buf = io.BytesIO()
            pil_rgb.save(full_buf, format="PNG", optimize=True)
            full_b64 = base64.standard_b64encode(full_buf.getvalue()).decode()

            figures.append({
                "id": f"fig_{len(figures) + 1}",
                "page": page_idx + 1,
                "width": w,
                "height": h_px,
                "thumb_b64": thumb_b64,
                "image_b64": full_b64,
            })

    doc.close()
    return figures


CLASSIFY_PROMPT = """\
You are an OECT/bioelectronics expert analyzing figures from a research paper.

For EACH image below, classify into ONE category and provide a brief Korean caption.

Categories:
- "circuit": circuit diagram, measurement setup, bias scheme (transistor symbols, voltage sources, ammeters)
- "device_schematic": device cross-section, layer stack, electrode layout, chip design
- "performance_curve": transfer curve (IDS-VGS), output curve, response vs concentration, time-series
- "mechanism": sensing mechanism diagram, working principle illustration (molecular binding, ion flow)
- "device_photo": actual device photo, optical micrograph, SEM/TEM image
- "other": anything else (graphs, chemical structures, flowcharts, tables)

Return ONLY a JSON array, one object per image in order:
[
  {"id": "fig_1", "category": "device_schematic", "caption": "PEDOT:PSS 채널 기반 OECT 단면도, Ag/AgCl 게이트"},
  {"id": "fig_2", "category": "performance_curve", "caption": "코르티솔 농도별 I_DS 응답 곡선"}
]

No markdown, no code fences, just the JSON array."""


def classify_figures(figures: list[dict], gemini_call_fn) -> list[dict]:
    """Gemini에 썸네일들을 한 번에 보내서 카테고리 + 캡션 받기.

    Args:
        figures: extract_images_from_pdf 결과
        gemini_call_fn: contents를 받는 호출 함수 (app._call_gemini)

    Returns:
        figures에 category, caption 필드 추가한 리스트
    """
    if not figures:
        return []

    parts = [{"text": CLASSIFY_PROMPT}]
    for fig in figures:
        parts.append({"text": f"\n--- {fig['id']} ---"})
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": fig["thumb_b64"],
            }
        })

    try:
        text = gemini_call_fn([{"parts": parts}])
    except Exception as e:
        # 분류 실패 시 모두 other로
        for fig in figures:
            fig["category"] = "other"
            fig["caption"] = f"분류 실패: {str(e)[:60]}"
        return figures

    # JSON 파싱
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()

    try:
        classifications = json.loads(text)
    except json.JSONDecodeError:
        for fig in figures:
            fig["category"] = "other"
            fig["caption"] = "분류 응답 파싱 실패"
        return figures

    by_id = {c.get("id"): c for c in classifications if isinstance(c, dict)}
    for fig in figures:
        c = by_id.get(fig["id"], {})
        cat = c.get("category", "other")
        if cat not in FIGURE_CATEGORIES:
            cat = "other"
        fig["category"] = cat
        fig["caption"] = c.get("caption", "")

    return figures


# ─── Vector 회로 폴백 (raster 추출이 0개일 때만) ─────────────────────────────

# 페이지 렌더 DPI: 너무 높으면 토큰 폭증, 너무 낮으면 회로 선이 뭉개짐
RENDER_DPI = 180
# 페이지에서 잘라낸 회로 ROI의 최소 크기 (이보다 작으면 노이즈로 간주)
MIN_ROI_WIDTH = 200
MIN_ROI_HEIGHT = 150


def render_pages_as_images(pdf_bytes: bytes, dpi: int = RENDER_DPI) -> list[dict]:
    """PDF의 각 페이지를 PNG 이미지로 렌더링.

    Vector graphic으로 그려진 회로도 이 단계에서 픽셀화되어 잡을 수 있음.

    Returns:
        [{"page": 1, "width": W, "height": H,
          "thumb_b64": "...", "image_b64": "..."}]
    """
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    pages = []
    zoom = dpi / 72.0  # PDF 기본 72dpi 기준
    matrix = fitz.Matrix(zoom, zoom)

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        try:
            pix = page.get_pixmap(matrix=matrix, alpha=False)
        except Exception:
            continue

        try:
            pil = Image.open(io.BytesIO(pix.tobytes("png")))
            pil.load()
        except Exception:
            continue

        w, h_px = pil.size

        # 썸네일 (분류용 — 페이지는 크니까 600px까지 허용)
        thumb = pil.copy()
        thumb.thumbnail((600, 600), Image.Resampling.LANCZOS)
        thumb_buf = io.BytesIO()
        thumb.save(thumb_buf, format="JPEG", quality=80)
        thumb_b64 = base64.standard_b64encode(thumb_buf.getvalue()).decode()

        # 풀 이미지 (크롭 소스로 메모리에 유지하기 위해 PNG bytes도 보관)
        full_buf = io.BytesIO()
        pil.save(full_buf, format="PNG", optimize=True)
        full_bytes = full_buf.getvalue()

        pages.append({
            "page": page_idx + 1,
            "width": w,
            "height": h_px,
            "thumb_b64": thumb_b64,
            "_full_bytes": full_bytes,  # 내부용 (크롭 후 제거)
            "image_b64": base64.standard_b64encode(full_bytes).decode(),
        })

    doc.close()
    return pages


CIRCUIT_ROI_PROMPT = """\
You are an OECT/bioelectronics expert. Each image below is a FULL PAGE rendered from a research paper PDF.

For each page, find ALL CIRCUIT diagrams (transistor symbols, voltage sources, ammeters, bias schemes, measurement setups) and return their bounding boxes in NORMALIZED coordinates [0..1] where (0,0)=top-left, (1,1)=bottom-right.

If a page has NO circuit diagram, return an empty boxes array for that page.
A "circuit" must contain explicit electrical schematic symbols — NOT chemical structures, NOT layer cross-sections, NOT graphs.

Return ONLY a JSON array, one object per page in order:
[
  {"page": 1, "boxes": []},
  {"page": 2, "boxes": [{"x0": 0.12, "y0": 0.55, "x1": 0.48, "y1": 0.82, "caption": "OECT 바이어스 회로"}]}
]

No markdown, no code fences, just the JSON array."""


def detect_and_crop_circuits(pages: list[dict], gemini_call_fn) -> list[dict]:
    """페이지 렌더 결과에서 회로 ROI를 찾아 크롭.

    Args:
        pages: render_pages_as_images 결과
        gemini_call_fn: app._call_gemini

    Returns:
        figures 형식의 리스트 (category="circuit" 고정)
    """
    if not pages:
        return []

    parts = [{"text": CIRCUIT_ROI_PROMPT}]
    for p in pages:
        parts.append({"text": f"\n--- page {p['page']} ---"})
        parts.append({
            "inline_data": {
                "mime_type": "image/jpeg",
                "data": p["thumb_b64"],
            }
        })

    try:
        text = gemini_call_fn([{"parts": parts}])
    except Exception:
        return []

    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()

    try:
        detections = json.loads(text)
    except json.JSONDecodeError:
        return []

    by_page = {d.get("page"): d for d in detections if isinstance(d, dict)}

    cropped = []
    for p in pages:
        det = by_page.get(p["page"], {})
        boxes = det.get("boxes", []) if isinstance(det, dict) else []
        if not boxes:
            continue

        try:
            full_pil = Image.open(io.BytesIO(p["_full_bytes"]))
            full_pil.load()
        except Exception:
            continue

        W, H = full_pil.size
        for box in boxes:
            try:
                x0 = max(0.0, float(box.get("x0", 0)))
                y0 = max(0.0, float(box.get("y0", 0)))
                x1 = min(1.0, float(box.get("x1", 1)))
                y1 = min(1.0, float(box.get("y1", 1)))
            except (TypeError, ValueError):
                continue
            if x1 <= x0 or y1 <= y0:
                continue

            # 약간 패딩 (선이 잘리지 않도록 +2%)
            pad = 0.02
            x0 = max(0.0, x0 - pad)
            y0 = max(0.0, y0 - pad)
            x1 = min(1.0, x1 + pad)
            y1 = min(1.0, y1 + pad)

            px0, py0 = int(x0 * W), int(y0 * H)
            px1, py1 = int(x1 * W), int(y1 * H)
            if px1 - px0 < MIN_ROI_WIDTH or py1 - py0 < MIN_ROI_HEIGHT:
                continue

            crop = full_pil.crop((px0, py0, px1, py1))
            crop_buf = io.BytesIO()
            crop.save(crop_buf, format="PNG", optimize=True)
            crop_b64 = base64.standard_b64encode(crop_buf.getvalue()).decode()

            cropped.append({
                "id": f"vec_{len(cropped) + 1}",
                "page": p["page"],
                "width": px1 - px0,
                "height": py1 - py0,
                "image_b64": crop_b64,
                "category": "circuit",
                "caption": (box.get("caption") or "논문 페이지에서 추출한 회로 (vector)").strip(),
                "source": "vector_fallback",
            })

    return cropped


def group_by_category(figures: list[dict]) -> dict[str, list[dict]]:
    """카테고리별로 figure 그룹핑. thumb_b64는 제거 (네트워크 절약)."""
    grouped = {cat: [] for cat in FIGURE_CATEGORIES}
    for fig in figures:
        cat = fig.get("category", "other")
        item = {
            "id": fig["id"],
            "page": fig["page"],
            "width": fig["width"],
            "height": fig["height"],
            "image_b64": fig["image_b64"],
            "caption": fig.get("caption", ""),
        }
        # 폴백 출처 표시 (프론트에서 뱃지로 사용 가능)
        if fig.get("source"):
            item["source"] = fig["source"]
        grouped[cat].append(item)
    return grouped
