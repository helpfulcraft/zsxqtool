# IMP-001: 知识星球内容总管实现指南

> **摘要**: 本文档是 `RFC-001` 的配套实现文档，旨在为开发者提供该项目的关键代码模块、函数、数据结构和工作流程的详细技术说明。

## 1. 项目结构与环境设置

### 1.1. 目录结构

```
Qt/
├── gui/
│   └── main_gui.py           # PySide6 GUI主程序
├── logic/
│   ├── zsxq_crawler.py       # 核心逻辑：爬虫
│   ├── process_with_ai.py    # 核心逻辑：AI处理
│   ├── build_html.py         # 核心逻辑：HTML生成
│   ├── template.html         # Jinja2 网站模板
│   ├── style.css             # 网站样式表
│   └── app.js                # 网站交互脚本
├── output/                     # 数据输出目录（自动生成）
│   ├── [GroupID]-[Timestamp]-raw/   # 原始抓取数据
│   │   ├── [topic_id].md
│   │   └── [topic_id]/
│   │       ├── image.png
│   │       └── file.zip
│   ├── [GroupID]-[Timestamp]-processed/ # AI处理后数据
│   └── [GroupID]-[Timestamp]-web/       # 生成的静态网站
...
```

### 1.2. 环境依赖

项目主要依赖以下Python包。建议使用虚拟环境进行管理。

```
pip install -r requirements.txt
```

**`requirements.txt` 内容建议:**
```txt
PySide6
requests
beautifulsoup4
openai
markdown2
Jinja2
python-frontmatter
```

## 2. 关键模块实现详解 (`logic/`)

### 2.1. `zsxq_crawler.py` - 爬虫模块

该模块负责从知识星球API获取原始帖子数据。

- **入口函数**: `run_crawler(crawl_mode, group_id, token, ...)`
  - 此函数是所有抓取任务的起点。它根据GUI传入的 `crawl_mode`（全部、精华、关键词、单帖）构建不同的API URL，并循环调用 `get_data` 以处理翻页，直到没有更多内容为止。
  - **关键实现**:
    ```python
    # 根据抓取模式构建基础URL
    if crawl_mode == '关键词搜索':
        url = f"https://api.zsxq.com/v2/search/topics?group_id={group_id}&keyword={encoded_keyword}&count=20"
    elif crawl_mode == '单个帖子':
        # 单个帖子的URL在 get_data 中特殊处理
        url = f"https://api.zsxq.com/v2/topics/{post_id}" 
    else: # 全部或精华
        url = f"https://api.zsxq.com/v2/groups/{group_id}/topics?count=20"
        if crawl_mode == '仅精华':
            url += "&scope=digests"

    # 循环翻页逻辑
    while url:
        # get_data 返回下一页的URL，或在结束时返回None
        url = get_data(url, output_dir, log_callback, token, is_single_post)
    ```

- **核心函数**: `get_data(url, output_dir, ...)`
  - 负责执行单次API请求、解析响应、处理帖子并返回下一页的URL。
  - **鲁棒性**: 包含了针对网络错误（`requests.exceptions.RequestException`）、JSON解析错误和API返回特定错误码（如`1059`）的重试逻辑。
  - **内容解析**: `handle_link_to_md(text)` 是一个关键的辅助函数，它使用 `BeautifulSoup` 将知识星球特有的富文本格式（如 `<e type="web" ...>`, `<e type="mention" ...>`）转换为标准的Markdown语法，增强了内容的可读性和后续处理的兼容性。
  - **数据存储**: 使用 `frontmatter.Post` 对象来构建包含YAML元数据和Markdown内容的帖子。元数据包括`topic_id`, `author`, `create_time`等，正文则是解析后的Markdown。
    ```python
    post = frontmatter.Post("")
    post.metadata = { 'topic_id': ..., 'author': ... }
    post.content = "..."
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(frontmatter.dumps(post, allow_unicode=True))
    ```
  - **并发下载**: 使用 `concurrent.futures.ThreadPoolExecutor` 来并发下载帖子中的所有图片和附件，极大地缩短了抓取包含大量媒体文件的帖子的时间。

### 2.2. `process_with_ai.py` - AI处理模块

该模块负责读取原始Markdown文件，调用大语言模型进行分析，并将结果写回新的文件。

- **入口函数**: `run_ai_processing(source_folder_name, base_url, api_key, concurrency, ...)`
  - 管理整个处理流程，使用 `ThreadPoolExecutor` 并发调用 `process_single_file`，使得AI处理可以高效进行。
  - **增量处理**: `process_single_file` 内部会检查目标目录是否已存在处理好的文件，如果存在且包含AI元数据，则会跳过，避免重复请求和浪费资源。

