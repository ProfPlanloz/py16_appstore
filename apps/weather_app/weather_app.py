import threading
import urllib.request
import json
import os
import time

# Fensterhöhe (160) für drei Navi-Zeilen, Graph und Tages-Tabs
APP = {
    "id": "weather",
    "name": "WEATHER",
    "w": 140,
    "h": 160,
    "resizable": False,
    "icon": "weather_app.p16img"
}
SAVE_PATH = "weather_save.json"

# Schützt das parallele Schreiben der Save-Datei aus Worker- und Main-Thread.
_save_lock = threading.Lock()


def _normalize_wd(data):
    """Migriert alle bisherigen Cache-Formate auf das aktuelle days_C/days_F-Schema.

    - Uralt:   {temp, graph}
    - Vorgänger: {temp_C, temp_F, graph_C, graph_F}
    - Aktuell:  {temp_C, temp_F, days_C, days_F, day_labels}
    """
    # Uraltformat (eine Einheit, ein Tag)
    if "temp_C" not in data:
        c = data.get("temp", 0)
        graph = data.get("graph", [])
        return {
            "temp_C": c,
            "temp_F": round(c * 9 / 5 + 32),
            "cond": data.get("cond", ""),
            "days_C": [graph] if graph else [[]],
            "days_F": [[round(x * 9 / 5 + 32) for x in graph]] if graph else [[]],
            "day_labels": ["TODAY"],
        }
    # Vorgängerformat: hatte nur einen Tag in graph_C/graph_F
    if "days_C" not in data:
        gc = data.get("graph_C", [])
        gf = data.get("graph_F", [])
        data = dict(data)
        data["days_C"] = [gc] if gc else [[]]
        data["days_F"] = [gf] if gf else [[]]
        data["day_labels"] = data.get("day_labels", ["TODAY"])
        return data
    return data


# Wochentags-Kürzel für die Tages-Tabs (time.strptime: Montag = 0)
_WD = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]


def draw_weather_icon(py16, ix, iy, cond):
    """Zeichnet ein ~16x16 Wetter-Icon (Top-Left = ix, iy) nur mit py-16-Primitiven."""
    cx, cy = ix + 8, iy + 8

    def cloud(ox, oy, c):
        py16.circfill(ox + 4, oy + 8, 3, c)
        py16.circfill(ox + 8, oy + 7, 4, c)
        py16.circfill(ox + 11, oy + 9, 3, c)
        py16.rectfill(ox + 4, oy + 8, 8, 3, c)

    def sun(scx, scy, r, core, ray):
        py16.circfill(scx, scy, r, core)
        for dx, dy in ((0, -1), (0, 1), (-1, 0), (1, 0)):
            py16.line(scx + dx * (r + 1), scy + dy * (r + 1),
                      scx + dx * (r + 3), scy + dy * (r + 3), ray)

    if "THUNDER" in cond:                                   # Gewitter
        cloud(ix, iy - 1, 5)
        py16.line(cx, iy + 8, cx - 2, iy + 12, 10)
        py16.line(cx - 2, iy + 12, cx + 1, iy + 12, 10)
        py16.line(cx + 1, iy + 12, cx - 1, iy + 15, 10)
    elif any(k in cond for k in ("RAIN", "DRIZZLE", "SHOWER")):  # Regen
        cloud(ix, iy - 1, 6)
        for dx in (-3, 0, 3):
            py16.line(cx + dx, iy + 10, cx + dx - 1, iy + 14, 12)
    elif any(k in cond for k in ("SNOW", "SLEET", "BLIZZARD", "ICE")):  # Schnee
        cloud(ix, iy - 1, 6)
        for dx in (-3, 0, 3):
            py16.pset(cx + dx, iy + 12, 7)
            py16.pset(cx + dx, iy + 14, 7)
    elif any(k in cond for k in ("FOG", "MIST", "HAZE")):   # Nebel
        for i, yy in enumerate((iy + 5, iy + 8, iy + 11, iy + 14)):
            py16.line(ix + 2 + (i % 2), yy, ix + 13 - (i % 2), yy, 6)
    elif any(k in cond for k in ("SUNNY", "CLEAR")):        # Klar
        sun(cx, cy, 4, 10, 9)
    elif "PARTLY" in cond:                                  # Heiter bis wolkig
        sun(ix + 11, iy + 5, 3, 10, 9)
        cloud(ix, iy + 2, 6)
    else:                                                   # bewölkt / generisch
        cloud(ix, iy + 1, 6)


def temp_display(win):
    """Anzeigetext für die Temperatur in der aktuell gewählten Einheit.
    Liegen keine Daten vor, fällt es auf den Status-Text (LOADING/ERROR) zurück."""
    wd = win.get("weather_data")
    if not wd:
        return win.get("result", "")
    if win.get("unit", "C") == "F":
        return f"{wd['temp_F']} F"
    return f"{wd['temp_C']} C"


