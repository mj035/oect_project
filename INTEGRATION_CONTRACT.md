# 팀 통합 계약서 (Integration Contract)

## 📌 TL;DR

현재 프로젝트는 **논문 PDF에서 실제 figure를 추출해 카테고리별 분류**하는 방식으로 회로/구조 시각화를 해결합니다.
팀원의 schemdraw 기반 회로 생성기는 **폴백(fallback)** 으로 통합됩니다 — 논문 PDF에 회로 이미지가 없을 때만 발동.

---

## 🔀 역할 분담

| 모듈 | 담당 | 역할 | 상태 |
|---|---|---|---|
| `app.py` + `figures.py` | 메인 | PDF → PyMuPDF → Gemini 분류 → 카테고리별 figure 반환 | ✅ 구현 완료 |
| `circuit_fallback/` | 팀원 | 텍스트 → schemdraw → 생성 회로 PNG | 🔄 팀원 작업 중 |

---

## 📞 통합 API 계약

팀원은 아래 **함수 시그니처** 만 준수하면 됩니다. 나머지 모든 구현은 자율.

### 팀원 모듈이 노출해야 하는 함수

**파일 위치**: `circuit_fallback/generator.py`

```python
def generate_fallback_circuit(
    paper_text: str,
    out_dir: str = "./out"
) -> dict:
    """
    논문 텍스트 → schemdraw 회로도 PNG 생성.

    Args:
        paper_text: 논문 초록 or 본문 텍스트 (pypdf 추출 결과)
        out_dir: PNG 저장 디렉토리

    Returns:
        {
          "success": bool,
          "image_path": str | None,   # out_dir 기준 상대/절대 경로
          "image_b64": str | None,    # PNG base64 (없으면 None, 있으면 이것만 써도 됨)
          "topology": str,            # "common_source" | "transimpedance" | "unknown"
          "confidence": float,        # 0.0~1.0
          "components": list,         # [{"type": "OECT", "label": "T1"}, ...]
          "error": str | None         # 실패 시 에러 메시지
        }

    실패 시: {"success": False, "error": "...", ...나머지 None}
    """
```

### 호출 시점 (메인 쪽 로직)

```python
# app.py (의사코드)
def render_circuit_section(pdf_bytes, paper_text):
    figures = extract_figures_from_pdf(pdf_bytes)
    circuit_imgs = figures.get("circuit", [])

    if circuit_imgs:
        # 1차: 실제 논문 이미지 사용
        return {"source": "paper_figure", "images": circuit_imgs}

    # 2차: 팀원 fallback 호출
    from circuit_fallback.generator import generate_fallback_circuit
    fb = generate_fallback_circuit(paper_text)
    if fb["success"]:
        return {"source": "generated", "image_b64": fb["image_b64"],
                "topology": fb["topology"]}

    return {"source": "none", "message": "회로 정보 없음"}
```

---

## 🚫 반드시 지켜야 할 것

### 1. API 통일 — Gemini 사용
- ❌ Anthropic Claude 사용 금지 (이 프로젝트는 Gemini API만 씀)
- ✅ 기존 `.env`의 `GEMINI_API_KEY` 재사용
- ✅ `from google import genai` 로 호출 통일
- Claude 고집하면 키 관리/과금이 이원화되고 팀 배포 복잡도 증가

### 2. Topology는 2개만 — 무리하지 말자
- ✅ `common_source` (센서 front-end, Vgs/Vds/R_load)
- ✅ `transimpedance` (Opamp + R_f)
- ❌ 나머지 (common_gate, differential_pair, inverter, voltage_divider 등) → 모두 `"topology": "unknown"` 반환하고 이미지 생성 스킵

이유: 논문별 토폴로지 편차가 커서 억지로 구현하면 "컴포넌트 나열" 같은 반쪽짜리 결과가 나옴. **2개를 확실히** > 8개를 엉성하게.

### 3. 모델 비용
- ❌ Claude Opus 4-5/4-7 사용 금지 (오버킬 + 비쌈)
- ✅ **Gemini 2.5 Flash** 사용 (메인 프로젝트와 동일)

### 4. 출력 JSON 스키마 엄수
응답 필드는 위 시그니처의 정확히 그대로. 필드 추가/삭제/이름 변경 금지.