- **核心函数**: `process_single_file(raw_filepath, ...)`
  - 负责处理单个 `.md` 文件。它加载文件，调用AI分析，然后将AI返回的 `tags`, `digest`, `topic` 添加到文件的YAML Front Matter中，并保存到 `-processed` 目录。

- **AI调用与Prompt**: `get_ai_analysis(content, ...)`
  - 构造 `openai.OpenAI` 客户端，并传入从GUI获取的 `base_url` 和 `api_key`。
  - **Prompt模板**是核心，它经过精心设计，指导AI严格按照指定的JSON格式返回结果，这是结构化数据提取的关键。
    ```python
    AI_PROMPT_TEMPLATE = """
    你是一个优秀的内容分类专家...
    请严格按照以下JSON格式返回结果...
    {{
        "tags": [...],
        "digest": "...",
        "topic": "..."
    }}
    ---
    帖子内容如下：
    {content}
    """
    prompt = AI_PROMPT_TEMPLATE.format(content=post.content, topics_list=OFFICIAL_TOPICS)
    ```
  - **鲁棒性设计**: 使用正则表达式 `re.search(r'\{.*\}', ...)` 从AI可能返回的额外文本（如"好的，这是您要的JSON："）中安全地提取JSON块，大大增强了数据解析的稳定性。

- **主题标准化**: `normalize_topic(ai_topic, ...)`
  - 这是保证数据一致性的重要手段。该函数使用 **Levenshtein编辑距离** 算法，计算AI生成的主题与预定义的官方主题列表 (`OFFICIAL_TOPICS`) 中每个主题的相似度。如果距离小于或等于一个阈值（`SIMILARITY_THRESHOLD`），则自动修正为官方主题。例如，AI返回的"技术心得"会被自动校正为"技术分享"。

### 2.3. `build_html.py` - HTML生成模块

该模块将AI处理过的数据转换为一个可交互的静态网站。

- **入口函数**: `run_html_generation(source_folder_name, ...)`
  - 协调整个构建流程，包括数据加载、HTML转换、资源路径修正和文件拷贝。

- **数据聚合与转换**:
  - 循环读取 `-processed` 目录下的所有 `.md` 文件。
  - 使用 `markdown2.markdown()` 将帖子的Markdown正文转换为HTML。
  - **路径修正**: 这是实现中最巧妙的部分之一。为了让网页能正确显示图片和附件，必须重写HTML内容中的相对路径。脚本使用正则表达式智能地将 `![...](file.png)` 转换为 `![...]([topic_id]/file.png)`，同时忽略 `http://`, `https://` 等绝对链接。
    ```python
    # 正则表达式确保只修改相对路径的Markdown链接
    content_with_paths = re.sub(
        r'(!?\[.*?\]\()((?!https?://|mailto:)[^)]+)(\))',
        rf'\g<1>{topic_id}/\g<2>\g<3>',
        post.content
    )
    ```
  - **资源拷贝**: 使用 `shutil.copytree()` 复制每个帖子的附件文件夹（从 `-raw` 目录查找），并使用 `shutil.copy()` 复制 `style.css` 和 `app.js` 到最终的 `-web` 输出目录。

- **模板渲染**:
  - 使用 `Jinja2` 加载 `template.html`。
  - **关键数据传递**: 脚本将所有帖子数据转换成的JSON字符串 `posts_json`，并将其嵌入到最终HTML的一个 `<script>` 标签中。这使得 `app.js` 可以在客户端直接访问所有数据，从而实现无需后端支持的纯前端动态过滤、排序和分页。
    ```python
    # posts_json 使得所有数据在客户端可用，为 app.js 的动态功能赋能
    posts_json = json.dumps(all_posts, ensure_ascii=False)
    
    output_html = template.render(
        posts_json=posts_json,  # 用于JS
        posts=all_posts,        # 用于Jinja2直接渲染初始页面（此版本已改为JS渲染）
        all_tags=sorted_tags,
        all_topics=sorted_topics
    )
    ```

## 3. GUI实现详解 (`gui/main_gui.py`)

GUI采用PySide6构建，是整个应用的交互中心。

