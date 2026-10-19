# MathM

面向日常科研与数学建模的本地论文工作台。支持章节写作、论文审查、数据图与三线表，并提供 macOS 桌面应用构建源码。

## 功能

- **独立章节**：标题、摘要、引言、相关工作、方法、实验、结果、讨论、结论，以及数模假设、符号与模型检验。
- **LaTeX 写作**：按真实研究材料撰写或润色；模板指定区域外保持原文；没有模板时生成通用草稿外壳。
- **图片**：CSV 生成折线、柱状和散点图，导出 PNG 600dpi、PDF、SVG、原始数据及复现脚本。
- **表格**：CSV 生成 booktabs 三线表，保留原始数值。
- **字体与指令**：各功能独立设置中英文字体、字号和补充提示词。
- **任务管理**：真实步骤进度、历史记录、取消、重试、成果下载。
- **清理**：任务临时目录结束即删；异常残留超过24小时，在启动及运行中每小时清理。

## 快速启动

需要 Python 3.12（桌面打包也使用此版本）。

```bash
git clone https://github.com/Miraitowaern/mathm.git
cd mathm
python3.12 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python start.py --open
```

浏览器访问 `http://127.0.0.1:8765`。macOS 完成依赖安装后，也可双击 `start.command`。

图表和基础解析在本机执行，不需要模型。AI 写作或审查需要在 `.env` 中设置：

```dotenv
MATHM_API_KEY=your-provider-key
MATHM_BASE_URL=https://your-provider.example/v1
MATHM_MODEL=your-provider-model
```

可从 `.env.example` 复制配置。接口须兼容 `/chat/completions`；配置后重启应用。AI 仅在任务勾选确认后发送解析文字至配置的服务商，不上传原件。不要把真实密钥提交到仓库。

## 技能

源码包含项目自有的 `skills/mathm-latex-writing`，通用科研写作可直接使用。Nature / HWB 等第三方技能**不随公开源码分发**；按其来源许可取得后，可导入已有本地技能：

```bash
python scripts/import_skills.py /path/to/your/skills \
  --names nature-writing nature-polishing nature-figure nature-shared
```

导入目录默认是项目内 `skills/`，已在 Git 中忽略第三方技能。也可通过 `MATHM_SKILLS_DIR` 指向自己的技能根目录，但该目录需同时包含 `mathm-latex-writing`。Nature 风格和章节规则在导入后启用；未导入时请选择“通用学术写作”。HWB 读题与 AI 审查需要对应 `hwb-*` 技能。来源与依赖说明见 [技能文档](docs/skills.md)。

## 使用说明

- [论文写作、图表、字体及提示词](docs/论文写作使用说明.md)
- [macOS 桌面构建](docs/desktop.md)

自定义模板在 `document` 环境内放置 `% MATHM_BODY_START` 与 `% MATHM_BODY_END` 标记；应用只替换标记之间的内容。

LaTeX 正文和表格暂不自动编译。字体、页边距、页数与正式投稿格式需在可信 XeLaTeX / Overleaf 环境核验。模型不会代替真实实验，不应把生成成功视为论文正确。

## 测试

```bash
python -m unittest discover -s tests -v
```

单元测试使用模拟模型响应，不需要密钥和真实第三方技能。图表测试会实际生成图片；缺少可选 Nature 审查工具时明确标记审查未执行。测试不代表真实模型论文质量已验证。

## 项目结构

```text
app.py                  本机 HTTP 服务、上传与任务存储
writing.py              LaTeX 写作与项目打包
studio.py               章节、语言、风格规则路由
assets.py               本地图片与表格任务
typography.py           字体校验与支持的图表指令
figure_renderer.py      固定、可复现绘图程序
static/                 页面、交互与样式
desktop/                Swift 原生外壳与桌面构建器
skills/                 项目自有技能及可选导入技能
scripts/                本地技能导入工具
tests/                  自动化测试
```

## 数据与范围

网页模式的数据默认保存在项目 `data/`；桌面版数据在当前用户的 `Library/Application Support/MathM/`。源码不包含用户上传材料、数据库、密钥、历史报告、运行时环境或已打包 `.app`。

上传文件不会作为程序执行；图表只运行仓库固定绘图代码。当前 CSV 项目资源需为单层文件；不支持 ZIP 模板、扫描 PDF OCR、自动数值复算或 AI 机制示意图。本工具绑定本机回环地址，未设计为公网服务。
