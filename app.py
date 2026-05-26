import os
import json
import time
import base64
import requests
from google import genai
from flask import Flask, request, jsonify, render_template, redirect, url_for
from dotenv import load_dotenv

from figures import (
    extract_images_from_pdf,
    classify_figures,
    group_by_category,
    render_pages_as_images,
    detect_and_crop_circuits,
)
from circuit_fallback import generate_fallback_circuit
import cache

load_dotenv()

app = Flask(__name__)

# Gemini 클라이언트
gemini_client = genai.Client(api_key=os.environ.get("GEMINI_API_KEY"))
GEMINI_MODELS = ["models/gemini-2.5-flash", "models/gemini-2.0-flash-lite", "models/gemini-2.0-flash"]

# ─── 키워드 딕셔너리 (소자 + 행동 → 검색어) ────────────────────────────────
KEYWORD_MAP = {
    ("cardiac", "sensing"):       "OECT cardiac electrophysiology sensing PEDOT:PSS organic electrochemical transistor",
    ("cardiac", "monitoring"):    "OECT cardiac ECG electrocardiogram wearable monitoring implantable",
    ("cardiac", "stimulation"):   "OECT cardiac pacemaker electrical stimulation implantable bioelectronics",
    ("cardiac", "drug_delivery"): "OECT cardiac drug delivery electroactive controlled release",

    ("liver",   "sensing"):       "OECT liver hepatic biosensor electrochemical sensing biomarker",
    ("liver",   "monitoring"):    "OECT liver function monitoring biomarker electrochemical",
    ("liver",   "stimulation"):   "OECT liver hepatic electrical stimulation electrochemical",
    ("liver",   "drug_delivery"): "OECT liver hepatic drug delivery electrochemical release",

    ("skin",    "sensing"):       "OECT skin sweat biosensor wearable flexible stretchable",
    ("skin",    "monitoring"):    "OECT skin wearable health monitoring flexible electronics",
    ("skin",    "stimulation"):   "OECT skin electrostimulation transdermal iontophoresis",
    ("skin",    "drug_delivery"): "OECT skin transdermal drug delivery iontophoresis patch",

    ("eye",     "sensing"):       "OECT ocular eye electroretinogram retinal sensing implant",
    ("eye",     "monitoring"):    "OECT intraocular pressure glaucoma eye monitoring",
    ("eye",     "stimulation"):   "OECT retinal prosthesis stimulation visual implantable",
    ("eye",     "drug_delivery"): "OECT ocular drug delivery eye implant controlled release",

    ("brain",   "sensing"):       "OECT neural brain electrocorticography recording MEA implant",
    ("brain",   "monitoring"):    "OECT brain neural recording monitoring cortex PEDOT probe",
    ("brain",   "stimulation"):   "OECT neural brain deep stimulation implantable probe",
    ("brain",   "drug_delivery"): "OECT brain intrathecal drug delivery neural ionic",

    ("muscle",  "sensing"):       "OECT electromyography muscle EMG sensing flexible electrode",
    ("muscle",  "monitoring"):    "OECT muscle EMG wearable monitoring stretchable",
    ("muscle",  "stimulation"):   "OECT neuromuscular electrical stimulation prosthetic",
    ("muscle",  "drug_delivery"): "OECT muscle electrophoretic drug delivery ionic",
}

ORGAN_LABELS = {
    "cardiac": "심장 (Cardiac)",
    "liver":   "간 (Liver)",
    "skin":    "피부 (Skin)",
    "eye":     "눈 (Eye)",
    "brain":   "뇌 (Brain)",
    "muscle":  "근육 (Muscle)",
}

ORGAN_ICONS = {
    "cardiac": "❤️",
    "liver":   "🧪",
    "skin":    "🖐️",
    "eye":     "👁️",
    "brain":   "🧠",
    "muscle":  "💪",
}

ACTION_LABELS = {
    "sensing":       "센싱 (Sensing)",
    "monitoring":    "모니터링 (Monitoring)",
    "stimulation":   "치료/자극 (Stimulation)",
    "drug_delivery": "약물전달 (Drug Delivery)",
}

