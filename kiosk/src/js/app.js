// =========================================================================
// app.js — 병원 안내 로봇 프로토타입 흐름 오케스트레이션
//
// 흐름:
//  1) 음성 화면: 마이크 버튼
//  2) 듣는 중 화면: recognizer.listen()으로 인식 (목=예시질문 / 실제=STT+LLM)
//  3) 결과 화면: 안내도 + 해당 방 반투명 빨강 하이라이트 + 위치 안내 문구
//               + "안내할까요?" 네/아니오
//  4) 이동 중 화면: 로봇 이동(목) → 도착
//  아니오 → 1) 음성 화면 복귀
//
// 입력측은 recognizer 계약(recognizer/index.js)만 사용 → 목/실제를 몰라도 된다.
// 로봇 제어는 robotController 목.
// =========================================================================

import { CONFIG } from './config.js';
import { recognizer } from './recognizer/index.js';
import { LOCATIONS, findLocation } from './data/locations.js';
import { routeTo, pointAt, routeDots } from './data/guideRoute.js';
import { robotController } from './robotController.js';

const CONF_HIGH = 0.85;  // 이 이상이면 바로 안내
const CONF_LOW = 0.5;    // 이 이상~HIGH 미만이면 "맞나요?" 확인
// 도착 문구를 보여주는 시간. return_home_watcher 의 RETURN_DELAY_SEC 과 같은 값이어야
// 화면 복귀와 로봇의 초기 위치 복귀가 동시에 일어난다.
const ARRIVE_HOLD_MS = 5000;
let _arrivalToken = null;   // 마지막 도착 안내 식별(그 사이 새 도착·화면 이동이 있으면 이전 복귀 타이머 무시)
let currentLocation = null;
let arrivalTimer = null;
let movingRoute = null;   // 안내도 위 모식 이동 경로(복도)
let routeDotEls = [];     // 이동 트랙 점 엘리먼트

/** 한글 받침 유무로 주제 조사(은/는) 선택. 화장실→'은', 내과→'는'. */
function josa(word) {
  if (!word) return '는';
  const code = word.charCodeAt(word.length - 1);
  if (code < 0xAC00 || code > 0xD7A3) return '는';  // 한글 음절이 아니면 기본값
  return (code - 0xAC00) % 28 !== 0 ? '은' : '는';   // 받침 있으면 '은'
}

// ---- 다국어(한/영/일/중) -----------------------------------------------------
// 인식된 질문의 언어로 매 요청마다 lang을 정하고, 답변·버튼·안내를 그 언어로 낸다.
// 지도 이미지의 라벨은 한글 그대로 두고(방 안에 안 들어감), 답변 텍스트에만 외국어를 쓴다.
let lang = 'ko';

/**
 * 질문 언어 감지: 한글→ko, 가나(히라가나/가타카나)→ja, (가나 없이)한자→zh, 영문→en, 그 외 ko.
 * 순서 주의: 일본어·중국어는 한자를 공유하므로 가나가 있으면 일본어로 확정하고,
 *            가나 없이 한자만 있으면 중국어로 본다(문장으로 물으면 정확, 한자 단어 하나는 경계).
 */
function detectLang(text) {
  if (/[가-힣]/.test(text)) return 'ko';
  if (/[぀-ヿ]/.test(text)) return 'ja';   // 히라가나·가타카나 → 일본어 확정
  if (/[一-鿿]/.test(text)) return 'zh';   // 가나 없이 한자만 → 중국어
  if (/[A-Za-z]/.test(text)) return 'en';
  return 'ko';
}

/** 현재 lang에 맞는 값 선택(ko/en/ja/zh 순 인자). 값 없으면 한국어로 폴백. */
function tt(ko, en, ja, zh) {
  if (lang === 'zh') return zh != null ? zh : ko;
  if (lang === 'ja') return ja != null ? ja : ko;
  if (lang === 'en') return en != null ? en : ko;
  return ko;
}

/** 현재 언어에 맞는 장소 이름/위치설명(해당 언어 값 없으면 한국어로 폴백). */
function locName(loc) { return tt(loc.name, loc.name_en, loc.name_ja, loc.name_zh); }
function locDesc(loc) { return tt(loc.desc, loc.desc_en, loc.desc_ja, loc.desc_zh); }

// 문구 모음. 각 항목은 현재 lang 기준으로 문자열을 만든다. tt(한국어, 영어, 일본어, 중국어).
const STR = {
  notHeard:     () => tt('잘 못 들었어요. 다시 말씀해 주세요.', "Sorry, I didn't catch that. Please try again.", '聞き取れませんでした。もう一度お願いします。', '没有听清，请再说一次。'),
  listenPrompt: () => tt('말씀해 주세요.', 'Please speak now.', 'お話しください。', '请说话。'),   // 음성 전용(녹음 직전)
  notHeardSpeak: () => tt('인식하지 못했습니다. 다시 말씀해 주세요.', "I couldn't recognize that. Please say it again.", '認識できませんでした。もう一度お話しください。', '未能识别，请再说一次。'),   // 음성 전용
  retryListen:  () => tt('🎤 다시 듣기', '🎤 Try again', '🎤 もう一度', '🎤 再试一次'),
  confirmMsg:   (n) => tt(`'${n}' 말씀하신 게 맞나요?`, `Did you mean ${n}?`, `${n}でよろしいですか？`, `您是说${n}吗？`),
  confirmSpeak: (n) => tt(`${n} 말씀하신 게 맞나요?`, `Did you mean ${n}?`, `${n}でよろしいですか？`, `您是说${n}吗？`),
  yesRight:     () => tt('네, 맞아요', 'Yes', 'はい', '是的'),
  noRetry:      () => tt('아니요, 다시', 'No, retry', 'いいえ、やり直す', '不是，重新'),
  whichMsg:     () => tt('어느 곳을 찾으시나요?', 'Which place are you looking for?', 'どちらをお探しですか？', '您要找哪里？'),
  whichSpeak:   () => tt('아래에서 찾으시는 장소를 선택해 주세요.', 'Please select the place you are looking for below.', 'お探しの場所を下からお選びください。', '请在下方选择您要找的地点。'),
  speakAgain:   () => tt('🎤 다시 말하기', '🎤 Speak again', '🎤 もう一度話す', '🎤 重新说'),
  yesBtn:       () => tt('네', 'Yes', 'はい', '是'),
  noBtn:        () => tt('아니오', 'No', 'いいえ', '否'),
  backHome:     () => tt('처음으로', 'Home', '最初へ', '返回首页'),
  // 위치 안내(표시): 문장 끝 마침표 없음(2026-10-12) — 산부인과는 …에 있습니다 / OB-GYN is … / 産婦人科は…にあります / 妇产科在…
  located:      (loc) => tt(
    `'${locName(loc)}'${josa(locName(loc))} ${locDesc(loc)}에 있습니다`,
    `${locName(loc)} is ${locDesc(loc)}`,
    `${locName(loc)}は${locDesc(loc)}にあります`,
    `${locName(loc)}在${locDesc(loc)}`),
  // 위치 안내(음성): 표시와 같되 한국어는 따옴표 없음, 마침표 유지(끊어 읽기).
  locatedSpeak: (loc) => tt(
    `${locName(loc)}${josa(locName(loc))} ${locDesc(loc)}에 있습니다.`,
    `${locName(loc)} is ${locDesc(loc)}.`,
    `${locName(loc)}は${locDesc(loc)}にあります。`,
    `${locName(loc)}在${locDesc(loc)}。`),
  confirmGuideQ: () => tt('해당 위치로 안내를 시작할까요?', 'Would you like me to start guiding you there?', 'そちらへご案内しましょうか？', '需要我带您过去吗？'),
  notReadyQ:    (loc) => tt(`${locName(loc)}${josa(locName(loc))} 아직 안내 준비 중입니다`, `${locName(loc)} is not available for guidance yet.`, `${locName(loc)}はまだご案内の準備中です。`, `${locName(loc)}暂时还不能提供引导。`),
  guideStartMsg: (loc) => tt(`${locName(loc)}(으)로 이동합니다`, `Guiding you to ${locName(loc)}`, `${locName(loc)}へご案内します`, `正在带您前往${locName(loc)}`),
  guideStartSpeak: (loc) => tt(`${locName(loc)}로 안내를 시작합니다.`, `Starting guidance to ${locName(loc)}.`, `${locName(loc)}へのご案内を開始します。`, `开始引导您前往${locName(loc)}。`),
  movingMsg:    (loc) => tt(`${locName(loc)}(으)로 이동 중입니다`, `Going to ${locName(loc)}`, `${locName(loc)}へ移動中です`, `正在前往${locName(loc)}`),
  remaining:    (m) => tt(`남은 거리 약 ${m.toFixed(1)} m (직선)`, `About ${m.toFixed(1)} m left (straight line)`, `残り約 ${m.toFixed(1)} m（直線距離）`, `剩余约 ${m.toFixed(1)} m（直线距离）`),
  noResponse:   () => tt('요청을 보냈지만 응답이 없습니다', 'Sent the request but got no response.', 'リクエストを送信しましたが応答がありません。', '已发送请求，但没有响应。'),
  reqFailed:    () => tt('이동 요청을 처리하지 못했습니다', "Couldn't process the guidance request.", 'ご案内リクエストを処理できませんでした。', '无法处理引导请求。'),
  arrived:      (loc) => tt(`${locName(loc)}에 도착했습니다`, `Arrived at ${locName(loc)}.`, `${locName(loc)}に到着しました。`, `已到达${locName(loc)}。`),
  arrivedSpeak: (loc) => tt(`${locName(loc)}에 도착했습니다. 안내를 마무리합니다.`, `We have arrived at ${locName(loc)}. This concludes the guidance.`, `${locName(loc)}に到着しました。ご案内を終了します。`, `已到达${locName(loc)}。引导结束。`),   // 음성 전용

  // --- 접수(S-04) 흐름 문구 ---
  stepFirst:     () => tt(['정보 입력', '증상', '완료'], ['Info', 'Symptoms', 'Done'], ['情報入力', '症状', '完了'], ['填写信息', '症状', '完成']),
  stepRevisit:   () => tt(['본인 확인', '확인', '완료'], ['Verify', 'Confirm', 'Done'], ['本人確認', '確認', '完了'], ['身份确认', '确认', '完成']),
  visitQ:        () => tt('이전에 방문하신 적이 있으신가요?', 'Have you visited us before?', '以前にご来院されたことはありますか？', '您以前来过吗？'),
  formTitle:        () => tt('정보를 입력해 주세요', 'Please enter your details', '情報を入力してください', '请输入信息'),   // 초진·재진 공통
  formSpeak:        () => tt('정보를 입력해 주세요.', 'Please enter your details.', '情報を入力してください。', '请输入信息。'),
  needInfo:      () => tt('이름과 주민번호를 모두 입력해 주세요', 'Please enter both name and ID number', '名前と住民番号を入力してください', '请输入姓名和身份证号'),
  errName:       () => tt('이름을 입력해 주세요.', 'Please enter your name.', 'お名前を入力してください。', '请输入姓名。'),
  errRrn:        () => tt('주민등록번호 13자리를 정확히 입력해 주세요. (예: 900101-1234567)', 'Please enter the full 13-digit ID number. (e.g., 900101-1234567)', '住民登録番号13桁を正しく入力してください。（例: 900101-1234567）', '请完整输入13位号码。（例: 900101-1234567）'),
  errRrnRevisit: () => tt('앞 6자리와 뒤 첫자리를 입력해 주세요. (예: 900101-1)', 'Please enter the first 6 digits and the first digit after the dash. (e.g., 900101-1)', '前6桁と後ろの最初の1桁を入力してください。（例: 900101-1）', '请输入前6位和后面的第1位。（例: 900101-1）'),
  errContact:    () => tt('연락처를 정확히 입력해 주세요. (예: 010-1234-5678)', 'Please enter a valid phone number. (e.g., 010-1234-5678)', '電話番号を正しく入力してください。（例: 010-1234-5678）', '请输入正确的电话号码。（例: 010-1234-5678）'),
  errNotRegistered: () => tt('등록된 환자 정보가 없습니다. 처음이시면 뒤로 가서 "초진"으로 접수해 주세요.', 'No patient record found. If this is your first visit, go back and register as a new patient.', '登録された患者情報がありません。初めての方は戻って「初診」で受付してください。', '未找到患者信息。如是初次就诊，请返回选择“初诊”登记。'),
  errNameMismatch: () => tt('등록된 정보와 이름이 일치하지 않습니다. 다시 확인해 주세요.', 'The name does not match our records. Please check again.', '登録情報とお名前が一致しません。ご確認ください。', '姓名与登记信息不符，请重新确认。'),
  errCheckFailed: () => tt('본인 확인 중 오류가 발생했어요. 다시 시도해 주세요.', 'Verification failed. Please try again.', '本人確認でエラーが発生しました。もう一度お試しください。', '本人验证出错，请重试。'),
  needInfoSpeak: () => tt('이름과 주민번호를 입력해 주세요.', 'Please enter your name and ID number.', '名前と住民番号を入力してください。', '请输入姓名和身份证号。'),
  // 문진 화면 음성 상태 표시줄
  ivSpeaking:   () => tt('안내를 들려드리고 있어요', 'Playing the guidance…', 'ご案内を再生しています', '正在播放提示'),
  ivListening:  () => tt('듣고 있어요. 말씀해 주세요', "I'm listening. Please speak.", 'お話しください。聞いています', '正在聆听，请说话'),
  ivProcessing: () => tt('확인하고 있어요', 'Checking…', '確認しています', '正在确认'),
  ivMicError:   () => tt('마이크를 사용할 수 없어요. 직원에게 문의해 주세요', 'The microphone is unavailable. Please ask a staff member.', 'マイクが使えません。スタッフにお声がけください', '麦克风无法使用，请联系工作人员'),
  // 문진 시작 안내(음성 전용 — 화면엔 표시하지 않음)
  symptomQ:      () => tt('어디가 불편하신지 알려주세요.', 'Please tell me where you feel unwell.', 'どこが具合が悪いか教えてください。', '请告诉我您哪里不舒服。'),
  emergencySpeak:() => tt('증상이 급하신 것 같습니다. 응급실이나 가까운 직원에게 바로 도움을 요청하세요.', 'This may be urgent. Please go to the ER or ask nearby staff for help immediately.', '緊急のようです。救急室か近くのスタッフにすぐ助けを求めてください。', '情况可能紧急。请立即前往急诊室或向附近工作人员求助。'),
  emergencyMsg:  () => tt('응급 상황일 수 있어요. 응급실이나 직원에게 바로 도움을 요청하세요.', 'This may be an emergency. Please go to the ER or ask staff for help right away.', '緊急の可能性があります。救急室かスタッフにすぐ助けを求めてください。', '可能是紧急情况。请立即前往急诊室或向工作人员求助。'),
  emgTitle:      () => tt('응급 상황일 수 있습니다', 'This may be an emergency', '緊急の可能性があります', '可能是紧急情况'),
  emgSub:        () => tt('즉시 직원을 호출하거나 119에 연락하세요.', 'Please call staff immediately, or dial 119.', 'すぐにスタッフを呼ぶか、119に連絡してください。', '请立即呼叫工作人员，或拨打119。'),
  emgCall:       () => tt('🔔 직원 호출', '🔔 Call staff', '🔔 スタッフを呼ぶ', '🔔 呼叫工作人员'),
  emgCalled:     () => tt('직원을 호출했습니다. 잠시만 기다려 주세요.', 'Staff have been called. Please wait a moment.', 'スタッフを呼びました。少々お待ちください。', '已呼叫工作人员，请稍候。'),
  symptomSay:    () => tt('증상 말하기', 'Describe symptoms', '症状を話す', '描述症状'),
  triageHardSpeak: () => tt('해당 증상만으로는 특정 진료과를 추천하기 어렵습니다. 원하시는 과를 직접 선택해주세요.', 'It is difficult to recommend a specific department from these symptoms alone. Please choose the department you want.', 'この症状だけでは特定の診療科をおすすめするのが難しいです。ご希望の科を直接お選びください。', '仅凭这些症状难以推荐特定科室，请直接选择您想挂号的科室。'),
  triageHardMsg: () => tt('진료과를 직접 골라 주세요.', 'Please choose a department.', '診療科をお選びください。', '请选择科室。'),
  disclaimer:    () => tt('※ 이 안내는 진단이 아닙니다. 정확한 것은 의료진과 상담하세요.', '※ This is not a diagnosis. Please consult medical staff for accuracy.', '※ これは診断ではありません。正確なことは医療スタッフにご相談ください。', '※ 此提示不是诊断。准确信息请咨询医务人员。'),
  recommendSpeak: (loc) => tt(`추천 진료과는 ${locName(loc)}입니다. 해당 진료과로 접수하시거나 다른 진료과를 선택해주세요.`, `The recommended department is ${locName(loc)}. Please register there or choose another department.`, `おすすめの診療科は${locName(loc)}です。この診療科で受付するか、他の診療科をお選びください。`, `推荐科室是${locName(loc)}。请在该科室挂号或选择其他科室。`),
  recommendMsg:  (loc) => tt(`추천 진료과는 '${locName(loc)}'입니다`, `Recommended department: ${locName(loc)}`, `おすすめの診療科は「${locName(loc)}」です`, `推荐科室：${locName(loc)}`),
  acceptDeptBtn: (loc) => tt(`✅ ${locName(loc)} (추천)`, `✅ ${locName(loc)} (recommended)`, `✅ ${locName(loc)}（おすすめ）`, `✅ ${locName(loc)}（推荐）`),
  queuePos:      (p) => tt(` (순번 ${p}번)`, ` (ticket #${p})`, `（受付番号 ${p}番）`, `（号码 ${p}号）`),
  guideDeptBtn:  (loc) => tt(`📍 ${locName(loc)} 위치 안내`, `📍 Guide me to ${locName(loc)}`, `📍 ${locName(loc)}へ案内`, `📍 带我去${locName(loc)}`),
  // 환자 대기 현황 화면
  waitTitle:     () => tt('접수가 완료되었습니다', 'Registration complete', '受付が完了しました', '挂号完成'),
  // 대기표(병원 번호표 형식): 라벨 + 큰 숫자 / 대기인수
  waitTicketLabel: () => tt('접수번호', 'Ticket No.', '受付番号', '挂号号码'),
  waitCount:     (m) => tt(`대기인수: ${m} 명`, `Waiting: ${m}`, `待ち人数: ${m} 名`, `等候人数：${m} 人`),
  waitDoneSpeak: () => tt('접수가 완료되었습니다.', 'Registration complete.', '受付が完了しました。', '挂号完成。'),
  waitCalled:    (loc) => tt(`🔔 호출되었습니다 — ${locName(loc)}(으)로 오세요`, `🔔 You're called — please go to ${locName(loc)}`, `🔔 お呼びしました — ${locName(loc)}へお越しください`, `🔔 已叫号 — 请前往${locName(loc)}`),
  waitInProgress: (loc) => tt(`🩺 진료 중입니다 — ${locName(loc)}`, `🩺 In consultation — ${locName(loc)}`, `🩺 診療中です — ${locName(loc)}`, `🩺 就诊中 — ${locName(loc)}`),
  waitDone:      () => tt('진료가 완료되었습니다. 이용해 주셔서 감사합니다.', 'Your visit is complete. Thank you.', '診療が完了しました。ありがとうございました。', '就诊完成，谢谢您。'),
  loadingMsg:    () => tt('확인 중입니다…', 'Checking…', '確認中です…', '确认中…'),
  idlePrompt:    () => tt('계속 이용하시겠어요?', 'Are you still there?', 'まだご利用中ですか？', '还在使用吗？'),
  idleContinue:  () => tt('계속하기', 'Continue', '続ける', '继续'),
};

