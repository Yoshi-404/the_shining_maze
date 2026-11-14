import math
import numpy as np
import pygame
from OpenGL.GL import *
from OpenGL.GLU import *
from .settings import BLOCK_SIZE, WALL_HEIGHT, DISPLAY_SIZE

# ---------------------------------------------------------------------------
# Geometria do cubo unitário
# ---------------------------------------------------------------------------
_VERTICES = (
    (1,-1,-1),(1,1,-1),(-1,1,-1),(-1,-1,-1),
    (1,-1, 1),(1,1, 1),(-1,-1, 1),(-1,1, 1),
)
_SURFACES = (
    (0,1,2,3),(3,2,7,6),(6,7,5,4),(4,5,1,0),(1,5,7,2),(4,0,3,6),
)
_NORMALS = (
    (0,0,-1),(-1,0,0),(0,0,1),(1,0,0),(0,1,0),(0,-1,0),
)
_UV = ((0,0),(1,0),(1,1),(0,1))


# ---------------------------------------------------------------------------
# Carregamento de textura
# ---------------------------------------------------------------------------
def load_texture(path: str) -> int | None:
    try:
        surf = pygame.image.load(path)
        data = pygame.image.tostring(surf, "RGBA", 1)
        w, h = surf.get_width(), surf.get_height()
        tid  = glGenTextures(1)
        glBindTexture(GL_TEXTURE_2D, tid)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_REPEAT)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR)
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR)
        glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA, w, h, 0, GL_RGBA, GL_UNSIGNED_BYTE, data)
        return tid
    except Exception as e:
        print(f"[renderer] Textura '{path}': {e}")
        return None


# ---------------------------------------------------------------------------
# Iluminação (lanterna spotlight)
# ---------------------------------------------------------------------------
def setup_lighting():
    glEnable(GL_LIGHTING)
    # Modelo de luz global: reduz a luz ambiente global de 0.20 padrão para 0.015 (escuridão realista de terror)
    glLightModelfv(GL_LIGHT_MODEL_AMBIENT, (0.015, 0.018, 0.025, 1.0))

    # LIGHT0: Foco principal potente da lanterna (Spotlight de alto contraste)
    glEnable(GL_LIGHT0)
    glLightfv(GL_LIGHT0, GL_AMBIENT,  (0.002, 0.003, 0.005, 1.0))
    glLightfv(GL_LIGHT0, GL_DIFFUSE,  (2.2, 2.15, 2.3, 1.0))
    glLightfv(GL_LIGHT0, GL_SPECULAR, (1.2, 1.2, 1.3, 1.0))
    glLightf (GL_LIGHT0, GL_SPOT_CUTOFF,   30.0)
    glLightf (GL_LIGHT0, GL_SPOT_EXPONENT, 18.0)
    glLightf (GL_LIGHT0, GL_CONSTANT_ATTENUATION, 0.8)
    glLightf (GL_LIGHT0, GL_LINEAR_ATTENUATION, 0.035)
    glLightf (GL_LIGHT0, GL_QUADRATIC_ATTENUATION, 0.003)

    # LIGHT1: Rebote suave ao redor dos pés do jogador
    glEnable(GL_LIGHT1)
    glLightfv(GL_LIGHT1, GL_AMBIENT,  (0.002, 0.003, 0.005, 1.0))
    glLightfv(GL_LIGHT1, GL_DIFFUSE,  (0.06, 0.06, 0.08, 1.0))
    glLightf (GL_LIGHT1, GL_SPOT_CUTOFF, 180.0)
    glLightf (GL_LIGHT1, GL_CONSTANT_ATTENUATION, 1.0)
    glLightf (GL_LIGHT1, GL_LINEAR_ATTENUATION, 0.3)
    glLightf (GL_LIGHT1, GL_QUADRATIC_ATTENUATION, 0.2)

    # LIGHT2: Luz pontual quente da fogueira mais próxima (ativada dinamicamente por proximidade)
    glLightfv(GL_LIGHT2, GL_AMBIENT,  (0.02, 0.01, 0.0, 1.0))
    glLightfv(GL_LIGHT2, GL_DIFFUSE,  (1.15, 0.55, 0.12, 1.0))
    glLightfv(GL_LIGHT2, GL_SPECULAR, (0.60, 0.30, 0.08, 1.0))
    glLightf (GL_LIGHT2, GL_SPOT_CUTOFF, 180.0)
    glLightf (GL_LIGHT2, GL_CONSTANT_ATTENUATION, 0.7)
    glLightf (GL_LIGHT2, GL_LINEAR_ATTENUATION, 0.18)
    glLightf (GL_LIGHT2, GL_QUADRATIC_ATTENUATION, 0.06)
    glDisable(GL_LIGHT2)

    glEnable(GL_COLOR_MATERIAL)
    glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)


# ---------------------------------------------------------------------------
# Neblina volumétrica
# ---------------------------------------------------------------------------
def setup_fog() -> tuple:
    fog_color = (0.012, 0.018, 0.032, 1.0)
    glEnable(GL_FOG)
    glFogi(GL_FOG_MODE, GL_EXP2)
    glFogfv(GL_FOG_COLOR, fog_color)
    glFogf(GL_FOG_DENSITY, 0.10)
    glHint(GL_FOG_HINT, GL_NICEST)
    return fog_color


# ---------------------------------------------------------------------------
# Primitivas 3D reutilizáveis
# ---------------------------------------------------------------------------
def _draw_box(sx, sy, sz):
    """Desenha um paralelepípedo centrado na origem com dimensões (sx, sy, sz)."""
    hx, hy, hz = sx * 0.5, sy * 0.5, sz * 0.5
    glBegin(GL_QUADS)
    for i, face in enumerate(_SURFACES):
        glNormal3fv(_NORMALS[i])
        for v in face:
            vx, vy, vz = _VERTICES[v]
            glVertex3f(vx * hx, vy * hy, vz * hz)
    glEnd()


def _draw_cylinder(r_bot, r_top, height, sides=10):
    """Desenha cilindro/tronco de cone ao longo de +Y (0 até height) com tampas."""
    angles = [2.0 * math.pi * i / sides for i in range(sides + 1)]
    slope_y = (r_bot - r_top) / max(height, 1e-4)

    glBegin(GL_QUAD_STRIP)
    for th in angles:
        c, s = math.cos(th), math.sin(th)
        n_len = math.sqrt(c * c + slope_y * slope_y + s * s) or 1.0
        glNormal3f(c / n_len, slope_y / n_len, s / n_len)
        glVertex3f(c * r_top, height, s * r_top)
        glVertex3f(c * r_bot, 0.0, s * r_bot)
    glEnd()

    if r_bot > 0.0:
        glBegin(GL_TRIANGLE_FAN)
        glNormal3f(0.0, -1.0, 0.0)
        glVertex3f(0.0, 0.0, 0.0)
        for th in angles:
            glVertex3f(math.cos(th) * r_bot, 0.0, math.sin(th) * r_bot)
        glEnd()

    if r_top > 0.0:
        glBegin(GL_TRIANGLE_FAN)
        glNormal3f(0.0, 1.0, 0.0)
        glVertex3f(0.0, height, 0.0)
        for th in reversed(angles):
            glVertex3f(math.cos(th) * r_top, height, math.sin(th) * r_top)
        glEnd()


def _draw_ellipsoid(rx, ry, rz, slices=10, stacks=6):
    """Desenha um elipsoide centrado na origem com normais suaves."""
    for i in range(stacks):
        lat0 = math.pi * (-0.5 + i / stacks)
        lat1 = math.pi * (-0.5 + (i + 1) / stacks)
        z0, zr0 = math.sin(lat0), math.cos(lat0)
        z1, zr1 = math.sin(lat1), math.cos(lat1)

        glBegin(GL_QUAD_STRIP)
        for j in range(slices + 1):
            lng = 2.0 * math.pi * j / slices
            x, y = math.cos(lng), math.sin(lng)
            glNormal3f(x * zr0, z0, y * zr0)
            glVertex3f(x * zr0 * rx, z0 * ry, y * zr0 * rz)
            glNormal3f(x * zr1, z1, y * zr1)
            glVertex3f(x * zr1 * rx, z1 * ry, y * zr1 * rz)
        glEnd()


def _draw_colonial_lantern_frame():
    """Desenha a estrutura metálica estática (tampa e base) de uma lanterna colonial."""
    glColor3f(0.10, 0.10, 0.12)
    glPushMatrix()
    glTranslatef(0.0, 0.14, 0.0)
    _draw_cylinder(0.13, 0.04, 0.09, sides=6)
    glPopMatrix()

    glPushMatrix()
    glTranslatef(0.0, -0.14, 0.0)
    _draw_cylinder(0.07, 0.11, 0.05, sides=6)
    glPopMatrix()


def _draw_colonial_lantern(glow_rgb=(1.0, 0.35, 0.16), pulse=1.0):
    """Desenha uma lanterna colonial 3D pendente com núcleo luminoso."""
    _draw_colonial_lantern_frame()

    glPushAttrib(GL_ENABLE_BIT)
    glDisable(GL_LIGHTING)
    glColor3f(glow_rgb[0] * pulse, glow_rgb[1] * pulse, glow_rgb[2] * pulse)
    glPushMatrix()
    glTranslatef(0.0, -0.09, 0.0)
    _draw_cylinder(0.08, 0.09, 0.23, sides=6)
    glPopMatrix()
    glPopAttrib()


_floor_dlist = None
_floor_cache_key = None
_exit_arch_dlist = None
_exit_iron_gate_dlist = None
_campfire_base_dlist = None
_corpse_body_dlist = None
_exit_cells_cache = None


