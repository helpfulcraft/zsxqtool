import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QLabel, QComboBox, QLineEdit,
                             QPushButton, QTextEdit, QGroupBox, QSpinBox, QCheckBox)
from PySide6.QtCore import QSize, QThread, Signal, QObject, Qt, QSettings
import webbrowser
import http.server
import socketserver
import functools

# 添加项目根目录到系统路径
current_dir = os.path.dirname(os.path.abspath(__file__))
project_root = os.path.dirname(current_dir)
sys.path.append(project_root)

from logic.zsxq_crawler import run_crawler
from logic.process_with_ai import run_ai_processing
from logic.build_html import run_html_generation

# --- 抓取工作线程 ---
class CrawlerWorker(QObject):
    finished = Signal()
    log_message = Signal(str)

    def __init__(self, crawl_mode, search_keyword, post_id, debug_num, group_id, token):
        super().__init__()
        self.crawl_mode = crawl_mode
        self.search_keyword = search_keyword
        self.post_id = post_id
        self.debug_num = debug_num
        self.group_id = group_id
        self.token = token

    def run(self):
        """执行爬虫任务"""
        try:
            run_crawler(
                crawl_mode=self.crawl_mode,
                search_keyword=self.search_keyword,
                post_id=self.post_id,
                debug_num=self.debug_num,
                group_id=self.group_id,
                token=self.token,
                log_callback=self.log_message.emit
            )
        except Exception as e:
            self.log_message.emit(f"发生未捕获的异常: {e}")
        finally:
            self.finished.emit()


# --- AI处理工作线程 ---
class AiWorker(QObject):
    finished = Signal()
    log_message = Signal(str)

    def __init__(self, source_folder_name: str, base_url: str, api_key: str, concurrency: int):
        super().__init__()
        self.source_folder_name = source_folder_name
        self.base_url = base_url
        self.api_key = api_key
        self.concurrency = concurrency

    def run(self):
        try:
            run_ai_processing(self.source_folder_name, self.base_url, self.api_key, self.concurrency, self.log_message.emit)
        except Exception as e:
            self.log_message.emit(f"发生未捕获的异常: {e}")
        finally:
            self.finished.emit()


# --- HTML 生成工作线程 ---
class HtmlWorker(QObject):
    finished = Signal()
    log_message = Signal(str)

    def __init__(self, source_folder_name: str):
        super().__init__()
        self.source_folder_name = source_folder_name

    def run(self):
        try:
            run_html_generation(self.source_folder_name, self.log_message.emit)
        except Exception as e:
            self.log_message.emit(f"发生未捕t捕的异常: {e}")
        finally:
            self.finished.emit()