// 정적 화면 문구(홈/폼/버튼). data-i18n / data-i18n-ph 속성으로 매칭. [ko, en, ja, zh]
const LANG_IDX = { ko: 0, en: 1, ja: 2, zh: 3 };
const LABELS = {
  'interview.title': ['증상을 설명해주세요', 'Please describe your symptoms', '症状を説明してください', '请描述您的症状'],
  'vol.title':     ['소리 크기', 'Volume', '音量', '音量'],
  'home.title':    ['무엇을 도와드릴까요?', 'How can I help you?', '何かお手伝いしましょうか？', '有什么可以帮您？'],
  'home.intake':   ['접수 안내', 'Reception', '受付', '挂号'],
  'home.location': ['위치 안내', 'Find a place', '場所案内', '位置引导'],
  'mic.hint':      ['버튼을 누르고 가고 싶은 곳을 말씀하세요', 'Press the button and say where you want to go', 'ボタンを押して行き先をお話しください', '按下按钮，说出您要去的地方'],
  'listening.title': ['듣고 있어요…', 'Listening…', '聞いています…', '正在聆听…'],
  'btn.back':      ['뒤로', 'Back', '戻る', '返回'],
  'btn.cancel':    ['취소', 'Cancel', 'キャンセル', '取消'],
  'btn.home':      ['처음으로', 'Home', '最初へ', '返回首页'],
  'btn.confirm':   ['확인', 'Confirm', '確認', '确认'],
  'intake.submit': ['입력', 'Submit', '入力', '提交'],
  'ph.name':       ['이름', 'Name', 'お名前（ローマ字で入力）', '姓名（请用拼音/字母输入）'],
  'ph.rrn':        ['주민등록번호 (예: 900101-1234567)', 'ID number (e.g., 900101-1234567)', '住民登録番号（例: 900101-1234567）', '身份证号 (例: 900101-1234567)'],
  'ph.rrnRevisit': ['앞 6자리 + 뒤 1자리 (예: 900101-1)', 'First 6 + 1 digit (e.g., 900101-1)', '前6桁＋1桁（例: 900101-1）', '前6位 + 1位 (例: 900101-1)'],
  'ph.contact':    ['연락처 (예: 010-1234-5678)', 'Phone (e.g., 010-1234-5678)', '電話番号（例: 010-1234-5678）', '电话 (例: 010-1234-5678)'],
  'ph.symptom':    ['예) 머리가 아프고 열이 나요', 'e.g., I have a headache and a fever', '例) 頭が痛くて熱があります', '例) 头疼还发烧'],
};

function label(key) {
  const a = LABELS[key];
  return a ? (a[LANG_IDX[lang] || 0]) : key;
}

/** data-i18n / data-i18n-ph 속성이 붙은 정적 요소를 현재 언어로 갱신 + 국기 활성표시. */
function applyLang() {
  document.querySelectorAll('[data-i18n]').forEach((el) => { el.textContent = label(el.dataset.i18n); });
  document.querySelectorAll('[data-i18n-ph]').forEach((el) => { el.placeholder = label(el.dataset.i18nPh); });
  document.querySelectorAll('.lang-flag').forEach((f) => f.classList.toggle('active', f.dataset.lang === lang));
  const vt = document.getElementById('vol-toggle');
  if (vt) { vt.title = label('vol.title'); vt.setAttribute('aria-label', label('vol.title')); }
}

// ── 언어를 바꿀 때 '지금 화면'의 글자 다시 그리기 ── 화면마다 글자만 채우는 함수를 등록해 두고(음성·상태 변화 없음)
//  setLang 이 현재 화면 것을 다시 실행. data-i18n 고정 문구는 applyLang 이, JS로 채운 문구는 이것이 담당.
//  문진 대화 말풍선(이미 오간 AI 질문·환자 답)은 대화 기록이라 그대로 둔다.
const _relabel = {};
function onRelabel(screenId, fn) { _relabel[screenId] = fn; }
/** 문자열 또는 문자열을 만드는 함수 → 현재 언어 문자열 */
const txt = (x) => (typeof x === 'function' ? x() : (x || ''));

/** 국기 클릭 → 언어 변경(저장). */
function setLang(l) {
  if (!LANG_IDX.hasOwnProperty(l)) return;
  const changed = lang !== l;
  lang = l;
  robotController.lang = l;          // 로봇 음성도 화면 언어로
  try { localStorage.setItem('uiLang', l); } catch (_) { /* ignore */ }
  applyLang();
  const cur = document.querySelector('.screen.active');
  if (changed && cur && _relabel[cur.id]) _relabel[cur.id]();   // 지금 화면의 JS 문구도 새 언어로
  if (changed && l !== 'ko') prewarmSpeech(l);   // 그 언어 고정 안내를 미리 합성(한국어는 시작 때 이미)
}

// ── 음량 조절(환자 화면 공통) ── 0~100 드래그. 0 = 무음. 첫 화면으로 돌아가면 기본값(VOL_DEFAULT)으로.
//  2026-11-13: 기본 60 → 30(사용자 요청). 60 = TTS 서버 기준 크기, 30 = 그보다 약 6 dB 작게.
//  대기실 콜보드 호출은 환자 음량과 별개로 CALLBOARD_VOL(예전 기본 60) 고정.
const VOL_DEFAULT = 30;
const CALLBOARD_VOL = 60;
const STAFF_SCREENS = ['admin-gate', 'admin-screen', 'doctor-screen', 'callboard-screen'];

function setVolume(v) {
  v = Math.round(Math.min(100, Math.max(0, Number(v) || 0)));
  robotController.vol = v;
  const sl = document.getElementById('vol-slider');
  sl.style.setProperty('--v', `${v}%`);                         // 채운 막대 높이·손잡이 위치
  sl.setAttribute('aria-valuenow', String(v));
  document.getElementById('vol-val').textContent = String(v);
  // 아이콘: 0 = 스피커+✕, 1~33 = 음파 1줄, 34~66 = 2줄, 67~100 = 3줄
  const waves = v === 0 ? 0 : v <= 33 ? 1 : v <= 66 ? 2 : 3;
  [1, 2, 3].forEach((n) => { document.querySelector(`.vol-w${n}`).toggleAttribute('hidden', n > waves); });
  document.querySelector('.vol-x').toggleAttribute('hidden', waves !== 0);
  // 보이는 그림(스피커+음파/✕, 선 두께 포함)의 가로 중심이 버튼 중앙(x=15)에 오도록 이동
  document.getElementById('vol-g').setAttribute('transform', `translate(${({ 0: 0.0, 1: 3.2, 2: 1.4, 3: -0.4 })[waves]} 0)`);
}

function closeVolPanel() {
  document.getElementById('vol-ctrl').classList.remove('open');
  document.getElementById('vol-toggle').setAttribute('aria-expanded', 'false');
}

function initVolume() {
  const ctrl = document.getElementById('vol-ctrl');
  const toggle = document.getElementById('vol-toggle');
  const panel = document.getElementById('vol-panel');
  const slider = document.getElementById('vol-slider');
  toggle.addEventListener('click', (e) => {        // 국기와 같은 방식: 누르면 아래로 펼침, 다시 누르면 접힘
    e.stopPropagation();
    document.querySelector('.lang-bar').classList.remove('open');   // 국기 펼침과 동시에 열리지 않게
    const open = !ctrl.classList.contains('open');
    ctrl.classList.toggle('open', open);
    toggle.setAttribute('aria-expanded', String(open));
  });
  panel.addEventListener('click', (e) => e.stopPropagation());
  // 세로 드래그: 막대 위쪽 = 100, 아래쪽 = 0. 손가락이 막대 밖으로 나가도 계속 따라감(pointer capture)
  const track = slider.querySelector('.vol-track');
  const fromY = (y) => {
    const r = track.getBoundingClientRect();
    return ((r.bottom - y) / r.height) * 100;
  };
  slider.addEventListener('pointerdown', (e) => {
    e.preventDefault();
    slider.setPointerCapture(e.pointerId);
    setVolume(fromY(e.clientY));
  });
  slider.addEventListener('pointermove', (e) => {
    if (slider.hasPointerCapture(e.pointerId)) setVolume(fromY(e.clientY));
  });
  slider.addEventListener('keydown', (e) => {      // 키보드: ↑↓ 5씩, Home/End 끝
    const k = { ArrowUp: 5, ArrowRight: 5, ArrowDown: -5, ArrowLeft: -5 }[e.key];
    if (k) { e.preventDefault(); setVolume(robotController.vol + k); }
    else if (e.key === 'Home') setVolume(0);
    else if (e.key === 'End') setVolume(100);
  });
  document.addEventListener('click', closeVolPanel);       // 바깥을 누르면 접힘
  setVolume(VOL_DEFAULT);
}

