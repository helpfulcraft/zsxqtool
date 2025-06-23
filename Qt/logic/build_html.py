import os
import frontmatter
import markdown2
import json
import shutil
import re
from jinja2 import Environment, FileSystemLoader

# --- 路径配置 (将被动态化) ---
LOGIC_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.dirname(LOGIC_DIR)
TEMPLATE_DIR = LOGIC_DIR
TEMPLATE_NAME = 'template.html'

def run_html_generation(source_folder_name: str, log_callback=print):
    """
    读取指定目录中的所有处理过的Markdown文件，并使用模板生成最终的静态网站。
    source_folder_name: 例如 'processed_md' 或 'processed_md_digests'
    """
    log_callback(f"开始为数据集 '{source_folder_name}' 构建Web可视化页面...")

    # --- 动态路径构建 ---
    processed_md_dir = os.path.join(PROJECT_ROOT, 'output', source_folder_name)
    
    # --- 核心修复：构建原始附件的路径 ---
    # 附件总是存在于 "raw_" 目录中，而不是 "processed_" 目录
    raw_folder_name = source_folder_name.replace('processed_', 'raw_')
    raw_md_dir = os.path.join(PROJECT_ROOT, 'output', raw_folder_name)

    web_output_folder_name = source_folder_name.replace('processed_', 'web_')
    web_output_dir = os.path.join(PROJECT_ROOT, 'output', web_output_folder_name)
    
    # 1. 确保目录存在
    if not os.path.exists(processed_md_dir):
        log_callback(f"错误：找不到已处理的Markdown文件目录 '{processed_md_dir}'。请先运行AI处理步骤。")
        return
    if not os.path.exists(web_output_dir):
        os.makedirs(web_output_dir)
        log_callback(f"创建输出目录: {web_output_dir}")

    # 2. 加载所有处理过的帖子数据
    all_posts = []
    all_tags = set()
    all_topics = set()
    log_callback(f"正在从 '{processed_md_dir}' 加载数据...")

    filenames = sorted(os.listdir(processed_md_dir), reverse=True)
    if not filenames:
        log_callback("警告：已处理目录中没有找到任何 .md 文件。")
        return
        
    for filename in filenames:
        if filename.endswith('.md'):
            filepath = os.path.join(processed_md_dir, filename)
            try:
                post = frontmatter.load(filepath)
                
                # --- 核心修改：处理内容中的相对路径并复制资源 ---
                topic_id = post.metadata.get('topic_id')
                if not topic_id:
                    log_callback(f"  - [警告] 文件 {filename} 缺少 'topic_id' 元数据，无法处理其附件。")
                    continue
                
                # 1. 修正内容中的相对路径
                #    将 ![...](image.png) => ![...](<topic_id>/image.png)
                #    将 [...](file.zip)   => [...](<topic_id>/file.zip)
                #    使用一个相对复杂的正则表达式来确保只替换Markdown链接，而不是普通文本
                #    --- 核心修复：更新正则表达式，使其忽略绝对URL (http/https/mailto) ---
                content_with_paths = re.sub(r'(!?\[.*?\]\()((?!https?://|mailto:)[^)]+)(\))', rf'\g<1>{topic_id}/\g<2>\g<3>', post.content)
                html_content = markdown2.markdown(content_with_paths, extras=["cuddled-lists", "tables", "fenced-code-blocks", "break-on-newline"])

                post_data = post.metadata
                post_data['content'] = html_content
                
                # 2. 复制与该帖子关联的整个资源文件夹（如果存在）
                #    源: ../output/raw_xxx/123456789/  <--- 已修正为从raw目录查找
                #    目标: ../output/web_xxx/123456789/
                topic_assets_dir = os.path.join(raw_md_dir, str(topic_id))
                if os.path.exists(topic_assets_dir) and os.path.isdir(topic_assets_dir):
                    dest_assets_dir = os.path.join(web_output_dir, str(topic_id))
                    # shutil.copytree 在目标目录存在时会报错，所以先删除
                    if os.path.exists(dest_assets_dir):
                        shutil.rmtree(dest_assets_dir)
                    shutil.copytree(topic_assets_dir, dest_assets_dir)
                    log_callback(f"  - [资源] 已复制帖子 '{topic_id}' 的附件目录。")

                if 'tags' in post_data and post_data['tags']:
                    all_tags.update(post_data['tags'])
                
                if 'topic' in post_data and post_data['topic']:
                    all_topics.add(post_data['topic'])

                all_posts.append(post_data)

            except Exception as e:
                log_callback(f"  - [警告] 读取或处理文件 {filename} 失败: {e}")

    log_callback(f"  - [成功] 加载了 {len(all_posts)} 篇帖子。")
    log_callback(f"  - [成功] 发现了 {len(all_tags)} 个唯一标签。")
    log_callback(f"  - [成功] 发现了 {len(all_topics)} 个唯一主题。")

    # 3. 设置并加载Jinja2模板
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template(TEMPLATE_NAME)

    # 4. 渲染模板
    posts_json = json.dumps(all_posts, ensure_ascii=False)
    
    output_html = template.render(
        posts=all_posts, 
        posts_json=posts_json,
        all_tags=sorted(list(all_tags)),
        all_topics=sorted(list(all_topics)),
        default_theme='light'
    )

    # 5. 保存最终的HTML文件
    output_filepath = os.path.join(web_output_dir, 'index.html')
    try:
        with open(output_filepath, 'w', encoding='utf-8') as f:
            f.write(output_html)
        log_callback(f"\n[成功] 网站已生成！请在浏览器中打开: {os.path.abspath(output_filepath)}")
    except Exception as e:
        log_callback(f"\n[失败] 保存HTML文件失败: {e}")
        return

    # --- 核心修复：复制CSS和JS资源文件 ---
    log_callback("正在复制必要的样式(style.css)和脚本(app.js)文件...")
    assets_to_copy = ['style.css', 'app.js']
    for asset in assets_to_copy:
        source_path = os.path.join(TEMPLATE_DIR, asset)
        dest_path = os.path.join(web_output_dir, asset)
        if os.path.exists(source_path):
            try:
                shutil.copy(source_path, dest_path)
                log_callback(f"  - [成功] 已复制 {asset}")
            except Exception as e:
                log_callback(f"  - [失败] 复制 {asset} 失败: {e}")
        else:
            log_callback(f"  - [警告] 未在模板目录 {TEMPLATE_DIR} 中找到资源文件: {asset}，请确保它存在。")


if __name__ == '__main__':
    # 当独立运行时，提供一个默认的文件夹名进行测试
    run_html_generation('processed_md', log_callback=print)