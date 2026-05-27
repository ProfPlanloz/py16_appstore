import threading
import urllib.request
import json
import time
import os
import py16

# Das Krypto-Terminal-Paket für py16OS mit automatischer Icon-Zuweisung!
APP = {
    "id": "crypto", 
    "name": "KRYPTO", 
    "w": 160, 
    "h": 160, 
    "resizable": True,
    "min_w": 140, 
    "min_h": 110,
    "icon": "krypto.p16img" 
}

# Cache V2: Da wir nun OHLC Tuple statt einzelner Floats speichern,
# ändern wir den Dateinamen, um Crashs mit alten Caches zu vermeiden.
CACHE_FILE = "krypto_cache_v2.json"
EXPORT_FILE = "krypto_watchlist.txt"

def fetch_crypto(win, symbol):
    try:
        # 1. Aktuellen Live-Preis abfragen
        url = f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}"
        req = urllib.request.Request(url, headers={'User-Agent': 'py-16-os'})
        with urllib.request.urlopen(req, timeout=3) as response:
            data = json.loads(response.read().decode('utf-8'))
            price = float(data['price'])
            old_price = win.get("last_prices", {}).get(symbol, 0.0)
            
            # Trend-Farbe ermitteln (Grün = 11, Rot = 8)
            if old_price > 0:
                win["trend_color"] = 11 if price >= old_price else 8
            else:
                win["trend_color"] = 7
                
            win["last_prices"][symbol] = price
            
            # Formatierung
            if price > 10:
                win["result"] = f"${price:,.2f}"
            else:
                win["result"] = f"${price:,.4f}"

        # OHLC (Open, High, Low, Close) Funktion für sauberen Code
        def get_ohlc(url_str):
            req_h = urllib.request.Request(url_str, headers={'User-Agent': 'py-16-os'})
            with urllib.request.urlopen(req_h, timeout=3) as res:
                k_data = json.loads(res.read().decode('utf-8'))
                # Binance Array: [0: Time, 1: Open, 2: High, 3: Low, 4: Close]
                return [(float(k[1]), float(k[2]), float(k[3]), float(k[4])) for k in k_data]

        # 2. 24-Stunden-Historie (1h Intervalle, 24 Datenpunkte)
        win["histories_24h"][symbol] = get_ohlc(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=24")

        # 3. 7-Tage-Historie (1d Intervalle, 7 Datenpunkte)
        win["histories_7d"][symbol] = get_ohlc(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=7")

        # 4. 1-Monat-Historie (1d Intervalle, 30 Datenpunkte)
        win["histories_1m"][symbol] = get_ohlc(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1d&limit=30")

        # 5. 1-Jahr-Historie (1w Intervalle, 52 Datenpunkte)
        win["histories_1y"][symbol] = get_ohlc(f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1w&limit=52")

        # Flag für thread-sicheres Audio-Feedback setzen
        win["play_success"] = True
        win["error"] = False
        
        # Erfolgreichen Abruf-Zeitstempel setzen
        win["last_fetch_time"] = time.time()
        
        # Smart-Cache aktualisieren
        save_cache(win)
        
    except Exception as e:
        win["result"] = "API FEHLER!"
        win["trend_color"] = 8
        win["error"] = True
        win["play_error"] = True
        
    win["loading"] = False

def save_cache(win):
    try:
        cache_data = {
            "c_idx": win["c_idx"],
            "last_prices": win["last_prices"],
            "histories_24h": win["histories_24h"],
            "histories_7d": win["histories_7d"],
            "histories_1m": win["histories_1m"],
            "histories_1y": win["histories_1y"],
            "auto_refresh": win["auto_refresh"],
            "last_fetch_time": win["last_fetch_time"],
            "active_tab": win["active_tab"]
        }
        with open(CACHE_FILE, "w", encoding="utf-8") as f:
            json.dump(cache_data, f)
    except Exception:
        pass

def load_cache(win):
    if os.path.exists(CACHE_FILE):
        try:
            with open(CACHE_FILE, "r", encoding="utf-8") as f:
                cache_data = json.load(f)
                win["c_idx"] = cache_data.get("c_idx", 0)
                win["last_prices"] = cache_data.get("last_prices", {})
                win["histories_24h"] = cache_data.get("histories_24h", {})
                win["histories_7d"] = cache_data.get("histories_7d", {})
                win["histories_1m"] = cache_data.get("histories_1m", {})
                win["histories_1y"] = cache_data.get("histories_1y", {})
                win["auto_refresh"] = cache_data.get("auto_refresh", True)
                win["last_fetch_time"] = cache_data.get("last_fetch_time", 0.0)
                win["active_tab"] = cache_data.get("active_tab", 0)
                
                update_display_value(win)
        except Exception:
            pass

def update_display_value(win):
    symbol = win["symbols"][win["c_idx"]]
    if symbol in win["last_prices"]:
        price = win["last_prices"][symbol]
        if price > 10:
            win["result"] = f"${price:,.2f}"
        else:
            win["result"] = f"${price:,.4f}"
    else:
        win["result"] = "NO DATA"

def export_watchlist(win):
    try:
        symbol = win["symbols"][win["c_idx"]]
        coin_name = win["coins"][win["c_idx"]]
        current_p = win["result"]
        hist_24h = win["histories_24h"].get(symbol, [])
        hist_7d = win["histories_7d"].get(symbol, [])
        hist_1m = win["histories_1m"].get(symbol, [])
        hist_1y = win["histories_1y"].get(symbol, [])

        lines = [
            "=========================================",
            "        KRYPTO WATCHLIST MASTER REPORT   ",
            "=========================================",
            f"Exportzeitpunkt: {time.strftime('%Y-%m-%d %H:%M:%S')}",
            f"Coin:            {coin_name} ({symbol})",
            f"Kurs:            {current_p}",
            "-----------------------------------------",
            "VERLAUFSTRENDS (OHLC-Punkte geladen):",
            f"  24 Stunden-Verlauf:  {len(hist_24h)} Kerzen",
            f"  7 Tage-Verlauf:      {len(hist_7d)} Kerzen",
            f"  1 Monat-Verlauf:     {len(hist_1m)} Kerzen",
            f"  1 Jahr-Verlauf:      {len(hist_1y)} Kerzen",
            "========================================="
        ]

        with open(EXPORT_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
            
        win["play_export"] = True
        win["status_msg"] = "EXPORT OK!"
        win["status_time"] = time.time()
        return True
    except Exception:
        win["status_msg"] = "EXPORT ERR!"
        win["status_time"] = time.time()
        return False

def init(win):
    win["coins"] = ["BITCOIN", "ETHEREUM", "SOLANA", "DOGECOIN"]
    win["symbols"] = ["BTCUSDT", "ETHUSDT", "SOLUSDT", "DOGEUSDT"]
    win["c_idx"] = 0
    win["result"] = "READY"
    win["loading"] = False
    win["error"] = False
    win["trend_color"] = 7
    
    # Cache Strukturen
    win["last_prices"] = {}
    win["histories_24h"] = {}
    win["histories_7d"] = {}
    win["histories_1m"] = {}
    win["histories_1y"] = {}
    
    # Auto-Refresh & Navigation
    win["auto_refresh"] = True
    win["refresh_interval"] = 30
    win["last_fetch_time"] = 0.0
    win["active_tab"] = 0
    
    win["status_msg"] = ""
    win["status_time"] = 0.0
    win["btn_hover_type"] = 0 

    load_cache(win)

def update(win, lx, ly, m_pressed, m_sec_pressed, m_held):
    current_time = time.time()
    
    # --- Thread-Sicheres Audio abspielen ---
    if win.pop("play_success", False):
        py16.tone(587, duration_ms=60, wave=py16.WAVE_TRIANGLE, decay_ms=40)
        py16.tone(880, duration_ms=120, wave=py16.WAVE_TRIANGLE, decay_ms=100)
    
    if win.pop("play_error", False):
        py16.tone(130, duration_ms=150, wave=py16.WAVE_SAW, decay_ms=120)
        py16.tone(90, duration_ms=200, wave=py16.WAVE_NOISE, decay_ms=180)
        
    if win.pop("play_export", False):
        for freq in [1100, 1300, 1000, 1200, 850]:
            py16.tone(freq, duration_ms=25, wave=py16.WAVE_SQUARE, decay_ms=10)

    if win.get("status_msg") and current_time - win["status_time"] > 3.0:
        win["status_msg"] = ""

    # Auto-Refresh
    if win.get("auto_refresh") and not win.get("loading"):
        symbol = win["symbols"][win["c_idx"]]
        has_data = (symbol in win["last_prices"]) and \
                   (symbol in win["histories_24h"]) and \
                   (symbol in win["histories_7d"]) and \
                   (symbol in win["histories_1m"]) and \
                   (symbol in win["histories_1y"])
                   
        elapsed = current_time - win.get("last_fetch_time", 0.0)
        
        if (not has_data) or (elapsed >= win["refresh_interval"]):
            trigger_fetch(win)

    if win.get("loading"): 
        return
        
    btn_w, btn_h = 36, 11
    btn_y = 38 # Lokales Y für Update-Hitboxen
    bx1 = 6                     
    bx2 = bx1 + btn_w + 4       
    bx3 = bx2 + btn_w + 4       
    
    tab_y = 70
    tab_h = 10
    tab_w = (win["w"] - 24) // 4
    
    # Hover-Checks
    hover_tabs = []
    for idx in range(4):
        tx = 6 + idx * (tab_w + 4)
        hover_tabs.append(tx <= lx <= tx + tab_w and tab_y <= ly <= tab_y + tab_h)
        
    hover_update = (bx1 <= lx <= bx1 + btn_w and btn_y <= ly <= btn_y + btn_h)
    hover_auto = (bx2 <= lx <= bx2 + btn_w and btn_y <= ly <= btn_y + btn_h)
    hover_save = (bx3 <= lx <= bx3 + btn_w and btn_y <= ly <= btn_y + btn_h)
    
    if hover_update: win["btn_hover_type"] = 1
    elif hover_auto: win["btn_hover_type"] = 2
    elif hover_save: win["btn_hover_type"] = 3
    elif any(hover_tabs): win["btn_hover_type"] = 4 + hover_tabs.index(True)
    else: win["btn_hover_type"] = 0
    
    do_fetch = False
    
    if py16.btnp('right'):
        win["c_idx"] = (win["c_idx"] + 1) % len(win["coins"])
        update_display_value(win)
        win["trend_color"] = 7
        win["error"] = False
        py16.tone(330, duration_ms=30, wave=py16.WAVE_TRIANGLE, decay_ms=20)
        save_cache(win)
        
    if py16.btnp('left'):
        win["c_idx"] = (win["c_idx"] - 1) % len(win["coins"])
        update_display_value(win)
        win["trend_color"] = 7
        win["error"] = False
        py16.tone(330, duration_ms=30, wave=py16.WAVE_TRIANGLE, decay_ms=20)
        save_cache(win)
        
    if py16.btnp('z') or py16.btnp('enter'):
        do_fetch = True

    if m_pressed:
        if hover_update:
            do_fetch = True
        elif hover_auto:
            win["auto_refresh"] = not win["auto_refresh"]
            py16.tone(660, duration_ms=50, wave=py16.WAVE_TRIANGLE, decay_ms=40)
            save_cache(win)
        elif hover_save:
            export_watchlist(win)
        elif any(hover_tabs):
            clicked_tab = hover_tabs.index(True)
            if win["active_tab"] != clicked_tab:
                win["active_tab"] = clicked_tab
                py16.tone(480 + clicked_tab * 40, duration_ms=25, wave=py16.WAVE_TRIANGLE, decay_ms=15)
                save_cache(win)
        elif 14 <= ly <= 36: 
            if lx < win["w"] // 2:
                win["c_idx"] = (win["c_idx"] - 1) % len(win["coins"])
            else:
                win["c_idx"] = (win["c_idx"] + 1) % len(win["coins"])
            update_display_value(win)
            win["trend_color"] = 7
            win["error"] = False
            py16.tone(330, duration_ms=30, wave=py16.WAVE_TRIANGLE, decay_ms=20)
            save_cache(win)

    if do_fetch:
        trigger_fetch(win)

def trigger_fetch(win):
    win["loading"] = True
    win["result"] = "LOADING..."
    py16.tone(440, duration_ms=50, wave=py16.WAVE_SQUARE, decay_ms=30)
    
    symbol = win["symbols"][win["c_idx"]]
    t = threading.Thread(target=fetch_crypto, args=(win, symbol))
    t.daemon = True
    t.start()

def draw(win, wx, wy, ww, wh, is_active):
    import __main__
    sys_txt = getattr(__main__, "sys_text_color", 1)
    # OS Übersetzer einbinden (Fallback, falls außerhalb vom OS ausgeführt)
    tr = getattr(__main__, "tr", lambda x: x)
    
    content_y = wy + 14
    content_h = wh - 14
    
    # 1. Hintergrund (Hacker-Tiefschwarz)
    py16.rectfill(wx + 2, content_y, ww - 4, content_h - 2, 0)
    
    # 2. Coin-Auswahl
    text_y = content_y + 6
    py16.text("COIN:", wx + 6, text_y, sys_txt)
    
    current_coin = f"< {win['coins'][win['c_idx']]} >"
    color_map = [9, 2, 11, 10] 
    coin_color = color_map[win["c_idx"] % len(color_map)]
    py16.text(current_coin, wx + 6, text_y + 11, coin_color)
    
    # 3. Haupt-Buttons
    by = wy + 38
    btn_w, btn_h = 36, 11
    bx1 = wx + 6
    bx2 = bx1 + btn_w + 4
    bx3 = bx2 + btn_w + 4
    
    hover_type = win.get("btn_hover_type", 0)
    
    # [ UPDATE ]
    b1_col = 5 if win.get("loading") else (13 if hover_type == 1 else 1)
    py16.rectfill(bx1, by, btn_w, btn_h, b1_col)
    py16.rect(bx1, by, btn_w, btn_h, 7 if is_active else 5)
    py16.text(tr("UPDATE"), bx1 + 6, by + 3, 7)
    
    # [ AUTO ]
    b2_col = 11 if win["auto_refresh"] else 2
    if hover_type == 2: b2_col = 13
    py16.rectfill(bx2, by, btn_w, btn_h, b2_col)
    py16.rect(bx2, by, btn_w, btn_h, 7 if is_active else 5)
    py16.text(tr("AUTO"), bx2 + 10, by + 3, 7)
    
    # [ SAVE ]
    b3_col = 13 if hover_type == 3 else 1
    py16.rectfill(bx3, by, btn_w, btn_h, b3_col)
    py16.rect(bx3, by, btn_w, btn_h, 7 if is_active else 5)
    py16.text(tr("SAVE"), bx3 + 10, by + 3, 7)
    
    # Auto-Refresh Ladebalken
    if win["auto_refresh"] and not win["loading"] and win["last_fetch_time"] > 0:
        elapsed = time.time() - win["last_fetch_time"]
        progress = min(1.0, elapsed / win["refresh_interval"])
        bar_w = int((ww - 12) * (1.0 - progress))
        py16.rectfill(wx + 6, by + 13, ww - 12, 2, 5)
        py16.rectfill(wx + 6, by + 13, bar_w, 2, 12)
        
    res_color = 5 if win["loading"] else win["trend_color"]
    py16.text(tr(win["result"]), wx + 6, by + 17, res_color)
    
    if win.get("status_msg"):
        py16.text(tr(win["status_msg"]), wx + 6, by + 26, 14)
    
    # --- INTERAKTIVES TABS-SYSTEM ---
    tab_y = wy + 70
    tab_h = 10
    tab_w = (ww - 24) // 4
    tab_names = ["24H", "7D", "1M", "1Y"]
    
    for idx, name in enumerate(tab_names):
        tx = wx + 6 + idx * (tab_w + 4)
        is_active_tab = (win["active_tab"] == idx)
        
        tab_col = coin_color if is_active_tab else (5 if hover_type == 4 + idx else 1)
        
        py16.rectfill(tx, tab_y, tab_w, tab_h, tab_col)
        py16.rect(tx, tab_y, tab_w, tab_h, 7 if is_active_tab else 5)
        
        txt_col = 0 if is_active_tab else 7
        py16.text(name, tx + (tab_w - len(name) * 4) // 2 + 1, tab_y + 3, txt_col)
        
    # --- CANDLESTICK GRAPH (KERZENDIAGRAMM) ---
    gx = wx + 6
    gy = tab_y + tab_h + 2
    gw = ww - 12
    gh = (wy + wh) - gy - 8 
    
    if gh >= 30:
        py16.rect(gx, gy, gw, gh, 5)
        
        # Oszilloskop-Hintergrundraster
        py16.line(gx + 1, gy + gh // 2, gx + gw - 2, gy + gh // 2, 1)
        for g_idx in range(1, 4):
            grid_x = gx + (g_idx * gw) // 4
            py16.line(grid_x, gy + 1, grid_x, gy + gh - 2, 1)
            
        symbol = win["symbols"][win["c_idx"]]
        
        history = []
        points_count = 0
        if win["active_tab"] == 0:
            history = win["histories_24h"].get(symbol, [])
            points_count = 24
        elif win["active_tab"] == 1:
            history = win["histories_7d"].get(symbol, [])
            points_count = 7
        elif win["active_tab"] == 2:
            history = win["histories_1m"].get(symbol, [])
            points_count = 30
        elif win["active_tab"] == 3:
            history = win["histories_1y"].get(symbol, [])
            points_count = 52 
            
        if history and len(history) == points_count:
            # Min/Max finden (Index 1 = High, Index 2 = Low im Tupel)
            min_val = min(k[2] for k in history)
            max_val = max(k[1] for k in history)
            val_range = max_val - min_val if max_val != min_val else 1.0
            
            # Kerzen-Breite berechnen
            body_w = max(1, (gw // points_count) - 1)
            if body_w % 2 == 0 and body_w > 1: 
                body_w -= 1 # Ungerade Breite für perfekte Zentrierung um den Docht
            half_w = body_w // 2

            for i, (o, h, l, c) in enumerate(history):
                # X-Zentrum der Kerze
                px_x = gx + 4 + int((i * (gw - 8)) / (points_count - 1))
                
                # Y-Koordinaten (Invertiert: hoher Wert = kleines Y)
                y_o = gy + gh - 4 - int(((o - min_val) * (gh - 8)) / val_range)
                y_h = gy + gh - 4 - int(((h - min_val) * (gh - 8)) / val_range)
                y_l = gy + gh - 4 - int(((l - min_val) * (gh - 8)) / val_range)
                y_c = gy + gh - 4 - int(((c - min_val) * (gh - 8)) / val_range)

                # Farbe: Grün (11) wenn Schluss >= Open, Rot (8) wenn Schluss < Open
                c_color = 11 if c >= o else 8
                
                # 1. Docht/Lunte zeichnen (High zu Low)
                py16.line(px_x, y_h, px_x, y_l, c_color)
                
                # 2. Kerzenkörper zeichnen (Open zu Close)
                top_y = min(y_o, y_c)
                bot_y = max(y_o, y_c)
                rect_h = max(1, bot_y - top_y) # Mindestens 1px hoch, selbst bei Doji
                
                py16.rectfill(px_x - half_w, top_y, body_w, rect_h, c_color)
            
            max_str = f"MAX: {max_val:,.0f}" if max_val > 100 else f"MAX: {max_val:,.2f}"
            min_str = f"MIN: {min_val:,.0f}" if min_val > 100 else f"MIN: {min_val:,.2f}"
            py16.text(max_str, gx + 4, gy + 3, 6)
            py16.text(min_str, gx + 4, gy + gh - 9, 6)
        else:
            py16.text(tr("CHART BEREIT"), gx + (gw - 48) // 2, gy + (gh - 6) // 2, 5)
            
    # CRT-Glitch-Störung bei API-Fehlern
    if win.get("error"):
        jitter = py16.scanline_jitter(amplitude=1)
        py16.scanline_apply(jitter, wrap=True, y_start=content_y, y_end=content_y + content_h)