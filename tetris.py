"""Tetris — anpassat för pygame-pad (RPi Zero 2W, 600×1024 pekskärm).

Styrning:
  - Svep vänster/höger → flytta bricka
  - Svep upp → rotera
  - Svep ner → snabb fall (soft drop)
  - Tryck (tap) → rotera
  - HOME-knapp / ESC / × → tillbaka till launcher
"""

import pygame
import random
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'py-desktop'))
try:
    from status_bar import draw_status_bar, status_bar_quit_clicked, STATUS_H
    _HAS_SB = True
except ImportError:
    _HAS_SB = False
    STATUS_H = 30

HOME_EVENT = pygame.USEREVENT + 102

# --- Färger ---
BG_COLOR      = (8,   10,  18)
PANEL_COLOR   = (16,  20,  34)
GRID_COLOR    = (22,  28,  46)
GRID_LINE     = (30,  38,  62)
TEXT_COLOR    = (210, 215, 235)
DIM_COLOR     = (90, 100, 120)
SCORE_COLOR   = (0,  220, 170)
LEVEL_COLOR   = (220, 160,  0)
BTN_COLOR     = (28,  36,  58)
BTN_OUTLINE   = (0,  170, 130)
GHOST_ALPHA   = 55

# Tetromino-färger (en per typ)
COLORS = {
    "I": (0,   210, 220),
    "O": (240, 200,   0),
    "T": (180,  60, 220),
    "S": (40,  200,  80),
    "Z": (230,  50,  60),
    "J": (50,  110, 230),
    "L": (240, 140,  20),
}

# Former: rotationer som lista av (col, row)-offset från pivot
SHAPES = {
    "I": [[(0,1),(1,1),(2,1),(3,1)], [(2,0),(2,1),(2,2),(2,3)],
          [(0,2),(1,2),(2,2),(3,2)], [(1,0),(1,1),(1,2),(1,3)]],
    "O": [[(1,0),(2,0),(1,1),(2,1)]]*4,
    "T": [[(0,1),(1,1),(2,1),(1,0)], [(1,0),(1,1),(1,2),(2,1)],
          [(0,1),(1,1),(2,1),(1,2)], [(1,0),(1,1),(1,2),(0,1)]],
    "S": [[(1,0),(2,0),(0,1),(1,1)], [(1,0),(1,1),(2,1),(2,2)],
          [(1,1),(2,1),(0,2),(1,2)], [(0,0),(0,1),(1,1),(1,2)]],
    "Z": [[(0,0),(1,0),(1,1),(2,1)], [(2,0),(1,1),(2,1),(1,2)],
          [(0,1),(1,1),(1,2),(2,2)], [(1,0),(0,1),(1,1),(0,2)]],
    "J": [[(0,0),(0,1),(1,1),(2,1)], [(1,0),(2,0),(1,1),(1,2)],
          [(0,1),(1,1),(2,1),(2,2)], [(1,0),(1,1),(0,2),(1,2)]],
    "L": [[(2,0),(0,1),(1,1),(2,1)], [(1,0),(1,1),(1,2),(2,2)],
          [(0,1),(1,1),(2,1),(0,2)], [(0,0),(1,0),(1,1),(1,2)]],
}

COLS       = 10
ROWS       = 20
CELL       = 38          # pixlar per cell
FPS        = 60

SWIPE_THRESHOLD = 40
SWIPE_DEAD_ZONE = 12

# Fallhastighet: ticks per steg per nivå
FALL_SPEEDS = [48, 43, 38, 33, 28, 23, 18, 13, 8, 6, 5, 4, 3, 2, 1]

LINES_PER_LEVEL = 10


# ---------------------------------------------------------------------------
# Tetromino-klass
# ---------------------------------------------------------------------------

class Piece:
    def __init__(self, kind):
        self.kind   = kind
        self.color  = COLORS[kind]
        self.rot    = 0
        self.col    = COLS // 2 - 2
        self.row    = 0

    def cells(self, col=None, row=None, rot=None):
        c = self.col if col is None else col
        r = self.row if row is None else row
        rt = self.rot if rot is None else rot
        return [(c + dc, r + dr) for dc, dr in SHAPES[self.kind][rt % 4]]

    def rotated(self):
        return (self.rot + 1) % 4


# ---------------------------------------------------------------------------
# Spelplan
# ---------------------------------------------------------------------------

def empty_board():
    return [[None] * COLS for _ in range(ROWS)]


def valid(board, cells):
    for c, r in cells:
        if c < 0 or c >= COLS or r >= ROWS:
            return False
        if r >= 0 and board[r][c] is not None:
            return False
    return True


