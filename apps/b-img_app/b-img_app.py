# apps/bimg.py
APP = {
    "id": "b-img",
    "name": "B-IMG",
    "w": 160,
    "h": 190,
    "resizable": False
}

# 3x5 Pixel Font für das Text-Werkzeug (A-Z, 0-9)
FONT_3x5 = {
    'A': "010101111101101", 'B': "110101110101110", 'C': "011100100100011",
    'D': "110101101101110", 'E': "111100110100111", 'F': "111100110100100",
    'G': "011100101101011", 'H': "101101111101101", 'I': "111010010010111",
    'J': "111001001101011", 'K': "101110100110101", 'L': "100100100100111",
    'M': "101111101101101", 'N': "110101101101101", 'O': "010101101101010",
    'P': "110101110100100", 'Q': "010101101101011", 'R': "110101110101101",
    'S': "011100010001110", 'T': "111010010010010", 'U': "101101101101011",
    'V': "101101101010010", 'W': "101101101111101", 'X': "101101010101101",
    'Y': "101101010010010", 'Z': "111001010100111",
    '0': "010101101101010", '1': "010110010010111", '2': "110001010100111",
    '3': "110001010001110", '4': "101101111001001", '5': "111100110001110",
    '6': "011100111101011", '7': "111001010100100", '8': "010101010101010",
    '9': "010101011001010"
}
CHAR_LIST = list(FONT_3x5.keys())

UNDO_LIMIT = 50  # maximale Tiefe der Historie


def init(win):
    """Initialisierung des Window-Zustands"""
    win["pixels"] = [[7 for _ in range(16)] for _ in range(16)]
    win["color"] = 0
    win["tool"] = "STIFT"
    win["scale"] = 8
    win["canvas_x"] = 16
    win["canvas_y"] = 18
    win["msg"] = ""
    win["msg_col"] = 7          # FIX: war vorher nie initialisiert
    win["msg_timer"] = 0
    win["text_idx"] = 0         # Start-Buchstabe für das Text-Werkzeug

    # Undo/Redo-Historie (Listen von Raster-Schnappschüssen)
    win["undo"] = []
    win["redo"] = []

    # Laden: Liste vorhandener .p16img-Dateien + Index zum Durchblättern
    win["files"] = []
    win["load_idx"] = 0
    _refresh_files(win)

    # Dynamische Werkzeugliste (ID, Label)
    win["tools"] = [
        ("STIFT", "ST"),
        ("EIMER", "EI"),
        ("RAD", "RA"),
        ("PIPETTE", "PI"),
        ("LINIE", "LI"),
        ("KREIS", "KR"),
        ("RECHTECK", "RE"),
        ("TEXT", "TE")
    ]


# ---------------------------------------------------------------------------
#  Kleine Helfer
# ---------------------------------------------------------------------------

def _msg(win, text, col, timer):
    """Setzt eine Statusnachricht (vermeidet die alte Dreifach-Wiederholung)."""
    win["msg"] = text
    win["msg_col"] = col
    win["msg_timer"] = timer


def _layout(win):
    """Berechnet ALLE UI-Positionen zentral (lokale Koordinaten).
    Wird in update() und draw() identisch benutzt -> kein Auseinanderdriften."""
    cx, cy, scale = win["canvas_x"], win["canvas_y"], win["scale"]
    n_tools = len(win["tools"])
    z_plus_y = 18 + n_tools * 12 + 6
    pal_y = cy + 16 * scale + 4
    btn_y = pal_y + 12
    return {
        "cx": cx, "cy": cy, "scale": scale,
        "z_plus_y": z_plus_y,
        "z_minus_y": z_plus_y + 12,
        "pal_y": pal_y,
        "btn_y": btn_y,
        "btn_y2": btn_y + 12,
    }


def _buttons(L):
    """Definiert die Buttons der beiden unteren Reihen: (key, x, y, w, label).
    Eine Quelle der Wahrheit für Hit-Test (update) und Zeichnen (draw)."""
    by, by2 = L["btn_y"], L["btn_y2"]
    return [
        ("save",  16, by,  44, "SPEICH"),
        ("load",  62, by,  36, "LADEN"),
        ("clear", 100, by, 34, "LEER"),
        ("undo",  16, by2, 40, "UNDO"),
        ("redo",  60, by2, 40, "REDO"),
    ]


