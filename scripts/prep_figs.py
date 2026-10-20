#!/usr/bin/env python3
"""图表自动裁剪器：定位图表标题(caption) -> 推导裁剪框 -> 高清裁剪 -> 生成联络表供一次目检。

用法:
  python3 prep_figs.py auto <input.pdf> <out_dir> [dpi]   # 自动定位并裁剪(推荐第一步)
  python3 prep_figs.py crop <input.pdf> <spec.json> <out_dir> [dpi]  # 按坐标重裁(目检修正用)

auto 输出:
  figs/figNN.png / tabNN.png   裁剪结果
  contact_sheet.png            联络表(一次目检全部图)
  crop_report.txt              每张图的推导坐标与置信度(LOW/MEDIUM 需重点目检)
  crop_spec.json               坐标表(可直接编辑后用 crop 重裁)

crop 的 spec.json 格式: {"fig01": [page, x0, y0, x1, y1], ...}  (1-based 页码, pt 坐标)

推导规则(IEEE/ACM 双栏 Letter 版式实测有效, 非此版式请直接用 crop 手工指定):
  - Fig: 图在 caption 上方。caption 跨页宽>55% => 跨栏图[左右页边距]; 否则按 caption 所在栏取整栏。
         顶边取 caption 上方同栏内最近 drawing 聚类顶部; 无聚类则页顶(56)。
  - TABLE: 表在 caption 下方。底边取紧贴 caption 的表格线聚类底部+2(无框线表退化为文本块法)。
已知盲区(报告自动标记 LOW): 图/表紧邻另一张大表时聚类可能并入表格线, 目检联络表后用 crop 修正。
"""
import json
import os
import re
import sys

import fitz
from PIL import Image, ImageDraw

TOP_MARGIN = 56     # 正文区顶(避开页眉)
BOTTOM_MARGIN = 736
LEFT_MARGIN = 49
RIGHT_MARGIN = 564
MID = 306
CAPTION_RE = re.compile(r"^(Fig\.\s*\d+\.|TABLE\s+[IVX]+)")


def find_captions(page):
    caps = []
    for b in page.get_text("blocks"):
        m = CAPTION_RE.match(b[4].strip())
        if m:
            caps.append({"rect": fitz.Rect(b[:4]), "kind": "fig" if m.group(1).startswith("Fig") else "table",
                         "label": m.group(1)})
    caps.sort(key=lambda c: (c["rect"].y0, c["rect"].x0))
    return caps


def col_range(x0, x1):
    """按 caption 中心判断所属栏, 返回整栏横向范围。"""
    center = (x0 + x1) / 2
    return (LEFT_MARGIN, 300) if center < MID else (312, RIGHT_MARGIN)


def clusters(page):
    try:
        return page.cluster_drawings()
    except Exception:
        return []


def h_rules(page):
    """页面上的水平线段(表格框线/横线), 返回 fitz.Rect 列表(高<3, 宽>60)。"""
    out = []
    for d in page.get_drawings():
        r = d["rect"]
        if r.height < 3 and r.width > 60:
            out.append(r)
    return out


def nearest_h_rule_below(page, y_from, cx0, cx1, y_limit, min_w_frac=0.75):
    """caption 下方同栏内最靠下的宽横线 y1(表格 bottomrule; 宽度过滤排除图内轴线)。"""
    best = None
    min_w = min_w_frac * (cx1 - cx0)
    for r in h_rules(page):
        if r.y1 > y_from + 2 and r.y1 < y_limit and r.x1 > cx0 and r.x0 < cx1 and r.width >= min_w:
            if best is None or r.y1 > best:
                best = r.y1
    return best


def nearest_h_rule_above(page, y_to, cx0, cx1, y_limit, min_w_frac=0.0):
    """caption 上方同栏内最靠下的横线 y1(min_w_frac 过滤窄线, 如图内轴线)。"""
    best = None
    min_w = min_w_frac * (cx1 - cx0)
    for r in h_rules(page):
        if r.y1 < y_to - 2 and r.y1 > y_limit and r.x1 > cx0 and r.x0 < cx1 and r.width >= min_w:
            if best is None or r.y1 > best:
                best = r.y1
    return best


