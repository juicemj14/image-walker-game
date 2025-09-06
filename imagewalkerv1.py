# image_walker_forever.py
# Single-file game with Seed feature added (press Seed in menu -> warning -> enter numeric seed -> Generate Seed)
# Requires: pygame
# Optional: tkinter (file dialogs), Pillow/PIL (better image loading)

import os
import sys
import time
import math
import random
import json
import textwrap
from typing import Optional, List

import pygame
from pygame.locals import *

# Optional: tkinter for file dialogs
try:
    import tkinter as tk
    from tkinter import filedialog
    TK_OK = True
except Exception:
    TK_OK = False

# Optional: Pillow for robust image loading
try:
    from PIL import Image
    PIL_OK = True
except Exception:
    PIL_OK = False

pygame.init()
try:
    pygame.mixer.init()
except Exception:
    pass

# ---------- Config ----------
GAME_TITLE = "Image Walker Forever"

COIN_SAVE_FILE = os.path.join(os.path.expanduser("~"), ".image_walker_coins.json")
LEVEL_SAVE_FILE = os.path.join(os.getcwd(), "levels_save.json")

COIN_CHUNK_SPAWN_PROB = 0.06
SPRING_CHUNK_SPAWN_PROB = 0.015

SPRING_BOOST = -760.0
BUFF_DURATION_SECONDS = 60.0

DEFAULT_W, DEFAULT_H = 1000, 700