function showScreen(id) {
  document.documentElement.classList.remove('staff-boot');   // 의료진 주소 첫 화면 숨김 해제(index.html head)
  document.getElementById('top-tools').hidden = STAFF_SCREENS.includes(id);   // 음량·국기는 환자 화면에만
  document.querySelectorAll('.screen').forEach((el) => {
    el.classList.toggle('active', el.id === id);
  });
  if (typeof resetIdle === 'function') resetIdle();   // 화면 전환마다 유휴 타이머 재무장
}

// ---- 1 → 2: 음성 인식 시작 ----
async function startListening() {
  showScreen('listening-screen');
  await robotController.speak(STR.listenPrompt(), 'listenPrompt');   // 안내가 끝난 뒤 녹음(자기 목소리 인식 방지)
  if (!document.getElementById('listening-screen').classList.contains('active')) return;   // 안내 중 화면을 떠났으면 녹음 안 함

  const result = await recognizer.listen(lang); // 화면 언어로 음성인식 → {text, locationId, confidence} | null
  if (result === null) return;              // 사용자가 취소
  console.log('[app] 인식 결과:', result);
  handleRecognition(result);
}

// ---- 2 → 결과 or 재질문: 인식 결과 분기 ----
function handleRecognition(result) {
  const text = (result.text || '').trim();
  const conf = result.confidence || 0;
  const loc = result.locationId ? findLocation(result.locationId) : null;
  // 언어는 홈의 국기 버튼 선택(lang)을 따른다. (자동 감지 안 함)

  // 수속 의도("접수/수속/초진/재진/처음 왔어요") → S-04 흐름으로 진입
  if (isIntakeIntent(text)) { startIntake(); return; }

  // C. 인식 실패 / 무음 → 다시 듣기
  if (!text) {
    robotController.speak(STR.notHeardSpeak(), 'notHeard');
    showRetry(() => STR.notHeard(), [
      { label: () => STR.retryListen(), action: startListening },
    ]);
    return;
  }

  // 확정 → 바로 안내
  if (loc && conf >= CONF_HIGH) {
    showResult(loc);
    return;
  }

  // B. 저신뢰 → "맞나요?" 확인
  if (loc && conf >= CONF_LOW) {
    robotController.speak(STR.confirmSpeak(locName(loc)), 'confirmPlace');
    showRetry(() => STR.confirmMsg(locName(loc)), [
      { label: () => STR.yesRight(), action: () => showResult(loc) },
      { label: () => STR.noRetry(), action: startListening },
    ]);
    return;
  }

  // A. 소리는 들렸으나 장소 못 찾음 → 장소 버튼으로 고르게
  robotController.speak(STR.whichSpeak(), 'whichPlace');
  showRetry(() => STR.whichMsg(), [
    ...LOCATIONS.map((l) => ({ label: () => locName(l), action: () => showResult(l) })),
    { label: () => STR.speakAgain(), action: startListening },
  ]);
}

/** 재질문 화면: 메시지 + 선택 버튼들(+ 선택적 하단 안내문). back=있으면 "뒤로" 버튼 표시(누르면 실행). */
function showRetry(message, choices, note, stepIdx, recap, back) {
  // 접수 흐름에서 호출 시(stepIdx 지정) 상단 스텝 표시 → "지금 무슨 단계"를 이어줌.
  // 위치 안내 흐름(인식실패·재질문 등)은 stepIdx 없음 → 스텝 비움.
  const steps = document.getElementById('retry-steps');
  if (steps) { if (stepIdx == null) steps.innerHTML = ''; else setSteps('retry-steps', stepIdx); }
  const rc = document.getElementById('retry-recap');
  if (rc) rc.textContent = recap || '';                             // 문진 리캡(비면 CSS로 숨김)
  // message·note·choice.label 은 문자열 또는 함수(함수면 언어를 바꿀 때 다시 계산해 새 언어로 표시)
  document.getElementById('retry-msg').textContent = txt(message);
  document.getElementById('retry-note').textContent = txt(note);   // 비면 CSS로 숨김
  const box = document.getElementById('retry-choices');
  box.innerHTML = '';
  box.classList.remove('equal');                                    // 같은 크기 버튼은 호출측이 필요할 때만 켬
  const backBtn = document.getElementById('retry-back');
  backBtn.hidden = typeof back !== 'function';
  backBtn.onclick = back || null;                                   // 매번 덮어써서 이전 화면의 동작이 남지 않게
  choices.forEach((c) => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'chip' + (c.primary ? ' primary' : '');
    btn.textContent = txt(c.label);
    btn.addEventListener('click', c.action);
    box.appendChild(btn);
  });
  onRelabel('retry-screen', () => {
    if (stepIdx != null) setSteps('retry-steps', stepIdx);
    document.getElementById('retry-msg').textContent = txt(message);
    document.getElementById('retry-note').textContent = txt(note);
    box.querySelectorAll('button').forEach((b, i) => { if (choices[i]) b.textContent = txt(choices[i].label); });
  });
  showScreen('retry-screen');
}

async function showResult(loc) {
  currentLocation = loc;

  const hl = document.getElementById('hl');
  hl.style.left = `${loc.rect.x}%`;
  hl.style.top = `${loc.rect.y}%`;
  hl.style.width = `${loc.rect.w}%`;
  hl.style.height = `${loc.rect.h}%`;
  hl.classList.add('on');

  document.getElementById('result-banner').textContent = STR.located(loc);
  onRelabel('result-screen', () => { document.getElementById('result-banner').textContent = STR.located(loc); });
  showScreen('result-screen');

  // 실제 목표 좌표 유무 확인 → 없으면(약국 등) 이동 요청 자체를 차단
  const yesBtn = document.getElementById('yes-btn');
  const noBtn = document.getElementById('no-btn');
  const confirmQ = document.getElementById('confirm-q');
  yesBtn.textContent = STR.yesBtn();
  noBtn.textContent = STR.noBtn();
  let hasGoal = false;
  try {
    const g = await fetch(`/goal?id=${encodeURIComponent(loc.id)}`).then((r) => r.json());
    hasGoal = !g.error && typeof g.x === 'number';
  } catch (_) { hasGoal = false; }

  if (hasGoal) {
    yesBtn.disabled = false;
    confirmQ.textContent = STR.confirmGuideQ();
    robotController.speak(`${STR.locatedSpeak(loc)} ${STR.confirmGuideQ()}`, 'locatedConfirm');
  } else {
    yesBtn.disabled = true;                       // 좌표 미설정 → 이동 버튼 비활성화
    confirmQ.textContent = STR.notReadyQ(loc);
    // 좌표 없는 장소: 음성 없음(2026-10-13). 화면 안내는 그대로
  }
}

// ---- 3 → 4: 예 → 이동 ----

/** 이동 화면의 안내도를 목적지 기준으로 준비하고 로봇을 출발 지점에 놓는다. */
function setupMovingMap(loc) {
  const hl = document.getElementById('move-hl');
  hl.style.left = `${loc.rect.x}%`;
  hl.style.top = `${loc.rect.y}%`;
  hl.style.width = `${loc.rect.w}%`;
  hl.style.height = `${loc.rect.h}%`;
  hl.classList.add('on');
  document.getElementById('move-floor-badge').textContent = CONFIG.floor;

  movingRoute = routeTo(loc);
  renderRouteDots();                // 복도 위 이동 트랙(점들) 그리기
  // 출발 지점에는 애니메이션 없이 즉시 배치(이전 안내의 위치에서 미끄러져 오지 않도록)
  const marker = document.getElementById('robot-marker');
  marker.style.transition = 'none';
  placeRobot(0);
  void marker.offsetWidth;          // 스타일 반영 강제 후 transition 복구
  marker.style.transition = '';
}

/** 복도 위에 이동 트랙(점들)을 그린다. 로봇은 이 점들을 지나며 진행한다. */
function renderRouteDots() {
  const wrap = document.getElementById('move-map-wrap');
  wrap.querySelectorAll('.route-dot').forEach((d) => d.remove());
  routeDotEls = [];
  routeDots(movingRoute).forEach((pt) => {
    const dot = document.createElement('div');
    dot.className = 'route-dot';
    dot.style.left = `${pt.x}%`;
    dot.style.top = `${pt.y}%`;
    wrap.appendChild(dot);
    routeDotEls.push({ el: dot, t: null });
  });
  // 각 점의 진행률 위치(t)를 미리 계산 → 지나간 점 강조에 사용
  const n = routeDotEls.length - 1;
  routeDotEls.forEach((d, i) => { d.t = n === 0 ? 1 : i / n; });
}

/** 진행률(0~1) 위치로 로봇 머리를 옮기고, 지나온 점을 강조한다. */
function placeRobot(progress) {
  if (!movingRoute) return;
  const p = pointAt(movingRoute, progress);
  const marker = document.getElementById('robot-marker');
  marker.style.left = `${p.x}%`;
  marker.style.top = `${p.y}%`;
  // 로봇이 지나온 점은 '지남' 표시(색 진하게)
  routeDotEls.forEach((d) => {
    d.el.classList.toggle('passed', d.t <= progress + 1e-6);
  });
}

async function confirmYes() {
  if (!currentLocation) return;
  const loc = currentLocation;
  const msg = document.getElementById('moving-msg');
  const sub = document.getElementById('moving-sub');
  const doneBtn = document.getElementById('done-btn');

  // 안내 문구는 '만드는 함수'로 기억해 두고 언어를 바꾸면 다시 계산(남은 거리는 폴링이 갱신)
  let msgFn = () => STR.guideStartMsg(loc);
  const setMsg = (fn) => { msgFn = fn; msg.textContent = fn(); };
  onRelabel('moving-screen', () => { msg.textContent = msgFn(); doneBtn.textContent = STR.backHome(); });

  setupMovingMap(loc);
  showScreen('moving-screen');
  setMsg(msgFn);
  sub.textContent = '';
  doneBtn.textContent = STR.backHome();
  doneBtn.classList.add('hidden');
  robotController.speak(STR.guideStartSpeak(loc), 'guideStart');

  const sentAt = Date.now();
  const r = await robotController.goTo(loc);

  let arrived = r.arrived;
  if (!arrived && r.status === 'moving') {
    setMsg(() => STR.movingMsg(loc));
    // 실제 남은 거리 기반 진행률로 안내도 위 로봇을 움직인다(2Hz 폴링).
    arrived = await robotController.waitArrival(loc, sentAt, 480000, (s) => {
      if (typeof s.progress === 'number') placeRobot(s.progress);
      if (typeof s.remaining_m === 'number') {
        sub.textContent = STR.remaining(s.remaining_m);
      }
    });
  }

  if (arrived) {
    placeRobot(1);                  // 도착 → 방 위에 정확히
    showArrival(loc);
    return;                         // 5초 뒤 자동으로 음성 화면 복귀
  }

  if (r.status === 'moving') {              // 이동은 시작했으나 도착 확인 실패
    setMsg(() => STR.movingMsg(loc));
  } else if (r.status === 'timeout') {      // Nav2 미기동 등
    setMsg(() => STR.noResponse());
    sub.textContent = '';
    robotController.speak(STR.noResponse(), 'noResponse');
  } else {                                  // failed / blocked
    setMsg(() => STR.reqFailed());
    sub.textContent = '';
    robotController.speak(STR.reqFailed(), 'reqFailed');
  }
  doneBtn.classList.remove('hidden');
}

/**
 * 도착 화면. "XX에 도착했습니다"를 띄우고 ARRIVE_HOLD_MS 뒤 음성 화면으로 복귀한다.
 * 같은 시각에 로봇도 초기 위치로 출발한다
 * (return_home_watcher 의 RETURN_DELAY_SEC 을 같은 값으로 맞춰둠).
 */
function showArrival(loc) {
  document.getElementById('moving-msg').textContent = STR.arrived(loc);
  document.getElementById('moving-sub').textContent = '';
  onRelabel('moving-screen', () => { document.getElementById('moving-msg').textContent = STR.arrived(loc); });
  document.getElementById('done-btn').classList.add('hidden');
  // 도착 안내가 '끝난 뒤' ARRIVE_HOLD_MS 를 센다(먼저 세면 합성이 느릴 때 처음 화면 복귀가 안내 음성을 끊음).
  //  그 사이 다른 화면으로 갔으면(사용자가 먼저 조작) 복귀 타이머를 걸지 않는다.
  clearTimeout(arrivalTimer);
  arrivalTimer = null;
  const token = {};
  _arrivalToken = token;
  robotController.speak(STR.arrivedSpeak(loc), 'arrived').finally(() => {
    if (_arrivalToken !== token) return;
    if (!document.getElementById('moving-screen').classList.contains('active')) return;
    arrivalTimer = setTimeout(resetToVoice, ARRIVE_HOLD_MS);
  });
}

// ---- 3 → 1: 아니오 → 음성 화면 복귀 ----
function resetToVoice() {
  clearTimeout(arrivalTimer);   // 도착 후 자동복귀 대기 중 사용자가 먼저 조작한 경우
  arrivalTimer = null;
  currentLocation = null;
  currentPatient = null;
  clearInterval(_waitPoll); _waitPoll = null; _waitCtx = null;   // 대기 화면 폴링 정지
  document.getElementById('hl').classList.remove('on');
  document.getElementById('move-hl').classList.remove('on');
  recognizer.cancel();
  robotController.stopSpeak();
  hideIdle();                   // 무조작 리셋 오버레이·타이머 정리
  setVolume(VOL_DEFAULT);       // 다음 환자는 기본 음량으로
  closeVolPanel();
  showHomeMenu();               // 홈은 메뉴(위치/접수)부터 다시 시작
  showScreen('voice-screen');
}

// ---- 무조작 자동 리셋 (B-6): 아래 제외 화면 외에서 IDLE_MS 무조작 시 "계속?" → 홈 ----
let IDLE_MS = 60000;      // /config 로 덮어씀(환경변수 KIOSK_IDLE_SEC)
let _idleTimer = null;
let _idleWarn = null;
// 무조작 리셋 제외 화면: 홈·관리자 + 오래 켜 두는 화면
//  (대기=순번 보며 기다림, 이동 중=로봇 따라 걷는 중, 의사·콜보드=상시 표시)
const IDLE_EXEMPT = ['voice-screen', 'admin-screen', 'admin-gate',
  'wait-screen', 'moving-screen', 'doctor-screen', 'callboard-screen'];

