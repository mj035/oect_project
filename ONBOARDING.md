# OECT 논문 검색 & AI 분석 시스템 — 발표자료용 온보딩

> 이 문서는 **최종 발표자료를 만드는 팀원**이 프로젝트 전체 구조와 차별점을 빠르게 파악하도록 정리한 가이드입니다. Claude Code에서 이 문서를 열면 프로젝트 맥락을 그대로 받아서 슬라이드/스크립트 작성을 도와드릴 수 있어요.

---

## 한 줄 요약

> **MediaPipe 모션 인식으로 신체 부위를 선택하면 OECT 논문을 검색하고, 선택한 논문 PDF를 Gemini로 분석해 재료·구조·메커니즘·공정·응용·회로 6가지 항목으로 자동 정리해주는 웹 시스템.**

- **목적**: 학부 수업 발표 (학생 투표로 평가) — AI 툴 활용 프로젝트
- **차별점**: 단순 "검색 + 요약"이 아니라 **모션 인식 + 실제 논문 figure 추출 + 3계층 회로 폴백**으로 차별화
- **권장 발표 리프레이밍**: "OECT 논문 검색" → "**AI 연구 도우미 (OECT 예시)**"

---

## 프로젝트 위치

- 코드: `C:\Users\dhals\oect-paper-search\`
- 발표 PPTX (중간): `oect-paper-search\oect_midterm.pptx` (15장 / 10분)
- PPTX 빌더: `_build_pptx.py` (python-pptx) — 수정 후 `python _build_pptx.py` 재실행

---

## 사용자 흐름 (데모 시연 시나리오)

```
[1] 메인 페이지 (index.html)
    ├── 카메라 ON → MediaPipe Holistic이 손/얼굴 추적
    ├── 손→머리 = 뇌 / 손→가슴 = 심장 / 손→배 = 간
    ├── V사인+얼굴옆 = 눈 / 양손주먹 = 근육 / 양손손바닥 = 피부
    └── 1.5초 유지 → 자동 이동

[2] 장기 페이지 (organ.html)
    ├── 행동 선택: sensing / monitoring / stimulation / drug_delivery
    ├── [논문 검색] → OpenAlex API (무료) → 카드 목록
    └── [AI PDF 분석] 클릭
         │
         ├── PDF 다운로드 (출판사 차단 시 업로드 폴백 노출)
         ├── Gemini 2.5 Flash → 6필드 분석
         ├── PyMuPDF로 figure 추출 → Gemini가 카테고리 분류
         └── 결과: 재료(8카테고리) / 디바이스 구조 / 메커니즘 /
                  공정 / 응용 / 회로(3계층 폴백)
```

---

## 차별 포인트 (발표에서 어필할 것)

### ① 모션 인식 UX
- MediaPipe Holistic을 CDN으로 띄워 카메라 없이는 못 보는 인터랙션
- 학생 청중에게 "직접 해봐" 시연 가능 → 임팩트 ↑

### ② 6필드 분석 스키마 (★ 핵심 설계)
```
1. materials          — 8카테고리 dict (substrate/source/drain/channel/
                        gate/electrolyte/interconnect/encapsulation)