- **核心设计模式**: **Worker-Thread**
  - **背景**: 爬虫、AI处理和文件IO都是耗时操作。如果在GUI主线程中执行，会导致界面冻结（"假死"）。
  - **实现**:
    1.  为每个耗时任务（抓取、AI、HTML、HTTP服务器）创建一个 `QObject` 的子类（`CrawlerWorker`, `AiWorker`, `HtmlWorker`, `ServerWorker`）。
    2.  在 `Worker` 类中定义一个 `run` 方法，该方法内调用 `logic/` 目录中对应的函数。
    3.  在 `Worker` 类中定义 `finished` 和 `log_message` 等信号 (`Signal`)，用于与主线程通信。
    4.  当用户点击按钮时（如"开始抓取"）：
        - 创建一个 `QThread` 和一个对应的 `Worker` 实例。
        - 将 `Worker` 移动到 `QThread` 中：`worker.moveToThread(thread)`。
        - **连接信号与槽**: 这是该模式的精髓。
            - `thread.started.connect(worker.run)`: 线程一旦启动，就自动执行 `run` 方法。
            - `worker.finished.connect(thread.quit)`: 任务完成后，`worker` 发出 `finished` 信号，使线程安全退出。
            - `worker.log_message.connect(self.append_log)`: `worker` 在执行过程中可以通过 `log_message` 信号将日志信息实时传递给主窗口的日志显示区。
            - `thread.finished.connect(self.on_task_finished)`: 线程退出后，主窗口可以执行一些UI更新操作（如重新启用按钮）。
        - 启动线程：`thread.start()`。

- **代码示例（启动抓取任务）**:
  ```python
  def on_start_clicked(self):
      # ... 从UI获取参数 ...
      self.set_controls_enabled(False) # 禁用所有按钮，防止重复点击
      
      self.worker_thread = QThread()
      self.crawler_worker = CrawlerWorker(...) # 用参数初始化Worker

      self.crawler_worker.moveToThread(self.worker_thread)

      # 连接信号
      self.worker_thread.started.connect(self.crawler_worker.run)
      self.crawler_worker.finished.connect(self.worker_thread.quit)
      self.crawler_worker.log_message.connect(self.append_log)
      self.worker_thread.finished.connect(self.on_task_finished)
      
      self.worker_thread.start()
  ```

- **配置持久化**: 使用 `QSettings`
  - 在 `MainWindow` 的 `closeEvent` 方法中调用 `self.save_settings()`，在 `__init__` 中调用 `self.load_settings()`。
  - 这样可以保存用户上次关闭应用时的窗口大小、位置以及输入的星球ID、Token、API密钥等信息，提升了用户体验。
  - `save_settings` 方法:
    ```python
    def save_settings(self):
        settings = QSettings("MyCompany", "ZsxqManager")
        settings.setValue("geometry", self.saveGeometry())
        settings.setValue("token", self.token_input.text())
        # ... 保存其他控件的值 ...
    ```

- **动态UI**: 界面的控件（如关键词输入框）会根据用户选择的抓取模式动态显示或隐藏，提升了界面的整洁性。

## 4. 前端实现 (`template.html`, `app.js`, `style.css`)

前端负责最终内容的展示和交互。

- **`template.html`**:
  - 使用Jinja2语法 (`{% for ... %}`) 来动态生成筛选器按钮（主题、标签等）。
  - 最关键的部分是嵌入了一个ID为 `posts-data` 的 `<script>` 标签，其类型为 `application/json`。`build_html.py` 将所有帖子数据转换成的JSON字符串就放在这里。
    ```html
    <script id="posts-data" type="application/json">
        {{ posts_json | safe }}
    </script>
    ```

- **`app.js`**:
  - **核心是纯客户端过滤和渲染逻辑**。
  - **初始化**: 页面加载时，首先通过 `JSON.parse` 读取并解析 `#posts-data` 中的JSON字符串，将其存入一个全局变量 `allPosts`。
  - **事件监听**: 为顶部的所有筛选器（主题、标签、精华、排序）和搜索框添加事件监听器。
  - **过滤函数 `filterAndRender()`**:
    1.  获取当前所有筛选条件（选中的主题、标签，输入的搜索词等）。
    2.  使用原生的 `allPosts.filter(...)` 方法，在一两毫秒内从数千条数据中筛选出所有匹配的帖子。
        - 标签过滤：`post.tags.includes(selectedTag)`
        - 主题过滤：`post.topic === selectedTopic`
        - 搜索过滤：`post.content.includes(searchTerm) || post.digest.includes(searchTerm)`
    3.  对筛选结果进行排序，然后进行分页切割。
    4.  调用 `renderPosts(paginated_posts)` 和 `renderPagination()` 函数。
  - **渲染函数 `renderPosts(posts)`**:
    1.  清空当前的帖子列表容器 (`#posts-container`)。
    2.  遍历 `posts` 数组，为每个帖子动态创建HTML元素字符串，并一次性地通过 `.innerHTML` 插入到DOM中，性能较高。

- **`style.css`**:
  - 负责网站的整体布局和美化。
  - 实现了响应式卡片式设计。
  - **支持暗黑/明亮模式切换**。通过给 `body` 添加/移除 `.dark-mode` 类，并配合相应的CSS规则，实现了主题的动态切换。切换状态会通过 `localStorage` 持久化。
  - 对筛选器、标签、代码块等元素都进行了样式定义。 