"""Authoring aid for the car sprites in index.html. Not needed to run or test the site.

    python tools/cargen.py            print a CARS entry (JS) for every car described in SPECS below
    python tools/cargen.py --sheet    render every car in index.html, in both themes, to tools/out/cars_<theme>.png

A car is described in metres (x from the rear bumper, h = height above ground): body outline, side glass, where the
panel shading changes, wheel axles. The generator rasterises that at 16 px/m into the H/B/S/D/G/O/. alphabet the page's
car engine draws. Paste the printed entry into the CARS array in index.html. After that, index.html is the source of
truth: hand-tweaked pixels there are not reflected back into SPECS, so only re-run this for a new or reworked car.
Do not draw logos, badges or lettering into a sprite.
"""
import asyncio
import math
import sys

from playwright.async_api import async_playwright

from common import OUT, open_page

GROUND = 28.0     # y edge where the tyres touch (tyre bottom row is 27, the road line is row 28)

def inside(poly, x, y):
    c = False
    n = len(poly)
    for i in range(n):
        x1, y1 = poly[i]; x2, y2 = poly[(i + 1) % n]
        if (y1 > y) != (y2 > y):
            if x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
                c = not c
    return c

def raster(poly, W, H=29):
    return {(x, y) for y in range(H) for x in range(W) if inside(poly, x + .5, y + .5)}

