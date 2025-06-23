import pprint
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
from concurrent.futures import ThreadPoolExecutor, as_completed

from PySide6.QtCore import QObject, Signal, QThread

# ===============================================================
# 全局配置 - 这些现在作为后备，优先使用GUI传入的值
# ===============================================================
# 知识星球 API 的访问令牌 (备用，实际值应由GUI传入)
ZSXQ_ACCESS_TOKEN_FALLBACK = 'F0107543-661C-4E0E-9D42-CFE769AD1AF9_4E936A0F4E574D35'
# HTTP请求的用户代理
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:79.0) Gecko/20100101 Firefox/79.0'
# 知识星球圈子ID (备用，实际值应由GUI传入)
GROUP_ID_FALLBACK = '88885284844882'

# --- 默认抓取设置 (这些值会被GUI覆盖) ---
DOWLOAD_PICS = True         # 是否下载图片
DOWLOAD_FILES = True        # 是否下载附件
DOWLOAD_COMMENTS = True     # 是否下载评论
COUNTS_PER_TIME = 20        # 每次API请求获取的帖子数量
SLEEP_FLAG = True           # 是否在每次API请求后暂停
SLEEP_SEC = 1               # 暂停秒数
# ===============================================================

# 全局变量
num = 0             # 已处理的帖子计数器
g_debug_num = None  # 用于调试，限制抓取的帖子总数，由GUI传入


def save_as_markdown(topic_data, output_dir, log_callback=print):
    """
    将单个帖子数据保存为带有YAML Front Matter的Markdown文件。

    Args:
        topic_data (dict): 包含帖子所有信息的字典。
        output_dir (str): 保存Markdown文件的目标目录。
        log_callback (function): 用于记录日志的回调函数。
    """
    # 创建一个空的 frontmatter Post 对象
    post = frontmatter.Post("")

    # 设置YAML Front Matter元数据
    post.metadata = {
        'topic_id': topic_data.get('topic_id'),
        'author': topic_data.get('author'),
        'create_time': topic_data.get('create_time'),
        'digested': topic_data.get('digested', False), # 是否为精华帖
        'image_urls': topic_data.get('image_urls', []), # 帖子中的图片本地路径
        'file_paths': topic_data.get('file_paths', []), # 帖子中的附件本地路径
        'likes': topic_data.get('likes', 0), # 点赞数
        'comments_count': topic_data.get('comments_count', 0), # 评论数
    }

    # 准备Markdown内容部分
    content_parts = []
    # 帖子正文
    content_parts.append(topic_data.get('text', ''))

    # 添加图片附件链接
    if topic_data.get('image_urls'):
        content_parts.append("\n\n**图片附件:**\n")
        for img_path in topic_data.get('image_urls'):
            img_name = os.path.basename(img_path)
            # 使用相对路径链接到图片
            content_parts.append(f"![image]({img_name})")

    # 添加文件附件链接
    if topic_data.get('file_paths'):
        content_parts.append("\n\n**文件附件:**\n")
        for file_path in topic_data.get('file_paths'):
            file_name = os.path.basename(file_path)
            # 使用相对路径链接到文件
            content_parts.append(f"- [{file_name}]({file_name})")

    # 如果是问答帖，添加回答部分
    if topic_data.get('answer'):
        content_parts.append(f"\n\n---\n\n**回答 by {topic_data.get('answer_author', '')}:**\n\n{topic_data.get('answer', '')}")

    # 添加评论区
    if topic_data.get('comments'):
        content_parts.append("\n\n---\n\n### 评论区\n\n")
        for comment in topic_data.get('comments'):
            content_parts.append(comment)

    # 将所有内容部分合并为最终的Markdown内容
    post.content = "\n".join(content_parts)

    # 构造最终文件路径
    filepath = os.path.join(output_dir, f"{topic_data.get('topic_id')}.md")
    try:
        # 使用 frontmatter 库将元数据和内容写入文件
        with open(filepath, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post, allow_unicode=True, sort_keys=False, width=10000))
        log_callback(f"  - [成功] 已保存帖子: {filepath}")
    except Exception as e:
        log_callback(f"  - [失败] 保存帖子失败: {filepath}, 错误: {e}")

