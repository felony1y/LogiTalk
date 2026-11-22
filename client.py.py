"""LogiTalk — клієнт.

Потрібно:  pip install customtkinter
Запуск:    python client.py
Адреса сервера вводиться як  IP  або  IP:порт  (наприклад 192.168.0.5:5555)
"""
import json
import os
import queue
import socket
import threading
import traceback
import zlib

import customtkinter as ctk

DEFAULT_PORT = 5555
CONFIG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logitalk_config.json")

# ---------- Палітра ----------
BG = "#1A1C2C"
PANEL = "#232638"
FIELD = "#2B2F47"
BUBBLE_OTHER = "#2D3150"
BUBBLE_OWN = "#4A55C4"
TEXT = "#E9EAF5"
MUTED = "#8D91B0"
ACCENT = "#7C8CFF"
ACCENT_HOVER = "#97A4FF"
DANGER = "#F08A9B"
ONLINE = "#6FD3A8"
NAME_COLORS = ["#8FB4FF", "#F2A77C", "#7FD6C2", "#E59BD2", "#D9C46B", "#A99BFF"]
FONT = "Segoe UI"

ctk.set_appearance_mode("dark")

w = ctk.CTk(fg_color=BG)
w.title("LogiTalk")
w.geometry("760x640")
w.minsize(560, 480)

f_title = ctk.CTkFont(family=FONT, size=34, weight="bold")
f_head = ctk.CTkFont(family=FONT, size=20, weight="bold")
f_body = ctk.CTkFont(family=FONT, size=15)
f_small = ctk.CTkFont(family=FONT, size=12)
f_name = ctk.CTkFont(family=FONT, size=13, weight="bold")
f_italic = ctk.CTkFont(family=FONT, size=15, slant="italic")

# ---------- Стан ----------
sock = None
my_name = ""
session = 0              # номер поточного підключення (старі події ігноруються)
in_chat = False
send_lock = threading.Lock()
events = queue.Queue()   # мережевий потік -> інтерфейс (tkinter не любить інші потоки)
bubbles = {}


def encode(data):
    return (json.dumps(data, ensure_ascii=False) + "\n").encode("utf-8")


# ---------- Мережа ----------
def parse_addr(text):
    text = text.strip()
    if ":" in text:
        host, _, port = text.rpartition(":")
        host, port = host.strip(), int(port)
    else:
        host, port = text, DEFAULT_PORT
    if not host or not 1 <= port <= 65535:
        raise ValueError
    return host, port


def explain(err):
    if isinstance(err, socket.timeout):
        return ("Сервер не відповідає. Перевірте IP, порт, фаєрвол "
                "і чи відкрито порт на роутері.")
    if isinstance(err, ConnectionRefusedError):
        return "Сервер відмовив у з'єднанні. Перевірте, чи він запущений і чи правильний порт."
    if isinstance(err, socket.gaierror):
        return "Не вдалося знайти такий сервер. Перевірте адресу."
    return f"Помилка підключення: {err}"


def net_worker(sid, host, port, name):
    global sock
    try:
        s = socket.create_connection((host, port), timeout=8)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
        s.sendall(encode({"type": "hello", "name": name}))
        s.settimeout(None)
    except OSError as e:
        events.put((sid, "error", explain(e)))
        return

    if sid != session:          # користувач уже натиснув щось інше
        s.close()
        return
    sock = s

    buf = b""
    try:
        while True:
            data = s.recv(4096)
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                if line.strip():
                    try:
                        events.put((sid, "packet", json.loads(line.decode("utf-8"))))
                    except ValueError:
                        pass
    except OSError:
        pass
    finally:
        try:
            s.close()
        except OSError:
            pass
        events.put((sid, "closed", None))


def send_packet(pk):
    if not sock:
        return False
    try:
        with send_lock:
            sock.sendall(encode(pk))
        return True
    except OSError:
        return False


# ---------- Інтерфейс: вхід ----------
login_frame = ctk.CTkFrame(w, fg_color="transparent")
login_frame.pack(fill="both", expand=True)

card = ctk.CTkFrame(login_frame, fg_color=PANEL, corner_radius=22)
card.place(relx=0.5, rely=0.5, anchor="center")

ctk.CTkLabel(card, text="LogiTalk", font=f_title, text_color=TEXT).pack(padx=50, pady=(36, 2))
ctk.CTkLabel(card, text="Чат для своїх", font=f_body, text_color=MUTED).pack(pady=(0, 22))

