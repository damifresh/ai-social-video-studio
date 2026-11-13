from __future__ import annotations
import math, random, textwrap
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

def _dims(aspect: str):
    # 720p targets
    if aspect == "9:16": return (720, 1280)
    if aspect == "1:1": return (720, 720)
    return (1280, 720)  # 16:9

def _font(size: int):
    # Try common macOS fonts
    for name in ["/System/Library/Fonts/Supplemental/Arial Bold.ttf",
                 "/System/Library/Fonts/Supplemental/Arial.ttf",
                 "/System/Library/Fonts/Helvetica.ttc",
                 "/Library/Fonts/Arial.ttf"]:
        try: return ImageFont.truetype(name, size)
        except Exception: pass
    return ImageFont.load_default()

def _wrap(draw, text, font, max_w):
    words = (text or "").split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        bbox = draw.textbbox((0,0), test, font=font)
        if bbox[2]-bbox[0] <= max_w or not cur:
            cur = test
        else:
            lines.append(cur); cur = w
    if cur: lines.append(cur)
    return lines[:6]

def generate_scene_image(scene: dict, out_path: Path, aspect: str = "16:9", style: str = "cinematic", idx: int = 0) -> Path:
    W,H = _dims(aspect)
    rng = random.Random((scene.get('narration','') + str(idx)))
    palettes = {
        "cinematic": [(15,23,42),(30,41,59),(99,102,241),(14,165,233)],
        "documentary": [(20,30,20),(40,60,40),(180,160,90),(230,220,200)],
        "educational": [(10,30,60),(20,60,120),(80,180,255),(240,248,255)],
        "explainer": [(25,25,35),(60,60,90),(0,200,180),(255,255,255)],
        "news": [(15,15,20),(40,40,50),(220,50,50),(240,240,240)],
        "motivational": [(30,10,40),(80,20,60),(255,140,0),(255,230,180)],
        "marketing": [(10,10,30),(40,20,80),(255,80,120),(255,255,255)],
        "faceless": [(12,12,18),(30,30,45),(120,120,255),(220,220,240)],
    }
    pal = palettes.get(style, palettes["cinematic"])
    img = Image.new("RGB", (W,H), pal[0])
    draw = ImageDraw.Draw(img, "RGBA")
    # gradient background
    for y in range(H):
        t = y / max(1,H-1)
        r = int(pal[0][0]*(1-t) + pal[1][0]*t)
        g = int(pal[0][1]*(1-t) + pal[1][1]*t)
        b = int(pal[0][2]*(1-t) + pal[1][2]*t)
        draw.line([(0,y),(W,y)], fill=(r,g,b,255))
    # decorative shapes
    for _ in range(6):
        x = rng.randint(-W//4, W)
        y = rng.randint(-H//4, H)
        rad = rng.randint(min(W,H)//10, min(W,H)//2)
        col = pal[2 + (_%2)]
        alpha = rng.randint(20, 60)
        draw.ellipse([x-rad,y-rad,x+rad,y+rad], fill=(col[0],col[1],col[2],alpha))
    # subtle grid
    step = 80
    for x in range(0,W,step): draw.line([(x,0),(x,H)], fill=(255,255,255,10))
    for y in range(0,H,step): draw.line([(0,y),(W,y)], fill=(255,255,255,10))
    # title/overlay
    title = (scene.get('text_overlay') or scene.get('title') or '').strip()[:90]
    desc = (scene.get('visual_description') or scene.get('narration') or '').strip()[:180]
    margin = 60
    title_font = _font(max(28, W//18))
    body_font = _font(max(20, W//32))
    small_font = _font(max(16, W//45))
    # bottom panel
    panel_h = int(H*0.38)
    draw.rectangle([0, H-panel_h, W, H], fill=(0,0,0,120))
    y = H-panel_h + 30
    for line in _wrap(draw, title, title_font, W - margin*2):
        draw.text((margin, y), line, font=title_font, fill=(255,255,255,240))
        bbox = draw.textbbox((0,0), line, font=title_font); y += (bbox[3]-bbox[1]) + 8
    y += 6
    for line in _wrap(draw, desc, body_font, W - margin*2)[:3]:
        draw.text((margin, y), line, font=body_font, fill=(220,230,245,220))
        bbox = draw.textbbox((0,0), line, font=body_font); y += (bbox[3]-bbox[1]) + 6
    # scene badge
    badge = f"SCENE {idx+1} · {style.upper()}"
    draw.rounded_rectangle([margin, 40, margin + 20 + len(badge)*12, 80], radius=8, fill=(pal[2][0],pal[2][1],pal[2][2],200))
    draw.text((margin+10, 48), badge, font=small_font, fill=(255,255,255,240))
    # kind label (honest)
    kind = scene.get('visual_kind','animated_graphic')
    label = "ANIMATED GRAPHIC" if kind == 'animated_graphic' else kind.upper().replace('_',' ')
    draw.text((W-margin-220, 48), label, font=small_font, fill=(200,210,230,180))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=92)
    return out_path
