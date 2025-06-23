import re
import requests
import json
import os
import shutil
import datetime
import urllib.request
from bs4 import BeautifulSoup
from urllib.parse import quote
from urllib.parse import unquote
import base64
import time
import frontmatter
import pprint

ZSXQ_ACCESS_TOKEN = 'F0107543-661C-4E0E-9D42-CFE769AD1AF9_4E936A0F4E574D35'    # 请从浏览器开发者工具中获取最新的 Token
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:79.0) Gecko/20100101 Firefox/79.0'    # 登录时使用的User-Agent（必须修改）
GROUP_ID = '88885284844882'                         # 知识星球中的小组ID

# --- 抓取模式设置 ---
# CRAWL_MODE: 'all' (所有帖子), 'digests' (仅精华), 'search' (关键词搜索)
CRAWL_MODE = 'search'
SEARCH_KEYWORD = 'AI'  # 仅在 CRAWL_MODE = 'search' 时生效

# PDF_FILE_NAME is no longer needed
DOWLOAD_PICS = True
DOWLOAD_COMMENTS = True
# ONLY_DIGESTS = True # 此变量已弃用，由CRAWL_MODE代替
FROM_DATE_TO_DATE = False
EARLY_DATE = '2017-05-25T00:00:00.000+0800'
LATE_DATE = '2018-05-25T00:00:00.000+0800'
DELETE_PICS_WHEN_DONE = True
DELETE_HTML_WHEN_DONE = True
COUNTS_PER_TIME = 3
DEBUG = True
DEBUG_NUM = None  # 设置为None以抓取所有帖子
SLEEP_FLAG = True
SLEEP_SEC = 1

# html_template is no longer needed

num = 0

def save_as_markdown(topic_data, output_dir):
    """
    将单个帖子数据保存为带有YAML Front Matter的Markdown文件。
    """
    post = frontmatter.Post("") # 创建一个空的post对象

    # 填充元数据
    post.metadata = {
        'topic_id': topic_data.get('topic_id'),
        'author': topic_data.get('author'),
        'create_time': topic_data.get('create_time'),
        'digested': topic_data.get('digested', False),
        'image_urls': topic_data.get('image_urls', []),
        'file_names': topic_data.get('file_names', []),
        'likes': topic_data.get('likes', 0),
        'comments_count': topic_data.get('comments_count', 0),
    }

    # 填充正文内容
    content_parts = []
    content_parts.append(topic_data.get('text', ''))

    if topic_data.get('answer'):
        content_parts.append(f"\n\n---\n\n**回答 by {topic_data.get('answer_author', '')}:**\n\n{topic_data.get('answer', '')}")

    if topic_data.get('comments'):
        content_parts.append("\n\n---\n\n### 评论区\n\n")
        for comment in topic_data.get('comments'):
            content_parts.append(comment)

    post.content = "\n".join(content_parts)

    # 保存文件
    filepath = os.path.join(output_dir, f"{topic_data.get('topic_id')}.md")
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post))
        print(f"  - [成功] 已保存帖子: {filepath}")
    except Exception as e:
        print(f"  - [失败] 保存帖子失败: {filepath}, 错误: {e}")

def handle_link_to_md(text):
    """
    将知识星球特定的HTML标记转换为标准的Markdown格式。
    """
    if not text:
        return ""
    # 先移除所有无法识别的、空的或包裹性的<e>标签
    text = re.sub(r'<e[^>]*>', '', text).replace('</e>', '')

    soup = BeautifulSoup(text, "html.parser")
    for mention in soup.find_all('e', attrs={'type': 'mention'}):
        mention.replace_with(f"@{mention.attrs.get('title', '')}")
    for tag in soup.find_all('e', attrs={'type': 'hashtag'}):
        tag.replace_with(f"#{unquote(tag.attrs.get('title', ''))}")
    for link in soup.find_all('e', attrs={'type': 'web'}):
        link.replace_with(f"[{unquote(link.attrs.get('title', ''))}]({unquote(link.attrs.get('href', ''))})")
    
    clean_text = soup.get_text()
    clean_text = clean_text.replace('<br/>', '\n').replace('<br>', '\n')
    return clean_text

