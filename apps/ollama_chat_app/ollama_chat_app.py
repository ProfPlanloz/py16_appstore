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
# Page 0: letters. Page 1: numbers + symbols. Both pages are 3 rows of
# 10 keys, so the same hit-test works for either. If your font lacks a
# glyph it just renders blank (no crash) - swap the entry to taste.
KEYS_L1 = ['Q','W','E','R','T','Z','U','I','O','P']
KEYS_L2 = ['A','S','D','F','G','H','J','K','L','-']
KEYS_L3 = ['Y','X','C','V','B','N','M',',','.','?']

SYM_L1  = ['1','2','3','4','5','6','7','8','9','0']
SYM_L2  = ['.',',','?','!',':',';',"'",'"','(',')']
SYM_L3  = ['-','_','/','@','#','&','%','+','=','*']

PAGE_LETTERS = [KEYS_L1, KEYS_L2, KEYS_L3]
PAGE_SYMBOLS = [SYM_L1, SYM_L2, SYM_L3]

TOKENS = [256, 512, 1024, 2048, 4096, 8192]

# How many past messages (user+assistant turns) to send back as context.
# Keeps the request bounded so it never grows past the model's num_ctx.
HISTORY_LIMIT = 20

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
        # Snapshot first: a background thread may append while we serialize.
        snapshot = list(win["chat_lines"])
        log = [text for (_kind, text) in snapshot]
        with open(CHATLOG_FILE, "w") as f:
            json.dump({"chat_log": log}, f, indent=4)
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
        win["pull_pct"] = 0
        win["pull_status"] = "STARTING"
        req = urllib.request.Request("http://localhost:11434/api/pull", method="POST")
        req.add_header("Content-Type", "application/json")
        payload = json.dumps({"name": "tinyllama", "stream": True}).encode()

        with urllib.request.urlopen(req, data=payload, timeout=600) as res:
            for raw in res:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw.decode())
                except Exception:
                    continue
                if "error" in obj:
                    raise RuntimeError(str(obj["error"]))

                status = obj.get("status", "")
                if status:
                    # Keep it short for the tiny font.
                    win["pull_status"] = status.upper()[:24]

                total = obj.get("total")
                completed = obj.get("completed", 0)
                if total:
                    win["pull_pct"] = int(completed * 100 / total)
                elif "success" in status.lower():
                    win["pull_pct"] = 100

        win["pull_pct"] = 100
        win["pull_status"] = "VERIFYING"
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
    win["chat_lines"] = [("sys", "SYS: WELCOME! SEARCHING OLLAMA...")]
    win["is_thinking"] = False
    win["gen_id"] = 0
    win["kbd_page"] = 0
    win["scroll_y"] = 0
    win["messages"] = []   # role/content history for /api/chat
    win["pull_pct"] = 0
    win["pull_status"] = ""
    
    win["temp"] = 0.8
    win["token_idx"] = 3
    win["sys_prompt"] = ""
    win["use_memory"] = True
    
    load_settings(win)
    threading.Thread(target=initial_check, args=(win,), daemon=True).start()

def send_prompt(win):
    if win["is_thinking"]: return False
    prompt = win["input_text"].strip()
    if not prompt: return False

    idx = win["model_idx"] % len(win["models"])
    model = win["models"][idx]
    if model == "NO MODELS": return False

    add_chat(win, "YOU: " + prompt.upper())
    win["input_text"] = ""
    win["is_thinking"] = True
    win["status"] = "AI THINKING..."
    win["gen_id"] = win.get("gen_id", 0) + 1
    gen_id = win["gen_id"]

    sys_p = win["sys_prompt"].strip()
    temp = win["temp"]
    max_t = TOKENS[win["token_idx"]]

    # Build the /api/chat messages payload: optional system prompt, then
    # the trimmed history (only if memory is on), then this turn's prompt.
    messages = []
    if sys_p:
        messages.append({"role": "system", "content": sys_p})
    if win["use_memory"]:
        messages.extend(win["messages"][-HISTORY_LIMIT:])
    messages.append({"role": "user", "content": prompt})

    threading.Thread(target=generate_response, args=(win, gen_id, model, prompt, messages, temp, max_t), daemon=True).start()
    return True

