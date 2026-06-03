import urllib.request
import xml.etree.ElementTree as ET
import threading
import textwrap
import re
import html
import json
import os
import time
import datetime
import email.utils

# --- Pfade ---------------------------------------------------------------
# Relativ zum Plugin-File statt zum Arbeitsverzeichnis. Falls __file__
# beim dynamischen Laden nicht gesetzt ist, fallen wir auf "apps/" zurueck.
try:
    _BASE_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    _BASE_DIR = "apps"

CONFIG_PATH = os.path.join(_BASE_DIR, "news_feeds.json")
CACHE_PATH = os.path.join(_BASE_DIR, "news_cache.json")
READ_PATH = os.path.join(_BASE_DIR, "news_read.json")

# Gelesen-IDs pro Feed werden gekappt, damit die Datei nicht unbegrenzt waechst.
READ_LIMIT = 300

# Cache laeuft nach dieser Zeit ab und wird beim naechsten Oeffnen neu
# geladen. Ein Rechtsklick auf eine Feed-Karte erzwingt sofortiges Neuladen.
CACHE_TTL = 900  # 15 Minuten in Sekunden

# Schuetzt parallele Datei-Schreibvorgaenge (mehrere Fetch-Threads).
_FILE_LOCK = threading.Lock()

DEFAULT_FEEDS = [
    {"name": "TAGESSCHAU", "url": "https://www.tagesschau.de/infoservices/alle-meldungen-100~rss2.xml"},
    {"name": "HEISE IT-NEWS", "url": "https://www.heise.de/rss/heise-atom.xml"}
]

APP = {
    "id": "news",
    "name": "NEWS",
    "w": 180,
    "h": 140,
    "resizable": False,
    "icon": "news_app.p16img"
}

# --- Bildschirm-Tastatur: EINE Quelle der Wahrheit ----------------------
# Layout + Geometrie nur hier definiert. update() (Hit-Test) und draw()
# (Rendering) lesen beide aus _kb_keys(), damit nichts auseinanderdriftet.
KB_ROWS = ["1234567890-/", "QWERTZUIOP:.", "ASDFGHJKL_?=", "YXCVBNM"]
KB_ORIGIN_X = 6
KB_ORIGIN_Y = 74
KEY_W = 12
KEY_H = 14
KEY_PAD = 2

# Layout-Konstanten der Listen
ROW_H = 24          # Hoehe einer Feed-/News-Karte
FEED_TOP = 28       # erster Karten-Offset in feed_list
LIST_TOP = 30       # erster Karten-Offset in list

# Auto-Refresh: alle N Frames pruefen, ob ein Feed-Cache veraltet ist, und
# dann EINEN solchen Feed leise im Hintergrund neu laden (nur waehrend das
# Fenster im Vordergrund ist, da update() sonst nicht tickt).
AUTO_REFRESH_FRAMES = 1800   # ~30 s bei 60 FPS

# Loeschen erfordert eine Bestaetigung: zweiter Klick innerhalb dieser Frames.
DEL_CONFIRM_FRAMES = 150     # ~2.5 s

# --- Uebersetzungen ------------------------------------------------------
# Deutsche Defaults; ueber lang/*.json mit Keys wie "NEWS:FEEDS" ueberschreibbar.
_DEFAULT_STRINGS = {
    "FEEDS": "RSS FEEDS:", "ADD": "+ FEED", "EDIT": "EDIT", "DONE": "DONE",
    "NEWS": "NEWS", "DEL": "DEL", "SURE": "SURE?", "NEW": "NEU",
    "LOADING": "LADE NACHRICHTEN", "CANCEL_HINT": "RECHTSKLICK = ABBRUCH",
    "BACK_FEEDS": "< FEEDS", "BACK": "< BACK", "NEW_FEED": "NEUER RSS-FEED:",
    "EDIT_FEED": "FEED BEARBEITEN:", "ERROR": "FEHLER BEIM LADEN!",
    "NAME": "NAME: ", "URL": "URL:  ", "SAVE": "SAVE",
}

_tr_fn = None  # gecachte Referenz auf die Host-Funktion tr() (oder False)


