import numpy as np
import soundcard as sc
import pygame
import math
import sys
import threading
import queue

SAMPLE_RATE = 48000
BLOCK_SIZE = 512

target_queue = queue.Queue(maxsize=1)
calibration_queue = queue.Queue(maxsize=1)

def generate_channel_map(num_channels):
    """Creates geometric 2D target maps based on native speaker layouts."""
    cmap = {}
    if num_channels <= 2:
        cmap[0] = -90  # Audio Channel Index 0 -> Left Hemisphere (-90°)
        cmap[1] = 90   # Audio Channel Index 1 -> Right Hemisphere (+90°)
    elif num_channels <= 6:
        cmap[0] = -30  # Front Left
        cmap[1] = 30   # Front Right
        cmap[2] = 0    # Center
        cmap[4] = -110 # Rear Left
        cmap[5] = 110  # Rear Right
    else:
        cmap[0] = -30  
        cmap[1] = 30   
        cmap[2] = 0    
        cmap[4] = -90  # Side Left
        cmap[5] = 90   # Side Right
        cmap[6] = -150 # Rear Left
        cmap[7] = 150  # Rear Right
    return cmap

def universal_audio_loop():
    try:
        mic = sc.default_microphone()
        speaker = sc.default_speaker()
    except Exception as e:
        print(f"[-] Sound hardware error: {e}")
        return

    detected_channels = mic.channels
    print(f"[+] Multi-Channel Audio Online. Game Output: {detected_channels} Channels.")

    channel_map = generate_channel_map(detected_channels)

    noise_baseline = np.zeros(detected_channels)
    is_calibrating = False
    calibration_frames = 0
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
                cmd = calibration_queue.get()
                if cmd == "START":
                    is_calibrating = True
                    calibration_frames = 0
                    calibration_buffer = []

            if is_calibrating:
                calibration_buffer.append(raw_power)
                calibration_frames += 1
                if calibration_frames >= 80:
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

            if best_angle is not None and max_intensity > 0.002:
                distance_pct = max(0.1, min(1.0, 1.0 - (max_intensity * 5.0)))

                if target_queue.full():
                    try: target_queue.get_nowait()
                    except queue.Empty: pass
                target_queue.put({"active": True, "angle": best_angle, "dist": distance_pct})
            else:
                if target_queue.full():
                    try: target_queue.get_nowait()
                    except queue.Empty: pass
                target_queue.put({"active": False, "angle": 0, "dist": 1.0})

threading.Thread(target=universal_audio_loop, daemon=True).start()

pygame.init()
WIDTH, HEIGHT = 500, 500
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Universal Acoustic Tracker")
clock = pygame.time.Clock()
font = pygame.font.SysFont("monospace", 14)

BLACK = (5, 8, 5)
HUD_GREEN = (0, 220, 0)
GRID_GREEN = (0, 50, 0)
ALERT_RED = (255, 40, 40)
WHITE = (240, 240, 240)

CENTER = (WIDTH // 2, HEIGHT // 2)
RADAR_RADIUS = 200

def to_screen_pixels(angle_deg, dist_pct):
    rad = math.radians(angle_deg - 90)
    radius = dist_pct * RADAR_RADIUS
    return CENTER + int(radius * math.cos(rad)), CENTER + int(radius * math.sin(rad))

sweep_angle = 0
active_blip = {"active": False, "x": 0, "y": 0, "alpha": 0}

print("\n[!] INSTRUCTIONS: Press 'C' while stationary to calibrate and filter out your own game noises.\n")

while True:
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            pygame.quit()
            sys.exit()
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_c:
                print("[*] Calibrating... Keep your vehicle completely still.")
                calibration_queue.put("START")

    screen.fill(BLACK)

    pygame.draw.circle(screen, HUD_GREEN, CENTER, RADAR_RADIUS, 1)
    pygame.draw.circle(screen, GRID_GREEN, CENTER, int(RADAR_RADIUS * 0.66), 1)
    pygame.draw.circle(screen, GRID_GREEN, CENTER, int(RADAR_RADIUS * 0.33), 1)
    pygame.draw.line(screen, GRID_GREEN, (CENTER, CENTER - RADAR_RADIUS), (CENTER, CENTER + RADAR_RADIUS), 1)
    pygame.draw.line(screen, GRID_GREEN, (CENTER - RADAR_RADIUS, CENTER), (CENTER + RADAR_RADIUS, CENTER), 1)

    if not target_queue.empty():
        packet = target_queue.get()
        if packet["active"]:
            tx, ty = to_screen_pixels(packet["angle"], packet["dist"])
            active_blip = {"active": True, "x": tx, "y": ty, "alpha": 255}
        else:
            active_blip["alpha"] = max(0, active_blip["alpha"] - 8)
            if active_blip["alpha"] == 0: active_blip["active"] = False

    sweep_angle = (sweep_angle + 5) % 360
    sx, sy = to_screen_pixels(sweep_angle, 1.0)
    pygame.draw.line(screen, (0, 60, 0), CENTER, (sx, sy), 2)

    if active_blip["active"]:
        pygame.draw.circle(screen, ALERT_RED, (active_blip["x"], active_blip["y"]), 8)
        pygame.draw.circle(screen, HUD_GREEN, (active_blip["x"], active_blip["y"]), 14, 1)

    hud_text = font.render("SYSTEM: ACTIVE | PRESS 'C' TO MASK ENGINE", True, HUD_GREEN)
    screen.blit(hud_text, (15, HEIGHT - 30))

    pygame.display.flip()
    clock.tick(60) 