// 무조작 자동 리셋 기능 전체 끔(사용자 요청 2026-10-02): "계속?" 창·idlePrompt TTS·홈 복귀 모두 없음.
//  다시 켜려면 false 로. (제외 화면 목록 IDLE_EXEMPT 는 켤 때를 위해 보존)
const IDLE_DISABLED = true;

/** 조작 시마다 유휴 타이머 리셋. 제외 화면에선 동작 안 함(떠 있던 "계속?" 창도 닫음). */
function resetIdle() {
  clearTimeout(_idleTimer);
  if (IDLE_DISABLED) { hideIdle(); return; }
  const active = document.querySelector('.screen.active');
  const id = active ? active.id : '';
  if (IDLE_EXEMPT.includes(id)) { hideIdle(); return; }
  if (!document.getElementById('idle-modal').hidden) return;   // 프롬프트 떠 있으면 그쪽 타이머가 관리
  _idleTimer = setTimeout(showIdlePrompt, IDLE_MS);
}

/** "계속 이용하시겠어요?" 오버레이. 15초 더 무응답이면 홈으로 초기화. */
function showIdlePrompt() {
  document.getElementById('idle-msg').textContent = STR.idlePrompt();
  document.getElementById('idle-continue').textContent = STR.idleContinue();
  document.getElementById('idle-modal').hidden = false;
  robotController.speak(STR.idlePrompt(), 'idlePrompt');
  clearTimeout(_idleWarn);
  _idleWarn = setTimeout(() => { hideIdle(); resetToVoice(); }, 15000);
}

function hideIdle() {
  clearTimeout(_idleWarn); _idleWarn = null;
  clearTimeout(_idleTimer); _idleTimer = null;
  const m = document.getElementById('idle-modal');
  if (m) m.hidden = true;
}

function idleContinue() {
  hideIdle();
  resetIdle();   // 다시 카운트 시작
}

// ---- 로딩(확인 중) 오버레이 (B-8) ----
function showLoading() {
  document.getElementById('loading-msg').textContent = STR.loadingMsg();
  document.getElementById('loading-modal').hidden = false;
}
function hideLoading() {
  document.getElementById('loading-modal').hidden = true;
}

/**
 * 개발용 타자 입력: 마이크 없이 텍스트로 질문 → 실제 매칭(/listen) → 화면에 글로 답변.
 *  · URL 에 ?dev=1 이 있을 때만 활성 (start_ui.sh 안내). 프로덕션엔 영향 없음.
 *  · 실제 음성 인식과 같은 파이프라인(handleRecognition)을 그대로 탄다.
 */
function initDevInput() {
  if (!new URLSearchParams(location.search).has('dev')) return;
  const form = document.getElementById('dev-input');
  const input = document.getElementById('dev-text');
  if (!form || !input) return;
  form.hidden = false;
  form.addEventListener('submit', async (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text) return;
    input.blur();
    let result;
    try {
      // /listen 에 텍스트만 보내면 서버가 매칭만 수행(마이크 녹음 없이) → {text, locationId, confidence}
      const res = await fetch('/listen', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      });
      result = await res.json();
    } catch (_) {
      result = { text, locationId: null, confidence: 0 };
    }
    console.log('[dev] 타자 질문:', text, '→', result);
    handleRecognition(result);   // 실제 인식과 동일 흐름
  });
}

// =========================================================================
// S-04 접수: 초진/재진 → 환자 정보 등록 → (초진)증상 음성→진료과 / (재진)예약이면
// 이전 진료과 → 해당 진료과 대기명단 등록 → 위치 안내(S-01) 제안.
//   환자 데이터셋·대기명단은 서버(kiosk_server.py)가 파일로 저장한다.
// =========================================================================
let currentPatient = null;   // {name, rrn, visitType, lastDept, found}

/** 발화가 수속 의도인지(접수/수속/초진/재진/처음 왔어요 등). */
function isIntakeIntent(text) {
  return /(접수|수속|초진|재진|처음\s*왔|처음\s*이|등록하)/.test(text);
}

// 응급 키워드(KTAS 1~2, 4개국어). 규칙 기반으로 LLM 트리아지보다 먼저 검사한다.
const EMERGENCY_KW = [
  // 한국어
  '의식이 없', '의식 잃', '의식을 잃', '쓰러졌', '쓰러져', '기절', '정신을 잃', '반응이 없',
  '숨을 못 쉬', '숨이 안', '숨쉬기 힘', '호흡곤란', '숨이 막',
  '가슴이 심하게', '가슴이 찢', '가슴이 조여', '심한 흉통', '가슴을 쥐어짜',
  '갑자기 머리가 심하게', '머리가 깨질', '심한 두통', '머리가 터질',
  '배가 찢어질', '배가 너무 아파', '심한 복통', '참을 수 없는 복통',
  '피를 토', '토혈', '피가 많이', '대량 출혈', '출혈이 심', '하혈',
  '마비', '한쪽 힘이 빠', '반신', '얼굴이 돌아가', '말이 어눌',
  '경련', '발작', '뇌전증', '심장이 멈', '심정지', '맥박이 없', '심장마비',
  '응급', '위독', '119',
  // English
  'unconscious', 'passed out', 'collapsed', 'fainted', 'unresponsive',
  "can't breathe", 'cannot breathe', 'can not breathe', 'difficulty breathing', 'short of breath', 'choking',
  'severe chest pain', 'crushing chest pain', 'chest tightness', 'heart attack',
  'sudden severe headache', 'worst headache', 'thunderclap headache',
  'severe abdominal pain', 'unbearable stomach pain',
  'vomiting blood', 'coughing up blood', 'heavy bleeding',
  'paralysis', 'one side weak', 'face drooping', 'slurred speech', 'stroke',
  'seizure', 'convulsion', 'convulsing', 'cardiac arrest', 'no pulse', 'heart stopped',
  'emergency', 'dying', 'call 911',
  // 日本語
  '意識がない', '意識を失', '倒れた', '気を失', '反応がない',
  '息ができない', '息苦しい', '呼吸困難', '息が止ま',
  '激しい胸の痛み', '胸が締め付け', '心臓発作',
  '突然の激しい頭痛', '割れるような頭痛', '激しい頭痛',
  '激しい腹痛', '耐えられない腹痛',
  '血を吐', '吐血', '大量出血', '出血がひどい', '血が止まらない',
  '麻痺', '片側が動かない', '半身', 'ろれつが回らない',
  'けいれん', '発作', 'ひきつけ', '心停止', '心臓が止ま', '脈がない',
  '救急', '緊急', '死にそう',
  // 中文
  '昏迷', '失去意识', '晕倒', '昏倒', '不省人事',
  '无法呼吸', '呼吸困难', '喘不过气', '憋气',
  '剧烈胸痛', '胸口剧痛', '胸闷得厉害', '心脏病发作',
  '突然剧烈头痛', '头痛欲裂', '剧烈头痛',
  '剧烈腹痛', '肚子剧痛', '腹部剧烈疼痛',
  '吐血', '咯血', '大量出血', '出血不止',
  '瘫痪', '半身不遂', '一侧无力', '嘴歪', '说话不清', '中风',
  '抽搐', '惊厥', '痉挛', '抽风', '心跳停止', '心脏骤停', '没有脉搏',
  '急救', '危急', '快不行了',
];
const EMERGENCY_RE = new RegExp(EMERGENCY_KW.map((s) => s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'i');

/** 응급 의심 표현(4개국어 규칙). LLM 트리아지보다 먼저 검사. */
function isEmergency(text) {
  return false;   // 응급 기능 제거 — 트리거 안 함(키워드/화면 코드는 보존, 미사용)
}

/** 응급 분기 화면(트리아지·대기등록 안 함). 크게·다국어 + 직원 호출. */
function showEmergency() {
  document.getElementById('emg-title').textContent = STR.emgTitle();
  document.getElementById('emg-sub').textContent = STR.emgSub();
  const call = document.getElementById('emg-call');
  call.textContent = STR.emgCall();
  call.disabled = false;
  onRelabel('emergency-screen', () => {
    document.getElementById('emg-title').textContent = STR.emgTitle();
    document.getElementById('emg-sub').textContent = STR.emgSub();
    if (!call.disabled) call.textContent = STR.emgCall();
  });
  showScreen('emergency-screen');
  robotController.speak(STR.emergencySpeak(), 'emergency');
}

/** 직원 호출: 소리(비프) + 화면 안내. 실제 호출 신호 연동 자리(현재는 데모용 알림). */
function emgCallStaff() {
  const call = document.getElementById('emg-call');
  call.disabled = true;
  document.getElementById('emg-sub').textContent = STR.emgCalled();
  emgBeep();
  robotController.speak(STR.emgCalled(), 'emergencyCalled');
}

/** 데모용 경보음(Web Audio, 버튼 클릭 제스처로 재생 허용). */
function emgBeep() {
  try {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return;
    const ctx = new Ctx();
    const o = ctx.createOscillator();
    const g = ctx.createGain();
    o.type = 'square'; o.connect(g); g.connect(ctx.destination);
    g.gain.value = 0.12;
    o.start();
    let n = 0;
    const iv = setInterval(() => {
      o.frequency.value = (n % 2 === 0) ? 988 : 740;   // 삐뽀삐뽀
      n += 1;
      if (n > 7) { clearInterval(iv); o.stop(); ctx.close(); }
    }, 260);
  } catch (_) { /* 오디오 불가 무시 */ }
}

/** 접수 흐름 스텝 인디케이터 렌더. activeIdx: 0정보/본인 · 1증상/확인 · 2완료. */
function setSteps(hostId, activeIdx, forceVt) {
  const host = document.getElementById(hostId);
  if (!host) return;
  const vt = forceVt || (currentPatient && currentPatient.visitType) || 'first';   // forceVt: 화면별로 단계 이름 고정
  const labels = vt === 'revisit' ? STR.stepRevisit() : STR.stepFirst();
  host.innerHTML = '';
  labels.forEach((lab, i) => {
    if (i > 0) {
      const sep = document.createElement('div');
      sep.className = 'step-sep' + (i <= activeIdx ? ' done' : '');
      host.appendChild(sep);
    }
    const step = document.createElement('div');
    step.className = 'step' + (i === activeIdx ? ' active' : (i < activeIdx ? ' done' : ''));
    const dot = document.createElement('div');
    dot.className = 'step-dot';
    dot.textContent = i < activeIdx ? '✓' : String(i + 1);
    const t = document.createElement('span');
    t.textContent = lab;
    step.appendChild(dot); step.appendChild(t);
    host.appendChild(step);
  });
}

/** 접수 시작: 초진/재진 선택. */
function startIntake() {
  clearTimeout(arrivalTimer); arrivalTimer = null;
  currentPatient = null;
  robotController.speak(STR.visitQ(), 'visitQ');
  showRetry(() => STR.visitQ(), [
    // "이전에 방문?" → 네 = 재진, 아니오 = 초진
    { label: () => STR.yesBtn(), action: () => startPatientForm('revisit') },
    { label: () => STR.noBtn(), action: () => startPatientForm('first') },
  ]);   // "처음으로"는 화면 하단 고정 버튼(retry-screen)이 있어 목록엔 넣지 않음(중복 방지)
  document.getElementById('retry-choices').classList.add('equal');   // 네/아니오 같은 크기(언어 무관)
}

// ── 주민번호 세그먼트 입력(숫자당 한 칸) ─────────────────────────────────
// 초진: 13칸 전부 입력. 재진: 앞 7칸(생년월일6+성별1)만 입력 + 뒤 6칸은 * 고정(미리 표시).
// 실제 입력 숫자는 f-rrn.dataset.rrn 에 보관(초진 13 / 재진 7). 조회·저장에 사용.
function rrnSync() {
  const el = document.getElementById('f-rrn');
  const cells = el.querySelectorAll('input.rrn-cell');
  el.dataset.rrn = Array.from(cells).map((c) => c.value.replace(/\D/g, '')).join('');
  el.classList.remove('invalid');
  document.getElementById('form-msg').textContent = '';
}

function rrnFocusStep(cell, dir) {
  const cells = Array.from(cell.parentElement.querySelectorAll('input.rrn-cell'));
  const next = cells[cells.indexOf(cell) + dir];
  if (next) next.focus();
}

/** editable=편집 가능한 칸 수(초진 13 / 재진 7). digits=초기값. 뒤는 * 고정 칸. */
function buildRrnCells(editable, digits) {
  const el = document.getElementById('f-rrn');
  el.innerHTML = '';
  el.dataset.rrn = (digits || '').slice(0, editable);
  el.classList.remove('invalid');
  for (let i = 0; i < 13; i++) {
    if (i === 6) {                                   // 생년월일 6자리 뒤 하이픈
      const sep = document.createElement('span');
      sep.className = 'rrn-sep'; sep.textContent = '-';
      el.appendChild(sep);
    }
    if (i < editable) {
      const cell = document.createElement('input');
      cell.className = 'rrn-cell'; cell.type = 'text';
      cell.inputMode = 'numeric'; cell.maxLength = 1; cell.autocomplete = 'off';
      cell.value = (digits && digits[i]) || '';
      cell.addEventListener('input', () => {
        cell.value = cell.value.replace(/\D/g, '').slice(0, 1);
        rrnSync();
        if (cell.value) rrnFocusStep(cell, +1);      // 입력되면 다음 칸으로
      });
      cell.addEventListener('keydown', (e) => {
        if (e.key === 'Backspace' && !cell.value) { e.preventDefault(); rrnFocusStep(cell, -1); }
      });
      cell.addEventListener('focus', () => cell.select());
      el.appendChild(cell);
    } else {
      const star = document.createElement('span');   // 재진: 처음부터 표시되는 * 칸(고정)
      star.className = 'rrn-cell rrn-star'; star.textContent = '*';
      star.setAttribute('aria-hidden', 'true');
      el.appendChild(star);
    }
  }
}

/** on=재진(앞7칸 입력+뒤6칸 *), off=초진(13칸 전부). initialRrn=값 보존용. */
function setRrnMask(on, initialRrn) {
  const digits = (initialRrn || '').replace(/\D/g, '').slice(0, on ? 7 : 13);
  buildRrnCells(on ? 7 : 13, digits);
}

/** 폼의 주민번호 실제 입력 숫자(초진 13 / 재진 7). */
function rrnFieldValue() {
  return document.getElementById('f-rrn').dataset.rrn || '';
}

// ── 전화번호 자동 하이픈(010-1234-5678) ─────────────────────────────────
// 숫자만 입력하면 - 를 자동 삽입(3-4-4). 사용자가 직접 - 를 찍지 않아도 된다.
function formatPhone(v) {
  const d = (v || '').replace(/\D/g, '').slice(0, 11);
  if (d.length < 4) return d;
  if (d.length < 8) return `${d.slice(0, 3)}-${d.slice(3)}`;
  return `${d.slice(0, 3)}-${d.slice(3, 7)}-${d.slice(7)}`;
}

/** 입력 이벤트에서 값을 자동 하이픈 포맷 + 커서 위치 보정. */
function onPhoneInput(e) {
  const el = e.target;
  const digitsBefore = el.value.slice(0, el.selectionStart).replace(/\D/g, '').length;
  el.value = formatPhone(el.value);
  let pos = 0, seen = 0;                        // 커서를 '앞의 숫자 개수' 위치로 재배치
  while (pos < el.value.length && seen < digitsBefore) {
    if (/\d/.test(el.value[pos])) seen++;
    pos++;
  }
  el.setSelectionRange(pos, pos);
  el.classList.remove('invalid');
  document.getElementById('form-msg').textContent = '';
}

/** 환자 정보 입력 화면. 초진=이름/주민번호/연락처, 재진=이름/주민번호. */
function startPatientForm(visitType) {
  // 같은 visitType으로 되돌아온 경우(뒤로/수정) 입력값 보존, 아니면 새로 시작.
  if (!currentPatient || currentPatient.visitType !== visitType) currentPatient = { visitType };
  const first = visitType === 'first';
  document.getElementById('form-title').textContent = STR.formTitle();
  document.getElementById('f-contact-row').hidden = !first;   // 재진은 연락처 없음
  document.getElementById('f-name').value = currentPatient.name || '';
  document.getElementById('f-contact').value = currentPatient.contact || '';
  setRrnMask(!first, currentPatient.rrn || '');   // 재진만 뒷자리 마스킹
  setSteps('form-steps', 0);
  onRelabel('form-screen', () => {
    document.getElementById('form-title').textContent = STR.formTitle();
    setSteps('form-steps', 0);
    document.getElementById('form-msg').textContent = '';   // 오류 안내는 지움(다시 확인 누르면 새 언어로)
  });
  showScreen('form-screen');
  robotController.speak(STR.formSpeak(), 'formIntro');
  document.getElementById('f-name').focus();
}

/** 환자 정보 폼 제출 → 초진=등록 후 증상, 재진=조회 후 예약 여부. */
/** 폼 오류 표시(친절 안내 + 해당 필드 강조 + 포커스). */
function showFormError(fieldId, msg) {
  ['f-name', 'f-rrn', 'f-contact'].forEach((id) => document.getElementById(id).classList.remove('invalid'));
  const f = document.getElementById(fieldId);
  f.classList.add('invalid');
  const m = document.getElementById('form-msg');
  m.textContent = `ℹ️ ${msg}`;
  // 입력 오류는 화면 안내만(음성 없음, 2026-10-13)
  if (fieldId === 'f-rrn') {                          // 세그먼트: 첫 빈 칸(없으면 첫 칸)으로
    const cells = f.querySelectorAll('input.rrn-cell');
    (Array.from(cells).find((c) => !c.value) || cells[0])?.focus();
  } else {
    f.focus();
  }
}

async function submitPatientForm() {
  const name = document.getElementById('f-name').value.trim();
  const rrn = rrnFieldValue();                    // 재진은 마스킹된 표시 대신 실제 숫자
  const contact = document.getElementById('f-contact').value.trim();
  const first = currentPatient.visitType === 'first';
  // 형식 검증: 이름 필수 · 주민번호 13자리 · (초진)연락처 9~11자리
  if (!name) { showFormError('f-name', STR.errName()); return; }
  const rrnLen = rrn.replace(/\D/g, '').length;
  if (first) {
    if (rrnLen !== 13) { showFormError('f-rrn', STR.errRrn()); return; }   // 초진: 전체 13자리
    const c = contact.replace(/\D/g, '');
    if (c.length < 9 || c.length > 11) { showFormError('f-contact', STR.errContact()); return; }
  } else {
    if (rrnLen !== 7) { showFormError('f-rrn', STR.errRrnRevisit()); return; }  // 재진: 앞6+성별1
  }
  document.getElementById('form-msg').textContent = '';
  ['f-name', 'f-rrn', 'f-contact'].forEach((id) => document.getElementById(id).classList.remove('invalid'));
  currentPatient.name = name;
  currentPatient.rrn = rrn;
  currentPatient.contact = contact;

  if (currentPatient.visitType === 'first') {
    showLoading();
    try {
      await fetch('/patient/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, rrn, contact }),
      });
    } catch (_) { /* 저장 실패해도 흐름은 계속 */ } finally { hideLoading(); }
    startInterview();                      // 초진 → 대화형 문진
  } else {
    // 재진: 먼저 환자 데이터셋 등록 여부 + 이름 일치 확인. 미등록/불일치면 접수 차단.
    let chk = null;
    showLoading();
    try {
      const cr = await fetch('/patient/check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, rrn }),
      });
      chk = await cr.json();
    } catch (_) { chk = null; } finally { hideLoading(); }
    if (!chk) { showFormError('f-rrn', STR.errCheckFailed()); return; }        // 조회 실패
    if (!chk.found) { showFormError('f-rrn', STR.errNotRegistered()); return; } // 미등록
    if (!chk.nameMatch) { showFormError('f-name', STR.errNameMismatch()); return; } // 이름 불일치

    // 등록 확인됨 → 예약(reservations.json) 조회 → 예약 있으면 자동 등록, 없으면 문진.
    let info = { reservation: null };
    showLoading();
    try {
      const res = await fetch('/reservation/check', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, rrn }),
      });
      info = await res.json();
    } catch (_) { /* 조회 실패 → 예약 없음으로 간주 */ } finally { hideLoading(); }
    currentPatient.reservation = info.reservation || null;

    if (info.reservation && findLocation(info.reservation)) {
      // 예약대로 자동 등록(예약 소비). 간호사가 적어둔 증상/사유를 대기명단에 함께 기록.
      addToWaitlist(info.reservation, info.reservationSymptom || '', 'revisit', true);
    } else {
      startInterview();                                        // 예약 없음 → 대화형 문진(안내 음성은 문진 시작 대사 하나)
    }
  }
}

