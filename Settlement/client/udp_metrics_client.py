# udp_metrics_client.py
# UDP 지연(RTT)/손실(타임아웃) 측정 클라이언트
# - 서버에 PING:<seq>: 보내고 PONG:<seq>: 수신까지 RTT 측정
# - 타임아웃이면 손실로 카운트
# - 종료 후 STATS:로 서버 메트릭 조회

import socket
import time
import sys
import statistics

SERVER_HOST = "127.0.0.1"
SERVER_PORT = 12000
BUF_SIZE = 2048
SEP = ":"


def parse_kv_stats(line: str):
    # STATS:TOTAL=..:PONG=..:CLIENTS=..:RPS60=..:
    out = {}
    parts = line.strip().split(SEP)
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k] = v
    return out


def main():
    host = SERVER_HOST
    port = SERVER_PORT
    count = 20
    interval = 0.2
    timeout = 0.5

    # 간단 인자 지원: python3 udp_metrics_client.py <host> <port> <count>
    if len(sys.argv) >= 2:
        host = sys.argv[1]
    if len(sys.argv) >= 3:
        port = int(sys.argv[2])
    if len(sys.argv) >= 4:
        count = int(sys.argv[3])

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)

    rtts = []
    lost = 0

    print(f"[UDP 측정] server={host}:{port} count={count} interval={interval}s timeout={timeout}s\n")

    try:
        for seq in range(1, count + 1):
            msg = f"PING:{seq}:"
            t0 = time.perf_counter()
            sock.sendto((msg + "\n").encode("utf-8"), (host, port))

            try:
                data, _ = sock.recvfrom(BUF_SIZE)
                t1 = time.perf_counter()
                line = data.decode("utf-8", errors="ignore").strip()
                parts = line.split(SEP)
                if len(parts) >= 2 and parts[0] == "PONG" and parts[1].strip() == str(seq):
                    rtt_ms = (t1 - t0) * 1000.0
                    rtts.append(rtt_ms)
                    print(f"#{seq:02d} PONG  rtt={rtt_ms:.2f} ms")
                else:
                    lost += 1
                    print(f"#{seq:02d} BAD_RESP ({line})")
            except socket.timeout:
                lost += 1
                print(f"#{seq:02d} TIMEOUT (loss)")

            time.sleep(interval)

        sent = count
        recv = len(rtts)
        loss_rate = (lost / sent) * 100.0

        print("\n--- 결과 요약 ---")
        print(f"sent={sent}, recv={recv}, lost={lost}, loss_rate={loss_rate:.1f}%")
        if rtts:
            print(f"avg={statistics.mean(rtts):.2f} ms, min={min(rtts):.2f} ms, max={max(rtts):.2f} ms")
            if len(rtts) >= 2:
                print(f"stdev={statistics.pstdev(rtts):.2f} ms")

        # 서버 메트릭 조회
        sock.sendto(b"STATS:\n", (host, port))
        try:
            data, _ = sock.recvfrom(BUF_SIZE)
            line = data.decode("utf-8", errors="ignore").strip()
            if line.startswith("STATS:"):
                s = parse_kv_stats(line)
                print("\n--- 서버 메트릭(STATS) ---")
                print(f"TOTAL={s.get('TOTAL')} PONG={s.get('PONG')} CLIENTS={s.get('CLIENTS')} RPS60={s.get('RPS60')}")
            else:
                print("\n[STATS] 응답 이상:", line)
        except socket.timeout:
            print("\n[STATS] 타임아웃")

    finally:
        sock.close()


if __name__ == "__main__":
    main()
