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

# ================================
# ACESSIBILIDADE E AJUSTES DE CÂMERA (Item 14)
# ================================
fov = 70.0                   # Campo de visão (60.0 a 95.0 graus)
head_bobbing = True          # Oscilação rítmica da câmera ao caminhar
camera_shake = True          # Tremores traumáticos em sustos/alta ansiedade
photosensitivity_mode = False # Reduz flashes brancos, estroboscópios e piscadas
invert_mouse_y = False       # Inverter eixo vertical do mouse

# ================================
# DIFICULDADE E DIMENSÕES DO LABIRINTO (Item 13)
# ================================
difficulty = "NORMAL"
DIFFICULTIES = ["FACIL", "NORMAL", "DIFICIL"]

DIFFICULTY_PRESETS = {
    "FACIL": {
        "label": "Facil",
        "desc": "19x19 | Jack lento | Menos frio",
        "maze_size": (19, 19),
        "jack_interval": 440,
        "drain_mult": 0.7,
        "freeze_mult": 0.7,
        "num_campfires": 14,
    },
    "NORMAL": {
        "label": "Normal",
        "desc": "25x25 | Experiencia padrao",
        "maze_size": (25, 25),
        "jack_interval": 320,
        "drain_mult": 1.0,
        "freeze_mult": 1.0,
        "num_campfires": 10,
    },
    "DIFICIL": {
        "label": "Dificil",
        "desc": "31x31 | Jack veloz | Nevasca severa",
        "maze_size": (31, 31),
        "jack_interval": 230,
        "drain_mult": 1.35,
        "freeze_mult": 1.35,
        "num_campfires": 6,
    }
}

# ================================
# PERSISTÊNCIA DE DADOS (save_data.json)
# ================================
import json
import copy

SAVE_FILE = os.path.join(BASE_DIR, "save_data.json")

DEFAULT_SAVE_DATA = {
    "version": 1,
    "settings": {
        "master_volume": 1.0,
        "mouse_sensitivity": 0.003,
        "fov": 70.0,
        "head_bobbing": True,
        "camera_shake": True,
        "photosensitivity_mode": False,
        "invert_mouse_y": False,
        "difficulty": "NORMAL"
    },
    "progress": {
        "completion_count": 0,
        "total_games": 0,
        "total_wins": 0,
        "total_jumpscares": 0,
        "total_batteries_collected": 0
    },
    "records": {
        "best_time": None,
        "best_times_by_diff": {
            "FACIL": None,
            "NORMAL": None,
            "DIFICIL": None
        },
        "max_distance": 0.0,
        "lowest_peak_anxiety": None
    }
}

save_data = None

def load_save_data():
    """Carrega save_data.json e sincroniza com as configurações e variáveis globais."""
    global master_volume, mouse_sensitivity, fov, head_bobbing, camera_shake
    global photosensitivity_mode, invert_mouse_y, difficulty, completion_count, save_data

    loaded = {}
    if os.path.isfile(SAVE_FILE):
        try:
            with open(SAVE_FILE, "r", encoding="utf-8") as f:
                loaded = json.load(f)
        except Exception as e:
            print(f"[settings] Erro ao ler save_data.json: {e}")
            loaded = {}

    save_data = copy.deepcopy(DEFAULT_SAVE_DATA)
    if isinstance(loaded.get("settings"), dict):
        save_data["settings"].update(loaded["settings"])
    if isinstance(loaded.get("progress"), dict):
        save_data["progress"].update(loaded["progress"])
    if isinstance(loaded.get("records"), dict):
        for k, v in loaded["records"].items():
            if k == "best_times_by_diff" and isinstance(v, dict):
                save_data["records"]["best_times_by_diff"].update(v)
            else:
                save_data["records"][k] = v

    # Aplica nas variáveis em tempo de execução
    cfg = save_data["settings"]
    master_volume = float(cfg.get("master_volume", 1.0))
    mouse_sensitivity = float(cfg.get("mouse_sensitivity", 0.003))
    fov = float(cfg.get("fov", 70.0))
    head_bobbing = bool(cfg.get("head_bobbing", True))
    camera_shake = bool(cfg.get("camera_shake", True))
    photosensitivity_mode = bool(cfg.get("photosensitivity_mode", False))
    invert_mouse_y = bool(cfg.get("invert_mouse_y", False))
    diff = cfg.get("difficulty", "NORMAL")
    if diff in DIFFICULTIES:
        difficulty = diff

    prog = save_data["progress"]
    completion_count = int(prog.get("completion_count", 0))

    return save_data


def save_save_data():
    """Grava o estado atual das configurações e progresso em save_data.json de forma atômica."""
    global save_data
    if save_data is None:
        save_data = copy.deepcopy(DEFAULT_SAVE_DATA)

    save_data["settings"]["master_volume"] = float(master_volume)
    save_data["settings"]["mouse_sensitivity"] = float(mouse_sensitivity)
    save_data["settings"]["fov"] = float(fov)
    save_data["settings"]["head_bobbing"] = bool(head_bobbing)
    save_data["settings"]["camera_shake"] = bool(camera_shake)
    save_data["settings"]["photosensitivity_mode"] = bool(photosensitivity_mode)
    save_data["settings"]["invert_mouse_y"] = bool(invert_mouse_y)
    save_data["settings"]["difficulty"] = str(difficulty)
    save_data["progress"]["completion_count"] = int(completion_count)

    tmp_file = SAVE_FILE + ".tmp"
    try:
        with open(tmp_file, "w", encoding="utf-8") as f:
            json.dump(save_data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_file, SAVE_FILE)
    except Exception as e:
        print(f"[settings] Erro ao gravar save_data.json: {e}")


def record_game_start():
    """Registra uma nova partida iniciada."""
    if save_data is None:
        load_save_data()
    save_data["progress"]["total_games"] = save_data["progress"].get("total_games", 0) + 1
    save_save_data()


def record_game_completion(run_time, distance, jumpscares, peak_anxiety, diff_key, batteries_collected=0):
    """Atualiza recordes e estatísticas após fuga bem-sucedida do labirinto."""
    global completion_count, save_data
    completion_count += 1
    if save_data is None:
        load_save_data()

    save_data["progress"]["completion_count"] = completion_count
    save_data["progress"]["total_wins"] = save_data["progress"].get("total_wins", 0) + 1
    save_data["progress"]["total_jumpscares"] = save_data["progress"].get("total_jumpscares", 0) + int(jumpscares)
    save_data["progress"]["total_batteries_collected"] = (
        save_data["progress"].get("total_batteries_collected", 0) + int(batteries_collected)
    )

    recs = save_data["records"]
    new_records = {}

    old_best = recs.get("best_time")
    if old_best is None or run_time < old_best:
        recs["best_time"] = round(run_time, 2)
        new_records["best_time"] = True

    diff_times = recs.setdefault("best_times_by_diff", {})
    old_diff_best = diff_times.get(diff_key)
    if old_diff_best is None or run_time < old_diff_best:
        diff_times[diff_key] = round(run_time, 2)
        new_records["diff_best_time"] = True

    if distance > recs.get("max_distance", 0.0):
        recs["max_distance"] = round(distance, 1)

    old_anx = recs.get("lowest_peak_anxiety")
    if old_anx is None or peak_anxiety < old_anx:
        recs["lowest_peak_anxiety"] = round(peak_anxiety, 2)

    save_save_data()
    return new_records