def text_bottom_below(page, y_from, cx0, cx1, y_limit):
    """caption 下方同栏内文本块的最大 y1(即表体最后一行的底部)。"""
    best = None
    for b in page.get_text("blocks"):
        if b[6] != 0:
            continue
        br = fitz.Rect(b[:4])
        if br.y0 > y_from and br.y1 < y_limit and br.x1 > cx0 and br.x0 < cx1:
            if best is None or br.y1 > best:
                best = br.y1
    return best


def derive_crop(page, cap, caps, cls, table_bottoms=None):
    r = cap["rect"]
    W = page.rect.width
    cross = (r.x1 - r.x0) > 0.55 * (RIGHT_MARGIN - LEFT_MARGIN)
    confidence = "HIGH"
    if cap["kind"] == "fig":
        cx0, cx1 = (LEFT_MARGIN, RIGHT_MARGIN) if cross else col_range(r.x0, r.x1)
        cy1 = r.y0 - 2
        cy0 = TOP_MARGIN
        best = None
        for cl in cls:
            if cl.y1 <= r.y0 + 4 and cl.y0 >= TOP_MARGIN - 6 \
               and cl.x1 > cx0 and cl.x0 < cx1 and cl.width > 60 and cl.height > 40:
                if best is None or cl.y0 < best.y0:
                    best = cl
        if best is not None:
            cy0 = best.y0 - 3
        for c in caps:  # 上方紧邻 TABLE: 查该表已推导的底边(先表后图两遍处理保证可用)
            if c is not cap and c["kind"] == "table" and c["rect"].y1 <= r.y0 \
               and c["rect"].x1 > cx0 and c["rect"].x0 < cx1 and r.y0 - c["rect"].y1 < 420:
                confidence = "LOW"
                tb_bottom = (table_bottoms or {}).get(id(c))
                if tb_bottom:
                    cy0 = max(cy0, tb_bottom + 4)
                else:
                    cy0 = max(cy0, c["rect"].y1 + 2)
        for c in caps:  # 上方紧邻另一 Fig caption
            if c is not cap and c["kind"] == "fig" and c["rect"].y1 <= r.y0 \
               and c["rect"].x1 > cx0 and c["rect"].x0 < cx1 and (r.y0 - c["rect"].y1) < 200:
                cy0 = max(cy0, c["rect"].y1 + 4)
    else:  # table: 表体在 caption 下方
        # 表注常窄而居中, 不能只看宽度: 中心贴近页面中线即视为跨栏表
        centered = abs((r.x0 + r.x1) / 2 - W / 2) < 50
        if cross or centered:
            cx0, cx1 = LEFT_MARGIN, RIGHT_MARGIN
        else:
            cx0, cx1 = col_range(r.x0, r.x1)
        cy0 = r.y1 + 2
        y_limit = BOTTOM_MARGIN - 50
        for c in caps:  # 下方另一 caption 边界
            if c is not cap and c["rect"].y0 > r.y1 and c["rect"].x1 > cx0 and c["rect"].x0 < cx1:
                y_limit = min(y_limit, c["rect"].y0 - 2)
        # 表底: 表体最后一行文本底部 +10pt 范围内最靠下的宽横线(bottomrule)
        tb = text_bottom_below(page, r.y1, cx0, cx1, y_limit)
        y_rule = nearest_h_rule_below(page, r.y1, cx0, cx1, (tb + 10) if tb else y_limit)
        if y_rule:
            cy1 = y_rule + 3
        elif tb:
            cy1 = tb + 4
        else:  # 无框线且无文本: 退化到限制边界
            cy1 = y_limit
            confidence = "MEDIUM"
    return [round(v, 1) for v in (cx0, cy0, cx1, cy1)], confidence


