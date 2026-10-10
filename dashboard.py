import json
import os
from datetime import datetime
from flask import Flask, render_template
import yaml

app = Flask(__name__)

STATE_FILE = "state.json"
HISTORY_FILE = "history.json"


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


def load_hosts():
    with open("hosts.yaml", "r", encoding="utf-8") as f:
        return yaml.safe_load(f)["hosts"]


@app.route("/")
def index():
    hosts = load_hosts()
    state = load_state()
    history = load_history()

    rows = []
    up_count = 0
    down_count = 0

    for host in hosts:
        name = host["name"]
        entry = state.get(name)

        if isinstance(entry, dict):
            status = entry.get("status", "UNKNOWN")
            rtt = entry.get("rtt")
            ssl_days = entry.get("ssl_days")
            checked_at = entry.get("checked_at", "—")
        else:
            status = entry if entry else "UNKNOWN"
            rtt = None
            ssl_days = None
            checked_at = "—"

        if status == "UP":
            up_count += 1
        elif status == "DOWN":
            down_count += 1

        rows.append({
            "name": name,
            "address": host["address"],
            "ports": ", ".join(str(p) for p in host.get("ports", [])),
            "status": status,
            "rtt": rtt,
            "ssl_days": ssl_days,
            "checked_at": checked_at,
        })

    chart_data = {
        name: entries for name, entries in history.items()
    }

    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return render_template(
        "index.html",
        rows=rows,
        now=now,
        up_count=up_count,
        down_count=down_count,
        total=len(rows),
        chart_data=json.dumps(chart_data, ensure_ascii=False),
    )


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)