// ── AI 대화형 문진(사이클8) ──────────────────────────────────────────────
// 서버 무상태: interviewMsgs(클라 보유)를 매 요청에 통째로 전송.
// messages의 assistant=AI 꼬리질문, user=환자 답변. 첫 질문(symptomQ)은 음성 안내 전용(화면·서버에 안 넣음)
// → 서버의 꼬리질문 상한(MAX_FOLLOWUPS=2)이 "첫 질문 뒤 최대 2개"로 정확히 맞는다.
let interviewMsgs = [];
let interviewBusy = false;

/** 문진 시작: intake 화면을 채팅으로 초기화하고 첫 질문 표시. */
function startInterview() {
  interviewMsgs = [];
  interviewBusy = false;
  setSteps('intake-steps', 1, 'revisit');  // 증상 화면은 초진도 재진과 같은 단계 표시(본인 확인/확인/완료)
  onRelabel('intake-screen', () => {
    setSteps('intake-steps', 1, 'revisit');
    const mic = document.getElementById('iv-mic');
    if (mic && mic.dataset.state) setIvMic(mic.dataset.state);
  });
  document.getElementById('interview-log').innerHTML = '';
  document.getElementById('intake-text').value = '';
  document.getElementById('intake-form').hidden = !new URLSearchParams(location.search).has('dev');   // 음성 전용(?dev=1 시험용 타자만)
  showScreen('intake-screen');
  // 안내 음성이 끝난 뒤 녹음 시작(동시에 요청하면 서버가 녹음을 먼저 잡아 안내가 말하기 전까지 막힘)
  setIvMic('speaking');
  const seq = ++_ivSpeakSeq;
  robotController.speak(STR.symptomQ(), 'symptomQ').then(() => listenIfInterviewing(seq));   // 음성도 병행 대기(마이크 없으면 타자)
}

/** 채팅 말풍선 추가(ai=AI 질문 / me=환자 답변). */
function addChatMsg(who, text) {
  // 대화창: AI = 왼쪽(테두리 있는 흰 말풍선), 환자 = 오른쪽(주색 말풍선). 넘치면 오래된 메시지는 위로 밀려 가려짐
  const log = document.getElementById('interview-log');
  const div = document.createElement('div');
  div.className = 'chat-msg ' + (who === 'me' ? 'me' : 'ai');
  div.textContent = text;
  log.appendChild(div);
  // 항상 최신 메시지가 보이게 맨 아래로. 그려진 뒤 한 번 더 맞춤
  log.scrollTop = log.scrollHeight;
  requestAnimationFrame(() => { log.scrollTop = log.scrollHeight; });
}

/** 고정 안내 음성 목록(언어 l, 실제 speak()로 보내는 문장과 글자까지 동일) → TTS 서버 캐시 미리 채움.
    문장이 바뀌어도 여기서 STR을 그대로 호출하므로 자동으로 맞춰진다. AI 꼬리질문처럼 매번 다른 문장은 제외. */
function prewarmSpeech(l = 'ko') {
  const saved = lang;
  lang = l;
  const texts = [];
  try {
    const walkin = ['internal', 'surgery', 'wonmu', 'pediatric', 'pain'];
    texts.push(STR.listenPrompt(), STR.notHeardSpeak(), STR.whichSpeak(), STR.visitQ(), STR.formSpeak(),
      STR.symptomQ(), STR.triageHardSpeak(), STR.waitDoneSpeak(), STR.noResponse(), STR.reqFailed());
    LOCATIONS.forEach((loc) => {
      texts.push(`${STR.locatedSpeak(loc)} ${STR.confirmGuideQ()}`, STR.guideStartSpeak(loc), STR.arrivedSpeak(loc));
      if (walkin.includes(loc.id)) texts.push(STR.recommendSpeak(loc));
    });
  } finally { lang = saved; }
  fetch('/speak/prewarm', {
    method: 'POST', headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ texts: [...new Set(texts)], lang: l }),
  }).catch(() => { /* TTS 서버 없음 → 무시(재생 때 합성) */ });
}

/** 안내 음성이 끝난 뒤 호출: 그 사이 더 새 안내가 나갔거나(seq 불일치), 타자로 답했거나, 화면을 떠났으면 녹음하지 않는다. */
let _ivSpeakSeq = 0;
/** 문진 화면 음성 상태 표시: speaking(안내 중) / listening(듣는 중) / processing(확인 중) / error / idle */
function setIvMic(state) {
  const el = document.getElementById('iv-mic');
  if (!el) return;
  el.dataset.state = state;
  const txt = { speaking: STR.ivSpeaking, listening: STR.ivListening, processing: STR.ivProcessing, error: STR.ivMicError }[state];
  el.querySelector('.chat-mic-text').textContent = txt ? txt() : '';
}

function listenIfInterviewing(seq) {
  if (seq !== _ivSpeakSeq) return;
  const active = document.querySelector('.screen.active');
  if (!active || active.id !== 'intake-screen' || interviewBusy) return;
  listenInterview();
}

/** 음성으로 답변 대기(타자 제출 시 cancel→null). */
async function listenInterview() {
  setIvMic('listening');
  const result = await recognizer.listen(lang);   // 화면 언어로 음성인식
  if (result === null) return;
  if (result.error) { setIvMic('error'); return; }       // 마이크·음성인식 서버 문제
  const t = (result.text || '').trim();
  if (t) { submitAnswer(t); return; }
  // 말소리 없이 끝남(서버 대기 제한) → 아직 이 화면에서 답을 기다리면 다시 듣기. 오류(마이크 없음 등)면 멈춤
  if (!result.error) listenIfInterviewing(_ivSpeakSeq);
}

/** 환자 답변 처리: 응급 선검사 → /interview로 다음 질문 or 종합. */
async function submitAnswer(text) {
  if (interviewBusy) return;               // 중복 제출 방지
  interviewBusy = true;
  addChatMsg('me', text);
  interviewMsgs.push({ role: 'user', text });
  const inp = document.getElementById('intake-text');
  inp.value = ''; inp.blur();
  recognizer.cancel();
  setIvMic('processing');

  if (isEmergency(text)) { showEmergency(); return; }   // (a) 클라 응급 선검사(서버도 이중)

  showLoading();
  let data = {};
  try {
    const res = await fetch('/interview', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lang, messages: interviewMsgs }),
    });
    data = await res.json();
  } catch (_) { data = { action: 'done' }; } finally { hideLoading(); }

  if (data.action === 'emergency') { showEmergency(); return; }
  if (data.action === 'ask' && data.question) {
    addChatMsg('ai', data.question);
    interviewMsgs.push({ role: 'assistant', text: data.question });
    interviewBusy = false;
    setIvMic('speaking');
    const seq = ++_ivSpeakSeq;
    robotController.speak(data.question, 'interviewQ').then(() => listenIfInterviewing(seq));   // 질문 음성 끝난 뒤 녹음
    return;
  }
  finishInterview();                       // done/무효 → 종합
}

/** 종합: /interview/summarize → 추천 진료과 + 요약. (AI가 done 이거나 꼬리질문 상한 도달 시) */
async function finishInterview() {
  interviewBusy = true;
  recognizer.cancel();
  showLoading();
  let data = {};
  try {
    const res = await fetch('/interview/summarize', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ lang, messages: interviewMsgs }),
    });
    data = await res.json();
  } catch (_) { data = {}; } finally { hideLoading(); }

  if (data.emergency) { showEmergency(); return; }       // 종합 단계 응급 방어
  const visitType = (currentPatient && currentPatient.visitType) || 'first';
  const dep = data.locationId ? findLocation(data.locationId) : null;
  const summaryKo = (data.summaryKo || '').trim();
  const userMsgs = interviewMsgs.filter((m) => m.role === 'user').map((m) => m.text);
  const chief = userMsgs[0] || userMsgs.join(' ');   // 짧은 주증상(첫 발화)
  const summary = summaryKo || userMsgs.join(' ');    // 의료진용 한국어 요약(폴백=발화 합침)
  showInterviewResult(dep, chief, summary, visitType);   // 환자 확인 문장(recap)은 표시하지 않음(2026-10-12)
}

