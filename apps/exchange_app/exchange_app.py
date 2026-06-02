import urllib.request
import json
import threading
import os
import time
import py16

APP = {
    "id": "currency",
    "name": "EXCHANGE",
    "w": 140,
    "h": 120,
    "resizable": False
}

# Speicherdatei fuer Persistenz ueber Cart-Neustarts hinweg.
# Namespaced, damit sie nicht mit anderen Plugins kollidiert.
SAVE_PATH = "currency_save.json"

# Offline-Standardwerte (relativ zu EUR), falls noch nie gefetcht wurde.
DEFAULT_RATES = {
    "EUR": 1.0, "USD": 1.08, "GBP": 0.85, "JPY": 160.0, "CHF": 0.98,
    "AUD": 1.65, "CAD": 1.47, "CNY": 7.80, "INR": 90.0, "BRL": 5.40,
    "ZAR": 20.0, "SEK": 11.5, "NOK": 11.5, "MXN": 18.0, "TRY": 35.0, "PLN": 4.30
}

# --- Layout: zentrale Button-Rechtecke (x, y, w, h), lokal zum Fenster ---
# draw() UND update() lesen aus dieser Tabelle, damit gezeichnete Flaechen
# und Hit-Boxen nie auseinanderdriften, wenn man einen Button verschiebt.
LAYOUT = {
    "base_dec":   (10, 20, 12, 12),
    "base_inc":   (46, 20, 12, 12),
    "swap":       (62, 20, 16, 12),
    "target_dec": (82, 20, 12, 12),
    "target_inc": (118, 20, 12, 12),
    "amt_dec":    (10, 45, 12, 12),
    "amt_inc":    (46, 45, 12, 12),
    "update":     (30, 96, 80, 14),
}

# Ab diesem Alter (Sekunden) gelten die Kurse als veraltet -> Warnfarbe.
STALE_AFTER = 24 * 3600

# Mindestabstand (Sekunden) zwischen zwei Fetch-Anfragen (API schonen).
COOLDOWN = 30


def _hit(lx, ly, rect):
    """True, wenn der lokale Klick (lx, ly) im Rechteck liegt."""
    x, y, w, h = rect
    return x <= lx <= x + w and y <= ly <= y + h


def _arrow_btn(wx, wy, rect, symbol):
    """Kleiner < / > Button mit zentriertem Symbol (absolute Koordinaten)."""
    x, y, w, h = rect
    py16.rectfill(wx + x, wy + y, w, h, 5)
    py16.text(symbol, wx + x + 3, wy + y + 4, 7)


def _get_tr(win):
    """Translation-Helper einmalig aufloesen und cachen.

    Vermeidet den 'from __main__ import tr'-Import in jedem Frame. Der
    Fallback gibt das englische Literal bzw. den Key zurueck.
    """
    tr = win.get("tr")
    if tr is None:
        try:
            from __main__ import tr as host_tr
            tr = host_tr
        except Exception:
            tr = lambda key: key.split(":")[-1].replace("_", " ")
        win["tr"] = tr
    return tr


def _fmt_age(secs):
    """Sekunden kompakt als Alter formatieren: <1M, 5M, 2H, 3D."""
    secs = int(max(0, secs))
    if secs < 60:
        return "<1M"
    mins = secs // 60
    if mins < 60:
        return f"{mins}M"
    hours = mins // 60
    if hours < 24:
        return f"{hours}H"
    return f"{hours // 24}D"


def _cooldown_left(win):
    """Verbleibende Sekunden bis der naechste Fetch erlaubt ist (0 = jetzt)."""
    return max(0.0, COOLDOWN - (time.time() - win.get("last_fetch", 0.0)))


def _load():
    """Gespeicherten Zustand laden; bei Fehlern ein leeres Dict."""
    if os.path.isfile(SAVE_PATH):
        try:
            with open(SAVE_PATH) as f:
                data = json.load(f)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
    return {}