# ─── OpenAlex 논문 검색 ──────────────────────────────────────────────────────
OA_API_URL = "https://api.openalex.org/works"
OA_CONTACT = os.environ.get("OPENALEX_EMAIL", "oect-search@example.com")


def search_papers(organ: str, action: str, limit: int = 6) -> list:
    query = KEYWORD_MAP.get((organ, action), f"OECT {organ} {action}")
    params = {
        "search":   query,
        "per_page": limit + 4,
        "sort":     "cited_by_count:desc",
        "mailto":   OA_CONTACT,
    }

    try:
        resp = requests.get(OA_API_URL, params=params, timeout=20)
        if resp.status_code == 429:
            time.sleep(3)
            resp = requests.get(OA_API_URL, params=params, timeout=20)
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.Timeout:
        raise RuntimeError("OpenAlex API 응답 시간 초과. 잠시 후 다시 시도하세요.")
    except requests.exceptions.RequestException as e:
        raise RuntimeError(f"OpenAlex API 오류: {e}")

    papers = []
    for item in data.get("results", []):
        abstract = _rebuild_abstract(item.get("abstract_inverted_index"))
        if not abstract:
            continue

        authors = []
        for authorship in item.get("authorships", []):
            name = authorship.get("author", {}).get("display_name")
            if name:
                authors.append(name)

        pdf_url = None
        oa = item.get("open_access", {})
        if oa.get("is_oa"):
            pdf_url = oa.get("oa_url")
        best_loc = item.get("best_oa_location") or {}
        if best_loc.get("pdf_url"):
            pdf_url = best_loc["pdf_url"]

        papers.append({
            "paperId":       item.get("id", ""),
            "title":         item.get("title", "제목 없음"),
            "authors":       authors,
            "year":          item.get("publication_year"),
            "abstract":      abstract,
            "url":           item.get("doi", "") or item.get("id", ""),
            "citationCount": item.get("cited_by_count", 0),
            "pdfUrl":        pdf_url,
        })
        if len(papers) >= limit:
            break

    return papers


def _rebuild_abstract(inverted_index: dict | None) -> str:
    if not inverted_index:
        return ""
    word_positions = []
    for word, positions in inverted_index.items():
        for pos in positions:
            word_positions.append((pos, word))
    word_positions.sort()
    return " ".join(w for _, w in word_positions)


# ─── Gemini AI 분석 ──────────────────────────────────────────────────────────

MATERIALS_SCHEMA_DOC = """\
"materials" must be an OBJECT with EXACTLY these 8 keys, each value an array of strings:
  - "substrate":      device substrate / carrier (e.g. "PET", "PI (polyimide)", "glass", "PDMS", "paper")
  - "source":         source electrode material (e.g. "Au", "Pt", "evaporated Au")
  - "drain":          drain electrode material (e.g. "Au", "Pt"). Often same as source — repeat it.
  - "channel":        organic semiconductor / mixed conductor (e.g. "PEDOT:PSS", "p(g2T-TT)", "BBL")
  - "gate":           gate electrode material (e.g. "Ag/AgCl", "Pt wire", "PEDOT:PSS pellet")
  - "electrolyte":    electrolyte / ion source (e.g. "PBS", "1× PBS", "ionic liquid", "PVA hydrogel", "saliva")
  - "interconnect":   interconnect / wiring / contact pads (e.g. "Cr/Au", "Ag paste", "ITO trace")
  - "encapsulation":  passivation / encapsulation layer (e.g. "parylene-C", "SU-8", "PDMS encap", "photoresist")
For categories not mentioned in the source, use an empty array []. Do NOT use placeholder strings inside arrays.
A single material may appear in multiple categories if it serves multiple roles (e.g. PEDOT:PSS as both channel and gate).
"""