def T(key):
    """Liefert die uebersetzte UI-Zeichenkette. Faellt auf den deutschen
    Default zurueck, wenn der Host kein tr() bereitstellt oder den Key nicht
    kennt."""
    global _tr_fn
    if _tr_fn is None:
        try:
            from __main__ import tr
            _tr_fn = tr
        except Exception:
            _tr_fn = False
    default = _DEFAULT_STRINGS.get(key, key)
    if _tr_fn:
        full = "NEWS:" + key
        try:
            val = _tr_fn(full)
            if val and val != full:
                return val
        except Exception:
            pass
    return default


def _kb_keys():
    """Liefert alle Tasten als Dicts mit Koordinaten relativ zu
    (KB_ORIGIN_X, KB_ORIGIN_Y). update() nutzt die lokalen Koordinaten
    direkt, draw() addiert wx/wy."""
    step_x = KEY_W + KEY_PAD
    step_y = KEY_H + KEY_PAD
    keys = []
    for r, row in enumerate(KB_ROWS):
        for c, ch in enumerate(row):
            keys.append({
                "x": KB_ORIGIN_X + c * step_x,
                "y": KB_ORIGIN_Y + r * step_y,
                "w": KEY_W, "h": KEY_H,
                "kind": "char", "label": ch,
            })
    by = KB_ORIGIN_Y + 3 * step_y
    keys.append({"x": KB_ORIGIN_X + 7 * step_x, "y": by,
                 "w": KEY_W * 2 + KEY_PAD, "h": KEY_H, "kind": "space", "label": "_"})
    keys.append({"x": KB_ORIGIN_X + 9 * step_x, "y": by,
                 "w": KEY_W, "h": KEY_H, "kind": "back", "label": "<"})
    keys.append({"x": KB_ORIGIN_X + 10 * step_x, "y": by,
                 "w": KEY_W * 2 + KEY_PAD, "h": KEY_H, "kind": "save", "label": "SAVE"})
    return keys


# --- Text-Saeuberung -----------------------------------------------------
_TAG_RE = re.compile(r'<[^>]+>')
_WS_RE = re.compile(r'\s+')


def _clean(text):
    """HTML-Entities aufloesen, Tags entfernen, Whitespace normalisieren.
    Einmal beim Parsen ausgefuehrt, sodass Listen- und Detailansicht
    sauberen Text bekommen."""
    if not text:
        return ""
    text = html.unescape(text)
    text = _TAG_RE.sub('', text)
    return _WS_RE.sub(' ', text).strip()


# --- Datum parsen --------------------------------------------------------
def _parse_date(s):
    """Wandelt RSS- (RFC 822) oder Atom- (ISO 8601) Datumsangaben in einen
    Unix-Zeitstempel (float). Unbekannt/leer -> 0.0 (sortiert ans Ende)."""
    if not s:
        return 0.0
    s = s.strip()
    # RFC 822: "Mon, 02 Jun 2025 14:30:00 +0200"
    try:
        dt = email.utils.parsedate_to_datetime(s)
        if dt is not None:
            return dt.timestamp()
    except Exception:
        pass
    # ISO 8601: "2025-06-02T14:30:00Z" / "...+02:00"
    try:
        iso = s.replace("Z", "+00:00")
        dt = datetime.datetime.fromisoformat(iso)
        return dt.timestamp()
    except Exception:
        return 0.0


def _fmt_date(ts):
    """Kurze Anzeige 'TT.MM.' fuer die Liste. 0 -> leer."""
    if not ts:
        return ""
    try:
        t = time.localtime(ts)
        return "%02d.%02d." % (t.tm_mday, t.tm_mon)
    except Exception:
        return ""


def _item_id(title, guid):
    """Stabile ID fuer die Ungelesen-Markierung: bevorzugt die feed-eigene
    guid/id, faellt sonst auf den Titel zurueck."""
    return (guid or title or "").strip()


# --- Datei-IO (gesperrt) -------------------------------------------------
def _save_cache(win):
    with _FILE_LOCK:
        try:
            with open(CACHE_PATH, "w") as f:
                json.dump(win["cache"], f)
        except Exception:
            pass


def _save_feeds(win):
    with _FILE_LOCK:
        try:
            with open(CONFIG_PATH, "w") as f:
                json.dump(win["feeds"], f, indent=2)
        except Exception:
            pass


