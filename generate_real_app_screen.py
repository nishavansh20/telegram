import os
from PIL import Image, ImageDraw, ImageFont

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ASSETS_DIR = os.path.join(BASE_DIR, "assets")
OUTPUT_PATH = os.path.join(ASSETS_DIR, "peak_arena_app_screen.png")

W, H = 720, 1280
img = Image.new("RGBA", (W, H), (8, 8, 10, 255))
draw = ImageDraw.Draw(img)

font_dir = "C:/Windows/Fonts"
font_bold = os.path.join(font_dir, "segoeuib.ttf") if os.path.exists(os.path.join(font_dir, "segoeuib.ttf")) else None
font_reg = os.path.join(font_dir, "segoeui.ttf") if os.path.exists(os.path.join(font_dir, "segoeui.ttf")) else None

if font_bold and font_reg:
    f_status = ImageFont.truetype(font_reg, 18)
    f_title = ImageFont.truetype(font_bold, 24)
    f_wallet = ImageFont.truetype(font_bold, 20)
    f_badge = ImageFont.truetype(font_bold, 13)
    f_card_title = ImageFont.truetype(font_bold, 21)
    f_label = ImageFont.truetype(font_bold, 12)
    f_val_large = ImageFont.truetype(font_bold, 23)
    f_btn = ImageFont.truetype(font_bold, 18)
    f_sub = ImageFont.truetype(font_reg, 13)
    f_nav = ImageFont.truetype(font_bold, 12)
else:
    f_status = f_title = f_wallet = f_badge = f_card_title = f_label = f_val_large = f_btn = f_sub = f_nav = ImageFont.load_default()

# 1. Status Bar
draw.text((24, 8), "10:45", fill=(200, 200, 200), font=f_status)
draw.text((W - 130, 8), "5G  98% [■]", fill=(200, 200, 200), font=f_status)

# 2. AppBar (36 - 98)
logo_path = os.path.join(ASSETS_DIR, "logo.png")
if os.path.exists(logo_path):
    logo = Image.open(logo_path).convert("RGBA").resize((44, 44), Image.Resampling.LANCZOS)
    mask = Image.new("L", (44, 44), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, 44, 44), radius=12, fill=255)
    img.paste(logo, (24, 44), mask)
    draw.rounded_rectangle([23, 43, 69, 89], radius=12, outline=(212, 160, 23), width=2)

draw.text((80, 46), "PEAK ARENA", fill=(255, 255, 255), font=f_title)
draw.text((82, 73), "OFFICIAL ESPORTS APP", fill=(0, 240, 255), font=f_badge)

# Wallet pill
w_box = [W - 145, 46, W - 24, 86]
draw.rounded_rectangle(w_box, radius=20, fill=(28, 24, 12), outline=(212, 160, 23), width=2)
draw.text((W - 132, 53), "₹750", fill=(251, 191, 36), font=f_wallet)
draw.text((W - 62, 55), "WALLET", fill=(212, 160, 23), font=f_badge)

# 3. Game category tabs (104 - 144)
tabs = [("Free Fire", True), ("BGMI", False), ("TDM 4v4", False), ("Offers", False)]
tx = 24
for name, active in tabs:
    tw = draw.textlength(name, font=f_badge) + 26
    if active:
        draw.rounded_rectangle([tx, 102, tx + tw, 138], radius=18, fill=(212, 160, 23), outline=(251, 191, 36), width=1)
        draw.text((tx + 13, 112), name, fill=(0, 0, 0), font=f_badge)
    else:
        draw.rounded_rectangle([tx, 102, tx + tw, 138], radius=18, fill=(18, 20, 26), outline=(35, 43, 58), width=1)
        draw.text((tx + 13, 112), name, fill=(139, 145, 158), font=f_badge)
    tx += tw + 10

