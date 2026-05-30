# apps/sheets.py
import re
import csv
import os
import json
import math
import statistics

# App metadata for py16OS
APP = {
    "id": "sheets",
    "name": "SHEETS",
    "w": 230,  # Slightly wider start, since the keyboard now has 13 columns
    "h": 160,
    "resizable": True,
    "min_w": 220,
    "min_h": 140,
    "icon": "sheets_app.p16img",
}

# --- HELPERS FOR SPREADSHEET COORDINATES ---

def parse_cell_id(cell_id):
    """Converts a cell ID like 'B3' or '$B$3' into 0-based column/row indices.
    Leading $ anchors are ignored here (only relevant for shift_formula)."""
    m = re.match(r"^\$?([A-Z]+)\$?([0-9]+)$", cell_id.upper())
    if not m:
        return None
    col_str, row_str = m.groups()
    
    col_idx = 0
    for char in col_str:
        col_idx = col_idx * 26 + (ord(char) - ord('A') + 1)
    col_idx -= 1
    
    row_idx = int(row_str) - 1
    return col_idx, row_idx

def get_cell_id(col_idx, row_idx):
    """Converts column/row indices into a cell ID like 'A1'."""
    col_str = ""
    temp = col_idx + 1
    while temp > 0:
        temp, remainder = divmod(temp - 1, 26)
        col_str = chr(65 + remainder) + col_str
    return f"{col_str}{row_idx + 1}"

def resolve_range(start_cell, end_cell):
    """Returns a list of all cell IDs within a range (e.g. A1:B3)."""
    start = parse_cell_id(start_cell)
    end = parse_cell_id(end_cell)
    if not start or not end:
        return []
    
    c0, r0 = start
    c1, r1 = end
    
    min_c, max_c = min(c0, c1), max(c0, c1)
    min_r, max_r = min(r0, r1), max(r0, r1)
    
    cells = []
    for c in range(min_c, max_c + 1):
        for r in range(min_r, max_r + 1):
            cells.append(get_cell_id(c, r))
    return cells

def shift_formula(formula, dc, dr):
    """Shifts cell references in a formula relatively (copy & paste).
    Absolute references with $ stay fixed: $A$1 does not move at all,
    $A1 fixes the column, A$1 fixes the row."""
    if not formula.startswith("="):
        return formula

    def replacer(match):
        col_anchor, col_str, row_anchor, row_str = match.groups()

        c = 0
        for char in col_str.upper():
            c = c * 26 + (ord(char) - ord('A') + 1)
        c -= 1
        r = int(row_str) - 1

        new_c = c if col_anchor else max(0, c + dc)
        new_r = r if row_anchor else max(0, r + dr)

        cell = get_cell_id(new_c, new_r)
        # Keep anchors in the result (e.g. $A$1 stays $A$1)
        if col_anchor or row_anchor:
            m = re.match(r"^([A-Z]+)([0-9]+)$", cell)
            cell = f"{col_anchor}{m.group(1)}{row_anchor}{m.group(2)}"
        return cell

    return re.sub(r"(\$?)([A-Z]+)(\$?)([0-9]+)", replacer, formula)

# --- SAFE FORMULA EVALUATOR (tokenizer + recursive parser) ---
#
# Replaces the previous eval()-based approach. The old one could
# freeze the whole OS (=9**9**9 -> integer power blocks the frame)
# and could not handle nested IFs. This parser:
#   * works with float only -> no giant integers, no freeze
#   * supports operator precedence, parentheses, comparisons and logic
#   * lets functions nest freely: IF(AND(A1>0,A1<9),SUM(B1:B3),0)
# There is NO eval() and NO builtins anymore - only the nodes defined here.

class FormulaError(Exception):
    """Internal evaluation error -> the cell shows ERROR."""
    pass

class _Circular(Exception):
    """Circular reference that propagates through dependent cells -> CIRC!."""
    pass

_POW_LIMIT = 1e6  # Caps powers so inf/nan avalanches stay avoidable

# Token patterns (order matters: multi-char operators first)
_TOKEN_RE = re.compile(r"""
    \s+
  | (?P<num>\d*\.\d+|\d+\.?)
  | (?P<ref>\$?[A-Z]+\$?[0-9]+)
  | (?P<name>[A-Z]+)
  | (?P<op><>|!=|<=|>=|==|\*\*|[-+*/%(),:<>=&|!])
""", re.VERBOSE)


def _tokenize(expr):
    """Splits an (already upper-cased) expression into tokens."""
    tokens, pos = [], 0
    while pos < len(expr):
        m = _TOKEN_RE.match(expr, pos)
        if not m or m.end() == pos:
            raise FormulaError(f"unknown character: {expr[pos]!r}")
        pos = m.end()
        if m.lastgroup is None:        # pure whitespace
            continue
        tokens.append((m.lastgroup, m.group(m.lastgroup)))
    tokens.append(("end", ""))
    return tokens


def _num(v):
    """Coerces a cell value into a number: bool->1/0, text/empty->0.0 (as before)."""
    if isinstance(v, bool):
        return 1.0 if v else 0.0
    if isinstance(v, (int, float)):
        return float(v)
    try:
        return float(v)
    except (ValueError, TypeError):
        return 0.0


def _finite(x):
    """Guards against inf/nan that would otherwise silently spread through the sheet."""
    if x != x or x in (float("inf"), float("-inf")):
        raise FormulaError("overflow")
    return x


# Range / variadic aggregate functions. Receive a flat list of the
# evaluated raw values (float | "" | str) and decide themselves.
def _numeric(values):
    out = []
    for v in values:
        if isinstance(v, bool):
            out.append(1.0 if v else 0.0)
        elif isinstance(v, (int, float)):
            out.append(float(v))
        elif isinstance(v, str) and v not in ("",):
            try:
                out.append(float(v))
            except ValueError:
                pass
    return out

