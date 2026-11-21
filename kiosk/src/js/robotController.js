// =========================================================================
// robotController.js — 로봇 제어 모듈
//
// 서버(kiosk_server)의 파일버스/상태 API로 실제 로봇을 제어한다.
//   goTo(location): Promise  — 목적지로 이동(nav_request 전송)
//   speak(message, id): void  — 안내 음성/문구 (id = 대사 이름, TTS 허용 목록용)
// =========================================================================

export const robotController = {
  /**
   * 목적지로 이동.
   *  /nav 로 nav_request 전송 + done/failed 폴링
   *    → {status:'moving'|'failed'|'timeout'|'blocked', arrived:false}
   *      ('moving' = 워처가 goal 수락(이동 시작). 도착 알림은 다음 사이클)
   * @param {object} location
   * @returns {Promise<object>}
   */
  async goTo(location) {
    console.log(`[robot] goTo(${location.name})`);
    await this._resolveTarget(location); // 실제 목표 좌표 콘솔 출력
    return this._sendNav(location);
  },

  /** 실제 로봇에 이동 요청(nav_request 파일버스) + 상태 폴링 */
  async _sendNav(location) {
    try {
      const res = await fetch('/nav', { method: 'POST', body: JSON.stringify({ id: location.id }) });
      const data = await res.json();
      if (data.blocked) {
        console.warn(`[robot] ${location.name}: 좌표 미설정 → 이동 차단`);
        return { status: 'blocked', arrived: false };
      }
      if (!data.ok || !data.file) return { status: 'failed', arrived: false };
      console.log(`[robot] nav_request 작성: ${data.file} (place_name=${data.name})`);

      // 워처 처리(done=goal 수락=이동 시작)까지 폴링 (~15초)
      for (let i = 0; i < 30; i++) {
        await new Promise((r) => setTimeout(r, 500));
        const s = await fetch(`/nav_status?file=${encodeURIComponent(data.file)}`).then((r) => r.json());
        if (s.status === 'accepted') return { status: 'moving', arrived: false };
        if (s.status === 'failed') return { status: 'failed', arrived: false };
      }
      return { status: 'timeout', arrived: false };
    } catch (err) {
      console.error('[robot] /nav 요청 실패:', err);
      return { status: 'failed', arrived: false };
    }
  },

  /**
   * 목적지 도착까지 대기.
   *  /robot_status 를 폴링한다(= return_home_watcher 가 TF로 판정한 결과).
   *  기존 nav_request_watcher 는 "goal 수락" 시점에만 파일을 옮기고 실제 도착은
   *  알려주지 않으므로, 도착 여부는 이 경로로만 알 수 있다.
   *
   * @param {object} location  목적지
   * @param {number} sentAt    이동 요청을 보낸 시각(Date.now()) — 이전 도착 기록 무시용
   * @param {number} timeoutMs 최대 대기
   * @returns {Promise<boolean>} 도착했으면 true
   */
  async waitArrival(location, sentAt, timeoutMs = 480000, onUpdate = null) {
    const deadline = Date.now() + timeoutMs;
    while (Date.now() < deadline) {
      await new Promise((r) => setTimeout(r, 700));
      let s;
      try {
        s = await fetch('/robot_status').then((r) => r.json());
      } catch (_) {
        continue;                       // 일시적 통신 실패는 재시도
      }
      if (s.state === 'unknown') return false;   // 감시 노드 미실행 → 도착 판정 불가
      // 이번 요청보다 오래된 상태는 무시(이전 안내의 잔여 기록일 수 있음)
      if ((s.updated_at || 0) * 1000 < sentAt - 2000) continue;
      if (onUpdate) onUpdate(s);                 // 진행률 등을 화면에 반영
      if (s.state === 'arrived' && s.place === location.name) return true;
    }
    return false;
  },

  /** 실제 목표 좌표 계산 + 출력 (신뢰 가능: map_labels nav_goal / 폴백: 안내도 추정) */
  async _resolveTarget(location) {
    try {
      const res = await fetch(`/goal?id=${encodeURIComponent(location.id)}`);
      const goal = await res.json();
      if (!goal.error && typeof goal.x === 'number') {
        console.log(
          `[robot] ★실제 목표 좌표(map): x=${goal.x}, y=${goal.y}, ` +
          `yaw=${goal.yaw_deg ?? '?'}° (frame=${goal.frame_id})`
        );
        // TODO(다음 사이클): 여기서 ROS NavigateToPose goal 발행
        return;
      }
      // map_labels에 좌표 없음(예: 약국) → 안내도 추정(비신뢰) 표시
      const { guideRectToMap } = await import('./utils/coordTransform.js');
      const est = guideRectToMap(location.rect);
      console.warn(
        `[robot] ${location.name}: ${goal.error || '좌표 없음'}. ` +
        `안내도 추정(비신뢰, 오차 ~11m): x=${est.x.toFixed(2)}, y=${est.y.toFixed(2)}`
      );
    } catch (err) {
      console.warn('[robot] 목표 좌표 조회 실패:', err);
    }
  },

  /**
   * 안내 음성. 1순위 = 서버측 MeloTTS(로봇 스피커, 자연스러운 한국어).
   * tts_server가 꺼져 있으면 브라우저 내장 TTS로 폴백.
   * @param {string} id  대사 이름(예: 'arrived'). 서버의 TTS 허용 목록(TTS_ONLY_FILE)에 없으면 무음.
   * @returns {Promise<void>} 재생이 끝나면 resolve (호출측이 await 하면 순서 보장)
   */
  /** 음성 언어(ko/en/ja/zh) — 화면 언어 변경 시 app.js가 맞춰 둔다. TTS 서버가 이 언어 모델로 읽는다. */
  lang: 'ko',
  /** 음량 0~100 — 환자 화면 음량 슬라이더가 바꾼다(첫 화면 기본값은 app.js VOL_DEFAULT). TTS 서버가 재생 직전 이 크기로 맞춘다(0=무음). */
  vol: 30,

  /** vol 을 주면 이 대사만 그 크기로(콜보드 호출처럼 환자 음량과 별개인 경우) */
  async speak(message, id = '', lang = null, vol = null) {
    const l = lang || this.lang;
    const v = vol == null ? this.vol : vol;
    console.log(`[robot] speak[${id}](${l}): "${message}"`);
    if (!message) return;
    try {
      const res = await fetch('/speak', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text: message, id, lang: l, vol: v }),
      });
      const data = await res.json();
      if (data && data.muted) return;       // 허용 목록에 없는 대사 → 무음(폴백도 안 함)
      if (data && data.skipped) return;     // 새 대사에 밀려 끊김/건너뜀 → 브라우저 음성으로 대신 읽지 않음
      if (data && data.ok) return;          // MeloTTS로 재생 완료
      console.warn('[robot] /speak 실패 → 브라우저 TTS 폴백:', data && data.error);
    } catch (err) {
      console.warn('[robot] /speak 요청 실패 → 브라우저 TTS 폴백:', err);
    }
    this._browserSpeak(message, l);         // 폴백
  },

  /** 폴백: 브라우저 내장 음성합성 (기계음) */
  _browserSpeak(message, lang = 'ko') {
    try {
      const synth = window.speechSynthesis;
      if (!synth) return;
      const u = new SpeechSynthesisUtterance(message);
      u.lang = ({ ko: 'ko-KR', en: 'en-US', ja: 'ja-JP', zh: 'zh-CN' })[lang] || 'ko-KR';
      u.rate = 1.0;
      synth.cancel();
      synth.speak(u);
    } catch (_) { /* TTS 미지원 환경 무시 */ }
  },

  stopSpeak() {
    try { window.speechSynthesis && window.speechSynthesis.cancel(); } catch (_) {}
    // 보드 스피커(MeloTTS)에서 나오는 키오스크 음성도 멈춤(콜보드 호출 안내는 서버가 건드리지 않음)
    fetch('/speak/stop', { method: 'POST', keepalive: true }).catch(() => {});
  },
};
