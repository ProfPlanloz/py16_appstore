import py16
import math
import json
import os
import random

# ---------------------------------------------------------------------------
# ARKANOID  -  py16os Plugin (Vollversion)
# Verbesserungen: normalisierte Ballgeschwindigkeit, Clipping, Brick-Pushout,
#                 Substep-Bewegung (kein Tunneling), Konstanten statt Magic-Numbers.
# Erweiterungen:  Highscore-Persistenz, endlose Level, Power-Ups, Partikel,
#                 Pause (Rechtsklick/X), Leben als Symbole, tr()-Unterstuetzung.
# ---------------------------------------------------------------------------

APP = {
    "id": "arkanoid",
    "name": "ARKANOID",
    "w": 160,
    "h": 150,
    "resizable": False,
    "icon": "arkanoid_app.p16img",
}

# --- Spielfeld-Konstanten (statt ueberall hartcodierter Zahlen) -------------
FIELD_W = APP["w"]          # 160
FIELD_H = APP["h"]          # 150
TOP = 14                    # Platz fuer die OS-Titlebar
NORM_PADDLE_W = 36
WIDE_PADDLE_W = 54
PADDLE_H = 4
PADDLE_Y = 135
BALL_R = 2
EFFECT_FRAMES = 540         # Dauer von Power-Ups (~9s bei 60fps)
MAX_BALLS = 6
SAVE_PATH = "arkanoid_save.json"

# Power-Up-Typen -> Farbe aus der py-16 Palette
PU_COLOR = {"E": 11, "M": 12, "L": 8, "S": 10}


# --- Sprache: tr() vom Host nutzen, sonst deutscher Literal -----------------
def T(key, fallback):
    try:
        from __main__ import tr
        s = tr(key)
        if s and s != key:
            return s
    except Exception:
        pass
    return fallback


# --- Highscore-Persistenz ---------------------------------------------------
def _load_high():
    if os.path.isfile(SAVE_PATH):
        try:
            with open(SAVE_PATH) as f:
                return int(json.load(f).get("high", 0))
        except Exception:
            pass
    return 0


def _save_high(win):
    try:
        with open(SAVE_PATH, "w") as f:
            json.dump({"high": int(win.get("high", 0))}, f)
    except Exception:
        pass


# --- Ballgeschwindigkeit konstant halten ------------------------------------
def set_ball_speed(b, speed):
    mag = math.hypot(b["dx"], b["dy"])
    if mag < 1e-6:
        b["dx"], b["dy"] = 0.0, -speed
    else:
        b["dx"] = b["dx"] / mag * speed
        b["dy"] = b["dy"] / mag * speed


def eff_speed(win):
    s = win["base_speed"]
    if win.get("slow_timer", 0) > 0:
        s *= 0.6
    return s


def paddle_width(win):
    return WIDE_PADDLE_W if win.get("wide_timer", 0) > 0 else NORM_PADDLE_W