def _get_exit_iron_gate_dlist():
    global _exit_iron_gate_dlist
    if _exit_iron_gate_dlist is None:
        _exit_iron_gate_dlist = glGenLists(1)
        glNewList(_exit_iron_gate_dlist, GL_COMPILE)
        glColor3f(0.11, 0.12, 0.14)
        for ry in (-0.25, 0.60, 1.45):
            glPushMatrix()
            glTranslatef(0.0, ry, 0.0)
            _draw_box(1.36, 0.065, 0.075)
            glPopMatrix()
        for i in range(-3, 4):
            bx = i * 0.18
            glPushMatrix()
            glTranslatef(bx, 0.55, 0.0)
            _draw_box(0.045, 2.95, 0.045)
            glPopMatrix()
            glPushMatrix()
            glTranslatef(bx, 1.92, 0.0)
            _draw_cylinder(0.035, 0.0, 0.14, sides=5)
            glPopMatrix()
        glColor3f(0.28, 0.20, 0.10)
        glPushMatrix()
        glTranslatef(0.0, 0.25, 0.0)
        _draw_box(0.18, 0.22, 0.10)
        glPopMatrix()
        glEndList()
    return _exit_iron_gate_dlist


def _get_exit_arch_dlist():
    global _exit_arch_dlist
    if _exit_arch_dlist is None:
        _exit_arch_dlist = glGenLists(1)
        glNewList(_exit_arch_dlist, GL_COMPILE)
        for side in (-1.0, 1.0):
            px = side * 0.80
            glColor3f(0.22, 0.22, 0.25)
            glPushMatrix()
            glTranslatef(px, -0.82, 0.0)
            _draw_box(0.40, 0.36, 0.44)
            glPopMatrix()

            glColor3f(0.18, 0.12, 0.09)
            glPushMatrix()
            glTranslatef(px, 0.78, 0.0)
            _draw_box(0.28, 2.85, 0.32)
            glPopMatrix()

            glColor3f(0.12, 0.12, 0.14)
            glPushMatrix()
            glTranslatef(side * 0.62, 1.50, 0.14)
            _draw_box(0.24, 0.05, 0.05)
            glPopMatrix()

            glPushMatrix()
            glTranslatef(side * 0.54, 1.32, 0.18)
            _draw_colonial_lantern_frame()
            glPopMatrix()

        glColor3f(0.16, 0.10, 0.08)
        glPushMatrix()
        glTranslatef(0.0, 2.26, 0.0)
        _draw_box(2.06, 0.36, 0.40)
        glPopMatrix()

        glColor3f(0.82, 0.87, 0.94)
        glPushMatrix()
        glTranslatef(0.0, 2.49, 0.0)
        _draw_box(2.10, 0.12, 0.44)
        glPopMatrix()
        glEndList()
    return _exit_arch_dlist


def _get_campfire_base_dlist():
    global _campfire_base_dlist
    if _campfire_base_dlist is None:
        _campfire_base_dlist = glGenLists(1)
        glNewList(_campfire_base_dlist, GL_COMPILE)
        glColor3f(0.28, 0.29, 0.32)
        for i in range(9):
            ang = 2.0 * math.pi * i / 9.0
            sx = math.cos(ang) * 0.42
            sz = math.sin(ang) * 0.42
            glPushMatrix()
            glTranslatef(sx, 0.06, sz)
            glRotatef(math.degrees(ang) * 2.0, 0.0, 1.0, 0.0)
            _draw_ellipsoid(0.11, 0.07, 0.09, slices=6, stacks=4)
            glPopMatrix()

        glColor3f(0.22, 0.13, 0.08)
        for i in range(4):
            glPushMatrix()
            glTranslatef(0.0, 0.09, 0.0)
            glRotatef(i * 45.0, 0.0, 1.0, 0.0)
            glRotatef(72.0, 1.0, 0.0, 0.0)
            glTranslatef(0.0, -0.26, 0.0)
            _draw_cylinder(0.055, 0.045, 0.52, sides=6)
            glPopMatrix()
        glEndList()
    return _campfire_base_dlist


def _get_corpse_body_dlist():
    global _corpse_body_dlist
    if _corpse_body_dlist is None:
        _corpse_body_dlist = glGenLists(1)
        glNewList(_corpse_body_dlist, GL_COMPILE)

        # 1. Poça de sangue congelado na neve (sem iluminação chapada, polígono irregular)
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(-2.0, -2.0)
        glBegin(GL_TRIANGLE_FAN)
        glColor4f(0.32, 0.02, 0.02, 0.88)
        glVertex3f(0.05, 0.01, 0.05)
        for i in range(15):
            th = 2.0 * math.pi * i / 14.0
            rad = 0.58 + 0.18 * math.sin(i * 2.7)
            glVertex3f(0.05 + math.cos(th) * rad, 0.01, 0.05 + math.sin(th) * rad * 0.85)
        glEnd()
        glDisable(GL_POLYGON_OFFSET_FILL)
        glDisable(GL_BLEND)

        # 2. Corpo 3D articulado caído na neve
        glEnable(GL_LIGHTING)

        # Tronco (parka azul-inverno)
        glColor3f(0.18, 0.30, 0.44)
        glPushMatrix()
        glTranslatef(0.0, 0.14, -0.05)
        glRotatef(12.0, 0.0, 0.0, 1.0)
        _draw_box(0.46, 0.24, 0.68)
        glPopMatrix()

        # Camada de neve acumulada sobre as costas
        glColor3f(0.76, 0.84, 0.92)
        glPushMatrix()
        glTranslatef(-0.02, 0.25, -0.04)
        _draw_ellipsoid(0.20, 0.06, 0.30, slices=8, stacks=4)
        glPopMatrix()

        # Capuz + cabeça tombada
        glColor3f(0.22, 0.34, 0.48)
        glPushMatrix()
        glTranslatef(0.04, 0.17, 0.38)
        _draw_ellipsoid(0.16, 0.15, 0.17, slices=8, stacks=5)
        glPopMatrix()

        glColor3f(0.62, 0.65, 0.72)
        glPushMatrix()
        glTranslatef(0.09, 0.15, 0.42)
        _draw_ellipsoid(0.10, 0.10, 0.11, slices=8, stacks=4)
        glPopMatrix()

        # Pernas dobradas e botas
        glColor3f(0.14, 0.16, 0.22)
        for sx, yaw_leg in ((-0.13, -12.0), (0.14, 18.0)):
            glPushMatrix()
            glTranslatef(sx, 0.10, -0.58)
            glRotatef(yaw_leg, 0.0, 1.0, 0.0)
            _draw_box(0.16, 0.15, 0.54)
            glColor3f(0.10, 0.07, 0.05)
            glTranslatef(0.0, 0.02, -0.30)
            _draw_box(0.15, 0.18, 0.22)
            glColor3f(0.14, 0.16, 0.22)
            glPopMatrix()

        # Braço direito estendido em direção à lanterna caída
        glColor3f(0.18, 0.30, 0.44)
        glPushMatrix()
        glTranslatef(0.32, 0.10, 0.24)
        glRotatef(-35.0, 0.0, 1.0, 0.0)
        _draw_box(0.13, 0.12, 0.48)
        glPopMatrix()

        # Mochila de expedição caída ao lado
        glColor3f(0.28, 0.22, 0.15)
        glPushMatrix()
        glTranslatef(-0.46, 0.15, 0.05)
        glRotatef(24.0, 0.0, 1.0, 0.0)
        _draw_box(0.28, 0.24, 0.38)
        glPopMatrix()

        # Corpo metálico da lanterna caída no chão
        glColor3f(0.16, 0.18, 0.20)
        glPushMatrix()
        glTranslatef(0.48, 0.05, 0.56)
        glRotatef(-42.0, 0.0, 1.0, 0.0)
        glRotatef(90.0, 1.0, 0.0, 0.0)
        _draw_cylinder(0.035, 0.048, 0.22, sides=8)
        glPopMatrix()

        glEndList()
    return _corpse_body_dlist


# ---------------------------------------------------------------------------
# Geometria
# ---------------------------------------------------------------------------
def draw_cube(x, y, z, tex_id, color=(1,1,1), is_tall=True):
    glPushMatrix()
    glTranslatef(x, y, z)
    if is_tall:
        glScalef(1, WALL_HEIGHT / 2, 1)
    if tex_id:
        glBindTexture(GL_TEXTURE_2D, tex_id)
    glBegin(GL_QUADS)
    glColor3fv(color)
    for i, face in enumerate(_SURFACES):
        glNormal3fv(_NORMALS[i])
        for j, v in enumerate(face):
            u, vt = _UV[j]
            if is_tall and i not in (4, 5):
                vt *= (WALL_HEIGHT / 2)
            glTexCoord2f(u, vt)
            glVertex3fv(_VERTICES[v])
    glEnd()
    glPopMatrix()


def draw_walls(maze_map, W, H, tex_hedge):
    for y in range(H):
        for x in range(W):
            if maze_map[y][x] == 1:
                draw_cube((x - W/2)*BLOCK_SIZE, WALL_HEIGHT/2 - 1,
                          (y - H/2)*BLOCK_SIZE, tex_hedge)


