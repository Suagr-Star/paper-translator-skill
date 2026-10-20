---
name: paper-translator
description: 论文翻译归档。当用户给出一篇 PDF/DOC 论文，要求翻译成中文、图表嵌入、生成 docx 并按分类归档时使用。触发词：翻译论文、论文归档、翻一下这篇论文、把论文整理成 docx。覆盖 IEEE/ACM 双栏与单栏论文的全文抽取、图表高清自动裁剪、中文翻译规范、docx 单栏组装、分类归档全流程。
---

# 论文翻译归档 Skill

把一篇论文（PDF/DOC）变成一份「单栏中文、文图混排、图表完整」的 docx，归档到分类文件夹。

## 配置（使用前改这里）

- `ARCHIVE_ROOT`：归档根目录，如 `~/Documents/论文库/已翻译论文/`
- 分类规则：一分类一个子文件夹（如 `ct图像分割/`、`情感计算/`）；遇到新领域**自动新建**中文短名文件夹，无需请示
- 文件名：`中文标题_来源缩写_年份.docx`（来源如 IEEE-TMI / arXiv-ICLR2026 / CVPR）
- 同目录下若有文献管理数据库（Zotero 的 storage/、*.sqlite），**绝不可误动**

## docx 顶部三件套（每篇必填）

1. **信息栏**：中文标题、英文标题、作者与单位、收录期刊/会议、等级分区
   （中科院分区 + JCR/CCF，用 web_search 核实；预印本如实标注「暂为预印本/会议版发表于 XX」）、
   发表时间、DOI、归档说明
2. **导读区**（信息栏之下、正文之前，由 meta 的 `key_problem` / `key_innovations` 渲染）：
   - `key_problem`：本文要解决的问题，2–4 句（错配/缺口是什么，后果是什么）
   - `key_innovations`：核心创新点 3–5 条，每条「做了什么 + 关键数字/效果」
3. **正文**：单栏、按原文行文顺序文图混排，不复刻原版式

## 快速流程（约 8 步）

```bash
# 0. 建工作目录（会话工作区下）
mkdir -p paper_work && cd paper_work

# 1. 抽取全文文本（分栏感知）——读这个翻译，不要逐页目检文本
python3 <skill>/scripts/extract_pdf.py extract <论文.pdf> paper_work
#    产出: fulltext.txt(带页标记) / captions.txt / images/ / vector/ / pages/

# 2. 图表自动裁剪 + 联络表（一步到位）
python3 <skill>/scripts/prep_figs.py auto <论文.pdf> paper_work [dpi=250]
#    产出: figs/*.png / contact_sheet.png / crop_report.txt / crop_spec.json

# 3. 目检 contact_sheet.png（只看这一张图！）
#    - HIGH 通常直接可用；LOW/MEDIUM 重点核对边界
#    - 不满意的: 改 crop_spec.json 里对应坐标 -> 重裁:
#      python3 <skill>/scripts/prep_figs.py crop <论文.pdf> paper_work/crop_spec.json paper_work

# 4. 通读 fulltext.txt（分段 Read），注意排除图内文字块的干扰
# 5. web_search 核实期刊/会议与分区
# 6. 写翻译分片 spec_p1.json ~ spec_pN.json（见下节），参考文献逐行放 refs.txt
# 7. 合并 + 生成 docx（一步完成）
python3 <skill>/scripts/merge_spec.py paper_work "$ARCHIVE_ROOT/<分类>/<文件名>.docx"
# 8. 校验（见质检清单）-> report_artifacts -> 清理 pages/ images/ vector/ 中间产物
```

## 翻译规范

- **准确、合理、易懂**；长句拆短，逻辑连接词显化
- 缩写首次出现给「中文（英文全称, 缩写）」，后文直接用缩写；模型/数据集/指标名保留英文
  （U-Net、Dice、IoU、MLLM、GRPO…）
- 图表标题译为「图N / 表N」，与正文引用编号一致；表格数据原样保留，仅译表头/表注
- 英文 prompt 模板类内容：正文用 `note` block 意译，重要原文（如附录 prompt 表）整表裁图保留
- 公式：docx 写 OMML 成本过高，用 `note` block 文本近似（下标 `_{}`、求和 `Σ`），加译注
  「公式为文本近似排版」
- 参考文献：**保留英文原文**，每行一条放 `refs.txt`（避免 JSON 转义问题），merge 时自动挂
  「参考文献（保留原文）」标题
