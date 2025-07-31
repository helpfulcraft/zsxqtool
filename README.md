# 知识星球内容总管 (ZSXQ Content Manager)

[![Python](https://img.shields.io/badge/Python-3.9%2B-blue.svg)](https://www.python.org/downloads/) [![Qt](https://img.shields.io/badge/Qt-PySide6-green.svg)](https://www.qt.io) [![License](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

一款功能强大的知识星球内容抓取、处理、归档和浏览的桌面工具，为您提供一站式知识管理解决方案。

![GUI Screenshot](https:/github.com/helpfulcraft/zsxqtool/master/main_GUI.png)

---

## ✨ 核心功能

- **🚀 自动化抓取**: 替代手动复制粘贴，自动抓取星球内的帖子、评论、图片和附件。支持多种抓取模式（全部/精华/搜索/单帖）。
- **🧠 智能化处理**: 集成大语言模型（LLM），对抓取的内容进行自动化的标签提取、摘要生成和主题分类。
- **📦 结构化归档**: 将原始信息保存为结构化的 Markdown 文件，元数据使用 YAML Front Matter 格式存储，便于二次利用。
- **💻 本地化网站**: 将处理后的结果生成一个可交互、可搜索的本地静态网站，方便您随时离线浏览和检索。
- **🔐 数据安全**: 所有数据（包括Token）均保存在用户本地，确保您的数据安全和隐私。

## 🛠️ 技术栈

- **图形界面 (GUI)**: `PySide6` (Qt for Python)
- **核心逻辑**: `requests`, `openai`, `markdown2`, `Jinja2`
- **数据存储**: 本地文件系统 (Markdown, HTML, CSS, JS, JSON)

## 📖 工作流程

本工具的核心是一个三步走的数据处理流水线：

1.  **抓取 (Crawl)**
    - **目标**: 从知识星球 API 获取原始数据，并以结构化的方式存储为本地 Markdown 文件。
    - **过程**: 通过模拟登录，调用星球 API 进行翻页式抓取，并将帖子内容（包括图片、附件链接）转换为 Markdown 格式，同时将元数据存储在 YAML Front Matter 中。

2.  **AI 处理 (AI Process)**
    - **目标**: 利用大语言模型（LLM）对抓取的原始 Markdown 文件进行内容增强。
    - **过程**:
        - **并发处理**: 使用 `ThreadPoolExecutor` 并发读取和处理所有 `.md` 文件，提升效率。
        - **智能分析**: 将每个帖子的内容填入精心设计的提示词模板（Prompt），调用 AI 完成**生成标签 (tags)**、**生成摘要 (digest)**、**指定主题 (topic)** 三项任务，并要求返回严格的 JSON 格式。
        - **分类校正**: 为了保证分类体系的一致性，程序使用了**莱文斯坦距离 (Levenshtein distance)** 算法，将 AI 返回的主题与一个预设的官方主题列表进行模糊匹配和自动校正。
    - **输出**: AI 生成的 `tags`, `digest`, `topic` 等信息被更新回每个 `.md` 文件的 YAML Front Matter 中。

3.  **生成 HTML (Generate)**
    - **目标**: 将所有处理过的数据汇集起来，生成一个功能丰富的单页面静态网站。
    - **过程**:
        - **数据聚合**: 读取所有处理后 `.md` 文件，将它们的元数据和内容加载到内存中，并收集所有标签和主题用于生成筛选器。
        - **路径修正**: 在将 Markdown 转换为 HTML 后，通过正则表达式**修正内容中指向本地图片/附件的相对路径**，确保链接在最终的 `index.html` 中依然有效。
        - **模板渲染**: 使用 `Jinja2` 模板引擎，将所有帖子数据、标签集、主题集渲染进 `template.html`，生成最终的 `index.html`。所有数据同时也被序列化为 JSON 嵌入页面，以实现客户端的快速搜索和过滤。

## ⚠️ 注意事项

- **API 变更风险**: 本项目依赖的知识星球 API 并非官方公开的稳定接口。知识星球官方可能会在任何时候对其进行修改（例如更改 API 的 URL 地址或参数），这可能导致抓取功能失效。
- **如何应对**: 如果您发现抓取功能无法正常工作，很有可能是 API 发生了变更。届时，您可能需要手动更新代码以适配最新的 API。
- **相关文件**: API 的核心请求逻辑位于 `Qt/logic/zsxq_crawler.py` 文件中。您可以检查此文件，并根据网络请求分析的结果进行相应修改。

## �� 快速开始

### 1. 环境准备

- 确保您已安装 `Python 3.9` 或更高版本。

### 2. 安装

```bash
# 1. 克隆本项目
git clone https://github.com/helpfulcraft/zsxqtool.git

# 2. 进入项目目录
cd zsxqtool

# 3. 安装依赖
pip install -r requirements.txt
```

### 3. 配置与运行

1.  运行主程序启动图形界面：
    ```bash
    python Qt/gui/main_gui.py
    ```
2.  在GUI界面中，填入您的 **`知识星球 Access Token`** 和要抓取的 **`星球 ID`**。
3.  根据需要配置 AI 相关的 Key 和 Base URL。
4.  选择抓取模式，点击"开始抓取"按钮，即可开始您的知识管理之旅！

## 📂 项目结构

```
.
├── Qt/
│   ├── gui/                # GUI 界面代码 (main_gui.py)
│   └── logic/              # 核心业务逻辑代码 (爬虫、AI处理、HTML生成)
├── output/                 # 生成的所有数据（默认被 .gitignore 忽略）
├── templates/              # HTML 模板
├── requirements.txt        # Python 依赖列表
└── README.md               # 就是您正在看的这个文件
```

## 📄 开源许可

本项目采用 [MIT License](LICENSE) 开源许可。 
