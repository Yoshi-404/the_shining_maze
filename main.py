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
    build_maze_chunks, draw_maze_optimized, draw_battery_pickup,
    cleanup_floor_display_list, draw_jumpscare_3d, draw_viewmodel_flashlight
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
            if maze_map[my][mx] in (1, 5):
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
            if cell_type in (1, 5):
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
                if mm[ny][nx] not in (1, 5):   # não é parede nem portão travado
                    step = first if first else (nx, ny)
                    if (nx, ny) == goal:
                        return step
                    visited.add((nx, ny))
                    queue.append(((nx, ny), step))
    return None


def find_distant_open_cell(mm, mw, mh, ref_pos, avoid_pos=None):
    """Retorna a célula aberta (0) mais distante de ref_pos, evitando proximidade com avoid_pos."""
    best_cell = None
    best_dist = -1
    fallback_cell = None
    fallback_dist = -1

    for y in range(1, mh - 1):
        for x in range(1, mw - 1):
            if mm[y][x] != 0:
                continue
            d_ref = abs(x - ref_pos[0]) + abs(y - ref_pos[1])
            if d_ref > fallback_dist:
                fallback_dist = d_ref
                fallback_cell = (x, y)
            if avoid_pos is not None and abs(x - avoid_pos[0]) + abs(y - avoid_pos[1]) < 4:
                continue
            if d_ref > best_dist:
                best_dist = d_ref
                best_cell = (x, y)

    if best_cell is not None:
        return best_cell
    return fallback_cell if fallback_cell is not None else ref_pos


def has_line_of_sight(mm, mw, mh, cell_a, cell_b, max_cells=12):
    """Verifica se ha linha de visao desobstruida entre duas celulas do labirinto."""
    dx = cell_b[0] - cell_a[0]
    dy = cell_b[1] - cell_a[1]
    if math.hypot(dx, dy) > max_cells:
        return False
    steps = max(1, int(max(abs(dx), abs(dy)) * 3))
    ax, ay = cell_a[0] + 0.5, cell_a[1] + 0.5
    bx, by = cell_b[0] + 0.5, cell_b[1] + 0.5
    for i in range(1, steps):
        t = i / float(steps)
        ix = int(math.floor(ax + (bx - ax) * t))
        iy = int(math.floor(ay + (by - ay) * t))
        if not (0 <= ix < mw and 0 <= iy < mh):
            return False
        if mm[iy][ix] == 1:
            return False
    return True


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


def _render_font_to_gl_texture(text, color=(160, 20, 20), font_size=56, bold=False, font_name="impact"):
    try:
        font = pygame.font.SysFont(font_name, font_size, bold=bold)
    except Exception:
        font = pygame.font.Font(None, font_size)
    surf = font.render(text, True, color)
    w, h = surf.get_size()
    pw, ph = _next_pow2(w), _next_pow2(h)
    padded = pygame.Surface((pw, ph), pygame.SRCALPHA)
    padded.fill((0, 0, 0, 0))
    padded.blit(surf, (0, 0))
    raw = pygame.image.tostring(padded, "RGBA", False)
    tid = glGenTextures(1)
    glBindTexture(GL_TEXTURE_2D, tid)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE)
    glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE)
    glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, pw, ph, 0, GL_RGBA, GL_UNSIGNED_BYTE, raw)
    return tid, w / pw, h / ph, w, h


def create_text_texture(text, color=(160, 20, 20), font_size=56):
    """Cria uma textura OpenGL com texto. Retorna (tex_id, u_max, v_max)."""
    tid, u_max, v_max, _, _ = _render_font_to_gl_texture(
        text, color=color, font_size=font_size, bold=False, font_name="impact"
    )
    return tid, u_max, v_max


def create_ui_label_texture(text, color=(235, 240, 248), font_size=18, bold=True, font_name="arial"):
    """Cria uma textura OpenGL nítida em proporção 1:1 para HUD e prompts. Retorna (tid, u_max, v_max, w, h)."""
    return _render_font_to_gl_texture(
        text, color=color, font_size=font_size, bold=bold, font_name=font_name
    )


def _draw_ui_label(tex_info, x, y, alpha=1.0, align="center"):
    """Desenha uma textura de label em proporção 1:1 dentro de glOrtho(0, W, H, 0)."""
    if not tex_info or alpha <= 0.0:
        return
    tid, u_max, v_max, w, h = tex_info
    if align == "left":
        tx = float(round(x))
    elif align == "right":
        tx = float(round(x - w))
    else:
        tx = float(round(x - w * 0.5))
    ty = float(round(y - h * 0.5))

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_CURRENT_BIT)
    glEnable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glBindTexture(GL_TEXTURE_2D, tid)
    glColor4f(1.0, 1.0, 1.0, alpha)
    glBegin(GL_QUADS)
    glTexCoord2f(0.0, 0.0);     glVertex2f(tx, ty)
    glTexCoord2f(u_max, 0.0);   glVertex2f(tx + w, ty)
    glTexCoord2f(u_max, v_max); glVertex2f(tx + w, ty + h)
    glTexCoord2f(0.0, v_max);   glVertex2f(tx, ty + h)
    glEnd()
    glPopAttrib()


def reveal_visited_radius(visited_cells, center_cell, mw, mh, radius):
    """Revela células no minimapa em raio euclidiano ao redor de center_cell."""
    cx0, cy0 = center_cell
    r_sq = radius * radius + 1
    for ry in range(-radius, radius + 1):
        for rx in range(-radius, radius + 1):
            if rx * rx + ry * ry <= r_sq:
                vx, vy = cx0 + rx, cy0 + ry
                if 0 <= vx < mw and 0 <= vy < mh:
                    visited_cells.add((vx, vy))


def resolve_corpse_search(mm, mw, mh, corpse_cell, exit_grid, visited_cells, roll=None):
    """Resolve vasculhar corpo em esquema risco vs. recompensa, sempre entregando suprimentos úteis."""
    if roll is None:
        roll = random.random()

    if roll < 0.28:
        reveal_visited_radius(visited_cells, corpse_cell, mw, mh, 4)
        return {
            "outcome": "TRAP",
            "battery_delta": 0.30,
            "hypo_delta": -0.20,
            "anxiety_delta": 0.35,
            "stamina_delta": 0.0,
            "jumpscare": True,
            "flicker_ms": 550,
            "alert_jack": True,
            "minimap_ms": 0,
            "toast_key": "CORPSE_TRAP",
            "toast_style": "TRAP",
        }
    if roll < 0.64:
        reveal_visited_radius(visited_cells, corpse_cell, mw, mh, 6)
        cur_step = corpse_cell
        for _ in range(12):
            nxt_step = bfs_next_step(mm, mw, mh, cur_step, exit_grid)
            if not nxt_step or nxt_step == exit_grid:
                break
            reveal_visited_radius(visited_cells, nxt_step, mw, mh, 1)
            cur_step = nxt_step
        return {
            "outcome": "MAP",
            "battery_delta": 0.50,
            "hypo_delta": -0.25,
            "anxiety_delta": -0.25,
            "stamina_delta": 0.50,
            "jumpscare": False,
            "flicker_ms": 0,
            "alert_jack": False,
            "minimap_ms": 5500,
            "toast_key": "CORPSE_MAP",
            "toast_style": "MAP",
        }
    reveal_visited_radius(visited_cells, corpse_cell, mw, mh, 3)
    return {
        "outcome": "KIT",
        "battery_delta": 0.75,
        "hypo_delta": -0.45,
        "anxiety_delta": -0.35,
        "stamina_delta": 1.0,
        "jumpscare": False,
        "flicker_ms": 0,
        "alert_jack": False,
        "minimap_ms": 0,
        "toast_key": "CORPSE_KIT",
        "toast_style": "BATTERY",
    }


def _draw_hud_badges_and_prompt(
    toast_alpha, toast_tex, near_campfire, campfire_badge_tex,
    near_unsearched, prompt_e_textures, now_ms,
):
    """Renderiza os labels 1:1 das pílulas do HUD e o painel chanfrado do prompt [E]."""
    has_toast = toast_alpha > 0.0 and toast_tex is not None
    has_camp = bool(near_campfire and campfire_badge_tex is not None)
    has_prompt = bool(near_unsearched and prompt_e_textures)
    if not (has_toast or has_camp or has_prompt):
        return

    W2, H2 = DISPLAY_SIZE
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W2, H2, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_LINE_BIT | GL_CURRENT_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
    glDisable(GL_TEXTURE_2D); glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    if has_toast:
        _draw_ui_label(toast_tex, 22.0 + 248.0 * 0.5, (H2 - 130.0) + 10.0, alpha=toast_alpha, align="center")

    if has_camp:
        camp_y = (H2 - 154.0) if toast_alpha > 0.01 else (H2 - 130.0)
        _draw_ui_label(
            campfire_badge_tex, 22.0 + 24.0 + (248.0 - 24.0) * 0.5, camp_y + 10.0,
            alpha=1.0, align="center",
        )

    if has_prompt:
        pw, ph = 346.0, 46.0
        px = (W2 - pw) * 0.5
        py = H2 - 118.0
        glColor4f(0.03, 0.04, 0.06, 0.84)
        _draw_chamfered_quad_gl(px, py, pw, ph, 6.0, filled=True)
        glLineWidth(1.2)
        glColor4f(0.38, 0.48, 0.60, 0.72)
        _draw_chamfered_quad_gl(px, py, pw, ph, 6.0, filled=False)

        kx, ky, kw, kh = px + 14.0, py + 9.0, 28.0, 28.0
        glColor4f(0.14, 0.18, 0.25, 0.95)
        _draw_chamfered_quad_gl(kx, ky, kw, kh, 4.0, filled=True)
        kp = 0.70 + 0.30 * abs(math.sin(now_ms / 240.0))
        glColor4f(0.88, 0.76, 0.42, kp)
        _draw_chamfered_quad_gl(kx, ky, kw, kh, 4.0, filled=False)

        _draw_ui_label(prompt_e_textures["key"], kx + kw * 0.5, ky + kh * 0.5, alpha=1.0, align="center")
        _draw_ui_label(prompt_e_textures["title"], px + 54.0, py + 15.0, alpha=1.0, align="left")
        _draw_ui_label(prompt_e_textures["sub"], px + 54.0, py + 32.0, alpha=1.0, align="left")

    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)