def get_data(url, output_dir):

    OVER_DATE_BREAK = False

    global num
        
    headers = {
        'Cookie': 'zsxq_access_token=' + ZSXQ_ACCESS_TOKEN,
        'User-Agent': USER_AGENT
    }
    
    print("正在请求URL:", url)

    retry_count = 0
    while True:
        try:
            rsp = requests.get(url, headers=headers)
            response_json = rsp.json()
            if response_json.get('succeeded'):
                break
            if response_json.get('code') == 1059:
                retry_count += 1
                print(f"API返回内部错误，将在 {SLEEP_SEC} 秒后进行第 {retry_count} 次重试...")
                if SLEEP_FLAG:
                    time.sleep(SLEEP_SEC)
                continue
            print("错误：API返回了未处理的错误。")
            return
        except Exception as e:
            retry_count += 1
            print(f"请求或解析JSON时发生异常: {e}，将在 {SLEEP_SEC} 秒后进行第 {retry_count} 次重试...")
            if SLEEP_FLAG:
                time.sleep(SLEEP_SEC)
    
    try:
        resp_data = response_json.get('resp_data', {})
        
        # --- 删除所有诊断日志 ---
        
        # 终极修正：API返回的键名始终是 'topics'
        # 其中的每一项是一个包含 'group' 和 'topic' 的包装对象
        raw_items = resp_data.get('topics', [])
        topics = [item.get('topic') for item in raw_items if item.get('topic')]

        if not topics:
            print("未找到更多帖子。")
            return

        # 注意：这里不再定义 output_dir，而是使用传入的参数

        for topic in topics:
            if DEBUG and DEBUG_NUM is not None and num >= DEBUG_NUM:
                break
            
            num += 1
            print(f"正在处理第 {num} 个帖子...")
            
            # --- 删除所有诊断日志 ---
            
            content = topic.get('question', topic.get('talk', topic.get('task', topic.get('solution'))))
            if not content:
                print("  - [警告] 帖子内容为空，已跳过。")
                continue

            # 收集数据
            topic_data = {
                'topic_id': topic.get('topic_id'),
                'author': content.get('owner', {}).get('name', '匿名用户') if not content.get('anonymous') else '匿名用户',
                'create_time': (topic.get('create_time')[:23]).replace('T', ' '),
                'digested': topic.get('digested', False),
                'likes': topic.get('likes_count', 0),
                'comments_count': topic.get('comments_count', 0),
                'text': handle_link_to_md(content.get('text', '')),
                'image_urls': [img.get('large', {}).get('url') for img in content.get('images', []) if img.get('large', {}).get('url')],
                'file_names': [f.get('name') for f in content.get('files', [])],
            }

            # 处理问答
            if topic.get('question'):
                topic_data['answer_author'] = topic.get('answer', {}).get('owner', {}).get('name', '')
                topic_data['answer'] = handle_link_to_md(topic.get('answer', {}).get('text', ""))

            # 处理评论
            topic_data['comments'] = []
            if DOWLOAD_COMMENTS and topic.get('show_comments'):
                for comment in topic.get('show_comments'):
                    author_name = comment.get('owner', {}).get('name', '未知用户')
                    comment_text = handle_link_to_md(comment.get('text', ''))
                    if comment.get('repliee'):
                        repliee_name = comment.get('repliee', {}).get('name', '未知用户')
                        topic_data['comments'].append(f"> **{author_name}** 回复 **{repliee_name}**: {comment_text}\n")
                    else:
                        topic_data['comments'].append(f"> **{author_name}**: {comment_text}\n")
            
            # 保存为Markdown
            save_as_markdown(topic_data, output_dir)

    except Exception as e:
        import traceback
        print(f"处理响应数据时发生异常: {e}")
        traceback.print_exc()
        return

    if DEBUG and DEBUG_NUM is not None and num >= DEBUG_NUM:
        print("已达到DEBUG数量上限，所有抓取任务完成。")
        return
       
    if OVER_DATE_BREAK:
        print("已达到设定的最早时间，停止抓取。")
        return

    # 终极修正：分页逻辑
    next_page_data = response_json.get('resp_data', {})
    
    if 'topics' in next_page_data and next_page_data.get('topics'):
        last_wrapped_item = next_page_data['topics'][-1]
        last_topic_item = last_wrapped_item.get('topic')

        if last_topic_item:
            create_time = last_topic_item.get('create_time')
            if not create_time:
                 print("警告：无法从最后一个帖子中获取create_time，分页可能中断。")
                 return

            end_time = quote(create_time)
            if len(end_time) == 33:
                end_time = end_time[:24] + '0' + end_time[24:]
            
            base_next_url = url.split('&end_time=')[0]
            next_url = base_next_url + '&end_time=' + end_time

            if SLEEP_FLAG:
                time.sleep(SLEEP_SEC)
            get_data(next_url, output_dir)
        else:
            print("所有帖子处理完毕。")
    else:
        print("所有帖子处理完毕。")

