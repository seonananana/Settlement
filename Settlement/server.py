# server.py
# ExpenseChat TCP Server (방/비번/방입퇴장알림/정산/DB/핑)
# Protocol (":" 구분, 끝에 ":" 권장)
# ID:<id>:
# PING:
# ROOM:LIST:
# ROOM:JOIN:<room>[:<pw>]:
# BR:<msg>:
# TO:<toID>:<msg>:
# LIST:
# FILE:<toID>:<filename>:
# FILEDATA:<toID>:<filename>:<base64>:
# EXP:ADD:<amount>:<category>:<memo>:
# EXP:LIST:
# EXP:MINE:
# BAL:
# SETTLE:
# QUIT:

import socket
import threading
import sqlite3
from datetime import datetime
from typing import Optional, Dict, Set, Tuple, List

HOST = "0.0.0.0"
PORT = 10000
BUF_SIZE = 4096
DB_FILE = "settlement.db"
SEP = ":"


# ------------- 전역 상태 -------------
lock = threading.Lock()
clients: Dict[str, socket.socket] = {}          # {user_id: socket}
client_rooms: Dict[str, str] = {}              # {user_id: room}
rooms: Set[str] = set(["default"])             # room set
room_passwords: Dict[str, Optional[str]] = {}  # {room: password or None}


