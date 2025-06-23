import os
import frontmatter
import openai
import json
import time
import re
import traceback
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading

# --- 配置 ---
# API 配置现在从调用参数获取，这些作为后备或说明
DEEPSEEK_API_KEY_FALLBACK = "YOUR_DEEPSEEK_API_KEY"
DEEPSEEK_BASE_URL_FALLBACK = "https://api.deepseek.com"

# 2. 输入和输出目录 (这些将被移除，因为路径现在是动态的)
# RAW_MD_DIR = './output/raw_md/'
# PROCESSED_MD_DIR = './output/processed_md/'

# 3. AI处理的配置 
AI_MODEL = "deepseek-chat" # 使用DeepSeek模型
# 针对知识星球场景的"进阶版"分类方案
OFFICIAL_TOPICS_PRO = [
    # ----------- 专业技能 & 职场 -----------
    "技术分享", 
    "产品与设计", 
    "运营与营销",
    "内容创作",      # <-- [新增] 覆盖写作、自媒体、短视频等高频内容
    "职场进阶",

    # ----------- 商业洞察 & 价值创造 -----------
    "行业观察",
    "商业模式", 
    "投资理财",      # <-- [新增] 覆盖股票、基金、房产等财商内容
    "创业之路", 

    # ----------- 个人成长 & 生活方式 -----------
    "思维与方法", 
    "效率工具", 
    "生活美学", 
    "随想杂谈",
    
    # ----------- 元分类 (用于整理) -----------
    "星球互动与公告" # <-- [新增] 用于处理欢迎语、问答、公告、打卡等非主题性内容
]

# 针对知识星球场景的"进阶版"标签方案
OFFICIAL_TAGS_PRO = [
    # 技术
    "AI", "算法", "后端", "前端", "数据库", "架构", "DevOps", "安全", "Android", "iOS", "小程序",
    # 产品
    "产品设计", "产品经理", "用户体验", "UI", "UX", "需求分析",
    # 运营
    "用户增长", "新媒体", "市场营销", "SEO", "品牌", "内容运营",
    # 职场
    "求职面试", "职业规划", "管理", "沟通", "晋升", "远程工作",
    # 商业
    "商业模式", "案例分析", "行业动态", "电商", "金融科技", "SaaS",
    # 投资
    "投资理财", "股票", "基金", "房产", "财商", "加密货币",
    # 创业
    "创业", "融资", "团队管理", "MVP", "独立开发",
    # 成长
    "思维模型", "学习方法", "知识管理", "阅读", "决策",
    # 工具
    "效率工具", "Notion", "Obsidian", "ChatGPT", "自动化",
    # 生活
    "生活记录", "健康", "旅行", "摄影"
]

OFFICIAL_TOPICS = OFFICIAL_TOPICS_PRO # 使用进阶版
OFFICIAL_TAGS = OFFICIAL_TAGS_PRO # 使用进阶版标签
SIMILARITY_THRESHOLD = 2 # 主题相似度阈值，编辑距离小于等于此值则被标准化
TAG_SIMILARITY_THRESHOLD = 1 # 标签相似度阈值，更严格
AI_PROMPT_TEMPLATE = """
你是一个优秀的内容分类专家。请仔细阅读以下帖子内容，并为它完成三项任务：
1.  **生成标签(tags)**: 提取3至5个核心关键词作为标签。
2.  **生成摘要(digest)**: 写一个不超过50字的摘要，总结帖子主要内容。
3.  **指定主题(topic)**: 从以下列表中选择一个最合适的主题：{topics_list}。如果都不合适，请生成一个新的、不超过5个字的主题。

请严格按照以下JSON格式返回结果，不要包含任何额外的解释或文本。

{{
    "tags": ["关键词1", "关键词2"],
    "digest": "这是一个关于...",
    "topic": "技术分享"
}}

---
帖子内容如下：
{content}
"""

# --- 核心功能 ---

def get_ai_analysis(content: str, base_url: str, api_key: str, log_callback=print) -> dict:
    """
    调用 DeepSeek API 对给定内容进行分析，返回标签和主题。
    返回一个包含'tags'和'theme'的字典，失败则返回空字典。
    """
    start_time = time.time()
    if not api_key or "sk-" not in api_key:
        log_callback("  - [错误] API密钥未配置或格式不正确。")
        return {}

    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url
    )
    prompt = AI_PROMPT_TEMPLATE.format(
        topics_list=OFFICIAL_TOPICS,
        content=content
    )
    
    retry_count = 0
    while True:
        try:
            log_callback(f"  - [{datetime.now().strftime('%H:%M:%S')}] 正在调用DeepSeek AI进行分析...")
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            
            result_text = response.choices[0].message.content
            log_callback(f"  - [{datetime.now().strftime('%H:%M:%S')}] AI返回原始结果: {result_text}")
            
            # 1. 增强JSON解析：使用正则表达式从返回文本中提取JSON对象
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if not json_match:
                log_callback(f"  - [{datetime.now().strftime('%H:%M:%S')}] [警告] AI返回的内容中找不到JSON对象，正在重试...")
                time.sleep(2)
                continue

            json_string = json_match.group(0)
            analysis_data = json.loads(json_string)
            
            # --- 核心修复：放宽对AI返回结果的校验 ---
            # 不再要求所有字段必须存在。只要返回的是合法JSON，就接受。
            # 主循环中的 .get() 会优雅地处理可能缺失的字段。
            elapsed_time = time.time() - start_time
            log_callback(f"  - [{datetime.now().strftime('%H:%M:%S')}] AI分析完成，已解析JSON。耗时: {elapsed_time:.2f}秒")
            return analysis_data

        except json.JSONDecodeError:
            log_callback(f"  - [{datetime.now().strftime('%H:%M:%S')}] [警告] AI返回的不是有效的JSON，正在重试...")
            time.sleep(2)
        except Exception as e:
            log_callback(f"  - [{datetime.now().strftime('%H:%M:%S')}] [错误] 调用DeepSeek API时发生错误: {e}")
            return {}

