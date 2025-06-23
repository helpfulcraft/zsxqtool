import os
import frontmatter
import openai
import json
import time
import re
import traceback
from datetime import datetime

# --- 配置 ---
# 1. DeepSeek API 配置
# 文档: https://platform.deepseek.com/api-docs/
DEEPSEEK_API_KEY = "sk-9f84715d7b8e40ca8ebb81208f0fc143"
DEEPSEEK_BASE_URL = "https://api.deepseek.com"

# 2. 输入和输出目录
RAW_MD_DIR = './output/raw_md/'
PROCESSED_MD_DIR = './output/processed_md/'

# 3. AI处理的配置
AI_MODEL = "deepseek-chat" # 使用DeepSeek模型
# 针对知识星球场景的“进阶版”分类方案
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



SIMILARITY_THRESHOLD = 2 # 主题相似度阈值，编辑距离小于等于此值则被标准化
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

def get_ai_analysis(content: str) -> dict:
    """
    调用 DeepSeek API 对给定内容进行分析，返回标签和主题。
    返回一个包含'tags'和'theme'的字典，失败则返回空字典。
    """
    start_time = time.time()
    if not DEEPSEEK_API_KEY or "sk-" not in DEEPSEEK_API_KEY:
        print("  - [错误] DeepSeek API密钥未配置或格式不正确。")
        return {}

    client = openai.OpenAI(
        api_key=DEEPSEEK_API_KEY,
        base_url=DEEPSEEK_BASE_URL
    )
    prompt = AI_PROMPT_TEMPLATE.format(
        topics_list=OFFICIAL_TOPICS,
        content=content
    )
    
    retry_count = 0
    while True:
        try:
            print(f"  - [{datetime.now().strftime('%H:%M:%S')}] 正在调用DeepSeek AI进行分析...")
            response = client.chat.completions.create(
                model=AI_MODEL,
                messages=[{"role": "user", "content": prompt}],
                temperature=0.2,
            )
            
            result_text = response.choices[0].message.content
            print(f"  - [{datetime.now().strftime('%H:%M:%S')}] AI返回原始结果:", result_text)
            
            # 1. 增强JSON解析：使用正则表达式从返回文本中提取JSON对象
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if not json_match:
                print(f"  - [{datetime.now().strftime('%H:%M:%S')}] [警告] AI返回的内容中找不到JSON对象，正在重试...")
                time.sleep(2)
                continue

            json_string = json_match.group(0)
            analysis_data = json.loads(json_string)
            
            # 验证新的三个字段是否存在
            if 'tags' in analysis_data and 'digest' in analysis_data and 'topic' in analysis_data:
                elapsed_time = time.time() - start_time
                print(f"  - [{datetime.now().strftime('%H:%M:%S')}] AI分析完成，耗时: {elapsed_time:.2f}秒")
                return analysis_data
            else:
                print(f"  - [{datetime.now().strftime('%H:%M:%S')}] [警告] AI返回的JSON格式不正确，缺少'tags', 'digest'或'topic'字段。")
                return {}

        except json.JSONDecodeError:
            print(f"  - [{datetime.now().strftime('%H:%M:%S')}] [警告] AI返回的不是有效的JSON，正在重试...")
            time.sleep(2)
        except Exception as e:
            print(f"  - [{datetime.now().strftime('%H:%M:%S')}] [错误] 调用DeepSeek API时发生错误: {e}")
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

def normalize_topic(ai_topic: str) -> str:
    """
    标准化AI生成的主题，将其与官方列表进行模糊匹配。
    """
    if ai_topic in OFFICIAL_TOPICS:
        return ai_topic
    
    for official_topic in OFFICIAL_TOPICS:
        distance = levenshtein_distance(ai_topic, official_topic)
        if distance <= SIMILARITY_THRESHOLD:
            print(f"  - [主题标准化] AI主题 '{ai_topic}' 已被标准化为 '{official_topic}' (编辑距离: {distance})")
            return official_topic
    
    print(f"  - [主题标准化] AI生成了新主题: '{ai_topic}'")
    return ai_topic

def process_all_files():
    """
    遍历所有原始MD文件，使用AI进行处理，并保存到新目录。
    """
    if not os.path.exists(PROCESSED_MD_DIR):
        os.makedirs(PROCESSED_MD_DIR)

    start_time = time.time()
    print(f"[{datetime.now().strftime('%H:%M:%S')}] 开始处理目录 '{RAW_MD_DIR}' 中的文件...")

    total_files = len([f for f in os.listdir(RAW_MD_DIR) if f.endswith('.md')])
    processed_files = 0

    for filename in os.listdir(RAW_MD_DIR):
        if filename.endswith('.md'):
            file_start_time = time.time()
            filepath = os.path.join(RAW_MD_DIR, filename)
            processed_files += 1
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] [进度: {processed_files}/{total_files}] 处理文件: {filename}")

            try:
                post = frontmatter.load(filepath)
                
                # 检查新的字段，决定是否跳过
                if 'tags' in post.metadata and 'digest' in post.metadata and 'topic' in post.metadata:
                    print(f"  - [{datetime.now().strftime('%H:%M:%S')}] [跳过] 该文件似乎已经处理过。")
                else:
                    analysis_result = get_ai_analysis(post.content)
                    if analysis_result:
                        ai_topic = analysis_result.get('topic', '未分类')
                        normalized_topic = normalize_topic(ai_topic)

                        post.metadata['tags'] = analysis_result.get('tags', [])
                        post.metadata['digest'] = analysis_result.get('digest', '')
                        post.metadata['topic'] = normalized_topic
                        
                        if 'theme' in post.metadata:
                            del post.metadata['theme']
                            
                        print(f"  - [{datetime.now().strftime('%H:%M:%S')}] [成功] AI分析完成。")
                    else:
                        print(f"  - [{datetime.now().strftime('%H:%M:%S')}] [失败] 未能从AI获取有效分析结果。")

                output_filepath = os.path.join(PROCESSED_MD_DIR, filename)
                with open(output_filepath, 'w', encoding='utf-8') as f:
                    f.write(frontmatter.dumps(post))
                file_elapsed_time = time.time() - file_start_time
                print(f"  - [{datetime.now().strftime('%H:%M:%S')}] [保存] 已将处理后的文件保存至 {output_filepath} (耗时: {file_elapsed_time:.2f}秒)")

            except Exception as e:
                print(f"  - [{datetime.now().strftime('%H:%M:%S')}] [严重错误] 处理文件 {filename} 时发生未知异常: {e}")
                traceback.print_exc()

    total_elapsed_time = time.time() - start_time
    print(f"\n[{datetime.now().strftime('%H:%M:%S')}] 所有文件处理完成！")
    print(f"总耗时: {total_elapsed_time:.2f}秒")
    print(f"平均每个文件耗时: {total_elapsed_time/total_files:.2f}秒")

if __name__ == '__main__':
    process_all_files() 