def _save(win):
    """Zustand atomar speichern (temp + replace), Fehler tolerieren."""
    data = {
        "base_idx": win["base_idx"],
        "target_idx": win["target_idx"],
        "amt_idx": win["amt_idx"],
        "rates": win["rates"],
        "prev_rates": win["prev_rates"],
        "live_fetches": win["live_fetches"],
        "last_update": win.get("last_update"),
    }
    try:
        tmp = SAVE_PATH + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f)
        os.replace(tmp, SAVE_PATH)
    except Exception:
        pass


def fetch_rates_thread(win):
    """Holt die aktuellen Wechselkurse asynchron im Hintergrund."""
    win["fetching"] = True
    win["status"] = "FETCHING"

    try:
        req = urllib.request.Request(
            "https://open.er-api.com/v6/latest/EUR",
            headers={'User-Agent': 'py16os-currency-app/1.3'}
        )
        with urllib.request.urlopen(req, timeout=5) as response:
            data = json.loads(response.read().decode('utf-8'))

        # API-Antwort validieren, bevor wir sie nutzen. Fehlt "rates" oder
        # meldet die API einen Fehler, ist das KEIN Netzwerkfehler.
        if data.get("result") != "success" or "rates" not in data:
            win["status"] = "API_ERROR"
            return

        # Neue Raten in einem frischen Dict aufbauen und atomar zuweisen,
        # damit draw() nie eine halb-aktualisierte Tabelle liest.
        new_rates = dict(win["rates"])
        new_rates["EUR"] = 1.0
        for cur in win["currencies"]:
            if cur in data["rates"]:
                new_rates[cur] = data["rates"][cur]

        win["prev_rates"] = win["rates"]   # bisherige Raten = Vergleichsbasis
        win["rates"] = new_rates
        win["live_fetches"] = win.get("live_fetches", 0) + 1
        # Zeitstempel der Kurse (API liefert UTC-Unix; Fallback: jetzt).
        win["last_update"] = data.get("time_last_update_unix") or time.time()
        win["status"] = "LIVE_DATA_OK"
        _save(win)
    except Exception:
        win["status"] = "NETWORK_ERROR"
    finally:
        win["fetching"] = False


def init(win):
    """Wird einmalig beim Laden der App aufgerufen."""
    saved = _load()

    win["currencies"] = [
        "EUR", "USD", "GBP", "JPY", "CHF", "AUD", "CAD",
        "CNY", "INR", "BRL", "ZAR", "SEK", "NOK", "MXN", "TRY", "PLN"
    ]

    # Reihenfolge der Quellen: laufende Session > gespeichert > Default.
    win["base_idx"] = win.get("base_idx", saved.get("base_idx", 0))
    win["target_idx"] = win.get("target_idx", saved.get("target_idx", 1))

    win["rates"] = win.get("rates", saved.get("rates", dict(DEFAULT_RATES)))
    win["prev_rates"] = win.get("prev_rates", saved.get("prev_rates", dict(win["rates"])))

    # Zaehler echter Live-Fetches. Der Trend-Pfeil braucht zwei davon, sonst
    # wuerde er Live-Daten gegen die Offline-Dummy-Werte vergleichen.
    win["live_fetches"] = win.get("live_fetches", saved.get("live_fetches", 0))

    # Zeitstempel des letzten erfolgreichen Fetches (Unix-Sekunden) oder None.
    win["last_update"] = win.get("last_update", saved.get("last_update"))

    # Feste Betraege-Liste und aktueller Index (2 = 10.0)
    win["amounts"] = [1.0, 5.0, 10.0, 50.0, 100.0, 500.0, 1000.0]
    win["amt_idx"] = win.get("amt_idx", saved.get("amt_idx", 2))

    # Indizes gegen kaputte/aeltere Speicherdateien absichern.
    max_cur = len(win["currencies"]) - 1
    win["base_idx"] = min(max(0, win["base_idx"]), max_cur)
    win["target_idx"] = min(max(0, win["target_idx"]), max_cur)
    win["amt_idx"] = min(max(0, win["amt_idx"]), len(win["amounts"]) - 1)

    # Wenn ein Zeitstempel existiert, hatten wir schon mal echte Daten.
    default_status = "LIVE_DATA_OK" if win["last_update"] else "LOCAL_DEFAULT"
    win["status"] = win.get("status", default_status)
    win["fetching"] = win.get("fetching", False)
    # Zeitpunkt des letzten Fetch-Versuchs (Session-only, nicht persistiert),
    # damit der Cooldown nach einem Neustart nicht aktiv bleibt.
    win["last_fetch"] = win.get("last_fetch", 0.0)


