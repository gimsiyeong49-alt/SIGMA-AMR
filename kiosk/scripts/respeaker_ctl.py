#!/usr/bin/env python3
# respeaker_ctl.py — reSpeaker XVF3800 장치 내부 제어(USB 제어 전송) — 스피커 앰프·마이크 음소거 핀 읽기/쓰기
#
#   사용법:  python3 scripts/respeaker_ctl.py status        핀 상태 읽기(앰프 X0D31, 마이크 음소거 X0D30 …)
#            python3 scripts/respeaker_ctl.py amp-on        스피커 앰프 켜기(X0D31 = 0)
#   근거: Seeed 위키 GPIO 표 "X0D31 Output — Amplifier enable (low = enabled)", "X0D30 — Mute LED + mic mute (high = mute)"
#         명령: GPO 리소스 20 · 읽기 cmd 0(0x80 표시) · 쓰기 cmd 1 [핀, 값]. 제어 전송 bRequest 0, wValue=cmd, wIndex=resid,
#         읽기 응답 첫 바이트 = 상태(0=성공).
#   2026-11-15: 소리 데이터는 장치까지 가는데(장치 에코 제거 채널 반응) 스피커가 무음 — 앰프 핀 확인용으로 작성.
#   USB 장치 파일 쓰기 권한이 필요(없으면 sudo 또는 udev 규칙 MODE=0666, install_respeaker_autofix.sh).
import ctypes, fcntl, glob, os, struct, sys, time

VID = 0x2886
GPO_RESID, GPO_READ, GPO_WRITE = 20, 0, 1
# 읽기 값 6개 = 핀 번호 순서(2026-11-15 확인: X0D11·X0D33 을 켜 보니 0번·4번 값이 바뀜). 읽기 길이 5 로 하면 상태 66(길이 오류)
PINS = ["X0D11", "X0D30(마이크 음소거·빨간 LED, 1=음소거)", "X0D31(스피커 앰프, 0=켜짐)", "X0D32", "X0D33(LED 전원, 1=켜짐)", "X0D39"]


class CtrlTransfer(ctypes.Structure):
    _fields_ = [("bRequestType", ctypes.c_uint8), ("bRequest", ctypes.c_uint8), ("wValue", ctypes.c_uint16),
                ("wIndex", ctypes.c_uint16), ("wLength", ctypes.c_uint16), ("timeout", ctypes.c_uint32),
                ("data", ctypes.c_void_p)]


USBDEVFS_CONTROL = (3 << 30) | (ctypes.sizeof(CtrlTransfer) << 16) | (ord("U") << 8) | 0


def find_node():
    for d in glob.glob("/sys/bus/usb/devices/*"):
        try:
            if int(open(f"{d}/idVendor").read(), 16) == VID and "reSpeaker" in open(f"{d}/product").read():
                return "/dev/bus/usb/%03d/%03d" % (int(open(f"{d}/busnum").read()), int(open(f"{d}/devnum").read()))
        except (OSError, ValueError):
            continue
    return None


def ctrl(fd, req_type, wvalue, windex, buf):
    b = ctypes.create_string_buffer(bytes(buf), len(buf))
    ct = CtrlTransfer(req_type, 0, wvalue, windex, len(buf), 1000, ctypes.cast(b, ctypes.c_void_p))
    n = fcntl.ioctl(fd, USBDEVFS_CONTROL, ct)
    return b.raw[:n] if req_type & 0x80 else n


def read_gpo(fd, n=6):
    """→ (상태, 값 목록). 상태 0 = 성공, 64 = 다시 시도, 66 = 길이 오류 — 0 이 아니면 값은 의미 없음"""
    for _ in range(3):
        r = ctrl(fd, 0xC0, 0x80 | GPO_READ, GPO_RESID, b"\0" * (n + 1))
        if r[0] != 64:
            break
        time.sleep(0.05)
    return r[0], list(r[1:])


def main():
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    node = find_node()
    if not node:
        print("reSpeaker 없음"); return 1
    try:
        fd = os.open(node, os.O_RDWR)
    except PermissionError:
        print(f"권한 없음: {node} — sudo 로 실행하거나 install_respeaker_autofix.sh 로 udev 권한 설치"); return 3
    try:
        if cmd == "amp-on":
            st, before = read_gpo(fd)
            if st != 0:
                print(f"  · 바꾸기 전 앰프 핀 읽기 실패(상태 {st})")
            else:
                print(f"  · 바꾸기 전 앰프 핀 X0D31 = {before[2]} ({'꺼짐 ← 무음 원인' if before[2] else '켜짐'})")
            ctrl(fd, 0x40, GPO_WRITE, GPO_RESID, bytes([31, 0]))
            print("  · 스피커 앰프 켜기(X0D31=0) 보냄")
        st, vals = read_gpo(fd)
        if st != 0:
            print(f"핀 읽기 실패: 상태 바이트 {st} (0=성공) — 값을 믿을 수 없음"); return 4
        print(f"상태 바이트 {st} (0=성공) · 출력 핀 값 {vals}")
        for name, v in zip(PINS, vals):
            print(f"  {name}: {v}")
        return 0
    finally:
        os.close(fd)


if __name__ == "__main__":
    sys.exit(main())