def levenshtein_distance(s1, s2):
    if len(s1) < len(s2):
        return levenshtein_distance(s2, s1)
    if len(s2) == 0:
        return len(s1)
    previous_row = range(len(s2) + 1)
    for i, c1 in enumerate(s1):
        current_row = [i + 1]
        for j, c2 in enumerate(s2):
            insertions = previous_row[j + 1] + 1
            deletions = current_row[j] + 1
            substitutions = previous_row[j] + (c1 != c2)
            current_row.append(min(insertions, deletions, substitutions))
        previous_row = current_row
    return previous_row[-1]

def normalize_topic(ai_topic: str, log_callback=print) -> str:
    """
    标准化AI生成的主题，将其与官方列表进行模糊匹配。
    """
    if ai_topic in OFFICIAL_TOPICS:
        return ai_topic
    
    for official_topic in OFFICIAL_TOPICS:
        distance = levenshtein_distance(ai_topic, official_topic)
        if distance <= SIMILARITY_THRESHOLD:
            log_callback(f"  - [主题标准化] AI主题 '{ai_topic}' 已被标准化为 '{official_topic}' (编辑距离: {distance})")
            return official_topic
    
    log_callback(f"  - [主题标准化] AI生成了新主题: '{ai_topic}'")
    return ai_topic

def normalize_tags(ai_tags: list, log_callback=print) -> list:
    """
    标准化AI生成的标签列表，将其与官方列表进行模糊匹配，并去重。
    与`normalize_topic`逻辑类似，但处理的是标签列表。
    """
    if not isinstance(ai_tags, list):
        log_callback(f"  - [标签标准化] 警告: AI返回的'tags'不是列表，已忽略。返回空列表。")
        return []

    normalized_tags = set()
    for tag in ai_tags:
        # 完全匹配
        if tag in OFFICIAL_TAGS:
            normalized_tags.add(tag)
            continue
        
        # 模糊匹配
        best_match = None
        # 使用一个比阈值大的初始最小距离
        min_distance = TAG_SIMILARITY_THRESHOLD + 1

        for official_tag in OFFICIAL_TAGS:
            distance = levenshtein_distance(tag, official_tag)
            if distance < min_distance:
                min_distance = distance
                best_match = official_tag
        
        # 如果找到足够相似的官方标签，则使用官方标签
        if min_distance <= TAG_SIMILARITY_THRESHOLD:
            log_callback(f"  - [标签标准化] AI标签 '{tag}' 已被标准化为 '{best_match}' (编辑距离: {min_distance})")
            normalized_tags.add(best_match)
        else:
            # 如果没有找到相似的，保留原始AI标签，但可以记录一下
            log_callback(f"  - [标签标准化] AI生成了新标签: '{tag}' (未在官方列表中找到匹配项)")
            normalized_tags.add(tag)
            
    return list(normalized_tags)

