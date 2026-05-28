import wave
import struct
import math
import random
import os


def generate_wind_sound(filename):
    sample_rate = 44100
    duration = 5.0
    num_samples = int(sample_rate * duration)
    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(2)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        val_l = 0
        val_r = 0
        for _ in range(num_samples):
            val_l = val_l * 0.95 + random.uniform(-1000, 1000)
            val_r = val_r * 0.95 + random.uniform(-1000, 1000)
            vl = max(min(int(val_l), 32767), -32768)
            vr = max(min(int(val_r), 32767), -32768)
            wav_file.writeframes(struct.pack('hh', vl, vr))


def generate_hum_sound(filename):
    sample_rate = 44100
    duration = 2.0
    num_samples = int(sample_rate * duration)
    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(num_samples):
            t = float(i) / sample_rate
            v = math.sin(2.0 * math.pi * 60.0 * t) + 0.5 * math.sin(2.0 * math.pi * 65.0 * t)
            v *= (0.6 + 0.4 * math.sin(2.0 * math.pi * 2.0 * t))
            v *= 15000
            wav_file.writeframes(struct.pack('h', int(v)))


def generate_heartbeat_sound(filename):
    """Gera um som realista de 'lub-dub' (batimento cardíaco)."""
    sample_rate = 44100
    # Primeiro batimento (LUB) – mais grave e longo
    def thump(freq, attack_ms, decay_ms, amplitude):
        attack  = int(sample_rate * attack_ms  / 1000)
        decay   = int(sample_rate * decay_ms   / 1000)
        samples = []
        for i in range(attack + decay):
            t = float(i) / sample_rate
            env = (i / attack) if i < attack else (1.0 - (i - attack) / decay)
            v = math.sin(2.0 * math.pi * freq * t) * env * amplitude
            # Adiciona sub-harmônico para soar mais carnal
            v += math.sin(2.0 * math.pi * freq * 0.5 * t) * env * amplitude * 0.4
            samples.append(max(min(int(v), 32767), -32768))
        return samples

    lub  = thump(freq=55, attack_ms=20, decay_ms=120, amplitude=28000)
    gap1 = [0] * int(sample_rate * 0.10)   # pausa 100ms entre lub e dub
    dub  = thump(freq=70, attack_ms=15, decay_ms=80,  amplitude=20000)
    gap2 = [0] * int(sample_rate * 0.55)   # pausa longa antes do próximo ciclo

    all_samples = lub + gap1 + dub + gap2

    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for s in all_samples:
            wav_file.writeframes(struct.pack('h', s))


def generate_footstep_sound(filename):
    """Gera som de passo na neve."""
    sample_rate = 44100
    duration = 0.45
    num_samples = int(sample_rate * duration)
    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        
        last_val = 0.0
        for i in range(num_samples):
            t = float(i) / sample_rate
            
            # Envelope com dois picos suaves (imitando calcanhar -> ponta do pé)
            env1 = math.exp(-((t - 0.08) ** 2) / 0.005) * 0.6
            env2 = math.exp(-((t - 0.25) ** 2) / 0.015) * 1.0
            env = env1 + env2
            
            # Filtro passa-baixa simples no ruído para tirar a estridência (som de tiro)
            noise = random.uniform(-1, 1)
            last_val = last_val * 0.6 + noise * 0.4
            
            v = last_val * 5000 * env
            wav_file.writeframes(struct.pack('h', int(max(min(v, 32767), -32768))))

def generate_whisper_sound(filename):
    """Gera som de sussurro assustador."""
    sample_rate = 44100
    duration = 2.0
    num_samples = int(sample_rate * duration)
    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        val = 0
        for i in range(num_samples):
            t = float(i) / sample_rate
            env = math.sin(t * math.pi / duration)  # envelope suave
            val = val * 0.5 + random.uniform(-1, 1) * 0.5
            v = val * 8000 * env
            wav_file.writeframes(struct.pack('h', int(max(min(v, 32767), -32768))))

def generate_drip_sound(filename):
    """Gera som de gotejamento."""
    sample_rate = 44100
    duration = 0.1
    num_samples = int(sample_rate * duration)
    with wave.open(filename, 'w') as wav_file:
        wav_file.setnchannels(1)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        for i in range(num_samples):
            t = float(i) / sample_rate
            # Pitch sweep SUBINDO de 400Hz para 1200Hz rápido (típico de gota d'água 'bloop')
            freq = 400 + 800 * (t / duration)
            v = math.sin(2.0 * math.pi * freq * t)
            # Envelope com attack instantâneo e decaimento exponencial curto
            env = math.exp(-t * 30)
            v = v * 20000 * env
            wav_file.writeframes(struct.pack('h', int(max(min(v, 32767), -32768))))

if __name__ == '__main__':
    out_dir = os.path.join(os.path.dirname(__file__), '..', 'sounds')
    os.makedirs(out_dir, exist_ok=True)
    
    generate_wind_sound(os.path.join(out_dir, 'wind.wav'))
    generate_hum_sound(os.path.join(out_dir, 'exit.wav'))
    generate_heartbeat_sound(os.path.join(out_dir, 'heartbeat.wav'))
    generate_footstep_sound(os.path.join(out_dir, 'footstep.wav'))
    generate_whisper_sound(os.path.join(out_dir, 'whisper1.wav'))
    generate_whisper_sound(os.path.join(out_dir, 'whisper2.wav'))
    generate_drip_sound(os.path.join(out_dir, 'drip.wav'))
    
    print("Sons gerados com sucesso na pasta assets/sounds!")