def make_sheet(out_dir, names, cols=5, cell=(380, 300)):
    rows = (len(names) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * cell[0], rows * cell[1]), "white")
    d = ImageDraw.Draw(sheet)
    for i, f in enumerate(names):
        img = Image.open(os.path.join(out_dir, "figs", f + ".png"))
        img.thumbnail((cell[0] - 16, cell[1] - 36))
        x, y = (i % cols) * cell[0], (i // cols) * cell[1]
        sheet.paste(img, (x + 8, y + 28))
        d.text((x + 8, y + 6), f, fill="red")
        d.rectangle([x, y, x + cell[0] - 1, y + cell[1] - 1], outline="gray")
    sheet.save(os.path.join(out_dir, "contact_sheet.png"))


def check_layout(doc):
    p = doc[0].rect
    if abs(p.width - 612) > 20 or abs(p.height - 792) > 20:
        print(f"[警告] 页面 {p.width:.0f}x{p.height:.0f} 非 Letter 双栏论文, 自动推导边距可能失效, 请目检联络表")


def auto(pdf, out_dir, dpi=250):
    os.makedirs(os.path.join(out_dir, "figs"), exist_ok=True)
    doc = fitz.open(pdf)
    check_layout(doc)
    report, spec, names = [], {}, []
    counters = {"fig": 0, "table": 0}
    # 两遍处理: 先推导全部表格底边并缓存, 图的顶边跨大表时直接引用
    page_caps = [(pno, page, find_captions(page), clusters(page)) for pno, page in enumerate(doc, 1)]
    table_bottom_cache = {}
    for pno, page, caps, cls in page_caps:
        for cap in caps:
            if cap["kind"] == "table":
                box, _ = derive_crop(page, cap, caps, cls)
                table_bottom_cache[id(cap)] = box[3]
    for pno, page, caps, cls in page_caps:
        for cap in caps:
            box, conf = derive_crop(page, cap, caps, cls, table_bottom_cache)
            if box[3] - box[1] < 8 or box[2] - box[0] < 30:  # 空框防御: 回退到整栏区域
                box = [box[0], TOP_MARGIN, box[2], BOTTOM_MARGIN if cap["kind"] == "table" else cap["rect"].y0 - 2]
                conf = "LOW"
            counters[cap["kind"]] += 1
            name = f"{'fig' if cap['kind']=='fig' else 'tab'}{counters[cap['kind']]:02d}"
            pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(*box))
            pix.save(os.path.join(out_dir, "figs", name + ".png"))
            names.append(name)
            spec[name] = [pno] + box
            report.append(f"{name}\t{cap['label']}\tp{pno}\t{box}\t{conf}")
    with open(os.path.join(out_dir, "crop_report.txt"), "w", encoding="utf-8") as f:
        f.write("name\tcaption\tpage\t[x0,y0,x1,y1]\tconfidence\n" + "\n".join(report))
    with open(os.path.join(out_dir, "crop_spec.json"), "w", encoding="utf-8") as f:
        json.dump(spec, f, indent=1)
    make_sheet(out_dir, names)
    n_low = sum(1 for r in report if "LOW" in r or "MEDIUM" in r)
    print(f"图表 {len(names)} 张 | 需重点目检: {n_low} 张(见 crop_report.txt)")
    print(f"联络表: {out_dir}/contact_sheet.png —— 目检后改 crop_spec.json 用 crop 子命令重裁")


def crop(pdf, spec_path, out_dir, dpi=250):
    os.makedirs(os.path.join(out_dir, "figs"), exist_ok=True)
    doc = fitz.open(pdf)
    spec = json.load(open(spec_path, encoding="utf-8"))
    for name, (p, x0, y0, x1, y1) in spec.items():
        pix = doc[p - 1].get_pixmap(dpi=dpi, clip=fitz.Rect(x0, y0, x1, y1))
        pix.save(os.path.join(out_dir, "figs", name + ".png"))
    make_sheet(out_dir, sorted(spec.keys()))
    print(f"重裁 {len(spec)} 张, 联络表: {out_dir}/contact_sheet.png")


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "auto":
        auto(sys.argv[2], sys.argv[3], int(sys.argv[4]) if len(sys.argv) > 4 else 250)
    elif cmd == "crop":
        crop(sys.argv[2], sys.argv[3], sys.argv[4], int(sys.argv[5]) if len(sys.argv) > 5 else 250)
    else:
        print(__doc__)
        sys.exit(1)
