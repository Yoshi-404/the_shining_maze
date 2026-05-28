"""Módulo de renderização OpenGL: texturas, iluminação, neblina e geometria."""
import math
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
    glEnable(GL_LIGHT0)
    glLightfv(GL_LIGHT0, GL_AMBIENT,  (0.04, 0.04, 0.08, 1.0))
    glLightfv(GL_LIGHT0, GL_DIFFUSE,  (0.8,  0.8,  0.9,  1.0))
    glLightfv(GL_LIGHT0, GL_SPECULAR, (0.2,  0.2,  0.2,  1.0))
    glLightf (GL_LIGHT0, GL_SPOT_CUTOFF,   35.0)
    glLightf (GL_LIGHT0, GL_SPOT_EXPONENT, 10.0)
    glEnable(GL_COLOR_MATERIAL)
    glColorMaterial(GL_FRONT_AND_BACK, GL_AMBIENT_AND_DIFFUSE)


# ---------------------------------------------------------------------------
# Neblina volumétrica
# ---------------------------------------------------------------------------
def setup_fog() -> tuple:
    fog_color = (0.02, 0.04, 0.08, 1.0)
    glEnable(GL_FOG)
    glFogi(GL_FOG_MODE, GL_EXP2)
    glFogfv(GL_FOG_COLOR, fog_color)
    glFogf(GL_FOG_DENSITY, 0.09)
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
    if tex_snow:
        glBindTexture(GL_TEXTURE_2D, tex_snow)
    glBegin(GL_QUADS)
    glNormal3f(0, 1, 0)
    glColor3f(1.0, 1.0, 1.0)   # branco puro para a neve
    fw, fh = W * BLOCK_SIZE, H * BLOCK_SIZE
    glTexCoord2f(0,  0 ); glVertex3f(-fw, -1, -fh)
    glTexCoord2f(W,  0 ); glVertex3f( fw, -1, -fh)
    glTexCoord2f(W,  H ); glVertex3f( fw, -1,  fh)
    glTexCoord2f(0,  H ); glVertex3f(-fw, -1,  fh)
    glEnd()


def draw_skybox(tex_skybox, px, py, pz):
    if not tex_skybox:
        return
    glPushMatrix()
    glTranslatef(px, py, pz)
    glScalef(40, 40, 40)
    glPushAttrib(GL_ENABLE_BIT | GL_DEPTH_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_FOG)
    glDepthMask(GL_FALSE)
    glBindTexture(GL_TEXTURE_2D, tex_skybox)
    glBegin(GL_QUADS)
    glColor3f(1, 1, 1)
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
    """Compila chão + paredes na VRAM (Display List OpenGL)."""
    dlist = glGenLists(1)
    glNewList(dlist, GL_COMPILE)
    draw_floor(tex_snow, W, H)
    draw_walls(maze_map, W, H, tex_hedge)
    glEndList()
    return dlist