def generate_response(win, gen_id, model, prompt, messages, temp, max_tokens):
    # This worker only owns the UI while it is the current generation.
    # STOP (or a new prompt) bumps win["gen_id"], which retires this one.
    def current():
        return win.get("gen_id") == gen_id

    try:
        req = urllib.request.Request("http://localhost:11434/api/chat", method="POST")
        req.add_header("Content-Type", "application/json")

        payload_dict = {
            "model": model,
            "messages": messages,
            "stream": True,
            "options": {"temperature": temp, "num_predict": max_tokens}
        }

        payload = json.dumps(payload_dict).encode()

        stream_start = len(win["chat_lines"])
        buf = ""
        set_stream_lines(win, stream_start, buf)
        if current(): win["status"] = "STREAMING..."

        with urllib.request.urlopen(req, data=payload, timeout=120) as res:
            for raw in res:
                if not current():   # stopped or superseded
                    break
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw.decode())
                except Exception:
                    continue
                if "error" in obj:
                    raise RuntimeError(str(obj["error"]))
                # /api/chat streams partial assistant messages.
                chunk = obj.get("message", {}).get("content", "")
                if chunk:
                    buf += chunk
                    set_stream_lines(win, stream_start, buf)
                if obj.get("done"):
                    break

        if current():
            if not buf:
                set_stream_lines(win, stream_start, "EMPTY RESPONSE.")
            elif win["use_memory"]:
                # Commit this completed turn to history.
                win["messages"].append({"role": "user", "content": prompt})
                win["messages"].append({"role": "assistant", "content": buf})
                # Bound memory so the request can't grow without limit.
                if len(win["messages"]) > HISTORY_LIMIT:
                    win["messages"] = win["messages"][-HISTORY_LIMIT:]
            win["status"] = "READY"
    except Exception as e:
        if current():
            add_chat(win, "SYS: ERROR - " + str(e)[:30])
            win["status"] = "NETWORK ERROR"
    finally:
        if current():
            win["is_thinking"] = False

def _wrap_lines(kind, text):
    # Word-wrap text into (kind, line) tuples. Long words (tokens/URLs)
    # are hard-split so nothing overflows the right border.
    lines = []
    current = ""
    for w in text.split(" "):
        while len(w) > 46:
            if current:
                lines.append((kind, current))
                current = ""
            lines.append((kind, w[:46]))
            w = w[46:]
        if not current:
            current = w
        elif len(current) + len(w) + 1 > 46:
            lines.append((kind, current))
            current = w
        else:
            current = current + " " + w
    if current:
        lines.append((kind, current))
    return lines

def add_chat(win, text):
    if text.startswith("AI:"):
        kind = "ai"
    elif text.startswith("YOU:"):
        kind = "you"
    else:
        kind = "sys"
    win["chat_lines"].extend(_wrap_lines(kind, text))
    win["scroll_y"] = max(0, len(win["chat_lines"]) - 9)

