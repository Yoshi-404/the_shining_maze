import random
import math
import pygame
from OpenGL.GL import *
from .settings import DISPLAY_SIZE

# ================================
# PARTÍCULAS (NEVE CAINDO)
# ================================
NUM_PARTICLES = 600
particles = []
for _ in range(NUM_PARTICLES):
    particles.append([
        random.uniform(-15.0, 15.0),  # dx
        random.uniform(-1.0, 10.5),   # y
        random.uniform(-15.0, 15.0),  # dz
        random.uniform(0.02, 0.08),   # velocidade vertical base
        random.uniform(0.0, 6.283),   # fase de turbulência
    ])


def draw_particles(player_x, player_z, dt=0.0166, blizzard_intensity=0.0):
    blizzard = max(0.0, min(1.0, float(blizzard_intensity)))
    active_count = min(len(particles), int(360 + 240 * blizzard))
    step = max(0.0, dt * 60.0)
    fall_mult = 1.0 + 1.75 * blizzard
    wind_x = 0.012 + 0.165 * blizzard
    wind_z = 0.004 + 0.075 * blizzard

    glPushAttrib(GL_ENABLE_BIT | GL_POINT_BIT | GL_LINE_BIT | GL_COLOR_BUFFER_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    if blizzard > 0.12:
        glLineWidth(1.2 + 0.8 * blizzard)
        streak = 1.45 * blizzard
        head_alpha = 0.18 + 0.42 * blizzard
        glBegin(GL_LINES)
        for p in particles[:active_count]:
            px = player_x + p[0]
            py = p[1]
            pz = player_z + p[2]
            vy = p[3] * fall_mult
            glColor4f(0.84, 0.92, 1.0, head_alpha)
            glVertex3f(px, py, pz)
            glColor4f(0.76, 0.86, 0.98, 0.0)
            glVertex3f(px + wind_x * streak, py + vy * streak, pz + wind_z * streak)
        glEnd()

    glPointSize(2.6 + 0.9 * blizzard)
    glColor4f(0.84, 0.92, 1.0, 0.78 + 0.20 * blizzard)
    glBegin(GL_POINTS)
    for p in particles[:active_count]:
        px = player_x + p[0]
        py = p[1]
        pz = player_z + p[2]
        glVertex3f(px, py, pz)

        if step > 0.0:
            vy = p[3] * fall_mult
            turb = math.sin(p[4] + p[1] * 0.7) * (0.015 + 0.045 * blizzard)
            p[1] -= vy * step
            p[0] -= (wind_x + turb) * step
            p[2] -= (wind_z - turb * 0.5) * step

            if p[0] < -15.0 or p[0] > 15.0:
                p[0] = ((p[0] + 15.0) % 30.0) - 15.0
            if p[2] < -15.0 or p[2] > 15.0:
                p[2] = ((p[2] + 15.0) % 30.0) - 15.0

            if p[1] < -1.0:
                p[1] = random.uniform(8.8, 10.5)
                p[0] = random.uniform(-15.0, 15.0)
                p[2] = random.uniform(-15.0, 15.0)

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

def maybe_add_footprint(px, pz, yaw, is_moving, now_ms=None):
    if not is_moving:
        return
    if now_ms is None:
        now_ms = pygame.time.get_ticks()
    last = _last_footprint_pos[0]
    if last is not None:
        dx = px - last[0]
        dz = pz - last[1]
        if math.sqrt(dx*dx + dz*dz) < FOOTPRINT_SPACING:
            return
    footprints.append((px, pz, yaw, now_ms))
    _last_footprint_pos[0] = (px, pz)
    if len(footprints) > MAX_FOOTPRINTS:
        footprints.pop(0)

def draw_footprints(now_ms=None):
    if not footprints:
        return
    now = pygame.time.get_ticks() if now_ms is None else now_ms
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


def _draw_edge_vignette(w, h, bx, by, r, g, b, alpha):
    """Gradiente perimetral suave usando vertex colors (centro 100% transparente)."""
    if alpha <= 0.005:
        return
    outer = (
        (0.0, 0.0), (w, 0.0), (w, h), (0.0, h), (0.0, 0.0)
    )
    inner = (
        (bx, by), (w - bx, by), (w - bx, h - by), (bx, h - by), (bx, by)
    )
    glBegin(GL_TRIANGLE_STRIP)
    for (ox, oy), (ix, iy) in zip(outer, inner):
        glColor4f(r, g, b, alpha)
        glVertex2f(ox, oy)
        glColor4f(r, g, b, 0.0)
        glVertex2f(ix, iy)
    glEnd()


def _draw_frost_border(w, h, hypothermia, now):
    """Cristais e veios de geada crescendo pelas bordas da tela na hipotermia."""
    if hypothermia <= 0.02:
        return
    strength = min(1.0, hypothermia)
    shimmer = 0.85 + 0.15 * math.sin(now / 260.0)
    reach_x = w * (0.06 + 0.14 * strength)
    reach_y = h * (0.06 + 0.15 * strength)

    # Shards triangulares ancorados nas 4 bordas e nos 4 cantos
    glBegin(GL_TRIANGLES)
    for i in range(28):
        side = i % 4
        t = ((i * 37 + 13) % 100) / 100.0
        base_half = 16.0 + ((i * 19) % 24)
        length = (0.45 + 0.55 * (((i * 29 + 7) % 100) / 100.0))
        a_base = (0.28 + 0.42 * strength) * shimmer

        if side == 0:  # topo
            cx = t * w
            tip_y = length * reach_y
            pts = ((cx - base_half, 0.0), (cx + base_half, 0.0), (cx + math.sin(i) * 14.0, tip_y))
        elif side == 1:  # fundo
            cx = t * w
            tip_y = h - length * reach_y
            pts = ((cx - base_half, h), (cx + base_half, h), (cx - math.sin(i) * 14.0, tip_y))
        elif side == 2:  # esquerda
            cy = t * h
            tip_x = length * reach_x
            pts = ((0.0, cy - base_half), (0.0, cy + base_half), (tip_x, cy + math.cos(i) * 12.0))
        else:  # direita
            cy = t * h
            tip_x = w - length * reach_x
            pts = ((w, cy - base_half), (w, cy + base_half), (tip_x, cy - math.cos(i) * 12.0))

        glColor4f(0.82, 0.94, 1.0, a_base)
        glVertex2f(*pts[0])
        glVertex2f(*pts[1])
        glColor4f(0.55, 0.82, 0.98, 0.0)
        glVertex2f(*pts[2])

    # Agulhas diagonais maiores saindo dos 4 cantos
    corners = ((0.0, 0.0, 1.0, 1.0), (w, 0.0, -1.0, 1.0), (w, h, -1.0, -1.0), (0.0, h, 1.0, -1.0))
    for cx, cy, sx, sy in corners:
        for k in range(3):
            ang = 0.25 + k * 0.48
            dist = (0.75 + 0.25 * (k % 2)) * (reach_x * 1.15)
            spread = 22.0 + k * 6.0
            tx = cx + sx * math.cos(ang) * dist
            ty = cy + sy * math.sin(ang) * dist
            glColor4f(0.88, 0.96, 1.0, (0.35 + 0.45 * strength) * shimmer)
            glVertex2f(cx + sx * spread, cy)
            glVertex2f(cx, cy + sy * spread)
            glColor4f(0.60, 0.85, 1.0, 0.0)
            glVertex2f(tx, ty)
    glEnd()

    # Galhos cristalinos finos quando a hipotermia passa de 30%
    if strength > 0.30:
        line_alpha = min(0.70, (strength - 0.30) * 0.95) * shimmer
        glLineWidth(1.2)
        glBegin(GL_LINES)
        for cx, cy, sx, sy in corners:
            for k in range(4):
                ang = 0.18 + k * 0.36
                trunk = (0.55 + 0.45 * ((k + 1) / 4.0)) * reach_x * 1.25
                mx = cx + sx * math.cos(ang) * (trunk * 0.55)
                my = cy + sy * math.sin(ang) * (trunk * 0.55)
                ex = cx + sx * math.cos(ang) * trunk
                ey = cy + sy * math.sin(ang) * trunk
                glColor4f(0.85, 0.95, 1.0, line_alpha)
                glVertex2f(cx, cy)
                glColor4f(0.65, 0.88, 1.0, line_alpha * 0.35)
                glVertex2f(mx, my)
                glVertex2f(mx, my)
                glColor4f(0.60, 0.85, 1.0, 0.0)
                glVertex2f(ex, ey)
                # Ramificacao lateral
                glColor4f(0.75, 0.92, 1.0, line_alpha * 0.45)
                glVertex2f(mx, my)
                glColor4f(0.60, 0.85, 1.0, 0.0)
                glVertex2f(mx + sx * 18.0, my + sy * 8.0)
        glEnd()


def _draw_chamfered_rect(x, y, w, h, chamfer, filled=True):
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


def _draw_hud_icons(panel_x, stam_y, anx_y, batt_y, stamina, anxiety, anx_col, battery, flashlight_on, now):
    ix = panel_x + 20.0

    # Icone de folego: duplo chevron de velocidade
    glColor4f(0.95, 0.82, 0.25, 0.92 if stamina > 0.15 else 0.45)
    glBegin(GL_TRIANGLES)
    for off in (-3.5, 2.0):
        glVertex2f(ix - 3.0 + off, stam_y - 3.5)
        glVertex2f(ix + 3.0 + off, stam_y)
        glVertex2f(ix - 3.0 + off, stam_y + 3.5)
    glEnd()

    # Icone de ansiedade: coracao estilizado pulsando com o ritmo da ansiedade
    beat_hz = 1.4 + anxiety * 4.2
    beat = abs(math.sin((now / 1000.0) * math.pi * beat_hz))
    scale = 1.0 + 0.22 * (beat ** 3)
    r, g, b = anx_col
    glColor4f(r, g, b, 0.95)
    hs = 4.6 * scale
    glBegin(GL_TRIANGLES)
    glVertex2f(ix - hs, anx_y - 0.5 * scale)
    glVertex2f(ix, anx_y - 0.5 * scale)
    glVertex2f(ix - hs * 0.5, anx_y - hs * 0.72)
    glVertex2f(ix, anx_y - 0.5 * scale)
    glVertex2f(ix + hs, anx_y - 0.5 * scale)
    glVertex2f(ix + hs * 0.5, anx_y - hs * 0.72)
    glVertex2f(ix - hs, anx_y - 0.5 * scale)
    glVertex2f(ix + hs, anx_y - 0.5 * scale)
    glVertex2f(ix, anx_y + hs * 0.95)
    glEnd()

    # Icone de bateria: raio eletrico + LED indicador de lanterna ligada
    if not flashlight_on or battery <= 0.02:
        glColor4f(0.45, 0.48, 0.55, 0.75)
    elif battery > 0.20:
        glColor4f(0.20, 0.88, 1.0, 0.95)
    else:
        glColor4f(1.0, 0.25, 0.20, 0.6 + 0.4 * abs(math.sin(now / 140.0)))
    glBegin(GL_TRIANGLES)
    glVertex2f(ix + 1.5, batt_y - 5.2)
    glVertex2f(ix - 3.2, batt_y + 0.4)
    glVertex2f(ix + 0.8, batt_y + 0.4)
    glVertex2f(ix - 0.4, batt_y - 0.4)
    glVertex2f(ix + 3.4, batt_y - 0.4)
    glVertex2f(ix - 1.5, batt_y + 5.2)
    glEnd()

    # Micro LED da lanterna ao lado do raio
    led_x = ix + 8.0
    if flashlight_on and battery > 0.02:
        glColor4f(1.0, 0.95, 0.48, 0.95)
    else:
        glColor4f(0.22, 0.24, 0.28, 0.75)
    glBegin(GL_QUADS)
    glVertex2f(led_x, batt_y - 3.0)
    glVertex2f(led_x + 3.5, batt_y - 3.0)
    glVertex2f(led_x + 3.5, batt_y + 3.0)
    glVertex2f(led_x, batt_y + 3.0)
    glEnd()


def _draw_ecg_trace(bar_x, center_y, bar_w, anxiety, anx_col, now):
    """Linha de ECG pulsante que acelera e ganha amplitude conforme o panico."""
    # Fundo de preenchimento sutil indicando o nivel proporcional
    anx_fill = max(0.0, min(bar_w, bar_w * anxiety))
    r, g, b = anx_col
    glColor4f(r, g, b, 0.24)
    glBegin(GL_QUADS)
    glVertex2f(bar_x, center_y - 6.0)
    glVertex2f(bar_x + anx_fill, center_y - 6.0)
    glVertex2f(bar_x + anx_fill, center_y + 6.0)
    glVertex2f(bar_x, center_y + 6.0)
    glEnd()

    # Linha base de monitor medico
    glColor4f(0.22, 0.28, 0.36, 0.55)
    glLineWidth(1.0)
    glBegin(GL_LINES)
    glVertex2f(bar_x, center_y)
    glVertex2f(bar_x + bar_w, center_y)
    glEnd()

    samples = 56
    t_s = now / 1000.0
    freq = 1.6 + anxiety * 3.4
    amp = 2.0 + anxiety * 5.2
    glLineWidth(1.6)
    glBegin(GL_LINE_STRIP)
    for i in range(samples + 1):
        u = i / float(samples)
        px = bar_x + u * bar_w
        phase = ((u * 2.2 - t_s * freq * 0.45) % 1.0)
        if 0.18 < phase < 0.25:
            spike = -0.35
        elif 0.25 <= phase < 0.30:
            spike = 1.0
        elif 0.30 <= phase < 0.36:
            spike = -0.55
        elif 0.45 <= phase < 0.55:
            spike = 0.28 * math.sin((phase - 0.45) * math.pi / 0.10)
        else:
            spike = 0.0
        jitter = (math.sin(t_s * 34.0 + i * 2.1) * 0.22 * max(0.0, anxiety - 0.45))
        py = center_y - spike * amp + jitter * amp
        fade = 0.45 + 0.55 * (1.0 - abs(u - min(1.0, anxiety)) * 0.5)
        glColor4f(min(1.0, r + 0.15), min(1.0, g + 0.12), min(1.0, b + 0.12), 0.95 * fade)
        glVertex2f(px, py)
    glEnd()


_TOAST_STYLE_COLORS = {
    "BATTERY": ((0.04, 0.22, 0.12), (0.22, 0.95, 0.48)),
    "MAP":     ((0.04, 0.16, 0.26), (0.28, 0.82, 1.00)),
    "TRAP":    ((0.26, 0.12, 0.04), (1.00, 0.62, 0.18)),
}


def draw_anxiety_hud(
    anxiety, battery, stamina=1.0, hypothermia=0.0, blood_overlay_timer=0,
    flashlight_on=True, battery_toast_alpha=0.0, near_campfire=False, toast_style="BATTERY",
    now_ms=None,
):
    W, H = DISPLAY_SIZE
    now = pygame.time.get_ticks() if now_ms is None else now_ms

    glMatrixMode(GL_PROJECTION)
    glPushMatrix()
    glLoadIdentity()
    glOrtho(0, W, H, 0, -1, 1)
    glMatrixMode(GL_MODELVIEW)
    glPushMatrix()
    glLoadIdentity()

    glPushAttrib(GL_ENABLE_BIT | GL_COLOR_BUFFER_BIT | GL_LINE_BIT | GL_LIGHTING_BIT | GL_CURRENT_BIT)
    glDisable(GL_LIGHTING)
    glDisable(GL_TEXTURE_2D)
    glDisable(GL_DEPTH_TEST)
    glDisable(GL_FOG)
    glShadeModel(GL_SMOOTH)
    glEnable(GL_BLEND)
    glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    # 1. Vinhetas perifericas de estado (sem lavar o centro da tela com cor plana)
    if anxiety > 0.65:
        pulse = 0.55 + 0.45 * abs(math.sin(now / 150.0))
        edge_a = min(0.65, (anxiety - 0.65) / 0.35 * 0.55 * pulse)
        _draw_edge_vignette(W, H, W * 0.25, H * 0.25, 0.72, 0.02, 0.04, edge_a)

    if blood_overlay_timer > 0:
        blood_a = min(1.0, blood_overlay_timer / 3000.0) * 0.70
        _draw_edge_vignette(W, H, W * 0.22, H * 0.22, 0.68, 0.0, 0.02, blood_a)

    if near_campfire:
        warm_pulse = 0.80 + 0.20 * math.sin(now / 180.0)
        _draw_edge_vignette(W, H, W * 0.38, H * 0.38, 0.95, 0.45, 0.10, 0.08 * warm_pulse)

    if hypothermia > 0.0:
        pulse_ice = 0.75 + 0.25 * math.sin(now / 220.0)
        ice_a = min(0.75, hypothermia * 0.62 * pulse_ice)
        _draw_edge_vignette(
            W, H,
            W * (0.30 - 0.09 * hypothermia),
            H * (0.30 - 0.09 * hypothermia),
            0.55, 0.80, 0.96, ice_a,
        )
        _draw_frost_border(W, H, hypothermia, now)

    # 2. Painel chanfrado inferior-esquerdo (stamina, ECG ansiedade, bateria segmentada)
    PANEL_X = 22
    PANEL_Y = H - 104
    PANEL_W = 248
    PANEL_H = 82

    glColor4f(0.03, 0.04, 0.06, 0.76)
    _draw_chamfered_rect(PANEL_X, PANEL_Y, PANEL_W, PANEL_H, 7.0, filled=True)
    glLineWidth(1.2)
    glColor4f(0.32, 0.40, 0.50, 0.45)
    _draw_chamfered_rect(PANEL_X, PANEL_Y, PANEL_W, PANEL_H, 7.0, filled=False)

    # Filete lateral de acento visual
    glColor4f(0.58, 0.14, 0.14, 0.78)
    glBegin(GL_QUADS)
    glVertex2f(PANEL_X + 3, PANEL_Y + 9)
    glVertex2f(PANEL_X + 6, PANEL_Y + 9)
    glVertex2f(PANEL_X + 6, PANEL_Y + PANEL_H - 9)
    glVertex2f(PANEL_X + 3, PANEL_Y + PANEL_H - 9)
    glEnd()

    BAR_X = PANEL_X + 40
    BAR_W = PANEL_W - 54
    STAM_CY = PANEL_Y + 18
    ANX_CY  = PANEL_Y + 42
    BATT_CY = PANEL_Y + 65

    # Cor da ansiedade (fria -> ambar -> rubi pulsante)
    anx_pulse = 1.0 + (0.14 * math.sin(now / 140.0) if anxiety > 0.70 else 0.0)
    if anxiety < 0.40:
        anx_col = (0.30, 0.56, 0.88)
    elif anxiety < 0.75:
        mix = (anxiety - 0.40) / 0.35
        anx_col = (0.30 + mix * 0.65, 0.56 - mix * 0.36, 0.88 - mix * 0.66)
    else:
        anx_col = (min(1.0, 0.96 * anx_pulse), 0.14, 0.18)

    _draw_hud_icons(PANEL_X, STAM_CY, ANX_CY, BATT_CY, stamina, anxiety, anx_col, battery, flashlight_on, now)

    # Barra 1: Folego / Stamina (trilho chanfrado + brilho superior)
    glColor4f(0.08, 0.10, 0.14, 0.85)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X, STAM_CY - 3.5)
    glVertex2f(BAR_X + BAR_W, STAM_CY - 3.5)
    glVertex2f(BAR_X + BAR_W, STAM_CY + 3.5)
    glVertex2f(BAR_X, STAM_CY + 3.5)
    glEnd()

    stam_fill = max(0.0, min(float(BAR_W), BAR_W * stamina))
    if stamina > 0.25:
        sr, sg, sb = 0.95, 0.80, 0.22
    else:
        blink_s = 0.5 + 0.5 * abs(math.sin(now / 120.0))
        sr, sg, sb = 0.95, 0.28 * blink_s, 0.15
    if stam_fill > 1.0:
        glColor4f(sr, sg, sb, 0.92)
        glBegin(GL_QUADS)
        glVertex2f(BAR_X, STAM_CY - 3.0)
        glVertex2f(BAR_X + stam_fill, STAM_CY - 3.0)
        glVertex2f(BAR_X + stam_fill, STAM_CY + 3.0)
        glVertex2f(BAR_X, STAM_CY + 3.0)
        glEnd()
        glColor4f(1.0, 0.96, 0.72, 0.38)
        glBegin(GL_QUADS)
        glVertex2f(BAR_X, STAM_CY - 3.0)
        glVertex2f(BAR_X + stam_fill, STAM_CY - 3.0)
        glVertex2f(BAR_X + stam_fill, STAM_CY - 1.2)
        glVertex2f(BAR_X, STAM_CY - 1.2)
        glEnd()

    # Barra 2: Ansiedade / ECG animado em slot rebaixado
    glColor4f(0.05, 0.07, 0.10, 0.90)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X, ANX_CY - 7.0)
    glVertex2f(BAR_X + BAR_W, ANX_CY - 7.0)
    glVertex2f(BAR_X + BAR_W, ANX_CY + 7.0)
    glVertex2f(BAR_X, ANX_CY + 7.0)
    glEnd()
    _draw_ecg_trace(BAR_X, ANX_CY, BAR_W, anxiety, anx_col, now)

    # Barra 3: Bateria segmentada em 10 celulas
    num_cells = 10
    gap = 2.0
    cell_w = (BAR_W - gap * (num_cells - 1)) / float(num_cells)
    if not flashlight_on:
        br, bg, bb, ba = 0.36, 0.38, 0.44, 0.55
    elif battery > 0.45:
        br, bg, bb, ba = 0.08, 0.85, 0.98, 0.95
    elif battery > 0.20:
        br, bg, bb, ba = 0.98, 0.82, 0.16, 0.95
    else:
        blink = abs(math.sin(now / 150.0))
        br, bg, bb, ba = 0.98, 0.12, 0.14, 0.50 + blink * 0.45

    lit_level = max(0.0, min(float(num_cells), battery * num_cells))
    for i in range(num_cells):
        cx = BAR_X + i * (cell_w + gap)
        glColor4f(0.08, 0.10, 0.13, 0.88)
        glBegin(GL_QUADS)
        glVertex2f(cx, BATT_CY - 4.0)
        glVertex2f(cx + cell_w, BATT_CY - 4.0)
        glVertex2f(cx + cell_w, BATT_CY + 4.0)
        glVertex2f(cx, BATT_CY + 4.0)
        glEnd()

        cell_frac = max(0.0, min(1.0, lit_level - i))
        if cell_frac > 0.05:
            glColor4f(br, bg, bb, ba * (0.45 + 0.55 * cell_frac))
            glBegin(GL_QUADS)
            glVertex2f(cx + 0.5, BATT_CY - 3.2)
            glVertex2f(cx + 0.5 + (cell_w - 1.0) * cell_frac, BATT_CY - 3.2)
            glVertex2f(cx + 0.5 + (cell_w - 1.0) * cell_frac, BATT_CY + 3.2)
            glVertex2f(cx + 0.5, BATT_CY + 3.2)
            glEnd()

    # Terminal positivo da pilha na extremidade direita
    glColor4f(0.45, 0.52, 0.62, 0.65)
    glBegin(GL_QUADS)
    glVertex2f(BAR_X + BAR_W + 1.5, BATT_CY - 2.0)
    glVertex2f(BAR_X + BAR_W + 4.0, BATT_CY - 2.0)
    glVertex2f(BAR_X + BAR_W + 4.0, BATT_CY + 2.0)
    glVertex2f(BAR_X + BAR_W + 1.5, BATT_CY + 2.0)
    glEnd()

    # 3. Toast de recompensa/alerta alinhado logo acima do painel inferior-esquerdo
    if battery_toast_alpha > 0.0:
        toast_x = PANEL_X
        toast_y = PANEL_Y - 26
        toast_w = PANEL_W
        toast_h = 20
        bg_rgb, bd_rgb = _TOAST_STYLE_COLORS.get(toast_style, _TOAST_STYLE_COLORS["BATTERY"])
        glColor4f(bg_rgb[0], bg_rgb[1], bg_rgb[2], 0.84 * battery_toast_alpha)
        _draw_chamfered_rect(toast_x, toast_y, toast_w, toast_h, 3.5, filled=True)
        glLineWidth(1.2)
        glColor4f(bd_rgb[0], bd_rgb[1], bd_rgb[2], 0.92 * battery_toast_alpha)
        _draw_chamfered_rect(toast_x, toast_y, toast_w, toast_h, 3.5, filled=False)

    # 4. Indicador de aquecimento na fogueira (empilhado acima do toast se ativo)
    if near_campfire:
        camp_x = PANEL_X
        camp_y = (PANEL_Y - 50) if battery_toast_alpha > 0.01 else (PANEL_Y - 26)
        camp_w = PANEL_W
        camp_h = 20
        warm_pulse = 0.78 + 0.22 * math.sin(now / 180.0)
        glColor4f(0.22, 0.10, 0.03, 0.84)
        _draw_chamfered_rect(camp_x, camp_y, camp_w, camp_h, 3.5, filled=True)
        glLineWidth(1.2)
        glColor4f(1.0, 0.58, 0.16, 0.90 * warm_pulse)
        _draw_chamfered_rect(camp_x, camp_y, camp_w, camp_h, 3.5, filled=False)

        # Ícone vetorial de chama em duas camadas (laranja externa + núcleo amarelo)
        fx = camp_x + 14.0
        fy = camp_y + camp_h * 0.5
        sway = math.sin(now / 110.0) * 1.1
        glColor4f(1.0, 0.45, 0.08, 0.96)
        glBegin(GL_POLYGON)
        glVertex2f(fx, fy + 6.0)
        glVertex2f(fx - 4.5, fy + 2.5)
        glVertex2f(fx - 3.0, fy - 1.5)
        glVertex2f(fx + sway, fy - 6.2)
        glVertex2f(fx + 3.0, fy - 1.5)
        glVertex2f(fx + 4.5, fy + 2.5)
        glEnd()

        glColor4f(1.0, 0.90, 0.32, 0.98)
        glBegin(GL_POLYGON)
        glVertex2f(fx, fy + 4.8)
        glVertex2f(fx - 2.3, fy + 2.2)
        glVertex2f(fx - 1.2, fy - 0.5)
        glVertex2f(fx - sway * 0.4, fy - 3.0)
        glVertex2f(fx + 1.2, fy - 0.5)
        glVertex2f(fx + 2.3, fy + 2.2)
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
