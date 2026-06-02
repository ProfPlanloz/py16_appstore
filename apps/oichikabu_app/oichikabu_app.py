# apps/oichikabu.py
import random

APP = {
    "id": "oichikabu",
    "name": "OICHIKABU",
    "w": 180,
    "h": 165,               # Fenster etwas höher gemacht für besseres Layout
    "resizable": False,
    "icon": "oichikabu_app.p16img"
}

# --- Buttons an EINER Stelle definiert (lokale Fenster-Koordinaten) ----------
# draw() und update() lesen beide hieraus. So können Zeichen-Rechteck und
# Treffer-Test nicht mehr auseinanderdriften, wenn man das Layout anpasst.
# Format pro Button: (action, x, y, w, h, label)
BUTTONS = {
    "BETTING": [
        ("bet_minus",  20, 135, 30, 15, "-10"),
        ("bet_plus",   60, 135, 30, 15, "+10"),
        ("deal",      100, 135, 60, 15, "DEAL"),
    ],
    "PLAYER": [
        ("hit",        20, 135, 50, 15, "HIT"),
        ("stand",     110, 135, 50, 15, "STAND"),
    ],
    "OVER": [
        ("replay",     65, 135, 50, 15, "REPLAY"),
    ],
}

def button_at(state, lx, ly):
    """Liefert die action des getroffenen Buttons (oder None)."""
    for action, x, y, w, h, label in BUTTONS.get(state, []):
        if x <= lx <= x + w and y <= ly <= y + h:
            return action
    return None

def draw_buttons(py16, wx, wy, state):
    """Zeichnet alle Buttons des aktuellen Zustands aus derselben Definition."""
    for action, x, y, w, h, label in BUTTONS.get(state, []):
        py16.rectfill(wx + x, wy + y, w, h, 6)
        py16.rect(wx + x, wy + y, w, h, 5)
        # Label mittig im Button (3x5-Font ~ 4 px pro Zeichen)
        tx = wx + x + (w - len(label) * 4) // 2
        ty = wy + y + (h - 5) // 2
        py16.text(label, tx, ty, 1)
# -----------------------------------------------------------------------------

def reset_game(win):
    win["deck"] = [i for i in range(1, 11)] * 4
    random.shuffle(win["deck"])
    win["player"] = []
    win["dealer"] = []

    # Wenn man pleite ist, gibt einem die Bank frisches Geld
    if win.get("money", 0) <= 0:
        win["money"] = 100

    # Wette darf nicht höher als das verfügbare Geld sein
    win["bet"] = min(win.get("bet", 10), win["money"])

    win["state"] = "BETTING"
    win["msg"] = "PLACE YOUR BET"

def deal_cards(win):
    win["player"] = [win["deck"].pop(), win["deck"].pop()]
    win["dealer"] = [win["deck"].pop(), win["deck"].pop()]
    win["state"] = "PLAYER"
    win["msg"] = "YOUR TURN"

def get_score(cards):
    return sum(cards) % 10

def init(win):
    win["money"] = 100
    win["bet"] = 10
    reset_game(win)