def draw_exit(maze_map, W, H, cam_pos=None, max_dist=38.0, now_ms=None):
    """Desenha as saídas (real e armadilha) como portais 3D em arco do Hotel Overlook."""
    global _exit_cells_cache
    if _exit_cells_cache is None or _exit_cells_cache[0] is not maze_map or _exit_cells_cache[1] != W or _exit_cells_cache[2] != H:
        cells = []
        for y in range(H):
            for x in range(W):
                if maze_map[y][x] in (2, 3, 5):
                    cx = (x - W / 2) * BLOCK_SIZE
                    cz = (y - H / 2) * BLOCK_SIZE
                    open_dx, open_dz = 0.0, 1.0
                    for dx, dy in ((0, 1), (0, -1), (1, 0), (-1, 0)):
                        nx, ny = x + dx, y + dy
                        if 0 <= nx < W and 0 <= ny < H and maze_map[ny][nx] not in (1, 5):
                            open_dx, open_dz = float(dx), float(dy)
                            break
                    gate_angle = math.degrees(math.atan2(open_dx, open_dz))
                    cells.append((x, y, cx, cz, gate_angle))
        _exit_cells_cache = (maze_map, W, H, cells)

    t = (pygame.time.get_ticks() if now_ms is None else now_ms) / 1000.0
    pulse = 0.72 + 0.28 * math.sin(t * 2.6)
    FLOOR_Y = -0.97
    max_dist_sq = max_dist * max_dist

    for x, y, cx, cz, gate_angle in _exit_cells_cache[3]:
        cell_val = maze_map[y][x]
        if cell_val not in (2, 3, 5):
            continue
        if cam_pos is not None:
            dx = cx - cam_pos[0]
            dz = cz - cam_pos[2]
            if dx * dx + dz * dz > max_dist_sq:
                continue

        arch_list = _get_exit_arch_dlist()

        glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_POLYGON_BIT)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_LIGHTING)

        glPushMatrix()
        glTranslatef(cx, 0.0, cz)
        glRotatef(gate_angle, 0.0, 1.0, 0.0)

        glCallList(arch_list)
        if cell_val == 5:
            glCallList(_get_exit_iron_gate_dlist())

        # Núcleo luminoso das duas lanternas coloniais pendentes (apagado quando travado)
        glDisable(GL_LIGHTING)
        if cell_val == 5:
            glColor3f(0.14, 0.15, 0.18)
        else:
            glColor3f(1.0 * pulse, 0.32 * pulse, 0.14 * pulse)
        for side in (-1.0, 1.0):
            glPushMatrix()
            glTranslatef(side * 0.54, 1.32 - 0.09, 0.18)
            _draw_cylinder(0.08, 0.09, 0.23, sides=6)
            glPopMatrix()

        if cell_val != 5:
            # Tapete de luz quente projetado na neve sob o arco
            glEnable(GL_BLEND)
            glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
            glEnable(GL_POLYGON_OFFSET_FILL)
            glPolygonOffset(-2.0, -2.0)

            glBegin(GL_TRIANGLE_FAN)
            glColor4f(1.0, 0.28, 0.14, 0.48 * pulse)
            glVertex3f(0.0, FLOOR_Y, 0.10)
            glColor4f(0.65, 0.08, 0.06, 0.0)
            for i in range(17):
                th = 2.0 * math.pi * i / 16
                glVertex3f(math.cos(th) * 0.95, FLOOR_Y, 0.10 + math.sin(th) * 0.95)
            glEnd()

        glPopMatrix()
        glPopAttrib()


def draw_campfires(campfires, cam_pos=None, max_dist=34.0, now_ms=None):
    """Renderiza fogueiras 3D com anel de pedras, toras cruzadas, chamas multi-camadas e brasas."""
    if not campfires:
        return
    t = (pygame.time.get_ticks() if now_ms is None else now_ms) / 1000.0
    FLOOR_Y = -0.98
    max_dist_sq = max_dist * max_dist

    for cx, cz in campfires:
        if cam_pos is not None:
            dx_c = cx - cam_pos[0]
            dz_c = cz - cam_pos[2]
            if dx_c * dx_c + dz_c * dz_c > max_dist_sq:
                continue

        base_list = _get_campfire_base_dlist()
        glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_POINT_BIT)
        glDisable(GL_TEXTURE_2D)

        # 1. Anel de pedras + toras cruzadas (Display List estática em espaço local)
        glEnable(GL_LIGHTING)
        glPushMatrix()
        glTranslatef(cx, FLOOR_Y, cz)
        glRotatef((cx * 31.0 + cz * 57.0) % 360.0, 0.0, 1.0, 0.0)
        glCallList(base_list)
        glPopMatrix()

        # 2. Chamas 3D animadas + brilho no chão + fagulhas ascendentes
        glDisable(GL_LIGHTING)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)

        pulse = 0.80 + 0.20 * math.sin(t * 7.5 + cx)
        glBegin(GL_TRIANGLE_FAN)
        glColor4f(1.0, 0.45, 0.08, 0.28 * pulse)
        glVertex3f(cx, FLOOR_Y + 0.01, cz)
        glColor4f(0.8, 0.20, 0.0, 0.0)
        for i in range(15):
            th = 2.0 * math.pi * i / 14
            glVertex3f(cx + math.cos(th) * 0.90, FLOOR_Y + 0.01, cz + math.sin(th) * 0.90)
        glEnd()

        # Línguas de fogo cruzadas em 3D (externa laranja, núcleo amarelo)
        for layer, (r_base, h_base, col_bot, col_top) in enumerate([
            (0.24, 0.62, (0.95, 0.25, 0.04, 0.68), (1.0, 0.55, 0.05, 0.0)),
            (0.14, 0.42, (1.00, 0.78, 0.20, 0.85), (1.0, 0.96, 0.65, 0.0)),
        ]):
            for k in range(3):
                rot_y = math.radians(k * 60.0 + t * 25.0 * (1 if layer else -1))
                sway = math.sin(t * 9.0 + k * 2.1 + cx) * 0.06
                fh = h_base * (0.85 + 0.22 * math.sin(t * 11.5 + k * 1.7 + layer))
                dx = math.cos(rot_y) * r_base
                dz = math.sin(rot_y) * r_base
                glBegin(GL_TRIANGLES)
                glColor4f(*col_bot)
                glVertex3f(cx - dx, FLOOR_Y + 0.08, cz - dz)
                glVertex3f(cx + dx, FLOOR_Y + 0.08, cz + dz)
                glColor4f(*col_top)
                glVertex3f(cx + sway, FLOOR_Y + 0.08 + fh, cz - sway)
                glEnd()

        # Fagulhas/brasas subindo
        glPointSize(3.0)
        glBegin(GL_POINTS)
        for i in range(7):
            phase = (t * (0.8 + (i % 3) * 0.25) + i * 0.17 + abs(cx)) % 1.0
            sy = FLOOR_Y + 0.18 + phase * 1.15
            sx = cx + math.sin(t * 4.5 + i * 2.3) * (0.08 + phase * 0.18)
            sz = cz + math.cos(t * 3.8 + i * 1.9) * (0.08 + phase * 0.18)
            glColor4f(1.0, 0.65 - phase * 0.35, 0.15, (1.0 - phase) * 0.9)
            glVertex3f(sx, sy, sz)
        glEnd()

        glDepthMask(GL_TRUE)
        glPopAttrib()


def draw_corpse(tex_corpse, cx, cz, cam_pos=None, max_dist=34.0, now_ms=None, searched=False):
    """Renderiza um sobrevivente congelado 3D na neve com mochila e lanterna piscando."""
    if cam_pos is not None:
        dx_c = cx - cam_pos[0]
        dz_c = cz - cam_pos[2]
        if dx_c * dx_c + dz_c * dz_c > max_dist * max_dist:
            return

    t = (pygame.time.get_ticks() if now_ms is None else now_ms) / 1000.0
    FLOOR_Y = -0.98
    rot_deg = ((cx * 37.0 + cz * 73.0) % 360.0)
    body_list = _get_corpse_body_dlist()

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_POLYGON_BIT)
    glDisable(GL_TEXTURE_2D)

    glPushMatrix()
    glTranslatef(cx, FLOOR_Y, cz)
    glRotatef(rot_deg, 0.0, 1.0, 0.0)

    glCallList(body_list)

    # Lente da lanterna 3D caída no chão (apagada se já vasculhado; pisca no escuro caso contrário)
    glDisable(GL_LIGHTING)
    glPushMatrix()
    glTranslatef(0.48, 0.05, 0.56)
    glRotatef(-42.0, 0.0, 1.0, 0.0)
    glRotatef(90.0, 1.0, 0.0, 0.0)
    glTranslatef(0.0, 0.22, 0.0)
    if searched:
        glColor3f(0.18, 0.20, 0.22)
    else:
        flicker = 1.0 if math.sin(t * 7.3 + cx * 3.0) > -0.45 else 0.15
        glColor3f(1.0 * flicker, 0.92 * flicker, 0.62 * flicker)
    _draw_cylinder(0.044, 0.044, 0.02, sides=8)
    glPopMatrix()

    if not searched:
        # Pequeno feixe/halo no chão diante da lanterna caída
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE)
        glDepthMask(GL_FALSE)
        glBegin(GL_TRIANGLE_FAN)
        glColor4f(1.0, 0.88, 0.50, 0.30 * flicker)
        glVertex3f(0.55, 0.03, 0.65)
        glColor4f(0.7, 0.55, 0.2, 0.0)
        for i in range(13):
            th = 2.0 * math.pi * i / 12.0
            glVertex3f(0.72 + math.cos(th) * 0.65, 0.03, 0.84 + math.sin(th) * 0.65)
        glEnd()
        glDepthMask(GL_TRUE)

    glPopMatrix()
    glPopAttrib()


