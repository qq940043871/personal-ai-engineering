# -*- coding: utf-8 -*-
"""把身份证正反面拼到一张图上，并叠加斜向平铺水印。"""
import math
import os

from PIL import Image, ImageDraw, ImageFont

BASE = r"D:/ai_person/personal-ai-engineering/ai-tools/05-photo-merge"
FONT_PATH = r"C:/Windows/Fonts/simhei.ttf"
TEXT = "仅供停保用"

front = Image.open(os.path.join(BASE, "身份证_1.jpg")).rotate(90, expand=True).convert("RGB")
back = Image.open(os.path.join(BASE, "身份证_2.jpg")).rotate(90, expand=True).convert("RGB")

w, h = front.size  # 1440 x 810

margin = 30
gap = 24
canvas_w = w + margin * 2
canvas_h = h * 2 + gap + margin * 2

canvas = Image.new("RGB", (canvas_w, canvas_h), (238, 238, 238))
canvas.paste(front, (margin, margin))
canvas.paste(back, (margin, margin + h + gap))

# --- 斜向平铺半透明水印 ---
wm = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
draw = ImageDraw.Draw(wm)
font = ImageFont.truetype(FONT_PATH, 58)
bbox = draw.textbbox((0, 0), TEXT, font=font)
text_w = bbox[2] - bbox[0]
text_h = bbox[3] - bbox[1]

diag = int(math.hypot(canvas_w, canvas_h)) + 200
tile = Image.new("RGBA", (diag, diag), (0, 0, 0, 0))
td = ImageDraw.Draw(tile)
step_x = text_w + 110
step_y = text_h + 130
for y in range(0, diag, step_y):
    for x in range(0, diag, step_x):
        td.text((x, y), TEXT, font=font, fill=(205, 30, 30, 62))

tile = tile.rotate(30, resample=Image.BICUBIC)
left = (diag - canvas_w) // 2
top = (diag - canvas_h) // 2
tile = tile.crop((left, top, left + canvas_w, top + canvas_h))

result = Image.alpha_composite(canvas.convert("RGBA"), tile).convert("RGB")
out_path = os.path.join(BASE, "身份证_合并_水印.jpg")
result.save(out_path, quality=93, subsampling=0)
print("saved:", out_path, result.size)