def _push_undo(win):
    """Aktuellen Rasterzustand auf den Undo-Stack legen, Redo verwerfen."""
    win["undo"].append([row[:] for row in win["pixels"]])
    if len(win["undo"]) > UNDO_LIMIT:
        win["undo"].pop(0)
    win["redo"].clear()


def _undo(win):
    if win["undo"]:
        win["redo"].append([row[:] for row in win["pixels"]])
        win["pixels"] = win["undo"].pop()
        _msg(win, "UNDO", 10, 45)


def _redo(win):
    if win["redo"]:
        win["undo"].append([row[:] for row in win["pixels"]])
        win["pixels"] = win["redo"].pop()
        _msg(win, "REDO", 10, 45)


def _refresh_files(win):
    """Liste der vorhandenen .p16img-Dateien im apps/-Ordner aktualisieren."""
    import os
    try:
        files = sorted(f for f in os.listdir("apps") if f.endswith(".p16img"))
    except Exception:
        files = []
    win["files"] = files
    if win.get("load_idx", 0) >= len(files):
        win["load_idx"] = 0


# ---------------------------------------------------------------------------
#  Speichern / Laden
# ---------------------------------------------------------------------------

def save_image(win):
    """Speichert das 16x16 Raster regelkonform als 32x32 .p16img.
    FIX: nutzt einen freien, fortlaufenden Dateinamen statt immer zu
    überschreiben (bimg_001.p16img, bimg_002.p16img, ...)."""
    try:
        import os
        os.makedirs("apps", exist_ok=True)

        n = 1
        while True:
            path = os.path.join("apps", "bimg_%03d.p16img" % n)
            if not os.path.exists(path):
                break
            n += 1

        with open(path, "w") as f:
            f.write("# P16IMG 32x32\n")
            for row in win["pixels"]:
                line = "".join("%X%X" % (c, c) for c in row)
                f.write(line + "\n")
                f.write(line + "\n")

        _msg(win, "OK %03d" % n, 11, 120)   # Grün
        _refresh_files(win)
    except Exception:
        _msg(win, "ERR!", 8, 120)           # Rot