name_entry = ctk.CTkEntry(card, placeholder_text="Ваше ім'я", width=300, height=44,
                          corner_radius=12, border_width=0, fg_color=FIELD,
                          font=f_body, text_color=TEXT)
name_entry.pack(pady=6)

addr_entry = ctk.CTkEntry(card, placeholder_text="Адреса сервера, напр. 192.168.0.5:5555",
                          width=300, height=44, corner_radius=12, border_width=0,
                          fg_color=FIELD, font=f_body, text_color=TEXT)
addr_entry.pack(pady=6)

connect_btn = ctk.CTkButton(card, text="Підключитися", width=300, height=46,
                            corner_radius=12, font=f_name, fg_color=ACCENT,
                            hover_color=ACCENT_HOVER, text_color="#12142A")
connect_btn.pack(pady=(16, 6))

status = ctk.CTkLabel(card, text="", font=f_small, text_color=MUTED,
                      wraplength=300, justify="center")
status.pack(padx=20, pady=(6, 28))


def set_status(text, color=MUTED):
    status.configure(text=text, text_color=color)


# ---------- Інтерфейс: чат ----------
chat_frame = ctk.CTkFrame(w, fg_color="transparent")

header = ctk.CTkFrame(chat_frame, fg_color=PANEL, corner_radius=16, height=56)
header.pack(fill="x", padx=12, pady=(12, 6))
header.pack_propagate(False)
ctk.CTkLabel(header, text="LogiTalk", font=f_head, text_color=TEXT).pack(side="left", padx=18)
online_label = ctk.CTkLabel(header, text="", font=f_small, text_color=ONLINE)
online_label.pack(side="right", padx=18)

chat = ctk.CTkScrollableFrame(chat_frame, fg_color="transparent", corner_radius=0)
chat.pack(fill="both", expand=True, padx=6, pady=0)

bottom = ctk.CTkFrame(chat_frame, fg_color=PANEL, corner_radius=16)
bottom.pack(fill="x", padx=12, pady=(6, 4))

msg_entry = ctk.CTkEntry(bottom, placeholder_text="Напишіть повідомлення…", height=44,
                         corner_radius=12, border_width=0, fg_color=FIELD,
                         font=f_body, text_color=TEXT)
msg_entry.pack(side="left", fill="x", expand=True, padx=(10, 8), pady=10)

send_btn = ctk.CTkButton(bottom, text="Надіслати", width=110, height=44, corner_radius=12,
                         font=f_name, fg_color=ACCENT, hover_color=ACCENT_HOVER,
                         text_color="#12142A")
send_btn.pack(side="right", padx=(0, 10), pady=10)

ctk.CTkLabel(chat_frame, text="Щоб видалити своє повідомлення — натисніть на нього правою кнопкою миші",
             font=f_small, text_color=MUTED).pack(pady=(0, 8))


def scroll_bottom():
    def go():
        try:
            chat._parent_canvas.yview_moveto(1.0)
        except Exception:
            pass
    w.after(80, go)


def name_color(name):
    return NAME_COLORS[zlib.crc32(name.encode("utf-8")) % len(NAME_COLORS)]


def add_message(mid, name, text, tm, own):
    row = ctk.CTkFrame(chat, fg_color="transparent")
    row.pack(fill="x", padx=6, pady=3)

    bubble = ctk.CTkFrame(row, corner_radius=18,
                          fg_color=BUBBLE_OWN if own else BUBBLE_OTHER)
    if own:
        bubble.pack(side="right", padx=(70, 4))
    else:
        bubble.pack(side="left", padx=(4, 70))

    if not own:
        ctk.CTkLabel(bubble, text=name, font=f_name, text_color=name_color(name),
                     anchor="w").pack(fill="x", padx=16, pady=(10, 0))

    text_label = ctk.CTkLabel(bubble, text=text, font=f_body, text_color=TEXT,
                              wraplength=430, justify="left", anchor="w")
    text_label.pack(fill="x", padx=16, pady=(8 if own else 2, 0))

    time_label = ctk.CTkLabel(bubble, text=tm, font=f_small,
                              text_color="#C3C8FF" if own else MUTED, anchor="e")
    time_label.pack(fill="x", padx=16, pady=(0, 8))

    bubbles[mid] = {"bubble": bubble, "text": text_label, "own": own}

    if own:
        for widget in (bubble, text_label, time_label):
            widget.bind("<Button-3>", lambda e, m=mid: delete_message(m))
            widget.bind("<Button-2>", lambda e, m=mid: delete_message(m))   # macOS


def add_system(text):
    ctk.CTkLabel(chat, text=text, font=f_small, text_color=MUTED).pack(pady=6)


