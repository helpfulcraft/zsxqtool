import os
import frontmatter
import markdown2
import json
from jinja2 import Environment, FileSystemLoader

# --- 配置 ---
PROCESSED_MD_DIR = './output/processed_md/'
WEB_OUTPUT_DIR = './output/web/'
TEMPLATE_DIR = './templates/'
TEMPLATE_NAME = 'template.html'

def build_website():
    """
    读取所有处理过的Markdown文件，并使用模板生成最终的静态网站。
    """
    print("开始构建Web可视化页面...")

    # 1. 确保输出目录存在
    if not os.path.exists(WEB_OUTPUT_DIR):
        os.makedirs(WEB_OUTPUT_DIR)

    # 2. 加载所有处理过的帖子数据
    all_posts = []
    all_tags = set()
    all_topics = set() # 新增：用于收集所有主题
    print(f"正在从 '{PROCESSED_MD_DIR}' 加载数据...")

    for filename in sorted(os.listdir(PROCESSED_MD_DIR), reverse=True): # 按文件名（ID）降序排列
        if filename.endswith('.md'):
            filepath = os.path.join(PROCESSED_MD_DIR, filename)
            try:
                post = frontmatter.load(filepath)
                
                # 将Markdown正文转换为HTML
                html_content = markdown2.markdown(post.content)

                post_data = post.metadata
                post_data['content'] = html_content
                
                # 收集标签
                if 'tags' in post_data and post_data['tags']:
                    all_tags.update(post_data['tags'])
                
                # 新增：收集主题
                if 'topic' in post_data and post_data['topic']:
                    all_topics.add(post_data['topic'])

                all_posts.append(post_data)

            except Exception as e:
                print(f"  - [警告] 读取或处理文件 {filename} 失败: {e}")

    print(f"  - [成功] 加载了 {len(all_posts)} 篇帖子。")
    print(f"  - [成功] 发现了 {len(all_tags)} 个唯一标签。")
    print(f"  - [成功] 发现了 {len(all_topics)} 个唯一主题。") # 新增日志

    # 3. 设置并加载Jinja2模板
    env = Environment(loader=FileSystemLoader(TEMPLATE_DIR))
    template = env.get_template(TEMPLATE_NAME)

    # 4. 渲染模板
    # 将帖子数据转换为JSON格式，以便前端JS使用
    posts_json = json.dumps(all_posts, ensure_ascii=False)
    
    output_html = template.render(
        posts=all_posts, 
        posts_json=posts_json,
        all_tags=sorted(list(all_tags)),
        all_topics=sorted(list(all_topics)), # 新增：将主题列表传递给模板
        default_theme='light'  # 默认主题
    )

    # 5. 保存最终的HTML文件
    output_filepath = os.path.join(WEB_OUTPUT_DIR, 'index.html')
    try:
        with open(output_filepath, 'w', encoding='utf-8') as f:
            f.write(output_html)
        print(f"\n[成功] 网站已生成！请在浏览器中打开: {output_filepath}")
    except Exception as e:
        print(f"\n[失败] 保存HTML文件失败: {e}")


if __name__ == '__main__':
    build_website() 