PDF_PROMPT = """\
You are a materials science and bioelectronics expert specializing in OECTs (Organic Electrochemical Transistors).

Analyze this OECT paper and return ONLY a valid JSON object with exactly these FIVE keys:

- "materials": OBJECT (see schema below)
- "device_structure": string — device layer composition, channel/gate geometry, electrodes, substrate (2-3 sentences in Korean)
  (e.g. "PET 기판 위 Au 소스/드레인 사이 PEDOT:PSS 채널(W/L=100/10μm), 상부 PBS 전해질과 Ag/AgCl 게이트 전극")
- "mechanism": string — sensing/operating principle: how the device detects/responds (2-3 sentences in Korean)
  (e.g. "코르티솔이 각인층에 결합하면 이온 이동이 차단되어 채널 탈도핑이 억제되고 I_DS가 감소")
- "process": array of strings — ALL fabrication steps in order, as detailed as possible (in Korean)
- "application": string — target analyte or application + key performance metrics (1-2 sentences in Korean)
  (e.g. "코르티솔 바이오센서, 검출한계 1 pM, 응답시간 5초")

""" + MATERIALS_SCHEMA_DOC + """
Since this is the full paper, extract maximum detail. Do not use "확인 불가" unless truly absent.

Respond with ONLY the JSON object, no markdown, no code blocks, no extra text."""

ABSTRACT_PROMPT = """\
You are a materials science and bioelectronics expert specializing in OECTs (Organic Electrochemical Transistors).

Analyze this OECT paper abstract and return ONLY a valid JSON object with exactly these FIVE keys:

- "materials": OBJECT (see schema below)
- "device_structure": string — device layer composition and geometry (1-2 sentences in Korean)
- "mechanism": string — sensing/operating principle (1-2 sentences in Korean)
- "process": array of strings — fabrication steps in order (in Korean)
- "application": string — target analyte/application + key performance (1 sentence in Korean)

""" + MATERIALS_SCHEMA_DOC + """
For non-materials fields that cannot be determined from the abstract:
  - "process": ["초록에서 확인 불가"]
  - string fields: "초록에서 확인 불가"

Respond with ONLY the JSON object, no markdown, no code blocks, no extra text.

Abstract:
{abstract}"""

# 5개 기본 필드 (분석 결과 호환성을 위해)
ANALYSIS_FIELDS = ["materials", "device_structure", "mechanism", "process", "application"]

# 재료 8카테고리 (순서 = UI 표시 순서)
MATERIAL_CATEGORIES = [
    "substrate", "source", "drain", "channel",
    "gate", "electrolyte", "interconnect", "encapsulation",
]


def _normalize_materials(value, fallback_text: str) -> dict:
    """재료 필드를 8카테고리 dict로 정규화.
    - dict 입력: 8키 보장 + 각 값 배열 보장
    - list 입력 (구 스키마 / 모델이 형식 어김): 전체를 _uncategorized 버킷에 보관
    - 그 외/누락: 빈 배열 8개 + _uncategorized=[fallback_text]
    """
    out = {k: [] for k in MATERIAL_CATEGORIES}
    if isinstance(value, dict):
        for k in MATERIAL_CATEGORIES:
            v = value.get(k)
            if isinstance(v, list):
                out[k] = [str(x) for x in v if x is not None and str(x).strip()]
            elif isinstance(v, str) and v.strip():
                out[k] = [v.strip()]
        # 모델이 8키 외 필드를 줬다면 _uncategorized로 백업 (정보 손실 방지)
        extras = []
        for k, v in value.items():
            if k in MATERIAL_CATEGORIES:
                continue
            if isinstance(v, list):
                extras.extend(str(x) for x in v if x and str(x).strip())
            elif isinstance(v, str) and v.strip():
                extras.append(v.strip())
        if extras:
            out["_uncategorized"] = extras
        return out
    if isinstance(value, list):
        items = [str(x) for x in value if x is not None and str(x).strip()]
        if items:
            out["_uncategorized"] = items
        return out
    if isinstance(value, str) and value.strip():
        out["_uncategorized"] = [value.strip()]
        return out
    out["_uncategorized"] = [fallback_text]
    return out


def _normalize_summary(parsed: dict, fallback_text: str) -> dict:
    """Gemini 응답을 5필드 스키마로 정규화. 구 스키마(circuit, materials=array)도 호환."""
    result = {}
    for key in ANALYSIS_FIELDS:
        if key == "materials":
            result[key] = _normalize_materials(parsed.get("materials"), fallback_text)
            continue
        if key in parsed:
            result[key] = parsed[key]
        elif key == "device_structure" and "circuit" in parsed:
            # 구 스키마 호환: circuit → device_structure
            result[key] = parsed["circuit"]
        elif key == "process":
            result[key] = [fallback_text]
        else:
            result[key] = fallback_text
    return result


