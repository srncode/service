import hashlib
from io import BytesIO
from pathlib import Path

import qrcode
from PIL import Image, ImageDraw, ImageFont

BASE = Path(__file__).resolve().parent

# ───────────── 폰트 ─────────────
# (경로, ttc 인덱스) 순서대로 시도. Streamlit Cloud는 packages.txt 에 fonts-nanum 추가
_FONT_CANDIDATES = [
    ("fonts/NanumGothicBold.ttf", 0),
    ("fonts/NanumGothicExtraBold.ttf", 0),
    ("/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf", 0),
    ("/usr/share/fonts/truetype/nanum/NanumGothicBold.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc", 1),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Bold.ttc", 1),
    ("C:/Windows/Fonts/malgunbd.ttf", 0),
    ("/System/Library/Fonts/AppleSDGothicNeo.ttc", 0),
]
_BLACK_CANDIDATES = [
    ("fonts/NanumGothicExtraBold.ttf", 0),
    ("/usr/share/fonts/truetype/nanum/NanumGothicExtraBold.ttf", 0),
    ("/usr/share/fonts/opentype/noto/NotoSansCJK-Black.ttc", 1),
    ("/usr/share/fonts/truetype/noto/NotoSansCJK-Black.ttc", 1),
]


def _font(size, black=False):
    cands = (_BLACK_CANDIDATES + _FONT_CANDIDATES) if black else _FONT_CANDIDATES
    for path, idx in cands:
        p = Path(path) if Path(path).is_absolute() else BASE / path
        if p.exists():
            try:
                return ImageFont.truetype(str(p), size, index=idx)
            except Exception:
                continue
    return ImageFont.load_default()


# ───────────── 이미지 에셋 (있으면 사용, 없으면 직접 그린 도형으로 대체) ─────────────
def _asset(name, width):
    """assets/<name> 을 불러와 내용 영역만 잘라 width 로 키움. 없으면 None."""
    p = BASE / "assets" / name
    if not p.exists():
        return None
    im = Image.open(p).convert("RGBA")
    bg = Image.new("RGBA", im.size, "white")
    bg.alpha_composite(im)
    g = bg.convert("L")
    box = g.point(lambda v: 255 if v < 200 else 0).getbbox()
    if box:
        g = g.crop(box)
    h = round(g.height * width / g.width)
    g = g.resize((width, h), Image.LANCZOS)
    # 확대로 흐려진 가장자리를 또렷하게 (명암 대비 강화)
    g = g.point(lambda v: 0 if v < 90 else 255 if v > 170 else int((v - 90) * 255 / 80))
    return g.convert("RGB")


# ───────────── 지역 구분코드 (임의 규칙) ─────────────
def zone_label(region, address):
    """'대전 유성 07-3' 형태.
    - 시/도 : 배송 지역
    - 시/군/구 : 상세주소 첫 단어에서 '시·군·구' 제거
    - 앞 숫자(01~30) : 시/군/구 + 도로명 해시 → 같은 길이면 같은 구역
    - 뒤 숫자(1~9)   : 전체 주소 해시 → 건물/호수 단위 구분
    """
    tokens = address.split()
    district = tokens[1] if len(tokens) > 1 else ""
    short = district
    if len(district) > 2 and district[-1] in "시군구":
        short = district[:-1]
    road = tokens[2] if len(tokens) > 2 else ""
    area = hashlib.sha256(f"{district}{road}".encode()).digest()[0] % 30 + 1
    sub = hashlib.sha256(" ".join(tokens).encode()).digest()[1] % 9 + 1
    return f"{region} {short}".strip(), f"{area:02d}-{sub}"


