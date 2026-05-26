"""텍스트 → OECT 회로 폴백 생성기.

흐름:
  1. Gemini에 분석 텍스트(mechanism + device_structure 등) + 분석 요약 + figure 캡션을
     함께 보내서 토폴로지 분류 + 파라미터(재료/전압/센싱요소) JSON으로 받음
  2. OECT 도메인 룰로 confidence 후보정
  3. 매칭되는 schemdraw 템플릿 호출 → PNG base64 반환

실패 시에도 generic_3_terminal로 최소 1장은 그림.
"""
import json
import re
from typing import Callable, Iterable

from .templates import TOPOLOGY_RENDERERS

VALID_TOPOLOGIES = ("common_source", "transimpedance", "voltage_divider", "generic_3_terminal")


CLASSIFY_PROMPT = """\
You are an OECT/bioelectronics circuit expert. Analyze the paper materials below and identify the most likely circuit topology used in the measurement/sensing setup.

You will receive multiple sources stitched together:
  [SUMMARY]      — pre-extracted analysis (materials, device_structure, mechanism, application)
  [FIGURES]      — captions of detected figures (may hint at bias values)
  [PAPER_TEXT]   — raw text excerpt from the paper PDF

Output a JSON object with EXACTLY these fields:
{
  "topology": "common_source" | "transimpedance" | "voltage_divider" | "generic_3_terminal",
  "channel_material": string,           // e.g. "PEDOT:PSS", "p(g2T-TT)"
  "electrolyte": string,                // e.g. "PBS", "saliva"
  "gate_type": string,                  // e.g. "Ag/AgCl", "Pt wire"
  "v_ds": string,                       // e.g. "-0.6 V" or "V_DS" if not stated
  "v_gs": string,                       // e.g. "0.2 V" or "V_GS" if not stated
  "sensing_element": string | null,
  "confidence": number                  // see scoring rubric below
}

Topology guide:
- "common_source": V_DS between source/drain, V_GS at gate, I_DS measured. Most OECT sensing papers.
- "transimpedance": OECT current → op-amp + feedback resistor → voltage. Photo/enzymatic sensors with op-amp readout.
- "voltage_divider": OECT in series with R_load, V_out at divider node. Simple readout circuits.
- "generic_3_terminal": choose if no clear topology can be inferred.

Confidence scoring rubric (FOLLOW THIS — do not be overly conservative):
- 0.8~1.0: Explicit V_DS AND V_GS values stated, topology unambiguous from text/captions.
- 0.6~0.8: Clear OECT bias scheme described, channel + gate materials known, topology inferable.
- 0.4~0.6: Channel material + gate type known, OECT measurement implied, topology by domain default.
- 0.2~0.4: Only OECT use confirmed, materials partially known, topology guessed by convention.
- 0.0~0.2: Almost no circuit-relevant information present.

For OECT sensing/monitoring/recording papers without explicit op-amp or load resistor mentions,
the default topology is "common_source" — do not collapse to generic_3_terminal unless truly nothing is known.

Output ONLY the JSON object. No markdown, no code fences, no commentary.

{text}
"""


def _parse_response(text: str) -> dict:
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


def _components_list(params: dict, topology: str) -> list:
    base = [
        {"type": "OECT", "label": params.get("channel_material", "PEDOT:PSS")},
        {"type": "Electrolyte", "label": params.get("electrolyte", "PBS")},
        {"type": "Gate", "label": params.get("gate_type", "Ag/AgCl")},
    ]
    extras = {
        "common_source":     [{"type": "VSource", "label": "V_DS"}, {"type": "VSource", "label": "V_GS"}, {"type": "Ammeter", "label": "I_DS"}],
        "transimpedance":    [{"type": "Opamp"}, {"type": "Resistor", "label": "R_f"}],
        "voltage_divider":   [{"type": "Resistor", "label": "R_load"}],
        "generic_3_terminal": [],
    }
    return base + extras.get(topology, [])


# OECT 도메인 키워드 — 후처리 보정용
OECT_CHANNEL_HINTS = ("PEDOT:PSS", "PEDOT", "p(g2T-TT)", "BBL", "P3HT", "PProDOT", "polyaniline")
OECT_GATE_HINTS = ("Ag/AgCl", "AgCl", "Pt wire", "Pt gate", "ITO gate", "Au gate")
TOPOLOGY_HINTS = {
    "transimpedance":   ("transimpedance", "op-amp", "opamp", "operational amplifier", "feedback resistor"),
    "voltage_divider":  ("voltage divider", "load resistor", "R_load", "pull-up resistor"),
    "common_source":    ("common source", "common-source", "transfer curve", "I_DS", "I_D-V_G", "I-V"),
}