2. device_structure   — 레이어 구성·지오메트리
3. mechanism          — 센싱/동작 메커니즘
4. process            — 제작 단계 array
5. application        — 타겟 + 성능 지표
6. circuit            — 텍스트 분석 X, 실제 논문 figure에서만 추출
```
- **재료를 8카테고리로 분할한 이유**: 단일 chip 묶음은 OECT 디바이스 구조가 한눈에 안 들어옴. "기판/채널/게이트/전해질" 비교가 발표 핵심
- **circuit을 텍스트에서 뺀 이유**: 기존엔 "회로" 텍스트 항목이 자꾸 "동작 원리"나 "초록에서 확인 불가"로 채워지는 정체성 혼란 발생 → figure 추출 전용으로 분리

### ③ 3계층 회로 폴백 (★ 가장 차별화되는 부분)

```
┌────────────────────────────────────────────────────┐
│ 1순위: PyMuPDF 임베디드 raster → Gemini 분류        │
│        (figures.py — 기존 메인 경로)                 │
├────────────────────────────────────────────────────┤
│ 2순위: 페이지 PNG 렌더 → Gemini ROI 검출 → PIL crop │
│        (vector graphic 회로 대응)                    │
├────────────────────────────────────────────────────┤
│ 3순위: PDF 텍스트 + summary + figure 캡션 →         │
│        Gemini 토폴로지 분류 → schemdraw 템플릿 생성  │
│        (circuit_fallback/ — 자체 구현)              │
└────────────────────────────────────────────────────┘
```

- 각 회로에 `source` 메타: `"raster"` / `"vector_fallback"` / `"text_generated"`
- 프론트는 **출처 뱃지 + 신뢰도 게이지**로 구분 표시
- **always-on 모드 (2026-05-05~)**: 회로 raster 유무와 무관하게 3순위도 항상 발동 → 발표 임팩트용 "같은 회로 두 가지 방식 비교 표시"

### ④ schemdraw를 "LLM이 코드 짜는 방식"으로 안 쓴 이유
- LLM이 schemdraw 코드 직접 작성 → 품질 불안정 (실험으로 확인)
- 대신 **LLM은 분류기로만** 사용 + 미리 만든 템플릿 4종이 그림:
  - `common_source` / `transimpedance` / `voltage_divider` / `generic_3_terminal`
- `generic_3_terminal`이 안전망 → **빈 회로 탭이 절대 안 나옴**

### ⑤ 3순위 신뢰도 향상 (도메인 룰 후처리)
- raw confidence 0%였던 "회로 없는 논문"을 final 1.0까지 끌어올림
- 후처리 룰:
  - PEDOT:PSS / Ag / AgCl 매칭 시 +0.10씩
  - V_DS / V_GS 수치 발견 시 +0.05씩
  - 토폴로지 키워드 발견 시 +0.10
- summary(분석된 6필드) + figure 캡션을 폴백 입력으로 같이 주입

### ⑥ 분석 결과 캐싱 (시연 안정성)
- SHA-256(PDF bytes) 기반 디스크 캐싱 (`cache/{sha}.{kind}.json`)
- 같은 PDF 두 번째부터 **~50ms 즉시 응답** (Gemini 호출 0회)
- 응답에 `cached: true` 플래그
- **발표 시연 안정성 확보**: 시연용 5~10편 사전 분석 → quota 사고 0%

---

## 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│  Browser                                                 │
│  ├── MediaPipe Holistic (CDN)                            │
│  └── organ.html (검색·분석 UI, 6필드 탭)                  │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
┌─────────────────────────────────────────────────────────┐
│  Flask (app.py)                                          │
│  ├── /api/search        → OpenAlex (무료, 논문 검색)     │
│  ├── /api/analyze       → Gemini (6필드 분석)            │
│  ├── /api/extract-figures → PyMuPDF + Gemini (figure 분류)│
│  ├── /api/analyze-upload, /api/extract-figures-upload     │
│  │       (출판사 PDF 차단 폴백)                            │
│  └── /api/trigger       → 모션팀 연동                     │
├─────────────────────────────────────────────────────────┤
│  cache.py  ← SHA-256 디스크 캐시                          │
│  figures.py ← 1·2순위 (raster / vector ROI)              │
│  circuit_fallback/                                       │
│    ├── generator.py    (3순위 메인 — Gemini 분류 + 룰)   │
│    ├── templates.py    (토폴로지 4종 렌더러)             │
│    └── oect_symbols.py (OECT 커스텀 schemdraw 심볼)      │
└──────────────┬──────────────────────────────────────────┘
               │
               ▼
        ┌──────────────┐    ┌──────────────┐
        │ Gemini 2.5   │    │ OpenAlex API │
        │ Flash        │    │ (무료)        │
        │ (+ fallback: │    └──────────────┘
        │   2.0-flash) │
        └──────────────┘
```

