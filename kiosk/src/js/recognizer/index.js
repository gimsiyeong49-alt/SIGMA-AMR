// =========================================================================
// recognizer/index.js — 입력측(음성 인식 → 의도 분석) 계약 + 목/실제 선택
//
// 계약(contract):
//   recognizer.listen(): Promise<Recognition | null>
//     Recognition = {
//       text: string,            // 인식된 발화
//       locationId: string|null, // 매칭된 장소 id (locations.js) 또는 null
//       confidence: number,      // 0~1
//     }
//     · 사용자가 취소하면 null 로 resolve 된다.
//   recognizer.cancel(): void    // 진행 중인 listen()을 취소(null resolve)
//
// 화면 코드(app.js)는 이 계약만 알면 되고, 목/실제 구현을 몰라도 된다.
// =========================================================================

import { realRecognizer } from './real.js';

// 실제 STT(마이크+whisper)만 사용한다.
export const recognizer = realRecognizer;

console.log('[recognizer] 모드 = REAL(stt/llm)');
