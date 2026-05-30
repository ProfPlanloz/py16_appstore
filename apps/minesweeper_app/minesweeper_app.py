import random
import json
import os
import py16

# Konstante für die Höhe der OS-Fensterleiste
TITLE_H = 14

APP = {
    "id": "minesweeper",
    "name": "MINEN",
    "w": 204, 
    "h": 176 + TITLE_H, # Höhe angepasst, um Platz für die OS-Leiste zu machen
    "resizable": False,
    "icon": "minesweeper_app.p16img"
}

CONFIGS = [
    {"c": 8,  "r": 8,  "m": 10}, # L = Leicht
    {"c": 12, "r": 12, "m": 22}, # M = Mittel
    {"c": 16, "r": 12, "m": 35}  # S = Schwer
]

CELL_SIZE = 12
# Das Grid rutscht um die Höhe der Titlebar nach unten
OFFSET_Y = 24 + TITLE_H 
SAVE_PATH = "minesweeper_save.json"

# Gemeinsames UI-Button-Layout: wird von update() (Hit-Test) UND draw()
# (Zeichnen) genutzt, damit beide nicht mehr von Hand synchron gehalten
# werden müssen.
NEW_BTN = ("neu", 4, 24)  # (label, x-offset, width)
# Schwierigkeits-Buttons: (label, x-offset, width, diff_index, tone_freq)
DIFF_BUTTONS = [
    ("L", 32, 12, 0, 500),
    ("M", 48, 12, 1, 600),
    ("S", 64, 12, 2, 700),
]

def load_highscores(win):
    """Lädt die Bestzeiten aus dem Dateisystem."""
    win["highscores"] = [999, 999, 999]
    if os.path.isfile(SAVE_PATH):
        try:
            with open(SAVE_PATH, "r") as f:
                win["highscores"] = json.load(f).get("scores", [999, 999, 999])
        except Exception: 
            pass

def save_highscore(win):
    """Speichert die Bestzeit, falls unterboten."""
    diff = win.get("diff", 0)
    seconds = win["frames"] // 60
    if seconds < win["highscores"][diff]:
        win["highscores"][diff] = seconds
        try:
            with open(SAVE_PATH, "w") as f:
                json.dump({"scores": win["highscores"]}, f)
        except Exception: 
            pass

def reset_game(win):
    diff = win.get("diff", 0)
    cfg = CONFIGS[diff]
    
    win["cols"] = cfg["c"]
    win["rows"] = cfg["r"]
    win["total_mines"] = cfg["m"]
    win["mines_left"] = cfg["m"]
    win["grid"] = [{"mine": False, "rev": False, "flag": False, "adj": 0} for _ in range(cfg["c"] * cfg["r"])]
    win["game_over"] = False
    win["won"] = False
    win["first_click"] = True
    win["btn_down"] = None
    win["frames"] = 0
    win["timer_active"] = False
    py16.particles_clear()

def init(win):
    win["diff"] = 0
    load_highscores(win)
    reset_game(win)

def place_mines(win, safe_x, safe_y):
    mines_placed = 0
    grid = win["grid"]
    cols, rows = win["cols"], win["rows"]
    
    while mines_placed < win["total_mines"]:
        idx = random.randint(0, cols * rows - 1)
        cx, cy = idx % cols, idx // cols
        
        if not grid[idx]["mine"] and (abs(cx - safe_x) > 1 or abs(cy - safe_y) > 1):
            grid[idx]["mine"] = True
            mines_placed += 1
            
    for cy in range(rows):
        for cx in range(cols):
            idx = cy * cols + cx
            if grid[idx]["mine"]: continue
            
            count = 0
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < cols and 0 <= ny < rows and grid[ny * cols + nx]["mine"]:
                        count += 1
            grid[idx]["adj"] = count

