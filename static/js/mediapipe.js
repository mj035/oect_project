/**
 * MediaPipe Holistic 기반 모션 인식 → 장기(organ) 선택
 *
 * 감지 규칙:
 *   손 → 머리 위          → brain   (기존 유지)
 *   V사인 + 얼굴 옆       → eye     (검지+중지만 펴고 얼굴 근처)
 *   손 → 가슴 위치        → cardiac (기존 유지)
 *   손 → 배 위치          → liver   (기존 유지)
 *   양손 주먹             → muscle  (양손 모든 손가락 접기)
 *   양손 손바닥 펼침       → skin    (양손 모든 손가락 펴기)
 */

(function () {
  'use strict';

  const HOLD_MS = 1500;

  const video  = document.getElementById('webcam');
  const canvas = document.getElementById('pose-canvas');
  const dot    = document.getElementById('detect-dot');
  const txt    = document.getElementById('detect-text');
  const ctx    = canvas.getContext('2d');

  let currentOrgan = null;
  let holdStart    = 0;
  let navigating   = false;

  // ── 초기화: Holistic 로드 ──
  async function init() {
    const CDN = 'https://cdn.jsdelivr.net/npm/@mediapipe/holistic@0.5.1675471629/';

    await loadScript(CDN + 'holistic.js');

    const holistic = new window.Holistic({
      locateFile: (file) => CDN + file,
    });

    holistic.setOptions({
      modelComplexity: 1,
      smoothLandmarks: true,
      minDetectionConfidence: 0.5,
      minTrackingConfidence: 0.5,
    });

    holistic.onResults(onResults);

    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { width: 640, height: 480, facingMode: 'user' },
      });
      video.srcObject = stream;
      video.onloadedmetadata = () => {
        canvas.width  = video.videoWidth;
        canvas.height = video.videoHeight;
        txt.textContent = '모델 로딩 중...';
        detectLoop(holistic);
      };
    } catch (e) {
      txt.textContent = '카메라 접근 불가 — 아래 버튼으로 선택하세요';
      console.warn('Camera error:', e);
    }
  }

  async function detectLoop(holistic) {
    if (navigating) return;
    await holistic.send({ image: video });
    requestAnimationFrame(() => detectLoop(holistic));
  }

  // ─────────────────────────────────────────────────────
  //  손가락 제스처 판별 (Hand Landmarks 21개 기준)
  //
  //  랜드마크 인덱스:
  //    4 = 엄지 끝,   3 = 엄지 IP
  //    8 = 검지 끝,   6 = 검지 PIP
  //   12 = 중지 끝,  10 = 중지 PIP
  //   16 = 약지 끝,  14 = 약지 PIP
  //   20 = 소지 끝,  18 = 소지 PIP
  // ─────────────────────────────────────────────────────

  function isFingerExtended(hand, tipIdx, pipIdx) {
    return hand[tipIdx].y < hand[pipIdx].y;
  }

  function isFingerCurled(hand, tipIdx, pipIdx) {
    return hand[tipIdx].y > hand[pipIdx].y;
  }

  /** V사인: 검지+중지 펴고, 약지+소지 접기 */
  function isVSign(hand) {
    if (!hand) return false;
    const indexUp  = isFingerExtended(hand, 8, 6);
    const middleUp = isFingerExtended(hand, 12, 10);
    const ringDown  = isFingerCurled(hand, 16, 14);
    const pinkyDown = isFingerCurled(hand, 20, 18);
    return indexUp && middleUp && ringDown && pinkyDown;
  }

  /** 주먹: 검지+중지+약지+소지 모두 접기 */
  function isFist(hand) {
    if (!hand) return false;
    return isFingerCurled(hand, 8, 6)
        && isFingerCurled(hand, 12, 10)
        && isFingerCurled(hand, 16, 14)
        && isFingerCurled(hand, 20, 18);
  }

  /** 손바닥: 검지+중지+약지+소지 모두 펴기 */
  function isOpenPalm(hand) {
    if (!hand) return false;
    return isFingerExtended(hand, 8, 6)
        && isFingerExtended(hand, 12, 10)
        && isFingerExtended(hand, 16, 14)
        && isFingerExtended(hand, 20, 18);
  }

  // ── Holistic 결과 처리 ──
  function onResults(results) {
    ctx.save();
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    ctx.translate(canvas.width, 0);
    ctx.scale(-1, 1);

    const pose = results.poseLandmarks;
    const leftHand  = results.leftHandLandmarks;   // 왼손 21개
    const rightHand = results.rightHandLandmarks;   // 오른손 21개

    if (pose) drawPoseLandmarks(pose);
    if (leftHand) drawHandLandmarks(leftHand, '#3ecf8e');
    if (rightHand) drawHandLandmarks(rightHand, '#f59e0b');
    ctx.restore();

    if (!pose) {
      setDetect(null, '포즈를 감지할 수 없습니다');
      return;
    }

    // 기본 pose 랜드마크
    const nose     = pose[0];
    const lShould  = pose[11];
    const rShould  = pose[12];
    const lHip     = pose[23];
    const rHip     = pose[24];
    const shoulderY = (lShould.y + rShould.y) / 2;
    const shoulderX = (lShould.x + rShould.x) / 2;
    const hipY      = (lHip.y + rHip.y) / 2;
    const noseY     = nose.y;

    // 활성 손 위치 (pose 기준, 더 높은 쪽)
    const lWrist = pose[15];
    const rWrist = pose[16];
    const handVisible = (lWrist.visibility || 0) > 0.4 || (rWrist.visibility || 0) > 0.4;

    if (!handVisible) {
      setDetect(null, '손을 카메라에 보여주세요');
      return;
    }

    // 활성 손 (더 높은 손)
    const activeWrist = rWrist.y < lWrist.y ? rWrist : lWrist;

    let detected = null;

    // ── 우선순위 1: 양손 제스처 (muscle, skin) ──

    // 근육: 양손 주먹
    if (leftHand && rightHand && isFist(leftHand) && isFist(rightHand)) {
      detected = 'muscle';
    }
    // 피부: 양손 손바닥 펼침
    else if (leftHand && rightHand && isOpenPalm(leftHand) && isOpenPalm(rightHand)) {
      detected = 'skin';
    }

    // ── 우선순위 2: 한손 제스처 + 위치 (eye) ──

    // 눈: V사인이 얼굴 옆에 있을 때
    else if (isVSignNearFace(leftHand, nose) || isVSignNearFace(rightHand, nose)) {
      detected = 'eye';
    }

    // ── 우선순위 3: 위치 기반 (brain, cardiac, liver) — 기존 유지 ──

    // 뇌: 손이 머리 위
    else if (activeWrist.y < noseY - 0.08) {
      detected = 'brain';
    }
    // 심장: 손이 가슴 위치
    else if (activeWrist.y >= shoulderY - 0.03 && activeWrist.y < shoulderY + 0.10
             && Math.abs(activeWrist.x - shoulderX) < 0.20) {
      detected = 'cardiac';
    }
    // 간: 손이 배 위치
    else if (activeWrist.y >= shoulderY + 0.10 && activeWrist.y < hipY + 0.05
             && Math.abs(activeWrist.x - shoulderX) < 0.25) {
      detected = 'liver';
    }

    // 아무것도 해당 안 되면 null
    processDetection(detected);
  }

  /** V사인이 얼굴 옆에 있는지 판별 */
  function isVSignNearFace(hand, nose) {
    if (!hand || !isVSign(hand)) return false;
    const wrist = hand[0];
    // 손목이 코 근처 높이 (위아래 여유 20%) & 수평 거리 30% 이내
    const verticalNear = Math.abs(wrist.y - nose.y) < 0.20;
    const horizontalNear = Math.abs(wrist.x - nose.x) < 0.30;
    return verticalNear && horizontalNear;
  }

  // ── 감지 상태 관리 ──
  function processDetection(organ) {
    if (navigating) return;

    if (organ !== currentOrgan) {
      currentOrgan = organ;
      holdStart = Date.now();
    }

    const held = Date.now() - holdStart;
    const progress = Math.min(held / HOLD_MS, 1);

    if (organ) {
      const labels = {
        brain:   '🧠 뇌 (Brain)',
        eye:     '👁️ 눈 (Eye) — V사인 감지',
        cardiac: '❤️ 심장 (Cardiac)',
        liver:   '🧪 간 (Liver)',
        muscle:  '💪 근육 (Muscle) — 양손 주먹 감지',
        skin:    '🖐️ 피부 (Skin) — 양손 펼침 감지',
      };
      const pct = Math.round(progress * 100);
      if (progress >= 1) {
        setDetect(organ, `${labels[organ]} 확정! 이동 중...`);
        navigate(organ);
      } else {
        setDetect(organ, `${labels[organ]} (${pct}%)`);
      }
    } else {
      setDetect(null, '제스처 또는 손 위치로 장기를 선택하세요');
    }
  }

  function navigate(organ) {
    navigating = true;
    setTimeout(() => {
      window.location.href = `/organ/${organ}`;
    }, 400);
  }

  function setDetect(organ, message) {
    dot.classList.toggle('active', !!organ);
    txt.textContent = message;
  }

  // ── 그리기 ──

  function drawPoseLandmarks(lm) {
    const connections = [
      [11,12],[11,13],[13,15],[12,14],[14,16],
      [11,23],[12,24],[23,24],[23,25],[24,26],
      [25,27],[26,28],
    ];
    ctx.strokeStyle = 'rgba(79,142,247,0.3)';
    ctx.lineWidth = 2;
    for (const [a, b] of connections) {
      if ((lm[a].visibility || 0) > 0.3 && (lm[b].visibility || 0) > 0.3) {
        ctx.beginPath();
        ctx.moveTo(lm[a].x * canvas.width, lm[a].y * canvas.height);
        ctx.lineTo(lm[b].x * canvas.width, lm[b].y * canvas.height);
        ctx.stroke();
      }
    }
    const keyPoints = [0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28];
    for (const i of keyPoints) {
      if ((lm[i].visibility || 0) > 0.3) {
        ctx.beginPath();
        ctx.arc(lm[i].x * canvas.width, lm[i].y * canvas.height, 4, 0, 2 * Math.PI);
        ctx.fillStyle = '#4f8ef7';
        ctx.fill();
      }
    }
  }

  function drawHandLandmarks(hand, color) {
    const connections = [
      [0,1],[1,2],[2,3],[3,4],        // 엄지
      [0,5],[5,6],[6,7],[7,8],        // 검지
      [0,9],[9,10],[10,11],[11,12],   // 중지
      [0,13],[13,14],[14,15],[15,16], // 약지
      [0,17],[17,18],[18,19],[19,20], // 소지
      [5,9],[9,13],[13,17],           // 손바닥 연결
    ];
    ctx.strokeStyle = color + '66';
    ctx.lineWidth = 1.5;
    for (const [a, b] of connections) {
      ctx.beginPath();
      ctx.moveTo(hand[a].x * canvas.width, hand[a].y * canvas.height);
      ctx.lineTo(hand[b].x * canvas.width, hand[b].y * canvas.height);
      ctx.stroke();
    }
    // 손가락 끝 강조
    for (const i of [4, 8, 12, 16, 20]) {
      ctx.beginPath();
      ctx.arc(hand[i].x * canvas.width, hand[i].y * canvas.height, 3, 0, 2 * Math.PI);
      ctx.fillStyle = color;
      ctx.fill();
    }
  }

  // ── 유틸 ──

  function loadScript(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement('script');
      s.src = src;
      s.onload = resolve;
      s.onerror = reject;
      document.head.appendChild(s);
    });
  }

  init();
})();