def handle_link_to_md(text):
    """
    处理知识星球特定的富文本格式，将其转换为标准的Markdown。
    知识星球的富文本使用 <e> 标签来表示链接、@某人、话题等。

    Args:
        text (str): 从API获取的原始HTML格式文本。

    Returns:
        str: 转换后的Markdown格式文本。
    """
    if not text:
        return ""
    # 替换换行符
    text = text.replace('<br/>', '\n').replace('<br>', '\n')
    # 使用BeautifulSoup解析HTML
    soup = BeautifulSoup(text, "html.parser")
    # 处理加粗文本
    for bold in soup.select('e[type="text_bold"]'):
        title = unquote(bold.attrs.get('title', ''))
        bold.replace_with(f"# {title}\n\n")
    # 处理@用户
    for mention in soup.select('e[type="mention"]'):
        mention.replace_with(f"@{mention.attrs.get('title', '')}")
    # 处理#话题#
    for tag in soup.select('e[type="hashtag"]'):
        tag.replace_with(f"#{unquote(tag.attrs.get('title', ''))}")
    # 处理网页链接
    for link in soup.select('e[type="web"]'):
        title = unquote(link.attrs.get('title', ''))
        href = unquote(link.attrs.get('href', ''))
        link.replace_with(f"[{title}]({href})")
    # 处理标准的<a>标签
    for a in soup.find_all('a'):
        href = a.get('href', '')
        link_text = a.get_text(strip=True)
        if href and link_text:
            if link_text == href:
                 a.replace_with(href) # 如果链接文本和URL相同，则只保留URL
            else:
                 a.replace_with(f"[{link_text}]({href})") # 转换为Markdown链接
        elif href:
            a.replace_with(href) # 如果只有href，则只保留URL
        else:
            a.unwrap() # 如果没有href，则移除a标签，保留内部文本
    return soup.get_text()