# ───────────── 도형 도우미 ─────────────
def _lock(d, cx, cy, w, color, bg):
    """자물쇠: 중심 (cx,cy), 몸통 너비 w"""
    bh = w * 0.8
    top = cy - bh * 0.15
    sh_w = w * 0.62
    t = max(2, int(w * 0.14))
    d.arc([cx - sh_w / 2, top - bh * 0.85, cx + sh_w / 2, top + bh * 0.35],
          180, 360, fill=color, width=t)
    d.line([cx - sh_w / 2 + t / 2, top - bh * 0.25, cx - sh_w / 2 + t / 2, top + 2],
           fill=color, width=t)
    d.line([cx + sh_w / 2 - t / 2, top - bh * 0.25, cx + sh_w / 2 - t / 2, top + 2],
           fill=color, width=t)
    d.rounded_rectangle([cx - w / 2, top, cx + w / 2, top + bh], radius=w * 0.14, fill=color)
    r = w * 0.1
    d.ellipse([cx - r, top + bh * 0.3 - r, cx + r, top + bh * 0.3 + r], fill=bg)
    d.rectangle([cx - r * 0.45, top + bh * 0.3, cx + r * 0.45, top + bh * 0.68], fill=bg)


def _cube(d, cx, cy, s, color, bg, lw, lock=False, filled=False):
    """등각 상자. s = 한 변 길이(꼭짓점까지 거리)"""
    import math
    dx, dy = s * math.cos(math.radians(30)), s * 0.5
    top = [(cx, cy - s), (cx + dx, cy - dy), (cx, cy), (cx - dx, cy - dy)]
    left = [(cx - dx, cy - dy), (cx, cy), (cx, cy + s), (cx - dx, cy + dy)]
    right = [(cx, cy), (cx + dx, cy - dy), (cx + dx, cy + dy), (cx, cy + s)]
    if filled:
        d.polygon(top + [top[0]], fill=color)
        for poly in (left, right):
            d.polygon(poly, fill=color)
        d.line(top + [top[0]], fill=bg, width=lw)
        d.line([(cx, cy), (cx, cy + s)], fill=bg, width=lw)
        d.line([(cx - dx, cy - dy), (cx, cy), (cx + dx, cy - dy)], fill=bg, width=lw)
        return
    for poly in (top, left, right):
        d.polygon(poly, fill=bg)
        d.line(poly + [poly[0]], fill=color, width=lw, joint="curve")
    # 테이프
    d.line([(cx - dx * 0.5, cy - s * 0.75), (cx + dx * 0.5, cy - dy * 0.75 - 0 + 0)],
           fill=color, width=lw)
    if lock:
        _lock(d, cx + dx * 0.5, cy + s * 0.2, s * 0.42, color, bg)


def _icon_handle(d, cx, cy, k, c, bg):
    _cube(d, cx, cy - 18 * k, 34 * k, c, bg, int(5 * k), filled=True)
    # 두 손(받치는 모양)
    for sgn in (-1, 1):
        pts = [(cx + sgn * 50 * k, cy - 8 * k),
               (cx + sgn * 40 * k, cy + 38 * k),
               (cx + sgn * 8 * k, cy + 52 * k),
               (cx + sgn * 6 * k, cy + 38 * k),
               (cx + sgn * 28 * k, cy + 28 * k),
               (cx + sgn * 34 * k, cy - 4 * k)]
        d.polygon(pts, fill=c)
        d.rounded_rectangle([cx + sgn * 56 * k - 8 * k, cy + 6 * k, cx + sgn * 56 * k + 8 * k, cy + 52 * k],
                            radius=6 * k, fill=c)
    d.rounded_rectangle([cx - 56 * k, cy + 44 * k, cx + 56 * k, cy + 56 * k], radius=6 * k, fill=c)


