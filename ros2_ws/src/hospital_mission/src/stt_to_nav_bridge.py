#!/usr/bin/env python3

import subprocess
import re

STT_CMD = ["stt"]

NAV_SCRIPT = "/mnt/ssd/cart_ros2/src/hospital_mission/src/voice_to_nav.py"

LABELS = [
    "화장실",
    "417",
    "415",
    "410",
    "411",
    "412",
    "419",
    "track",
]

def extract_label(text):
    for label in LABELS:
        if label in text:
            return label
    return None

def clean_text(line):
    line = line.strip()
    line = re.sub(r"원본 인식\s*:", "", line)
    line = re.sub(r"파일 생성\s*:", "", line)
    line = line.replace("[", "").replace("]", "")
    return line.strip()

def main():
    print("[BRIDGE] STT → Nav bridge started")

    proc = subprocess.Popen(
        STT_CMD,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1
    )

    for line in proc.stdout:
        print(line, end="")

        text = clean_text(line)
        label = extract_label(text)

        if label:
            print(f"\n[BRIDGE] 목적지 감지: {label}")
            subprocess.run([
                "python3",
                NAV_SCRIPT,
                label
            ])

if __name__ == "__main__":
    main()