# --- Level-Aufbau -----------------------------------------------------------
def build_level(level):
    """Erzeugt das Brick-Layout fuer ein Level. Hoehere Level = mehr Reihen,
    haertere und (selten) unzerstoerbare Bloecke."""
    bricks = []
    colors = [8, 9, 10, 11, 12]  # Rot, Orange, Gelb, Gruen, Blau
    rows = min(5 + (level - 1) // 2, 8)
    cols = 8
    pattern = (level - 1) % 3

    for row in range(rows):
        for col in range(cols):
            # Muster: 0=voll, 1=Schachbrett, 2=Pyramide
            if pattern == 1 and (row + col) % 2 == 1:
                continue
            if pattern == 2 and (col < row or col > cols - 1 - row):
                continue

            unbreak = (level >= 3 and pattern == 0 and row == 0 and col % 3 == 1)
            tough = (not unbreak) and (level >= 2 and random.random() < 0.20)

            bricks.append({
                "x": 8 + col * 18,
                "y": 25 + row * 10,
                "w": 16,
                "h": 8,
                "c": 6 if unbreak else colors[row % len(colors)],
                "hp": 1 if not tough else 2,
                "unbreak": unbreak,
                "active": True,
            })
    return bricks


def breakable_left(win):
    return sum(1 for br in win["bricks"] if br["active"] and not br["unbreak"])


# --- Ball / Paddle zuruecksetzen --------------------------------------------
def stick_ball(win):
    """Ein einzelner Ball klebt am Paddle (Zustand vor dem Abschuss)."""
    p = win["paddle"]
    win["balls"] = [{
        "x": p["x"] + p["w"] / 2.0,
        "y": p["y"] - BALL_R - 1,
        "dx": 0.0, "dy": 0.0, "r": BALL_R,
    }]


def reset_round(win):
    """Neue Runde nach Leben-Verlust oder neuem Level: Paddle/Ball + Effekte."""
    win["wide_timer"] = 0
    win["slow_timer"] = 0
    win["powerups"] = []
    win["parts"] = []
    win["paddle"] = {"w": NORM_PADDLE_W, "h": PADDLE_H, "y": PADDLE_Y,
                     "x": (FIELD_W - NORM_PADDLE_W) // 2}
    stick_ball(win)
    win["launch_timer"] = 90      # ~1.5s, dann startet der Ball automatisch
    win["state"] = "START"


def new_game(win):
    win["score"] = 0
    win["lives"] = 3
    win["level"] = 1
    win["base_speed"] = 2.6
    win["bricks"] = build_level(1)
    reset_round(win)


def next_level(win):
    win["level"] += 1
    win["base_speed"] = min(2.6 + (win["level"] - 1) * 0.25, 4.5)
    win["bricks"] = build_level(win["level"])
    reset_round(win)


def init(win):
    win["high"] = _load_high()
    new_game(win)


# --- Power-Ups & Partikel ---------------------------------------------------
def spawn_particles(win, x, y, c):
    for _ in range(5):
        win["parts"].append({
            "x": x, "y": y,
            "dx": random.uniform(-1.2, 1.2),
            "dy": random.uniform(-1.5, 0.3),
            "c": c, "life": random.randint(8, 16),
        })


def maybe_spawn_powerup(win, x, y):
    if random.random() < 0.18:
        kind = random.choice(["E", "M", "L", "S"])
        win["powerups"].append({"x": x - 3, "y": y, "kind": kind})


def apply_powerup(win, kind):
    if kind == "E":
        win["wide_timer"] = EFFECT_FRAMES
    elif kind == "S":
        win["slow_timer"] = EFFECT_FRAMES
    elif kind == "L":
        win["lives"] += 1
    elif kind == "M":
        extra = []
        for b in win["balls"]:
            for ang in (-0.4, 0.4):
                if len(win["balls"]) + len(extra) >= MAX_BALLS:
                    break
                c, s = math.cos(ang), math.sin(ang)
                nb = dict(b)
                nb["dx"] = b["dx"] * c - b["dy"] * s
                nb["dy"] = b["dx"] * s + b["dy"] * c
                extra.append(nb)
        win["balls"].extend(extra)
    py16.tone(1046, 25, py16.WAVE_SQUARE)


# --- Kollisionen ------------------------------------------------------------
def collide_walls(win, b, sp):
    hit = False
    if b["x"] - b["r"] < 0:
        b["x"] = b["r"]; b["dx"] = abs(b["dx"]); hit = True
    elif b["x"] + b["r"] > FIELD_W:
        b["x"] = FIELD_W - b["r"]; b["dx"] = -abs(b["dx"]); hit = True
    if b["y"] - b["r"] < TOP:
        b["y"] = TOP + b["r"]; b["dy"] = abs(b["dy"]); hit = True
    if hit:
        set_ball_speed(b, sp)
        py16.tone(220, 10, py16.WAVE_NOISE)


def collide_paddle(win, b, p, sp):
    if (b["dy"] > 0 and
            b["y"] + b["r"] >= p["y"] and b["y"] - b["r"] <= p["y"] + p["h"] and
            b["x"] + b["r"] >= p["x"] and b["x"] - b["r"] <= p["x"] + p["w"]):
        b["y"] = p["y"] - b["r"]
        hit_pos = max(0.0, min(1.0, (b["x"] - p["x"]) / p["w"]))
        angle = (hit_pos - 0.5) * 2.0          # ~ -57°..+57°
        b["dx"] = math.sin(angle)
        b["dy"] = -abs(math.cos(angle))
        set_ball_speed(b, sp)
        py16.tone(440, 30, py16.WAVE_SQUARE)


def collide_brick(win, b, sp):
    for br in win["bricks"]:
        if not br["active"]:
            continue
        if (b["x"] + b["r"] >= br["x"] and b["x"] - b["r"] <= br["x"] + br["w"] and
                b["y"] + b["r"] >= br["y"] and b["y"] - b["r"] <= br["y"] + br["h"]):
            cx = br["x"] + br["w"] / 2.0
            cy = br["y"] + br["h"] / 2.0
            ndx = (b["x"] - cx) / (br["w"] / 2.0)
            ndy = (b["y"] - cy) / (br["h"] / 2.0)
            # Reflexion + Ball aus dem Brick herausschieben (kein Steckenbleiben)
            if abs(ndx) > abs(ndy):
                if ndx > 0:
                    b["dx"] = abs(b["dx"]); b["x"] = br["x"] + br["w"] + b["r"]
                else:
                    b["dx"] = -abs(b["dx"]); b["x"] = br["x"] - b["r"]
            else:
                if ndy > 0:
                    b["dy"] = abs(b["dy"]); b["y"] = br["y"] + br["h"] + b["r"]
                else:
                    b["dy"] = -abs(b["dy"]); b["y"] = br["y"] - b["r"]
            set_ball_speed(b, sp)

            if br["unbreak"]:
                py16.tone(180, 12, py16.WAVE_NOISE)
            else:
                br["hp"] -= 1
                win["score"] += 10
                if br["hp"] <= 0:
                    br["active"] = False
                    spawn_particles(win, cx, cy, br["c"])
                    maybe_spawn_powerup(win, cx, cy)
                    py16.tone(880, 20, py16.WAVE_SQUARE)
                else:
                    br["c"] = 6  # angeschlagen -> grau
                    py16.tone(660, 15, py16.WAVE_SQUARE)
            return True
    return False


def step_balls(win, p, sp):
    """Bewegt alle Baelle in Substeps (verhindert Tunneling) und entfernt
    heruntergefallene. Gibt True zurueck, wenn alle Baelle weg sind."""
    fallen = []
    for b in win["balls"]:
        set_ball_speed(b, sp)  # Geschwindigkeit jeden Frame exakt halten
        steps = max(1, int(math.hypot(b["dx"], b["dy"])) + 1)
        gone = False
        for _ in range(steps):
            b["x"] += b["dx"] / steps
            b["y"] += b["dy"] / steps
            collide_walls(win, b, sp)
            collide_paddle(win, b, p, sp)
            collide_brick(win, b, sp)
            if b["y"] - b["r"] > FIELD_H:
                gone = True
                break
        if gone:
            fallen.append(b)
    for b in fallen:
        win["balls"].remove(b)
    return len(win["balls"]) == 0


def update_effects(win):
    if win.get("wide_timer", 0) > 0:
        win["wide_timer"] -= 1
    if win.get("slow_timer", 0) > 0:
        win["slow_timer"] -= 1

    # Partikel
    alive = []
    for pt in win["parts"]:
        pt["x"] += pt["dx"]
        pt["y"] += pt["dy"]
        pt["dy"] += 0.12
        pt["life"] -= 1
        if pt["life"] > 0:
            alive.append(pt)
    win["parts"] = alive

    # Fallende Power-Ups
    p = win["paddle"]
    keep = []
    for pu in win["powerups"]:
        pu["y"] += 1.3
        if (pu["y"] + 6 >= p["y"] and pu["y"] <= p["y"] + p["h"] and
                pu["x"] + 6 >= p["x"] and pu["x"] <= p["x"] + p["w"]):
            apply_powerup(win, pu["kind"])
        elif pu["y"] > FIELD_H:
            pass  # verfehlt -> verwerfen
        else:
            keep.append(pu)
    win["powerups"] = keep


def lose_life(win):
    win["lives"] -= 1
    py16.tone(150, 200, py16.WAVE_SAW)
    if win["lives"] <= 0:
        win["state"] = "GAMEOVER"
        if win["score"] > win["high"]:
            win["high"] = win["score"]
            _save_high(win)
    else:
        reset_round(win)


# --- Update ----------------------------------------------------------------
def update(win, lx, ly, mp, msp, mh):
    state = win["state"]
    p = win["paddle"]
    p["w"] = paddle_width(win)
    p["x"] = max(0, min(FIELD_W - p["w"], lx - p["w"] // 2))

    if state == "START":
        # Ball klebt am Paddle und folgt ihm
        b = win["balls"][0]
        b["x"] = p["x"] + p["w"] / 2.0
        b["y"] = p["y"] - BALL_R - 1
        win["launch_timer"] = win.get("launch_timer", 0) - 1
        # Automatischer Abschuss nach Countdown - oder sofort per Klick
        if mp or win["launch_timer"] <= 0:
            b["dx"] = random.choice((-0.4, 0.4))
            b["dy"] = -1.0
            set_ball_speed(b, eff_speed(win))
            win["state"] = "PLAY"
        return

    if state in ("GAMEOVER",):
        if mp:
            new_game(win)
        return

    if state == "PAUSE":
        if msp:
            win["state"] = "PLAY"
        return

    # ---- PLAY ----
    if msp:
        win["state"] = "PAUSE"
        return

    update_effects(win)
    sp = eff_speed(win)

    if step_balls(win, p, sp):
        lose_life(win)
        return

    if breakable_left(win) == 0:
        py16.tone(600, 300, py16.WAVE_TRIANGLE)
        win["score"] += 100  # Level-Bonus
        next_level(win)


# --- Draw ------------------------------------------------------------------
def draw(win, wx, wy, ww, wh, active):
    py16.clip(wx, wy + 14, ww, wh - 14)
    py16.rectfill(wx, wy + 14, ww, wh - 14, 0)

    # HUD
    py16.text(f"P:{win['score']}", wx + 4, wy + 16, 7)
    py16.text(f"LV{win['level']}", wx + ww // 2 - 8, wy + 16, 11)
    # Leben als Symbole (max 5 gezeichnet, sonst Zahl)
    if win["lives"] <= 5:
        for i in range(win["lives"]):
            py16.circfill(wx + ww - 6 - i * 7, wy + 18, 2, 8)
    else:
        py16.text(f"x{win['lives']}", wx + ww - 18, wy + 16, 8)

    # Bricks
    for br in win["bricks"]:
        if not br["active"]:
            continue
        bx, by = wx + br["x"], wy + br["y"]
        py16.rectfill(bx, by, br["w"], br["h"], br["c"])
        py16.line(bx, by, bx + br["w"] - 1, by, 7)        # Lichtkante oben
        py16.rect(bx, by, br["w"], br["h"], 0)            # Umriss
        if br["unbreak"]:
            py16.line(bx, by + br["h"] - 1, bx + br["w"] - 1, by + br["h"] - 1, 5)

    # Partikel
    for pt in win["parts"]:
        py16.pset(int(wx + pt["x"]), int(wy + pt["y"]), pt["c"])

    # Power-Ups (kleines Kaestchen mit Buchstabe)
    for pu in win["powerups"]:
        px, py_ = wx + int(pu["x"]), wy + int(pu["y"])
        py16.rectfill(px, py_, 7, 7, PU_COLOR[pu["kind"]])
        py16.rect(px, py_, 7, 7, 0)
        py16.text(pu["kind"], px + 2, py_ + 1, 0)

    # Paddle
    p = win["paddle"]
    py16.rectfill(wx + p["x"], wy + p["y"], p["w"], p["h"], 6)
    py16.rect(wx + p["x"], wy + p["y"], p["w"], p["h"], 5)

    # Baelle
    for b in win["balls"]:
        py16.circfill(int(wx + b["x"]), int(wy + b["y"]), b["r"], 7)

    # Aktive Effekt-Anzeige (kleine Balken unten links)
    if win.get("wide_timer", 0) > 0:
        py16.text("E", wx + 4, wy + wh - 8, 11)
    if win.get("slow_timer", 0) > 0:
        py16.text("S", wx + 12, wy + wh - 8, 10)

    # Overlays
    state = win["state"]
    if state == "START":
        _panel(wx, wy, ww, 1, 7)
        py16.text(T("ARKANOID:LEVEL", "LEVEL") + f" {win['level']}",
                  wx + ww // 2 - 18, wy + 73, 10)
        secs = max(1, win.get("launch_timer", 0) // 60 + 1)
        py16.text(T("ARKANOID:GETREADY", "GLEICH GEHT'S LOS") + f" {secs}",
                  wx + 22, wy + 81, 7)
    elif state == "PAUSE":
        _panel(wx, wy, ww, 1, 7)
        py16.text(T("ARKANOID:PAUSE", "PAUSE"), wx + ww // 2 - 10, wy + 73, 10)
        py16.text(T("ARKANOID:RESUME", "X = WEITER"), wx + ww // 2 - 18, wy + 81, 7)
    elif state == "GAMEOVER":
        _panel(wx, wy, ww, 8, 7)
        py16.text(T("ARKANOID:OVER", "GAME OVER!"), wx + ww // 2 - 20, wy + 71, 7)
        py16.text(f"HI:{win['high']}", wx + ww // 2 - 14, wy + 79, 10)
        py16.text(T("ARKANOID:RETRY", "KLICK FUER NEUSTART"), wx + 24, wy + 87, 7)

    py16.clip()


def _panel(wx, wy, ww, fill, border):
    py16.rectfill(wx + 15, wy + 68, ww - 30, 28, fill)
    py16.rect(wx + 15, wy + 68, ww - 30, 28, border)