# --- 新增：HTTP服务器工作线程 ---
class ServerWorker(QObject):
    server_started = Signal(str)
    server_stopped = Signal()
    log_message = Signal(str)

    def __init__(self, directory, port=8000):
        super().__init__()
        self.directory = directory
        self.port = port
        self.httpd = None

    def run(self):
        # --- 核心修复：使用 functools.partial 来为 Handler 预设 directory 参数 ---
        Handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=self.directory)

        try:
            self.httpd = socketserver.TCPServer(("", self.port), Handler)
            self.log_message.emit(f"本地预览服务器已在 http://localhost:{self.port} 启动")
            self.log_message.emit(f"服务目录: {self.directory}")
            self.server_started.emit(f"http://localhost:{self.port}")
            self.httpd.serve_forever()
        except Exception as e:
            self.log_message.emit(f"启动服务器失败: {e}")
        finally:
            self.log_message.emit("本地预览服务器已停止。")
            self.server_stopped.emit()

    def stop(self):
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()

        # --- 窗口基础设置 ---
        self.setWindowTitle("知识星球内容总管")
        self.setMinimumSize(QSize(800, 600))
        
        # --- 初始化线程变量 ---
        self.server_thread = None
        self.server_worker = None
        self.worker_thread = None # 用于抓取、AI、HTML的通用线程

        # --- 中心部件 ---
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # --- 主布局 ---
        main_layout = QVBoxLayout(central_widget)

        # --- 抓取设置组 ---
        settings_group = QGroupBox("抓取设置")
        settings_layout = QVBoxLayout()
        
        # --- 第一行：模式和数量 ---
        row1_layout = QHBoxLayout()
        
        # 抓取模式
        mode_label = QLabel("抓取模式:")
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["全部帖子", "仅精华", "关键词搜索", "单个帖子"])
        self.mode_combo.currentTextChanged.connect(self.on_mode_changed)
        row1_layout.addWidget(mode_label)
        row1_layout.addWidget(self.mode_combo)
        
        row1_layout.addSpacing(30) # 增加一些间距

        # 抓取数量
        count_label = QLabel("抓取数量:")
        self.crawl_count_spinbox = QSpinBox()
        self.crawl_count_spinbox.setRange(1, 9999)
        self.crawl_count_spinbox.setValue(10) # 默认值
        self.crawl_all_checkbox = QCheckBox("抓取全部")
        self.crawl_all_checkbox.stateChanged.connect(self.on_crawl_all_changed)
        row1_layout.addWidget(count_label)
        row1_layout.addWidget(self.crawl_count_spinbox)
        row1_layout.addWidget(self.crawl_all_checkbox)
        row1_layout.addStretch() # 伸缩因子
        
        settings_layout.addLayout(row1_layout)

        # --- 第二行：关键词（可隐藏）---
        self.keyword_layout_widget = QWidget()
        keyword_layout = QHBoxLayout(self.keyword_layout_widget)
        keyword_layout.setContentsMargins(0, 5, 0, 5) # 调整边距
        keyword_label = QLabel("搜索关键词:")
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText("请输入搜索关键词")
        keyword_layout.addWidget(keyword_label)
        keyword_layout.addWidget(self.keyword_input)
        settings_layout.addWidget(self.keyword_layout_widget)
        self.keyword_layout_widget.setVisible(False)

        # --- 新增：第三行：帖子ID（可隐藏）---
        self.post_id_layout_widget = QWidget()
        post_id_layout = QHBoxLayout(self.post_id_layout_widget)
        post_id_layout.setContentsMargins(0, 5, 0, 5)
        post_id_label = QLabel("帖子ID:")
        self.post_id_input = QLineEdit()
        self.post_id_input.setPlaceholderText("请输入要抓取的单个帖子的ID")
        post_id_layout.addWidget(post_id_label)
        post_id_layout.addWidget(self.post_id_input)
        settings_layout.addWidget(self.post_id_layout_widget)
        self.post_id_layout_widget.setVisible(False)

        # --- 新增：星球ID和Token设置 ---
        auth_layout = QHBoxLayout()
        group_id_label = QLabel("星球ID:")
        self.group_id_input = QLineEdit()
        self.group_id_input.setPlaceholderText("请输入星球ID")
        token_label = QLabel("Access Token:")
        self.token_input = QLineEdit()
        self.token_input.setPlaceholderText("请输入你的Access Token")
        self.token_input.setEchoMode(QLineEdit.Normal) # Token设为密码模式
        auth_layout.addWidget(group_id_label)
        auth_layout.addWidget(self.group_id_input)
        auth_layout.addSpacing(15)
        auth_layout.addWidget(token_label)
        auth_layout.addWidget(self.token_input)
        settings_layout.addLayout(auth_layout)

        # --- 第四行：开始按钮 ---
        self.start_button = QPushButton("开始抓取")
        self.start_button.clicked.connect(self.on_start_clicked)
        settings_layout.addWidget(self.start_button)

        settings_group.setLayout(settings_layout)
        main_layout.addWidget(settings_group)
        
        # --- 新增：数据源选择组 ---
        source_group = QGroupBox("数据源选择")
        source_layout = QHBoxLayout(source_group)
        source_label = QLabel("请选择要处理的数据集:")
        self.source_folder_combo = QComboBox()
        self.source_folder_combo.currentIndexChanged.connect(self.update_button_states)
        self.refresh_folders_button = QPushButton("刷新列表")
        self.refresh_folders_button.clicked.connect(self.populate_source_folders_combo)
        source_layout.addWidget(source_label)
        source_layout.addWidget(self.source_folder_combo, 1) # Add stretch factor
        source_layout.addWidget(self.refresh_folders_button)
        main_layout.addWidget(source_group)

        # --- 新增：处理流程组 ---
        processing_group = QGroupBox("处理流程")
        processing_layout = QVBoxLayout(processing_group)

        # AI API 设置
        api_settings_layout = QHBoxLayout()
        base_url_label = QLabel("API Base URL:")
        self.base_url_input = QLineEdit()
        api_key_label = QLabel("API Key:")
        self.api_key_input = QLineEdit()
        self.api_key_input.setEchoMode(QLineEdit.Normal)
        
        concurrency_label = QLabel("并发数:")
        self.concurrency_spinbox = QSpinBox()
        self.concurrency_spinbox.setRange(1, 1000) # 设置范围
        
        api_settings_layout.addWidget(base_url_label)
        api_settings_layout.addWidget(self.base_url_input)
        api_settings_layout.addWidget(api_key_label)
        api_settings_layout.addWidget(self.api_key_input)
        api_settings_layout.addWidget(concurrency_label)
        api_settings_layout.addWidget(self.concurrency_spinbox)
        
        processing_layout.addLayout(api_settings_layout)

        # 按钮行
        buttons_layout = QHBoxLayout()
        self.process_ai_button = QPushButton("(2) 开始AI处理")
        self.process_ai_button.clicked.connect(self.on_process_ai_clicked)
        
        self.build_html_button = QPushButton("(3) 生成最终网页")
        self.build_html_button.clicked.connect(self.on_build_html_clicked)

        self.preview_button = QPushButton("在浏览器中预览")
        self.preview_button.clicked.connect(self.on_preview_clicked)

        buttons_layout.addWidget(self.process_ai_button)
        buttons_layout.addWidget(self.build_html_button)
        buttons_layout.addWidget(self.preview_button)
        buttons_layout.addStretch()
        
        processing_layout.addLayout(buttons_layout)
        
        main_layout.addWidget(processing_group)

        # --- 运行日志组 ---
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        log_layout.addWidget(self.log_text)
        log_group.setLayout(log_layout)
        main_layout.addWidget(log_group, stretch=1) # 让日志区域占据更多空间

        self.ai_thread = None
        self.ai_worker = None
        self.html_thread = None
        self.html_worker = None
        
        # 加载设置
        self.load_settings()
        
        # 初始化时填充数据源和加载设置
        self.populate_source_folders_combo()

    def on_mode_changed(self, text):
        self.keyword_layout_widget.setVisible(text == "关键词搜索")
        self.post_id_layout_widget.setVisible(text == "单个帖子")

    def on_crawl_all_changed(self, state):
        self.crawl_count_spinbox.setEnabled(state == Qt.CheckState.Unchecked.value)

    def append_log(self, message):
        self.log_text.append(message)

    def on_start_clicked(self):
        # 从GUI获取参数
        crawl_mode_text = self.mode_combo.currentText()
        mode_map = {"全部帖子": "all", "仅精华": "digests", "关键词搜索": "search", "单个帖子": "single_post"}
        crawl_mode = mode_map.get(crawl_mode_text)
        
        search_keyword = self.keyword_input.text() if crawl_mode == "search" else ""
        post_id = self.post_id_input.text() if crawl_mode == "single_post" else ""
        group_id = self.group_id_input.text()
        token = self.token_input.text()
        
        debug_num = None if self.crawl_all_checkbox.isChecked() else self.crawl_count_spinbox.value()

        if not group_id or not token:
            self.append_log("错误：必须输入星球ID和Access Token。")
            self.set_controls_enabled(True)
            return
        if crawl_mode == 'search' and not search_keyword:
            self.append_log("错误：使用关键词搜索模式时，必须输入关键词。")
            self.set_controls_enabled(True)
            return
        if crawl_mode == "single_post" and not post_id.strip():
            self.append_log("错误：请输入帖子ID！")
            return
            
        self.set_controls_enabled(False)
        self.append_log("="*20 + " 任务开始 " + "="*20)

        self.thread = QThread(self)
        self.crawler_worker = CrawlerWorker(crawl_mode, search_keyword, post_id, debug_num, group_id, token)
        self.crawler_worker.moveToThread(self.thread)

        self.thread.started.connect(self.crawler_worker.run)
        self.crawler_worker.finished.connect(self.thread.quit)
        self.crawler_worker.finished.connect(self.crawler_worker.deleteLater)
        self.thread.finished.connect(self.thread.deleteLater)
        self.crawler_worker.log_message.connect(self.append_log)
        self.crawler_worker.finished.connect(self.on_task_finished)
        
        self.thread.start()

    def on_task_finished(self):
        self.append_log("="*20 + " 抓取任务结束 " + "="*20)
        self.set_controls_enabled(True)
        self.thread = None 
        self.crawler_worker = None
        # 抓取结束后，重新扫描文件夹并更新按钮状态
        self.populate_source_folders_combo()

    def populate_source_folders_combo(self):
        """扫描output目录，填充可选的数据源文件夹"""
        self.log_text.append("正在刷新数据源列表...")
        self.source_folder_combo.clear()
        
        output_path = os.path.join(project_root, 'output')
        if not os.path.exists(output_path):
            os.makedirs(output_path)
        
        try:
            all_files = os.listdir(output_path)
            raw_folders = [f for f in all_files if f.startswith('raw_md') and os.path.isdir(os.path.join(output_path, f))]
            
            if not raw_folders:
                self.log_text.append("未在 'output' 目录中找到任何 'raw_md' 开头的数据文件夹。")
            else:
                self.source_folder_combo.addItems(sorted(raw_folders))
                self.log_text.append(f"发现 {len(raw_folders)} 个可用数据集。")
        except Exception as e:
            self.log_text.append(f"刷新数据源列表时出错: {e}")
        
        self.update_button_states() # 填充后立即更新按钮状态

    def on_process_ai_clicked(self):
        source_folder = self.source_folder_combo.currentText()
        if not source_folder:
            self.append_log("错误：请先从下拉菜单中选择一个要处理的数据集。")
            return
        
        base_url = self.base_url_input.text()
        api_key = self.api_key_input.text()
        concurrency = self.concurrency_spinbox.value()

        if not api_key or not base_url:
            self.append_log("错误：请先设置API Base URL和API Key。")
            return

        self.set_controls_enabled(False)
        self.log_text.append("\n" + "="*20 + " AI处理任务开始 " + "="*20)

        self.ai_thread = QThread(self)
        self.ai_worker = AiWorker(source_folder, base_url, api_key, concurrency)
        self.ai_worker.moveToThread(self.ai_thread)

        self.ai_thread.started.connect(self.ai_worker.run)
        self.ai_worker.log_message.connect(self.append_log)
        self.ai_worker.finished.connect(self.on_ai_task_finished)
        
        self.ai_worker.finished.connect(self.ai_thread.quit)
        self.ai_worker.finished.connect(self.ai_worker.deleteLater)
        self.ai_thread.finished.connect(self.ai_thread.deleteLater)
        
        self.ai_thread.start()

    def on_ai_task_finished(self):
        self.append_log("="*20 + " AI处理任务结束 " + "="*20)
        self.set_controls_enabled(True)
        self.ai_thread = None
        self.ai_worker = None
        self.update_button_states() # 处理结束后更新按钮状态

    def on_build_html_clicked(self):
        source_folder = self.source_folder_combo.currentText()
        if not source_folder:
            self.append_log("错误：请先从下拉菜单中选择一个要生成网页的数据集。")
            return
            
        # 从原始目录推断出已处理目录的名称
        processed_folder = source_folder.replace('raw_', 'processed_')

        self.set_controls_enabled(False)
        self.log_text.append("\n" + "="*20 + " 生成网页任务开始 " + "="*20)

        self.html_thread = QThread(self)
        self.html_worker = HtmlWorker(processed_folder) # <--- 传递文件夹名
        self.html_worker.moveToThread(self.html_thread)

        self.html_thread.started.connect(self.html_worker.run)
        self.html_worker.log_message.connect(self.append_log)
        self.html_worker.finished.connect(self.on_html_task_finished)

        self.html_worker.finished.connect(self.html_thread.quit)
        self.html_worker.finished.connect(self.html_worker.deleteLater)
        self.html_thread.finished.connect(self.html_thread.deleteLater)

        self.html_thread.start()

    def on_html_task_finished(self):
        self.append_log("="*20 + " 生成网页任务结束 " + "="*20)
        self.set_controls_enabled(True)
        self.html_thread = None
        self.html_worker = None
        self.update_button_states() # 生成结束后更新按钮状态

    def on_preview_clicked(self):
        """启动HTTP服务器并打开浏览器"""
        # 如果已经有一个服务器在运行，先停止它
        if self.server_thread and self.server_thread.isRunning():
            self.append_log("检测到已有预览服务器在运行，将先停止它...")
            self.server_worker.stop()
            self.server_thread.quit()
            self.server_thread.wait() # 等待线程完全停止
            self.append_log("旧服务器已停止。")

        # 检查是否有可用的数据集
        if self.source_folder_combo.count() > 0:
            # --- 核心修复：获取当前选中的文本，而不是第一个 ---
            source_folder_name = self.source_folder_combo.currentText()
            web_output_folder_name = source_folder_name.replace('raw_', 'web_').replace('processed_', 'web_')
            web_dir = os.path.join(project_root, 'output', web_output_folder_name)

            if not os.path.exists(web_dir):
                self.append_log(f"错误：找不到对应的Web目录 '{web_dir}'。")
                return

            self.server_thread = QThread(self)
            self.server_worker = ServerWorker(web_dir)
            self.server_worker.moveToThread(self.server_thread)

            self.server_worker.log_message.connect(self.append_log)
            self.server_worker.server_started.connect(lambda url: webbrowser.open(url))
            
            self.server_thread.started.connect(self.server_worker.run)
            self.server_thread.finished.connect(self.server_worker.deleteLater)

            self.append_log("正在启动本地预览服务器...")
            self.server_thread.start()

    def closeEvent(self, event):
        """重写窗口关闭事件，确保所有后台线程都已停止"""
        self.append_log("正在关闭应用程序...")
        
        # 标记正在关闭，防止新的任务启动
        self.is_closing = True 
        
        # 1. 停止所有可能的工作线程
        threads_to_wait = []
        if self.thread and self.thread.isRunning():
            self.append_log("等待抓取线程结束...")
            threads_to_wait.append(self.thread)
        
        if self.ai_thread and self.ai_thread.isRunning():
            self.append_log("等待AI处理线程结束...")
            threads_to_wait.append(self.ai_thread)
            
        if self.html_thread and self.html_thread.isRunning():
            self.append_log("等待HTML生成线程结束...")
            threads_to_wait.append(self.html_thread)
            
        for t in threads_to_wait:
            t.quit()
            if not t.wait(3000):
                self.append_log(f"一个工作线程未能及时停止。")

        # 2. 停止本地Web服务器
        if self.server_thread and self.server_thread.isRunning():
            self.append_log("正在停止本地服务器...")
            self.server_worker.stop()
            self.server_thread.quit()
            if not self.server_thread.wait(3000):
                self.append_log("服务器线程未能及时停止。")

        # 3. 保存设置
        self.save_settings()
        self.append_log("所有任务完成，应用程序已关闭。")
        
        # 4. 接受关闭事件并退出应用
        event.accept()
        QApplication.instance().quit()

    def update_button_states(self):
        """根据当前选择和状态更新按钮的可用性"""
        selected_folder = self.source_folder_combo.currentText()
        
        if not selected_folder:
            self.process_ai_button.setEnabled(False)
            self.build_html_button.setEnabled(False)
            self.preview_button.setEnabled(False)
            return

        # 只要有数据源可选，就可以进行AI处理
        self.process_ai_button.setEnabled(True)

        # 检查对应的processed文件夹是否存在且不为空，以决定是否可以生成网页
        output_path = os.path.join(project_root, 'output')
        processed_folder_name = selected_folder.replace('raw_', 'processed_')
        processed_folder_path = os.path.join(output_path, processed_folder_name)
        
        can_build_html = False
        if os.path.exists(processed_folder_path) and os.path.isdir(processed_folder_path):
            if len(os.listdir(processed_folder_path)) > 0:
                can_build_html = True

        self.build_html_button.setEnabled(can_build_html)
        
        # 检查对应的web文件夹是否存在且有index.html，以决定是否可以预览
        web_folder_name = selected_folder.replace('raw_', 'web_')
        web_folder_path = os.path.join(output_path, web_folder_name)
        can_preview = os.path.exists(os.path.join(web_folder_path, 'index.html'))
        self.preview_button.setEnabled(can_preview)
        
    def set_controls_enabled(self, enabled):
        """统一设置控件的可用状态"""
        self.mode_combo.setEnabled(enabled)
        self.crawl_count_spinbox.setEnabled(enabled and not self.crawl_all_checkbox.isChecked())
        self.crawl_all_checkbox.setEnabled(enabled)
        self.keyword_input.setEnabled(enabled)
        self.start_button.setEnabled(enabled)
        self.base_url_input.setEnabled(enabled)
        self.api_key_input.setEnabled(enabled)
        self.concurrency_spinbox.setEnabled(enabled)
        
        # 如果正在关闭，则禁用所有按钮
        if hasattr(self, 'is_closing') and self.is_closing:
            enabled = False
            
        if not enabled:
            self.process_ai_button.setEnabled(False)
            self.build_html_button.setEnabled(False)
            self.preview_button.setEnabled(False)
        else:
            self.update_button_states()

    def load_settings(self):
        """加载配置"""
        settings = QSettings("MyCompany", "ZsxqCrawler")
        self.group_id_input.setText(settings.value("group_id", ""))
        self.token_input.setText(settings.value("access_token", ""))
        self.base_url_input.setText(settings.value("base_url", "https://api.deepseek.com"))
        self.api_key_input.setText(settings.value("api_key", ""))
        self.concurrency_spinbox.setValue(int(settings.value("concurrency", 20)))

    def save_settings(self):
        """保存配置"""
        settings = QSettings("MyCompany", "ZsxqCrawler")
        settings.setValue("group_id", self.group_id_input.text())
        settings.setValue("access_token", self.token_input.text())
        settings.setValue("base_url", self.base_url_input.text())
        settings.setValue("api_key", self.api_key_input.text())
        settings.setValue("concurrency", self.concurrency_spinbox.value())

def main():
    app = QApplication(sys.argv)
    # --- 核心修复：禁用最后一个窗口关闭时自动退出程序的行为 ---
    # 这允许我们在closeEvent中执行清理操作而不会立即退出
    app.setQuitOnLastWindowClosed(False) 
    window = MainWindow()
    window.show()
    sys.exit(app.exec())

if __name__ == '__main__':
    main() 