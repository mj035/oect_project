"""OECT 전용 schemdraw 커스텀 심볼.

게이트가 전해질 위에 떠있는 OECT의 구조적 특징을 회로도에 반영.
앵커: drain (오른쪽), source (왼쪽), gate (위), electrolyte (중앙 위)
"""
import schemdraw
import schemdraw.elements as elm
from schemdraw.segments import Segment, SegmentText, SegmentCircle


class OECT(elm.Element):
    """OECT 트랜지스터 심볼.

    좌우 두 전극(source/drain) 사이에 채널이 있고, 채널 위에 전해질 박스,
    그 위에 게이트 단자가 떠있는 구조.

    사용 예:
        d += (T1 := OECT().label('OECT', loc='bottom'))
        d += elm.Line().right().at(T1.drain)
    """

    def __init__(self, *args, channel_label="PEDOT:PSS", electrolyte_label="PBS",
                 gate_label="Ag/AgCl", **kwargs):
        super().__init__(*args, **kwargs)
        # 좌표는 schemdraw 단위 (1.0 = 1 grid)
        # 채널: y=0에서 y=0.4 사이 직사각형, x=-1.0 ~ x=1.0
        # 전해질: y=0.5 ~ y=1.1, 점선
        # 게이트: y=1.4에서 단자 나옴

        # 소스/드레인 리드선
        self.segments.append(Segment([(-1.5, 0.2), (-1.0, 0.2)]))   # source 리드
        self.segments.append(Segment([(1.0, 0.2), (1.5, 0.2)]))     # drain 리드

        # 채널 (실선 박스)
        self.segments.append(Segment([
            (-1.0, 0.0), (1.0, 0.0), (1.0, 0.4), (-1.0, 0.4), (-1.0, 0.0)
        ]))

        # 전해질 (점선 박스)
        self.segments.append(Segment(
            [(-1.0, 0.5), (1.0, 0.5), (1.0, 1.1), (-1.0, 1.1), (-1.0, 0.5)],
            ls="--",
        ))

        # 게이트 전극 (전해질 안에 떠있는 막대)
        self.segments.append(Segment([(-0.3, 0.8), (0.3, 0.8)], lw=2))
        # 게이트 리드선 (위로 빠짐)
        self.segments.append(Segment([(0.0, 0.8), (0.0, 1.6)]))

        # 라벨
        self.segments.append(SegmentText((0.0, 0.2), channel_label, fontsize=9))
        self.segments.append(SegmentText((0.0, 1.25), electrolyte_label, fontsize=8, color="#0a7"))
        self.segments.append(SegmentText((0.55, 0.8), gate_label, fontsize=8, color="#a06"))

        # 단자 라벨 (S/D)
        self.segments.append(SegmentText((-1.45, 0.05), "S", fontsize=8))
        self.segments.append(SegmentText((1.45, 0.05), "D", fontsize=8))
        self.segments.append(SegmentText((-0.15, 1.5), "G", fontsize=8))

        # 앵커: 외부 회로가 연결할 점
        self.anchors["source"] = (-1.5, 0.2)
        self.anchors["drain"] = (1.5, 0.2)
        self.anchors["gate"] = (0.0, 1.6)
        self.anchors["center"] = (0.0, 0.2)

        # bbox (자동 레이아웃용)
        self.params["drop"] = (1.5, 0.2)
