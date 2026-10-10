import os
import json
import time
import ssl
import socket
import subprocess
import platform
import requests
import yaml
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

STATE_FILE = "state.json"
HISTORY_FILE = "history.json"
MUTES_FILE = "mutes.json"
SSL_DAYS_WARNING = 30
HISTORY_LIMIT = 100


def ping(host):
    param = "-n" if platform.system().lower() == "windows" else "-c"
    try:
        start = time.time()
        result = subprocess.run(
            ["ping", param, "1", "-w", "2000", host],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
        )
        elapsed_ms = round((time.time() - start) * 1000)
        return result.returncode == 0, elapsed_ms
    except (subprocess.TimeoutExpired, Exception):
        return False, None


def check_port(host, port, timeout=3):
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except (socket.timeout, ConnectionRefusedError, OSError):
        return False


def check_ssl(host, port=443):
    try:
        ctx = ssl.create_default_context()
        with socket.create_connection((host, port), timeout=5) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                cert = ssock.getpeercert()
                expire_str = cert["notAfter"]
                expire_date = datetime.strptime(expire_str, "%b %d %H:%M:%S %Y %Z")
                now_utc = datetime.now(expire_date.tzinfo)
                days_left = (expire_date - now_utc).days
                return days_left
    except Exception:
        return None


def load_hosts():
    with open("hosts.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["hosts"]

 
def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_mutes():
    if os.path.exists(MUTES_FILE):
        with open(MUTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=2, ensure_ascii=False)


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_history(history):
    for name in history:
        history[name] = history[name][-HISTORY_LIMIT:]
    with open(HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def check_host(host):
    address = host["address"]

    ok, rtt = ping(address)
    if not ok:
        return "DOWN", None, None

    for port in host.get("ports", []):
        if not check_port(address, port):
            return "DOWN", None, None

    ssl_days = None
    if host.get("check_ssl"):
        ssl_days = check_ssl(address)

    return "UP", rtt, ssl_days


def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        return True
    except requests.exceptions.RequestException as e:
        print(f"Ошибка отправки в Telegram: {e}")
        return False


def main():
    hosts = load_hosts()
    old_state = load_state()
    mutes = load_mutes()
    now_ts = time.time()
    new_state = {}
    history = load_history()
    alerts = []

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    for host in hosts:
        name = host["name"]
        address = host["address"]
        current, rtt, ssl_days = check_host(host)

        new_state[name] = {
            "status": current,
            "rtt": rtt,
            "ssl_days": ssl_days,
            "checked_at": now,
        }

        if current == "UP" and rtt is not None:
            history.setdefault(name, []).append({
                "time": now,
                "rtt": rtt,
            })

        previous_entry = old_state.get(name)
        if isinstance(previous_entry, dict):
            previous = previous_entry.get("status")
        else:
            previous = previous_entry

        if previous is None:
            continue

        muted_until = mutes.get(name, 0)
        is_muted = muted_until > now_ts

        if not is_muted:
            if previous == "UP" and current == "DOWN":
                alerts.append(f"🔴 {name} ({address}) — УПАЛ")

            if previous == "DOWN" and current == "UP":
                alerts.append(f"🟢 {name} ({address}) — ВОССТАНОВЛЕН")

            if ssl_days is not None and ssl_days < SSL_DAYS_WARNING:
                alerts.append(
                    f"🔒 {name} ({address}) — SSL истекает через {ssl_days} дн."
                )

    save_state(new_state)
    save_history(history)

    if alerts:
        message = (
            f"<b>Сетевой алерт</b>\n"
            f"Время: {now}\n\n"
            + "\n".join(alerts)
        )
        send_telegram(message)
        print(f"[{now}] Отправлен алерт: {len(alerts)} изменений")
    else:
        print(f"[{now}] Без изменений.")


if __name__ == "__main__":
    main()