# ------------- DB -------------
def init_db():
    conn = sqlite3.connect(DB_FILE)
    try:
        cur = conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS expenses (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                room TEXT NOT NULL,
                user TEXT NOT NULL,
                amount INTEGER NOT NULL,
                category TEXT NOT NULL,
                memo TEXT,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.commit()
    finally:
        conn.close()


def db_execute(sql: str, params: Tuple = ()) -> int:
    conn = sqlite3.connect(DB_FILE)
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def db_query(sql: str, params: Tuple = ()) -> List[sqlite3.Row]:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    try:
        cur = conn.cursor()
        cur.execute(sql, params)
        return cur.fetchall()
    finally:
        conn.close()


# ------------- 유틸 -------------
def log_chat(text: str):
    # 필요하면 파일 로그로 남김 (발표/보고서용)
    try:
        ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open("chat.log", "a", encoding="utf-8") as f:
            f.write(f"[{ts}] {text}\n")
    except:
        pass


def send_line(sock: socket.socket, text: str):
    try:
        sock.sendall((text + "\n").encode("utf-8"))
    except:
        pass


def safe_strip_trailing_colon(line: str) -> str:
    line = line.strip()
    if line.endswith(":"):
        return line[:-1]
    return line


def broadcast_global(text: str, exclude_id: Optional[str] = None):
    with lock:
        items = list(clients.items())
    for uid, s in items:
        if exclude_id is not None and uid == exclude_id:
            continue
        send_line(s, text)


def broadcast_room(text: str, room: str, exclude_id: Optional[str] = None):
    with lock:
        # room에 속한 유저만
        targets = [(uid, sock) for uid, sock in clients.items() if client_rooms.get(uid) == room]
    for uid, s in targets:
        if exclude_id is not None and uid == exclude_id:
            continue
        send_line(s, text)


def get_room_password(room: str) -> Optional[str]:
    with lock:
        return room_passwords.get(room)


def set_room_password(room: str, pw: Optional[str]):
    with lock:
        room_passwords[room] = pw


def list_room_members(room: str) -> List[str]:
    with lock:
        return [uid for uid in clients.keys() if client_rooms.get(uid) == room]


# ------------- 핵심 처리 -------------
def handle_client(conn: socket.socket, addr):
    my_id: Optional[str] = None
    my_room: str = "default"
    buffer = ""

    print(f"[연결] {addr}")
    log_chat(f"CONNECT addr={addr}")

    try:
        while True:
            data = conn.recv(BUF_SIZE)
            if not data:
                break
            buffer += data.decode("utf-8", errors="ignore")

            while "\n" in buffer:
                raw_line, buffer = buffer.split("\n", 1)
                raw_line = raw_line.strip()
                if not raw_line:
                    continue

                line = safe_strip_trailing_colon(raw_line)

                # code만 먼저 분리
                if SEP in line:
                    code = line.split(SEP, 1)[0]
                else:
                    code = line

                # ---------- 로그인 ----------
                if code == "ID":
                    # ID:<wanted>
                    parts = line.split(SEP, 1)
                    if len(parts) < 2 or not parts[1].strip():
                        send_line(conn, "ID:FAIL:BAD_FORMAT:")
                        continue

                    wanted = parts[1].strip()

                    with lock:
                        if wanted in clients:
                            send_line(conn, "ID:FAIL:ID_IN_USE:")
                            continue
                        clients[wanted] = conn
                        client_rooms[wanted] = "default"
                        rooms.add("default")

                    my_id = wanted
                    my_room = "default"

                    send_line(conn, "ID:OK:")
                    print(f"[로그인] {my_id} / {addr}")
                    log_chat(f"LOGIN id={my_id} addr={addr}")

                    # 전체 입장 알림(전체)
                    broadcast_global(f"SYS:ENTER:{my_id}:", exclude_id=my_id)
                    # 같은 방(default) 입장 알림(방 단위)
                    broadcast_room(f"SYS:ROOM_ENTER:{my_id}:{my_room}:", my_room, exclude_id=my_id)
                    continue

                # 로그인 안 됐으면 차단
                if my_id is None:
                    send_line(conn, "ERROR:NOT_LOGGED_IN:먼저 ID를 등록하세요:")
                    continue

                # ---------- PING/PONG ----------
                if code == "PING":
                    send_line(conn, "PONG:")
                    continue

                # ---------- ROOM ----------
                if code == "ROOM":
                    # ROOM:LIST
                    # ROOM:JOIN:<room>[:pw]
                    parts = line.split(SEP)
                    if len(parts) < 2:
                        send_line(conn, "ERROR:BAD_ROOM:형식 오류:")
                        continue

                    sub = parts[1].strip()

                    if sub == "LIST":
                        with lock:
                            rlist = sorted(list(rooms))
                        payload = ",".join(rlist)
                        send_line(conn, f"ROOM:LIST:{len(rlist)}:{payload}:")
                        continue

                    if sub == "JOIN":
                        if len(parts) < 3:
                            send_line(conn, "ROOM:JOIN:FAIL:BAD_NAME:")
                            continue

                        room_name = parts[2].strip()
                        provided_pw = parts[3] if len(parts) >= 4 else None
                        if provided_pw is not None:
                            provided_pw = provided_pw.strip() or None

                        if not room_name:
                            send_line(conn, "ROOM:JOIN:FAIL:BAD_NAME:")
                            continue

                        # 방 생성/비번 설정/검증
                        stored_pw = get_room_password(room_name)

                        if stored_pw is None and room_name not in room_passwords:
                            # 최초 생성: 제공된 pw로 설정(없으면 None)
                            set_room_password(room_name, provided_pw)
                            with lock:
                                rooms.add(room_name)
                            stored_pw = provided_pw
                        else:
                            # 기존 방: pw 필요하면 검사
                            if stored_pw:
                                if not provided_pw:
                                    send_line(conn, "ROOM:JOIN:FAIL:NEED_PASSWORD:")
                                    continue
                                if provided_pw != stored_pw:
                                    send_line(conn, "ROOM:JOIN:FAIL:BAD_PASSWORD:")
                                    continue

                        old_room = my_room

                        with lock:
                            client_rooms[my_id] = room_name
                            my_room = room_name
                            rooms.add(room_name)

                        send_line(conn, f"ROOM:JOIN:OK:{room_name}:")

                        # ✅ 방 이동 알림(같은 방 사람에게만)
                        if old_room != room_name:
                            broadcast_room(f"SYS:ROOM_LEAVE:{my_id}:{old_room}:", old_room, exclude_id=my_id)
                            broadcast_room(f"SYS:ROOM_ENTER:{my_id}:{room_name}:", room_name, exclude_id=my_id)

                        log_chat(f"ROOM_JOIN id={my_id} {old_room} -> {room_name}")
                        continue

                    send_line(conn, "ERROR:UNKNOWN_ROOM:알 수 없는 ROOM 명령:")
                    continue

                # ---------- 전체 채팅(방 단위) ----------
                if code == "BR":
                    # BR:<msg> (msg는 콜론 포함 가능)
                    # "BR:" 이후를 그대로 msg로 취급
                    msg = ""
                    if line.startswith("BR:"):
                        msg = line[3:]  # 'BR:' 제거
                    msg = msg.strip()
                    if not msg:
                        send_line(conn, "ERROR:BAD_BR:메시지가 없습니다:")
                        continue

                    broadcast_room(f"BR:{my_id}:{msg}:", my_room)
                    log_chat(f"BR room={my_room} {my_id}: {msg}")
                    continue

                # ---------- 귓속말 ----------
                if code == "TO":
                    # TO:<toID>:<msg> (msg 콜론 포함 가능)
                    # split 최대 2번만
                    parts = line.split(SEP, 2)
                    if len(parts) < 3:
                        send_line(conn, "TO:FAIL:BAD_FORMAT:")
                        continue
                    to_id = parts[1].strip()
                    msg = parts[2].strip()

                    with lock:
                        target = clients.get(to_id)

                    if not target:
                        send_line(conn, "TO:FAIL:NO_SUCH_USER:")
                    else:
                        send_line(target, f"TO:{my_id}:{msg}:")
                        send_line(conn, "TO:OK:")
                        log_chat(f"TO {my_id} -> {to_id}: {msg}")
                    continue

                # ---------- 접속자 리스트(현재 방 기준) ----------
                if code == "LIST":
                    ids = list_room_members(my_room)
                    payload = ",".join(ids)
                    send_line(conn, f"LIST:{len(ids)}:{payload}:")
                    continue

                # ---------- 파일 ----------
                if code == "FILE":
                    # FILE:toID:filename
                    parts = line.split(SEP, 2)
                    if len(parts) < 3:
                        send_line(conn, "ERROR:FILE_BAD_FORMAT:형식 오류:")
                        continue
                    to_id = parts[1].strip()
                    filename = parts[2].strip()

                    with lock:
                        target = clients.get(to_id)
                    if not target:
                        send_line(conn, "ERROR:FILE_NO_SUCH_USER:대상 없음:")
                        continue

                    send_line(target, f"FILE:{my_id}:{filename}:")
                    continue

                if code == "FILEDATA":
                    # FILEDATA:toID:filename:base64
                    parts = line.split(SEP, 3)
                    if len(parts) < 4:
                        send_line(conn, "ERROR:FILEDATA_BAD_FORMAT:형식 오류:")
                        continue
                    to_id = parts[1].strip()
                    filename = parts[2].strip()
                    b64 = parts[3].strip()

                    with lock:
                        target = clients.get(to_id)
                    if not target:
                        send_line(conn, "ERROR:FILEDATA_NO_SUCH_USER:대상 없음:")
                        continue

                    send_line(target, f"FILEDATA:{my_id}:{filename}:{b64}:")
                    continue

                # ---------- 지출(EXP) ----------
                if code == "EXP":
                    parts = line.split(SEP, 1)
                    if len(parts) < 2:
                        send_line(conn, "ERROR:BAD_EXP:형식 오류:")
                        continue

                    # sub까지 분리
                    rest = parts[1]
                    sub = rest.split(SEP, 1)[0].strip() if SEP in rest else rest.strip()

                    if sub == "ADD":
                        # EXP:ADD:amount:category:memo (memo 콜론 포함 가능)
                        parts2 = line.split(SEP, 4)
                        # [EXP, ADD, amount, category, memo]
                        if len(parts2) < 4:
                            send_line(conn, "EXP:ADD:FAIL:BAD_FORMAT:")
                            continue

                        amount_str = parts2[2].strip()
                        category = parts2[3].strip()
                        memo = parts2[4].strip() if len(parts2) >= 5 else ""

                        try:
                            amount = int(amount_str)
                            if amount <= 0:
                                raise ValueError
                        except:
                            send_line(conn, "EXP:ADD:FAIL:BAD_AMOUNT:")
                            continue

                        created_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                        exp_id = db_execute(
                            "INSERT INTO expenses(room,user,amount,category,memo,created_at) VALUES(?,?,?,?,?,?)",
                            (my_room, my_id, amount, category, memo, created_at),
                        )

                        send_line(conn, f"EXP:ADD:OK:{exp_id}:")
                        # 방 사람들에게 새 지출 알림
                        broadcast_room(f"EXP:NEW:{exp_id}:{my_id}:{amount}:{category}:{memo}:", my_room)
                        log_chat(f"EXP_ADD room={my_room} id={exp_id} user={my_id} {amount} {category} {memo}")
                        continue

                    if sub == "LIST":
                        rows = db_query(
                            "SELECT id,user,amount,category,memo FROM expenses WHERE room=? ORDER BY id",
                            (my_room,),
                        )
                        items = []
                        for r in rows:
                            items.append(f"{r['id']}#{r['user']}#{r['amount']}#{r['category']}#{r['memo']}")
                        payload = "|".join(items)
                        send_line(conn, f"EXP:LIST:{len(rows)}:{payload}:")
                        continue

                    if sub == "MINE":
                        rows = db_query(
                            "SELECT id,user,amount,category,memo FROM expenses WHERE room=? AND user=? ORDER BY id",
                            (my_room, my_id),
                        )
                        items = []
                        for r in rows:
                            items.append(f"{r['id']}#{r['user']}#{r['amount']}#{r['category']}#{r['memo']}")
                        payload = "|".join(items)
                        send_line(conn, f"EXP:MINE:{len(rows)}:{payload}:")
                        continue

                    send_line(conn, "ERROR:UNKNOWN_EXP:알 수 없는 EXP 명령:")
                    continue

                # ---------- BAL ----------
                if code == "BAL":
                    rows = db_query(
                        "SELECT user, SUM(amount) AS total FROM expenses WHERE room=? GROUP BY user",
                        (my_room,),
                    )
                    if not rows:
                        send_line(conn, "BAL:0:0:0::")
                        continue

                    sums = {r["user"]: int(r["total"]) for r in rows}
                    total = sum(sums.values())
                    n = len(sums)
                    per = total // n if n > 0 else 0

                    entries = []
                    for uid, paid in sums.items():
                        diff = paid - per
                        entries.append(f"{uid}#{paid}#{diff}")
                    payload = ",".join(entries)

                    send_line(conn, f"BAL:{total}:{per}:{n}:{payload}:")
                    continue

                # ---------- SETTLE ----------
                if code == "SETTLE":
                    rows = db_query(
                        "SELECT user, SUM(amount) AS total FROM expenses WHERE room=? GROUP BY user",
                        (my_room,),
                    )
                    if not rows:
                        send_line(conn, "SETTLE:0::")
                        continue

                    sums = {r["user"]: int(r["total"]) for r in rows}
                    total = sum(sums.values())
                    n = len(sums)
                    per = total // n if n > 0 else 0

                    creditors = []  # [uid, diff+]
                    debtors = []    # [uid, need+]
                    for uid, paid in sums.items():
                        diff = paid - per
                        if diff > 0:
                            creditors.append([uid, diff])
                        elif diff < 0:
                            debtors.append([uid, -diff])

                    transfers = []
                    i = j = 0
                    while i < len(debtors) and j < len(creditors):
                        duid, damt = debtors[i]
                        cuid, camt = creditors[j]
                        amount = min(damt, camt)
                        if amount > 0:
                            transfers.append(f"{duid}#{cuid}#{amount}")
                        damt -= amount
                        camt -= amount
                        if damt == 0:
                            i += 1
                        else:
                            debtors[i][1] = damt
                        if camt == 0:
                            j += 1
                        else:
                            creditors[j][1] = camt

                    payload = ",".join(transfers)
                    send_line(conn, f"SETTLE:{len(transfers)}:{payload}:")
                    continue

                # ---------- QUIT ----------
                if code in ("QUIT", "Q"):
                    send_line(conn, "QUIT:OK:")
                    raise SystemExit

                # ---------- UNKNOWN ----------
                send_line(conn, "ERROR:UNKNOWN_CMD:알 수 없는 명령:")

    except SystemExit:
        pass
    except Exception as e:
        print(f"[에러] {addr} - {e}")
        log_chat(f"ERROR addr={addr} {e}")
    finally:
        if my_id:
            last_room = my_room

            with lock:
                if clients.get(my_id) is conn:
                    del clients[my_id]
                client_rooms.pop(my_id, None)

            # ✅ 같은 방 사람들에게 “방에서 나감”
            if last_room:
                broadcast_room(f"SYS:ROOM_LEAVE:{my_id}:{last_room}:", last_room, exclude_id=my_id)

            # 기존: 전체 퇴장 알림
            broadcast_global(f"SYS:LEAVE:{my_id}:", exclude_id=my_id)

            print(f"[종료] {my_id} / {addr}")
            log_chat(f"LEAVE id={my_id} room={last_room} addr={addr}")

        conn.close()


def main():
    init_db()

    server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    server.bind((HOST, PORT))
    server.listen()

    print(f"[서버 시작] {HOST}:{PORT}")

    try:
        while True:
            conn, addr = server.accept()
            t = threading.Thread(target=handle_client, args=(conn, addr), daemon=True)
            t.start()
    except KeyboardInterrupt:
        print("\n[서버 종료]")
    finally:
        server.close()


if __name__ == "__main__":
    main()
