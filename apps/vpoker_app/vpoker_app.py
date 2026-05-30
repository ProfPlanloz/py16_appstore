import random
import math

APP = {
    "id": "vpoker",
    "name": "V-POKER",
    "w": 180,
    "h": 140,
    "resizable": False,
    "icon": "vpoker_app.p16img"
}

def get_deck():
    # Ranks: 2-10, 11=J, 12=Q, 13=K, 14=A
    # Suits: 0=Spades, 1=Hearts, 2=Clubs, 3=Diamonds
    return [(r, s) for r in range(2, 15) for s in range(4)]

def evaluate_hand(hand):
    ranks = sorted([c[0] for c in hand])
    suits = [c[1] for c in hand]
    
    flush = len(set(suits)) == 1
    straight = False
    if len(set(ranks)) == 5:
        if ranks[4] - ranks[0] == 4:
            straight = True
        # Special case: low Ace (A, 2, 3, 4, 5)
        if ranks == [2, 3, 4, 5, 14]:
            straight = True
            ranks = [1, 2, 3, 4, 5]
            
    counts = {r: ranks.count(r) for r in set(ranks)}
    vals = sorted(counts.values(), reverse=True)
    
    if straight and flush and ranks == [10, 11, 12, 13, 14]:
        return 250, "ROYAL FLUSH"
    if straight and flush:
        return 50, "STRAIGHT FLUSH"
    if vals == [4, 1]:
        return 25, "4 OF A KIND"
    if vals == [3, 2]:
        return 9, "FULL HOUSE"
    if flush:
        return 6, "FLUSH"
    if straight:
        return 4, "STRAIGHT"
    if vals == [3, 1, 1]:
        return 3, "3 OF A KIND"
    if vals == [2, 2, 1]:
        return 2, "TWO PAIR"
    if vals == [2, 1, 1, 1]:
        # Jacks or better
        pairs = [r for r, c in counts.items() if c == 2]
        if pairs[0] >= 11:
            return 1, "JACKS OR BTR"
            
    return 0, "GAME OVER"

def init(win):
    win["credits"] = 100
    win["bet"] = 1
    win["deck"] = get_deck()
    win["hand"] = []
    win["held"] = [False] * 5
    win["state"] = "IDLE" # IDLE -> DRAW -> IDLE
    win["msg"] = "PLACE BET"
    
    # --- Status variables for visual effects ---
    win["last_win_mult"] = 0
    win["glow_timer"] = 0
    win["show_pays"] = False # Paytable status

