import threading
import urllib.request
import json
import os
import time

# Fensterhöhe erhöht (145) für drei Text-Zeilen
APP = {
    "id": "weather", 
    "name": "WEATHER", 
    "w": 140, 
    "h": 145, 
    "resizable": False,
    "icon": "weather_app.p16img"
}
SAVE_PATH = "weather_save.json"

def fetch_weather(win, city):
    try:
        url_city = city.replace(" ", "+")
        # j1 returns full JSON data, default language is English
        url = f"https://wttr.in/{url_city}?format=j1"
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode('utf-8'))
            
            # 1. Current temperature
            current = data['current_condition'][0]
            temp = int(current['temp_C'])
            
            # 2. Extended weather data (description)
            cond = "UNKNOWN"
            if 'weatherDesc' in current:
                cond = current['weatherDesc'][0]['value']
                
            # 3. Daily trend for the graph (hourly values)
            hourly = data['weather'][0]['hourly']
            graph_data = [int(h['tempC']) for h in hourly]
            
            win["weather_data"] = {
                "temp": temp,
                "cond": cond.upper()[:16],  # Shorten text if too long
                "graph": graph_data
            }
            win["result"] = f"{temp} C"
            
            # --- SAVE CACHE ---
            if "cache" not in win:
                win["cache"] = {}
            win["cache"][city] = {
                "timestamp": time.time(),
                "data": win["weather_data"]
            }
            save_config(win)
            
    except Exception as e:
        win["result"] = "ERROR!"
        win["weather_data"] = None
    
    win["loading"] = False

def save_config(win):
    try:
        with open(SAVE_PATH, "w") as f:
            json.dump({
                "cont_idx": win.get("cont_idx", 0),
                "ctry_idx": win.get("ctry_idx", 0),
                "city_idx": win.get("city_idx", 0),
                "cache": win.get("cache", {})
            }, f)
    except Exception:
        pass

