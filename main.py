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
    draw_skybox, draw_exit, draw_floor, draw_corpse, draw_campfires,
    draw_flashlight_volumetric_shaft, draw_jack_billboard,
    build_maze_chunks, draw_maze_optimized, draw_battery_pickup
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

def check_collision(x, z, radius=0.0):
    """
    Colisão contínua e exata (Círculo vs AABBs das células do labirinto).
    Elimina paredes invisíveis, quinas com travamento e vazamentos através de paredes.
    """
    global maze_map, MAP_WIDTH, MAP_HEIGHT
    if not maze_map or MAP_WIDTH <= 0 or MAP_HEIGHT <= 0:
        return False

    half_b = BLOCK_SIZE * 0.5

    if radius <= 0.0:
        mx = math.floor((x / BLOCK_SIZE) + MAP_WIDTH / 2.0 + 0.5)
        my = math.floor((z / BLOCK_SIZE) + MAP_HEIGHT / 2.0 + 0.5)
        if 0 <= mx < MAP_WIDTH and 0 <= my < MAP_HEIGHT:
            if maze_map[my][mx] == 1:
                return True
            if maze_map[my][mx] == 2:
                return "EXIT"
            return False
        return True

    # Células potencialmente interceptadas pelo círculo do jogador
    min_c = math.floor(((x - radius) / BLOCK_SIZE) + MAP_WIDTH / 2.0 + 0.5)
    max_c = math.floor(((x + radius) / BLOCK_SIZE) + MAP_WIDTH / 2.0 + 0.5)
    min_r = math.floor(((z - radius) / BLOCK_SIZE) + MAP_HEIGHT / 2.0 + 0.5)
    max_r = math.floor(((z + radius) / BLOCK_SIZE) + MAP_HEIGHT / 2.0 + 0.5)

    has_exit = False
    r_sq = radius * radius

    for my in range(min_r, max_r + 1):
        for mx in range(min_c, max_c + 1):
            if mx < 0 or mx >= MAP_WIDTH or my < 0 or my >= MAP_HEIGHT:
                return True

            cell_type = maze_map[my][mx]
            if cell_type == 1:
                # Centro e limites AABB exatos da parede
                cx = (mx - MAP_WIDTH / 2.0) * BLOCK_SIZE
                cz = (my - MAP_HEIGHT / 2.0) * BLOCK_SIZE
                bx0 = cx - half_b
                bx1 = cx + half_b
                bz0 = cz - half_b
                bz1 = cz + half_b

                closest_x = max(bx0, min(x, bx1))
                closest_z = max(bz0, min(z, bz1))
                dist_sq = (x - closest_x) ** 2 + (z - closest_z) ** 2
                if dist_sq < r_sq:
                    return True

            elif cell_type == 2:
                cx = (mx - MAP_WIDTH / 2.0) * BLOCK_SIZE
                cz = (my - MAP_HEIGHT / 2.0) * BLOCK_SIZE
                bx0 = cx - half_b
                bx1 = cx + half_b
                bz0 = cz - half_b
                bz1 = cz + half_b

                closest_x = max(bx0, min(x, bx1))
                closest_z = max(bz0, min(z, bz1))
                dist_sq = (x - closest_x) ** 2 + (z - closest_z) ** 2
                if dist_sq < (radius + 0.25) ** 2:
                    has_exit = True

    return "EXIT" if has_exit else False

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


def calc_3d_spatial_volume(listener_x, listener_z, listener_yaw, source_x, source_z, max_dist=22.0, base_vol=1.0):
    """Calcula atenuação acústica realista por distância e espacialização estéreo 3D (left, right)."""
    dx = source_x - listener_x
    dz = source_z - listener_z
    dist = math.hypot(dx, dz)
    if dist >= max_dist:
        return 0.0, 0.0

    # Atenuação por distância suave (não satura de forma abrupta)
    norm_dist = max(0.0, (dist - 1.0) / max(0.1, max_dist - 1.0))
    attenuation = (1.0 - norm_dist) ** 1.6

    # Ângulo relativo no plano horizontal em relação ao vetor de visão do ouvinte
    angle_to_source = math.atan2(dz, dx)
    rel_angle = (angle_to_source - listener_yaw) % (2.0 * math.pi)
    if rel_angle > math.pi:
        rel_angle -= 2.0 * math.pi

    # Pan horizontal estéreo (-1.0 à esquerda, +1.0 à direita)
    pan = math.sin(rel_angle)
    # Leve abafamento físico quando o som vem diretamente de trás
    rear_factor = 1.0 - 0.15 * max(0.0, -math.cos(rel_angle))

    # Lei de panning por potência constante (equal-power stereo law)
    pan_clamped = max(-1.0, min(1.0, pan))
    theta = (pan_clamped + 1.0) * (math.pi / 4.0)
    left_gain = math.cos(theta)
    right_gain = math.sin(theta)

    vol = attenuation * base_vol * rear_factor * _gs.master_volume
    return max(0.0, min(1.0, vol * left_gain)), max(0.0, min(1.0, vol * right_gain))


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


_chroma_tex_id = None

def cleanup_chromatic_aberration_texture():
    global _chroma_tex_id
    if _chroma_tex_id is not None:
        try:
            glDeleteTextures([_chroma_tex_id])
        except Exception:
            pass
        _chroma_tex_id = None


def draw_chromatic_aberration(intensity):
    """Captura o backbuffer e re-renderiza separando canais RGB."""
    global _chroma_tex_id
    W, H = DISPLAY_SIZE
    off = int(intensity * 10)
    if off < 1:
        return
    # Captura cena atual reutilizando textura existente
    if _chroma_tex_id is None:
        _chroma_tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, _chroma_tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
        glCopyTexImage2D(GL_TEXTURE_2D, 0, GL_RGB, 0, 0, W, H, 0)
    else:
        glBindTexture(GL_TEXTURE_2D, _chroma_tex_id)
        glCopyTexSubImage2D(GL_TEXTURE_2D, 0, 0, 0, 0, 0, W, H)

    # Re-renderiza sobre si mesmo (glOrtho com Y=0 na base, como OpenGL default)
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W, 0, H, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
    glEnable(GL_TEXTURE_2D)
    glBindTexture(GL_TEXTURE_2D, _chroma_tex_id)
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

    # Player position (centralizado na célula)
    map_x = (px / BLOCK_SIZE) + mw / 2.0
    map_y = (pz / BLOCK_SIZE) + mh / 2.0
    px_screen = W - size - margin + (map_x + 0.5) * cell_w
    py_screen = margin + (map_y + 0.5) * cell_h
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


_pause_tex_id = None
_last_pause_state = None

def cleanup_pause_overlay_texture():
    global _pause_tex_id, _last_pause_state
    if _pause_tex_id is not None:
        try:
            glDeleteTextures([_pause_tex_id])
        except Exception:
            pass
        _pause_tex_id = None
    _last_pause_state = None


