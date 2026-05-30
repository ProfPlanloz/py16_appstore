import random

APP = {
    "id": "mahjong",
    "name": "MAHJONG",
    "w": 180, 
    "h": 160,
    "resizable": False
}

def reset_game(win):
    """Builds the board and shuffles the tiles."""
    layout = []
    # Level 0 (Bottom): 6x6 grid + 4 wing tiles = 40 tiles
    for x in range(2, 14, 2):
        for y in range(0, 12, 2): 
            layout.append((0, x, y))
    layout.extend([(0, 0, 4), (0, 0, 6), (0, 14, 4), (0, 14, 6)])
    
    # Level 1 (Middle): 4x4 grid = 16 tiles
    for x in range(4, 12, 2):
        for y in range(2, 10, 2): 
            layout.append((1, x, y))
            
    # Level 2 (Top): 2x2 grid = 4 tiles
    for x in range(6, 10, 2):
        for y in range(4, 8, 2): 
            layout.append((2, x, y))
    
    # 60 tiles in total = 30 pairs
    # O = Circles (Münzen), B = Bamboo (Bambus), C = Characters (Schriftzeichen)
    types = ["O1", "O2", "O3", "O4", "O5", 
             "B1", "B2", "B3", "B4", "B5", 
             "C1", "C2", "C3", "C4", "C5"] * 4
    random.shuffle(types)
    
    win["tiles"] = []
    for i, (z, x, y) in enumerate(layout):
        win["tiles"].append({
            "id": i, "z": z, "x": x, "y": y, 
            "type": types[i], "active": True
        })
    win["selected"] = None
    win["won"] = False

def init(win):
    """Initialization when the plugin is loaded for the first time."""
    reset_game(win)

def is_free(win, t_idx):
    """Checks if a tile is selectable (Mahjong rules)."""
    t = win['tiles'][t_idx]
    if not t['active']: 
        return False
        
    has_top = False
    has_left = False
    has_right = False
    
    for i, other in enumerate(win['tiles']):
        if not other['active'] or i == t_idx: 
            continue
        
        # Overlap logic: The tiles are 2 grid units large each
        x_ov = max(0, min(other['x']+2, t['x']+2) - max(other['x'], t['x'])) > 0
        y_ov = max(0, min(other['y']+2, t['y']+2) - max(other['y'], t['y'])) > 0
        
        if other['z'] > t['z']:
            # Covered by a tile on a higher level
            if x_ov and y_ov: 
                has_top = True
        elif other['z'] == t['z']:
            # Blockages on the same level
            if y_ov:
                if other['x'] + 2 == t['x']: 
                    has_left = True
                elif t['x'] + 2 == other['x']: 
                    has_right = True
                    
    # Must not be covered from above, and must be free on at least one side
    if has_top: 
        return False
    if has_left and has_right: 
        return False
    return True

def update(win, lx, ly, mp, msp, mh):
    """Logic update when the window is focused."""
    if mp:
        # Ignore clicks on the title bar (OS handles this)
        if ly < 14:
            return
            
        # Check "New" button
        if 10 <= lx <= 60 and 142 <= ly <= 154:
            reset_game(win)
            return
            
        # Check "Shuffle" button (re-distribute only active tiles)
        if 70 <= lx <= 120 and 142 <= ly <= 154:
            active_types = [t['type'] for t in win['tiles'] if t['active']]
            random.shuffle(active_types)
            idx = 0
            for t in win['tiles']:
                if t['active']:
                    t['type'] = active_types[idx]
                    idx += 1
            win['selected'] = None
            return

        if win["won"]:
            return

        # Which tile was clicked? (Search from top to bottom)
        clicked_idx = -1
        for i in range(len(win["tiles"])-1, -1, -1):
            t = win["tiles"][i]
            if not t["active"]: 
                continue
                
            # Simulate screen coordinates (local to the window)
            sx = 16 + t['x'] * 8 - t['z'] * 2
            sy = 16 + t['y'] * 10 - t['z'] * 3
            if sx <= lx <= sx+16 and sy <= ly <= sy+20:
                clicked_idx = i
                break
                
        # Execute action if free tile clicked
        if clicked_idx != -1 and is_free(win, clicked_idx):
            if win["selected"] == clicked_idx:
                # Deselect
                win["selected"] = None
            elif win["selected"] is not None:
                # Check for pair
                t1 = win["tiles"][win["selected"]]
                t2 = win["tiles"][clicked_idx]
                
                if t1['type'] == t2['type']:
                    # Match!
                    t1['active'] = False
                    t2['active'] = False
                    win["selected"] = None
                    
                    # Check win conditions
                    if not any(t['active'] for t in win["tiles"]):
                        win["won"] = True
                else:
                    # Select other tile
                    win["selected"] = clicked_idx
            else:
                win["selected"] = clicked_idx

