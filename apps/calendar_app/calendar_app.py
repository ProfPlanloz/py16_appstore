# apps/calendar.py
APP = {
    "id": "calendar",
    "name": "CALENDAR",
    "w": 140,
    "h": 160,
    "resizable": True,
    "min_w": 140,
    "min_h": 140,
    "icon": "calendar_app.p16img"
}

SAVE_PATH = "calendar_events.json"

# Termin-Farben (Palette-Indizes): Rot, Grün, Gelb, Blau
EVENT_COLORS = [8, 11, 10, 12]
YELLOW = 10  # heller Hintergrund -> braucht dunkle Schrift

# Durchschaltbare Termin-Label. "" = kein Label, nur Farbe.
# Werte sind zugleich die tr()-Keys (englische Wörter als Fallback).
EVENT_LABELS = ["", "APPT", "BIRTHDAY", "HOLIDAY", "OFF", "URGENT", "DOCTOR", "MEETING"]

# Maße des Termin-Modals an EINER Stelle, damit update() und draw() nicht auseinanderlaufen
MODAL_W = 72
MODAL_H = 50

# Lokale Y-Position (relativ zur Fenster-Oberkante), ab der die Mini-Agenda beginnt.
# 42 (Raster-Start) + 60 (immer 6 Zeilen reserviert) + 4 (Abstand).
AGENDA_Y = 106


def _beep(freq, dur=6):
    """Dezentes Ton-Feedback. Fehlt py16.tone, passiert nichts."""
    try:
        import py16
        py16.tone(freq, dur, py16.WAVE_SQUARE)
    except Exception:
        pass


def _today():
    """Aktuelles Datum frisch ermitteln (nicht cachen -> bleibt über Mitternacht korrekt)."""
    import datetime
    n = datetime.datetime.now()
    return n.year, n.month, n.day


def _norm_event(v):
    """Vereinheitlicht einen gespeicherten Termin auf {'color': int, 'label': str}.

    Akzeptiert das alte Reinfarben-Format (int) genauso wie das neue Dict-Format.
    """
    if isinstance(v, dict):
        try:
            col = int(v.get("color", EVENT_COLORS[0]))
        except Exception:
            col = EVENT_COLORS[0]
        return {"color": col, "label": str(v.get("label", ""))}
    try:
        return {"color": int(v), "label": ""}
    except Exception:
        return {"color": EVENT_COLORS[0], "label": ""}


def _ensure_event(win, date):
    ev = win["events"].get(date)
    if ev is None:
        ev = {"color": EVENT_COLORS[0], "label": ""}
        win["events"][date] = ev
    return ev


def _cycle_label(win, date, step):
    ev = _ensure_event(win, date)
    lbl = ev.get("label", "")
    try:
        i = EVENT_LABELS.index(lbl)
    except ValueError:
        i = 0
    ev["label"] = EVENT_LABELS[(i + step) % len(EVENT_LABELS)]


def _save_events(win):
    """Speichert die markierten Tage im Dateisystem."""
    import json
    try:
        with open(SAVE_PATH, "w") as f:
            json.dump({"events": win["events"]}, f)
    except Exception:
        pass


