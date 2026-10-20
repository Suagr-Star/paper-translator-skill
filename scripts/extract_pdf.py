#!/usr/bin/env python3
"""论文 PDF 抽取器：提取分栏文本、嵌入图片、页面渲染图，供翻译与 docx 组装使用。

用法:
  python3 extract_pdf.py extract <input.pdf> <out_dir>   # 抽取全部内容
  python3 extract_pdf.py region  <input.pdf> <out.png> <x0> <y0> <x1> <y1> [dpi]  # 裁剪渲染某区域(矢量图/表格用)

输出 (out_dir 下):
  fulltext.txt        全文文本，带页码标记，分栏感知排序
  captions.txt        检测到的图表标题行 (Fig./Figure/Table/图/表)
  images/img_pNNN_kNNN_WxH.png   嵌入位图 (按 xref 去重)
  vector/vector_pNNN_kNNN.png    矢量图形聚类裁剪 (面积过滤后的候选)
  pages/page_NNN.png  每页整页渲染图 (150dpi, 供人工/AI 查看排版)
"""
import os
import re
import sys

import fitz  # PyMuPDF

CAPTION_RE = re.compile(
    r"^\s*(Fig(ure)?s?\.?\s*\d+|Table\s*\d+|图\s*\d+|表\s*\d+)", re.IGNORECASE
)


def looks_two_column(page, blocks):
    """启发式: 判断页面是否双栏。"""
    text_blocks = [b for b in blocks if b[6] == 0 and b[4].strip()]
    if len(text_blocks) < 6:
        return False
    w = page.rect.width
    mid = w / 2
    left = [b for b in text_blocks if b[2] <= mid + w * 0.05]
    right = [b for b in text_blocks if b[0] >= mid - w * 0.05]
    if len(left) < 3 or len(right) < 3:
        return False
    # 左右块在垂直方向上需要有交叠(排除上下堆叠的版式)
    l_top = min(b[1] for b in left)
    r_top = min(b[1] for b in right)
    l_bot = max(b[3] for b in left)
    r_bot = max(b[3] for b in right)
    return min(l_bot, r_bot) - max(l_top, r_top) > page.rect.height * 0.3


def sorted_blocks(page):
    blocks = page.get_text("blocks")
    if looks_two_column(page, blocks):
        mid = page.rect.width / 2
        text = [b for b in blocks if b[6] == 0]
        other = [b for b in blocks if b[6] != 0]
        left = sorted([b for b in text if b[2] <= mid + page.rect.width * 0.05], key=lambda b: (b[1], b[0]))
        right = sorted([b for b in text if b[2] > mid + page.rect.width * 0.05], key=lambda b: (b[1], b[0]))
        return left + right + other
    return sorted(blocks, key=lambda b: (b[1], b[0]))


def extract(input_pdf, out_dir):
    doc = fitz.open(input_pdf)
    os.makedirs(os.path.join(out_dir, "images"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "vector"), exist_ok=True)
    os.makedirs(os.path.join(out_dir, "pages"), exist_ok=True)

    fulltext = []
    captions = []
    seen_xrefs = set()
    n_vec = 0

    for pno, page in enumerate(doc):
        page_no = pno + 1
        # --- 文本 ---
        text_parts = []
        for b in sorted_blocks(page):
            txt = b[4].strip()
            if not txt:
                continue
            text_parts.append(txt)
            for line in txt.splitlines():
                if CAPTION_RE.match(line):
                    captions.append(f"p{page_no}: {line.strip()}")
        fulltext.append(f"\n===== 第 {page_no} 页 =====\n" + "\n".join(text_parts))

        # --- 整页渲染 (供查看) ---
        pix = page.get_pixmap(dpi=150)
        pix.save(os.path.join(out_dir, "pages", f"page_{page_no:03d}.png"))

        # --- 嵌入位图 ---
        img_idx = 0
        for info in page.get_images(full=True):
            xref = info[0]
            if xref in seen_xrefs:
                continue
            seen_xrefs.add(xref)
            try:
                pix = fitz.Pixmap(doc, xref)
                if pix.colorspace and pix.colorspace.n > 3:
                    pix = fitz.Pixmap(fitz.csRGB, pix)
                w, h = pix.width, pix.height
                if w * h < 10000:  # 过滤图标/装饰
                    continue
                name = f"img_p{page_no:03d}_k{img_idx:02d}_{w}x{h}.png"
                pix.save(os.path.join(out_dir, "images", name))
                img_idx += 1
            except Exception as e:  # CMYK/JBIG2 等无法直接解码的交给整页渲染兜底
                print(f"[warn] xref {xref} p{page_no} 解码失败: {e}")

        # --- 矢量图形聚类 (候选插图, 需人工确认) ---
        try:
            clusters = page.cluster_drawings()
        except Exception:
            clusters = []
        k = 0
        for rect in clusters:
            if rect.width < 80 or rect.height < 60:
                continue
            if rect.width * rect.height < page.rect.width * page.rect.height * 0.02:
                continue
            k += 1
            n_vec += 1
            pix = page.get_pixmap(dpi=200, clip=rect)
            pix.save(os.path.join(out_dir, "vector", f"vector_p{page_no:03d}_k{k:02d}.png"))

    with open(os.path.join(out_dir, "fulltext.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(fulltext))
    with open(os.path.join(out_dir, "captions.txt"), "w", encoding="utf-8") as f:
        f.write("\n".join(captions))

    print(f"页数: {len(doc)}")
    print(f"嵌入图片: {len(os.listdir(os.path.join(out_dir, 'images')))}")
    print(f"矢量候选: {n_vec}")
    print(f"图表标题行: {len(captions)}")
    print(f"输出目录: {out_dir}")


def render_region(input_pdf, out_png, x0, y0, x1, y1, dpi=200, page_no=1):
    doc = fitz.open(input_pdf)
    page = doc[page_no - 1]
    pix = page.get_pixmap(dpi=dpi, clip=fitz.Rect(x0, y0, x1, y1))
    pix.save(out_png)
    print(f"已保存 {out_png}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    cmd = sys.argv[1]
    if cmd == "extract":
        extract(sys.argv[2], sys.argv[3])
    elif cmd == "region":
        dpi = int(sys.argv[9]) if len(sys.argv) > 9 else 200
        render_region(sys.argv[2], sys.argv[3], *[float(v) for v in sys.argv[4:8]], dpi=dpi)
    else:
        print(__doc__)
        sys.exit(1)