def draw_pause_overlay(selected, in_settings, vol, sens, settings_sel):
    """Renderiza o menu de pausa como overlay OpenGL sobre a cena congelada."""
    global _pause_tex_id, _last_pause_state
    W, H = DISPLAY_SIZE
    state_key = (
        selected, in_settings, round(vol, 2), round(sens, 1), settings_sel,
        _gs.difficulty, int(_gs.fov), _gs.head_bobbing, _gs.camera_shake,
        _gs.photosensitivity_mode, _gs.invert_mouse_y
    )

    if _pause_tex_id is None:
        _pause_tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, _pause_tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        _last_pause_state = None

    if state_key != _last_pause_state:
        overlay = pygame.Surface((W, H), pygame.SRCALPHA)
        overlay.fill((0, 0, 0, 180))
        try:
            tfont = pygame.font.SysFont("impact", 68)
            ofont_main = pygame.font.SysFont("arial", 36)
            ofont_set = pygame.font.SysFont("arial", 25)
            hfont = pygame.font.SysFont("arial", 21)
        except Exception:
            tfont = pygame.font.Font(None, 68)
            ofont_main = pygame.font.Font(None, 36)
            ofont_set = pygame.font.Font(None, 25)
            hfont = pygame.font.Font(None, 21)

        if not in_settings:
            title = tfont.render("PAUSA", True, (210, 210, 210))
            overlay.blit(title, title.get_rect(center=(W // 2, H // 2 - 130)))
            options = ["Continuar", "Configuracoes & Acessibilidade", "Sair ao Menu"]
            for i, opt in enumerate(options):
                color = (255, 255, 80) if i == selected else (170, 170, 170)
                prefix = "> " if i == selected else "  "
                surf = ofont_main.render(prefix + opt, True, color)
                overlay.blit(surf, surf.get_rect(center=(W // 2, H // 2 - 20 + i * 60)))
            hint = hfont.render("[SETAS] Navegar  |  ENTER Selecionar  |  ESC Retomar",
                                True, (120, 120, 120))
            overlay.blit(hint, hint.get_rect(center=(W // 2, H - 40)))
        else:
            title = tfont.render("CONFIGURACOES", True, (210, 210, 210))
            overlay.blit(title, title.get_rect(center=(W // 2, 85)))
            
            diff_label = _gs.DIFFICULTY_PRESETS.get(_gs.difficulty, {}).get("label", _gs.difficulty)
            items = [
                f"Volume Geral: {int(vol * 100)}%",
                f"Sensibilidade Mouse: {int(sens)}",
                f"Dificuldade: {diff_label} (Aplica no proximo labirinto)",
                f"Campo de Visao (FOV): {int(_gs.fov)}°",
                f"Balanco de Camera (Bobbing): {'Ligado' if _gs.head_bobbing else 'Desligado'}",
                f"Tremores de Camera (Shake): {'Ligado' if _gs.camera_shake else 'Desligado'}",
                f"Fotosensibilidade (Sem Flashes): {'Ligado' if _gs.photosensitivity_mode else 'Desligado'}",
                f"Inverter Eixo Y: {'Sim' if _gs.invert_mouse_y else 'Nao'}",
                "Voltar ao Menu de Pausa"
            ]
            
            start_y = 155
            spacing = 44
            for i, item in enumerate(items):
                color = (255, 255, 80) if i == settings_sel else (175, 175, 175)
                prefix = "> " if i == settings_sel else "  "
                surf = ofont_set.render(prefix + item, True, color)
                overlay.blit(surf, surf.get_rect(center=(W // 2, start_y + i * spacing)))
                
            hint = hfont.render("[ESQ/DIR ou ENTER] Ajustar  |  [SETAS CIMA/BAIXO] Navegar  |  ESC Voltar",
                                True, (130, 130, 130))
            overlay.blit(hint, hint.get_rect(center=(W // 2, H - 35)))

        raw = pygame.image.tostring(overlay, "RGBA", True)
        glBindTexture(GL_TEXTURE_2D, _pause_tex_id)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, raw)
        _last_pause_state = state_key

    glBindTexture(GL_TEXTURE_2D, _pause_tex_id)
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
    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)


_gl_screen_tex_id = None

def cleanup_screen_texture():
    global _gl_screen_tex_id
    if _gl_screen_tex_id is not None:
        try:
            glDeleteTextures([_gl_screen_tex_id])
        except Exception:
            pass
        _gl_screen_tex_id = None


def render_surface_to_opengl(surf):
    """Renderiza uma Surface Pygame 2D diretamente no viewport OpenGL via projeção ortográfica."""
    global _gl_screen_tex_id
    W, H = DISPLAY_SIZE
    if _gl_screen_tex_id is None:
        _gl_screen_tex_id = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, _gl_screen_tex_id)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)

    raw = pygame.image.tostring(surf, "RGBA", True)
    glBindTexture(GL_TEXTURE_2D, _gl_screen_tex_id)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, W, H, 0, GL_RGBA, GL_UNSIGNED_BYTE, raw)

    glClearColor(0.0, 0.0, 0.0, 1.0)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W, 0, H, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
    glEnable(GL_TEXTURE_2D)
    glBindTexture(GL_TEXTURE_2D, _gl_screen_tex_id)
    glColor4f(1.0, 1.0, 1.0, 1.0)
    glBegin(GL_QUADS)
    glTexCoord2f(0, 0); glVertex2f(0, 0)
    glTexCoord2f(1, 0); glVertex2f(W, 0)
    glTexCoord2f(1, 1); glVertex2f(W, H)
    glTexCoord2f(0, 1); glVertex2f(0, H)
    glEnd()
    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)
    pygame.display.flip()


def run_menu(screen, font, title_font):
    clock = pygame.time.Clock()
    canvas = pygame.Surface(DISPLAY_SIZE)
    snowflakes = [[random.randint(0, DISPLAY_SIZE[0]), random.randint(0, DISPLAY_SIZE[1])] for _ in range(150)]
    _fade_result = None
    _fade_alpha = 0

    while True:
        dt = clock.tick(60) / 1000.0
        dt_step = min(dt, 0.1) * 60.0
        if _fade_result and _fade_alpha >= 255:
            return _fade_result

        for event in pygame.event.get():
            if event.type == QUIT: return "QUIT"
            if event.type == KEYDOWN and not _fade_result:
                if event.key == K_RETURN: _fade_result = "GAME"
                if event.key == K_ESCAPE: return "QUIT"
                if event.key == K_s: _fade_result = "SETTINGS"
                if event.key in (K_d, K_TAB):
                    idx = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
                    _gs.difficulty = _gs.DIFFICULTIES[(idx + 1) % len(_gs.DIFFICULTIES)]
                    _gs.save_save_data()
                    
        canvas.fill((5, 5, 8)) 
        
        for flake in snowflakes:
            flake[1] += random.randint(1, 4) * dt_step
            if flake[1] > DISPLAY_SIZE[1]:
                flake[1] = 0
                flake[0] = random.randint(0, DISPLAY_SIZE[0])
            pygame.draw.circle(canvas, (220, 220, 255), (int(flake[0]), int(flake[1])), 2)
        
        title_text = title_font.render("THE SHINING MAZE", True, (150, 10, 10))
        title_rect = title_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 - 110))
        canvas.blit(title_text, title_rect)
        
        if (pygame.time.get_ticks() // 600) % 2 == 0:
            start_text = font.render("> Pressione [ENTER] para Entrar <", True, (255, 255, 255))
            start_rect = start_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 35))
            canvas.blit(start_text, start_rect)
        
        diff_info = _gs.DIFFICULTY_PRESETS.get(_gs.difficulty, {})
        diff_text = font.render(f"Dificuldade: {diff_info.get('label', _gs.difficulty)} ({diff_info.get('desc', '')})  [D]", True, (200, 185, 100))
        diff_rect = diff_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 85))
        canvas.blit(diff_text, diff_rect)

        # Estatísticas e Recordes salvos (save_data.json)
        recs = _gs.save_data.get("records", {}) if _gs.save_data else {}
        diff_best = recs.get("best_times_by_diff", {}).get(_gs.difficulty)
        best_str = f"{int(diff_best//60)}m {int(diff_best%60):02d}s" if diff_best is not None else "--:--"
        total_wins = _gs.save_data.get("progress", {}).get("total_wins", 0) if _gs.save_data else 0
        rec_text = font.render(f"Melhor Tempo [{_gs.difficulty}]: {best_str}   |   Fugas Concluidas: {total_wins}", True, (120, 160, 175))
        rec_rect = rec_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 125))
        canvas.blit(rec_text, rec_rect)

        inst_text = font.render("Use fones (Audio 3D) | [F] Lanterna | WASD Mover | [S] Configuracoes", True, (130, 130, 130))
        inst_rect = inst_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1] - 40))
        canvas.blit(inst_text, inst_rect)
        
        if _fade_result:
            _fade_alpha = min(255, _fade_alpha + int(round(17 * dt_step)))
            _fade_surf = pygame.Surface(DISPLAY_SIZE)
            _fade_surf.fill((0, 0, 0))
            _fade_surf.set_alpha(_fade_alpha)
            canvas.blit(_fade_surf, (0, 0))

        render_surface_to_opengl(canvas)


def run_settings_screen(screen, font, title_font, is_pause=False):
    clock = pygame.time.Clock()
    canvas = pygame.Surface(DISPLAY_SIZE)
    vol = _gs.master_volume
    sens = _gs.mouse_sensitivity * 1000.0
    selected = 0
    num_items = 9

    try:
        opt_font = pygame.font.SysFont("arial", 25)
        hint_font = pygame.font.SysFont("arial", 20)
    except Exception:
        opt_font = font
        hint_font = font

    while True:
        clock.tick(60)
        for event in pygame.event.get():
            if event.type == QUIT: return "QUIT"
            if event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    _gs.master_volume = vol
                    _gs.mouse_sensitivity = sens / 1000.0
                    _gs.save_save_data()
                    return "GAME" if is_pause else "MENU"
                if event.key in (K_RETURN, K_SPACE):
                    if selected == 8:
                        _gs.master_volume = vol
                        _gs.mouse_sensitivity = sens / 1000.0
                        _gs.save_save_data()
                        return "GAME" if is_pause else "MENU"
                    elif selected == 2:
                        idx = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
                        _gs.difficulty = _gs.DIFFICULTIES[(idx + 1) % len(_gs.DIFFICULTIES)]
                    elif selected == 4:
                        _gs.head_bobbing = not _gs.head_bobbing
                    elif selected == 5:
                        _gs.camera_shake = not _gs.camera_shake
                    elif selected == 6:
                        _gs.photosensitivity_mode = not _gs.photosensitivity_mode
                    elif selected == 7:
                        _gs.invert_mouse_y = not _gs.invert_mouse_y
                if event.key == K_UP:
                    selected = (selected - 1) % num_items
                if event.key == K_DOWN:
                    selected = (selected + 1) % num_items
                if event.key == K_LEFT:
                    if selected == 0: vol = max(0.0, vol - 0.1)
                    elif selected == 1: sens = max(1.0, sens - 1.0)
                    elif selected == 2:
                        idx = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
                        _gs.difficulty = _gs.DIFFICULTIES[(idx - 1) % len(_gs.DIFFICULTIES)]
                    elif selected == 3:
                        _gs.fov = max(60.0, _gs.fov - 5.0)
                    elif selected == 4: _gs.head_bobbing = not _gs.head_bobbing
                    elif selected == 5: _gs.camera_shake = not _gs.camera_shake
                    elif selected == 6: _gs.photosensitivity_mode = not _gs.photosensitivity_mode
                    elif selected == 7: _gs.invert_mouse_y = not _gs.invert_mouse_y
                if event.key == K_RIGHT:
                    if selected == 0: vol = min(2.0, vol + 0.1)
                    elif selected == 1: sens = min(10.0, sens + 1.0)
                    elif selected == 2:
                        idx = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
                        _gs.difficulty = _gs.DIFFICULTIES[(idx + 1) % len(_gs.DIFFICULTIES)]
                    elif selected == 3:
                        _gs.fov = min(95.0, _gs.fov + 5.0)
                    elif selected == 4: _gs.head_bobbing = not _gs.head_bobbing
                    elif selected == 5: _gs.camera_shake = not _gs.camera_shake
                    elif selected == 6: _gs.photosensitivity_mode = not _gs.photosensitivity_mode
                    elif selected == 7: _gs.invert_mouse_y = not _gs.invert_mouse_y

        canvas.fill((10, 10, 16))
        title = "CONFIGURACOES & ACESSIBILIDADE"
        t = title_font.render(title, True, (170, 170, 180))
        canvas.blit(t, t.get_rect(center=(DISPLAY_SIZE[0]//2, 75)))

        diff_data = _gs.DIFFICULTY_PRESETS.get(_gs.difficulty, {})
        diff_str = f"{diff_data.get('label', _gs.difficulty)} ({diff_data.get('desc', '')})"

        items = [
            f"Volume Geral: {int(vol * 100)}%",
            f"Sensibilidade Mouse: {int(sens)}",
            f"Dificuldade: {diff_str}",
            f"Campo de Visao (FOV): {int(_gs.fov)}°",
            f"Balanco de Camera (Bobbing): {'Ligado' if _gs.head_bobbing else 'Desligado'}",
            f"Tremores de Camera (Shake): {'Ligado' if _gs.camera_shake else 'Desligado'}",
            f"Fotosensibilidade (Sem Flashes): {'Ligado' if _gs.photosensitivity_mode else 'Desligado'}",
            f"Inverter Eixo Y: {'Sim' if _gs.invert_mouse_y else 'Nao'}",
            "Voltar ao Menu Principal" if not is_pause else "Retomar Jogo"
        ]

        start_y = 150
        spacing = 46
        for i, text in enumerate(items):
            color = (255, 255, 80) if i == selected else (175, 175, 175)
            prefix = "> " if i == selected else "  "
            surf = opt_font.render(prefix + text, True, color)
            canvas.blit(surf, surf.get_rect(center=(DISPLAY_SIZE[0]//2, start_y + i * spacing)))

        hint = hint_font.render("[ESQ/DIR ou ENTER] Ajustar  |  [SETAS CIMA/BAIXO] Navegar  |  ESC Voltar",
                                True, (120, 120, 120))
        canvas.blit(hint, hint.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1] - 40)))

        render_surface_to_opengl(canvas)


def run_end_screen(screen, font, title_font, stats=None):
    new_recs = {}
    if stats:
        run_time, dist, jumpscares, peak_anx, batts = stats
        new_recs = _gs.record_game_completion(run_time, dist, jumpscares, peak_anx, _gs.difficulty, batts)
    else:
        _gs.completion_count += 1
        _gs.save_save_data()
    cc = _gs.completion_count

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
    bg_color = (min(20 + cc * 20, 200), max(8 - cc, 2), max(10 - cc, 2))

    clock = pygame.time.Clock()
    canvas = pygame.Surface(DISPLAY_SIZE)
    _fade_result = None
    _fade_alpha = 0
    while True:
        dt = clock.tick(60) / 1000.0
        dt_step = min(dt, 0.1) * 60.0
        if _fade_result and _fade_alpha >= 255:
            return _fade_result

        for event in pygame.event.get():
            if event.type == QUIT: return "QUIT"
            if event.type == KEYDOWN and not _fade_result:
                if event.key == K_RETURN: _fade_result = "MENU"
                if event.key == K_ESCAPE: return "QUIT"

        canvas.fill(bg_color)

        if cc >= 3:
            ox = random.randint(-cc, cc)
            oy = random.randint(-cc, cc)
        else:
            ox, oy = 0, 0

        title_color = (min(20 + cc * 30, 255), max(40 - cc * 5, 0), max(60 - cc * 8, 0))
        title_text = title_font.render("VOCÊ ESCAPOU", True, title_color)
        title_rect = title_text.get_rect(center=(DISPLAY_SIZE[0]//2 + ox, DISPLAY_SIZE[1]//2 - 60 + oy))
        canvas.blit(title_text, title_rect)

        count_color = (180, 20, 20) if cc >= 2 else (100, 100, 100)
        count_text = font.render(f"Vezes que escapou: {cc}", True, count_color)
        count_rect = count_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 10))
        canvas.blit(count_text, count_rect)

        if stats:
            run_time, dist, jumpscares, peak_anx, batts = stats
            s0 = font.render(f"Tempo: {int(run_time//60)}m {int(run_time%60):02d}s", True, (130, 130, 130))
            s1 = font.render(f"Distância: {dist:.1f} m", True, (130, 130, 130))
            s2 = font.render(f"Jumpscares: {jumpscares}", True, (130, 130, 130))
            s3 = font.render(f"Pico de Ansiedade: {int(peak_anx*100)}%", True, (130, 130, 130))
            s4 = font.render(f"Baterias Coletadas: {batts}", True, (80, 220, 150))
            canvas.blit(s0, s0.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 40)))
            canvas.blit(s1, s1.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 65)))
            canvas.blit(s2, s2.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 90)))
            canvas.blit(s3, s3.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 115)))
            canvas.blit(s4, s4.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 140)))
            if new_recs.get("best_time") or new_recs.get("diff_best_time"):
                rec_alert = font.render("★ NOVO RECORDE DE TEMPO! ★", True, (255, 220, 70))
                canvas.blit(rec_alert, rec_alert.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 170)))

        start_text = font.render(sub_msg, True, (200, 200, 200))
        start_rect = start_text.get_rect(center=(DISPLAY_SIZE[0]//2, DISPLAY_SIZE[1]//2 + 210))
        canvas.blit(start_text, start_rect)

        if _fade_result:
            _fade_alpha = min(255, _fade_alpha + int(round(17 * dt_step)))
            _fade_surf = pygame.Surface(DISPLAY_SIZE)
            _fade_surf.fill((0, 0, 0))
            _fade_surf.set_alpha(_fade_alpha)
            canvas.blit(_fade_surf, (0, 0))

        render_surface_to_opengl(canvas)

def run_game():
    global maze_map, MAP_WIDTH, MAP_HEIGHT
    diff_key = _gs.difficulty if _gs.difficulty in _gs.DIFFICULTY_PRESETS else "NORMAL"
    diff_cfg = _gs.DIFFICULTY_PRESETS[diff_key]
    mw, mh = diff_cfg["maze_size"]
    maze_map, MAP_WIDTH, MAP_HEIGHT = generate_maze(mw, mh)
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
    gluPerspective(_gs.fov, (DISPLAY_SIZE[0] / DISPLAY_SIZE[1]), 0.1, 80.0)
    glMatrixMode(GL_MODELVIEW)

    glEnable(GL_DEPTH_TEST)
    fog_color = setup_fog()
    setup_lighting()

    tex_hedge = load_texture(tex("hedge.png"))
    tex_snow  = load_texture(tex("snow.png"))
    tex_skybox = load_texture(tex("skybox.png"))

    if tex_hedge and tex_snow:
        glEnable(GL_TEXTURE_2D)

    # Compila labirinto em chunks espaciais otimizados (Hidden-Face Removal + Frustum Culling)
    maze_chunks = build_maze_chunks(tex_hedge, maze_map, MAP_WIDTH, MAP_HEIGHT, chunk_size=5)

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
    tex_jack   = load_texture(tex("jack.png"))

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
    battery_toast_tex = create_text_texture("+45% BATERIA RECARREGADA", color=(80, 255, 160), font_size=28)
    
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
    max_camps = diff_cfg.get("num_campfires", 10)
    for cx, cy in free_cells[:max_camps]:
        wx = (cx - MAP_WIDTH/2) * BLOCK_SIZE
        wz = (cy - MAP_HEIGHT/2) * BLOCK_SIZE
        campfires.append((wx, wz))

    # ---- Gerar Teto Sangrento (Zonas de Gotejamento) ----
    blood_drip_zones = []
    # O terror aumenta progressivamente: Chuva de sangue apenas a partir da 3ª Fase
    if _gs.completion_count >= 2:
        drip_cells = free_cells[max_camps:max_camps + 6]
        for cx, cy in drip_cells:
            blood_drip_zones.append((cx - MAP_WIDTH/2, cy - MAP_HEIGHT/2))

    # ---- Baterias Coletáveis Espalhadas pelo Labirinto (Pickups 3D) ----
    battery_pickups = []
    num_batteries = 8 if diff_key == "FACIL" else (6 if diff_key == "NORMAL" else 4)
    bat_candidates = [
        (x, y) for (x, y) in free_cells[max_camps + 6:]
        if not (x <= 3 and y <= 3) and abs(x - exit_grid[0]) + abs(y - exit_grid[1]) > 4
    ]
    if not bat_candidates:
        bat_candidates = [
            (x, y) for (x, y) in free_cells
            if not (x <= 3 and y <= 3) and abs(x - exit_grid[0]) + abs(y - exit_grid[1]) > 4
        ]
    random.shuffle(bat_candidates)
    for bx, by in bat_candidates[:num_batteries]:
        bwx = (bx - MAP_WIDTH / 2.0) * BLOCK_SIZE
        bwz = (by - MAP_HEIGHT / 2.0) * BLOCK_SIZE
        battery_pickups.append({'pos': (bwx, bwz), 'collected': False})
    stat_batteries_collected = 0
    battery_toast_timer_ms = 0

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
    flashlight_on    = True
    battery          = 1.0
    drain_mult       = diff_cfg.get("drain_mult", 1.0)
    BATT_DRAIN_RATE  = 0.00022 * drain_mult   # ~75s de uso contínuo da lanterna
    batt_warning_played = False  # já tocou aviso de bateria fraca
    try:
        click_snd = pygame.mixer.Sound(snd("click.wav"))
        click_snd.set_volume(min(1.0, 0.8 * vol_mult))
    except Exception as e:
        print(f"Click: {e}")
        click_snd = None

    try:
        battery_snd = pygame.mixer.Sound(snd("battery.wav"))
        battery_snd.set_volume(min(1.0, 0.8 * vol_mult))
    except Exception as e:
        print(f"Battery snd: {e}")
        battery_snd = None

    # ---- Jack Perseguidor ----
    # Começa no canto oposto ao jogador
    jack_pos = (MAP_WIDTH - 3, MAP_HEIGHT - 3)
    # Garante que não está em parede
    while maze_map[jack_pos[1]][jack_pos[0]] == 1 and jack_pos[0] > 1:
        jack_pos = (jack_pos[0] - 1, jack_pos[1])
    base_jack_interval = diff_cfg.get("jack_interval", 320) * 10
    jack_move_interval = max(1000, base_jack_interval - int(madness * 1500))  # ms entre movimentos
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
    for fname in ["jumpscare_jack.png", "jumpscare_twins.png", "jumpscare_bug.png"]:
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
    current_js_tex     = None
    # Tipo de efeito extra para cada jumpscare (0=normal,1=flash,2=glitch,3=negativo)
    js_effect_type     = 0

    # ---- Fôlego e Stamina ----
    stamina          = 1.0     # [0.0..1.0] Fôlego para corrida contínua
    is_fatigued      = False   # Verdadeiro temporariamente quando esgota o fôlego

    # ---- Ansiedade e Terror Psicológico ----
    anxiety          = 0.0     # [0.0..1.0] Medo e taquicardia
    ANXIETY_RISE     = 0.0018  # Reatividade mais perceptível na escuridão
    ANXIETY_FALL     = 0.0015  # Alívio visível ao descansar ou em fogueiras
    BASE_SPEED       = 0.10    # Velocidade base de caminhada natural

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
            dt = clock.tick(60) / 1000.0
            dt = min(dt, 0.1)
            dt_step = dt * 60.0
            now_ms = pygame.time.get_ticks()
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
                            _gs.save_save_data()
                        elif paused:
                            paused = False
                            pygame.mouse.set_visible(False)
                            pygame.event.set_grab(True)
                            pygame.mouse.get_rel()
                        else:
                            paused = True
                            pause_selected = 0
                            pause_exiting = False
                            pygame.mouse.set_visible(True)
                            pygame.event.set_grab(False)
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
                                        jumpscare_start_ms = now_ms
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
                    elif event.key == K_f and not paused and not jumpscare_active:
                        flashlight_on = not flashlight_on
                        if click_snd:
                            click_snd.play()
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
                            pause_settings_sel = (pause_settings_sel - 1) % 9
                        elif event.key == K_DOWN:
                            pause_settings_sel = (pause_settings_sel + 1) % 9
                        elif event.key == K_LEFT:
                            if pause_settings_sel == 0:
                                pause_vol = max(0.0, pause_vol - 0.1)
                                _gs.master_volume = pause_vol
                            elif pause_settings_sel == 1:
                                pause_sens = max(1.0, pause_sens - 1.0)
                                _gs.mouse_sensitivity = pause_sens / 1000.0
                                mouse_sensitivity = _gs.mouse_sensitivity
                            elif pause_settings_sel == 2:
                                idx = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
                                _gs.difficulty = _gs.DIFFICULTIES[(idx - 1) % len(_gs.DIFFICULTIES)]
                            elif pause_settings_sel == 3:
                                _gs.fov = max(60.0, _gs.fov - 5.0)
                                glMatrixMode(GL_PROJECTION); glLoadIdentity()
                                gluPerspective(_gs.fov, (DISPLAY_SIZE[0] / DISPLAY_SIZE[1]), 0.1, 80.0)
                                glMatrixMode(GL_MODELVIEW)
                            elif pause_settings_sel == 4:
                                _gs.head_bobbing = not _gs.head_bobbing
                            elif pause_settings_sel == 5:
                                _gs.camera_shake = not _gs.camera_shake
                            elif pause_settings_sel == 6:
                                _gs.photosensitivity_mode = not _gs.photosensitivity_mode
                            elif pause_settings_sel == 7:
                                _gs.invert_mouse_y = not _gs.invert_mouse_y
                        elif event.key == K_RIGHT:
                            if pause_settings_sel == 0:
                                pause_vol = min(2.0, pause_vol + 0.1)
                                _gs.master_volume = pause_vol
                            elif pause_settings_sel == 1:
                                pause_sens = min(10.0, pause_sens + 1.0)
                                _gs.mouse_sensitivity = pause_sens / 1000.0
                                mouse_sensitivity = _gs.mouse_sensitivity
                            elif pause_settings_sel == 2:
                                idx = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
                                _gs.difficulty = _gs.DIFFICULTIES[(idx + 1) % len(_gs.DIFFICULTIES)]
                            elif pause_settings_sel == 3:
                                _gs.fov = min(95.0, _gs.fov + 5.0)
                                glMatrixMode(GL_PROJECTION); glLoadIdentity()
                                gluPerspective(_gs.fov, (DISPLAY_SIZE[0] / DISPLAY_SIZE[1]), 0.1, 80.0)
                                glMatrixMode(GL_MODELVIEW)
                            elif pause_settings_sel == 4:
                                _gs.head_bobbing = not _gs.head_bobbing
                            elif pause_settings_sel == 5:
                                _gs.camera_shake = not _gs.camera_shake
                            elif pause_settings_sel == 6:
                                _gs.photosensitivity_mode = not _gs.photosensitivity_mode
                            elif pause_settings_sel == 7:
                                _gs.invert_mouse_y = not _gs.invert_mouse_y
                        elif event.key in (K_RETURN, K_SPACE):
                            if pause_settings_sel == 8:
                                _gs.master_volume = pause_vol
                                _gs.mouse_sensitivity = pause_sens / 1000.0
                                mouse_sensitivity = _gs.mouse_sensitivity
                                pause_in_settings = False
                            elif pause_settings_sel == 2:
                                idx = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
                                _gs.difficulty = _gs.DIFFICULTIES[(idx + 1) % len(_gs.DIFFICULTIES)]
                            elif pause_settings_sel == 4:
                                _gs.head_bobbing = not _gs.head_bobbing
                            elif pause_settings_sel == 5:
                                _gs.camera_shake = not _gs.camera_shake
                            elif pause_settings_sel == 6:
                                _gs.photosensitivity_mode = not _gs.photosensitivity_mode
                            elif pause_settings_sel == 7:
                                _gs.invert_mouse_y = not _gs.invert_mouse_y
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
                draw_floor(tex_snow, MAP_WIDTH, MAP_HEIGHT)
                draw_maze_optimized(maze_chunks, (player_pos[0], player_pos[1] + bob_offset, player_pos[2]), max_dist=60.0)
                draw_exit(maze_map, MAP_WIDTH, MAP_HEIGHT)
                draw_pause_overlay(pause_selected, pause_in_settings,
                                   pause_vol, pause_sens, pause_settings_sel)
                # Fade-out ao selecionar "Sair ao Menu"
                if pause_exiting:
                    pause_exit_alpha = min(255, pause_exit_alpha + int(round(17 * dt_step)))
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
                continue

            dx, dy = pygame.mouse.get_rel()
            yaw += dx * mouse_sensitivity
            dy_eff = dy if _gs.invert_mouse_y else -dy
            pitch += dy_eff * mouse_sensitivity
            pitch = max(-math.pi/2 + 0.1, min(math.pi/2 - 0.1, pitch))

            front_x = math.cos(yaw)
            front_z = math.sin(yaw)
            right_x = math.cos(yaw + math.pi/2)
            right_z = math.sin(yaw + math.pi/2)

            keys = pygame.key.get_pressed()
            new_x = player_pos[0]
            new_z = player_pos[2]

            # ---- Sistema de Movimentação e Stamina (Fôlego) ----
            shift_pressed = keys[pygame.K_LSHIFT] or keys[pygame.K_RSHIFT]
            moving_input  = (keys[pygame.K_w] or keys[pygame.K_UP] or
                             keys[pygame.K_s] or keys[pygame.K_DOWN] or
                             keys[pygame.K_a] or keys[pygame.K_LEFT] or
                             keys[pygame.K_d] or keys[pygame.K_RIGHT])

            # Recuperação de fadiga
            if stamina <= 0.04:
                is_fatigued = True
            elif stamina >= 0.25:
                is_fatigued = False

            sprinting = shift_pressed and moving_input and not is_fatigued and stamina > 0.05
            speed_mult = 1.65 if sprinting else (0.85 if is_fatigued else 1.0)

            # Efeito de hipotermia na agilidade (não congela o jogador)
            if hypothermia > 0.65:
                speed_mult *= max(0.70, 1.0 - (hypothermia - 0.65) * 0.70)

            effective_speed = BASE_SPEED * speed_mult * dt_step

            is_moving = False
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                new_x += front_x * effective_speed; new_z += front_z * effective_speed; is_moving = True
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                new_x -= front_x * effective_speed; new_z -= front_z * effective_speed; is_moving = True
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                new_x -= right_x * effective_speed; new_z -= right_z * effective_speed; is_moving = True
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                new_x += right_x * effective_speed; new_z += right_z * effective_speed; is_moving = True

            # Drenagem e regeneração contínua de Stamina
            if sprinting and is_moving:
                stamina = max(0.0, stamina - 0.0038 * dt_step)  # ~4.4s de corrida contínua
            else:
                recover_rate = 0.0033 if is_moving else 0.0055  # recupera em ~5s andando ou ~3s parado
                stamina = min(1.0, stamina + recover_rate * dt_step)

            # ---- Sistema de Ansiedade e Pânico ----
            # 1. Recuperação em repouso com lanterna acesa
            if not is_moving and flashlight_on:
                anxiety = max(0.0, anxiety - ANXIETY_FALL * 0.9 * dt_step)

            # 2. Escuridão total (lanterna apagada) causa aumento nítido e progressivo de medo
            if not flashlight_on:
                anxiety = min(1.0, anxiety + ANXIETY_RISE * 1.1 * dt_step)

            # 3. Corrida consome fôlego e eleva a frequência cardíaca
            if sprinting:
                anxiety = min(1.0, anxiety + ANXIETY_RISE * 0.5 * dt_step)

            # 4. Pico de Pânico (Substitui o congelamento por adrenalina e taquicardia)
            in_panic = anxiety >= 0.85
            if anxiety >= 1.0:
                shake_trauma = min(1.0, shake_trauma + 0.65)
                if heartbeat_snd:
                    heartbeat_snd.set_volume(min(1.0, 1.0 * vol_mult))
                    heartbeat_snd.play()
                anxiety = 0.75  # Recua para 75% mantendo o ritmo cardíaco intenso sem travar controles

            stat_peak_anxiety = max(stat_peak_anxiety, anxiety)

            # ---- Lanterna com Bateria ----
            if flashlight_on:
                battery = max(0.0, battery - BATT_DRAIN_RATE * dt_step)

            # ---- Lógica de Nevasca e Hipotermia ----
            if not blizzard_active and now_ms >= next_blizzard_ms:
                blizzard_active = True
                blizzard_end_ms = now_ms + random.randint(15000, 25000)
            
            if blizzard_active:
                blizzard_intensity = min(1.0, blizzard_intensity + 0.003 * dt_step)
                if now_ms >= blizzard_end_ms:
                    blizzard_active = False
                    next_blizzard_ms = now_ms + random.randint(35000, 60000)
            else:
                blizzard_intensity = max(0.0, blizzard_intensity - 0.002 * dt_step)
                
            current_fog = 0.09 + (0.26 * blizzard_intensity)
            glFogf(GL_FOG_DENSITY, current_fog)

            near_campfire = False
            for fx, fz in campfires:
                if math.dist([player_pos[0], player_pos[2]], [fx, fz]) < BLOCK_SIZE * 2.0:
                    near_campfire = True
                    break
                    
            freeze_mult = diff_cfg.get("freeze_mult", 1.0)
            if blizzard_active and blizzard_intensity > 0.5:
                if near_campfire:
                    hypothermia = max(0.0, hypothermia - 0.01 * dt_step)
                    anxiety = max(0.0, anxiety - 0.005 * dt_step)
                else:
                    hypothermia = min(1.0, hypothermia + 0.001 * freeze_mult * dt_step)
                    if flashlight_on:
                        battery = max(0.0, battery - BATT_DRAIN_RATE * 1.6 * dt_step) # Bateria drena mais rápido no frio
            else:
                if near_campfire:
                    hypothermia = max(0.0, hypothermia - 0.01 * dt_step)
                    anxiety = max(0.0, anxiety - 0.005 * dt_step)
                else:
                    hypothermia = max(0.0, hypothermia - 0.0005 * dt_step)

            if hypothermia >= 1.0 and not jumpscare_active:
                jumpscare_active = True
                jumpscare_start_ms = now_ms
                current_js_tex = random.choice(jumpscare_textures) if jumpscare_textures else None
                js_effect_type = 3 # Efeito negativo para frio
                anxiety = 1.0
                hypothermia = 0.5 # Reseta metade para dar uma chance

            # ---- Lógica de Teto Sangrento ----
            if blood_overlay_timer > 0:
                blood_overlay_timer -= dt * 1000.0

                
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
                if drip_snd and blood_drip_zones:
                    closest_drip = min(blood_drip_zones, key=lambda z: math.hypot(player_pos[0] - z[0]*BLOCK_SIZE, player_pos[2] - z[1]*BLOCK_SIZE))
                    dl, dr = calc_3d_spatial_volume(player_pos[0], player_pos[2], yaw,
                                                    closest_drip[0] * BLOCK_SIZE, closest_drip[1] * BLOCK_SIZE,
                                                    max_dist=12.0, base_vol=0.75 * vol_mult)
                    dch = pygame.mixer.find_channel()
                    if dch:
                        dch.set_volume(dl, dr)
                        dch.play(drip_snd)
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

                is_illuminated = flashlight_on and is_looking and battery > 0.02 and now_ms > flicker_off_until
                if fj_dist < BLOCK_SIZE * 3 or (is_illuminated and fj_dist < BLOCK_SIZE * 15 and now_ms > fj['spawn_ms'] + 500):
                    # Falso Jack desaparece
                    anxiety = min(1.0, anxiety + 0.15)
                else:
                    kept_fake_jacks.append(fj)
            fake_jacks = kept_fake_jacks

            # ---- Coleta de Baterias 3D ----
            for b in battery_pickups:
                if not b['collected']:
                    dist_b = math.hypot(player_pos[0] - b['pos'][0], player_pos[2] - b['pos'][1])
                    if dist_b < BLOCK_SIZE * 0.75:
                        b['collected'] = True
                        battery = min(1.0, battery + 0.45)
                        anxiety = max(0.0, anxiety - 0.20)
                        stat_batteries_collected += 1
                        battery_toast_timer_ms = now_ms + 2500
                        if battery_snd:
                            battery_snd.play()

            # ---- Movimentação do Inimigo (BFS Dinâmico) ----
            edx = player_pos[0] - exit_pos[0]
            edz = player_pos[2] - exit_pos[1]
            dist_exit = math.sqrt(edx * edx + edz * edz)

            # ---- Jack Perseguidor ----
            player_grid = (int(math.floor(player_pos[0] / BLOCK_SIZE + MAP_WIDTH / 2.0 + 0.5)),
                           int(math.floor(player_pos[2] / BLOCK_SIZE + MAP_HEIGHT / 2.0 + 0.5)))
            
            # Resolução de Bloqueio da IA na Saída (Modo FLEE vs CHASE)
            EXIT_ZONE_DIST = BLOCK_SIZE * 6.5
            player_in_exit_zone = dist_exit < EXIT_ZONE_DIST

            if now_ms >= next_jack_move_ms:
                if player_in_exit_zone:
                    # Modo FLEE: Jack recua em direção ao ponto mais distante da saída
                    corner_a = (1, 1)
                    corner_b = (MAP_WIDTH - 3, MAP_HEIGHT - 3)
                    dist_a = abs(exit_grid[0] - corner_a[0]) + abs(exit_grid[1] - corner_a[1])
                    dist_b = abs(exit_grid[0] - corner_b[0]) + abs(exit_grid[1] - corner_b[1])
                    retreat_goal = corner_a if dist_a > dist_b else corner_b
                    
                    next_step = bfs_next_step(maze_map, MAP_WIDTH, MAP_HEIGHT, jack_pos, retreat_goal)
                    if next_step:
                        jack_pos = next_step
                    next_jack_move_ms = now_ms + int(jack_move_interval * 0.75)
                else:
                    # Modo CHASE: Persegue o jogador via BFS
                    next_step = bfs_next_step(maze_map, MAP_WIDTH, MAP_HEIGHT, jack_pos, player_grid)
                    if next_step:
                        jack_pos = next_step
                    next_jack_move_ms = now_ms + jack_move_interval

            jack_wx = (jack_pos[0] - MAP_WIDTH  / 2) * BLOCK_SIZE
            jack_wz = (jack_pos[1] - MAP_HEIGHT / 2) * BLOCK_SIZE
            jack_dist = math.sqrt((player_pos[0]-jack_wx)**2 + (player_pos[2]-jack_wz)**2)

            # Terror psicológico: ansiedade sobe progressivamente com a proximidade do Jack
            if jack_dist < BLOCK_SIZE * 7.0 and not player_in_exit_zone:
                prox = 1.0 - (jack_dist / (BLOCK_SIZE * 7.0))
                anxiety = min(1.0, anxiety + (0.0005 + 0.0020 * (prox ** 2)) * dt_step)

            # Passos do Jack (espacialização 3D real com atenuação e panning)
            if jack_ch:
                jl, jr = calc_3d_spatial_volume(player_pos[0], player_pos[2], yaw,
                                                jack_wx, jack_wz,
                                                max_dist=18.0, base_vol=0.75 * vol_mult)
                jack_ch.set_volume(jl, jr)

            # Interação do Jack com o jogador
            if player_in_exit_zone:
                # Se o jogador estiver na zona de saída e o Jack se aproximar, Jack se dissipa na névoa e é expulso para o fundo do labirinto
                if jack_dist < BLOCK_SIZE * 2.5:
                    corner_a = (1, 1)
                    corner_b = (MAP_WIDTH - 3, MAP_HEIGHT - 3)
                    dist_a = abs(exit_grid[0] - corner_a[0]) + abs(exit_grid[1] - corner_a[1])
                    dist_b = abs(exit_grid[0] - corner_b[0]) + abs(exit_grid[1] - corner_b[1])
                    jack_pos = corner_a if dist_a > dist_b else corner_b
                    next_jack_move_ms = now_ms + 12000
            else:
                # Jack captura o jogador fora da zona de saída
                if jack_dist < BLOCK_SIZE * 1.8 and not jumpscare_active and not in_panic:
                    jumpscare_active   = True
                    jumpscare_start_ms = now_ms
                    current_js_tex     = random.choice(jumpscare_textures)
                    js_effect_type     = random.choice([0, 1, 2, 3]) if madness > 0.4 else 1
                    if grito_snd: grito_snd.play()
                    anxiety = min(1.0, anxiety + 0.5)  # Sobe ansiedade sem forçar 1.0 direto
                    # Reinicia Jack longe
                    jack_pos = (MAP_WIDTH - 3, MAP_HEIGHT - 3)
                    next_jack_move_ms = now_ms + 18000  # Mais tempo antes de voltar

            # Jack imita respiração/sussurro se estiver perto mas não atacando (3D espacializado)
            if 3.0 * BLOCK_SIZE < jack_dist < 10.0 * BLOCK_SIZE and random.random() < 0.005 and whisper_snds:
                try:
                    s = random.choice(whisper_snds)
                    wl, wr = calc_3d_spatial_volume(player_pos[0], player_pos[2], yaw,
                                                    jack_wx, jack_wz,
                                                    max_dist=12.0, base_vol=0.85 * vol_mult)
                    wch = pygame.mixer.find_channel()
                    if wch:
                        wch.set_volume(wl, wr)
                        wch.play(s)
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
            cur_cell = (int(math.floor((player_pos[0] / BLOCK_SIZE) + MAP_WIDTH / 2.0 + 0.5)),
                        int(math.floor((player_pos[2] / BLOCK_SIZE) + MAP_HEIGHT / 2.0 + 0.5)))
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

            # ---- Piscar de tela (cc >= 3, desativado no modo fotossensibilidade) ----
            if cc >= 3 and not _gs.photosensitivity_mode:
                if not blink_active and now_ms >= next_blink_ms and not jumpscare_active:
                    blink_active   = True
                    blink_until_ms = now_ms + random.randint(100, 250)
                    next_blink_ms  = now_ms + random.randint(25000, 55000)
                if blink_active and now_ms >= blink_until_ms:
                    blink_active = False
            else:
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
            if not flashlight_on or battery <= 0.02 or now_ms < flicker_off_until:
                flicker_val = 0.0
            elif _gs.photosensitivity_mode:
                # Iluminação constante e suave para evitar crises e estresse visual
                flicker_val = max(0.2, batt_factor)
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

            eff = flicker_val if flashlight_on else 0.0
            glLightfv(GL_LIGHT0, GL_DIFFUSE,
                      (2.2 * eff, 2.15 * eff, 2.35 * eff, 1.0))
            glLightfv(GL_LIGHT0, GL_SPECULAR,
                      (1.2 * eff, 1.2 * eff, 1.3 * eff, 1.0))
            glLightfv(GL_LIGHT1, GL_DIFFUSE,
                      (0.06 * eff, 0.06 * eff, 0.08 * eff, 1.0))

            # ---- Camera Shake + Tontura ----
            shake_trauma = max(0.0, shake_trauma - 0.03 * dt_step)
            # Trauma extra vindo da ansiedade alta
            if anxiety > 0.5:
                shake_trauma = max(shake_trauma, (anxiety - 0.5) * 0.4)
            shake_amp   = (shake_trauma * shake_trauma) if _gs.camera_shake else 0.0
            shake_yaw   = shake_amp * (
                math.sin(t_s * 23.1) * 0.018 + math.sin(t_s * 47.3) * 0.009)
            shake_pitch = shake_amp * (
                math.sin(t_s * 19.7) * 0.012 + math.sin(t_s * 37.1) * 0.006)
            # Tontura: oscilação lenta e ampla no yaw e pitch
            if dizzy_active and _gs.camera_shake:
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
                bob_time += (0.25 + anxiety * 0.15) * dt_step
                if math.floor(bob_time / math.pi) > math.floor(last_step_bob / math.pi):
                    if footstep_snd:
                        footstep_snd.set_volume(min(1.0, (0.01 + anxiety * 0.04) * _gs.master_volume))
                        footstep_snd.play()
                last_step_bob = bob_time
            else:
                # Dispara "passo extra" se o jogador acabou de parar
                if was_moving and madness > 0.1:
                    fake_echoes.append(now_ms + random.randint(200, 500))
                bob_time += (0 - bob_time) * min(1.0, 0.1 * dt_step)
                last_step_bob = bob_time

            was_moving = is_moving
            bob_offset = (math.sin(bob_time) * 0.05) if _gs.head_bobbing else 0.0

            # ---- Registra pegada a cada "passo" (semi-período do bobbing) ----
            maybe_add_footprint(player_pos[0], player_pos[2], yaw, is_moving)

            # ---- Física de Som Espacial 3D ----
            if hum_ch is not None:
                hl, hr = calc_3d_spatial_volume(player_pos[0], player_pos[2], yaw,
                                                exit_pos[0], exit_pos[1],
                                                max_dist=22.0, base_vol=0.75)
                hum_ch.set_volume(hl, hr)
            # Panning do vento: usa o ângulo relativo entre frente do jogador e saída
            if wind_ch is not None:
                ang = math.atan2(-edz, -edx) - yaw  # Ângulo relativo
                pan = math.sin(ang)                  # -1 (esq) a +1 (dir)
                wind_base = (0.3 + 0.5 * blizzard_intensity) * _gs.master_volume
                theta_w = (max(-1.0, min(1.0, pan)) + 1.0) * (math.pi / 4.0)
                wind_ch.set_volume(min(1.0, wind_base * math.cos(theta_w)),
                                   min(1.0, wind_base * math.sin(theta_w))) 
            
            # ---- Detecção de saída por proximidade (sempre ativa) ----
            if dist_exit < EXIT_REACH:
                pygame.mixer.stop()
                run_time = (pygame.time.get_ticks() - run_start_ms) / 1000.0
                return ("END", run_time, stat_distance, stat_jumpscares, stat_peak_anxiety, stat_batteries_collected)

            # ---- Redução de efeitos perto da saída ----
            # Perto da saída, aliviar ansiedade para evitar soft-lock
            if dist_exit < BLOCK_SIZE * 5:
                exit_relief = 1.0 - (dist_exit / (BLOCK_SIZE * 5))
                anxiety = max(0.0, anxiety - ANXIETY_FALL * (1 + exit_relief * 5))

            old_x, old_z = player_pos[0], player_pos[2]

            col_x = check_collision(new_x, player_pos[2], radius=0.35)
            if col_x == "EXIT":
                pygame.mixer.stop()
                run_time = (pygame.time.get_ticks() - run_start_ms) / 1000.0
                return ("END", run_time, stat_distance, stat_jumpscares, stat_peak_anxiety, stat_batteries_collected)
            elif not col_x:
                player_pos[0] = new_x

            col_z = check_collision(player_pos[0], new_z, radius=0.35)
            if col_z == "EXIT":
                pygame.mixer.stop()
                run_time = (pygame.time.get_ticks() - run_start_ms) / 1000.0
                return ("END", run_time, stat_distance, stat_jumpscares, stat_peak_anxiety, stat_batteries_collected)
            elif not col_z:
                player_pos[2] = new_z
            
            stat_distance += math.hypot(player_pos[0] - old_x, player_pos[2] - old_z)

            look_x = player_pos[0] + math.cos(pitch + shake_pitch) * math.cos(yaw + shake_yaw)
            look_y = player_pos[1] + math.sin(pitch + shake_pitch)
            look_z = player_pos[2] + math.cos(pitch + shake_pitch) * math.sin(yaw + shake_yaw)

            glClearColor(*fog_color) 
            glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
            glLoadIdentity()
            
            # Posiciona a Câmera (com shake aplicado no look target)
            cam_pos = (player_pos[0], player_pos[1] + bob_offset, player_pos[2])
            look_target = (look_x, look_y + bob_offset, look_z)
            gluLookAt(cam_pos[0], cam_pos[1], cam_pos[2],
                      look_target[0], look_target[1], look_target[2],
                      0, 1, 0)

            # Iluminação posicionada no espaço de visão da câmera
            look_dir = (look_x - player_pos[0], look_y - player_pos[1], look_z - player_pos[2])
            glLightfv(GL_LIGHT0, GL_POSITION, (cam_pos[0], cam_pos[1], cam_pos[2], 1.0))
            glLightfv(GL_LIGHT0, GL_SPOT_DIRECTION, look_dir)
            glLightfv(GL_LIGHT1, GL_POSITION, (player_pos[0], player_pos[1] - 0.4, player_pos[2], 1.0))

            # 1. Desenha o Skybox no fundo de tudo
            draw_skybox(tex_skybox, player_pos[0], player_pos[1], player_pos[2])

            # 2. Desenha o chão de neve contínuo
            draw_floor(tex_snow, MAP_WIDTH, MAP_HEIGHT)

            # 3. Renderiza o labirinto otimizado com Frustum Culling e Hidden Face Removal
            draw_maze_optimized(maze_chunks, cam_pos, max_dist=60.0)
            draw_blood_trails(blood_decals)
            for c in corpses:
                draw_corpse(tex_corpse, c['pos'][0], c['pos'][1])
            draw_footprints()

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

            # 4b. Pickups 3D de Bateria
            for b in battery_pickups:
                if not b['collected']:
                    draw_battery_pickup(b['pos'][0], b['pos'][1], now_ms)

            # Cone volumétrico e feixes de luz da lanterna (Spotlight + Shafts)
            draw_flashlight_volumetric_shaft(cam_pos, look_dir, eff, blizzard_intensity)

            # 3. Desenha o Jack (e os Falsos Jacks) com Billboard 3D e sombra projetada
            draw_jack_shadow(jack_wx, jack_wz, jack_dist, madness)
            draw_jack_billboard(tex_jack, jack_wx, jack_wz, player_pos[0], player_pos[2], jack_dist, madness, now_ms, is_fake=False)
            for fj in fake_jacks:
                fj_wx, fj_wz = fj['pos']
                fj_dist = math.dist([player_pos[0], player_pos[2]], [fj_wx, fj_wz])
                draw_jack_shadow(fj_wx, fj_wz, fj_dist, madness)
                draw_jack_billboard(tex_jack, fj_wx, fj_wz, player_pos[0], player_pos[2], fj_dist, madness, now_ms, is_fake=True)

            # 4. Partículas e Bafadas de Frio (billboards)
            draw_particles(player_pos[0], player_pos[2], dt)
            draw_ceiling_drips(blood_drip_zones, now_ms)

            # 5b. Bafadas de Frio (billboards)
            draw_breath_puffs(breath_puffs, now_ms, yaw)

            # 5c. Aberração Cromática (efeito de alucinação em alta ansiedade)
            if anxiety > 0.6:
                draw_chromatic_aberration((anxiety - 0.6) / 0.4)


            # 5. Overlays 2D (HUD)
            toast_remaining = battery_toast_timer_ms - now_ms
            toast_alpha = max(0.0, min(1.0, toast_remaining / 400.0)) if toast_remaining > 0 else 0.0
            draw_anxiety_hud(anxiety, battery, stamina=stamina, hypothermia=hypothermia,
                             blood_overlay_timer=blood_overlay_timer,
                             flashlight_on=flashlight_on, battery_toast_alpha=toast_alpha)

            if toast_alpha > 0.0 and battery_toast_tex:
                glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                W2, H2 = DISPLAY_SIZE
                glOrtho(0, W2, H2, 0, -1, 1)
                glMatrixMode(GL_MODELVIEW);  glPushMatrix(); glLoadIdentity()
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
                glDisable(GL_LIGHTING); glDisable(GL_DEPTH_TEST)
                glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                
                tid, u_max, v_max = battery_toast_tex
                glEnable(GL_TEXTURE_2D)
                glBindTexture(GL_TEXTURE_2D, tid)
                glColor4f(1.0, 1.0, 1.0, toast_alpha)
                
                TW = int(210); TH = int(16)
                TX = (W2 - TW) // 2; TY = H2 - 58
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
                    # ---- Flash Branco: tela explode em branco (suavizado em modo fotossensibilidade) ----
                    if _gs.photosensitivity_mode:
                        glDisable(GL_TEXTURE_2D)
                        glColor4f(0.0, 0.0, 0.0, 0.75)
                        glBegin(GL_QUADS)
                        glVertex2f(0, 0); glVertex2f(W2, 0)
                        glVertex2f(W2, H2); glVertex2f(0, H2)
                        glEnd()
                    else:
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
                game_fade_alpha = max(0, game_fade_alpha - int(round(17 * dt_step)))
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
    finally:
        pygame.mixer.stop()
        cleanup_chromatic_aberration_texture()
        cleanup_pause_overlay_texture()
        try:
            if 'maze_chunks' in locals() and maze_chunks:
                for ch in maze_chunks:
                    glDeleteLists(ch['dlist'], 1)
        except Exception:
            pass
        if 'battery_toast_tex' in locals() and battery_toast_tex:
            try: glDeleteTextures([battery_toast_tex[0]])
            except Exception: pass
        for tid in [tex_hedge, tex_snow, tex_skybox, tex_corpse, tex_jack]:
            if tid:
                try: glDeleteTextures([tid])
                except Exception: pass
        if 'jumpscare_textures' in locals():
            for tid in jumpscare_textures:
                try: glDeleteTextures([tid])
                except Exception: pass
        if 'wall_text_textures' in locals():
            for item in wall_text_textures.values():
                try: glDeleteTextures([item[0]])
                except Exception: pass
        if 'trap_tex_info' in locals() and trap_tex_info:
            try: glDeleteTextures([trap_tex_info[0]])
            except Exception: pass
        if 'interact_tex_info' in locals() and interact_tex_info:
            try: glDeleteTextures([interact_tex_info[0]])
            except Exception: pass

# ================================
# FLUXO PRINCIPAL
# ================================

def main():
    pygame.init()
    pygame.font.init()
    _gs.load_save_data()
    
    # Inicializa o contexto OpenGL uma única vez para toda a sessão
    screen = pygame.display.set_mode(DISPLAY_SIZE, DOUBLEBUF | OPENGL)
    pygame.display.set_caption("The Shining Maze")
    
    try:
        title_font = pygame.font.SysFont("impact", 90)
        font = pygame.font.SysFont("arial", 28)
    except:
        title_font = pygame.font.Font(None, 90)
        font = pygame.font.Font(None, 28)
        
    state = "MENU"
    stats = None
    
    while state != "QUIT":
        if state == "MENU":
            pygame.display.set_caption("The Shining Maze - Menu")
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            state = run_menu(screen, font, title_font)
            
        elif state == "GAME":
            _gs.record_game_start()
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
            pygame.display.set_caption("The Shining Maze - Settings")
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            state = run_settings_screen(screen, font, title_font, is_pause=False)
            
        elif state == "END":
            pygame.display.set_caption("The Shining Maze - Você Sobreviveu! Até agora...")
            pygame.mouse.set_visible(True)
            pygame.event.set_grab(False)
            state = run_end_screen(screen, font, title_font, stats)

    cleanup_screen_texture()
    pygame.quit()
    sys.exit()

if __name__ == "__main__":
    main()