def update(win, lx, ly, m_pressed, m_sec_pressed, m_held):
    import py16
    
    # --- 1. Update global particles ---
    py16.particles_update()
    
    # --- 2. Normal UI inputs ---
    if not m_pressed:
        return
        
    # --- PAYS button toggle ---
    if 110 <= ly <= 126 and 90 <= lx <= 125:
        win["show_pays"] = not win.get("show_pays", False)
        py16.tone(880, 20, py16.WAVE_SQUARE)
        return

    # --- If paytable is open, close on any click ---
    if win.get("show_pays"):
        win["show_pays"] = False
        return
        
    # Click: Hold card (only in DRAW state)
    if win["state"] == "DRAW" and 40 <= ly <= 76:
        for i in range(5):
            cx = 15 + i * 30
            if cx <= lx <= cx + 24:
                win["held"][i] = not win["held"][i]
                py16.tone(600 + (200 if win["held"][i] else 0), 20, py16.WAVE_SQUARE)
                
    # Bottom buttons (Y: 110 to 126)
    if 110 <= ly <= 126:
        # BET ONE button
        if win["state"] == "IDLE" and 10 <= lx <= 45:
            win["bet"] = win["bet"] + 1 if win["bet"] < 5 else 1
            py16.tone(880, 20, py16.WAVE_SQUARE)
            
        # BET MAX button
        elif win["state"] == "IDLE" and 50 <= lx <= 85:
            win["bet"] = 5
            py16.tone(880, 20, py16.WAVE_SQUARE)
            
        # DEAL / DRAW button
        elif 130 <= lx <= 170:
            if win["state"] == "IDLE":
                if win["credits"] >= win["bet"]:
                    win["credits"] -= win["bet"]
                    win["deck"] = get_deck()
                    random.shuffle(win["deck"])
                    win["hand"] = [win["deck"].pop() for _ in range(5)]
                    win["held"] = [False] * 5
                    win["state"] = "DRAW"
                    win["msg"] = "HOLD CARDS"
                    win["last_win_mult"] = 0
                    py16.tone(440, 50, py16.WAVE_TRIANGLE)
                else:
                    win["msg"] = "NO CREDITS!"
                    py16.tone(220, 100, py16.WAVE_SAW)
                    
            elif win["state"] == "DRAW":
                # Draw new cards and reveal immediately
                for i in range(5):
                    if not win["held"][i]:
                        win["hand"][i] = win["deck"].pop()
                        
                # Evaluate
                mult, desc = evaluate_hand(win["hand"])
                win["last_win_mult"] = mult
                
                if mult > 0:
                    win["credits"] += win["bet"] * mult
                    win["msg"] = f"{desc} +{win['bet'] * mult}"
                    
                    # Center of the window for juicy particle bursts
                    px = win.get("x", 0) + win.get("w", 180) // 2
                    py = win.get("y", 0) + win.get("h", 140) // 2
                    
                    if mult >= 50: # Jackpot / Huge win!
                        py16.burst_explosion(px, py, color=10)
                        py16.burst_confetti(px, py, count=50)
                        py16.tone(1200, 300, py16.WAVE_SAW)
                    elif mult >= 4: # Good win
                        py16.burst_sparks(px, py, color=10)
                        py16.tone(880, 200, py16.WAVE_SQUARE)
                    else: # Standard win
                        py16.tone(880, 150, py16.WAVE_SQUARE)
                else:
                    win["msg"] = desc
                    py16.tone(300, 150, py16.WAVE_SAW)
                    
                win["state"] = "IDLE"

def draw_suit(wx, wy, suit, color):
    import py16
    c = color
    if suit == 0: # Spades
        py16.pset(wx+2, wy, c)
        py16.rectfill(wx+1, wy+1, 3, 1, c)
        py16.rectfill(wx, wy+2, 5, 1, c)
        py16.pset(wx, wy+3, c); py16.pset(wx+2, wy+3, c); py16.pset(wx+4, wy+3, c)
        py16.rectfill(wx+1, wy+4, 3, 1, c)
    elif suit == 1: # Hearts
        py16.pset(wx+1, wy, c); py16.pset(wx+3, wy, c)
        py16.rectfill(wx, wy+1, 5, 2, c)
        py16.rectfill(wx+1, wy+3, 3, 1, c)
        py16.pset(wx+2, wy+4, c)
    elif suit == 2: # Clubs
        py16.rectfill(wx+1, wy, 3, 1, c)
        py16.rectfill(wx, wy+1, 5, 2, c)
        py16.pset(wx+2, wy+1, 7) # Cutout middle
        py16.pset(wx+1, wy+3, c); py16.pset(wx+3, wy+3, c)
        py16.rectfill(wx+1, wy+4, 3, 1, c)
    elif suit == 3: # Diamonds
        py16.pset(wx+2, wy, c)
        py16.rectfill(wx+1, wy+1, 3, 1, c)
        py16.rectfill(wx, wy+2, 5, 1, c)
        py16.rectfill(wx+1, wy+3, 3, 1, c)
        py16.pset(wx+2, wy+4, c)

def draw_card(wx, wy, card, held):
    import py16
    rank, suit = card
    
    # Card Background & Border
    py16.rectfill(wx, wy, 24, 36, 7)
    py16.rect(wx, wy, 24, 36, 0) # Outline ignores palette
    
    # Color: 8=Red. 1=Dark blue
    color = 8 if suit in (1, 3) else 1 
    rank_char = {11:"J", 12:"Q", 13:"K", 14:"A"}.get(rank, str(rank))
    
    # Top left
    py16.text(rank_char, wx + 2, wy + 2, color)
    draw_suit(wx + 2, wy + 8, suit, color)
    
    # Bottom right
    tw = len(rank_char) * 4 - 1
    py16.text(rank_char, wx + 22 - tw, wy + 29, color)
    draw_suit(wx + 17, wy + 23, suit, color)
    
    # Hold indicator
    if held:
        py16.rectfill(wx + 2, wy + 14, 20, 9, 10)
        py16.text("HOLD", wx + 4, wy + 16, 1)