def cleanup_floor_display_list():
    global _floor_dlist, _floor_cache_key, _exit_arch_dlist, _exit_iron_gate_dlist, _campfire_base_dlist, _corpse_body_dlist, _exit_cells_cache
    for dl in (_floor_dlist, _exit_arch_dlist, _exit_iron_gate_dlist, _campfire_base_dlist, _corpse_body_dlist):
        if dl is not None:
            try:
                glDeleteLists(dl, 1)
            except Exception:
                pass
    _floor_dlist = None
    _floor_cache_key = None
    _exit_arch_dlist = None
    _exit_iron_gate_dlist = None
    _campfire_base_dlist = None
    _corpse_body_dlist = None
    _exit_cells_cache = None


def draw_floor(tex_snow, W, H):
    global _floor_dlist, _floor_cache_key
    cache_key = (tex_snow, W, H)
    if _floor_dlist is None or _floor_cache_key != cache_key:
        if _floor_dlist is not None:
            try:
                glDeleteLists(_floor_dlist, 1)
            except Exception:
                pass
        half_w = (W * BLOCK_SIZE) * 0.5 + BLOCK_SIZE
        half_h = (H * BLOCK_SIZE) * 0.5 + BLOCK_SIZE
        step = BLOCK_SIZE * 0.5
        nx = max(1, int(round((2.0 * half_w) / step)))
        nz = max(1, int(round((2.0 * half_h) / step)))

        _floor_dlist = glGenLists(1)
        glNewList(_floor_dlist, GL_COMPILE)
        glBegin(GL_QUADS)
        glNormal3f(0.0, 1.0, 0.0)
        glColor3f(1.0, 1.0, 1.0)
        for iz in range(nz):
            z0 = -half_h + iz * step
            z1 = z0 + step
            v0 = (z0 + half_h) / step
            v1 = v0 + 1.0
            for ix in range(nx):
                x0 = -half_w + ix * step
                x1 = x0 + step
                u0 = (x0 + half_w) / step
                u1 = u0 + 1.0
                glTexCoord2f(u0, v0); glVertex3f(x0, -1.0, z0)
                glTexCoord2f(u1, v0); glVertex3f(x1, -1.0, z0)
                glTexCoord2f(u1, v1); glVertex3f(x1, -1.0, z1)
                glTexCoord2f(u0, v1); glVertex3f(x0, -1.0, z1)
        glEnd()
        glEndList()
        _floor_cache_key = cache_key

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    if tex_snow:
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_snow)
    else:
        glDisable(GL_TEXTURE_2D)
    glCallList(_floor_dlist)
    glPopAttrib()