def start_fetch(win, city):
    """Startet einen Netzwerk-Abruf und vergibt dafür ein eindeutiges Token.
    Nur der Thread mit dem jeweils neuesten Token darf seine Daten committen."""
    win["req_id"] = win.get("req_id", 0) + 1
    win["loading"] = True
    win["result"] = "LOADING..."
    win["weather_data"] = None
    t = threading.Thread(target=fetch_weather, args=(win, city, win["req_id"]))
    t.daemon = True
    t.start()


def fetch_weather(win, city, req_id):
    try:
        url_city = city.replace(" ", "+")
        # j1 returns full JSON data, default language is English
        url = f"https://wttr.in/{url_city}?format=j1"
        req = urllib.request.Request(url, headers={'User-Agent': 'curl/7.68.0'})
        with urllib.request.urlopen(req, timeout=4) as response:
            data = json.loads(response.read().decode('utf-8'))

            # 1. Aktuelle Temperatur (beide Einheiten direkt von wttr.in)
            current = data['current_condition'][0]
            temp_c = int(current['temp_C'])
            temp_f = int(current['temp_F'])

            # 2. Wetterbeschreibung
            cond = "UNKNOWN"
            if 'weatherDesc' in current:
                cond = current['weatherDesc'][0]['value']

            # 3. Tagesverläufe (bis zu 3 Tage, stündliche Werte, beide Einheiten)
            weather = data.get('weather', [])[:3]
            days_c = [[int(h['tempC']) for h in d['hourly']] for d in weather]
            days_f = [[int(h['tempF']) for h in d['hourly']] for d in weather]

            day_labels = []
            for idx, d in enumerate(weather):
                try:
                    wday = time.strptime(d['date'], "%Y-%m-%d").tm_wday
                    day_labels.append("TODAY" if idx == 0 else _WD[wday])
                except Exception:
                    day_labels.append("TODAY" if idx == 0 else f"D{idx + 1}")

            wd = {
                "temp_C": temp_c,
                "temp_F": temp_f,
                "cond": cond.upper()[:16],  # Shorten text if too long
                "days_C": days_c if days_c else [[]],
                "days_F": days_f if days_f else [[]],
                "day_labels": day_labels if day_labels else ["TODAY"],
            }

        # --- STALE-GUARD: nur committen, wenn dies noch der neueste Request ist ---
        if win.get("req_id") != req_id:
            return

        win["weather_data"] = wd
        win["result"] = ""  # Status leeren -> Temperatur wird angezeigt

        # --- SAVE CACHE ---
        if "cache" not in win:
            win["cache"] = {}
        win["cache"][city] = {
            "timestamp": time.time(),
            "data": wd
        }
        save_config(win)

    except Exception:
        if win.get("req_id") == req_id:
            win["result"] = "ERROR!"
            win["weather_data"] = None

    finally:
        # loading nur freigeben, wenn wir noch der aktuelle Request sind,
        # damit ein veralteter Thread nicht den Ladezustand eines neueren beendet.
        if win.get("req_id") == req_id:
            win["loading"] = False