def _draw_trap_banner(trap_banner_textures, rem_ms, now_ms, photosensitivity_mode):
    """Renderiza o banner chanfrado de armadilha da saída falsa."""
    alpha = max(0.0, min(1.0, rem_ms / 450.0))
    if alpha <= 0.0 or not trap_banner_textures:
        return

    W2, H2 = DISPLAY_SIZE
    pw, ph = 480.0, 84.0
    jx = math.sin(now_ms * 0.09) * 2.5 if not photosensitivity_mode else 0.0
    jy = math.cos(now_ms * 0.13) * 1.8 if not photosensitivity_mode else 0.0
    px = (W2 - pw) * 0.5 + jx
    py = (H2 - ph) * 0.44 + jy

    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W2, H2, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_LINE_BIT | GL_CURRENT_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
    glDisable(GL_TEXTURE_2D); glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    glColor4f(0.12, 0.02, 0.03, 0.88 * alpha)
    _draw_chamfered_quad_gl(px, py, pw, ph, 8.0, filled=True)
    glLineWidth(1.5)
    glColor4f(0.86, 0.16, 0.18, 0.92 * alpha)
    _draw_chamfered_quad_gl(px, py, pw, ph, 8.0, filled=False)

    glLineWidth(1.0)
    glColor4f(0.92, 0.25, 0.22, 0.55 * alpha)
    glBegin(GL_LINES)
    glVertex2f(px + 28.0, py + 7.0); glVertex2f(px + pw - 28.0, py + 7.0)
    glVertex2f(px + 28.0, py + ph - 7.0); glVertex2f(px + pw - 28.0, py + ph - 7.0)
    glEnd()

    _draw_ui_label(trap_banner_textures["sub"], px + pw * 0.5, py + 22.0, alpha=alpha, align="center")
    _draw_ui_label(trap_banner_textures["title"], px + pw * 0.5, py + 54.0, alpha=alpha, align="center")

    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)


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
    if _gs.photosensitivity_mode:
        return
    W, H = DISPLAY_SIZE
    shift_px = intensity * 10.0
    if shift_px < 1.0:
        return
    du = shift_px / W
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

    def _quad(u_shift):
        glBegin(GL_QUADS)
        glTexCoord2f(0.0 + u_shift, 0.0); glVertex2f(0, 0)
        glTexCoord2f(1.0 + u_shift, 0.0); glVertex2f(W, 0)
        glTexCoord2f(1.0 + u_shift, 1.0); glVertex2f(W, H)
        glTexCoord2f(0.0 + u_shift, 1.0); glVertex2f(0, H)
        glEnd()

    glColorMask(GL_TRUE,  GL_FALSE, GL_FALSE, GL_TRUE); _quad(du)   # Red  → direita
    glColorMask(GL_FALSE, GL_TRUE,  GL_FALSE, GL_TRUE); _quad(0.0)  # Green → centro
    glColorMask(GL_FALSE, GL_FALSE, GL_TRUE,  GL_TRUE); _quad(-du)  # Blue  → esquerda
    glColorMask(GL_TRUE,  GL_TRUE,  GL_TRUE,  GL_TRUE)

    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)

# ================================
# ESTADOS DO JOGO
# ================================

def _draw_chamfered_quad_gl(x, y, w, h, chamfer, filled=True):
    pts = (
        (x + chamfer, y), (x + w - chamfer, y),
        (x + w, y + chamfer), (x + w, y + h - chamfer),
        (x + w - chamfer, y + h), (x + chamfer, y + h),
        (x, y + h - chamfer), (x, y + chamfer),
    )
    glBegin(GL_POLYGON if filled else GL_LINE_LOOP)
    for px, py in pts:
        glVertex2f(px, py)
    glEnd()


def draw_minimap(mm, mw, mh, px, pz, yaw=0.0, visited_cells=None, campfires=None, corpses=None, jack_dist=999.0, now_ms=None):
    W, H = DISPLAY_SIZE
    size = 196
    margin = 22
    x0 = W - size - margin
    y0 = margin
    pad = 10
    map_size = size - 2 * pad
    mx0 = x0 + pad
    my0 = y0 + pad
    now = pygame.time.get_ticks() if now_ms is None else now_ms

    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W, H, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_LINE_BIT | GL_POINT_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    # Moldura chanfrada escura
    glColor4f(0.03, 0.04, 0.06, 0.84)
    _draw_chamfered_quad_gl(x0, y0, size, size, 8.0, filled=True)

    glLineWidth(1.5)
    if jack_dist < BLOCK_SIZE * 7.0:
        pulse = 0.70 + 0.25 * abs(math.sin(now / 160.0))
        glColor4f(0.90, 0.16, 0.16, pulse)
    else:
        glColor4f(0.34, 0.42, 0.52, 0.55)
    _draw_chamfered_quad_gl(x0, y0, size, size, 8.0, filled=False)

    # Celulas exploradas (Fog of War)
    cell_w = map_size / mw
    cell_h = map_size / mh
    gold_pulse = 0.78 + 0.17 * abs(math.sin(now / 220.0))
    glBegin(GL_QUADS)
    for y in range(mh):
        for x in range(mw):
            if visited_cells is not None and (x, y) not in visited_cells:
                continue
            val = mm[y][x]
            if val == 1:
                glColor4f(0.34, 0.44, 0.38, 0.92)
            elif val == 2:
                glColor4f(0.98, 0.82, 0.20, min(0.98, gold_pulse))
            elif val == 5:
                glColor4f(0.55, 0.12, 0.14, 0.90)
            else:
                glColor4f(0.11, 0.14, 0.19, 0.72)
            cx = mx0 + x * cell_w
            cy = my0 + y * cell_h
            glVertex2f(cx, cy)
            glVertex2f(cx + cell_w, cy)
            glVertex2f(cx + cell_w, cy + cell_h)
            glVertex2f(cx, cy + cell_h)

    # Marcadores descobertos (Fogueiras e Corpos nao vasculhados)
    inset_x = cell_w * 0.18
    inset_y = cell_h * 0.18
    if campfires:
        glColor4f(1.0, 0.55, 0.12, 0.95)
        for fx, fz in campfires:
            gx = int(round(fx / BLOCK_SIZE + mw / 2.0))
            gy = int(round(fz / BLOCK_SIZE + mh / 2.0))
            if visited_cells is None or (gx, gy) in visited_cells:
                cx = mx0 + gx * cell_w + inset_x
                cy = my0 + gy * cell_h + inset_y
                glVertex2f(cx, cy)
                glVertex2f(cx + cell_w - 2 * inset_x, cy)
                glVertex2f(cx + cell_w - 2 * inset_x, cy + cell_h - 2 * inset_y)
                glVertex2f(cx, cy + cell_h - 2 * inset_y)

    if corpses:
        glColor4f(0.82, 0.22, 0.35, 0.90)
        for c in corpses:
            if c.get("searched"):
                continue
            gx = int(round(c["pos"][0] / BLOCK_SIZE + mw / 2.0))
            gy = int(round(c["pos"][1] / BLOCK_SIZE + mh / 2.0))
            if visited_cells is None or (gx, gy) in visited_cells:
                cx = mx0 + gx * cell_w + inset_x
                cy = my0 + gy * cell_h + inset_y
                glVertex2f(cx, cy)
                glVertex2f(cx + cell_w - 2 * inset_x, cy)
                glVertex2f(cx + cell_w - 2 * inset_x, cy + cell_h - 2 * inset_y)
                glVertex2f(cx, cy + cell_h - 2 * inset_y)
    glEnd()

    # Cone de visao + seta direcional do jogador
    map_x = (px / BLOCK_SIZE) + mw / 2.0
    map_y = (pz / BLOCK_SIZE) + mh / 2.0
    px_screen = mx0 + (map_x + 0.5) * cell_w
    py_screen = my0 + (map_y + 0.5) * cell_h
    cone_len = 15.0
    cone_spread = 0.48
    tip_r = 5.5
    back_r = 4.2

    glBegin(GL_TRIANGLES)
    glColor4f(0.20, 0.85, 1.0, 0.22)
    glVertex2f(px_screen, py_screen)
    glVertex2f(px_screen + math.cos(yaw - cone_spread) * cone_len,
               py_screen + math.sin(yaw - cone_spread) * cone_len)
    glVertex2f(px_screen + math.cos(yaw + cone_spread) * cone_len,
               py_screen + math.sin(yaw + cone_spread) * cone_len)

    glColor4f(0.25, 0.98, 0.65, 1.0)
    glVertex2f(px_screen + math.cos(yaw) * tip_r,
               py_screen + math.sin(yaw) * tip_r)
    glVertex2f(px_screen + math.cos(yaw - 2.35) * back_r,
               py_screen + math.sin(yaw - 2.35) * back_r)
    glVertex2f(px_screen + math.cos(yaw + 2.35) * back_r,
               py_screen + math.sin(yaw + 2.35) * back_r)
    glEnd()

    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)


def draw_jack_shadow(jack_wx, jack_wz, jack_dist, madness, now_ms=None):
    """Desenha uma sombra/silhueta escura e pulsante no chão na posição do Jack."""
    MAX_SHADOW_DIST = 12.0
    if jack_dist > MAX_SHADOW_DIST:
        return
    alpha = (1.0 - jack_dist / MAX_SHADOW_DIST) * (0.4 + madness * 0.4)
    FLOOR_Y = -0.96
    SHADOW_SIZE = BLOCK_SIZE * 0.7
    t = (pygame.time.get_ticks() if now_ms is None else now_ms) / 1000.0
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


def _chamfer_points_2d(rect, c=8):
    x, y, w, h = rect
    return [
        (x + c, y), (x + w - c, y),
        (x + w, y + c), (x + w, y + h - c),
        (x + w - c, y + h), (x + c, y + h),
        (x, y + h - c), (x, y + c),
    ]


def _draw_chamfered_pygame(surf, rect, c, fill_col, border_col=None, border_w=2):
    pts = _chamfer_points_2d(rect, c)
    pygame.draw.polygon(surf, fill_col, pts)
    if border_col is not None:
        pygame.draw.polygon(surf, border_col, pts, border_w)


def _draw_menu_button(surf, rect, label, font, selected, danger=False):
    fill = (32, 16, 18, 225) if (selected and danger) else (
        (22, 30, 40, 228) if selected else (10, 12, 18, 195)
    )
    border = (220, 65, 65, 240) if (selected and danger) else (
        (235, 195, 75, 240) if selected else (75, 90, 110, 150)
    )
    _draw_chamfered_pygame(surf, rect, 7, fill, border, 2 if selected else 1)
    if selected:
        bar_col = (210, 45, 45, 240) if danger else (225, 175, 55, 240)
        pygame.draw.rect(surf, bar_col, (rect.x + 5, rect.y + 7, 4, rect.h - 14))
    tcol = (255, 235, 130) if selected else (195, 200, 210)
    txt = font.render(label, True, tcol)
    surf.blit(txt, txt.get_rect(center=rect.center))