---

## 기술 스택

| 구분 | 기술 | 비고 |
|------|------|------|
| Backend | Flask (Python) | `app.py` 단일 파일 ~29KB |
| LLM | Google Gemini 2.5 Flash | 무료 티어, fallback: 2.0-flash-lite/2.0-flash |
| 논문 검색 | OpenAlex API | 무료, 키 불필요 |
| PDF 처리 | PyMuPDF + Pillow | raster 임베디드 + 페이지 렌더 |
| 회로 폴백 | schemdraw + matplotlib | 자체 OECT 심볼 구현 |
| Frontend | Vanilla HTML/CSS/JS | 다크 테마, 16:9 |
| 모션 인식 | MediaPipe Holistic (CDN) | 손/얼굴/포즈 통합 |

---

## 파일 구조

```
oect-paper-search/
├── app.py                  ← Flask 서버 + 모든 API + 6필드 분석 로직
├── cache.py                ← SHA-256 PDF 캐싱
├── figures.py              ← 1·2순위 회로 추출 (raster + vector ROI)
├── circuit_fallback/       ← 3순위 회로 생성기 (자체 구현)
│   ├── generator.py        ← Gemini 분류 + 도메인 룰 + 템플릿 호출
│   ├── templates.py        ← 토폴로지 4종 렌더러
│   ├── oect_symbols.py     ← OECT 커스텀 schemdraw 심볼
│   └── __init__.py
├── templates/
│   ├── index.html          ← MediaPipe 모션 인식 메인
│   └── organ.html          ← 논문 검색 + 6필드 분석 UI (~32KB)
├── static/                 ← css / js / img
├── cache/                  ← PDF 분석 결과 디스크 캐시 (.gitignored)
├── INTEGRATION_CONTRACT.md ← 팀원 schemdraw 모듈 통합 계약서
├── README.md               ← 실행/사용법
├── requirements.txt
├── oect_midterm.pptx       ← 중간 발표 PPT (15장, 10분)
├── _build_pptx.py          ← python-pptx 기반 PPT 빌더
└── .env                    ← GEMINI_API_KEY (gitignored)
```

---

## 발표 시연 시 주의사항 (★ 중요)

### Gemini quota 운영
- 무료 티어: **분당 10회 / 일일 250회 / 분당 토큰 250k**
- 논문 1편 분석 = Gemini 호출 5~6회 (analyze + figure 분류 + AI 회로 + vector ROI)
- 일일 ~50편이면 한도 도달
- **quota는 계정 단위 공유** — 같은 Google 계정에서 새 키 만들어도 풀 동일
- **발표 임박 시 결제 활성화(pay-as-you-go) 강력 권장** — 논문당 ~10원, 100원 미만으로 발표 사고 0%

### 시연 안정성 확보 절차
1. 발표 직전 시연용 논문 5~10편을 사전 분석 → 캐시 채워두기
2. 캐시된 논문은 50ms 응답 (네트워크/quota 무관)
3. 백업 영상도 준비 (인터넷·카메라 실패 대비)

### PDF 차단 대응
- Wiley 등 출판사가 403 차단 → 프론트에 `pdfFailed` 표시
- "PDF 업로드 분석" 버튼이 자동으로 노출 → 사용자가 PDF 직접 업로드해 분석

---

## 알려진 이슈 (발표에서 굳이 말 안 해도 됨)

- `voltage_divider` 템플릿은 단순화 버전 (드레인 라인에 R_load 직렬). 더 정밀한 분배 회로 미구현
- OECT 심볼의 PBS/Ag/AgCl 라벨이 게이트 막대에 살짝 겹침 (보기엔 큰 문제 X)

---

## 팀원 schemdraw 모듈 통합 방침 (참고)