def set_stream_lines(win, start, buf):
    # Re-wrap the in-progress streamed answer and replace the slice it
    # owns in place. Slice assignment is atomic under the GIL.
    follow = win["scroll_y"] >= max(0, len(win["chat_lines"]) - 9)
    new_lines = _wrap_lines("ai", "AI:  " + buf)
    win["chat_lines"][start:] = new_lines
    # Only stick to the bottom if the user hadn't scrolled up to read.
    if follow:
        win["scroll_y"] = max(0, len(win["chat_lines"]) - 9)

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

    # Scrolling stays available even while a reply streams in.
    if 214 <= lx <= 224:
        if 30 <= ly <= 44: win["scroll_y"] = max(0, win["scroll_y"] - 1)
        elif 74 <= ly <= 88: win["scroll_y"] = min(max(0, len(win["chat_lines"]) - 9), win["scroll_y"] + 1)

    # While a reply is streaming, the SEND key becomes STOP. Bumping
    # gen_id retires the worker thread; it stops at the next token and
    # leaves the partial answer in place.
    if win["is_thinking"]:
        if ly >= 110 and (ly - 110) // 18 == 3 and 180 <= lx <= 224:
            win["gen_id"] = win.get("gen_id", 0) + 1
            win["is_thinking"] = False
            win["status"] = "STOPPED"
            py16.tone(200, 30, py16.WAVE_NOISE)
        return

    if 6 <= lx <= 20 and 16 <= ly <= 26:
        win["model_idx"] = (win["model_idx"] - 1) % len(win["models"])
        win["messages"] = [] 
        py16.tone(600, 20, py16.WAVE_SQUARE)
    elif 134 <= lx <= 148 and 16 <= ly <= 26:
        win["model_idx"] = (win["model_idx"] + 1) % len(win["models"])
        win["messages"] = []
        py16.tone(600, 20, py16.WAVE_SQUARE)

    if ly >= 110:
        if handle_keyboard_typing(win, lx, ly, "input_text", 46): return
        
        row = (ly - 110) // 18
        if row == 3:
            if 6 <= lx <= 30: # LOG
                save_chat_history(win)
                py16.tone(400, 15, py16.WAVE_SQUARE)
            elif 34 <= lx <= 58: # CLR 
                win["chat_lines"] = [("sys", "SYS: CHAT & MEMORY CLEARED.")]
                win["messages"] = []
                win["scroll_y"] = 0
                py16.tone(300, 20, py16.WAVE_NOISE)
            elif 62 <= lx <= 86: # SYS 
                win["bak_temp"] = win["temp"]
                win["bak_token_idx"] = win["token_idx"]
                win["bak_sys"] = win["sys_prompt"]
                win["bak_mem"] = win["use_memory"]
                win["view"] = "settings"
                py16.tone(500, 15, py16.WAVE_SQUARE)
            elif 90 <= lx <= 112: # 12# / ABC page toggle
                win["kbd_page"] = 1 - win.get("kbd_page", 0)
                py16.tone(650, 15, py16.WAVE_SQUARE)
            elif 116 <= lx <= 150: # SPACE
                if len(win["input_text"]) < 46:
                    win["input_text"] += " "
                    py16.tone(700, 10, py16.WAVE_TRIANGLE)
            elif 154 <= lx <= 176: # DEL
                win["input_text"] = win["input_text"][:-1]
                py16.tone(300, 15, py16.WAVE_NOISE)
            elif 180 <= lx <= 224: # SEND
                if send_prompt(win):
                    py16.tone(900, 30, py16.WAVE_SQUARE)
                else:
                    py16.tone(200, 30, py16.WAVE_NOISE)

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
            if not win["use_memory"]: win["messages"] = [] 
            py16.tone(500, 15, py16.WAVE_SQUARE)

    if ly >= 110:
        if handle_keyboard_typing(win, lx, ly, "sys_prompt", 85): return
        
        row = (ly - 110) // 18
        if row == 3:
            if 6 <= lx <= 30: # ESC
                win["temp"] = win.get("bak_temp", 0.8)
                win["token_idx"] = win.get("bak_token_idx", 3)
                win["sys_prompt"] = win.get("bak_sys", "")
                win["use_memory"] = win.get("bak_mem", True)
                win["view"] = "chat"
                py16.tone(400, 15, py16.WAVE_SQUARE)
            elif 34 <= lx <= 56: # 12# / ABC page toggle
                win["kbd_page"] = 1 - win.get("kbd_page", 0)
                py16.tone(650, 15, py16.WAVE_SQUARE)
            elif 60 <= lx <= 150: # SPACE
                if len(win["sys_prompt"]) < 85:
                    win["sys_prompt"] += " "
                    py16.tone(700, 10, py16.WAVE_TRIANGLE)
            elif 154 <= lx <= 176: # DEL
                win["sys_prompt"] = win["sys_prompt"][:-1]
                py16.tone(300, 15, py16.WAVE_NOISE)
            elif 180 <= lx <= 224: # OK
                save_settings(win)
                add_chat(win, "SYS: SETTINGS SAVED.")
                win["view"] = "chat"
                py16.tone(900, 30, py16.WAVE_SQUARE)