def draw_symbol(py16, t_type, sx, sy):
    """Draws small pixel-art symbols for the Mahjong tiles."""
    n = int(t_type[1])
    
    # O = Circles
    if t_type[0] == 'O':
        c1 = 1 # Dark blue
        c2 = 8 # Red
        if n == 1:
            py16.circfill(sx+8, sy+10, 6, c1)
            py16.circfill(sx+8, sy+10, 4, c2)
            py16.circfill(sx+8, sy+10, 2, 10) # Center: Yellow
        elif n == 2:
            py16.circfill(sx+8, sy+5, 3, c1)
            py16.circfill(sx+8, sy+15, 3, c2)
        elif n == 3:
            py16.circfill(sx+4, sy+4, 2, c1)
            py16.circfill(sx+8, sy+10, 2, c2)
            py16.circfill(sx+12, sy+16, 2, c1)
        elif n == 4:
            py16.circfill(sx+4, sy+5, 2, c1)
            py16.circfill(sx+12, sy+5, 2, c1)
            py16.circfill(sx+4, sy+15, 2, c2)
            py16.circfill(sx+12, sy+15, 2, c2)
        elif n == 5:
            py16.circfill(sx+4, sy+4, 2, c1)
            py16.circfill(sx+12, sy+4, 2, c1)
            py16.circfill(sx+8, sy+10, 2, c2)
            py16.circfill(sx+4, sy+16, 2, c1)
            py16.circfill(sx+12, sy+16, 2, c1)

    # B = Bamboo
    elif t_type[0] == 'B':
        c = 3 # Dark green
        c2 = 1 # Dark blue
        
        def stick(x, y, color):
            py16.rectfill(x, y, 2, 6, color)
            py16.pset(x, y+2, 7) # White highlight
            
        if n == 1:
            # A large special bamboo shoot
            py16.rectfill(sx+6, sy+5, 4, 10, c)
            py16.rectfill(sx+5, sy+9, 6, 2, c2)
            py16.circfill(sx+8, sy+10, 1, 8)
        elif n == 2:
            stick(sx+7, sy+3, c)
            stick(sx+7, sy+11, c2)
        elif n == 3:
            stick(sx+7, sy+3, c2)
            stick(sx+4, sy+11, c)
            stick(sx+10, sy+11, c)
        elif n == 4:
            stick(sx+4, sy+3, c)
            stick(sx+10, sy+3, c2)
            stick(sx+4, sy+11, c2)
            stick(sx+10, sy+11, c)
        elif n == 5:
            stick(sx+4, sy+3, c)
            stick(sx+10, sy+3, c2)
            stick(sx+7, sy+7, c)
            stick(sx+4, sy+11, c2)
            stick(sx+10, sy+11, c)

    # C = Characters
    elif t_type[0] == 'C':
        c = 1 # Blue for the top number
        cr = 8 # Red for the bottom character
        
        # Bottom character "Wan" (highly simplified for 8-bit)
        py16.line(sx+5, sy+13, sx+11, sy+13, cr)
        py16.line(sx+8, sy+13, sx+8, sy+16, cr)
        py16.line(sx+5, sy+15, sx+11, sy+15, cr)
        py16.line(sx+8, sy+16, sx+5, sy+18, cr)
        py16.line(sx+8, sy+16, sx+11, sy+18, cr)

        # Top character (numbers 1-5)
        yt = sy+4
        if n == 1:
            py16.line(sx+5, yt+2, sx+11, yt+2, c)
        elif n == 2:
            py16.line(sx+6, yt, sx+10, yt, c)
            py16.line(sx+5, yt+4, sx+11, yt+4, c)
        elif n == 3:
            py16.line(sx+5, yt-1, sx+11, yt-1, c)
            py16.line(sx+6, yt+2, sx+10, yt+2, c)
            py16.line(sx+4, yt+5, sx+12, yt+5, c)
        elif n == 4:
            py16.rect(sx+5, yt, 6, 5, c)
            py16.line(sx+7, yt+1, sx+7, yt+3, c)
            py16.line(sx+9, yt+1, sx+9, yt+3, c)
        elif n == 5:
            py16.line(sx+5, yt, sx+11, yt, c)
            py16.line(sx+8, yt, sx+8, yt+5, c)
            py16.line(sx+5, yt+3, sx+11, yt+3, c)
            py16.line(sx+5, yt+2, sx+5, yt+5, c)
            py16.line(sx+4, yt+5, sx+12, yt+5, c)


def draw(win, wx, wy, ww, wh, active):
    """Draws the game board and UI into the window."""
    import py16
    from __main__ import tr
    
    # Background (table) - Only fill the content area to leave the window frame visible
    py16.clip(wx+1, wy+14, ww-2, wh-15)
    py16.rectfill(wx+1, wy+14, ww-2, wh-15, 3) # Classic dark green
    
    # Render tiles (from bottom to top, for correct 3D effect)
    for i, t in enumerate(win["tiles"]):
        if not t["active"]: 
            continue
        
        sx = wx + 16 + t['x'] * 8 - t['z'] * 2
        sy = wy + 16 + t['y'] * 10 - t['z'] * 3
        
        free = is_free(win, i)
        selected = (win["selected"] == i)
        
        # 3D shadow border bottom & right
        py16.rectfill(sx+2, sy+20, 16, 2, 5) 
        py16.rectfill(sx+16, sy+2, 2, 20, 5) 
        
        # Tile body
        bg = 7 # White for free tiles
        if not free: 
            bg = 6 # Grayish for blocked tiles
        if selected: 
            bg = 10 # Yellow for the selected tile
            
        py16.rectfill(sx, sy, 16, 20, bg)
        py16.rect(sx, sy, 16, 20, 1) # Border (Dark blue)
        
        # Draw pixel-art symbol on the tile
        draw_symbol(py16, t['type'], sx, sy)
        
    # Bottom menu bar
    py16.rectfill(wx+10, wy+142, 50, 12, 6)
    py16.rect(wx+10, wy+142, 50, 12, 1) 
    py16.text(tr("NEW"), wx+28, wy+146, 1) 
    
    py16.rectfill(wx+70, wy+142, 50, 12, 6)
    py16.rect(wx+70, wy+142, 50, 12, 1) 
    py16.text(tr("SHUFFLE"), wx+81, wy+146, 1) 
    
    # Victory screen
    if win["won"]:
        py16.rectfill(wx+40, wy+60, 100, 30, 1) 
        py16.rect(wx+40, wy+60, 100, 30, 10)
        py16.text("YOU WIN!", wx+72, wy+72, 10)
        
    py16.clip()