def _save_read(win):
    with _FILE_LOCK:
        try:
            # Listen statt Sets, damit JSON sie serialisieren kann.
            data = {url: list(ids) for url, ids in win["read"].items()}
            with open(READ_PATH, "w") as f:
                json.dump(data, f)
        except Exception:
            pass


def _mark_read(win, url, gid):
    """Markiert ein Item als gelesen und kappt die Historie pro Feed."""
    if not gid:
        return
    seen = win["read"].setdefault(url, [])
    if gid in seen:
        return
    seen.append(gid)
    if len(seen) > READ_LIMIT:
        del seen[:len(seen) - READ_LIMIT]
    _save_read(win)


def _unread_count(win, url):
    """Anzahl ungelesener Items im Cache dieses Feeds. 0, wenn nicht geladen."""
    entry = win["cache"].get(url)
    if not entry:
        return 0
    seen = set(win["read"].get(url, []))
    return sum(1 for it in entry["items"] if it.get("gid", it.get("title", "")) not in seen)


def _download_and_parse(url):
    """Laedt den Feed und liefert die sortierte Item-Liste. Wirft bei Fehlern.
    Geteilt von Vordergrund- (fetch_feed) und Hintergrund-Refresh."""
    # SSL-Verifizierung bleibt AN (kein CERT_NONE mehr).
    req = urllib.request.Request(url, headers={'User-Agent': 'py-16-OS-NewsApp/1.1'})
    with urllib.request.urlopen(req, timeout=5) as response:
        xml_data = response.read()

    root = ET.fromstring(xml_data)
    items = []
    for el in root.iter():
        tag = el.tag.lower()
        if tag.endswith('item') or tag.endswith('entry'):
            t_text, d_text = "Kein Titel", ""
            guid, date_text = "", ""
            for child in el:
                ctag = child.tag.lower()
                if ctag.endswith('title') and child.text:
                    t_text = child.text
                elif (ctag.endswith('description') or ctag.endswith('summary')) and child.text:
                    d_text = child.text
                elif (ctag.endswith('guid') or ctag.endswith('}id') or ctag == 'id') and child.text:
                    guid = child.text.strip()
                elif (ctag.endswith('pubdate') or ctag.endswith('published')
                      or ctag.endswith('}updated') or ctag == 'updated'
                      or ctag.endswith('}date') or ctag.endswith(':date')) and child.text:
                    # pubDate/published bevorzugen; updated nur als Fallback.
                    if not date_text or 'date' in ctag or 'pub' in ctag or 'publish' in ctag:
                        date_text = child.text.strip()
            title = _clean(t_text)
            pub = _parse_date(date_text)
            items.append({
                "title": title,
                "desc": _clean(d_text),
                "gid": _item_id(title, guid),
                "pub": pub,
                "date": _fmt_date(pub),
            })

    # Neueste zuerst (Items ohne Datum -> pub=0 -> ans Ende).
    items.sort(key=lambda it: it.get("pub", 0.0), reverse=True)
    return items


def fetch_feed(win, url, gen):
    """Laeuft im Hintergrund-Thread. Cache-Key ist die URL (eindeutig,
    ueberlebt Umbenennungen). 'gen' verwirft veraltete Antworten, falls
    der Nutzer zwischenzeitlich woanders geklickt oder abgebrochen hat."""
    try:
        items = _download_and_parse(url)
        # Stale-Antwort? -> still verwerfen.
        if gen != win.get("fetch_gen"):
            return
        win["cache"][url] = {"items": items, "ts": time.time()}
        _save_cache(win)
        win["feed"] = items
        win["state"] = "list"
    except Exception as e:
        if gen != win.get("fetch_gen"):
            return
        win["error_msg"] = str(e)
        win["state"] = "error"


def fetch_feed_silent(win, url):
    """Hintergrund-Refresh: aktualisiert nur den Cache, ohne den sichtbaren
    Zustand (state/feed) zu beruehren. So bleiben Lese-Ansicht und Scroll
    unangetastet; nur die Ungelesen-Zaehler aktualisieren sich."""
    try:
        items = _download_and_parse(url)
        win["cache"][url] = {"items": items, "ts": time.time()}
        _save_cache(win)
    except Exception:
        pass
    finally:
        win["auto_busy"] = False