def _parse_gemini_json(text: str) -> dict:
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        inner = lines[1:]
        if inner and inner[-1].strip() == "```":
            inner = inner[:-1]
        text = "\n".join(inner).strip()
    if text.endswith("```"):
        text = text[:-3].strip()
    return json.loads(text)


def _call_gemini(contents):
    """gemini-2.5-flash를 최대 4회 재시도 (503 과부하 대응, 간격 점점 늘림)."""
    model = GEMINI_MODELS[0]  # gemini-2.5-flash
    delays = [3, 6, 10, 15]   # 재시도 대기 시간 (초)

    for attempt in range(4):
        try:
            response = gemini_client.models.generate_content(
                model=model,
                contents=contents,
            )
            print(f"[Gemini] 성공: {model} (시도 {attempt + 1})")
            return response.text
        except Exception as e:
            err_str = str(e)
            print(f"[Gemini] {model} 시도 {attempt + 1} 실패: {err_str[:80]}")
            if "503" in err_str and attempt < 3:
                print(f"[Gemini] {delays[attempt]}초 후 재시도...")
                time.sleep(delays[attempt])
                continue
            if "429" in err_str:
                # rate limit: 다른 모델도 한 번씩만 시도
                for fallback in GEMINI_MODELS[1:]:
                    try:
                        response = gemini_client.models.generate_content(
                            model=fallback,
                            contents=contents,
                        )
                        print(f"[Gemini] fallback 성공: {fallback}")
                        return response.text
                    except Exception:
                        continue
            raise RuntimeError(f"Gemini API 오류: {err_str[:120]}")
    raise RuntimeError("Gemini 서버 과부하. 잠시 후 다시 시도하세요.")


def _analyze_pdf_bytes(pdf_bytes: bytes) -> dict:
    """PDF 바이트 → 캐시 조회 → 미스 시 Gemini 호출 → 저장 → 반환.

    호출자가 이미 PDF 바이트를 갖고 있을 때 사용 (URL 다운로드 / 업로드 모두).
    """
    sha = cache.pdf_sha(pdf_bytes)
    cached = cache.load(sha, "analyze")
    if cached:
        # 캐시 히트 — _meta 빼고 summary만 반환
        cached.pop("_meta", None)
        print(f"[cache:analyze] HIT {sha[:12]}")
        return cached

    print(f"[cache:analyze] MISS {sha[:12]} → Gemini 호출")
    try:
        pdf_b64 = base64.standard_b64encode(pdf_bytes).decode("utf-8")
        text = _call_gemini([
            {
                "parts": [
                    {"inline_data": {"mime_type": "application/pdf", "data": pdf_b64}},
                    {"text": PDF_PROMPT},
                ]
            }
        ])
        parsed = _parse_gemini_json(text)
        summary = _normalize_summary(parsed, "PDF에서 확인 불가")
    except json.JSONDecodeError:
        raise RuntimeError("Gemini 응답 파싱 오류 (JSON 형식 아님)")
    except Exception as e:
        raise RuntimeError(f"Gemini PDF 분석 오류: {e}")

    cache.save(sha, "analyze", summary)
    return summary


def analyze_with_pdf(pdf_url: str) -> dict:
    try:
        pdf_bytes = _download_pdf_bytes(pdf_url)
        print(f"[PDF] 다운로드 성공: {len(pdf_bytes)} bytes")
    except Exception as e:
        raise RuntimeError(f"PDF 다운로드 실패: {e}")
    return _analyze_pdf_bytes(pdf_bytes)


def analyze_with_abstract(abstract: str) -> dict:
    prompt = ABSTRACT_PROMPT.format(abstract=abstract[:3000])

    try:
        text = _call_gemini(prompt)
        parsed = _parse_gemini_json(text)
        return _normalize_summary(parsed, "초록에서 확인 불가")
    except json.JSONDecodeError:
        return _normalize_summary({}, "응답 파싱 오류")
    except Exception as e:
        summary = _normalize_summary({}, "API 오류")
        summary["mechanism"] = f"Gemini API 오류: {str(e)[:120]}"
        return summary


