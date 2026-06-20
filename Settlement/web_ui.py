import sqlite3
from datetime import date
from flask import Flask, request, render_template_string, Response, redirect, url_for
from io import StringIO
import csv

# ---- UDP 측정용(최소 패치) ----
import socket
import time
import statistics

DB_FILE = "settlement.db"

# UDP 메트릭 서버 주소(기본: 같은 환경에서 실행한다고 가정)
UDP_HOST = "127.0.0.1"
UDP_PORT = 12000

app = Flask(__name__)


def get_conn():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    return conn


# ---------------------------
# UDP 측정 유틸 (JSON 없음)
# ---------------------------
def _udp_send_recv(message: str, timeout: float = 0.25):
    """UDP로 1회 요청/응답. 실패 시 None"""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    try:
        sock.sendto((message + "\n").encode("utf-8"), (UDP_HOST, UDP_PORT))
        data, _ = sock.recvfrom(2048)
        return data.decode("utf-8", errors="ignore").strip()
    except Exception:
        return None
    finally:
        sock.close()


def udp_get_stats(timeout: float = 0.25):
    """
    STATS:TOTAL=..:PONG=..:CLIENTS=..:RPS60=..:
    -> dict 반환. 실패 시 None
    """
    line = _udp_send_recv("STATS:", timeout=timeout)
    if not line or not line.startswith("STATS:"):
        return None

    out = {}
    parts = line.split(":")
    for p in parts[1:]:
        if "=" in p:
            k, v = p.split("=", 1)
            out[k] = v
    return out