def init(win):
    # Strukturierte Orte nach Kontinenten -> Ländern -> Städten
    win["locations"] = {
        "EUROPE": {
            "GERMANY": ["BERLIN", "MUNICH", "HAMBURG", "FRANKFURT", "COLOGNE", "STUTTGART"],
            "FRANCE": ["PARIS", "LYON", "MARSEILLE", "NICE"],
            "UK": ["LONDON", "EDINBURGH", "MANCHESTER", "GLASGOW"],
            "ITALY": ["ROME", "MILAN", "NAPLES", "VENICE"],
            "SPAIN": ["MADRID", "BARCELONA", "SEVILLE", "VALENCIA"],
            "AUSTRIA": ["VIENNA", "SALZBURG", "INNSBRUCK"],
            "SWITZERLAND": ["BERN", "ZURICH", "GENEVA"],
            "NETHERLANDS": ["AMSTERDAM", "ROTTERDAM", "THE HAGUE"],
            "SWEDEN": ["STOCKHOLM", "GOTHENBURG", "MALMO"],
            "NORWAY": ["OSLO", "BERGEN"],
            "POLAND": ["WARSAW", "KRAKOW", "GDANSK"],
            "GREECE": ["ATHENS", "THESSALONIKI"],
            "PORTUGAL": ["LISBON", "PORTO"],
            "BELGIUM": ["BRUSSELS", "ANTWERP"],
            "UKRAINE": ["KYIV", "KHARKIV", "ODESA", "LVIV"],
            "RUSSIA": ["MOSCOW", "SAINT PETERSBURG", "NOVOSIBIRSK"]
        },
        "AMERICAS": {
            "USA": ["WASHINGTON", "NEW YORK", "LOS ANGELES", "CHICAGO", "MIAMI", "SAN FRANCISCO", "HOUSTON"],
            "CANADA": ["OTTAWA", "TORONTO", "VANCOUVER", "MONTREAL", "CALGARY"],
            "MEXICO": ["MEXICO CITY", "CANCUN", "GUADALAJARA"],
            "BRAZIL": ["BRASILIA", "RIO DE JANEIRO", "SAO PAULO", "SALVADOR"],
            "ARGENTINA": ["BUENOS AIRES", "CORDOBA", "ROSARIO"],
            "CHILE": ["SANTIAGO", "VALPARAISO"],
            "COLOMBIA": ["BOGOTA", "MEDELLIN", "CALI"],
            "PERU": ["LIMA", "CUSCO"],
            "CUBA": ["HAVANA"]
        },
        "ASIA": {
            "JAPAN": ["TOKYO", "OSAKA", "KYOTO", "SAPPORO", "FUKUOKA"],
            "CHINA": ["BEIJING", "SHANGHAI", "HONG KONG", "SHENZHEN", "GUANGZHOU"],
            "SOUTH KOREA": ["SEOUL", "BUSAN", "INCHEON"],
            "INDIA": ["NEW DELHI", "MUMBAI", "BANGALORE", "KOLKATA", "CHENNAI"],
            "UAE": ["DUBAI", "ABU DHABI"],
            "THAILAND": ["BANGKOK", "CHIANG MAI", "PHUKET"],
            "VIETNAM": ["HANOI", "HO CHI MINH", "DA NANG"],
            "INDONESIA": ["JAKARTA", "SURABAYA", "BALI"],
            "PHILIPPINES": ["MANILA", "CEBU"],
            "SINGAPORE": ["SINGAPORE"],
            "TURKEY": ["ISTANBUL", "ANKARA", "IZMIR"]
        },
        "AFRICA": {
            "EGYPT": ["CAIRO", "ALEXANDRIA", "LUXOR"],
            "SOUTH AFRICA": ["PRETORIA", "CAPE TOWN", "JOHANNESBURG", "DURBAN"],
            "MOROCCO": ["CASABLANCA", "MARRAKESH", "RABAT"],
            "KENYA": ["NAIROBI", "MOMBASA"],
            "NIGERIA": ["LAGOS", "ABUJA", "KANO"],
            "GHANA": ["ACCRA", "KUMASI"],
            "SENEGAL": ["DAKAR"],
            "ETHIOPIA": ["ADDIS ABABA"],
            "TANZANIA": ["DAR ES SALAAM", "ZANZIBAR"]
        },
        "OCEANIA": {
            "AUSTRALIA": ["CANBERRA", "SYDNEY", "MELBOURNE", "PERTH", "BRISBANE", "ADELAIDE"],
            "NEW ZEALAND": ["WELLINGTON", "AUCKLAND", "CHRISTCHURCH", "QUEENSTOWN"],
            "FIJI": ["SUVA", "NADI"],
            "PAPUA NEW GUINEA": ["PORT MORESBY"]
        }
    }
    win["continents"] = list(win["locations"].keys())
    
    win["cont_idx"] = 0
    win["ctry_idx"] = 0
    win["city_idx"] = 0
    win["cache"] = {}
    
    if os.path.isfile(SAVE_PATH):
        try:
            with open(SAVE_PATH) as f:
                saved = json.load(f)
                win["cont_idx"] = saved.get("cont_idx", 0)
                win["ctry_idx"] = saved.get("ctry_idx", 0)
                win["city_idx"] = saved.get("city_idx", 0)
                win["cache"] = saved.get("cache", {})
                
                # Sicherheits-Checks: Bounds Validation
                if win["cont_idx"] >= len(win["continents"]): 
                    win["cont_idx"] = 0
                
                curr_cont = win["continents"][win["cont_idx"]]
                countries = list(win["locations"][curr_cont].keys())
                
                if win["ctry_idx"] >= len(countries): 
                    win["ctry_idx"] = 0
                
                curr_ctry = countries[win["ctry_idx"]]
                cities = win["locations"][curr_cont][curr_ctry]
                
                if win["city_idx"] >= len(cities): 
                    win["city_idx"] = 0
                    
        except Exception:
            pass

    win["result"] = ""
    win["weather_data"] = None
    win["loading"] = False
    
    # --- START-STADT AUS CACHE LADEN (FALLS VORHANDEN) ---
    curr_cont = win["continents"][win["cont_idx"]]
    curr_ctry = list(win["locations"][curr_cont].keys())[win["ctry_idx"]]
    city = win["locations"][curr_cont][curr_ctry][win["city_idx"]]
    cdata = win["cache"].get(city)
    
    if cdata and (time.time() - cdata.get("timestamp", 0) < 1800): # 30 Minuten
        win["weather_data"] = cdata["data"]
        win["result"] = f"{cdata['data']['temp']} C"
    else:
        # AUTO-FETCH BEIM START
        win["loading"] = True
        win["result"] = "LOADING..."
        t = threading.Thread(target=fetch_weather, args=(win, city))
        t.daemon = True
        t.start()
    
    # Y-Koordinaten für Button und Navigation anpassen
    win["btn_x"] = 8
    win["btn_y"] = 60
    win["btn_w"] = 40
    win["btn_h"] = 14
    win["btn_hover"] = False