def update(win, lx, ly, mp, msp, mh):
    """Logik-Update, rechnet mit lokalen Koordinaten (lx, ly)."""
    if not mp:
        return

    curs = win["currencies"]
    max_idx = len(curs) - 1
    changed = True   # wird unten auf False gesetzt, wenn nichts Persistentes passiert

    if _hit(lx, ly, LAYOUT["base_dec"]):
        win["base_idx"] = win["base_idx"] - 1 if win["base_idx"] > 0 else max_idx
    elif _hit(lx, ly, LAYOUT["base_inc"]):
        win["base_idx"] = win["base_idx"] + 1 if win["base_idx"] < max_idx else 0
    elif _hit(lx, ly, LAYOUT["swap"]):
        win["base_idx"], win["target_idx"] = win["target_idx"], win["base_idx"]
    elif _hit(lx, ly, LAYOUT["target_dec"]):
        win["target_idx"] = win["target_idx"] - 1 if win["target_idx"] > 0 else max_idx
    elif _hit(lx, ly, LAYOUT["target_inc"]):
        win["target_idx"] = win["target_idx"] + 1 if win["target_idx"] < max_idx else 0
    elif _hit(lx, ly, LAYOUT["amt_dec"]):
        win["amt_idx"] = max(0, win["amt_idx"] - 1)
    elif _hit(lx, ly, LAYOUT["amt_inc"]):
        win["amt_idx"] = min(len(win["amounts"]) - 1, win["amt_idx"] + 1)
    elif _hit(lx, ly, LAYOUT["update"]):
        if not win.get("fetching", False) and _cooldown_left(win) <= 0:
            win["last_fetch"] = time.time()
            threading.Thread(target=fetch_rates_thread, args=(win,), daemon=True).start()
        changed = False   # Fetch-Thread speichert selbst bei Erfolg
    else:
        changed = False   # Klick ins Leere

    if changed:
        _save(win)