def lock(board, piece):
    for c, r in piece.cells():
        if 0 <= r < ROWS:
            board[r][c] = piece.color


def clear_lines(board):
    full = [r for r in range(ROWS) if all(board[r][c] is not None for c in range(COLS))]
    for r in full:
        del board[r]
        board.insert(0, [None] * COLS)
    return len(full)


def ghost_row(board, piece):
    r = piece.row
    while valid(board, piece.cells(row=r + 1)):
        r += 1
    return r


def random_piece():
    return Piece(random.choice(list(SHAPES.keys())))


# ---------------------------------------------------------------------------
# Ritfunktioner
# ---------------------------------------------------------------------------

def _cell_rect(offset_x, offset_y, col, row):
    return pygame.Rect(offset_x + col * CELL + 1,
                       offset_y + row * CELL + 1,
                       CELL - 2, CELL - 2)


def _draw_cell(surface, offset_x, offset_y, col, row, color, alpha=255, radius=4):
    rect = _cell_rect(offset_x, offset_y, col, row)
    if alpha < 255:
        s = pygame.Surface((rect.w, rect.h), pygame.SRCALPHA)
        pygame.draw.rect(s, (*color, alpha), (0, 0, rect.w, rect.h), border_radius=radius)
        surface.blit(s, rect.topleft)
    else:
        pygame.draw.rect(surface, color, rect, border_radius=radius)
        # Highlight-kant
        lighter = tuple(min(255, v + 60) for v in color)
        pygame.draw.line(surface, lighter, rect.topleft, (rect.right - 1, rect.top), 1)
        pygame.draw.line(surface, lighter, rect.topleft, (rect.left, rect.bottom - 1), 1)


def _draw_board(surface, board, offset_x, offset_y):
    # Bakgrund
    bg = pygame.Rect(offset_x, offset_y, COLS * CELL, ROWS * CELL)
    pygame.draw.rect(surface, PANEL_COLOR, bg)
    # Rutnät
    for c in range(COLS + 1):
        x = offset_x + c * CELL
        pygame.draw.line(surface, GRID_LINE, (x, offset_y), (x, offset_y + ROWS * CELL))
    for r in range(ROWS + 1):
        y = offset_y + r * CELL
        pygame.draw.line(surface, GRID_LINE, (offset_x, y), (offset_x + COLS * CELL, y))
    # Låsta brickor
    for r in range(ROWS):
        for c in range(COLS):
            if board[r][c]:
                _draw_cell(surface, offset_x, offset_y, c, r, board[r][c])


def _draw_piece(surface, piece, offset_x, offset_y, alpha=255):
    for c, r in piece.cells():
        if r >= 0:
            _draw_cell(surface, offset_x, offset_y, c, r, piece.color, alpha)


def _draw_ghost(surface, board, piece, offset_x, offset_y):
    gr = ghost_row(board, piece)
    if gr == piece.row:
        return
    ghost = Piece(piece.kind)
    ghost.col = piece.col
    ghost.row = gr
    ghost.rot = piece.rot
    _draw_piece(surface, ghost, offset_x, offset_y, alpha=GHOST_ALPHA)


def _draw_next(surface, next_piece, panel_x, panel_y, label_font, cell_size=22):
    label = label_font.render("NÄSTA", True, DIM_COLOR)
    surface.blit(label, (panel_x, panel_y))
    py = panel_y + 28
    cells = SHAPES[next_piece.kind][0]
    min_c = min(c for c, r in cells)
    min_r = min(r for c, r in cells)
    for dc, dr in cells:
        x = panel_x + (dc - min_c) * cell_size
        y = py + (dr - min_r) * cell_size
        rect = pygame.Rect(x + 1, y + 1, cell_size - 2, cell_size - 2)
        pygame.draw.rect(surface, next_piece.color, rect, border_radius=3)


def _draw_status(surface, screen_w, score, level, lines):
    if _HAS_SB:
        draw_status_bar(surface, screen_w, app_name="Tetris")
    else:
        pygame.draw.rect(surface, PANEL_COLOR, (0, 0, screen_w, STATUS_H))
        f = pygame.font.SysFont(None, 22)
        title = f.render("TETRIS", True, LEVEL_COLOR)
        surface.blit(title, (10, 7))


