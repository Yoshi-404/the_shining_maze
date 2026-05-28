import pygame
from pygame.locals import *
try:
    from OpenGL.GL import *
    from OpenGL.GLU import *
except ImportError:
    print("Erro: PyOpenGL não está instalado.")
    import sys
    sys.exit()

import math
import sys
import random
from collections import deque

import game.settings as _gs
from game.settings import BLOCK_SIZE, PLAYER_HEIGHT, DISPLAY_SIZE, tex, snd
from game.maze_gen import generate_maze
from game.renderer import (
    setup_lighting, setup_fog, build_maze_display_list, load_texture, 
    draw_skybox, draw_exit, draw_floor, draw_corpse, draw_campfires
)
from game.effects import (
    draw_particles, draw_footprints, draw_anxiety_hud, draw_breath_puffs,
    maybe_add_footprint, clear_footprints, draw_blood_trails, draw_ceiling_drips
)

# ================================
# ESTADO GLOBAL DO MAPA
# ================================
maze_map = []
MAP_WIDTH = 0
MAP_HEIGHT = 0

def check_collision(x, z):
    map_x = int(round((x / BLOCK_SIZE) + MAP_WIDTH/2))
    map_y = int(round((z / BLOCK_SIZE) + MAP_HEIGHT/2))
    if 0 <= map_x < MAP_WIDTH and 0 <= map_y < MAP_HEIGHT:
        if maze_map[map_y][map_x] == 1: return True
        if maze_map[map_y][map_x] == 2: return "EXIT"
    return False

# ================================
# HELPERS DOS NOVOS FEATURES
# ================================

def bfs_next_step(mm, mw, mh, start, goal):
    """Retorna a próxima célula em direção a goal via BFS."""
    if start == goal:
        return None
    visited = {start}
    queue = deque([(start, None)])   # (pos, first_step)
    while queue:
        (cx, cy), first = queue.popleft()
        for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)]:
            nx, ny = cx+dx, cy+dy
            if 0 <= nx < mw and 0 <= ny < mh and (nx,ny) not in visited:
                if mm[ny][nx] != 1:   # não é parede
                    step = first if first else (nx, ny)
                    if (nx, ny) == goal:
                        return step
                    visited.add((nx, ny))
                    queue.append(((nx, ny), step))
    return None


def _next_pow2(n):
    p = 1
    while p < n: p <<= 1
    return p


def create_text_texture(text, color=(160, 20, 20), font_size=56):
    """Cria uma textura OpenGL com texto. Retorna (tex_id, u_max, v_max)."""
    try:
        font = pygame.font.SysFont("impact", font_size)
    except Exception:
        font = pygame.font.Font(None, font_size)
    surf = font.render(text, True, color)
    w, h = surf.get_size()
    pw, ph = _next_pow2(w), _next_pow2(h)
    padded = pygame.Surface((pw, ph), pygame.SRCALPHA)
    padded.fill((0, 0, 0, 0))
    padded.blit(surf, (0, 0))
    raw = pygame.image.tostring(padded, "RGBA", True)
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tid)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, pw, ph, 0, GL_RGBA, GL_UNSIGNED_BYTE, raw)
    return tid, w/pw, h/ph


def setup_wall_texts(mm, mw, mh):
    """
    Encontra faces de paredes em células vazias e retorna lista de
    (world_x, world_z, normal_dx, normal_dz, text_label, min_madness).
    """
    messages = [
        ("REDRUM",                  0.00), # Aparece desde a primeira run
        ("ALL WORK AND NO PLAY",    0.05),
        ("NO ESCAPE",               0.15),
        ("COME PLAY WITH US",       0.25),
        ("HERE'S JOHNNY!",          0.40),
        ("HE'S WATCHING YOU",       0.55),
    ]
    candidates = []
    for my in range(2, mh-2):
        for mx in range(2, mw-2):
            if mm[my][mx] == 0:
                for dx, dy in [(1,0),(-1,0),(0,1),(0,-1)]:
                    nx, ny = mx+dx, my+dy
                    if 0 <= nx < mw and 0 <= ny < mh and mm[ny][nx] == 1:
                        candidates.append((mx, my, dx, dy))
    random.shuffle(candidates)
    chosen = []
    MIN_SEP = 6
    for mx, my, dx, dy in candidates:
        too_close = any(abs(mx-px)+abs(my-py) < MIN_SEP for px,py,_,_,_,_ in chosen)
        if not too_close:
            idx = len(chosen)
            if idx >= len(messages):
                break
            label, min_mad = messages[idx]
            wx = (mx - mw/2) * BLOCK_SIZE + dx * (BLOCK_SIZE/2 - 0.05)
            wz = (my - mh/2) * BLOCK_SIZE + dy * (BLOCK_SIZE/2 - 0.05)
            chosen.append((wx, wz, float(dx), float(dy), label, min_mad))
        if len(chosen) >= len(messages):
            break
    return chosen


def draw_chromatic_aberration(intensity):
    """Captura o backbuffer e re-renderiza separando canais RGB."""
    W, H = DISPLAY_SIZE
    off = int(intensity * 10)
    if off < 1:
        return
    # Captura cena atual
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tid)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glCopyTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 0, 0, W, H, 0)
    # Re-renderiza sobre si mesmo (glOrtho com Y=0 na base, como OpenGL default)
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W, 0, H, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
    glEnable(GL_TEXTURE_2D)
    glBindTexture(GL_TEXTURE_2D, tid)
    glEnable(GL_BLEND)
    glBlendFunc(GL_ONE, GL_ONE)   # Aditivo para mistura dos canais
    glClear(GL_COLOR_BUFFER_BIT)

    def _quad(x0):
        glBegin(GL_QUADS)
        glTexCoord2f(0,0); glVertex2f(x0,     0)
        glTexCoord2f(1,0); glVertex2f(x0 + W, 0)
        glTexCoord2f(1,1); glVertex2f(x0 + W, H)
        glTexCoord2f(0,1); glVertex2f(x0,     H)
        glEnd()

    glColorMask(GL_TRUE,  GL_FALSE, GL_FALSE, GL_TRUE); _quad(-off)  # Red  → direita
    glColorMask(GL_FALSE, GL_TRUE,  GL_FALSE, GL_TRUE); _quad(0)     # Green → centro
    glColorMask(GL_FALSE, GL_FALSE, GL_TRUE,  GL_TRUE); _quad(off)   # Blue  → esquerda
    glColorMask(GL_TRUE,  GL_TRUE,  GL_TRUE,  GL_TRUE)

    glDeleteTextures([tid])
    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)

# ================================
# ESTADOS DO JOGO
# ================================

def draw_minimap(mm, mw, mh, px, pz):
    W, H = DISPLAY_SIZE
    size = 180
    margin = 20
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W, H, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    # Background
    glColor4f(0.0, 0.0, 0.0, 0.7)
    glBegin(GL_QUADS)
    glVertex2f(W - size - margin, margin)
    glVertex2f(W - margin, margin)
    glVertex2f(W - margin, margin + size)
    glVertex2f(W - size - margin, margin + size)
    glEnd()

    # Cells
    cell_w = size / mw
    cell_h = size / mh
    glBegin(GL_QUADS)
    for y in range(mh):
        for x in range(mw):
            if mm[y][x] == 1:
                glColor4f(0.8, 0.8, 0.8, 0.9)
            elif mm[y][x] == 2:
                glColor4f(0.8, 0.1, 0.1, 0.9)
            else:
                continue
            cx = W - size - margin + x * cell_w
            cy = margin + y * cell_h
            glVertex2f(cx, cy)
            glVertex2f(cx + cell_w, cy)
            glVertex2f(cx + cell_w, cy + cell_h)
            glVertex2f(cx, cy + cell_h)
    glEnd()

    # Player position
    map_x = (px / BLOCK_SIZE) + mw/2
    map_y = (pz / BLOCK_SIZE) + mh/2
    px_screen = W - size - margin + map_x * cell_w
    py_screen = margin + map_y * cell_h
    glColor4f(0.1, 0.9, 0.1, 1.0)
    glPointSize(6.0)
    glBegin(GL_POINTS)
    glVertex2f(px_screen, py_screen)
    glEnd()

    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)


def draw_jack_shadow(jack_wx, jack_wz, jack_dist, madness):
    """Desenha uma sombra/silhueta escura e pulsante no chão na posição do Jack."""
    MAX_SHADOW_DIST = 12.0
    if jack_dist > MAX_SHADOW_DIST:
        return
    alpha = (1.0 - jack_dist / MAX_SHADOW_DIST) * (0.4 + madness * 0.4)
    FLOOR_Y = -0.96
    SHADOW_SIZE = BLOCK_SIZE * 0.7
    t = pygame.time.get_ticks() / 1000.0
    pulse = 1.0 + 0.15 * math.sin(t * 3.0)
    size = SHADOW_SIZE * pulse

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glEnable(GL_POLYGON_OFFSET_FILL)
    glPolygonOffset(-3.0, -3.0)

    # Sombra central densa
    glColor4f(0.0, 0.0, 0.0, alpha * 0.8)
    glBegin(GL_TRIANGLE_FAN)
    glVertex3f(jack_wx, FLOOR_Y, jack_wz)
    segments = 16
    for i in range(segments + 1):
        angle = 2.0 * math.pi * i / segments
        sx = jack_wx + math.cos(angle) * size * 0.4
        sz = jack_wz + math.sin(angle) * size * 0.4
        glVertex3f(sx, FLOOR_Y, sz)
    glEnd()

    # Halo externo sutil
    glColor4f(0.05, 0.0, 0.02, alpha * 0.3)
    glBegin(GL_TRIANGLE_FAN)
    glVertex3f(jack_wx, FLOOR_Y, jack_wz)
    for i in range(segments + 1):
        angle = 2.0 * math.pi * i / segments
        sx = jack_wx + math.cos(angle) * size
        sz = jack_wz + math.sin(angle) * size
        glVertex3f(sx, FLOOR_Y, sz)
    glEnd()

    glPopAttrib()


