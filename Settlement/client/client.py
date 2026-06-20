# client.py
# ExpenseChat TCP Client (명령어 UX + /leave + 방 입퇴장 알림 + PING/PONG)
import socket
import threading
import sys
import os
import base64
import time

HOST = "127.0.0.1"
PORT = 10000
SEP = ":"
BUF_SIZE = 4096

my_id = None
current_room = "default"

waiting_manual_pong = False  # /ping 친 뒤에만 PONG 출력


def send_line(sock, text: str):
    try:
        sock.sendall((text + "\n").encode("utf-8"))
    except:
        pass


def show_message(line: str):
    global current_room, waiting_manual_pong

    line = line.strip()
    if not line:
        return

    # 끝 ":" 제거(표시만)
    if line.endswith(":"):
        line = line[:-1]

    parts = line.split(SEP)
    code = parts[0]

    # 로그인 결과
    if code == "ID":
        if len(parts) >= 2 and parts[1] == "OK":
            print("[시스템] 로그인 성공")
        elif len(parts) >= 3 and parts[1] == "FAIL":
            print(f"[시스템] 로그인 실패: {parts[2]}")
        else:
            print("[서버]", line)
        return

    # PONG
    if code == "PONG":
        if waiting_manual_pong:
            print("[시스템] 서버 응답: PONG")
            waiting_manual_pong = False
        return

    # SYS
    if code == "SYS":
        if len(parts) >= 3:
            ev = parts[1]
            uid = parts[2]

            if ev == "ENTER":
                print(f"[알림] {uid} 님 입장")
            elif ev == "LEAVE":
                print(f"[알림] {uid} 님 퇴장")

            # ✅ 방 단위 이벤트
            elif ev == "ROOM_ENTER":
                room = parts[3] if len(parts) >= 4 else ""
                print(f"[방 알림] {uid} 님이 방({room})에 들어왔어요")
            elif ev == "ROOM_LEAVE":
                room = parts[3] if len(parts) >= 4 else ""
                print(f"[방 알림] {uid} 님이 방({room})에서 나갔어요")
            else:
                print("[SYS]", line)
        else:
            print("[SYS]", line)
        return

    # ROOM
    if code == "ROOM":
        if len(parts) >= 2:
            sub = parts[1]

            if sub == "LIST":
                # ROOM:LIST:count:room1,room2,...
                if len(parts) >= 3:
                    cnt = parts[2]
                    print(f"[방 목록] 총 {cnt}개")
                    if len(parts) >= 4 and parts[3]:
                        names = parts[3].split(",")
                        for r in names:
                            if r:
                                print(f"  - {r}")
                else:
                    print("[ROOM LIST]", line)
                return

            if sub == "JOIN":
                # ROOM:JOIN:OK:room
                # ROOM:JOIN:FAIL:REASON
                if len(parts) >= 3 and parts[2] == "OK":
                    room_name = parts[3] if len(parts) >= 4 else ""
                    current_room = room_name or current_room
                    print(f"[방 전환] 현재 방 = {current_room}")
                elif len(parts) >= 3 and parts[2] == "FAIL":
                    reason = parts[3] if len(parts) >= 4 else ""
                    if reason == "BAD_NAME":
                        print("[방] 방 이름이 올바르지 않습니다.")
                    elif reason == "NEED_PASSWORD":
                        print("[방] 비밀번호가 필요한 방입니다. /room <name> <password>")
                    elif reason == "BAD_PASSWORD":
                        print("[방] 비밀번호가 올바르지 않습니다.")
                    else:
                        print(f"[방] 입장 실패: {reason}")
                else:
                    print("[ROOM JOIN]", line)
                return

        print("[ROOM]", line)
        return

    # 전체 채팅(방 단위)
    if code == "BR":
        if len(parts) >= 3:
            uid = parts[1]
            msg = SEP.join(parts[2:])  # 메시지에 ':'가 섞여도 최대한 복구
            print(f"[전체][{uid}] {msg}")
        else:
            print("[BR]", line)
        return

    # 귓속말
    if code == "TO":
        if len(parts) >= 3 and parts[1] not in ("OK", "FAIL"):
            uid = parts[1]
            msg = SEP.join(parts[2:])
            print(f"[귓속말][{uid}] {msg}")
        elif len(parts) >= 2 and parts[1] == "OK":
            print("[시스템] 귓속말 전송 완료")
        elif len(parts) >= 3 and parts[1] == "FAIL":
            print(f"[시스템] 귓속말 실패: {parts[2]}")
        else:
            print("[TO]", line)
        return

    # 접속자 리스트(현재 방 기준)
    if code == "LIST":
        if len(parts) >= 3:
            cnt = parts[1]
            ids = parts[2]
            print(f"[접속자 {cnt}명] {ids}")
        else:
            print("[LIST]", line)
        return

    # 파일
    if code == "FILE":
        if len(parts) >= 3:
            from_id = parts[1]
            filename = parts[2]
            print(f"[파일][{from_id}] {filename} 전송 중... (잠시 후 저장)")
        else:
            print("[파일 헤더]", line)
        return

    if code == "FILEDATA":
        if len(parts) >= 4:
            from_id = parts[1]
            filename = parts[2]
            b64 = parts[3]
            try:
                data = base64.b64decode(b64.encode("ascii"))
                save_name = f"recv_{filename}"
                with open(save_name, "wb") as f:
                    f.write(data)
                print(f"[파일][{from_id}] {filename} 수신 완료 → {save_name}")
            except Exception as e:
                print(f"[파일 에러] 디코딩 실패: {e}")
        else:
            print("[FILEDATA]", line)
        return

    # 지출
    if code == "EXP":
        if len(parts) >= 2:
            sub = parts[1]

            if sub == "ADD":
                if len(parts) >= 3 and parts[2] == "OK":
                    print(f"[지출] 등록 완료 (ID={parts[3]})" if len(parts) >= 4 else "[지출] 등록 완료")
                elif len(parts) >= 3 and parts[2] == "FAIL":
                    print(f"[지출] 등록 실패: {parts[3] if len(parts)>=4 else ''}")
                else:
                    print("[EXP ADD]", line)
                return

            if sub == "NEW":
                # EXP:NEW:expID:user:amount:category:memo
                if len(parts) >= 6:
                    exp_id = parts[2]
                    user = parts[3]
                    amount = parts[4]
                    category = parts[5]
                    memo = parts[6] if len(parts) >= 7 else ""
                    print(f"[지출 #{exp_id}][{user}] {amount}원 ({category}) - {memo}")
                else:
                    print("[EXP NEW]", line)
                return

            if sub == "LIST":
                # EXP:LIST:count:payload
                if len(parts) >= 3:
                    cnt = parts[2]
                    print(f"[지출 목록] 총 {cnt}건")
                    if len(parts) >= 4 and parts[3]:
                        rows = parts[3].split("|")
                        for row in rows:
                            if not row:
                                continue
                            eid, user, amt, cat, memo = row.split("#", 4)
                            print(f"  #{eid} {user} {amt}원 [{cat}] {memo}")
                else:
                    print("[EXP LIST]", line)
                return

            if sub == "MINE":
                if len(parts) >= 3:
                    cnt = parts[2]
                    print(f"[내 지출] 총 {cnt}건")
                    if len(parts) >= 4 and parts[3]:
                        rows = parts[3].split("|")
                        for row in rows:
                            if not row:
                                continue
                            eid, user, amt, cat, memo = row.split("#", 4)
                            print(f"  #{eid} {amt}원 [{cat}] {memo}")
                else:
                    print("[EXP MINE]", line)
                return

        print("[EXP]", line)
        return

    # BAL
    if code == "BAL":
        if len(parts) >= 5:
            total = parts[1]
            per = parts[2]
            cnt = parts[3]
            print(f"[정산 요약] 총액 {total}원, 인원 {cnt}명, 1인당 {per}원")
            if parts[4]:
                rows = parts[4].split(",")
                for row in rows:
                    if not row:
                        continue
                    uid, paid, diff = row.split("#", 2)
                    diff_i = int(diff)
                    if diff_i > 0:
                        print(f"  {uid}: {paid}원 (+{diff_i}원 더 냈음)")
                    elif diff_i < 0:
                        print(f"  {uid}: {paid}원 ({-diff_i}원 덜 냈음)")
                    else:
                        print(f"  {uid}: {paid}원 (딱 맞게 냈음)")
        else:
            print("[BAL]", line)
        return

    # SETTLE
    if code == "SETTLE":
        if len(parts) >= 3:
            cnt = parts[1]
            print(f"[정산 추천] 총 {cnt}건")
            if parts[2]:
                rows = parts[2].split(",")
                for row in rows:
                    if not row:
                        continue
                    from_id, to_id, amount = row.split("#", 2)
                    print(f"  {from_id} → {to_id} : {amount}원 송금")
        else:
            print("[SETTLE]", line)
        return

    # QUIT
    if code == "QUIT":
        print("[시스템] 서버가 종료 응답을 보냈습니다.")
        return

    # ERROR
    if code == "ERROR":
        if len(parts) >= 3:
            print(f"[에러][{parts[1]}] {parts[2]}")
        else:
            print("[에러]", line)
        return

    print("[서버]", line)