def _auto_refresh_tick(win):
    """Periodischer Check: laedt EINEN veralteten Feed leise nach."""
    if win.get("auto_busy"):
        return
    if win.get("t", 0) % AUTO_REFRESH_FRAMES != 0:
        return
    now = time.time()
    stalest_url, stalest_ts = None, None
    for feed in win["feeds"]:
        url = feed["url"]
        entry = win["cache"].get(url)
        ts = entry.get("ts", 0) if entry else 0
        if now - ts > CACHE_TTL:
            if stalest_ts is None or ts < stalest_ts:
                stalest_ts, stalest_url = ts, url
    if stalest_url:
        win["auto_busy"] = True
        threading.Thread(target=fetch_feed_silent, args=(win, stalest_url), daemon=True).start()


def _open_feed(win, idx, force=False):
    """Einzige Stelle, die einen Feed oeffnet (von Button-Klick,
    Karten-Klick und Force-Refresh genutzt)."""
    if not (0 <= idx < len(win["feeds"])):
        return
    url = win["feeds"][idx]["url"]
    entry = win["cache"].get(url)
    win["scroll_y"] = 0
    win["current_url"] = url
    fresh = entry and (time.time() - entry.get("ts", 0) <= CACHE_TTL)
    if entry and fresh and not force:
        win["feed"] = entry["items"]
        win["state"] = "list"
    else:
        win["state"] = "loading"
        win["fetch_gen"] = win.get("fetch_gen", 0) + 1
        threading.Thread(target=fetch_feed, args=(win, url, win["fetch_gen"]), daemon=True).start()


def _save_new_feed(win):
    name = (win.get("kb_name") or "").strip()
    url = (win.get("kb_url") or "").strip()
    if not (name and url):
        return
    ei = win.get("edit_idx")
    if ei is not None and 0 <= ei < len(win["feeds"]):
        old_url = win["feeds"][ei]["url"]
        win["feeds"][ei] = {"name": name, "url": url}
        if old_url != url:
            # Cache/Lese-Status der alten URL verwerfen.
            win["cache"].pop(old_url, None)
            win["read"].pop(old_url, None)
            _save_cache(win)
            _save_read(win)
    else:
        win["feeds"].append({"name": name, "url": url})
    win["edit_idx"] = None
    _save_feeds(win)
    win["state"] = "feed_list"


def _delete_feed(win, idx):
    """Loescht einen Feed inkl. seines Cache- und Lese-Status."""
    if not (0 <= idx < len(win["feeds"])):
        return
    url = win["feeds"][idx]["url"]
    del win["feeds"][idx]
    win["cache"].pop(url, None)
    win["read"].pop(url, None)
    _save_feeds(win)
    _save_cache(win)
    _save_read(win)


def _arm_or_delete(win, idx):
    """Erster DEL-Klick scharfschalten ('SURE?'), zweiter Klick innerhalb
    DEL_CONFIRM_FRAMES loescht tatsaechlich."""
    armed = win.get("del_armed_idx", -1)
    if armed == idx and (win["t"] - win.get("del_armed_t", 0)) < DEL_CONFIRM_FRAMES:
        _delete_feed(win, idx)
        win["del_armed_idx"] = -1
    else:
        win["del_armed_idx"] = idx
        win["del_armed_t"] = win["t"]


def _enter_edit(win, idx):
    """Oeffnet das Formular mit vorbefuellten Werten zum Bearbeiten."""
    if not (0 <= idx < len(win["feeds"])):
        return
    win["edit_idx"] = idx
    win["kb_name"] = win["feeds"][idx]["name"]
    win["kb_url"] = win["feeds"][idx]["url"]
    win["kb_focus"] = 0
    win["del_armed_idx"] = -1
    win["state"] = "add_feed"


