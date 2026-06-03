import time
import threading
import urllib.request
import urllib.parse
import os
import json

# Die OS-Spezifikation fuer unser Fenster (hoeher fuer Vorlagen + SHIFT-Reihe)
APP = {
    "id": "qrcode",
    "name": "QR CODE",
    "w": 176,
    "h": 166,
    "resizable": False
}

# On-Screen-Tastatur, drei Ebenen (umschaltbar per SHIFT).
# Jede Reihe ist exakt 10 Zeichen breit; ' ' = leerer Slot (wird uebersprungen).
LAYER_UPPER = ["1234567890", "QWERTZUIOP", "ASDFGHJKL-", "YXCVBNM.:/"]
LAYER_LOWER = ["1234567890", "qwertzuiop", "asdfghjkl-", "yxcvbnm.:/"]
LAYER_SYM   = ["!@#$%&*+=?", "()[]<>_-~^", ";,'\"`|\\/.:", "          "]
LAYERS = [LAYER_UPPER, LAYER_LOWER, LAYER_SYM]
LAYER_NAMES = ["ABC", "abc", "SYM"]

# Vorlagen: Anzeigereihenfolge im Menue + Felder je Typ
MENU_ORDER = ["WLAN", "KONTAKT", "BITCOIN", "STANDORT", "WEBSEITE"]
TEMPLATE_FIELDS = {
    "WLAN":     ["SSID", "PASSWORT"],   # PASSWORT leer -> offenes Netz
    "KONTAKT":  ["NAME", "TEL", "EMAIL"],
    "BITCOIN":  ["ADRESSE", "BETRAG"],  # BETRAG optional
    "STANDORT": ["LAT", "LON"],
    "WEBSEITE": ["URL"],
}

# Dateinamen namespaced, um Kollisionen mit anderen Plugins zu vermeiden
SAVE_FILE = "qrcode_data.json"
EXPORT_FILE = "qrcode_export.png"
IMPORT_FILE = "qrcode_import.png"

MAX_LEN = 60        # Limit fuer manuelle Tastatureingabe
FIELD_MAX = 80      # Limit pro Vorlagen-Feld

ECC_LEVELS = ["L", "M", "Q", "H"]      # waehlbare Fehlerkorrektur-Stufen
EXPORT_SCALES = [2, 4, 8, 16]          # waehlbare Pixel pro Modul (PNG)


def init(win):
    """Wird einmalig beim Registrieren des Plugins aufgerufen."""
    win['text'] = ""
    # states: input, menu, form, importing, display, error
    win['state'] = "input"
    win['qr_matrix'] = []
    win['error_msg'] = ""
    win['export_msg'] = ""
    win['status_msg'] = ""
    win['decode_id'] = 0      # Token: invalidiert verspaetete Decode-Threads
    win['kb_layer'] = 0       # 0=ABC 1=abc 2=SYM
    win['ecc'] = 'M'          # Fehlerkorrektur-Level: L M Q H
    win['export_scale'] = 4   # Pixel pro Modul beim PNG-Export
    win['form_type'] = ""
    win['form_values'] = []
    win['form_idx'] = 0


# ---------------------------------------------------------------- Persistenz

def save_data(win):
    try:
        with open(SAVE_FILE, "w") as f:
            json.dump({"text": win['text']}, f)
        win['status_msg'] = "GESPEICHERT!"
    except Exception:
        win['status_msg'] = "FEHLER!"