def receiver(sock: socket.socket):
    buffer = ""
    try:
        while True:
            data = sock.recv(BUF_SIZE)
            if not data:
                print("[시스템] 서버 연결 끊김")
                break
            buffer += data.decode("utf-8", errors="ignore")
            while "\n" in buffer:
                line, buffer = buffer.split("\n", 1)
                line = line.strip()
                if not line:
                    continue
                show_message(line)
    except Exception as e:
        print(f"[수신 에러] {e}")
    finally:
        sock.close()
        sys.exit(0)


def ping_loop(sock: socket.socket):
    # 30초마다 자동 핑(화면 출력 없음)
    while True:
        time.sleep(30)
        try:
            sock.sendall(b"PING:\n")
        except:
            break


def print_help():
    print("\n=== 명령어 도움말 ===")
    print("/help                     : 이 도움말 보기")
    print("/room <name> [password]   : 방(프로젝트) 선택/생성")
    print("/rooms                    : 방 목록 조회")
    print("/leave                    : 현재 방 나가기(기본 방으로 이동)")
    print("/ping                     : 서버에 PING 보내기")
    print("/w <id> <msg>             : 귓속말")
    print("/list                     : 접속자 리스트(현재 방)")
    print("/file <id> <경로>         : 파일 전송 (base64 한 줄)")
    print("/exp add 금액 카테고리 [메모...]")
    print("/exp list                 : 현재 방의 전체 지출")
    print("/exp mine                 : 현재 방의 내 지출")
    print("/bal                      : 현재 방 기준 정산 요약")
    print("/settle                   : 현재 방 기준 정산 추천")
    print("/quit                     : 종료")
    print("그 외 텍스트             : 현재 방 전체 채팅")
    print("====================\n")


