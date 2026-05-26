import random
import math
import pygame
from OpenGL.GL import *
from .settings import DISPLAY_SIZE

# ================================
# PARTÍCULAS (NEVE CAINDO)
# ================================
NUM_PARTICLES = 400
particles = []
for _ in range(NUM_PARTICLES):
    particles.append([
        random.uniform(-15, 15), # dx
        random.uniform(-1, 10),  # y
        random.uniform(-15, 15), # dz
        random.uniform(0.02, 0.08) # velocidade
    ])

def draw_particles(player_x, player_z):
    glPushAttrib(GL_ENABLE_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glPointSize(3.0) 
    glColor3fv((0.8, 0.9, 1.0)) 
    glBegin(GL_POINTS)
    for p in particles:
        px = player_x + p[0]
        py = p[1]
        pz = player_z + p[2]
        
        glVertex3f(px, py, pz)
        
        p[1] -= p[3]
        p[0] -= 0.01
        
        if p[1] < -1 or p[0] < -15:
            p[1] = 10.0
            p[0] = random.uniform(-15, 15)
            p[2] = random.uniform(-15, 15)
            
    glEnd()
    glPopAttrib()


# ================================
# PEGADAS NA NEVE
# ================================
MAX_FOOTPRINTS = 300
footprints = []
_last_footprint_pos = [None]
FOOTPRINT_SPACING = 0.6
FOOTPRINT_LIFE_MS  = 3000

def maybe_add_footprint(px, pz, yaw, is_moving):
    if not is_moving:
        return
    last = _last_footprint_pos[0]
    if last is not None:
        dx = px - last[0]
        dz = pz - last[1]
        if math.sqrt(dx*dx + dz*dz) < FOOTPRINT_SPACING:
            return
    footprints.append((px, pz, yaw, pygame.time.get_ticks()))
    _last_footprint_pos[0] = (px, pz)
    if len(footprints) > MAX_FOOTPRINTS:
        footprints.pop(0)

def draw_footprints():
    if not footprints:
        return
    now = pygame.time.get_ticks()
    while footprints and now - footprints[0][3] > FOOTPRINT_LIFE_MS:
        footprints.pop(0)
    if not footprints:
        return

    glPushAttrib(GL_ENABLE_BIT | GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glEnable(GL_POLYGON_OFFSET_FILL)
    glPolygonOffset(-1.0, -1.0)

    FLOOR_Y = -0.98
    W    = 0.12
    L    = 0.22
    SIDE = 0.18

    glBegin(GL_QUADS)
    for idx, (fx, fz, fyw, ts) in enumerate(footprints):
        age_ratio = (now - ts) / FOOTPRINT_LIFE_MS
        alpha = (1.0 - age_ratio) * 0.55
        glColor4f(0.55, 0.65, 0.72, alpha)

        fx_dir = math.cos(fyw)
        fz_dir = math.sin(fyw)
        rx = math.cos(fyw + math.pi / 2)
        rz = math.sin(fyw + math.pi / 2)

        side = SIDE if idx % 2 == 0 else -SIDE
        cx = fx + rx * side
        cz = fz + rz * side

        glVertex3f(cx + fx_dir*L - rx*W, FLOOR_Y, cz + fz_dir*L - rz*W)
        glVertex3f(cx + fx_dir*L + rx*W, FLOOR_Y, cz + fz_dir*L + rz*W)
        glVertex3f(cx - fx_dir*L + rx*W, FLOOR_Y, cz - fz_dir*L + rz*W)
        glVertex3f(cx - fx_dir*L - rx*W, FLOOR_Y, cz - fz_dir*L - rz*W)
    glEnd()
    glPopAttrib()


# ================================
# BAFADAS DE FRIO
# ================================
def draw_breath_puffs(breath_puffs, now_ms, yaw):
    if not breath_puffs: return
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    
    cam_right_x = math.cos(yaw + math.pi/2)
    cam_right_z = math.sin(yaw + math.pi/2)
    
    for p in breath_puffs:
        age    = (now_ms - p[0]) / 1500.0
        alpha  = (1.0 - age) * 0.45
        size   = 0.05 + age * 0.35
        wx = p[1] + p[4] * age * 0.6
        wy = p[2] + age * 0.25
        wz = p[3] + p[5] * age * 0.6
        
        glColor4f(0.85, 0.92, 1.0, alpha)
        glBegin(GL_QUADS)
        glVertex3f(wx - cam_right_x*size, wy - size, wz - cam_right_z*size)
        glVertex3f(wx + cam_right_x*size, wy - size, wz + cam_right_z*size)
        glVertex3f(wx + cam_right_x*size, wy + size, wz + cam_right_z*size)
        glVertex3f(wx - cam_right_x*size, wy + size, wz - cam_right_z*size)
        glEnd()
    glPopAttrib()


# ================================
# HUD DE ANSIEDADE
# ================================
def draw_anxiety_hud(anxiety):
    W, H = DISPLAY_SIZE
    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    glOrtho(0, W, H, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glDisable(GL_DEPTH_TEST)
    glDisable(GL_FOG)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    BAR_W  = 200
    BAR_H  = 14
    BAR_X  = W // 2 - BAR_W // 2
    BAR_Y  = H - 36
    FILL   = int(BAR_W * anxiety)

    glColor4f(0.0, 0.0, 0.0, 0.55)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X - 2,        BAR_Y - 2)
    glVertex2f(BAR_X + BAR_W+2,  BAR_Y - 2)
    glVertex2f(BAR_X + BAR_W+2,  BAR_Y + BAR_H+2)
    glVertex2f(BAR_X - 2,        BAR_Y + BAR_H+2)
    glEnd()

    r = min(1.0, anxiety * 2.0)
    g = min(1.0, (1.0 - anxiety) * 2.0)
    glColor4f(r, g, 0.0, 0.9)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X,        BAR_Y)
    glVertex2f(BAR_X + FILL, BAR_Y)
    glVertex2f(BAR_X + FILL, BAR_Y + BAR_H)
    glVertex2f(BAR_X,        BAR_Y + BAR_H)
    glEnd()

    if anxiety > 0.7:
        pulse = abs(math.sin(pygame.time.get_ticks() / 150.0))
        glColor4f(1.0, 0.0, 0.0, pulse * 0.35 * anxiety)
        glBegin(GL_QUADS)
        glVertex2f(0,  0); glVertex2f(W, 0)
        glVertex2f(W, H); glVertex2f(0, H)
        glEnd()

    glPopAttrib()
    glMatrixMode(GL_PROJECTION)
    glPopMatrix()
    glMatrixMode(GL_MODELVIEW)
    glPopMatrix()
    glEnable(GL_DEPTH_TEST)

def clear_footprints():
    footprints.clear()
    _last_footprint_pos[0] = None