def _domain_boost(params: dict, topology: str, paper_text: str) -> tuple[float, str]:
    """OECT 도메인 룰로 confidence 가산. (boost, reason) 반환."""
    boost = 0.0
    reasons = []

    text_low = (paper_text or "").lower()

    # 채널 재료 매칭
    ch = (params.get("channel_material") or "").lower()
    if any(h.lower() in ch for h in OECT_CHANNEL_HINTS) or any(h.lower() in text_low for h in OECT_CHANNEL_HINTS):
        boost += 0.10
        reasons.append("OECT 채널 재료 확인됨")

    # 게이트 재료 매칭
    gate = (params.get("gate_type") or "").lower()
    if any(h.lower() in gate for h in OECT_GATE_HINTS) or any(h.lower() in text_low for h in OECT_GATE_HINTS):
        boost += 0.10
        reasons.append("게이트 전극 타입 확인됨")

    # V_DS, V_GS 수치 (-0.6 V 같은) 추출 가능 여부
    vds = params.get("v_ds") or ""
    vgs = params.get("v_gs") or ""
    voltage_pat = re.compile(r"-?\d+(\.\d+)?\s*[mμnu]?V", re.IGNORECASE)
    if voltage_pat.search(vds):
        boost += 0.05
        reasons.append("V_DS 수치 추출됨")
    if voltage_pat.search(vgs):
        boost += 0.05
        reasons.append("V_GS 수치 추출됨")

    # 토폴로지별 키워드 일치
    hints = TOPOLOGY_HINTS.get(topology, ())
    if any(h in text_low for h in hints):
        boost += 0.10
        reasons.append(f"본문에 {topology} 키워드 등장")

    # generic으로 떨어진 경우는 가산 안 함 (오히려 confidence 낮게 유지)
    if topology == "generic_3_terminal":
        boost = min(boost, 0.05)

    return boost, ", ".join(reasons)


def _build_input(paper_text: str, summary: dict | None, figure_captions: Iterable[str] | None) -> str:
    """Gemini에 보낼 멀티섹션 입력 조립."""
    parts = []

    if summary and isinstance(summary, dict):
        s = []
        for key in ("materials", "device_structure", "mechanism", "application"):
            v = summary.get(key)
            if not v:
                continue
            if isinstance(v, list):
                v = "; ".join(str(x) for x in v)
            s.append(f"- {key}: {v}")
        if s:
            parts.append("[SUMMARY]\n" + "\n".join(s))

    if figure_captions:
        cleaned = [c.strip() for c in figure_captions if c and str(c).strip()]
        if cleaned:
            parts.append("[FIGURES]\n" + "\n".join(f"- {c}" for c in cleaned[:30]))

    if paper_text and paper_text.strip():
        parts.append("[PAPER_TEXT]\n" + paper_text.strip()[:5000])

    return "\n\n".join(parts) if parts else (paper_text or "")[:5000]


def generate_fallback_circuit(
    paper_text: str,
    out_dir: str = "./out",
    gemini_call_fn: Callable | None = None,
    summary: dict | None = None,
    figure_captions: Iterable[str] | None = None,
) -> dict:
    """논문 텍스트(+요약+캡션) → 회로 PNG 생성. INTEGRATION_CONTRACT.md 시그니처 준수.

    Args:
        paper_text: PDF 본문 추출 텍스트
        out_dir: 사용 안 함 (호환성)
        gemini_call_fn: app._call_gemini 주입
        summary: analyze 결과 dict (materials/device_structure/mechanism/application)
        figure_captions: 1/2순위에서 분류된 figure 캡션 리스트
    """
    composed = _build_input(paper_text or "", summary, figure_captions)
    if not composed.strip():
        return _failure("입력 텍스트가 비어있음", topology="generic_3_terminal")

    params: dict = {}
    topology = "generic_3_terminal"
    raw_confidence = 0.0
    boost_reason = ""

    if gemini_call_fn is not None:
        try:
            prompt = CLASSIFY_PROMPT.replace("{text}", composed)
            resp_text = gemini_call_fn(prompt)
            parsed = _parse_response(resp_text)

            t = parsed.get("topology", "generic_3_terminal")
            if t not in VALID_TOPOLOGIES:
                t = "generic_3_terminal"
            topology = t
            try:
                raw_confidence = float(parsed.get("confidence", 0.0) or 0.0)
            except (TypeError, ValueError):
                raw_confidence = 0.0
            params = {
                "channel_material": parsed.get("channel_material"),
                "electrolyte":      parsed.get("electrolyte"),
                "gate_type":        parsed.get("gate_type"),
                "v_ds":             parsed.get("v_ds"),
                "v_gs":             parsed.get("v_gs"),
                "sensing_element":  parsed.get("sensing_element"),
            }
        except json.JSONDecodeError:
            topology = "generic_3_terminal"
            raw_confidence = 0.0
        except Exception:
            topology = "generic_3_terminal"
            raw_confidence = 0.0

    # 도메인 룰 보정
    boost, boost_reason = _domain_boost(params, topology, composed)
    confidence = max(0.0, min(1.0, raw_confidence + boost))

    # 템플릿 렌더링 — generic이 안전망
    renderer = TOPOLOGY_RENDERERS.get(topology) or TOPOLOGY_RENDERERS["generic_3_terminal"]
    try:
        image_b64 = renderer(params)
    except Exception as e:
        if topology != "generic_3_terminal":
            try:
                image_b64 = TOPOLOGY_RENDERERS["generic_3_terminal"](params)
                topology = "generic_3_terminal"
            except Exception as e2:
                return _failure(f"렌더링 실패: {e2}", topology=topology)
        else:
            return _failure(f"렌더링 실패: {e}", topology=topology)

    return {
        "success": True,
        "image_path": None,
        "image_b64": image_b64,
        "topology": topology,
        "confidence": confidence,
        "raw_confidence": raw_confidence,
        "boost_reason": boost_reason,
        "components": _components_list(params, topology),
        "error": None,
    }


def _failure(msg: str, topology: str = "unknown") -> dict:
    return {
        "success": False,
        "image_path": None,
        "image_b64": None,
        "topology": topology,
        "confidence": 0.0,
        "components": [],
        "error": msg,
    }
