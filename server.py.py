"""LogiTalk — сервер.

Запуск:   python server.py          (порт 5555)
          python server.py 7000     (свій порт)
"""
import json
import socket
import sys
import threading
import time
import uuid
from collections import OrderedDict

HOST = "0.0.0.0"          # слухаємо на всіх мережевих інтерфейсах
PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 5555
MAX_HISTORY = 100          # скільки останніх повідомлень показувати новачкам
MAX_TEXT = 2000

lock = threading.RLock()
clients = {}               # сокет -> {"name", "uid", "send_lock"}
history = OrderedDict()    # id повідомлення -> {"id", "name", "text", "time", "owner"}


def encode(data):
    return (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")


def send(conn, data):
    with lock:
        info = clients.get(conn)
    if not info:
        return False
    try:
        with info["send_lock"]:
            conn.sendall(encode(data))
        return True
    except OSError:
        return False


def broadcast(data):
    with lock:
        targets = list(clients.keys())
    for conn in targets:
        if not send(conn, data):
            remove_client(conn)


def users_packet():
    with lock:
        return {"type": "users", "users": [c["name"] for c in clients.values()]}


def remove_client(conn):
    with lock:
        info = clients.pop(conn, None)
    try:
        conn.close()
    except OSError:
        pass
    if info:
        print(f"[-] {info['name']} вийшов")
        broadcast({"type": "system", "text": f"{info['name']} вийшов з чату"})
        broadcast(users_packet())


def read_lines(conn):
    """Віддає повні рядки. Буфер — байти, тому кирилиця не ламається."""
    buf = b""
    while True:
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                yield line
        data = conn.recv(4096)
        if not data or len(buf) > 65536:
            return
        buf += data


def public(msg):
    return {k: v for k, v in msg.items() if k != "owner"}


def handle_client(conn, addr):
    try:
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        conn.settimeout(10)                      # на привітання — 10 секунд
        lines = read_lines(conn)
        first = next(lines, None)
        if first is None:
            return
        hello = json.loads(first.decode("utf-8"))
        if hello.get("type") != "hello":
            return
        name = str(hello.get("name", "")).strip()[:20]
        if not name:
            return
        conn.settimeout(None)

        with lock:
            taken = {c["name"] for c in clients.values()}
            unique, n = name, 2
            while unique in taken:
                unique, n = f"{name} ({n})", n + 1
            name = unique
            uid = str(uuid.uuid4())
            clients[conn] = {"name": name, "uid": uid, "send_lock": threading.Lock()}
            past = [public(m) for m in history.values()]

        print(f"[+] {name} підключився з {addr[0]}")
        send(conn, {"type": "welcome", "name": name, "history": past})
        broadcast({"type": "system", "text": f"{name} приєднався до чату"})
        broadcast(users_packet())

        for line in lines:
            try:
                pk = json.loads(line.decode("utf-8"))
            except ValueError:
                continue
            kind = pk.get("type")

            if kind == "message":
                text = str(pk.get("text", "")).strip()
                if not text or len(text) > MAX_TEXT:
                    continue
                msg = {
                    "type": "message",
                    "id": str(uuid.uuid4()),
                    "name": name,
                    "text": text,
                    "time": time.strftime("%H:%M"),
                    "owner": uid,
                }
                with lock:
                    history[msg["id"]] = msg
                    while len(history) > MAX_HISTORY:
                        history.popitem(last=False)
                broadcast(public(msg))

            elif kind == "delete":
                mid = pk.get("id")
                with lock:
                    msg = history.get(mid)
                    allowed = bool(msg) and msg["owner"] == uid
                    if allowed:
                        del history[mid]
                if allowed:
                    broadcast({"type": "delete", "id": mid})

    except (OSError, ValueError):
        pass
    finally:
        remove_client(conn)


def main():
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        srv.bind((HOST, PORT))
    except OSError as e:
        print(f"Не вдалося зайняти порт {PORT}: {e}")
        print("Можливо, сервер уже запущений або порт зайнятий іншою програмою.")
        return
    srv.listen()

    print("=" * 40)
    print("  LOGITALK SERVER")
    print("=" * 40)
    print(f"Сервер запущено на порту {PORT}")
    try:
        print("Адреса у локальній мережі:", socket.gethostbyname(socket.gethostname()))
    except OSError:
        pass
    print("Очікую користувачів... (Ctrl+C — зупинити)\n")

    try:
        while True:
            conn, addr = srv.accept()
            threading.Thread(target=handle_client, args=(conn, addr), daemon=True).start()
    except KeyboardInterrupt:
        print("\nСервер зупиняється...")
    finally:
        srv.close()


if __name__ == "__main__":
    main()
