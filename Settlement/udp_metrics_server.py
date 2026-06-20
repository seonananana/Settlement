# udp_metrics_server.py
# UDP 측정용 서버 (지연/손실/메트릭)
# - 수신:  PING:<seq>:
# - 응답:  PONG:<seq>:
# - 조회:  STATS:
# - 응답:  STATS:TOTAL=<n>:PONG=<n>:CLIENTS=<n>:RPS60=<n>:

import socket
import time
import threading
from collections import deque

HOST = "0.0.0.0"
PORT = 12000
BUF_SIZE = 2048
SEP = ":"


class Metrics:
    def __init__(self):
        self.lock = threading.Lock()
        self.total_ping = 0
        self.total_pong = 0
        self.clients = set()
        self.last60 = deque()  # 최근 60초 ping 수신 시간(모노토닉)

    def on_ping(self, addr):
        now = time.monotonic()
        with self.lock:
            self.total_ping += 1
            self.clients.add(addr)
            self.last60.append(now)
            # 60초 밖 제거
            cutoff = now - 60.0
            while self.last60 and self.last60[0] < cutoff:
                self.last60.popleft()

    def on_pong(self):
        with self.lock:
            self.total_pong += 1

    def snapshot(self):
        now = time.monotonic()
        with self.lock:
            cutoff = now - 60.0
            while self.last60 and self.last60[0] < cutoff:
                self.last60.popleft()
            rps60 = len(self.last60)  # 60초 동안의 요청 수 (간단 지표)
            return {
                "TOTAL": self.total_ping,
                "PONG": self.total_pong,
                "CLIENTS": len(self.clients),
                "RPS60": rps60,
            }


def sendto(sock: socket.socket, addr, text: str):
    try:
        sock.sendto((text + "\n").encode("utf-8"), addr)
    except:
        pass


def reporter(metrics: Metrics):
    while True:
        time.sleep(5)
        s = metrics.snapshot()
        print(f"[UDP METRICS] TOTAL={s['TOTAL']} PONG={s['PONG']} CLIENTS={s['CLIENTS']} RPS60={s['RPS60']}")


def main():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((HOST, PORT))

    metrics = Metrics()
    t = threading.Thread(target=reporter, args=(metrics,), daemon=True)
    t.start()

    print(f"[UDP 메트릭 서버 시작] {HOST}:{PORT}")
    print("수신: PING:<seq>:  | 응답: PONG:<seq>:  | 조회: STATS:\n")

    try:
        while True:
            data, addr = sock.recvfrom(BUF_SIZE)
            line = data.decode("utf-8", errors="ignore").strip()
            if not line:
                continue

            parts = line.split(SEP)
            cmd = parts[0].strip()

            if cmd == "PING":
                # PING:<seq>:
                seq = parts[1].strip() if len(parts) >= 2 else ""
                metrics.on_ping(addr)
                sendto(sock, addr, f"PONG:{seq}:")
                metrics.on_pong()
                continue

            if cmd == "STATS":
                s = metrics.snapshot()
                sendto(sock, addr, f"STATS:TOTAL={s['TOTAL']}:PONG={s['PONG']}:CLIENTS={s['CLIENTS']}:RPS60={s['RPS60']}:")
                continue

            # 알 수 없는 메시지는 무시(측정용이라 안전하게)
    except KeyboardInterrupt:
        print("\n[UDP 메트릭 서버 종료]")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