# ─── Flask 라우트 ─────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """MediaPipe 모션 인식 메인 페이지."""
    return render_template("index.html", organs=ORGAN_LABELS, organ_icons=ORGAN_ICONS)


@app.route("/organ/<organ>")
def organ_page(organ):
    """특정 organ의 논문 검색 페이지."""
    organ = organ.strip().lower()
    if organ not in ORGAN_LABELS:
        return redirect(url_for("index"))
    return render_template(
        "organ.html",
        organ=organ,
        organ_label=ORGAN_LABELS[organ],
        organ_icon=ORGAN_ICONS.get(organ, "🔬"),
        organs=ORGAN_LABELS,
        actions=ACTION_LABELS,
    )


def _do_search(organ: str, action: str) -> tuple:
    organ  = organ.strip().lower()
    action = action.strip().lower()

    if organ not in ORGAN_LABELS:
        return {"error": f"알 수 없는 소자: '{organ}'"}, 400
    if action not in ACTION_LABELS:
        return {"error": f"알 수 없는 행동: '{action}'"}, 400

    try:
        papers = search_papers(organ, action)
    except RuntimeError as e:
        return {"error": str(e)}, 502

    if not papers:
        return {"error": "관련 논문을 찾지 못했습니다. 다른 조합을 시도해 보세요."}, 404

    results = []
    for paper in papers:
        authors = paper["authors"]
        author_str = ", ".join(authors[:3])
        if len(authors) > 3:
            author_str += f" 외 {len(authors) - 3}명"

        results.append({
            "title":         paper["title"],
            "authors":       author_str,
            "year":          paper["year"],
            "citationCount": paper["citationCount"],
            "url":           paper["url"],
            "pdfUrl":        paper["pdfUrl"],
            "abstractShort": paper["abstract"][:400] + "…" if len(paper["abstract"]) > 400 else paper["abstract"],
            "fullAbstract":  paper["abstract"],
        })

    return {
        "organ":       organ,
        "action":      action,
        "organLabel":  ORGAN_LABELS[organ],
        "actionLabel": ACTION_LABELS[action],
        "keyword":     KEYWORD_MAP.get((organ, action), ""),
        "papers":      results,
    }, 200


@app.route("/api/search", methods=["POST"])
def api_search():
    data = request.get_json(force=True) or {}
    result, code = _do_search(data.get("organ", ""), data.get("action", ""))
    return jsonify(result), code


@app.route("/api/analyze", methods=["POST"])
def api_analyze():
    data     = request.get_json(force=True) or {}
    abstract = data.get("abstract", "")
    pdf_url  = data.get("pdfUrl") or data.get("pdf_url") or ""

    if not abstract and not pdf_url:
        return jsonify({"error": "abstract 또는 pdfUrl 중 하나는 필요합니다."}), 400

    pdf_failed_reason = ""
    if pdf_url:
        try:
            summary = analyze_with_pdf(pdf_url)
            return jsonify({"summary": summary, "source": "pdf"})
        except RuntimeError as e:
            pdf_failed_reason = str(e)
            print(f"[analyze] PDF 실패 ({e}), 초록으로 fallback")
            if not abstract:
                return jsonify({"error": str(e)}), 502

    summary = analyze_with_abstract(abstract)
    resp = {"summary": summary, "source": "abstract"}
    if pdf_failed_reason:
        resp["pdfFailed"] = pdf_failed_reason
    return jsonify(resp)


@app.route("/api/analyze-upload", methods=["POST"])
def api_analyze_upload():
    """사용자가 직접 업로드한 PDF를 Gemini로 분석 (캐시 자동 적용)."""
    if "pdf" not in request.files:
        return jsonify({"error": "PDF 파일이 없습니다."}), 400

    pdf_file = request.files["pdf"]
    pdf_bytes = pdf_file.read()

    if len(pdf_bytes) < 5000:
        return jsonify({"error": "파일이 너무 작습니다."}), 400
    if pdf_bytes[:4] != b"%PDF":
        return jsonify({"error": "PDF 형식이 아닙니다."}), 400

    try:
        summary = _analyze_pdf_bytes(pdf_bytes)
        return jsonify({"summary": summary, "source": "pdf"})
    except Exception as e:
        return jsonify({"error": f"PDF 분석 오류: {str(e)[:120]}"}), 502