def get_data(url, output_dir, log_callback, token, is_single_post=False):
    """
    核心函数：通过API获取帖子数据，处理并保存。支持分页递归调用。

    Args:
        url (str): 要请求的API URL。
        output_dir (str): 保存文件的目录。
        log_callback (function): 日志回调函数。
        token (str): 知识星球的access_token。
        is_single_post (bool): 标记当前是否为抓取单个帖子模式。
    """
    global num, g_debug_num # 使用全局变量来计数和控制总数
    headers = {
        'Cookie': 'zsxq_access_token=' + token,
        'User-Agent': USER_AGENT
    }
    log_callback("正在请求URL: " + url)

    # 请求重试逻辑
    retry_count = 0
    while True:
        try:
            rsp = requests.get(url, headers=headers, timeout=30)
            response_json = rsp.json()
            if response_json.get('succeeded'):
                break # 请求成功，跳出重试循环
            if response_json.get('code') == 1059: # 知识星球API的一个常见内部错误码
                retry_count += 1
                log_callback(f"API返回内部错误(1059)，将在 {SLEEP_SEC} 秒后进行第 {retry_count} 次重试...")
                if SLEEP_FLAG:
                    time.sleep(SLEEP_SEC)
                continue # 继续下一次重试
            else:
                log_callback(f"错误: API逻辑失败，无法重试. 响应: {response_json}")
                return # 无法处理的错误，函数返回

        except requests.exceptions.RequestException as e:
            retry_count += 1
            log_callback(f"错误: 网络请求失败: {e}，将在 {SLEEP_SEC} 秒后进行第 {retry_count} 次重试...")
            if SLEEP_FLAG:
                time.sleep(SLEEP_SEC)
            continue
        except json.JSONDecodeError:
            retry_count += 1
            log_callback(f"错误: 解析JSON失败，将在 {SLEEP_SEC} 秒后进行第 {retry_count} 次重试...")
            if SLEEP_FLAG:
                time.sleep(SLEEP_SEC)
            continue

    try:
        resp_data = response_json.get('resp_data', {})
        
        topics = []
        # 根据是否是单帖模式，从不同的JSON结构中提取帖子列表
        if is_single_post:
            if 'topic' in resp_data:
                topics = [resp_data['topic']]
        else:
            raw_items = resp_data.get('topics', [])
            # API在不同端点返回的topics列表结构可能不一致：
            # - /groups/.../topics 直接返回 topic 对象列表 [topic, topic, ...]
            # - /search/topics 可能返回包装过的对象列表 [{'topic': {...}}, ...]
            # 此处进行兼容性处理
            if raw_items and 'topic' in raw_items[0]:
                # 兼容包装过的列表（例如搜索结果）
                topics = [item.get('topic') for item in raw_items if item.get('topic')]
            else:
                # 兼容直接的topic对象列表
                topics = raw_items
        
        if not topics:
            log_callback("未找到更多帖子。")
            return

        # 遍历获取到的每一个帖子
        for topic in topics:
            # 检查是否达到了调试设置的抓取数量上限
            if g_debug_num is not None and num >= g_debug_num:
                break
            
            topic_id = topic.get('topic_id')
            if not topic_id:
                log_callback("  - [警告] 帖子缺少topic_id，已跳过。")
                continue
                
            # 检查帖子是否已经下载过，如果存在则跳过
            output_filepath = os.path.join(output_dir, f"{topic_id}.md")
            if os.path.exists(output_filepath):
                log_callback(f"  - [跳过] 帖子 {topic_id} 已存在。")
                continue

            num += 1
            log_callback(f"正在处理第 {num} 个帖子 (ID: {topic_id})...")
            
            # 帖子内容可能在不同的字段中（talk, question, task, solution）
            content = topic.get('question', topic.get('talk', topic.get('task', topic.get('solution'))))
            if not content:
                log_callback("  - [警告] 帖子内容为空，已跳过。")
                continue

            # 处理帖子正文中的富文本
            parsed_text = handle_link_to_md(content.get('text', ''))
            # 处理文章链接（如果存在）
            if content.get('article'):
                article_title = content.get('article', {}).get('title', '阅读原文')
                article_url = content.get('article', {}).get('article_url', '')
                if article_url:
                    parsed_text += f"\n\n---\n🔗 [{article_title}]({article_url})"

            # 准备要保存的帖子数据字典
            topic_data = {
                'topic_id': str(topic_id),
                'author': content.get('owner', {}).get('name', '匿名用户') if not content.get('anonymous') else '匿名用户',
                'create_time': (topic.get('create_time')[:23]).replace('T', ' '), # 格式化时间
                'digested': topic.get('digested', False),
                'likes': topic.get('likes_count', 0),
                'comments_count': topic.get('comments_count', 0),
                'text': parsed_text,
                'image_urls': [],
                'file_paths': [],
            }

            # 下载图片
            if DOWLOAD_PICS and content.get('images'):
                # 为每个帖子创建一个独立的子目录存放图片和附件
                image_dir = os.path.join(output_dir, str(topic_id))
                os.makedirs(image_dir, exist_ok=True)
                # 使用线程池并发下载图片
                with ThreadPoolExecutor(max_workers=5) as executor:
                    future_to_url = {executor.submit(download_image, img.get('large', {}).get('url'), os.path.join(image_dir, os.path.basename(img.get('large', {}).get('url').split('?')[0])), log_callback): img.get('large', {}).get('url') for img in content.get('images') if img.get('large', {}).get('url')}
                    for future in as_completed(future_to_url):
                        img_url = future_to_url[future]
                        try:
                            img_local_path = future.result()
                            if img_local_path:
                                # 将下载成功的图片本地路径添加到数据中
                                topic_data['image_urls'].append(img_local_path)
                        except Exception as exc:
                            log_callback(f'    - [图片] 下载生成异常: {img_url}, 错误: {exc}')
            
            # 下载附件
            if DOWLOAD_FILES and content.get('files'):
                file_dir = os.path.join(output_dir, str(topic_id))
                os.makedirs(file_dir, exist_ok=True)
                # 使用线程池并发下载附件
                with ThreadPoolExecutor(max_workers=3) as executor:
                    future_to_file = {executor.submit(download_file, f.get('file_id'), os.path.join(file_dir, f.get('name')), token, log_callback): f.get('name') for f in content.get('files') if f.get('file_id') and f.get('name')}
                    for future in as_completed(future_to_file):
                        file_name = future_to_file[future]
                        try:
                            file_local_path = future.result()
                            if file_local_path:
                                # 将下载成功的附件本地路径添加到数据中
                                topic_data['file_paths'].append(file_local_path)
                        except Exception as exc:
                            log_callback(f'    - [附件] 下载生成异常: {file_name}, 错误: {exc}')

            # 如果是问答帖，提取回答内容
            if topic.get('question'):
                topic_data['answer_author'] = topic.get('answer', {}).get('owner',{}).get('name', '')
                topic_data['answer'] = handle_link_to_md(topic.get('answer', {}).get('text', ""))

            # 处理评论
            topic_data['comments'] = []
            if DOWLOAD_COMMENTS and topic.get('show_comments'):
                for comment in topic.get('show_comments'):
                    author_name = comment.get('owner', {}).get('name', '未知用户')
                    comment_text = handle_link_to_md(comment.get('text', ''))
                    repliee = comment.get('repliee') # 被回复的人
                    if repliee:
                        repliee_name = repliee.get('name', '未知用户')
                        # 格式化为 "A 回复 B: ..."
                        topic_data['comments'].append(f"> **{author_name}** 回复 **{repliee_name}**: {comment_text}\n")
                    else:
                        # 格式化为 "A: ..."
                        topic_data['comments'].append(f"> **{author_name}**: {comment_text}\n")
            
            # 所有数据处理完毕，保存为Markdown文件
            save_as_markdown(topic_data, output_dir, log_callback)

    except Exception as e:
        import traceback
        log_callback(f"处理响应数据时发生严重异常: {e}")
        log_callback(traceback.format_exc())
        return

    # 检查是否达到调试数量限制
    if g_debug_num is not None and num >= g_debug_num:
        log_callback(f"已达到设定的抓取数量上限 ({g_debug_num})，任务完成。")
        return

    # 如果是抓取单帖模式，到此结束
    if is_single_post:
        log_callback("单帖抓取完成。")
        return
        
    # --- 分页逻辑 ---
    next_page_data = response_json.get('resp_data', {})
    # 检查返回的数据中是否还有下一页的帖子
    if 'topics' in next_page_data and next_page_data.get('topics'):
        topics_in_page = next_page_data['topics']
        last_topic_item = None
        # 兼容不同API返回的结构，以正确获取用于分页的最后一个topic
        if 'topic' in topics_in_page[0]:
            # 兼容搜索接口返回的包装结构
            for item in reversed(topics_in_page):
                if item.get('topic'):
                    last_topic_item = item.get('topic')
                    break
        else:
            # 兼容普通帖子列表接口，直接取最后一个
            last_topic_item = topics_in_page[-1]
        
        if last_topic_item:
            create_time = last_topic_item.get('create_time')
            if not create_time:
                 log_callback("警告: 无法从最后一个帖子获取create_time，分页中断。")
                 return

            # 知识星球的分页是通过上一页最后一个帖子的创建时间来实现的
            end_time = quote(create_time)
            # 对时间字符串进行特殊处理以符合API要求
            if len(end_time) == 33:
                end_time = end_time[:24] + '0' + end_time[24:]
            
            # 构建下一页的URL
            base_next_url = url.split('&end_time=')[0]
            next_url = f"{base_next_url}&end_time={end_time}"

            # 暂停一段时间，防止请求过于频繁
            if SLEEP_FLAG:
                time.sleep(SLEEP_SEC)
            # 递归调用自身来获取下一页的数据
            get_data(next_url, output_dir, log_callback, token, is_single_post=False)
        else:
            log_callback("所有帖子处理完毕 (最后一个分页批次无有效topic)。")
    else:
        log_callback("所有帖子处理完毕 (API未返回更多topics)。")

