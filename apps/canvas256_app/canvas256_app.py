import py16
import math
import os
import glob
from collections import deque

APP = {
    "id": "canvas256",
    "name": "CANVAS 256",
    "w": 220,
    "h": 174,               # +14px Höhe für die korrekte Titelleiste
    "resizable": True,
    "min_w": 220,           # Mindestbreite, damit die Palette nicht abgeschnitten wird
    "min_h": 114,
    "icon": "canvas256_app.p16img"
}

CANVAS_W = 256
CANVAS_H = 224

def init(win):
    win["canvas"] = [0] * (CANVAS_W * CANVAS_H)
    win["tool"] = 0        # 0:Brush, 1:Fill, 2:Line, 3:Rect, 4:Circ
    win["color"] = 7
    win["brush_size"] = 1
    win["mirror"] = 0      # 0:Off, 1:X, 2:Y, 3:Both
    win["zoom"] = 1
    win["pan_x"] = 0
    win["pan_y"] = 0
    
    # State-Tracking fürs Zeichnen
    win["is_drawing"] = False
    win["sx"] = -1
    win["sy"] = -1
    win["lx"] = -1
    win["ly"] = -1
    win["preview"] = []
    win["msg"] = ""
    win["msg_timer"] = 0
    win["show_palette"] = False

# --- ALGORITHMEN ---