# Helper to draw Tournament Poster Card
def draw_tournament_card(card_y, banner_file, badge_txt, title, mode_txt, p1_lbl, p1_val, p1_col, p2_lbl, p2_val, p2_col, p3_lbl, p3_val, p3_col, slots_txt, slots_pct, btn_txt, btn_col):
    card_h = 350
    cx1, cy1, cx2, cy2 = 20, card_y, W - 20, card_y + card_h
    card_w = cx2 - cx1

    # Base card background
    draw.rounded_rectangle([cx1, cy1, cx2, cy2], radius=18, fill=(13, 14, 18), outline=(212, 160, 23), width=2)

    # Banner image with gradient
    banner_path = os.path.join(ASSETS_DIR, banner_file)
    banner_h = 135
    if os.path.exists(banner_path):
        banner = Image.open(banner_path).convert("RGBA").resize((card_w - 4, banner_h), Image.Resampling.LANCZOS)
        grad = Image.new("RGBA", (card_w - 4, banner_h))
        g_draw = ImageDraw.Draw(grad)
        for y in range(banner_h):
            alpha = int(255 * (y / banner_h) ** 1.3)
            g_draw.line([(0, y), (card_w - 4, y)], fill=(13, 14, 18, alpha))
        banner = Image.alpha_composite(banner, grad)
        img.paste(banner, (cx1 + 2, cy1 + 2))

    # Badge on banner
    bw = draw.textlength(badge_txt, font=f_badge)
    draw.rounded_rectangle([cx1 + 16, cy1 + 16, cx1 + 32 + bw, cy1 + 38], radius=6, fill=(251, 191, 36))
    draw.text((cx1 + 24, cy1 + 20), badge_txt, fill=(0, 0, 0), font=f_badge)

    draw.text((cx1 + 16, cy1 + 75), title, fill=(255, 255, 255), font=f_card_title)
    draw.text((cx1 + 16, cy1 + 105), mode_txt, fill=(0, 240, 255), font=f_sub)

    # 3-Stat Container Box
    bx1, by1, bx2, by2 = cx1 + 14, cy1 + 140, cx2 - 14, cy1 + 215
    draw.rounded_rectangle([bx1, by1, bx2, by2], radius=12, fill=(21, 24, 33), outline=(40, 48, 65), width=1)

    col_w = (bx2 - bx1) // 3
    # Stat 1
    draw.text((bx1 + 15, by1 + 12), p1_lbl, fill=(139, 145, 158), font=f_label)
    draw.text((bx1 + 15, by1 + 36), p1_val, fill=p1_col, font=f_val_large)
    draw.line([(bx1 + col_w, by1 + 10), (bx1 + col_w, by2 - 10)], fill=(40, 48, 65), width=1)

    # Stat 2
    draw.text((bx1 + col_w + 15, by1 + 12), p2_lbl, fill=(139, 145, 158), font=f_label)
    draw.text((bx1 + col_w + 15, by1 + 36), p2_val, fill=p2_col, font=f_val_large)
    draw.line([(bx1 + 2 * col_w, by1 + 10), (bx1 + 2 * col_w, by2 - 10)], fill=(40, 48, 65), width=1)

    # Stat 3
    draw.text((bx1 + 2 * col_w + 15, by1 + 12), p3_lbl, fill=(139, 145, 158), font=f_label)
    draw.text((bx1 + 2 * col_w + 15, by1 + 36), p3_val, fill=p3_col, font=f_val_large)

    # Slots Progress Bar
    draw.text((cx1 + 16, cy1 + 228), slots_txt, fill=(200, 200, 200), font=f_sub)
    draw.text((cx2 - 135, cy1 + 228), "• ALMOST FULL", fill=(255, 120, 0), font=f_badge)
    
    px1, py1, px2, py2 = cx1 + 16, cy1 + 252, cx2 - 16, cy1 + 262
    draw.rounded_rectangle([px1, py1, px2, py2], radius=5, fill=(35, 43, 58))
    fill_w = int((px2 - px1) * slots_pct)
    draw.rounded_rectangle([px1, py1, px1 + fill_w, py2], radius=5, fill=(251, 191, 36))

    # Join Match CTA Button
    btn_x1, btn_y1, btn_x2, btn_y2 = cx1 + 16, cy1 + 280, cx2 - 16, cy1 + 332
    draw.rounded_rectangle([btn_x1, btn_y1, btn_x2, btn_y2], radius=10, fill=btn_col)
    btn_w = draw.textlength(btn_txt, font=f_btn)
    draw.text((btn_x1 + (btn_x2 - btn_x1 - btn_w) // 2, btn_y1 + 15), btn_txt, fill=(0, 0, 0), font=f_btn)

# Card 1: Solo BR
draw_tournament_card(
    card_y=155,
    banner_file="freefire_br.jpg",
    badge_txt="OFFICIAL TOURNAMENT",
    title="BERMUDA SOLO BATTLE ROYALE",
    mode_txt="Solo BR  •  Bermuda Map  •  Daily Free Tournaments",
    p1_lbl="PRIZE POOL", p1_val="₹700", p1_col=(251, 191, 36),
    p2_lbl="PER KILL", p2_val="₹12", p2_col=(0, 240, 255),
    p3_lbl="ENTRY FEE", p3_val="₹15", p3_col=(16, 185, 129),
    slots_txt="44 / 48 Slots Filled",
    slots_pct=0.91,
    btn_txt="JOIN MATCH (₹15 ENTRY)",
    btn_col=(16, 185, 129)
)

# Card 2: Clash Squad 4v4
draw_tournament_card(
    card_y=525,
    banner_file="freefire_cs.jpg",
    badge_txt="CS RANKED 4V4",
    title="CLASH SQUAD SQUAD WAR",
    mode_txt="Squad 4v4  •  Kalahari Map  •  Instant Room Code",
    p1_lbl="WINNER CASH", p1_val="₹35", p1_col=(251, 191, 36),
    p2_lbl="FORMAT", p2_val="4 VS 4", p2_col=(0, 240, 255),
    p3_lbl="ENTRY FEE", p3_val="₹20", p3_col=(16, 185, 129),
    slots_txt="7 / 8 Slots Filled",
    slots_pct=0.88,
    btn_txt="JOIN SQUAD ROOM (₹20 ENTRY)",
    btn_col=(0, 240, 255)
)

# 5. Promo & Instant UPI Banner (895 - 1000)
ub_x1, ub_y1, ub_x2, ub_y2 = 20, 895, W - 20, 1000
draw.rounded_rectangle([ub_x1, ub_y1, ub_x2, ub_y2], radius=16, fill=(18, 20, 28), outline=(212, 160, 23), width=2)
hero_path = os.path.join(ASSETS_DIR, "hero_banner.jpg")
if os.path.exists(hero_path):
    hero = Image.open(hero_path).convert("RGBA").resize((ub_x2 - ub_x1 - 4, ub_y2 - ub_y1 - 4), Image.Resampling.LANCZOS)
    h_grad = Image.new("RGBA", (ub_x2 - ub_x1 - 4, ub_y2 - ub_y1 - 4))
    hg_draw = ImageDraw.Draw(h_grad)
    for y in range(ub_y2 - ub_y1 - 4):
        hg_draw.line([(0, y), (ub_x2 - ub_x1 - 4, y)], fill=(12, 14, 20, 215))
    hero = Image.alpha_composite(hero, h_grad)
    img.paste(hero, (ub_x1 + 2, ub_y1 + 2))

draw.text((ub_x1 + 20, ub_y1 + 16), "• INSTANT 5-MIN UPI CASHOUT •", fill=(251, 191, 36), font=f_card_title)
draw.text((ub_x1 + 20, ub_y1 + 48), "PhonePe  •  Google Pay  •  Paytm  •  Direct to Bank", fill=(200, 200, 200), font=f_sub)
draw.rounded_rectangle([ub_x1 + 20, ub_y1 + 72, ub_x1 + 330, ub_y1 + 96], radius=6, fill=(212, 160, 23))
draw.text((ub_x1 + 28, ub_y1 + 75), "USE CODE: PEAK10 FOR ₹10 FREE", fill=(0, 0, 0), font=f_badge)

# Trust badge (1015 - 1180)
tb_x1, tb_y1, tb_x2, tb_y2 = 20, 1015, W - 20, 1180
draw.rounded_rectangle([tb_x1, tb_y1, tb_x2, tb_y2], radius=14, fill=(15, 17, 23), outline=(35, 43, 58), width=1)
draw.text((tb_x1 + 20, tb_y1 + 18), "• 100% SECURE & ANTI-CHEAT VERIFIED", fill=(16, 185, 129), font=f_card_title)
draw.text((tb_x1 + 20, tb_y1 + 52), "• Auto Room ID & Password sent 15 mins before match", fill=(220, 220, 220), font=f_sub)
draw.text((tb_x1 + 20, tb_y1 + 80), "• Instant Kill Verification & Winnings Auto-Credited", fill=(220, 220, 220), font=f_sub)
draw.text((tb_x1 + 20, tb_y1 + 108), "• 24x7 WhatsApp & In-App Customer Support", fill=(220, 220, 220), font=f_sub)

# 6. Bottom Navigation Bar (1200 - 1280) with clean drawn vector icons
nav_y = 1205
draw.rectangle([0, nav_y, W, H], fill=(13, 14, 18))
draw.line([(0, nav_y), (W, nav_y)], fill=(35, 43, 58), width=1)

nav_tabs = ["Rank", "Offers", "Home", "Wallet", "Profile"]
nw = W // 5

def draw_vector_icon(idx, active):
    cx = idx * nw + nw // 2
    cy = nav_y + 20
    col = (251, 191, 36) if active else (139, 145, 158)
    if idx == 0: # Trophy
        draw.rectangle([cx - 7, cy - 8, cx + 7, cy + 2], fill=col)
        draw.polygon([(cx - 3, cy + 2), (cx + 3, cy + 2), (cx, cy + 8)], fill=col)
        draw.rectangle([cx - 8, cy + 8, cx + 8, cy + 11], fill=col)
    elif idx == 1: # Offers Tag
        draw.polygon([(cx - 9, cy - 8), (cx + 3, cy - 8), (cx + 9, cy - 1), (cx - 3, cy + 10), (cx - 9, cy + 3)], fill=col)
    elif idx == 2: # Home
        draw.polygon([(cx, cy - 10), (cx - 10, cy), (cx + 10, cy)], fill=col)
        draw.rectangle([cx - 8, cy, cx + 8, cy + 10], fill=col)
        draw.rectangle([cx - 3, cy + 4, cx + 3, cy + 10], fill=(13, 14, 18))
    elif idx == 3: # Wallet
        draw.rounded_rectangle([cx - 10, cy - 7, cx + 10, cy + 8], radius=3, fill=col)
        draw.ellipse([cx + 1, cy - 2, cx + 6, cy + 3], fill=(13, 14, 18))
    elif idx == 4: # Profile
        draw.ellipse([cx - 5, cy - 8, cx + 5, cy + 1], fill=col)
        draw.pieslice([cx - 9, cy + 1, cx + 9, cy + 15], 180, 360, fill=col)

for i, name in enumerate(nav_tabs):
    active = (i == 2)
    draw_vector_icon(i, active)
    nx = i * nw + nw // 2
    col = (251, 191, 36) if active else (139, 145, 158)
    tw = draw.textlength(name, font=f_nav)
    draw.text((nx - tw // 2, nav_y + 45), name, fill=col, font=f_nav)

img.save(OUTPUT_PATH, "PNG", quality=95)
print(f"Updated Peak Arena App Screen: {OUTPUT_PATH}")