def draw_button(wx, wy, w, h, text, active):
    import py16
    bg_color = 6 if active else 5
    text_color = 1 if active else 6 # Dark text for active, light grey for inactive
    
    py16.rectfill(wx, wy, w, h, bg_color)
    py16.rect(wx, wy, w, h, 0)
    
    tw = len(text) * 4 - 1
    tx = wx + (w - tw) // 2
    ty = wy + (h - 5) // 2
    py16.text(text, int(tx), int(ty), text_color)

def draw(win, wx, wy, ww, wh, is_active):
    import py16
    
    win["glow_timer"] = win.get("glow_timer", 0) + 1
    
    # Background (Casino Green)
    py16.rectfill(wx, wy + 14, ww, wh - 14, 3)
    
    # Top bar with credits and message
    py16.rectfill(wx, wy + 14, ww, 12, 1)
    py16.text(f"CREDITS: {win['credits']}", wx + 4, wy + 18, 7)
    py16.text(win["msg"], wx + 100, wy + 18, 10)
    
    # Draw cards
    for i in range(5):
        cx = wx + 15 + i * 30
        cy = wy + 40
        
        # --- Win glow (Additive Blending) ---
        if win["state"] == "IDLE" and win.get("last_win_mult", 0) > 0:
            pulse = (math.sin(win["glow_timer"] * 0.15) + 1) / 2 # Sine 0.0 to 1.0
            py16.blend_mode("add")
            glow_r = int(14 + pulse * 6) # Radius wobbles organically
            py16.circfill(cx + 12, cy + 18, glow_r, 9) # Orange glow around the center
            py16.blend_mode("normal")
            
        if len(win["hand"]) > 0:
            draw_card(cx, cy, win["hand"][i], win["held"][i])
        else:
            # Fancy card back for empty hands
            py16.rectfill(cx, cy, 24, 36, 1)
            py16.rect(cx, cy, 24, 36, 0)
            for py in range(cy + 4, cy + 32, 4):
                py16.line(cx + 4, py, cx + 19, py, 12)
            py16.rect(cx + 3, cy + 3, 18, 30, 12)
            
    # Current bet display
    py16.text(f"BET: {win['bet']}", wx + 15, wy + 90, 7)
    
    # Evaluate current hand before final draw
    if win["state"] == "DRAW":
        mult, desc = evaluate_hand(win["hand"])
        if mult > 0:
            py16.text(f"CURRENT: {desc}", wx + 65, wy + 90, 10)
    
    # Buttons
    draw_button(wx + 10, wy + 110, 35, 16, "BET 1", win["state"] == "IDLE")
    draw_button(wx + 50, wy + 110, 35, 16, "MAX", win["state"] == "IDLE")
    
    # PAYS button
    draw_button(wx + 90, wy + 110, 35, 16, "PAYS", True)
    
    deal_txt = "DEAL" if win["state"] == "IDLE" else "DRAW"
    draw_button(wx + 130, wy + 110, 40, 16, deal_txt, True)
    
    # --- Paytable overlay ---
    if win.get("show_pays"):
        py16.rectfill(wx + 15, wy + 30, 150, 75, 1) # Dark blue
        py16.rect(wx + 15, wy + 30, 150, 75, 6) # Grey border
        
        pays = [
            ("ROYAL FLUSH", 250),
            ("STRAIGHT FLUSH", 50),
            ("4 OF A KIND", 25),
            ("FULL HOUSE", 9),
            ("FLUSH", 6),
            ("STRAIGHT", 4),
            ("3 OF A KIND", 3),
            ("TWO PAIR", 2),
            ("JACKS OR BTR", 1)
        ]
        
        for i, (name, mult) in enumerate(pays):
            y = wy + 34 + i * 7
            py16.text(name, wx + 20, y, 7)
            
            # Display of actual win based on bet!
            val_str = str(mult * win['bet'])
            vw = len(val_str) * 4 - 1
            val_color = 10 if mult >= 50 else 6 # Yellow for high wins
            py16.text(val_str, wx + 160 - vw, y, val_color)

    # --- Draw particles ---
    # Draws confetti and sparks in front of everything else!
    py16.particles_draw()