# ─── 논문 이미지 추출 + 분류 ──────────────────────────────────────────────────

def _download_pdf_bytes(pdf_url: str) -> bytes:
    """공용 PDF 다운로더 + 검증."""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept": "application/pdf,*/*",
    }
    r = requests.get(pdf_url, headers=headers, timeout=30, allow_redirects=True)
    r.raise_for_status()
    pdf_bytes = r.content
    content_type = r.headers.get("Content-Type", "")
    if "text/html" in content_type or pdf_bytes[:5] in (b"<!DOC", b"<html"):
        raise ValueError("PDF 접근이 차단되었습니다 (출판사 제한)")
    if len(pdf_bytes) < 5000:
        raise ValueError("다운로드된 파일이 너무 작습니다")
    if pdf_bytes[:4] != b"%PDF":
        raise ValueError("PDF 형식이 아닙니다")
    return pdf_bytes


def _extract_pdf_text(pdf_bytes: bytes, max_chars: int = 6000) -> str:
    """PDF에서 텍스트만 추출 (3순위 폴백용)."""
    try:
        import fitz
        doc = fitz.open(stream=pdf_bytes, filetype="pdf")
        chunks = []
        for page in doc:
            chunks.append(page.get_text())
            if sum(len(c) for c in chunks) >= max_chars:
                break
        doc.close()
        return ("\n".join(chunks))[:max_chars]
    except Exception:
        return ""


def _process_pdf_figures(pdf_bytes: bytes, summary: dict | None = None) -> dict:
    """PDF bytes → figure 추출 → Gemini 분류 → 카테고리별 그룹핑.

    1순위: 임베디드 raster 이미지 추출 + 분류
    2순위: 회로 0개면 페이지 렌더 + Gemini ROI 검출 + 크롭 (vector 회로)
    3순위: 그래도 회로 0개면 텍스트(+summary+caption) → schemdraw 템플릿 자동 생성
    같은 PDF는 두 번째 호출부터 디스크 캐시에서 즉시 반환.
    """
    sha = cache.pdf_sha(pdf_bytes)
    cached = cache.load(sha, "figures")
    if cached:
        cached.pop("_meta", None)
        cached["cached"] = True
        print(f"[cache:figures] HIT {sha[:12]}")
        return cached
    print(f"[cache:figures] MISS {sha[:12]} → 추출 시작")

    figures = extract_images_from_pdf(pdf_bytes)

    if figures:
        figures = figures[:20]
        figures = classify_figures(figures, _call_gemini)

    has_circuit = any(f.get("category") == "circuit" for f in figures)
    fallback_used = False
    fallback_meta = None

    # 2순위: vector 폴백
    if not has_circuit:
        try:
            print("[figures] raster에서 회로 미발견 → 페이지 렌더 폴백 시도")
            pages = render_pages_as_images(pdf_bytes)
            pages = pages[:12]
            cropped = detect_and_crop_circuits(pages, _call_gemini)
            if cropped:
                print(f"[figures] vector 폴백 성공: {len(cropped)}개 회로 추출")
                figures.extend(cropped)
                has_circuit = True
                fallback_used = True
            else:
                print("[figures] vector 폴백에서도 회로 미발견")
        except Exception as e:
            print(f"[figures] vector 폴백 실패: {str(e)[:120]}")

    # 3순위: 텍스트 → schemdraw 자동 생성
    # 1·2순위 결과 유무와 무관하게 항상 실행 — 원본/AI 생성을 나란히 비교 표시
    try:
        print("[figures] AI 생성 회로 추가 시도 (논문 회로 유무와 무관하게)")
        text = _extract_pdf_text(pdf_bytes, max_chars=10000)
        captions = [f.get("caption", "") for f in figures if f.get("caption")]

        gen = generate_fallback_circuit(
            paper_text=text,
            gemini_call_fn=_call_gemini,
            summary=summary,
            figure_captions=captions,
        )
        if gen.get("success") and gen.get("image_b64"):
            conf = gen["confidence"]
            raw = gen.get("raw_confidence", conf)
            print(f"[figures] 텍스트→회로 생성 성공: topology={gen['topology']} "
                  f"raw={raw:.2f} boost→{conf:.2f} ({gen.get('boost_reason','')})")
            figures.append({
                "id": "gen_1",
                "page": 0,
                "width": 0,
                "height": 0,
                "image_b64": gen["image_b64"],
                "category": "circuit",
                "caption": (
                    f"텍스트 기반 자동 생성 회로 ({gen['topology']}, "
                    f"신뢰도 {conf:.2f})"
                ),
                "source": "text_generated",
            })
            # 1·2순위가 회로를 못 잡았을 때만 fallbackUsed=True (의미 보존)
            if not has_circuit:
                fallback_used = True
            fallback_meta = {
                "topology": gen["topology"],
                "confidence": conf,
                "rawConfidence": raw,
                "boostReason": gen.get("boost_reason", ""),
                "components": gen.get("components", []),
            }
        else:
            print(f"[figures] 텍스트→회로 생성 실패: {gen.get('error')}")
    except Exception as e:
        print(f"[figures] 3순위 폴백 실패: {str(e)[:120]}")

    if not figures:
        empty = {"figures": {}, "count": 0, "fallbackUsed": False}
        cache.save(sha, "figures", empty)
        return empty

    grouped = group_by_category(figures)
    result = {
        "figures": grouped,
        "count": len(figures),
        "fallbackUsed": fallback_used,
    }
    if fallback_meta:
        result["fallbackMeta"] = fallback_meta
    cache.save(sha, "figures", result)
    return result


def _summary_from_request(data: dict) -> dict | None:
    """request에서 summary 파싱 (옵셔널)."""
    s = data.get("summary")
    if isinstance(s, dict) and s:
        return s
    if isinstance(s, str) and s.strip():
        try:
            parsed = json.loads(s)
            if isinstance(parsed, dict):
                return parsed
        except json.JSONDecodeError:
            pass
    return None


@app.route("/api/extract-figures", methods=["POST"])
def api_extract_figures():
    """PDF URL에서 figure 추출 → 분류 → 카테고리별 반환."""
    data = request.get_json(force=True) or {}
    pdf_url = data.get("pdfUrl") or data.get("pdf_url") or ""
    if not pdf_url:
        return jsonify({"error": "pdfUrl이 필요합니다."}), 400

    try:
        pdf_bytes = _download_pdf_bytes(pdf_url)
    except Exception as e:
        return jsonify({"error": f"PDF 다운로드 실패: {e}", "pdfBlocked": True}), 502

    summary = _summary_from_request(data)
    try:
        result = _process_pdf_figures(pdf_bytes, summary=summary)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"이미지 처리 오류: {str(e)[:120]}"}), 500


@app.route("/api/extract-figures-upload", methods=["POST"])
def api_extract_figures_upload():
    """사용자 업로드 PDF에서 figure 추출."""
    if "pdf" not in request.files:
        return jsonify({"error": "PDF 파일이 없습니다."}), 400
    pdf_file = request.files["pdf"]
    pdf_bytes = pdf_file.read()

    if len(pdf_bytes) < 5000 or pdf_bytes[:4] != b"%PDF":
        return jsonify({"error": "유효한 PDF가 아닙니다."}), 400

    # form-data로 summary가 JSON string으로 올 수 있음
    summary = None
    raw_summary = request.form.get("summary")
    if raw_summary:
        try:
            parsed = json.loads(raw_summary)
            if isinstance(parsed, dict):
                summary = parsed
        except json.JSONDecodeError:
            pass

    try:
        result = _process_pdf_figures(pdf_bytes, summary=summary)
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": f"이미지 처리 오류: {str(e)[:120]}"}), 500


@app.route("/api/trigger", methods=["POST"])
def api_trigger():
    data = request.get_json(force=True) or {}
    result, code = _do_search(data.get("organ", ""), data.get("action", ""))
    return jsonify(result), code


if __name__ == "__main__":
    if not os.environ.get("GEMINI_API_KEY"):
        print("경고: GEMINI_API_KEY 환경변수가 설정되지 않았습니다. .env 파일을 확인하세요.")
    app.run(debug=False, host="0.0.0.0", port=5000)