def draw(win, wx, wy, ww, wh, active):
    """Reines Rendern mit absoluten Koordinaten."""
    tr = _get_tr(win)

    py16.clip(wx, wy, ww, wh)

    # Hintergrundfarbe (Start bei wy + 13 fuer die Titelleiste)
    py16.rectfill(wx, wy + 13, ww, wh - 13, 6)

    base_cur = win["currencies"][win["base_idx"]]
    target_cur = win["currencies"][win["target_idx"]]

    # --- ZEILE 1: Waehrungen waehlen (Y = 20) ---
    _arrow_btn(wx, wy, LAYOUT["base_dec"], "<")
    py16.text(base_cur, wx + 34 - len(base_cur) * 2, wy + 24, 1)
    _arrow_btn(wx, wy, LAYOUT["base_inc"], ">")

    # Mitte: tippbarer Swap-Button (tauscht Basis <-> Ziel)
    sx, sy, sw, sh = LAYOUT["swap"]
    py16.rectfill(wx + sx, wy + sy, sw, sh, 5)
    py16.text("->", wx + sx + 4, wy + sy + 4, 7)

    _arrow_btn(wx, wy, LAYOUT["target_dec"], "<")
    py16.text(target_cur, wx + 106 - len(target_cur) * 2, wy + 24, 1)
    _arrow_btn(wx, wy, LAYOUT["target_inc"], ">")

    # --- ZEILE 2: Betrag und Ergebnis (Y = 45) ---
    _arrow_btn(wx, wy, LAYOUT["amt_dec"], "<")
    amount = win["amounts"][win["amt_idx"]]
    amt_str = f"{amount:.0f}"
    py16.text(amt_str, wx + 34 - len(amt_str) * 2, wy + 49, 1)
    _arrow_btn(wx, wy, LAYOUT["amt_inc"], ">")

    # Gleichheitszeichen Mitte
    py16.text("=", wx + 68, wy + 49, 5)

    # Ergebnis berechnen (mit Schutz gegen Division durch 0)
    base_rate = win["rates"].get(base_cur, 1.0) or 1.0
    target_rate = win["rates"].get(target_cur, 1.0) or 1.0
    multiplier = target_rate / base_rate
    result = amount * multiplier

    res_str = f"{result:.2f}"
    res_x = wx + 106 - len(res_str) * 2
    py16.text(res_str, res_x, wy + 49, 1)

    # Trend-Indikator: erst ab zwei echten Live-Fetches sinnvoll, sonst
    # vergleicht man Live-Daten gegen die Offline-Dummy-Werte.
    if win.get("live_fetches", 0) >= 2:
        prev_base = win["prev_rates"].get(base_cur, base_rate) or 1.0
        prev_target = win["prev_rates"].get(target_cur, target_rate) or 1.0
        prev_multiplier = prev_target / prev_base

        trend_x = res_x + len(res_str) * 4 + 4
        trend_y = wy + 49

        # Toleranz gegen Fliesskomma-Ungenauigkeiten beim Vergleich
        if multiplier - prev_multiplier > 0.0001:
            # Gruenes Dreieck (Kurs gestiegen) - Farbindex 11
            py16.pset(trend_x + 2, trend_y + 1, 11)
            py16.line(trend_x + 1, trend_y + 2, trend_x + 3, trend_y + 2, 11)
            py16.line(trend_x, trend_y + 3, trend_x + 4, trend_y + 3, 11)
        elif prev_multiplier - multiplier > 0.0001:
            # Rotes Dreieck (Kurs gefallen) - Farbindex 8
            py16.line(trend_x, trend_y + 1, trend_x + 4, trend_y + 1, 8)
            py16.line(trend_x + 1, trend_y + 2, trend_x + 3, trend_y + 2, 8)
            py16.pset(trend_x + 2, trend_y + 3, 8)

    # --- ZEILE 3: Status + Alter + Update (Y = 76 / 86 / 96) ---
    status_key = win["status"]
    status_col = 8 if "ERROR" in status_key else (11 if "LIVE" in status_key else 5)
    status_text = tr(f"CURRENCY:{status_key}")
    py16.text(status_text, wx + 70 - len(status_text) * 2, wy + 76, status_col)

    # Alter der Kurse anzeigen (nur wenn schon einmal gefetcht wurde)
    last = win.get("last_update")
    if last:
        age = time.time() - last
        age_text = f"{tr('CURRENCY:AGE')} {_fmt_age(age)}"
        age_col = 9 if age > STALE_AFTER else 5   # 9 = orange (veraltet)
        py16.text(age_text, wx + 70 - len(age_text) * 2, wy + 86, age_col)

    # Update-Button (deaktiviert waehrend Fetch und in der Cooldown-Phase)
    bx, by, bw, bh = LAYOUT["update"]
    cool = _cooldown_left(win)
    if win.get("fetching", False):
        btn_col, btn_text = 5, tr("CURRENCY:FETCHING")
    elif cool > 0:
        btn_col, btn_text = 5, f"{tr('CURRENCY:WAIT')} {int(cool) + 1}S"
    else:
        btn_col, btn_text = 1, tr("CURRENCY:UPDATE_RATES")
    py16.rectfill(wx + bx, wy + by, bw, bh, btn_col)
    py16.text(btn_text, wx + 70 - len(btn_text) * 2, wy + 101, 7)

    py16.clip()