_AGG_FUNCS = {
    "SUM":     lambda vs: sum(_numeric(vs)),
    "AVG":     lambda vs: (lambda n: sum(n) / len(n) if n else 0.0)(_numeric(vs)),
    "AVERAGE": lambda vs: (lambda n: sum(n) / len(n) if n else 0.0)(_numeric(vs)),
    "MIN":     lambda vs: (lambda n: min(n) if n else 0.0)(_numeric(vs)),
    "MAX":     lambda vs: (lambda n: max(n) if n else 0.0)(_numeric(vs)),
    "PRODUCT": lambda vs: (lambda n: math.prod(n) if n else 0.0)(_numeric(vs)),
    "COUNT":   lambda vs: float(len(_numeric(vs))),                      # numbers only
    "COUNTA":  lambda vs: float(sum(1 for v in vs if v != "")),          # everything non-empty
    "MEDIAN":  lambda vs: (lambda n: statistics.median(n) if n else 0.0)(_numeric(vs)),
}

# Scalar functions. Receive already-evaluated float arguments.
def _scalar_round(args):
    x = args[0]
    n = int(args[1]) if len(args) > 1 else 0
    return float(round(x, n))

_SCALAR_FUNCS = {
    "ABS":   lambda a: abs(a[0]),
    "INT":   lambda a: float(int(a[0])),
    "ROUND": _scalar_round,
    "SQRT":  lambda a: math.sqrt(a[0]) if a[0] >= 0 else _raise("SQRT<0"),
    "MOD":   lambda a: math.fmod(a[0], a[1]) if a[1] != 0 else _raise("MOD0"),
    "POW":   lambda a: _finite(a[0] ** a[1]),
    "SIGN":  lambda a: float((a[0] > 0) - (a[0] < 0)),
}

def _raise(msg):
    raise FormulaError(msg)


class _Parser:
    """Recursive descent parser. Precedence (low -> high):
       OR -> AND -> NOT -> comparison -> +/- -> * / % -> unary -/+ -> power -> atom
    """
    def __init__(self, tokens, grid, visited):
        self.toks = tokens
        self.i = 0
        self.grid = grid
        self.visited = visited

    def peek(self):
        return self.toks[self.i]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def expect(self, value):
        kind, val = self.next()
        if val != value:
            raise FormulaError(f"expected {value!r}, found {val!r}")

    # --- Levels ---
    def parse(self):
        v = self.parse_or()
        if self.peek()[0] != "end":
            raise FormulaError("unexpected token at end")
        return v

    def parse_or(self):
        v = self.parse_and()
        while self.peek()[1] in ("OR", "|"):
            self.next()
            r = self.parse_and()
            v = 1.0 if (self._truth(v) or self._truth(r)) else 0.0
        return v

    def parse_and(self):
        v = self.parse_not()
        while self.peek()[1] in ("AND", "&"):
            self.next()
            r = self.parse_not()
            v = 1.0 if (self._truth(v) and self._truth(r)) else 0.0
        return v

    def parse_not(self):
        if self.peek()[1] == "NOT" or self.peek()[1] == "!":
            self.next()
            return 0.0 if self._truth(self.parse_not()) else 1.0
        return self.parse_cmp()

    def parse_cmp(self):
        v = self.parse_add()
        kind, val = self.peek()
        if val in ("=", "==", "<>", "!=", "<", ">", "<=", ">="):
            self.next()
            r = self.parse_add()
            if val in ("=", "=="):  res = v == r
            elif val in ("<>", "!="): res = v != r
            elif val == "<":  res = v < r
            elif val == ">":  res = v > r
            elif val == "<=": res = v <= r
            else:             res = v >= r
            return 1.0 if res else 0.0
        return v

    def parse_add(self):
        v = self.parse_mul()
        while self.peek()[1] in ("+", "-"):
            op = self.next()[1]
            r = self.parse_mul()
            v = v + r if op == "+" else v - r
        return v

    def parse_mul(self):
        v = self.parse_unary()
        while self.peek()[1] in ("*", "/", "%"):
            op = self.next()[1]
            r = self.parse_unary()
            if op == "*":
                v = v * r
            elif op == "/":
                if r == 0:
                    raise FormulaError("division by zero")
                v = v / r
            else:
                if r == 0:
                    raise FormulaError("modulo by zero")
                v = math.fmod(v, r)
        return _finite(v)

    def parse_unary(self):
        kind, val = self.peek()
        if val == "-":
            self.next(); return -self.parse_unary()
        if val == "+":
            self.next(); return self.parse_unary()
        return self.parse_pow()

    def parse_pow(self):
        base = self.parse_atom()
        if self.peek()[1] == "**":
            self.next()
            exp = self.parse_unary()  # right-associative
            if abs(base) > _POW_LIMIT or abs(exp) > 64:
                raise FormulaError("power too large")
            return _finite(base ** exp)
        return base

    def parse_atom(self):
        kind, val = self.next()
        if kind == "num":
            return float(val)
        if kind == "ref":
            return _num(self._eval_ref(val))
        if val == "(":
            v = self.parse_or()
            self.expect(")")
            return v
        if kind == "name":
            return self.parse_func(val)
        raise FormulaError(f"unexpected: {val!r}")

    # --- Function call ---
    def parse_func(self, name):
        self.expect("(")
        if name == "IF":
            return self.parse_if()
        flat = self.collect_args()  # list of raw values (ranges expanded)
        self.expect(")")
        if name in _AGG_FUNCS:
            return float(_AGG_FUNCS[name](flat))
        if name in ("AND", "OR", "NOT"):
            truths = [self._truth(x) for x in flat if x != ""]
            if name == "AND": return 1.0 if all(truths) else 0.0
            if name == "OR":  return 1.0 if any(truths) else 0.0
            return 0.0 if (truths and truths[0]) else 1.0
        if name in _SCALAR_FUNCS:
            nums = [_num(x) for x in flat]
            return _finite(float(_SCALAR_FUNCS[name](nums)))
        raise FormulaError(f"unknown function {name}")

    def parse_if(self):
        cond = self.parse_or()
        self.expect(",")
        # Always parse both branches (syntax check), but use only one.
        then_start = self.i
        self._skip_arg()
        self.expect(",")
        else_start = self.i
        self._skip_arg()
        self.expect(")")
        branch = then_start if self._truth(cond) else else_start
        sub = _Parser(self.toks[branch:], self.grid, self.visited)
        return sub.parse_or()

    def collect_args(self):
        """Collects arguments; an 'A1:B3' token pair is expanded into a value list."""
        out = []
        if self.peek()[1] == ")":
            return out
        while True:
            # Detect a range: ref ':' ref
            if self.peek()[0] == "ref" and self.toks[self.i + 1][1] == ":":
                c0 = self.next()[1]
                self.expect(":")
                if self.peek()[0] != "ref":
                    raise FormulaError("range expects a cell after ':'")
                c1 = self.next()[1]
                for rc in resolve_range(c0, c1):
                    out.append(self._eval_ref(rc))
            else:
                out.append(self.parse_or())
            if self.peek()[1] == ",":
                self.next(); continue
            break
        return out

    def _skip_arg(self):
        """Skips one argument up to the next , or ) at paren depth 0."""
        depth = 0
        while True:
            kind, val = self.peek()
            if kind == "end":
                raise FormulaError("incomplete IF")
            if depth == 0 and val in (",", ")"):
                return
            if val == "(":
                depth += 1
            elif val == ")":
                depth -= 1
            self.next()

    # --- Helpers ---
    def _truth(self, v):
        return bool(_num(v) != 0.0) if not isinstance(v, str) else (v not in ("", "0", "0.0"))

    def _eval_ref(self, ref):
        norm = ref.replace("$", "")
        v = eval_cell(norm, self.grid, self.visited.copy())
        if v == "CIRC!":
            raise _Circular()
        if v == "ERROR":
            raise FormulaError("reference error")
        return v


