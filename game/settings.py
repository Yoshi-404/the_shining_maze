import os

# Diretórios de assets
BASE_DIR     = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TEXTURES_DIR = os.path.join(BASE_DIR, "assets", "textures")
SOUNDS_DIR   = os.path.join(BASE_DIR, "assets", "sounds")

def tex(name):  return os.path.join(TEXTURES_DIR, name)
def snd(name):  return os.path.join(SOUNDS_DIR,   name)

# Dimensões do mundo
BLOCK_SIZE    = 2.0
WALL_HEIGHT   = 8.0
PLAYER_HEIGHT = 1.5
DISPLAY_SIZE  = (1000, 700)

# ================================
# ESTADO DE PROGRESSÃO (LOUCURA)
# ================================
# Incrementado a cada vez que o jogador completa o labirinto.
# Escala volumes, jumpscares e efeitos de loucura.
completion_count = 0

# ================================
# CONFIGURAÇÕES DO JOGADOR
# ================================
master_volume = 1.0
mouse_sensitivity = 0.003