def load_data(win):
    if os.path.exists(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r") as f:
                data = json.load(f)
                win['text'] = data.get("text", "")
            win['status_msg'] = "GELADEN!"
        except Exception:
            win['status_msg'] = "FEHLER!"
    else:
        win['status_msg'] = "KEIN SAVEGAME"


# ----------------------------------------------------------- Vorlagen-Payload

def _esc(s):
    """Escaping fuer WIFI/MECARD: Backslash vor  \\ ; , : \""""
    out = ""
    for ch in s:
        if ch in '\\;,:"':
            out += "\\" + ch
        else:
            out += ch
    return out


def build_payload(t, vals):
    """Baut aus den Formularfeldern den standardkonformen QR-Inhalt."""
    if t == "WLAN":
        ssid, pw = (vals + ["", ""])[:2]
        if pw:
            return "WIFI:T:WPA;S:%s;P:%s;;" % (_esc(ssid), _esc(pw))
        return "WIFI:T:nopass;S:%s;;" % _esc(ssid)
    if t == "KONTAKT":
        name, tel, email = (vals + ["", "", ""])[:3]
        s = "MECARD:"
        if name:
            s += "N:%s;" % _esc(name)
        if tel:
            s += "TEL:%s;" % _esc(tel)
        if email:
            s += "EMAIL:%s;" % _esc(email)
        return s + ";"
    if t == "BITCOIN":
        addr, amt = (vals + ["", ""])[:2]
        return ("bitcoin:%s?amount=%s" % (addr, amt)) if amt else ("bitcoin:%s" % addr)
    if t == "STANDORT":
        lat, lon = (vals + ["", ""])[:2]
        return "geo:%s,%s" % (lat, lon)
    if t == "WEBSEITE":
        url = vals[0] if vals else ""
        if url and not url.lower().startswith(("http://", "https://")):
            url = "https://" + url
        return url
    return ""


# ----------------------------------------------------------- QR erzeugen/lesen

def generate_qr(win):
    """Erzeugt den QR-Code lokal (offline) via segno."""
    try:
        import segno
    except ImportError:
        win['error_msg'] = "SEGNO FEHLT (pip inst.)"
        win['state'] = 'error'
        return
    try:
        qr = segno.make(win['text'], error=win.get('ecc', 'M').lower())
        matrix = [[bool(c) for c in row] for row in qr.matrix_iter(border=0)]
        win['qr_matrix'] = matrix
        win['export_msg'] = ""
        win['state'] = 'display'
    except Exception as e:
        win['error_msg'] = str(e)[:25]
        win['state'] = 'error'


def export_qr(win):
    """Exportiert den aktuellen Code als .png (segno, kein Pillow noetig)."""
    if not win.get('text'):
        return
    try:
        import segno
    except ImportError:
        win['export_msg'] = "SEGNO FEHLT"
        return
    try:
        sc = win.get('export_scale', 4)
        qr = segno.make(win['text'], error=win.get('ecc', 'M').lower())
        qr.save(EXPORT_FILE, scale=sc, border=4)
        win['export_msg'] = "OK x%d" % sc
    except Exception:
        win['export_msg'] = "EXPORT FEHLER"


def decode_qr(win, my_id):
    """Liest ein lokales PNG ein und decodiert den Text via API.

    my_id ist das Token aus win['decode_id'] beim Start. Aendert es sich
    (Abbruch durch den Nutzer), werden die Ergebnisse verworfen.
    """
    try:
        filename = IMPORT_FILE
        if not os.path.exists(filename):
            filename = EXPORT_FILE
        if not os.path.exists(filename):
            if win['decode_id'] == my_id:
                win['error_msg'] = "KEIN BILD GEFUNDEN"
                win['state'] = 'error'
            return

        with open(filename, "rb") as f:
            file_data = f.read()

        boundary = '----py16OSBoundary'
        body = (
            f'--{boundary}\r\n'
            f'Content-Disposition: form-data; name="file"; filename="qr.png"\r\n'
            f'Content-Type: image/png\r\n\r\n'
        ).encode('utf-8') + file_data + f'\r\n--{boundary}--\r\n'.encode('utf-8')

        req = urllib.request.Request(
            "https://api.qrserver.com/v1/read-qr-code/",
            data=body,
            headers={'Content-Type': f'multipart/form-data; boundary={boundary}'}
        )
        resp = urllib.request.urlopen(req, timeout=5)
        resp_data = json.loads(resp.read().decode('utf-8'))

        symbol = resp_data[0]["symbol"][0]
        decoded_text = symbol["data"]
        error_msg = symbol["error"]

        if win['decode_id'] != my_id:
            return  # abgebrochen -> Ergebnis verwerfen

        if decoded_text:
            win['text'] = decoded_text
            win['status_msg'] = "BILD IMPORTIERT!"
            win['state'] = 'input'
        else:
            win['error_msg'] = error_msg[:25] if error_msg else "NICHT LESBAR"
            win['state'] = 'error'
    except Exception as e:
        if win['decode_id'] == my_id:
            win['error_msg'] = str(e)[:25]
            win['state'] = 'error'


# ----------------------------------------------------------------- Tastatur

def _key_at(win, lx, ly):
    """Gibt das angetippte Tastatur-Zeichen der aktiven Ebene zurueck, sonst None."""
    layout = LAYERS[win.get('kb_layer', 0)]
    for r, row in enumerate(layout):
        for c, char in enumerate(row):
            if char == ' ':
                continue
            bx = 6 + c * 16
            by = 40 + r * 16
            if bx <= lx < bx + 14 and by <= ly < by + 14:
                return char
    return None


def _draw_keyboard(win, wx, wy):
    import py16
    layout = LAYERS[win.get('kb_layer', 0)]
    for r, row in enumerate(layout):
        for c, char in enumerate(row):
            if char == ' ':
                continue
            bx = wx + 6 + c * 16
            by = wy + 40 + r * 16
            py16.rectfill(bx, by, 14, 14, 6)
            py16.rect(bx, by, 14, 14, 5)
            py16.text(char, bx + 5, by + 5, 1)


def _btn(wx, wy, x, y, w, label, color_bg=6, color_tx=1):
    import py16
    py16.rectfill(wx + x, wy + y, w, 14, color_bg)
    py16.rect(wx + x, wy + y, w, 14, 5)
    py16.text(label, wx + x + 5, wy + y + 5, color_tx)


# ------------------------------------------------------------------- Update

def update(win, lx, ly, mp, msp, mh):
    if not mp:
        return
    st = win['state']

    if st == 'input':
        win['status_msg'] = ""

        ch = _key_at(win, lx, ly)
        if ch is not None:
            if len(win['text']) < MAX_LEN:
                win['text'] += ch
            return

        # Reihe 1 (y108): SAVE | LOAD | IMPORT | DEL
        if 108 <= ly < 122:
            if 6 <= lx < 42:
                save_data(win)
            elif 46 <= lx < 82:
                load_data(win)
            elif 86 <= lx < 130:
                win['decode_id'] += 1
                win['state'] = 'importing'
                threading.Thread(target=decode_qr, args=(win, win['decode_id']),
                                 daemon=True).start()
            elif 134 <= lx < 170:
                win['text'] = win['text'][:-1]
        # Reihe 2 (y126): SHIFT | VORLAGE | GEN
        elif 126 <= ly < 140:
            if 6 <= lx < 50:
                win['kb_layer'] = (win['kb_layer'] + 1) % 3
            elif 54 <= lx < 106:
                win['state'] = 'menu'
            elif 110 <= lx < 170:
                if win['text']:
                    generate_qr(win)
        # Reihe 3 (y144): LEERTASTE
        elif 144 <= ly < 158:
            if 6 <= lx < 170 and len(win['text']) < MAX_LEN:
                win['text'] += " "

    elif st == 'menu':
        for i, name in enumerate(MENU_ORDER):
            by = 22 + i * 22
            if 20 <= lx < 156 and by <= ly < by + 16:
                win['form_type'] = name
                win['form_values'] = [""] * len(TEMPLATE_FIELDS[name])
                win['form_idx'] = 0
                win['state'] = 'form'
                return
        # ZURUECK
        if 20 <= lx < 156 and 134 <= ly < 150:
            win['state'] = 'input'

    elif st == 'form':
        idx = win['form_idx']

        ch = _key_at(win, lx, ly)
        if ch is not None:
            if len(win['form_values'][idx]) < FIELD_MAX:
                win['form_values'][idx] += ch
            return

        # Reihe 1 (y108): SHIFT | ZURUECK | DEL
        if 108 <= ly < 122:
            if 6 <= lx < 50:
                win['kb_layer'] = (win['kb_layer'] + 1) % 3
            elif 54 <= lx < 106:
                if idx > 0:
                    win['form_idx'] -= 1
                else:
                    win['state'] = 'menu'
            elif 110 <= lx < 170:
                win['form_values'][idx] = win['form_values'][idx][:-1]
        # Reihe 2 (y126): WEITER / FERTIG
        elif 126 <= ly < 140:
            if 6 <= lx < 170:
                if idx < len(win['form_values']) - 1:
                    win['form_idx'] += 1
                else:
                    win['text'] = build_payload(win['form_type'], win['form_values'])
                    win['status_msg'] = "VORLAGE UEBERNOMMEN"
                    win['state'] = 'input'
        # Reihe 3 (y144): LEERTASTE
        elif 144 <= ly < 158:
            if 6 <= lx < 170 and len(win['form_values'][idx]) < FIELD_MAX:
                win['form_values'][idx] += " "

    elif st == 'importing':
        # ABBRECHEN: Token erhoehen -> laufender Thread verwirft sein Ergebnis
        if 6 <= lx < 66 and 146 <= ly < 160:
            win['decode_id'] += 1
            win['state'] = 'input'
            win['status_msg'] = "ABGEBROCHEN"

    elif st == 'display':
        # Settings-Zeile (y124): ECC-Level | Export-Skalierung
        if 124 <= ly < 138:
            if 6 <= lx < 76:        # ECC: naechste Stufe -> neu erzeugen
                cur = win.get('ecc', 'M')
                i = (ECC_LEVELS.index(cur) + 1) % len(ECC_LEVELS)
                win['ecc'] = ECC_LEVELS[i]
                generate_qr(win)
                return
            elif 82 <= lx < 170:    # PNG-Skalierung
                cur = win.get('export_scale', 4)
                i = EXPORT_SCALES.index(cur) if cur in EXPORT_SCALES else 1
                win['export_scale'] = EXPORT_SCALES[(i + 1) % len(EXPORT_SCALES)]
                return
        # Bottom-Zeile (y146): ZURUECK | EXPORT
        if 6 <= lx < 56 and 146 <= ly < 160:
            win['state'] = 'input'
        elif 60 <= lx < 110 and 146 <= ly < 160:
            export_qr(win)

    elif st == 'error':
        if 6 <= lx < 56 and 146 <= ly < 160:        # ZURUECK
            win['state'] = 'input'


# --------------------------------------------------------------------- Draw

def draw(win, wx, wy, ww, wh, active):
    import py16
    st = win['state']

    if st == 'input':
        disp_text = win['text'][-24:] if len(win['text']) > 24 else win['text']
        py16.text("TXT: " + disp_text, wx + 6, wy + 18, 1)
        if int(time.time() * 2) % 2 == 0:
            py16.text("_", wx + 6 + 20 + len(disp_text) * 4, wy + 18, 1)

        if win['status_msg']:
            py16.text(win['status_msg'], wx + 6, wy + 30, 8)

        _draw_keyboard(win, wx, wy)

        # Reihe 1: SAVE | LOAD | IMPORT | DEL
        _btn(wx, wy, 6, 108, 36, "SAVE")
        _btn(wx, wy, 46, 108, 36, "LOAD")
        _btn(wx, wy, 86, 108, 44, "IMPORT")
        _btn(wx, wy, 134, 108, 36, "DEL", color_tx=8)
        # Reihe 2: SHIFT | VORLAGE | GEN
        _btn(wx, wy, 6, 126, 44, LAYER_NAMES[win['kb_layer']])
        _btn(wx, wy, 54, 126, 52, "VORLAGE")
        _btn(wx, wy, 110, 126, 60, "GEN", color_bg=11, color_tx=1)
        # Reihe 3: LEERTASTE
        _btn(wx, wy, 6, 144, 164, "LEERTASTE")

    elif st == 'menu':
        for i, name in enumerate(MENU_ORDER):
            _btn(wx, wy, 20, 22 + i * 22, 136, name)
        _btn(wx, wy, 20, 134, 136, "ZURUECK", color_tx=8)

    elif st == 'form':
        t = win['form_type']
        fields = TEMPLATE_FIELDS[t]
        idx = win['form_idx']
        py16.text(t, wx + 6, wy + 17, 11)

        for i, fname in enumerate(fields):
            y = wy + 25 + i * 8
            val = win['form_values'][i]
            show = val[-16:] if len(val) > 16 else val
            marker = ">" if i == idx else " "
            py16.text("%s%s:%s" % (marker, fname, show), wx + 6, y, 1)
            if i == idx and int(time.time() * 2) % 2 == 0:
                cx = wx + 6 + (1 + len(fname) + 1 + len(show)) * 4
                py16.text("_", cx, y, 1)

        _draw_keyboard(win, wx, wy)

        last = (idx == len(fields) - 1)
        _btn(wx, wy, 6, 108, 44, LAYER_NAMES[win['kb_layer']])
        _btn(wx, wy, 54, 108, 52, "ZURUECK")
        _btn(wx, wy, 110, 108, 60, "DEL", color_tx=8)
        _btn(wx, wy, 6, 126, 164, "FERTIG" if last else "WEITER",
             color_bg=11 if last else 6)
        _btn(wx, wy, 6, 144, 164, "LEERTASTE")

    elif st == 'importing':
        py16.text("LESE BILD...", wx + ww // 2 - 24, wy + 40, 1)
        _btn(wx, wy, 6, 146, 60, "ABBRECHEN", color_tx=8)

    elif st == 'display':
        matrix = win.get('qr_matrix', [])
        if matrix:
            n = len(matrix)
            avail = min(ww - 16, 88)
            scale = max(1, min(avail // n, 4))
            qr_px = n * scale
            off_x = (ww - qr_px) // 2
            off_y = 18
            py16.rectfill(wx + off_x - 4, wy + off_y - 4, qr_px + 8, qr_px + 8, 7)
            for y in range(n):
                rowm = matrix[y]
                for x in range(n):
                    if rowm[x]:
                        py16.rectfill(wx + off_x + x * scale,
                                      wy + off_y + y * scale, scale, scale, 1)
        # Settings-Zeile: ECC-Level + Export-Skalierung
        _btn(wx, wy, 6, 124, 70, "ECC:" + win.get('ecc', 'M'))
        _btn(wx, wy, 82, 124, 88, "PNG x%d" % win.get('export_scale', 4))
        # Bottom-Zeile: ZURUECK | EXPORT
        _btn(wx, wy, 6, 146, 50, "ZURUECK")
        _btn(wx, wy, 60, 146, 50, "EXPORT")
        if win.get('export_msg'):
            py16.text(win['export_msg'], wx + 115, wy + 151, 8)

    elif st == 'error':
        py16.text("FEHLER!", wx + 6, wy + 40, 8)
        py16.text(win.get('error_msg', ''), wx + 6, wy + 50, 8)
        _btn(wx, wy, 6, 146, 50, "ZURUECK")
