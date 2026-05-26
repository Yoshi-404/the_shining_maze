import wave
import struct
import math
import random


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


if __name__ == '__main__':
    generate_wind_sound('wind.wav')
    generate_hum_sound('exit.wav')
    generate_heartbeat_sound('heartbeat.wav')
    print("Sons gerados com sucesso!")