def build(c):
    s = c.get('s', 16.0)
    W = math.ceil(c['L'] * s)
    H = 29
    def P(pts): return [(x * s, GROUND - h * s) for x, h in pts]
    def px(x_m): return int(math.floor(x_m * s))
    def py(h_m): return int(math.floor(GROUND - h_m * s))
    body = raster(P(c['body']), W)
    g = {}
    for p in body: g[p] = None
    glass = set()
    for gp in c['glass']:
        glass |= raster(P(gp), W) & body
    belt_row = py(c['belt'])           # first row below the glass
    split_row, rock_row = py(c['split']), py(c['rock'])
    R = c['R']; Ri = int(R)
    wcx = [round(c['axles'][0] * s), round(c['axles'][1] * s)]
    wcy = 27 - Ri
    for (x, y) in body:
        if (x, y) in glass: g[(x, y)] = 'G'
        elif y >= rock_row: g[(x, y)] = 'D'
        elif y >= split_row: g[(x, y)] = 'S'
        else: g[(x, y)] = 'B'
    # roof / hood top edge highlight
    for (x, y) in list(body):
        if g[(x, y)] != 'G' and (x, y - 1) not in body: g[(x, y)] = 'H'
    # beltline under the glass
    for (x, y) in glass:
        if (x, y + 1) in body and (x, y + 1) not in glass: g[(x, y + 1)] = 'D'
    # bottom outline
    for (x, y) in list(body):
        if (x, y + 1) not in body and g[(x, y)] in 'BSH': g[(x, y)] = 'D'
    # pillars through the glass
    for xm, wpx in c.get('pillars', []):
        for (x, y) in glass:
            if px(xm) <= x < px(xm) + wpx: g[(x, y)] = 'D'
    # shoulder crease
    if 'crease' in c:
        hm, x1, x2 = c['crease']; y = py(hm)
        for x in range(px(x1), px(x2) + 1):
            if (x, y) in body and g[(x, y)] in 'BSD': g[(x, y)] = 'H'
    # custom ops (applied before arches so arches still cut them)
    def op(o):
        k = o[0]
        if k == 'px':
            _, xm, hm, ch = o; q = (px(xm), py(hm)); g[q] = ch; body.add(q)
        elif k == 'rect':
            _, xm, hm, w, h, ch = o
            for dx in range(w):
                for dy in range(h):
                    q = (px(xm) + dx, py(hm) + dy)
                    if q in body or o[-1] in 'D': g[q] = ch; body.add(q)
        elif k == 'hline':
            _, x1, x2, hm, ch = o
            for x in range(px(x1), px(x2) + 1):
                q = (x, py(hm)); g[q] = ch; body.add(q)
        elif k == 'poly':   # fill a polygon, adds to the body
            _, pts, ch = o
            for q in raster(P(pts), W): g[q] = ch; body.add(q)
        elif k == 'disc':   # filled circle (race roundel) where the body is
            _, xm, hm, r, ch = o
            cx, cy = xm * s, GROUND - hm * s
            for q in list(body):
                if math.hypot(q[0] + .5 - cx, q[1] + .5 - cy) <= r: g[q] = ch
        elif k == 'polyin':  # fill a polygon but only where the body already is
            _, pts, ch = o
            for q in raster(P(pts), W) & body: g[q] = ch
    for o in c.get('ops', []): op(o)
    # mirror (front-bottom corner of the side glass) and door handle
    if not c.get('nomirror'):
        gx = c['glass'][0][-1][0]
        for dx in range(3):
            for dy in range(2):
                q = (px(gx - 0.10) + dx, py(c['belt'] + 0.16) + dy)
                if q in body: g[q] = 'B'
    hx = c.get('handle', (c['pillars'][-1][0] + 0.2) if c.get('pillars') else c['seams'][0] + 0.2)
    for dx in range(2):
        q = (px(hx) + dx, py(c['belt'] - 0.15))
        if q in body and g[q] in 'BSH': g[q] = 'D'
    # door seams
    for xm in c.get('seams', []):
        x = px(xm)
        for y in range(belt_row + 1, rock_row):
            if (x, y) in body and g[(x, y)] in 'BSH': g[(x, y)] = 'O'
    # wheel arches
    ra = R + 1.5 + c.get('arch', 0.0)
    for cx in wcx:
        for (x, y) in list(body):
            d = math.hypot(x - cx, y - wcy)
            if d <= ra: g[(x, y)] = 'O'
        for (x, y) in list(body):
            d = math.hypot(x - cx, y - wcy)
            if ra < d <= ra + 1.1 and g[(x, y)] in 'BSH': g[(x, y)] = 'D'
        for dy, half in ((Ri - 1, Ri), (Ri, Ri - 1)):
            for dx in range(-half, half + 1):
                q = (cx + dx, wcy + dy)
                if q not in body or g[q] != 'O': g[q] = 'O'
    # lights (after arches)
    for o in c.get('lights', []):
        xm, hm, w, h, ch = o
        for dx in range(w):
            for dy in range(h):
                q = (px(xm) + dx, py(hm) + dy)
                if q in body: g[q] = ch
    for o in c.get('late', []): op(o)
    ys = [y for (x, y), v in g.items() if v]
    top = min(ys)
    rows = []
    for y in range(top, 28):
        rows.append(''.join(g.get((x, y)) or '.' for x in range(W)))
    return dict(id=c['id'], cap=c['cap'], name=c['name'], oy=top, wx=wcx, wy=wcy, wr=R, sp=c.get('sp', 5), rows=rows, W=W)

def js(c):
    d = build(c)
    sp = '' if d['sp'] == 5 else f",sp:{d['sp']}"
    hdr = f"{{id:'{d['id']}',cap:'{d['cap']}',name:'{d['name']}',oy:{d['oy']},wx:[{d['wx'][0]},{d['wx'][1]}],wy:{d['wy']},wr:{d['wr']}{sp},rows:["
    return hdr + "\n" + ",\n".join("'%s'" % r for r in d['rows']) + "\n]},"


# Cars. Metres: x from the rear bumper, h above ground. body = closed polygon (rear-bottom, up the tail, along the
# top, down the nose, back along the bottom). Keys: L length, s px per metre (16), R wheel radius in px, axles = rear and
# front axle x, glass = side window polygons, belt = height of the window sill, split/rock = heights where the body
# colour steps down, pillars = (x, width px), seams = door shut lines, ops = extra shapes, lights = (x, h, w px, h px).
def car(**k):
    k.setdefault('split', k['belt'] - 0.30)
    k.setdefault('rock', 0.27)
    k.setdefault('crease', (k['split'] + 0.05, 0.12, k['L'] - 0.12))
    return k

