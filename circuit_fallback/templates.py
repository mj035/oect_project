"""OECT 회로 토폴로지 템플릿 4종.

각 함수는 파라미터 dict를 받아 schemdraw Drawing을 만들고 PNG bytes 반환.
파라미터:
  - channel_material: str (예: "PEDOT:PSS")
  - electrolyte: str (예: "PBS")
  - gate_type: str (예: "Ag/AgCl")
  - v_ds: str (예: "-0.6 V")
  - v_gs: str (예: "0.2 V")
  - sensing_element: str | None (예: "MIP layer")
"""
import io
import base64

import matplotlib
matplotlib.use("Agg")  # GUI 없는 환경

import schemdraw
import schemdraw.elements as elm

from .oect_symbols import OECT


def _drawing_to_png_b64(d: schemdraw.Drawing) -> str:
    """Drawing → PNG bytes → base64 문자열."""
    buf = io.BytesIO()
    d.save(buf, dpi=160)
    return base64.standard_b64encode(buf.getvalue()).decode()


def _common(params: dict) -> dict:
    """파라미터 기본값 채우기."""
    return {
        "channel_material": params.get("channel_material") or "PEDOT:PSS",
        "electrolyte":      params.get("electrolyte")      or "PBS",
        "gate_type":        params.get("gate_type")        or "Ag/AgCl",
        "v_ds":             params.get("v_ds")             or "V_DS",
        "v_gs":             params.get("v_gs")             or "V_GS",
        "sensing_element":  params.get("sensing_element"),
    }


def render_common_source(params: dict) -> str:
    """Common-source: V_DS + V_GS + I_DS 측정 (가장 흔함)."""
    p = _common(params)
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.0)
        T1 = d.add(OECT(channel_label=p["channel_material"],
                        electrolyte_label=p["electrolyte"],
                        gate_label=p["gate_type"]))

        # 드레인 → 전류계 → V_DS → GND
        d += elm.Line().right(d.unit * 0.5).at(T1.drain)
        d += (A1 := elm.MeterA().right().label("I_DS"))
        d += elm.Line().right(d.unit * 0.3)
        d += elm.SourceV().down().reverse().label(p["v_ds"], loc="right")
        d += elm.Ground()

        # 소스 → GND
        d += elm.Line().left(d.unit * 0.5).at(T1.source)
        d += elm.Ground()

        # 게이트 → V_GS → GND
        d += elm.Line().up(d.unit * 0.4).at(T1.gate)
        d += elm.SourceV().up().reverse().label(p["v_gs"], loc="right")
        d += elm.Ground()

        d += elm.Label().at((0, -1.5)).label(
            f"Common-source bias\n({p['channel_material']} / {p['electrolyte']} / {p['gate_type']})",
            fontsize=10,
        )

    return _drawing_to_png_b64(d)


def render_transimpedance(params: dict) -> str:
    """Transimpedance: I_DS → opamp → V_out (광/효소 센서에서 흔함)."""
    p = _common(params)
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.0)
        T1 = d.add(OECT(channel_label=p["channel_material"],
                        electrolyte_label=p["electrolyte"],
                        gate_label=p["gate_type"]))

        # 게이트 → V_GS → GND
        d += elm.Line().up(d.unit * 0.4).at(T1.gate)
        d += elm.SourceV().up().reverse().label(p["v_gs"], loc="right")
        d += elm.Ground()

        # 소스 → V_DS → GND
        d += elm.Line().left(d.unit * 0.5).at(T1.source)
        d += elm.SourceV().down().label(p["v_ds"], loc="left")
        d += elm.Ground()

        # 드레인 → opamp 반전 입력
        d += elm.Line().right(d.unit * 0.6).at(T1.drain)
        op = d.add(elm.Opamp(leads=True).anchor("in1"))

        # 비반전 입력 → GND
        d += elm.Line().left(d.unit * 0.3).at(op.in2)
        d += elm.Ground()

        # 피드백 저항 (drain → out)
        d += elm.Line().up(d.unit * 0.8).at(op.in1)
        d += elm.Resistor().right().label("R_f")
        d += elm.Line().down(d.unit * 0.8).to(op.out)

        # 출력
        d += elm.Line().right(d.unit * 0.5).at(op.out)
        d += elm.Dot().label("V_out", loc="right")

        d += elm.Label().at((0, -1.5)).label(
            f"Transimpedance amplifier\n({p['channel_material']} / {p['electrolyte']})",
            fontsize=10,
        )

    return _drawing_to_png_b64(d)


def render_voltage_divider(params: dict) -> str:
    """Voltage divider: OECT 드레인에 R_load 직렬, V_out은 그 사이.

    레이아웃을 단순화하기 위해 OECT를 가로 그대로 두고 드레인 라인에 R_load를
    직렬 삽입한 뒤 V_DD까지 연결.
    """
    p = _common(params)
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.0)
        T1 = d.add(OECT(channel_label=p["channel_material"],
                        electrolyte_label=p["electrolyte"],
                        gate_label=p["gate_type"]))

        # 드레인 → R_load → V_DD
        d += elm.Line().right(d.unit * 0.4).at(T1.drain)
        d += (vout := elm.Dot().label("V_out", loc="top"))
        d += elm.Resistor().right().label("R_load")
        d += elm.SourceV().up().reverse().label(p["v_ds"], loc="right")
        d += elm.Ground()

        # 소스 → GND
        d += elm.Line().left(d.unit * 0.4).at(T1.source)
        d += elm.Ground()

        # 게이트 → V_GS → GND
        d += elm.Line().up(d.unit * 0.4).at(T1.gate)
        d += elm.SourceV().up().reverse().label(p["v_gs"], loc="right")
        d += elm.Ground()

        d += elm.Label().at((0, -1.5)).label(
            f"Voltage divider readout\n({p['channel_material']} / {p['electrolyte']})",
            fontsize=10,
        )

    return _drawing_to_png_b64(d)


def render_generic_3_terminal(params: dict) -> str:
    """Generic: 토폴로지 미상일 때 OECT 3단자만 라벨링."""
    p = _common(params)
    with schemdraw.Drawing(show=False) as d:
        d.config(unit=2.0)
        T1 = d.add(OECT(channel_label=p["channel_material"],
                        electrolyte_label=p["electrolyte"],
                        gate_label=p["gate_type"]))

        # 단자만 빼주기
        d += elm.Line().right(d.unit * 0.5).at(T1.drain)
        d += elm.Dot().label("Drain", loc="right")

        d += elm.Line().left(d.unit * 0.5).at(T1.source)
        d += elm.Dot().label("Source", loc="left")

        d += elm.Line().up(d.unit * 0.3).at(T1.gate)
        d += elm.Dot().label("Gate", loc="top")

        sense = p["sensing_element"]
        note = f"\nSensing: {sense}" if sense else ""
        d += elm.Label().at((0, -1.5)).label(
            f"OECT (generic 3-terminal){note}\n"
            f"V_DS={p['v_ds']} | V_GS={p['v_gs']}",
            fontsize=10,
        )

    return _drawing_to_png_b64(d)


TOPOLOGY_RENDERERS = {
    "common_source":     render_common_source,
    "transimpedance":    render_transimpedance,
    "voltage_divider":   render_voltage_divider,
    "generic_3_terminal": render_generic_3_terminal,
}