def load_image(path):
    """Liest eine .p16img-Datei und liefert ein 16x16-Raster (Palettenindizes)
    zurück, oder None bei Fehler. Funktioniert sowohl mit dem hier
    geschriebenen 32x32-Format als auch mit echten 16x16-Bildern, indem es
    bei Bedarf herunterskaliert."""
    try:
        with open(path) as f:
            rows = [ln.strip() for ln in f
                    if ln.strip() and not ln.lstrip().startswith("#")]
        if not rows:
            return None

        h = len(rows)
        px_w = len(rows[0])
        step_y = max(1, h // 16)
        step_x = max(1, px_w // 16)

        grid = [[7] * 16 for _ in range(16)]
        for y in range(16):
            row = rows[min(y * step_y, h - 1)]
            for x in range(16):
                ch = row[min(x * step_x, len(row) - 1)]
                try:
                    grid[y][x] = int(ch, 16) & 0xF
                except ValueError:
                    grid[y][x] = 7
        return grid
    except Exception:
        return None


def _do_load(win):
    """Lädt die nächste verfügbare .p16img-Datei und blättert weiter."""
    import os
    _refresh_files(win)
    files = win.get("files", [])
    if not files:
        _msg(win, "KEINE", 8, 90)
        return

    idx = win.get("load_idx", 0) % len(files)
    name = files[idx]
    grid = load_image(os.path.join("apps", name))
    if grid is None:
        _msg(win, "ERR!", 8, 120)
        return

    _push_undo(win)                 # Laden ist rückgängig machbar
    win["pixels"] = grid
    win["load_idx"] = (idx + 1) % len(files)
    _msg(win, name.replace(".p16img", "")[:8], 11, 120)


# ---------------------------------------------------------------------------
#  Zeichen-Primitiven (unverändert)
# ---------------------------------------------------------------------------

def flood_fill(pixels, sx, sy, fill_color):
    """Füllt einen zusammenhängenden Bereich mit der ausgewählten Farbe"""
    target_color = pixels[sy][sx]
    if target_color == fill_color:
        return
    stack = [(sx, sy)]
    while stack:
        x, y = stack.pop()
        if pixels[y][x] == target_color:
            pixels[y][x] = fill_color
            if x > 0: stack.append((x - 1, y))
            if x < 15: stack.append((x + 1, y))
            if y > 0: stack.append((x, y - 1))
            if y < 15: stack.append((x, y + 1))


def draw_line(pixels, x0, y0, x1, y1, col):
    """Bresenham-Linienalgorithmus"""
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        if 0 <= x0 < 16 and 0 <= y0 < 16:
            pixels[y0][x0] = col
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def draw_rect(pixels, x0, y0, x1, y1, col):
    """Zeichnet die Kontur eines Rechtecks"""
    x_min, x_max = min(x0, x1), max(x0, x1)
    y_min, y_max = min(y0, y1), max(y0, y1)
    for x in range(x_min, x_max + 1):
        if 0 <= x < 16:
            if 0 <= y_min < 16: pixels[y_min][x] = col
            if 0 <= y_max < 16: pixels[y_max][x] = col
    for y in range(y_min, y_max + 1):
        if 0 <= y < 16:
            if 0 <= x_min < 16: pixels[y][x_min] = col
            if 0 <= x_max < 16: pixels[y][x_max] = col


def draw_circle(pixels, x0, y0, x1, y1, col):
    """Bresenham-Kreisalgorithmus (Radius aus Distanz x1,y1 zum Start)"""
    r = int(((x1 - x0) ** 2 + (y1 - y0) ** 2) ** 0.5)
    x = r
    y = 0
    err = 0
    while x >= y:
        points = [(x0+x, y0+y), (x0+y, y0+x), (x0-y, y0+x), (x0-x, y0+y),
                  (x0-x, y0-y), (x0-y, y0-x), (x0+y, y0-x), (x0+x, y0-y)]
        for px, py in points:
            if 0 <= px < 16 and 0 <= py < 16:
                pixels[py][px] = col
        y += 1
        err += 1 + 2 * y
        if 2 * (err - x) + 1 > 0:
            x -= 1
            err += 1 - 2 * x


# ---------------------------------------------------------------------------
#  Eingabe
# ---------------------------------------------------------------------------

def update(win, lx, ly, mp, msp, mh):
    """Eingabelogik für Klicks und Zeichenaktionen"""
    # FIX: Drag-Zustand zurücksetzen, sobald die Maus nicht mehr gehalten wird.
    # Verhindert, dass ein von außerhalb ins Canvas gezogener Strich einen
    # veralteten Startpunkt der letzten Form benutzt.
    if not mh:
        win.pop("drag_backup", None)
        win.pop("drag_start", None)

    if win["msg_timer"] > 0:
        win["msg_timer"] -= 1
        if win["msg_timer"] <= 0:
            win["msg"] = ""

    L = _layout(win)
    cx, cy, scale = L["cx"], L["cy"], L["scale"]

    # --- 0. Hover Test (Wo ist die Maus auf dem Raster?) ---
    win["hover_x"], win["hover_y"] = -1, -1
    if cx <= lx < cx + 16 * scale and cy <= ly < cy + 16 * scale:
        win["hover_x"] = int((lx - cx) // scale)
        win["hover_y"] = int((ly - cy) // scale)

    # --- 1. Hit-Test: Werkzeugleiste ---
    if mp and 2 <= lx < 14:
        for idx, (t_id, t_label) in enumerate(win["tools"]):
            t_y = 18 + idx * 12
            if t_y <= ly < t_y + 10:
                win["tool"] = t_id

        # Zoom Buttons (unterhalb der Werkzeuge)
        if L["z_plus_y"] <= ly < L["z_plus_y"] + 10:
            win["scale"] = min(10, win["scale"] + 1)
        elif L["z_minus_y"] <= ly < L["z_minus_y"] + 10:
            win["scale"] = max(2, win["scale"] - 1)

    # --- 2. GLOBALER SHORTCUT: Rechtsklick = Pipette ---
    if msp and win["hover_x"] != -1:
        if win["tool"] == "TEXT":
            # Rechtsklick schaltet beim Text-Werkzeug den Buchstaben durch
            win["text_idx"] = (win.get("text_idx", 0) + 1) % len(CHAR_LIST)
        else:
            win["color"] = win["pixels"][win["hover_y"]][win["hover_x"]]
            if win["tool"] == "PIPETTE":
                win["tool"] = "STIFT"

    # --- 3. Hit-Test: Zeichnen auf dem Canvas ---
    if (mp or mh) and win["hover_x"] != -1:
        grid_x, grid_y = win["hover_x"], win["hover_y"]

        # Beim frischen Klick: Backup + Undo-Schnappschuss
        if mp:
            win["drag_start"] = (grid_x, grid_y)
            win["drag_backup"] = [row[:] for row in win["pixels"]]
            if win["tool"] != "PIPETTE":
                _push_undo(win)

        # Falls Backup fehlt (Maus von außen ins Fenster gezogen)
        if "drag_backup" not in win:
            win["drag_backup"] = [row[:] for row in win["pixels"]]
            win["drag_start"] = (grid_x, grid_y)
            if win["tool"] != "PIPETTE":
                _push_undo(win)

        # Form-Werkzeuge (Live-Vorschau aus Backup)
        if win["tool"] in ("LINIE", "KREIS", "RECHTECK"):
            win["pixels"] = [row[:] for row in win["drag_backup"]]
            sx, sy = win["drag_start"]
            if win["tool"] == "LINIE":
                draw_line(win["pixels"], sx, sy, grid_x, grid_y, win["color"])
            elif win["tool"] == "RECHTECK":
                draw_rect(win["pixels"], sx, sy, grid_x, grid_y, win["color"])
            elif win["tool"] == "KREIS":
                draw_circle(win["pixels"], sx, sy, grid_x, grid_y, win["color"])

        # Standard-Werkzeuge (Pixelgenau)
        else:
            if win["tool"] == "STIFT":
                win["pixels"][grid_y][grid_x] = win["color"]
            elif win["tool"] == "RAD":
                win["pixels"][grid_y][grid_x] = 7
            elif win["tool"] == "EIMER" and mp:
                flood_fill(win["pixels"], grid_x, grid_y, win["color"])
            elif win["tool"] == "PIPETTE" and mp:
                win["color"] = win["pixels"][grid_y][grid_x]
                win["tool"] = "STIFT"
            elif win["tool"] == "TEXT" and mp:
                char_str = FONT_3x5[CHAR_LIST[win.get("text_idx", 0)]]
                for i, bit in enumerate(char_str):
                    if bit == '1':
                        px = grid_x + (i % 3)
                        py = grid_y + (i // 3)
                        if 0 <= px < 16 and 0 <= py < 16:
                            win["pixels"][py][px] = win["color"]

    # --- 4. Hit-Test: Farbauswahl ---
    if mp and 16 <= lx < 144 and L["pal_y"] <= ly < L["pal_y"] + 8:
        win["color"] = int((lx - 16) // 8)

    # --- 5. Hit-Test: UI Buttons (untere Reihen) ---
    if mp:
        for key, bx, by, bw, _label in _buttons(L):
            if bx <= lx < bx + bw and by <= ly < by + 10:
                if key == "save":
                    save_image(win)
                elif key == "load":
                    _do_load(win)
                elif key == "clear":
                    _push_undo(win)
                    win["pixels"] = [[7 for _ in range(16)] for _ in range(16)]
                    _msg(win, "LEER", 10, 60)
                elif key == "undo":
                    _undo(win)
                elif key == "redo":
                    _redo(win)
                break

    # --- 6. Fenstergröße dynamisch anpassen ---
    L = _layout(win)  # Scale kann sich oben geändert haben
    win["w"] = max(160, cx + 16 * win["scale"] + 16)
    win["h"] = max(190, L["btn_y2"] + 14)


# ---------------------------------------------------------------------------
#  Zeichnen
# ---------------------------------------------------------------------------

def draw(win, wx, wy, ww, wh, active):
    """Rendert die Benutzeroberfläche und das Canvas"""
    import py16

    # Auf das Fenster begrenzen, damit nichts über den Rand malt
    py16.clip(wx, wy + 14, ww, wh - 14)

    L = _layout(win)
    cx = wx + L["cx"]
    cy = wy + L["cy"]
    scale = L["scale"]

    # Hintergrund
    py16.rectfill(wx, wy + 14, ww, wh - 14, 6)
    py16.rect(cx - 1, cy - 1, 16 * scale + 2, 16 * scale + 2, 5)

    # Werkzeuge
    for idx, (t_id, t_label) in enumerate(win["tools"]):
        t_y = wy + 18 + idx * 12
        bg_col = 13 if win["tool"] == t_id else 5
        text_col = 7 if win["tool"] == t_id else 6
        py16.rectfill(wx + 2, t_y, 12, 10, bg_col)
        py16.rect(wx + 2, t_y, 12, 10, 0)
        py16.text(t_label, wx + 4, t_y + 3, text_col)

    # Zoom Buttons (+ und -)
    z_plus_y = wy + L["z_plus_y"]
    py16.rectfill(wx + 2, z_plus_y, 12, 10, 5)
    py16.rect(wx + 2, z_plus_y, 12, 10, 0)
    py16.text("+", wx + 5, z_plus_y + 3, 7)

    z_minus_y = wy + L["z_minus_y"]
    py16.rectfill(wx + 2, z_minus_y, 12, 10, 5)
    py16.rect(wx + 2, z_minus_y, 12, 10, 0)
    py16.text("-", wx + 5, z_minus_y + 3, 7)

    # Canvas
    for y in range(16):
        for x in range(16):
            c = win["pixels"][y][x]
            px = cx + x * scale
            py = cy + y * scale
            if c == 7:
                cb_col = 6 if (x + y) % 2 == 0 else 5
                py16.rectfill(px, py, scale, scale, cb_col)
            else:
                py16.rectfill(px, py, scale, scale, c)

    # Hover-Cursor bzw. Text-Vorschau
    hx, hy = win.get("hover_x", -1), win.get("hover_y", -1)
    if hx != -1 and hy != -1:
        if win["tool"] == "TEXT":
            char_str = FONT_3x5[CHAR_LIST[win.get("text_idx", 0)]]
            for i, bit in enumerate(char_str):
                if bit == '1':
                    dx, dy = i % 3, i // 3
                    if 0 <= hx + dx < 16 and 0 <= hy + dy < 16:
                        px = cx + (hx + dx) * scale
                        py = cy + (hy + dy) * scale
                        py16.rectfill(px, py, scale, scale, win["color"])
                        py16.rect(px, py, scale, scale, 7)
        else:
            py16.rect(cx + hx * scale, cy + hy * scale, scale, scale, 7)

    # Farbpalette
    pal_y = wy + L["pal_y"]
    py16.rect(wx + 15, pal_y - 1, 128 + 2, 10, 0)
    for i in range(16):
        pyx = wx + 16 + i * 8
        py16.rectfill(pyx, pal_y, 8, 8, i)
        if i == win["color"]:
            py16.rect(pyx, pal_y, 8, 8, 7)
            py16.rect(pyx + 1, pal_y + 1, 6, 6, 0)

    # Untere Buttons (SPEICH / LADEN / LEER / UNDO / REDO)
    for key, bx, by, bw, label in _buttons(L):
        enabled = True
        if key == "undo":
            enabled = bool(win["undo"])
        elif key == "redo":
            enabled = bool(win["redo"])
        bg = 5 if enabled else 1
        fg = 7 if enabled else 6
        py16.rectfill(wx + bx, wy + by, bw, 10, bg)
        py16.rect(wx + bx, wy + by, bw, 10, 0)
        py16.text(label, wx + bx + 3, wy + by + 3, fg)

    # Statuszeile rechts neben UNDO/REDO
    info_x = wx + 104
    info_y = wy + L["btn_y2"] + 3
    if win["tool"] == "TEXT":
        py16.text("TXT:" + CHAR_LIST[win.get("text_idx", 0)], info_x, info_y, 11)
    elif win["msg"]:
        py16.text(win["msg"], info_x, info_y, win["msg_col"])

    py16.clip()  # Clipping zurücksetzen
