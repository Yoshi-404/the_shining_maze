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

def draw_particles(player_x, player_z, dt=0.0166):
    glPushAttrib(GL_ENABLE_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glPointSize(3.0) 
    glColor3fv((0.8, 0.9, 1.0)) 
    glBegin(GL_POINTS)
    step = dt * 60.0
    for p in particles:
        px = player_x + p[0]
        py = p[1]
        pz = player_z + p[2]
        
        glVertex3f(px, py, pz)
        
        p[1] -= p[3] * step
        p[0] -= 0.01 * step
        
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
# SANGUE NO CHÃO
# ================================
def draw_blood_trails(blood_decals):
    if not blood_decals:
        return

    glPushAttrib(GL_ENABLE_BIT | GL_DEPTH_BUFFER_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    glEnable(GL_POLYGON_OFFSET_FILL)
    glPolygonOffset(-1.5, -1.5)

    FLOOR_Y = -0.97
    
    glBegin(GL_QUADS)
    for (bx, bz, rot) in blood_decals:
        # Pinta uma mancha irregular de sangue escuro
        glColor4f(0.5, 0.05, 0.05, 0.85)
        
        S = 0.35
        cos_r = math.cos(rot) * S
        sin_r = math.sin(rot) * S
        
        # Faz um formato não perfeitamente quadrado para parecer uma mancha
        glVertex3f(bx - cos_r - sin_r*0.5, FLOOR_Y, bz - sin_r + cos_r*0.5)
        glVertex3f(bx + cos_r - sin_r*0.8, FLOOR_Y, bz + sin_r + cos_r*0.8)
        glVertex3f(bx + cos_r + sin_r*0.5, FLOOR_Y, bz + sin_r - cos_r*0.5)
        glVertex3f(bx - cos_r + sin_r*1.2, FLOOR_Y, bz - sin_r - cos_r*1.2)
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


def draw_anxiety_hud(anxiety, battery, stamina=1.0, hypothermia=0.0, blood_overlay_timer=0, flashlight_on=True, battery_toast_alpha=0.0):
    W, H = DISPLAY_SIZE
    now = pygame.time.get_ticks()

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
    BAR_H  = 8
    BAR_X  = W // 2 - BAR_W // 2

    STAMINA_Y = H - 46
    ANXIETY_Y = H - 32
    BATT_Y    = H - 18

    # ----------------------------------------------------
    # 1. Barra de Fôlego / Stamina (Ambar Dourado)
    # ----------------------------------------------------
    glColor4f(0.0, 0.0, 0.0, 0.65)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X - 2,        STAMINA_Y - 1)
    glVertex2f(BAR_X + BAR_W+2,  STAMINA_Y - 1)
    glVertex2f(BAR_X + BAR_W+2,  STAMINA_Y + BAR_H+1)
    glVertex2f(BAR_X - 2,        STAMINA_Y + BAR_H+1)
    glEnd()

    stam_fill = max(0, min(BAR_W, int(BAR_W * stamina)))
    if stamina > 0.25:
        glColor4f(0.95, 0.82, 0.22, 0.95)   # Ouro brilhante
    else:
        blink_stam = 0.5 + 0.5 * abs(math.sin(now / 120.0))
        glColor4f(0.95, 0.30 * blink_stam, 0.15, 0.95)   # Alerta de exaustão

    glBegin(GL_QUADS)
    glVertex2f(BAR_X,             STAMINA_Y)
    glVertex2f(BAR_X + stam_fill, STAMINA_Y)
    glVertex2f(BAR_X + stam_fill, STAMINA_Y + BAR_H)
    glVertex2f(BAR_X,             STAMINA_Y + BAR_H)
    glEnd()

    # Marcador de corrida / fôlego à esquerda
    glColor4f(0.95, 0.85, 0.30, 0.85 if stamina > 0.15 else 0.4)
    glBegin(GL_TRIANGLES)
    glVertex2f(BAR_X - 12, STAMINA_Y + BAR_H / 2.0)
    glVertex2f(BAR_X - 6,  STAMINA_Y + 1)
    glVertex2f(BAR_X - 6,  STAMINA_Y + BAR_H - 1)
    glEnd()

    # ----------------------------------------------------
    # 2. Barra de Ansiedade / Pânico (Violeta -> Rubi Pulsante)
    # ----------------------------------------------------
    glColor4f(0.0, 0.0, 0.0, 0.65)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X - 2,        ANXIETY_Y - 1)
    glVertex2f(BAR_X + BAR_W+2,  ANXIETY_Y - 1)
    glVertex2f(BAR_X + BAR_W+2,  ANXIETY_Y + BAR_H+1)
    glVertex2f(BAR_X - 2,        ANXIETY_Y + BAR_H+1)
    glEnd()

    anx_fill = max(0, min(BAR_W, int(BAR_W * anxiety)))
    anx_pulse = 1.0 + (0.15 * math.sin(now / 140.0) if anxiety > 0.70 else 0.0)
    if anxiety < 0.4:
        r_col, g_col, b_col = 0.30, 0.45, 0.75
    elif anxiety < 0.75:
        mix = (anxiety - 0.4) / 0.35
        r_col = 0.30 + mix * 0.65
        g_col = 0.45 - mix * 0.30
        b_col = 0.75 - mix * 0.55
    else:
        r_col, g_col, b_col = 0.98 * anx_pulse, 0.12, 0.15

    glColor4f(r_col, g_col, b_col, 0.95)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X,            ANXIETY_Y)
    glVertex2f(BAR_X + anx_fill, ANXIETY_Y)
    glVertex2f(BAR_X + anx_fill, ANXIETY_Y + BAR_H)
    glVertex2f(BAR_X,            ANXIETY_Y + BAR_H)
    glEnd()

    # Marcador de pânico à esquerda (Coração / Alerta)
    glColor4f(r_col, g_col, b_col, 0.90)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X - 10, ANXIETY_Y + 1)
    glVertex2f(BAR_X - 6,  ANXIETY_Y + 1)
    glVertex2f(BAR_X - 6,  ANXIETY_Y + BAR_H - 1)
    glVertex2f(BAR_X - 10, ANXIETY_Y + BAR_H - 1)
    glEnd()

    # ----------------------------------------------------
    # 3. Barra de Bateria da Lanterna (Ciano Elétrico)
    # ----------------------------------------------------
    glColor4f(0.0, 0.0, 0.0, 0.65)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X - 2,        BATT_Y - 1)
    glVertex2f(BAR_X + BAR_W+2,  BATT_Y - 1)
    glVertex2f(BAR_X + BAR_W+2,  BATT_Y + BAR_H+1)
    glVertex2f(BAR_X - 2,        BATT_Y + BAR_H+1)
    glEnd()

    batt_fill = max(0, min(BAR_W, int(BAR_W * battery)))
    if not flashlight_on:
        glColor4f(0.35, 0.35, 0.40, 0.5)
    elif battery > 0.45:
        glColor4f(0.0, 0.85, 1.0, 0.95)   # Ciano elétrico
    elif battery > 0.20:
        glColor4f(1.0, 0.85, 0.15, 0.95)  # Amarelo
    else:
        blink = abs(math.sin(now / 150.0))
        glColor4f(1.0, 0.10, 0.10, 0.5 + blink * 0.45)

    glBegin(GL_QUADS)
    glVertex2f(BAR_X,             BATT_Y)
    glVertex2f(BAR_X + batt_fill, BATT_Y)
    glVertex2f(BAR_X + batt_fill, BATT_Y + BAR_H)
    glVertex2f(BAR_X,             BATT_Y + BAR_H)
    glEnd()

    # LED indicador da lanterna ligada/desligada
    led_x = BAR_X - 10
    led_y = BATT_Y + 1
    if flashlight_on and battery > 0.02:
        glColor4f(1.0, 0.95, 0.4, 0.95)
    else:
        glColor4f(0.2, 0.2, 0.25, 0.7)
    glBegin(GL_QUADS)
    glVertex2f(led_x,     led_y)
    glVertex2f(led_x + 4, led_y)
    glVertex2f(led_x + 4, led_y + BAR_H - 2)
    glVertex2f(led_x,     led_y + BAR_H - 2)
    glEnd()

    # Toast/Notificação visual de recarga de bateria
    if battery_toast_alpha > 0.0:
        toast_w = 210
        toast_h = 16
        toast_x = W // 2 - toast_w // 2
        toast_y = STAMINA_Y - 22
        glColor4f(0.04, 0.22, 0.12, 0.75 * battery_toast_alpha)
        glBegin(GL_QUADS)
        glVertex2f(toast_x, toast_y)
        glVertex2f(toast_x + toast_w, toast_y)
        glVertex2f(toast_x + toast_w, toast_y + toast_h)
        glVertex2f(toast_x, toast_y + toast_h)
        glEnd()

        glColor4f(0.2, 0.95, 0.45, 0.9 * battery_toast_alpha)
        glLineWidth(1.5)
        glBegin(GL_LINE_LOOP)
        glVertex2f(toast_x, toast_y)
        glVertex2f(toast_x + toast_w, toast_y)
        glVertex2f(toast_x + toast_w, toast_y + toast_h)
        glVertex2f(toast_x, toast_y + toast_h)
        glEnd()


    if anxiety > 0.7:
        pulse = abs(math.sin(pygame.time.get_ticks() / 150.0))
        glColor4f(1.0, 0.0, 0.0, pulse * 0.35 * anxiety)
        glBegin(GL_QUADS)
        glVertex2f(0,  0); glVertex2f(W, 0)
        glVertex2f(W, H); glVertex2f(0, H)
        glEnd()

    if hypothermia > 0.0:
        pulse_ice = 0.5 + 0.5 * math.sin(pygame.time.get_ticks() / 200.0)
        alpha = (hypothermia * 0.4) + (pulse_ice * 0.2 * hypothermia)
        glColor4f(0.6, 0.8, 1.0, alpha)
        glBegin(GL_QUADS)
        glVertex2f(0,  0); glVertex2f(W, 0)
        glVertex2f(W, H); glVertex2f(0, H)
        glEnd()

    if blood_overlay_timer > 0:
        alpha = min(1.0, blood_overlay_timer / 3000.0) * 0.6  # 3 segundos máx
        glColor4f(0.8, 0.0, 0.0, alpha)
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