def check_win(win):
    cols, rows = win["cols"], win["rows"]
    rev_count = sum(1 for c in win["grid"] if c["rev"])
    if rev_count == (cols * rows) - win["total_mines"]:
        win["won"] = True
        win["game_over"] = True
        win["timer_active"] = False
        win["mines_left"] = 0
        for c in win["grid"]:
            if c["mine"]: c["flag"] = True
        save_highscore(win)
        py16.tone(600, 200, py16.WAVE_TRIANGLE)
        # Konfetti in der Mitte des Fensters (Partikel nutzen Bildschirm-Koords)
        py16.burst_confetti(win["x"] + win["w"] // 2, win["y"] + win["h"] // 2, count=50)

def reveal(win, start_cx, start_cy):
    stack = [(start_cx, start_cy)]
    grid = win["grid"]
    cols, rows = win["cols"], win["rows"]
    
    while stack:
        cx, cy = stack.pop()
        if not (0 <= cx < cols and 0 <= cy < rows): continue
            
        idx = cy * cols + cx
        cell = grid[idx]
        
        if cell["rev"] or cell["flag"]: continue
        
        cell["rev"] = True
        
        if cell["mine"]:
            win["game_over"] = True
            win["timer_active"] = False
            for c in grid:
                if c["mine"] and not c["flag"]: c["rev"] = True
            py16.tone(150, 300, py16.WAVE_NOISE)
            # Explosion berechnen (mit TITLE_H Offset)
            ox = (win["w"] - cols * CELL_SIZE) // 2
            abs_x = win["x"] + ox + cx * CELL_SIZE + CELL_SIZE//2
            abs_y = win["y"] + OFFSET_Y + cy * CELL_SIZE + CELL_SIZE//2
            py16.burst_explosion(abs_x, abs_y, color=8)
            return
            
        if cell["adj"] == 0:
            for dy in [-1, 0, 1]:
                for dx in [-1, 0, 1]:
                    stack.append((cx + dx, cy + dy))

def chord(win, cx, cy):
    """Deckt umliegende Felder auf (Chording)."""
    grid = win["grid"]
    cols, rows = win["cols"], win["rows"]
    cell = grid[cy * cols + cx]
    
    if not cell["rev"] or cell["adj"] == 0:
        return

    flag_count = 0
    neighbors = []
    for dy in [-1, 0, 1]:
        for dx in [-1, 0, 1]:
            nx, ny = cx + dx, cy + dy
            if 0 <= nx < cols and 0 <= ny < rows:
                n_idx = ny * cols + nx
                neighbors.append((nx, ny))
                if grid[n_idx]["flag"]:
                    flag_count += 1
                    
    if flag_count == cell["adj"]:
        for nx, ny in neighbors:
            if not grid[ny * cols + nx]["flag"] and not grid[ny * cols + nx]["rev"]:
                reveal(win, nx, ny)
        if not win["game_over"]:
            check_win(win)

def update(win, lx, ly, mp, msp, mh):
    win["btn_down"] = None
    win["hover_idx"] = -1
    
    if win["timer_active"]:
        win["frames"] += 1
        
    py16.particles_update()
    
    # 1. UI Buttons abfragen (verschoben um TITLE_H)
    if TITLE_H + 4 <= ly <= TITLE_H + 18:
        _, nx, nw = NEW_BTN
        if nx <= lx <= nx + nw:
            win["btn_down"] = "neu" if mh else None
            if mp:
                reset_game(win)
                py16.tone(440, 50, py16.WAVE_SQUARE)
        else:
            for label, bx, bw, diff_idx, freq in DIFF_BUTTONS:
                if bx <= lx <= bx + bw:
                    win["btn_down"] = label if mh else None
                    if mp:
                        win["diff"] = diff_idx
                        reset_game(win)
                        py16.tone(freq, 40, py16.WAVE_TRIANGLE)
                    break
        return

    if win["game_over"]:
        return

    # 2. Grid-Interaktion
    cols, rows = win["cols"], win["rows"]
    ox = (win["w"] - cols * CELL_SIZE) // 2
    
    if ox <= lx < ox + cols * CELL_SIZE and OFFSET_Y <= ly < OFFSET_Y + rows * CELL_SIZE:
        cx = (lx - ox) // CELL_SIZE
        cy = (ly - OFFSET_Y) // CELL_SIZE
        idx = cy * cols + cx
        cell = win["grid"][idx]
        win["hover_idx"] = idx

        if mp:
            if win["first_click"]:
                place_mines(win, cx, cy)
                win["first_click"] = False
                win["timer_active"] = True
            
            if cell["rev"]:
                chord(win, cx, cy) 
            elif not cell["flag"]:
                reveal(win, cx, cy)
                if not win["game_over"]:
                    check_win(win)
                    py16.tone(800, 10, py16.WAVE_SQUARE)

        # Flagge setzen: Sekundär-Eingabe (X) ODER explizit rechte Maustaste.
        # msp deckt X/Sekundär ab; mouse_btnp(2) stellt sicher, dass der
        # echte Rechtsklick auch dann zieht, wenn der Host ihn nicht auf
        # die Sekundär-Eingabe mappt.
        elif msp or py16.mouse_btnp(2):
            if not cell["rev"]:
                cell["flag"] = not cell["flag"]
                win["mines_left"] += -1 if cell["flag"] else 1
                py16.tone(500, 20, py16.WAVE_SQUARE)

def draw_button(wx, wy, bx, bw, text, is_pressed, text_color):
    by, bh = 4, 14
    if is_pressed:
        py16.rectfill(wx + bx, wy + by, bw, bh, 5)
        py16.rect(wx + bx, wy + by, bw, bh, 5)
        py16.text(text, wx + bx + (bw - len(text)*4)//2 + 1, wy + by + 5 + 1, text_color)
    else:
        py16.rectfill(wx + bx, wy + by, bw, bh, 6)
        py16.rect(wx + bx, wy + by, bw, bh, 5)
        py16.line(wx + bx, wy + by, wx + bx + bw - 1, wy + by, 7)
        py16.line(wx + bx, wy + by, wx + bx, wy + by + bh - 1, 7)
        py16.text(text, wx + bx + (bw - len(text)*4)//2, wy + by + 5, text_color)

def draw_smiley(wx, wy, bx, is_pressed, game_over, won):
    by, bh, bw = 4, 14, 24
    bg_color = 5 if is_pressed else 6
    offset = 1 if is_pressed else 0
    
    py16.rectfill(wx + bx, wy + by, bw, bh, bg_color)
    py16.rect(wx + bx, wy + by, bw, bh, 5)
    if not is_pressed:
        py16.line(wx + bx, wy + by, wx + bx + bw - 1, wy + by, 7)
        py16.line(wx + bx, wy + by, wx + bx, wy + by + bh - 1, 7)
        
    cx, cy = wx + bx + bw//2 + offset, wy + by + bh//2 + offset
    py16.circfill(cx, cy, 5, 10) 
    py16.circ(cx, cy, 5, 0) 
    
    if game_over and not won:
        py16.pset(cx-2, cy-2, 0); py16.pset(cx-1, cy-1, 0)
        py16.pset(cx+2, cy-2, 0); py16.pset(cx+1, cy-1, 0)
        py16.line(cx-2, cy+2, cx+2, cy+2, 0)
    elif won: 
        py16.line(cx-3, cy-2, cx+3, cy-2, 0)
        py16.rectfill(cx-3, cy-2, 2, 2, 0)
        py16.rectfill(cx+1, cy-2, 2, 2, 0)
        py16.pset(cx-2, cy+2, 0); py16.pset(cx+2, cy+2, 0)
        py16.line(cx-1, cy+3, cx+1, cy+3, 0)
    else: 
        py16.pset(cx-2, cy-2, 0); py16.pset(cx+2, cy-2, 0)
        py16.pset(cx-2, cy+1, 0); py16.pset(cx+2, cy+1, 0)
        py16.line(cx-1, cy+2, cx+1, cy+2, 0)

def draw(win, wx, wy, ww, wh, is_active):
    # WICHTIG: Das Rechteck wird erst AB TITLE_H gezeichnet.
    # So wird die obere Leiste vom OS nicht mehr übermalt!
    py16.rectfill(wx, wy + TITLE_H, ww, wh - TITLE_H, 6)
    
    # 3D-Rahmen, der exakt unter der OS-Leiste beginnt
    py16.line(wx, wy + TITLE_H, wx + ww - 1, wy + TITLE_H, 5)
    py16.line(wx, wy + TITLE_H, wx, wy + wh - 1, 5)
    py16.line(wx, wy + wh - 1, wx + ww - 1, wy + wh - 1, 7)
    py16.line(wx + ww - 1, wy + TITLE_H, wx + ww - 1, wy + wh - 1, 7)
    
    py16.line(wx + 1, wy + TITLE_H + 1, wx + ww - 2, wy + TITLE_H + 1, 0)
    py16.line(wx + 1, wy + TITLE_H + 1, wx + 1, wy + wh - 2, 0)
    py16.line(wx + 1, wy + wh - 2, wx + ww - 2, wy + wh - 2, 6)
    py16.line(wx + ww - 2, wy + TITLE_H + 1, wx + ww - 2, wy + wh - 2, 6)
    
    active_color = 1 if is_active else 5
    btn_down = win.get("btn_down")
    
    # Buttons (wy wird ebenfalls mit TITLE_H addiert)
    cy_ui = wy + TITLE_H
    draw_smiley(wx, cy_ui, NEW_BTN[1], btn_down == "neu", win["game_over"], win["won"])
    for label, bx, bw, diff_idx, freq in DIFF_BUTTONS:
        draw_button(wx, cy_ui, bx, bw, label, btn_down == label or win["diff"] == diff_idx, active_color)
    
    status_color = 5
    if is_active:
        status_color = 8 if (win["game_over"] and not win["won"]) else (3 if win["won"] else 0)
    
    py16.text(f"M:{win['mines_left']:02d}", wx + 80, cy_ui + 9, status_color)
    
    hs = win["highscores"][win["diff"]]
    if hs < 999:
        py16.text(f"HS:{hs:03d}", wx + 116, cy_ui + 9, 2)
        
    seconds = min(win["frames"] // 60, 999)
    py16.text(f"T:{seconds:03d}", wx + ww - 32, cy_ui + 9, status_color)

    # Spielfeld Rendern
    cols, rows = win["cols"], win["rows"]
    ox = wx + (ww - cols * CELL_SIZE) // 2
    
    gw, gh = cols * CELL_SIZE, rows * CELL_SIZE
    oy = wy + OFFSET_Y
    py16.line(ox - 1, oy - 1, ox + gw, oy - 1, 5)
    py16.line(ox - 1, oy - 1, ox - 1, oy + gh, 5)
    py16.line(ox - 1, oy + gh, ox + gw, oy + gh, 7)
    py16.line(ox + gw, oy - 1, ox + gw, oy + gh, 7)
    
    num_colors = [0, 12, 11, 8, 1, 4, 13, 0, 5] 
    
    for cy in range(rows):
        for cx in range(cols):
            idx = cy * cols + cx
            cell = win["grid"][idx]
            x, y = ox + cx * CELL_SIZE, wy + OFFSET_Y + cy * CELL_SIZE
            
            if cell["rev"]:
                # Aufgedecktes Feld
                py16.rectfill(x, y, CELL_SIZE, CELL_SIZE, 7)
                py16.rect(x, y, CELL_SIZE, CELL_SIZE, 5)
                
                # Falsch gesetzte Fahne bei Game Over
                if win["game_over"] and not win["won"] and cell["flag"] and not cell["mine"]:
                    py16.rectfill(x + 5, y + 2, 4, 3, 8) # Rote Fahne
                    py16.line(x + 4, y + 2, x + 4, y + 8, 0) # Mast
                    py16.line(x + 2, y + 8, x + 6, y + 8, 0) # Sockel
                    py16.line(x + 2, y + 2, x + 9, y + 9, 0) # Durchstreichen
                elif cell["mine"]:
                    py16.circfill(x + CELL_SIZE//2, y + CELL_SIZE//2, 3, 8 if idx == win.get("hover_idx") else 0)
                    py16.pset(x + CELL_SIZE//2 - 1, y + CELL_SIZE//2 - 1, 7)
                elif cell["adj"] > 0:
                    py16.text(str(cell["adj"]), x + 4, y + 4, num_colors[cell["adj"]])
            else:
                # Verdecktes Feld mit Hover
                base_color = 7 if (idx == win.get("hover_idx") and is_active and not win["game_over"]) else 6
                py16.rectfill(x, y, CELL_SIZE, CELL_SIZE, base_color)
                py16.line(x, y, x + CELL_SIZE - 1, y, 7)
                py16.line(x, y, x, y + CELL_SIZE - 1, 7)
                py16.line(x + CELL_SIZE - 1, y, x + CELL_SIZE - 1, y + CELL_SIZE - 1, 5)
                py16.line(x, y + CELL_SIZE - 1, x + CELL_SIZE - 1, y + CELL_SIZE - 1, 5)
                
                if cell["flag"]:
                    py16.rectfill(x + 5, y + 2, 4, 3, 8) # Rote Fahne
                    py16.line(x + 4, y + 2, x + 4, y + 8, 0) # Mast
                    py16.line(x + 2, y + 8, x + 6, y + 8, 0) # Sockel

    if win["game_over"]:
        py16.particles_draw()