def _icon_glass(d, cx, cy, k, c, bg):
    bowl = [(cx - 32 * k, cy - 52 * k), (cx + 32 * k, cy - 52 * k),
            (cx + 28 * k, cy - 8 * k), (cx + 8 * k, cy + 8 * k),
            (cx - 8 * k, cy + 8 * k), (cx - 28 * k, cy - 8 * k)]
    d.polygon(bowl, fill=c)
    # 깨진 틈
    d.polygon([(cx - 6 * k, cy - 52 * k), (cx + 6 * k, cy - 52 * k), (cx + 2 * k, cy - 40 * k),
               (cx + 10 * k, cy - 32 * k), (cx - 2 * k, cy - 36 * k)], fill=bg)
    d.rectangle([cx - 5 * k, cy + 6 * k, cx + 5 * k, cy + 48 * k], fill=c)
    d.rounded_rectangle([cx - 28 * k, cy + 46 * k, cx + 28 * k, cy + 56 * k], radius=4 * k, fill=c)


def _icon_umbrella(d, cx, cy, k, c, bg):
    cy = cy + 14 * k
    r = 44 * k
    d.pieslice([cx - r, cy - 40 * k - r * 0.95, cx + r, cy - 40 * k + r * 1.05], 180, 360, fill=c)
    # 살 사이 물결 모양
    y0 = cy - 40 * k + r * 0.05
    for i in range(4):
        x0 = cx - r + i * (r / 2)
        d.ellipse([x0, y0 - 7 * k, x0 + r / 2, y0 + 7 * k], fill=bg if i % 2 == 0 else bg)
    d.rectangle([cx - r - 2, y0 - 1, cx + r + 2, y0 + 1], fill=c)
    d.rectangle([cx - 3 * k, y0, cx + 3 * k, cy + 36 * k], fill=c)
    d.arc([cx - 24 * k, cy + 12 * k, cx + 0 * k, cy + 52 * k], 0, 180, fill=c, width=int(6 * k))
    d.line([(cx - 3 * k, cy + 30 * k), (cx - 3 * k, cy + 34 * k)], fill=c, width=int(6 * k))


def _icon_up(d, cx, cy, k, c, bg):
    for sgn in (-1, 1):
        x = cx + sgn * 22 * k
        d.polygon([(x, cy - 56 * k), (x - 20 * k, cy - 26 * k), (x + 20 * k, cy - 26 * k)], fill=c)
        d.rectangle([x - 6 * k, cy - 30 * k, x + 6 * k, cy + 30 * k], fill=c)
    d.rectangle([cx - 46 * k, cy + 42 * k, cx + 46 * k, cy + 54 * k], fill=c)