def handle_keyboard_typing(win, lx, ly, target_key, max_len):
    import py16
    row = (ly - 110) // 18
    if row < 3:
        col = (lx - 6) // 22
        layout = PAGE_SYMBOLS if win.get("kbd_page", 0) == 1 else PAGE_LETTERS
        keys = layout[row]
        if 0 <= col < len(keys):
            # .lower() only affects letters; digits/symbols pass through.
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
        py16.text("DOWNLOADING TINYLLAMA...", wx+26, wy+50, 1)

        # Live status line from the pull stream (e.g. "PULLING MANIFEST",
        # "DOWNLOADING", "VERIFYING SHA256", "SUCCESS").
        st = win.get("pull_status", "")
        if st:
            py16.text(st, wx+(ww - len(st)*4)//2, wy+72, 5)

        pct = max(0, min(100, win.get("pull_pct", 0)))
        bar_x, bar_y, bar_w, bar_h = wx+20, wy+92, ww-40, 14
        py16.rect(bar_x, bar_y, bar_w, bar_h, 7)
        fill_w = int((bar_w - 2) * pct / 100)
        if fill_w > 0:
            py16.rectfill(bar_x+1, bar_y+1, fill_w, bar_h-2, 11)
        pctlabel = str(pct) + "%"
        py16.text(pctlabel, wx+(ww - len(pctlabel)*4)//2, wy+112, 1)
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
    
    active_mod = win["models"][win["model_idx"] % len(win["models"])]
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
        kind, line = win["chat_lines"][i]
        col = 11 if kind == "ai" else (10 if kind == "you" else 6)
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
    
    layout = PAGE_SYMBOLS if win.get("kbd_page", 0) == 1 else PAGE_LETTERS

    def draw_row(keys, row_idx):
        # Dim the keys while a reply streams in (input is locked).
        locked = mode == "chat" and win["is_thinking"]
        face = 5 if locked else 7
        label = 5 if locked else 1
        for i, key in enumerate(keys):
            kx = wx + 6 + (i * 22)
            ky = kbd_y + (row_idx * 18)
            py16.rectfill(kx, ky, 20, 16, face)
            py16.rect(kx, ky, 20, 16, 5)
            py16.text(key, kx+8, ky+6, label)

    draw_row(layout[0], 0)
    draw_row(layout[1], 1)
    draw_row(layout[2], 2)
    
    row3_y = kbd_y + 54
    
    pg = win.get("kbd_page", 0)
    toggle_label = "ABC" if pg == 1 else "12#"

    if mode == "chat":
        thinking = win["is_thinking"]
        py16.rectfill(wx+6, row3_y, 24, 16, 5 if thinking else 9)
        py16.text("LOG", wx+9, row3_y+6, 5 if thinking else 7)
        py16.rectfill(wx+34, row3_y, 24, 16, 5 if thinking else 8)
        py16.text("CLR", wx+37, row3_y+6, 5 if thinking else 7)
        py16.rectfill(wx+62, row3_y, 24, 16, 5 if thinking else 2)
        py16.text("SYS", wx+65, row3_y+6, 5 if thinking else 7)
        py16.rectfill(wx+90, row3_y, 22, 16, 5 if thinking else 3)
        py16.text(toggle_label, wx+92, row3_y+6, 5 if thinking else 7)
        py16.rectfill(wx+116, row3_y, 34, 16, 5 if thinking else 7)
        py16.text("SPACE", wx+120, row3_y+6, 5 if thinking else 1)
        py16.rectfill(wx+154, row3_y, 22, 16, 5)
        py16.text("DEL", wx+156, row3_y+6, 5 if thinking else 7)
        if thinking:
            py16.rectfill(wx+180, row3_y, 44, 16, 8)   # red
            py16.text("STOP", wx+186, row3_y+6, 7)
        else:
            py16.rectfill(wx+180, row3_y, 44, 16, 11)
            py16.text("SEND", wx+186, row3_y+6, 1)
    else:
        py16.rectfill(wx+6, row3_y, 24, 16, 8)
        py16.text("ESC", wx+9, row3_y+6, 7)
        py16.rectfill(wx+34, row3_y, 22, 16, 3)
        py16.text(toggle_label, wx+36, row3_y+6, 7)
        py16.rectfill(wx+60, row3_y, 90, 16, 7)
        py16.text("SPACE", wx+90, row3_y+6, 1)
        py16.rectfill(wx+154, row3_y, 22, 16, 5)
        py16.text("DEL", wx+156, row3_y+6, 7)
        py16.rectfill(wx+180, row3_y, 44, 16, 10)
        py16.text("OK", wx+196, row3_y+6, 1)