/** 종합 결과 화면(retry 재사용): 리캡 + 추천 진료과 확인. 다른 과 선택·다시 문진 가능.
    symptom=짧은 주증상, summary=한국어 요약(대기명단에 함께 저장). */
function showInterviewResult(dep, symptom, summary, visitType) {
  const walkin = ['internal', 'surgery', 'wonmu', 'pediatric', 'pain'];
  if (dep) {
    robotController.speak(STR.recommendSpeak(dep), 'recommend');
    const others = LOCATIONS.filter((l) => walkin.includes(l.id) && l.id !== dep.id);
    showRetry(() => STR.recommendMsg(dep), [
      { label: () => STR.acceptDeptBtn(dep), action: () => addToWaitlist(dep.id, symptom, visitType, false, summary), primary: true },
      ...others.map((l) => ({ label: () => locName(l), action: () => addToWaitlist(l.id, symptom, visitType, false, summary) })),
    ], '', 1, '', startInterview);         // "증상 다시 말하기" 대신 하단 "뒤로"(증상 입력부터 다시)                             // 추천 화면엔 "진단 아님" 안내를 두지 않음(2026-10-12)
  } else {
    robotController.speak(STR.triageHardSpeak(), 'triageHard');
    showRetry(() => STR.triageHardMsg(), [
      ...LOCATIONS.filter((l) => walkin.includes(l.id))
        .map((l) => ({ label: () => locName(l), action: () => addToWaitlist(l.id, symptom, visitType, false, summary) })),
    ], () => STR.disclaimer(), 1, '', startInterview);
  }
}

/** 진료과 대기명단에 환자 등록 → 확인 + 위치 안내 제안. consumeReservation=예약대로 등록.
    summary=문진 종합 한국어 요약(의료진용, 있으면 함께 저장). */
async function addToWaitlist(deptId, symptom, visitType, consumeReservation, summary) {
  const dep = findLocation(deptId);
  let res = {};
  showLoading();
  try {
    const r = await fetch('/waitlist/add', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        name: (currentPatient && currentPatient.name) || '',
        rrn: (currentPatient && currentPatient.rrn) || '',
        deptId, visitType: visitType || 'first', symptom: symptom || '',
        symptomSummary: summary || '',
        consumeReservation: !!consumeReservation,
        lang,                                   // 접수 언어 → 콜보드가 이 언어로 호출
      }),
    });
    res = await r.json();
  } catch (_) { res = {}; } finally { hideLoading(); }

  showWaitScreen(dep, res.ticket, res.id, res.ahead || 0, !!consumeReservation);
}

// ---- 환자 대기 현황 화면 (접수 완료 후, 폴링으로 순번·호출 갱신) ----
let _waitPoll = null;
let _waitCtx = null;   // {deptId, id, dep}

function showWaitScreen(dep, ticket, id, ahead, reserved) {
  _waitCtx = { deptId: dep.id, id, dep };
  document.getElementById('wait-title').textContent = STR.waitTitle();
  document.getElementById('wait-ticket-label').textContent = STR.waitTicketLabel();
  document.getElementById('wait-ticket-num').textContent = String(ticket);
  const g = document.getElementById('wait-guide');
  g.textContent = STR.guideDeptBtn(dep);
  g.onclick = () => showResult(dep);
  updateWaitUI(ahead, 'waiting');
  setSteps('wait-steps', 2);
  onRelabel('wait-screen', () => {               // 대기 인원·호출 문구는 2.5초 폴링이 새 언어로 갱신
    document.getElementById('wait-title').textContent = STR.waitTitle();
    document.getElementById('wait-ticket-label').textContent = STR.waitTicketLabel();
    g.textContent = STR.guideDeptBtn(dep);
    setSteps('wait-steps', 2);
  });
  showScreen('wait-screen');
  robotController.speak(STR.waitDoneSpeak(), 'waitTicket');   // 음성은 "접수가 완료되었습니다." 하나(예약 자동등록도 동일)
  clearInterval(_waitPoll);
  _waitPoll = setInterval(pollWait, 2500);
}

/** 대기 화면 표시 갱신(대기/임박/호출/진료중). */
function updateWaitUI(ahead, status) {
  const scr = document.getElementById('wait-screen');
  scr.classList.remove('called', 'soon', 'in-progress');
  const aheadEl = document.getElementById('wait-ahead');
  const statusEl = document.getElementById('wait-status');
  if (status === 'in_progress') {
    aheadEl.textContent = '';
    statusEl.textContent = STR.waitInProgress(_waitCtx.dep);
    scr.classList.add('in-progress');
  } else if (status === 'called') {
    aheadEl.textContent = '';
    statusEl.textContent = STR.waitCalled(_waitCtx.dep);
    scr.classList.add('called');
  } else {
    aheadEl.textContent = STR.waitCount(ahead);
    statusEl.textContent = '';                                    // "곧 순서입니다" 문구는 표시하지 않음
    if (ahead <= 1) scr.classList.add('soon');                    // 임박 강조(대기인수 색)만 유지
  }
}

/** 2.5초마다 내 대기 상태 폴링. 호출되면 안내, 완료(목록서 빠짐)면 감사 인사. */
async function pollWait() {
  if (!_waitCtx) { clearInterval(_waitPoll); _waitPoll = null; return; }
  let s;
  try {
    const r = await fetch('/waitlist/status', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deptId: _waitCtx.deptId, id: _waitCtx.id }),
    });
    s = await r.json();
  } catch (_) { return; }
  if (!s.found || s.status === 'done') {   // 완료(소프트완료 status=done 또는 목록서 빠짐)
    clearInterval(_waitPoll); _waitPoll = null;
    document.getElementById('wait-screen').classList.remove('called', 'soon', 'in-progress');
    document.getElementById('wait-ahead').textContent = '';
    document.getElementById('wait-status').textContent = STR.waitDone();
    return;
  }
  const wasCalled = document.getElementById('wait-screen').classList.contains('called');
  updateWaitUI(s.ahead, s.status);
  // 호출 음성은 대기실 콜보드(?callboard=1)가 낸다(2026-10-13). 키오스크는 화면 표시(초록 깜빡임)만.
}

// ---- 관리자: 탭 3페이지(환자 데이터셋 / 예약 명단 / 대기 현황) (URL ?nurse=1, 예전 ?admin=1) ----
let _admDeptFilled = false;
let _admData = { patients: [], reservations: [], waitlistById: {}, patientCount: 0, depts: [] };
let _patSort = 'name';   // 환자 데이터셋 정렬 키
let _resSort = 'name';   // 예약 명단 정렬 키
let _adminPin = '';      // 관리자 PIN(인증 후 저장, admin 요청 헤더로 전송)
let _adminProtected = false;  // PIN 필요 여부(자동 잠금 활성 조건)
let _adminRefresh = null;     // 대기명단 자동 새로고침 interval
let _adminIdle = null;        // 자동 잠금 타이머
const ADMIN_IDLE_MS = 3 * 60 * 1000;   // 3분 무조작 → 재인증

/** 관리자 요청: X-Admin-Pin 헤더를 붙여 보낸다. */
function adminFetch(url, opts = {}) {
  const headers = Object.assign({}, opts.headers, { 'X-Admin-Pin': _adminPin });
  return fetch(url, Object.assign({}, opts, { headers }));
}

/** 예약 등록 폼의 진료과 select 채우기(화장실 제외, 최초 1회). */
function populateAdminDept(depts) {
  const sel = document.getElementById('adm-dept');
  if (!sel || _admDeptFilled || !(depts && depts.length)) return;
  depts.filter((d) => d.id !== 'toilet').forEach((d) => {
    const o = document.createElement('option');
    o.value = d.id; o.textContent = d.name;
    sel.appendChild(o);
  });
  _admDeptFilled = true;
}

/** 정렬 비교기. key: name(이름) / rrn(주민번호) / contact(전화번호). */
function _admSorted(list, key) {
  const arr = [...(list || [])];
  arr.sort((a, b) => {
    const va = (a[key === 'rrn' ? 'rrn_masked' : key] || '').toString();
    const vb = (b[key === 'rrn' ? 'rrn_masked' : key] || '').toString();
    return va.localeCompare(vb, 'ko');
  });
  return arr;
}

/** 삭제 버튼 생성 헬퍼. */
function _delBtn(onClick) {
  const b = document.createElement('button');
  b.type = 'button'; b.className = 'admin-del'; b.textContent = '삭제';
  b.addEventListener('click', onClick);
  return b;
}

/** 페이지 1: 환자 데이터셋(이름·주민번호·전화번호). */
function renderPatients() {
  const box = document.getElementById('admin-patients');
  box.innerHTML = '';
  const ps = _admSorted(_admData.patients, _patSort);
  if (!ps.length) { box.innerHTML = '<p class="admin-empty">등록된 환자가 없습니다.</p>'; return; }
  const ul = document.createElement('ul');
  ul.className = 'admin-resv-list';
  ps.forEach((p) => {
    const li = document.createElement('li');
    const span = document.createElement('span');
    // 의료진용: 전체 주민번호(복호화)가 있으면 그대로, 없으면(구데이터) 마스킹 폴백
    const rrn = p.rrn_full || p.rrn_masked;
    span.textContent = `${p.name} · ${rrn}${p.contact ? ` · ${p.contact}` : ''}`;
    li.appendChild(span);
    li.appendChild(_delBtn(() => removePatient(p.rrn_hash)));
    ul.appendChild(li);
  });
  box.appendChild(ul);
}

/** 페이지 2: 예약 명단(이름·주민번호·전화번호·진료과·증상). */
function renderReservations() {
  const box = document.getElementById('admin-reservations');
  box.innerHTML = '';
  const rs = _admSorted(_admData.reservations, _resSort);
  if (!rs.length) { box.innerHTML = '<p class="admin-empty">등록된 예약이 없습니다.</p>'; return; }
  const ul = document.createElement('ul');
  ul.className = 'admin-resv-list';
  rs.forEach((r) => {
    const li = document.createElement('li');
    const span = document.createElement('span');
    const tail = r.contact ? ` · ${r.contact}` : '';
    const dt = r.date ? ` · 📅 ${r.date}` : '';
    const sym = r.symptom ? ` · “${r.symptom}”` : '';
    span.textContent = `${r.name} · ${r.rrn_masked}${tail} → ${r.deptName}${dt}${sym}`;
    li.appendChild(span);
    li.appendChild(_delBtn(() => removeReservation(r.rrn_hash)));
    ul.appendChild(li);
  });
  box.appendChild(ul);
}

/** 페이지 3: 진료과별 대기 현황(칸 분리) + 칸마다 삭제. */
function renderWaitlist() {
  // 간호사 대기 현황(2026-10-13 개편): 대기/호출/진료중 = 위 목록, 의사가 '진료 완료' 하면 아래 '완료된 환자'로 자동 이동 + 의사 메모 표시.
  //  간호사 버튼: 대기=호출, 호출됨=재호출(진료 시작·완료는 의사 화면). 줄 표시는 '#순번 · 이름'만.
  const body = document.getElementById('admin-body');
  body.innerHTML = '';
  const wl = _admData.waitlistById || {};
  const deptIds = Object.keys(wl).filter((id) => (wl[id] || []).length);
  if (!deptIds.length) { body.innerHTML = '<p class="admin-empty">대기 중인 환자가 없습니다.</p>'; return; }
  const row = (e) => {
    const li = document.createElement('li');
    const info = document.createElement('div');
    info.className = 'wait-info';
    const line = document.createElement('span');
    line.className = 'wait-line';
    line.textContent = `#${e.ticket} · ${e.name}`;
    info.appendChild(line);
    li.appendChild(info);
    return { li, info };
  };
  deptIds.forEach((id) => {
    const dep = findLocation(id);
    const div = document.createElement('div');
    div.className = 'admin-dept';
    const active = wl[id].filter((e) => ['waiting', 'called', 'in_progress'].includes(e.status));
    const done = wl[id].filter((e) => e.status === 'done')
      .sort((a, b) => (b.done_at || 0) - (a.done_at || 0));             // 최근 완료가 위
    const h = document.createElement('h3');
    h.textContent = `${dep ? dep.name : id} (${active.length}명)`;
    div.appendChild(h);

    const ol = document.createElement('ol');
    if (!active.length) ol.innerHTML = '<p class="admin-empty">대기 중인 환자가 없습니다.</p>';
    active.forEach((e) => {
      const { li } = row(e);
      if (e.status === 'called') li.classList.add('called');
      else if (e.status === 'in_progress') li.classList.add('in-progress');
      const acts = document.createElement('span');
      acts.className = 'admin-acts';
      if (e.status === 'in_progress') {
        const st = document.createElement('span');
        st.className = 'admin-state'; st.textContent = '🩺 진료 중';
        acts.appendChild(st);
      } else {
        const callBtn = document.createElement('button');
        callBtn.type = 'button'; callBtn.className = 'admin-act call';
        callBtn.textContent = e.status === 'called' ? '재호출' : '호출';
        callBtn.addEventListener('click', () => callWaitlist(id, e.id));
        acts.appendChild(callBtn);
      }
      acts.appendChild(_delBtn(() => removeWaitlistEntry(id, e.id)));
      li.appendChild(acts);
      ol.appendChild(li);
    });
    div.appendChild(ol);

    if (done.length) {
      const dh = document.createElement('h4');
      dh.className = 'admin-done-head';
      dh.textContent = `완료된 환자 (${done.length}명)`;
      div.appendChild(dh);
      const dl = document.createElement('ol');
      dl.className = 'admin-done-list';
      done.forEach((e) => {
        const { li, info } = row(e);
        li.classList.add('done');
        const memo = document.createElement('span');
        memo.className = 'admin-memo';
        memo.textContent = e.memo ? `🗒 ${e.memo}` : '🗒 메모 없음';
        info.appendChild(memo);
        const acts = document.createElement('span');
        acts.className = 'admin-acts';
        acts.appendChild(_delBtn(() => removeWaitlistEntry(id, e.id)));
        li.appendChild(acts);
        dl.appendChild(li);
      });
      div.appendChild(dl);
    }
    body.appendChild(div);
  });
}

async function loadAdmin() {
  try { _admData = await (await adminFetch('/waitlist')).json(); } catch (_) { /* keep last */ }
  populateAdminDept(_admData.depts);
  document.getElementById('admin-summary').textContent =
    `등록 환자 ${_admData.patientCount || 0}명 · 예약 ${(_admData.reservations || []).length}건`;
  renderPatients();
  renderReservations();
  renderWaitlist();
}