def _draw_quit(surface, screen_w):
    r = pygame.Rect(screen_w - 44, 5, 38, 22)
    pygame.draw.rect(surface, BTN_COLOR, r, border_radius=5)
    pygame.draw.rect(surface, BTN_OUTLINE, r, 1, border_radius=5)
    f = pygame.font.SysFont(None, 22)
    t = f.render("×", True, TEXT_COLOR)
    surface.blit(t, (r.centerx - t.get_width() // 2, r.centery - t.get_height() // 2))
    return r


def _draw_panel(surface, score, level, lines, next_piece, panel_x, panel_y, panel_w):
    font_l = pygame.font.SysFont(None, 28)
    font_s = pygame.font.SysFont(None, 24)
    y = panel_y

    def _stat(label, value, color):
        nonlocal y
        lbl = font_s.render(label, True, DIM_COLOR)
        surface.blit(lbl, (panel_x, y))
        val = font_l.render(str(value), True, color)
        surface.blit(val, (panel_x, y + 20))
        y += 55

    _stat("POÄNG", score, SCORE_COLOR)
    _stat("NIVÅ", level, LEVEL_COLOR)
    _stat("RADER", lines, TEXT_COLOR)

    y += 10
    _draw_next(surface, next_piece, panel_x, y, font_s)


def _draw_button(surface, rect, label, font):
    pygame.draw.rect(surface, BTN_COLOR, rect, border_radius=10)
    pygame.draw.rect(surface, BTN_OUTLINE, rect, 2, border_radius=10)
    t = font.render(label, True, TEXT_COLOR)
    surface.blit(t, (rect.centerx - t.get_width() // 2,
                     rect.centery - t.get_height() // 2))


def _draw_overlay(surface, screen_w, screen_h, title, title_color, score, font_big, font_med, font_s):
    overlay = pygame.Surface((screen_w, screen_h), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    surface.blit(overlay, (0, 0))

    t = font_big.render(title, True, title_color)
    surface.blit(t, (screen_w // 2 - t.get_width() // 2, screen_h // 2 - 100))

    sc = font_med.render(f"Poäng: {score}", True, SCORE_COLOR)
    surface.blit(sc, (screen_w // 2 - sc.get_width() // 2, screen_h // 2 - 40))

    btn = pygame.Rect(screen_w // 2 - 110, screen_h // 2 + 20, 220, 54)
    _draw_button(surface, btn, "Starta om", font_med)

    hint = font_s.render("ESC / × för att avsluta", True, DIM_COLOR)
    surface.blit(hint, (screen_w // 2 - hint.get_width() // 2, screen_h // 2 + 95))
    return btn


# ---------------------------------------------------------------------------
# Poängberäkning
# ---------------------------------------------------------------------------

LINE_SCORES = {1: 100, 2: 300, 3: 500, 4: 800}


def calc_score(cleared, level):
    return LINE_SCORES.get(cleared, 0) * (level + 1)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run_tetris(surface, screen_w, screen_h):
    """Entry point för launcher."""
    clock    = pygame.time.Clock()
    font_big = pygame.font.SysFont(None, 56)
    font_med = pygame.font.SysFont(None, 38)
    font_s   = pygame.font.SysFont(None, 26)

    # Layout: spelplan centrerad, sidopanel till höger
    board_w   = COLS * CELL
    board_h   = ROWS * CELL
    panel_w   = 100
    gap       = 14
    total_w   = board_w + gap + panel_w
    offset_x  = (screen_w - total_w) // 2
    offset_y  = STATUS_H + (screen_h - STATUS_H - board_h) // 2
    panel_x   = offset_x + board_w + gap
    panel_y   = offset_y + 10

    def _new_game():
        board = empty_board()
        piece = random_piece()
        nxt   = random_piece()
        return board, piece, nxt, 0, 0, 0, 0   # board,piece,next,score,level,lines,fall_tick

    board, piece, next_piece, score, level, lines, fall_tick = _new_game()

    game_over = False
    paused    = False

    swipe_start = None
    swiping     = False
    quit_rect   = None

    running = True
    while running:
        clock.tick(FPS)

        # ------------------------------------------------------------------ #
        # Events
        # ------------------------------------------------------------------ #
        for ev in pygame.event.get():
            if ev.type == pygame.QUIT:
                running = False

            elif ev.type == HOME_EVENT:
                running = False

            elif ev.type == pygame.KEYDOWN:
                if ev.key == pygame.K_ESCAPE:
                    running = False
                elif game_over:
                    if ev.key == pygame.K_r:
                        board, piece, next_piece, score, level, lines, fall_tick = _new_game()
                        game_over = False
                elif not paused:
                    if ev.key == pygame.K_LEFT:
                        if valid(board, piece.cells(col=piece.col - 1)):
                            piece.col -= 1
                    elif ev.key == pygame.K_RIGHT:
                        if valid(board, piece.cells(col=piece.col + 1)):
                            piece.col += 1
                    elif ev.key == pygame.K_UP:
                        nr = piece.rotated()
                        if valid(board, piece.cells(rot=nr)):
                            piece.rot = nr
                        # Wall-kick: prova ±1
                        elif valid(board, piece.cells(col=piece.col + 1, rot=nr)):
                            piece.col += 1
                            piece.rot = nr
                        elif valid(board, piece.cells(col=piece.col - 1, rot=nr)):
                            piece.col -= 1
                            piece.rot = nr
                    elif ev.key == pygame.K_DOWN:
                        if valid(board, piece.cells(row=piece.row + 1)):
                            piece.row += 1
                    elif ev.key == pygame.K_SPACE:
                        # Hard drop
                        piece.row = ghost_row(board, piece)
                        fall_tick = 9999

            elif ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                pos = ev.pos
                if _HAS_SB and status_bar_quit_clicked(pos):
                    running = False
                elif game_over:
                    btn = pygame.Rect(screen_w // 2 - 110, screen_h // 2 + 20, 220, 54)
                    if btn.collidepoint(pos):
                        board, piece, next_piece, score, level, lines, fall_tick = _new_game()
                        game_over = False
                else:
                    swipe_start = pos
                    swiping = True

            elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1 and swiping:
                if swipe_start and not game_over:
                    dx = ev.pos[0] - swipe_start[0]
                    dy = ev.pos[1] - swipe_start[1]
                    adx, ady = abs(dx), abs(dy)

                    if adx < SWIPE_DEAD_ZONE and ady < SWIPE_DEAD_ZONE:
                        # Tap → rotera
                        nr = piece.rotated()
                        if valid(board, piece.cells(rot=nr)):
                            piece.rot = nr
                        elif valid(board, piece.cells(col=piece.col + 1, rot=nr)):
                            piece.col += 1; piece.rot = nr
                        elif valid(board, piece.cells(col=piece.col - 1, rot=nr)):
                            piece.col -= 1; piece.rot = nr
                    elif adx > SWIPE_THRESHOLD or ady > SWIPE_THRESHOLD:
                        if adx > ady:
                            steps = max(1, int(adx / CELL))
                            if dx > 0:
                                for _ in range(steps):
                                    if valid(board, piece.cells(col=piece.col + 1)):
                                        piece.col += 1
                            else:
                                for _ in range(steps):
                                    if valid(board, piece.cells(col=piece.col - 1)):
                                        piece.col -= 1
                        else:
                            if dy > SWIPE_THRESHOLD:
                                # Svep ner → hard drop
                                piece.row = ghost_row(board, piece)
                                fall_tick = 9999
                            elif dy < -SWIPE_THRESHOLD:
                                # Svep upp → rotera
                                nr = piece.rotated()
                                if valid(board, piece.cells(rot=nr)):
                                    piece.rot = nr
                                elif valid(board, piece.cells(col=piece.col + 1, rot=nr)):
                                    piece.col += 1; piece.rot = nr
                                elif valid(board, piece.cells(col=piece.col - 1, rot=nr)):
                                    piece.col -= 1; piece.rot = nr
                swiping = False
                swipe_start = None

        # ------------------------------------------------------------------ #
        # Spellogik — gravity
        # ------------------------------------------------------------------ #
        if not game_over and not paused:
            speed = FALL_SPEEDS[min(level, len(FALL_SPEEDS) - 1)]
            fall_tick += 1
            if fall_tick >= speed:
                fall_tick = 0
                if valid(board, piece.cells(row=piece.row + 1)):
                    piece.row += 1
                else:
                    # Lås brickan
                    lock(board, piece)
                    cleared = clear_lines(board)
                    if cleared:
                        score  += calc_score(cleared, level)
                        lines  += cleared
                        level   = lines // LINES_PER_LEVEL
                    piece       = next_piece
                    next_piece  = random_piece()
                    fall_tick   = 0
                    # Kollision direkt → game over
                    if not valid(board, piece.cells()):
                        game_over = True

        # ------------------------------------------------------------------ #
        # Rita
        # ------------------------------------------------------------------ #
        surface.fill(BG_COLOR)
        _draw_status(surface, screen_w, score, level, lines)

        _draw_board(surface, board, offset_x, offset_y)

        if not game_over:
            _draw_ghost(surface, board, piece, offset_x, offset_y)
            _draw_piece(surface, piece, offset_x, offset_y)

        _draw_panel(surface, score, level, lines, next_piece,
                    panel_x, panel_y, panel_w)

        # Kant runt spelplanen
        pygame.draw.rect(surface, BTN_OUTLINE,
                         (offset_x - 1, offset_y - 1,
                          COLS * CELL + 2, ROWS * CELL + 2), 1)

        if game_over:
            _draw_overlay(surface, screen_w, screen_h,
                          "GAME OVER", (230, 60, 60),
                          score, font_big, font_med, font_s)

        pygame.display.flip()