def _apply_setting_change(sel, step_dir, vol, sens, update_gl_proj=False):
    """Aplica alteracao incremental ou alternancia a um item das configuracoes."""
    if sel == 0:
        vol = max(0.0, min(2.0, round(vol + 0.1 * step_dir, 2)))
        _gs.master_volume = vol
    elif sel == 1:
        sens = max(1.0, min(10.0, round(sens + 1.0 * step_dir)))
        _gs.mouse_sensitivity = sens / 1000.0
    elif sel == 2:
        idx = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
        _gs.difficulty = _gs.DIFFICULTIES[(idx + step_dir) % len(_gs.DIFFICULTIES)]
    elif sel == 3:
        _gs.fov = max(60.0, min(95.0, _gs.fov + 5.0 * step_dir))
        if update_gl_proj:
            glMatrixMode(GL_PROJECTION); glLoadIdentity()
            gluPerspective(_gs.fov, (DISPLAY_SIZE[0] / DISPLAY_SIZE[1]), 0.1, 80.0)
            glMatrixMode(GL_MODELVIEW)
    elif sel == 4:
        _gs.head_bobbing = not _gs.head_bobbing
    elif sel == 5:
        _gs.camera_shake = not _gs.camera_shake
    elif sel == 6:
        _gs.photosensitivity_mode = not _gs.photosensitivity_mode
    elif sel == 7:
        _gs.invert_mouse_y = not _gs.invert_mouse_y
    return vol, sens, (sel == 8)


def _format_settings_items(vol, sens, back_label):
    diff_data = _gs.DIFFICULTY_PRESETS.get(_gs.difficulty, {})
    diff_str = f"{diff_data.get('label', _gs.difficulty)}"
    return [
        f"<  Volume Geral: {int(vol * 100)}%  >",
        f"<  Sensibilidade Mouse: {int(sens)}  >",
        f"<  Dificuldade: {diff_str}  >",
        f"<  Campo de Visao (FOV): {int(_gs.fov)}°  >",
        f"Balanco de Camera (Bobbing): {'Ligado' if _gs.head_bobbing else 'Desligado'}",
        f"Tremores de Camera (Shake): {'Ligado' if _gs.camera_shake else 'Desligado'}",
        f"Fotosensibilidade (Sem Flashes): {'Ligado' if _gs.photosensitivity_mode else 'Desligado'}",
        f"Inverter Eixo Y: {'Sim' if _gs.invert_mouse_y else 'Nao'}",
        back_label,
    ]


