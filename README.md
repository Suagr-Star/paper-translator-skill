# Paper Translator Skill — 论文翻译归档的 Agent Skill 方法论

> 一个让 LLM Agent（Claude Code / Cherry Studio Agent 等）**稳定、高效地把学术论文翻译成中文 docx 并自动归档**的 Skill。
> 首篇实战 3 小时 → Skill 固化后目标 1.5 小时内/篇；图表区域自动裁剪在 IEEE 双栏论文上 **21/21 全命中**。

---

## 这是什么

给它一篇 PDF/DOC 论文，它产出一份：

- **单栏中文排版**的 `.docx`（不复刻原版式，按原文行文顺序文图混排）
- 顶部带 **出处信息栏**（期刊/会议、中科院分区 + JCR/CCF 等级、发表时间、DOI）
- 顶部带 **导读区**（本文解决什么问题 + 核心创新点列表）
- **全部图表**按原位嵌入（250dpi 高清裁剪，非碎片位图）、表格转可搜索的文字表格
- 自动按学科**分类归档**到对应文件夹，新领域自动建夹

整个流程由 Agent 依据 `SKILL.md` 自主执行，四个 Python 脚本负责其中所有「确定性工作」。

## 为什么把它做成 Skill 而不是一次性的对话

第一篇论文我们用「纯对话」方式翻译，踩了很多坑：双栏文本顺序错乱、493 个碎片化的嵌入图片、
图表边界靠反复截图目检、翻译输出太长导致 JSON 组装失败……每个坑都消耗了大量时间。
第二篇开始前，我们把所有教训沉淀成 `SKILL.md` + 脚本，效果是：**图表环节从 8 次人工目检降到 1 次**。

这个仓库本身就是方法论：**LLM 的工作记忆不可靠、上下文有限，但文件系统是可靠的。
把「每次都要重新想」的东西变成「每次都直接照做」的文件，就是 Skill 的本质。**

## 方法论：六条核心原则

### 1. 流程分解为「确定性脚本」与「LLM 工作」两类，绝不混用

| 环节 | 归属 | 理由 |
|---|---|---|
| PDF 文本抽取、双栏排序 | 脚本（`extract_pdf.py`） | 规则确定，代码 100% 正确且免费 |
| 图表区域定位与裁剪 | 脚本（`prep_figs.py`） | caption 坐标 + 表格线是确定性信号 |
| docx 组装、排版 | 脚本（`build_docx.py`） | 格式化是机器的强项 |
| 通读论文、翻译、提炼导读 | LLM | 语义理解不可替代 |
| 图表完整性目检 | LLM（但只看一张联络表） | 视觉确认需要多模态，但要压缩到一次 |
| 期刊等级核实 | LLM + 网络搜索 | 事实性查询 |

**原则：LLM 不做任何「能用代码算出来」的事。** 我们曾让 LLM 目测估算图表坐标，反复 8 次；
改为脚本按 caption 推导后，LLM 只需确认一张缩略图联络表。

### 2. 嵌入位图是碎片，整页裁剪才是完整的

学术论文 PDF 里的嵌入图片经常是碎片（一篇论文能抽出 493 个小图块——matplotlib 的每个子元素
都是独立位图）。正确做法：**把整页渲染成高清位图，按「图表标题（caption）的坐标」推导区域后裁剪**。

`prep_figs.py` 的推导规则（IEEE/ACM 双栏版式实测有效）：

- **插图**：图在 caption 上方；顶边取上方 drawing 聚类的顶部
- **表格**：表在 caption 下方；底边取「表体最后一行文本 +10pt 内的最宽横线」
  （即 booktabs 的 `\bottomrule`，宽度过滤 ≥0.75 栏宽，排除图内坐标轴线）
- **图在大表正下方**（最难的边缘场景）：先推导全部表格底边并缓存，图顶边直接引用——两遍处理消除歧义
- 无法确定的场景输出 `LOW` 标记，人工目检时重点关注

### 3. 一次目检原则：所有需要人眼确认的内容，收敛到一张联络表

不要逐页目检渲染图（17 页论文 × 图片页 = 十几次截图阅读）。脚本把全部裁剪结果拼成
**一张联络表（contact sheet）**，红字标注文件名，一眼扫完 21 张图。

### 4. 长输出分片化

翻译一篇 17 页论文约 3 万字中文，单次 JSON 输出必然失败或截断。做法：
按章节写 `spec_p1.json ~ spec_p5.json` 分片（每次一个 Write 调用），参考文献放 `refs.txt`
纯文本（避免 JSON 转义地狱），最后 `merge_spec.py` 一键合并组装。