def save_config(win):
    # Lock + flache Kopie des Caches: verhindert interleaved Writes und
    # "dictionary changed size during iteration", wenn Main- und Worker-Thread
    # gleichzeitig speichern.
    with _save_lock:
        try:
            with open(SAVE_PATH, "w") as f:
                json.dump({
                    "cont_idx": win.get("cont_idx", 0),
                    "ctry_idx": win.get("ctry_idx", 0),
                    "city_idx": win.get("city_idx", 0),
                    "unit": win.get("unit", "C"),
                    "cache": dict(win.get("cache", {}))
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
    win["unit"] = "C"

    if os.path.isfile(SAVE_PATH):
        try:
            with open(SAVE_PATH) as f:
                saved = json.load(f)
                win["cont_idx"] = saved.get("cont_idx", 0)
                win["ctry_idx"] = saved.get("ctry_idx", 0)
                win["city_idx"] = saved.get("city_idx", 0)
                win["unit"] = saved.get("unit", "C")
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
    win["req_id"] = 0
    win["day_idx"] = 0

    # --- START-STADT AUS CACHE LADEN (FALLS VORHANDEN) ---
    curr_cont = win["continents"][win["cont_idx"]]
    curr_ctry = list(win["locations"][curr_cont].keys())[win["ctry_idx"]]
    city = win["locations"][curr_cont][curr_ctry][win["city_idx"]]
    cdata = win["cache"].get(city)

    if cdata and (time.time() - cdata.get("timestamp", 0) < 1800):  # 30 Minuten
        win["weather_data"] = _normalize_wd(cdata["data"])
        win["result"] = ""
    else:
        start_fetch(win, city)  # AUTO-FETCH BEIM START

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

    # --- EINHEIT UMSCHALTEN (Rechtsklick / X) --- auch während des Ladens erlaubt
    if m_sec_pressed:
        win["unit"] = "F" if win.get("unit", "C") == "C" else "C"
        save_config(win)

    if win.get("loading"):
        return

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

        # Hitbox: Tages-Tabs (Forecast) unter dem Graphen
        elif 128 <= ly <= 139:
            wd = win.get("weather_data")
            if wd:
                ndays = max(1, len(wd.get("days_C", [])))
                tab_w = max(1, (win.get("w", 140) - 16) // 3)
                for i in range(ndays):
                    tx0 = 8 + i * tab_w
                    if tx0 <= lx <= tx0 + tab_w - 2:
                        win["day_idx"] = i
                        break

    if city_changed:
        save_config(win)
        win["day_idx"] = 0

        # --- STADT WECHSEL: CACHE PRÜFEN ---
        curr_cont = win["continents"][win["cont_idx"]]
        curr_ctry = list(win["locations"][curr_cont].keys())[win["ctry_idx"]]
        city = win["locations"][curr_cont][curr_ctry][win["city_idx"]]
        cdata = win["cache"].get(city)

        if cdata and (time.time() - cdata.get("timestamp", 0) < 1800):
            win["weather_data"] = _normalize_wd(cdata["data"])
            win["result"] = ""
        else:
            start_fetch(win, city)

    if do_fetch:
        curr_cont = win["continents"][win["cont_idx"]]
        curr_ctry = list(win["locations"][curr_cont].keys())[win["ctry_idx"]]
        city = win["locations"][curr_cont][curr_ctry][win["city_idx"]]
        start_fetch(win, city)  # UPDATE-Button erzwingt frischen Abruf

    # --- PARTIKEL-STEUERUNG ---
    temp_val = 15
    cond = ""
    if win.get("weather_data"):
        temp_val = win["weather_data"]["temp_C"]
        cond = win["weather_data"]["cond"]

    emitter = win["emitter"]
    emitter.x = win.get("x", 0) + win.get("w", 140) // 2
    emitter.blend = "normal"

    is_rain = any(k in cond for k in ("RAIN", "DRIZZLE", "SHOWER"))
    is_snow = any(k in cond for k in ("SNOW", "SLEET", "BLIZZARD"))

    if is_rain:  # REGEN: blaue Tropfen fallen schnell von oben
        emitter.y = win.get("y", 0) + 14
        emitter.color_list = [12, 6]
        emitter.vy = 2.2
        emitter.vx_var = 0.1
        emitter.rate = 2
    elif is_snow or temp_val < 5:  # SCHNEE / KALT
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

    # 1. Dynamischer Hintergrund (immer nach Celsius bewertet)
    bg_color = 1
    wdata = win.get("weather_data")
    if wdata:
        t = wdata["temp_C"]
        if t < 5:
            bg_color = 13
        elif t > 22:
            bg_color = 2

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

    # Resultat Text (Temperatur in gewählter Einheit)
    if win.get("loading"):
        res_color = 9
    elif win.get("result") == "ERROR!":
        res_color = 8
    else:
        res_color = 11
    py16.text(temp_display(win), bx + bw + 8, by + 4, res_color)

    # Wetter-Icon rechts in der Button-Zeile
    if wdata:
        draw_weather_icon(py16, wx + ww - 18, wy + win["btn_y"] - 1, wdata["cond"])

    # 5. Erweiterte Daten, Tages-Graph & Forecast-Tabs
    if wdata:
        py16.text(wdata["cond"], wx + 8, by + 16, 7)

        unit = win.get("unit", "C")
        days = wdata["days_F"] if unit == "F" else wdata["days_C"]
        labels = wdata.get("day_labels") or ["TODAY"]
        ndays = max(1, len(days))

        di = win.get("day_idx", 0)
        if di >= ndays:
            di = 0
        graph = days[di] if days else []

        gx, gy, gw, gh = wx + 8, by + 26, ww - 16, 40
        py16.rectfill(gx, gy, gw, gh, 0)
        py16.rect(gx, gy, gw, gh, 5)

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
            sel_lab = labels[di] if di < len(labels) else f"D{di + 1}"
            py16.text(sel_lab, gx + gw - len(sel_lab) * 4 - 2, gy + 4, 5)

        # Tages-Tabs (klickbar) unter dem Graphen
        tab_w = (ww - 16) // 3
        ty = gy + gh + 2
        for i in range(ndays):
            tx = gx + i * tab_w
            sel = (i == di)
            py16.rectfill(tx, ty, tab_w - 2, 11, 12 if sel else 1)
            py16.rect(tx, ty, tab_w - 2, 11, 7 if sel else 5)
            lab = labels[i] if i < len(labels) else f"D{i + 1}"
            lw = len(lab) * 4
            py16.text(lab, tx + (tab_w - 2 - lw) // 2, ty + 3, 7 if sel else 6)