def draw_skybox(tex_skybox, px, py, pz):
    if not tex_skybox:
        return
    glPushMatrix()
    glTranslatef(px, py, pz)
    glScalef(40, 40, 40)
    glPushAttrib(GL_ENABLE_BIT | GL_DEPTH_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glEnable(GL_FOG)
    glDepthMask(GL_FALSE)
    glBindTexture(GL_TEXTURE_2D, tex_skybox)
    glBegin(GL_QUADS)
    glColor3f(0.12, 0.15, 0.22)   # Céu noturno escuro de nevasca
    for i, face in enumerate(_SURFACES):
        if i == 5:   # sem chão no skybox
            continue
        for j, v in enumerate(face):
            u, vt = _UV[j]
            glTexCoord2f(u, vt)
            glVertex3fv(_VERTICES[v])
    glEnd()
    glPopAttrib()
    glPopMatrix()


def build_maze_display_list(tex_snow, tex_hedge, maze_map, W, H) -> int:
    """Compila chão + paredes na VRAM (Display List OpenGL legada/fallback)."""
    dlist = glGenLists(1)
    glNewList(dlist, GL_COMPILE)
    draw_floor(tex_snow, W, H)
    draw_walls(maze_map, W, H, tex_hedge)
    glEndList()
    return dlist


# ---------------------------------------------------------------------------
# Frustum Culling e Otimização de Chunks do Labirinto (Item 3)
# ---------------------------------------------------------------------------
def extract_frustum_planes() -> np.ndarray:
    """Extrai os 6 planos do frustum de visão (Left, Right, Bottom, Top, Near, Far) normalizados a partir das matrizes GL."""
    proj = glGetFloatv(GL_PROJECTION_MATRIX)
    modl = glGetFloatv(GL_MODELVIEW_MATRIX)
    clip = np.dot(modl, proj)

    planes = np.zeros((6, 4), dtype=np.float32)
    planes[0] = clip[:, 3] + clip[:, 0]  # Left
    planes[1] = clip[:, 3] - clip[:, 0]  # Right
    planes[2] = clip[:, 3] + clip[:, 1]  # Bottom
    planes[3] = clip[:, 3] - clip[:, 1]  # Top
    planes[4] = clip[:, 3] + clip[:, 2]  # Near
    planes[5] = clip[:, 3] - clip[:, 2]  # Far

    for i in range(6):
        n = np.linalg.norm(planes[i, :3])
        if n > 0.0:
            planes[i] /= n
    return planes


def aabb_in_frustum(planes: np.ndarray, min_x: float, min_y: float, min_z: float,
                    max_x: float, max_y: float, max_z: float, margin: float = 1.5) -> bool:
    """Testa se um AABB intersecta o frustum de visão da câmera com margem de segurança."""
    for i in range(6):
        px = (max_x + margin) if planes[i, 0] >= 0.0 else (min_x - margin)
        py = (max_y + margin) if planes[i, 1] >= 0.0 else (min_y - margin)
        pz = (max_z + margin) if planes[i, 2] >= 0.0 else (min_z - margin)
        if (planes[i, 0] * px + planes[i, 1] * py + planes[i, 2] * pz + planes[i, 3]) < 0.0:
            return False
    return True


def build_maze_chunks(tex_hedge: int | None, maze_map: list, W: int, H: int, chunk_size: int = 5) -> list:
    """Divide o labirinto em chunks espaciais e compila display lists otimizadas com remoção de faces internas (Hidden Face Removal)."""
    chunks = []
    num_cx = (W + chunk_size - 1) // chunk_size
    num_cy = (H + chunk_size - 1) // chunk_size

    uv_v_scale = 2.0
    FLOOR_Y = -1.0
    CEIL_Y  = WALL_HEIGHT - 1.0
    half_b  = BLOCK_SIZE * 0.5
    SUB_H   = 2
    SUB_V   = 8

    def _emit_wall_face(x0, z0, x1, z1, nx, ny, nz, u_start, u_end):
        glNormal3f(nx, ny, nz)
        for ih in range(SUB_H):
            ht0 = ih / SUB_H
            ht1 = (ih + 1) / SUB_H
            hx0 = x0 + (x1 - x0) * ht0
            hz0 = z0 + (z1 - z0) * ht0
            hx1 = x0 + (x1 - x0) * ht1
            hz1 = z0 + (z1 - z0) * ht1
            ua = u_start + (u_end - u_start) * ht0
            ub = u_start + (u_end - u_start) * ht1
            for iv in range(SUB_V):
                vt0 = iv / SUB_V
                vt1 = (iv + 1) / SUB_V
                y0 = FLOOR_Y + (CEIL_Y - FLOOR_Y) * vt0
                y1 = FLOOR_Y + (CEIL_Y - FLOOR_Y) * vt1
                va = uv_v_scale * vt0
                vb = uv_v_scale * vt1
                glTexCoord2f(ua, va); glVertex3f(hx0, y0, hz0)
                glTexCoord2f(ua, vb); glVertex3f(hx0, y1, hz0)
                glTexCoord2f(ub, vb); glVertex3f(hx1, y1, hz1)
                glTexCoord2f(ub, va); glVertex3f(hx1, y0, hz1)

    for cy in range(num_cy):
        for cx in range(num_cx):
            x_start = cx * chunk_size
            x_end   = min(W, (cx + 1) * chunk_size)
            y_start = cy * chunk_size
            y_end   = min(H, (cy + 1) * chunk_size)

            min_x = (x_start - W / 2.0) * BLOCK_SIZE - half_b
            max_x = (x_end   - W / 2.0) * BLOCK_SIZE - half_b
            min_z = (y_start - H / 2.0) * BLOCK_SIZE - half_b
            max_z = (y_end   - H / 2.0) * BLOCK_SIZE - half_b

            dlist = glGenLists(1)
            glNewList(dlist, GL_COMPILE)

            # Paredes do chunk (apenas faces visíveis voltadas para espaços abertos)
            if tex_hedge:
                glBindTexture(GL_TEXTURE_2D, tex_hedge)
            glBegin(GL_QUADS)
            glColor3f(1.0, 1.0, 1.0)

            for my in range(y_start, y_end):
                for mx in range(x_start, x_end):
                    if maze_map[my][mx] != 1:
                        continue

                    bx_c = (mx - W / 2.0) * BLOCK_SIZE
                    bz_c = (my - H / 2.0) * BLOCK_SIZE
                    bx0 = bx_c - half_b
                    bx1 = bx_c + half_b
                    bz0 = bz_c - half_b
                    bz1 = bz_c + half_b

                    # Face Norte (Z-) - apenas se adjacente não for parede
                    if my == 0 or maze_map[my - 1][mx] != 1:
                        _emit_wall_face(bx1, bz0, bx0, bz0, 0.0, 0.0, -1.0, 1.0, 0.0)

                    # Face Sul (Z+) - apenas se adjacente não for parede
                    if my == H - 1 or maze_map[my + 1][mx] != 1:
                        _emit_wall_face(bx0, bz1, bx1, bz1, 0.0, 0.0, 1.0, 0.0, 1.0)

                    # Face Oeste (X-) - apenas se adjacente não for parede
                    if mx == 0 or maze_map[my][mx - 1] != 1:
                        _emit_wall_face(bx0, bz0, bx0, bz1, -1.0, 0.0, 0.0, 0.0, 1.0)

                    # Face Leste (X+) - apenas se adjacente não for parede
                    if mx == W - 1 or maze_map[my][mx + 1] != 1:
                        _emit_wall_face(bx1, bz1, bx1, bz0, 1.0, 0.0, 0.0, 1.0, 0.0)

                    # Face Superior (Topo da sebe)
                    glNormal3f(0.0, 1.0, 0.0)
                    glTexCoord2f(0.0, 0.0); glVertex3f(bx0, CEIL_Y, bz0)
                    glTexCoord2f(1.0, 0.0); glVertex3f(bx1, CEIL_Y, bz0)
                    glTexCoord2f(1.0, 1.0); glVertex3f(bx1, CEIL_Y, bz1)
                    glTexCoord2f(0.0, 1.0); glVertex3f(bx0, CEIL_Y, bz1)

            glEnd()
            glEndList()

            center_x = (min_x + max_x) * 0.5
            center_z = (min_z + max_z) * 0.5
            radius   = math.hypot(max_x - min_x, max_z - min_z) * 0.5

            chunks.append({
                'dlist': dlist,
                'min_x': min_x, 'max_x': max_x,
                'min_y': FLOOR_Y, 'max_y': CEIL_Y,
                'min_z': min_z, 'max_z': max_z,
                'center_x': center_x, 'center_z': center_z,
                'radius': radius
            })

    return chunks


def draw_maze_optimized(chunks: list, cam_pos: tuple, max_dist: float = 65.0) -> tuple:
    """Renderiza apenas os chunks do labirinto visíveis dentro do frustum e do alcance da visão."""
    if not chunks:
        return 0, 0

    planes = extract_frustum_planes()
    cx, _, cz = cam_pos
    rendered = 0
    total = len(chunks)

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glEnable(GL_TEXTURE_2D)
    glEnable(GL_LIGHTING)
    glColor3f(1.0, 1.0, 1.0)

    for chunk in chunks:
        # 1. Distance culling (distância máxima da visão + raio)
        dx = chunk['center_x'] - cx
        dz = chunk['center_z'] - cz
        if math.hypot(dx, dz) > max_dist + chunk['radius']:
            continue

        # 2. Frustum culling com margem de segurança de 1.5m
        if not aabb_in_frustum(planes, chunk['min_x'], chunk['min_y'], chunk['min_z'],
                               chunk['max_x'], chunk['max_y'], chunk['max_z'], margin=1.5):
            continue

        glCallList(chunk['dlist'])
        rendered += 1

    glPopAttrib()
    return rendered, total



# ---------------------------------------------------------------------------
# Baterias Coletáveis Espalhadas pelo Labirinto (Item 5)
# ---------------------------------------------------------------------------
def draw_battery_pickup(wx: float, wz: float, now_ms: int):
    """Renderiza um pickup 3D de bateria flutuando e rotacionando com emissão suave no piso."""
    t_s = now_ms / 1000.0
    FLOOR_Y = -0.97
    pulse = 0.7 + 0.3 * math.sin(t_s * 4.5)
    float_y = -0.45 + 0.08 * math.sin(t_s * 3.0)
    rot_deg = (t_s * 85.0) % 360.0

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glDisable(GL_TEXTURE_2D)

    # 1. Halo no piso (projeção luminosa suave)
    glDisable(GL_LIGHTING)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE)
    glEnable(GL_POLYGON_OFFSET_FILL)
    glPolygonOffset(-2.0, -2.0)

    halo_r = 0.5 * pulse
    glBegin(GL_TRIANGLE_FAN)
    glColor4f(0.15, 0.9, 0.4, 0.35 * pulse)
    glVertex3f(wx, FLOOR_Y, wz)
    glColor4f(0.02, 0.3, 0.1, 0.0)
    segments = 12
    for i in range(segments + 1):
        th = 2.0 * math.pi * i / segments
        glVertex3f(wx + math.cos(th) * halo_r, FLOOR_Y, wz + math.sin(th) * halo_r)
    glEnd()
    glDisable(GL_POLYGON_OFFSET_FILL)

    # 2. Bateria 3D (Corpo cilíndrico octogonal, terminal dourado e anel fluorescente)
    glEnable(GL_LIGHTING)
    glDisable(GL_BLEND)
    glPushMatrix()
    glTranslatef(wx, float_y, wz)
    glRotatef(rot_deg, 0.0, 1.0, 0.0)

    r = 0.13
    h_body = 0.38
    h_half = h_body / 2.0
    sides = 8

    # Tubo da bateria: base preta, anel fluorescente de alta energia, topo preto
    sections = [
        (-h_half, -h_half + 0.10, (0.15, 0.16, 0.18)),
        (-h_half + 0.10, -h_half + 0.26, (0.25, 0.95, 0.35)),
        (-h_half + 0.26, h_half, (0.15, 0.16, 0.18)),
    ]

    for y_bot, y_top, col in sections:
        glColor3fv(col)
        glBegin(GL_QUAD_STRIP)
        for i in range(sides + 1):
            th = 2.0 * math.pi * i / sides
            nx, nz = math.cos(th), math.sin(th)
            glNormal3f(nx, 0.0, nz)
            glVertex3f(nx * r, y_top, nz * r)
            glVertex3f(nx * r, y_bot, nz * r)
        glEnd()

    # Base e topo da bateria
    glBegin(GL_TRIANGLE_FAN)
    glNormal3f(0.0, -1.0, 0.0)
    glColor3f(0.2, 0.2, 0.22)
    glVertex3f(0.0, -h_half, 0.0)
    for i in range(sides + 1):
        th = 2.0 * math.pi * i / sides
        glVertex3f(math.cos(th) * r, -h_half, math.sin(th) * r)
    glEnd()

    glBegin(GL_TRIANGLE_FAN)
    glNormal3f(0.0, 1.0, 0.0)
    glColor3f(0.28, 0.28, 0.3)
    glVertex3f(0.0, h_half, 0.0)
    for i in range(sides + 1):
        th = 2.0 * math.pi * i / sides
        glVertex3f(math.cos(th) * r, h_half, math.sin(th) * r)
    glEnd()

    # Terminal positivo (+)
    nub_r = 0.05
    nub_h = 0.08
    glColor3f(0.9, 0.8, 0.2)
    glBegin(GL_QUAD_STRIP)
    for i in range(sides + 1):
        th = 2.0 * math.pi * i / sides
        nx, nz = math.cos(th), math.sin(th)
        glNormal3f(nx, 0.0, nz)
        glVertex3f(nx * nub_r, h_half + nub_h, nz * nub_r)
        glVertex3f(nx * nub_r, h_half, nz * nub_r)
    glEnd()
    glBegin(GL_TRIANGLE_FAN)
    glNormal3f(0.0, 1.0, 0.0)
    glVertex3f(0.0, h_half + nub_h, 0.0)
    for i in range(sides + 1):
        th = 2.0 * math.pi * i / sides
        glVertex3f(math.cos(th) * nub_r, h_half + nub_h, math.sin(th) * nub_r)
    glEnd()

    glPopMatrix()
    glPopAttrib()


# ---------------------------------------------------------------------------
# Efeito Volumétrico da Lanterna (Cone e Feixes de Luz)
# ---------------------------------------------------------------------------
def draw_flashlight_volumetric_shaft(cam_pos, look_dir, eff, blizzard_intensity):
    """Renderiza cone de luz volumétrico atmosférico com partículas e feixes que reagem à névoa."""
    if eff <= 0.02:
        return

    dx, dy, dz = look_dir
    norm = math.sqrt(dx*dx + dy*dy + dz*dz) or 1.0
    dx, dy, dz = dx/norm, dy/norm, dz/norm

    # Base e dimensões do cone
    length = 16.0
    radius = 3.8
    segments = 18

    up = (0.0, 1.0, 0.0) if abs(dy) < 0.94 else (1.0, 0.0, 0.0)
    rx = dy * up[2] - dz * up[1]
    ry = dz * up[0] - dx * up[2]
    rz = dx * up[1] - dy * up[0]
    r_norm = math.sqrt(rx*rx + ry*ry + rz*rz) or 1.0
    rx, ry, rz = rx/r_norm, ry/r_norm, rz/r_norm

    ux = ry * dz - rz * dy
    uy = rz * dx - rx * dz
    uz = rx * dy - ry * dx

    # Vértice de origem (ligeiramente à frente da lente)
    apex_x = cam_pos[0] + dx * 0.30
    apex_y = cam_pos[1] + dy * 0.30
    apex_z = cam_pos[2] + dz * 0.30

    base_cx = cam_pos[0] + dx * length
    base_cy = cam_pos[1] + dy * length
    base_cz = cam_pos[2] + dz * length

    # Mais visível cortando a escuridão e a névoa
    alpha = min(0.38, eff * (0.12 + 0.22 * blizzard_intensity))

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE)  # Blend aditivo para feixes de luz
    glDepthMask(GL_FALSE)              # Não bloqueia profundidade dos objetos

    glBegin(GL_TRIANGLE_FAN)
    # Vértice central próximo da lanterna: foco intenso e brilhante
    glColor4f(0.95, 0.98, 1.0, alpha)
    glVertex3f(apex_x, apex_y, apex_z)

    # Base circular do cone com desvanecimento suave
    glColor4f(0.20, 0.30, 0.55, 0.0)
    for i in range(segments + 1):
        th = 2.0 * math.pi * i / segments
        c, s = math.cos(th), math.sin(th)
        px = base_cx + (rx * c + ux * s) * radius
        py = base_cy + (ry * c + uy * s) * radius
        pz = base_cz + (rz * c + uz * s) * radius
        glVertex3f(px, py, pz)
    glEnd()

    glDepthMask(GL_TRUE)
    glPopAttrib()