SPECS = [
 car(id='mk1rabbit', cap='mk1_rabbit.spr', name='VW Rabbit (Mk1)', L=3.80, R=4.6, sp=4, axles=(0.80, 3.20),
     body=[(0,0.13),(0,0.66),(0.04,0.92),(0.28,1.36),(0.42,1.41),(2.00,1.41),(2.60,0.97),(3.48,0.88),(3.74,0.82),(3.80,0.66),(3.80,0.13)],
     glass=[[(0.26,1.01),(0.47,1.29),(1.99,1.29),(2.50,1.01)]], belt=1.00,
     pillars=[(0.88,1),(1.50,2)], seams=[1.5,2.55],
     ops=[('polyin',[(0,0.30),(0.14,0.30),(0.14,0.56),(0,0.56)],'D'),('polyin',[(3.64,0.30),(3.80,0.30),(3.80,0.56),(3.64,0.56)],'D')],
     lights=[(3.52,0.76,3,2,'H'),(0.0,0.82,1,3,'H')]),

 car(id='mk1truck', cap='mk1_rabbit_truck.spr', name='VW Rabbit Truck (Mk1)', L=4.36, R=4.6, sp=4, axles=(1.00, 3.625),
     body=[(0,0.13),(0,0.97),(1.42,0.97),(1.50,1.00),(1.56,1.36),(1.68,1.41),(2.55,1.41),(3.15,0.97),(4.20,0.86),(4.30,0.82),(4.36,0.66),(4.36,0.13)],
     glass=[[(1.64,1.02),(1.72,1.29),(2.52,1.29),(3.02,1.01)]], belt=1.00,
     seams=[0.14, 3.05], pillars=[],
     ops=[('hline',0.10,1.40,0.90,'D'),('polyin',[(4.20,0.30),(4.36,0.30),(4.36,0.56),(4.20,0.56)],'D')],
     lights=[(4.08,0.76,3,2,'H'),(0.0,0.76,1,3,'H')]),

 car(id='mk3gti', cap='mk3_gti.spr', name='VW Golf GTI (Mk3)', L=4.02, R=4.9, axles=(0.715, 3.19),
     body=[(0,0.13),(0,0.72),(0.04,0.88),(0.18,1.06),(0.50,1.31),(0.85,1.385),(1.5,1.395),(2.0,1.385),(2.75,0.97),(3.70,0.85),(3.90,0.79),(4.02,0.66),(4.02,0.13)],
     glass=[[(0.34,1.02),(0.70,1.29),(1.98,1.29),(2.52,1.01)]], belt=1.00,
     pillars=[(1.02,1),(1.56,2)], seams=[1.56,2.5],
     lights=[(3.66,0.74,3,2,'H'),(0.0,0.80,1,3,'H')]),

 car(id='mk3jetta', cap='mk3_jetta.spr', name='VW Jetta (Mk3)', L=4.38, R=4.9, axles=(1.055, 3.53),
     body=[(0,0.13),(0,0.78),(0.03,0.95),(0.30,0.98),(0.85,1.00),(1.30,1.30),(1.55,1.40),(2.15,1.39),(2.95,0.97),(3.95,0.85),(4.22,0.78),(4.38,0.64),(4.38,0.13)],
     glass=[[(1.02,1.01),(1.45,1.29),(2.15,1.29),(2.65,1.01)]], belt=1.00,
     pillars=[(1.85,2)], seams=[1.85,2.6],
     lights=[(4.0,0.74,3,2,'H'),(0.0,0.84,1,3,'H')]),

 car(id='mk4r32', cap='mk4_r32.spr', name='VW Golf R32 (Mk4)', L=4.19, R=5.4, axles=(0.795, 3.31), rock=0.36,
     body=[(0,0.13),(0,0.80),(0.05,0.95),(0.30,1.15),(0.65,1.34),(1.0,1.42),(1.6,1.45),(2.1,1.41),(2.95,0.98),(3.95,0.87),(4.12,0.80),(4.19,0.65),(4.19,0.13)],
     glass=[[(0.42,1.07),(0.82,1.31),(1.2,1.34),(1.6,1.35),(2.08,1.32),(2.62,1.03)]], belt=1.00,
     pillars=[(1.08,1),(1.60,2)], seams=[1.6,2.55],
     lights=[(3.82,0.76,3,2,'H'),(0.0,0.84,1,3,'H')]),

 car(id='mk7wagon', cap='mk7_sportwagen.spr', name='VW Golf Sportwagen (Mk7)', L=4.56, R=5.6, axles=(1.075, 3.71),
     body=[(0,0.13),(0,0.80),(0.03,1.05),(0.20,1.38),(0.40,1.47),(0.9,1.48),(2.30,1.48),(3.02,0.99),(4.30,0.88),(4.50,0.82),(4.56,0.66),(4.56,0.13)],
     glass=[[(0.18,1.08),(0.45,1.36),(2.28,1.36),(2.90,1.03)]], belt=1.00,
     pillars=[(0.98,1),(1.62,2)], seams=[1.62,2.55],
     ops=[('hline',0.50,2.15,1.52,'S')],
     lights=[(4.2,0.74,3,2,'H'),(0.0,0.86,1,3,'H')]),

 car(id='p964', cap='964_911.spr', name='Porsche 964 911', L=4.25, R=5.1, axles=(1.15, 3.42), belt=0.96, split=0.68, rock=0.27,
     body=[(0,0.13),(0,0.60),(0,0.92),(0.18,1.0),(0.5,1.07),(0.95,1.17),(1.4,1.28),(1.75,1.31),(2.05,1.31),(2.85,0.97),(3.2,0.95),(3.7,0.94),(4.0,0.90),(4.17,0.82),(4.25,0.66),(4.25,0.13)],
     glass=[[(1.14,0.99),(1.42,1.20),(2.10,1.235),(2.66,0.96)]], pillars=[(1.55,2)], seams=[1.82,2.85],
     lights=[(3.95,0.80,3,2,'H'),(0.0,0.74,2,2,'H')]),
 car(id='p930', cap='930_flachbau.spr', name='Porsche 930 Flachbau', L=4.29, R=5.1, axles=(1.18, 3.45), belt=0.96, split=0.68, arch=0.6,
     body=[(0,0.13),(0,0.62),(0,1.08),(0.55,1.13),(0.75,1.12),(1.0,1.18),(1.45,1.27),(1.75,1.31),(2.05,1.31),(2.85,0.97),(3.40,0.89),(3.90,0.78),(4.15,0.68),(4.29,0.58),(4.29,0.13)],
     glass=[[(1.14,0.99),(1.42,1.20),(2.10,1.235),(2.66,0.96)]], pillars=[(1.55,2)], seams=[1.85,2.88],
     ops=[('hline',0.06,0.55,1.00,'D')],
     lights=[(3.95,0.70,3,2,'H'),(0.0,0.70,2,2,'H')]),
 car(id='rs2', cap='rs2_avant.spr', name='Audi RS2 Avant', L=4.52, R=5.3, axles=(1.03, 3.64), rock=0.30,
     body=[(0,0.13),(0,0.82),(0.05,1.02),(0.18,1.34),(0.30,1.41),(0.5,1.42),(2.35,1.42),(3.12,0.98),(4.28,0.87),(4.46,0.80),(4.52,0.64),(4.52,0.13)],
     glass=[[(0.22,1.05),(0.36,1.33),(2.30,1.33),(2.95,1.02)]], belt=1.00,
     pillars=[(0.80,1),(1.62,2)], seams=[1.65,2.65],
     ops=[('hline',0.45,2.20,1.46,'S')],
     lights=[(4.28,0.72,3,2,'H'),(0.0,0.88,2,3,'H')]),

 car(id='rs6', cap='rs6_avant.spr', name='Audi RS6 Avant', L=4.98, s=15.5, R=5.8, axles=(1.19, 4.10), arch=0.7, belt=1.00,
     body=[(0,0.13),(0,0.86),(0.03,1.00),(0.30,1.32),(0.70,1.44),(1.2,1.46),(2.3,1.46),(3.25,1.00),(4.75,0.90),(4.92,0.84),(4.98,0.70),(4.98,0.13)],
     glass=[[(0.46,1.08),(0.78,1.35),(2.28,1.35),(3.05,1.03)]],
     pillars=[(1.05,1),(1.78,2)], seams=[1.80,2.85],
     lights=[(4.65,0.76,3,2,'H'),(0.0,0.90,2,3,'H')]),

 car(id='gto', cap='90_quattro_imsa_gto.spr', name='Audi 90 Quattro IMSA GTO', L=4.58, R=5.6, axles=(1.07, 3.62), arch=1.0, belt=0.97, split=0.66, rock=0.26,
     body=[(0,0.15),(0,0.90),(0.02,0.96),(0.90,0.98),(1.25,1.14),(1.50,1.26),(2.05,1.28),(2.85,0.97),(3.10,0.99),(4.05,0.98),(4.30,0.88),(4.50,0.62),(4.58,0.24),(4.58,0.12)],
     glass=[[(0.98,0.99),(1.40,1.18),(2.05,1.21),(2.62,0.99)]], pillars=[(1.75,2)], seams=[1.75,2.5],
     ops=[('poly',[(0.0,1.12),(0.0,1.32),(0.60,1.34),(0.60,1.12)],'B'),('hline',0.0,0.60,1.33,'H'),('rect',0.18,1.11,2,3,'D'),
          ('disc',2.05,0.47,2.3,'H'),('px',2.05,0.47,'D')],
     lights=[(4.28,0.78,3,2,'H')]),
]