---

## 💎 보존 (팀원의 자산)

팀원의 다음 작업물은 **그대로 유지**:

1. **`oect_symbol.py`** — OECT 전용 schemdraw 커스텀 심볼
   - 채널 + 전해질 물결 + Ag/AgCl 게이트
   - 앵커 (drain, source, gate, electrolyte)
   - **이게 폴백 결과물의 핵심 품질 포인트**
   - 발표 때 "OECT 전용 심볼 자체 설계" 어필 가능

2. **`test_symbol.py`** — 심볼 단독 프리뷰
   - 통합과 무관하게 유지 (검증용)

3. **pydantic 스키마** — 내부 구현 자유, 다만 최종 반환은 위 시그니처 따라야 함

---

## 🔌 통합 절차

### 팀원 쪽 체크리스트
- [ ] Anthropic → Gemini API 변경 (`google-genai` 라이브러리)
- [ ] Topology 2개로 축소 (나머지는 `"unknown"` 반환)
- [ ] `generate_fallback_circuit()` 함수 export
- [ ] 반환 dict 스키마 일치 확인
- [ ] `out_dir` 경로 인자화 (하드코딩 금지)

### 메인 쪽 체크리스트
- [ ] `circuit_fallback/` 디렉토리 import 경로 설정
- [ ] 폴백 호출 로직 `app.py`에 추가
- [ ] "회로" 탭에 `source` 뱃지 표시 ("논문 원본" vs "자동 생성")
- [ ] 통합 테스트: 회로 이미지 있는 논문 + 없는 논문 각 1편

---

## 🎯 최종 UI (회로 탭 기준)

```
Case A: PDF에서 회로 이미지 발견
┌────────────────────────────────┐
│ [논문 원본] 뱃지                  │
│ ┌──────┬──────┬──────┐           │
│ │ Fig3a│Fig 4 │ ...  │  ← 실제 논문 이미지
│ └──────┴──────┴──────┘           │
│ 캡션: "common-source 측정 setup"  │
└────────────────────────────────┘

Case B: PDF에 회로 이미지 없음 (팀원 폴백 발동)
┌────────────────────────────────┐
│ [자동 생성] 뱃지                  │
│ ┌────────────────────┐           │
│ │  [schemdraw 회로]  │  ← 팀원 생성물
│ │  OECT + R_load     │           │
│ └────────────────────┘           │
│ topology: common_source          │
│ confidence: 0.78                 │
└────────────────────────────────┘

Case C: 둘 다 실패
┌────────────────────────────────┐
│ 회로 정보를 추출하지 못했습니다     │
└────────────────────────────────┘
```

---

## ❓ FAQ

**Q. 회로 이미지가 멀티패널(Figure 1a/1b/1c 합쳐진)이면?**
A. 전체 figure를 그대로 보여주고 Gemini 캡션에 "(a)가 회로도" 같은 정보 포함. 자동 크롭은 안 함.

**Q. 폴백이 완전히 실패하면?**
A. "회로 정보 없음" 메시지만 표시. 에러 아님, 정상 케이스로 취급.

**Q. Claude Opus가 더 정확할 것 같은데?**
A. 실험해본 결과 이 작업(텍스트에서 topology 분류 + 컴포넌트 리스트)은 Gemini 2.5 Flash로 충분. Opus는 10배 비용으로 5% 개선. 비용 대비 효율 나쁨.

**Q. 팀원 원본 프로젝트(oect-circuit/)를 그대로 별도로 유지하면 안 되나?**
A. OK. `oect-circuit/` 디렉토리를 독립 저장소로 두고, `circuit_fallback/`은 얇은 래퍼로 만들어도 됨. 단 import 경로와 API 시그니처만 맞출 것.

---

## 📅 타임라인 제안

| 일자 | 작업 |
|---|---|
| D+0 | 팀원과 이 문서 리뷰, 계약 확정 |
| D+1~2 | 팀원: Gemini 전환 + topology 2개 집중 구현 |
| D+2 | 메인: 폴백 호출 로직 추가 |
| D+3 | 통합 테스트 (논문 3~5편) |
| D+4 | 발표 데모 리허설 |

---

작성: 메인 모듈 (app.py) 담당자
최종 확인: 2026-04-20