# ---------------------------------------------------------------------------
# Modelo 3D Articulado do Jack Torrance com Machado
# ---------------------------------------------------------------------------
def _draw_jack_model(t_s, jack_dist, madness, is_fake=False, swing_override=None, head_turn_deg=0.0):
    """Renderiza a hierarquia 3D articulada do Jack Torrance com machado de incêndio."""
    fake_alpha = (0.42 + 0.18 * math.sin(t_s * 5.0)) if is_fake else 1.0

    def _col(r, g, b):
        if is_fake:
            lum = 0.299 * r + 0.587 * g + 0.114 * b
            glColor4f(0.40 + lum * 0.35, 0.55 + lum * 0.42, 0.75 + lum * 0.35, fake_alpha)
        else:
            red_tint = min(0.28, madness * 0.28)
            glColor4f(
                min(1.0, r + red_tint * 0.22),
                g * (1.0 - red_tint * 0.35),
                b * (1.0 - red_tint * 0.35),
                1.0,
            )

    walk_freq = 8.0 if jack_dist < 12.0 else 4.5
    leg_angle = math.sin(t_s * walk_freq) * (12.0 if swing_override is not None else 32.0)

    # 1. Pernas e botas articuladas (pivô no quadril y = 0.96)
    for side, ang in ((-1.0, leg_angle), (1.0, -leg_angle)):
        glPushMatrix()
        glTranslatef(side * 0.15, 0.96, 0.0)
        glRotatef(ang, 1.0, 0.0, 0.0)

        # Calça veludo cotelê
        _col(0.16, 0.12, 0.09)
        glPushMatrix()
        glTranslatef(0.0, -0.38, 0.0)
        _draw_box(0.19, 0.74, 0.20)
        glPopMatrix()

        # Bota pesada de inverno
        _col(0.09, 0.06, 0.04)
        glPushMatrix()
        glTranslatef(0.0, -0.84, 0.04)
        _draw_box(0.20, 0.20, 0.28)
        glPopMatrix()
        glPopMatrix()

    # 2. Tronco com inclinação ameaçadora
    lean_deg = 8.0 + (10.0 if (jack_dist < 7.0 or swing_override is not None) else 0.0)
    glPushMatrix()
    glTranslatef(0.0, 0.94, 0.0)
    glRotatef(lean_deg, 1.0, 0.0, 0.0)

    # Jaqueta bordô xadrez de inverno
    _col(0.38, 0.11, 0.09)
    glPushMatrix()
    glTranslatef(0.0, 0.36, 0.0)
    _draw_box(0.56, 0.70, 0.30)
    glPopMatrix()

    # Faixas escuras do xadrez da jaqueta + bolsos
    _col(0.16, 0.05, 0.04)
    for py in (0.22, 0.44):
        glPushMatrix()
        glTranslatef(0.0, py, 0.0)
        _draw_box(0.58, 0.07, 0.31)
        glPopMatrix()

    # Camisa azul por baixo e gola levantada
    _col(0.14, 0.22, 0.36)
    glPushMatrix()
    glTranslatef(0.0, 0.38, 0.02)
    _draw_box(0.18, 0.64, 0.29)
    glPopMatrix()

    _col(0.32, 0.09, 0.07)
    glPushMatrix()
    glTranslatef(0.0, 0.72, -0.02)
    _draw_box(0.36, 0.11, 0.28)
    glPopMatrix()

    # 3. Cabeça 3D esculpida
    glPushMatrix()
    glTranslatef(0.0, 0.90, 0.02)
    glRotatef(head_turn_deg, 0.0, 1.0, 0.0)
    glRotatef(math.sin(t_s * 2.4) * 6.0, 0.0, 0.0, 1.0)

    # Rosto pálido
    _col(0.76, 0.64, 0.58)
    _draw_ellipsoid(0.16, 0.20, 0.17, slices=10, stacks=6)

    # Cabelos desgrenhados nas laterais e topo
    _col(0.15, 0.11, 0.09)
    for sx in (-0.14, 0.14):
        glPushMatrix()
        glTranslatef(sx, 0.06, -0.02)
        _draw_box(0.08, 0.22, 0.24)
        glPopMatrix()
    glPushMatrix()
    glTranslatef(0.0, 0.18, -0.03)
    _draw_box(0.28, 0.09, 0.26)
    glPopMatrix()

    # Nariz
    _col(0.70, 0.56, 0.50)
    glPushMatrix()
    glTranslatef(0.0, -0.01, 0.165)
    _draw_box(0.04, 0.07, 0.05)
    glPopMatrix()

    # Sobrancelhas arqueadas sinistras
    _col(0.10, 0.07, 0.06)
    for sx, tilt in ((-0.065, -20.0), (0.065, 20.0)):
        glPushMatrix()
        glTranslatef(sx, 0.07, 0.155)
        glRotatef(tilt, 0.0, 0.0, 1.0)
        _draw_box(0.07, 0.022, 0.025)
        glPopMatrix()

    # Sorriso maníaco aberto com dentes
    _col(0.10, 0.01, 0.02)
    glPushMatrix()
    glTranslatef(0.0, -0.09, 0.152)
    _draw_box(0.13, 0.055, 0.025)
    glPopMatrix()

    _col(0.86, 0.83, 0.75)
    glPushMatrix()
    glTranslatef(0.0, -0.076, 0.162)
    _draw_box(0.10, 0.018, 0.015)
    glPopMatrix()

    # Olhos com brilho sinistro (sem iluminação para se destacar na escuridão)
    glPushAttrib(GL_ENABLE_BIT)
    glDisable(GL_LIGHTING)
    for sx in (-0.06, 0.06):
        glColor4f(0.94, 0.92, 0.88, fake_alpha)
        glPushMatrix()
        glTranslatef(sx, 0.035, 0.155)
        _draw_box(0.045, 0.028, 0.02)
        glPopMatrix()

        if is_fake:
            glColor4f(0.55, 0.88, 1.0, fake_alpha)
        else:
            glColor4f(1.0, 0.22, 0.14, 1.0)
        glPushMatrix()
        glTranslatef(sx, 0.035, 0.168)
        _draw_box(0.020, 0.020, 0.012)
        glPopMatrix()
    glPopAttrib()
    glPopMatrix()  # fim cabeça

    # 4. Braço esquerdo
    glPushMatrix()
    glTranslatef(-0.34, 0.62, 0.0)
    glRotatef(-leg_angle * 0.85, 1.0, 0.0, 0.0)
    _col(0.36, 0.10, 0.08)
    glPushMatrix()
    glTranslatef(0.0, -0.26, 0.0)
    _draw_box(0.15, 0.52, 0.15)
    glPopMatrix()
    _col(0.72, 0.60, 0.54)
    glPushMatrix()
    glTranslatef(0.0, -0.56, 0.02)
    _draw_box(0.11, 0.12, 0.12)
    glPopMatrix()
    glPopMatrix()

    # 5. Braço direito + Machado de Incêndio 3D
    if swing_override is not None:
        chop_t = min(1.0, swing_override * 1.85)
        arm_pitch = -145.0 + chop_t * 115.0
        arm_roll = -18.0 + chop_t * 32.0
    elif jack_dist < 7.0:
        arm_pitch = -115.0 + math.sin(t_s * 6.5) * 42.0
        arm_roll = -10.0
    else:
        arm_pitch = -35.0 + leg_angle * 0.6
        arm_roll = 0.0

    glPushMatrix()
    glTranslatef(0.34, 0.62, 0.0)
    glRotatef(arm_pitch, 1.0, 0.0, 0.0)
    glRotatef(arm_roll, 0.0, 0.0, 1.0)

    _col(0.36, 0.10, 0.08)
    glPushMatrix()
    glTranslatef(0.0, -0.26, 0.0)
    _draw_box(0.15, 0.52, 0.15)
    glPopMatrix()
    _col(0.72, 0.60, 0.54)
    glPushMatrix()
    glTranslatef(0.0, -0.56, 0.02)
    _draw_box(0.11, 0.12, 0.12)
    glPopMatrix()

    # Machado 3D empunhado na mão direita
    glPushMatrix()
    glTranslatef(0.0, -0.56, 0.08)
    glRotatef(78.0, 1.0, 0.0, 0.0)

    # Cabo longo de madeira
    _col(0.38, 0.21, 0.10)
    glPushMatrix()
    glTranslatef(0.0, 0.24, 0.0)
    _draw_box(0.048, 0.94, 0.055)
    glPopMatrix()

    # Cabeça metálica do machado + fio prateado + pico traseiro + sangue
    _col(0.42, 0.45, 0.50)
    glPushMatrix()
    glTranslatef(0.0, 0.64, 0.06)
    _draw_box(0.06, 0.18, 0.22)
    glPopMatrix()

    _col(0.80, 0.84, 0.88)
    glPushMatrix()
    glTranslatef(0.0, 0.64, 0.18)
    _draw_box(0.028, 0.22, 0.07)
    glPopMatrix()

    _col(0.55, 0.03, 0.03)
    glPushMatrix()
    glTranslatef(0.0, 0.61, 0.17)
    _draw_box(0.034, 0.12, 0.08)
    glPopMatrix()

    _col(0.35, 0.38, 0.42)
    glPushMatrix()
    glTranslatef(0.0, 0.66, -0.11)
    _draw_box(0.035, 0.055, 0.14)
    glPopMatrix()

    glPopMatrix()  # fim machado
    glPopMatrix()  # fim braço direito
    glPopMatrix()  # fim tronco