def _brush_offs(size):
    s = -((size - 1) // 2)
    e = size // 2
    return [(dx, dy) for dy in range(s, e + 1) for dx in range(s, e + 1)]

def _mirror_pts(x, y, mode):
    pts = [(x, y)]
    if mode in (1, 3): pts.append((CANVAS_W - 1 - x, y))
    if mode in (2, 3): pts.append((x, CANVAS_H - 1 - y))
    if mode == 3:      pts.append((CANVAS_W - 1 - x, CANVAS_H - 1 - y))
    return pts

def paint_pixel(win, x, y, c):
    for dx, dy in _brush_offs(win["brush_size"]):
        for mx, my in _mirror_pts(x + dx, y + dy, win["mirror"]):
            if 0 <= mx < CANVAS_W and 0 <= my < CANVAS_H:
                win["canvas"][my * CANVAS_W + mx] = c

def flood_fill(win, x, y, replacement_col):
    if not (0 <= x < CANVAS_W and 0 <= y < CANVAS_H): return
    target_col = win["canvas"][y * CANVAS_W + x]
    if target_col == replacement_col: return
    
    q = deque([(x, y)])
    while q:
        cx, cy = q.popleft()
        if not (0 <= cx < CANVAS_W and 0 <= cy < CANVAS_H): continue
        idx = cy * CANVAS_W + cx
        if win["canvas"][idx] == target_col:
            win["canvas"][idx] = replacement_col
            q.append((cx - 1, cy))
            q.append((cx + 1, cy))
            q.append((cx, cy - 1))
            q.append((cx, cy + 1))

def perform_fill(win, cx, cy):
    for mx, my in _mirror_pts(cx, cy, win["mirror"]):
        flood_fill(win, mx, my, win["color"])

def get_line_pixels(x0, y0, x1, y1):
    pixels = []
    dx = abs(x1 - x0)
    dy = abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx - dy
    while True:
        pixels.append((x0, y0))
        if x0 == x1 and y0 == y1: break
        e2 = 2 * err
        if e2 > -dy:
            err -= dy
            x0 += sx
        if e2 < dx:
            err += dx
            y0 += sy
    return pixels

def get_rect_pixels(x0, y0, x1, y1):
    pixels = []
    rx0, rx1 = min(x0, x1), max(x0, x1)
    ry0, ry1 = min(y0, y1), max(y0, y1)
    for x in range(rx0, rx1 + 1):
        pixels.append((x, ry0))
        pixels.append((x, ry1))
    for y in range(ry0, ry1 + 1):
        pixels.append((rx0, y))
        pixels.append((rx1, y))
    return pixels

def get_circ_pixels(xc, yc, r):
    pixels = []
    x, y = 0, r
    d = 3 - 2 * r
    while y >= x:
        pixels.extend([(xc+x, yc+y), (xc-x, yc+y), (xc+x, yc-y), (xc-x, yc-y),
                       (xc+y, yc+x), (xc-y, yc+x), (xc+y, yc-x), (xc-y, yc-x)])
        x += 1
        if d > 0:
            y -= 1
            d = d + 4 * (x - y) + 10
        else:
            d = d + 4 * x + 6
    return pixels

def clamp_pan(win, ww, wh):
    z = win["zoom"]
    vw = ww // z
    vh = (wh - 38) // z  # 38 = 14px Titel + 24px Toolbar
    win["pan_x"] = max(0, min(win["pan_x"], max(0, CANVAS_W - vw)))
    win["pan_y"] = max(0, min(win["pan_y"], max(0, CANVAS_H - vh)))

def save_p16canvas(win):
    filename = "canvas_001.p16canvas"
    for i in range(1, 1000):
        cand = f"canvas_{i:03d}.p16canvas"
        if not os.path.exists(cand):
            filename = cand
            break
    try:
        with open(filename, "w") as f:
            f.write(f"# P16CANVAS {CANVAS_W}x{CANVAS_H} v2\n")
            canvas = win["canvas"]
            for y in range(CANVAS_H):
                row = canvas[y*CANVAS_W : (y+1)*CANVAS_W]
                f.write("".join(format(c & 0xFF, "02X") for c in row) + "\n")
        win["msg"] = "SAVED!"
        win["msg_timer"] = 60
    except Exception:
        win["msg"] = "ERROR"
        win["msg_timer"] = 60

def load_p16canvas(win):
    try:
        files = glob.glob("*.p16canvas")
        if not files:
            win["msg"] = "NO FILE"
            win["msg_timer"] = 60
            return
        files.sort(key=os.path.getmtime, reverse=True)
        with open(files[0], "r") as f:
            lines = f.readlines()
        
        new_canvas = [0] * (CANVAS_W * CANVAS_H)
        y = 0
        for line in lines:
            line = line.strip()
            if not line or line.startswith("#"): continue
            if y >= CANVAS_H: break
            
            if len(line) == CANVAS_W * 2:
                row = [int(line[i:i+2], 16) for i in range(0, len(line), 2)]
            elif len(line) == CANVAS_W:
                row = [int(c, 16) for c in line]
            else: continue
            
            new_canvas[y*CANVAS_W : (y+1)*CANVAS_W] = row
            y += 1
        if y > 0:
            win["canvas"] = new_canvas
            win["msg"] = "LOADED!"
            win["msg_timer"] = 60
    except Exception:
        win["msg"] = "ERROR"
        win["msg_timer"] = 60

# --- OS-LOGIK ---

def finish_stroke(win):
    """Beendet einen laufenden Strich/Form und committet die Vorschau.
    Wird aufgerufen, sobald die Maustaste losgelassen wird – unabhaengig
    davon, wo der Cursor steht (Canvas, Toolbar oder Titelleiste)."""
    win["is_drawing"] = False
    if win["tool"] in (2, 3, 4) and win["preview"]:
        for px, py_ in win["preview"]:
            paint_pixel(win, px, py_, win["color"])
        py16.tone(440, 20, py16.WAVE_SQUARE)
    win["preview"] = []

def update(win, lx, ly, mp, msp, mh):
    if win.get("msg_timer", 0) > 0:
        win["msg_timer"] -= 1

    # Maustaste losgelassen? Laufenden Strich/Form IMMER sauber beenden –
    # auch wenn der Cursor dabei ueber Toolbar/Titelleiste gezogen wurde.
    # Verhindert "haengende" Formen, die sonst nie committen.
    if win["is_drawing"] and not mh:
        finish_stroke(win)
        return

    # Titelleiste des OS (0 bis 13) ignorieren!
    if ly < 14:
        return
        
    # Wenn die große Farbpalette offen ist, fange alle Klicks ab
    if win.get("show_palette"):
        if mp:
            if 20 <= lx < 148 and 40 <= ly < 168:
                c_x = (lx - 20) // 8
                c_y = (ly - 40) // 8
                win["color"] = c_y * 16 + c_x
                py16.tone(500, 10, py16.WAVE_SQUARE)
            win["show_palette"] = False
        return

    # App-eigene Toolbar (14 bis 37)
    if ly < 38:
        if mp:
            # Reihe 1: Werkzeuge (y: 16 bis 26)
            if 16 <= ly <= 26:
                for i in range(5):
                    if 4 + i*14 <= lx <= 16 + i*14:
                        win["tool"] = i; py16.tone(400, 10, py16.WAVE_SQUARE)
                
                # Basis-Farbpalette (0-15)
                for i in range(16):
                    if 80 + i*8 <= lx <= 88 + i*8:
                        win["color"] = i; py16.tone(500, 10, py16.WAVE_SQUARE)
                
                # Palette-Erweitern-Button (PAL)
                if 208 <= lx <= 219:
                    win["show_palette"] = True
                    py16.tone(600, 15, py16.WAVE_SQUARE)
            
            # Reihe 2: Modi (y: 27 bis 37)
            elif 27 <= ly <= 37:
                # Pinselgrößen
                for i in range(4):
                    if 4 + i*14 <= lx <= 16 + i*14:
                        win["brush_size"] = i + 1; py16.tone(450, 10, py16.WAVE_SQUARE)
                
                # Spiegelung
                for i in range(4):
                    if 70 + i*14 <= lx <= 82 + i*14:
                        win["mirror"] = i; py16.tone(450, 10, py16.WAVE_SQUARE)
                
                # Zoom
                for i in range(3):
                    if 140 + i*14 <= lx <= 152 + i*14:
                        if i == 0 and win["zoom"] > 1: win["zoom"] -= 1
                        elif i == 1: win["zoom"] = 1
                        elif i == 2 and win["zoom"] < 8: win["zoom"] += 1
                        clamp_pan(win, win["w"], win["h"])
                        py16.tone(350 + i*50, 10, py16.WAVE_SQUARE)
                
                # Save & Load
                if 186 <= lx <= 200:
                    save_p16canvas(win)
                    py16.tone(600, 15, py16.WAVE_SQUARE)
                elif 204 <= lx <= 218:
                    load_p16canvas(win)
                    py16.tone(660, 15, py16.WAVE_SQUARE)
        return  # Eingaben im UI blockieren den Canvas

    # Canvas-Bereich (Pixel-Mapping)
    z = win["zoom"]
    cx = win["pan_x"] + lx // z
    cy = win["pan_y"] + (ly - 38) // z

    # Pan-Zentrierung via Rechtsklick
    if msp:
        vw, vh = win["w"] // z, (win["h"] - 38) // z
        win["pan_x"] = cx - vw // 2
        win["pan_y"] = cy - vh // 2
        clamp_pan(win, win["w"], win["h"])
        if not win.get("pan_hint_shown"):
            win["msg"] = "PAN"
            win["msg_timer"] = 30
            win["pan_hint_shown"] = True
        return

    # Zeichen-Logik
    if mp:
        win["is_drawing"] = True
        win["sx"], win["sy"] = cx, cy
        win["lx"], win["ly"] = cx, cy
        if win["tool"] == 0:
            paint_pixel(win, cx, cy, win["color"])
        elif win["tool"] == 1:
            perform_fill(win, cx, cy)
            py16.tone(330, 30, py16.WAVE_TRIANGLE)

    elif mh and win["is_drawing"]:
        if win["tool"] == 0 and (cx != win["lx"] or cy != win["ly"]):
            for px, py_ in get_line_pixels(win["lx"], win["ly"], cx, cy):
                paint_pixel(win, px, py_, win["color"])
            win["lx"], win["ly"] = cx, cy
        elif win["tool"] in (2, 3, 4):
            # Form-Vorschau aktualisieren
            if win["tool"] == 2: win["preview"] = get_line_pixels(win["sx"], win["sy"], cx, cy)
            elif win["tool"] == 3: win["preview"] = get_rect_pixels(win["sx"], win["sy"], cx, cy)
            elif win["tool"] == 4:
                r = int(math.sqrt((cx - win["sx"])**2 + (cy - win["sy"])**2))
                win["preview"] = get_circ_pixels(win["sx"], win["sy"], r)

def draw(win, wx, wy, ww, wh, is_active):
    # UI Hintergrund (Startet jetzt bei wy + 14 unter der OS-Titelleiste)
    py16.rectfill(wx, wy + 14, ww, 24, 5)
    py16.rect(wx, wy + 14, ww, 24, 0)

    # 1. Werkzeuge (B=Brush, F=Fill, L=Line, R=Rect, C=Circ)
    t_names = ["B", "F", "L", "R", "C"]
    for i in range(5):
        bg = 11 if win["tool"] == i else 6
        py16.rectfill(wx + 4 + i*14, wy + 16, 12, 10, bg)
        py16.text(t_names[i], wx + 8 + i*14, wy + 19, 1 if win["tool"]==i else 7)

    # 2. Farbpalette (0-15)
    for i in range(16):
        py16.rectfill(wx + 80 + i*8, wy + 16, 8, 10, i)
        if win["color"] == i:
            py16.rect(wx + 80 + i*8, wy + 16, 8, 10, 7 if i < 8 else 0)

    # P-Button (Öffnet alle 256 Farben)
    py16.rectfill(wx + 208, wy + 16, 12, 10, 8)
    py16.rect(wx + 208, wy + 16, 12, 10, 0)
    py16.text("P", wx + 212, wy + 19, 1)

    # 3. Pinselgrößen (1-4)
    for i in range(4):
        bg = 11 if win["brush_size"] == i + 1 else 6
        py16.rectfill(wx + 4 + i*14, wy + 27, 12, 10, bg)
        py16.text(str(i+1), wx + 8 + i*14, wy + 30, 1 if win["brush_size"]==i+1 else 7)

    # 4. Spiegelung (-, X, Y, +)
    m_names = ["-", "X", "Y", "+"]
    for i in range(4):
        bg = 11 if win["mirror"] == i else 6
        py16.rectfill(wx + 70 + i*14, wy + 27, 12, 10, bg)
        py16.text(m_names[i], wx + 74 + i*14, wy + 30, 1 if win["mirror"]==i else 7)

    # 5. Zoom Steuerung (-, 1, +)
    z_names = ["-", "1", "+"]
    for i in range(3):
        py16.rectfill(wx + 140 + i*14, wy + 27, 12, 10, 6)
        py16.text(z_names[i], wx + 144 + i*14, wy + 30, 7)
    
    # 6. Save & Load Buttons
    py16.rectfill(wx + 186, wy + 27, 14, 10, 10)
    py16.rect(wx + 186, wy + 27, 14, 10, 0)
    py16.text("SV", wx + 188, wy + 30, 1)
    
    py16.rectfill(wx + 204, wy + 27, 14, 10, 9)
    py16.rect(wx + 204, wy + 27, 14, 10, 0)
    py16.text("LD", wx + 206, wy + 30, 1)

    # Status-Nachricht (z.B. SAVED!)
    if win.get("msg_timer", 0) > 0:
        py16.text(win["msg"], wx + 186, wy + 19, 8)

    # --- RENDER ENGINE FÜR CANVAS (mit Clipping & Run-Length) ---
    z = win["zoom"]
    pan_x, pan_y = win["pan_x"], win["pan_y"]
    canvas = win["canvas"]
    cw, ch = ww // z, (wh - 38) // z

    # Clip auf exakten Canvas-Zeichenbereich beschränken (14 Titel + 24 UI = 38 Offset)
    py16.clip(wx, wy + 38, ww, wh - 38)
    py16.rectfill(wx, wy + 38, ww, wh - 38, 0)  # Hintergrund sichern

    # Optimiertes Run-Length-Rendering
    for vy in range(ch + 2):
        cy = pan_y + vy
        if cy < 0 or cy >= CANVAS_H: continue
        row_base = cy * CANVAS_W
        sy0 = wy + 38 + vy * z
        vx = 0
        while vx <= cw + 1:
            cxp = pan_x + vx
            if cxp < 0 or cxp >= CANVAS_W:
                vx += 1; continue
            c = canvas[row_base + cxp]
            if c == 0:
                vx += 1; continue
                
            run_end = vx + 1
            while run_end <= cw + 1 and (pan_x + run_end) < CANVAS_W and canvas[row_base + pan_x + run_end] == c:
                run_end += 1
                
            sx0 = wx + vx * z
            w_ = (run_end - vx) * z
            if z == 1 and w_ == 1:
                py16.pset(sx0, sy0, c)
            else:
                py16.rectfill(sx0, sy0, w_, z, c)
            vx = run_end

    # Zeichne Form-Vorschau (Linien, Rechtecke, Kreise)
    if win.get("is_drawing") and win["tool"] in (2, 3, 4) and win["preview"]:
        py16.blend_mode("alpha", alpha=180)
        cells = set()
        offs = _brush_offs(win["brush_size"])
        # Pixel + Brush Size + Mirroring expandieren
        for px, py_ in win["preview"]:
            for dx, dy in offs:
                for mx, my in _mirror_pts(px + dx, py_ + dy, win["mirror"]):
                    if 0 <= mx < CANVAS_W and 0 <= my < CANVAS_H:
                        cells.add((mx, my))
                        
        for px, py_ in cells:
            sx0 = wx + (px - pan_x) * z
            sy0 = wy + 38 + (py_ - pan_y) * z
            if wx <= sx0 < wx + ww and wy + 38 <= sy0 < wy + wh:
                if z == 1: py16.pset(sx0, sy0, win["color"])
                else: py16.rectfill(sx0, sy0, z, z, win["color"])
        py16.blend_mode("normal")

    # Clip zurücksetzen für restliches OS
    py16.clip()

    # Modal: Große 256-Farbpalette über allem zeichnen, wenn aktiv
    if win.get("show_palette"):
        py16.rectfill(wx + 16, wy + 36, 136, 136, 1)
        py16.rect(wx + 16, wy + 36, 136, 136, 0)
        for i in range(256):
            cx = i % 16
            cy = i // 16
            px = wx + 20 + cx * 8
            py_ = wy + 40 + cy * 8
            py16.rectfill(px, py_, 8, 8, i)
            if win["color"] == i:
                py16.rect(px, py_, 8, 8, 7 if i < 8 else 0)
                py16.rect(px + 1, py_ + 1, 6, 6, 1 if i < 8 else 7)