def draw_pause_overlay(selected, in_settings, vol, sens, settings_sel):
    """Renderiza o menu de pausa como overlay OpenGL sobre a cena congelada."""
    W, H = DISPLAY_SIZE
    overlay = pygame.Surface((W, H), pygame.SRCALPHA)
    overlay.fill((0, 0, 0, 170))
    try:
        tfont = pygame.font.SysFont("impact", 72)
        ofont = pygame.font.SysFont("arial", 36)
        hfont = pygame.font.SysFont("arial", 22)
    except Exception:
        tfont = pygame.font.Font(None, 72)
        ofont = pygame.font.Font(None, 36)
        hfont = pygame.font.Font(None, 22)

    if not in_settings:
        title = tfont.render("PAUSA", True, (200, 200, 200))
        overlay.blit(title, title.get_rect(center=(W // 2, H // 2 - 130)))
        options = ["Continuar", "Configuracoes", "Sair ao Menu"]
        for i, opt in enumerate(options):
            color = (255, 255, 80) if i == selected else (160, 160, 160)
            prefix = "> " if i == selected else "  "
            surf = ofont.render(prefix + opt, True, color)
            overlay.blit(surf, surf.get_rect(center=(W // 2, H // 2 - 20 + i * 60)))
        hint = hfont.render("[SETAS] Navegar  |  ENTER Selecionar  |  ESC Voltar",
                            True, (100, 100, 100))
        overlay.blit(hint, hint.get_rect(center=(W // 2, H - 40)))
    else:
        title = tfont.render("CONFIGURACOES", True, (200, 200, 200))
        overlay.blit(title, title.get_rect(center=(W // 2, H // 2 - 130)))
        items = [f"Volume: {int(vol * 100)}%",
                 f"Sensibilidade: {int(sens)}",
                 "Voltar"]
        for i, item in enumerate(items):
            color = (255, 255, 80) if i == settings_sel else (160, 160, 160)
            prefix = "> " if i == settings_sel else "  "
            surf = ofont.render(prefix + item, True, color)
            overlay.blit(surf, surf.get_rect(center=(W // 2, H // 2 - 20 + i * 60)))
        hint = hfont.render("[ESQUERDA/DIREITA] Ajustar  |  [SETAS] Navegar  |  ESC Voltar",
                            True, (100, 100, 100))
        overlay.blit(hint, hint.get_rect(center=(W // 2, H - 40)))

    # Upload para textura OpenGL e renderiza como quad fullscreen
    raw = pygame.image.tostring(overlay, "RGBA", True)
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tid)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, W, H, 0, GL_RGBA,
                 GL_UNSIGNED_BYTE, raw)
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W, 0, H, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
    glEnable(GL_TEXTURE_2D); glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glColor4f(1.0, 1.0, 1.0, 1.0)
    glBegin(GL_QUADS)
    glTexCoord2f(0, 0); glVertex2f(0, 0)
    glTexCoord2f(1, 0); glVertex2f(W, 0)
    glTexCoord2f(1, 1); glVertex2f(W, H)
    glTexCoord2f(0, 1); glVertex2f(0, H)
    glEnd()
    glDeleteTextures([tid])
    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)


def run_menu(screen, font, title_font):
    clock = pygame.time.Clock()
    snowflakes = [[random.randint(0, DISPLAY_SIZE[0]), random.randint(0, DISPLAY_SIZE[1])] for _ in range(150)]
    _fade_result = None
    _fade_alpha = 0

    while True:
        if _fade_result and _fade_alpha >= 255:
            return _fade_result

        for event in pygame.event.get():
            if event.type == QUIT: return "QUIT"
            if event.type == KEYDOWN and not _fade_result:
                if event.key == K_RETURN: _fade_result = "GAME"
                if event.key == K_ESCAPE: return "QUIT"
                if event.key == K_s: _fade_result = "SETTINGS"
                    
        screen.fill((5, 5, 8)) 
        
        for flake in snowflakes:
            flake[1] += random.randint(1, 4)
            if flake[1] > DISPLAY_SIZE[1]:
                flake[1] = 0
                flake[0] = random.randint(0, DISPLAY_SIZE[0])
            pygame.draw.circle(screen, (220, 220, 255), flake, 2)
        
        title_text = title_font.render("THE SHINING MAZE", True, (150, 10, 10))
        title_rect = title_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 - 100))
        screen.blit(title_text, title_rect)
        
        if (pygame.time.get_ticks() // 600) % 2 == 0:
            start_text = font.render("> Pressione [ENTER] para Entrar <", True, (255, 255, 255))
            start_rect = start_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 50))
            screen.blit(start_text, start_rect)
        
        inst_text = font.render("Use fones | WASD p/ Mover | [S] Settings", True, (120, 120, 120))
        inst_rect = inst_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1] - 50))
        screen.blit(inst_text, inst_rect)
        
        if _fade_result:
            _fade_alpha = min(255, _fade_alpha + 17)
            _fade_surf = pygame.Surface(DISPLAY_SIZE)
            _fade_surf.fill((0, 0, 0))
            _fade_surf.set_alpha(_fade_alpha)
            screen.blit(_fade_surf, (0, 0))

        pygame.display.flip()
        clock.tick(60)

def run_settings_screen(screen, font, title_font, is_pause=False):
    clock = pygame.time.Clock()
    
    vol = _gs.master_volume
    sens = _gs.mouse_sensitivity * 1000.0
    selected = 0
    
    while True:
        for event in pygame.event.get():
            if event.type == QUIT: return "QUIT"
            if event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    _gs.master_volume = vol
                    _gs.mouse_sensitivity = sens / 1000.0
                    return "GAME" if is_pause else "MENU"
                if event.key == K_RETURN and selected == 2:
                    _gs.master_volume = vol
                    _gs.mouse_sensitivity = sens / 1000.0
                    return "GAME" if is_pause else "MENU"
                if event.key == K_UP:
                    selected = max(0, selected - 1)
                if event.key == K_DOWN:
                    selected = min(2, selected + 1)
                if event.key == K_LEFT:
                    if selected == 0: vol = max(0.0, vol - 0.1)
                    elif selected == 1: sens = max(1.0, sens - 1.0)
                if event.key == K_RIGHT:
                    if selected == 0: vol = min(2.0, vol + 0.1)
                    elif selected == 1: sens = min(10.0, sens + 1.0)

        screen.fill((10, 10, 15))
        title = "PAUSE / SETTINGS" if is_pause else "SETTINGS"
        t = title_font.render(title, True, (150, 150, 150))
        screen.blit(t, t.get_rect(center=(DISPLAY_SIZE[0]//2, 100)))

        c0 = (255, 255, 0) if selected == 0 else (100, 100, 100)
        t0 = font.render(f"Volume: {int(vol*100)}%", True, c0)
        screen.blit(t0, t0.get_rect(center=(DISPLAY_SIZE[0]//2, 300)))

        c1 = (255, 255, 0) if selected == 1 else (100, 100, 100)
        t1 = font.render(f"Sensibilidade Mouse: {int(sens)}", True, c1)
        screen.blit(t1, t1.get_rect(center=(DISPLAY_SIZE[0]//2, 400)))

        c2 = (255, 255, 0) if selected == 2 else (100, 100, 100)
        t2 = font.render("Voltar" if not is_pause else "Retomar Jogo", True, c2)
        screen.blit(t2, t2.get_rect(center=(DISPLAY_SIZE[0]//2, 550)))

        pygame.display.flip()
        clock.tick(60)


def run_end_screen(screen, font, title_font, stats=None):
    # ---- Incrementa loucura a cada vez que o jogador escapa ----
    _gs.completion_count += 1
    cc = _gs.completion_count

    # Mensagens que ficam mais perturbadoras
    madness_lines = [
        "Pressione [ENTER] para Voltar ao Menu",
        "Por que voltar? Ele ainda está lá...",
        "Você sente que está sendo observado.",
        "Não há saída real. Nunca houve.",
        "REDRUM. REDRUM. REDRUM.",
        "Você não consegue parar, consegue?",
        "ELE SABE QUE VOCÊ ESTÁ VOLTANDO.",
        "AQUI NÃO HÁ ESCAPE. SÓ O LABIRINTO.",
    ]
    sub_msg = madness_lines[min(cc - 1, len(madness_lines) - 1)]

    # Cor da tela: escuro carmesim na 1a vez, vermelho sangue depois
    bg_color = (min(20 + cc * 20, 200), max(8 - cc, 2), max(10 - cc, 2))

    clock = pygame.time.Clock()
    _fade_result = None
    _fade_alpha = 0
    while True:
        if _fade_result and _fade_alpha >= 255:
            return _fade_result

        for event in pygame.event.get():
            if event.type == QUIT: return "QUIT"
            if event.type == KEYDOWN and not _fade_result:
                if event.key == K_RETURN: _fade_result = "MENU"
                if event.key == K_ESCAPE: return "QUIT"

        screen.fill(bg_color)

        # Título fica mais vermelho / tremendo conforme loucura
        if cc >= 3:
            ox = random.randint(-cc, cc)
            oy = random.randint(-cc, cc)
        else:
            ox, oy = 0, 0

        title_color = (min(20 + cc * 30, 255), max(40 - cc * 5, 0), max(60 - cc * 8, 0))
        title_text = title_font.render("VOCÊ ESCAPOU", True, title_color)
        title_rect = title_text.get_rect(center=(DISPLAY_SIZE[0]//2 + ox, DISPLAY_SIZE[1]//2 - 50 + oy))
        screen.blit(title_text, title_rect)

        # Contador de vezes
        count_color = (180, 20, 20) if cc >= 2 else (100, 100, 100)
        count_text = font.render(f"Vezes que escapou: {cc}", True, count_color)
        count_rect = count_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 20))
        screen.blit(count_text, count_rect)

        if stats:
            run_time, dist, jumpscares, peak_anx = stats
            s0 = font.render(f"Tempo: {int(run_time//60)}m {int(run_time%60)}s", True, (130, 130, 130))
            s1 = font.render(f"Distância: {dist:.1f} m", True, (130, 130, 130))
            s2 = font.render(f"Jumpscares: {jumpscares}", True, (130, 130, 130))
            s3 = font.render(f"Pico de Ansiedade: {int(peak_anx*100)}%", True, (130, 130, 130))
            screen.blit(s0, s0.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 55)))
            screen.blit(s1, s1.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 85)))
            screen.blit(s2, s2.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 115)))
            screen.blit(s3, s3.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 145)))

        start_text = font.render(sub_msg, True, (200, 200, 200))
        start_rect = start_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 200))
        screen.blit(start_text, start_rect)

        if _fade_result:
            _fade_alpha = min(255, _fade_alpha + 17)
            _fade_surf = pygame.Surface(DISPLAY_SIZE)
            _fade_surf.fill((0, 0, 0))
            _fade_surf.set_alpha(_fade_alpha)
            screen.blit(_fade_surf, (0, 0))

        pygame.display.flip()
        clock.tick(60)

def run_game():
    global maze_map, MAP_WIDTH, MAP_HEIGHT
    maze_map, MAP_WIDTH, MAP_HEIGHT = generate_maze(25, 25)
    # Limpa pegadas do jogo anterior
    clear_footprints()

    # ---- Nível de loucura (escala com completações) ----
    cc = _gs.completion_count          # 0 = primeira jogada, 1 = segunda, etc.
    madness = min(cc / 5.0, 1.0)      # 0.0 → 1.0, satura em 5 completações
    # Multiplicador de volume: 1.0 → 2.5x mais alto (e escala com master_volume)
    vol_mult = (1.0 + madness * 1.5) * _gs.master_volume
    # Duração do jumpscare: 0.6s → 2.0s
    JUMPSCARE_DUR_MS = int(600 + madness * 1400)
    # Número de zonas gatilho: 2 → 10
    num_triggers = 2 + int(madness * 8)

    glMatrixMode(GL_PROJECTION)
    glLoadIdentity()
    gluPerspective(70, (DISPLAY_SIZE[0] / DISPLAY_SIZE[1]), 0.1, 80.0)
    glMatrixMode(GL_MODELVIEW)

    glEnable(GL_DEPTH_TEST)
    fog_color = setup_fog()
    setup_lighting()

    tex_hedge = load_texture(tex("hedge.png"))
    tex_snow  = load_texture(tex("snow.png"))
    tex_skybox = load_texture(tex("skybox.png"))

    if tex_hedge and tex_snow:
        glEnable(GL_TEXTURE_2D)

    maze_dlist = build_maze_display_list(tex_snow, tex_hedge, maze_map, MAP_WIDTH, MAP_HEIGHT)

    # ---- Textos nas Paredes ----
    wall_text_data   = setup_wall_texts(maze_map, MAP_WIDTH, MAP_HEIGHT)
    # Cría texturas GL depois que OpenGL já está ativo
    wall_text_textures = {}   # label -> (tex_id, u_max, v_max)
    for (_, _, _, _, label, _) in wall_text_data:
        if label not in wall_text_textures:
            wall_text_textures[label] = create_text_texture(label)

    exit_pos = (0.0, 0.0)
    exit_grid = (MAP_WIDTH - 2, MAP_HEIGHT - 2)  # fallback
    
    tex_corpse = load_texture(tex("corpse.png"))

    fake_exit_pos = None
    fake_exit_cell = None
    fake_exit_triggered = False
    
    corpse_cells = []

    for ey in range(MAP_HEIGHT):
        for ex in range(MAP_WIDTH):
            if maze_map[ey][ex] == 2:
                exit_pos = ((ex - MAP_WIDTH/2) * BLOCK_SIZE,
                            (ey - MAP_HEIGHT/2) * BLOCK_SIZE)
                exit_grid = (ex, ey)
            elif maze_map[ey][ex] == 3:
                fake_exit_pos = ((ex - MAP_WIDTH/2) * BLOCK_SIZE,
                                 (ey - MAP_HEIGHT/2) * BLOCK_SIZE)
                fake_exit_cell = (ex, ey)
            elif maze_map[ey][ex] == 4:
                corpse_cells.append((ex, ey))

    EXIT_REACH = BLOCK_SIZE * 1.5  # Distância para detectar saída
    
    trap_tex_info = create_text_texture("VOCÊ NÃO PODE SAIR", color=(200, 0, 0), font_size=80)
    trap_text_timer_ms = 0
    interact_tex_info = create_text_texture("Pressione [E] para vasculhar", font_size=40)
    
    fake_jacks = []
    next_fake_jack_ms = pygame.time.get_ticks() + 15000
    
    blood_decals = []
    corpses = []
    for cx, cy in corpse_cells:
        wx = (cx - MAP_WIDTH/2) * BLOCK_SIZE
        wz = (cy - MAP_HEIGHT/2) * BLOCK_SIZE
        corpses.append({'pos': (wx, wz), 'searched': False})
        
        # Gerar rastro de sangue saindo do corpo (trilha direcional)
        bcx, bcy = cx, cy
        visited_blood = {(bcx, bcy)}
        for _ in range(18):
            blood_decals.append(((bcx - MAP_WIDTH/2) * BLOCK_SIZE + random.uniform(-0.5, 0.5), 
                                 (bcy - MAP_HEIGHT/2) * BLOCK_SIZE + random.uniform(-0.5, 0.5),
                                 random.uniform(0, 3.14*2)))
            adj = [(bcx+dx, bcy+dy) for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)] 
                   if maze_map[bcy+dy][bcx+dx] in (0, 4) and (bcx+dx, bcy+dy) not in visited_blood]
            if not adj: # Permite voltar se for beco sem saída
                adj = [(bcx+dx, bcy+dy) for dx, dy in [(0,1),(0,-1),(1,0),(-1,0)] 
                       if maze_map[bcy+dy][bcx+dx] in (0, 4)]
            if adj:
                bcx, bcy = random.choice(adj)
                visited_blood.add((bcx, bcy))

    # ---- Gerar Campfires (Zonas Seguras) ----
    campfires = []
    free_cells = [(x, y) for y in range(1, MAP_HEIGHT-1) for x in range(1, MAP_WIDTH-1) 
                  if maze_map[y][x] == 0 and (x, y) not in corpse_cells]
    random.shuffle(free_cells)
    for cx, cy in free_cells[:12]: # até 12 fogueiras pelo mapa
        wx = (cx - MAP_WIDTH/2) * BLOCK_SIZE
        wz = (cy - MAP_HEIGHT/2) * BLOCK_SIZE
        campfires.append((wx, wz))

    # ---- Gerar Teto Sangrento (Zonas de Gotejamento) ----
    blood_drip_zones = []
    # O terror aumenta progressivamente: Chuva de sangue apenas a partir da 3ª Fase
    if _gs.completion_count >= 2:
        # Reduzida a frequência: de 15 para apenas 6 áreas de gotejamento espalhadas
        drip_cells = free_cells[12:18] 
        for cx, cy in drip_cells:
            blood_drip_zones.append((cx - MAP_WIDTH/2, cy - MAP_HEIGHT/2))

    # ---- Áudio (inicia apenas se ainda não foi inicializado) ----
    if not pygame.mixer.get_init():
        pygame.mixer.init(frequency=44100, size=-16, channels=2, buffer=512)
    wind_snd = None
    hum_snd  = None
    try:
        wind_snd = pygame.mixer.Sound(snd("wind.wav"))
        wind_snd.set_volume(min(1.0, 0.25 * vol_mult))
        wind_ch = wind_snd.play(-1)   # Loop infinito
    except Exception as e:
        print(f"Vento: {e}")
        wind_ch = None
    try:
        hum_snd = pygame.mixer.Sound(snd("exit.wav"))
        hum_ch  = hum_snd.play(-1)
    except Exception as e:
        print(f"Zumbido: {e}")
        hum_ch = None
        
    try:
        drip_snd = pygame.mixer.Sound(snd("drip.wav"))
        drip_snd.set_volume(min(1.0, 0.6 * vol_mult))
    except Exception as e:
        print(f"Drip: {e}")
        drip_snd = None

    # ---- Batimento cardíaco (volume sobe com loucura) ----
    try:
        heartbeat_snd = pygame.mixer.Sound(snd("heartbeat.wav"))
    except Exception as e:
        print(f"Heartbeat: {e}")
        heartbeat_snd = None
    next_beat_ms = pygame.time.get_ticks()

    # ---- Lanterna com Bateria ----
    battery          = 1.0
    BATT_DRAIN_MOVE  = 0.00012   # por frame ao mover (Aumentado para mais suspense)
    BATT_IDLE_DRAIN  = 0.000015  # drena lentamente mesmo parado
    BATT_RECHARGE    = 0.00011   # recarrega quando parado (Um pouco mais lento)
    batt_warning_played = False  # já tocou aviso de bateria fraca

    # ---- Jack Perseguidor ----
    # Começa no canto oposto ao jogador
    jack_pos = (MAP_WIDTH - 3, MAP_HEIGHT - 3)
    # Garante que não está em parede
    while maze_map[jack_pos[1]][jack_pos[0]] == 1 and jack_pos[0] > 1:
        jack_pos = (jack_pos[0] - 1, jack_pos[1])
    jack_move_interval = max(1200, 3500 - int(madness * 1800))  # ms entre movimentos
    next_jack_move_ms  = pygame.time.get_ticks() + 10000   # 10s de graça
    jack_ch = None
    try:
        jack_snd = pygame.mixer.Sound(snd("heartbeat.wav"))
        jack_ch  = jack_snd.play(-1)
        if jack_ch: jack_ch.set_volume(0.0)
    except Exception:
        jack_snd = None


    # ---- Vozes esporadicas (intervalo diminui com loucura) ----
    voice_snds = []
    for fname in ["danny1.wav", "danny2.wav"]:
        try:
            voice_snds.append(pygame.mixer.Sound(snd(fname)))
        except Exception as e:
            print(f"Voz {fname}: {e}")
    voice_min_ms = int(30000 - madness * 25000)
    voice_max_ms = int(90000 - madness * 75000)
    next_voice_ms = pygame.time.get_ticks() + random.randint(voice_min_ms, voice_max_ms)

    # ---- Sussurros (frequentes com alta loucura) ----
    whisper_snds = []
    for fname in ["whisper1.wav", "whisper2.wav"]:
        try: whisper_snds.append(pygame.mixer.Sound(snd(fname)))
        except: pass
    whisper_min_ms = int(10000 - madness * 8000)
    whisper_max_ms = int(40000 - madness * 35000)
    next_whisper_ms = pygame.time.get_ticks() + random.randint(whisper_min_ms, whisper_max_ms)

    # ---- Passos na Neve ----
    try: footstep_snd = pygame.mixer.Sound(snd("footstep.wav"))
    except: footstep_snd = None
    last_step_bob = 0.0

    # ---- Jumpscare (pré-carrega texturas na GPU para evitar memory leak) ----
    jumpscare_textures = []
    for fname in ["jumpscare_jack.png", "jumpscare_twins.png"]:
        try:
            surf = pygame.image.load(tex(fname)).convert_alpha()
            w, h = surf.get_size()
            raw = pygame.image.tostring(surf, "RGBA", False)
            tid = glGenTextures(1)
            glBindTexture(GL_TEXTURE_2D, tid)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
            glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, raw)
            jumpscare_textures.append(tid)
        except Exception as e:
            print(f"Jumpscare img {fname}: {e}")

    # Carrega os sons de susto
    try:
        grito_snd = pygame.mixer.Sound(snd("grito.mp3"))
        grito_snd.set_volume(min(1.0, vol_mult))
    except Exception as e:
        print(f"grito snd: {e}")
        grito_snd = None

    try:
        scare_snd = pygame.mixer.Sound(snd("scare.mp3"))
        scare_snd.set_volume(min(1.0, vol_mult))
    except Exception as e:
        print(f"scare snd: {e}")
        scare_snd = None

    # ---- Partículas de Inseto (quadradinhos marrons subindo pelo personagem) ----
    BUG_DUR_MS       = 4500    # duração total da animação
    BUG_PART_COUNT   = 38      # número de partículas
    bug_active       = False
    bug_start_ms     = 0
    bug_particles    = []      # lista de dicts de partícula
    # Frequência: bem espaçada, fica menor com mais completações
    next_bug_ms = pygame.time.get_ticks() + random.randint(120000, 240000)

    def spawn_bug_particles():
        W, H = DISPLAY_SIZE
        parts = []
        for _ in range(BUG_PART_COUNT):
            edge = random.randint(0, 2)   # 0=fundo, 1=esq, 2=dir
            if edge == 0:
                sx = random.uniform(W * 0.05, W * 0.95)
                sy = H + random.uniform(10, 40)
            elif edge == 1:
                sx = random.uniform(-30, 10)
                sy = random.uniform(H * 0.65, H)
            else:
                sx = random.uniform(W - 10, W + 30)
                sy = random.uniform(H * 0.65, H)
            foot_x = W * 0.5 + random.uniform(-70, 70)
            foot_y = H * 0.87 + random.uniform(-20, 20)
            face_x = W * 0.5 + random.uniform(-25, 25)
            face_y = H * 0.12 + random.uniform(-15, 15)
            parts.append({
                'sx': sx, 'sy': sy,
                'fx': foot_x, 'fy': foot_y,
                'ex': face_x, 'ey': face_y,
                'size': random.randint(3, 7),
                'delay': random.uniform(0.0, 0.25),
                'speed': random.uniform(0.75, 1.3),
                'wobble': random.uniform(0, math.pi * 2),
                'brown': random.randint(90, 150),
            })
        return parts

    # ---- Piscar de Tela (cc >= 3) ----
    blink_active    = False
    blink_until_ms  = 0
    next_blink_ms   = pygame.time.get_ticks() + random.randint(8000, 18000)

    # ---- Tontura (cc >= 4) ----
    dizzy_active    = False
    dizzy_until_ms  = 0
    dizzy_strength  = 0.0
    next_dizzy_ms   = pygame.time.get_ticks() + random.randint(12000, 30000)

    # Sorteia zonas gatilho no labirinto (2 → 10 conforme loucura)
    # Exclui células perto do início E perto da saída
    EXIT_SAFE_DIST = 6  # raio de células sem jumpscare ao redor da saída
    empty_cells = [(x, y) for y in range(MAP_HEIGHT) for x in range(MAP_WIDTH)
                   if maze_map[y][x] == 0]
    trigger_zones = set()
    candidates = [
        c for c in empty_cells
        if not (c[0] <= 3 and c[1] <= 3)  # longe do início
        and abs(c[0] - exit_grid[0]) + abs(c[1] - exit_grid[1]) > EXIT_SAFE_DIST  # longe da saída
    ]
    for _ in range(min(num_triggers, len(candidates))):
        z = random.choice(candidates)
        trigger_zones.add(z)
        candidates.remove(z)
    triggered_zones = set()

    jumpscare_active   = False
    jumpscare_start_ms = 0
    # JUMPSCARE_DUR_MS já calculado acima (escala com madness)
    current_js_image   = None
    # Tipo de efeito extra para cada jumpscare (0=normal,1=flash,2=glitch,3=negativo)
    js_effect_type     = 0

    # ---- Ansiedade ----
    anxiety        = 0.0
    ANXIETY_RISE     = 0.0015  # +por frame ao correr (mais lento)
    ANXIETY_FALL     = 0.001
    panic_until_ms   = 0
    BASE_SPEED       = 0.10   # Velocidade base reduzida

    # ---- Lanterna Tremeluzente ----
    flicker_val  = 1.0     # intensidade atual [0..1]
    flicker_off_until = 0  # timestamp para restaurar após apagão

    # ---- Camera Shake ----
    shake_yaw   = 0.0
    shake_pitch = 0.0
    shake_trauma = 0.0    # 0 = calmo, 1 = máx trauma (decai por frame)

    # ---- Nevasca e Hipotermia ----
    blizzard_active = False
    blizzard_intensity = 0.0
    next_blizzard_ms = pygame.time.get_ticks() + random.randint(25000, 45000)
    blizzard_end_ms = 0
    hypothermia = 0.0

    # ---- Sangue no Teto ----
    blood_overlay_timer = 0
    next_drip_ms = 0


    # ---- Bafadas de Frio (Billboards) ----
    breath_puffs = []       # lista de (start_ms, wx, wy, wz, dx, dz)
    next_breath_ms = pygame.time.get_ticks() + 2000

    start_x = (1 - MAP_WIDTH/2) * BLOCK_SIZE
    start_z  = (1 - MAP_HEIGHT/2) * BLOCK_SIZE
    player_pos = [start_x, PLAYER_HEIGHT - 1, start_z]

    yaw   = math.pi / 4
    pitch = 0.0
    move_speed = BASE_SPEED
    mouse_sensitivity = _gs.mouse_sensitivity
    bob_time = 0.0
    minimap_timer_ms = 0

    # ---- Pausa ----
    paused = False
    pause_selected = 0
    pause_in_settings = False
    pause_vol = _gs.master_volume
    pause_sens = _gs.mouse_sensitivity * 1000.0
    pause_settings_sel = 0
    pause_exiting = False
    pause_exit_alpha = 0

    # ---- Fade-in do inicio ----
    game_fade_alpha = 255

    # ---- Defaults para camera (necessario se pausar no 1o frame) ----
    bob_offset = 0.0
    look_x = player_pos[0] + math.cos(yaw)
    look_y = player_pos[1]
    look_z = player_pos[2] + math.sin(yaw)

    clock = pygame.time.Clock()
    pygame.mouse.get_rel() 
    
    # ---- Estatísticas da Run ----
    stat_distance = 0.0
    stat_jumpscares = 0
    stat_peak_anxiety = 0.0
    run_start_ms = pygame.time.get_ticks()
    
    # Fila de ecos falsos
    fake_echoes = []
    was_moving = False

    try:
        while True:
            for event in pygame.event.get():
                if event.type == QUIT: return "QUIT"
                if event.type == KEYDOWN:
                    if event.key == K_ESCAPE:
                        if pause_exiting:
                            pass
                        elif pause_in_settings:
                            _gs.master_volume = pause_vol
                            _gs.mouse_sensitivity = pause_sens / 1000.0
                            mouse_sensitivity = _gs.mouse_sensitivity
                            pause_in_settings = False
                        elif paused:
                            paused = False
                            pygame.mouse.set_visible(False)
                            pygame.event.set_grab(True)
                            pygame.mouse.get_rel()
                        else:
                            paused = True
                    elif event.key == K_e and not paused and not jumpscare_active:
                        # ---- Interação com Corpos ----
                        for c in corpses:
                            if not c['searched']:
                                dist = math.dist([player_pos[0], player_pos[2]], [c['pos'][0], c['pos'][1]])
                                if dist < BLOCK_SIZE * 1.5:
                                    c['searched'] = True
                                    if random.random() < 0.5:
                                        # Azar: Jumpscare
                                        jumpscare_active = True
                                        jumpscare_start_ms = pygame.time.get_ticks()
                                        current_js_tex = tex_corpse  # O corpo agarra a tela
                                        js_effect_type = random.choice([0, 1, 2, 3])
                                        if grito_snd: grito_snd.play()
                                        anxiety = 1.0
                                        battery = 0.0
                                    else:
                                        # Sorte: Bateria Cheia e alívio
                                        battery = 1.0
                                        anxiety = max(0.0, anxiety - 0.3)
                                    break
                            pause_selected = 0
                            pause_exiting = False
                            pygame.mouse.set_visible(True)
                            pygame.event.set_grab(False)
                    elif paused and not pause_exiting and not pause_in_settings:
                        if event.key == K_UP:
                            pause_selected = (pause_selected - 1) % 3
                        elif event.key == K_DOWN:
                            pause_selected = (pause_selected + 1) % 3
                        elif event.key == K_RETURN:
                            if pause_selected == 0:
                                paused = False
                                pygame.mouse.set_visible(False)
                                pygame.event.set_grab(True)
                                pygame.mouse.get_rel()
                            elif pause_selected == 1:
                                pause_in_settings = True
                                pause_vol = _gs.master_volume
                                pause_sens = _gs.mouse_sensitivity * 1000.0
                                pause_settings_sel = 0
                            elif pause_selected == 2:
                                pause_exiting = True
                                pause_exit_alpha = 0
                    elif paused and not pause_exiting and pause_in_settings:
                        if event.key == K_UP:
                            pause_settings_sel = max(0, pause_settings_sel - 1)
                        elif event.key == K_DOWN:
                            pause_settings_sel = min(2, pause_settings_sel + 1)
                        elif event.key == K_LEFT:
                            if pause_settings_sel == 0:
                                pause_vol = max(0.0, pause_vol - 0.1)
                            elif pause_settings_sel == 1:
                                pause_sens = max(1.0, pause_sens - 1.0)
                        elif event.key == K_RIGHT:
                            if pause_settings_sel == 0:
                                pause_vol = min(2.0, pause_vol + 0.1)
                            elif pause_settings_sel == 1:
                                pause_sens = min(10.0, pause_sens + 1.0)
                        elif event.key == K_RETURN and pause_settings_sel == 2:
                            _gs.master_volume = pause_vol
                            _gs.mouse_sensitivity = pause_sens / 1000.0
                            mouse_sensitivity = _gs.mouse_sensitivity
                            pause_in_settings = False
                    elif not paused:
                        if event.key == K_m:
                            minimap_timer_ms = pygame.time.get_ticks() + 3000



            # ---- Processar Ecos Falsos ----
            for e_ms in fake_echoes[:]:
                if now_ms >= e_ms:
                    fake_echoes.remove(e_ms)
                    if footstep_snd:
                        footstep_snd.set_volume(min(1.0, (0.02 + anxiety * 0.05) * _gs.master_volume))
                        footstep_snd.play()

            # ---- Pausa: cena congelada + overlay ----
            if paused:
                pygame.mouse.get_rel()
                glClearColor(*fog_color)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
                glLoadIdentity()
                gluLookAt(player_pos[0], player_pos[1] + bob_offset, player_pos[2],
                          look_x, look_y + bob_offset, look_z, 0, 1, 0)
                draw_skybox(tex_skybox, player_pos[0], player_pos[1], player_pos[2])
                glCallList(maze_dlist)
                draw_exit(maze_map, MAP_WIDTH, MAP_HEIGHT)
                draw_pause_overlay(pause_selected, pause_in_settings,
                                   pause_vol, pause_sens, pause_settings_sel)
                # Fade-out ao selecionar "Sair ao Menu"
                if pause_exiting:
                    pause_exit_alpha = min(255, pause_exit_alpha + 17)
                    if pause_exit_alpha >= 255:
                        return "MENU"
                    _pe_W, _pe_H = DISPLAY_SIZE
                    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                    glOrtho(0, _pe_W, _pe_H, 0, -1, 1)
                    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
                    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
                    glDisable(GL_TEXTURE_2D); glEnable(GL_BLEND)
                    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                    glColor4f(0.0, 0.0, 0.0, pause_exit_alpha / 255.0)
                    glBegin(GL_QUADS)
                    glVertex2f(0, 0); glVertex2f(_pe_W, 0)
                    glVertex2f(_pe_W, _pe_H); glVertex2f(0, _pe_H)
                    glEnd()
                    glPopAttrib()
                    glMatrixMode(GL_PROJECTION); glPopMatrix()
                    glMatrixMode(GL_MODELVIEW); glPopMatrix()
                    glEnable(GL_DEPTH_TEST)
                pygame.display.flip()
                clock.tick(60)
                continue

            dx, dy = pygame.mouse.get_rel()
            yaw += dx * mouse_sensitivity
            pitch -= dy * mouse_sensitivity
            pitch = max(-math.pi/2 + 0.1, min(math.pi/2 - 0.1, pitch))

            front_x = math.cos(yaw)
            front_z = math.sin(yaw)
            right_x = math.cos(yaw + math.pi/2)
            right_z = math.sin(yaw + math.pi/2)

            keys = pygame.key.get_pressed()
            new_x = player_pos[0]
            new_z = player_pos[2]

            # ---- Sistema de Ansiedade ----
            now_ms = pygame.time.get_ticks()
            in_panic = now_ms < panic_until_ms

            if in_panic:
                # Paralisia: não aceita input de movimento
                move_speed = 0.0
                is_moving  = False
                sprinting  = False
                # Ansiedade cai durante pânico para evitar loop infinito
                anxiety = max(0.0, anxiety - ANXIETY_FALL * 3)
            else:
                is_moving = False
                sprinting = (keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]) and battery > 0.05
                effective_speed = move_speed * (1.8 if sprinting else 1.0)

                if keys[pygame.K_w] or keys[pygame.K_UP]:
                    new_x += front_x * effective_speed; new_z += front_z * effective_speed; is_moving = True
                if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                    new_x -= front_x * effective_speed; new_z -= front_z * effective_speed; is_moving = True
                if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                    new_x -= right_x * effective_speed; new_z -= right_z * effective_speed; is_moving = True
                if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                    new_x += right_x * effective_speed; new_z += right_z * effective_speed; is_moving = True

                if is_moving:
                    anxiety_mult = 3.0 if sprinting else 1.0
                    anxiety = min(1.0, anxiety + ANXIETY_RISE * anxiety_mult)
                else:
                    sprinting = False
                    anxiety = max(0.0, anxiety - ANXIETY_FALL)

                if anxiety >= 1.0:
                    # Gatilho de pânico: congela o personagem por 2 segundos
                    panic_until_ms = now_ms + 2000
                    anxiety        = 0.5  # Reseta para metade

                stat_peak_anxiety = max(stat_peak_anxiety, anxiety)

                # Velocidade reduz com alta ansiedade (0.15 -> 0.05)
                move_speed = BASE_SPEED * (1.0 - anxiety * 0.66)

            # ---- Lanterna com Bateria ----
            if is_moving:
                drain = BATT_DRAIN_MOVE * (3.0 if sprinting else 1.0)
                battery = max(0.0, battery - drain)
            else:
                battery = min(1.0, battery + BATT_RECHARGE)
            battery = max(0.0, battery - BATT_IDLE_DRAIN)

            # ---- Lógica de Nevasca e Hipotermia ----
            if not blizzard_active and now_ms >= next_blizzard_ms:
                blizzard_active = True
                blizzard_end_ms = now_ms + random.randint(15000, 25000)
                if wind_snd: wind_snd.play()
            
            if blizzard_active:
                blizzard_intensity = min(1.0, blizzard_intensity + 0.003)
                if now_ms >= blizzard_end_ms:
                    blizzard_active = False
                    next_blizzard_ms = now_ms + random.randint(35000, 60000)
            else:
                blizzard_intensity = max(0.0, blizzard_intensity - 0.002)
                
            current_fog = 0.09 + (0.26 * blizzard_intensity)
            glFogf(GL_FOG_DENSITY, current_fog)

            near_campfire = False
            for fx, fz in campfires:
                if math.dist([player_pos[0], player_pos[2]], [fx, fz]) < BLOCK_SIZE * 2.0:
                    near_campfire = True
                    break
                    
            if blizzard_active and blizzard_intensity > 0.5:
                if near_campfire:
                    hypothermia = max(0.0, hypothermia - 0.01)
                else:
                    hypothermia = min(1.0, hypothermia + 0.001)
                    battery = max(0.0, battery - BATT_IDLE_DRAIN * 4.0) # Bateria drena rápido no frio
            else:
                if near_campfire:
                    hypothermia = max(0.0, hypothermia - 0.01)
                else:
                    hypothermia = max(0.0, hypothermia - 0.0005)

            if hypothermia >= 1.0 and not jumpscare_active:
                jumpscare_active = True
                jumpscare_start_ms = now_ms
                current_js_tex = random.choice(jumpscare_textures) if jumpscare_textures else None
                js_effect_type = 3 # Efeito negativo para frio
                anxiety = 1.0
                hypothermia = 0.5 # Reseta metade para dar uma chance

            # ---- Lógica de Teto Sangrento ----
            if blood_overlay_timer > 0:
                # Decaimento fixo por frame (assume ~60fps)
                blood_overlay_timer -= 1000 / 60.0

                
            near_drip = False
            for zx, zz in blood_drip_zones:
                wx = zx * BLOCK_SIZE
                wz = zz * BLOCK_SIZE
                dist = math.hypot(player_pos[0] - wx, player_pos[2] - wz)
                if dist < BLOCK_SIZE * 3.5:
                    near_drip = True
                # Checa se está em cima (passando no bloco)
                if dist < BLOCK_SIZE * 0.7:
                    if blood_overlay_timer <= 0:
                        blood_overlay_timer = 3000 # 3 segundos de overlay vermelho
                        anxiety = min(1.0, anxiety + 0.3)
                        if drip_snd: drip_snd.play()
                        
            if near_drip and now_ms > next_drip_ms:
                if drip_snd:
                    # Toca com pan posicional aproximado ou apenas volume
                    drip_snd.play()
                next_drip_ms = now_ms + random.randint(1500, 3000)

            # ---- Armadilha da Falsa Saída ----
            if fake_exit_pos and not fake_exit_triggered:
                dist_fake_exit = math.dist([player_pos[0], player_pos[2]], [fake_exit_pos[0], fake_exit_pos[1]])
                if dist_fake_exit < EXIT_REACH * 1.5:
                    fake_exit_triggered = True
                    maze_map[fake_exit_cell[1]][fake_exit_cell[0]] = 0  # Apaga o brilho
                    battery = 0.0  # Apaga a lanterna (Escuro Absoluto)
                    anxiety = 1.0  # Pânico Total
                    if grito_snd:
                        grito_snd.play()

            # ---- Falsos Jacks ----
            if madness > 0.3 and now_ms >= next_fake_jack_ms:
                ray_x, ray_z = player_pos[0], player_pos[2]
                step_size = BLOCK_SIZE * 0.5
                steps = 0
                while steps < 40:
                    ray_x += front_x * step_size
                    ray_z += front_z * step_size
                    steps += 1
                    if check_collision(ray_x, ray_z):
                        if steps * step_size > BLOCK_SIZE * 6:
                            fj_x = ray_x - front_x * BLOCK_SIZE
                            fj_z = ray_z - front_z * BLOCK_SIZE
                            if not check_collision(fj_x, fj_z):
                                fake_jacks.append({'pos': (fj_x, fj_z), 'spawn_ms': now_ms})
                        break
                next_fake_jack_ms = now_ms + random.randint(5000, 15000)

            kept_fake_jacks = []
            for fj in fake_jacks:
                fj_wx, fj_wz = fj['pos']
                fj_dist = math.dist([player_pos[0], player_pos[2]], [fj_wx, fj_wz])
                
                dx = fj_wx - player_pos[0]
                dz = fj_wz - player_pos[2]
                angle_to_fj = math.atan2(dz, dx)
                diff_angle = (angle_to_fj - yaw) % (2*math.pi)
                if diff_angle > math.pi: diff_angle -= 2*math.pi
                is_looking = abs(diff_angle) < math.radians(25)

                is_illuminated = is_looking and battery > 0.02 and now_ms > flicker_off_until
                if fj_dist < BLOCK_SIZE * 3 or (is_illuminated and fj_dist < BLOCK_SIZE * 15 and now_ms > fj['spawn_ms'] + 500):
                    # Falso Jack desaparece
                    anxiety = min(1.0, anxiety + 0.15)
                else:
                    kept_fake_jacks.append(fj)
            fake_jacks = kept_fake_jacks

            # ---- Movimentação do Inimigo (BFS Dinâmico) ----
            edx = player_pos[0] - exit_pos[0]
            edz = player_pos[2] - exit_pos[1]
            dist_exit = math.sqrt(edx * edx + edz * edz)

            # ---- Jack Perseguidor ----
            player_grid = (int(round(player_pos[0] / BLOCK_SIZE + MAP_WIDTH / 2)),
                           int(round(player_pos[2] / BLOCK_SIZE + MAP_HEIGHT / 2)))
            if now_ms >= next_jack_move_ms:
                next_step = bfs_next_step(maze_map, MAP_WIDTH, MAP_HEIGHT, jack_pos, player_grid)
                if next_step:
                    jack_pos = next_step
                next_jack_move_ms = now_ms + jack_move_interval
            jack_wx = (jack_pos[0] - MAP_WIDTH  / 2) * BLOCK_SIZE
            jack_wz = (jack_pos[1] - MAP_HEIGHT / 2) * BLOCK_SIZE
            jack_dist = math.sqrt((player_pos[0]-jack_wx)**2 + (player_pos[2]-jack_wz)**2)
            # Passos do Jack (volume aumenta com proximidade)
            if jack_ch:
                jack_vol = max(0.0, min(1.0, (1.0 - jack_dist / 18.0) * vol_mult * 0.7))
                jack_ch.set_volume(jack_vol)
            # Jack captura o jogador (não perto da saída)
            if jack_dist < BLOCK_SIZE * 1.8 and not jumpscare_active and not in_panic and dist_exit > BLOCK_SIZE * 6:
                jumpscare_active   = True
                jumpscare_start_ms = now_ms
                current_js_tex     = random.choice(jumpscare_textures)
                js_effect_type     = random.choice([0, 1, 2, 3]) if madness > 0.4 else 1
                if grito_snd: grito_snd.play()
                anxiety = min(1.0, anxiety + 0.5)  # Sobe ansiedade sem forçar 1.0 direto
                # Reinicia Jack longe
                jack_pos = (MAP_WIDTH - 3, MAP_HEIGHT - 3)
                next_jack_move_ms = now_ms + 18000  # Mais tempo antes de voltar

            # Jack imita respiração/sussurro se estiver perto mas não atacando
            if 3.0 * BLOCK_SIZE < jack_dist < 10.0 * BLOCK_SIZE and random.random() < 0.005 and whisper_snds:
                try:
                    s = random.choice(whisper_snds)
                    s.set_volume(max(0.1, 1.0 - jack_dist/12.0) * vol_mult)
                    s.play()
                except:
                    pass

            # ---- Batimento cardíaco ----
            if heartbeat_snd:
                bpm      = 60 + anxiety * 100
                interval = int(60000 / bpm)
                if now_ms >= next_beat_ms:
                    heartbeat_snd.set_volume(min(1.0, (0.3 + anxiety * 0.7) * vol_mult))
                    heartbeat_snd.play()
                    next_beat_ms = now_ms + interval


            # ---- Vozes esporádicas ----
            if voice_snds and now_ms >= next_voice_ms:
                chosen = random.choice(voice_snds)
                chosen.set_volume(min(1.0, 0.85 * vol_mult))
                chosen.play()
                # Próxima voz (intervalo reduz com loucura)
                next_voice_ms = now_ms + random.randint(voice_min_ms, voice_max_ms)

            # ---- Sussurros ----
            if whisper_snds and madness > 0.1 and now_ms >= next_whisper_ms:
                chosen = random.choice(whisper_snds)
                chosen.set_volume(min(1.0, (0.4 + madness * 0.6) * _gs.master_volume))
                chosen.play()
                next_whisper_ms = now_ms + random.randint(whisper_min_ms, whisper_max_ms)

            # ---- Jumpscare por zona (não perto da saída) ----
            cur_cell = (int(round((player_pos[0] / BLOCK_SIZE) + MAP_WIDTH/2)),
                        int(round((player_pos[2] / BLOCK_SIZE) + MAP_HEIGHT/2)))
            if cur_cell in trigger_zones and cur_cell not in triggered_zones and dist_exit > BLOCK_SIZE * 6:
                triggered_zones.add(cur_cell)
                if jumpscare_textures:
                    current_js_tex = random.choice(jumpscare_textures)
                    jumpscare_active   = True
                    jumpscare_start_ms = now_ms
                    stat_jumpscares += 1
                    # Efeito varia com loucura: 0=normal, 1=flash, 2=glitch, 3=negativo
                    if madness < 0.2:
                        js_effect_type = 0  # normal sempre
                    elif madness < 0.5:
                        js_effect_type = random.choice([0, 1])
                    elif madness < 0.8:
                        js_effect_type = random.choice([0, 1, 2])
                    else:
                        js_effect_type = random.choice([0, 1, 2, 3])
                    if scare_snd:
                        scare_snd.set_volume(min(1.0, vol_mult))
                        scare_snd.play()
                    # Spike na ansiedade!
                    anxiety = min(1.0, anxiety + 0.5)

            # Desativa jumpscare após duração
            if jumpscare_active and now_ms - jumpscare_start_ms > JUMPSCARE_DUR_MS:
                jumpscare_active = False
                shake_trauma = 0.7 + madness * 0.3   # Jumpscare gera shake violento (mais com loucura)

            # ---- Piscar de tela (cc >= 3) ----
            if cc >= 3:
                if not blink_active and now_ms >= next_blink_ms and not jumpscare_active:
                    blink_active   = True
                    blink_until_ms = now_ms + random.randint(100, 250)
                    next_blink_ms  = now_ms + random.randint(25000, 55000)
                if blink_active and now_ms >= blink_until_ms:
                    blink_active = False

            # ---- Tontura (cc >= 4) ----
            if cc >= 4:
                if not dizzy_active and now_ms >= next_dizzy_ms:
                    dizzy_active   = True
                    dizzy_until_ms = now_ms + random.randint(3000, 7000)
                    dizzy_strength = random.uniform(0.4, 1.0)
                    next_dizzy_ms  = now_ms + random.randint(20000, 50000)
                if dizzy_active and now_ms >= dizzy_until_ms:
                    dizzy_active   = False
                    dizzy_strength = 0.0

            # ---- Partículas de Inseto (aparecem com menos frequência) ----
            if not bug_active and now_ms >= next_bug_ms:
                bug_active    = True
                bug_start_ms  = now_ms
                bug_particles = spawn_bug_particles()
                next_bug_ms   = now_ms + random.randint(
                    max(90000, 180000 - cc * 12000),
                    max(120000, 260000 - cc * 18000)
                )

            if bug_active and now_ms - bug_start_ms > BUG_DUR_MS:
                bug_active    = False
                bug_particles = []

            # ---- Lanterna com Bateria + Tremido ----
            t_s = now_ms / 1000.0
            batt_factor = max(0.0, battery)       # 0.0 → 1.0
            if now_ms < flicker_off_until:
                flicker_val = 0.0
            elif battery <= 0.02:
                flicker_val = 0.0                 # Lanterna completamente apagada
            else:
                noise = (math.sin(t_s * 18.7) * 0.5 +
                         math.sin(t_s * 37.3) * 0.3 +
                         math.sin(t_s * 73.1) * 0.2)
                # Bateria fraca aumenta o flicker e diminui o brilho base
                batt_noise_scale = 1.0 - batt_factor * 0.5   # mais barulho com bateria baixa
                flicker_val = batt_factor * (1.0 - anxiety * 0.35 + noise * (anxiety + batt_noise_scale) * 0.2)
                flicker_val = max(0.03, min(1.0, flicker_val))
                # Apagão por ansiedade (mais frequente com bateria baixa)
                blackout_chance = 0.008 + (1.0 - batt_factor) * 0.025
                if anxiety > 0.45 and random.random() < blackout_chance:
                    dur = random.randint(80, 350) + int((1.0 - batt_factor) * 400)
                    flicker_off_until = now_ms + dur

            eff = flicker_val
            glLightfv(GL_LIGHT0, GL_DIFFUSE,
                      (0.8 * eff, 0.8 * eff, 0.9 * eff, 1.0))
            glLightfv(GL_LIGHT0, GL_SPECULAR,
                      (0.2 * eff, 0.2 * eff, 0.2 * eff, 1.0))

            # ---- Camera Shake + Tontura ----
            shake_trauma = max(0.0, shake_trauma - 0.03)
            # Trauma extra vindo da ansiedade alta
            if anxiety > 0.5:
                shake_trauma = max(shake_trauma, (anxiety - 0.5) * 0.4)
            shake_amp   = shake_trauma * shake_trauma  # quadrático = mais suave no início
            shake_yaw   = shake_amp * (
                math.sin(t_s * 23.1) * 0.018 + math.sin(t_s * 47.3) * 0.009)
            shake_pitch = shake_amp * (
                math.sin(t_s * 19.7) * 0.012 + math.sin(t_s * 37.1) * 0.006)
            # Tontura: oscilação lenta e ampla no yaw e pitch
            if dizzy_active:
                dizzy_yaw   = dizzy_strength * (math.sin(t_s * 1.3) * 0.12 + math.sin(t_s * 2.1) * 0.06)
                dizzy_pitch = dizzy_strength * (math.sin(t_s * 0.9) * 0.08 + math.sin(t_s * 1.7) * 0.04)
                shake_yaw   += dizzy_yaw
                shake_pitch += dizzy_pitch
            else:
                pass  # sem tontura

            # ---- Bafada de Frio ----
            if now_ms >= next_breath_ms and not in_panic:
                # Emite bafo em frente ao jogador, na altura dos olhos
                breath_puffs.append([
                    now_ms,
                    player_pos[0] + front_x * 0.5,
                    player_pos[1] - 0.1,
                    player_pos[2] + front_z * 0.5,
                    front_x, front_z
                ])
                next_breath_ms = now_ms + random.randint(2500, 4000)
            # Remove bafadas expiradas (> 1.5s)
            breath_puffs[:] = [p for p in breath_puffs if now_ms - p[0] < 1500]

            if is_moving:
                bob_time += 0.25 + anxiety * 0.15
                if math.floor(bob_time / math.pi) > math.floor(last_step_bob / math.pi):
                    if footstep_snd:
                        footstep_snd.set_volume(min(1.0, (0.01 + anxiety * 0.04) * _gs.master_volume))
                        footstep_snd.play()
                last_step_bob = bob_time
            else:
                # Dispara "passo extra" se o jogador acabou de parar
                if was_moving and madness > 0.1:
                    fake_echoes.append(now_ms + random.randint(200, 500))
                bob_time += (0 - bob_time) * 0.1
                last_step_bob = bob_time

            was_moving = is_moving
            bob_offset = math.sin(bob_time) * 0.05

            # ---- Registra pegada a cada "passo" (semi-período do bobbing) ----
            maybe_add_footprint(player_pos[0], player_pos[2], yaw, is_moving)

            # ---- Física de Som Espacial ----
            # (dist_exit, edx, edz já calculados acima)
            MAX_HUM_DIST = 20.0   # Raio máximo em que a saída é audível
            if hum_ch is not None:
                hum_vol = max(0.0, 1.0 - dist_exit / MAX_HUM_DIST)
                hum_snd.set_volume(hum_vol * 0.7)
            # Panning do vento: usa o ângulo relativo entre frente do jogador e saída
            if wind_ch is not None:
                ang = math.atan2(-edz, -edx) - yaw  # Ângulo relativo
                pan = math.sin(ang)                  # -1 (esq) a +1 (dir)
                left  = min(1.0, 1.0 - pan * 0.5)
                right = min(1.0, 1.0 + pan * 0.5)
                wind_ch.set_volume(left * 0.3, right * 0.3) 
            
            # ---- Detecção de saída por proximidade (sempre ativa) ----
            if dist_exit < EXIT_REACH:
                pygame.mixer.stop()
                run_time = (pygame.time.get_ticks() - run_start_ms) / 1000.0
                return ("END", run_time, stat_distance, stat_jumpscares, stat_peak_anxiety)

            # ---- Redução de efeitos perto da saída ----
            # Perto da saída, aliviar ansiedade para evitar soft-lock
            if dist_exit < BLOCK_SIZE * 5:
                exit_relief = 1.0 - (dist_exit / (BLOCK_SIZE * 5))
                anxiety = max(0.0, anxiety - ANXIETY_FALL * (1 + exit_relief * 5))

            old_x, old_z = player_pos[0], player_pos[2]

            col_x = check_collision(new_x, player_pos[2])
            if col_x == "EXIT":
                pygame.mixer.stop()
                run_time = (pygame.time.get_ticks() - run_start_ms) / 1000.0
                return ("END", run_time, stat_distance, stat_jumpscares, stat_peak_anxiety)
            elif not col_x:
                player_pos[0] = new_x

            col_z = check_collision(player_pos[0], new_z)
            if col_z == "EXIT":
                pygame.mixer.stop()
                run_time = (pygame.time.get_ticks() - run_start_ms) / 1000.0
                return ("END", run_time, stat_distance, stat_jumpscares, stat_peak_anxiety)
            elif not col_z:
                player_pos[2] = new_z
            
            stat_distance += math.hypot(player_pos[0] - old_x, player_pos[2] - old_z)

            look_x = player_pos[0] + math.cos(pitch + shake_pitch) * math.cos(yaw + shake_yaw)
            look_y = player_pos[1] + math.sin(pitch + shake_pitch)
            look_z = player_pos[2] + math.cos(pitch + shake_pitch) * math.sin(yaw + shake_yaw)

            glLightfv(GL_LIGHT0, GL_POSITION, (player_pos[0], player_pos[1] + bob_offset, player_pos[2], 1.0))
            glLightfv(GL_LIGHT0, GL_SPOT_DIRECTION, (look_x - player_pos[0], look_y - player_pos[1], look_z - player_pos[2]))

            glClearColor(*fog_color) 
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glLoadIdentity()
            
            # Posiciona a Câmera (com shake aplicado no look target)
            gluLookAt(player_pos[0], player_pos[1] + bob_offset, player_pos[2],
                      look_x, look_y + bob_offset, look_z,
                      0, 1, 0)

            # 1. Desenha o Skybox no fundo de tudo
            draw_skybox(tex_skybox, player_pos[0], player_pos[1], player_pos[2])

            # 2. Renderiza o labirinto
            # 1. Chão e Paredes
            draw_floor(tex_snow, MAP_WIDTH, MAP_HEIGHT)
            draw_blood_trails(blood_decals)
            for c in corpses:
                draw_corpse(tex_corpse, c['pos'][0], c['pos'][1])
            draw_footprints()
            glCallList(maze_dlist)

            # 2b. Textos nas paredes (surgem conforme madness)
            if wall_text_data:
                WALL_H = 2.5   # altura do texto no mundo
                TEXT_W = 1.6   # metade da largura
                TEXT_H = 0.45  # metade da altura
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                glDisable(GL_LIGHTING)
                glEnable(GL_TEXTURE_2D)
                glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                for (wx, wz, ndx, ndz, label, min_mad) in wall_text_data:
                    if madness < min_mad:
                        continue
                    fade = min(1.0, (madness - min_mad) / 0.12)  # aparece gradualmente
                    # Pulsa levemente
                    pulse = 0.7 + 0.3 * abs(math.sin(t_s * 1.8 + wx))
                    alpha = fade * pulse
                    tid, umax, vmax = wall_text_textures[label]
                    glBindTexture(GL_TEXTURE_2D, tid)
                    glColor4f(1.0, 0.08, 0.08, alpha)
                    # Eixos da face dependem do normal
                    wy = WALL_H
                    glBegin(GL_QUADS)
                    if abs(ndx) > 0.5:  # face aponta em X → quad no plano Y-Z
                        glTexCoord2f(0, vmax);    glVertex3f(wx, wy - TEXT_H, wz - TEXT_W)
                        glTexCoord2f(umax, vmax); glVertex3f(wx, wy - TEXT_H, wz + TEXT_W)
                        glTexCoord2f(umax, 0);    glVertex3f(wx, wy + TEXT_H, wz + TEXT_W)
                        glTexCoord2f(0, 0);       glVertex3f(wx, wy + TEXT_H, wz - TEXT_W)
                    else:               # face aponta em Z → quad no plano X-Y
                        glTexCoord2f(0, vmax);    glVertex3f(wx - TEXT_W, wy - TEXT_H, wz)
                        glTexCoord2f(umax, vmax); glVertex3f(wx + TEXT_W, wy - TEXT_H, wz)
                        glTexCoord2f(umax, 0);    glVertex3f(wx + TEXT_W, wy + TEXT_H, wz)
                        glTexCoord2f(0, 0);       glVertex3f(wx - TEXT_W, wy + TEXT_H, wz)
                    glEnd()
                glPopAttrib()

            # 4. Saída animada
            draw_exit(maze_map, MAP_WIDTH, MAP_HEIGHT)
            draw_campfires(campfires)

            # 3. Desenha o Jack (e os Falsos Jacks)
            draw_jack_shadow(jack_wx, jack_wz, jack_dist, madness)
            for fj in fake_jacks:
                fj_wx, fj_wz = fj['pos']
                fj_dist = math.dist([player_pos[0], player_pos[2]], [fj_wx, fj_wz])
                draw_jack_shadow(fj_wx, fj_wz, fj_dist, madness)

            # 4. Partículas e Bafadas de Frio (billboards)
            draw_particles(player_pos[0], player_pos[2])
            draw_ceiling_drips(blood_drip_zones, now_ms)

            # 5b. Bafadas de Frio (billboards)
            draw_breath_puffs(breath_puffs, now_ms, yaw)

            # 5c. Aberração Cromática (efeito de alucinação em alta ansiedade)
            if anxiety > 0.6:
                draw_chromatic_aberration((anxiety - 0.6) / 0.4)


            # 5. Overlays 2D (HUD)
            draw_anxiety_hud(anxiety, battery, hypothermia, blood_overlay_timer)

            # ---- Prompt de Interação ----
            near_unsearched = False
            for c in corpses:
                if not c['searched']:
                    c_dist = math.dist([player_pos[0], player_pos[2]], [c['pos'][0], c['pos'][1]])
                    if c_dist < BLOCK_SIZE * 1.5:
                        near_unsearched = True
                        break
            
            if near_unsearched and interact_tex_info:
                glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                W2, H2 = DISPLAY_SIZE
                glOrtho(0, W2, H2, 0, -1, 1)
                glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity()
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                glDisable(GL_LIGHTING); glDisable(GL_DEPTH_TEST)
                glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                
                tid, u_max, v_max = interact_tex_info
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, tid)
                glColor4f(1, 1, 1, 1)
                
                TW = int(600); TH = int(60)
                TX = (W2 - TW) // 2; TY = H2 - 120
                glBegin(GL_QUADS)
                glTexCoord2f(0, 0);         glVertex2f(TX, TY)
                glTexCoord2f(u_max, 0);     glVertex2f(TX + TW, TY)
                glTexCoord2f(u_max, v_max); glVertex2f(TX + TW, TY + TH)
                glTexCoord2f(0, v_max);     glVertex2f(TX, TY + TH)
                glEnd()
                
                glPopAttrib()
                glMatrixMode(GL_PROJECTION); glPopMatrix()
                glMatrixMode(GL_MODELVIEW); glPopMatrix()
                glEnable(GL_DEPTH_TEST)

            # 6b. Minimapa
            if now_ms < minimap_timer_ms:
                draw_minimap(maze_map, MAP_WIDTH, MAP_HEIGHT, player_pos[0], player_pos[2])

            # 6c. Piscar de tela (tela preta por frames)
            if blink_active:
                W2b, H2b = DISPLAY_SIZE
                glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                glOrtho(0, W2b, H2b, 0, -1, 1)
                glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
                glDisable(GL_TEXTURE_2D)
                glDisable(GL_BLEND)
                glColor3f(0.0, 0.0, 0.0)
                glBegin(GL_QUADS)
                glVertex2f(0,0); glVertex2f(W2b,0)
                glVertex2f(W2b,H2b); glVertex2f(0,H2b)
                glEnd()
                glPopAttrib()
                glMatrixMode(GL_PROJECTION); glPopMatrix()
                glMatrixMode(GL_MODELVIEW); glPopMatrix()
                glEnable(GL_DEPTH_TEST)

            # 6c. Overlay de tontura (vinheta roxa pulsando)
            if dizzy_active:
                W2d, H2d = DISPLAY_SIZE
                diz_pulse = abs(math.sin(t_s * 1.5)) * dizzy_strength
                glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                glOrtho(0, W2d, H2d, 0, -1, 1)
                glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
                glDisable(GL_TEXTURE_2D)
                glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                glColor4f(0.3, 0.0, 0.4, diz_pulse * 0.45)
                glBegin(GL_QUADS)
                glVertex2f(0,0); glVertex2f(W2d,0)
                glVertex2f(W2d,H2d); glVertex2f(0,H2d)
                glEnd()
                glPopAttrib()
                glMatrixMode(GL_PROJECTION); glPopMatrix()
                glMatrixMode(GL_MODELVIEW); glPopMatrix()
                glEnable(GL_DEPTH_TEST)

            # 7. Jumpscare com variações visuais baseadas em loucura
            if trap_text_timer_ms > now_ms:
                glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                W2, H2 = DISPLAY_SIZE
                glOrtho(0, W2, H2, 0, -1, 1)
                glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity()
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                glDisable(GL_LIGHTING); glDisable(GL_DEPTH_TEST)
                glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                
                tid, u_max, v_max = trap_tex_info
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, tid)
                glColor4f(1, 1, 1, 1)
                
                # Draw text overlay
                TW = int(800); TH = int(120)
                TX = (W2 - TW) // 2; TY = (H2 - TH) // 2
                glBegin(GL_QUADS)
                glTexCoord2f(0, 0);         glVertex2f(TX, TY)
                glTexCoord2f(u_max, 0);     glVertex2f(TX + TW, TY)
                glTexCoord2f(u_max, v_max); glVertex2f(TX + TW, TY + TH)
                glTexCoord2f(0, v_max);     glVertex2f(TX, TY + TH)
                glEnd()
                
                glPopAttrib()
                glMatrixMode(GL_PROJECTION); glPopMatrix()
                glMatrixMode(GL_MODELVIEW); glPopMatrix()
                glEnable(GL_DEPTH_TEST)

            elif jumpscare_active and current_js_tex is not None:
                W2, H2 = DISPLAY_SIZE
                js_age = (now_ms - jumpscare_start_ms) / max(JUMPSCARE_DUR_MS, 1)

                glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                glOrtho(0, W2, H2, 0, -1, 1)
                glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity()
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
                glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

                if js_effect_type == 1:
                    # ---- Flash Branco: tela explode em branco ----
                    flash_alpha = max(0.0, 1.0 - js_age * 2.0)
                    glDisable(GL_TEXTURE_2D)
                    glColor4f(1.0, 1.0, 1.0, flash_alpha)
                    glBegin(GL_QUADS)
                    glVertex2f(0, 0); glVertex2f(W2, 0)
                    glVertex2f(W2, H2); glVertex2f(0, H2)
                    glEnd()

                elif js_effect_type == 2:
                    # ---- Glitch: imagem deslocada em tiras horizontais ----
                    glDisable(GL_TEXTURE_2D)
                    glColor4f(0.0, 0.0, 0.0, 0.9)
                    glBegin(GL_QUADS)
                    glVertex2f(0,0); glVertex2f(W2,0)
                    glVertex2f(W2,H2); glVertex2f(0,H2)
                    glEnd()
                    glEnable(GL_TEXTURE_2D)

                    JS_W = int(W2 * 0.85); JS_H = int(H2 * 0.85)
                    JS_X = (W2 - JS_W) // 2; JS_Y = (H2 - JS_H) // 2
                    glBindTexture(GL_TEXTURE_2D, current_js_tex)
                    # Renderiza em tiras com offsets aleatórios de glitch
                    STRIPS = 12
                    sh = JS_H // STRIPS
                    for i in range(STRIPS):
                        ox = random.randint(-30, 30)
                        y0 = JS_Y + i * sh
                        y1 = y0 + sh
                        t0 = i / STRIPS; t1 = (i + 1) / STRIPS
                        glColor3f(1, 1, 1)
                        glBegin(GL_QUADS)
                        glTexCoord2f(0, t0); glVertex2f(JS_X + ox,        y0)
                        glTexCoord2f(1, t0); glVertex2f(JS_X + JS_W + ox, y0)
                        glTexCoord2f(1, t1); glVertex2f(JS_X + JS_W + ox, y1)
                        glTexCoord2f(0, t1); glVertex2f(JS_X + ox,        y1)
                        glEnd()
                    # Sobreposição vermelha piscando
                    glDisable(GL_TEXTURE_2D)
                    pulse = abs(math.sin(now_ms / 80.0))
                    glColor4f(1.0, 0.0, 0.0, pulse * 0.4)
                    glBegin(GL_QUADS)
                    glVertex2f(0,0); glVertex2f(W2,0)
                    glVertex2f(W2,H2); glVertex2f(0,H2)
                    glEnd()

                elif js_effect_type == 3:
                    # ---- Negativo/Vermelho: tudo invertido e saturado de vermelho ----
                    glDisable(GL_TEXTURE_2D)
                    glColor4f(0.6, 0.0, 0.0, 0.92)
                    glBegin(GL_QUADS)
                    glVertex2f(0,0); glVertex2f(W2,0)
                    glVertex2f(W2,H2); glVertex2f(0,H2)
                    glEnd()
                    glEnable(GL_TEXTURE_2D)

                    JS_W = W2; JS_H = H2
                    JS_X = 0; JS_Y = 0
                    glBindTexture(GL_TEXTURE_2D, current_js_tex)
                    glBlendFunc(GL_ONE_MINUS_DST_COLOR, GL_ZERO)  # Blend de inversão
                    glColor3f(1, 1, 1)
                    glBegin(GL_QUADS)
                    glTexCoord2f(0,0); glVertex2f(0,   0)
                    glTexCoord2f(1,0); glVertex2f(W2,  0)
                    glTexCoord2f(1,1); glVertex2f(W2,  H2)
                    glTexCoord2f(0,1); glVertex2f(0,   H2)
                    glEnd()
                    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

                else:
                    # ---- Normal (tipo 0): centralizado com fundo escuro ----
                    glDisable(GL_TEXTURE_2D)
                    glColor4f(0.0, 0.0, 0.0, 0.82)
                    glBegin(GL_QUADS)
                    glVertex2f(0, 0); glVertex2f(W2, 0)
                    glVertex2f(W2, H2); glVertex2f(0, H2)
                    glEnd()
                    glEnable(GL_TEXTURE_2D)

                    JS_W = int(W2 * 0.65); JS_H = int(H2 * 0.65)
                    JS_X = (W2 - JS_W) // 2; JS_Y = (H2 - JS_H) // 2
                    glBindTexture(GL_TEXTURE_2D, current_js_tex)
                    glColor3f(1, 1, 1)
                    glBegin(GL_QUADS)
                    glTexCoord2f(0, 0); glVertex2f(JS_X,        JS_Y)
                    glTexCoord2f(1, 0); glVertex2f(JS_X + JS_W, JS_Y)
                    glTexCoord2f(1, 1); glVertex2f(JS_X + JS_W, JS_Y + JS_H)
                    glTexCoord2f(0, 1); glVertex2f(JS_X,        JS_Y + JS_H)
                    glEnd()

                glPopAttrib()
                glMatrixMode(GL_PROJECTION); glPopMatrix()
                glMatrixMode(GL_MODELVIEW);  glPopMatrix()
                glEnable(GL_DEPTH_TEST)

            # 8. Partículas de Inseto – quadradinhos marrons subindo pelo personagem
            if bug_active and bug_particles:
                bug_age_ratio = (now_ms - bug_start_ms) / BUG_DUR_MS  # 0.0 → 1.0
                W2b, H2b = DISPLAY_SIZE

                glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                glOrtho(0, W2b, H2b, 0, -1, 1)
                glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
                glDisable(GL_TEXTURE_2D)
                glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                glBegin(GL_QUADS)

                for p in bug_particles:
                    # Tempo local por partícula (com delay e speed individuais)
                    t_raw = (bug_age_ratio - p['delay']) / max(1.0 - p['delay'], 0.01)
                    t = max(0.0, min(t_raw * p['speed'], 1.0))

                    # Fase 0 (0→0.45): spawn → pé do jogador (chão)
                    # Fase 1 (0.45→0.88): pé → rosto (subindo)
                    # Fase 2 (0.88→1.0): fadeout no rosto
                    if t < 0.45:
                        tt = t / 0.45
                        # ease-in quadrático
                        tt = tt * tt
                        x = p['sx'] + (p['fx'] - p['sx']) * tt
                        y = p['sy'] + (p['fy'] - p['sy']) * tt
                    elif t < 0.88:
                        tt = (t - 0.45) / 0.43
                        # ease-out: desacelera no rosto
                        tt = 1.0 - (1.0 - tt) * (1.0 - tt)
                        x = p['fx'] + (p['ex'] - p['fx']) * tt
                        y = p['fy'] + (p['ey'] - p['fy']) * tt
                    else:
                        x = p['ex'] + math.sin(t * 30 + p['wobble']) * 4
                        y = p['ey']

                    # Oscilação lateral (imita rastejo)
                    x += math.sin(t * 22 + p['wobble']) * 6

                    # Alpha: surge rápido, some devagar no final
                    if t < 0.08:
                        alpha = t / 0.08
                    elif t > 0.88:
                        alpha = 1.0 - (t - 0.88) / 0.12
                    else:
                        alpha = 1.0

                    if alpha <= 0.0 or t <= 0.0:
                        continue

                    # Cor marrom com variação
                    br = p['brown'] / 255.0
                    glColor4f(br, br * 0.45, br * 0.1, alpha)

                    s = p['size']
                    glVertex2f(x,     y)
                    glVertex2f(x + s, y)
                    glVertex2f(x + s, y + s)
                    glVertex2f(x,     y + s)

                glEnd()
                glPopAttrib()
                glMatrixMode(GL_PROJECTION); glPopMatrix()
                glMatrixMode(GL_MODELVIEW); glPopMatrix()
                glEnable(GL_DEPTH_TEST)

            # ---- Fade-in suave no inicio do jogo ----
            if game_fade_alpha > 0:
                game_fade_alpha = max(0, game_fade_alpha - 17)
                _fi_W, _fi_H = DISPLAY_SIZE
                glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                glOrtho(0, _fi_W, _fi_H, 0, -1, 1)
                glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
                glDisable(GL_TEXTURE_2D); glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                glColor4f(0.0, 0.0, 0.0, game_fade_alpha / 255.0)
                glBegin(GL_QUADS)
                glVertex2f(0, 0); glVertex2f(_fi_W, 0)
                glVertex2f(_fi_W, _fi_H); glVertex2f(0, _fi_H)
                glEnd()
                glPopAttrib()
                glMatrixMode(GL_PROJECTION); glPopMatrix()
                glMatrixMode(GL_MODELVIEW); glPopMatrix()
                glEnable(GL_DEPTH_TEST)

            pygame.display.flip()
            clock.tick(60)
    finally:
        # Garante que todos os sons param ao sair do estado de jogo
        pygame.mixer.stop()

# ================================
# FLUXO PRINCIPAL
# ================================

def main():
    pygame.init()
    pygame.font.init()
    
    try:
        title_font = pygame.font.SysFont("impact", 90)
        font = pygame.font.SysFont("arial", 28)
    except:
        title_font = pygame.font.Font(None, 90)
        font = pygame.font.Font(None, 28)
        
    state = "MENU"
    
    while state != "QUIT":
        if state == "MENU":
            screen = pygame.display.set_mode(DISPLAY_SIZE)
            pygame.display.set_caption("The Shining Maze - Menu")
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            state = run_menu(screen, font, title_font)
            
        elif state == "GAME":
            pygame.display.set_mode(DISPLAY_SIZE, DOUBLEBUF | OPENGL)
            pygame.display.set_caption("The Shining Maze - Inside")
            pygame.mouse.set_visible(False)
            pygame.event.set_grab(True)
            res = run_game()
            if isinstance(res, tuple):
                state = res[0]
                stats = res[1:]
            else:
                state = res
                stats = None
            
        elif state == "SETTINGS":
            screen = pygame.display.set_mode(DISPLAY_SIZE)
            pygame.display.set_caption("The Shining Maze - Settings")
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            state = run_settings_screen(screen, font, title_font, is_pause=False)
            
        elif state == "END":
            screen = pygame.display.set_mode(DISPLAY_SIZE)
            pygame.display.set_caption("The Shining Maze - Você Sobreviveu! Até agora...")
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            state = run_end_screen(screen, font, title_font, stats if 'stats' in locals() else None)

    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
