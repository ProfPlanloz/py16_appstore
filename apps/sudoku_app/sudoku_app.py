import random

# App-Registrierung für das py16OS
APP = {
    "id": "sudoku",
    "name": "SUDOKU",
    "w": 154, "h": 184,
    "resizable": False,
    "icon": "sudoku_app.p16img"
}

# --- Layout-Konstanten (Punkt 3: keine Magic Numbers mehr) ---------------
# Werden in update() (Klick-Hitboxen) UND draw() (Zeichnen) verwendet,
# damit beide nie auseinanderdriften können.
GRID_N      = 9
CELL        = 14                       # Kantenlänge einer Zelle
GRID_X      = 12                       # linker Rand des Gitters
GRID_Y      = 20                       # oberer Rand des Gitters
GRID_W      = CELL * GRID_N            # 126 -> Gitterbreite/-höhe
GRID_END_X  = GRID_X + GRID_W          # 138
GRID_END_Y  = GRID_Y + GRID_W          # 146

PAD_Y       = 152                      # oberer Rand des Ziffernblocks
PAD_BTN     = 12                       # Kantenlänge eines Ziffern-Buttons
PAD_STEP    = CELL                     # Abstand zwischen den Buttons
PAD_COUNT   = 10                       # Buttons 1-9 + "X" (Löschen)

DIFF_Y      = 168                      # oberer Rand der Schwierigkeits-Buttons
DIFF_H      = 10
DIFF_W      = 40
DIFF_X      = (12, 55, 98)             # x-Position EINFACH / MITTEL / SCHWER
DIFF_LABELS = ("EINFACH", "MITTEL", "SCHWER")
DIFF_LABEL_DX = (6, 8, 8)             # x-Versatz zum groben Zentrieren des Texts
DIFF_LEER   = (35, 45, 55)            # zu entfernende Felder je Stufe


# --- Sudoku-Logik --------------------------------------------------------