def draw_jack_billboard(tex_jack, jack_wx, jack_wz, player_x, player_z, jack_dist, madness, now_ms, is_fake=False, move_yaw=None):
    """Renderiza o Jack Torrance como modelo 3D articulado com animação de marcha e machado."""
    if jack_dist > 45.0:
        return

    dx = player_x - jack_wx
    dz = player_z - jack_wz
    player_angle_deg = math.degrees(math.atan2(dx, dz))

    if move_yaw is not None and jack_dist >= 5.0:
        body_angle_deg = math.degrees(math.atan2(math.cos(move_yaw), math.sin(move_yaw)))
        head_turn = (player_angle_deg - body_angle_deg + 180.0) % 360.0 - 180.0
        head_turn = max(-55.0, min(55.0, head_turn))
    else:
        body_angle_deg = player_angle_deg
        head_turn = 0.0

    FLOOR_Y = -1.0
    t_s = now_ms / 1000.0
    walk_freq = 8.0 if jack_dist < 12.0 else 4.5
    bob_h = abs(math.sin(t_s * walk_freq)) * 0.06
    jitter_x = (math.sin(t_s * 29.0) * 0.05) if is_fake else 0.0

    glPushMatrix()
    glTranslatef(jack_wx + jitter_x, FLOOR_Y + bob_h, jack_wz)
    glRotatef(body_angle_deg, 0.0, 1.0, 0.0)

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_LIGHTING_BIT)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_LIGHTING)
    if is_fake:
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    _draw_jack_model(t_s, jack_dist, madness, is_fake=is_fake, head_turn_deg=head_turn)

    glPopAttrib()
    glPopMatrix()


# ---------------------------------------------------------------------------
# Jumpscares Cinematográficos 3D e Lanterna Viewmodel 3D
# ---------------------------------------------------------------------------
def _draw_grady_twin_3d(tilt_deg):
    """Renderiza uma das Gêmeas Grady em 3D (vestido azul, faixa escura, cabeça inclinada)."""
    # Sapatos e meias brancas
    glColor3f(0.08, 0.08, 0.10)
    for sx in (-0.09, 0.09):
        glPushMatrix()
        glTranslatef(sx, 0.05, 0.04)
        _draw_box(0.09, 0.09, 0.16)
        glPopMatrix()

        glColor3f(0.86, 0.88, 0.92)
        glPushMatrix()
        glTranslatef(sx, 0.25, 0.0)
        _draw_cylinder(0.042, 0.046, 0.34, sides=8)
        glPopMatrix()
        glColor3f(0.08, 0.08, 0.10)

    # Saia plissada azul-pálido
    glColor3f(0.52, 0.70, 0.84)
    glPushMatrix()
    glTranslatef(0.0, 0.42, 0.0)
    _draw_cylinder(0.28, 0.14, 0.48, sides=10)
    glPopMatrix()

    # Faixa na cintura
    glColor3f(0.18, 0.16, 0.24)
    glPushMatrix()
    glTranslatef(0.0, 0.88, 0.0)
    _draw_cylinder(0.145, 0.145, 0.07, sides=10)
    glPopMatrix()

    # Tronco do vestido + gola branca
    glColor3f(0.52, 0.70, 0.84)
    glPushMatrix()
    glTranslatef(0.0, 1.08, 0.0)
    _draw_box(0.28, 0.34, 0.18)
    glPopMatrix()

    glColor3f(0.92, 0.94, 0.96)
    glPushMatrix()
    glTranslatef(0.0, 1.24, 0.02)
    _draw_box(0.22, 0.06, 0.18)
    glPopMatrix()

    # Braços rígidos ao lado do corpo
    for sx in (-0.19, 0.19):
        glColor3f(0.52, 0.70, 0.84)
        glPushMatrix()
        glTranslatef(sx, 1.06, 0.0)
        _draw_box(0.08, 0.28, 0.09)
        glPopMatrix()
        glColor3f(0.80, 0.76, 0.74)
        glPushMatrix()
        glTranslatef(sx, 0.85, 0.0)
        _draw_box(0.07, 0.14, 0.07)
        glPopMatrix()

    # Cabeça inclinada + cabelo escuro + olhos vazios
    glPushMatrix()
    glTranslatef(0.0, 1.40, 0.01)
    glRotatef(tilt_deg, 0.0, 0.0, 1.0)

    glColor3f(0.80, 0.76, 0.74)
    _draw_ellipsoid(0.12, 0.15, 0.13, slices=10, stacks=6)

    glColor3f(0.09, 0.07, 0.06)
    glPushMatrix()
    glTranslatef(0.0, 0.04, -0.03)
    _draw_box(0.27, 0.24, 0.20)
    glPopMatrix()

    glPushAttrib(GL_ENABLE_BIT)
    glDisable(GL_LIGHTING)
    glColor3f(0.04, 0.01, 0.02)
    for sx in (-0.045, 0.045):
        glPushMatrix()
        glTranslatef(sx, 0.02, 0.125)
        _draw_box(0.034, 0.028, 0.015)
        glPopMatrix()
    glPopAttrib()
    glPopMatrix()


def _draw_claw_hand_3d(lunge):
    """Renderiza uma mão congelada e ensanguentada avançando contra a lente."""
    # Antebraço congelado
    glColor3f(0.45, 0.50, 0.58)
    glPushMatrix()
    glTranslatef(0.0, -0.35, 0.0)
    _draw_cylinder(0.085, 0.072, 0.36, sides=8)
    glPopMatrix()

    # Palma
    glColor3f(0.56, 0.58, 0.66)
    glPushMatrix()
    glTranslatef(0.0, 0.08, 0.0)
    _draw_box(0.20, 0.22, 0.07)
    glPopMatrix()

    # Manchas de sangue na palma
    glColor3f(0.52, 0.03, 0.03)
    glPushMatrix()
    glTranslatef(0.02, 0.10, 0.038)
    _draw_box(0.11, 0.12, 0.01)
    glPopMatrix()

    # 5 dedos em garra curvando para a câmera
    curl = 25.0 + lunge * 42.0
    finger_specs = [
        (-0.11, 0.04, 32.0, 0.13),
        (-0.07, 0.19, 6.0, 0.16),
        (-0.02, 0.20, 0.0, 0.175),
        (0.035, 0.19, -5.0, 0.16),
        (0.085, 0.17, -12.0, 0.13),
    ]
    for fx, fy, splay, flen in finger_specs:
        glPushMatrix()
        glTranslatef(fx, fy, 0.0)
        glRotatef(splay, 0.0, 0.0, 1.0)
        glRotatef(-curl, 1.0, 0.0, 0.0)
        glColor3f(0.56, 0.58, 0.66)
        _draw_cylinder(0.019, 0.014, flen * 0.6, sides=6)
        glTranslatef(0.0, flen * 0.6, 0.0)
        glRotatef(-curl * 0.85, 1.0, 0.0, 0.0)
        glColor3f(0.45, 0.05, 0.06)
        _draw_cylinder(0.014, 0.008, flen * 0.45, sides=6)
        glPopMatrix()


