import os
import json
import time
import socket
import ssl
import subprocess
import platform
import requests
import yaml
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
API_URL = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}"

STATE_FILE = "state.json"
HISTORY_FILE = "history.json"
MUTES_FILE = "mutes.json"


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_history():
    if os.path.exists(HISTORY_FILE):
        with open(HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def load_mutes():
    if os.path.exists(MUTES_FILE):
        with open(MUTES_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_mutes(mutes):
    with open(MUTES_FILE, "w", encoding="utf-8") as f:
        json.dump(mutes, f, indent=2, ensure_ascii=False)


def load_hosts():
    with open("hosts.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["hosts"]


def find_host(name):
    hosts = load_hosts()
    for host in hosts:
        if host["name"].lower() == name.lower():
            return host
    return None


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
                return (expire_date - now_utc).days
    except Exception:
        return None


def get_updates(offset=None):
    url = f"{API_URL}/getUpdates"
    params = {"timeout": 30}
    if offset is not None:
        params["offset"] = offset
    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        return response.json().get("result", [])
    except requests.exceptions.RequestException:
        return []


def send_message(chat_id, text):
    url = f"{API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"Ошибка sendMessage: {e}")


def send_message_with_buttons(chat_id, text, buttons):
    url = f"{API_URL}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "HTML",
        "reply_markup": {
            "inline_keyboard": buttons,
        },
    }
    try:
        requests.post(url, json=payload, timeout=10)
    except requests.exceptions.RequestException as e:
        print(f"Ошибка sendMessage: {e}")


def answer_callback(callback_id, text=None):
    url = f"{API_URL}/answerCallbackQuery"
    payload = {"callback_query_id": callback_id}
    if text:
        payload["text"] = text
    try:
        requests.post(url, json=payload, timeout=10)
    except requests.exceptions.RequestException:
        pass


def cmd_status():
    state = load_state()
    if not state:
        return "Состояние ещё не собрано. Запусти monitor.py."

    up = sum(1 for v in state.values() if isinstance(v, dict) and v.get("status") == "UP")
    down = sum(1 for v in state.values() if isinstance(v, dict) and v.get("status") == "DOWN")
    total = len(state)

    return (
        f"<b>Статус мониторинга</b>\n\n"
        f"🟢 Доступно: <b>{up}</b>\n"
        f"🔴 Недоступно: <b>{down}</b>\n"
        f"📊 Всего хостов: <b>{total}</b>"
    )


def cmd_hosts():
    state = load_state()
    hosts = load_hosts()
    if not state:
        return "Состояние ещё не собрано. Запусти monitor.py."

    lines = ["<b>Список хостов</b>\n"]
    for host in hosts:
        name = host["name"]
        entry = state.get(name)
        if isinstance(entry, dict):
            status = entry.get("status", "UNKNOWN")
            rtt = entry.get("rtt")
            rtt_str = f" ({rtt} мс)" if rtt else ""
        else:
            status = "UNKNOWN"
            rtt_str = ""

        icon = "🟢" if status == "UP" else "🔴" if status == "DOWN" else "🟡"
        lines.append(f"{icon} <b>{name}</b> — {host['address']}{rtt_str}")

    return "\n".join(lines)


def cmd_host(name):
    state = load_state()
    entry = state.get(name)

    if not entry:
        return f"Хост <b>{name}</b> не найден."

    if isinstance(entry, dict):
        status = entry.get("status", "UNKNOWN")
        rtt = entry.get("rtt")
        ssl_days = entry.get("ssl_days")
        checked_at = entry.get("checked_at", "—")
    else:
        status = entry
        rtt = None
        ssl_days = None
        checked_at = "—"

    icon = "🟢" if status == "UP" else "🔴" if status == "DOWN" else "🟡"

    msg = f"<b>{name}</b>\n\n"
    msg += f"{icon} Статус: <b>{status}</b>\n"
    if rtt:
        msg += f"⚡ RTT: <b>{rtt} мс</b>\n"
    if ssl_days is not None:
        msg += f"🔒 SSL: <b>{ssl_days} дн.</b>\n"
    msg += f"🕐 Проверено: {checked_at}"

    return msg


def cmd_check(name):
    host = find_host(name)
    if not host:
        return f"Хост <b>{name}</b> не найден в hosts.yaml."

    address = host["address"]
    result = f"<b>Проверка {host['name']}</b>\n\n"

    ok, rtt = ping(address)
    if ok:
        result += f"🟢 Ping: <b>OK</b> ({rtt} мс)\n"
    else:
        result += f"🔴 Ping: <b>FAIL</b>\n"
        return result

    for port in host.get("ports", []):
        if check_port(address, port):
            result += f"🟢 Порт {port}: <b>открыт</b>\n"
        else:
            result += f"🔴 Порт {port}: <b>закрыт</b>\n"

    if host.get("check_ssl"):
        days = check_ssl(address)
        if days is None:
            result += f"⚠️ SSL: <b>не удалось проверить</b>\n"
        else:
            icon = "🟢" if days > 30 else "🔴"
            result += f"{icon} SSL: <b>{days} дн.</b>\n"

    result += f"\n🕐 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
    return result


def cmd_uptime(name):
    history = load_history()
    host_key = None
    for key in history.keys():
        if key.lower() == name.lower():
            host_key = key
            break

    if not host_key:
        return f"Нет истории для <b>{name}</b>. Подожди несколько запусков monitor.py."

    entries = history[host_key]
    if not entries:
        return f"История для <b>{name}</b> пуста."

    total = len(entries)
    ok = sum(1 for e in entries if e.get("rtt") is not None)
    percent = round(ok / total * 100, 2)

    rtts = [e["rtt"] for e in entries if e.get("rtt")]
    avg_rtt = round(sum(rtts) / len(rtts)) if rtts else 0

    return (
        f"<b>Uptime {host_key}</b>\n\n"
        f"📊 Uptime: <b>{percent}%</b>\n"
        f"✅ Проверок: <b>{total}</b>\n"
        f"🟢 Успешных: <b>{ok}</b>\n"
        f"⚡ Средний RTT: <b>{avg_rtt} мс</b>"
    )


def cmd_mute(name, minutes):
    host = find_host(name)
    if not host:
        return f"Хост <b>{name}</b> не найден."

    try:
        minutes = int(minutes)
    except ValueError:
        return "Неверный формат. Используй: <code>/mute Yandex 60</code>"

    mutes = load_mutes()
    until = time.time() + minutes * 60
    mutes[host["name"]] = until
    save_mutes(mutes)

    until_str = datetime.fromtimestamp(until).strftime("%Y-%m-%d %H:%M:%S")
    return (
        f"🔇 <b>{host['name']}</b> заглушен на {minutes} мин.\n"
        f"Алерты не будут приходить до <b>{until_str}</b>."
    )


def cmd_unmute(name):
    host = find_host(name)
    if not host:
        return f"Хост <b>{name}</b> не найден."

    mutes = load_mutes()
    if host["name"] in mutes:
        del mutes[host["name"]]
        save_mutes(mutes)
        return f"🔔 <b>{host['name']}</b> разглушен."

    return f"Хост <b>{host['name']}</b> не был заглушен."


def handle_command(text, chat_id):
    text = text.strip()
    parts = text.split()

    if not parts:
        return

    cmd = parts[0].lower()

    if cmd == "/status":
        send_message(chat_id, cmd_status())

    elif cmd == "/hosts":
        send_message(chat_id, cmd_hosts())

    elif cmd == "/host" and len(parts) >= 2:
        send_message(chat_id, cmd_host(parts[1]))

    elif cmd == "/check" and len(parts) >= 2:
        send_message(chat_id, cmd_check(parts[1]))

    elif cmd == "/uptime" and len(parts) >= 2:
        send_message(chat_id, cmd_uptime(parts[1]))

    elif cmd == "/mute" and len(parts) >= 3:
        send_message(chat_id, cmd_mute(parts[1], parts[2]))

    elif cmd == "/unmute" and len(parts) >= 2:
        send_message(chat_id, cmd_unmute(parts[1]))

    elif cmd == "/start":
        welcome = (
            "🌐 <b>Network Monitor Bot</b>\n\n"
            "Мониторинг сетевой доступности в реальном времени.\n\n"
            "📊 <b>СТАТУС</b>\n"
            "/status — общая сводка\n"
            "/hosts — список всех хостов\n"
            "/host Имя — детали по хосту\n\n"
            "🔍 <b>ПРОВЕРКА</b>\n"
            "/check Имя — проверить хост сейчас\n"
            "/uptime Имя — процент доступности\n\n"
            "🔇 <b>УПРАВЛЕНИЕ</b>\n"
            "/mute Имя мин. — отключить алерты\n"
            "/unmute Имя — включить алерты\n\n"
            "💡 <b>Примеры:</b>\n"
            "<code>/check Yandex</code>\n"
            "<code>/mute GitHub 60</code>"
        )
        buttons = [
            [
                {"text": "📊 Статус", "callback_data": "status"},
                {"text": "📋 Хосты", "callback_data": "hosts"},
            ],
            [
                {"text": "❓ Помощь", "callback_data": "help"},
            ],
        ]
        send_message_with_buttons(chat_id, welcome, buttons)


def main():
    print("Бот запущен. Ожидание команд...")
    offset = None

    while True:
        updates = get_updates(offset)

        for update in updates:
            offset = update["update_id"] + 1

            if "callback_query" in update:
                callback = update["callback_query"]
                callback_id = callback["id"]
                data = callback.get("data", "")
                chat_id = callback["message"]["chat"]["id"]

                if data == "status":
                    send_message(chat_id, cmd_status())
                elif data == "hosts":
                    send_message(chat_id, cmd_hosts())
                elif data == "help":
                    send_message(
                        chat_id,
                        "Напиши /start, чтобы снова увидеть меню.",
                    )

                answer_callback(callback_id)
                continue

            message = update.get("message")
            if not message:
                continue

            text = message.get("text", "")
            chat_id = message["chat"]["id"]

            if text:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] {text}")
                handle_command(text, chat_id)

        time.sleep(1)


if __name__ == "__main__":
    main()