def update(win, lx, ly, m_pressed, m_sec_pressed, m_held):
    import py16
    
    if "emitter" not in win:
        win["emitter"] = py16.Emitter(
            x=win.get("x", 0) + win.get("w", 140) // 2,
            y=win.get("y", 0) + 14,
            rate=0, life=40, vy=1,
            color_list=[7], size=1, blend="normal"
        )

    if win.get("loading"): return
    
    bx, by, bw, bh = win["btn_x"], win["btn_y"], win["btn_w"], win["btn_h"]
    win["btn_hover"] = (bx <= lx <= bx + bw and by <= ly <= by + bh)

    do_fetch = False
    city_changed = False
    
    curr_cont = win["continents"][win["cont_idx"]]
    countries = list(win["locations"][curr_cont].keys())
    curr_ctry = countries[win["ctry_idx"]]
    cities = win["locations"][curr_cont][curr_ctry]
    
    # --- MAUS STEUERUNG (OS-konform via lx, ly, m_pressed) ---
    if m_pressed:
        if win["btn_hover"]:
            do_fetch = True
            
        # Hitbox: Kontinent (< / >)
        elif 4 <= lx <= 24 and 14 <= ly <= 24:
            win["cont_idx"] = (win["cont_idx"] - 1) % len(win["continents"])
            win["ctry_idx"] = 0
            win["city_idx"] = 0
            city_changed = True
        elif 110 <= lx <= 134 and 14 <= ly <= 24:
            win["cont_idx"] = (win["cont_idx"] + 1) % len(win["continents"])
            win["ctry_idx"] = 0
            win["city_idx"] = 0
            city_changed = True
            
        # Hitbox: Land (< / >)
        elif 4 <= lx <= 24 and 26 <= ly <= 36:
            win["ctry_idx"] = (win["ctry_idx"] - 1) % len(countries)
            win["city_idx"] = 0
            city_changed = True
        elif 110 <= lx <= 134 and 26 <= ly <= 36:
            win["ctry_idx"] = (win["ctry_idx"] + 1) % len(countries)
            win["city_idx"] = 0
            city_changed = True
            
        # Hitbox: Stadt (< / >)
        elif 4 <= lx <= 24 and 38 <= ly <= 48:
            win["city_idx"] = (win["city_idx"] - 1) % len(cities)
            city_changed = True
        elif 110 <= lx <= 134 and 38 <= ly <= 48:
            win["city_idx"] = (win["city_idx"] + 1) % len(cities)
            city_changed = True

    if city_changed:
        win["result"] = ""
        win["weather_data"] = None
        save_config(win)
        
        # --- STADT WECHSEL: CACHE PRÜFEN ---
        curr_cont = win["continents"][win["cont_idx"]]
        curr_ctry = list(win["locations"][curr_cont].keys())[win["ctry_idx"]]
        city = win["locations"][curr_cont][curr_ctry][win["city_idx"]]
        cdata = win["cache"].get(city)
        
        if cdata and (time.time() - cdata.get("timestamp", 0) < 1800):
            win["weather_data"] = cdata["data"]
            win["result"] = f"{cdata['data']['temp']} C"
        else:
            win["loading"] = True
            win["result"] = "LOADING..."
            t = threading.Thread(target=fetch_weather, args=(win, city))
            t.daemon = True
            t.start()

    if do_fetch:
        curr_cont = win["continents"][win["cont_idx"]]
        curr_ctry = list(win["locations"][curr_cont].keys())[win["ctry_idx"]]
        city = win["locations"][curr_cont][curr_ctry][win["city_idx"]]
        
        win["loading"] = True
        win["result"] = "LOADING..."
        
        t = threading.Thread(target=fetch_weather, args=(win, city))
        t.daemon = True
        t.start()

    # --- PARTIKEL-STEUERUNG ---
    temp_val = 15
    if win.get("weather_data"):
        temp_val = win["weather_data"]["temp"]

    emitter = win["emitter"]
    emitter.x = win.get("x", 0) + win.get("w", 140) // 2
    
    if temp_val < 5:  # KALT
        emitter.y = win.get("y", 0) + 14
        emitter.color_list = [7, 6]
        emitter.vy = 0.5
        emitter.vx_var = 0.3
        emitter.rate = 1
    elif temp_val > 22:  # HEISS
        emitter.y = win.get("y", 0) + win.get("h", APP["h"]) - 4
        emitter.color_list = [10, 9]
        emitter.vy = -0.6
        emitter.vx_var = 0.4
        emitter.rate = 1
    else:
        emitter.rate = 0

    emitter.update()
    py16.particles_update()