def update(win, lx, ly, m_pressed, m_sec_pressed, m_held):
    if not m_pressed:
        return

    # Klicks in der Titelleiste ignorieren
    if ly < 14:
        return

    # Treffer-Test einmal gegen den Zustand BEIM EINTRITT in update().
    # Wechselt der Zustand unten (z.B. PLAYER -> DEALER -> OVER), wird dieser
    # action-Wert dort nicht mehr benutzt, daher ist das ungefährlich.
    action = button_at(win["state"], lx, ly)

    if win["state"] == "BETTING":
        if action == "bet_minus":
            win["bet"] = max(10, win["bet"] - 10)
        elif action == "bet_plus":
            win["bet"] = min(win["money"], win["bet"] + 10)
        elif action == "deal":
            deal_cards(win)

    elif win["state"] == "PLAYER":
        if action == "hit":
            win["player"].append(win["deck"].pop())
            if len(win["player"]) >= 3:
                win["state"] = "DEALER"
        elif action == "stand":
            win["state"] = "DEALER"

    # ABSICHTLICH "if" statt "elif": HIT/STAND oben kann den Zustand gerade
    # auf DEALER gesetzt haben. Dann soll der Dealer noch im SELBEN Frame zu
    # Ende spielen, statt erst beim nächsten Klick.
    if win["state"] == "DEALER":
        while get_score(win["dealer"]) <= 4 and len(win["dealer"]) < 3:
            win["dealer"].append(win["deck"].pop())

        win["state"] = "OVER"
        p_score = get_score(win["player"])
        d_score = get_score(win["dealer"])

        if p_score > d_score:
            win["msg"] = "YOU WIN!"
            win["money"] += win["bet"]
        elif d_score > p_score:
            win["msg"] = "DEALER WINS!"
            win["money"] -= win["bet"]
        else:
            win["msg"] = "TIE - DEALER WINS!"
            win["money"] -= win["bet"]

    # ABSICHTLICH "elif": Lief der DEALER-Block gerade durch, ist dieser Klick
    # bereits "verbraucht" – REPLAY darf erst beim nächsten Klick reagieren,
    # damit man nicht versehentlich sofort eine neue Runde startet.
    elif win["state"] == "OVER":
        if action == "replay":
            reset_game(win)

def draw_card(py16, cx, cy, val, hidden=False):
    # Weiße Karte mit dunkelgrauem Rand
    py16.rectfill(cx, cy, 20, 30, 7)
    py16.rect(cx, cy, 20, 30, 5)

    if hidden:
        # Kartenrückseite
        py16.rectfill(cx + 2, cy + 2, 16, 26, 1)
        py16.rect(cx + 4, cy + 4, 12, 22, 12)
    else:
        # Farbe 8 (Rot) für gerade Zahlen, Farbe 1 (Dunkelblau) für ungerade.
        # So umgehen wir den "Farbe-0-ist-transparent"-Bug deines Systems!
        c = 8 if val % 2 == 0 else 1
        s_val = str(val)

        # Obere linke und untere rechte Zahl
        py16.text(s_val, cx + 2, cy + 4, c)

        # Wenn der Wert "10" ist, rutscht der Text etwas weiter nach links, damit er passt
        x_offset = 8 if val == 10 else 12
        py16.text(s_val, cx + x_offset, cy + 20, c)

        # Dekoratives Zentrum (Hanafuda/Kabufuda angedeutet)
        py16.rectfill(cx + 7, cy + 12, 6, 6, c)

def draw(win, wx, wy, ww, wh, is_active):
    import py16

    # Casino-Tisch
    py16.rectfill(wx, wy + 14, ww, wh - 14, 3)

    # Geld & Wette oben rechts
    py16.text("MONEY: $" + str(win["money"]), wx + 100, wy + 20, 10)
    bet_color = 10 if win["state"] == "BETTING" else 6
    py16.text("BET:   $" + str(win["bet"]), wx + 100, wy + 30, bet_color)

    # DEALER
    py16.text("DEALER", wx + 10, wy + 20, 7)
    for i, val in enumerate(win["dealer"]):
        cx = wx + 10 + i * 25
        cy = wy + 30
        hide = (win["state"] == "PLAYER" and i == 1)
        draw_card(py16, cx, cy, val, hidden=hide)

    if win["state"] != "PLAYER" and win["state"] != "BETTING":
        py16.text("SCORE: " + str(get_score(win["dealer"])), wx + 90, wy + 40, 10)

    # PLAYER
    py16.text("PLAYER", wx + 10, wy + 68, 7)
    for i, val in enumerate(win["player"]):
        cx = wx + 10 + i * 25
        cy = wy + 78
        draw_card(py16, cx, cy, val)

    if win["state"] != "BETTING":
        py16.text("SCORE: " + str(get_score(win["player"])), wx + 90, wy + 88, 10)

    # Nachricht
    msg_x = wx + (ww - len(win["msg"]) * 4) // 2
    py16.text(win["msg"], msg_x, wy + 120, 10)

    # Buttons aus der gemeinsamen Definition (gleiche Quelle wie der Treffer-Test)
    draw_buttons(py16, wx, wy, win["state"])