/** ?nurse(예전 ?admin) 진입: PIN 필요 여부 확인 → 게이트 또는 바로 진입. */
async function initAdminGate() {
  let info = { required: false, ok: true };
  try {
    info = await (await fetch('/admin/auth', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin: '' }),
    })).json();
  } catch (_) { /* 서버 무응답 → 게이트 표시(안전측) */ info = { required: true, ok: false }; }
  _adminProtected = !!info.required;
  if (!info.required) { startAdminUI(); return; }
  showScreen('admin-gate');
  document.getElementById('gate-pin').focus();
}

/** PIN 제출 → 인증되면 관리자 진입. */
async function submitGate(e) {
  e.preventDefault();
  const pin = document.getElementById('gate-pin').value;
  let r = { ok: false };
  try {
    r = await (await fetch('/admin/auth', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ pin }),
    })).json();
  } catch (_) { /* ignore */ }
  if (r.ok) {
    _adminPin = pin;
    _adminProtected = true;
    document.getElementById('gate-msg').textContent = '';
    startAdminUI();
  } else {
    document.getElementById('gate-msg').textContent = 'PIN이 올바르지 않습니다.';
    document.getElementById('gate-pin').value = '';
    document.getElementById('gate-pin').focus();
  }
}

/** 관리자 화면 진입 + 자동 새로고침 + 자동 잠금 타이머. */
function startAdminUI() {
  showScreen('admin-screen');
  loadAdmin();
  clearInterval(_adminRefresh);
  _adminRefresh = setInterval(loadAdmin, 5000);
  resetAdminIdle();
  console.log('[app] 관리자 모드');
}

/** 무조작 타이머 리셋(admin 화면 조작 시). PIN 보호 상태에서만. */
function resetAdminIdle() {
  if (!_adminProtected) return;
  clearTimeout(_adminIdle);
  _adminIdle = setTimeout(lockAdmin, ADMIN_IDLE_MS);
}

/** 자동 잠금: 새로고침·타이머 정지, PIN 폐기, 게이트로 복귀. */
function lockAdmin() {
  clearInterval(_adminRefresh); _adminRefresh = null;
  clearInterval(_docRefresh); _docRefresh = null;   // 의사 화면 폴링도 정지
  clearTimeout(_adminIdle); _adminIdle = null;
  _adminPin = '';
  document.getElementById('gate-pin').value = '';
  document.getElementById('gate-msg').textContent = '자동 잠금되었습니다. 다시 인증하세요.';
  showScreen('admin-gate');
  document.getElementById('gate-pin').focus();
}

/** 탭 전환. */
function showAdminPage(page) {
  document.querySelectorAll('.admin-tab').forEach((t) => t.classList.toggle('active', t.dataset.page === page));
  ['patients', 'reservations', 'waitlist'].forEach((p) => {
    document.getElementById(`page-${p}`).hidden = (p !== page);
  });
}

/** 간호사: 대기명단 항목 삭제. */
async function removeWaitlistEntry(deptId, id) {
  try {
    await adminFetch('/waitlist/remove', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deptId, id }),
    });
  } catch (_) { /* ignore */ }
  loadAdmin();
}

/** 간호사: 환자 호출(상태 → 호출됨). */
async function callWaitlist(deptId, id) {
  try {
    await adminFetch('/waitlist/call', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deptId, id }),
    });
  } catch (_) { /* ignore */ }
  loadAdmin();
}

/** 간호사: 진료 완료(목록에서 정리). */

/** 간호사: 등록 환자(데이터셋) 삭제(rrn_hash로). */
async function removePatient(rrnHash) {
  try {
    await adminFetch('/patient/remove', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rrnHash }),
    });
  } catch (_) { /* ignore */ }
  loadAdmin();
}

/** 간호사: 예약 삭제(rrn_hash로). */
async function removeReservation(rrnHash) {
  try {
    await adminFetch('/reservation/remove', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ rrnHash }),
    });
  } catch (_) { /* ignore */ }
  loadAdmin();
}

/** 간호사: 예약을 등록(별도 저장). 다음 예약 증상/사유 포함. */
async function submitReservation() {
  const name = document.getElementById('adm-name').value.trim();
  const rrn = document.getElementById('adm-rrn').value.trim();
  const deptId = document.getElementById('adm-dept').value;
  const d = document.getElementById('adm-date').value;      // yyyy-mm-dd
  const t = document.getElementById('adm-time').value;      // HH:MM (선택)
  const date = d && t ? `${d} ${t}` : (d || t);              // 서버는 표시용 문자열로 저장(예: 2026-10-20 14:30)
  const symptom = document.getElementById('adm-symptom').value.trim();
  if (!name || !rrn || !deptId) {
    document.getElementById('admin-summary').textContent = '예약 등록: 이름·주민번호·진료과를 모두 입력하세요.';
    return;
  }
  try {
    await adminFetch('/reservation/set', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ name, rrn, deptId, symptom, date }),
    });
  } catch (_) { /* ignore */ }
  document.getElementById('adm-name').value = '';
  document.getElementById('adm-rrn').value = '';
  document.getElementById('adm-date').value = '';
  document.getElementById('adm-time').value = '';
  document.getElementById('adm-symptom').value = '';
  loadAdmin();
}

/** 홈 2단계: 메뉴 ↔ 위치 안내용 마이크 전환. */
function showHomeMenu() {
  document.getElementById('home-menu').hidden = false;
  document.getElementById('mic-area').hidden = true;
}
function showLocationMic() {
  document.getElementById('home-menu').hidden = true;
  document.getElementById('mic-area').hidden = false;
}

// =========================================================================
// 의사용 화면 (URL ?doctor=1) — 자기 진료과 대기 + 진료 진행 + 메모. 한국어 고정.
//   PIN 게이트는 간호사 admin과 공통(ADMIN_PIN). 자동 잠금(lockAdmin)도 공용.
// =========================================================================
// 의사가 선택 가능한 진료과: 진료(외래) 5개. 영상의학과·진단검사의학과(지원과)·화장실 제외.
const DOCTOR_DEPTS = ['internal', 'surgery', 'wonmu', 'pediatric', 'pain'];
let _docDept = null;
let _docRefresh = null;
const _DOC_ST = { waiting: '대기', called: '🔔 호출됨', in_progress: '🩺 진료중', done: '✅ 완료' };

async function initDoctorGate() {
  let info = { required: false, ok: true };
  try {
    info = await (await fetch('/admin/auth', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin: '' }),
    })).json();
  } catch (_) { info = { required: true, ok: false }; }
  _adminProtected = !!info.required;
  if (!info.required) { startDoctorUI(); return; }
  showScreen('admin-gate');
  document.getElementById('gate-pin').focus();
}

async function submitDoctorGate(e) {
  e.preventDefault();
  const pin = document.getElementById('gate-pin').value;
  let r = { ok: false };
  try {
    r = await (await fetch('/admin/auth', {
      method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pin }),
    })).json();
  } catch (_) { /* ignore */ }
  if (r.ok) {
    _adminPin = pin; _adminProtected = true;
    document.getElementById('gate-msg').textContent = '';
    startDoctorUI();
  } else {
    document.getElementById('gate-msg').textContent = 'PIN이 올바르지 않습니다.';
    document.getElementById('gate-pin').value = '';
    document.getElementById('gate-pin').focus();
  }
}

function startDoctorUI() {
  _docDept = null;
  const box = document.getElementById('doctor-dept-btns');
  box.innerHTML = '';
  DOCTOR_DEPTS.forEach((id) => {
    const loc = findLocation(id);
    const b = document.createElement('button');
    b.type = 'button'; b.className = 'doctor-dept-btn'; b.textContent = loc ? loc.name : id;
    b.addEventListener('click', () => selectDoctorDept(id));
    box.appendChild(b);
  });
  document.getElementById('doctor-dept-select').hidden = false;
  document.getElementById('doctor-queue').hidden = true;
  showScreen('doctor-screen');
  resetAdminIdle();
}

function selectDoctorDept(id) {
  _docDept = id;
  const loc = findLocation(id);
  document.getElementById('doctor-dept-name').textContent = `${loc ? loc.name : id} 진료`;
  document.getElementById('doctor-dept-select').hidden = true;
  document.getElementById('doctor-queue').hidden = false;
  loadDoctorQueue();
  clearInterval(_docRefresh);
  _docRefresh = setInterval(loadDoctorQueue, 3000);
}

function doctorSwitchDept() {
  clearInterval(_docRefresh); _docRefresh = null;
  _docDept = null;
  document.getElementById('doctor-dept-select').hidden = false;
  document.getElementById('doctor-queue').hidden = true;
}

const _docDrafts = {};   // 진료 메모 초안(entry id → 글). 저장/완료 시 삭제
const _docSavedAt = {};  // 메모 저장 성공 시각(버튼에 '✓ 저장됨' 2초 표시용)
const _docSaveFail = {}; // 메모 저장 실패 표시

async function loadDoctorQueue() {
  if (!_docDept) return;
  let data = { active: [], done: [] };
  try {
    data = await (await adminFetch(`/doctor/queue?dept=${encodeURIComponent(_docDept)}`)).json();
  } catch (_) { return; }
  // 쓰는 중인 메모칸의 포커스·커서 위치를 기억했다가 다시 그린 뒤 되돌린다
  const act = document.activeElement;
  const focusId = act && act.classList && act.classList.contains('doctor-memo-input') ? act.dataset.entry : null;
  const sel = focusId ? [act.selectionStart, act.selectionEnd] : null;
  renderDoctorList(document.getElementById('doctor-active'), data.active || [], false);   // '오늘 완료'는 간호사 화면으로 이동(2026-10-13)
  if (focusId) {
    const ta = document.querySelector(`.doctor-memo-input[data-entry="${CSS.escape(focusId)}"]`);
    if (ta) { ta.focus(); try { ta.setSelectionRange(sel[0], sel[1]); } catch (_) { /* ignore */ } }
  }
  resetAdminIdle();
}

function _docActBtn(label, kind, on) {
  const b = document.createElement('button');
  b.type = 'button'; b.className = `doctor-act ${kind}`; b.textContent = label;
  b.addEventListener('click', on);
  return b;
}

function renderDoctorList(box, list, isDone) {
  box.innerHTML = '';
  if (!list.length) {
    box.innerHTML = `<p class="admin-empty">${isDone ? '완료된 환자가 없습니다.' : '대기 중인 환자가 없습니다.'}</p>`;
    return;
  }
  list.forEach((e) => {
    const card = document.createElement('div');
    card.className = 'doctor-card' + (e.status === 'in_progress' ? ' active' : '') + (isDone ? ' done' : '');
    const head = document.createElement('div');
    head.className = 'doctor-card-head';
    const vt = e.visit_type === 'revisit' ? '재진' : '초진';
    head.textContent = `#${e.ticket} · ${e.name} · ${e.rrn_masked} · ${vt} · ${_DOC_ST[e.status] || ''}`;
    card.appendChild(head);
    const summ = document.createElement('p');
    summ.className = 'doctor-summary';
    summ.textContent = `📝 ${e.symptom_summary || e.symptom || '증상 요약 없음'}`;
    card.appendChild(summ);
    if (!isDone) {
      const acts = document.createElement('div');
      acts.className = 'doctor-acts';
      // 호출·재호출은 간호사 화면 담당(2026-10-13) — 의사는 진료 시작·진료 완료만
      acts.appendChild(_docActBtn('진료 시작', 'start', () => doctorAction('/waitlist/start', e.id)));
      const memoWrap = document.createElement('div');
      memoWrap.className = 'doctor-memo';
      const ta = document.createElement('textarea');
      ta.className = 'field doctor-memo-input'; ta.rows = 2;
      ta.placeholder = '진료 메모 (의료진용)';
      ta.dataset.entry = e.id;
      // 3초 자동 갱신 때 쓰던 메모가 지워지지 않게: 저장 안 한 초안을 보관했다가 다시 채움
      ta.value = Object.prototype.hasOwnProperty.call(_docDrafts, e.id) ? _docDrafts[e.id] : (e.memo || '');
      // 저장 상태 표시줄: 저장된 내용과 다르면 '저장 안 됨', 같으면 '✓ 저장됨 · 시각'
      const status = document.createElement('p');
      status.className = 'doctor-memo-status';
      const paintStatus = () => {
        const saved = (e.memo || '').trim();
        const cur = ta.value.trim();
        status.classList.remove('saved', 'unsaved', 'failed');
        if (_docSaveFail[e.id]) { status.textContent = '⚠ 저장하지 못했습니다. 다시 눌러 주세요.'; status.classList.add('failed'); }
        else if (cur !== saved) { status.textContent = '● 저장하지 않은 변경 사항이 있습니다'; status.classList.add('unsaved'); }
        else if (e.memo_at && saved) { status.textContent = `✓ 저장됨 · ${_hhmm(e.memo_at)}`; status.classList.add('saved'); }
        else status.textContent = '';
      };
      ta.addEventListener('input', () => { _docDrafts[e.id] = ta.value; delete _docSaveFail[e.id]; paintStatus(); });
      paintStatus();
      // 진료 완료 = 메모 저장 + 완료(간호사 화면 '완료된 환자'로 이동, 메모 함께 표시)
      acts.appendChild(_docActBtn('진료 완료', 'done', () => doctorFinish(e.id, ta.value)));
      card.appendChild(acts);
      const save = document.createElement('button');
      save.type = 'button'; save.className = 'btn-secondary doctor-memo-save';
      const justSaved = Date.now() - (_docSavedAt[e.id] || 0) < 2000;      // 저장 직후 2초간 버튼에 확인 표시
      save.textContent = justSaved ? '✓ 저장됨' : '메모 저장';
      if (justSaved) save.classList.add('saved');
      save.addEventListener('click', () => { save.textContent = '저장 중…'; save.disabled = true; doctorSaveMemo(e.id, ta.value); });
      memoWrap.appendChild(ta); memoWrap.appendChild(save);
      card.appendChild(memoWrap);
      card.appendChild(status);
    } else if (e.memo) {
      const m = document.createElement('p');
      m.className = 'doctor-memo-read';
      m.textContent = `🗒 ${e.memo}`;
      card.appendChild(m);
    }
    box.appendChild(card);
  });
}

