#!/usr/bin/env python3
# nav_request_watcher_sim.py — 실제 주행 요청 감시기(hospital_mission/nav_request_watcher)를 '그대로' 불러와
#   요청 폴더만 시뮬 전용 폴더로 바꿔 실행한다. (실제 코드는 런치 인자를 안 읽고 실제 버스 폴더가 고정돼 있어,
#   그대로 띄우면 실제 로봇 요청 폴더를 건드림 → 모듈 변수만 바꿔 치움. 실제 코드는 수정하지 않음)
#   필수 환경변수: SIM_BUS (시뮬 전용 버스 폴더)
import importlib.machinery
import importlib.util
import os
import sys
from pathlib import Path

SRC = os.environ.get("NRW_SRC", "/mnt/ssd/cart_ros2/install/hospital_mission/lib/hospital_mission/nav_request_watcher")
bus = Path(os.environ["SIM_BUS"]).resolve()
if "llm_package/bus" in str(bus):
    sys.exit("SIM_BUS 가 실제 버스 폴더입니다 — 중단")
loader = importlib.machinery.SourceFileLoader("nav_request_watcher_real", SRC)
spec = importlib.util.spec_from_loader(loader.name, loader)
m = importlib.util.module_from_spec(spec)
loader.exec_module(m)
m.NAV_REQUEST_DIR = bus / "nav_request"
m.NAV_REQUEST_DONE_DIR = bus / "nav_request_done"
print(f"[sim] 주행 요청 폴더 → {m.NAV_REQUEST_DIR}", flush=True)
m.main()