def _get_pause_menu_rects(W, H, in_settings):
    if not in_settings:
        return [pygame.Rect(W // 2 - 205, H // 2 - 44 + i * 60, 410, 46) for i in range(3)]
    return [pygame.Rect(W // 2 - 300, 155 + i * 44 - 18, 600, 36) for i in range(9)]


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
        overlay.fill((4, 6, 10, 145))
        try:
            tfont = pygame.font.SysFont("impact", 64)
            ofont_main = pygame.font.SysFont("arial", 26)
            ofont_set = pygame.font.SysFont("arial", 22)
            hfont = pygame.font.SysFont("arial", 19)
        except Exception:
            tfont = pygame.font.Font(None, 64)
            ofont_main = pygame.font.Font(None, 26)
            ofont_set = pygame.font.Font(None, 22)
            hfont = pygame.font.Font(None, 19)

        rects = _get_pause_menu_rects(W, H, in_settings)
        if not in_settings:
            panel_rect = pygame.Rect(W // 2 - 245, H // 2 - 190, 490, 360)
            _draw_chamfered_pygame(overlay, panel_rect, 12, (8, 10, 15, 220), (85, 100, 120, 175), 2)
            title = tfont.render("PAUSA", True, (220, 225, 232))
            overlay.blit(title, title.get_rect(center=(W // 2, H // 2 - 125)))
            options = ["Continuar", "Configuracoes & Acessibilidade", "Sair ao Menu"]
            for i, (opt, rect) in enumerate(zip(options, rects)):
                _draw_menu_button(overlay, rect, opt, ofont_main, i == selected, danger=(i == 2))
            hint = hfont.render("[MOUSE / SETAS] Selecionar  |  [ENTER / CLIQUE] Confirmar  |  [ESC] Retomar",
                                True, (150, 160, 175))
            overlay.blit(hint, hint.get_rect(center=(W // 2, H - 38)))
        else:
            panel_rect = pygame.Rect(W // 2 - 340, 42, 680, H - 84)
            _draw_chamfered_pygame(overlay, panel_rect, 12, (8, 10, 15, 225), (85, 100, 120, 175), 2)
            title = tfont.render("CONFIGURACOES", True, (220, 225, 232))
            overlay.blit(title, title.get_rect(center=(W // 2, 92)))

            items = _format_settings_items(vol, sens, "Voltar ao Menu de Pausa")
            for i, (item, rect) in enumerate(zip(items, rects)):
                _draw_menu_button(overlay, rect, item, ofont_set, i == settings_sel)

            hint = hfont.render("[CLIQUE ESQ/DIR ou SETAS] Ajustar  |  [ESC] Voltar",
                                True, (150, 160, 175))
            overlay.blit(hint, hint.get_rect(center=(W // 2, H - 30)))

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
_menu_3d_cache = None


def _get_menu_3d_scene():
    """Constroi e armazena em cache o diorama 3D usado no fundo dos menus."""
    global _menu_3d_cache
    if _menu_3d_cache is not None:
        return _menu_3d_cache

    mw, mh = 9, 9
    mm = [[1] * mw for _ in range(mh)]
    for y in range(2, mh - 1):
        mm[y][4] = 0
    mm[1][4] = 2
    mm[4][3] = 0
    mm[4][5] = 0
    mm[6][3] = 0
    mm[6][5] = 0

    tex_hedge = load_texture(tex("hedge.png"))
    tex_snow = load_texture(tex("snow.png"))
    tex_skybox = load_texture(tex("skybox.png"))
    tex_jack = None
    chunks = build_maze_chunks(tex_hedge, mm, mw, mh, chunk_size=5)

    _menu_3d_cache = {
        "maze": mm,
        "mw": mw,
        "mh": mh,
        "chunks": chunks,
        "tex_hedge": tex_hedge,
        "tex_snow": tex_snow,
        "tex_skybox": tex_skybox,
        "tex_jack": tex_jack,
    }
    return _menu_3d_cache


def draw_menu_background_3d(now_ms, mode="MENU"):
    """Renderiza uma cena 3D ao vivo do labirinto nevado no fundo dos menus."""
    scene = _get_menu_3d_scene()
    W, H = DISPLAY_SIZE
    t_s = now_ms / 1000.0

    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    gluPerspective(60.0, W / H, 0.1, 80.0)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()

    glEnable(GL_DEPTH_TEST)
    fog_col = setup_fog()
    if mode == "END":
        fog_col = (0.07, 0.015, 0.02, 1.0)
        glFogfv(GL_FOG_COLOR, fog_col)
        glFogf(GL_FOG_DENSITY, 0.105)
    else:
        glFogf(GL_FOG_DENSITY, 0.085)

    glClearColor(*fog_col)
    glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    setup_lighting()

    cx = -1.0 + math.sin(t_s * 0.36) * 0.45
    cy = 0.68 + math.sin(t_s * 0.62) * 0.06
    cz = 4.6 + math.cos(t_s * 0.24) * 0.30
    lx = -1.0 + math.sin(t_s * 0.26) * 0.20
    ly = 0.28
    lz = -3.8
    gluLookAt(cx, cy, cz, lx, ly, lz, 0, 1, 0)

    cam_dir = (lx - cx, ly - cy, lz - cz)
    glLightfv(GL_LIGHT0, GL_POSITION, (cx, cy, cz, 1.0))
    glLightfv(GL_LIGHT0, GL_SPOT_DIRECTION, cam_dir)
    glLightfv(GL_LIGHT0, GL_DIFFUSE, (1.5, 1.48, 1.65, 1.0))
    glLightfv(GL_LIGHT1, GL_POSITION, (cx, cy - 0.3, cz, 1.0))
    glLightfv(GL_LIGHT1, GL_DIFFUSE, (0.09, 0.10, 0.13, 1.0))

    cf_pos = (-1.0, -3.0)
    cf_flicker = 1.0 if _gs.photosensitivity_mode else (
        0.90 + 0.10 * math.sin(t_s * 12.5) + 0.05 * math.cos(t_s * 21.0)
    )
    glEnable(GL_LIGHT2)
    glLightfv(GL_LIGHT2, GL_POSITION, (cf_pos[0], -0.35, cf_pos[1], 1.0))
    if mode == "END":
        glLightfv(GL_LIGHT2, GL_DIFFUSE, (1.45 * cf_flicker, 0.22 * cf_flicker, 0.12 * cf_flicker, 1.0))
    else:
        glLightfv(GL_LIGHT2, GL_DIFFUSE, (1.25 * cf_flicker, 0.58 * cf_flicker, 0.15 * cf_flicker, 1.0))

    draw_skybox(scene["tex_skybox"], cx, cy, cz)
    draw_floor(scene["tex_snow"], scene["mw"], scene["mh"])
    draw_maze_optimized(scene["chunks"], (cx, cy, cz), max_dist=50.0)
    draw_exit(scene["maze"], scene["mw"], scene["mh"], cam_pos=(cx, cy, cz), now_ms=now_ms)
    draw_campfires([cf_pos], cam_pos=(cx, cy, cz), now_ms=now_ms)

    jack_x = -1.0 + math.sin(t_s * 0.40) * 0.32
    jack_z = -4.6 + math.cos(t_s * 0.28) * 0.30
    jdist = math.hypot(cx - jack_x, cz - jack_z)
    draw_jack_shadow(jack_x, jack_z, jdist, 0.65, now_ms=now_ms)
    draw_jack_billboard(scene["tex_jack"], jack_x, jack_z, cx, cz, jdist, 0.65, now_ms, is_fake=False)
    draw_particles(cx, cz, 0.016, blizzard_intensity=(0.35 if mode == "END" else 0.18))

    glDisable(GL_LIGHT2)
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()


def cleanup_screen_texture():
    global _gl_screen_tex_id, _menu_3d_cache
    if _gl_screen_tex_id is not None:
        try:
            glDeleteTextures([_gl_screen_tex_id])
        except Exception:
            pass
        _gl_screen_tex_id = None
    if _menu_3d_cache is not None:
        for ch in _menu_3d_cache.get("chunks", []):
            try:
                glDeleteLists(ch["dlist"], 1)
            except Exception:
                pass
        for key in ("tex_hedge", "tex_snow", "tex_skybox"):
            tid = _menu_3d_cache.get(key)
            if tid:
                try:
                    glDeleteTextures([tid])
                except Exception:
                    pass
        cleanup_floor_display_list()
        _menu_3d_cache = None


def render_surface_to_opengl(surf, clear_bg=True):
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

    if clear_bg:
        glClearColor(0.0, 0.0, 0.0, 1.0)
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W, 0, H, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
    glEnable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
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
    W, H = DISPLAY_SIZE
    clock = pygame.time.Clock()
    canvas = pygame.Surface(DISPLAY_SIZE, pygame.SRCALPHA)
    _fade_result = None
    _fade_alpha = 0
    selected = 0

    try:
        menu_font = pygame.font.SysFont("arial", 23)
        sub_font = pygame.font.SysFont("arial", 19)
    except Exception:
        menu_font = font
        sub_font = font

    btn_w, btn_h = 460, 42
    btn_rects = [pygame.Rect(W // 2 - btn_w // 2, H // 2 - 10 + i * 52, btn_w, btn_h) for i in range(4)]

    def _activate(idx):
        nonlocal _fade_result
        if idx == 0:
            _fade_result = "GAME"
        elif idx == 1:
            di = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
            _gs.difficulty = _gs.DIFFICULTIES[(di + 1) % len(_gs.DIFFICULTIES)]
            _gs.save_save_data()
        elif idx == 2:
            _fade_result = "SETTINGS"
        elif idx == 3:
            return "QUIT"
        return None

    while True:
        now_ms = pygame.time.get_ticks()
        dt = clock.tick(60) / 1000.0
        dt_step = min(dt, 0.1) * 60.0
        if _fade_result and _fade_alpha >= 255:
            return _fade_result

        for event in pygame.event.get():
            if event.type == QUIT:
                return "QUIT"
            if _fade_result:
                continue
            if event.type == MOUSEMOTION:
                mx, my = event.pos
                for i, r in enumerate(btn_rects):
                    if r.collidepoint(mx, my):
                        selected = i
                        break
            elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                for i, r in enumerate(btn_rects):
                    if r.collidepoint(mx, my):
                        selected = i
                        res = _activate(i)
                        if res == "QUIT":
                            return "QUIT"
                        break
            elif event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    return "QUIT"
                elif event.key == K_UP:
                    selected = (selected - 1) % 4
                elif event.key == K_DOWN:
                    selected = (selected + 1) % 4
                elif event.key == K_RETURN:
                    res = _activate(selected)
                    if res == "QUIT":
                        return "QUIT"
                elif event.key == K_LEFT and selected == 1:
                    di = _gs.DIFFICULTIES.index(_gs.difficulty) if _gs.difficulty in _gs.DIFFICULTIES else 1
                    _gs.difficulty = _gs.DIFFICULTIES[(di - 1) % len(_gs.DIFFICULTIES)]
                    _gs.save_save_data()
                elif event.key == K_RIGHT and selected == 1:
                    _activate(1)
                elif event.key in (K_d, K_TAB):
                    _activate(1)
                elif event.key == K_s:
                    _fade_result = "SETTINGS"

        draw_menu_background_3d(now_ms, mode="MENU")
        canvas.fill((0, 0, 0, 0))

        # Vinheta sutil + card chanfrado central sobre a cena 3D
        panel_rect = pygame.Rect(W // 2 - 340, H // 2 - 220, 680, 500)
        _draw_chamfered_pygame(canvas, panel_rect, 14, (6, 8, 13, 178), (95, 110, 130, 145), 2)

        shadow_t = title_font.render("THE SHINING MAZE", True, (15, 5, 5))
        title_text = title_font.render("THE SHINING MAZE", True, (185, 22, 22))
        canvas.blit(shadow_t, shadow_t.get_rect(center=(W // 2 + 3, H // 2 - 137)))
        canvas.blit(title_text, title_text.get_rect(center=(W // 2, H // 2 - 140)))

        sub_tag = sub_font.render("OVERLOOK HOTEL  //  EDICAO 3D", True, (175, 185, 200))
        canvas.blit(sub_tag, sub_tag.get_rect(center=(W // 2, H // 2 - 72)))

        diff_info = _gs.DIFFICULTY_PRESETS.get(_gs.difficulty, {})
        diff_lbl = f"Dificuldade: {diff_info.get('label', _gs.difficulty)} ({diff_info.get('desc', '')})  [D]"
        labels = [
            "Iniciar Jogo  [ENTER]",
            diff_lbl,
            "Configuracoes & Acessibilidade  [S]",
            "Sair  [ESC]",
        ]
        for i, (lbl, r) in enumerate(zip(labels, btn_rects)):
            _draw_menu_button(canvas, r, lbl, menu_font, i == selected, danger=(i == 3))

        recs = _gs.save_data.get("records", {}) if _gs.save_data else {}
        diff_best = recs.get("best_times_by_diff", {}).get(_gs.difficulty)
        best_str = f"{int(diff_best // 60)}m {int(diff_best % 60):02d}s" if diff_best is not None else "--:--"
        total_wins = _gs.save_data.get("progress", {}).get("total_wins", 0) if _gs.save_data else 0
        rec_text = sub_font.render(f"Melhor Tempo [{_gs.difficulty}]: {best_str}   |   Fugas Concluidas: {total_wins}",
                                   True, (130, 195, 215))
        canvas.blit(rec_text, rec_text.get_rect(center=(W // 2, H // 2 + 225)))

        inst_text = sub_font.render("Mouse ou Setas  |  [F] Lanterna (apague para se esconder)  |  [M] Minimapa",
                                    True, (175, 182, 192))
        canvas.blit(inst_text, inst_text.get_rect(center=(W // 2, H - 30)))

        if _fade_result:
            _fade_alpha = min(255, _fade_alpha + int(round(17 * dt_step)))
            fade_s = pygame.Surface(DISPLAY_SIZE, pygame.SRCALPHA)
            fade_s.fill((0, 0, 0, _fade_alpha))
            canvas.blit(fade_s, (0, 0))

        render_surface_to_opengl(canvas, clear_bg=False)


def run_settings_screen(screen, font, title_font, is_pause=False):
    W, H = DISPLAY_SIZE
    clock = pygame.time.Clock()
    canvas = pygame.Surface(DISPLAY_SIZE, pygame.SRCALPHA)
    vol = _gs.master_volume
    sens = _gs.mouse_sensitivity * 1000.0
    selected = 0
    num_items = 9

    try:
        opt_font = pygame.font.SysFont("arial", 22)
        hint_font = pygame.font.SysFont("arial", 19)
        head_font = pygame.font.SysFont("impact", 54)
    except Exception:
        opt_font = font
        hint_font = font
        head_font = title_font

    item_rects = [pygame.Rect(W // 2 - 310, 152 + i * 46 - 18, 620, 38) for i in range(num_items)]

    def _finish():
        _gs.master_volume = vol
        _gs.mouse_sensitivity = sens / 1000.0
        _gs.save_save_data()
        return "GAME" if is_pause else "MENU"

    while True:
        now_ms = pygame.time.get_ticks()
        clock.tick(60)
        for event in pygame.event.get():
            if event.type == QUIT:
                return "QUIT"
            if event.type == MOUSEMOTION:
                mx, my = event.pos
                for i, r in enumerate(item_rects):
                    if r.collidepoint(mx, my):
                        selected = i
                        break
            elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                for i, r in enumerate(item_rects):
                    if r.collidepoint(mx, my):
                        selected = i
                        delta = -1 if (i in (0, 1, 2, 3) and mx < r.centerx) else 1
                        vol, sens, exit_flag = _apply_setting_change(i, delta, vol, sens)
                        if exit_flag:
                            return _finish()
                        break
            elif event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    return _finish()
                elif event.key == K_UP:
                    selected = (selected - 1) % num_items
                elif event.key == K_DOWN:
                    selected = (selected + 1) % num_items
                elif event.key == K_LEFT:
                    vol, sens, _ = _apply_setting_change(selected, -1, vol, sens)
                elif event.key == K_RIGHT:
                    vol, sens, _ = _apply_setting_change(selected, 1, vol, sens)
                elif event.key in (K_RETURN, K_SPACE):
                    vol, sens, exit_flag = _apply_setting_change(selected, 1, vol, sens)
                    if exit_flag:
                        return _finish()

        draw_menu_background_3d(now_ms, mode="SETTINGS")
        canvas.fill((0, 0, 0, 0))

        panel_rect = pygame.Rect(W // 2 - 350, 42, 700, H - 84)
        _draw_chamfered_pygame(canvas, panel_rect, 12, (6, 8, 13, 210), (95, 110, 130, 165), 2)

        t = head_font.render("CONFIGURACOES & ACESSIBILIDADE", True, (215, 222, 230))
        canvas.blit(t, t.get_rect(center=(W // 2, 92)))

        back_lbl = "Voltar ao Menu Principal" if not is_pause else "Retomar Jogo"
        items = _format_settings_items(vol, sens, back_lbl)
        for i, (text, r) in enumerate(zip(items, item_rects)):
            _draw_menu_button(canvas, r, text, opt_font, i == selected)

        hint = hint_font.render("[CLIQUE ESQ/DIR ou SETAS] Ajustar  |  [ESC] Salvar e Voltar",
                                True, (160, 168, 180))
        canvas.blit(hint, hint.get_rect(center=(W // 2, H - 28)))

        render_surface_to_opengl(canvas, clear_bg=False)


def run_end_screen(screen, font, title_font, stats=None):
    W, H = DISPLAY_SIZE
    new_recs = {}
    if stats:
        run_time, dist, jumpscares, peak_anx, batts = stats
        new_recs = _gs.record_game_completion(run_time, dist, jumpscares, peak_anx, _gs.difficulty, batts)
    else:
        _gs.completion_count += 1
        _gs.save_save_data()
    cc = _gs.completion_count

    madness_lines = [
        "Selecione uma opcao para continuar",
        "Por que voltar? Ele ainda esta la...",
        "Voce sente que esta sendo observado.",
        "Nao ha saida real. Nunca houve.",
        "REDRUM. REDRUM. REDRUM.",
        "Voce nao consegue parar, consegue?",
        "ELE SABE QUE VOCE ESTA VOLTANDO.",
        "AQUI NAO HA ESCAPE. SO O LABIRINTO.",
    ]
    sub_msg = madness_lines[min(cc - 1, len(madness_lines) - 1)]

    try:
        stat_font = pygame.font.SysFont("arial", 22)
        btn_font = pygame.font.SysFont("arial", 23)
    except Exception:
        stat_font = font
        btn_font = font

    btn_rects = [
        pygame.Rect(W // 2 - 260, H // 2 + 185, 245, 44),
        pygame.Rect(W // 2 + 15, H // 2 + 185, 245, 44),
    ]
    selected = 0

    clock = pygame.time.Clock()
    canvas = pygame.Surface(DISPLAY_SIZE, pygame.SRCALPHA)
    _fade_result = None
    _fade_alpha = 0
    while True:
        now_ms = pygame.time.get_ticks()
        dt = clock.tick(60) / 1000.0
        dt_step = min(dt, 0.1) * 60.0
        if _fade_result and _fade_alpha >= 255:
            return _fade_result

        for event in pygame.event.get():
            if event.type == QUIT:
                return "QUIT"
            if _fade_result:
                continue
            if event.type == MOUSEMOTION:
                mx, my = event.pos
                for i, r in enumerate(btn_rects):
                    if r.collidepoint(mx, my):
                        selected = i
                        break
            elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                mx, my = event.pos
                if btn_rects[0].collidepoint(mx, my):
                    _fade_result = "MENU"
                elif btn_rects[1].collidepoint(mx, my):
                    return "QUIT"
            elif event.type == KEYDOWN:
                if event.key == K_ESCAPE:
                    return "QUIT"
                elif event.key in (K_LEFT, K_UP):
                    selected = (selected - 1) % 2
                elif event.key in (K_RIGHT, K_DOWN):
                    selected = (selected + 1) % 2
                elif event.key == K_RETURN:
                    if selected == 0:
                        _fade_result = "MENU"
                    else:
                        return "QUIT"

        draw_menu_background_3d(now_ms, mode="END")
        canvas.fill((0, 0, 0, 0))

        card_rect = pygame.Rect(W // 2 - 330, H // 2 - 235, 660, 495)
        border_c = (185, 45, 45, 195) if cc >= 2 else (110, 130, 150, 180)
        _draw_chamfered_pygame(canvas, card_rect, 14, (8, 8, 12, 208), border_c, 2)

        ox = random.randint(-cc, cc) if cc >= 3 else 0
        oy = random.randint(-cc, cc) if cc >= 3 else 0

        title_color = (min(170 + cc * 20, 255), max(75 - cc * 10, 20), max(75 - cc * 10, 20))
        title_text = title_font.render("VOCE ESCAPOU", True, title_color)
        canvas.blit(title_text, title_text.get_rect(center=(W // 2 + ox, H // 2 - 155 + oy)))

        count_color = (225, 65, 65) if cc >= 2 else (175, 185, 200)
        count_text = stat_font.render(f"Fugas Concluidas: {cc}", True, count_color)
        canvas.blit(count_text, count_text.get_rect(center=(W // 2, H // 2 - 88)))

        if stats:
            run_time, dist, jumpscares, peak_anx, batts = stats
            stat_rows = [
                (f"Tempo: {int(run_time // 60)}m {int(run_time % 60):02d}s", (205, 210, 220)),
                (f"Distancia Percorrida: {dist:.1f} m", (205, 210, 220)),
                (f"Jumpscares Sofridos: {jumpscares}", (205, 210, 220)),
                (f"Pico de Ansiedade: {int(peak_anx * 100)}%", (205, 210, 220)),
                (f"Baterias Coletadas: {batts}", (95, 235, 160)),
            ]
            for idx, (s_lbl, scol) in enumerate(stat_rows):
                s_surf = stat_font.render(s_lbl, True, scol)
                canvas.blit(s_surf, s_surf.get_rect(center=(W // 2, H // 2 - 42 + idx * 30)))
            if new_recs.get("best_time") or new_recs.get("diff_best_time"):
                rec_alert = stat_font.render("* NOVO RECORDE DE TEMPO! *", True, (255, 220, 75))
                canvas.blit(rec_alert, rec_alert.get_rect(center=(W // 2, H // 2 + 114)))

        sub_surf = stat_font.render(sub_msg, True, (210, 210, 220) if cc < 3 else (225, 90, 90))
        canvas.blit(sub_surf, sub_surf.get_rect(center=(W // 2, H // 2 + 152)))

        _draw_menu_button(canvas, btn_rects[0], "Voltar ao Menu  [ENTER]", btn_font, selected == 0)
        _draw_menu_button(canvas, btn_rects[1], "Sair  [ESC]", btn_font, selected == 1, danger=True)

        if _fade_result:
            _fade_alpha = min(255, _fade_alpha + int(round(17 * dt_step)))
            fade_s = pygame.Surface(DISPLAY_SIZE, pygame.SRCALPHA)
            fade_s.fill((0, 0, 0, _fade_alpha))
            canvas.blit(fade_s, (0, 0))

        render_surface_to_opengl(canvas, clear_bg=False)


def _update_nearest_campfire_light(px, pz, campfires, t_s, photosensitivity):
    """Ativa a luz pontual GL_LIGHT2 na fogueira mais proxima (< 18m)."""
    nearest_camp = None
    nearest_camp_d = 18.0
    for fx, fz in campfires:
        d_cf = math.hypot(px - fx, pz - fz)
        if d_cf < nearest_camp_d:
            nearest_camp_d = d_cf
            nearest_camp = (fx, fz)
    if nearest_camp is not None:
        cf_flicker = 1.0 if photosensitivity else (
            0.88 + 0.12 * math.sin(t_s * 13.7) + 0.06 * math.cos(t_s * 23.1)
        )
        glEnable(GL_LIGHT2)
        glLightfv(GL_LIGHT2, GL_POSITION, (nearest_camp[0], -0.35, nearest_camp[1], 1.0))
        glLightfv(GL_LIGHT2, GL_DIFFUSE, (1.20 * cf_flicker, 0.56 * cf_flicker, 0.14 * cf_flicker, 1.0))
    else:
        glDisable(GL_LIGHT2)


def _draw_wall_texts(wall_text_data, wall_text_textures, madness, t_s):
    """Renderiza inscricoes nas paredes conforme o nivel de loucura."""
    if not wall_text_data:
        return
    WALL_H = 1.35
    TEXT_W = 0.82
    TEXT_H = 0.28
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_POLYGON_BIT)
    glDisable(GL_LIGHTING)
    glEnable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glEnable(GL_POLYGON_OFFSET_FILL)
    glPolygonOffset(-1.0, -1.0)
    for (wx, wz, ndx, ndz, label, min_mad) in wall_text_data:
        if madness < min_mad:
            continue
        fade = min(1.0, (madness - min_mad) / 0.12)
        pulse = 0.7 + 0.3 * abs(math.sin(t_s * 1.8 + wx))
        alpha = fade * pulse
        tid, umax, vmax = wall_text_textures[label]
        glBindTexture(GL_TEXTURE_2D, tid)
        glColor4f(1.0, 0.08, 0.08, alpha)
        wy = WALL_H
        rx = -ndz
        rz = ndx
        glBegin(GL_QUADS)
        glTexCoord2f(0.0, vmax);  glVertex3f(wx - rx * TEXT_W, wy - TEXT_H, wz - rz * TEXT_W)
        glTexCoord2f(umax, vmax); glVertex3f(wx + rx * TEXT_W, wy - TEXT_H, wz + rz * TEXT_W)
        glTexCoord2f(umax, 0.0);  glVertex3f(wx + rx * TEXT_W, wy + TEXT_H, wz + rz * TEXT_W)
        glTexCoord2f(0.0, 0.0);   glVertex3f(wx - rx * TEXT_W, wy + TEXT_H, wz - rz * TEXT_W)
        glEnd()
    glPopAttrib()


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
    
    tex_corpse = None
    tex_jack   = None

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
    
    trap_text_timer_ms = 0
    prompt_e_textures = {
        "key": create_ui_label_texture("E", color=(250, 224, 150), font_size=15, bold=True),
        "title": create_ui_label_texture("VASCULHAR SOBREVIVENTE", color=(240, 244, 250), font_size=14, bold=True),
        "sub": create_ui_label_texture("Suprimentos  •  Kit Térmico  •  Mapa", color=(158, 176, 198), font_size=12, bold=False),
    }
    trap_banner_textures = {
        "sub": create_ui_label_texture("ARMADILHA DO OVERLOOK", color=(240, 175, 145), font_size=12, bold=True),
        "title": create_ui_label_texture("VOCÊ NÃO PODE SAIR", color=(235, 42, 42), font_size=30, bold=False, font_name="impact"),
    }
    toast_textures = {
        "BATTERY": create_ui_label_texture("+45% BATERIA RECARREGADA", color=(140, 255, 190), font_size=12, bold=True),
        "CORPSE_KIT": create_ui_label_texture("+75% BATERIA  •  KIT TÉRMICO", color=(140, 255, 190), font_size=12, bold=True),
        "CORPSE_MAP": create_ui_label_texture("MAPA REVELADO  •  +50% BATERIA", color=(150, 225, 255), font_size=12, bold=True),
        "CORPSE_TRAP": create_ui_label_texture("ARMADILHA! +30% BATERIA E MAPA", color=(255, 200, 120), font_size=11, bold=True),
    }
    campfire_badge_tex = create_ui_label_texture("ZONA SEGURA  •  AQUECENDO", color=(255, 212, 150), font_size=12, bold=True)
    active_toast_key = "BATTERY"
    active_toast_style = "BATTERY"
    
    fake_jacks = []
    next_fake_jack_ms = pygame.time.get_ticks() + 15000
    
    blood_decals = []
    corpses = []
    for cx, cy in corpse_cells:
        wx = (cx - MAP_WIDTH/2) * BLOCK_SIZE
        wz = (cy - MAP_HEIGHT/2) * BLOCK_SIZE
        corpses.append({'pos': (wx, wz), 'cell': (cx, cy), 'searched': False})
        
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
    # Comeca em uma celula aberta distante do jogador e da saida
    jack_pos = find_distant_open_cell(maze_map, MAP_WIDTH, MAP_HEIGHT, (1, 1), avoid_pos=exit_grid)
    jack_target_cell = jack_pos
    jack_wx = (jack_pos[0] - MAP_WIDTH / 2.0) * BLOCK_SIZE
    jack_wz = (jack_pos[1] - MAP_HEIGHT / 2.0) * BLOCK_SIZE
    jack_move_yaw = math.atan2((1 - MAP_HEIGHT / 2.0) * BLOCK_SIZE - jack_wz,
                               (1 - MAP_WIDTH / 2.0) * BLOCK_SIZE - jack_wx)
    base_jack_speed = {"FACIL": 2.3, "NORMAL": 3.0, "DIFICIL": 3.8}.get(diff_key, 3.0)
    jack_speed = base_jack_speed * (1.0 + 0.25 * madness)
    next_jack_move_ms  = pygame.time.get_ticks() + 10000   # 10s de graca
    jack_last_known_cell = None
    jack_patrol_goal = None
    jack_alerted = False
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

    # ---- Jumpscares 3D procedurais (sem PNGs 2D planos) ----

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

    # ---- Veios de Frio / Delirio nas Bordas da Tela ----
    FROST_CREEP_DUR_MS   = 4500    # duracao total da animacao
    frost_creep_active   = False
    frost_creep_start_ms = 0
    frost_veins          = []
    next_frost_creep_ms  = pygame.time.get_ticks() + random.randint(120000, 240000)

    def spawn_frost_veins():
        W, H = DISPLAY_SIZE
        veins = []
        edge_bias = [0, 1, 2, 3, 2, 3, 1]
        for i in range(22):
            side = random.choice(edge_bias)
            if side == 0:
                x, y = random.uniform(0.05 * W, 0.95 * W), 0.0
                ang = random.uniform(math.pi * 0.25, math.pi * 0.75)
            elif side == 1:
                x, y = random.uniform(0.05 * W, 0.95 * W), float(H)
                ang = random.uniform(-math.pi * 0.75, -math.pi * 0.25)
            elif side == 2:
                x, y = 0.0, random.uniform(0.08 * H, 0.95 * H)
                ang = random.uniform(-math.pi * 0.35, math.pi * 0.35)
            else:
                x, y = float(W), random.uniform(0.08 * H, 0.95 * H)
                ang = random.uniform(math.pi * 0.65, math.pi * 1.35)

            segs = random.randint(6, 10)
            step_len = random.uniform(16.0, 26.0)
            pts = [(x, y)]
            branches = []
            cur_ang = ang
            for s in range(segs):
                cur_ang += random.uniform(-0.42, 0.42)
                nx = x + math.cos(cur_ang) * step_len
                ny = y + math.sin(cur_ang) * step_len
                pts.append((nx, ny))
                if 1 <= s <= segs - 2 and random.random() < 0.45:
                    b_ang = cur_ang + random.choice((-1, 1)) * random.uniform(0.45, 0.85)
                    bx = nx + math.cos(b_ang) * step_len * 0.85
                    by = ny + math.sin(b_ang) * step_len * 0.85
                    branches.append(((nx, ny), (bx, by)))
                x, y = nx, ny

            veins.append({
                'pts': pts,
                'branches': branches,
                'delay': random.uniform(0.0, 0.22),
                'speed': random.uniform(0.85, 1.35),
                'width': random.uniform(1.2, 2.3),
                'blood': (madness > 0.55 or (i % 4 == 0 and anxiety > 0.5)),
            })
        return veins

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
    # JUMPSCARE_DUR_MS ja calculado acima (escala com madness)
    # Tipo de jumpscare 3D: 0=Jack, 1=Jack Flash, 2=Gemeas Grady, 3=Garra Congelada
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
    near_campfire = False

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
    light_yaw   = yaw
    light_pitch = pitch
    sway_x = 0.0
    sway_y = 0.0
    move_speed = BASE_SPEED
    mouse_sensitivity = _gs.mouse_sensitivity
    bob_time = 0.0
    minimap_timer_ms = 0
    visited_cells = {
        (vx, vy)
        for vy in range(max(0, 0), min(MAP_HEIGHT, 3))
        for vx in range(max(0, 0), min(MAP_WIDTH, 3))
    }

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
    eff = 1.0
    light_dir = (math.cos(yaw), 0.0, math.sin(yaw))
    jack_dist = math.hypot(player_pos[0] - jack_wx, player_pos[2] - jack_wz)
    pause_frozen_ms = pygame.time.get_ticks()
    t_s = pause_frozen_ms / 1000.0

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
    paused_total_ms = 0

    def _resume_from_pause():
        nonlocal paused, vol_mult
        paused = False
        vol_mult = (1.0 + madness * 1.5) * _gs.master_volume
        if wind_snd: wind_snd.set_volume(min(1.0, 0.25 * vol_mult))
        if drip_snd: drip_snd.set_volume(min(1.0, 0.6 * vol_mult))
        if click_snd: click_snd.set_volume(min(1.0, 0.8 * vol_mult))
        if battery_snd: battery_snd.set_volume(min(1.0, 0.8 * vol_mult))
        if grito_snd: grito_snd.set_volume(min(1.0, vol_mult))
        if scare_snd: scare_snd.set_volume(min(1.0, vol_mult))
        pygame.mixer.unpause()
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
        pygame.mouse.get_rel()

    try:
        while True:
            raw_dt_ms = clock.tick(60)
            dt = min(raw_dt_ms / 1000.0, 0.1)
            dt_step = dt * 60.0
            now_ms = pygame.time.get_ticks() - paused_total_ms
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
                            _resume_from_pause()
                        else:
                            paused = True
                            pause_frozen_ms = now_ms
                            pause_selected = 0
                            pause_exiting = False
                            pygame.mixer.pause()
                            pygame.mouse.set_visible(True)
                            pygame.event.set_grab(False)
                    elif event.key == K_e and not paused and not jumpscare_active:
                        # ---- Interação com Corpos ----
                        for c in corpses:
                            if not c['searched']:
                                dist = math.dist([player_pos[0], player_pos[2]], [c['pos'][0], c['pos'][1]])
                                if dist < BLOCK_SIZE * 1.5:
                                    c['searched'] = True
                                    stat_batteries_collected += 1
                                    battery_toast_timer_ms = now_ms + 3000
                                    res = resolve_corpse_search(
                                        maze_map, MAP_WIDTH, MAP_HEIGHT, c['cell'], exit_grid, visited_cells
                                    )
                                    battery = min(1.0, battery + res["battery_delta"])
                                    hypothermia = max(0.0, hypothermia + res["hypo_delta"])
                                    anxiety = max(0.0, min(1.0, anxiety + res["anxiety_delta"]))
                                    stamina = min(1.0, stamina + res["stamina_delta"])
                                    active_toast_key = res["toast_key"]
                                    active_toast_style = res["toast_style"]
                                    if res["minimap_ms"] > 0:
                                        minimap_timer_ms = max(minimap_timer_ms, now_ms + res["minimap_ms"])
                                    if res["jumpscare"]:
                                        jumpscare_active = True
                                        jumpscare_start_ms = now_ms
                                        js_effect_type = 3
                                        stat_jumpscares += 1
                                        if grito_snd:
                                            grito_snd.play()
                                    elif battery_snd:
                                        battery_snd.play()
                                    if res["flicker_ms"] > 0:
                                        flicker_off_until = max(flicker_off_until, now_ms + res["flicker_ms"])
                                    if res["alert_jack"]:
                                        jack_last_known_cell = c['cell']
                                        jack_alerted = True
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
                                _resume_from_pause()
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
                            pause_vol, pause_sens, _ = _apply_setting_change(
                                pause_settings_sel, -1, pause_vol, pause_sens, update_gl_proj=True
                            )
                            mouse_sensitivity = _gs.mouse_sensitivity
                        elif event.key == K_RIGHT:
                            pause_vol, pause_sens, _ = _apply_setting_change(
                                pause_settings_sel, 1, pause_vol, pause_sens, update_gl_proj=True
                            )
                            mouse_sensitivity = _gs.mouse_sensitivity
                        elif event.key in (K_RETURN, K_SPACE):
                            pause_vol, pause_sens, back = _apply_setting_change(
                                pause_settings_sel, 1, pause_vol, pause_sens, update_gl_proj=True
                            )
                            mouse_sensitivity = _gs.mouse_sensitivity
                            if back:
                                pause_in_settings = False
                                _gs.save_save_data()
                    elif not paused:
                        if event.key == K_m:
                            minimap_timer_ms = now_ms + 3000
                elif paused and not pause_exiting:
                    if event.type == MOUSEMOTION:
                        mx, my = event.pos
                        p_rects = _get_pause_menu_rects(DISPLAY_SIZE[0], DISPLAY_SIZE[1], pause_in_settings)
                        for idx, r in enumerate(p_rects):
                            if r.collidepoint(mx, my):
                                if pause_in_settings:
                                    pause_settings_sel = idx
                                else:
                                    pause_selected = idx
                                break
                    elif event.type == MOUSEBUTTONDOWN and event.button == 1:
                        mx, my = event.pos
                        p_rects = _get_pause_menu_rects(DISPLAY_SIZE[0], DISPLAY_SIZE[1], pause_in_settings)
                        for idx, r in enumerate(p_rects):
                            if r.collidepoint(mx, my):
                                if not pause_in_settings:
                                    pause_selected = idx
                                    if idx == 0:
                                        _resume_from_pause()
                                    elif idx == 1:
                                        pause_in_settings = True
                                        pause_vol = _gs.master_volume
                                        pause_sens = _gs.mouse_sensitivity * 1000.0
                                        pause_settings_sel = 0
                                    elif idx == 2:
                                        pause_exiting = True
                                        pause_exit_alpha = 0
                                else:
                                    pause_settings_sel = idx
                                    delta = -1 if (idx in (0, 1, 2, 3) and mx < r.centerx) else 1
                                    pause_vol, pause_sens, back = _apply_setting_change(
                                        idx, delta, pause_vol, pause_sens, update_gl_proj=True
                                    )
                                    mouse_sensitivity = _gs.mouse_sensitivity
                                    if back:
                                        pause_in_settings = False
                                        _gs.save_save_data()
                                break



            # ---- Processar Ecos Falsos ----
            for e_ms in fake_echoes[:]:
                if now_ms >= e_ms:
                    fake_echoes.remove(e_ms)
                    if footstep_snd:
                        footstep_snd.set_volume(min(1.0, (0.02 + anxiety * 0.05) * _gs.master_volume))
                        footstep_snd.play()

            # ---- Pausa: cena congelada completa + overlay ----
            if paused:
                paused_total_ms += raw_dt_ms
                pygame.mouse.get_rel()
                glClearColor(*fog_color)
                glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
                glLoadIdentity()
                cam_pos = (player_pos[0], player_pos[1] + bob_offset, player_pos[2])
                gluLookAt(cam_pos[0], cam_pos[1], cam_pos[2],
                          look_x, look_y + bob_offset, look_z, 0, 1, 0)
                glLightfv(GL_LIGHT0, GL_POSITION, (cam_pos[0], cam_pos[1], cam_pos[2], 1.0))
                glLightfv(GL_LIGHT0, GL_SPOT_DIRECTION, light_dir)
                glLightfv(GL_LIGHT1, GL_POSITION, (player_pos[0], player_pos[1] - 0.4, player_pos[2], 1.0))
                _update_nearest_campfire_light(player_pos[0], player_pos[2], campfires,
                                               pause_frozen_ms / 1000.0, _gs.photosensitivity_mode)

                draw_skybox(tex_skybox, player_pos[0], player_pos[1], player_pos[2])
                draw_floor(tex_snow, MAP_WIDTH, MAP_HEIGHT)
                draw_maze_optimized(maze_chunks, cam_pos, max_dist=60.0)
                draw_blood_trails(blood_decals)
                for c in corpses:
                    draw_corpse(
                        tex_corpse, c['pos'][0], c['pos'][1],
                        cam_pos=cam_pos, now_ms=pause_frozen_ms, searched=c['searched'],
                    )
                draw_footprints(now_ms=pause_frozen_ms)
                _draw_wall_texts(wall_text_data, wall_text_textures, madness, pause_frozen_ms / 1000.0)
                draw_exit(maze_map, MAP_WIDTH, MAP_HEIGHT, cam_pos=cam_pos, now_ms=pause_frozen_ms)
                draw_campfires(campfires, cam_pos=cam_pos, now_ms=pause_frozen_ms)
                for b in battery_pickups:
                    if not b['collected']:
                        draw_battery_pickup(b['pos'][0], b['pos'][1], pause_frozen_ms)
                draw_flashlight_volumetric_shaft(cam_pos, light_dir, eff, blizzard_intensity)
                draw_jack_shadow(jack_wx, jack_wz, jack_dist, madness, now_ms=pause_frozen_ms)
                draw_jack_billboard(
                    tex_jack, jack_wx, jack_wz, player_pos[0], player_pos[2],
                    jack_dist, madness, pause_frozen_ms, is_fake=False,
                    move_yaw=(jack_move_yaw if pause_frozen_ms >= next_jack_move_ms else None),
                )
                for fj in fake_jacks:
                    fj_wx, fj_wz = fj['pos']
                    fj_dist = math.dist([player_pos[0], player_pos[2]], [fj_wx, fj_wz])
                    draw_jack_shadow(fj_wx, fj_wz, fj_dist, madness, now_ms=pause_frozen_ms)
                    draw_jack_billboard(tex_jack, fj_wx, fj_wz, player_pos[0], player_pos[2],
                                        fj_dist, madness, pause_frozen_ms, is_fake=True)
                draw_particles(player_pos[0], player_pos[2], dt=0.0, blizzard_intensity=blizzard_intensity)
                draw_viewmodel_flashlight(flashlight_on, eff, sway_x, sway_y, bob_offset, pause_frozen_ms)
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

            # Inercia suave da lanterna (weapon sway + atraso realista do facho)
            sway_decay = max(0.0, 1.0 - 0.18 * dt_step)
            sway_x = max(-0.045, min(0.045, sway_x * sway_decay - dx * 0.00055))
            sway_y = max(-0.035, min(0.035, sway_y * sway_decay - dy_eff * 0.00045))
            lag_alpha = min(1.0, 0.24 * dt_step)
            light_yaw += (yaw - light_yaw) * lag_alpha
            light_pitch += (pitch - light_pitch) * lag_alpha

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

            move_dx = 0.0
            move_dz = 0.0
            if keys[pygame.K_w] or keys[pygame.K_UP]:
                move_dx += front_x; move_dz += front_z
            if keys[pygame.K_s] or keys[pygame.K_DOWN]:
                move_dx -= front_x; move_dz -= front_z
            if keys[pygame.K_a] or keys[pygame.K_LEFT]:
                move_dx -= right_x; move_dz -= right_z
            if keys[pygame.K_d] or keys[pygame.K_RIGHT]:
                move_dx += right_x; move_dz += right_z

            move_len = math.hypot(move_dx, move_dz)
            is_moving = move_len > 1e-5
            if is_moving:
                new_x += (move_dx / move_len) * effective_speed
                new_z += (move_dz / move_len) * effective_speed

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

            # 2. Escuridão total (lanterna apagada) aumenta ansiedade; ficar parado no escuro alivia a punição
            if not flashlight_on:
                dark_mult = 0.45 if not is_moving else 0.95
                anxiety = min(1.0, anxiety + ANXIETY_RISE * dark_mult * dt_step)

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
                js_effect_type = 3 # Garra congelada 3D
                stat_jumpscares += 1
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
                    maze_map[fake_exit_cell[1]][fake_exit_cell[0]] = 5  # Fecha o portão de ferro da armadilha
                    battery = 0.0  # Apaga a lanterna (Escuro Absoluto)
                    anxiety = 1.0  # Pânico Total
                    trap_text_timer_ms = now_ms + 3200
                    stat_jumpscares += 1
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
                        active_toast_key = "BATTERY"
                        active_toast_style = "BATTERY"
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

            # Revela celulas exploradas no minimapa (Fog of War)
            reveal_r = 2 if (flashlight_on and battery > 0.02) else 1
            for ry in range(-reveal_r, reveal_r + 1):
                for rx in range(-reveal_r, reveal_r + 1):
                    if reveal_r == 2 and rx * rx + ry * ry > 5:
                        continue
                    if reveal_r == 1 and abs(rx) + abs(ry) > 1:
                        continue
                    vx, vy = player_grid[0] + rx, player_grid[1] + ry
                    if 0 <= vx < MAP_WIDTH and 0 <= vy < MAP_HEIGHT:
                        visited_cells.add((vx, vy))

            # Resolução de Bloqueio da IA na Saída (Modo FLEE vs CHASE vs PATROL)
            EXIT_ZONE_DIST = BLOCK_SIZE * 6.5
            player_in_exit_zone = dist_exit < EXIT_ZONE_DIST
            jack_dist = math.hypot(player_pos[0] - jack_wx, player_pos[2] - jack_wz)

            if not player_in_exit_zone and now_ms >= next_jack_move_ms:
                light_active = flashlight_on and battery > 0.02 and now_ms >= flicker_off_until
                los_far = has_line_of_sight(maze_map, MAP_WIDTH, MAP_HEIGHT, jack_pos, player_grid, max_cells=15)
                los_close = has_line_of_sight(maze_map, MAP_WIDTH, MAP_HEIGHT, jack_pos, player_grid, max_cells=4)
                detected = (
                    (light_active and (jack_dist < BLOCK_SIZE * 10.5 or los_far))
                    or (sprinting and is_moving and jack_dist < BLOCK_SIZE * 8.5)
                    or (jack_dist < BLOCK_SIZE * 2.6 or los_close)
                )
                if detected:
                    jack_last_known_cell = player_grid
                    jack_alerted = True

            if now_ms >= next_jack_move_ms:
                tx = (jack_target_cell[0] - MAP_WIDTH / 2.0) * BLOCK_SIZE
                tz = (jack_target_cell[1] - MAP_HEIGHT / 2.0) * BLOCK_SIZE
                jdx = tx - jack_wx
                jdz = tz - jack_wz
                jdist_wp = math.hypot(jdx, jdz)
                if jdist_wp < 0.15:
                    jack_pos = jack_target_cell
                    nxt = None
                    if player_in_exit_zone:
                        # Modo FLEE: Jack recua em direcao a celula aberta mais distante da saida
                        jack_alerted = False
                        jack_last_known_cell = None
                        retreat_goal = find_distant_open_cell(
                            maze_map, MAP_WIDTH, MAP_HEIGHT, exit_grid, avoid_pos=player_grid
                        )
                        nxt = bfs_next_step(maze_map, MAP_WIDTH, MAP_HEIGHT, jack_pos, retreat_goal)
                    elif jack_last_known_cell is not None and jack_pos != jack_last_known_cell:
                        # Modo CHASE / INVESTIGATE: vai ate a ultima posicao vista/ouvida
                        nxt = bfs_next_step(maze_map, MAP_WIDTH, MAP_HEIGHT, jack_pos, jack_last_known_cell)
                    else:
                        # Modo PATROL: jogador apagou a lanterna e saiu da linha de visao
                        jack_last_known_cell = None
                        jack_alerted = False
                        if jack_patrol_goal is None or jack_pos == jack_patrol_goal:
                            patrol_cands = [
                                c for c in empty_cells
                                if abs(c[0] - jack_pos[0]) + abs(c[1] - jack_pos[1]) >= 6
                            ]
                            if patrol_cands:
                                jack_patrol_goal = random.choice(patrol_cands)
                            else:
                                jack_patrol_goal = find_distant_open_cell(
                                    maze_map, MAP_WIDTH, MAP_HEIGHT, jack_pos, avoid_pos=exit_grid
                                )
                        nxt = bfs_next_step(maze_map, MAP_WIDTH, MAP_HEIGHT, jack_pos, jack_patrol_goal)
                        if nxt is None:
                            jack_patrol_goal = None
                    if nxt:
                        jack_target_cell = nxt
                        tx = (jack_target_cell[0] - MAP_WIDTH / 2.0) * BLOCK_SIZE
                        tz = (jack_target_cell[1] - MAP_HEIGHT / 2.0) * BLOCK_SIZE
                        jdx = tx - jack_wx
                        jdz = tz - jack_wz
                        jdist_wp = math.hypot(jdx, jdz)
                if jdist_wp > 1e-4:
                    speed_factor = 1.25 if player_in_exit_zone else (1.0 if jack_alerted else 0.76)
                    cur_j_speed = jack_speed * speed_factor
                    step_m = min(jdist_wp, cur_j_speed * dt)
                    jack_wx += (jdx / jdist_wp) * step_m
                    jack_wz += (jdz / jdist_wp) * step_m
                    jack_move_yaw = math.atan2(jdz, jdx)

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
                    jack_pos = find_distant_open_cell(
                        maze_map, MAP_WIDTH, MAP_HEIGHT, exit_grid, avoid_pos=player_grid
                    )
                    jack_target_cell = jack_pos
                    jack_wx = (jack_pos[0] - MAP_WIDTH / 2.0) * BLOCK_SIZE
                    jack_wz = (jack_pos[1] - MAP_HEIGHT / 2.0) * BLOCK_SIZE
                    jack_dist = math.hypot(player_pos[0] - jack_wx, player_pos[2] - jack_wz)
                    jack_last_known_cell = None
                    jack_patrol_goal = None
                    jack_alerted = False
                    next_jack_move_ms = now_ms + 12000
            else:
                # Jack captura o jogador fora da zona de saída
                if jack_dist < BLOCK_SIZE * 1.8 and not jumpscare_active:
                    jumpscare_active   = True
                    jumpscare_start_ms = now_ms
                    js_effect_type     = random.choice([0, 1])
                    stat_jumpscares   += 1
                    if grito_snd: grito_snd.play()
                    anxiety = min(1.0, anxiety + 0.5)  # Sobe ansiedade sem forçar 1.0 direto
                    # Reinicia Jack longe em celula aberta valida
                    jack_pos = find_distant_open_cell(
                        maze_map, MAP_WIDTH, MAP_HEIGHT, player_grid, avoid_pos=exit_grid
                    )
                    jack_target_cell = jack_pos
                    jack_wx = (jack_pos[0] - MAP_WIDTH / 2.0) * BLOCK_SIZE
                    jack_wz = (jack_pos[1] - MAP_HEIGHT / 2.0) * BLOCK_SIZE
                    jack_dist = math.hypot(player_pos[0] - jack_wx, player_pos[2] - jack_wz)
                    jack_last_known_cell = None
                    jack_patrol_goal = None
                    jack_alerted = False
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

            # ---- Jumpscare por zona (nao perto da saida) ----
            cur_cell = (int(math.floor((player_pos[0] / BLOCK_SIZE) + MAP_WIDTH / 2.0 + 0.5)),
                        int(math.floor((player_pos[2] / BLOCK_SIZE) + MAP_HEIGHT / 2.0 + 0.5)))
            if cur_cell in trigger_zones and cur_cell not in triggered_zones and dist_exit > BLOCK_SIZE * 6:
                triggered_zones.add(cur_cell)
                jumpscare_active   = True
                jumpscare_start_ms = now_ms
                stat_jumpscares += 1
                # Tipo 3D varia com loucura: 0=Jack, 1=Jack Flash, 2=Gemeas Grady, 3=Garra Congelada
                if madness < 0.2:
                    js_effect_type = 0
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

            # ---- Veios de Frio / Delirio nas Bordas ----
            if not frost_creep_active and now_ms >= next_frost_creep_ms:
                frost_creep_active   = True
                frost_creep_start_ms = now_ms
                frost_veins          = spawn_frost_veins()
                next_frost_creep_ms  = now_ms + random.randint(
                    max(90000, 180000 - cc * 12000),
                    max(120000, 260000 - cc * 18000)
                )

            if frost_creep_active and now_ms - frost_creep_start_ms > FROST_CREEP_DUR_MS:
                frost_creep_active = False
                frost_veins        = []

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
            maybe_add_footprint(player_pos[0], player_pos[2], yaw, is_moving, now_ms=now_ms)

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
                run_time = (now_ms - run_start_ms) / 1000.0
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
                run_time = (now_ms - run_start_ms) / 1000.0
                return ("END", run_time, stat_distance, stat_jumpscares, stat_peak_anxiety, stat_batteries_collected)
            elif not col_x:
                player_pos[0] = new_x

            col_z = check_collision(player_pos[0], new_z, radius=0.35)
            if col_z == "EXIT":
                pygame.mixer.stop()
                run_time = (now_ms - run_start_ms) / 1000.0
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

            # Iluminação posicionada no espaço de visão da câmera (com atraso suave do facho)
            look_dir = (look_x - player_pos[0], look_y - player_pos[1], look_z - player_pos[2])
            light_dx = math.cos(light_pitch + shake_pitch) * math.cos(light_yaw + shake_yaw)
            light_dy = math.sin(light_pitch + shake_pitch)
            light_dz = math.cos(light_pitch + shake_pitch) * math.sin(light_yaw + shake_yaw)
            light_dir = (light_dx, light_dy, light_dz)
            glLightfv(GL_LIGHT0, GL_POSITION, (cam_pos[0], cam_pos[1], cam_pos[2], 1.0))
            glLightfv(GL_LIGHT0, GL_SPOT_DIRECTION, light_dir)
            glLightfv(GL_LIGHT1, GL_POSITION, (player_pos[0], player_pos[1] - 0.4, player_pos[2], 1.0))

            # Luz dinamica da fogueira mais proxima (< 18m)
            _update_nearest_campfire_light(player_pos[0], player_pos[2], campfires, t_s, _gs.photosensitivity_mode)

            # 1. Desenha o Skybox no fundo de tudo
            draw_skybox(tex_skybox, player_pos[0], player_pos[1], player_pos[2])

            # 2. Desenha o chão de neve contínuo
            draw_floor(tex_snow, MAP_WIDTH, MAP_HEIGHT)

            # 3. Renderiza o labirinto otimizado com Frustum Culling e Hidden Face Removal
            draw_maze_optimized(maze_chunks, cam_pos, max_dist=60.0)
            draw_blood_trails(blood_decals)
            for c in corpses:
                draw_corpse(
                    tex_corpse, c['pos'][0], c['pos'][1],
                    cam_pos=cam_pos, now_ms=now_ms, searched=c['searched'],
                )
            draw_footprints(now_ms=now_ms)

            # 2b. Textos nas paredes (surgem conforme madness)
            _draw_wall_texts(wall_text_data, wall_text_textures, madness, t_s)

            # 4. Saída animada
            draw_exit(maze_map, MAP_WIDTH, MAP_HEIGHT, cam_pos=cam_pos, now_ms=now_ms)
            draw_campfires(campfires, cam_pos=cam_pos, now_ms=now_ms)

            # 4b. Pickups 3D de Bateria
            for b in battery_pickups:
                if not b['collected']:
                    draw_battery_pickup(b['pos'][0], b['pos'][1], now_ms)

            # Cone volumétrico e feixes de luz da lanterna (Spotlight + Shafts)
            draw_flashlight_volumetric_shaft(cam_pos, light_dir, eff, blizzard_intensity)

            # 3. Desenha o Jack (e os Falsos Jacks) em 3D articulado com sombra projetada
            draw_jack_shadow(jack_wx, jack_wz, jack_dist, madness, now_ms=now_ms)
            draw_jack_billboard(
                tex_jack, jack_wx, jack_wz, player_pos[0], player_pos[2],
                jack_dist, madness, now_ms, is_fake=False,
                move_yaw=(jack_move_yaw if now_ms >= next_jack_move_ms else None),
            )
            for fj in fake_jacks:
                fj_wx, fj_wz = fj['pos']
                fj_dist = math.dist([player_pos[0], player_pos[2]], [fj_wx, fj_wz])
                draw_jack_shadow(fj_wx, fj_wz, fj_dist, madness, now_ms=now_ms)
                draw_jack_billboard(tex_jack, fj_wx, fj_wz, player_pos[0], player_pos[2], fj_dist, madness, now_ms, is_fake=True)

            # 4. Partículas e Bafadas de Frio (billboards)
            draw_particles(player_pos[0], player_pos[2], dt, blizzard_intensity=blizzard_intensity)
            draw_ceiling_drips(blood_drip_zones, now_ms)

            # 5b. Bafadas de Frio (billboards)
            draw_breath_puffs(breath_puffs, now_ms, yaw)

            # 5b-2. Lanterna tatica 3D em primeira pessoa (com weapon sway)
            if not jumpscare_active:
                draw_viewmodel_flashlight(flashlight_on, eff, sway_x, sway_y, bob_offset, now_ms)

            # 5c. Aberração Cromática (efeito de alucinação em alta ansiedade)
            if anxiety > 0.6 and not _gs.photosensitivity_mode:
                draw_chromatic_aberration((anxiety - 0.6) / 0.4)


            # 5. Overlays 2D (HUD)
            toast_remaining = battery_toast_timer_ms - now_ms
            toast_alpha = max(0.0, min(1.0, toast_remaining / 400.0)) if toast_remaining > 0 else 0.0
            draw_anxiety_hud(
                anxiety, battery, stamina=stamina, hypothermia=hypothermia,
                blood_overlay_timer=blood_overlay_timer,
                flashlight_on=flashlight_on, battery_toast_alpha=toast_alpha,
                near_campfire=near_campfire, toast_style=active_toast_style,
                now_ms=now_ms,
            )

            # ---- Prompt de Interação ----
            near_unsearched = False
            for c in corpses:
                if not c['searched']:
                    c_dist = math.dist([player_pos[0], player_pos[2]], [c['pos'][0], c['pos'][1]])
                    if c_dist < BLOCK_SIZE * 1.5:
                        near_unsearched = True
                        break

            _draw_hud_badges_and_prompt(
                toast_alpha, toast_textures.get(active_toast_key),
                near_campfire, campfire_badge_tex,
                near_unsearched, prompt_e_textures, now_ms,
            )

            # 6b. Minimapa com Fog of War
            if now_ms < minimap_timer_ms:
                draw_minimap(
                    maze_map, MAP_WIDTH, MAP_HEIGHT, player_pos[0], player_pos[2],
                    yaw=yaw, visited_cells=visited_cells, campfires=campfires,
                    corpses=corpses, jack_dist=jack_dist, now_ms=now_ms,
                )

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
                _draw_trap_banner(
                    trap_banner_textures, trap_text_timer_ms - now_ms,
                    now_ms, _gs.photosensitivity_mode,
                )

            elif jumpscare_active:
                js_age = (now_ms - jumpscare_start_ms) / max(JUMPSCARE_DUR_MS, 1)
                draw_jumpscare_3d(js_effect_type, js_age, madness, now_ms, _gs.photosensitivity_mode)

            # 8. Veios organicos de frio / delirio nas bordas da tela
            if frost_creep_active and frost_veins:
                creep_age = (now_ms - frost_creep_start_ms) / FROST_CREEP_DUR_MS
                W2b, H2b = DISPLAY_SIZE

                glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
                glOrtho(0, W2b, H2b, 0, -1, 1)
                glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_LINE_BIT)
                glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST)
                glDisable(GL_TEXTURE_2D)
                glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

                for v in frost_veins:
                    t_raw = (creep_age - v['delay']) / max(1.0 - v['delay'], 0.01)
                    t = max(0.0, min(t_raw * v['speed'], 1.0))
                    if t <= 0.0:
                        continue
                    grow = min(1.0, t / 0.55)
                    fade = 1.0 if t < 0.72 else max(0.0, 1.0 - (t - 0.72) / 0.28)
                    alpha = fade * (0.78 if v['blood'] else 0.72)
                    if alpha <= 0.01:
                        continue

                    pts = v['pts']
                    max_seg = max(1, int(math.ceil(grow * (len(pts) - 1))))
                    cr, cg, cb = (0.55, 0.05, 0.07) if v['blood'] else (0.76, 0.90, 0.98)

                    glLineWidth(v['width'])
                    glBegin(GL_LINE_STRIP)
                    for idx in range(min(len(pts), max_seg + 1)):
                        p_fade = max(0.0, 1.0 - (idx / float(max(1, len(pts) - 1))) * 0.65)
                        glColor4f(cr, cg, cb, alpha * p_fade)
                        glVertex2f(pts[idx][0], pts[idx][1])
                    glEnd()

                    if grow > 0.35 and v['branches']:
                        glLineWidth(max(1.0, v['width'] * 0.65))
                        glBegin(GL_LINES)
                        for b0, b1 in v['branches']:
                            glColor4f(cr, cg, cb, alpha * 0.55)
                            glVertex2f(b0[0], b0[1])
                            glColor4f(cr, cg, cb, 0.0)
                            glVertex2f(b1[0], b1[1])
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
        cleanup_floor_display_list()
        try:
            if 'maze_chunks' in locals() and maze_chunks:
                for ch in maze_chunks:
                    glDeleteLists(ch['dlist'], 1)
        except Exception:
            pass
        for tid in [tex_hedge, tex_snow, tex_skybox]:
            if tid:
                try: glDeleteTextures([tid])
                except Exception: pass
        if 'wall_text_textures' in locals():
            for item in wall_text_textures.values():
                try: glDeleteTextures([item[0]])
                except Exception: pass
        for tex_dict in (toast_textures, prompt_e_textures, trap_banner_textures):
            for item in tex_dict.values():
                if item:
                    try: glDeleteTextures([item[0]])
                    except Exception: pass
        if campfire_badge_tex:
            try: glDeleteTextures([campfire_badge_tex[0]])
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