# encode_image, download_image functions remain unchanged for now

def encode_image(image_url):
    with open(image_url, "rb") as image_file:
        encoded_string = base64.b64encode(image_file.read())
    return 'data:image/png;base64,' + encoded_string.decode('utf-8')

def download_image(url, local_url):
    try:
        urllib.request.urlretrieve(url, local_url)
    except urllib.error.ContentTooShortError:
        print('Network not good. Reloading ' + url)
        download_image(url, local_url)

if __name__ == '__main__':
    # 根据抓取模式，动态决定输出目录
    output_dir_base = './output'
    output_dir = ''

    if CRAWL_MODE == 'digests':
        output_dir = os.path.join(output_dir_base, 'raw_md_digests')
    elif CRAWL_MODE == 'search':
        # 清理关键词，使其能安全地作为目录名
        sanitized_keyword = re.sub(r'[\\/*?:"<>|]', "", SEARCH_KEYWORD)
        sanitized_keyword = re.sub(r'\s+', '_', sanitized_keyword).strip('_')
        output_dir = os.path.join(output_dir_base, f'raw_md_search_{sanitized_keyword}')
    else: # 'all'
        output_dir = os.path.join(output_dir_base, 'raw_md')
    
    print("-" * 50)
    print(f"抓取模式: '{CRAWL_MODE}'")
    if CRAWL_MODE == 'search':
        print(f"搜索关键词: '{SEARCH_KEYWORD}'")
    print(f"所有文件将保存到目录: {output_dir}")
    print("-" * 50)

    if not os.path.exists(output_dir):
        os.makedirs(output_dir)

    # For image downloads, if enabled
    if DOWLOAD_PICS:
        images_path = r'./images'
        if os.path.exists(images_path):
            shutil.rmtree(images_path)
        os.mkdir(images_path)

    # 根据CRAWL_MODE构建起始URL
    base_url = f"https://api.zsxq.com/v2/groups/{GROUP_ID}"
    start_url = ''

    if CRAWL_MODE == 'digests':
        print("抓取模式: 仅精华")
        start_url = f"{base_url}/topics?scope=digests&count={COUNTS_PER_TIME}"
    elif CRAWL_MODE == 'search':
        if not SEARCH_KEYWORD.strip():
            raise ValueError("错误：当CRAWL_MODE为'search'时，必须提供SEARCH_KEYWORD。")
        print(f"抓取模式: 搜索, 关键词: '{SEARCH_KEYWORD}'")
        keyword_encoded = quote(SEARCH_KEYWORD)
        # 注意：搜索API的分页逻辑可能与普通抓取不同，但我们假设它兼容基于end_time的分页
        start_url = f"https://api.zsxq.com/v2/search/topics?keyword={keyword_encoded}&group_id={GROUP_ID}&count={COUNTS_PER_TIME}"
    else: # CRAWL_MODE == 'all'
        print("抓取模式: 所有帖子")
        start_url = f"{base_url}/topics?count={COUNTS_PER_TIME}"

    url = start_url
    # 搜索模式下，end_time可能不适用，所以不添加
    if FROM_DATE_TO_DATE and LATE_DATE.strip() and CRAWL_MODE != 'search':
        url = start_url + '&end_time=' + quote(LATE_DATE.strip())
    
    print("开始抓取帖子...")
    print("起始URL:", url)

    get_data(url, output_dir)

    print("抓取完成！")

    if DOWLOAD_PICS and DELETE_PICS_WHEN_DONE:
        print("正在删除下载的图片...")
        shutil.rmtree(r'./images') 
