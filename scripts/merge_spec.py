#!/usr/bin/env python3
"""合并翻译分片: spec_p*.json (数字升序) + refs.txt -> spec_full.json -> 调 build_docx.py 生成 docx。

用法:
  python3 merge_spec.py <工作目录> <输出.docx>
工作目录需含:
  spec_p1.json ... spec_pN.json   翻译分片(第一个含 meta 字段; blocks 依文件名顺序拼接)
  refs.txt                        参考文献每行一条(可无; 有则加「参考文献(保留原文)」标题)
"""
import glob
import json
import os
import sys


def main(work_dir, out_docx):
    parts = sorted(glob.glob(os.path.join(work_dir, "spec_p*.json")),
                   key=lambda p: int("".join(filter(str.isdigit, os.path.basename(p)))))
    if not parts:
        sys.exit("未找到 spec_p*.json")
    full = {"meta": {}, "blocks": []}
    for p in parts:
        part = json.load(open(p, encoding="utf-8"))
        if "meta" in part:
            full["meta"] = part["meta"]
        full["blocks"].extend(part["blocks"])
    refs = os.path.join(work_dir, "refs.txt")
    if os.path.exists(refs):
        full["blocks"].append({"type": "h1", "text": "参考文献（保留原文）"})
        for line in open(refs, encoding="utf-8"):
            line = line.strip()
            if line:
                full["blocks"].append({"type": "reference", "text": line})
    spec_path = os.path.join(work_dir, "spec_full.json")
    json.dump(full, open(spec_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"合并完成: meta={'有' if full['meta'] else '缺失!'} blocks={len(full['blocks'])}")
    builder = os.path.join(os.path.dirname(os.path.abspath(__file__)), "build_docx.py")
    os.system(f'python3 "{builder}" "{spec_path}" "{out_docx}"')


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
