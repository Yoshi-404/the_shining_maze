import math
import numpy as np
import pygame
from OpenGL.GL import *
from OpenGL.GLU import *
from .settings import BLOCK_SIZE, WALL_HEIGHT

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


def draw_exit(maze_map, W, H):
    """Desenha a saída como um marcador luminoso no chão."""
    t = pygame.time.get_ticks() / 1000.0
    pulse = 0.6 + 0.4 * math.sin(t * 2.5)

    for y in range(H):
        for x in range(W):
            if maze_map[y][x] == 2 or maze_map[y][x] == 3:
                cx = (x - W/2) * BLOCK_SIZE
                cz = (y - H/2) * BLOCK_SIZE
                FLOOR_Y = -0.97  # Logo acima do chão para evitar z-fighting

                glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
                glDisable(GL_LIGHTING)
                glDisable(GL_TEXTURE_2D)
                glEnable(GL_BLEND)
                glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
                glEnable(GL_POLYGON_OFFSET_FILL)
                glPolygonOffset(-2.0, -2.0)

                half = BLOCK_SIZE * 0.9

                # Brilho externo (halo grande, avermelhado transparente)
                glColor4f(0.9 * pulse, 0.1 * pulse, 0.1 * pulse, 0.25 * pulse)
                glBegin(GL_QUADS)
                glVertex3f(cx - half * 1.3, FLOOR_Y, cz - half * 1.3)
                glVertex3f(cx + half * 1.3, FLOOR_Y, cz - half * 1.3)
                glVertex3f(cx + half * 1.3, FLOOR_Y, cz + half * 1.3)
                glVertex3f(cx - half * 1.3, FLOOR_Y, cz + half * 1.3)
                glEnd()

                # Quadrado principal (vermelho vivo brilhante)
                glColor4f(1.0 * pulse, 0.1, 0.1, 0.7)
                glBegin(GL_QUADS)
                glVertex3f(cx - half, FLOOR_Y + 0.01, cz - half)
                glVertex3f(cx + half, FLOOR_Y + 0.01, cz - half)
                glVertex3f(cx + half, FLOOR_Y + 0.01, cz + half)
                glVertex3f(cx - half, FLOOR_Y + 0.01, cz + half)
                glEnd()

                # Anel interno pulsante
                inner = half * (0.4 + 0.15 * math.sin(t * 4.0))
                glColor4f(1.0, 0.5, 0.5, 0.85 * pulse)
                glBegin(GL_QUADS)
                glVertex3f(cx - inner, FLOOR_Y + 0.02, cz - inner)
                glVertex3f(cx + inner, FLOOR_Y + 0.02, cz - inner)
                glVertex3f(cx + inner, FLOOR_Y + 0.02, cz + inner)
                glVertex3f(cx - inner, FLOOR_Y + 0.02, cz + inner)
                glEnd()

                glPopAttrib()


def draw_campfires(campfires):
    if not campfires:
        return
    t = pygame.time.get_ticks() / 1000.0
    pulse = 0.7 + 0.3 * math.sin(t * 5.0)

    for cx, cz in campfires:
        FLOOR_Y = -0.97

        glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        glDisable(GL_LIGHTING)
        glDisable(GL_TEXTURE_2D)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        # 1. Halo no chão (menor e bem suave, para não parecer saída)
        glEnable(GL_POLYGON_OFFSET_FILL)
        glPolygonOffset(-2.0, -2.0)
        half = BLOCK_SIZE * 0.5
        glColor4f(1.0, 0.4, 0.0, 0.15 * pulse)
        glBegin(GL_QUADS)
        glVertex3f(cx - half, FLOOR_Y, cz - half)
        glVertex3f(cx + half, FLOOR_Y, cz - half)
        glVertex3f(cx + half, FLOOR_Y, cz + half)
        glVertex3f(cx - half, FLOOR_Y, cz + half)
        glEnd()
        glDisable(GL_POLYGON_OFFSET_FILL)

        # 2. Objeto 3D: Um pequeno "aquecedor" ou lanterna brilhante flutuando/apoiada
        glPushMatrix()
        # Flutua levemente
        hover = 0.05 * math.sin(t * 3.0 + cx)
        glTranslatef(cx, FLOOR_Y + 0.25 + hover, cz)
        glScalef(0.12, 0.15, 0.12)  # Um pequeno pilar/caixa

        glColor4f(1.0, 0.7 * pulse, 0.1, 0.9)
        glBegin(GL_QUADS)
        for face in _SURFACES:
            for v in face:
                glVertex3fv(_VERTICES[v])
        glEnd()

        # Cubo interno mais brilhante
        glScalef(0.7, 0.7, 0.7)
        glColor4f(1.0, 1.0, 0.8, 1.0)
        glBegin(GL_QUADS)
        for face in _SURFACES:
            for v in face:
                glVertex3fv(_VERTICES[v])
        glEnd()

        glPopMatrix()
        glPopAttrib()