def draw(win, wx, wy, ww, wh, is_active):
    import py16
    
    content_y = wy + 14
    content_h = wh - 14
    
    # 1. Dynamischer Hintergrund
    bg_color = 1
    wdata = win.get("weather_data")
    if wdata:
        t = wdata["temp"]
        if t < 5: bg_color = 13
        elif t > 22: bg_color = 2
            
    py16.rectfill(wx + 2, content_y, ww - 4, content_h - 2, bg_color)
    
    # 2. Partikel (geclipt auf Fenstergröße)
    py16.clip(wx + 2, content_y, ww - 4, content_h - 2)
    py16.particles_draw()
    py16.clip()
    
    # 3. Hierarchische Navigation
    curr_cont = win["continents"][win["cont_idx"]]
    countries = list(win["locations"][curr_cont].keys())
    curr_ctry = countries[win["ctry_idx"]]
    curr_city = win["locations"][curr_cont][curr_ctry][win["city_idx"]]
    
    # Zeile 1: Kontinent
    py16.text("<", wx + 8, content_y + 4, 7)
    py16.text(">", wx + 124, content_y + 4, 7)
    cw1 = len(curr_cont) * 4
    py16.text(curr_cont, wx + (ww - cw1) // 2, content_y + 4, 6)
    
    # Zeile 2: Land
    py16.text("<", wx + 8, content_y + 16, 7)
    py16.text(">", wx + 124, content_y + 16, 7)
    cw2 = len(curr_ctry) * 4
    py16.text(curr_ctry, wx + (ww - cw2) // 2, content_y + 16, 6)
    
    # Zeile 3: Stadt (Hervorgehoben in Gelb/10)
    py16.text("<", wx + 8, content_y + 28, 7)
    py16.text(">", wx + 124, content_y + 28, 7)
    cw3 = len(curr_city) * 4
    py16.text(curr_city, wx + (ww - cw3) // 2, content_y + 28, 10)
    
    # 4. Button
    bx, by, bw, bh = wx + win["btn_x"], wy + win["btn_y"], win["btn_w"], win["btn_h"]
    btn_color = 5 if win.get("loading") else (13 if win.get("btn_hover") else 12)
    
    py16.rectfill(bx, by, bw, bh, btn_color)
    py16.rect(bx, by, bw, bh, 7 if is_active else 5)
    py16.text("UPDATE", bx + 8, by + 4, 7)
    
    # Resultat Text (Temperatur)
    res_color = 9 if win["loading"] else 11
    py16.text(win.get("result", ""), bx + bw + 8, by + 4, res_color)
    
    # 5. Erweiterte Daten & Tages-Graph
    if wdata:
        py16.text(wdata["cond"], wx + 8, by + 16, 7)
        
        gx, gy, gw, gh = wx + 8, by + 26, ww - 16, 40
        py16.rectfill(gx, gy, gw, gh, 0)
        py16.rect(gx, gy, gw, gh, 5)
        
        graph = wdata["graph"]
        if graph:
            min_t, max_t = min(graph), max(graph)
            range_t = max(1, max_t - min_t)
            
            pts = []
            step_x = (gw - 4) / max(1, len(graph) - 1)
            for i, t in enumerate(graph):
                px = gx + 2 + i * step_x
                py = gy + gh - 4 - ((t - min_t) / range_t) * (gh - 8)
                pts.append((px, py))
                
            for i in range(len(pts) - 1):
                py16.line(int(pts[i][0]), int(pts[i][1]), int(pts[i+1][0]), int(pts[i+1][1]), 10)
                py16.pset(int(pts[i][0]), int(pts[i][1]), 7)
            
            py16.pset(int(pts[-1][0]), int(pts[-1][1]), 7)
            
            py16.text(f"{max_t}", gx + 4, gy + 4, 6)
            py16.text(f"{min_t}", gx + 4, gy + gh - 8, 6)
            py16.text("TODAY", gx + gw - 24, gy + 4, 5)