def _agenda_metrics(wh):
    """Liefert (lokale Agenda-Y, Anzahl Einträge die passen) für die aktuelle Höhe."""
    btn_y = wh - 16
    avail = btn_y - 2 - AGENDA_Y       # Platz zwischen Raster und TODAY-Button
    max_entries = max(0, (avail - 8) // 8)  # 8px Titel + 8px pro Zeile
    return AGENDA_Y, max_entries


def _upcoming(win, limit):
    """Sortierte Liste (date_str, color, label) ab heute, auf 'limit' begrenzt."""
    ty, tm, td = _today()
    today_key = f"{ty}-{tm:02d}-{td:02d}"
    items = []
    for k, v in win["events"].items():
        if k >= today_key:  # ISO-Datum YYYY-MM-DD vergleicht sich lexikografisch korrekt
            items.append((k, v.get("color", EVENT_COLORS[0]), v.get("label", "")))
    items.sort(key=lambda x: x[0])
    return items[:limit]


def init(win):
    import json, os
    ty, tm, _td = _today()
    win["year"] = ty
    win["month"] = tm
    win["events"] = {}
    win["modal_date"] = None
    win["modal_x"] = 0
    win["modal_y"] = 0

    # Persistente Daten laden
    if os.path.isfile(SAVE_PATH):
        try:
            with open(SAVE_PATH, "r") as f:
                data = json.load(f).get("events", {})
                # Migration: alte Liste -> Dict (Rot als Standardfarbe)
                if isinstance(data, list):
                    data = {d: EVENT_COLORS[0] for d in data}
                # Alle Werte auf {'color','label'} normalisieren
                win["events"] = {k: _norm_event(v) for k, v in data.items()}
        except Exception:
            pass


def update(win, lx, ly, mp, msp, mh):
    import calendar

    ww = win.get("w", 140)
    wh = win.get("h", 160)

    # --- MODAL OVERLAY LOGIK ---
    if win.get("modal_date"):
        # Rechtsklick schließt das Modal sofort
        if msp:
            win["modal_date"] = None
            return
        if mp:
            mx = win["modal_x"]
            my = win["modal_y"]
            date = win["modal_date"]
            # Klick innerhalb des Modals?
            if mx <= lx <= mx + MODAL_W and my <= ly <= my + MODAL_H:
                # Farb-Buttons (Modal bleibt offen, damit man danach ein Label wählen kann)
                if my + 4 <= ly <= my + 14:
                    for i, c in enumerate(EVENT_COLORS):
                        cx = mx + 4 + i * 14
                        if cx <= lx <= cx + 10:
                            _ensure_event(win, date)["color"] = c
                            _save_events(win)
                            _beep(988)
                # Label-Zeile: < zurück, sonst vor
                elif my + 18 <= ly <= my + 30:
                    step = -1 if (mx + 3 <= lx <= mx + 11) else 1
                    _cycle_label(win, date, step)
                    _save_events(win)
                    _beep(760, 5)
                # CLEAR Button
                elif my + 34 <= ly <= my + 46:
                    if mx + 4 <= lx <= mx + MODAL_W - 4:
                        if date in win["events"]:
                            del win["events"][date]
                            _save_events(win)
                        win["modal_date"] = None
                        _beep(440, 8)
            else:
                win["modal_date"] = None  # Klick daneben schließt das Modal
        return  # Blockiert die normalen Kalender-Klicks, solange Modal offen ist

    # Dynamische Hitboxen basierend auf Fenstergröße
    header_y = 16
    grid_y = 42
    btn_y = wh - 16
    ag_y, ag_max = _agenda_metrics(wh)

    # Navigation oben (Monat/Jahr)
    if header_y <= ly <= header_y + 10:
        # Links "<"
        if 4 <= lx <= 16:
            if mp:  # Linksklick: 1 Monat zurück
                win["month"] -= 1
                if win["month"] < 1:
                    win["month"] = 12
                    win["year"] = max(1, win["year"] - 1)
                _beep(600, 5)
            elif msp:  # Rechtsklick: 1 Jahr zurück
                win["year"] = max(1, win["year"] - 1)
                _beep(600, 5)

        # Rechts ">"
        elif ww - 16 <= lx <= ww - 4:
            if mp:  # Linksklick: 1 Monat vor
                win["month"] += 1
                if win["month"] > 12:
                    win["month"] = 1
                    win["year"] += 1
                _beep(640, 5)
            elif msp:  # Rechtsklick: 1 Jahr vor
                win["year"] += 1
                _beep(640, 5)

    # Jump-To-Today Button unten
    elif btn_y <= ly <= btn_y + 10:
        btn_x = (ww - 50) // 2
        if btn_x <= lx <= btn_x + 50 and mp:
            ty, tm, _td = _today()
            win["year"] = ty
            win["month"] = tm
            _beep(920)

    # Raster-Klick für Termine öffnet das Modal
    elif grid_y <= ly <= grid_y + 60 and mp:
        col_w = 18
        grid_w = 7 * col_w
        start_x = (ww - grid_w) // 2

        cal = calendar.monthcalendar(win["year"], win["month"])

        row_idx = (ly - grid_y) // 10
        col_idx = (lx - start_x) // col_w

        if 0 <= row_idx < len(cal) and 0 <= col_idx < 7:
            day = cal[row_idx][col_idx]
            if day != 0:
                date_str = f"{win['year']}-{win['month']:02d}-{day:02d}"
                win["modal_date"] = date_str
                # Modal an der Klickposition öffnen, aber innerhalb des Fensters halten
                win["modal_x"] = min(lx, ww - (MODAL_W + 2))
                win["modal_y"] = min(ly, wh - (MODAL_H + 2))
                _beep(880)

    # Klick auf einen Agenda-Eintrag springt zum jeweiligen Monat
    elif ag_max > 0 and (ag_y + 8) <= ly < (ag_y + 8 + ag_max * 8) and mp:
        idx = (ly - (ag_y + 8)) // 8
        items = _upcoming(win, ag_max)
        if 0 <= idx < len(items):
            yy, mm, _dd = items[idx][0].split("-")
            win["year"] = int(yy)
            win["month"] = int(mm)
            _beep(720)


def draw(win, wx, wy, ww, wh, active):
    import py16
    import calendar

    try:
        from __main__ import tr
    except ImportError:
        tr = lambda x: x

    # Auf den Fensterinhalt clippen, damit nichts (z. B. Modal-Schatten) über den Rand zeichnet
    py16.clip(wx, wy + 14, ww, wh - 14)

    # Aktuelles Datum frisch holen -> Markierung & TODAY bleiben über Mitternacht korrekt
    ty, tm, td = _today()

    # Hintergrund & Rand (Titelleiste des OS aussparen!)
    py16.rectfill(wx, wy + 14, ww, wh - 14, 6)
    py16.rect(wx, wy + 14, ww, wh - 14, 5)

    header_y = wy + 16
    grid_y = wy + 42
    btn_y = wy + wh - 16

    col_w = 18
    grid_w = 7 * col_w
    start_x = wx + (ww - grid_w) // 2

    # === Header ===
    month_names = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
                   "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]
    m_str = tr(month_names[win["month"] - 1])
    header_txt = f"{m_str} {win['year']}"

    btn_color = 6 if active else 5

    # Navigationstasten
    py16.rectfill(wx + 4, header_y, 12, 10, btn_color)
    py16.rect(wx + 4, header_y, 12, 10, 5)
    py16.text("<", wx + 8, header_y + 3, 1)

    py16.rectfill(wx + ww - 16, header_y, 12, 10, btn_color)
    py16.rect(wx + ww - 16, header_y, 12, 10, 5)
    py16.text(">", wx + ww - 12, header_y + 3, 1)

    txt_w = len(header_txt) * 4
    py16.text(header_txt, wx + (ww - txt_w) // 2, header_y + 3, 1)

    # === Wochentage ===
    py16.line(wx + 4, wy + 29, wx + ww - 4, wy + 29, 5)
    days = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

    for i, d in enumerate(days):
        d_txt = tr(d)[:2]
        dx = start_x + i * col_w + 5
        c = 1 if i < 5 else 8
        py16.text(d_txt, dx, wy + 32, c)

    # === Kalender-Raster ===
    cal = calendar.monthcalendar(win["year"], win["month"])
    for row_idx, row in enumerate(cal):
        for col_idx, day in enumerate(row):
            if day != 0:
                dx = start_x + col_idx * col_w
                dy = grid_y + row_idx * 10

                is_today = (win["year"] == ty and
                            win["month"] == tm and
                            day == td)

                date_str = f"{win['year']}-{win['month']:02d}-{day:02d}"
                ev = win["events"].get(date_str)
                event_color = ev["color"] if ev else None

                day_str = str(day)
                tw = len(day_str) * 4
                tx = dx + (col_w - tw) // 2

                # Farb-Hintergrund für markierte Termine
                # (heute bekommt eine eigene Box -> dort separat behandelt)
                if event_color is not None and not is_today:
                    py16.rectfill(tx - 2, dy + 1, tw + 3, 5, event_color)

                if is_today:
                    py16.rectfill(dx + 2, dy - 2, 14, 9, 1)
                    py16.text(day_str, tx, dy, 7)
                    # Heute UND Termin: kleiner Farbstreifen, der die Heute-Box "überlebt"
                    if event_color is not None:
                        py16.rectfill(dx + 3, dy + 5, 12, 2, event_color)
                else:
                    color = 1 if col_idx < 5 else 8  # Farbe 1 (Dunkelblau) für Werktage
                    if event_color is not None:
                        # Gelber Hintergrund braucht dunkle Schrift, der Rest weiße Schrift
                        color = 0 if event_color == YELLOW else 7
                    py16.text(day_str, tx, dy, color)

    # === Mini-Agenda ===
    ag_y_local, ag_max = _agenda_metrics(wh)
    if ag_max > 0:
        ax = wx + 6
        ay = wy + ag_y_local
        py16.line(wx + 4, ay - 2, wx + ww - 4, ay - 2, 5)
        py16.text(tr("UPCOMING"), ax, ay, 1)

        items = _upcoming(win, ag_max)
        if not items:
            py16.text(tr("NO EVENTS"), ax, ay + 9, 5)
        else:
            for i, (ds, col, lbl) in enumerate(items):
                ry = ay + 8 + i * 8
                yy, mm, dd = ds.split("-")
                m_lbl = tr(month_names[int(mm) - 1])
                py16.text(f"{m_lbl} {int(dd):02d}", ax, ry + 1, 1)
                sw_x = ax + 26
                py16.rectfill(sw_x, ry + 1, 5, 5, col)
                py16.rect(sw_x, ry + 1, 5, 5, 0)
                if lbl:
                    py16.text(tr(lbl), sw_x + 8, ry + 1, 1)

    # === Jump-To-Today Button ===
    btn_x = wx + (ww - 50) // 2
    py16.rectfill(btn_x, btn_y, 50, 10, btn_color)
    py16.rect(btn_x, btn_y, 50, 10, 5)

    today_str = tr("TODAY")
    tw = len(today_str) * 4
    py16.text(today_str, btn_x + (50 - tw) // 2, btn_y + 3, 1)

    # === MODAL OVERLAY ZEICHNEN ===
    if win.get("modal_date"):
        mx = wx + win["modal_x"]
        my = wy + win["modal_y"]

        ev = win["events"].get(win["modal_date"])
        cur_color = ev["color"] if ev else None
        cur_label = ev["label"] if ev else ""

        # Schatten & Kasten
        py16.rectfill(mx + 2, my + 2, MODAL_W, MODAL_H, 0)
        py16.rectfill(mx, my, MODAL_W, MODAL_H, 6)
        py16.rect(mx, my, MODAL_W, MODAL_H, 5)

        # 4 Farb-Buttons (aktive Farbe bekommt einen hellen Rahmen)
        for i, c in enumerate(EVENT_COLORS):
            cx = mx + 4 + i * 14
            py16.rectfill(cx, my + 4, 10, 10, c)
            py16.rect(cx, my + 4, 10, 10, 0)
            if cur_color == c:
                py16.rect(cx - 1, my + 3, 12, 12, 7)

        # Label-Zeile mit < / >
        py16.rectfill(mx + 3, my + 18, 8, 11, 5)
        py16.rect(mx + 3, my + 18, 8, 11, 0)
        py16.text("<", mx + 5, my + 21, 1)

        py16.rectfill(mx + MODAL_W - 11, my + 18, 8, 11, 5)
        py16.rect(mx + MODAL_W - 11, my + 18, 8, 11, 0)
        py16.text(">", mx + MODAL_W - 9, my + 21, 1)

        disp = tr(cur_label) if cur_label else "-"
        lbl_x = mx + 12
        lbl_w = MODAL_W - 24
        dw = len(disp) * 4
        py16.text(disp, lbl_x + (lbl_w - dw) // 2, my + 21, 1)

        # Löschen-Button
        py16.rectfill(mx + 4, my + 34, MODAL_W - 8, 11, 5)
        py16.rect(mx + 4, my + 34, MODAL_W - 8, 11, 0)
        clr_str = tr("CLEAR")
        clr_w = len(clr_str) * 4
        py16.text(clr_str, mx + 4 + (MODAL_W - 8 - clr_w) // 2, my + 37, 1)

    # Clipping zurücksetzen, damit der Rest des Desktops normal zeichnet
    py16.clip()