def download_image(url, local_path, log_callback):
    """
    下载单个图片。

    Args:
        url (str): 图片的URL。
        local_path (str): 本地保存路径。
        log_callback (function): 日志回调函数。

    Returns:
        str or None: 成功则返回本地路径，失败则返回None。
    """
    try:
        r = requests.get(url, stream=True, timeout=20)
        r.raise_for_status() # 如果请求失败（非2xx状态码），则抛出异常
        with open(local_path, 'wb') as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        log_callback(f"    - [图片] 已下载: {local_path}")
        return local_path
    except Exception as e:
        log_callback(f"    - [图片] 下载失败: {url}, 错误: {e}")
        return None

def download_file(file_id, local_path, token, log_callback):
    """
    下载单个附件。附件下载需要先通过一个API获取真实的下载链接。

    Args:
        file_id (str): 附件的ID。
        local_path (str): 本地保存路径。
        token (str): 知识星球access_token。
        log_callback (function): 日志回调函数。

    Returns:
        str or None: 成功则返回本地路径，失败则返回None。
    """
    # 获取下载链接的API
    download_url_api = f"https://api.zsxq.com/v2/files/{file_id}/download_url"
    headers = {'Cookie': f'zsxq_access_token={token}', 'User-Agent': USER_AGENT}
    try:
        # 第一步：请求API获取真实下载链接
        r = requests.get(download_url_api, headers=headers, timeout=20)
        r.raise_for_status()
        resp_json = r.json()
        if not resp_json.get('succeeded'):
            log_callback(f"    - [附件] 获取下载链接API失败: {resp_json}")
            return None
        
        real_download_url = resp_json.get('resp_data', {}).get('download_url')
        if not real_download_url:
            log_callback(f"    - [附件] 未找到下载链接: {file_id}")
            return None

        # 第二步：使用获取到的链接下载文件
        r_file = requests.get(real_download_url, stream=True, timeout=60)
        r_file.raise_for_status()
        with open(local_path, 'wb') as f:
            for chunk in r_file.iter_content(chunk_size=8192):
                f.write(chunk)
        log_callback(f"    - [附件] 已下载: {local_path}")
        return local_path
    except Exception as e:
        log_callback(f"    - [附件] 下载文件失败: ID={file_id}, 错误={e}")
        return None

