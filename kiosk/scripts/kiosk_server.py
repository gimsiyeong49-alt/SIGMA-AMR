#!/usr/bin/env python3
# =========================================================================
# kiosk_server.py — 정적 파일 서버 + STT 브리지 (같은 출처, CORS 불필요)
#
# - GET  *            : src/ 정적 파일 서빙 (기존 serve.sh 대체)
# - POST /listen      : stt_package로 1회 녹음+인식 → {text, locationId, confidence}
#     · 실제 인식은 whisper-server(127.0.0.1:8080)와 마이크가 필요.
#     · 테스트용: 바디 {"text":"원무과 어디예요"} 또는 ?text=... 를 주면
#       마이크 없이 매칭만 수행(파이프라인 검증용).
#
# 파이썬 표준 라이브러리만 사용 (추가 설치 없음). stt 소스는 sys.path로 import.
# =========================================================================

import re
import json
import os
import sys
import time
import array
import audioop
import select
import wave
import tempfile
from collections import deque
import hashlib
import hmac
import base64
import secrets
import subprocess
import threading
import http.server
import socketserver
import urllib.request
from pathlib import Path
from urllib.parse import urlparse, parse_qs

SRC_DIR = Path(__file__).resolve().parents[1] / "src"

# ── 실험 기록(2026-11-16, 논문 표 1·2 — scripts/experiment.py 가 읽음) ──
#  logs/experiment_events.jsonl 에 사건 한 줄씩: listen(위치 인식 결과)·recommend(진료과 추천)·nav(안내 시작)·register(접수 진료과).
#  ★ 개인정보·문장은 남기지 않는다(이름·주민번호·증상·인식 문장 없음) — 장소/진료과 id 와 시각만.
EXP_LOG = Path(__file__).resolve().parents[1] / "logs" / "experiment_events.jsonl"
_LAST_SPEECH_END = 0.0     # 마지막 녹음에서 '말이 끝난' 시각(녹음기가 마지막으로 목소리를 들은 순간)