def _konflikt(b, r, c):
    """True, wenn der Wert in (r, c) gegen eine Sudoku-Regel verstößt.

    Prüft Zeile, Spalte und 3x3-Block. Leere Felder (0) sind nie ein Konflikt.
    """
    v = b[r][c]
    if v == 0:
        return False
    for i in range(GRID_N):
        if (i != c and b[r][i] == v) or (i != r and b[i][c] == v):
            return True
    br, bc = (r // 3) * 3, (c // 3) * 3
    for dr in range(3):
        for dc in range(3):
            rr, cc = br + dr, bc + dc
            if (rr, cc) != (r, c) and b[rr][cc] == v:
                return True
    return False


def _zaehle_loesungen(b, grenze=2):
    """Zählt die Lösungen von b und bricht bei 'grenze' ab.

    Für den Eindeutigkeitstest reicht grenze=2: sobald eine zweite Lösung
    gefunden wird, wissen wir, dass das Rätsel mehrdeutig ist. ACHTUNG:
    verändert b während der Suche, stellt es aber wieder her -> immer eine
    Kopie übergeben.
    """
    for r in range(GRID_N):
        for c in range(GRID_N):
            if b[r][c] == 0:
                gesamt = 0
                for v in range(1, 10):
                    b[r][c] = v
                    if not _konflikt(b, r, c):
                        gesamt += _zaehle_loesungen(b, grenze)
                        if gesamt >= grenze:
                            b[r][c] = 0
                            return gesamt
                b[r][c] = 0
                return gesamt
    return 1  # kein leeres Feld mehr -> vollständige, gültige Lösung


def _erzeuge_loesung():
    """Liefert ein vollständig gefülltes, gültiges 9x9-Sudoku-Gitter.

    Alle Schritte sind regelerhaltend und sorgen für hohe Varianz (Punkt 2).
    """
    # Basisgitter (mathematisch garantiert gültig)
    g = [[(i * 3 + i // 3 + j) % 9 + 1 for j in range(9)] for i in range(9)]

    # Zahlen 1-9 umbenennen
    zahlen = list(range(1, 10))
    random.shuffle(zahlen)
    g = [[zahlen[v - 1] for v in row] for row in g]

    # Zeilen innerhalb jedes Bandes mischen
    for band in range(3):
        perm = [0, 1, 2]
        random.shuffle(perm)
        rows = [g[band * 3 + p][:] for p in perm]
        for k in range(3):
            g[band * 3 + k] = rows[k]

    # Spalten innerhalb jedes Stacks mischen
    for stack in range(3):
        perm = [0, 1, 2]
        random.shuffle(perm)
        for r in range(9):
            orig = g[r][stack * 3:stack * 3 + 3]
            for k in range(3):
                g[r][stack * 3 + k] = orig[perm[k]]

    # Ganze Bänder (Zeilenblöcke) untereinander tauschen
    bperm = [0, 1, 2]
    random.shuffle(bperm)
    g = [g[bperm[b] * 3 + k][:] for b in range(3) for k in range(3)]

    # Ganze Stacks (Spaltenblöcke) untereinander tauschen
    sperm = [0, 1, 2]
    random.shuffle(sperm)
    for r in range(9):
        row = g[r]
        g[r] = [row[sperm[s] * 3 + k] for s in range(3) for k in range(3)]

    # Gelegentlich transponieren
    if random.random() < 0.5:
        g = [[g[c][r] for c in range(9)] for r in range(9)]

    return g


def erzeuge_sudoku(win, entfernen=45):
    """Generiert ein neues, garantiert eindeutig lösbares Sudoku (Punkt 1)."""
    loesung = _erzeuge_loesung()
    board = [row[:] for row in loesung]

    # Felder in zufälliger Reihenfolge leeren, aber nur, solange das Rätsel
    # danach noch GENAU EINE Lösung hat. Sonst Feld zurücksetzen.
    zellen = [(r, c) for r in range(9) for c in range(9)]
    random.shuffle(zellen)
    geleert = 0
    for r, c in zellen:
        if geleert >= entfernen:
            break
        gemerkt = board[r][c]
        board[r][c] = 0
        if _zaehle_loesungen([row[:] for row in board]) == 1:
            geleert += 1
        else:
            board[r][c] = gemerkt  # mehrdeutig -> Feld wieder füllen

    win['loesung'] = loesung
    win['board'] = board
    # Vorgegeben sind genau die Felder, die nicht geleert wurden
    win['given'] = [[board[r][c] != 0 for c in range(9)] for r in range(9)]
    win['sel_r'] = -1
    win['sel_c'] = -1
    win['gewonnen'] = False


def init(win):
    """Wird einmalig vom OS aufgerufen, wenn die App gestartet wird."""
    erzeuge_sudoku(win)


def check_gewonnen(win):
    """True, wenn das Brett voll und regelkonform ist.

    Prüft die Sudoku-Regeln statt gegen die gespeicherte Lösung zu
    vergleichen -> JEDE gültige Lösung zählt als Sieg (Punkt 1).
    """
    b = win['board']
    for r in range(9):
        for c in range(9):
            if b[r][c] == 0 or _konflikt(b, r, c):
                return False
    return True


def update(win, lx, ly, mp, msp, mh):
    """Wird jeden Frame aufgerufen, während das Fenster aktiv ist (Logik)."""
    if not mp:
        return  # Nur auf neue Klicks (Mausklick runter) reagieren

    # Klick auf das Sudoku-Gitter?
    if GRID_X <= lx < GRID_END_X and GRID_Y <= ly < GRID_END_Y:
        r = (ly - GRID_Y) // CELL
        c = (lx - GRID_X) // CELL
        if 0 <= r < GRID_N and 0 <= c < GRID_N:
            win['sel_r'] = r
            win['sel_c'] = c
        return

    # Klick auf den Ziffernblock oder Löschen-Button
    if PAD_Y <= ly <= PAD_Y + PAD_BTN and win['sel_r'] >= 0 and not win['gewonnen']:
        for i in range(1, PAD_COUNT + 1):  # i == PAD_COUNT -> "X" (Löschen)
            bx = GRID_X + (i - 1) * PAD_STEP
            if bx <= lx <= bx + PAD_BTN:
                if not win['given'][win['sel_r']][win['sel_c']]:
                    if i == PAD_COUNT:
                        win['board'][win['sel_r']][win['sel_c']] = 0   # Löschen
                    else:
                        win['board'][win['sel_r']][win['sel_c']] = i   # Zahl setzen
                        win['gewonnen'] = check_gewonnen(win)
                return

    # Klick auf die Schwierigkeitsgrad-/Neues-Spiel-Buttons
    if DIFF_Y <= ly <= DIFF_Y + DIFF_H:
        for k in range(3):
            if DIFF_X[k] <= lx <= DIFF_X[k] + DIFF_W:
                erzeuge_sudoku(win, DIFF_LEER[k])
                return


def draw(win, wx, wy, ww, wh, active):
    """Wird jeden Frame aufgerufen, um das Fenster zu zeichnen."""
    import py16

    # Zeichnen auf den Fensterinhalt (unter der Titelleiste) begrenzen,
    # damit nichts über den Fensterrand hinausgemalt wird.
    py16.clip(wx, wy + 14, ww, wh - 14)

    # 1. Haupt-Hintergrund (unterhalb der Titelleiste)
    py16.rectfill(wx, wy + 14, ww, wh - 14, 6)  # 6 = Hellgrau

    # 2. Sudoku-Feld-Hintergrund (grün, wenn gewonnen)
    bg = 11 if win['gewonnen'] else 7  # 11 = Grün, 7 = Weiß
    py16.rectfill(wx + GRID_X, wy + GRID_Y, GRID_W, GRID_W, bg)

    # Ausgewählte Zelle markieren
    if win['sel_r'] >= 0 and not win['gewonnen']:
        py16.rectfill(wx + GRID_X + win['sel_c'] * CELL,
                      wy + GRID_Y + win['sel_r'] * CELL, CELL, CELL, 9)  # 9 = Orange

    # 3. Gitterlinien
    for i in range(GRID_N + 1):
        col = 0 if i % 3 == 0 else 5  # 0 = Schwarz (Blöcke), 5 = Dunkelgrau (Zellen)
        x = wx + GRID_X + i * CELL
        py16.line(x, wy + GRID_Y, x, wy + GRID_END_Y, col)
        y = wy + GRID_Y + i * CELL
        py16.line(wx + GRID_X, y, wx + GRID_END_X, y, col)

    # 4. Zahlen eintragen (Färbung jetzt regelbasiert, nicht via Lösung)
    board = win['board']
    for r in range(9):
        for c in range(9):
            val = board[r][c]
            if val > 0:
                if win['given'][r][c]:
                    col = 1                          # Dunkelblau = vorgegeben
                elif _konflikt(board, r, c):
                    col = 8                           # Rot = Regelkonflikt
                else:
                    col = 12                          # Blau = (noch) konfliktfrei
                py16.text(str(val), wx + GRID_X + 5 + c * CELL,
                          wy + GRID_Y + 4 + r * CELL, col)

    # 5. Ziffernblock 1-9 und "X" (Löschen)
    for i in range(1, PAD_COUNT + 1):
        bx = wx + GRID_X + (i - 1) * PAD_STEP
        by = wy + PAD_Y
        py16.rectfill(bx, by, PAD_BTN, PAD_BTN, 7)   # Füllung (Weiß)
        py16.rect(bx, by, PAD_BTN, PAD_BTN, 0)       # Rand (Schwarz)
        txt = str(i) if i < PAD_COUNT else "X"
        txt_col = 1 if i < PAD_COUNT else 8          # Zahlen Dunkelblau, X Rot
        py16.text(txt, bx + 4, by + 4, txt_col)

    # 6. Schwierigkeitsgrad-Buttons
    for k in range(3):
        py16.rectfill(wx + DIFF_X[k], wy + DIFF_Y, DIFF_W, DIFF_H, 5)  # Dunkelgrau
        py16.text(DIFF_LABELS[k], wx + DIFF_X[k] + DIFF_LABEL_DX[k],
                  wy + DIFF_Y + 3, 7)  # Weißer Text

    # Clip-Box wieder auf Vollbild zurücksetzen
    py16.clip()