def draw_ceiling_drips(zones, now_ms):
    """Desenha gotas de sangue caindo do teto em áreas específicas."""
    if not zones:
        return
        
    from game.settings import BLOCK_SIZE
    from game.renderer import WALL_HEIGHT
    
    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)
    
    glColor4f(0.8, 0.0, 0.0, 0.7)
    
    glBegin(GL_QUADS)
    for zx, zz in zones:
        wx = zx * BLOCK_SIZE
        wz = zz * BLOCK_SIZE
        # O teto fica em WALL_HEIGHT/2, o chão em -1.0
        # Gera gotas pseudo-aleatórias baseadas na posição e tempo
        for i in range(5):
            # Fase pseudo-aleatória por gota
            phase = (zx * 13.3 + zz * 7.7 + i * 11.1) % 1000.0
            speed = 3.0 + (i % 3)
            drop_y = (WALL_HEIGHT/2) - ((now_ms / 1000.0 * speed + phase) % (WALL_HEIGHT/2 + 1.0))
            
            # Posição X e Z da gota dentro do bloco
            drop_x = wx + ((i * 3.7) % BLOCK_SIZE) - BLOCK_SIZE/2
            drop_z = wz + ((i * 5.1) % BLOCK_SIZE) - BLOCK_SIZE/2
            
            s = 0.02 # Tamanho da gota
            
            glVertex3f(drop_x - s, drop_y - s*3, drop_z)
            glVertex3f(drop_x + s, drop_y - s*3, drop_z)
            glVertex3f(drop_x + s, drop_y + s,   drop_z)
            glVertex3f(drop_x - s, drop_y + s,   drop_z)
            
            glVertex3f(drop_x, drop_y - s*3, drop_z - s)
            glVertex3f(drop_x, drop_y - s*3, drop_z + s)
            glVertex3f(drop_x, drop_y + s,   drop_z + s)
            glVertex3f(drop_x, drop_y + s,   drop_z - s)
    glEnd()
    
    glPopAttrib()