- 메인 파이프라인은 **이미지 추출 방식 유지** — 팀원 모듈은 **3순위 폴백**으로만 통합
- `circuit_fallback/generator.py`의 `generate_fallback_circuit(paper_text, out_dir) -> dict` 시그니처 합의
- Topology 2개로 축소 (`common_source`, `transimpedance`), 나머지 `"unknown"`
- API는 Gemini로 통일 (Claude 금지 — 키/과금 이원화 방지)
- 팀원의 OECT 커스텀 schemdraw 심볼은 **자산으로 보존** → 발표 때 "OECT 전용 심볼 자체 설계" 어필 포인트

---

## 발표 슬라이드 구성 추천 (10분 기준 15장)

| # | 슬라이드 | 핵심 메시지 |
|---|---|---|
| 1 | 표지 | "AI 연구 도우미 (OECT 예시)" |
| 2 | 문제 정의 | OECT 논문 읽기의 어려움 (재료/구조 산재) |
| 3 | 솔루션 한 줄 | 모션→검색→6필드 자동 분석 |
| 4 | 시스템 데모 (캡처 1) | 메인 화면 모션 인식 |
| 5 | 시스템 데모 (캡처 2) | 6필드 탭 결과 |
| 6 | 차별화 ① 6필드 스키마 | 왜 6개로 나눴나, 8카테고리 재료 |
| 7 | 차별화 ② 3계층 회로 폴백 | raster → vector ROI → text-generated |
| 8 | 차별화 ③ LLM은 분류기로만 | schemdraw 템플릿 4종 + 도메인 룰 |
| 9 | 차별화 ④ 신뢰도 향상 | 0% → 100% 끌어올린 도메인 룰 |
| 10 | 차별화 ⑤ 시연 안정성 | SHA-256 캐싱, quota 대응 |
| 11 | 아키텍처 | Flask + Gemini + OpenAlex + MediaPipe |
| 12 | 라이브 데모 | 실제 시연 (캐시된 논문) |
| 13 | 한계 및 향후 | 회로 토폴로지 확장, 통합 분석 엔드포인트 |
| 14 | 기여도 | 팀원별 담당 (메인 / schemdraw 심볼) |
| 15 | Q&A | — |

---

## 발표자료 만들 때 Claude Code 활용 팁

이 ONBOARDING.md를 Claude Code에서 연 상태로:
- "이 시스템 차별점을 3분 발표 스크립트로 만들어줘" → 위 ⑥ 항목들 활용해 작성 가능
- "회로 폴백 3계층을 그림으로 그릴 텍스트 다이어그램 만들어줘" → 위 아키텍처 섹션 응용
- "예상 Q&A 10개 만들어줘" → 알려진 이슈 + 기술 결정 사항 기반
- "발표 슬라이드 텍스트만 뽑아줘" → 위 15장 구성에서 각 장 본문 자동 생성

코드 직접 보고 싶으면:
- `app.py`의 `MATERIAL_CATEGORIES` 상수와 `_normalize_materials()` (8카테고리 핵심)
- `circuit_fallback/generator.py` (3순위 폴백 + 도메인 룰)
- `figures.py` (1·2순위 회로 추출)
- `templates/organ.html`의 `renderMaterialsBlock()` 함수 (UI 표시 로직)

---

## 🛠 팀원 환경 셋업 (localhost 시연용)

> 이 ONBOARDING은 **프로젝트 맥락만** 담고 있어요. 실제 코드와 API 키는 별도로 전달받아야 합니다.

### Step 0. 전달받아야 할 것

| 항목 | 어디서 | 비고 |
|---|---|---|
| 코드 전체 (`oect-paper-search/` 폴더) | 프로젝트 담당자 (GitHub repo / ZIP / USB) | `.env`는 **빠져있음** (정상) |
| (선택) `cache/` 폴더 | 프로젝트 담당자 | 시연용 사전 분석 결과. 있으면 시연 즉시 응답 |
| Gemini API 키 | **본인이 직접 발급** ← API 키는 절대 공유받지 말 것 | 무료, 30초 |

