import numpy as np
import soundcard as sc
import pygame
import math
import threading
import queue

SAMPLE_RATE = 48000
BLOCK_SIZE = 512

target_queue = queue.Queue(maxsize=1)
calibration_queue = queue.Queue(maxsize=1)

def generate_channel_map(num_channels):
    cmap = {}
    if num_channels <= 2:
        cmap[0], cmap[1] = -90, 90
    elif num_channels <= 6:
        cmap[0], cmap[1], cmap[2], cmap[4], cmap[5] = -30, 30, 0, -110, 110
    else:
        cmap[0], cmap[1], cmap[2], cmap[4], cmap[5], cmap[6], cmap[7] = -30, 30, 0, -90, 90, -150, 150
    return cmap

def universal_audio_loop():
    try:
        mic = sc.default_microphone()
        speaker = sc.default_speaker()
    except Exception as e:
        print(f"[-] Sound hardware error: {e}")
        return

    detected_channels = mic.channels
    print(f"[+] Multi-Channel Audio Online: {detected_channels} Channels.")
    channel_map = generate_channel_map(detected_channels)

    noise_baseline = np.zeros(detected_channels)
    is_calibrating = False
    calibration_buffer = []

    with mic.recorder(samplerate=SAMPLE_RATE, channels=detected_channels) as recorder, \
         speaker.player(samplerate=SAMPLE_RATE, channels=detected_channels) as player:

        while True:
            try:
                data = recorder.record(numframes=BLOCK_SIZE)
            except Exception:
                break

            player.play(data)
            raw_power = np.sqrt(np.mean(data**2, axis=0))

            if not calibration_queue.empty():
                if calibration_queue.get() == "START":
                    is_calibrating = True
                    calibration_buffer = []

            if is_calibrating:
                calibration_buffer.append(raw_power)
                if len(calibration_buffer) >= 80:
                    noise_baseline = np.max(np.array(calibration_buffer), axis=0) * 1.2
                    is_calibrating = False
                    print(f"[+] Calibration Complete. Background noise masked.")
                continue

            clean_power = np.maximum(0, raw_power - noise_baseline)
            mean_ambient = np.mean(clean_power)

            best_angle = None
            max_intensity = 0.0

            for ch_idx, angle in channel_map.items():
                if ch_idx >= len(clean_power): continue
                if clean_power[ch_idx] > mean_ambient * 1.5 and clean_power[ch_idx] > max_intensity:
                    max_intensity = clean_power[ch_idx]
                    best_angle = angle

            if target_queue.full():
                try: target_queue.get_nowait()
                except queue.Empty: pass

            if best_angle is not None and max_intensity > 0.002:
                distance_pct = max(0.1, min(1.0, 1.0 - (max_intensity * 5.0)))
                target_queue.put({"active": True, "angle": best_angle, "dist": distance_pct})
            else:
                target_queue.put({"active": False, "angle": 0, "dist": 1.0})

threading.Thread(target=universal_audio_loop, daemon=True).start()

pygame.init()
WIDTH, HEIGHT = 500, 500
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Universal Acoustic Tracker")
clock = pygame.time.Clock()

BLACK = (5, 8, 5)
HUD_GREEN = (0, 220, 0)
ALERT_RED = (255, 40, 40)
CENTER = (WIDTH // 2, HEIGHT // 2)
RADAR_RADIUS = 200

def to_screen_pixels(angle_deg, dist_pct):
    rad = math.radians(angle_deg - 90)
    radius = dist_pct * RADAR_RADIUS
    return CENTER + int(radius * math.cos(rad)), CENTER + int(radius * math.sin(rad))

active_blip = {"active": False, "x": 0, "y": 0}
print("\n[!] INSTRUCTIONS: Press 'C' while stationary to calibrate and filter out your own game noises.\n")

while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            raise SystemExit
        elif event.type == pygame.KEYDOWN and event.key == pygame.K_c:
            print("[*] Calibrating... Keep your vehicle completely still.")
            calibration_queue.put("START")

    screen.fill(BLACK)
    pygame.draw.circle(screen, HUD_GREEN, CENTER, RADAR_RADIUS, 1)

    if not target_queue.empty():
        packet = target_queue.get()
        if packet["active"]:
            tx, ty = to_screen_pixels(packet["angle"], packet["dist"])
            active_blip = {"active": True, "x": tx, "y": ty}
        else:
            active_blip["active"] = False

    if active_blip["active"]:
        pygame.draw.circle(screen, ALERT_RED, (active_blip["x"], active_blip["y"]), 8)
        pygame.draw.circle(screen, HUD_GREEN, (active_blip["x"], active_blip["y"]), 14, 1)

    pygame.display.flip()
    clock.tick(60)