def safe_math_eval(expr):
    """Evaluates a pure (cell-free) expression. Drop-in replacement for the
    previous string eval. Returns float or 'ERROR'."""
    try:
        v = _Parser(_tokenize(str(expr).upper()), {}, set()).parse()
        return float(v)
    except Exception:
        return "ERROR"


def eval_cell(cell_id, grid, visited=None):
    """Recursively computes a cell's value, resolving formulas.
    Returns: float (number), str (text / error code) or "" (empty)."""
    if visited is None:
        visited = set()

    if cell_id in visited:
        return "CIRC!"  # circular-reference error

    val = grid.get(cell_id, "")
    if not val:
        return ""

    if not val.startswith("="):
        # Not a formula -> try as number, otherwise text
        try:
            return float(val)
        except ValueError:
            return val

    # Evaluate the formula
    visited.add(cell_id)
    formula = val[1:].upper().strip()
    if not formula:
        return ""
    try:
        result = _Parser(_tokenize(formula), grid, visited).parse()
        return float(result)
    except _Circular:
        return "CIRC!"
    except FormulaError:
        return "ERROR"
    except Exception:
        return "ERROR"


# --- EXPORT & IMPORT (CSV) ---

def save_csv(filename, grid, formats, col_widths):
    """Saves the cell table as a CSV file and the formats into a .fmt sidecar."""
    max_col = 0
    max_row = 0
    for cell_id, val in grid.items():
        if val:
            c, r = parse_cell_id(cell_id)
            if c > max_col: max_col = c
            if r > max_row: max_row = r
            
    rows = [["" for _ in range(max_col + 1)] for _ in range(max_row + 1)]
    for cell_id, val in grid.items():
        if val:
            c, r = parse_cell_id(cell_id)
            rows[r][c] = val
            
    try:
        with open(filename, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerows(rows)
        # Save formats and column widths in a sidecar file
        with open(filename + ".fmt", "w", encoding="utf-8") as f:
            json.dump({"formats": formats, "col_widths": col_widths}, f)
        return True
    except Exception:
        return False

def load_csv(filename):
    """Loads data from a CSV file and formats from a .fmt file."""
    new_grid = {}
    new_formats = {}
    new_col_widths = {}
    try:
        if not os.path.exists(filename):
            return None
        with open(filename, "r", newline="", encoding="utf-8") as f:
            reader = csv.reader(f, delimiter=";")
            for r_idx, row in enumerate(reader):
                for c_idx, val in enumerate(row):
                    if val.strip():
                        cell_id = get_cell_id(c_idx, r_idx)
                        new_grid[cell_id] = val.strip()
                        
        if os.path.exists(filename + ".fmt"):
            with open(filename + ".fmt", "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, dict) and "formats" in data:
                    new_formats = data.get("formats", {})
                    for k, v in data.get("col_widths", {}).items():
                        try:
                            new_col_widths[int(k)] = v
                        except ValueError:
                            pass
                else:
                    new_formats = data 
                
        return new_grid, new_formats, new_col_widths
    except Exception:
        return None

# --- EVENT MAPPING (PYGAME KEYS -> CHARS) ---

def pygame_key_to_char(key, mods):
    """Translates key input into upper-case letters and symbols."""
    import pygame
    shift = bool(mods & pygame.KMOD_SHIFT)
    
    if pygame.K_0 <= key <= pygame.K_9:
        val = key - pygame.K_0
        if shift:
            if val == 8: return "("
            if val == 9: return ")"
            if val == 7: return "/"
            if val == 5: return "%"
            if val == 4: return "$"
            if val == 0: return "="
            if val == 1: return "!"
            return str(val)
        return str(val)
        
    if pygame.K_a <= key <= pygame.K_z:
        return chr(key - pygame.K_a + ord('A'))
        
    if pygame.K_KP0 <= key <= pygame.K_KP9:
        return str(key - pygame.K_KP0)
        
    if key == pygame.K_PLUS or key == pygame.K_KP_PLUS: return "+"
    if key == pygame.K_MINUS or key == pygame.K_KP_MINUS: return "-"
    if key == pygame.K_ASTERISK or key == pygame.K_KP_MULTIPLY: return "*"
    if key == pygame.K_SLASH or key == pygame.K_KP_DIVIDE: return "/"
    if key == pygame.K_EQUALS: return "="
    if key == pygame.K_PERIOD or key == pygame.K_KP_PERIOD: return ">" if shift else "."
    if key == pygame.K_COMMA: return "<" if shift else ","
    if key == pygame.K_LESS: return ">" if shift else "<"
    if key == pygame.K_SEMICOLON: return ":" if shift else ";"
    if key == pygame.K_SPACE: return " "
    
    return None

# --- ON-SCREEN KEYBOARD LAYOUT ---
# The keyboard is now 13 columns wide to make room for the logic symbols!
KBD_LAYOUT = [
    ["1","2","3","4","5","6","7","8","9","0","+","-","!"],
    ["Q","W","E","R","T","Z","U","I","O","P","*","/","="],
    ["A","S","D","F","G","H","J","K","L","(",")","<",">"],
    ["Y","X","C","V","B","N","M",".",",",":","SPC","DEL","ENT"]
]

# --- LIFECYCLE METHODS ---

def init(win):
    """Initializes the window state."""
    win["grid"] = {}             # Stores the raw cell formulas (e.g. A1 -> "=B1*2")
    win["formats"] = {}          # Stores the cell background colors
    win["col_widths"] = {}       # Stores manually adjusted column widths
    win["resizing_col"] = None   # Which column is currently being resized?
    win["resize_start_x"] = 0    # Mouse start X when the resize began
    win["resize_start_w"] = 0    # Initial column width at resize start
    win["sel_col"] = 0           # Currently selected column (0-25 -> A-Z)
    win["sel_row"] = 0           # Currently selected row (0-98 -> 1-99)
    win["scroll_col"] = 0        # Column scroll offset
    win["scroll_row"] = 0        # Row scroll offset
    win["editing"] = False       # True when in formula-edit mode
    win["edit_text"] = ""        # Current text input for the formula
    win["editing_filename"] = False # True when in filename-edit mode
    win["filename"] = "SHEET.CSV"
    win["t"] = 0                 # Frame counter for the blinking cursor
    win["prev_keys"] = None      # Prevents repeated input while a key is held
    win["message"] = "Ready"    # Status message in the footer
    win["msg_timer"] = 0         # Timer for status messages
    win["show_keyboard"] = False # On-screen keyboard state
    win["clipboard"] = None      # Clipboard for copy & paste
    win["show_chart"] = False    # NEW: show the chart instead of the grid

def update(win, lx, ly, m_pressed, m_sec_pressed, m_held):
    """Updates calculations, mouse input and keyboard events."""
    import pygame
    win["t"] += 1
    
    if win["msg_timer"] > 0:
        win["msg_timer"] -= 1
    else:
        win["message"] = "Ready"
        
    row_height = 11
    kbd_height = 56 if win["show_keyboard"] else 0
    visible_rows = min(99, max(1, (win["h"] - 68 - kbd_height) // row_height))
    
    # 0. DRAG & DROP FOR COLUMN WIDTHS
    if win.get("resizing_col") is not None:
        if m_held:
            delta = lx - win["resize_start_x"]
            new_w = max(15, win["resize_start_w"] + delta) # min width 15 pixels
            win["col_widths"][win["resizing_col"]] = new_w
        else:
            win["resizing_col"] = None
    
    # 1. HANDLE MOUSE CLICKS (only when not currently resizing columns)
    if m_pressed and win.get("resizing_col") is None:
        # Click on the toolbar row (Y: 16 to 28)
        if 16 <= ly <= 28:
            # Filename input field (X: 6 to 74)
            if 6 <= lx <= 74:
                win["editing_filename"] = True
                win["editing"] = False
            # LOAD button (X: 78 to 110)
            elif 78 <= lx <= 110:
                data = load_csv(win["filename"])
                if data is not None:
                    win["grid"], win["formats"], win["col_widths"] = data
                    win["message"] = "File loaded!"
                else:
                    win["message"] = "Load failed!"
                win["msg_timer"] = 120
                win["editing_filename"] = False
            # SAVE button (X: 114 to 154)
            elif 114 <= lx <= 154:
                # Auto-commit any open cell edit
                if win["editing"]:
                    prev_cell = get_cell_id(win["sel_col"], win["sel_row"])
                    win["grid"][prev_cell] = win["edit_text"]
                    win["editing"] = False
                
                success = save_csv(win["filename"], win["grid"], win["formats"], win["col_widths"])
                if success:
                    win["message"] = "File saved!"
                else:
                    win["message"] = "Save failed!"
                win["msg_timer"] = 120
                win["editing_filename"] = False
            # NEW button (X: 158 to 182)
            elif 158 <= lx <= 182:
                win["grid"] = {}
                win["formats"] = {}
                win["col_widths"] = {}
                win["sel_col"] = 0
                win["sel_row"] = 0
                win["scroll_col"] = 0
                win["scroll_row"] = 0
                win["editing"] = False
                win["editing_filename"] = False
                win["message"] = "Sheet cleared!"
                win["msg_timer"] = 120
            # KBD button (X: 186 to 214) - toggle the on-screen keyboard
            elif 186 <= lx <= 214:
                win["show_keyboard"] = not win["show_keyboard"]
                
        # Click on the formula bar (Y: 32 to 44)
        elif 32 <= ly <= 44:
            if 32 <= lx <= 56: # COPY button
                cell_id = get_cell_id(win["sel_col"], win["sel_row"])
                win["clipboard"] = {
                    "col": win["sel_col"],
                    "row": win["sel_row"],
                    "text": win["grid"].get(cell_id, ""),
                    "format": win["formats"].get(cell_id, 7)
                }
                win["message"] = f"Copied: {cell_id}"
                win["msg_timer"] = 120
            elif 60 <= lx <= 88: # PASTE button
                if win.get("clipboard"):
                    source_c = win["clipboard"]["col"]
                    source_r = win["clipboard"]["row"]
                    dc = win["sel_col"] - source_c
                    dr = win["sel_row"] - source_r
                    shifted = shift_formula(win["clipboard"]["text"], dc, dr)
                    
                    target_id = get_cell_id(win["sel_col"], win["sel_row"])
                    win["grid"][target_id] = shifted
                    win["formats"][target_id] = win["clipboard"].get("format", 7)
                    win["message"] = f"Pasted: {target_id}"
                    win["msg_timer"] = 120
            elif 92 <= lx <= 116: # FMT button (cell formatting)
                cell_id = get_cell_id(win["sel_col"], win["sel_row"])
                current = win["formats"].get(cell_id, 7)
                colors = [7, 11, 10, 6, 14, 13] # white, green, yellow, grey, pink, indigo
                try:
                    idx = (colors.index(current) + 1) % len(colors)
                except ValueError:
                    idx = 0
                win["formats"][cell_id] = colors[idx]
            elif 120 <= lx <= 148: # CHART button (toggle chart)
                win["show_chart"] = not win.get("show_chart", False)
                win["editing_filename"] = False
                if win["editing"]:
                    prev_cell = get_cell_id(win["sel_col"], win["sel_row"])
                    win["grid"][prev_cell] = win["edit_text"]
                    win["editing"] = False
            elif 152 <= lx <= win["w"] - 6: # Click into the formula field
                win["editing"] = True
                win["editing_filename"] = False
                sel_id = get_cell_id(win["sel_col"], win["sel_row"])
                win["edit_text"] = win["grid"].get(sel_id, "")
            
        # Click on the column header (Y: 48 to 58) -> resize columns
        elif 48 <= ly <= 58:
            if lx >= 21:
                curr_x = 21
                col_idx = win["scroll_col"]
                while col_idx < 26 and curr_x < win["w"]:
                    cw = win["col_widths"].get(col_idx, 40)
                    curr_x += cw
                    # Check if the click is near the column's right divider (+/- 4 pixels)
                    if abs(lx - curr_x) <= 4:
                        win["resizing_col"] = col_idx
                        win["resize_start_x"] = lx
                        win["resize_start_w"] = cw
                        win["editing_filename"] = False
                        # Close any open edit
                        if win["editing"]:
                            prev_cell = get_cell_id(win["sel_col"], win["sel_row"])
                            win["grid"][prev_cell] = win["edit_text"]
                            win["editing"] = False
                        break
                    col_idx += 1
            
        # Click into the cell grid (Y: 58 + row coordinates)
        elif 58 + 10 <= ly <= 58 + 10 + visible_rows * row_height:
            if 21 <= lx <= win["w"] - 6:
                grid_x = lx - 21
                grid_y = ly - 68
                
                curr_x = 0
                click_col = win["scroll_col"]
                while click_col < 26:
                    cw = win["col_widths"].get(click_col, 40)
                    if curr_x <= grid_x < curr_x + cw:
                        break
                    curr_x += cw
                    click_col += 1
                
                click_row = win["scroll_row"] + (grid_y // row_height)
                
                if click_col < 26 and click_row < 99:
                    win["editing_filename"] = False
                    # Clicking the already-selected cell again starts edit mode
                    if win["sel_col"] == click_col and win["sel_row"] == click_row:
                        win["editing"] = True
                        cell_id = get_cell_id(click_col, click_row)
                        win["edit_text"] = win["grid"].get(cell_id, "")
                    else:
                        # Commit the previous cell edit
                        if win["editing"]:
                            prev_cell = get_cell_id(win["sel_col"], win["sel_row"])
                            win["grid"][prev_cell] = win["edit_text"]
                            win["editing"] = False
                        win["sel_col"] = click_col
                        win["sel_row"] = click_row

        # Click on the on-screen keyboard
        if win["show_keyboard"] and ly >= win["h"] - 12 - 56:
            kbd_y_start = win["h"] - 12 - 56
            start_x = (win["w"] - 208) // 2  # adjusted for 13 columns
            
            # Figure out which key was clicked
            if start_x <= lx <= start_x + 208 and ly >= kbd_y_start + 4:
                col = (lx - start_x) // 16
                row = (ly - kbd_y_start - 4) // 13
                
                if 0 <= col < 13 and 0 <= row < 4:
                    char = KBD_LAYOUT[row][col]
                    
                    if char == "DEL":
                        if win["editing_filename"]: win["filename"] = win["filename"][:-1]
                        elif win["editing"]: win["edit_text"] = win["edit_text"][:-1]
                    elif char == "ENT":
                        if win["editing_filename"]:
                            win["editing_filename"] = False
                        elif win["editing"]:
                            cell_id = get_cell_id(win["sel_col"], win["sel_row"])
                            win["grid"][cell_id] = win["edit_text"]
                            win["editing"] = False
                            win["sel_row"] = min(98, win["sel_row"] + 1)
                        else:
                            win["editing"] = True
                            cell_id = get_cell_id(win["sel_col"], win["sel_row"])
                            win["edit_text"] = win["grid"].get(cell_id, "")
                    else:
                        if char == "SPC": char = " "
                        
                        # If nothing is being edited yet, start edit mode
                        if not win["editing"] and not win["editing_filename"]:
                            win["editing"] = True
                            win["edit_text"] = char
                        # Otherwise append to the relevant text
                        elif win["editing_filename"] and len(win["filename"]) < 16:
                            win["filename"] += char
                        elif win["editing"] and len(win["edit_text"]) < 64:
                            win["edit_text"] += char
                        
    # 2. HANDLE KEYBOARD (via pygame key polling)
    keys = pygame.key.get_pressed()
    mods = pygame.key.get_mods()
    
    if win["prev_keys"] is None:
        win["prev_keys"] = keys
        
    # Scan all keys for rising edges (just pressed)
    for key_idx in range(len(keys)):
        if keys[key_idx] and not win["prev_keys"][key_idx]:
            ctrl = bool(mods & pygame.KMOD_CTRL)
            
            # --- Shortcuts: copy & paste (CTRL+C / CTRL+V) ---
            if ctrl and not win["editing"] and not win["editing_filename"]:
                if key_idx == pygame.K_c:
                    cell_id = get_cell_id(win["sel_col"], win["sel_row"])
                    win["clipboard"] = {
                        "col": win["sel_col"],
                        "row": win["sel_row"],
                        "text": win["grid"].get(cell_id, ""),
                        "format": win["formats"].get(cell_id, 7)
                    }
                    win["message"] = f"Copied: {cell_id}"
                    win["msg_timer"] = 120
                    continue
                elif key_idx == pygame.K_v:
                    if win.get("clipboard"):
                        source_c = win["clipboard"]["col"]
                        source_r = win["clipboard"]["row"]
                        dc = win["sel_col"] - source_c
                        dr = win["sel_row"] - source_r
                        shifted = shift_formula(win["clipboard"]["text"], dc, dr)
                        target_id = get_cell_id(win["sel_col"], win["sel_row"])
                        win["grid"][target_id] = shifted
                        win["formats"][target_id] = win["clipboard"].get("format", 7)
                        win["message"] = f"Pasted: {target_id}"
                        win["msg_timer"] = 120
                    continue

            # --- CASE A: editing the filename ---
            if win["editing_filename"]:
                if key_idx == pygame.K_RETURN or key_idx == pygame.K_KP_ENTER:
                    win["editing_filename"] = False
                elif key_idx == pygame.K_BACKSPACE:
                    win["filename"] = win["filename"][:-1]
                else:
                    char = pygame_key_to_char(key_idx, mods)
                    if char and len(win["filename"]) < 16:
                        win["filename"] += char
                        
            # --- CASE B: editing cell content / formula ---
            elif win["editing"]:
                if key_idx == pygame.K_RETURN or key_idx == pygame.K_KP_ENTER:
                    cell_id = get_cell_id(win["sel_col"], win["sel_row"])
                    win["grid"][cell_id] = win["edit_text"]
                    win["editing"] = False
                    # Auto-advance one row down after confirming
                    win["sel_row"] = min(98, win["sel_row"] + 1)
                elif key_idx == pygame.K_ESCAPE:
                    win["editing"] = False
                elif key_idx == pygame.K_BACKSPACE:
                    win["edit_text"] = win["edit_text"][:-1]
                else:
                    char = pygame_key_to_char(key_idx, mods)
                    if char and len(win["edit_text"]) < 64:
                        win["edit_text"] += char
                        
            # --- CASE C: grid navigation ---
            else:
                if key_idx == pygame.K_UP:
                    win["sel_row"] = max(0, win["sel_row"] - 1)
                elif key_idx == pygame.K_DOWN:
                    win["sel_row"] = min(98, win["sel_row"] + 1)
                elif key_idx == pygame.K_LEFT:
                    win["sel_col"] = max(0, win["sel_col"] - 1)
                elif key_idx == pygame.K_RIGHT:
                    win["sel_col"] = min(25, win["sel_col"] + 1)
                elif key_idx == pygame.K_RETURN or key_idx == pygame.K_KP_ENTER:
                    win["editing"] = True
                    cell_id = get_cell_id(win["sel_col"], win["sel_row"])
                    win["edit_text"] = win["grid"].get(cell_id, "")
                elif key_idx == pygame.K_DELETE or key_idx == pygame.K_BACKSPACE:
                    cell_id = get_cell_id(win["sel_col"], win["sel_row"])
                    if cell_id in win["grid"]:
                        del win["grid"][cell_id]
                else:
                    # Typing immediately enters write mode
                    char = pygame_key_to_char(key_idx, mods)
                    if char:
                        win["editing"] = True
                        win["edit_text"] = char
                        
    win["prev_keys"] = keys
    
    # 3. AUTOMATIC GRID SCROLLING (keep the selection in view)
    # Freeze scroll logic while a column is being resized
    if win.get("resizing_col") is None:
        if win["sel_col"] < win["scroll_col"]:
            win["scroll_col"] = win["sel_col"]
        else:
            sel_x = 0
            for c in range(win["scroll_col"], win["sel_col"] + 1):
                sel_x += win["col_widths"].get(c, 40)
                
            # If the right edge of the selected cell goes off screen
            if sel_x > win["w"] - 27:
                while True:
                    win["scroll_col"] += 1
                    sel_x = 0
                    for c in range(win["scroll_col"], win["sel_col"] + 1):
                        sel_x += win["col_widths"].get(c, 40)
                    if sel_x <= win["w"] - 27 or win["scroll_col"] == win["sel_col"]:
                        break
                        
        if win["sel_row"] < win["scroll_row"]:
            win["scroll_row"] = win["sel_row"]
        elif win["sel_row"] >= win["scroll_row"] + visible_rows:
            win["scroll_row"] = win["sel_row"] - visible_rows + 1

def draw_button(bx, by, bw, bh, text, color):
    """Draws a retro-styled bevel button element."""
    import py16
    py16.rectfill(bx, by, bw, bh, color)
    py16.rect(bx, by, bw, bh, 0)
    tx = bx + (bw - len(text) * 4) // 2
    ty = by + (bh - 5) // 2
    py16.text(text, tx, ty, 7)

def draw(win, wx, wy, ww, wh, is_active):
    """Renders the spreadsheet user interface."""
    import py16
    
    row_height = 11
    kbd_height = 56 if win["show_keyboard"] else 0
    visible_rows = min(99, max(1, (wh - 68 - kbd_height) // row_height))
    
    # Window background (light grey)
    py16.rectfill(wx, wy + 12, ww, wh - 12, 6)
    
    # --- 1. TOOLBAR HEADER (file actions) ---
    # Filename input box
    file_bg = 10 if win["editing_filename"] else 7
    py16.rectfill(wx + 6, wy + 16, 68, 12, file_bg)
    py16.rect(wx + 6, wy + 16, 68, 12, 0)
    
    # Truncate text if too long for the box
    disp_file = win["filename"]
    if len(disp_file) > 16: disp_file = disp_file[:15] + " "
    py16.text(disp_file, wx + 8, wy + 20, 1)
    
    # Filename cursor blink
    if win["editing_filename"] and (win["t"] // 30) % 2 == 0:
        cursor_x = wx + 8 + len(disp_file) * 4
        py16.line(cursor_x, wy + 19, cursor_x, wy + 25, 1)
        
    # Functional bevel buttons
    draw_button(wx + 78, wy + 16, 32, 12, "LOAD", 11 if is_active else 5)
    draw_button(wx + 114, wy + 16, 40, 12, "SAVE", 12 if is_active else 5)
    draw_button(wx + 158, wy + 16, 24, 12, "NEW", 8 if is_active else 5)
    
    # NEW: keyboard toggle button
    draw_button(wx + 186, wy + 16, 28, 12, "KBD", 9 if win["show_keyboard"] else 5)
    
    # --- 2. FORMULA BAR (shows the current raw formula) ---
    sel_id = get_cell_id(win["sel_col"], win["sel_row"])
    
    # Cell-selection box (dark grey)
    py16.rectfill(wx + 6, wy + 32, 22, 12, 5)
    py16.rect(wx + 6, wy + 32, 22, 12, 0)
    py16.text(sel_id, wx + 8, wy + 36, 7)
    
    # NEW: copy / paste buttons in the formula bar
    draw_button(wx + 32, wy + 32, 24, 12, "COPY", 9 if is_active else 5)
    draw_button(wx + 60, wy + 32, 28, 12, "PASTE", 11 if is_active else 5)
    draw_button(wx + 92, wy + 32, 24, 12, "FMT", 10 if is_active else 5)
    draw_button(wx + 120, wy + 32, 28, 12, "CHART", 12 if win.get("show_chart") else 5)
    
    # Size the formula field
    py16.rectfill(wx + 152, wy + 32, ww - 158, 12, 7)
    py16.rect(wx + 152, wy + 32, ww - 158, 12, 0)
    
    # Render formula text or live input
    disp_formula = win["edit_text"] if win["editing"] else win["grid"].get(sel_id, "")
    max_chars = (ww - 160) // 4
    if len(disp_formula) > max_chars:
        disp_formula = disp_formula[:max_chars-3] + "..."
    py16.text(disp_formula, wx + 156, wy + 36, 1)
    
    # Formula cursor blink
    if win["editing"] and (win["t"] // 30) % 2 == 0:
        cursor_x = wx + 156 + len(win["edit_text"]) * 4
        if cursor_x < wx + ww - 10:
            py16.line(cursor_x, wy + 35, cursor_x, wy + 41, 1)
            
    # --- 3. RENDERING: CHART OR TABLE ---
    col_start_x = 21
    grid_start_y = 48
    
    if win.get("show_chart"):
        # === CHART VIEW ===
        chart_y = wy + grid_start_y
        chart_h = wh - grid_start_y - kbd_height - 12 # 12 for the status bar
        chart_w = ww - 12
        chart_x = wx + 6
        
        # Background and border
        py16.rectfill(chart_x, chart_y, chart_w, chart_h, 0)
        py16.rect(chart_x, chart_y, chart_w, chart_h, 5)
        
        # Read the data of the active column
        col_name = get_cell_id(win["sel_col"], 0)[:-1]
        data_pts = []
        for r in range(99):
            cell_id = f"{col_name}{r+1}"
            val = eval_cell(cell_id, win["grid"])
            try:
                v = float(val)
                data_pts.append((r, v))
            except (ValueError, TypeError):
                pass
                
        if not data_pts:
            py16.text(f"NO DATA IN COLUMN {col_name}", chart_x + 10, chart_y + chart_h // 2, 8)
        else:
            py16.text(f"CHART: COLUMN {col_name}", chart_x + 4, chart_y + 4, 7)
            
            min_v = min(0, min(v for _, v in data_pts))
            max_v = max(0.001, max(v for _, v in data_pts)) # Avoid division by zero
            range_v = max_v - min_v
            
            pad_top = 15
            pad_bot = 5
            plot_h = chart_h - pad_top - pad_bot
            
            # Compute the position of the zero line
            zero_y = chart_y + pad_top + plot_h - int((0 - min_v) / range_v * plot_h)
            
            # Draw the zero line
            py16.line(chart_x, zero_y, chart_x + chart_w, zero_y, 5)
            
            # Compute and draw the bars
            n_bars = len(data_pts)
            bar_space = chart_w / n_bars
            bar_w = max(1, int(bar_space) - 1)
            
            for i, (r, v) in enumerate(data_pts):
                bx = chart_x + 1 + int(i * bar_space)
                bh = int(abs(v) / range_v * plot_h)
                
                if v >= 0:
                    by = zero_y - bh
                    color = 11 # green for positive values
                else:
                    by = zero_y
                    color = 8  # red for negative values
                    
                if bh > 0:
                    py16.rectfill(bx, by, bar_w, bh, color)
                    
            # Min/max labels in light grey
            py16.text(str(int(max_v) if max_v.is_integer() else f"{max_v:.1f}"), chart_x + 2, chart_y + pad_top, 6)
            if min_v < 0:
                py16.text(str(int(min_v) if min_v.is_integer() else f"{min_v:.1f}"), chart_x + 2, chart_y + chart_h - 10, 6)

    else:
        # === TABLE VIEW ===
        # Column headers (A, B, C...)
        curr_x = col_start_x
        col_idx = win["scroll_col"]
        while curr_x < ww - 6 and col_idx < 26:
            cw = win["col_widths"].get(col_idx, 40)
            col_name = get_cell_id(col_idx, 0)[:-1]
            px = wx + curr_x
            
            # If the column runs off the right edge, clip it visually
            draw_w = min(cw, (ww - 6) - curr_x)
            if draw_w > 0:
                py16.rectfill(px, wy + grid_start_y, draw_w, 10, 5)
                py16.rect(px, wy + grid_start_y, draw_w, 10, 0)
                
                # Center the text if there is enough room
                if draw_w > 8:
                    tx = px + max(2, (cw - len(col_name) * 4) // 2)
                    if tx + len(col_name) * 4 <= px + draw_w:
                        py16.text(col_name, tx, wy + grid_start_y + 3, 7)
            
            curr_x += cw
            col_idx += 1
                
        # Row headers (1, 2, 3...)
        for r in range(visible_rows):
            curr_row = win["scroll_row"] + r
            if curr_row < 99:
                row_name = str(curr_row + 1)
                py = wy + grid_start_y + 10 + r * row_height
                py16.rectfill(wx + 6, py, 15, row_height, 5)
                py16.rect(wx + 6, py, 15, row_height, 0)
                # Centering offset for two-digit numbers
                tx = wx + 8 if len(row_name) == 1 else wx + 6
                py16.text(row_name, tx, py + 3, 7)
                
        # --- 4. RENDER THE CELL GRID (with active clipping) ---
        py16.clip(wx + 21, wy + grid_start_y + 10, ww - 27, visible_rows * row_height)
        
        curr_x = col_start_x
        col_idx = win["scroll_col"]
        while curr_x < ww - 6 and col_idx < 26:
            cw = win["col_widths"].get(col_idx, 40)
            cell_col_name = get_cell_id(col_idx, 0)[:-1]
            px = wx + curr_x
            
            for r in range(visible_rows):
                curr_row = win["scroll_row"] + r
                if curr_row >= 99: continue
                
                cell_name = f"{cell_col_name}{curr_row + 1}"
                py = wy + grid_start_y + 10 + r * row_height
                
                is_selected = (col_idx == win["sel_col"] and curr_row == win["sel_row"])
                
                # Load the cell background color from the formats
                if is_selected:
                    cell_bg = 12
                else:
                    cell_bg = win["formats"].get(cell_name, 7)
                    
                py16.rectfill(px, py, cw, row_height, cell_bg)
                py16.rect(px, py, cw, row_height, 0)
                
                if is_selected and win["editing"]:
                    val_str = win["edit_text"]
                    text_color = 7
                else:
                    # Compute formula or value
                    val = eval_cell(cell_name, win["grid"])
                    if isinstance(val, float):
                        if val.is_integer():
                            val_str = str(int(val))
                        else:
                            val_str = f"{val:.2f}"
                    else:
                        val_str = str(val)
                    
                    # Compute the text color
                    if is_selected:
                        text_color = 7
                    else:
                        # Adjust contrast on dark background colors
                        text_color = 7 if cell_bg in [1, 2, 3, 5, 13] else 1
                        
                        # Automatic red for negative numbers
                        if text_color == 1:
                            try:
                                if float(val) < 0:
                                    text_color = 8
                            except (ValueError, TypeError):
                                pass
                    
                # Truncate text to the cell width
                max_cell_chars = max(0, (cw - 4) // 4)
                if len(val_str) > max_cell_chars:
                    val_str = val_str[:max_cell_chars]
                    
                # Right-align numbers, left-align text
                is_num = False
                try:
                    float(val_str)
                    is_num = True
                except ValueError:
                    pass
                    
                if is_num and len(val_str) > 0:
                    tx = px + cw - len(val_str) * 4 - 2
                else:
                    tx = px + 2
                    
                # Only draw if there is enough room (column not too narrow)
                if max_cell_chars > 0:
                    py16.text(val_str, tx, py + 3, text_color)
                    
            curr_x += cw
            col_idx += 1
                
        py16.clip() # Reset clipping
        
        # --- 4.6. COLUMN-RESIZE INDICATOR ---
        # Draws a red guide line while a column is being dragged
        if win.get("resizing_col") is not None:
            curr_x = col_start_x
            for c in range(win["scroll_col"], win["resizing_col"] + 1):
                curr_x += win["col_widths"].get(c, 40)
                
            py16.clip(wx + 21, wy + grid_start_y, ww - 27, 10 + visible_rows * row_height)
            # Red line across the grid
            py16.line(wx + curr_x, wy + grid_start_y, wx + curr_x, wy + grid_start_y + 10 + visible_rows * row_height, 8)
            py16.clip()
    
    # --- 4.5. RENDER THE ON-SCREEN KEYBOARD ---
    if win["show_keyboard"]:
        kbd_y = wy + wh - 12 - 56
        py16.rectfill(wx, kbd_y, ww, 56, 5) # Dark-grey background for the keyboard
        py16.line(wx, kbd_y, wx + ww, kbd_y, 0) # Divider line on top
        
        start_x = wx + (ww - 208) // 2
        for row_idx, row in enumerate(KBD_LAYOUT):
            for col_idx, key in enumerate(row):
                kx = start_x + col_idx * 16
                ky = kbd_y + 4 + row_idx * 13
                
                # Coloring: special keys vs standard keys
                bg_col = 8 if key == "DEL" else (11 if key == "ENT" else 6)
                
                py16.rectfill(kx, ky, 14, 11, bg_col)
                py16.rect(kx, ky, 14, 11, 0)
                
                # Center the text
                tx = kx + (14 - len(key) * 4) // 2 + 1
                if key in ("DEL", "ENT", "SPC"):
                    py16.text(key, tx - 1, ky + 3, 7 if bg_col != 6 else 1)
                else:
                    py16.text(key, tx, ky + 3, 1)
    
    # --- 5. FOOTER (status messages) ---
    status_y = wy + wh - 10
    py16.rectfill(wx + 6, status_y, ww - 12, 10, 1)
    status_text = win["message"].upper()
    py16.text(status_text, wx + 10, status_y + 3, 10) # yellow status text
    
    # Active window frame for nice visual feedback
    if is_active:
        py16.rect(wx, wy, ww, wh, 12)