# ---------- Persistence helpers ----------
def load_coins_data():
    try:
        if os.path.exists(COIN_SAVE_FILE):
            with open(COIN_SAVE_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
                return {"coins": data.get("coins", []), "buff_end_time": float(data.get("buff_end_time", 0.0))}
    except Exception:
        pass
    return {"coins": [], "buff_end_time": 0.0}

def save_coins_data(data):
    try:
        with open(COIN_SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print("Failed to save coins data:", e)

def load_level_progress():
    try:
        if os.path.exists(LEVEL_SAVE_FILE):
            with open(LEVEL_SAVE_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception:
        pass
    return {"completed": []}

def save_level_progress(data):
    try:
        with open(LEVEL_SAVE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f)
    except Exception as e:
        print("Failed to save level progress:", e)

def delete_level_progress_file():
    try:
        if os.path.exists(LEVEL_SAVE_FILE):
            os.remove(LEVEL_SAVE_FILE)
    except Exception as e:
        print("Failed to delete save file:", e)

# ---------- Utilities ----------
def clamp(v, a, b):
    return max(a, min(b, v))

def load_image_pygame(path: str) -> Optional[pygame.Surface]:
    try:
        if PIL_OK:
            img = Image.open(path).convert("RGBA")
            mode = img.mode
            size = img.size
            data = img.tobytes()
            surf = pygame.image.fromstring(data, size, mode)
            return surf.convert_alpha()
        else:
            surf = pygame.image.load(path)
            if surf.get_alpha() is None:
                surf = surf.convert()
            else:
                surf = surf.convert_alpha()
            return surf
    except Exception:
        try:
            surf = pygame.image.load(path)
            if surf.get_alpha() is None:
                surf = surf.convert()
            else:
                surf = surf.convert_alpha()
            return surf
        except Exception as e:
            print("Failed to load image:", path, e)
            return None

# ---------- Asset Manager ----------
class AssetManager:
    def __init__(self):
        self.paths = {"background": None, "player": None}
        self.bg_cache = {}
        self.player_cache = {}
        self.lib_paths: List[str] = []
        self.lib_surfaces: List[Optional[pygame.Surface]] = []
        self.lib_cache = {}

    def load_single(self, key: str, path: str):
        if key not in self.paths:
            raise ValueError("Unknown asset key")
        self.paths[key] = path
        if key == "background":
            self.bg_cache.clear()
        elif key == "player":
            self.player_cache.clear()

    def load_many(self, paths: List[str]):
        paths = list(paths)
        self.lib_paths = paths
        self.lib_surfaces = []
        self.lib_cache.clear()
        for p in paths:
            s = load_image_pygame(p)
            if s:
                self.lib_surfaces.append(s)
            else:
                self.lib_surfaces.append(None)

    def get_bg(self, w: int, h: int) -> Optional[pygame.Surface]:
        key = (int(w), int(h))
        if key in self.bg_cache:
            return self.bg_cache[key]
        p = self.paths.get("background")
        if p and os.path.exists(p):
            surf = load_image_pygame(p)
            if surf:
                surf = pygame.transform.smoothscale(surf, (w, h))
                self.bg_cache[key] = surf
                return surf
        return None

    def get_player(self, size_px: int, angle_deg: float) -> Optional[pygame.Surface]:
        key = (int(size_px), int(round(angle_deg)) % 360)
        if key in self.player_cache:
            return self.player_cache[key]
        p = self.paths.get("player")
        if p and os.path.exists(p):
            surf = load_image_pygame(p)
            if surf:
                bw, bh = surf.get_width(), surf.get_height()
                scale = size_px / max(1, max(bw, bh))
                nw, nh = max(1, int(bw * scale)), max(1, int(bh * scale))
                surf = pygame.transform.smoothscale(surf, (nw, nh))
                surf = pygame.transform.rotate(surf, -key[1])
                surf = surf.convert_alpha()
                self.player_cache[key] = surf
                return surf
        return None

    def get_lib_photo(self, idx: int, target_w: Optional[int]=None, max_w=360, max_h=240) -> Optional[pygame.Surface]:
        if not (0 <= idx < len(self.lib_surfaces)):
            return None
        base = self.lib_surfaces[idx]
        if base is None:
            return None
        iw, ih = base.get_width(), base.get_height()
        if target_w:
            scale = target_w / iw
            if ih * scale > max_h:
                scale = max_h / ih
        else:
            scale = min(max_w / iw, max_h / ih, 1.0)
        nw, nh = max(1, int(iw * scale)), max(1, int(ih * scale))
        key = (idx, nw, nh)
        if key in self.lib_cache:
            return self.lib_cache[key]
        surf = pygame.transform.smoothscale(base, (nw, nh)).convert_alpha()
        self.lib_cache[key] = surf
        return surf

# ---------- Modes ----------
class SuperHexagonMode:
    def __init__(self, screen: pygame.Surface, assets: AssetManager, on_exit, app_ref=None):
        self.screen = screen; self.assets = assets; self.on_exit = on_exit; self.app_ref = app_ref
        self.w, self.h = screen.get_size(); self.cx, self.cy = self.w//2, self.h//2
        self.clock = pygame.time.Clock(); self.dt = 0.016; self.running = False
        self.hex_angle = 0.0; self.hex_rot_speed = 60.0
        self.player_angle = 0.0; self.player_rot_speed = 220.0
        self.player_size = 48
        self.obstacles = []; self.spawn_timer = 0.0; self.spawn_interval = 1.1
        self.elapsed = 0.0; self.key_left = False; self.key_right = False
        self.time_alive = 0.0; self.dead = False
        self.font = pygame.font.SysFont("Segoe UI", 18); self.small_font = pygame.font.SysFont("Segoe UI", 14)

    def start(self):
        self.running = True
        # Start music if app wants it
        try:
            if self.app_ref and getattr(self.app_ref, "music_loaded", False) and getattr(self.app_ref, "music_on", True):
                pygame.mixer.music.play(-1)
                self.app_ref.music_playing = True
        except Exception:
            pass

    def stop(self):
        self.running = False

    def tick(self, events, dt):
        if not self.running: return False
        if self.dead: return False
        for ev in events:
            if ev.type == KEYDOWN:
                if ev.key in (K_LEFT, K_a): self.key_left = True
                elif ev.key in (K_RIGHT, K_d): self.key_right = True
                elif ev.key == K_m and self.app_ref:
                    if not getattr(self.app_ref, "music_loaded", False): continue
                    if self.app_ref.music_playing:
                        try: pygame.mixer.music.stop()
                        except Exception: pass
                        self.app_ref.music_playing = False
                    else:
                        try: pygame.mixer.music.play(-1)
                        except Exception: pass
                        self.app_ref.music_playing = True
                elif ev.key == K_ESCAPE:
                    self.stop(); self.on_exit(); return False
            elif ev.type == KEYUP:
                if ev.key in (K_LEFT, K_a): self.key_left = False
                elif ev.key in (K_RIGHT, K_d): self.key_right = False
        self.time_alive += dt
        self._update(dt)
        self._draw()
        return True

    def _update(self, dt):
        self.hex_angle = (self.hex_angle + self.hex_rot_speed * dt) % 360.0
        if self.key_left and not self.key_right:
            self.player_angle = (self.player_angle - self.player_rot_speed * dt) % 360.0
        elif self.key_right and not self.key_left:
            self.player_angle = (self.player_angle + self.player_rot_speed * dt) % 360.0
        self.elapsed += dt
        self.spawn_timer -= dt
        if self.spawn_timer <= 0:
            self._spawn_pattern()
            self.spawn_interval = max(0.38, self.spawn_interval * 0.985)
            self.spawn_timer = self.spawn_interval
        for o in self.obstacles:
            o["r_in"] -= o["speed"] * dt
        r_player = self._player_ring_radius()
        px_ang = self.player_angle % 360.0
        for o in list(self.obstacles):
            r_out = o["r_in"] + o["thick"]
            if o["r_in"] <= r_player <= r_out:
                if self._angle_overlap(px_ang, o["angle"], o["arc_width"]):
                    self._game_over("You hit a wall"); return
            if r_out <= 0:
                self.obstacles.remove(o)
        self.hex_rot_speed = 60.0 + min(180.0, self.elapsed * 4.0)

    def _spawn_pattern(self):
        lanes = random.choice([6,7,8])
        lane_width = 360.0/lanes
        use_lane_pattern = random.random() < 0.55
        r_spawn = self._spawn_radius()
        thick = max(18.0, min(36.0, r_spawn * 0.06))
        base_speed = 180.0 + self.elapsed * 2.5
        color = (239,83,80)
        if use_lane_pattern:
            gap_lane = random.randrange(lanes)
            blocked = [i for i in range(lanes) if i != gap_lane]
            if random.random() < 0.25:
                extra = random.choice(blocked); blocked.remove(extra)
            for i in blocked:
                center_ang = (i + 0.5) * lane_width + random.uniform(-4.0,4.0)
                arc = lane_width * random.uniform(0.78, 0.98)
                self.obstacles.append({"angle": center_ang % 360.0, "arc_width": arc, "r_in": r_spawn, "thick": thick, "speed": base_speed * random.uniform(0.95,1.10), "col": color})
        else:
            count = random.choice([1,2,3])
            for _ in range(count):
                center_ang = random.uniform(0,360); arc = random.uniform(28,54)
                self.obstacles.append({"angle": center_ang % 360.0, "arc_width": arc, "r_in": r_spawn, "thick": thick, "speed": base_speed * random.uniform(0.95,1.15), "col": color})

    def _player_ring_radius(self): return max(30, int(min(self.w, self.h) * 0.28))
    def _spawn_radius(self): return max(80, int(min(self.w, self.h) * 0.65))

    @staticmethod
    def _angle_overlap(a1, a2, arc):
        diff = abs((a1 - a2 + 180.0) % 360.0 - 180.0); return diff <= arc/2.0

    @staticmethod
    def _point_on_circle(cx, cy, radius, angle_deg):
        a = math.radians(angle_deg); return cx + radius * math.cos(a), cy + radius * math.sin(a)

    def _game_over(self, reason):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        if self.dead: return
        self.dead = True
        go_font = pygame.font.SysFont("Segoe UI", 28)
        s = f"{reason}\nTime: {self.time_alive:.1f}s"
        clock = pygame.time.Clock()
        while True:
            for ev in pygame.event.get():
                if ev.type == QUIT: pygame.quit(); sys.exit()
                elif ev.type == KEYDOWN or ev.type == MOUSEBUTTONDOWN:
                    self.stop(); self.on_exit(); return
            self.screen.fill((0,0,0))
            lines = s.splitlines(); y = self.h//2 - 40
            for line in lines:
                surf = go_font.render(line, True, (255,255,255)); rect = surf.get_rect(center=(self.cx, y)); self.screen.blit(surf, rect); y += surf.get_height() + 6
            tip = self.small_font.render("Press any key or click to return to menu", True, (200,200,200))
            self.screen.blit(tip, (self.cx - tip.get_width()//2, y+10))
            pygame.display.flip(); clock.tick(30)

    def _draw(self):
        bg = self.assets.get_bg(self.w, self.h)
        if bg: self.screen.blit(bg, (0,0))
        else:
            bands = 12
            for i in range(bands):
                x0 = int(i * self.w / bands); x1 = int((i+1) * self.w / bands)
                shade = 12 + (i % 2) * 18; col = (shade, shade, shade)
                pygame.draw.rect(self.screen, col, (x0, 0, x1-x0, self.h))
        radius = max(40, int(min(self.w, self.h) * 0.38))
        self._draw_hex(self.cx, self.cy, radius, self.hex_angle, 8, (34,255,238))
        ring_r = self._player_ring_radius()
        pygame.draw.circle(self.screen, (51,51,51), (self.cx, self.cy), ring_r, width=2)
        for o in self.obstacles:
            self._draw_arc(self.cx, self.cy, o["r_in"], o["r_in"] + o["thick"], o["angle"], o["arc_width"], fill=o.get("col", (239,83,80)))
        px, py = self._point_on_circle(self.cx, self.cy, ring_r, self.player_angle)
        sprite = self.assets.get_player(self.player_size, self.player_angle + 90)
        if sprite:
            rect = sprite.get_rect(center=(int(px), int(py))); self.screen.blit(sprite, rect)
        else:
            self._draw_player_triangle(px, py, self.player_angle)
        hud = f"Time: {self.time_alive:.1f}s     ←/→ to dodge     Esc: Menu"
        surf = self.font.render(hud, True, (255,255,255)); self.screen.blit(surf, (10,10))
        pygame.display.flip()

    def _draw_hex(self, cx, cy, r, angle_deg, width, color):
        pts = []
        for k in range(6):
            ang = angle_deg + 60*k; a = math.radians(ang)
            x = cx + r * math.cos(a); y = cy + r * math.sin(a); pts.append((x,y))
        pygame.draw.polygon(self.screen, (0,0,0,0), pts, width=width)
        pygame.draw.polygon(self.screen, color, pts, width=width)

    def _draw_player_triangle(self, x, y, angle_deg):
        size = 42; pts = [(0, -size * 0.7), (-size * 0.6, size * 0.5), (size * 0.6, size * 0.5)]
        a = math.radians(angle_deg); c, s = math.cos(a), math.sin(a); rot = []
        for px, py in pts:
            rx = x + (px * c - py * s); ry = y + (px * s + py * c); rot.append((rx, ry))
        pygame.draw.polygon(self.screen, (255,255,255), rot); pygame.draw.polygon(self.screen, (17,17,17), rot, width=2)

    def _draw_arc(self, cx, cy, r_in, r_out, angle_deg, arc_width_deg, fill=(239,83,80)):
        steps = 10; a0 = angle_deg - arc_width_deg/2.0; a1 = angle_deg + arc_width_deg/2.0
        pts = []
        for i in range(steps + 1):
            ang = math.radians(a0 + (a1 - a0) * (i/steps)); pts.append((cx + r_out * math.cos(ang), cy + r_out * math.sin(ang)))
        for i in range(steps, -1, -1):
            ang = math.radians(a0 + (a1 - a0) * (i/steps)); pts.append((cx + r_in * math.cos(ang), cy + r_in * math.sin(ang)))
        pygame.draw.polygon(self.screen, fill, pts)

# --- Image Walker Mode ---
class ImageWalkerMode:
    COIN_ID_COUNTER = 0

    def __init__(self, screen: pygame.Surface, assets: AssetManager, on_exit, sidescroller=False, coins_data=None, app_ref=None):
        self.screen = screen; self.assets = assets; self.on_exit = on_exit; self.app_ref = app_ref
        self.w, self.h = screen.get_size(); self.dt = 0.016; self.running = False
        self.gravity = 1500.0; self.move_accel = 2200.0; self.max_speed = 360.0; self.jump_speed = 580.0
        self.friction_ground = 1800.0; self.friction_air = 200.0; self.kill_y = 1200.0
        self.pw, self.ph = 36, 48; self.px = 100.0; self.py = -50.0; self.vx = 0.0; self.vy = 0.0
        self.on_ground = False; self.dead = False
        self.platforms = []; self.movers = []; self.spikes = []; self.orbs = []
        self.hold_left = False; self.hold_right = False; self.want_jump = False
        self.springs = []
        self._photorefs = []
        self.font = pygame.font.SysFont("Segoe UI", 16); self.small_font = pygame.font.SysFont("Segoe UI", 12)
        self.time_alive = 0.0; self.score = 0
        self.cam_x = 0.0; self.cam_y = 0.0
        self.level_extent_x = 0.0; self.ground_y = 400
        self.sidescroller = sidescroller
        self.scroll_speed = 140.0 if sidescroller else 0.0
        self.left_wall_kill = True if sidescroller else False
        loaded = coins_data if coins_data is not None else load_coins_data()
        self.coins = loaded.get("coins", [])
        self.buff_end_time = float(loaded.get("buff_end_time", 0.0))
        self._msg = None; self._msg_timer = 0.0
        self._build_level()
        maxid = 0
        for c in self.coins:
            try:
                maxid = max(maxid, int(c.get("id", 0)))
            except Exception:
                pass
        ImageWalkerMode.COIN_ID_COUNTER = maxid + 1

    def _save_coins_state(self):
        data = {"coins": self.coins, "buff_end_time": self.buff_end_time}
        save_coins_data(data)

    def _generate_coin(self, x, y):
        for c in self.coins:
            if c.get("collected"): continue
            dx = c["x"] - x; dy = c["y"] - y
            if dx*dx + dy*dy < 64*64: return None
        cid = ImageWalkerMode.COIN_ID_COUNTER; ImageWalkerMode.COIN_ID_COUNTER += 1
        coin = {"id": cid, "x": float(x), "y": float(y), "r": 10.0, "collected": False}
        self.coins.append(coin); self._save_coins_state(); return coin

    def _generate_spring(self, x):
        sx = float(x); sy = float(self.ground_y - 12); w = 48; h = 12
        for s in self.springs:
            if abs(s["x"] - sx) < 80: return None
        spring = {"x": sx, "y": sy, "w": float(w), "h": float(h)}
        self.springs.append(spring); return spring

    def _build_level(self):
        self.platforms.clear(); self.movers.clear(); self.spikes.clear(); self.orbs.clear(); self.springs.clear(); self._photorefs.clear()
        lib_n = len(self.assets.lib_surfaces)
        self.level_extent_x = 0
        self._add_platform(self.level_extent_x, self.ground_y, 280, 40, img_idx=0 if lib_n else None)
        self.level_extent_x += 300
        self._add_orb(self.level_extent_x - 150, self.ground_y - 120, "normal")
        while self.level_extent_x < self.w * 1.5:
            self._add_level_chunk()
        if self.platforms:
            first = self.platforms[0]
            self.px = first["x"] + 20; self.py = first["y"] - self.ph - 2
        else:
            self.px = 100.0; self.py = self.ground_y - self.ph - 2
        self.cam_x = self.px - self.w * 0.4; self.cam_y = self.py - self.h * 0.6
        if not any(not c.get("collected", False) for c in self.coins):
            for i in range(3):
                cx = random.uniform(80, max(200, self.level_extent_x - 40))
                py = self.ground_y - random.uniform(40, 120)
                self._generate_coin(cx, py)

    def _add_level_chunk(self):
        lib_n = len(self.assets.lib_surfaces)
        w = random.randint(180,320); gap = random.randint(80,200); py = self.ground_y + random.randint(-140, 140)
        idx = (len(self.platforms)) % lib_n if lib_n > 0 else None
        self._add_platform(self.level_extent_x, py, w, None, img_idx=idx)
        if random.random() < 0.6:
            ox = self.level_extent_x + random.uniform(w*0.3, w*0.7); oy = py - random.uniform(80,160)
            typ = random.choices(["small","normal","high"], weights=[0.35,0.45,0.20])[0]; self._add_orb(ox, oy, typ)
        if random.random() < 0.35:
            mv_w = random.randint(80,140); mv_x = self.level_extent_x + random.uniform(w*0.2, w*0.8 - mv_w)
            mv_y = py - random.randint(60,140); mv_vx = random.choice([-120,120]); mv_range = random.randint(100,220)
            self._add_mover(mv_x, mv_y, mv_w, 20, vx=mv_vx, move_range=mv_range)
        if random.random() < 0.22:
            self._add_spikes(self.level_extent_x + w*0.25, py - 12, 64, 16)
        if random.random() < COIN_CHUNK_SPAWN_PROB:
            cx = self.level_extent_x + random.uniform(0.2*w, 0.8*w)
            cy = py - random.uniform(40, 120)
            self._generate_coin(cx, cy)
        if random.random() < SPRING_CHUNK_SPAWN_PROB:
            sx = self.level_extent_x + random.uniform(0.2*w, 0.8*w)
            self._generate_spring(sx)
        self.level_extent_x += w + gap

    def _add_platform(self, x, y, w, h=None, img_idx=None):
        photo = None
        if img_idx is not None and 0 <= img_idx < len(self.assets.lib_surfaces):
            photo = self.assets.get_lib_photo(img_idx, target_w=w, max_w=360, max_h=240)
            if photo:
                w, h = photo.get_width(), photo.get_height(); self._photorefs.append(photo)
        if h is None: h = 48
        self.platforms.append({"x": float(x), "y": float(y), "w": float(w), "h": float(h), "photo": photo})

    def _add_mover(self, x, y, w, h, vx=120, move_range=160):
        self.movers.append({"x": float(x), "y": float(y), "w": float(w), "h": float(h), "vx": float(vx), "home": float(x), "range": float(move_range)})

    def _add_spikes(self, x, y, w, h):
        self.spikes.append({"x": float(x), "y": float(y), "w": float(w), "h": float(h)})

    def _add_orb(self, x, y, typ):
        r = {"small":10, "normal":12, "high":14}.get(typ,12); self.orbs.append({"x": float(x), "y": float(y), "r": float(r), "type": typ})

    def start(self):
        self.running = True
        try:
            if self.app_ref and getattr(self.app_ref, "music_loaded", False) and getattr(self.app_ref, "music_on", True):
                pygame.mixer.music.play(-1)
                self.app_ref.music_playing = True
        except Exception:
            pass

    def stop(self):
        self._save_coins_state()
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        self.running = False

    def tick(self, events, dt):
        if not self.running: return False
        for ev in events:
            if ev.type == KEYDOWN:
                if ev.key in (K_LEFT, K_a): self.hold_left = True
                elif ev.key in (K_RIGHT, K_d): self.hold_right = True
                elif ev.key in (K_SPACE, K_UP): self.want_jump = True
                elif ev.key == K_ESCAPE:
                    self._save_coins_state(); self.stop(); self.on_exit(); return False
                elif ev.key == K_q:
                    self.export_gameplay()
                elif ev.key == K_m and self.app_ref:
                    if not getattr(self.app_ref, "music_loaded", False): continue
                    if self.app_ref.music_playing:
                        try: pygame.mixer.music.stop()
                        except Exception: pass
                        self.app_ref.music_playing = False
                        self.app_ref.music_on = False
                    else:
                        try: pygame.mixer.music.play(-1)
                        except Exception: pass
                        self.app_ref.music_playing = True
                        self.app_ref.music_on = True
            elif ev.type == KEYUP:
                if ev.key in (K_LEFT, K_a): self.hold_left = False
                elif ev.key in (K_RIGHT, K_d): self.hold_right = False
                elif ev.key in (K_SPACE, K_UP): self.want_jump = False
        self.time_alive += dt
        self._update(dt)
        self._draw()
        return True

    def export_gameplay(self):
        data = {
            "type": "ImageWalker",
            "px": self.px, "py": self.py, "vx": self.vx, "vy": self.vy, "on_ground": self.on_ground,
            "pw": self.pw, "ph": self.ph,
            "time_alive": self.time_alive, "score": self.score,
            "platforms": self.platforms, "movers": self.movers, "spikes": self.spikes, "orbs": self.orbs,
            "cam_x": self.cam_x, "cam_y": self.cam_y, "level_extent_x": self.level_extent_x,
            "sidescroller": self.sidescroller
        }
        filename = None
        try:
            if TK_OK:
                root = tk.Tk(); root.withdraw()
                path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files","*.json")])
                try:
                    if path:
                        with open(path, "w", encoding="utf-8") as f:
                            json.dump(data, f)
                        filename = path
                finally:
                    try: root.destroy()
                    except: pass
            else:
                ts = time.strftime("%Y%m%d_%H%M%S")
                filename = f"imagewalker_export_{ts}.json"
                with open(filename, "w", encoding="utf-8") as f:
                    json.dump(data, f)
        except Exception as e:
            print("Failed to export gameplay:", e)
            filename = None
        if filename:
            msg = f"Exported gameplay to:\n{os.path.basename(filename)}"
        else:
            msg = "Failed to export gameplay"
        self._msg = msg; self._msg_timer = 3.0
        print(msg)

    def _update(self, dt):
        accel = (-self.move_accel if self.hold_left else 0.0) + (self.move_accel if self.hold_right else 0.0)
        self.vx += accel * dt
        fr = self.friction_ground if self.on_ground else self.friction_air
        if accel == 0.0:
            if self.vx > 0: self.vx = max(0.0, self.vx - fr * dt)
            elif self.vx < 0: self.vx = min(0.0, self.vx + fr * dt)
        self.vx = clamp(self.vx, -self.max_speed, self.max_speed)
        self.vy += self.gravity * dt

        touched_types = self._orbs_touching_player()
        touching_orb = len(touched_types) > 0
        mult = 1.0
        if touching_orb:
            if "high" in touched_types: mult = 1.35
            elif "normal" in touched_types: mult = 1.0
            elif "small" in touched_types: mult = 0.6

        if self.want_jump and (self.on_ground or touching_orb):
            self.vy = -self.jump_speed * mult
        self.want_jump = False

        for m in self.movers:
            m["x"] += m["vx"] * dt
            if abs(m["x"] - m["home"]) > m["range"]:
                m["vx"] = -m["vx"]

        self.on_ground = False
        self.px += self.vx * dt
        self._resolve_collisions(axis="x")
        self.py += self.vy * dt
        self._resolve_collisions(axis="y")

        carry_vx = self._carry_velocity_from_mover()
        if carry_vx != 0.0 and self.on_ground:
            self.px += carry_vx * dt

        for s in self.spikes:
            if self._intersect(self.px, self.py, self.pw, self.ph, s["x"], s["y"], s["w"], s["h"]):
                self._game_over("Spikes got you")

        for spring in self.springs:
            if self._intersect(self.px, self.py, self.pw, self.ph, spring["x"], spring["y"], spring["w"], spring["h"]):
                if self.vy >= 0:
                    try:
                        gravity_scale = self.gravity / 1500.0
                        self.vy = SPRING_BOOST * (1.0 / max(0.2, gravity_scale))
                    except Exception:
                        self.vy = -760.0
                    self._msg = "Spring launched!"; self._msg_timer = 1.5

        for coin in self.coins:
            if coin.get("collected"): continue
            if self._circle_rect_overlap(coin["x"], coin["y"], coin["r"], self.px, self.py, self.pw, self.ph):
                coin["collected"] = True
                self.buff_end_time = time.time() + BUFF_DURATION_SECONDS
                self.score += 150
                self._msg = "Coin collected! Score bonus active for 60s"
                self._msg_timer = 3.0
                self._save_coins_state()
                break

        if self.py > self.kill_y:
            self._game_over("Fell out of bounds")

        tx = self.px - self.w * 0.4; ty = self.py - self.h * 0.6
        self.cam_x += (tx - self.cam_x) * min(1.0, 8.0 * dt)
        self.cam_y += (ty - self.cam_y) * min(1.0, 8.0 * dt)

        if self.sidescroller:
            self.cam_x += self.scroll_speed * dt
            target_cam_y = self.py - self.h * 0.6
            self.cam_y += (target_cam_y - self.cam_y) * min(1.0, 6.0 * dt)
            if self.left_wall_kill and self.px < self.cam_x:
                old_px = self.px
                self.px = self.cam_x
                if any(self._intersect(self.px, self.py, self.pw, self.ph, c["x"], c["y"], c["w"], c["h"])
                       for c in (self.platforms + self.movers)):
                    self._game_over("You got crushed")
                if self.px > old_px and self.vx < 0:
                    self.vx = 0.0

        now = time.time()
        bonus_mult = 2.0 if now < self.buff_end_time else 1.0
        computed_score = int(self.px * 0.1 + self.time_alive * 3)
        computed_score = int(computed_score * bonus_mult)
        self.score = max(self.score, computed_score)

        if self.cam_x + self.w * 1.5 > self.level_extent_x:
            self._add_level_chunk()

        if self._msg_timer > 0.0:
            self._msg_timer -= dt
            if self._msg_timer <= 0.0:
                self._msg = None; self._msg_timer = 0.0

    def _resolve_collisions(self, axis):
        for pl in self.platforms + self.movers:
            if not self._intersect(self.px, self.py, self.pw, self.ph, pl["x"], pl["y"], pl["w"], pl["h"]):
                continue
            if axis == "x":
                if self.vx > 0:
                    self.px = pl["x"] - self.pw
                elif self.vx < 0:
                    self.px = pl["x"] + pl["w"]
                self.vx = 0.0
            else:
                if self.vy > 0:
                    self.py = pl["y"] - self.ph
                    self.vy = 0.0
                    self.on_ground = True
                elif self.vy < 0:
                    self.py = pl["y"] + pl["h"]
                    self.vy = 0.0

    def _carry_velocity_from_mover(self):
        feet_y = self.py + self.ph
        for m in self.movers:
            on_top = (abs(feet_y - m["y"]) <= 2.0)
            overlapping_x = not (self.px + self.pw <= m["x"] or self.px >= m["x"] + m["w"])
            if on_top and overlapping_x:
                return m["vx"]
        return 0.0

    def _orbs_touching_player(self):
        types = set()
        for orb in self.orbs:
            if self._circle_rect_overlap(orb["x"], orb["y"], orb["r"], self.px, self.py, self.pw, self.ph):
                types.add(orb["type"])
        return types

    @staticmethod
    def _intersect(ax, ay, aw, ah, bx, by, bw, bh):
        return (ax < bx + bw) and (ax + aw > bx) and (ay < by + bh) and (ay + ah > by)

    @staticmethod
    def _circle_rect_overlap(cx, cy, r, rx, ry, rw, rh):
        closest_x = max(rx, min(cx, rx + rw))
        closest_y = max(ry, min(cy, ry + rh))
        dx = cx - closest_x; dy = cy - closest_y
        return (dx*dx + dy*dy) <= (r*r)

    def _game_over(self, reason):
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass
        if self.dead: return
        self.dead = True
        go_font = pygame.font.SysFont("Segoe UI", 28)
        s = f"{reason}\nTime: {self.time_alive:.1f}s   Score: {self.score}"
        clock = pygame.time.Clock()
        self._save_coins_state()
        while True:
            for ev in pygame.event.get():
                if ev.type == QUIT: pygame.quit(); sys.exit()
                elif ev.type == KEYDOWN or ev.type == MOUSEBUTTONDOWN:
                    self.stop(); self.on_exit(); return
            self.screen.fill((0,0,0))
            lines = s.splitlines(); y = self.h//2 - 40
            for line in lines:
                surf = go_font.render(line, True, (255,255,255)); rect = surf.get_rect(center=(self.w//2, y)); self.screen.blit(surf, rect); y += surf.get_height() + 6
            tip = self.small_font.render("Press any key or click to return to menu", True, (200,200,200))
            self.screen.blit(tip, (self.w//2 - tip.get_width()//2, y+10))
            pygame.display.flip(); clock.tick(30)

    def _draw(self):
        bg = self.assets.get_bg(self.w, self.h)
        if bg:
            self.screen.blit(bg, (0,0))
        else:
            self.screen.fill((15,15,20))
        for pl in self.platforms:
            sx = pl["x"] - self.cam_x; sy = pl["y"] - self.cam_y
            if pl.get("photo"):
                self.screen.blit(pl["photo"], (sx, sy))
            else:
                pygame.draw.rect(self.screen, (47,47,47), (sx, sy, pl["w"], pl["h"]))
        for m in self.movers:
            sx = m["x"] - self.cam_x; sy = m["y"] - self.cam_y
            pygame.draw.rect(self.screen, (76,199,255), (sx, sy, m["w"], m["h"]))
            pygame.draw.rect(self.screen, (8,74,102), (sx, sy, m["w"], m["h"]), width=2)
        for s in self.spikes:
            self._draw_spikes(s["x"] - self.cam_x, s["y"] - self.cam_y, s["w"], s["h"])
        t = self.time_alive
        for orb in self.orbs:
            sx = orb["x"] - self.cam_x; sy = orb["y"] - self.cam_y
            base_r = orb["r"]; r = base_r + math.sin(t * 3.0 + (sx + sy) * 0.01) * (base_r * 0.2)
            col = ((171,71,188) if orb["type"]=="small" else (255,213,79) if orb["type"]=="normal" else (239,83,80))
            pygame.draw.circle(self.screen, col, (int(sx),int(sy)), int(r))
            pygame.draw.circle(self.screen, (255,255,255), (int(sx),int(sy)), int(r*0.5), width=1)
        for sp in self.springs:
            sx = sp["x"] - self.cam_x; sy = sp["y"] - self.cam_y
            pygame.draw.rect(self.screen, (255,165,0), (sx, sy, sp["w"], sp["h"]))
            pygame.draw.rect(self.screen, (255,200,80), (sx, sy, sp["w"], sp["h"]), width=2)
        now = time.time()
        for coin in self.coins:
            if coin.get("collected"): continue
            sx = coin["x"] - self.cam_x; sy = coin["y"] - self.cam_y; r = coin.get("r", 10)
            pr = r + math.sin(now * 4.0 + coin["x"]*0.01) * 2.0
            outer = (100, 220, 120); inner = (200,255,200); shine = (255,255,255)
            pygame.draw.circle(self.screen, outer, (int(sx), int(sy)), int(pr))
            pygame.draw.circle(self.screen, inner, (int(sx), int(sy)), int(pr*0.5), width=1)
            pygame.draw.circle(self.screen, shine, (int(sx - pr*0.2), int(sy - pr*0.2)), max(1, int(pr*0.15)))
        pxs = self.px - self.cam_x; pys = self.py - self.cam_y
        sprite = self.assets.get_player(42, -15 if self.vx >= 0 else 15)
        if sprite:
            rect = sprite.get_rect(center=(int(pxs + self.pw//2), int(pys + self.ph//2))); self.screen.blit(sprite, rect)
        else:
            pygame.draw.rect(self.screen, (135,223,255), (pxs, pys, self.pw, self.ph))
            pygame.draw.rect(self.screen, (10,58,74), (pxs, pys, self.pw, self.ph), width=2)
        now = time.time(); remaining = max(0.0, self.buff_end_time - now)
        buff_text = f" (Bonus x2: {int(remaining)}s left)" if remaining > 0 else ""
        hud = f"Score: {self.score}    Time: {self.time_alive:.1f}s{buff_text}    ←/→ Move, Space Jump, Esc Menu (Q = Export)"
        hud_s = self.font.render(hud, True, (255,255,255)); self.screen.blit(hud_s, (10,10))
        tip = self.small_font.render("Jump Orbs • Springs launch you • Coins (green) give x2 for 60s", True, (204,204,102)); self.screen.blit(tip, (10, 34))
        if self._msg:
            lines = self._msg.splitlines()
            box_w = min(600, self.w - 80); box_h = 18 + len(lines)*20
            box_x = (self.w - box_w)//2; box_y = 60
            pygame.draw.rect(self.screen, (240,240,240), (box_x, box_y, box_w, box_h), border_radius=6)
            pygame.draw.rect(self.screen, (120,120,120), (box_x, box_y, box_w, box_h), width=1, border_radius=6)
            y = box_y + 6
            for line in lines:
                s = self.small_font.render(line, True, (10,10,10)); self.screen.blit(s, (box_x + 8, y)); y += 20
        pygame.display.flip()

    def _draw_spikes(self, x, y, w, h):
        n = max(3, int(w // max(8, h)))
        for i in range(n):
            x0 = x + i * (w / n); x1 = x + (i + 1) * (w / n)
            pygame.draw.polygon(self.screen, (238,68,85), [(x0, y + h), ((x0 + x1)/2, y), (x1, y + h)])
            pygame.draw.polygon(self.screen, (85,16,22), [(x0, y + h), ((x0 + x1)/2, y), (x1, y + h)], width=1)

# === Level system & generation used for seed ---
def generate_level_by_index(idx:int, width=2400, ground_y=400):
    rnd = random.Random(idx + 12345)
    x = 0; platforms = []
    platforms.append({"x": x, "y": ground_y, "w": 300, "h": 40}); x += 320
    while x < width - 200:
        w = rnd.randint(120, 320); gap = rnd.randint(40, 160); py = ground_y + rnd.randint(-120, 120)
        platforms.append({"x": x, "y": py, "w": w, "h": 48})
        if rnd.random() < 0.22:
            sx = x + rnd.uniform(0.2*w, 0.8*w); sw = rnd.randint(40, 80)
            platforms.append({"x": sx, "y": py - 20, "w": sw, "h": 20, "spikes": True})
        x += w + gap
    finish_x = width - 80; finish_y = ground_y - 80
    return {"platforms": platforms, "finish": {"x": finish_x, "y": finish_y, "size": 34}, "width": width, "ground_y": ground_y, "seed": idx}

class LevelPlayMode(ImageWalkerMode):
    def __init__(self, screen: pygame.Surface, assets: AssetManager, on_exit, level_data: dict, coins_data=None, app_ref=None):
        super().__init__(screen, assets, on_exit, sidescroller=False, coins_data=coins_data, app_ref=app_ref)
        self.platforms = []; self.movers = []; self.spikes = []; self.orbs = []; self._photorefs = []; self.springs = []
        self.level_extent_x = level_data.get("width", 1200)
        self.ground_y = level_data.get("ground_y", 400)
        for p in level_data.get("platforms", []):
            if p.get("spikes"):
                self.spikes.append({"x": float(p["x"]), "y": float(p["y"]), "w": float(p["w"]), "h": float(p["h"])})
            else:
                self.platforms.append({"x": float(p["x"]), "y": float(p["y"]), "w": float(p["w"]), "h": float(p["h"]), "photo": None})
        fx = level_data["finish"]["x"]; fy = level_data["finish"]["y"]; size = level_data["finish"]["size"]
        self.finish = {"x": float(fx), "y": float(fy), "size": int(size)}
        # NO special spawn fix per user request
        self.px = 100.0; self.py = self.ground_y - self.ph - 2; self.on_ground = True; self.vy = 0.0; self.vx = 0.0
        self.cam_x = max(0.0, self.px - self.w * 0.4); self.cam_y = max(0.0, self.py - self.h * 0.6)
        self.dead = False; self.time_alive = 0.0; self.score = 0

    def _update(self, dt):
        super()._update(dt)
        px1, py1 = self.px, self.py; px2, py2 = px1 + self.pw, py1 + self.ph
        f = self.finish
        fx1, fy1 = f["x"], f["y"]; fx2, fy2 = fx1 + f["size"], fy1 + f["size"]
        if (px1 < fx2 and px2 > fx1 and py1 < fy2 and py2 > fy1):
            self._level_complete()

    def _draw(self):
        bg = self.assets.get_bg(self.w, self.h)
        if bg: self.screen.blit(bg, (0,0))
        else: self.screen.fill((21,18,30))
        for pl in self.platforms:
            sx = pl["x"] - self.cam_x; sy = pl["y"] - self.cam_y
            pygame.draw.rect(self.screen, (60,60,60), (sx, sy, pl["w"], pl["h"]))
        for s in self.spikes:
            self._draw_spikes(s["x"] - self.cam_x, s["y"] - self.cam_y, s["w"], s["h"])
        f = self.finish
        fx = f["x"] - self.cam_x; fy = f["y"] - self.cam_y; size = f["size"]
        pygame.draw.rect(self.screen, (255,204,0), (fx, fy, size, size))
        pygame.draw.rect(self.screen, (255,150,0), (fx - 2, fy - 2, size + 4, size + 4), width=4)
        for sp in self.springs:
            sx = sp["x"] - self.cam_x; sy = sp["y"] - self.cam_y
            pygame.draw.rect(self.screen, (255,165,0), (sx, sy, sp["w"], sp["h"]))
            pygame.draw.rect(self.screen, (255,200,80), (sx, sy, sp["w"], sp["h"]), width=2)
        pxs = self.px - self.cam_x; pys = self.py - self.cam_y
        sprite = self.assets.get_player(42, -15 if self.vx >= 0 else 15)
        if sprite:
            rect = sprite.get_rect(center=(int(pxs + self.pw//2), int(pys + self.ph//2))); self.screen.blit(sprite, rect)
        else:
            pygame.draw.rect(self.screen, (135,223,255), (pxs, pys, self.pw, self.ph))
        hud = f"Level Time: {self.time_alive:.1f}s    ←/→ Move, Space Jump, Esc: Quit Level"
        hud_s = self.font.render(hud, True, (255,255,255)); self.screen.blit(hud_s, (10,10))
        pygame.display.flip()

    def _level_complete(self):
        s = f"You finished the level!\nTime: {self.time_alive:.1f}s"
        go_font = pygame.font.SysFont("Segoe UI", 28); clock = pygame.time.Clock()
        while True:
            for ev in pygame.event.get():
                if ev.type == QUIT: pygame.quit(); sys.exit()
                elif ev.type == KEYDOWN or ev.type == MOUSEBUTTONDOWN: self.stop(); self.on_exit(); return
            self.screen.fill((0,0,0)); lines = s.splitlines(); y = self.h//2 - 40
            for line in lines:
                surf = go_font.render(line, True, (255,255,255)); rect = surf.get_rect(center=(self.w//2, y))
                self.screen.blit(surf, rect); y += surf.get_height() + 6
            tip = self.small_font.render("Press any key or click to return", True, (200,200,200))
            self.screen.blit(tip, (self.w//2 - tip.get_width()//2, y+10))
            pygame.display.flip(); clock.tick(30)

# --- Level Selector ---
class LevelSelector:
    def __init__(self, app):
        self.app = app; self.total_levels = 50; self.pages = 5; self.per_page = 10
        self.page = 0; self.progress = load_level_progress(); self.level_cache = {}; self.imported_levels = {}

    def draw(self):
        screen = self.app.screen; w, h = self.app.w, self.app.h
        screen.fill((14,14,18)); title_font = pygame.font.SysFont("Segoe UI", 28, bold=True)
        title = title_font.render("Level Selector", True, (255,255,255)); screen.blit(title, (20, 16))
        left_x = 20; y = 64
        info_lines = ["Levels: 50 total", f"Page: {self.page+1}/{self.pages}", "", "Controls:", "Click a level to play it.", "Export level = save level geometry to JSON", "Import level = load JSON and play it", ""]
        for line in info_lines:
            s = self.app.small_font.render(line, True, (200,200,200)); screen.blit(s, (left_x, y)); y += 18
        bx = left_x; by = y + 8; btn_w, btn_h = 160, 28
        reset_rect = pygame.Rect(bx, by, btn_w, btn_h); del_rect = pygame.Rect(bx, by + btn_h + 8, btn_w, btn_h)
        pygame.draw.rect(screen, (80,80,80), reset_rect, border_radius=6); pygame.draw.rect(screen, (80,80,80), del_rect, border_radius=6)
        screen.blit(self.app.small_font.render("Reset Progress", True, (255,255,255)), (bx + 10, by + 6))
        screen.blit(self.app.small_font.render("Delete Save File", True, (255,255,255)), (bx + 10, by + btn_h + 14))
        nav_x = left_x; nav_y = by + 72
        prev_rect = pygame.Rect(nav_x, nav_y, 72, 28); next_rect = pygame.Rect(nav_x + 82, nav_y, 72, 28)
        pygame.draw.rect(screen, (70,70,70), prev_rect, border_radius=6); pygame.draw.rect(screen, (70,70,70), next_rect, border_radius=6)
        screen.blit(self.app.small_font.render("Prev", True, (255,255,255)), (prev_rect.x + 18, prev_rect.y + 6)); screen.blit(self.app.small_font.render("Next", True, (255,255,255)), (next_rect.x + 18, next_rect.y + 6))
        grid_x = 220; grid_y = 80; cell_w = 160; cell_h = 56; padding = 10
        levels_start = self.page * self.per_page + 1; mx, my = pygame.mouse.get_pos(); self._hit = None
        for i in range(self.per_page):
            lvl = levels_start + i; col = i % 2; row = i // 2
            x = grid_x + col * (cell_w + padding); y = grid_y + row * (cell_h + padding); rect = pygame.Rect(x, y, cell_w, cell_h)
            completed = (lvl in self.progress.get("completed", [])); color = (40, 100, 40) if completed else (50,50,50)
            if rect.collidepoint((mx,my)): self._hit = ("level", lvl, rect); color = (90,90,90) if not completed else (60,150,60)
            pygame.draw.rect(screen, color, rect, border_radius=8); pygame.draw.rect(screen, (140,140,140), rect, width=2, border_radius=8)
            screen.blit(self.app.font.render(f"Level {lvl}", True, (255,255,255)), (x + 12, y + 10))
            if completed: screen.blit(self.app.small_font.render("✔ Completed", True, (220,220,220)), (x + 12, y + 32))
            ex_rect = pygame.Rect(x + cell_w - 68, y + 8, 28, 20); im_rect = pygame.Rect(x + cell_w - 34, y + 8, 28, 20)
            pygame.draw.rect(screen, (120,120,120), ex_rect, border_radius=4); pygame.draw.rect(screen, (120,120,120), im_rect, border_radius=4)
            screen.blit(self.app.small_font.render("E", True, (0,0,0)), (ex_rect.x + 8, ex_rect.y + 2)); screen.blit(self.app.small_font.render("I", True, (0,0,0)), (im_rect.x + 8, im_rect.y + 2))
        footer = self.app.small_font.render("Finish all 50 levels to unlock reset option", True, (170,170,170)); screen.blit(footer, (220, grid_x + 3 * (cell_h + padding) + 12))
        pygame.display.flip()
        clock = pygame.time.Clock()
        while True:
            evs = pygame.event.get()
            for ev in evs:
                if ev.type == QUIT: pygame.quit(); sys.exit()
                elif ev.type == KEYDOWN and ev.key == K_ESCAPE: return
                elif ev.type == VIDEORESIZE:
                    self.app.screen = pygame.display.set_mode((ev.w, ev.h), RESIZABLE); self.app.w, self.app.h = self.app.screen.get_size(); return
                elif ev.type == MOUSEBUTTONDOWN and ev.button == 1:
                    px, py = ev.pos
                    if reset_rect.collidepoint((px,py)): self.progress = {"completed": []}; save_level_progress(self.progress); return
                    if del_rect.collidepoint((px,py)): delete_level_progress_file(); self.progress = {"completed": []}; return
                    if prev_rect.collidepoint((px,py)): self.page = max(0, self.page - 1); return
                    if next_rect.collidepoint((px,py)): self.page = min(self.pages - 1, self.page + 1); return
                    for i in range(self.per_page):
                        lvl = levels_start + i; col = i % 2; row = i // 2
                        x = grid_x + col * (cell_w + padding); y = grid_y + row * (cell_h + padding); rect = pygame.Rect(x, y, cell_w, cell_h)
                        if rect.collidepoint((px,py)):
                            level_data = generate_level_by_index(lvl)
                            if lvl in self.imported_levels:
                                level_data = self.imported_levels[lvl]
                            coins_state = load_coins_data()
                            self.app.start_level(lvl, level_data, coins_state)
                            return
                        ex_rect = pygame.Rect(x + cell_w - 68, y + 8, 28, 20); im_rect = pygame.Rect(x + cell_w - 34, y + 8, 28, 20)
                        if ex_rect.collidepoint((px,py)):
                            level_data = generate_level_by_index(lvl)
                            if lvl in self.imported_levels: level_data = self.imported_levels[lvl]
                            if TK_OK:
                                root = tk.Tk(); root.withdraw()
                                path = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON files","*.json")])
                                try:
                                    if path:
                                        with open(path, "w", encoding="utf-8") as f: json.dump(level_data, f)
                                finally:
                                    try: root.destroy()
                                    except: pass
                            else:
                                fname = f"exported_level_{lvl}.json"
                                with open(fname, "w", encoding="utf-8") as f: json.dump(level_data, f)
                            return
                        if im_rect.collidepoint((px,py)):
                            if TK_OK:
                                root = tk.Tk(); root.withdraw()
                                path = filedialog.askopenfilename(filetypes=[("JSON files","*.json"),("All files","*.*")])
                                try:
                                    if path:
                                        try:
                                            with open(path, "r", encoding="utf-8") as f:
                                                data = json.load(f)
                                                self.imported_levels[lvl] = data
                                        except Exception as e:
                                            print("Failed to load level JSON:", e)
                                finally:
                                    try: root.destroy()
                                    except: pass
                            else:
                                fname = f"imported_level_{lvl}.json"
                                if os.path.exists(fname):
                                    try:
                                        with open(fname, "r", encoding="utf-8") as f:
                                            data = json.load(f)
                                            self.imported_levels[lvl] = data
                                    except Exception as e:
                                        print("Failed to load local import:", e)
                            return
            clock.tick(60)
            for ev in evs:
                if ev.type == VIDEORESIZE: return

# ---------- Main App ----------
class ImageWalkerApp:
    def __init__(self, width=DEFAULT_W, height=DEFAULT_H, caption=GAME_TITLE):
        pygame.display.set_caption(caption)
        self.screen = pygame.display.set_mode((width, height), RESIZABLE)
        self.clock = pygame.time.Clock()
        self.assets = AssetManager()
        self.mode = None
        self.running = True
        self.font = pygame.font.SysFont("Segoe UI", 20)
        self.small_font = pygame.font.SysFont("Segoe UI", 14)
        self.w, self.h = self.screen.get_size()
        self.menu_buttons = []
        self.needs_layout = True
        self.about_rect = pygame.Rect(self.w - 150, 10, 140, 28)
        self.about_text = self.small_font.render("About", True, (255,255,255))
        self.level_selector = LevelSelector(self)
        self.level_progress = load_level_progress()
        self.coins_state = load_coins_data()
        self.music_path = None
        self.music_loaded = False
        self.music_on = True
        self.music_playing = False
        # seed UI state
        self.seed_prompt_active = False
        self.seed_input_value = ""
        self.seed_warning_shown = False

    def choose_file(self, multiple=False, filetypes=None):
        if not TK_OK:
            print("tkinter not available; file dialogs disabled.")
            return None
        if filetypes is None:
            filetypes=[("Images", "*.png *.jpg *.jpeg *.webp *.bmp *.gif"), ("All files", "*.*")]
        root = tk.Tk(); root.withdraw(); root.attributes("-topmost", True)
        try:
            if multiple:
                res = filedialog.askopenfilenames(title="Choose files", filetypes=filetypes)
                return list(res)
            else:
                res = filedialog.askopenfilename(title="Choose a file", filetypes=filetypes)
                return res
        finally:
            try: root.destroy()
            except Exception: pass

    def layout_menu(self):
        self.w, self.h = self.screen.get_size()
        self.about_rect = pygame.Rect(self.w - 150, 10, 140, 28)
        self.menu_buttons.clear()
        left_btn_w = 160
        self.levels_btn_rect = pygame.Rect(20, 120, left_btn_w, 48)
        # add Seed button on the right below About
        self.seed_btn_rect = pygame.Rect(self.w - 200, 120, 160, 48)
        btn_w = 420; btn_h = 54
        cx = self.w // 2
        start_y = 120
        labels = [
            ("Play: Image Walker", self.launch_image_walker),
            ("Play: Sidescroller Image Walker", self.launch_sidescroller),
            ("Play: Super Hexagon Mode", self.launch_super_hex),
            ("Set Background…", self.set_background),
            ("Set Player Sprite…", self.set_player),
            ("Set Platform Images… (unlimited)", self.set_platforms),
            ("Set Background Music…", self.set_background_music),
            ("Quit", self.quit)
        ]
        gap = 12; y = start_y
        for text, cb in labels:
            r = pygame.Rect(cx - btn_w//2, y, btn_w, btn_h)
            self.menu_buttons.append((r, text, cb))
            y += btn_h + gap
        self.needs_layout = False

    def set_background(self):
        path = self.choose_file(multiple=False)
        if path:
            self.assets.load_single("background", path)

    def set_player(self):
        path = self.choose_file(multiple=False)
        if path:
            self.assets.load_single("player", path)

    def set_platforms(self):
        paths = self.choose_file(multiple=True)
        if paths and len(paths) > 0:
            self.assets.load_many(paths)

    def set_background_music(self):
        music_types = [("Music Files", "*.mp3 *.wav *.ogg"), ("All files", "*.*")]
        path = self.choose_file(filetypes=music_types)
        if path:
            try:
                pygame.mixer.music.load(path)
                self.music_path = path
                self.music_loaded = True
            except Exception as e:
                print("Could not load music file:", e)
                self.music_path = None; self.music_loaded = False

    def launch_image_walker(self):
        def onexit():
            try:
                if isinstance(self.mode, ImageWalkerMode):
                    self.coins_state["coins"] = self.mode.coins
                    self.coins_state["buff_end_time"] = self.mode.buff_end_time
                    save_coins_data(self.coins_state)
            except Exception:
                pass
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self.mode = None
        mode = ImageWalkerMode(self.screen, self.assets, onexit, sidescroller=False, coins_data=self.coins_state, app_ref=self)
        self.mode = mode
        mode.start()

    def launch_sidescroller(self):
        def onexit():
            try:
                if isinstance(self.mode, ImageWalkerMode):
                    self.coins_state["coins"] = self.mode.coins
                    self.coins_state["buff_end_time"] = self.mode.buff_end_time
                    save_coins_data(self.coins_state)
            except Exception:
                pass
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self.mode = None
        mode = ImageWalkerMode(self.screen, self.assets, onexit, sidescroller=True, coins_data=self.coins_state, app_ref=self)
        self.mode = mode
        mode.start()

    def launch_super_hex(self):
        def onexit():
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self.mode = None
        mode = SuperHexagonMode(self.screen, self.assets, onexit, app_ref=self)
        self.mode = mode
        mode.start()

    def quit(self):
        try:
            save_coins_data(self.coins_state)
        except Exception:
            pass
        self.running = False

    def show_about_modal(self):
        clock = pygame.time.Clock()
        msg = "Created by juicemj14, you're free to edit the code only if you know what you're doing!!"
        wrapped = textwrap.wrap(msg, width=80)
        while True:
            for ev in pygame.event.get():
                if ev.type == QUIT:
                    pygame.quit(); sys.exit()
                elif ev.type in (KEYDOWN, MOUSEBUTTONDOWN):
                    return
                elif ev.type == VIDEORESIZE:
                    self.screen = pygame.display.set_mode((ev.w, ev.h), RESIZABLE)
                    self.w, self.h = self.screen.get_size()
            overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA)
            overlay.fill((0,0,0,160))
            self.screen.blit(overlay, (0,0))
            box_w = min(760, self.w - 120)
            box_h = 120 + len(wrapped)*22
            box_x = (self.w - box_w)//2
            box_y = (self.h - box_h)//2
            pygame.draw.rect(self.screen, (240,240,240), (box_x, box_y, box_w, box_h), border_radius=8)
            pygame.draw.rect(self.screen, (120,120,120), (box_x, box_y, box_w, box_h), width=2, border_radius=8)
            title_s = self.font.render("About", True, (10,10,10))
            self.screen.blit(title_s, (box_x + 14, box_y + 10))
            y = box_y + 42
            for line in wrapped:
                s = self.small_font.render(line, True, (10,10,10))
                self.screen.blit(s, (box_x + 14, y))
                y += 20
            tip = self.small_font.render("Press any key or click to continue", True, (80,80,80))
            self.screen.blit(tip, (box_x + 14, box_y + box_h - 30))
            pygame.display.flip()
            clock.tick(30)

    def start_level(self, level_index:int, level_data:dict, coins_data=None):
        def onexit():
            try:
                if isinstance(self.mode, ImageWalkerMode):
                    self.coins_state["coins"] = self.mode.coins
                    self.coins_state["buff_end_time"] = self.mode.buff_end_time
                    save_coins_data(self.coins_state)
            except Exception:
                pass
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self.mode = None
        mode = LevelPlayMode(self.screen, self.assets, onexit, level_data, coins_data=coins_data or self.coins_state, app_ref=self)
        mode._level_index = level_index
        self.mode = mode
        mode.start()
        return

    def _load_imagewalker_from_json(self, data):
        try:
            if data.get("type") != "ImageWalker":
                return False, "JSON is not an ImageWalker export."
            mode = ImageWalkerMode(self.screen, self.assets, lambda: None, sidescroller=bool(data.get("sidescroller", False)), coins_data=self.coins_state, app_ref=self)
            mode.platforms = data.get("platforms", [])
            mode.movers = data.get("movers", [])
            mode.spikes = data.get("spikes", [])
            mode.orbs = data.get("orbs", [])
            mode.px = float(data.get("px", 100.0)); mode.py = float(data.get("py", 100.0))
            mode.vx = float(data.get("vx", 0.0)); mode.vy = float(data.get("vy", 0.0))
            mode.on_ground = bool(data.get("on_ground", False))
            mode.pw = int(data.get("pw", mode.pw)); mode.ph = int(data.get("ph", mode.ph))
            mode.time_alive = float(data.get("time_alive", 0.0)); mode.score = int(data.get("score", 0))
            mode.cam_x = float(data.get("cam_x", mode.cam_x)); mode.cam_y = float(data.get("cam_y", mode.cam_y))
            mode.level_extent_x = float(data.get("level_extent_x", mode.level_extent_x))
            mode.cam_x = max(0.0, mode.cam_x); mode.cam_y = max(0.0, mode.cam_y)
            def onexit2():
                self.mode = None
            mode.on_exit = onexit2
            self.mode = mode; mode.start()
            return True, "Loaded"
        except Exception as e:
            return False, f"Failed to load gameplay: {e}"

    # --- Seed UI: warning modal + numeric input modal ---
    def seed_warning_modal(self):
        clock = pygame.time.Clock()
        msg = "ONLY USE THIS FEATURE IF YOU KNOW WHAT YOU'RE DOING!!!\n\nThis will let you generate a deterministic platform layout from a numeric seed.\nClick OK to continue or Cancel to go back."
        wrapped = textwrap.wrap(msg, width=64)
        while True:
            for ev in pygame.event.get():
                if ev.type == QUIT:
                    pygame.quit(); sys.exit()
                elif ev.type == VIDEORESIZE:
                    self.screen = pygame.display.set_mode((ev.w, ev.h), RESIZABLE); self.w, self.h = self.screen.get_size()
                elif ev.type == KEYDOWN:
                    if ev.key in (K_RETURN, K_KP_ENTER):
                        return True
                    elif ev.key == K_ESCAPE:
                        return False
                elif ev.type == MOUSEBUTTONDOWN:
                    mx,my = ev.pos
                    # if user clicks OK or Cancel by on-screen buttons
                    # We will draw buttons and check below
            # draw modal
            overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA); overlay.fill((0,0,0,160)); self.screen.blit(overlay, (0,0))
            box_w = min(760, self.w - 120); box_h = 180 + len(wrapped)*18; box_x = (self.w - box_w)//2; box_y = (self.h - box_h)//2
            pygame.draw.rect(self.screen, (255,230,220), (box_x, box_y, box_w, box_h), border_radius=8)
            pygame.draw.rect(self.screen, (120,60,60), (box_x, box_y, box_w, 36), border_radius=8)
            title = self.font.render("WARNING", True, (10,10,10)); self.screen.blit(title, (box_x + 14, box_y + 6))
            y = box_y + 46
            for line in wrapped:
                s = self.small_font.render(line, True, (10,10,10)); self.screen.blit(s, (box_x + 14, y)); y += 18
            # OK and Cancel buttons
            ok_rect = pygame.Rect(box_x + 18, box_y + box_h - 48, 120, 34)
            cancel_rect = pygame.Rect(box_x + 18 + 140, box_y + box_h - 48, 120, 34)
            pygame.draw.rect(self.screen, (100,200,100), ok_rect, border_radius=6); pygame.draw.rect(self.screen, (200,100,100), cancel_rect, border_radius=6)
            ok_s = self.small_font.render("OK", True, (10,10,10)); cancel_s = self.small_font.render("Cancel", True, (10,10,10))
            self.screen.blit(ok_s, (ok_rect.x + (ok_rect.w - ok_s.get_width())//2, ok_rect.y + 6))
            self.screen.blit(cancel_s, (cancel_rect.x + (cancel_rect.w - cancel_s.get_width())//2, cancel_rect.y + 6))
            pygame.display.flip()
            clock.tick(30)
            for ev in pygame.event.get():
                if ev.type == MOUSEBUTTONDOWN and ev.button == 1:
                    mx,my = ev.pos
                    if ok_rect.collidepoint((mx,my)):
                        return True
                    if cancel_rect.collidepoint((mx,my)):
                        return False

    def seed_input_modal(self):
        """Displays numeric input box. Returns integer seed or None if cancel."""
        clock = pygame.time.Clock()
        value = ""
        input_active = True
        while True:
            for ev in pygame.event.get():
                if ev.type == QUIT:
                    pygame.quit(); sys.exit()
                elif ev.type == VIDEORESIZE:
                    self.screen = pygame.display.set_mode((ev.w, ev.h), RESIZABLE); self.w, self.h = self.screen.get_size()
                elif ev.type == KEYDOWN:
                    if ev.key == K_ESCAPE:
                        return None
                    elif ev.key in (K_RETURN, K_KP_ENTER):
                        if len(value) == 0:
                            # ignore empty
                            continue
                        try:
                            seed_int = int(value)
                            return seed_int
                        except Exception:
                            return None
                    elif ev.key == K_BACKSPACE:
                        value = value[:-1]
                    else:
                        ch = ev.unicode
                        if ch.isdigit():
                            value += ch
                elif ev.type == MOUSEBUTTONDOWN and ev.button == 1:
                    # If user clicks Generate or Cancel: we'll handle after drawing
                    pass
            # draw input UI
            overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA); overlay.fill((0,0,0,160)); self.screen.blit(overlay, (0,0))
            box_w = min(700, self.w - 140); box_h = 140; box_x = (self.w - box_w)//2; box_y = (self.h - box_h)//2
            pygame.draw.rect(self.screen, (240,240,240), (box_x, box_y, box_w, box_h), border_radius=8)
            prompt = self.small_font.render("Enter numeric seed (digits only):", True, (10,10,10))
            self.screen.blit(prompt, (box_x + 14, box_y + 12))
            # input box
            inp_rect = pygame.Rect(box_x + 14, box_y + 40, box_w - 28, 36)
            pygame.draw.rect(self.screen, (255,255,255), inp_rect, border_radius=6)
            pygame.draw.rect(self.screen, (120,120,120), inp_rect, width=2, border_radius=6)
            txt = self.small_font.render(value if len(value) > 0 else "<type digits>", True, (10,10,10))
            self.screen.blit(txt, (inp_rect.x + 8, inp_rect.y + 8))
            # buttons
            gen_rect = pygame.Rect(box_x + 14, box_y + box_h - 46, 140, 34)
            cancel_rect = pygame.Rect(box_x + 14 + 160, box_y + box_h - 46, 140, 34)
            pygame.draw.rect(self.screen, (100,180,100), gen_rect, border_radius=6)
            pygame.draw.rect(self.screen, (180,100,100), cancel_rect, border_radius=6)
            gen_s = self.small_font.render("Generate Seed", True, (10,10,10)); cancel_s = self.small_font.render("Cancel", True, (10,10,10))
            self.screen.blit(gen_s, (gen_rect.x + (gen_rect.w - gen_s.get_width())//2, gen_rect.y + 6))
            self.screen.blit(cancel_s, (cancel_rect.x + (cancel_rect.w - cancel_s.get_width())//2, cancel_rect.y + 6))
            pygame.display.flip()
            clock.tick(30)
            for ev in pygame.event.get():
                if ev.type == MOUSEBUTTONDOWN and ev.button == 1:
                    mx,my = ev.pos
                    if gen_rect.collidepoint((mx,my)):
                        if len(value) == 0:
                            # nothing entered
                            continue
                        try:
                            return int(value)
                        except Exception:
                            return None
                    if cancel_rect.collidepoint((mx,my)):
                        return None

    def launch_seeded_image_walker(self, seed_int: int, sidescroller=False):
        """
        Start ImageWalker with deterministic initial layout generated from seed_int.
        We'll generate a level using generate_level_by_index(seed_int) and populate the mode.platforms
        with it. Subsequent chunks will continue using normal random generation.
        """
        level_data = generate_level_by_index(seed_int, width=2400, ground_y=400)
        def onexit():
            try:
                if isinstance(self.mode, ImageWalkerMode):
                    self.coins_state["coins"] = self.mode.coins
                    self.coins_state["buff_end_time"] = self.mode.buff_end_time
                    save_coins_data(self.coins_state)
            except Exception:
                pass
            try:
                pygame.mixer.music.stop()
            except Exception:
                pass
            self.mode = None
        mode = ImageWalkerMode(self.screen, self.assets, onexit, sidescroller=sidescroller, coins_data=self.coins_state, app_ref=self)
        # Replace platform set with deterministic platforms (no extra starting-ground fix per user)
        mode.platforms = []
        for p in level_data.get("platforms", []):
            if p.get("spikes"):
                mode.spikes.append({"x": float(p["x"]), "y": float(p["y"]), "w": float(p["w"]), "h": float(p["h"])})
            else:
                mode.platforms.append({"x": float(p["x"]), "y": float(p["y"]), "w": float(p["w"]), "h": float(p["h"]), "photo": None})
        mode.level_extent_x = level_data.get("width", mode.level_extent_x)
        # position player at first platform (as ImageWalkerMode normally would without the removed bugfix)
        if mode.platforms:
            first = mode.platforms[0]
            mode.px = first["x"] + 20
            mode.py = first["y"] - mode.ph - 2
        else:
            mode.px = 100.0
            mode.py = mode.ground_y - mode.ph - 2
        mode.cam_x = mode.px - mode.w * 0.4
        mode.cam_y = mode.py - mode.h * 0.6
        self.mode = mode
        mode.start()

    def run(self):
        FPS = 60
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0
            events = pygame.event.get()
            for ev in events:
                if ev.type == QUIT:
                    try: save_coins_data(self.coins_state)
                    except Exception: pass
                    self.running = False
                elif ev.type == VIDEORESIZE:
                    self.screen = pygame.display.set_mode((ev.w, ev.h), RESIZABLE)
                    self.needs_layout = True
                    self.w, self.h = self.screen.get_size()
                elif ev.type == KEYDOWN and ev.key == K_F1:
                    if self.mode is None:
                        self.show_about_modal()
                elif ev.type == KEYDOWN and ev.key == K_i and self.mode is None:
                    if TK_OK:
                        root = tk.Tk(); root.withdraw()
                        path = filedialog.askopenfilename(filetypes=[("JSON files","*.json"),("All files","*.*")])
                        try:
                            if path:
                                try:
                                    with open(path, "r", encoding="utf-8") as f:
                                        data = json.load(f)
                                    ok, msg = self._load_imagewalker_from_json(data)
                                    if not ok:
                                        self._modal_message(msg)
                                except Exception as e:
                                    self._modal_message(f"Failed to read JSON: {e}")
                        finally:
                            try: root.destroy()
                            except: pass
                    else:
                        fname = "imagewalker_import.json"
                        if os.path.exists(fname):
                            try:
                                with open(fname, "r", encoding="utf-8") as f:
                                    data = json.load(f)
                                ok, msg = self._load_imagewalker_from_json(data)
                                if not ok:
                                    self._modal_message(msg)
                            except Exception as e:
                                self._modal_message(f"Failed to read local JSON: {e}")
            # menu-only clicks (about, levels, seed)
            if self.mode is None:
                for ev in events:
                    if ev.type == MOUSEBUTTONDOWN and ev.button == 1:
                        mx, my = ev.pos
                        self.about_rect = pygame.Rect(self.w - 150, 10, 140, 28)
                        if hasattr(self, "levels_btn_rect") and self.levels_btn_rect.collidepoint((mx,my)):
                            self.level_selector.draw()
                        if self.about_rect.collidepoint((mx, my)):
                            self.show_about_modal()
                        if hasattr(self, "seed_btn_rect") and self.seed_btn_rect.collidepoint((mx,my)):
                            # Seed button clicked: show warning -> input -> generate
                            ok = self.seed_warning_modal()
                            if not ok:
                                # user cancelled warning
                                pass
                            else:
                                seed_val = self.seed_input_modal()
                                if seed_val is None:
                                    # cancelled input
                                    pass
                                else:
                                    # Start image walker with seed
                                    self.launch_seeded_image_walker(seed_val, sidescroller=False)
            # mode tick or menu draw
            if self.mode is None:
                if self.needs_layout:
                    self.layout_menu()
                self.draw_menu(events)
            else:
                cont = self.mode.tick(events, dt)
                if not cont:
                    try:
                        if isinstance(self.mode, ImageWalkerMode):
                            self.coins_state["coins"] = self.mode.coins
                            self.coins_state["buff_end_time"] = self.mode.buff_end_time
                            save_coins_data(self.coins_state)
                    except Exception:
                        pass
                    try:
                        pygame.mixer.music.stop()
                    except Exception:
                        pass
                    finished_flag = False
                    if isinstance(self.mode, LevelPlayMode):
                        idx = getattr(self.mode, "_level_index", None)
                        try:
                            if getattr(self.mode, "px", 0) + self.mode.pw >= self.mode.finish["x"]:
                                finished_flag = True
                        except Exception:
                            finished_flag = False
                        if finished_flag and idx is not None:
                            prog = load_level_progress()
                            completed = set(prog.get("completed", [])); completed.add(idx); prog["completed"] = sorted(list(completed)); save_level_progress(prog)
                    self.mode = None
            pygame.display.flip()
        pygame.quit()

    def _modal_message(self, text):
        clock = pygame.time.Clock(); wrapped = textwrap.wrap(text, width=80)
        while True:
            for ev in pygame.event.get():
                if ev.type == QUIT: pygame.quit(); sys.exit()
                elif ev.type in (KEYDOWN, MOUSEBUTTONDOWN): return
                elif ev.type == VIDEORESIZE:
                    self.screen = pygame.display.set_mode((ev.w, ev.h), RESIZABLE); self.w, self.h = self.screen.get_size(); return
            overlay = pygame.Surface((self.w, self.h), pygame.SRCALPHA); overlay.fill((0,0,0,160)); self.screen.blit(overlay, (0,0))
            box_w = min(760, self.w - 120); box_h = 120 + len(wrapped)*22; box_x = (self.w - box_w)//2; box_y = (self.h - box_h)//2
            pygame.draw.rect(self.screen, (240,240,240), (box_x, box_y, box_w, box_h), border_radius=8); pygame.draw.rect(self.screen, (120,120,120), (box_x, box_y, box_w, box_h), width=2, border_radius=8)
            title_s = self.font.render("Message", True, (10,10,10)); self.screen.blit(title_s, (box_x + 14, box_y + 10))
            y = box_y + 42
            for line in wrapped:
                s = self.small_font.render(line, True, (10,10,10)); self.screen.blit(s, (box_x + 14, y)); y += 20
            tip = self.small_font.render("Press any key or click to continue", True, (80,80,80)); self.screen.blit(tip, (box_x + 14, box_y + box_h - 30))
            pygame.display.flip(); clock.tick(30)

    def draw_menu(self, events):
        bg = self.assets.get_bg(*self.screen.get_size())
        if bg: self.screen.blit(bg, (0,0))
        else: self.screen.fill((11,11,11))
        title_font = pygame.font.SysFont("Segoe UI", 36, bold=True)
        title_s = title_font.render(GAME_TITLE, True, (255,255,255)); self.screen.blit(title_s, (self.w//2 - title_s.get_width()//2, 30))
        desc = "Image Walker Forever — Image Walker + Sidescroller + Levels + Springs + Coins"
        desc_s = self.small_font.render(desc, True, (187,187,187)); self.screen.blit(desc_s, (self.w//2 - desc_s.get_width()//2, 84))
        mx, my = pygame.mouse.get_pos()
        if hasattr(self, "levels_btn_rect"):
            hovered = self.levels_btn_rect.collidepoint((mx,my))
            color = (68,68,100) if hovered else (48,48,68)
            pygame.draw.rect(self.screen, color, self.levels_btn_rect, border_radius=8)
            text = self.small_font.render("Levels", True, (255,255,255))
            self.screen.blit(text, (self.levels_btn_rect.x + (self.levels_btn_rect.w - text.get_width())//2, self.levels_btn_rect.y + (self.levels_btn_rect.h - text.get_height())//2))
        # seed button on right
        if hasattr(self, "seed_btn_rect"):
            hovered_s = self.seed_btn_rect.collidepoint((mx,my))
            color_s = (90,70,40) if hovered_s else (70,50,30)
            pygame.draw.rect(self.screen, color_s, self.seed_btn_rect, border_radius=8)
            stext = self.small_font.render("Seed", True, (255,255,255))
            self.screen.blit(stext, (self.seed_btn_rect.x + (self.seed_btn_rect.w - stext.get_width())//2, self.seed_btn_rect.y + (self.seed_btn_rect.h - stext.get_height())//2))
        for rect, text, cb in self.menu_buttons:
            hovered = rect.collidepoint((mx,my))
            color = (48,48,48) if not hovered else (68,68,68)
            pygame.draw.rect(self.screen, color, rect, border_radius=8)
            pygame.draw.rect(self.screen, (140,140,140), rect, width=2, border_radius=8)
            txt_s = self.font.render(text, True, (255,255,255))
            self.screen.blit(txt_s, (rect.x + (rect.w - txt_s.get_width())//2, rect.y + (rect.h - txt_s.get_height())//2))
        for ev in events:
            if ev.type == MOUSEBUTTONDOWN and ev.button == 1:
                if hasattr(self, "levels_btn_rect") and self.levels_btn_rect.collidepoint(ev.pos):
                    self.level_selector.draw()
                if hasattr(self, "seed_btn_rect") and self.seed_btn_rect.collidepoint(ev.pos):
                    ok = self.seed_warning_modal()
                    if not ok:
                        pass
                    else:
                        seed_val = self.seed_input_modal()
                        if seed_val is None:
                            pass
                        else:
                            self.launch_seeded_image_walker(seed_val, sidescroller=False)
                for rect, text, cb in self.menu_buttons:
                    if rect.collidepoint(ev.pos):
                        cb()
            elif ev.type == KEYDOWN:
                if ev.key == K_ESCAPE:
                    self.running = False
                elif ev.key == K_i:
                    if TK_OK:
                        root = tk.Tk(); root.withdraw()
                        try:
                            path = filedialog.askopenfilename(filetypes=[("JSON files","*.json"),("All files","*.*")])
                            if path:
                                try:
                                    with open(path, "r", encoding="utf-8") as f:
                                        data = json.load(f)
                                    ok, msg = self._load_imagewalker_from_json(data)
                                    if not ok:
                                        self._modal_message(msg)
                                except Exception as e:
                                    self._modal_message(f"Failed to read JSON: {e}")
                        finally:
                            try: root.destroy()
                            except: pass
                    else:
                        fname = "imagewalker_import.json"
                        if os.path.exists(fname):
                            try:
                                with open(fname, "r", encoding="utf-8") as f: data = json.load(f)
                                ok, msg = self._load_imagewalker_from_json(data)
                                if not ok: self._modal_message(msg)
                            except Exception as e:
                                self._modal_message(f"Failed to read local JSON: {e}")
        # About button (visible only in menu)
        self.about_rect = pygame.Rect(self.w - 150, 10, 140, 28)
        hovered = self.about_rect.collidepoint((mx,my))
        pygame.draw.rect(self.screen, (68,68,68) if hovered else (48,48,48), self.about_rect, border_radius=6)
        pygame.draw.rect(self.screen, (120,120,120), self.about_rect, width=1, border_radius=6)
        self.screen.blit(self.about_text, (self.about_rect.x + 18, self.about_rect.y + 6))

# ---------- Run ----------
if __name__ == "__main__":
    app = ImageWalkerApp()
    app.run()