def udp_probe_rtt_loss(count: int = 5, timeout: float = 0.25, interval: float = 0.05):
    """
    PING:<seq>: -> PONG:<seq>:
    작은 횟수로 RTT/손실률 측정. 실패 시 None 반환.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(timeout)
    rtts = []
    lost = 0

    try:
        for seq in range(1, count + 1):
            msg = f"PING:{seq}:"
            t0 = time.perf_counter()
            try:
                sock.sendto((msg + "\n").encode("utf-8"), (UDP_HOST, UDP_PORT))
                data, _ = sock.recvfrom(2048)
                t1 = time.perf_counter()
                line = data.decode("utf-8", errors="ignore").strip()
                parts = line.split(":")
                if len(parts) >= 2 and parts[0] == "PONG" and parts[1].strip() == str(seq):
                    rtts.append((t1 - t0) * 1000.0)
                else:
                    lost += 1
            except Exception:
                lost += 1
            time.sleep(interval)

        sent = count
        recv = len(rtts)
        loss_rate = (lost / sent) * 100.0

        if recv == 0:
            # 전부 손실이면 측정 불가
            return {"sent": sent, "recv": recv, "lost": lost, "loss_rate": loss_rate, "avg": None, "min": None, "max": None}

        return {
            "sent": sent,
            "recv": recv,
            "lost": lost,
            "loss_rate": loss_rate,
            "avg": statistics.mean(rtts),
            "min": min(rtts),
            "max": max(rtts),
        }
    finally:
        sock.close()


# ---------------------------
# 웹 라우트
# ---------------------------
@app.route("/")
def index():
    conn = get_conn()
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT room FROM expenses ORDER BY room")
    rooms = [row["room"] for row in cur.fetchall()]
    conn.close()

    # UDP 상태(가벼운 STATS 1회만)
    udp_stats = udp_get_stats(timeout=0.15)
    udp_ok = udp_stats is not None

    template = """
    <!doctype html>
    <html lang="ko">
    <head>
        <meta charset="utf-8">
        <title>ExpenseChat 대시보드</title>
        <style>
            body {
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                padding: 24px;
                max-width: 960px;
                margin: 0 auto;
                background: #f9fafb;
            }
            a { color: #2563eb; text-decoration: none; }
            a:hover { text-decoration: underline; }

            .topbar {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 12px 20px;
                background: #111827;
                color: white;
                border-radius: 16px;
                margin-bottom: 16px;
                gap: 10px;
            }
            .brand {
                font-weight: 600;
                font-size: 18px;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            .logo-dot {
                width: 10px;
                height: 10px;
                border-radius: 999px;
                background: #10b981;
                display: inline-block;
            }
            .udp-pill {
                font-size: 12px;
                padding: 4px 10px;
                border-radius: 999px;
                background: #1f2937;
                display: inline-flex;
                align-items: center;
                gap: 6px;
                white-space: nowrap;
            }
            .dot {
                width: 8px; height: 8px; border-radius: 999px;
                background: #9ca3af;
            }
            .dot.on { background: #22c55e; }

            .topbar-right {
                font-size: 13px;
                opacity: 0.95;
                display: flex;
                align-items: center;
                gap: 10px;
            }
            select {
                font-size: 13px;
                padding: 3px 6px;
            }
            button {
                font-size: 13px;
                padding: 4px 10px;
                border-radius: 999px;
                border: none;
                background: #10b981;
                color: white;
                cursor: pointer;
            }
            button:hover { background: #059669; }

            .cards {
                display: flex;
                gap: 12px;
                flex-wrap: wrap;
                margin-bottom: 14px;
            }
            .card {
                flex: 1 1 220px;
                background: white;
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 10px 14px;
            }
            .label { font-size: 12px; color: #6b7280; }
            .value { font-size: 16px; font-weight: 650; }

            h2 { margin: 10px 0 8px; }
            .room-card {
                border: 1px solid #e5e7eb;
                border-radius: 12px;
                padding: 12px 16px;
                margin-bottom: 10px;
                background: white;
            }
            .room-name { font-weight: 600; font-size: 16px; margin-bottom: 4px; }
            .room-meta { font-size: 13px; color: #6b7280; }
        </style>
    </head>
    <body>
        <div class="topbar">
            <div class="brand">
                <span class="logo-dot"></span>
                ExpenseChat 대시보드
            </div>

            <div class="udp-pill">
                <span class="dot {% if udp_ok %}on{% endif %}"></span>
                UDP 메트릭 {% if udp_ok %}ON{% else %}OFF{% endif %}
            </div>

            <div class="topbar-right">
                {% if rooms %}
                <form method="get" action="/room" style="display:flex; align-items:center; gap:6px; margin:0;">
                    <select name="room">
                        {% for r in rooms %}
                          <option value="{{ r }}">{{ r }}</option>
                        {% endfor %}
                    </select>
                    <select name="range">
                        <option value="all">전체</option>
                        <option value="month">이번 달</option>
                    </select>
                    <button type="submit">보기</button>
                </form>
                {% else %}
                    방을 선택하면 지출·정산 현황을 한눈에 볼 수 있습니다
                {% endif %}
            </div>
        </div>

        <div class="cards">
            <div class="card">
                <div class="label">UDP 서버 메트릭</div>
                {% if udp_ok %}
                  <div class="value">TOTAL={{ udp_stats.get("TOTAL") }} / PONG={{ udp_stats.get("PONG") }}</div>
                  <div class="label">CLIENTS={{ udp_stats.get("CLIENTS") }} / RPS60={{ udp_stats.get("RPS60") }}</div>
                {% else %}
                  <div class="value">미실행 또는 접근 불가</div>
                  <div class="label">udp_metrics_server.py 실행 시 표시됨</div>
                {% endif %}
            </div>
            <div class="card">
                <div class="label">설계 포인트</div>
                <div class="value">TCP=서비스 / UDP=관측</div>
                <div class="label">UDP 미실행이어도 서비스 정상 동작</div>
            </div>
        </div>

        <h2>방 목록</h2>
        <p style="font-size:14px; color:#4b5563;">
            터미널에서 <code>/room &lt;이름&gt;</code> 으로 만든 방이 이 목록에 나타납니다.
        </p>

        {% for r in rooms %}
        <div class="room-card">
            <div class="room-name"><a href="/room/{{ r }}">{{ r }}</a></div>
            <div class="room-meta">이 방의 지출 내역과 정산 요약을 확인합니다.</div>
        </div>
        {% endfor %}
    </body>
    </html>
    """
    return render_template_string(template, rooms=rooms, udp_ok=udp_ok, udp_stats=udp_stats)


@app.route("/room", methods=["GET"])
def room_redirect():
    room = request.args.get("room")
    view_range = request.args.get("range", "all")
    if not room:
        return index()
    return redirect(url_for("room_detail", room_name=room, range=view_range))


@app.route("/room/<room_name>")
def room_detail(room_name):
    view_range = request.args.get("range", "all")
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("SELECT DISTINCT room FROM expenses ORDER BY room")
    rooms = [row["room"] for row in cur.fetchall()]

    start_str = end_str = None
    if view_range in ("month", "this_month"):
        today = date.today()
        month_start = today.replace(day=1)
        if month_start.month == 12:
            next_month = date(month_start.year + 1, 1, 1)
        else:
            next_month = date(month_start.year, month_start.month + 1, 1)
        start_str = month_start.strftime("%Y-%m-%d 00:00:00")
        end_str = next_month.strftime("%Y-%m-%d 00:00:00")

    if start_str:
        cur.execute(
            """
            SELECT id,user,amount,category,memo,created_at
            FROM expenses
            WHERE room = ? AND created_at >= ? AND created_at < ?
            ORDER BY id
            """,
            (room_name, start_str, end_str),
        )
    else:
        cur.execute(
            """
            SELECT id,user,amount,category,memo,created_at
            FROM expenses
            WHERE room = ?
            ORDER BY id
            """,
            (room_name,),
        )
    exp_rows = cur.fetchall()

    if start_str:
        cur.execute(
            """
            SELECT user, SUM(amount) AS total
            FROM expenses
            WHERE room = ? AND created_at >= ? AND created_at < ?
            GROUP BY user
            """,
            (room_name, start_str, end_str),
        )
    else:
        cur.execute(
            """
            SELECT user, SUM(amount) AS total
            FROM expenses
            WHERE room = ?
            GROUP BY user
            """,
            (room_name,),
        )
    sum_rows = cur.fetchall()

    if start_str:
        cur.execute(
            """
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE room = ? AND created_at >= ? AND created_at < ?
            GROUP BY category
            """,
            (room_name, start_str, end_str),
        )
    else:
        cur.execute(
            """
            SELECT category, SUM(amount) AS total
            FROM expenses
            WHERE room = ?
            GROUP BY category
            """,
            (room_name,),
        )
    cat_rows = cur.fetchall()
    conn.close()

    expenses = exp_rows
    sums = {row["user"]: row["total"] for row in sum_rows}
    total = sum(sums.values()) if sums else 0
    n = len(sums)
    per = total // n if n > 0 else 0

    creditors = []
    debtors = []
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
            transfers.append({"from": duid, "to": cuid, "amount": amount})
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

    user_labels = [row["user"] for row in sum_rows]
    user_values = [row["total"] for row in sum_rows]
    category_labels = [row["category"] for row in cat_rows]
    category_values = [row["total"] for row in cat_rows]

    # ---- UDP 측정(가볍게) ----
    udp_stats = udp_get_stats(timeout=0.15)
    udp_ok = udp_stats is not None
    udp_probe = udp_probe_rtt_loss(count=5, timeout=0.15, interval=0.02) if udp_ok else None

    template = """
    <!doctype html>
    <html lang="ko">
    <head>
        <meta charset="utf-8">
        <title>방 {{ room_name }} - ExpenseChat</title>
        <style>
            body {
                font-family: system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
                padding: 24px;
                max-width: 1080px;
                margin: 0 auto;
                background: #f9fafb;
            }
            a { color: #2563eb; text-decoration: none; }
            a:hover { text-decoration: underline; }

            .topbar {
                display: flex;
                align-items: center;
                justify-content: space-between;
                padding: 12px 20px;
                background: #111827;
                color: white;
                border-radius: 16px;
                margin-bottom: 16px;
                gap: 10px;
            }
            .brand { font-weight: 600; font-size: 18px; display:flex; gap:8px; align-items:center; }
            .logo-dot { width:10px; height:10px; border-radius:999px; background:#10b981; display:inline-block; }
            .room-pill { font-size: 13px; padding: 4px 10px; border-radius: 999px; background: #1f2937; white-space: nowrap; }
            .udp-pill {
                font-size: 12px; padding: 4px 10px; border-radius: 999px;
                background: #1f2937; display:inline-flex; align-items:center; gap:6px; white-space:nowrap;
            }
            .dot { width:8px; height:8px; border-radius:999px; background:#9ca3af; }
            .dot.on { background:#22c55e; }

            .topbar-right { display:flex; align-items:center; gap:10px; }
            .topbar-right a { color:#e5e7eb; font-size:13px; }
            select { font-size:13px; padding:3px 6px; }
            button {
                font-size:13px; padding:4px 10px; border-radius:999px; border:none;
                background:#10b981; color:white; cursor:pointer;
            }
            button:hover { background:#059669; }
            .export-link { font-size:13px; color:#e5e7eb; }

            .summary-row { display:flex; gap:12px; flex-wrap:wrap; margin-bottom:14px; }
            .summary-card {
                flex: 1 1 160px;
                background:white;
                border:1px solid #e5e7eb;
                border-radius:12px;
                padding:10px 14px;
            }
            .summary-label { font-size:12px; color:#6b7280; }
            .summary-value { font-size:18px; font-weight:650; }

            .layout { display:flex; gap:16px; align-items:flex-start; }
            .col-main { flex:3; }
            .col-side { flex:2; }

            table { border-collapse:collapse; width:100%; background:white; border-radius:12px; overflow:hidden; }
            th, td { border:1px solid #e5e7eb; padding:6px 8px; text-align:left; font-size:13px; }
            th { background:#f3f4f6; }

            h2 { margin: 0 0 8px 0; }
            .section { margin-bottom:20px; }
            .hint { font-size:13px; color:#6b7280; }

            .charts-row { display:flex; gap:16px; flex-wrap:wrap; margin-bottom:18px; }
            .chart-card {
                flex: 1 1 260px;
                background:white;
                border:1px solid #e5e7eb;
                border-radius:12px;
                padding:10px 14px;
                height:260px;
            }
            .chart-card canvas { width:100%; height:190px; }
        </style>
        <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    </head>
    <body>
        <div class="topbar">
            <div class="brand">
                <span class="logo-dot"></span> ExpenseChat
            </div>

            <div class="room-pill">방: {{ room_name }}</div>

            <div class="udp-pill">
                <span class="dot {% if udp_ok %}on{% endif %}"></span>
                UDP {% if udp_ok %}ON{% else %}OFF{% endif %}
            </div>

            <div class="topbar-right">
                <a href="/">← 방 목록</a>
                <form method="get" action="/room" style="display:flex; align-items:center; gap:6px; margin:0;">
                    <select name="room">
                        {% for r in rooms %}
                          <option value="{{ r }}" {% if r == room_name %}selected{% endif %}>{{ r }}</option>
                        {% endfor %}
                    </select>
                    <select name="range">
                        <option value="all" {% if view_range == "all" %}selected{% endif %}>전체</option>
                        <option value="month" {% if view_range != "all" %}selected{% endif %}>이번 달</option>
                    </select>
                    <button type="submit">보기</button>
                    <a class="export-link" href="/room/{{ room_name }}/csv?range={{ view_range }}">CSV</a>
                </form>
            </div>
        </div>

        <div class="summary-row">
            <div class="summary-card">
                <div class="summary-label">총액</div>
                <div class="summary-value">{{ total }}원</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">인원 수</div>
                <div class="summary-value">{{ n }}명</div>
            </div>
            <div class="summary-card">
                <div class="summary-label">1인당 금액</div>
                <div class="summary-value">{{ per }}원</div>
            </div>

            <div class="summary-card">
                <div class="summary-label">UDP RTT(평균)</div>
                {% if udp_ok and udp_probe and udp_probe.get("avg") is not none %}
                  <div class="summary-value">{{ "%.2f"|format(udp_probe.get("avg")) }} ms</div>
                  <div class="summary-label">min {{ "%.2f"|format(udp_probe.get("min")) }} / max {{ "%.2f"|format(udp_probe.get("max")) }}</div>
                {% elif udp_ok %}
                  <div class="summary-value">측정 불가</div>
                  <div class="summary-label">손실이 높거나 응답 없음</div>
                {% else %}
                  <div class="summary-value">미실행</div>
                  <div class="summary-label">udp_metrics_server.py 필요</div>
                {% endif %}
            </div>

            <div class="summary-card">
                <div class="summary-label">UDP 손실률</div>
                {% if udp_ok and udp_probe %}
                  <div class="summary-value">{{ "%.1f"|format(udp_probe.get("loss_rate")) }}%</div>
                  <div class="summary-label">sent {{ udp_probe.get("sent") }} / recv {{ udp_probe.get("recv") }}</div>
                {% else %}
                  <div class="summary-value">-</div>
                  <div class="summary-label">UDP OFF</div>
                {% endif %}
            </div>

            <div class="summary-card">
                <div class="summary-label">UDP 서버 메트릭</div>
                {% if udp_ok %}
                  <div class="summary-value">TOTAL {{ udp_stats.get("TOTAL") }} / PONG {{ udp_stats.get("PONG") }}</div>
                  <div class="summary-label">CLIENTS {{ udp_stats.get("CLIENTS") }} / RPS60 {{ udp_stats.get("RPS60") }}</div>
                {% else %}
                  <div class="summary-value">-</div>
                  <div class="summary-label">UDP OFF</div>
                {% endif %}
            </div>
        </div>

        <div class="charts-row">
            <div class="chart-card">
                <div class="summary-label">사용자별 지출 합계</div>
                <canvas id="userChart"></canvas>
            </div>
            <div class="chart-card">
                <div class="summary-label">카테고리별 지출 비율</div>
                <canvas id="categoryChart"></canvas>
            </div>
        </div>

        <div class="layout">
            <div class="col-main">
                <div class="section">
                    <h2>지출 내역</h2>
                    {% if expenses %}
                    <table>
                        <tr>
                            <th>ID</th><th>사용자</th><th>금액</th><th>카테고리</th><th>메모</th><th>시간</th>
                        </tr>
                        {% for e in expenses %}
                        <tr>
                            <td>{{ e["id"] }}</td>
                            <td>{{ e["user"] }}</td>
                            <td>{{ e["amount"] }}</td>
                            <td>{{ e["category"] }}</td>
                            <td>{{ e["memo"] }}</td>
                            <td>{{ e["created_at"] }}</td>
                        </tr>
                        {% endfor %}
                    </table>
                    {% else %}
                    <p class="hint">이 기간에는 지출이 없습니다.</p>
                    {% endif %}
                </div>
            </div>

            <div class="col-side">
                <div class="section">
                    <h2>정산 요약</h2>
                    {% if sums %}
                    <ul>
                    {% for uid, paid in sums.items() %}
                        {% set diff = paid - per %}
                        {% if diff > 0 %}
                          <li>{{ uid }}: {{ paid }}원 (+{{ diff }}원 더 냈음)</li>
                        {% elif diff < 0 %}
                          <li>{{ uid }}: {{ paid }}원 ({{ -diff }}원 덜 냈음)</li>
                        {% else %}
                          <li>{{ uid }}: {{ paid }}원 (딱 맞게 냈음)</li>
                        {% endif %}
                    {% endfor %}
                    </ul>
                    {% else %}
                    <p class="hint">정산할 데이터가 없습니다.</p>
                    {% endif %}
                </div>

                <div class="section">
                    <h2>정산 추천</h2>
                    {% if transfers %}
                    <ul>
                    {% for t in transfers %}
                      <li>{{ t["from"] }} → {{ t["to"] }} : {{ t["amount"] }}원 송금</li>
                    {% endfor %}
                    </ul>
                    {% else %}
                    <p class="hint">정산 추천이 필요 없습니다.</p>
                    {% endif %}
                </div>
            </div>
        </div>

        <script>
        document.addEventListener("DOMContentLoaded", function() {
            const userLabels = [{% for u in user_labels %}"{{ u }}"{% if not loop.last %},{% endif %}{% endfor %}];
            const userValues = [{% for v in user_values %}{{ v }}{% if not loop.last %},{% endif %}{% endfor %}];
            const catLabels = [{% for c in category_labels %}"{{ c }}"{% if not loop.last %},{% endif %}{% endfor %}];
            const catValues = [{% for v in category_values %}{{ v }}{% if not loop.last %},{% endif %}{% endfor %}];

            const userCtx = document.getElementById('userChart');
            if (userCtx && userLabels.length > 0) {
                new Chart(userCtx, {
                    type: 'bar',
                    data: { labels: userLabels, datasets: [{ label: '사용자별 지출', data: userValues }] },
                    options: { responsive: true, maintainAspectRatio: false, scales: { y: { beginAtZero: true } } }
                });
            }

            const catCtx = document.getElementById('categoryChart');
            if (catCtx && catLabels.length > 0) {
                new Chart(catCtx, {
                    type: 'pie',
                    data: { labels: catLabels, datasets: [{ label: '카테고리별 지출', data: catValues }] },
                    options: { responsive: true, maintainAspectRatio: false }
                });
            }
        });
        </script>
    </body>
    </html>
    """

    return render_template_string(
        template,
        room_name=room_name,
        expenses=expenses,
        sums=sums,
        total=total,
        n=n,
        per=per,
        transfers=transfers,
        rooms=rooms,
        view_range=view_range,
        user_labels=user_labels,
        user_values=user_values,
        category_labels=category_labels,
        category_values=category_values,
        udp_ok=udp_ok,
        udp_stats=udp_stats,
        udp_probe=udp_probe,
    )


@app.route("/room/<room_name>/csv")
def room_export_csv(room_name):
    view_range = request.args.get("range", "all")
    conn = get_conn()
    cur = conn.cursor()

    start_str = end_str = None
    if view_range in ("month", "this_month"):
        today = date.today()
        month_start = today.replace(day=1)
        if month_start.month == 12:
            next_month = date(month_start.year + 1, 1, 1)
        else:
            next_month = date(month_start.year, month_start.month + 1, 1)
        start_str = month_start.strftime("%Y-%m-%d 00:00:00")
        end_str = next_month.strftime("%Y-%m-%d 00:00:00")

    if start_str:
        cur.execute(
            """
            SELECT id, room, user, amount, category, memo, created_at
            FROM expenses
            WHERE room = ? AND created_at >= ? AND created_at < ?
            ORDER BY id
            """,
            (room_name, start_str, end_str),
        )
    else:
        cur.execute(
            """
            SELECT id, room, user, amount, category, memo, created_at
            FROM expenses
            WHERE room = ?
            ORDER BY id
            """,
            (room_name,),
        )

    rows = cur.fetchall()
    conn.close()

    output = StringIO()
    writer = csv.writer(output)
    writer.writerow(["id", "room", "user", "amount", "category", "memo", "created_at"])
    for row in rows:
        writer.writerow([
            row["id"], row["room"], row["user"], row["amount"],
            row["category"], row["memo"], row["created_at"]
        ])

    csv_data = output.getvalue()
    filename = f"{room_name}_{view_range}.csv"
    return Response(
        csv_data,
        mimetype="text/csv",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
