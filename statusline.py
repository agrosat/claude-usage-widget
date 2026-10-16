"""Statusline do Claude Code que também alimenta o widget da barra de tarefas.

Recebe o JSON da sessão via stdin, grava o estado em usage.json (escrita atômica),
acrescenta uma amostra por minuto em history.jsonl e imprime uma linha curta
para a statusline do terminal.
"""
import json
import os
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
USAGE = os.path.join(BASE, "usage.json")
HISTORY = os.path.join(BASE, "history.jsonl")
RAW = os.path.join(BASE, "last_input.json")
HISTORY_INTERVAL = 60  # segundos entre amostras do histórico


def dig(obj, *paths):
    """Retorna o primeiro valor encontrado entre vários caminhos 'a.b.c'."""
    for path in paths:
        cur = obj
        for key in path.split("."):
            if isinstance(cur, dict) and key in cur:
                cur = cur[key]
            else:
                cur = None
                break
        if cur is not None:
            return cur
    return None


def write_atomic(path, text):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(text)
    os.replace(tmp, path)


def main():
    raw = sys.stdin.buffer.read().decode("utf-8-sig", errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        data = {}
    write_atomic(RAW, raw)

    now = time.time()
    state = {
        "updated_at": now,
        "session_id": dig(data, "session_id"),
        "model": dig(data, "model.display_name", "model.id"),
        "cwd": dig(data, "workspace.current_dir", "cwd"),
        "cost_usd": dig(data, "cost.total_cost_usd"),
        "context_pct": dig(data, "context_window.used_percentage"),
        "five_hour_pct": dig(data, "rate_limits.five_hour.used_percentage"),
        "five_hour_resets_at": dig(data, "rate_limits.five_hour.resets_at"),
        "seven_day_pct": dig(data, "rate_limits.seven_day.used_percentage"),
        "seven_day_resets_at": dig(data, "rate_limits.seven_day.resets_at"),
    }
    write_atomic(USAGE, json.dumps(state, ensure_ascii=False, indent=2))

    try:
        last = os.path.getmtime(HISTORY)
    except OSError:
        last = 0
    if now - last >= HISTORY_INTERVAL:
        sample = {k: state[k] for k in ("updated_at", "five_hour_pct", "seven_day_pct", "context_pct")}
        with open(HISTORY, "a", encoding="utf-8") as f:
            f.write(json.dumps(sample) + "\n")

    parts = [state["model"] or "Claude"]
    for label, key in (("ctx", "context_pct"), ("5h", "five_hour_pct"), ("7d", "seven_day_pct")):
        if state[key] is not None:
            parts.append(f"{label} {round(state[key])}%")
    sys.stdout.reconfigure(encoding="utf-8")
    print(" · ".join(parts))


if __name__ == "__main__":
    main()