def run_crawler(crawl_mode, group_id, token, search_keyword="", post_id="", debug_num=None, log_callback=print):
    """
    爬虫主入口函数，由GUI调用。

    Args:
        crawl_mode (str): 抓取模式 ('all', 'digests', 'search', 'single_post')。
        group_id (str): 星球ID。
        token (str): 用户access_token。
        search_keyword (str, optional): 搜索模式下的关键词。
        post_id (str, optional): 单帖模式下的帖子ID。
        debug_num (int, optional): 限制抓取的帖子数量。
        log_callback (function, optional): 日志回调函数。
    """
    global num, g_debug_num
    num = 0 # 重置全局计数器
    
    # 优先使用GUI传入的参数，如果为空则使用文件顶部的后备值
    group_id = group_id or GROUP_ID_FALLBACK
    token = token or ZSXQ_ACCESS_TOKEN_FALLBACK

    # 设置调试用的抓取数量
    if debug_num:
        try:
            g_debug_num = int(debug_num)
        except (ValueError, TypeError):
            log_callback(f"警告：无效的抓取数量 '{debug_num}'。将抓取所有帖子。")
            g_debug_num = None
    else:
        g_debug_num = None
    
    # --- 设置输出目录 ---
    script_dir = os.path.dirname(os.path.abspath(__file__))
    qt_dir = os.path.dirname(script_dir)
    output_dir_base = os.path.join(qt_dir, 'output')
    output_dir = ''

    # 根据不同的抓取模式，确定不同的输出子目录名称
    if crawl_mode == 'digests':
        output_dir = os.path.join(output_dir_base, 'raw_md_digests')
    elif crawl_mode == 'search':
        # 清理关键词中的非法字符，用作目录名
        sanitized_keyword = re.sub(r'[\s\\/*?:"<>|]+', "_", search_keyword).strip('_')
        output_dir = os.path.join(output_dir_base, f'raw_md_search_{sanitized_keyword}')
    elif crawl_mode == 'single_post':
        output_dir = os.path.join(output_dir_base, f'raw_md_post_{post_id}')
    else: # 'all'
        output_dir = os.path.join(output_dir_base, 'raw_md')
    
    # 打印任务信息
    log_callback("-" * 50)
    log_callback(f"抓取模式: '{crawl_mode}'")
    if crawl_mode == 'search': log_callback(f"搜索关键词: '{search_keyword}'")
    if crawl_mode == 'single_post': log_callback(f"帖子ID: '{post_id}'")
    if debug_num is not None: log_callback(f"抓取数量: {debug_num}")
    log_callback(f"文件将保存到: {output_dir}")
    log_callback("-" * 50)

    # 创建输出目录（如果不存在）
    os.makedirs(output_dir, exist_ok=True)

    # --- 构造起始URL ---
    base_url = f"https://api.zsxq.com/v2/groups/{group_id}"
    start_url = ''

    if crawl_mode == 'digests':
        # 获取精华帖的URL
        start_url = f"{base_url}/topics?scope=digests&count={COUNTS_PER_TIME}"
    elif crawl_mode == 'search':
        # 获取搜索结果的URL
        keyword_encoded = quote(search_keyword)
        start_url = f"https://api.zsxq.com/v2/search/topics?keyword={keyword_encoded}&group_id={group_id}&count={COUNTS_PER_TIME}&sort=create_time"
    elif crawl_mode == 'single_post':
        # 获取单个帖子的URL
        start_url = f"https://api.zsxq.com/v2/topics/{post_id}"
    else: # 'all'
        # 获取全部帖子的URL
        start_url = f"{base_url}/topics?count={COUNTS_PER_TIME}"

    log_callback("开始抓取帖子...")
    log_callback(f"起始URL: {start_url}")
    
    # 调用核心函数开始抓取
    get_data(start_url, output_dir, log_callback, token, is_single_post=(crawl_mode == 'single_post'))

    log_callback("抓取完成！")