async function doctorAction(path, id) {
  try {
    await adminFetch(path, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deptId: _docDept, id }),
    });
  } catch (_) { /* ignore */ }
  loadDoctorQueue();
}

/** 진료 완료: 메모를 먼저 저장하고 완료 처리 → 간호사 화면 '완료된 환자'에 메모와 함께 표시. */
async function doctorFinish(id, memo) {
  try {
    await adminFetch('/waitlist/memo', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deptId: _docDept, id, memo }),
    });
  } catch (_) { /* 메모 실패해도 완료는 진행 */ }
  delete _docDrafts[id];
  doctorAction('/waitlist/done', id);
}

async function doctorSaveMemo(id, memo) {
  let ok = false;
  try {
    const r = await (await adminFetch('/waitlist/memo', {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ deptId: _docDept, id, memo }),
    })).json();
    ok = !!(r && r.ok);
  } catch (_) { /* 실패 표시 */ }
  if (ok) { delete _docDrafts[id]; delete _docSaveFail[id]; _docSavedAt[id] = Date.now(); setTimeout(loadDoctorQueue, 2100); }
  else _docSaveFail[id] = true;                       // 실패 시 초안은 지우지 않음(쓴 글 보존)
  loadDoctorQueue();
}

/** 초(epoch) → 'HH:MM' */
function _hhmm(sec) {
  const d = new Date(sec * 1000);
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
}

// =========================================================================
// 콜보드 (URL ?callboard=1) — 대기실 공용 모니터. 공개·순번만(PII 없음).
// =========================================================================
let _cbRefresh = null;

function startCallboard() {
  showScreen('callboard-screen');
  loadCallboard();
  clearInterval(_cbRefresh);
  _cbRefresh = setInterval(loadCallboard, 2500);
}

// ── 콜보드 호출 음성(2026-10-13) ── 새 호출·재호출(호출 시각이 바뀜)을 알아채 "홍, 길동 님, 진료실로 들어가 주세요."
//  · 콜보드를 처음 열 때 이미 호출돼 있던 환자는 말하지 않는다(다시 열 때마다 몰아서 말하지 않게)
//  · 여러 명이 동시에 호출되면 한 명씩 차례로
let _cbSeen = null;          // key → 마지막으로 안내한 호출 시각
const _cbQueue = [];
let _cbSpeaking = false;
const _TWO_CHAR_SURNAMES = ['남궁', '황보', '제갈', '사공', '선우', '서문', '독고', '동방'];

/** "홍길동" → "홍, 길동 님" (복성 남궁·황보 등 처리). 한글 3~4자가 아니면 "{이름} 님". */
function callNameText(name) {
  const n = (name || '').trim();
  if (/\s/.test(n)) { const [a, ...b] = n.split(/\s+/); return `${a}, ${b.join(' ')} 님`; }
  if (!/^[가-힣]{2,5}$/.test(n)) return `${n} 님`;
  const sl = n.length >= 4 && _TWO_CHAR_SURNAMES.includes(n.slice(0, 2)) ? 2 : 1;
  return `${n.slice(0, sl)}, ${n.slice(sl)} 님`;
}

const _CALL_TAIL = {   // 호출 문장(이름 뒤). 이름이 한글이면 이름만 한국어 음성, 나머지는 접수 언어로
  en: 'please come into the examination room.',
  ja: '診察室にお入りください。',
  zh: '请进入诊室。',
};

/** 접수 언어에 맞춘 호출 안내 → [[문장, 음성언어], ...] (한 명분). */
function callParts(name, l) {
  const n = (name || '').trim();
  if (!_CALL_TAIL[l]) return [[`${callNameText(n)}, 진료실로 들어가 주세요.`, 'ko']];
  if (/[가-힣]/.test(n)) {          // 한글 이름은 외국어 음성 모델이 못 읽음 → 이름만 한국어로
    if (l === 'ja') {                // 일본어: "홍 길동"(한국어) + "さま、診察室に…"(일본어). 様는 '요-'로 읽힐 수 있어 가나로
      return [[callNameText(n).replace(/ 님$/, ''), 'ko'], [`さま、${_CALL_TAIL.ja}`, 'ja']];
    }
    const tail = l === 'en' ? 'Please come into the examination room.' : _CALL_TAIL[l];
    return [[callNameText(n), 'ko'], [tail, l]];
  }
  if (l === 'en') return [[`${n}, ${_CALL_TAIL.en}`, 'en']];
  if (l === 'ja') return [[`${n}様、${_CALL_TAIL.ja}`, 'ja']];
  return [[`${n}，${_CALL_TAIL.zh}`, 'zh']];
}

function announceCalls(data) {
  const now = new Map();
  (data.depts || []).forEach((d) => (d.items || []).forEach((it) => {
    if (it.status === 'called' && it.key) now.set(it.key, { at: it.calledAt || 0, name: it.name || '', lang: it.lang || 'ko' });
  }));
  if (_cbSeen === null) {                       // 첫 조회: 기준만 잡고 말하지 않음
    _cbSeen = new Map([...now].map(([k, v]) => [k, v.at]));
    return;
  }
  now.forEach((v, k) => {
    if (!_cbSeen.has(k) || v.at > _cbSeen.get(k)) {
      _cbSeen.set(k, v.at);
      if (v.name) _cbQueue.push(callParts(v.name, v.lang));
    }
  });
  speakCallQueue();
}

async function speakCallQueue() {
  if (_cbSpeaking) return;
  _cbSpeaking = true;
  try {
    while (_cbQueue.length) {           // 한 명분(문장 1~2개)을 차례로 — 접수한 언어로
      for (const [text, l] of _cbQueue.shift()) await robotController.speak(text, 'callboardCall', l, CALLBOARD_VOL);
    }
  } finally { _cbSpeaking = false; }
}

async function loadCallboard() {
  let data = { depts: [] };
  try { data = await (await fetch('/callboard')).json(); } catch (_) { return; }
  announceCalls(data);
  const box = document.getElementById('callboard-body');
  box.innerHTML = '';
  const depts = (data.depts || []).filter((d) => (d.items || []).length);
  if (!depts.length) {
    box.innerHTML = '<p class="callboard-empty">현재 호출된 환자가 없습니다</p>';
    return;
  }
  depts.forEach((d) => {
    const col = document.createElement('div');
    col.className = 'callboard-dept';
    const h = document.createElement('div');
    h.className = 'callboard-dept-name'; h.textContent = d.deptName;
    col.appendChild(h);
    d.items.forEach((it) => {
      const row = document.createElement('div');
      row.className = 'callboard-num ' + (it.status === 'in_progress' ? 'in-progress' : 'called');
      const left = document.createElement('span');
      left.className = 'callboard-left';
      const num = document.createElement('span');
      num.className = 'callboard-ticket'; num.textContent = `${it.ticket}번`;
      left.appendChild(num);
      if (it.name) {
        const nm = document.createElement('span');
        nm.className = 'callboard-name'; nm.textContent = it.name;
        left.appendChild(nm);
      }
      const st = document.createElement('span');
      st.className = 'callboard-status'; st.textContent = it.status === 'in_progress' ? '진료중' : '호출';
      row.appendChild(left); row.appendChild(st);
      col.appendChild(row);
    });
    box.appendChild(col);
  });
}

function init() {
  initDevInput();

  // 홈 2단계: 위치 안내 → 마이크 표시 / 접수 안내 → 초진·재진 흐름
  document.getElementById('loc-btn').addEventListener('click', showLocationMic);
  document.getElementById('intake-btn').addEventListener('click', startIntake);
  document.getElementById('mic-btn').addEventListener('click', startListening);

  // 접수: 환자 정보 폼 제출
  document.getElementById('patient-form').addEventListener('submit', (e) => {
    e.preventDefault();
    submitPatientForm();
  });
  // 입력 중이면 오류 표시 해제(f-rrn 세그먼트는 rrnSync, f-contact는 onPhoneInput이 처리)
  document.getElementById('f-name').addEventListener('input', (e) => {
    e.target.classList.remove('invalid');
    document.getElementById('form-msg').textContent = '';
  });
  // 전화번호 자동 하이픈(010-1234-5678) — 숫자만 입력해도 - 자동 생성
  document.getElementById('f-contact').addEventListener('input', onPhoneInput);
  // 접수: 문진 답변 타자 입력(intake 화면)
  document.getElementById('intake-form').addEventListener('submit', (e) => {
    e.preventDefault();
    const text = document.getElementById('intake-text').value.trim();
    if (!text) return;
    submitAnswer(text);             // 응급 선검사 → /interview 로 다음 질문/종합
  });

  // 접수 흐름 뒤로가기(값 보존): 폼→초진/재진 선택, 증상→폼
  document.getElementById('form-back').addEventListener('click', startIntake);
  document.getElementById('intake-back').addEventListener('click', () => {
    recognizer.cancel();
    startPatientForm((currentPatient && currentPatient.visitType) || 'first');
  });
  document.getElementById('yes-btn').addEventListener('click', confirmYes);
  document.getElementById('no-btn').addEventListener('click', resetToVoice);
  document.getElementById('done-btn').addEventListener('click', resetToVoice);
  document.getElementById('emg-call').addEventListener('click', emgCallStaff);

  // 무조작 자동 리셋: 설정 시간 로드 + 활동 감지 + "계속하기" 버튼
  document.getElementById('idle-continue').addEventListener('click', idleContinue);
  ['click', 'keydown', 'touchstart'].forEach((ev) =>
    document.addEventListener(ev, resetIdle, true));
  fetch('/config').then((r) => r.json()).then((c) => {
    if (c && c.idleSec) IDLE_MS = c.idleSec * 1000;
  }).catch(() => { /* 기본 60초 유지 */ });
  document.getElementById('admin-refresh').addEventListener('click', loadAdmin);
  // 예약 주민번호: 숫자만 입력해도 6자리 뒤 '-' 자동(최대 13자리)
  document.getElementById('adm-rrn').addEventListener('input', (e) => {
    const dg = e.target.value.replace(/\D/g, '').slice(0, 13);
    e.target.value = dg.length > 6 ? `${dg.slice(0, 6)}-${dg.slice(6)}` : dg;
  });
  document.getElementById('reservation-form').addEventListener('submit', (e) => {
    e.preventDefault();
    submitReservation();
  });
  // 탭 전환
  document.querySelectorAll('.admin-tab').forEach((t) => {
    t.addEventListener('click', () => showAdminPage(t.dataset.page));
  });
  // 정렬 버튼(환자/예약)
  document.querySelectorAll('.admin-sort').forEach((bar) => {
    const which = bar.dataset.for;   // 'patients' | 'reservations'
    bar.querySelectorAll('.sort-btn').forEach((btn) => {
      btn.addEventListener('click', () => {
        bar.querySelectorAll('.sort-btn').forEach((b) => b.classList.toggle('active', b === btn));
        if (which === 'patients') { _patSort = btn.dataset.sort; renderPatients(); }
        else { _resSort = btn.dataset.sort; renderReservations(); }
      });
    });
  });

  // data-nav="voice-screen" (취소·뒤로 등) → 홈 화면 복귀
  document.getElementById('app').addEventListener('click', (e) => {
    if (e.target.closest('[data-nav]')) resetToVoice();
  });

  // 층 표기를 config 값으로 표시 (지도 이미지엔 굽지 않음)
  document.getElementById('floor-badge').textContent = CONFIG.floor;

  // 간호사 관리 모드(?nurse=1): PIN 게이트 → 통과 시 대기명단 화면(5초 자동 새로고침).
  //  ?admin=1 은 예전 주소 — 당분간 같은 화면으로 받고 주소창만 ?nurse=1 로 바꿔 보여 준다(호환).
  //  (내부 이름 admin-screen/_adminPin/lockAdmin 등은 의사 화면과 공용이라 그대로 둔다)
  const _qs = new URLSearchParams(location.search);
  if (_qs.has('nurse') || _qs.has('admin')) {
    if (!_qs.has('nurse')) {
      _qs.delete('admin'); _qs.set('nurse', '1');
      try { history.replaceState(null, '', `${location.pathname}?${_qs}${location.hash}`); } catch (_) { /* 표시만 바꾸는 것 — 실패해도 무시 */ }
    }
    document.getElementById('gate-form').addEventListener('submit', submitGate);
    const adminEl = document.getElementById('admin-screen');
    adminEl.addEventListener('click', resetAdminIdle);
    adminEl.addEventListener('keydown', resetAdminIdle);
    initAdminGate();
    return;
  }

  // 의사 모드(?doctor=1): PIN 게이트(공통) → 진료과 선택 → 대기목록/진료진행.
  if (new URLSearchParams(location.search).has('doctor')) {
    document.getElementById('gate-form').addEventListener('submit', submitDoctorGate);
    const docEl = document.getElementById('doctor-screen');
    docEl.addEventListener('click', resetAdminIdle);
    docEl.addEventListener('keydown', resetAdminIdle);
    document.getElementById('doctor-switch').addEventListener('click', doctorSwitchDept);
    initDoctorGate();
    return;
  }

  // 콜보드 모드(?callboard=1): 공개 표시(순번만, PII 없음).
  if (new URLSearchParams(location.search).has('callboard')) {
    startCallboard();
    return;
  }

  // 언어(국기): 접이식 — 접힘 상태 탭=펼치기, 펼침 상태 탭=선택 후 접기
  const langBar = document.querySelector('.lang-bar');
  document.querySelectorAll('.lang-flag').forEach((f) => {
    f.addEventListener('click', (e) => {
      e.stopPropagation();
      if (!langBar.classList.contains('open')) { closeVolPanel(); langBar.classList.add('open'); return; }
      setLang(f.dataset.lang);
      langBar.classList.remove('open');
    });
  });
  // 바깥을 누르면 펼침 닫기
  document.addEventListener('click', () => langBar.classList.remove('open'));
  let savedLang = 'ko';
  try { savedLang = localStorage.getItem('uiLang') || 'ko'; } catch (_) { /* ignore */ }
  setLang(savedLang);
  initVolume();

  showHomeMenu();
  showScreen('voice-screen');
  setTimeout(prewarmSpeech, 3000);   // 고정 안내 음성을 TTS 서버에 미리 합성(첫 재생도 즉시)
  console.log('[app] 초기화 완료');
}

document.addEventListener('DOMContentLoaded', init);