# ───────────── 메인: 라벨 생성 ─────────────
def make_label(order, qr_url, phone="010-123-4567", center="1516-1718"):
    S = 2  # 슈퍼샘플링 배율
    W, H = 1122, 1400
    img = Image.new("RGB", (W * S, H * S), "white")
    d = ImageDraw.Draw(img)
    BK, GR = (0, 0, 0), (96, 96, 96)

    def P(v):  # 좌표 스케일
        return v * S

    def text(xy, s, size, anchor="la", fill=BK, black=False):
        d.text((P(xy[0]), P(xy[1])), s, font=_font(P(size), black), fill=fill, anchor=anchor)

    # 테두리
    d.rounded_rectangle([P(22), P(22), P(1100), P(1358)], radius=P(42), outline=BK, width=P(5))

    # ── 로고 ──
    logo = _asset("Logo.png", P(800))
    if logo:
        img.paste(logo, (P(165), P(62)))
    else:
        lf = _font(P(108), True)
        x = P(150)
        base = P(166)
        for ch in "QRL":
            d.text((x, base), ch, font=lf, fill=BK, anchor="ls")
            x += d.textlength(ch, font=lf) + P(2)
        # 자물쇠 O
        ocx, ocy, orad = x + P(36), P(124), P(38)
        d.ellipse([ocx - orad, ocy - orad, ocx + orad, ocy + orad], outline=BK, width=P(13))
        _lock(d, ocx, ocy + P(3), P(26), BK, "white")
        x = ocx + orad + P(4)
        for ch in "CK":
            d.text((x, base), ch, font=lf, fill=BK, anchor="ls")
            x += d.textlength(ch, font=lf) + P(2)
        text((668, 112), "택배", 70, black=True)

        # 상자 아이콘 + 반짝임
        _cube(d, P(898), P(135), P(62), BK, "white", P(6), lock=True)
        for (x1, y1, x2, y2) in [(818, 76, 832, 88), (836, 56, 842, 70), (856, 52, 858, 64)]:
            d.line([(P(x1), P(y1)), (P(x2), P(y2))], fill=BK, width=P(4))

    # ── 구역 코드 ──
    area_txt, code = zone_label(order["region"], order["address"])
    cf = _font(P(96), True)
    af = _font(P(66), True)
    right = P(1030)
    cw = d.textlength(code, font=cf)
    d.text((right, P(318)), code, font=cf, fill=BK, anchor="rs")
    d.text((right - cw - P(22), P(316)), area_txt, font=af, fill=BK, anchor="rs")

    # ── QR + 모서리 ──
    qr = qrcode.QRCode(border=0, box_size=10, error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(qr_url)
    qr.make(fit=True)
    qimg = qr.make_image(fill_color="black", back_color="white").convert("RGB")
    qsz = P(432)
    qimg = qimg.resize((qsz, qsz), Image.NEAREST)
    img.paste(qimg, (P(345), P(400)))
    bx1, by1, bx2, by2, ln, rr = P(300), P(360), P(822), P(858), P(70), P(22)
    w = P(5)
    for (cx_, cy_, sx, sy) in [(bx1, by1, 1, 1), (bx2, by1, -1, 1), (bx1, by2, 1, -1), (bx2, by2, -1, -1)]:
        d.line([(cx_ + sx * rr, cy_), (cx_ + sx * ln, cy_)], fill=BK, width=w)
        d.line([(cx_, cy_ + sy * rr), (cx_, cy_ + sy * ln)], fill=BK, width=w)
        ax0, ax1 = sorted([cx_, cx_ + sx * 2 * rr])
        ay0, ay1 = sorted([cy_, cy_ + sy * 2 * rr])
        start = {(1, 1): 180, (-1, 1): 270, (1, -1): 90, (-1, -1): 0}[(sx, sy)]
        d.arc([ax0, ay0, ax1, ay1], start, start + 90, fill=BK, width=w)

    # ── 연락처 ──
    for cy_, label in [(928, f"구매자 안심번호: {phone}"), (998, f"고객 센터 번호: {center}")]:
        d.ellipse([P(80), P(cy_ - 9), P(98), P(cy_ + 9)], fill=BK)
        text((118, cy_), label, 48, anchor="lm")

    # ── 취급 아이콘 4개 (구분선 포함 이미지) ──
    icons = _asset("Icons.png", P(908))
    if icons:
        img.paste(icons, (P(107), P(1047)))
        d.line([(P(107), P(1047)), (P(1015), P(1047))], fill=(150, 150, 150), width=P(2))
    else:
        d.line([(P(107), P(1047)), (P(1015), P(1047))], fill=(150, 150, 150), width=P(2))

        # ── 취급 아이콘 4개 ──
        k = S * 1.0
        items = [(218, "취급주의", _icon_handle), (440, "파손주의", _icon_glass),
                 (665, "습기주의", _icon_umbrella), (892, "세워주세요", _icon_up)]
        for cx_, name, fn in items:
            fn(d, P(cx_), P(1118), k, BK, "white")
            text((cx_, 1213), name, 38, anchor="mm")
        for sx in (334, 556, 778):
            d.line([(P(sx), P(1062)), (P(sx), P(1243))], fill=(60, 60, 60), width=P(3))

    # ── 하단 배너 ──
    d.rounded_rectangle([P(60), P(1265), P(1062), P(1330)], radius=P(18), fill=GR)
    text((561, 1298), "배송 관계자 · 구매자 전용 / 개인정보는 표시되지 않습니다", 36,
         anchor="mm", fill="white")

    img = img.resize((W, H), Image.LANCZOS)
    buf = BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
