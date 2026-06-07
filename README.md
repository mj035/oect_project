# OECT 논문 검색 & PDF 분석 시스템

MediaPipe 모션 인식으로 신체 부위를 선택하면
관련 OECT 논문을 검색하고, 선택한 논문의 전체 PDF를 Gemini AI로 분석하여
재료/회로/공정 정보를 추출하는 웹 시스템입니다.

---

## 발표자료

| 발표 | PDF (바로 보기) | PPTX (원본) |
|------|----------------|-------------|
| 중간 발표 | [중간 발표 PDF](docs/OECT논문분석시스템_중간발표.pdf) | [PPTX](docs/OECT논문분석시스템_중간발표.pptx) |
| 기말 발표 | [기말 발표 PDF](docs/OECT논문분석시스템_기말발표.pdf) | [PPTX](docs/OECT논문분석시스템_기말발표.pptx) |

> PDF는 GitHub에서 바로 미리보기가 가능하며, PPTX는 다운로드 후 PowerPoint로 열 수 있습니다.

### 데모 영상

[OECT 논문 분석 시스템 데모 영상 보기](docs/OECT논문분석시스템_데모영상.mp4)


---

## 실행 방법

### 1. 패키지 설치

```bash
cd oect-paper-search
pip install -r requirements.txt
```

### 2. API 키 설정

`.env.example`을 복사하여 `.env` 파일을 만들고 Gemini API 키를 입력합니다.

```bash
copy .env.example .env
```

`.env` 파일:
```
GEMINI_API_KEY=여기에_Gemini_API_키_입력
OPENALEX_EMAIL=your_email@example.com
```

Gemini API 키는 https://aistudio.google.com/apikey 에서 무료로 발급받을 수 있습니다.

### 3. 서버 실행

```bash
python app.py
```

### 4. 웹 브라우저에서 접속

```
http://localhost:5000
```

---

## 사용 방법

### 모션 인식 (메인 페이지)
1. 카메라 권한을 허용합니다
2. 카메라 앞에서 손을 특정 위치로 가져갑니다:
   - **머리 위** → 뇌 (Brain)
   - **눈 높이** → 눈 (Eye)
   - **가슴 위치** → 심장 (Cardiac)
   - **배 위치** → 간 (Liver)
   - **팔 바깥쪽** → 근육 (Muscle)
   - **기본** → 피부 (Skin)
3. 1.5초 유지하면 자동으로 해당 장기 페이지로 이동합니다
4. 또는 하단 버튼으로 직접 선택할 수도 있습니다

### 논문 검색 & 분석 (장기 페이지)
1. 왼쪽 패널에서 **행동 타입** 선택 (센싱/모니터링/치료/약물전달)
2. **논문 검색** 버튼 클릭
3. 논문 카드 목록에서 원하는 논문의 **AI PDF 분석** 버튼 클릭
4. 재료 / 회로 / 공정 탭에서 분석 결과 확인

---

## API 엔드포인트

### 논문 검색 (AI 없이 빠른 검색)
```
POST /api/search
Content-Type: application/json
{"organ": "brain", "action": "sensing"}
```

### 개별 논문 AI 분석
```
POST /api/analyze
Content-Type: application/json
{"title": "...", "abstract": "...", "pdfUrl": "https://..."}
```

### 모션팀 연동
```
POST /api/trigger
Content-Type: application/json
{"organ": "cardiac", "action": "sensing"}
```

**organ 값:** cardiac / liver / skin / eye / brain / muscle
**action 값:** sensing / monitoring / stimulation / drug_delivery

---

## 기술 스택

| 구분 | 기술 |
|------|------|
| Frontend | HTML, CSS, JavaScript, MediaPipe Pose |
| Backend | Python Flask |
| 논문 검색 | OpenAlex API (무료) |
| AI 분석 | Google Gemini 2.5 Flash (무료 티어) |

---

## 파일 구조

```
oect-paper-search/
├── app.py                  ← Flask 서버 + 모든 API 로직
├── requirements.txt        ← Python 패키지
├── .env.example            ← 환경변수 예시
├── .env                    ← 실제 API 키 (직접 생성)
├── templates/
│   ├── index.html          ← MediaPipe 모션 인식 페이지
│   └── organ.html          ← 논문 검색 & AI 분석 페이지
├── static/
│   ├── css/
│   │   └── style.css       ← 공통 다크 테마
│   └── js/
│       └── mediapipe.js    ← 모션 인식 로직
└── docs/                   ← 발표자료 (중간/기말, PDF + PPTX)
```