def main():
    global my_id, waiting_manual_pong

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.connect((HOST, PORT))
    print(f"[시스템] 서버({HOST}:{PORT}) 연결 완료")

    # 로그인
    while True:
        user = input("사용할 ID 입력: ").strip()
        if not user:
            continue
        send_line(sock, f"ID:{user}:")
        resp = sock.recv(BUF_SIZE).decode("utf-8", errors="ignore").strip()
        print("서버 응답:", resp)
        if resp.startswith("ID:OK"):
            my_id = user
            break
        print("다른 ID를 사용하세요.\n")

    # 수신 스레드
    threading.Thread(target=receiver, args=(sock,), daemon=True).start()
    # 자동 ping
    threading.Thread(target=ping_loop, args=(sock,), daemon=True).start()

    print_help()

    try:
        while True:
            raw = input("> ")
            if raw is None:
                continue
            line = raw.strip()
            if not line:
                continue

            # -------- 명령어 정규화 --------
            norm = line

            # "/ exp ..." -> "/exp ..."
            if norm.startswith("/ "):
                norm = "/" + norm[2:].lstrip()

            # ".exp list" -> "/exp list"
            if norm.startswith("."):
                norm = "/" + norm[1:]

            lower_norm = norm.lower()

            # 슬래시 없이도 명령으로 처리(실수 방지)
            if not norm.startswith("/"):
                if lower_norm.startswith("room "):
                    norm = "/room " + norm[5:]
                elif lower_norm == "rooms":
                    norm = "/rooms"
                elif lower_norm == "leave":
                    norm = "/leave"
                elif lower_norm == "ping":
                    norm = "/ping"
                elif lower_norm == "help":
                    norm = "/help"
                elif lower_norm.startswith("exp "):
                    norm = "/exp " + norm[4:]
                elif lower_norm == "bal":
                    norm = "/bal"
                elif lower_norm == "settle":
                    norm = "/settle"
                elif lower_norm == "list":
                    norm = "/list"
                elif lower_norm == "quit":
                    norm = "/quit"
                elif lower_norm.startswith("w "):
                    norm = "/w " + norm[2:]
                elif lower_norm.startswith("file "):
                    norm = "/file " + norm[5:]

            line = norm
            lower = line.lower()

            # -------- 명령 처리 --------
            if lower == "/help":
                print_help()
                continue

            if lower == "/ping":
                waiting_manual_pong = True
                send_line(sock, "PING:")
                continue

            if lower.startswith("/room "):
                parts = line.split(" ", 2)
                room_name = parts[1].strip() if len(parts) >= 2 else ""
                if not room_name:
                    print("[사용법] /room <name> [password]")
                    continue
                if len(parts) >= 3 and parts[2].strip():
                    pw = parts[2].strip()
                    send_line(sock, f"ROOM:JOIN:{room_name}:{pw}:")
                else:
                    send_line(sock, f"ROOM:JOIN:{room_name}:")
                continue

            if lower == "/leave":
                send_line(sock, "ROOM:JOIN:default:")
                continue

            if lower == "/rooms":
                send_line(sock, "ROOM:LIST:")
                continue

            if lower.startswith("/w "):
                parts = line.split(" ", 2)
                if len(parts) < 3:
                    print("[사용법] /w <id> <msg>")
                    continue
                to_id = parts[1].strip()
                msg = parts[2].strip()
                send_line(sock, f"TO:{to_id}:{msg}:")
                continue

            if lower == "/list":
                send_line(sock, "LIST:")
                continue

            if lower.startswith("/file "):
                parts = line.split(" ", 2)
                if len(parts) < 3:
                    print("[사용법] /file <id> <경로>")
                    continue
                to_id = parts[1].strip()
                path = parts[2].strip()
                if not os.path.exists(path):
                    print("[파일] 존재하지 않는 경로입니다.")
                    continue
                filename = os.path.basename(path)
                try:
                    with open(path, "rb") as f:
                        data = f.read()
                    b64 = base64.b64encode(data).decode("ascii")
                    send_line(sock, f"FILE:{to_id}:{filename}:")
                    send_line(sock, f"FILEDATA:{to_id}:{filename}:{b64}:")
                    print(f"[파일] {to_id} 에게 {filename} 전송 요청")
                except Exception as e:
                    print(f"[파일 에러] {e}")
                continue

            if lower.startswith("/exp add"):
                # /exp add 70000 FOOD [memo...]
                parts = line.split(" ", 4)
                if len(parts) < 4:
                    print("[사용법] /exp add 금액 카테고리 [메모...]")
                    continue
                amount = parts[2].strip()
                category = parts[3].strip()
                memo = parts[4].strip() if len(parts) >= 5 else ""
                send_line(sock, f"EXP:ADD:{amount}:{category}:{memo}:")
                continue

            if lower == "/exp list":
                send_line(sock, "EXP:LIST:")
                continue

            if lower == "/exp mine":
                send_line(sock, "EXP:MINE:")
                continue

            if lower in ("/bal", "/balance"):
                send_line(sock, "BAL:")
                continue

            if lower == "/settle":
                send_line(sock, "SETTLE:")
                continue

            if lower == "/quit":
                send_line(sock, "QUIT:")
                break

            # 기본: 현재 방 전체채팅
            send_line(sock, f"BR:{line}:")
    finally:
        sock.close()
        print("[시스템] 클라이언트 종료")


if __name__ == "__main__":
    main()