def entry(c):
    d = build(c)
    sp = '' if d['sp'] == 5 else f",sp:{d['sp']}"
    hdr = (f"{{id:'{d['id']}',cap:'{d['cap']}',name:'{d['name']}',oy:{d['oy']},wx:[{d['wx'][0]},{d['wx'][1]}],"
           f"wy:{d['wy']},wr:{d['wr']}{sp},rows:[")
    return hdr + "\n" + ",\n".join("'%s'" % r for r in d['rows']) + "\n]},"


async def sheet():
    """One image per theme with every car as drawn by the page itself, six times life size."""
    async with async_playwright() as pw:
        browser = await pw.chromium.launch()
        for theme in ("green", "color"):
            tiles = []
            for cid in ["mk7golf"] + [c["id"] for c in SPECS]:
                ctx, pg, errs = await open_page(browser, car=cid)
                if theme == "color":
                    await pg.click('#phos button[data-p="color"]')
                png = await pg.evaluate("document.getElementById('car').toDataURL()")
                scr = await pg.evaluate("getComputedStyle(document.documentElement).getPropertyValue('--screen').trim()")
                cap = await pg.evaluate("document.querySelector('.cap').textContent")
                tiles.append((cid, cap, png, scr))
                await ctx.close()
            cells = "".join(f'<figure><img src="{png}"><figcaption>{cid} - {cap}</figcaption></figure>' for cid, cap, png, _ in tiles)
            html = (f'<body style="margin:0;background:#111;color:#ccc;font:12px monospace"><style>'
                    f'main{{display:grid;grid-template-columns:repeat(2,648px)}}figure{{margin:0}}'
                    f'img{{display:block;width:648px;height:204px;image-rendering:pixelated;background:{tiles[0][3]}}}'
                    f'figcaption{{padding:3px 6px}}</style><main>{cells}</main>')
            pg = await browser.new_page(viewport={"width": 1296, "height": 800})
            await pg.set_content(html)
            await pg.wait_for_timeout(200)
            path = OUT / f"cars_{theme}.png"
            await pg.screenshot(path=str(path), full_page=True)
            print(path)
            await pg.close()
        await browser.close()


if __name__ == '__main__':
    if '--sheet' in sys.argv:
        asyncio.run(sheet())
    else:
        print("\n".join(entry(c) for c in SPECS))