def init(win):
    # Feeds laden (oder Default schreiben).
    win["feeds"] = list(DEFAULT_FEEDS)
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r") as f:
                loaded = json.load(f)
            if isinstance(loaded, list):
                win["feeds"] = loaded
        except Exception:
            pass
    else:
        _save_feeds(win)  # Default-Datei einmalig anlegen

    # Cache laden. Altes/ungueltiges Format wird verworfen, damit
    # _open_feed nicht ueber eine Liste statt eines Dicts stolpert.
    win["cache"] = {}
    try:
        if os.path.exists(CACHE_PATH):
            with open(CACHE_PATH, "r") as f:
                raw = json.load(f)
            if isinstance(raw, dict) and all(
                isinstance(v, dict) and "items" in v for v in raw.values()
            ):
                win["cache"] = raw
    except Exception:
        pass

    # Gelesen-Status laden.
    win["read"] = {}
    try:
        if os.path.exists(READ_PATH):
            with open(READ_PATH, "r") as f:
                raw = json.load(f)
            if isinstance(raw, dict):
                win["read"] = {k: list(v) for k, v in raw.items() if isinstance(v, list)}
    except Exception:
        pass

    win["state"] = "feed_list"
    win["feed"] = []
    win["fetch_gen"] = 0
    win["t"] = 0
    win["edit_mode"] = False
    win["edit_idx"] = None
    win["del_armed_idx"] = -1
    win["auto_busy"] = False


