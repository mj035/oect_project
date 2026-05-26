"""분석 결과 디스크 캐싱.

PDF 본문을 SHA-256으로 해싱해 키로 사용. 같은 PDF는 두 번째 호출부터 즉시 응답.
- 발표 시연 안정성 확보 (네트워크/quota 사고 무관)
- 무료 API quota 소비 절감

캐시 종류:
  "analyze" : analyze_with_pdf 결과 (summary)
  "figures" : _process_pdf_figures 결과 (figures, fallbackMeta 등)
"""
import os
import json
import hashlib
import time

CACHE_DIR = os.path.join(os.path.dirname(__file__), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)


def pdf_sha(pdf_bytes: bytes) -> str:
    """PDF 바이트 → SHA-256 16진수 문자열."""
    return hashlib.sha256(pdf_bytes).hexdigest()


def _path(sha: str, kind: str) -> str:
    return os.path.join(CACHE_DIR, f"{sha}.{kind}.json")


def load(sha: str, kind: str) -> dict | None:
    """캐시 조회. 없거나 깨지면 None."""
    p = _path(sha, kind)
    if not os.path.exists(p):
        return None
    try:
        with open(p, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return None
        return data
    except (OSError, json.JSONDecodeError):
        return None


def save(sha: str, kind: str, data: dict) -> None:
    """캐시 저장. 실패해도 호출자에 영향 없음."""
    if not isinstance(data, dict):
        return
    p = _path(sha, kind)
    try:
        # _meta는 캐시 자체 메타정보 (히트 표시용)
        payload = dict(data)
        payload.setdefault("_meta", {})
        payload["_meta"].update({
            "cached_at": time.time(),
            "sha": sha,
        })
        # atomic write
        tmp = p + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)
        os.replace(tmp, p)
    except OSError:
        pass


def stats() -> dict:
    """현재 캐시 디렉토리 상태 (디버그용)."""
    files = [f for f in os.listdir(CACHE_DIR) if f.endswith(".json")]
    total_size = sum(os.path.getsize(os.path.join(CACHE_DIR, f)) for f in files)
    return {
        "dir": CACHE_DIR,
        "count": len(files),
        "total_bytes": total_size,
    }