def draw_jumpscare_3d(js_type, js_age, madness, now_ms, photosensitivity=False):
    """Renderiza jumpscares cinematográficos em 3D (Ataque do Jack, Gêmeas Grady ou Mão Congelada)."""
    W, H = DISPLAY_SIZE
    t_s = now_ms / 1000.0
    js_age = max(0.0, min(1.0, js_age))

    # 1. Fundo 2D escuro/dramático
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W, H, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST); glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    if js_type == 1 and not photosensitivity and js_age < 0.16:
        flash_a = (1.0 - js_age / 0.16) * 0.78
        glColor4f(1.0, 0.92, 0.90, flash_a)
    elif js_type == 2:
        glColor4f(0.02, 0.03, 0.05, 0.92)
    elif js_type == 3:
        glColor4f(0.04, 0.02, 0.06, 0.84)
    else:
        glColor4f(0.06, 0.01, 0.01, 0.88)
    glBegin(GL_QUADS)
    glVertex2f(0, 0); glVertex2f(W, 0)
    glVertex2f(W, H); glVertex2f(0, H)
    glEnd()
    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()

    # 2. Cena 3D Close-Up em Primeira Pessoa
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    gluPerspective(60.0, W / H, 0.05, 25.0)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_LIGHTING_BIT | GL_FOG_BIT)
    glClear(GL_DEPTH_BUFFER_BIT)
    glEnable(GL_DEPTH_TEST)
    glDisable(GL_TEXTURE_2D)
    glDisable(GL_FOG)
    glEnable(GL_LIGHTING)
    glEnable(GL_LIGHT0)
    glDisable(GL_LIGHT1)
    glDisable(GL_LIGHT2)

    if js_type in (0, 1):
        # Ataque do Jack Torrance com Dutch Angle e golpe de machado 3D
        lunge = min(1.0, js_age * 2.1)
        z_dist = -2.2 + lunge * 1.38
        shake_x = math.sin(t_s * 55.0) * 0.04
        shake_y = math.cos(t_s * 48.0) * 0.03
        dutch_deg = -11.0 + math.sin(js_age * 22.0) * 10.0

        glLightfv(GL_LIGHT0, GL_POSITION, (0.2, 0.3, 0.6, 1.0))
        glLightfv(GL_LIGHT0, GL_SPOT_DIRECTION, (0.0, -0.1, -1.0))
        glLightf(GL_LIGHT0, GL_SPOT_CUTOFF, 48.0)
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (2.6, 2.0, 1.9, 1.0))

        glRotatef(dutch_deg, 0.0, 0.0, 1.0)
        glTranslatef(shake_x, -1.68 + shake_y, z_dist)
        _draw_jack_model(t_s, jack_dist=1.0, madness=madness, is_fake=False, swing_override=js_age)

    elif js_type == 2:
        # Gêmeas Grady no corredor com avanço repentino
        lunge = 0.0 if js_age < 0.52 else min(1.0, (js_age - 0.52) / 0.25)
        z_dist = -3.0 + lunge * 1.55
        glLightfv(GL_LIGHT0, GL_POSITION, (0.0, 1.4, z_dist + 0.8, 1.0))
        glLightfv(GL_LIGHT0, GL_SPOT_DIRECTION, (0.0, -0.7, -0.4))
        glLightf(GL_LIGHT0, GL_SPOT_CUTOFF, 65.0)
        flick = 0.7 if photosensitivity else (0.45 + 0.55 * abs(math.sin(t_s * 34.0)))
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (1.5 * flick, 1.7 * flick, 2.0 * flick, 1.0))

        for gx, tilt in ((-0.35, -7.0), (0.35, 7.0)):
            glPushMatrix()
            glTranslatef(gx, -1.02, z_dist)
            _draw_grady_twin_3d(tilt)
            glPopMatrix()

    else:
        # Mão congelada e ensanguentada agarrando a câmera
        lunge = min(1.0, js_age * 1.9)
        glLightfv(GL_LIGHT0, GL_POSITION, (-0.3, 0.2, 0.5, 1.0))
        glLightfv(GL_LIGHT0, GL_SPOT_DIRECTION, (0.1, -0.1, -1.0))
        glLightf(GL_LIGHT0, GL_SPOT_CUTOFF, 60.0)
        glLightfv(GL_LIGHT0, GL_DIFFUSE, (1.6, 1.7, 2.2, 1.0))

        glRotatef(math.sin(t_s * 30.0) * 6.0, 0.0, 0.0, 1.0)
        glTranslatef(0.06, -0.52 + lunge * 0.44, -1.15 + lunge * 0.68)
        glRotatef(-28.0, 1.0, 0.0, 0.0)
        _draw_claw_hand_3d(lunge)

    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()

    # 3. Efeitos 2D de Lente (rasgos de sangue, interferência VHS ou veias nas bordas)
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    glOrtho(0, W, H, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING); glDisable(GL_FOG); glDisable(GL_DEPTH_TEST); glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND); glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    if js_type in (0, 1) and js_age > 0.30:
        slash_a = min(1.0, (js_age - 0.30) / 0.25) * 0.80
        glLineWidth(6.0)
        glColor4f(0.85, 0.02, 0.02, slash_a)
        glBegin(GL_LINES)
        glVertex2f(W * 0.14, H * 0.10)
        glVertex2f(W * 0.86, H * 0.88)
        glVertex2f(W * 0.18, H * 0.18)
        glVertex2f(W * 0.82, H * 0.82)
        glEnd()
        # Respingos de sangue nas bordas
        glColor4f(0.65, 0.02, 0.02, slash_a * 0.65)
        for i in range(10):
            ang = i * 0.628 + 0.3
            bx = W * 0.5 + math.cos(ang) * W * 0.38
            by = H * 0.5 + math.sin(ang) * H * 0.38
            r = 16.0 + (i % 3) * 10.0
            glBegin(GL_TRIANGLES)
            glVertex2f(bx, by - r); glVertex2f(bx + r, by + r * 0.6); glVertex2f(bx - r * 0.8, by + r)
            glEnd()

    elif js_type == 2:
        # Linhas de interferência VHS horizontais
        bar_count = 6 if photosensitivity else 14
        for i in range(bar_count):
            y0 = ((i * 53 + int(now_ms * (0.15 if photosensitivity else 0.7))) % H)
            bh = 4 + (i % 4) * 3
            a_bar = 0.18 if photosensitivity else (0.15 + 0.25 * ((i * 7) % 3))
            glColor4f(0.75, 0.85, 0.95, a_bar)
            glBegin(GL_QUADS)
            glVertex2f(0, y0); glVertex2f(W, y0)
            glVertex2f(W, y0 + bh); glVertex2f(0, y0 + bh)
            glEnd()

    elif js_type == 3:
        # Veias de geada e sangue nas bordas da tela
        glLineWidth(2.5)
        glColor4f(0.75, 0.12, 0.18, 0.75)
        for i in range(12):
            x_edge = (W * i) / 11.0
            glBegin(GL_LINE_STRIP)
            glVertex2f(x_edge, 0)
            glVertex2f(x_edge + math.sin(i * 2.1) * 30.0, H * 0.10)
            glVertex2f(x_edge - math.cos(i * 1.7) * 25.0, H * 0.18)
            glEnd()
            glBegin(GL_LINE_STRIP)
            glVertex2f(x_edge, H)
            glVertex2f(x_edge - math.sin(i * 1.9) * 30.0, H * 0.90)
            glVertex2f(x_edge + math.cos(i * 2.3) * 25.0, H * 0.82)
            glEnd()

    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)


def draw_viewmodel_flashlight(flashlight_on, eff, sway_x, sway_y, bob_offset, now_ms):
    """Renderiza uma lanterna tática 3D na mão do jogador com inércia (weapon sway) e lente acesa."""
    W, H = DISPLAY_SIZE
    glMatrixMode(GL_PROJECTION); glPushMatrix(); glLoadIdentity()
    gluPerspective(55.0, W / H, 0.05, 10.0)
    glMatrixMode(GL_MODELVIEW); glPushMatrix(); glLoadIdentity()
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT | GL_LIGHTING_BIT | GL_FOG_BIT)

    glClear(GL_DEPTH_BUFFER_BIT)
    glEnable(GL_DEPTH_TEST)
    glDisable(GL_TEXTURE_2D)
    glDisable(GL_FOG)
    glEnable(GL_LIGHTING)
    glEnable(GL_LIGHT0)
    glDisable(GL_LIGHT1)
    glDisable(GL_LIGHT2)

    glLightfv(GL_LIGHT0, GL_POSITION, (-0.5, 0.6, 0.4, 1.0))
    glLightfv(GL_LIGHT0, GL_SPOT_CUTOFF, 180.0)
    glLightfv(GL_LIGHT0, GL_DIFFUSE, (0.85, 0.88, 0.95, 1.0))

    glTranslatef(0.32 + sway_x, -0.26 + sway_y + bob_offset * 0.45, -0.58)
    glRotatef(14.0 - sway_x * 95.0, 0.0, 1.0, 0.0)
    glRotatef(8.0 + sway_y * 95.0, 1.0, 0.0, 0.0)
    glRotatef(-90.0, 1.0, 0.0, 0.0)  # Orienta eixo +Y do cilindro para frente (-Z)

    # Manga/luva escura segurando o cabo
    glColor3f(0.08, 0.09, 0.12)
    glPushMatrix()
    glTranslatef(0.0, -0.22, 0.0)
    _draw_cylinder(0.044, 0.040, 0.16, sides=10)
    glPopMatrix()

    # Corpo cilíndrico metálico escuro
    glColor3f(0.15, 0.16, 0.19)
    glPushMatrix()
    glTranslatef(0.0, -0.10, 0.0)
    _draw_cylinder(0.032, 0.032, 0.24, sides=12)
    glPopMatrix()

    # Anéis emborrachados de empunhadura
    glColor3f(0.05, 0.05, 0.06)
    for ry in (-0.04, 0.01, 0.06):
        glPushMatrix()
        glTranslatef(0.0, ry, 0.0)
        _draw_cylinder(0.035, 0.035, 0.018, sides=12)
        glPopMatrix()

    # Botão interruptor
    glColor3f(0.75, 0.14, 0.12) if flashlight_on else glColor3f(0.28, 0.12, 0.12)
    glPushMatrix()
    glTranslatef(0.0, 0.10, 0.033)
    _draw_box(0.016, 0.026, 0.014)
    glPopMatrix()

    # Cabeçote octogonal alargado
    glColor3f(0.20, 0.22, 0.26)
    glPushMatrix()
    glTranslatef(0.0, 0.14, 0.0)
    _draw_cylinder(0.033, 0.052, 0.08, sides=8)
    glPopMatrix()

    glColor3f(0.24, 0.26, 0.30)
    glPushMatrix()
    glTranslatef(0.0, 0.22, 0.0)
    _draw_cylinder(0.052, 0.052, 0.035, sides=8)
    glPopMatrix()

    # Lente frontal (brilha quando ligada)
    glDisable(GL_LIGHTING)
    if flashlight_on and eff > 0.02:
        glColor3f(min(1.0, 0.85 + 0.15 * eff), min(1.0, 0.82 + 0.14 * eff), 0.72)
    else:
        glColor3f(0.10, 0.12, 0.15)
    glPushMatrix()
    glTranslatef(0.0, 0.256, 0.0)
    _draw_cylinder(0.044, 0.044, 0.005, sides=12)
    glPopMatrix()

    glPopAttrib()
    glMatrixMode(GL_PROJECTION); glPopMatrix()
    glMatrixMode(GL_MODELVIEW); glPopMatrix()
    glEnable(GL_DEPTH_TEST)