def draw_corpse(tex_corpse, cx, cz):
    if not tex_corpse:
        return
        
    FLOOR_Y = -0.96  # Logo acima do chão e do sangue

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glEnable(GL_LIGHTING)
    glEnable(GL_TEXTURE_2D)
    glBindTexture(GL_TEXTURE_2D, tex_corpse)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glEnable(GL_POLYGON_OFFSET_FILL)
    glPolygonOffset(-2.5, -2.5)

    half = BLOCK_SIZE * 0.45
    glColor3f(1.0, 1.0, 1.0)
    
    glBegin(GL_QUADS)
    glNormal3f(0, 1, 0)
    glTexCoord2f(0, 0); glVertex3f(cx - half, FLOOR_Y, cz - half)
    glTexCoord2f(1, 0); glVertex3f(cx + half, FLOOR_Y, cz - half)
    glTexCoord2f(1, 1); glVertex3f(cx + half, FLOOR_Y, cz + half)
    glTexCoord2f(0, 1); glVertex3f(cx - half, FLOOR_Y, cz + half)
    glEnd()

    glPopAttrib()


def draw_floor(tex_snow, W, H):
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    if tex_snow:
        glEnable(GL_TEXTURE_2D)
        glBindTexture(GL_TEXTURE_2D, tex_snow)
    else:
        glDisable(GL_TEXTURE_2D)
    glBegin(GL_QUADS)
    glNormal3f(0.0, 1.0, 0.0)
    glColor3f(1.0, 1.0, 1.0)
    fw, fh = W * BLOCK_SIZE, H * BLOCK_SIZE
    uv_u = (2.0 * fw) / BLOCK_SIZE
    uv_v = (2.0 * fh) / BLOCK_SIZE
    glTexCoord2f(0.0,  0.0);  glVertex3f(-fw, -1.0, -fh)
    glTexCoord2f(uv_u, 0.0);  glVertex3f( fw, -1.0, -fh)
    glTexCoord2f(uv_u, uv_v); glVertex3f( fw, -1.0,  fh)
    glTexCoord2f(0.0,  uv_v); glVertex3f(-fw, -1.0,  fh)
    glEnd()
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

    uv_v_scale = WALL_HEIGHT / 2.0
    FLOOR_Y = -1.0
    CEIL_Y  = WALL_HEIGHT - 1.0
    half_b  = BLOCK_SIZE * 0.5

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
                        glNormal3f(0.0, 0.0, -1.0)
                        glTexCoord2f(1.0, 0.0);        glVertex3f(bx1, FLOOR_Y, bz0)
                        glTexCoord2f(1.0, uv_v_scale); glVertex3f(bx1, CEIL_Y,  bz0)
                        glTexCoord2f(0.0, uv_v_scale); glVertex3f(bx0, CEIL_Y,  bz0)
                        glTexCoord2f(0.0, 0.0);        glVertex3f(bx0, FLOOR_Y, bz0)

                    # Face Sul (Z+) - apenas se adjacente não for parede
                    if my == H - 1 or maze_map[my + 1][mx] != 1:
                        glNormal3f(0.0, 0.0, 1.0)
                        glTexCoord2f(0.0, 0.0);        glVertex3f(bx0, FLOOR_Y, bz1)
                        glTexCoord2f(0.0, uv_v_scale); glVertex3f(bx0, CEIL_Y,  bz1)
                        glTexCoord2f(1.0, uv_v_scale); glVertex3f(bx1, CEIL_Y,  bz1)
                        glTexCoord2f(1.0, 0.0);        glVertex3f(bx1, FLOOR_Y, bz1)

                    # Face Oeste (X-) - apenas se adjacente não for parede
                    if mx == 0 or maze_map[my][mx - 1] != 1:
                        glNormal3f(-1.0, 0.0, 0.0)
                        glTexCoord2f(0.0, 0.0);        glVertex3f(bx0, FLOOR_Y, bz0)
                        glTexCoord2f(0.0, uv_v_scale); glVertex3f(bx0, CEIL_Y,  bz0)
                        glTexCoord2f(1.0, uv_v_scale); glVertex3f(bx0, CEIL_Y,  bz1)
                        glTexCoord2f(1.0, 0.0);        glVertex3f(bx0, FLOOR_Y, bz1)

                    # Face Leste (X+) - apenas se adjacente não for parede
                    if mx == W - 1 or maze_map[my][mx + 1] != 1:
                        glNormal3f(1.0, 0.0, 0.0)
                        glTexCoord2f(1.0, 0.0);        glVertex3f(bx1, FLOOR_Y, bz1)
                        glTexCoord2f(1.0, uv_v_scale); glVertex3f(bx1, CEIL_Y,  bz1)
                        glTexCoord2f(0.0, uv_v_scale); glVertex3f(bx1, CEIL_Y,  bz0)
                        glTexCoord2f(0.0, 0.0);        glVertex3f(bx1, FLOOR_Y, bz0)

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
# Billboard 3D Animado do Jack Torrance com Machado
# ---------------------------------------------------------------------------
def draw_jack_billboard(tex_jack, jack_wx, jack_wz, player_x, player_z, jack_dist, madness, now_ms, is_fake=False):
    """Renderiza o Jack Torrance empunhando machado como um Billboard 3D animado voltado para a câmera."""
    if not tex_jack or jack_dist > 45.0:
        return

    dx = player_x - jack_wx
    dz = player_z - jack_wz
    angle_rad = math.atan2(dx, dz)
    angle_deg = math.degrees(angle_rad)

    FLOOR_Y = -1.0
    t_s = now_ms / 1000.0

    # Frequência da animação de marcha (acelera quando Jack está caçando perto)
    walk_freq = 7.5 if jack_dist < 12.0 else 4.0
    bob_h = abs(math.sin(t_s * walk_freq)) * 0.08
    sway_x = math.sin(t_s * (walk_freq * 0.5)) * 0.04
    scale_pulse = 1.0 + (0.05 * math.sin(t_s * 6.0) if jack_dist < 8.0 else 0.0)

    half_w = 0.95 * scale_pulse
    h = 2.45 * scale_pulse

    glPushMatrix()
    glTranslatef(jack_wx + sway_x, FLOOR_Y + bob_h, jack_wz)
    glRotatef(angle_deg, 0.0, 1.0, 0.0)

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
    glEnable(GL_TEXTURE_2D)
    glBindTexture(GL_TEXTURE_2D, tex_jack)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glEnable(GL_ALPHA_TEST)
    glAlphaFunc(GL_GREATER, 0.15)

    if is_fake:
        # Falsos Jacks: espectrais, translúcidos e pulsando
        alpha = 0.65 + 0.25 * math.sin(t_s * 4.0)
        glColor4f(0.8, 0.85, 1.0, alpha)
    else:
        # Jack real: tons opressivos e levemente avermelhados com alta loucura
        red_tint = min(0.3, madness * 0.3)
        glColor4f(1.0, 1.0 - red_tint, 1.0 - red_tint, 1.0)

    glBegin(GL_QUADS)
    glNormal3f(0.0, 0.0, 1.0)
    glTexCoord2f(0.0, 1.0); glVertex3f(-half_w, 0.0, 0.0)
    glTexCoord2f(1.0, 1.0); glVertex3f( half_w, 0.0, 0.0)
    glTexCoord2f(1.0, 0.0); glVertex3f( half_w, h,   0.0)
    glTexCoord2f(0.0, 0.0); glVertex3f(-half_w, h,   0.0)
    glEnd()

    glPopAttrib()
    glPopMatrix()