### Step 1. Python 환경

- Python 3.10+ 권장
- 가상환경 사용 권장 (선택):
  ```powershell
  python -m venv venv
  .\venv\Scripts\Activate.ps1
  ```

### Step 2. 의존성 설치

```powershell
cd oect-paper-search
pip install -r requirements.txt
```

주요 패키지: `flask`, `google-genai`, `PyMuPDF`, `Pillow`, `schemdraw>=0.19`, `matplotlib>=3.8.0`, `python-dotenv`

### Step 3. Gemini API 키 발급 (본인 키 사용)

1. https://aistudio.google.com/apikey 접속 (Google 로그인)
2. **Create API key** 클릭 → 키 복사
3. 무료 티어 한도: 분당 10회 / 일일 250회 (시연 5~10편이면 충분)

### Step 4. `.env` 파일 만들기

`.env.example`을 복사해서 `.env`를 만들고 본인 키 입력:

```powershell
copy .env.example .env
notepad .env
```

`.env` 내용:
```
GEMINI_API_KEY=발급받은_본인_키_여기에
OPENALEX_EMAIL=your_email@example.com
```

⚠️ **`.env`는 절대 GitHub에 커밋하지 말 것** (`.gitignore`에 이미 포함됨)

### Step 5. 서버 실행

```powershell
python app.py
```

성공 시 출력:
```
 * Running on http://127.0.0.1:5000
```

### Step 6. 브라우저에서 시연

1. http://localhost:5000 접속
2. 카메라 권한 **허용** (모션 인식용 — 거부 시 하단 버튼으로 수동 선택 가능)
3. 신체 부위로 손 이동 (예: 가슴 → 심장) → 1.5초 유지 → 자동 이동
4. 행동 선택 → "논문 검색" → 카드에서 "AI PDF 분석"
5. 6필드 탭(재료/구조/메커니즘/공정/응용/회로) 확인

### Step 7. (강력 추천) 시연 전 캐시 채워두기

발표 도중 quota 사고나 네트워크 끊김 방지:

1. 시연용 논문 5~10편을 발표 **하루 전**에 미리 분석 (한 번씩 클릭만)
2. `cache/{sha}.{kind}.json` 파일이 생성됨
3. 발표 당일엔 같은 논문 클릭 시 **50ms 즉시 응답** (Gemini 호출 0회)
4. 응답에 `"cached": true` 플래그 확인 가능

또는 프로젝트 담당자에게 `cache/` 폴더 통째로 받아서 자기 `oect-paper-search/cache/`에 복사하면 동일.

### 트러블슈팅

| 증상 | 원인 / 해결 |
|---|---|
| `ModuleNotFoundError: google.genai` | `pip install google-genai` 추가 설치 |
| `GEMINI_API_KEY not set` | `.env` 파일 위치·이름·키명 확인 (앱 실행 디렉토리에 있어야 함) |
| 카메라 안 켜짐 | 브라우저 권한 / HTTPS 아닌 localhost는 OK / 다른 앱이 점유 중인지 확인 |
| PDF 분석 실패 (403) | 출판사 차단 — 자동으로 "PDF 업로드" 버튼 노출됨. PDF 직접 다운받아 업로드 |
| `429 RESOURCE_EXHAUSTED` | Gemini quota 초과 — 분당 10회 한도. 1분 대기 또는 결제 활성화 |
| 회로 탭이 비어있음 | 정상적으론 안 발생 (always-on 폴백으로 `generic_3_terminal` 안전망). 발생 시 server.log 확인 |

### 시연 전 최종 체크리스트

- [ ] `python app.py` 정상 실행
- [ ] http://localhost:5000 로딩 OK
- [ ] 카메라 권한 허용·인식 동작
- [ ] 시연 논문 5편 이상 캐시 채움
- [ ] 백업 영상 1개 (인터넷·카메라 실패 대비)
- [ ] (결제 활성화 추천) Gemini API 결제 등록 — 논문당 ~10원