def enter_detail(win, idx):
    win["selected"] = idx
    win["state"] = "detail"
    win["detail_scroll_y"] = 0
    item = win["feed"][idx]
    # Als gelesen markieren.
    url = win.get("current_url")
    if url:
        _mark_read(win, url, item.get("gid", item.get("title", "")))
    max_chars = max(1, (win["w"] - 16) // 4)
    win["detail_lines"] = {
        "title": textwrap.wrap(item["title"], max_chars),
        "desc": textwrap.wrap(item["desc"], max_chars),  # bereits gesaeubert
    }
    win["detail_date"] = item.get("date", "")


def update(win, lx, ly, mp, msp, mh):
    win["t"] = win.get("t", 0) + 1
    _auto_refresh_tick(win)

    if msp:  # Rechtsklick
        if win["state"] == "loading":
            # Laufenden Ladevorgang abbrechen: Thread-Ergebnis verwerfen.
            win["fetch_gen"] = win.get("fetch_gen", 0) + 1
            win["state"] = "feed_list"
            return
        if win["state"] == "feed_list":
            # Rechtsklick auf eine Feed-Karte = Force-Refresh.
            if ly >= FEED_TOP:
                idx = int((ly - FEED_TOP + win.get("feed_scroll_y", 0)) // ROW_H)
                if 0 <= idx < len(win["feeds"]):
                    _open_feed(win, idx, force=True)
            return
        if win["state"] == "list":
            win["state"] = "feed_list"
        elif win["state"] == "detail":
            win["state"] = "list"
        elif win["state"] == "error":
            win["state"] = "feed_list"
        elif win["state"] == "add_feed":
            win["state"] = "feed_list"
            win["edit_idx"] = None
        if "drag_start_y" in win:
            del win["drag_start_y"]
        return

    if win["state"] == "loading":
        return

    if win["state"] == "add_feed":
        if mp:
            # Back-Button
            if 4 <= lx <= 44 and 14 <= ly <= 26:
                win["state"] = "feed_list"
                win["edit_idx"] = None
                return

            # Focus Name-Feld
            if 6 <= lx <= win["w"] - 6 and 32 <= ly <= 46:
                win["kb_focus"] = 0
                return

            # Focus URL-Feld
            if 6 <= lx <= win["w"] - 6 and 52 <= ly <= 66:
                win["kb_focus"] = 1
                return

            # Tastatur-Hit-Test ueber die gemeinsame Layout-Definition.
            for key in _kb_keys():
                if key["x"] <= lx <= key["x"] + key["w"] and key["y"] <= ly <= key["y"] + key["h"]:
                    _kb_press(win, key)
                    return

    elif win["state"] == "feed_list":
        if mp:
            # Header: EDIT/DONE-Umschalter
            if win["w"] - 92 <= lx <= win["w"] - 52 and 14 <= ly <= 26:
                win["edit_mode"] = not win.get("edit_mode", False)
                win["del_armed_idx"] = -1
                return

            # Header: [+ FEED] (neuer Feed)
            if lx >= win["w"] - 48 and 14 <= ly <= 26:
                win["state"] = "add_feed"
                win["edit_idx"] = None
                win["kb_name"] = ""
                win["kb_url"] = "https://"
                win["kb_focus"] = 0
                return

            # Sofort-Klick auf NEWS-Button (nur ausserhalb des Edit-Modus).
            btn_clicked = False
            if not win.get("edit_mode") and ly >= FEED_TOP:
                idx = int((ly - FEED_TOP + win.get("feed_scroll_y", 0)) // ROW_H)
                if 0 <= idx < len(win["feeds"]) and win["w"] - 42 <= lx <= win["w"] - 8:
                    btn_clicked = True
                    _open_feed(win, idx)

            if not btn_clicked:
                win["drag_start_y"] = ly
                win["drag_start_x"] = lx
                win["drag_start_scroll"] = win.get("feed_scroll_y", 0)
                win["drag_moved"] = False

        elif mh and "drag_start_y" in win:
            dy = win["drag_start_y"] - ly
            if abs(dy) > 4:
                win["drag_moved"] = True
            max_scroll = max(0, len(win["feeds"]) * ROW_H - (win["h"] - 14))
            win["feed_scroll_y"] = max(0, min(max_scroll, win["drag_start_scroll"] + dy))

        elif not mh and not mp and "drag_start_y" in win:
            # Tap (ohne Scrollen) auf eine Feed-Karte.
            if not win.get("drag_moved", False) and win["drag_start_y"] >= FEED_TOP:
                idx = int((win["drag_start_y"] - FEED_TOP + win.get("feed_scroll_y", 0)) // ROW_H)
                if 0 <= idx < len(win["feeds"]):
                    if win.get("edit_mode"):
                        # Rechter Bereich = DEL, sonst Bearbeiten.
                        if win["w"] - 42 <= win.get("drag_start_x", 0) <= win["w"] - 8:
                            _arm_or_delete(win, idx)
                        else:
                            _enter_edit(win, idx)
                    else:
                        _open_feed(win, idx)
            if "drag_start_y" in win:
                del win["drag_start_y"]

    elif win["state"] == "list":
        if mp:
            if 4 <= lx <= 44 and 14 <= ly <= 26:
                win["state"] = "feed_list"
                if "drag_start_y" in win:
                    del win["drag_start_y"]
                return
            else:
                win["drag_start_y"] = ly
                win["drag_start_scroll"] = win.get("scroll_y", 0)
                win["drag_moved"] = False
        elif mh and "drag_start_y" in win:
            dy = win["drag_start_y"] - ly
            if abs(dy) > 4:
                win["drag_moved"] = True
            max_scroll = max(0, len(win["feed"]) * ROW_H - (win["h"] - 30))
            win["scroll_y"] = max(0, min(max_scroll, win["drag_start_scroll"] + dy))
        elif not mh and not mp and "drag_start_y" in win:
            if not win.get("drag_moved", False) and win["drag_start_y"] > LIST_TOP:
                clicked_idx = int((win["drag_start_y"] - LIST_TOP + win.get("scroll_y", 0)) // ROW_H)
                if 0 <= clicked_idx < len(win["feed"]):
                    enter_detail(win, clicked_idx)
            if "drag_start_y" in win:
                del win["drag_start_y"]

    elif win["state"] == "detail":
        if mp:
            if 4 <= lx <= 44 and 14 <= ly <= 26:
                win["state"] = "list"
                if "drag_start_y" in win:
                    del win["drag_start_y"]
                return
            else:
                win["drag_start_y"] = ly
                win["drag_start_scroll"] = win.get("detail_scroll_y", 0)
        elif mh and "drag_start_y" in win:
            dy = win["drag_start_y"] - ly
            win["detail_scroll_y"] = max(0, min(win.get("max_detail_scroll", 0), win["drag_start_scroll"] + dy))
        elif not mh and not mp and "drag_start_y" in win:
            if "drag_start_y" in win:
                del win["drag_start_y"]

    elif win["state"] == "error":
        if mp and 10 <= lx <= 50 and 45 <= ly <= 57:
            win["state"] = "feed_list"


def _kb_press(win, key):
    """Verarbeitet einen Tastendruck. URL wird NICHT mehr kleingeschrieben
    (manche Feed-URLs sind case-sensitive)."""
    kind = key["kind"]
    if kind == "char":
        ch = key["label"]
        if win.get("kb_focus") == 0:
            win["kb_name"] += ch
        else:
            win["kb_url"] += ch
    elif kind == "space":
        if win.get("kb_focus") == 0:
            win["kb_name"] += " "
        else:
            win["kb_url"] += " "
    elif kind == "back":
        if win.get("kb_focus") == 0:
            win["kb_name"] = win["kb_name"][:-1]
        else:
            win["kb_url"] = win["kb_url"][:-1]
    elif kind == "save":
        _save_new_feed(win)


def draw(win, wx, wy, ww, wh, is_active):
    import py16
    py16.clip(wx, wy + 14, ww, wh - 14)
    py16.rectfill(wx, wy + 14, ww, wh - 14, 1)

    tc = 7 if is_active else 6
    hl = 10 if is_active else 5

    if win["state"] == "add_feed":
        # Back-Button
        py16.rectfill(wx + 4, wy + 14, 40, 12, 5)
        py16.rect(wx + 4, wy + 14, 40, 12, 6)
        py16.text(T("BACK"), wx + 8, wy + 18, tc)

        title = T("EDIT_FEED") if win.get("edit_idx") is not None else T("NEW_FEED")
        py16.text(title, wx + 50, wy + 18, hl)

        # Feld 1: Name
        f_col = 13 if win.get("kb_focus") == 0 else 5
        py16.rectfill(wx + 6, wy + 32, ww - 12, 14, f_col)
        py16.rect(wx + 6, wy + 32, ww - 12, 14, tc)
        py16.text((T("NAME") + win.get("kb_name", ""))[-35:], wx + 10, wy + 37, hl)

        # Feld 2: URL
        f_col = 13 if win.get("kb_focus") == 1 else 5
        py16.rectfill(wx + 6, wy + 52, ww - 12, 14, f_col)
        py16.rect(wx + 6, wy + 52, ww - 12, 14, tc)
        py16.text((T("URL") + win.get("kb_url", ""))[-35:], wx + 10, wy + 57, hl)

        # Tastatur ueber die gemeinsame Layout-Definition zeichnen.
        for key in _kb_keys():
            kx = wx + key["x"]
            ky = wy + key["y"]
            kind = key["kind"]
            if kind == "save":
                py16.rectfill(kx, ky, key["w"], key["h"], 11)  # Gruen
                py16.rect(kx, ky, key["w"], key["h"], tc)
                py16.text("SAVE", kx + 6, ky + 5, 0)            # Schwarz
            elif kind == "back":
                py16.rectfill(kx, ky, key["w"], key["h"], 5)
                py16.rect(kx, ky, key["w"], key["h"], 6)
                py16.text("<", kx + 4, ky + 5, 8)               # Rot
            elif kind == "space":
                py16.rectfill(kx, ky, key["w"], key["h"], 5)
                py16.rect(kx, ky, key["w"], key["h"], 6)
                py16.text("_", kx + 10, ky + 5, tc)
            else:
                py16.rectfill(kx, ky, key["w"], key["h"], 5)
                py16.rect(kx, ky, key["w"], key["h"], 6)
                py16.text(key["label"], kx + 4, ky + 5, tc)

    elif win["state"] == "loading":
        text = T("LOADING")
        px = wx + (ww - len(text) * 4) // 2
        py16.text(text, px, wy + wh // 2 - 12, tc)

        anim_frames = ["|", "/", "-", "\\"]
        spinner = anim_frames[(win.get("t", 0) // 8) % 4]
        py16.text(spinner, wx + ww // 2 - 2, wy + wh // 2 + 2, hl)

        hint = T("CANCEL_HINT")
        hx = wx + (ww - len(hint) * 4) // 2
        py16.text(hint, hx, wy + wh // 2 + 14, 6)

    elif win["state"] == "feed_list":
        py16.text(T("FEEDS"), wx + 6, wy + 18, tc)

        # EDIT/DONE-Umschalter
        edit_mode = win.get("edit_mode", False)
        py16.rectfill(wx + ww - 92, wy + 14, 40, 12, 8 if edit_mode else 1)
        py16.rect(wx + ww - 92, wy + 14, 40, 12, tc)
        py16.text(T("DONE") if edit_mode else T("EDIT"), wx + ww - 88, wy + 18, tc)

        # + FEED
        py16.rectfill(wx + ww - 48, wy + 14, 44, 12, 1)
        py16.rect(wx + ww - 48, wy + 14, 44, 12, tc)
        py16.text(T("ADD"), wx + ww - 44, wy + 18, tc)

        scroll = win.get("feed_scroll_y", 0)
        for i, feed in enumerate(win["feeds"]):
            item_y = wy + FEED_TOP + i * ROW_H - scroll
            if item_y > wy + wh or item_y + ROW_H < wy + 14:
                continue

            py16.rectfill(wx + 4, item_y + 2, ww - 12, 20, 13 if is_active else 5)

            unread = _unread_count(win, feed["url"])
            name_max = (ww - 90) // 4 if unread else (ww - 50) // 4
            py16.text(feed["name"][:max(1, name_max)], wx + 8, item_y + 6, hl)

            if unread:
                badge = (str(unread) if unread < 100 else "99+") + " " + T("NEW")
                py16.text(badge, wx + 8, item_y + 14, 11)  # gruen

            bx = wx + ww - 42
            by = item_y + 4
            if edit_mode:
                armed = win.get("del_armed_idx") == i and \
                    (win.get("t", 0) - win.get("del_armed_t", 0)) < DEL_CONFIRM_FRAMES
                py16.rectfill(bx, by, 34, 16, 8)  # rot
                py16.rect(bx, by, 34, 16, tc)
                lbl = T("SURE") if armed else T("DEL")
                py16.text(lbl, bx + (34 - len(lbl) * 4) // 2, by + 6, 7)
            else:
                py16.rectfill(bx, by, 34, 16, 1)
                py16.rect(bx, by, 34, 16, tc)
                py16.text(T("NEWS"), bx + 6, by + 6, tc)

    elif win["state"] == "list":
        url = win.get("current_url")
        seen = set(win["read"].get(url, [])) if url else set()
        for i, item in enumerate(win["feed"]):
            item_y = wy + LIST_TOP + i * ROW_H - win.get("scroll_y", 0)
            if item_y > wy + wh or item_y + ROW_H < wy + LIST_TOP:
                continue

            is_read = item.get("gid", item.get("title", "")) in seen
            py16.rectfill(wx + 4, item_y + 2, ww - 12, 20, 5)

            date = item.get("date", "")
            date_w = len(date) * 4 + 4 if date else 0
            max_c = max(1, (ww - 20 - date_w) // 4)
            t_short = item["title"][:max_c] + ("." if len(item["title"]) > max_c else "")
            d_short = item["desc"][:max_c] + ("." if len(item["desc"]) > max_c else "")

            # Gelesene Titel gedaempft (6 statt hl), ungelesene hervorgehoben.
            title_col = 6 if is_read else hl
            py16.text(t_short, wx + 8, item_y + 6, title_col)
            py16.text(d_short, wx + 8, item_y + 14, 6)

            if date:
                py16.text(date, wx + ww - date_w - 4, item_y + 6, 12)  # blau, klein

        py16.rectfill(wx + 4, wy + 14, 40, 12, 5)
        py16.rect(wx + 4, wy + 14, 40, 12, 6)
        py16.text(T("BACK_FEEDS"), wx + 6, wy + 18, tc)

    elif win["state"] == "detail":
        content_y = wy + 30 - win.get("detail_scroll_y", 0)
        for line in win["detail_lines"]["title"]:
            if wy + 14 < content_y < wy + wh:
                py16.text(line, wx + 6, content_y, hl)
            content_y += 8
        content_y += 6
        date = win.get("detail_date", "")
        if date and wy + 14 < content_y < wy + wh:
            py16.text(date, wx + 6, content_y, 12)  # blau
        if date:
            content_y += 10
        for line in win["detail_lines"]["desc"]:
            if wy + 14 < content_y < wy + wh:
                py16.text(line, wx + 6, content_y, tc)
            content_y += 6

        win["max_detail_scroll"] = max(0, content_y + win.get("detail_scroll_y", 0) - (wy + 30) - (wh - 40))

        py16.rectfill(wx + 4, wy + 14, 40, 12, 5)
        py16.rect(wx + 4, wy + 14, 40, 12, 6)
        py16.text(T("BACK"), wx + 8, wy + 18, tc)

    elif win["state"] == "error":
        py16.text(T("ERROR"), wx + 10, wy + 30, 8)
        py16.text(win.get("error_msg", "")[:40], wx + 10, wy + 38, 6)
        py16.rectfill(wx + 10, wy + 45, 40, 12, 5)
        py16.rect(wx + 10, wy + 45, 40, 12, 6)
        py16.text("BACK", wx + 18, wy + 49, tc)

    py16.clip()