def _exp_event(ev, **kw):
    try:
        rec = {"ev": ev, "t": round(time.time(), 3), **kw}
        line = json.dumps(rec, ensure_ascii=False)
        EXP_LOG.parent.mkdir(parents=True, exist_ok=True)
        with open(EXP_LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def _recent_speech_end(within=120.0):
    return round(_LAST_SPEECH_END, 3) if _LAST_SPEECH_END and time.time() - _LAST_SPEECH_END <= within else None
STT_SRC = Path("/mnt/ssd/cart_ros2/src/stt_package/stt/src")
LLM_SRC = Path("/mnt/ssd/cart_ros2/src/llm_package/llm/src")
MAP_LABELS = Path("/mnt/ssd/cart_ros2/src/hospital_mission/map/map_labels.json")

# nav 파일버스 (기존 nav_request_watcher 가 감시). 워처는 수정하지 않는다.
BUS = Path("/mnt/ssd/cart_ros2/src/llm_package/bus")
NAV_REQ_DIR = BUS / "nav_request"
NAV_DONE_DIR = BUS / "nav_request_done"      # 워처가 "goal 수락(이동 시작)" 시 이동 = 우리에겐 '이동 중'
NAV_FAILED_DIR = BUS / "nav_request_failed"  # nav_request_watcher엔 없지만 방어적으로 확인

# return_home_watcher(ROS 노드)가 기록하는 상태 파일.
#  이 서버는 stt의 .venv에서 돌아 rclpy가 없어 TF를 못 보므로,
#  "도착"은 오직 이 파일을 통해서만 알 수 있다. (state: moving/arrived/returning/idle)
ROBOT_STATUS_FILE = BUS / "kiosk_status.json"

# 환경변수(기본값 = 현재 운용값). stt CLI와 동일 키를 쓴다.
WHISPER_URL = os.environ.get("WHISPER_SERVER_URL", "http://127.0.0.1:8080/inference")
# MeloTTS 상주 서버(tts_server.py). 안내 문구를 로봇 스피커로 재생.
TTS_URL = os.environ.get("TTS_SERVER_URL", "http://127.0.0.1:5002/tts")
# TTS 허용 목록(대사 이름 한 줄에 하나, # 주석). 지정되면 목록에 있는 대사만 말한다(나머지 무음).
#  미지정(start_guide 등) = 전부 말함. 요청마다 다시 읽으므로 파일만 고치면 바로 반영.
TTS_ONLY_FILE = os.environ.get("TTS_ONLY_FILE", "")


def _tts_allowed(speak_id):
    if not TTS_ONLY_FILE:
        return True
    try:
        with open(TTS_ONLY_FILE, encoding="utf-8") as f:
            allow = {ln.split("#", 1)[0].strip() for ln in f} - {""}
    except OSError:
        return False            # 목록 파일이 없으면 전부 무음
    return speak_id in allow
STT_DEVICE = os.environ.get("STT_AUDIO_DEVICE", "plughw:0,0")
# 다채널 마이크(reSpeaker XVF3800 = 6ch: 0번 = DSP 처리 음성(에코 제거·노이즈 억제·AGC), 2~5번 = 마이크 원음)
#  → STT_CHANNELS 채널로 녹음해 STT_CHANNEL 번 채널만 뽑아 쓴다. 1채널 마이크는 1/0(예전과 동일). serve.sh가 자동 설정.
STT_CHANNELS = max(1, int(os.environ.get("STT_CHANNELS", "1") or 1))
STT_CHANNEL = min(max(0, int(os.environ.get("STT_CHANNEL", "0") or 0)), STT_CHANNELS - 1)
# 말소리 감지(VAD)용 채널. reSpeaker 0번(처리 음성)은 자동 게인(AGC)이 조용할 때 배경음을 키워 수준이 0.5초마다
#  150~1900으로 출렁여 기준을 못 잡는다 → 감지는 출렁임 없는 마이크 원음(2번)으로, 인식용 소리는 0번 그대로.
#  -1 이면 STT_CHANNEL 과 같은 채널(예전과 동일). serve.sh가 reSpeaker일 때 2로 설정.
_vad_ch = int(os.environ.get("STT_VAD_CHANNEL", "-1") or -1)
STT_VAD_CHANNEL = STT_CHANNEL if _vad_ch < 0 else min(_vad_ch, STT_CHANNELS - 1)


def _arecord_cmd(device, rate=16000, seconds=None):
    """마이크 녹음 명령(raw S16_LE). 다채널이면 STT_CHANNELS 로 녹음 — _pick_channel()로 한 채널만 꺼낸다."""
    cmd = ["arecord", "-D", device, "-f", "S16_LE", "-r", str(rate), "-c", str(STT_CHANNELS)]
    if seconds:
        cmd += ["-d", str(seconds)]
    return cmd + ["-t", "raw", "-q"]


def _pick_channel(data, ch=None):
    """다채널 인터리브 raw(S16_LE)에서 ch 번(기본 STT_CHANNEL) 채널만 모노로 꺼낸다. 1채널이면 그대로."""
    if STT_CHANNELS == 1:
        return data
    a = array.array("h")
    a.frombytes(data[: len(data) - (len(data) % (2 * STT_CHANNELS))])
    return a[(STT_CHANNEL if ch is None else ch)::STT_CHANNELS].tobytes()

# VAD 임계값. 마이크 게인에 따라 발화 RMS가 크게 달라져 고정값(예:500)은 취약하다.
#  · VAD_THRESHOLD 환경변수가 있으면 그 값으로 고정.
#  · 없으면 매 녹음 직전 주변음을 측정해 자동 보정한다(_resolve_vad_threshold).
VAD_THRESHOLD_ENV = os.environ.get("VAD_THRESHOLD")

# whisper 초기 프롬프트(어휘 힌트). 병원 진료과명 같은 도메인 단어를 미리 알려주면
# 오인식이 크게 줄어든다(예: 원목과→원무과, 내권/내꽝→내과). WHISPER_PROMPT로 교체 가능.
WHISPER_PROMPT = os.environ.get(
    "WHISPER_PROMPT", "산부인과 내과 외과 영상의학과 소아청소년과 마취통증의학과 진단검사의학과 화장실 접수 수납 진료실 안내"
)

# map_labels.json 존 name → 앱 locations.js 의 장소 id (및 역방향)
# ※ 원무과는 안내도 라벨로만 표기하고 목적지 대상이 아니므로 매칭에 넣지 않는다.
NAME_TO_ID = {"산부인과": "wonmu", "내과": "internal", "외과": "surgery", "영상의학과": "pharmacy", "소아청소년과": "pediatric", "마취통증의학과": "pain", "진단검사의학과": "labmed", "화장실": "toilet"}
ID_TO_NAME = {v: k for k, v in NAME_TO_ID.items()}

# 폴백 별칭(및 map_labels.json에 아직 없는 약국) → id
# ※ llm_package 매칭이 실패하거나 map_labels에 없는 장소를 위한 안전망.
EXTRA_ALIASES = {
    "산부인과": "wonmu",
    "영상의학과": "pharmacy",
    "내과": "internal",
    "외과": "surgery",
    "소아청소년과": "pediatric",
    "마취통증의학과": "pain",
    "진단검사의학과": "labmed",
    "화장실": "toilet", "변소": "toilet", "화장실이": "toilet",
}

# 영·일·중 장소 이름(src/js/data/locations.js의 name_en/ja/zh + 흔한 표현) → LLM이 꺼져도 외국어 매칭(2026-10-13)
_FOREIGN_ALIASES = {
    "wonmu": ["obstetrics and gynecology", "obstetrics", "gynecology", "ob-gyn", "obgyn", "産婦人科", "婦人科", "妇产科", "妇科"],
    "pharmacy": ["radiology", "x-ray", "放射線科", "レントゲン", "放射科"],
    "pain": ["anesthesiology and pain medicine", "pain medicine", "pain clinic", "麻酔科・ペインクリニック",
             "ペインクリニック", "麻酔科", "麻醉疼痛科", "疼痛科"],
    "labmed": ["laboratory medicine", "laboratory", "臨床検査科", "検査科", "检验科"],
    "toilet": ["restroom", "bathroom", "toilet", "washroom", "お手洗い", "トイレ", "洗手间", "卫生间", "厕所"],
    "internal": ["internal medicine", "内科"],
    "surgery": ["general surgery", "surgery", "外科"],
    "pediatric": ["pediatrics", "pediatric", "小児科", "儿科"],
}
# 긴 표현부터 비교(예: '産婦人科'가 '婦人科'보다, 'pain medicine'이 'pain'보다 먼저)
_FOREIGN_ALIAS_LIST = sorted(((a.lower(), i) for i, al in _FOREIGN_ALIASES.items() for a in al),
                             key=lambda x: -len(x[0]))

# ── STT 언어(2026-10-13): 화면에서 고른 언어로 Whisper 인식(예전엔 language=ko 고정) ──
#  Whisper medium은 다국어 모델이라 언어 코드만 바꾸면 된다. 초기 프롬프트도 그 언어의 장소 이름으로.
STT_LANGS = {"ko", "en", "ja", "zh"}
WHISPER_PROMPTS = {
    "ko": WHISPER_PROMPT,
    "en": "Internal Medicine, General Surgery, Obstetrics and Gynecology, Pediatrics, "
          "Anesthesiology and Pain Medicine, Radiology, Laboratory Medicine, Restroom, reception.",
    "ja": "内科、外科、産婦人科、小児科、麻酔科・ペインクリニック、放射線科、臨床検査科、お手洗い、受付。",
    "zh": "内科、外科、妇产科、儿科、麻醉疼痛科、放射科、检验科、洗手间、挂号。",
}

# ── LLM 매칭 폴백 (규칙으로 못 잡은 발화를 OpenAI로 장소 id에 매핑) ──
#  · start_ui.sh 에서만 켜짐: LLM_MATCH_ENABLE=1 + OPENAI_API_KEY. 그 외엔 규칙매칭만.
#  · 모델 교체: OPENAI_MODEL 환경변수(기본 gpt-4o-mini).
LLM_MATCH_ENABLE = os.environ.get("LLM_MATCH_ENABLE", "0") == "1"
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")


def _openai_classify(system, text, valid):
    """OpenAI Responses API로 text를 valid(id 집합) 중 하나로 분류. 실패/비활성/키없음/무효 → None."""
    if not LLM_MATCH_ENABLE:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    payload = {"model": OPENAI_MODEL, "instructions": system, "input": text,
               "temperature": 0, "max_output_tokens": 20}
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as r:
            result = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as exc:
        print(f"[kiosk] LLM 분류 실패: {exc}", flush=True)
        return None
    out = (result.get("output_text") or "").strip()
    if not out:
        for item in result.get("output", []):
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    out = c["text"].strip(); break
    out = out.strip().strip('.\'"').lower()
    return out if out in valid else None


def _openai_match(text):
    """규칙매칭 실패 발화 → 장소 id (동의어/부분명/오인식 흡수). 비활성·키없음·실패 시 None."""
    places = ", ".join(f"{n}={i}" for n, i in NAME_TO_ID.items())
    system = (
        "너는 병원 안내 키오스크의 장소 분류기다. 사용자의 발화를 아래 장소 중 정확히 "
        "하나의 id로 매핑한다. 동의어·부분명칭·오인식·뜻이 같은 말도 매핑한다"
        "(예: '청소년과'->pediatric, '엑스레이/방사선'->pharmacy, '애기 진료'->pediatric, "
        "'변소/토일렛'->toilet). 영어 발화도 같은 방식으로 매핑한다"
        "(예: 'radiology/x-ray'->pharmacy, 'pediatrics'->pediatric, 'restroom/toilet'->toilet, "
        "'internal medicine'->internal, 'surgery'->surgery, 'OB-GYN/obstetrics'->wonmu, "
        "'pain'->pain, 'laboratory'->labmed). 일본어 발화도 같은 방식으로 매핑한다"
        "(예: '放射線科/レントゲン'->pharmacy, '小児科/子供'->pediatric, 'お手洗い/トイレ'->toilet, "
        "'内科'->internal, '外科'->surgery, '産婦人科'->wonmu, '麻酔科/ペイン'->pain, "
        "'臨床検査/検査科'->labmed). 중국어(간체) 발화도 같은 방식으로 매핑한다"
        "(예: '放射科/拍片'->pharmacy, '儿科/小孩'->pediatric, '洗手间/厕所'->toilet, "
        "'内科'->internal, '外科'->surgery, '妇产科'->wonmu, '麻醉/疼痛'->pain, "
        "'检验科/化验'->labmed). 해당 장소가 없으면 정확히 NONE 이라고만 답한다. "
        "설명 없이 id 또는 NONE 한 단어만 출력한다.\n"
        f"장소(이름=id): {places}"
    )
    out = _openai_classify(system, text, set(NAME_TO_ID.values()))
    if out:
        print(f"[kiosk] LLM 매칭: {text!r} -> {out}", flush=True)
    return out


# ── 증상 → 진료과(트리아지) : S-04 수속 안내 ──
# 직접 접수하는 진료과만 대상(영상의학과·진단검사의학과는 타과 의뢰라 제외).
TRIAGE_IDS = {"internal", "surgery", "wonmu", "pediatric", "pain"}
# 순서 중요: 대상(소아/부인과)을 먼저 보고, 그다음 부위·증상. 내과는 일반 증상의 마지막 캐치.
_TRIAGE_RULES = [
    (("아이", "애기", "아기", "소아", "유아", "아들", "딸", "청소년", "우리 애"), "pediatric"),
    (("임신", "생리", "월경", "산부", "부인과", "출산", "자궁", "난소"), "wonmu"),
    (("상처", "베였", "찢어", "골절", "삐", "부러", "외상", "혹", "종기", "탈장", "다쳤", "피가", "찔", "화상"), "surgery"),
    (("허리", "어깨", "무릎", "관절", "신경통", "저림", "디스크", "만성 통증", "결림"), "pain"),
    (("열", "발열", "감기", "기침", "콧물", "가래", "인후", "목감기", "소화", "체했", "복통", "배가", "설사",
      "변비", "어지", "혈압", "당뇨", "몸살", "두통", "머리", "메스꺼", "구역"), "internal"),
]


def _triage_keyword(text):
    """증상 키워드 규칙(무료). 못 정하면 None."""
    for kws, dep in _TRIAGE_RULES:
        if any(k in text for k in kws):
            return dep
    return None


# 응급 키워드(KTAS 1~2, 4개국어) — 트리아지보다 먼저 규칙으로 검사(서버 안전망).
_EMERGENCY_KW = [
    # 한국어
    "의식이 없", "의식 잃", "의식을 잃", "쓰러졌", "쓰러져", "기절", "정신을 잃", "반응이 없",
    "숨을 못 쉬", "숨이 안 쉬", "숨쉬기 힘", "호흡곤란",
    "가슴이 심하게", "가슴이 찢", "가슴이 조여", "심한 흉통", "가슴을 쥐어짜",
    "갑자기 머리가 심하게", "심한 두통",
    "배가 찢어질", "심한 복통", "참을 수 없는 복통",
    "피를 토", "토혈", "대량 출혈", "출혈이 심", "하혈",
    "한쪽 힘이 빠", "반신마비", "반신불수", "얼굴이 돌아가", "말이 어눌",
    "몸이 마비", "마비가 왔", "마비됐", "마비돼",
    "경련", "발작", "뇌전증", "심장이 멈", "심정지", "맥박이 없", "심장마비",
    "응급", "위독", "119",
    # English
    "unconscious", "passed out", "collapsed", "fainted", "unresponsive",
    "can't breathe", "cannot breathe", "can not breathe", "difficulty breathing", "short of breath", "choking",
    "severe chest pain", "crushing chest pain", "chest tightness", "heart attack",
    "sudden severe headache", "worst headache", "thunderclap headache",
    "severe abdominal pain", "unbearable stomach pain",
    "vomiting blood", "coughing up blood", "heavy bleeding",
    "paralysis", "one side weak", "face drooping", "slurred speech", "stroke",
    "seizure", "convulsion", "convulsing", "cardiac arrest", "no pulse", "heart stopped",
    "emergency", "dying", "call 911",
    # 日本語
    "意識がない", "意識を失", "倒れた", "気を失", "反応がない",
    "息ができない", "息苦しい", "呼吸困難", "息が止ま",
    "激しい胸の痛み", "胸が締め付け", "心臓発作",
    "突然の激しい頭痛", "割れるような頭痛", "激しい頭痛",
    "激しい腹痛", "耐えられない腹痛",
    "血を吐", "吐血", "大量出血", "出血がひどい", "血が止まらない",
    "麻痺", "片側が動かない", "半身麻痺", "半身不随", "ろれつが回らない",
    "けいれん", "発作", "ひきつけ", "心停止", "心臓が止ま", "脈がない",
    "救急", "緊急", "死にそう",
    # 中文
    "昏迷", "失去意识", "晕倒", "昏倒", "不省人事",
    "无法呼吸", "呼吸困难", "喘不过气", "憋气",
    "剧烈胸痛", "胸口剧痛", "胸闷得厉害", "心脏病发作",
    "突然剧烈头痛", "头痛欲裂", "剧烈头痛",
    "剧烈腹痛", "肚子剧痛", "腹部剧烈疼痛",
    "吐血", "咯血", "大量出血", "出血不止",
    "瘫痪", "半身不遂", "一侧无力", "嘴歪", "说话不清", "中风",
    "抽搐", "惊厥", "痉挛", "抽风", "心跳停止", "心脏骤停", "没有脉搏",
    "急救", "危急", "快不行了",
]
_EMERGENCY_RE = re.compile("|".join(re.escape(k) for k in _EMERGENCY_KW), re.IGNORECASE)


def is_emergency(text):
    """응급 기능 제거(2026-09) — 항상 False. 키워드(_EMERGENCY_KW)는 보존하되 미사용."""
    return False


def _triage_match(text):
    """증상 텍스트 → 진료과 id. 키워드 규칙 우선, 실패 시 LLM 폴백(start_ui 전용). 애매하면 None."""
    if not text:
        return None
    dep = _triage_keyword(text)
    if dep:
        return dep
    system = (
        "너는 병원 접수 도우미다. 환자가 말한 증상을 듣고 아래 진료과 중 하나의 id로 분류한다. "
        "내과=internal(감기·발열·기침·소화불량·복통·두통·고혈압·당뇨 등 내과 질환), "
        "외과=surgery(베인 상처·외상·골절·삐끗·종기·탈장 등), "
        "산부인과=wonmu(임신·생리·부인과), "
        "소아청소년과=pediatric(영유아·아동·청소년 진료), "
        "마취통증의학과=pain(허리·목·어깨·관절 등 만성 통증·신경통). "
        "판단이 애매하거나 응급이면 정확히 NONE. 설명 없이 id 또는 NONE 한 단어만 출력한다."
    )
    out = _openai_classify(system, text, TRIAGE_IDS)
    if out:
        print(f"[kiosk] 트리아지: {text!r} -> {out}", flush=True)
    return out


# ── AI 대화형 문진 (사이클8) : /interview · /interview/summarize ──────────────
# 안전: 환자 답변은 LLM 호출 전에 is_emergency()(KTAS 키워드, 위에서 재사용)로 선검사.
# AI는 진단·병명·약을 말하지 않는다(프롬프트 명시 + 응급은 코드필터로 이중 방어).
# 꼬리질문 개수 상한은 서버·클라이언트 양쪽에서 강제. 서버는 무상태(대화는 클라가 보유).
MAX_FOLLOWUPS = 2                       # 꼬리질문 최대 개수(첫 증상 뒤 최대 2 → 총 3턴)
_LANG_NAME = {"ko": "한국어", "en": "English", "ja": "日本語", "zh": "中文"}


def _openai_text(system, user, max_tokens=220, temperature=0.2):
    """자유 서술형 출력용 LLM 호출(문진 질문/요약). 비활성·키없음·실패 시 None."""
    if not LLM_MATCH_ENABLE:
        return None
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        return None
    payload = {"model": OPENAI_MODEL, "instructions": system, "input": user,
               "temperature": temperature, "max_output_tokens": max_tokens}
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            result = json.loads(r.read().decode("utf-8", "ignore"))
    except Exception as exc:
        print(f"[kiosk] LLM 문진 호출 실패: {exc}", flush=True)
        return None
    out = (result.get("output_text") or "").strip()
    if not out:
        for item in result.get("output", []):
            for c in item.get("content", []):
                if c.get("type") in ("output_text", "text") and c.get("text"):
                    out = c["text"].strip(); break
    return out or None


def _parse_json_obj(s):
    """LLM 출력에서 JSON 객체 추출(코드펜스/잡텍스트 허용). 실패 시 None."""
    if not s:
        return None
    s = s.strip()
    if s.startswith("```"):
        s = s.strip("`")
        if s[:4].lower() == "json":
            s = s[4:]
    try:
        return json.loads(s)
    except Exception:
        pass
    m = re.search(r"\{.*\}", s, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            return None
    return None


def _transcript(messages):
    """[{role,text}] → 전사 문자열. role: user=환자 / assistant=도우미."""
    lines = []
    for m in messages or []:
        who = "환자" if m.get("role") == "user" else "도우미"
        t = (m.get("text") or "").strip()
        if t:
            lines.append(f"[{who}] {t}")
    return "\n".join(lines)


def _patient_texts(messages):
    """환자(user) 발화만 이어붙임(응급 재검사·트리아지 입력용)."""
    return " ".join((m.get("text") or "").strip()
                    for m in (messages or []) if m.get("role") == "user").strip()


def _last_user_text(messages):
    for m in reversed(messages or []):
        if m.get("role") == "user":
            return (m.get("text") or "").strip()
    return ""


def _interview_prompt(lang, asked=0):
    lang_name = _LANG_NAME.get(lang, "한국어")
    remaining = max(1, MAX_FOLLOWUPS - asked)
    return (
        "너는 한국 병원의 '접수 문진 도우미'다. 의사가 아니다. "
        "환자를 어느 진료과로 접수할지 정하는 데 필요한 핵심 정보를 최소한의 질문으로 모은다.\n"
        "[진료과] 내과(감기·발열·소화·복통·두통·어지럼·만성질환), 외과(상처·외상·골절·삠·화상), "
        "산부인과(임신·생리·부인과), 소아청소년과(아동), 마취통증의학과(허리·목·어깨·관절 등 통증).\n"
        "[언제 질문하고 언제 끝낼지 — 가장 중요]\n"
        "- 기본 동작은 '마침(done)'이다. 질문은 꼭 필요할 때만 한다. 다음 중 하나일 때만 질문한다: "
        "(1) 환자 답이 모호해 무슨 증상인지 불분명 (2) 가능한 진료과가 둘 이상이라 하나로 안 좁혀짐 "
        "(3) 놓치면 위험한 신호(응급 가능성) 확인이 필요.\n"
        "- 첫 답변만으로 진료과가 분명하면 추가 질문 없이 즉시 done. "
        "예) '발목을 접질렀어요'→외과 확정→done, '무릎이 예전부터 아파요'→마취통증의학→done, "
        "'생리가 불규칙해요'→산부인과→done, '손을 베였어요'→외과→done. "
        "확신이 서면 남은 질문이 있어도 곧바로 done 한다.\n"
        "[질문할 때 규칙]\n"
        "- 이미 말했거나 그로부터 자명한 것은 절대 다시 묻지 않는다"
        "(예: '머리가 아파요'면 부위는 머리 → 부위 재질문 금지). "
        "진료과 구분에 무의미한 세부도 묻지 않는다(예: 두통의 앞/옆/뒤통수 위치).\n"
        "- 진료과 구분·위험신호에 가장 결정적인 것 하나만 고른다. 대개 유용한 순서: "
        "① 동반 증상(열·구토·저림·시야 이상·호흡·출혈·어지럼 등) "
        "② 발병 시점·경과(언제부터, 갑자기/서서히, 악화 여부) "
        "③ 대상(성인/아이) ④ 외상·임신·만성 여부.\n"
        "- 답하기 쉬운 '구체적' 질문으로. 한 번에 질문 하나만. "
        f"남은 질문은 {remaining}개.\n"
        "[좋은 예] '머리가 아파요'→'열이나 메스꺼움, 시야 이상 같은 다른 증상도 함께 있나요?' / "
        "'배가 아파요'→'윗배와 아랫배 중 어디가, 언제부터 아프세요?' / "
        "'다쳤어요'→'어디를 어떻게 다치셨어요? (베임/부딪힘/삠 등)' / "
        "'무릎이 아파요'→'다쳐서 그런가요, 아니면 오래전부터 아팠나요?'\n"
        "[나쁜 예] 이미 부위를 말했는데 부위를 또 물음 / 진료과 구분에 영향 없는 세부 캐묻기 / "
        "진단적이거나 모호한 질문.\n"
        "[안전 — 최우선] 진단·병명 추정·질환 설명·약·처방·치료법·검사 해석·예후·위험도 판단 금지. "
        "환자가 '무슨 병이에요?/약 뭐 먹어요?/심각한가요?'라고 물어도 답하지 말고, "
        "'진단과 처방은 의료진이 해드려요. 접수를 도와드릴게요.'라고 안내한 뒤 필요한 질문을 잇는다.\n"
        f"[언어] 반드시 {lang_name}로만 답한다.\n"
        "[출력 — JSON 한 줄만. 다른 텍스트 절대 금지]\n"
        "- 더 물을 것: {\"action\":\"ask\",\"question\":\"<다음 질문>\"}\n"
        "- 정보 충분: {\"action\":\"done\"}"
    )


def interview_next(lang, messages):
    """다음 문진 행동 결정. 꼬리질문 상한 처리 후 LLM. (응급 기능 제거)"""
    asked = sum(1 for m in (messages or []) if m.get("role") == "assistant")
    if asked >= MAX_FOLLOWUPS:                   # 꼬리질문 상한 → 종합으로
        return {"action": "done"}
    obj = _parse_json_obj(_openai_text(_interview_prompt(lang, asked), _transcript(messages),
                                       max_tokens=120)) or {}
    if obj.get("action") == "ask":
        q = (obj.get("question") or "").strip()
        if q:
            return {"action": "ask", "question": q}
    return {"action": "done"}                     # 무효/실패/충분 → 안전하게 종합


def interview_summarize(lang, messages):
    """대화 전체 → 추천 진료과 id(기존 트리아지 재사용) + 한국어 요약 + 환자언어 리캡."""
    patient_text = _patient_texts(messages)
    if is_emergency(patient_text):               # 방어: 종합 단계에서도 응급 재확인
        return {"emergency": True}
    dep = _triage_match(patient_text)            # 기존 트리아지 매칭 그대로 재사용
    lang_name = _LANG_NAME.get(lang, "한국어")
    system = (
        "너는 한국 병원 접수 도우미다. 아래 접수 문진 대화를 바탕으로 두 가지를 만든다. "
        "진단·병명·약은 절대 쓰지 말고, 환자가 말한 사실만 정리한다.\n"
        "1) summary_ko: 의료진용 한국어 증상 요약. 있는 정보만 짧게"
        "(주요 증상/부위/발병 시기/양상/동반 증상/대상 중 해당되는 것만), 마지막에 한 문장 요약. 추측 금지.\n"
        f"2) recap: 환자 확인용 1~2문장 요약, 반드시 {lang_name}로.\n"
        "출력은 JSON 한 줄만: {\"summary_ko\":\"...\",\"recap\":\"...\"}"
    )
    obj = _parse_json_obj(_openai_text(system, _transcript(messages), max_tokens=300)) or {}
    summary_ko = (obj.get("summary_ko") or "").strip() or patient_text
    recap = (obj.get("recap") or "").strip() or summary_ko
    return {"emergency": False, "locationId": dep, "summaryKo": summary_ko, "recap": recap}


# =========================================================================
# S-04 접수 저장소. 관심사를 3개 파일로 분리(한쪽을 지워도 다른 쪽 안전).
#   · patients.json     — 환자 등록 정보만: {patients:[{name, rrn_masked, rrn_hash, contact, ...}]}
#   · reservations.json — 예약(별도 관리): {reservations:{rrn_hash:{name, rrn_masked, dept, created_at}}}
#   · waitlist.json      — 진료과별 대기명단: {dept_id:[{id, name, rrn_masked, visit_type, symptom, added_at}]}
#   주민번호는 평문 저장 금지: 매칭용 해시(rrn_hash) + 표시용 마스킹(rrn_masked)만 저장.
# =========================================================================
DATA_DIR = Path(__file__).resolve().parents[1] / "data"
PATIENTS_FILE = DATA_DIR / "patients.json"
RESERVATIONS_FILE = DATA_DIR / "reservations.json"
WAITLIST_FILE = DATA_DIR / "waitlist.json"
_data_lock = threading.Lock()

# 관리자(간호사) PIN. 설정돼 있으면 admin 데이터/동작 엔드포인트가 X-Admin-Pin 헤더를 요구.
# 비어 있으면(미설정) 개방(dev). start_ui.sh가 .admin_pin 또는 기본값으로 넣는다.
ADMIN_PIN = os.environ.get("ADMIN_PIN", "")
# 무조작 자동 리셋 시간(초). 환경변수 KIOSK_IDLE_SEC 로 조절. 클라이언트가 /config로 읽음.
KIOSK_IDLE_SEC = int(os.environ.get("KIOSK_IDLE_SEC", "60"))
# PIN이 필요한(민감) 엔드포인트 — 환자용(add/status/check/register/triage/listen)은 제외.
ADMIN_PATHS = {"/patient/remove", "/reservation/set", "/reservation/remove",
               "/waitlist/remove", "/waitlist/call", "/waitlist/done",
               "/waitlist/start", "/waitlist/memo"}


def _load_json(path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _save_json(path, obj):
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)   # 원자적 교체


def _rrn_digits(rrn):
    return "".join(ch for ch in (rrn or "") if ch.isdigit())


def _rrn_mask(digits):
    """주민번호 표시용 마스킹: 앞 6자리 + 성별자리 + 나머지 * (예: 900101-1******)."""
    if len(digits) >= 7:
        return f"{digits[:6]}-{digits[6]}{'*' * (len(digits) - 7)}"
    return (digits[:6] + "*" * max(0, len(digits) - 6)) or "******"


def _rrn_hash(digits):
    return hashlib.sha256(digits.encode("utf-8")).hexdigest() if digits else ""


# ── 주민번호 전체값 암호화(의료진 admin 표시용) ──────────────────────────
# 정책: 평문 저장 금지. 전체 주민번호는 기기 로컬 키로 '암호화'해서만 저장하고,
# PIN 인증된 admin 조회 때만 복호화해 보여준다(공개 화면·매칭엔 여전히 마스킹/해시 사용).
# 키가 없으면 암호화 비활성(rrn_enc 빈값) → admin은 마스킹으로 폴백.
# 구현: HMAC-SHA256 기반 CTR 키스트림 + 인증(encrypt-then-MAC). 외부 의존성 없음.
RRN_KEY_FILE = Path(__file__).resolve().parents[1] / ".rrn_key"


def _rrn_key():
    try:
        if RRN_KEY_FILE.exists():
            return base64.b64decode(RRN_KEY_FILE.read_text().strip())
        k = secrets.token_bytes(32)
        RRN_KEY_FILE.write_text(base64.b64encode(k).decode())
        try:
            os.chmod(RRN_KEY_FILE, 0o600)
        except OSError:
            pass
        return k
    except Exception:
        return None


def _rrn_keystream(key, nonce, n):
    ks = b""
    ctr = 0
    while len(ks) < n:
        ks += hmac.new(key, nonce + ctr.to_bytes(8, "big"), hashlib.sha256).digest()
        ctr += 1
    return ks[:n]


def _rrn_encrypt(digits):
    """전체 주민번호(숫자) → 기기키로 암호화한 base64. 키/값 없으면 ''."""
    key = _rrn_key()
    if not key or not digits:
        return ""
    data = digits.encode("utf-8")
    nonce = secrets.token_bytes(16)
    ct = bytes(a ^ b for a, b in zip(data, _rrn_keystream(key, nonce, len(data))))
    mac = hmac.new(key, b"rrn1" + nonce + ct, hashlib.sha256).digest()[:16]
    return base64.b64encode(b"rrn1" + nonce + mac + ct).decode()


def _rrn_decrypt(token):
    """_rrn_encrypt 역변환. 실패/키없음/변조 → None."""
    key = _rrn_key()
    if not key or not token:
        return None
    try:
        raw = base64.b64decode(token)
        if raw[:4] != b"rrn1":
            return None
        nonce, mac, ct = raw[4:20], raw[20:36], raw[36:]
        if not hmac.compare_digest(mac, hmac.new(key, b"rrn1" + nonce + ct, hashlib.sha256).digest()[:16]):
            return None
        return bytes(a ^ b for a, b in zip(ct, _rrn_keystream(key, nonce, len(ct)))).decode("utf-8")
    except Exception:
        return None


def _find_patient(patients, rrn_hash):
    return next((p for p in patients if p.get("rrn_hash") and p["rrn_hash"] == rrn_hash), None)


def _norm_name(s):
    """이름 비교용 정규화(공백 제거·소문자)."""
    return "".join((s or "").split()).lower()


def _rrn_masked_from(rrn):
    """입력(앞6+성별1=7자리 이상)에서 저장 포맷과 동일한 마스킹값 생성: 900101-1******.
    재진은 앞7자리만 입력받으므로 뒷 6자리는 항상 * (13자리 입력도 동일 결과)."""
    d = _rrn_digits(rrn)
    if len(d) < 7:
        return None
    return f"{d[:6]}-{d[6]}" + "*" * 6


def patient_check(name, rrn):
    """재진 본인확인: 데이터셋에 (앞7자리 마스킹값)일치 환자가 있는지 + 이름 일치 여부.
    재진은 앞6+성별1만 입력하므로 전체 해시가 아닌 마스킹값으로 대조한다.
    반환: {found, nameMatch}. 개인정보 보호 위해 저장된 이름은 반환하지 않는다."""
    masked = _rrn_masked_from(rrn)
    if not masked:
        return {"found": False, "nameMatch": False}
    with _data_lock:
        patients = _load_json(PATIENTS_FILE, {"patients": []}).get("patients", [])
    matches = [p for p in patients if p.get("rrn_masked") == masked]
    if not matches:
        return {"found": False, "nameMatch": False}
    return {"found": True,
            "nameMatch": any(_norm_name(p.get("name")) == _norm_name(name) for p in matches)}


# ── 환자 데이터셋(등록 전용) ──────────────────────────────────────────────
def patient_register(name, rrn, contact):
    """초진 등록(신규 생성 또는 기존 갱신). 이름·주민번호·연락처만 저장."""
    digits = _rrn_digits(rrn)
    h = _rrn_hash(digits)
    now = time.time()
    with _data_lock:
        data = _load_json(PATIENTS_FILE, {"patients": []})
        patients = data.setdefault("patients", [])
        p = _find_patient(patients, h)
        returning = p is not None
        enc = _rrn_encrypt(digits)                 # 전체 주민번호 암호화(admin 표시용). 키 없으면 ''
        if p is None:
            p = {"name": name, "rrn_masked": _rrn_mask(digits), "rrn_hash": h,
                 "rrn_enc": enc, "contact": contact or "", "created_at": now, "updated_at": now}
            patients.append(p)
        else:
            p["name"] = name or p.get("name", "")
            if enc:
                p["rrn_enc"] = enc                 # 재등록 시 암호화값 backfill/갱신
            if contact:
                p["contact"] = contact
            p["updated_at"] = now
        _save_json(PATIENTS_FILE, data)
        return {"ok": True, "isReturning": returning}


def patient_count():
    with _data_lock:
        return len(_load_json(PATIENTS_FILE, {"patients": []}).get("patients", []))


def patient_list():
    """등록 환자 목록(admin 표시용, PIN 보호). 의료진용이라 전체 주민번호(복호화)를 함께 제공.
    rrn_full=복호화 성공 시 전체(예 900101-1234567), 실패/구데이터면 ''(→클라가 마스킹 폴백)."""
    with _data_lock:
        data = _load_json(PATIENTS_FILE, {"patients": []})
    out = []
    for p in data.get("patients", []):
        dec = _rrn_decrypt(p.get("rrn_enc", ""))
        full = ""
        if dec and len(dec) >= 7:
            full = f"{dec[:6]}-{dec[6:]}"           # 900101-1234567 형태로 표시
        out.append({"name": p.get("name", ""), "rrn_masked": p.get("rrn_masked", ""),
                    "rrn_full": full, "rrn_hash": p.get("rrn_hash", ""),
                    "contact": p.get("contact", "")})
    return out


def patient_remove(rrn_hash):
    """admin: 등록 환자 삭제(rrn_hash로)."""
    with _data_lock:
        data = _load_json(PATIENTS_FILE, {"patients": []})
        arr = data.get("patients", [])
        n0 = len(arr)
        data["patients"] = [p for p in arr if p.get("rrn_hash") != rrn_hash]
        _save_json(PATIENTS_FILE, data)
        return {"ok": True, "removed": n0 - len(data["patients"])}


# ── 예약 관리(별도 파일) ─────────────────────────────────────────────────
def reservation_set(name, rrn, dept_id, symptom="", date=""):
    """간호사(admin)가 예약을 기록(예약 날짜·증상 포함). 데이터셋에서 연락처만 복사(파일 미변경)."""
    if dept_id not in ID_TO_NAME:
        return {"ok": False, "error": f"알 수 없는 진료과: {dept_id}"}
    digits = _rrn_digits(rrn)
    h = _rrn_hash(digits)
    if not h:
        return {"ok": False, "error": "주민번호가 필요합니다."}
    with _data_lock:
        pdata = _load_json(PATIENTS_FILE, {"patients": []})
        pp = _find_patient(pdata.get("patients", []), h)
        contact = pp.get("contact", "") if pp else ""      # 데이터셋에 있으면 연락처 복사
        data = _load_json(RESERVATIONS_FILE, {"reservations": {}})
        res = data.setdefault("reservations", {})
        res[h] = {"name": name, "rrn_masked": _rrn_mask(digits), "contact": contact,
                  "dept": dept_id, "symptom": symptom or "", "date": date or "",
                  "created_at": time.time()}
        _save_json(RESERVATIONS_FILE, data)
        return {"ok": True, "deptName": ID_TO_NAME[dept_id], "name": name}


def reservation_check(rrn, name=""):
    """재진: 예약 여부 조회(앞7자리 마스킹값 + 이름 기준). 반환: {reservation, ...}."""
    masked = _rrn_masked_from(rrn)
    with _data_lock:
        res = _load_json(RESERVATIONS_FILE, {"reservations": {}}).get("reservations", {})
    if masked:
        for r in res.values():
            if r.get("rrn_masked") == masked and _norm_name(r.get("name")) == _norm_name(name):
                dep = r.get("dept")
                return {"reservation": dep, "reservationName": ID_TO_NAME.get(dep, dep),
                        "reservationSymptom": r.get("symptom", ""), "name": r.get("name")}
    return {"reservation": None, "reservationName": None, "reservationSymptom": "", "name": None}


def reservation_clear(rrn_hash):
    """예약 소비/삭제(admin: 전체 해시 키로)."""
    with _data_lock:
        data = _load_json(RESERVATIONS_FILE, {"reservations": {}})
        res = data.get("reservations", {})
        if rrn_hash in res:
            del res[rrn_hash]
            _save_json(RESERVATIONS_FILE, data)
            return True
        return False


def reservation_clear_match(rrn, name):
    """재진 자동등록 후 예약 소비(앞7자리 마스킹값 + 이름 기준). 해당 예약 삭제."""
    masked = _rrn_masked_from(rrn)
    if not masked:
        return False
    with _data_lock:
        data = _load_json(RESERVATIONS_FILE, {"reservations": {}})
        res = data.get("reservations", {})
        keys = [k for k, r in res.items()
                if r.get("rrn_masked") == masked and _norm_name(r.get("name")) == _norm_name(name)]
        for k in keys:
            del res[k]
        if keys:
            _save_json(RESERVATIONS_FILE, data)
        return bool(keys)


def reservation_list():
    """예약 목록(admin 표시용). 각 항목에 삭제용 rrn_masked 포함."""
    with _data_lock:
        res = _load_json(RESERVATIONS_FILE, {"reservations": {}}).get("reservations", {})
    out = []
    for h, r in res.items():
        out.append({"rrn_hash": h, "name": r.get("name", ""), "rrn_masked": r.get("rrn_masked", ""),
                    "contact": r.get("contact", ""), "symptom": r.get("symptom", ""),
                    "date": r.get("date", ""),
                    "dept": r.get("dept"), "deptName": ID_TO_NAME.get(r.get("dept"), r.get("dept"))})
    return out


# ── 대기명단(진료과별) ───────────────────────────────────────────────────
def _load_waitlist():
    """대기명단 파일 로드. 구조: {queues:{dept_id:[entry]}, counters:{dept_id:int}}."""
    wl = _load_json(WAITLIST_FILE, {})
    wl.setdefault("queues", {})
    wl.setdefault("counters", {})
    return wl


# 상태 흐름(사이클10): waiting → called → in_progress → done.
# 활성 = 아직 진료 안 끝난 상태(대기/호출/진료중). done(완료)은 보존하되 활성에서 제외.
_ACTIVE = ("waiting", "called", "in_progress")


def _is_active(e):
    return e.get("status", "waiting") in _ACTIVE


def _ahead_count(queue, upto_index):
    """queue에서 index 앞쪽의 활성(대기/호출/진료중) 인원 수(완료 제외)."""
    return sum(1 for e in queue[:upto_index] if _is_active(e))


def _reset_counter_if_idle(wl, dept_id):
    """진료과에 활성 환자가 하나도 없으면 순번 카운터를 0으로(다음엔 1번부터).
    활성도 done도 전혀 없으면 빈 큐 키까지 정리."""
    q = wl["queues"].get(dept_id, [])
    if not any(_is_active(e) for e in q):
        wl["counters"][dept_id] = 0
        if not q:
            wl["queues"].pop(dept_id, None)


def waitlist_add(name, rrn, dept_id, visit_type, symptom, consume_reservation=False,
                 symptom_summary="", lang="ko"):
    """대기명단 등록(진료과별 순번 부여). 반환: {ok, deptId, deptName, ticket, id, ahead}.
    symptom=짧은 주증상(첫 발화), symptom_summary=문진 종합 한국어 요약(의료진용).
    lang=접수한 화면 언어(ko/en/ja/zh) — 콜보드가 그 언어로 호출 안내."""
    lang = lang if lang in _TTS_LANGS else "ko"
    if dept_id not in ID_TO_NAME:
        return {"ok": False, "error": f"알 수 없는 진료과: {dept_id}"}
    digits = _rrn_digits(rrn)
    masked = _rrn_masked_from(rrn) or _rrn_mask(digits)   # 초진(13)·재진(7) 모두 900101-1****** 로 통일
    now = time.time()
    entry_id = str(time.time_ns())
    with _data_lock:
        wl = _load_waitlist()
        q = wl["queues"].setdefault(dept_id, [])
        ticket = wl["counters"].get(dept_id, 0) + 1     # 진료과별 순번(재사용 안 함)
        wl["counters"][dept_id] = ticket
        q.append({"id": entry_id, "ticket": ticket, "name": name, "rrn_masked": masked,
                  "visit_type": visit_type, "symptom": symptom or "",
                  "symptom_summary": symptom_summary or "", "status": "waiting",
                  "memo": "", "lang": lang, "added_at": now, "called_at": None,
                  "in_progress_at": None, "done_at": None})
        ahead = _ahead_count(q, len(q) - 1)
        _save_json(WAITLIST_FILE, wl)
    if consume_reservation:
        reservation_clear_match(rrn, name)     # 예약대로 등록했으니 예약 삭제(마스킹+이름, 락 밖에서)
    return {"ok": True, "deptId": dept_id, "deptName": ID_TO_NAME[dept_id],
            "ticket": ticket, "id": entry_id, "ahead": ahead}


def waitlist_remove(dept_id, entry_id):
    """대기명단에서 특정 항목(id) 완전 삭제(간호사용). 반환: {ok, removed}.
    삭제 후 활성 환자가 없으면 순번 카운터를 0으로 리셋."""
    with _data_lock:
        wl = _load_waitlist()
        q = wl["queues"].get(dept_id, [])
        n0 = len(q)
        wl["queues"][dept_id] = [e for e in q if e.get("id") != entry_id]
        _reset_counter_if_idle(wl, dept_id)
        _save_json(WAITLIST_FILE, wl)
        return {"ok": True, "removed": n0 - len(wl["queues"].get(dept_id, []))}


def _waitlist_set_status(dept_id, entry_id, status, ts_field):
    """해당 entry 상태 전환 + 시각 기록. 완료 시 순번 리셋 검사."""
    with _data_lock:
        wl = _load_waitlist()
        for e in wl["queues"].get(dept_id, []):
            if e.get("id") == entry_id:
                e["status"] = status
                if ts_field:
                    e[ts_field] = time.time()
                if status == "done":
                    _reset_counter_if_idle(wl, dept_id)
                _save_json(WAITLIST_FILE, wl)
                return {"ok": True}
        return {"ok": False, "error": "항목 없음"}


def waitlist_call(dept_id, entry_id):
    """호출됨(간호사/의사). 상태 called + 호출 시각."""
    return _waitlist_set_status(dept_id, entry_id, "called", "called_at")


def waitlist_start(dept_id, entry_id):
    """진료 시작(의사). 상태 in_progress + 시작 시각."""
    return _waitlist_set_status(dept_id, entry_id, "in_progress", "in_progress_at")


def waitlist_done(dept_id, entry_id):
    """완료(소프트) → 삭제하지 않고 status=done + 완료 시각 보존(메모 유지)."""
    return _waitlist_set_status(dept_id, entry_id, "done", "done_at")


def waitlist_memo(dept_id, entry_id, memo):
    """진료 메모 저장(의사). 건강정보 — 인증 뒤에서만 호출됨."""
    with _data_lock:
        wl = _load_waitlist()
        for e in wl["queues"].get(dept_id, []):
            if e.get("id") == entry_id:
                e["memo"] = memo or ""
                e["memo_at"] = time.time()
                _save_json(WAITLIST_FILE, wl)
                return {"ok": True}
        return {"ok": False, "error": "항목 없음"}


def doctor_queue(dept_id):
    """의사용: 특정 진료과의 활성(대기/호출/진료중) + done(완료) 목록.
    증상요약·메모 포함(인증 뒤에서만 반환). 완료는 뒤로."""
    if dept_id not in ID_TO_NAME:
        return {"ok": False, "error": f"알 수 없는 진료과: {dept_id}"}
    with _data_lock:
        q = list(_load_waitlist()["queues"].get(dept_id, []))
    active = [e for e in q if _is_active(e)]
    done = [e for e in q if not _is_active(e)]
    return {"ok": True, "deptId": dept_id, "deptName": ID_TO_NAME[dept_id],
            "active": active, "done": done}


def callboard_data():
    """콜보드(공용 모니터, 공개): 모든 진료과의 호출됨/진료중 순번 + 이름.
    ★ 주민번호·증상요약·메모 등 건강정보는 절대 포함하지 않는다(순번·이름·상태만)."""
    with _data_lock:
        queues = _load_waitlist()["queues"]
    depts = []
    for dept_id, q in queues.items():
        # key·calledAt: 콜보드가 '새 호출/재호출'을 알아채 음성 안내하는 데만 사용(건강정보 아님)
        items = [{"ticket": e.get("ticket"), "status": e.get("status"),
                  "name": e.get("name", ""), "key": f"{dept_id}:{e.get('id', '')}",
                  "calledAt": e.get("called_at") or 0, "lang": e.get("lang") or "ko"}
                 for e in q if e.get("status") in ("called", "in_progress")]
        if items:
            items.sort(key=lambda x: (x["status"] != "called", x["ticket"] or 0))
            depts.append({"deptId": dept_id, "deptName": ID_TO_NAME.get(dept_id, dept_id),
                          "items": items})
    return {"depts": depts}


def waitlist_status(dept_id, entry_id):
    """환자 대기 현황: 내 순번·앞 인원·상태. 목록에 없으면 found=False(완료 등)."""
    with _data_lock:
        q = _load_waitlist()["queues"].get(dept_id, [])
    for i, e in enumerate(q):
        if e.get("id") == entry_id:
            return {"found": True, "ticket": e.get("ticket"), "ahead": _ahead_count(q, i),
                    "status": e.get("status", "waiting"),
                    "deptId": dept_id, "deptName": ID_TO_NAME.get(dept_id, dept_id)}
    return {"found": False}


# 마이크(STT 녹음)와 스피커(TTS 재생)의 공용 락.
#  로봇이 말하는 동안 녹음하면 자기 목소리를 인식하므로, 둘을 서로 배타적으로 실행한다.
_stt_lock = threading.Lock()


# ── 음성 끊기(2026-10-13): 키오스크 화면 음성은 새 음성이 오면 이전 것을 바로 끊는다 ──────────
#  · 키오스크 대사: 새 대사가 오면 재생 중인 키오스크 대사를 TTS /flush 로 중단, 기다리던 키오스크 대사는 건너뜀
#  · 콜보드 호출(callboardCall): 끊지도 끊기지도 않음(키오스크 대사는 호출 안내가 끝날 때까지 기다림)
#  · POST /speak/stop: 새 대사 없이 키오스크 음성만 멈춤("처음으로" 등 화면 이동)
_NON_INTERRUPT_IDS = {"callboardCall"}
_speak_state_lock = threading.Lock()
_speak_seq = 0            # 키오스크 대사 순번(+1씩)
_speak_latest = 0         # 가장 최근 키오스크 대사 순번(이보다 오래된 대기 대사는 건너뜀)
_speak_playing_id = None  # 지금 재생 중인 대사 id(None=없음)


def _interrupt_kiosk_speech():
    """키오스크 대사가 재생 중이면 TTS를 즉시 멈춘다(콜보드 호출 재생 중이면 그대로 둔다)."""
    if _speak_playing_id is None or _speak_playing_id in _NON_INTERRUPT_IDS:
        return
    try:
        req = urllib.request.Request(TTS_URL.rsplit("/", 1)[0] + "/flush", data=b"",
                                     headers={"Content-Type": "application/json"})
        urllib.request.urlopen(req, timeout=3).read()
    except Exception:
        pass


def speak_begin(speak_id):
    """키오스크 대사면 순번을 받고 재생 중인 이전 키오스크 대사를 끊는다. 반환: 순번(콜보드 호출은 0)."""
    global _speak_seq, _speak_latest
    if speak_id in _NON_INTERRUPT_IDS:
        return 0
    with _speak_state_lock:
        _speak_seq += 1
        _speak_latest = _speak_seq
        seq = _speak_seq
    _interrupt_kiosk_speech()
    return seq


def speak_superseded(seq):
    return seq != 0 and seq < _speak_latest


def speak_playing(speak_id):
    global _speak_playing_id
    _speak_playing_id = speak_id


def stop_kiosk_speech():
    """새 대사 없이 키오스크 음성만 멈춤(기다리던 키오스크 대사도 버림)."""
    global _speak_seq, _speak_latest
    with _speak_state_lock:
        _speak_seq += 1
        _speak_latest = _speak_seq
    _interrupt_kiosk_speech()


_TTS_LANGS = ("ko", "en", "zh", "ja")


def _tts_speak(text, lang="ko", vol=60):
    """TTS 상주 서버로 텍스트를 보내 그 언어 모델로 로봇 스피커에 재생(재생 끝까지 블록).
    tts_server가 꺼져 있으면 예외 → 호출측이 폴백(브라우저 TTS) 처리."""
    lang = lang if lang in _TTS_LANGS else "ko"
    vol = vol if isinstance(vol, int) and 0 <= vol <= 100 else 60
    body = json.dumps({"text": text, "lang": lang, "vol": vol}, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        TTS_URL, data=body,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8", "ignore"))


# ---- llm_package(map_labels.json) 기반 매칭 ----
def _load_llm():
    """llm_package 순수 매칭 함수 + map_labels 라벨 인덱스 로드. 실패 시 (None, None, 0)."""
    try:
        if str(LLM_SRC) not in sys.path:
            sys.path.insert(0, str(LLM_SRC))
        from llm.cli import load_map_labels, build_label_index, match_location
        zones = load_map_labels(MAP_LABELS)
        index = build_label_index(zones)
        mtime = MAP_LABELS.stat().st_mtime_ns
        return index, match_location, mtime
    except Exception as exc:
        print(f"[kiosk] llm_package 매칭 비활성(폴백 사용): {exc}")
        return None, None, 0


_LLM_INDEX, _LLM_MATCH, _LLM_MTIME = _load_llm()


def _reload_llm_if_changed():
    """map_labels.json 이 바뀌면(예: 약국 추가) 인덱스 재로드."""
    global _LLM_INDEX, _LLM_MATCH, _LLM_MTIME
    try:
        m = MAP_LABELS.stat().st_mtime_ns
        if _LLM_MATCH is None or m != _LLM_MTIME:
            _LLM_INDEX, _LLM_MATCH, _LLM_MTIME = _load_llm()
    except OSError:
        pass


def zone_has_goal(name):
    """map_labels.json에서 name zone에 nav_goal 좌표가 있는지."""
    try:
        data = json.loads(MAP_LABELS.read_text(encoding="utf-8"))
        z = next((z for z in data.get("zones", []) if z.get("name") == name), None)
        g = z.get("nav_goal") if z else None
        return bool(isinstance(g, dict) and "x" in g and "y" in g)
    except Exception:
        return False


def match_location(text):
    """인식 텍스트 → locations.js 장소 id (없으면 None)."""
    if not text:
        return None
    _reload_llm_if_changed()

    # 1) llm_package + map_labels.json 매칭
    if _LLM_INDEX is not None:
        try:
            hit = _LLM_MATCH(text, _LLM_INDEX)   # (zone, keyword) 또는 None
            if hit:
                name = hit[0].get("name", "")
                if name in NAME_TO_ID:
                    return NAME_TO_ID[name]
        except Exception:
            pass

    # 2) 폴백 별칭(map_labels에 없는 장소 포함)
    for word, loc_id in EXTRA_ALIASES.items():
        if word in text:
            return loc_id
    low = text.lower()
    for word, loc_id in _FOREIGN_ALIAS_LIST:      # 영·일·중 장소 이름
        if word in low:
            return loc_id

    # 3) 규칙으로 못 잡은 발화 → LLM 폴백(동의어/오인식). start_ui 전용(env+키)
    return _openai_match(text)


# ── 녹음 중 표시(bus/mic_active) ── 카메라 사람 감지 노드(vision_obstacle_node)가 이 파일이 있는 동안 AI 추론을 쉰다.
#  2026-11-12: 사람 감지 AI(SegFormer, GPU)가 도는 동안 reSpeaker 녹음이 0.25초만 받고 멈추고 xHCI "buffer overrun"
#  수천 건(카메라 영상만 받을 땐 정상) → 녹음하는 몇 초만 AI를 쉬게 한다. 녹음은 로봇이 서서 대화할 때만 하므로 주행 안전 영향 작음.
#  파일 내용 = 시작 시각. 서버가 죽어 파일이 남아도 감지 노드가 30초 넘은 표시는 무시한다.
MIC_FLAG = BUS / "mic_active"
_mic_depth = 0
_mic_lock = threading.Lock()


# ── reSpeaker 자동 복구 ── 녹음 데이터가 거의 안 들어오면(비정상 사양 125µs) 관리자 사본을 비밀번호 없이 실행해 USB 재인식.
#  설정(한 번): /usr/local/sbin/respeaker_check.sh(root 소유 사본) + /etc/sudoers.d/respeaker(그 파일 'fix' 만 허용).
#  설정 안 돼 있으면 sudo -n 이 바로 실패 → 로그 안내만. 2분에 한 번만 시도(반복 재인식 방지).
RESPEAKER_FIX = ["sudo", "-n", "/usr/local/sbin/respeaker_check.sh", "fix"]
_rsp_last_fix = 0.0


def _respeaker_autofix():
    global _rsp_last_fix
    if time.time() - _rsp_last_fix < 120:
        return
    _rsp_last_fix = time.time()

    def run():
        try:
            r = subprocess.run(RESPEAKER_FIX, capture_output=True, text=True, timeout=60)
            out = (r.stdout + r.stderr).strip().replace("\n", " / ")
            if r.returncode == 0:
                print(f"[kiosk] reSpeaker 자동 복구 결과: {out}", flush=True)
            else:
                print(f"[kiosk] ⚠ reSpeaker 자동 복구 실패(rc={r.returncode}): {out[:200]} — "
                      f"설정이 안 됐으면 HANDOFF/PROGRESS 의 sudoers 설정 참고, 아니면 허브 A-1 에서 다시 꽂기", flush=True)
        except Exception as exc:
            print(f"[kiosk] ⚠ reSpeaker 자동 복구 실행 오류: {exc}", flush=True)
    threading.Thread(target=run, daemon=True).start()


class _MicActive:
    def __enter__(self):
        global _mic_depth
        with _mic_lock:
            _mic_depth += 1
            try:
                MIC_FLAG.write_text(f"{time.time():.3f}\n")
            except OSError:
                pass
        return self

    def __exit__(self, *exc):
        global _mic_depth
        with _mic_lock:
            _mic_depth = max(0, _mic_depth - 1)
            if _mic_depth == 0:
                try:
                    MIC_FLAG.unlink()
                except OSError:
                    pass
        return False


def _measure_ambient_rms(device, seconds=1):
    with _MicActive():
        return _measure_ambient_rms_impl(device, seconds)


def _measure_ambient_rms_impl(device, seconds=1):
    """녹음 직전 주변음 RMS(하위 20퍼센타일)를 측정. 실패 시 None.
    하위 퍼센타일을 쓰는 이유: 사용자가 측정 중 말을 시작해도 조용한 구간이
    실제 노이즈 플로어를 대표하도록 하기 위함(임계값이 과대추정되지 않게).
    ※ arecord -d 는 정수 초만 받는다."""
    seconds = max(1, int(seconds))
    try:
        out = _pick_channel(subprocess.run(
            _arecord_cmd(device, 16000, seconds),
            capture_output=True, timeout=seconds + 2.0,
        ).stdout, STT_VAD_CHANNEL)
        if not out:
            return None
        a = array.array("h")
        a.frombytes(out[: len(out) - (len(out) % 2)])
        fr = int(16000 * 0.03)  # 30ms 프레임
        rmss = []
        for i in range(0, len(a) - fr, fr):
            frame = a[i:i + fr]
            rmss.append((sum(s * s for s in frame) / len(frame)) ** 0.5)
        if not rmss:
            return None
        rmss.sort()
        return rmss[len(rmss) // 5]  # 하위 20%
    except Exception:
        return None


_VAD_CACHED = None


def _resolve_vad_threshold():
    """VAD 임계값 결정: 환경변수 우선, 없으면 주변음 기반 자동 보정."""
    if VAD_THRESHOLD_ENV:
        try:
            thr = float(VAD_THRESHOLD_ENV)
            print(f"[kiosk] VAD 임계값(고정)={thr:.0f}", flush=True)
            return thr
        except ValueError:
            pass
    amb = _measure_ambient_rms(STT_DEVICE, 1)
    if amb is None:
        print("[kiosk] VAD 주변음 측정 실패 → 기본 임계값 500", flush=True)
        return 500.0
    thr = max(350.0, min(1500.0, amb * 2.2 + 120.0))
    print(f"[kiosk] VAD 자동보정: 주변음 RMS≈{amb:.0f} → 임계값 {thr:.0f}", flush=True)
    return thr


# ── 신경망 말소리 감지(Silero VAD) ── 있으면 '목소리인지'로 판단(크기 무관: 멀리서 조곤조곤 말해도, 소음은 무시).
#  모델·onnxruntime 이 없거나 STT_VAD=energy 면 예전 방식(소리 크기 기준)으로.
_SILERO = None
_SILERO_DIAG = None   # 진단용 두 번째 인스턴스: 감지 채널(원음)의 목소리 확률도 로그로 비교
_SILERO_TRIED = False
VAD_START_P = float(os.environ.get("VAD_START_P", "0.5"))    # 말 시작: 100ms 안 32ms 프레임 2개 이상이 이 확률 넘으면
VAD_KEEP_P = float(os.environ.get("VAD_KEEP_P", "0.35"))     # 말 이어짐: 프레임 하나라도 이 확률 넘으면


def _get_silero():
    global _SILERO, _SILERO_DIAG, _SILERO_TRIED
    if not _SILERO_TRIED:
        _SILERO_TRIED = True
        if os.environ.get("STT_VAD", "silero") != "energy":
            try:
                from speech_vad import SileroVAD
                _SILERO = SileroVAD()
                if STT_VAD_CHANNEL != STT_CHANNEL:
                    _SILERO_DIAG = SileroVAD()
                print("[kiosk] 말소리 감지: Silero VAD(목소리 판별)", flush=True)
            except Exception as exc:
                print(f"[kiosk] ⚠ Silero VAD 사용 불가 → 소리 크기 기준으로 감지: {exc}", flush=True)
    return _SILERO


def _get_vad_threshold():
    """임계값을 서버 시작 시 1회만 계산해 캐시.
    ★매 /listen마다 측정하면 그 1초 동안 사용자의 발화 앞부분이 잘린다★
    (게인이 고정이라 주변음은 안정적이므로 1회 측정으로 충분)."""
    global _VAD_CACHED
    if _VAD_CACHED is None:
        _VAD_CACHED = _resolve_vad_threshold()
    return _VAD_CACHED


def _whisper_transcribe(wav_path, prompt="", lang="ko"):
    """whisper-server(/inference)에 wav + 초기 프롬프트를 보내 텍스트를 받는다.
    stt_package의 run_whisper_server는 prompt를 지원하지 않아, 여기서 직접
    multipart 요청을 만든다(표준 라이브러리만 사용)."""
    boundary = "----kioskFormBoundary8xY2zQ"
    with open(wav_path, "rb") as f:
        audio = f.read()
    chunks = []

    def _field(name, value):
        chunks.append(
            (f"--{boundary}\r\nContent-Disposition: form-data; "
             f'name="{name}"\r\n\r\n{value}\r\n').encode("utf-8"))

    _field("language", lang if lang in STT_LANGS else "ko")
    _field("response_format", "json")
    if prompt:
        _field("prompt", prompt)
    chunks.append(
        (f"--{boundary}\r\nContent-Disposition: form-data; "
         f'name="file"; filename="{Path(wav_path).name}"\r\n'
         f"Content-Type: audio/wav\r\n\r\n").encode("utf-8"))
    chunks.append(audio)
    chunks.append(f"\r\n--{boundary}--\r\n".encode("utf-8"))
    body = b"".join(chunks)

    req = urllib.request.Request(
        WHISPER_URL, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=120) as resp:
        raw = resp.read().decode("utf-8", "ignore")
    print(f"[kiosk] whisper 응답 {time.time() - t0:.2f}초", flush=True)
    try:
        return (json.loads(raw).get("text") or "").strip()
    except (ValueError, AttributeError):
        return raw.strip()


# ── 녹음 대기 제한·취소 (2026-10-13) ─────────────────────────────────────
# 예전엔 stt_package 녹음기가 "말이 시작될 때까지" 무한정 기다려, 아무도 말하지 않으면
# 녹음이 마이크·스피커 공용 락(_stt_lock)을 쥔 채 끝나지 않아 안내 음성이 영영 막혔다.
#  · STT_WAIT_SEC(기본 8초) 동안 말소리가 없으면 녹음을 끝낸다(빈 결과).
#  · POST /listen/cancel: 그 시점까지 들어온 녹음 요청을 모두 취소(0.1초 안에 마이크 반납).
#    화면이 녹음을 취소할 때(타자 답변·화면 이동) 서버 녹음도 함께 멈추게 한다.
STT_WAIT_SEC = float(os.environ.get("STT_WAIT_SEC", "8"))
_listen_seq_lock = threading.Lock()
_listen_seq = 0        # /listen 요청마다 +1
_cancel_upto = 0       # 이 번호 이하의 녹음은 취소


def _new_listen_seq():
    global _listen_seq
    with _listen_seq_lock:
        _listen_seq += 1
        return _listen_seq


def cancel_listens():
    global _cancel_upto
    with _listen_seq_lock:
        _cancel_upto = _listen_seq


def _record_utterance(*args, **kwargs):
    with _MicActive():          # 녹음하는 동안 카메라 사람 감지 AI 쉬게(위 MIC_FLAG 설명)
        return _record_utterance_impl(*args, **kwargs)


def _record_utterance_impl(is_cancelled, device=None, threshold=None, wait_sec=None,
                           pre_roll_sec=2.0, silence_sec=1.2, min_record_sec=0.6, max_record_sec=12.0):
    """마이크에서 한 발화를 녹음해 WAV 경로를 돌려준다. 말이 없거나(wait_sec) 취소되면 None.
    VAD 파라미터(앱 키오스크용 튜닝, 예전 stt_package 녹음기와 같은 값):
     · pre_roll_sec=2.0  — 트리거 전 2초를 앞에 붙인다(약한 어두가 늦게 잡혀도 앞 ~1.1초를 살림)
     · silence_sec=1.2   — 문장 중간 짧은 쉼에서 성급히 끊지 않게
     · min_record_sec=0.6 — 초단편 오검출은 버림(앞 버퍼 포함 길이 기준, 예전과 동일)"""
    device = device or STT_DEVICE
    thr = threshold if threshold is not None else _get_vad_threshold()
    wait_sec = STT_WAIT_SEC if wait_sec is None else wait_sec
    chunk_sec, rate = 0.1, 16000
    chunk_bytes = int(rate * chunk_sec) * 2 * STT_CHANNELS     # 다채널이면 그만큼 크게 읽고 한 채널만 꺼냄
    proc = subprocess.Popen(_arecord_cmd(device, rate),
                            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    pre = deque(maxlen=max(1, int(pre_roll_sec / chunk_sec)))
    speech, in_speech = [], False
    peak, n_chunks = 0, 0          # 진단용: 들어온 소리 중 가장 큰 RMS(임계값과 비교해 로그로 남김)
    # 신경망 감지는 인식용 채널(reSpeaker 0번: 빔포밍·소음 억제된 음성)로 판단. 원음 채널 확률은 비교용 로그만
    sv, sd = _get_silero(), _SILERO_DIAG
    for v in (sv, sd):
        if v:
            v.reset()
    pmax, pmax_raw = 0.0, 0.0      # 진단용: 가장 높은 목소리 확률(인식 채널 / 원음 채널)
    t_wait = time.time()
    fd, buf = proc.stdout.fileno(), b""
    try:
        while True:
            if is_cancelled():
                print("[kiosk] 녹음 취소", flush=True)
                return None
            # 데이터가 안 와도 0.2초마다 취소·대기 제한을 확인(블로킹 read 금지 — 마이크가 멈춰도 갇히지 않게)
            ready, _, _ = select.select([fd], [], [], 0.2)
            now = time.time()
            if not ready:
                if proc.poll() is not None:
                    raise RuntimeError("arecord 종료(마이크 확인 필요)")
                if not in_speech and now - t_wait >= wait_sec:
                    print(f"[kiosk] {wait_sec:.0f}초 동안 소리 데이터/말소리 없음 → 녹음 종료 (받은 소리 {n_chunks*chunk_sec:.1f}초, 최대 RMS {peak}, 목소리 확률 최대 {pmax:.2f}(원음 {pmax_raw:.2f}))", flush=True)
                    # (2026-11-15: 11-12 잘 되던 때로 되돌림 — 녹음 데이터 미수신 시 reSpeaker 자동 복구 호출 제거)
                    return None
                continue
            part = os.read(fd, chunk_bytes - len(buf))
            if not part:
                if proc.poll() is not None:
                    raise RuntimeError("arecord 종료(마이크 확인 필요)")
                continue
            buf += part
            if len(buf) < chunk_bytes:
                continue
            data, vdata = _pick_channel(buf), _pick_channel(buf, STT_VAD_CHANNEL)
            buf = b""
            lvl = audioop.rms(vdata, 2)
            peak, n_chunks = max(peak, lvl), n_chunks + 1
            if sv:                     # 목소리 확률(프레임 32ms × 약 3개)
                ps = sv.probs(data)
                pmax = max([pmax] + ps)
                if sd:
                    pmax_raw = max([pmax_raw] + sd.probs(vdata))
                voice = (sum(p >= VAD_START_P for p in ps) >= 2) if not in_speech else any(p >= VAD_KEEP_P for p in ps)
            else:
                voice = lvl >= thr
            if not in_speech:
                pre.append(data)
                if voice:
                    in_speech, t_start, t_last = True, now, now
                    speech = list(pre)
                elif now - t_wait >= wait_sec:
                    print(f"[kiosk] {wait_sec:.0f}초 동안 말소리 없음 → 녹음 종료 (최대 RMS {peak}, 목소리 확률 최대 {pmax:.2f}(원음 {pmax_raw:.2f}){'' if sv else f' / 기준 {thr:.0f}'})", flush=True)
                    return None
            else:
                speech.append(data)
                if voice:
                    t_last = now
                if now - t_last >= silence_sec or now - t_start >= max_record_sec:
                    if len(speech) * chunk_sec >= min_record_sec:
                        fd, path = tempfile.mkstemp(prefix="stt_input_", suffix=".wav")
                        os.close(fd)
                        with wave.open(path, "wb") as wf:
                            wf.setnchannels(1); wf.setsampwidth(2); wf.setframerate(rate)
                            wf.writeframes(b"".join(speech))
                        global _LAST_SPEECH_END
                        _LAST_SPEECH_END = t_last          # 실험 기록: 말이 끝난 시각
                        why = "최대 길이" if now - t_start >= max_record_sec else "말 끝남"
                        print(f"[kiosk] 녹음 완료({why}): {len(speech)*chunk_sec:.1f}초, 최대 RMS {peak}, 목소리 확률 최대 {pmax:.2f}(원음 {pmax_raw:.2f})"
                              f"{'' if sv else f' / 기준 {thr:.0f}'}", flush=True)
                        return path
                    in_speech, speech = False, []      # 너무 짧음 → 버리고 계속 대기
                    pre.clear()
                    t_wait = now
    finally:
        if proc.poll() is None:
            proc.kill()
        try:
            proc.wait(timeout=2)
        except subprocess.TimeoutExpired:
            pass


def stt_listen_once(seq=None, lang="ko"):
    """마이크 1회 녹음 + whisper 인식 → 인식 텍스트(말이 없거나 취소되면 ""). (whisper-server + 마이크 필요)"""
    if str(STT_SRC) not in sys.path:
        sys.path.insert(0, str(STT_SRC))
    from stt.postprocess import postprocess_stt_text

    seq = seq if seq is not None else _new_listen_seq()
    audio_path = _record_utterance(lambda: _cancel_upto >= seq)
    if not audio_path:
        return ""
    try:
        text = _whisper_transcribe(audio_path, WHISPER_PROMPTS.get(lang, WHISPER_PROMPT), lang).replace("[끝]", "").strip()
    finally:
        try:
            os.remove(audio_path)            # 예전엔 /tmp에 녹음 파일이 계속 쌓였음
        except OSError:
            pass
    if _is_whisper_hallucination(text):
        print(f"[kiosk] 인식 결과 버림(Whisper 환각 문구): '{text}'", flush=True)
        return ""
    # 한국어 도메인 단어 보정은 한국어일 때만(외국어 문장을 한국어 단어로 바꾸지 않게)
    return postprocess_stt_text(text) if lang == "ko" else text


# Whisper가 잡음·무음을 받으면 학습 데이터(영상 자막)에서 흔한 문구를 지어낸다 → 인식 실패로 처리
_HALLUCINATION_RE = re.compile(
    r"시청해\s*주셔서|구독(과|\s*,|\s*및)?\s*좋아요|좋아요(와|\s*,)?\s*구독|구독\s*부탁|MBC\s*뉴스|자막\s*제공|"
    r"thank(s| you) for watching|please subscribe|like and subscribe|"
    r"ご視聴ありがとうございました|チャンネル登録|"
    r"谢谢观看|请订阅|字幕由", re.I)


def _is_whisper_hallucination(text):
    return bool(text) and bool(_HALLUCINATION_RE.search(text))


class Handler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(SRC_DIR), **kwargs)

    def end_headers(self):
        # 정적파일(JS 모듈·안내도 이미지)을 브라우저가 캐시하면 코드/라벨을 바꿔도
        # 옛 버전이 계속 보인다. 캐시 방지 헤더로 매 요청 최신본을 받게 한다.
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _send_json(self, obj, code=200):
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        except (BrokenPipeError, ConnectionResetError):
            # 2026-11-15: 결과가 나오기 전에 화면이 요청을 끊음(뒤로·처음으로·화면 전환 → recognizer.cancel) —
            #  예전엔 BrokenPipeError 추적 메시지가 두 번씩 찍혀 장애처럼 보였음. 결과만 버려지고 서버는 정상.
            self._client_gone = True
            print(f"[kiosk] {self.path} 응답 전에 화면이 연결을 끊음(뒤로·처음으로 등) → 결과 버림: "
                  f"{str(obj.get('text', '') if isinstance(obj, dict) else '')[:40]!r}", flush=True)

    def _admin_authed(self):
        """PIN 미설정이면 개방, 설정돼 있으면 X-Admin-Pin 헤더 일치 요구."""
        if not ADMIN_PIN:
            return True
        return self.headers.get("X-Admin-Pin", "") == ADMIN_PIN

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == "/nav_status":
            # 요청 파일이 어느 폴더에 있는지로 상태 판정.
            #  pending  = 아직 nav_request/ (워처 미처리 or Nav2 미기동)
            #  accepted = nav_request_done/ (워처가 goal 수락=이동 시작. ★도착 아님)
            #  failed   = nav_request_failed/ (해당 워처엔 없지만 방어적)
            fname = parse_qs(parsed.query).get("file", [""])[0]
            if not fname:
                self._send_json({"status": "unknown"})
                return
            if (NAV_REQ_DIR / fname).exists():
                st = "pending"
            elif (NAV_DONE_DIR / fname).exists():
                st = "accepted"
            elif (NAV_FAILED_DIR / fname).exists():
                st = "failed"
            else:
                st = "unknown"
            self._send_json({"status": st})
            return
        if parsed.path == "/robot_status":
            # 로봇 이동/도착 상태. return_home_watcher 가 갱신한다.
            #  · 파일이 없으면(감시 노드 미실행) state=unknown → 앱은 기존 동작 유지
            try:
                with open(ROBOT_STATUS_FILE, encoding="utf-8") as f:
                    self._send_json(json.load(f))
            except (OSError, ValueError):
                self._send_json({"state": "unknown", "place": "", "updated_at": 0})
            return
        if parsed.path == "/config":
            # 클라이언트 설정(무조작 리셋 시간 등). 공개(민감정보 아님).
            self._send_json({"idleSec": KIOSK_IDLE_SEC})
            return
        if parsed.path == "/waitlist":
            # 간호사 관리(?nurse=1)용: 진료과별 대기명단 + 환자 수. PIN 필요(설정 시).
            if not self._admin_authed():
                self._send_json({"error": "unauthorized"}, 403)
                return
            with _data_lock:
                wl = _load_waitlist()
                pdata = _load_json(PATIENTS_FILE, {"patients": []})
            queues = wl["queues"]
            self._send_json({
                "waitlistById": queues,
                "byName": {ID_TO_NAME.get(k, k): v for k, v in queues.items()},
                "patientCount": len(pdata.get("patients", [])),
                "patients": patient_list(),
                "reservations": reservation_list(),
                "depts": [{"id": i, "name": n} for i, n in ID_TO_NAME.items()],
            })
            return
        if parsed.path == "/doctor/queue":
            # 의사용: 특정 진료과 대기 목록(요약·메모 포함). 건강정보 → PIN 필요.
            if not self._admin_authed():
                self._send_json({"error": "unauthorized"}, 403)
                return
            dept = parse_qs(parsed.query).get("dept", [""])[0]
            self._send_json(doctor_queue(dept))
            return
        if parsed.path == "/callboard":
            # 대기실 공용 콜보드(공개): 호출/진료중 '순번만'. PII 없음.
            self._send_json(callboard_data())
            return
        if parsed.path == "/goal":
            # 장소 id → map_labels.json nav_goal (실제 목표 좌표). 없으면 error.
            loc_id = parse_qs(parsed.query).get("id", [""])[0]
            name = ID_TO_NAME.get(loc_id)
            if not name:
                self._send_json({"error": f"알 수 없는 장소 id: {loc_id}"})
                return
            try:
                data = json.loads(MAP_LABELS.read_text(encoding="utf-8"))
                zone = next((z for z in data.get("zones", []) if z.get("name") == name), None)
                g = zone.get("nav_goal") if zone else None
                if isinstance(g, dict) and "x" in g and "y" in g:
                    self._send_json({
                        "name": name, "x": g["x"], "y": g["y"],
                        "yaw_deg": g.get("yaw_deg"), "qz": g.get("qz"), "qw": g.get("qw"),
                        "frame_id": (zone or {}).get("frame_id", "map"),
                    })
                else:
                    self._send_json({"name": name, "error": "map_labels.json에 좌표(nav_goal) 미설정"})
            except Exception as exc:
                self._send_json({"error": str(exc)})
            return
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path

        if path == "/admin/auth":
            # PIN 확인(게이트용). 미설정이면 required=False → 게이트 없이 통과.
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                pin = (json.loads(self.rfile.read(n)) if n else {}).get("pin", "")
            except Exception:
                pin = ""
            self._send_json({"required": bool(ADMIN_PIN),
                             "ok": (not ADMIN_PIN) or (pin == ADMIN_PIN)})
            return

        if path in ADMIN_PATHS and not self._admin_authed():
            self._send_json({"error": "unauthorized"}, 403)
            return

        if path == "/listen/cancel":
            # 화면이 녹음을 취소(타자 답변·화면 이동) → 서버 녹음도 즉시 멈추고 마이크·스피커 락 반납
            cancel_listens()
            self._send_json({"ok": True})
            return

        if path == "/speak/stop":
            # 화면 이동("처음으로" 등): 키오스크 음성만 즉시 멈추고, 기다리던 키오스크 대사도 버림
            stop_kiosk_speech()
            self._send_json({"ok": True})
            return

        if path == "/speak/prewarm":
            # 화면이 고정 안내 문장 목록을 보내면 TTS 서버가 뒤에서 미리 합성(캐시) → 첫 재생도 즉시
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                pb = json.loads(self.rfile.read(n)) if n else {}
                texts, plang = pb.get("texts") or [], str(pb.get("lang") or "ko")
                body = json.dumps({"texts": texts, "lang": plang}, ensure_ascii=False).encode("utf-8")
                req = urllib.request.Request(
                    TTS_URL.rsplit("/", 1)[0] + "/prewarm", data=body,
                    headers={"Content-Type": "application/json; charset=utf-8"})
                with urllib.request.urlopen(req, timeout=5) as resp:
                    self._send_json(json.loads(resp.read().decode("utf-8", "ignore")))
            except Exception as exc:
                self._send_json({"ok": False, "error": str(exc)}, 200)
            return

        if path == "/speak":
            # 안내 문구를 MeloTTS로 합성해 로봇 스피커로 재생.
            #  _stt_lock 으로 STT 녹음과 배타 실행(말하는 중엔 녹음 안 함).
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n)) if n else {}
                text, speak_id = body.get("text", ""), str(body.get("id", "") or "")
                speak_lang = str(body.get("lang", "") or "ko")
                speak_vol = body.get("vol", 60)                # 환자 화면 음량(0~100, 기본 60)
                speak_vol = int(speak_vol) if str(speak_vol).isdigit() else 60
            except Exception:
                text, speak_id, speak_lang, speak_vol = "", "", "ko", 60
            text = (text or "").strip()
            if not text:
                self._send_json({"ok": False, "error": "empty text"}, 400)
                return
            if not _tts_allowed(speak_id):
                print(f"[kiosk] TTS 무음(허용 목록 밖) [{speak_id}]: {text}", flush=True)
                self._send_json({"ok": True, "muted": True})
                return
            seq = speak_begin(speak_id)                 # 재생 중인 이전 키오스크 대사 끊기
            try:
                with _stt_lock:
                    if speak_superseded(seq):           # 기다리는 사이 더 새 대사가 옴 → 건너뜀
                        self._send_json({"ok": True, "skipped": "superseded"})
                        return
                    speak_playing(speak_id or "?")
                    try:
                        r = _tts_speak(text, speak_lang, speak_vol)
                    finally:
                        speak_playing(None)
                if isinstance(r, dict) and r.get("error") in ("flushed", "stale", "lang_not_ready"):
                    if r.get("error") == "lang_not_ready":
                        print(f"[kiosk] TTS 건너뜀({speak_lang} 모델 로딩 중) [{speak_id}]: {text}", flush=True)
                    r = {"ok": True, "skipped": r.get("error")}  # 끊김/오래됨/언어 로딩 중: 브라우저 음성으로 대신 읽지 않게
                self._send_json(r if isinstance(r, dict) else {"ok": True})
            except Exception as exc:
                # tts_server 미기동 등 → 앱이 브라우저 TTS로 폴백하도록 실패 반환
                self._send_json({"ok": False, "error": str(exc)}, 200)
            return

        if path == "/nav":
            # {id} → 한글 라벨명 → nav_request 파일 작성. 좌표 없으면 차단(파일 안 씀).
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n)) if n else {}
            except Exception:
                body = {}
            loc_id = body.get("id", "")
            name = ID_TO_NAME.get(loc_id)
            if not name:
                self._send_json({"error": f"알 수 없는 장소 id: {loc_id}"})
                return
            if not zone_has_goal(name):
                # 좌표 미설정(예: 약국) → 요청 자체 차단 (failed로 보내지 않음)
                self._send_json({"blocked": True, "name": name, "reason": "좌표 미설정"})
                return
            try:
                NAV_REQ_DIR.mkdir(parents=True, exist_ok=True)
                stamp = time.strftime("%Y%m%d_%H%M%S") + f"_{int(time.time() * 1000) % 1000:03d}"
                fname = f"kiosk_{stamp}_{loc_id}.json"
                (NAV_REQ_DIR / fname).write_text(
                    json.dumps({"place_name": name, "source": "kiosk", "requested_at": time.time()},
                               ensure_ascii=False),
                    encoding="utf-8",
                )
                self._send_json({"ok": True, "file": fname, "name": name})
                _exp_event("nav", loc=loc_id, name=name)
            except Exception as exc:
                self._send_json({"error": str(exc)})
            return

        if path in ("/patient/register", "/patient/check", "/patient/remove", "/reservation/check",
                    "/reservation/set", "/reservation/remove", "/waitlist/add",
                    "/waitlist/remove", "/waitlist/call", "/waitlist/start", "/waitlist/done",
                    "/waitlist/memo", "/waitlist/status"):
            # S-04 접수: 환자 등록(데이터셋) · 예약(별도) · 대기명단
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n)) if n else {}
            except Exception:
                body = {}
            name = (body.get("name") or "").strip()
            rrn = (body.get("rrn") or "").strip()
            if path == "/patient/register":
                self._send_json(patient_register(name, rrn, (body.get("contact") or "").strip()))
            elif path == "/patient/check":
                self._send_json(patient_check(name, rrn))
            elif path == "/patient/remove":
                rh = (body.get("rrnHash") or "").strip() or _rrn_hash(_rrn_digits(rrn))
                self._send_json(patient_remove(rh))
            elif path == "/reservation/check":
                self._send_json(reservation_check(rrn, name))
            elif path == "/reservation/set":
                self._send_json(reservation_set(name, rrn, body.get("deptId") or "",
                                                (body.get("symptom") or "").strip(),
                                                (body.get("date") or "").strip()))
            elif path == "/reservation/remove":
                rh = (body.get("rrnHash") or "").strip() or _rrn_hash(_rrn_digits(rrn))
                self._send_json({"ok": reservation_clear(rh)})
            elif path == "/waitlist/remove":
                self._send_json(waitlist_remove(body.get("deptId") or "", body.get("id") or ""))
            elif path == "/waitlist/call":
                self._send_json(waitlist_call(body.get("deptId") or "", body.get("id") or ""))
            elif path == "/waitlist/start":
                self._send_json(waitlist_start(body.get("deptId") or "", body.get("id") or ""))
            elif path == "/waitlist/done":
                self._send_json(waitlist_done(body.get("deptId") or "", body.get("id") or ""))
            elif path == "/waitlist/memo":
                self._send_json(waitlist_memo(body.get("deptId") or "", body.get("id") or "",
                                              (body.get("memo") or "").strip()))
            elif path == "/waitlist/status":
                self._send_json(waitlist_status(body.get("deptId") or "", body.get("id") or ""))
            else:  # /waitlist/add
                _exp_event("register", dept=body.get("deptId") or "")
                self._send_json(waitlist_add(name, rrn, body.get("deptId") or "",
                                             body.get("visitType") or "",
                                             (body.get("symptom") or "").strip(),
                                             bool(body.get("consumeReservation")),
                                             (body.get("symptomSummary") or "").strip(),
                                             str(body.get("lang") or "ko")))
            return

        if path == "/triage":
            # 증상 → 진료과 id (S-04 수속). {text} 주입(타자) 또는 마이크 1회 녹음.
            debug_text = None
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                if n:
                    debug_text = (json.loads(self.rfile.read(n)) or {}).get("text")
            except Exception:
                debug_text = None
            try:
                if debug_text is not None:
                    text = debug_text
                else:
                    with _stt_lock:
                        text = stt_listen_once()
                if is_emergency(text):            # (a) 규칙 응급 필터 먼저 — LLM 트리아지 안 함
                    print(f"[kiosk] 증상='{text}'  →  응급(EMERGENCY)", flush=True)
                    self._send_json({"text": text, "locationId": None,
                                     "emergency": True, "confidence": 1.0})
                    return
                dep = _triage_match(text)         # (b) 비응급만 트리아지
                print(f"[kiosk] 증상='{text}'  →  진료과={dep or '없음'}", flush=True)
                _exp_event("recommend", src="triage", loc=dep, speech_end=_recent_speech_end(30.0))
                self._send_json({"text": text, "locationId": dep,
                                 "confidence": 0.95 if dep else 0.3})
            except Exception as exc:
                self._send_json({"text": "", "locationId": None, "confidence": 0.0,
                                 "error": str(exc)}, 200)
            return

        if path in ("/interview", "/interview/summarize"):
            # AI 대화형 문진(사이클8). 서버 무상태: 클라가 messages 전체를 매번 보냄.
            # {lang, messages:[{role:'user'|'assistant', text}]}  (환자용 → PIN 불필요)
            try:
                n = int(self.headers.get("Content-Length", 0) or 0)
                body = json.loads(self.rfile.read(n)) if n else {}
            except Exception:
                body = {}
            lang = body.get("lang") or "ko"
            messages = body.get("messages") or []
            try:
                if path == "/interview":
                    self._send_json(interview_next(lang, messages))
                else:
                    t_req = time.time()
                    res = interview_summarize(lang, messages)
                    _exp_event("recommend", src="interview", loc=res.get("locationId"), emergency=bool(res.get("emergency")),
                               t_req=round(t_req, 3), speech_end=_recent_speech_end(120.0))
                    self._send_json(res)
            except Exception as exc:
                # 실패해도 흐름이 멈추지 않게 안전 폴백(문진=종합으로, 종합=빈 요약)
                if path == "/interview":
                    self._send_json({"action": "done", "error": str(exc)}, 200)
                else:
                    self._send_json({"emergency": False, "locationId": None,
                                     "summaryKo": "", "recap": "", "error": str(exc)}, 200)
            return

        if path != "/listen":
            self.send_error(404)
            return

        # 본문: {lang} = 화면 언어(ko/en/ja/zh, 없으면 ko — 예전과 동일) · {text} = 테스트용 텍스트 주입(마이크 없이 매칭 검증)
        debug_text, stt_lang = None, "ko"
        try:
            n = int(self.headers.get("Content-Length", 0) or 0)
            if n:
                req_body = json.loads(self.rfile.read(n)) or {}
                debug_text = req_body.get("text")
                stt_lang = str(req_body.get("lang") or "ko")
        except Exception:
            debug_text = None
        if stt_lang not in STT_LANGS:
            stt_lang = "ko"
        if not debug_text:
            qs = parse_qs(urlparse(self.path).query)
            if "text" in qs:
                # http.server가 경로를 latin-1로 디코딩하므로 UTF-8로 복원
                debug_text = qs["text"][0].encode("latin-1", "ignore").decode("utf-8", "ignore")

        try:
            if debug_text is not None:
                text = debug_text
            else:
                seq = _new_listen_seq()          # 락 대기 중에 취소돼도 녹음을 시작하지 않게 도착 순번 기록
                with _stt_lock:
                    text = stt_listen_once(seq, stt_lang)

            loc = match_location(text)
            print(f"[kiosk] 인식({stt_lang})='{text}'  →  매칭={loc or '없음'}", flush=True)
            _exp_event("listen", loc=loc, typed=debug_text is not None,
                       speech_end=None if debug_text is not None else _recent_speech_end(30.0))
            self._send_json({
                "text": text,
                "locationId": loc,
                "confidence": 0.95 if loc else 0.3,
            })
        except Exception as exc:
            # STT 미구성(whisper-server/마이크 없음) 등 → 브라우저가 재시도 UX 처리
            self._send_json({
                "text": "", "locationId": None, "confidence": 0.0,
                "error": str(exc),
            }, 200)

    def log_message(self, *args):
        pass


def main():
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8000
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    with socketserver.ThreadingTCPServer(("0.0.0.0", port), Handler) as httpd:
        print(f"[kiosk] http://localhost:{port}/   (정적 + /listen + /goal + /nav)")
        print(f"[kiosk] STT_AUDIO_DEVICE={STT_DEVICE} (인식 채널 {STT_CHANNEL} · 감지 채널 {STT_VAD_CHANNEL} / {STT_CHANNELS})  WHISPER_SERVER_URL={WHISPER_URL}")
        # VAD 임계값을 시작 시 미리 측정(캐시). 이래야 첫 /listen 때 발화 앞부분이 안 잘림.
        try:
            MIC_FLAG.unlink()          # 이전 실행이 남긴 녹음 중 표시 정리
        except OSError:
            pass
        _get_vad_threshold()
        _get_silero()                  # 신경망 말소리 감지 모델도 미리 로드
        print("[kiosk] 종료: Ctrl+C")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()