### 5. 保真策略表：不同内容用不同的表示形式

| 内容 | 处理方式 | 理由 |
|---|---|---|
| 正文插图 | 裁图嵌入 | 保真优先 |
| 大性能表（十几列×几十行） | 裁图嵌入 | 转写易错，图片可读 |
| 小数据表（≤8 列） | 转文字表格 | 可搜索、可复制 |
| 英文 prompt 模板 | 裁图 / 意译注 | 翻译反而失真 |
| 数学公式 | `note` 文本近似 + 译注 | docx 写 OMML 成本过高 |
| 参考文献 | 保留英文原文 | 学术惯例 |

### 6. 记忆双链路：Skill 文件 + Agent 长期记忆

- `SKILL.md`：完整流程与规范（每次执行任务前必读）
- Agent 长期记忆（如 Cherry Studio 的 `FACT.md`）：只存一条指针「做翻译任务前先读 skill」
  + 少量高频事实（输出路径、分类规则）

Skill 是**操作手册**，记忆是**指向手册的路标**。两者都不可少：只有记忆没有手册，每次重新发挥；
只有手册没有记忆，Agent 不知道手册的存在。

## 快速开始

依赖：Python 3.9+，`pip install pymupdf python-docx pillow`（本 skill 在 macOS 系统 Python 3.9 实测通过）。

```bash
# 1. 抽取全文（分栏感知）
python3 scripts/extract_pdf.py extract paper.pdf work_dir

# 2. 图表自动裁剪 + 联络表（一次目检）
python3 scripts/prep_figs.py auto paper.pdf work_dir 250

# 3. （目检 contact_sheet.png，如需修正）改 work_dir/crop_spec.json 后重裁
python3 scripts/prep_figs.py crop paper.pdf work_dir/crop_spec.json work_dir

# 4. Agent 阅读全文并翻译，按章写 spec_pN.json 分片 + refs.txt
#    （spec 格式见 SKILL.md「spec 分片格式」一节，含导读区字段 key_problem / key_innovations）

# 5. 合并并生成 docx
python3 scripts/merge_spec.py work_dir "输出/中文标题_来源_年份.docx"
```

把 `SKILL.md` 放入你的 Agent 的技能目录（Claude Code 为 `.claude/skills/`，Cherry Studio 为
智能体技能目录），即可让 Agent 自动按流程执行。

## 仓库结构

```
paper-translator-skill/
├── README.md            # 本文件：方法论
├── SKILL.md             # Agent 技能定义（标准 skill 格式：frontmatter + 流程 + 规范 + 质检清单）
├── scripts/
│   ├── extract_pdf.py   # PDF → 分栏全文 + captions + 嵌入图 + 整页渲染
│   ├── prep_figs.py     # 图表自动裁剪（auto / crop 两个子命令）
│   ├── build_docx.py    # JSON spec → 单栏中文 docx（信息栏 + 导读区渲染）
│   └── merge_spec.py    # 合并翻译分片 + 参考文献 → 调用 build_docx 出成品
└── demo/                # 真实论文的中间产物示例
    ├── contact_sheet.png        # 图表裁剪联络表（21 张图一次目检）
    ├── crop_spec.json           # 自动推导的裁剪坐标
    ├── spec_example.json        # 翻译 spec 结构示例（meta + 导读字段 + 各类 block）
    └── refs_example.txt         # 参考文献纯文本格式示例
```

## 实战案例

**MVEI & EmObserver**（arXiv:2607.21061，ICLR 2026 会议版扩展，视觉情感智能方向）：

| 指标 | 数值 |
|---|---|
| 原文 | 17 页 IEEE 双栏，11 万字符，13 幅插图 + 8 张表格 + 4 组公式 + 86 条参考文献 |
| 自动抽取 | 全文分栏排序正确；21 个图表 caption 全部定位 |
| 自动裁剪 | 21/21 区域命中（4 个边缘场景保守标记 LOW，实际坐标同样精确） |
| 成品 | 6.8MB docx：209 段译文 + 17 图 8 表 + 导读区 + 信息栏 |
| 图表环节耗时 | 纯对话方式 8 次目检 → Skill 方式 1 次目检 |

## 适用范围与已知限制

- ✅ IEEE/ACM 双栏 Letter 版式（推导规则为此校准）
- ⚠️ 单栏 / A4 版式：`prep_figs.py auto` 的页边距常量需按论文微调，或手写 `crop_spec.json`
- ⚠️ 扫描版 PDF（无文本层）：脚本抽取为空，需 Agent 用整页渲染图逐页识读
- ⚠️ 数学公式为文本近似排版，不还原 OMML

## License

MIT