def process_single_file(raw_filepath, processed_md_dir, base_url, api_key, log_callback):
    """处理单个Markdown文件的完整逻辑"""
    filename = os.path.basename(raw_filepath)
    processed_filepath = os.path.join(processed_md_dir, filename)
    
    # 使用线程ID的最后两位作为标识，增加日志可读性
    thread_id_suffix = threading.get_ident() % 100
    log_prefix = f"[线程-{thread_id_suffix:02d}]"

    # --- 核心修复：先检查目标目录中是否已存在处理好的文件 ---
    if os.path.exists(processed_filepath):
        try:
            # 加载已处理的文件并检查元数据
            processed_post = frontmatter.load(processed_filepath)
            if all(k in processed_post.metadata for k in ['tags', 'digest', 'topic']) and processed_post.metadata.get('topic'):
                log_callback(f"{log_prefix} [跳过] {filename} 在目标目录中已存在且已处理。")
                return f"[跳过] {filename}"
        except Exception as e:
            # 如果检查出错，则打印警告并继续执行，重新处理该文件
            log_callback(f"{log_prefix} [警告] 检查已处理文件 {filename} 时出错: {e}。将重新处理。")

    file_start_time = time.time()
    log_callback(f"{log_prefix} 开始处理: {filename}")

    try:
        # 加载原始文件进行处理
        post = frontmatter.load(raw_filepath)
        
        # 调用AI进行分析
        threaded_log_callback = lambda msg: log_callback(f"{log_prefix} {msg}")
        analysis_result = get_ai_analysis(post.content, base_url, api_key, threaded_log_callback)

        if analysis_result:
            ai_tags = analysis_result.get('tags', [])
            normalized_tags = normalize_tags(ai_tags, threaded_log_callback)

            ai_topic = analysis_result.get('topic', '未分类')
            normalized_topic = normalize_topic(ai_topic, threaded_log_callback)

            post.metadata['tags'] = normalized_tags
            post.metadata['digest'] = analysis_result.get('digest', '')
            post.metadata['topic'] = normalized_topic
            
            # 兼容旧的'theme'字段，如果存在则移除
            if 'theme' in post.metadata:
                del post.metadata['theme']
        else:
            log_callback(f"{log_prefix} [失败] {filename} 未能从AI获取有效分析结果。")

        # 将处理后的文件写入目标目录
        with open(processed_filepath, 'w', encoding='utf-8') as f:
            f.write(frontmatter.dumps(post))

        file_elapsed_time = time.time() - file_start_time
        return f"[成功] {filename} (耗时: {file_elapsed_time:.2f}s)"

    except Exception as e:
        log_callback(f"{log_prefix} [严重错误] 处理 {filename} 时发生异常: {e}")
        # 即使出错，也尝试复制原文件到目标目录，避免数据丢失
        try:
            output_filepath = os.path.join(processed_md_dir, filename)
            if not os.path.exists(output_filepath):
                import shutil
                shutil.copy(raw_filepath, output_filepath)
                log_callback(f"{log_prefix} [补救] 已将原始文件 {filename} 复制到目标目录。")
        except Exception as copy_e:
            log_callback(f"{log_prefix} [严重错误] 复制原始文件 {filename} 时也失败: {copy_e}")
        
        return f"[失败] {filename} ({e})"


def run_ai_processing(source_folder_name: str, base_url: str, api_key: str, concurrency: int, log_callback=print):
    """
    使用线程池并发处理指定目录中的所有原始MD文件。
    """
    # 路径配置
    qt_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(qt_dir)
    raw_md_dir = os.path.join(project_root, 'output', source_folder_name)
    processed_folder_name = source_folder_name.replace('raw_', 'processed_')
    processed_md_dir = os.path.join(project_root, 'output', processed_folder_name)
    
    log_callback(f"数据源文件夹: {raw_md_dir}")
    log_callback(f"处理后输出文件夹: {processed_md_dir}")
    log_callback(f"并发数设置为: {concurrency}")

    # 检查输入目录
    if not os.path.exists(raw_md_dir) or not os.listdir(raw_md_dir):
        log_callback(f"错误：未找到原始Markdown文件目录 '{raw_md_dir}'，或目录为空。")
        log_callback("请先执行抓取任务。")
        return

    if not os.path.exists(processed_md_dir):
        os.makedirs(processed_md_dir)

    start_time = time.time()
    
    all_md_files_in_raw = [os.path.join(raw_md_dir, f) for f in os.listdir(raw_md_dir) if f.endswith('.md')]
    total_files = len(all_md_files_in_raw)
    
    if total_files == 0:
        log_callback(f"目录 '{source_folder_name}' 中没有找到 .md 文件。")
        return

    log_callback(f"开始检查 {total_files} 个文件的处理状态...")

    processed_count = 0
    
    with ThreadPoolExecutor(max_workers=concurrency) as executor:
        # 创建一个futures到文件名的映射
        future_to_file = {executor.submit(process_single_file, filepath, processed_md_dir, base_url, api_key, log_callback): os.path.basename(filepath) for filepath in all_md_files_in_raw}
        
        for future in as_completed(future_to_file):
            filepath = future_to_file[future]
            try:
                result_message = future.result()
                log_callback(f"  -> [处理结果] {result_message}")
            except Exception as exc:
                filename = os.path.basename(filepath)
                log_callback(f"  -> [严重错误] 文件 {filename} 在执行期间产生致命异常: {exc}")
                traceback.print_exc()
            
            processed_count += 1
            # 实时更新本次任务的进度
            log_callback(f"--- [本次任务进度: {processed_count}/{total_files}] ---")

    total_elapsed_time = time.time() - start_time
    log_callback(f"\n[{datetime.now().strftime('%H:%M:%S')}] 所有文件处理完成！")
    log_callback(f"总耗时: {total_elapsed_time:.2f}秒")
    if total_files > 0:
        log_callback(f"平均每个文件耗时: {total_elapsed_time/total_files:.2f}秒")

if __name__ == '__main__':
    # 当独立运行时，提供一个默认的文件夹名进行测试
    run_ai_processing('raw_md', DEEPSEEK_BASE_URL_FALLBACK, DEEPSEEK_API_KEY_FALLBACK, concurrency=50, log_callback=print) 