def mark_deleted(mid):
    item = bubbles.get(mid)
    if not item:
        return
    item["own"] = False
    item["bubble"].configure(fg_color=PANEL)
    item["text"].configure(text="Повідомлення видалено", font=f_italic, text_color=MUTED)


# ---------- Дії ----------
def connect(event=None):
    global session, sock
    name = name_entry.get().strip()[:20]
    addr = addr_entry.get().strip()
    if not name or not addr:
        set_status("Введіть ім'я та адресу сервера.", DANGER)
        return
    try:
        host, port = parse_addr(addr)
    except ValueError:
        set_status("Невірна адреса. Приклад: 192.168.0.5:5555", DANGER)
        return

    if sock:
        try:
            sock.close()
        except OSError:
            pass
        sock = None

    session += 1
    connect_btn.configure(state="disabled", text="Підключаюся…")
    set_status("")
    threading.Thread(target=net_worker, args=(session, host, port, name), daemon=True).start()


def send_message(event=None):
    text = msg_entry.get().strip()
    if not text:
        return "break"
    if send_packet({"type": "message", "text": text}):
        msg_entry.delete(0, "end")
    else:
        show_login("З'єднання втрачено. Підключіться знову.")
    return "break"


def delete_message(mid):
    item = bubbles.get(mid)
    if item and item["own"]:
        send_packet({"type": "delete", "id": mid})


def show_chat():
    global in_chat
    in_chat = True
    login_frame.pack_forget()
    chat_frame.pack(fill="both", expand=True)
    msg_entry.focus()


def show_login(message="", color=DANGER):
    global in_chat, sock
    in_chat = False
    if sock:
        try:
            sock.close()
        except OSError:
            pass
        sock = None
    for child in chat.winfo_children():
        child.destroy()
    bubbles.clear()
    online_label.configure(text="")
    chat_frame.pack_forget()
    login_frame.pack(fill="both", expand=True)
    connect_btn.configure(state="normal", text="Підключитися")
    set_status(message, color)


def save_config():
    try:
        with open(CONFIG, "w", encoding="utf-8") as f:
            json.dump({"name": name_entry.get().strip(), "addr": addr_entry.get().strip()}, f)
    except OSError:
        pass


def load_config():
    try:
        with open(CONFIG, encoding="utf-8") as f:
            cfg = json.load(f)
        name_entry.insert(0, cfg.get("name", ""))
        addr_entry.insert(0, cfg.get("addr", ""))
    except (OSError, ValueError):
        pass


def handle_packet(pk):
    global my_name
    kind = pk.get("type")

    if kind == "welcome":
        my_name = pk.get("name", "")
        show_chat()
        for m in pk.get("history", []):
            add_message(m["id"], m["name"], m["text"], m.get("time", ""), m["name"] == my_name)
        add_system("Ви в чаті")
        save_config()
        scroll_bottom()

    elif kind == "message":
        add_message(pk["id"], pk["name"], pk["text"], pk.get("time", ""), pk["name"] == my_name)
        scroll_bottom()

    elif kind == "delete":
        mark_deleted(pk.get("id"))

    elif kind == "system":
        add_system(pk.get("text", ""))
        scroll_bottom()

    elif kind == "users":
        online_label.configure(text=f"● {len(pk.get('users', []))} онлайн")


def poll():
    try:
        while True:
            sid, kind, data = events.get_nowait()
            if sid != session:
                continue
            try:
                if kind == "error":
                    show_login(data)
                elif kind == "closed":
                    show_login("З'єднання з сервером втрачено." if in_chat
                               else "Сервер закрив з'єднання.")
                elif kind == "packet":
                    handle_packet(data)
            except Exception:
                traceback.print_exc()
    except queue.Empty:
        pass
    w.after(80, poll)


def toggle_fullscreen(event=None):
    w.attributes("-fullscreen", not w.attributes("-fullscreen"))


def exit_fullscreen(event=None):
    w.attributes("-fullscreen", False)


def close_app():
    global session
    session += 1
    if sock:
        try:
            sock.close()
        except OSError:
            pass
    w.destroy()


connect_btn.configure(command=connect)
send_btn.configure(command=send_message)
name_entry.bind("<Return>", lambda e: addr_entry.focus())
addr_entry.bind("<Return>", connect)
msg_entry.bind("<Return>", send_message)
w.bind("<F11>", toggle_fullscreen)
w.bind("<Escape>", exit_fullscreen)
w.protocol("WM_DELETE_WINDOW", close_app)

load_config()
poll()
w.mainloop()
