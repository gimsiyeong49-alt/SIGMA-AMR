// =========================================================================
// recognizer/real.js — 실제 인식기 (STT + 장소 매칭)
//
// 계약(recognizer/index.js)의 listen()/cancel() 구현.
// 같은 출처의 POST /listen 을 호출한다 (kiosk_server.py 가 처리):
//   서버가 stt_package로 1회 녹음·인식 + 장소 매칭 → {text, locationId, confidence}
//
// ※ 실제 동작은 whisper-server(127.0.0.1:8080) + 마이크가 필요.
//   kiosk_server.py 로 실행해야 한다.
// =========================================================================

export const realRecognizer = {
  _abort: null,

  /** lang = 화면 언어(ko/en/ja/zh). 서버가 그 언어로 음성인식한다(없으면 한국어). */
  async listen(lang = 'ko') {
    this._abort = new AbortController();
    try {
      const res = await fetch('/listen', {
        method: 'POST', signal: this._abort.signal,
        headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ lang }),
      });
      const data = await res.json();

      if (data.error) {
        console.warn('[stt] 인식 오류:', data.error);
        return { text: data.text || '', locationId: null, confidence: 0, error: data.error };
      }
      return {
        text: data.text || '',
        locationId: data.locationId || null,
        confidence: typeof data.confidence === 'number' ? data.confidence : 0,
      };
    } catch (err) {
      if (err.name === 'AbortError') return null;   // 사용자가 취소
      console.error('[stt] /listen 요청 실패:', err);
      return { text: '', locationId: null, confidence: 0 };
    } finally {
      this._abort = null;
    }
  },

  cancel() {
    if (this._abort) {
      this._abort.abort();
      // 브라우저 요청만 끊으면 보드 서버는 말소리를 계속 기다리며 마이크·스피커를 잡고 있다 → 서버 녹음도 취소
      fetch('/listen/cancel', { method: 'POST', keepalive: true }).catch(() => {});
    }
  },
};
