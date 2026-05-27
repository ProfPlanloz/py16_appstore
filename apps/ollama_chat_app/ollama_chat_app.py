# apps/ollamachat.py
import urllib.request
import json
import threading
import os

APP = {
    "id": "ollamachat",
    "name": "OLLAMA",
    "w": 230,
    "h": 190,
    "resizable": False
}

# --- KEYBOARD LAYOUT ---
KEYS_L1 = ['Q','W','E','R','T','Z','U','I','O','P']
KEYS_L2 = ['A','S','D','F','G','H','J','K','L','-']
KEYS_L3 = ['Y','X','C','V','B','N','M',',','.','?']
TOKENS = [256, 512, 1024, 2048, 4096, 8192]

SAVE_FILE = "ollama_save.json"
CHATLOG_FILE = "ollama_chatlog.json"

# --- PERSISTENCE LOGIC ---
def load_settings(win):
    if os.path.isfile(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r") as f:
                data = json.load(f)
                win["temp"] = max(0.0, min(2.0, data.get("temp", 0.8)))
                win["token_idx"] = max(0, min(len(TOKENS)-1, data.get("token_idx", 3)))
                win["sys_prompt"] = data.get("sys_prompt", "")[:85]
                win["use_memory"] = data.get("use_memory", True)
        except Exception:
            pass

def save_settings(win):
    try:
        data = {
            "temp": win["temp"],
            "token_idx": win["token_idx"],
            "sys_prompt": win["sys_prompt"],
            "use_memory": win["use_memory"]
        }
        with open(SAVE_FILE, "w") as f:
            json.dump(data, f)
    except Exception:
        pass

def save_chat_history(win):
    try:
        with open(CHATLOG_FILE, "w") as f:
            json.dump({"chat_log": win["chat_lines"]}, f, indent=4)
        add_chat(win, "SYS: CHAT SAVED TO OLLAMA_CHATLOG.JSON")
    except Exception:
        add_chat(win, "SYS: ERROR SAVING CHAT.")

# --- STARTUP CHECK & PULL LOGIC ---
def initial_check(win):
    try:
        req = urllib.request.Request("http://localhost:11434/api/tags")
        with urllib.request.urlopen(req, timeout=2) as res:
            data = json.loads(res.read().decode())
            models = [x["name"] for x in data.get("models", [])]
            if models:
                win["models"] = models
                win["model_idx"] = 0
                win["status"] = f"{len(models)} MODELS READY"
                win["view"] = "chat"
            else:
                win["view"] = "missing_models"
    except Exception:
        win["view"] = "missing_ollama"

def pull_model(win):
    try:
        req = urllib.request.Request("http://localhost:11434/api/pull", method="POST")
        req.add_header("Content-Type", "application/json")
        payload = json.dumps({"name": "tinyllama", "stream": False}).encode()
        with urllib.request.urlopen(req, data=payload, timeout=600) as res:
            pass
        # Once finished, re-check to load the new model
        initial_check(win)
    except Exception:
        win["view"] = "pull_error"

# --- INIT LOGIC ---
def init(win):
    win["view"] = "loading"
    win["models"] = ["NO MODELS"]
    win["model_idx"] = 0
    win["status"] = "CONNECTING..."
    
    win["input_text"] = ""
    win["chat_lines"] = ["SYS: WELCOME! SEARCHING OLLAMA..."]
    win["is_thinking"] = False
    win["scroll_y"] = 0
    win["context"] = [] 
    
    win["temp"] = 0.8
    win["token_idx"] = 3
    win["sys_prompt"] = ""
    win["use_memory"] = True
    
    load_settings(win)
    threading.Thread(target=initial_check, args=(win,), daemon=True).start()

def send_prompt(win):
    if win["is_thinking"]: return
    prompt = win["input_text"].strip()
    if not prompt: return
    
    model = win["models"][win["model_idx"]]
    if model == "NO MODELS": return

    add_chat(win, "YOU: " + prompt.upper())
    win["input_text"] = ""
    win["is_thinking"] = True
    win["status"] = "AI THINKING..."
    
    sys_p = win["sys_prompt"].strip()
    temp = win["temp"]
    max_t = TOKENS[win["token_idx"]]
    ctx = win["context"] if win["use_memory"] else []
    
    threading.Thread(target=generate_response, args=(win, model, prompt, sys_p, temp, max_t, ctx), daemon=True).start()

def generate_response(win, model, prompt, sys_prompt, temp, max_tokens, ctx):
    try:
        req = urllib.request.Request("http://localhost:11434/api/generate", method="POST")
        req.add_header("Content-Type", "application/json")
        
        payload_dict = {
            "model": model, 
            "prompt": prompt, 
            "stream": False,
            "options": {"temperature": temp, "num_predict": max_tokens}
        }
        if sys_prompt: payload_dict["system"] = sys_prompt
        if ctx: payload_dict["context"] = ctx
            
        payload = json.dumps(payload_dict).encode()
        
        with urllib.request.urlopen(req, data=payload, timeout=120) as res:
            resp = json.loads(res.read().decode())
            answer = resp.get("response", "Empty response.")
            
            if win["use_memory"]:
                win["context"] = resp.get("context", [])
                
            add_chat(win, "AI:  " + answer)
            win["status"] = "READY"
    except Exception as e:
        add_chat(win, "SYS: ERROR - " + str(e)[:30])
        win["status"] = "NETWORK ERROR"
        
    win["is_thinking"] = False

def add_chat(win, text):
    words = text.split(" ")
    current = ""
    for w in words:
        if len(current) + len(w) + 1 > 46:
            win["chat_lines"].append(current)
            current = w
        else:
            current = current + " " + w if current else w
    if current:
        win["chat_lines"].append(current)
    
    max_scroll = max(0, len(win["chat_lines"]) - 9)
    win["scroll_y"] = max_scroll

# --- UPDATE LOGIC ---
def update(win, lx, ly, mp, msp, mh):
    if not mp: return
    
    v = win["view"]
    if v == "chat":
        update_chat(win, lx, ly)
    elif v == "settings":
        update_settings(win, lx, ly)
    elif v == "missing_ollama":
        update_missing_ollama(win, lx, ly)
    elif v == "install_info":
        update_install_info(win, lx, ly)
    elif v == "missing_models":
        update_missing_models(win, lx, ly)
    elif v == "pull_error":
        update_pull_error(win, lx, ly)
    # views "loading" and "pulling" block inputs!

def update_missing_ollama(win, lx, ly):
    import py16
    if 90 <= ly <= 110:
        if 40 <= lx <= 100: # YES
            win["view"] = "install_info"
            py16.tone(500, 15, py16.WAVE_SQUARE)
        elif 130 <= lx <= 190: # NO
            win["view"] = "chat"
            py16.tone(300, 15, py16.WAVE_SQUARE)

def update_install_info(win, lx, ly):
    import py16
    if 110 <= ly <= 130:
        if 40 <= lx <= 100: # BACK
            win["view"] = "missing_ollama"
            py16.tone(400, 15, py16.WAVE_SQUARE)
        elif 130 <= lx <= 190: # RETRY
            win["view"] = "loading"
            threading.Thread(target=initial_check, args=(win,), daemon=True).start()
            py16.tone(600, 15, py16.WAVE_SQUARE)

def update_missing_models(win, lx, ly):
    import py16
    if 100 <= ly <= 120:
        if 40 <= lx <= 100: # YES
            win["view"] = "pulling"
            threading.Thread(target=pull_model, args=(win,), daemon=True).start()
            py16.tone(500, 15, py16.WAVE_SQUARE)
        elif 130 <= lx <= 190: # NO
            win["view"] = "chat"
            py16.tone(300, 15, py16.WAVE_SQUARE)

def update_pull_error(win, lx, ly):
    import py16
    if 80 <= lx <= 150 and 110 <= ly <= 130: # CONTINUE
        win["view"] = "chat"
        py16.tone(400, 15, py16.WAVE_SQUARE)

def update_chat(win, lx, ly):
    import py16
    
    if 6 <= lx <= 20 and 16 <= ly <= 26:
        win["model_idx"] = (win["model_idx"] - 1) % len(win["models"])
        win["context"] = [] 
        py16.tone(600, 20, py16.WAVE_SQUARE)
    elif 134 <= lx <= 148 and 16 <= ly <= 26:
        win["model_idx"] = (win["model_idx"] + 1) % len(win["models"])
        win["context"] = []
        py16.tone(600, 20, py16.WAVE_SQUARE)
        
    if 214 <= lx <= 224:
        if 30 <= ly <= 44: win["scroll_y"] = max(0, win["scroll_y"] - 1)
        elif 74 <= ly <= 88: win["scroll_y"] = min(max(0, len(win["chat_lines"]) - 9), win["scroll_y"] + 1)

    if ly >= 110:
        if handle_keyboard_typing(win, lx, ly, "input_text", 46): return
        
        row = (ly - 110) // 18
        if row == 3:
            if 6 <= lx <= 32: # LOG
                save_chat_history(win)
                py16.tone(400, 15, py16.WAVE_SQUARE)
            elif 36 <= lx <= 62: # CLR 
                win["chat_lines"] = ["SYS: CHAT & MEMORY CLEARED."]
                win["context"] = []
                win["scroll_y"] = 0
                py16.tone(300, 20, py16.WAVE_NOISE)
            elif 66 <= lx <= 92: # SYS 
                win["bak_temp"] = win["temp"]
                win["bak_token_idx"] = win["token_idx"]
                win["bak_sys"] = win["sys_prompt"]
                win["bak_mem"] = win["use_memory"]
                win["view"] = "settings"
                py16.tone(500, 15, py16.WAVE_SQUARE)
            elif 96 <= lx <= 140: # SPACE
                if len(win["input_text"]) < 46:
                    win["input_text"] += " "
                    py16.tone(700, 10, py16.WAVE_TRIANGLE)
            elif 144 <= lx <= 174: # DEL
                win["input_text"] = win["input_text"][:-1]
                py16.tone(300, 15, py16.WAVE_NOISE)
            elif 178 <= lx <= 224: # SEND
                send_prompt(win)
                py16.tone(900, 30, py16.WAVE_SQUARE)

def update_settings(win, lx, ly):
    import py16
    
    if 30 <= ly <= 44:
        if 36 <= lx <= 48: 
            win["temp"] = max(0.0, round(win["temp"] - 0.1, 1))
            py16.tone(600, 15, py16.WAVE_SQUARE)
        elif 74 <= lx <= 86: 
            win["temp"] = min(2.0, round(win["temp"] + 0.1, 1))
            py16.tone(600, 15, py16.WAVE_SQUARE)
        elif 144 <= lx <= 156: 
            win["token_idx"] = max(0, win["token_idx"] - 1)
            py16.tone(600, 15, py16.WAVE_SQUARE)
        elif 194 <= lx <= 206: 
            win["token_idx"] = min(len(TOKENS) - 1, win["token_idx"] + 1)
            py16.tone(600, 15, py16.WAVE_SQUARE)

    if 50 <= ly <= 64:
        if 180 <= lx <= 216:
            win["use_memory"] = not win["use_memory"]
            if not win["use_memory"]: win["context"] = [] 
            py16.tone(500, 15, py16.WAVE_SQUARE)

    if ly >= 110:
        if handle_keyboard_typing(win, lx, ly, "sys_prompt", 85): return
        
        row = (ly - 110) // 18
        if row == 3:
            if 6 <= lx <= 32: # ESC
                win["temp"] = win.get("bak_temp", 0.8)
                win["token_idx"] = win.get("bak_token_idx", 3)
                win["sys_prompt"] = win.get("bak_sys", "")
                win["use_memory"] = win.get("bak_mem", True)
                win["view"] = "chat"
                py16.tone(400, 15, py16.WAVE_SQUARE)
            elif 36 <= lx <= 140: # SPACE
                if len(win["sys_prompt"]) < 85:
                    win["sys_prompt"] += " "
                    py16.tone(700, 10, py16.WAVE_TRIANGLE)
            elif 144 <= lx <= 174: # DEL
                win["sys_prompt"] = win["sys_prompt"][:-1]
                py16.tone(300, 15, py16.WAVE_NOISE)
            elif 178 <= lx <= 224: # OK
                save_settings(win)
                add_chat(win, "SYS: SETTINGS SAVED.")
                win["view"] = "chat"
                py16.tone(900, 30, py16.WAVE_SQUARE)

def handle_keyboard_typing(win, lx, ly, target_key, max_len):
    import py16
    row = (ly - 110) // 18
    if row < 3:
        col = (lx - 6) // 22
        keys = [KEYS_L1, KEYS_L2, KEYS_L3][row]
        if 0 <= col < len(keys):
            char = keys[col].lower()
            if len(win[target_key]) < max_len:
                win[target_key] += char
                py16.tone(800, 10, py16.WAVE_TRIANGLE)
        return True
    return False

# --- DRAW LOGIC ---
def draw(win, wx, wy, ww, wh, active):
    import py16
    py16.rectfill(wx, wy+14, ww, wh-14, 6)
    
    v = win["view"]
    if v == "chat":
        draw_chat(win, wx, wy)
        draw_keyboard(win, wx, wy, mode="chat")
    elif v == "settings":
        draw_settings(win, wx, wy)
        draw_keyboard(win, wx, wy, mode="settings")
    elif v == "loading":
        py16.text("CONNECTING TO OLLAMA...", wx+40, wy+80, 1)
    elif v == "missing_ollama":
        draw_missing_ollama(win, wx, wy)
    elif v == "install_info":
        draw_install_info(win, wx, wy)
    elif v == "missing_models":
        draw_missing_models(win, wx, wy)
    elif v == "pulling":
        py16.text("DOWNLOADING TINYLLAMA...", wx+26, wy+80, 1)
        py16.text("PLEASE WAIT...", wx+70, wy+100, 5)
        dots = "." * ((py16.t() // 15) % 4)
        py16.text("PULLING" + dots, wx+86, wy+130, 11)
    elif v == "pull_error":
        py16.rectfill(wx+4, wy+16, 222, 11, 8)
        py16.text("PULL ERROR", wx+80, wy+19, 7)
        py16.text("COULD NOT DOWNLOAD MODEL.", wx+10, wy+50, 1)
        py16.rectfill(wx+80, wy+110, 70, 20, 5)
        py16.text("CONTINUE", wx+96, wy+117, 7)

def draw_missing_ollama(win, wx, wy):
    import py16
    py16.rectfill(wx+4, wy+16, 222, 11, 8) 
    py16.text("ERROR: OLLAMA NOT DETECTED", wx+20, wy+19, 7)
    py16.text("COULD NOT REACH LOCALHOST:11434.", wx+10, wy+40, 1)
    py16.text("DO YOU WANT TO INSTALL OLLAMA?", wx+10, wy+60, 1)
    
    py16.rectfill(wx+40, wy+90, 60, 20, 11) 
    py16.text("YES", wx+60, wy+97, 1)
    py16.rectfill(wx+130, wy+90, 60, 20, 8) 
    py16.text("NO", wx+154, wy+97, 7)

def draw_install_info(win, wx, wy):
    import py16
    py16.rectfill(wx+4, wy+16, 222, 11, 2)
    py16.text("INSTALL INSTRUCTIONS", wx+40, wy+19, 7)
    py16.text("OPEN A TERMINAL ON YOUR PC:", wx+10, wy+40, 1)
    py16.rectfill(wx+10, wy+55, 210, 30, 0)
    py16.text("curl -fsSL https://ollama.com/", wx+14, wy+60, 10)
    py16.text("install.sh | sh", wx+14, wy+70, 10)
    
    py16.rectfill(wx+40, wy+110, 60, 20, 5) 
    py16.text("BACK", wx+56, wy+117, 7)
    py16.rectfill(wx+130, wy+110, 60, 20, 11) 
    py16.text("RETRY", wx+146, wy+117, 1)

def draw_missing_models(win, wx, wy):
    import py16
    py16.rectfill(wx+4, wy+16, 222, 11, 9) 
    py16.text("WARNING: NO MODELS FOUND", wx+20, wy+19, 7)
    py16.text("OLLAMA IS RUNNING, BUT EMPTY.", wx+10, wy+40, 1)
    py16.text("PULL 'TINYLLAMA' NOW?", wx+10, wy+60, 1)
    py16.text("(FASTEST DOWNLOAD, ~650MB)", wx+10, wy+75, 5)
    
    py16.rectfill(wx+40, wy+100, 60, 20, 11) 
    py16.text("YES", wx+60, wy+107, 1)
    py16.rectfill(wx+130, wy+100, 60, 20, 8) 
    py16.text("NO", wx+154, wy+107, 7)

def draw_chat(win, wx, wy):
    import py16
    py16.rectfill(wx+4, wy+16, 146, 11, 5)
    py16.rectfill(wx+6, wy+17, 12, 9, 12)
    py16.text("<", wx+10, wy+19, 7)
    
    active_mod = win["models"][win["model_idx"]]
    if len(active_mod) > 17: active_mod = active_mod[:15] + ".."
    py16.text(active_mod, wx+24, wy+19, 7)
    
    py16.rectfill(wx+134, wy+17, 12, 9, 12)
    py16.text(">", wx+138, wy+19, 7)
    
    color_status = 10 if win["is_thinking"] else (11 if win["use_memory"] else 9)
    py16.rectfill(wx+154, wy+16, 72, 11, 0)
    py16.text(win["status"][:16], wx+156, wy+19, color_status)

    py16.rectfill(wx+4, wy+30, 206, 58, 0)
    
    py16.rectfill(wx+214, wy+30, 12, 14, 5)
    py16.text("^", wx+218, wy+35, 7)
    py16.rectfill(wx+214, wy+74, 12, 14, 5)
    py16.text("v", wx+218, wy+79, 7)
    
    py16.clip(wx+6, wy+32, 202, 54)
    y_offset = 0
    start_idx = win["scroll_y"]
    for i in range(start_idx, min(len(win["chat_lines"]), start_idx + 9)):
        line = win["chat_lines"][i]
        col = 11 if line.startswith("AI:") else (10 if line.startswith("YOU:") else 6)
        py16.text(line, wx+6, wy+32 + y_offset, col)
        y_offset += 6
    py16.clip()
    
    py16.rectfill(wx+4, wy+92, 222, 14, 1)
    py16.text("> " + win["input_text"].upper() + ("_" if (py16.t() // 15) % 2 == 0 else ""), wx+6, wy+97, 7)

def draw_settings(win, wx, wy):
    import py16
    py16.rectfill(wx+4, wy+16, 222, 11, 2)
    py16.text("SYSTEM SETTINGS", wx+60, wy+19, 7)
    
    py16.text("TEMP:", wx+6, wy+34, 1)
    py16.rectfill(wx+36, wy+30, 12, 14, 5)
    py16.text("<", wx+40, wy+35, 7)
    py16.text(f"{win['temp']:.1f}", wx+52, wy+34, 1)
    py16.rectfill(wx+74, wy+30, 12, 14, 5)
    py16.text(">", wx+78, wy+35, 7)
    
    py16.text("TOKENS:", wx+96, wy+34, 1)
    py16.rectfill(wx+144, wy+30, 12, 14, 5)
    py16.text("<", wx+148, wy+35, 7)
    py16.text(str(TOKENS[win['token_idx']]), wx+160, wy+34, 1)
    py16.rectfill(wx+194, wy+30, 12, 14, 5)
    py16.text(">", wx+198, wy+35, 7)

    py16.text("CHAT MEMORY (CONTEXT):", wx+6, wy+54, 1)
    if win["use_memory"]:
        py16.rectfill(wx+180, wy+50, 36, 14, 11) 
        py16.text(" ON ", wx+184, wy+55, 1)
    else:
        py16.rectfill(wx+180, wy+50, 36, 14, 8)  
        py16.text(" OFF", wx+184, wy+55, 7)

    py16.text("SYSTEM PROMPT:", wx+6, wy+72, 1)
    py16.rectfill(wx+4, wy+80, 222, 26, 5) 
    
    sys_txt = win["sys_prompt"].upper() + ("_" if (py16.t() // 15) % 2 == 0 else "")
    if len(sys_txt) <= 44:
        py16.text(sys_txt, wx+6, wy+84, 7) 
    else:
        py16.text(sys_txt[:44], wx+6, wy+84, 7)
        py16.text(sys_txt[44:88], wx+6, wy+94, 7)

def draw_keyboard(win, wx, wy, mode):
    import py16
    kbd_y = wy + 110
    
    def draw_row(keys, row_idx):
        for i, key in enumerate(keys):
            kx = wx + 6 + (i * 22)
            ky = kbd_y + (row_idx * 18)
            py16.rectfill(kx, ky, 20, 16, 7)
            py16.rect(kx, ky, 20, 16, 5)
            py16.text(key, kx+8, ky+6, 1)

    draw_row(KEYS_L1, 0)
    draw_row(KEYS_L2, 1)
    draw_row(KEYS_L3, 2)
    
    row3_y = kbd_y + 54
    
    if mode == "chat":
        py16.rectfill(wx+6, row3_y, 26, 16, 9)
        py16.text("LOG", wx+10, row3_y+6, 7)
        py16.rectfill(wx+36, row3_y, 26, 16, 8) 
        py16.text("CLR", wx+40, row3_y+6, 7)
        py16.rectfill(wx+66, row3_y, 26, 16, 2)
        py16.text("SYS", wx+70, row3_y+6, 7)
        py16.rectfill(wx+96, row3_y, 44, 16, 7)
        py16.text("SPACE", wx+102, row3_y+6, 1)
        py16.rectfill(wx+144, row3_y, 30, 16, 5)
        py16.text("DEL", wx+150, row3_y+6, 7)
        py16.rectfill(wx+178, row3_y, 46, 16, 11)
        py16.text("SEND", wx+184, row3_y+6, 1)
    else:
        py16.rectfill(wx+6, row3_y, 26, 16, 8)
        py16.text("ESC", wx+10, row3_y+6, 7)
        py16.rectfill(wx+36, row3_y, 104, 16, 7)
        py16.text("SPACE", wx+74, row3_y+6, 1)
        py16.rectfill(wx+144, row3_y, 30, 16, 5)
        py16.text("DEL", wx+150, row3_y+6, 7)
        py16.rectfill(wx+178, row3_y, 46, 16, 10) 
        py16.text("OK", wx+194, row3_y+6, 1)