- 原文的图内文字会混入 fulltext.txt（如 Fig 内标签），翻译时识别并跳过，以裁剪图呈现

## spec 分片格式（build_docx.py 的输入）

```json
// spec_p1.json 第一个分片带 meta:
{ "meta": { "title_zh": "...", "title_en": "...", "authors": "...",
            "venue": "...", "tier": "...", "pub_date": "...", "doi": "...",
            "translated_note": "AI 翻译归档；图表取自原文...",
            "key_problem": "本文要解决的问题(2-4句)",
            "key_innovations": ["创新点1", "创新点2", "..."] },
  "blocks": [ ... ] }
// spec_p2.json.. 只含 {"blocks": [...]}
```

block 类型：`h1/h2/h3` 标题；`p` 段落（支持 `**粗**` `*斜*`，不支持 `__下划线__`）；
`image`（path 相对工作目录、caption、width_cm 默认 15）；`table`（rows 二维数组、caption、header）；
`note` 灰色小字（公式/译注/提示框）；`reference` 悬挂缩进文献条目。

分片建议：长文按章拆 3–5 片，每片一个 Write 调用，写完即合并，不要攒一个巨型 JSON。

## 图表处理策略（核心经验）

1. **正文插图一律用 prep_figs.py 裁剪，不要用嵌入位图**：论文嵌入图常是碎片
   （一篇论文可抽出一百多个小图块），整页按 caption 区域裁剪才完整，250dpi 足够清晰
2. **表格分两类**：
   - 大性能表（十几列×几十行）→ 裁图嵌入（保真、免转写出错）
   - 小数据表（≤8 列）→ 目检 pages/ 渲染图后转成中文表头 `table` block（可搜索、好读）；
     原「粗体=最优/下划线=次优」标记用 `**粗**`/`*斜*` 复现并在表注说明
3. **prep_figs.py 推导可靠性**（IEEE/ACM 双栏 Letter 版式实测 21/21 命中）：
   - Fig：caption 上方 drawing 聚类定顶边；上方紧邻大表时引用该表 bottomrule（两遍处理）
   - TABLE：表底 = 表体末行文本 +10pt 内最宽横线（≥0.75 栏宽，过滤图内轴线）
   - LOW 标记 ≠ 错误，只是该场景曾有失手案例，需重点目检
4. **非 Letter 双栏版式**（单栏/A4/扫描版）：auto 边距失效，直接目检 pages/ 渲染图后
   手写 crop_spec.json 用 crop 子命令
5. **扫描版 PDF**（无文本层）：fulltext.txt 为空 → 用 pages/ 整页渲染图逐页识读翻译

## 其他输入格式

- **.doc 老格式**：`textutil -convert docx <file.doc>`（macOS 自带）→ 解压取 `word/media/` 图 +
  python-docx/to_markdown 取文
- **.docx**：直接 unzip 取 word/media + python-docx 抽文
- **抓不到 DOI/分区**：如实标注「暂为预印本」，不要编造等级

## 效率要点（目标 1.5h 内/篇）

| 耗时大头 | 对策 |
|---|---|
| 反复目检整页渲染图定裁剪框 | prep_figs.py auto 一步完成，只目检 1 张联络表 |
| 逐页读文本 | fulltext.txt 一次通读（页标记 + 分栏排序已处理好） |
| 翻译本身 | 无法压缩，分片写、写完即合并，边写边推进 |
| 图表边界手工试错 | 推导规则已固化到 prep_figs.py，别再手推 |

## 质检清单（生成 docx 后必查）

- [ ] python-docx 重开：段落数合理、图片数 = 裁剪图数、media 无缺
- [ ] 图注编号 图1…图N / 表1…表N 连续且与正文引用一致
- [ ] 顶部信息栏齐全（期刊、分区、时间、DOI、标题、归档说明）
- [ ] 导读区在位：问题概述 + 创新点列表（key_problem / key_innovations）
- [ ] 抽查 2–3 段译文与公式 note
- [ ] 文件落盘到正确分类文件夹 → report_artifacts → 清理 pages/images/vector 中间产物

## 已归档论文（Agent 本地维护）

在 Agent 长期记忆中维护已归档清单（分类、文件名、当时的特殊处理）。
新论文动手前先检索，避免分类重复建夹、文件重名。
