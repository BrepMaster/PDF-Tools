import sys
import os
import webbrowser
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout,
                             QHBoxLayout, QPushButton, QListWidget, QLabel,
                             QFileDialog, QMessageBox, QProgressBar, QListWidgetItem,
                             QGroupBox, QSplitter, QGridLayout, QComboBox,
                             QTabWidget, QSpinBox, QRadioButton, QButtonGroup,
                             QTextEdit)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSettings, QPoint
from PyQt5.QtGui import (QIcon, QPixmap, QColor, QPalette, QDragEnterEvent,
                         QDropEvent, QPainter, QPen, QBrush, QFont)
import PyPDF2
from datetime import datetime
import fitz  # PyMuPDF，用于PDF预览

# 忽略警告
import warnings

warnings.filterwarnings("ignore", category=DeprecationWarning)


class PDFMergerThread(QThread):
    """用于合并PDF的后台线程"""
    progress_updated = pyqtSignal(int, str)
    merge_completed = pyqtSignal(str, int)
    merge_failed = pyqtSignal(str)

    def __init__(self, pdf_files, output_path):
        super().__init__()
        self.pdf_files = pdf_files
        self.output_path = output_path

    def run(self):
        try:
            pdf_merger = PyPDF2.PdfMerger()
            total_files = len(self.pdf_files)

            for i, pdf_file in enumerate(self.pdf_files):
                pdf_merger.append(pdf_file)
                progress = int((i + 1) / total_files * 100)
                file_name = os.path.basename(pdf_file)
                self.progress_updated.emit(progress, f"正在处理: {file_name}")

            with open(self.output_path, 'wb') as output_file:
                pdf_merger.write(output_file)

            pdf_merger.close()

            # 获取合并后的页数
            total_pages = 0
            with open(self.output_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                total_pages = len(pdf_reader.pages)

            self.merge_completed.emit(self.output_path, total_pages)

        except Exception as e:
            self.merge_failed.emit(str(e))


class PDFSplitterThread(QThread):
    """用于拆分PDF的后台线程"""
    progress_updated = pyqtSignal(int, str)
    split_completed = pyqtSignal(list)
    split_failed = pyqtSignal(str)

    def __init__(self, pdf_file, output_folder, split_mode, split_value):
        super().__init__()
        self.pdf_file = pdf_file
        self.output_folder = output_folder
        self.split_mode = split_mode  # 'page' 或 'range'
        self.split_value = split_value  # 每几页或页数范围列表

    def run(self):
        try:
            with open(self.pdf_file, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                total_pages = len(pdf_reader.pages)
                output_files = []

                if self.split_mode == 'page':
                    # 按每几页拆分
                    pages_per_file = self.split_value
                    num_files = (total_pages + pages_per_file - 1) // pages_per_file

                    for i in range(num_files):
                        start_page = i * pages_per_file
                        end_page = min((i + 1) * pages_per_file, total_pages)

                        pdf_writer = PyPDF2.PdfWriter()
                        for page_num in range(start_page, end_page):
                            pdf_writer.add_page(pdf_reader.pages[page_num])

                        output_filename = f"{os.path.splitext(os.path.basename(self.pdf_file))[0]}_part{i + 1:03d}.pdf"
                        output_path = os.path.join(self.output_folder, output_filename)

                        with open(output_path, 'wb') as output_file:
                            pdf_writer.write(output_file)

                        output_files.append(output_path)

                        progress = int((i + 1) / num_files * 100)
                        self.progress_updated.emit(progress, f"正在拆分: 第{i + 1}/{num_files}部分")

                elif self.split_mode == 'range':
                    # 按页数范围拆分
                    for i, page_range in enumerate(self.split_value):
                        pdf_writer = PyPDF2.PdfWriter()

                        for page_num in page_range:
                            if 0 <= page_num < total_pages:
                                pdf_writer.add_page(pdf_reader.pages[page_num])

                        if len(pdf_writer.pages) > 0:
                            output_filename = f"{os.path.splitext(os.path.basename(self.pdf_file))[0]}_part{i + 1:03d}.pdf"
                            output_path = os.path.join(self.output_folder, output_filename)

                            with open(output_path, 'wb') as output_file:
                                pdf_writer.write(output_file)

                            output_files.append(output_path)

                        progress = int((i + 1) / len(self.split_value) * 100)
                        self.progress_updated.emit(progress, f"正在拆分: 第{i + 1}/{len(self.split_value)}个范围")

                self.split_completed.emit(output_files)

        except Exception as e:
            self.split_failed.emit(str(e))


class ModernPDFListWidget(QListWidget):
    """自定义的PDF列表控件"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragEnabled(True)
        self.setDragDropMode(QListWidget.InternalMove)
        self.setSelectionMode(QListWidget.ExtendedSelection)

    def dragEnterEvent(self, event: QDragEnterEvent):
        if event.mimeData().hasUrls():
            event.accept()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event: QDropEvent):
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            pdf_files = []
            for url in urls:
                file_path = url.toLocalFile()
                if file_path.lower().endswith('.pdf'):
                    pdf_files.append(file_path)

            if pdf_files:
                self.parent().add_pdf_files_direct(pdf_files)
        else:
            super().dropEvent(event)


class PDFToolsApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.pdf_files = []
        self.current_tab = "merge"  # "merge" 或 "split"
        self.settings = QSettings("PDFTools", "PDFMerger")

        # 拆分功能相关的变量
        self.split_file_path = None
        self.output_folder_path = None

        self.initUI()
        self.apply_stylesheet()

    def initUI(self):
        """初始化用户界面"""
        self.setWindowTitle('PDF工具 - 合并与拆分')
        self.setGeometry(100, 100, 1000, 700)

        # 设置应用图标
        self.setWindowIcon(self.create_icon())

        # 创建中心部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        # 主布局
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)
        central_widget.setLayout(main_layout)

        # 创建标签页
        self.tab_widget = QTabWidget()

        # 合并标签页
        self.merge_tab = self.create_merge_tab()
        self.tab_widget.addTab(self.merge_tab, "PDF合并")

        # 拆分标签页
        self.split_tab = self.create_split_tab()
        self.tab_widget.addTab(self.split_tab, "PDF拆分")

        main_layout.addWidget(self.tab_widget, 1)

        # 底部进度条和状态栏
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        self.progress_bar.setTextVisible(True)
        main_layout.addWidget(self.progress_bar)

        # 创建状态栏
        self.statusBar().showMessage("就绪")

        # 连接信号
        self.connect_signals()

        # 更新按钮状态
        self.update_button_state()

        # 应用保存的窗口状态
        self.restore_window_state()

    def create_icon(self):
        """创建简单的红色PDF文档图标"""
        icon = QIcon()

        sizes = [16, 24, 32, 48, 64, 128, 256]

        for size in sizes:
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)

            # 红色PDF图标
            red_color = QColor(220, 50, 50)

            # 绘制文档形状
            margin = size * 0.15
            doc_width = size - 2 * margin
            doc_height = doc_width * 1.2  # 略高的矩形

            # 文档主体
            painter.setBrush(QBrush(red_color))
            painter.setPen(QPen(red_color.darker(130), max(1, size * 0.02)))
            painter.drawRoundedRect(int(margin), int(margin),
                                    int(doc_width), int(doc_height),
                                    int(size * 0.1), int(size * 0.1))

            # 文档折角
            fold_size = min(doc_width * 0.3, doc_height * 0.3)
            painter.setBrush(QBrush(red_color.darker(120)))
            fold_points = [
                QPoint(int(margin + doc_width - fold_size), int(margin)),
                QPoint(int(margin + doc_width), int(margin)),
                QPoint(int(margin + doc_width), int(margin + fold_size))
            ]
            painter.drawPolygon(fold_points)

            # 在中心绘制白色"P"
            painter.setPen(QPen(Qt.white, max(1, size * 0.02)))
            font_size = int(size * 0.3)
            font = QFont("Arial", font_size, QFont.Bold)
            painter.setFont(font)
            text = "P"
            text_rect = painter.fontMetrics().boundingRect(text)
            text_x = int((size - text_rect.width()) / 2)
            text_y = int((size + text_rect.height()) / 2)
            painter.drawText(text_x, text_y, text)

            painter.end()
            icon.addPixmap(pixmap)

        return icon

    def create_merge_tab(self):
        """创建合并标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # 创建分割器
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        # 左侧面板 - 文件管理
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.setSpacing(10)

        # 文件操作按钮
        button_layout = QHBoxLayout()

        self.add_button = self.create_styled_button("添加文件", "#3498db", "📄")
        self.add_folder_button = self.create_styled_button("添加文件夹", "#9b59b6", "📁")
        self.remove_button = self.create_styled_button("移除选中", "#e74c3c", "❌")
        self.clear_button = self.create_styled_button("清空列表", "#f39c12", "🗑️")

        button_layout.addWidget(self.add_button)
        button_layout.addWidget(self.add_folder_button)
        button_layout.addWidget(self.remove_button)
        button_layout.addWidget(self.clear_button)

        left_layout.addLayout(button_layout)

        # 排序选项
        sort_group = QGroupBox("排序方式")
        sort_layout = QHBoxLayout()

        self.sort_combo = QComboBox()
        self.sort_combo.addItem("手动排序（拖放调整）", "manual")
        self.sort_combo.addItem("按文件名升序", "name_asc")
        self.sort_combo.addItem("按文件名降序", "name_desc")
        self.sort_combo.addItem("按文件大小升序", "size_asc")
        self.sort_combo.addItem("按文件大小降序", "size_desc")
        self.sort_combo.addItem("按文件页数升序", "pages_asc")
        self.sort_combo.addItem("按文件页数降序", "pages_desc")

        self.apply_sort_button = self.create_styled_button("应用排序", "#2ecc71", "🔀")

        sort_layout.addWidget(self.sort_combo)
        sort_layout.addWidget(self.apply_sort_button)

        sort_group.setLayout(sort_layout)
        left_layout.addWidget(sort_group)

        # 文件列表
        list_group = QGroupBox("待合并文件列表")
        list_layout = QVBoxLayout()
        list_layout.setSpacing(5)

        self.file_list = ModernPDFListWidget()
        self.file_list.setAlternatingRowColors(True)
        self.file_list.setMinimumHeight(300)
        list_layout.addWidget(self.file_list, 1)

        # 文件计数
        self.file_count_label = QLabel("0 个文件")
        self.file_count_label.setAlignment(Qt.AlignCenter)
        list_layout.addWidget(self.file_count_label)

        list_group.setLayout(list_layout)
        left_layout.addWidget(list_group, 1)

        # 顺序调整按钮
        order_layout = QHBoxLayout()
        self.move_up_button = self.create_styled_button("上移", "#3498db", "⬆")
        self.move_down_button = self.create_styled_button("下移", "#3498db", "⬇")
        self.move_top_button = self.create_styled_button("置顶", "#9b59b6", "⏫")
        self.move_bottom_button = self.create_styled_button("置底", "#9b59b6", "⏬")

        order_layout.addWidget(self.move_up_button)
        order_layout.addWidget(self.move_down_button)
        order_layout.addWidget(self.move_top_button)
        order_layout.addWidget(self.move_bottom_button)

        left_layout.addLayout(order_layout)

        # 合并按钮
        self.merge_button = self.create_styled_button("开始合并", "#2c3e50", "🔗")
        self.merge_button.setStyleSheet("""
            QPushButton {
                background-color: #2c3e50;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #1a252f;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
                color: #bdc3c7;
            }
        """)
        left_layout.addWidget(self.merge_button)

        # 右侧面板 - 预览
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(10)

        # 预览区域
        preview_group = QGroupBox("PDF预览")
        preview_layout = QVBoxLayout()

        self.preview_label = QLabel("选择文件进行预览")
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setMinimumHeight(450)
        self.preview_label.setStyleSheet("""
            QLabel {
                background-color: #f8f9fa;
                border: 2px dashed #dee2e6;
                border-radius: 8px;
                padding: 20px;
                color: #6c757d;
                font-size: 14px;
            }
        """)

        preview_layout.addWidget(self.preview_label, 1)

        # 预览信息
        self.preview_info = QLabel("")
        self.preview_info.setAlignment(Qt.AlignCenter)
        preview_layout.addWidget(self.preview_info)

        preview_group.setLayout(preview_layout)
        right_layout.addWidget(preview_group, 1)

        # 添加面板到分割器
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([450, 550])

        return tab

    def create_split_tab(self):
        """创建拆分标签页"""
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(5, 5, 5, 5)
        layout.setSpacing(10)

        # 创建分割器
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        # 左侧面板 - 文件选择和设置
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(5, 5, 5, 5)
        left_layout.setSpacing(10)

        # 文件选择
        file_group = QGroupBox("选择要拆分的PDF文件")
        file_layout = QVBoxLayout()

        self.split_file_button = self.create_styled_button("选择PDF文件", "#3498db", "📄")
        file_layout.addWidget(self.split_file_button)

        self.split_file_label = QLabel("未选择文件")
        self.split_file_label.setWordWrap(True)
        self.split_file_label.setStyleSheet("""
            QLabel {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 6px;
                padding: 10px;
                color: #6c757d;
                font-size: 13px;
            }
        """)
        file_layout.addWidget(self.split_file_label)

        file_group.setLayout(file_layout)
        left_layout.addWidget(file_group)

        # 文件信息
        info_group = QGroupBox("文件信息")
        info_layout = QVBoxLayout()

        self.split_info_label = QLabel("请先选择PDF文件")
        self.split_info_label.setWordWrap(True)
        info_layout.addWidget(self.split_info_label)

        info_group.setLayout(info_layout)
        left_layout.addWidget(info_group)

        # 拆分模式选择
        mode_group = QGroupBox("拆分模式")
        mode_layout = QVBoxLayout()

        self.split_mode_group = QButtonGroup(self)

        self.mode_every_page = QRadioButton("按每几页拆分")
        self.mode_every_page.setChecked(True)
        self.split_mode_group.addButton(self.mode_every_page)
        mode_layout.addWidget(self.mode_every_page)

        self.mode_page_ranges = QRadioButton("按页数范围拆分")
        self.split_mode_group.addButton(self.mode_page_ranges)
        mode_layout.addWidget(self.mode_page_ranges)

        mode_group.setLayout(mode_layout)
        left_layout.addWidget(mode_group)

        # 拆分设置
        settings_group = QGroupBox("拆分设置")
        settings_layout = QVBoxLayout()

        # 每几页设置
        self.every_page_widget = QWidget()
        every_page_layout = QHBoxLayout(self.every_page_widget)
        every_page_layout.setContentsMargins(0, 0, 0, 0)

        self.pages_per_file_label = QLabel("每")
        self.pages_per_file_spin = QSpinBox()
        self.pages_per_file_spin.setMinimum(1)
        self.pages_per_file_spin.setMaximum(999)
        self.pages_per_file_spin.setValue(1)
        self.pages_per_file_spin.setSuffix("页")

        every_page_layout.addWidget(self.pages_per_file_label)
        every_page_layout.addWidget(self.pages_per_file_spin)
        every_page_layout.addStretch()

        settings_layout.addWidget(self.every_page_widget)

        # 页数范围设置
        self.page_ranges_widget = QWidget()
        page_ranges_layout = QVBoxLayout(self.page_ranges_widget)
        page_ranges_layout.setContentsMargins(0, 0, 0, 0)

        self.page_ranges_label = QLabel("输入页数范围，每行一个范围，如：\n1-5\n6-10\n或单个页码：\n15")
        self.page_ranges_label.setStyleSheet("color: #6c757d; font-size: 12px;")
        page_ranges_layout.addWidget(self.page_ranges_label)

        self.page_ranges_text = QTextEdit()
        self.page_ranges_text.setMaximumHeight(100)
        self.page_ranges_text.setPlaceholderText("例如：\n1-10\n11-20\n21-30")
        page_ranges_layout.addWidget(self.page_ranges_text)

        settings_layout.addWidget(self.page_ranges_widget)
        self.page_ranges_widget.setVisible(False)

        settings_group.setLayout(settings_layout)
        left_layout.addWidget(settings_group)

        # 输出设置
        output_group = QGroupBox("输出设置")
        output_layout = QVBoxLayout()

        self.output_folder_button = self.create_styled_button("选择输出文件夹", "#9b59b6", "📁")
        output_layout.addWidget(self.output_folder_button)

        self.output_folder_label = QLabel("未选择输出文件夹")
        self.output_folder_label.setWordWrap(True)
        self.output_folder_label.setStyleSheet("""
            QLabel {
                background-color: #f8f9fa;
                border: 1px solid #dee2e6;
                border-radius: 6px;
                padding: 10px;
                color: #6c757d;
                font-size: 13px;
            }
        """)
        output_layout.addWidget(self.output_folder_label)

        output_group.setLayout(output_layout)
        left_layout.addWidget(output_group)

        # 拆分按钮
        self.split_button = self.create_styled_button("开始拆分", "#e74c3c", "✂️")
        self.split_button.setStyleSheet("""
            QPushButton {
                background-color: #e74c3c;
                color: white;
                border: none;
                padding: 12px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #c0392b;
            }
            QPushButton:disabled {
                background-color: #95a5a6;
                color: #bdc3c7;
            }
        """)
        left_layout.addWidget(self.split_button)

        left_layout.addStretch()

        # 右侧面板 - 预览
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(5, 5, 5, 5)
        right_layout.setSpacing(10)

        # 预览区域
        split_preview_group = QGroupBox("PDF预览")
        split_preview_layout = QVBoxLayout()

        self.split_preview_label = QLabel("选择文件进行预览")
        self.split_preview_label.setAlignment(Qt.AlignCenter)
        self.split_preview_label.setMinimumHeight(500)
        self.split_preview_label.setStyleSheet("""
            QLabel {
                background-color: #f8f9fa;
                border: 2px dashed #dee2e6;
                border-radius: 8px;
                padding: 20px;
                color: #6c757d;
                font-size: 14px;
            }
        """)

        split_preview_layout.addWidget(self.split_preview_label, 1)

        # 预览信息
        self.split_preview_info = QLabel("")
        self.split_preview_info.setAlignment(Qt.AlignCenter)
        split_preview_layout.addWidget(self.split_preview_info)

        split_preview_group.setLayout(split_preview_layout)
        right_layout.addWidget(split_preview_group, 1)

        # 添加面板到分割器
        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([400, 600])

        return tab

    def create_styled_button(self, text, color, icon_text=""):
        """创建样式化按钮"""
        button = QPushButton(text)
        if icon_text:
            button.setText(f"{icon_text} {text}")

        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {color};
                color: white;
                border: none;
                padding: 8px;
                border-radius: 6px;
                font-weight: bold;
                font-size: 12px;
                margin: 2px;
            }}
            QPushButton:hover {{
                background-color: {self.darken_color(color)};
            }}
            QPushButton:pressed {{
                background-color: {self.darken_color(color, 40)};
            }}
            QPushButton:disabled {{
                background-color: #95a5a6;
                color: #bdc3c7;
            }}
        """)

        return button

    def darken_color(self, color, amount=20):
        """使颜色变暗"""
        try:
            color_obj = QColor(color)
            return color_obj.darker(100 + amount).name()
        except:
            return color

    def apply_stylesheet(self):
        """应用全局样式表"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #f5f7fa;
            }
            QGroupBox {
                font-weight: bold;
                border: 2px solid #dee2e6;
                border-radius: 8px;
                margin-top: 10px;
                padding-top: 10px;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 5px 0 5px;
            }
            QListWidget {
                background-color: white;
                border: 1px solid #dee2e6;
                border-radius: 6px;
                padding: 5px;
                font-size: 13px;
            }
            QListWidget::item {
                padding: 8px;
                border-bottom: 1px solid #f1f1f1;
            }
            QListWidget::item:selected {
                background-color: #d6eaf8;
                color: #2c3e50;
                border-radius: 4px;
            }
            QListWidget::item:hover {
                background-color: #f8f9fa;
            }
            QProgressBar {
                border: 1px solid #dee2e6;
                border-radius: 6px;
                text-align: center;
                height: 24px;
            }
            QProgressBar::chunk {
                background-color: #2ecc71;
                border-radius: 5px;
            }
            QComboBox {
                padding: 5px;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background-color: white;
            }
            QComboBox:hover {
                border-color: #3498db;
            }
            QComboBox::drop-down {
                border: none;
            }
            QSpinBox {
                padding: 5px;
                border: 1px solid #dee2e6;
                border-radius: 4px;
                background-color: white;
            }
            QTextEdit {
                border: 1px solid #dee2e6;
                border-radius: 4px;
                padding: 5px;
                background-color: white;
            }
            QRadioButton {
                padding: 5px;
            }
            QRadioButton::indicator {
                width: 16px;
                height: 16px;
            }
        """)

    def connect_signals(self):
        """连接信号和槽"""
        # 合并标签页信号
        self.add_button.clicked.connect(self.add_pdf_files)
        self.add_folder_button.clicked.connect(self.add_pdf_folder)
        self.remove_button.clicked.connect(self.remove_selected_pdf)
        self.clear_button.clicked.connect(self.clear_pdf_list)
        self.merge_button.clicked.connect(self.merge_pdfs)
        self.apply_sort_button.clicked.connect(self.apply_sorting)

        self.move_up_button.clicked.connect(self.move_item_up)
        self.move_down_button.clicked.connect(self.move_item_down)
        self.move_top_button.clicked.connect(self.move_item_top)
        self.move_bottom_button.clicked.connect(self.move_item_bottom)

        self.file_list.itemSelectionChanged.connect(self.on_selection_changed)
        self.file_list.itemDoubleClicked.connect(self.on_item_double_clicked)

        # 拆分标签页信号
        self.split_file_button.clicked.connect(self.select_split_file)
        self.mode_every_page.toggled.connect(self.on_split_mode_changed)
        self.output_folder_button.clicked.connect(self.select_output_folder)
        self.split_button.clicked.connect(self.split_pdf)

        # 标签页切换信号
        self.tab_widget.currentChanged.connect(self.on_tab_changed)

    def on_tab_changed(self, index):
        """标签页切换时更新当前标签"""
        if index == 0:
            self.current_tab = "merge"
        else:
            self.current_tab = "split"

    # ========== 合并功能相关方法 ==========

    def add_pdf_files(self):
        """添加PDF文件"""
        files, _ = QFileDialog.getOpenFileNames(
            self,
            '选择PDF文件',
            self.settings.value("last_dir", ""),
            'PDF文件 (*.pdf)'
        )

        if files:
            self.settings.setValue("last_dir", os.path.dirname(files[0]))
            self.add_pdf_files_direct(files)

    def add_pdf_files_direct(self, files):
        """直接添加PDF文件（用于拖放）"""
        new_files = []
        for file in files:
            if file not in self.pdf_files:
                new_files.append(file)

        if new_files:
            self.pdf_files.extend(new_files)
            self.update_file_list()
            self.update_button_state()
            self.statusBar().showMessage(f'已添加 {len(new_files)} 个PDF文件', 3000)

    def add_pdf_folder(self):
        """添加文件夹中的所有PDF文件"""
        folder = QFileDialog.getExistingDirectory(
            self,
            '选择文件夹',
            self.settings.value("last_dir", "")
        )

        if folder:
            self.settings.setValue("last_dir", folder)
            pdf_files = []
            for root, dirs, files in os.walk(folder):
                for file in files:
                    if file.lower().endswith('.pdf'):
                        pdf_files.append(os.path.join(root, file))

            if pdf_files:
                self.add_pdf_files_direct(pdf_files)

    def remove_selected_pdf(self):
        """移除选中的PDF文件"""
        selected_items = self.file_list.selectedItems()
        if not selected_items:
            QMessageBox.information(self, '提示', '请先选择要移除的文件')
            return

        for item in selected_items:
            file_path = item.data(Qt.UserRole)
            if file_path in self.pdf_files:
                self.pdf_files.remove(file_path)

        self.update_file_list()
        self.update_button_state()
        self.statusBar().showMessage(f'已移除 {len(selected_items)} 个文件', 3000)

    def clear_pdf_list(self):
        """清空PDF文件列表"""
        if not self.pdf_files:
            return

        reply = QMessageBox.question(
            self,
            '确认清空',
            f'确定要清空所有 {len(self.pdf_files)} 个PDF文件吗？',
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )

        if reply == QMessageBox.Yes:
            self.pdf_files.clear()
            self.update_file_list()
            self.update_button_state()
            self.statusBar().showMessage('已清空所有PDF文件', 3000)

    def apply_sorting(self):
        """应用排序"""
        if not self.pdf_files:
            return

        sort_type = self.sort_combo.currentData()

        if sort_type == "manual":
            QMessageBox.information(self, '提示', '请使用拖放方式手动调整顺序')
            return

        # 根据排序类型排序
        if sort_type == "name_asc":
            self.pdf_files.sort(key=lambda x: os.path.basename(x).lower())
        elif sort_type == "name_desc":
            self.pdf_files.sort(key=lambda x: os.path.basename(x).lower(), reverse=True)
        elif sort_type == "size_asc":
            self.pdf_files.sort(key=lambda x: os.path.getsize(x) if os.path.exists(x) else 0)
        elif sort_type == "size_desc":
            self.pdf_files.sort(key=lambda x: os.path.getsize(x) if os.path.exists(x) else 0, reverse=True)
        elif sort_type == "pages_asc":
            self.pdf_files.sort(key=lambda x: self.get_pdf_page_count(x))
        elif sort_type == "pages_desc":
            self.pdf_files.sort(key=lambda x: self.get_pdf_page_count(x), reverse=True)

        # 更新显示
        self.update_file_list()
        self.statusBar().showMessage(f'已按{self.sort_combo.currentText()}排序', 3000)

    def move_item_up(self):
        """上移选中的项目"""
        current_row = self.file_list.currentRow()
        if current_row > 0:
            self.pdf_files[current_row], self.pdf_files[current_row - 1] = \
                self.pdf_files[current_row - 1], self.pdf_files[current_row]
            self.update_file_list()
            self.file_list.setCurrentRow(current_row - 1)

    def move_item_down(self):
        """下移选中的项目"""
        current_row = self.file_list.currentRow()
        if current_row < len(self.pdf_files) - 1:
            self.pdf_files[current_row], self.pdf_files[current_row + 1] = \
                self.pdf_files[current_row + 1], self.pdf_files[current_row]
            self.update_file_list()
            self.file_list.setCurrentRow(current_row + 1)

    def move_item_top(self):
        """将选中项目移动到顶部"""
        current_row = self.file_list.currentRow()
        if current_row > 0:
            item = self.pdf_files.pop(current_row)
            self.pdf_files.insert(0, item)
            self.update_file_list()
            self.file_list.setCurrentRow(0)

    def move_item_bottom(self):
        """将选中项目移动到底部"""
        current_row = self.file_list.currentRow()
        if current_row < len(self.pdf_files) - 1:
            item = self.pdf_files.pop(current_row)
            self.pdf_files.append(item)
            self.update_file_list()
            self.file_list.setCurrentRow(len(self.pdf_files) - 1)

    def update_file_list(self):
        """更新文件列表显示"""
        self.file_list.clear()
        total_size = 0
        total_pages = 0

        for i, file_path in enumerate(self.pdf_files):
            file_name = os.path.basename(file_path)
            try:
                file_size = os.path.getsize(file_path)
                total_size += file_size
                size_str = self.format_file_size(file_size)

                # 获取PDF页数
                pages = self.get_pdf_page_count(file_path)
                total_pages += pages
                pages_str = f"{pages}页" if pages > 0 else ""

                item_text = f"{i + 1}. {file_name} ({size_str}, {pages_str})"
                item = QListWidgetItem(item_text)
                item.setData(Qt.UserRole, file_path)
                self.file_list.addItem(item)

            except:
                item = QListWidgetItem(f"{i + 1}. {file_name} (无法读取)")
                item.setData(Qt.UserRole, file_path)
                self.file_list.addItem(item)

        # 更新计数标签
        total_size_str = self.format_file_size(total_size)
        self.file_count_label.setText(f"{len(self.pdf_files)} 个文件 | 总大小: {total_size_str} | 总页数: {total_pages}页")

    def merge_pdfs(self):
        """合并PDF文件"""
        if not self.pdf_files:
            QMessageBox.warning(self, '警告', '请先添加PDF文件')
            return

        # 生成默认文件名
        default_name = f"合并_{datetime.now().strftime('%Y%m%d_%H%M%S')}.pdf"

        output_path, _ = QFileDialog.getSaveFileName(
            self,
            '保存合并后的PDF',
            os.path.join(self.settings.value("last_dir", ""), default_name),
            'PDF文件 (*.pdf)'
        )

        if not output_path:
            return

        # 确保文件扩展名为.pdf
        if not output_path.lower().endswith('.pdf'):
            output_path += '.pdf'

        self.settings.setValue("last_dir", os.path.dirname(output_path))

        # 禁用按钮并显示进度条
        self.set_ui_enabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self.statusBar().showMessage('正在合并PDF...')

        # 创建并启动合并线程
        self.merger_thread = PDFMergerThread(self.pdf_files, output_path)
        self.merger_thread.progress_updated.connect(self.update_progress)
        self.merger_thread.merge_completed.connect(self.merge_success)
        self.merger_thread.merge_failed.connect(self.merge_failed)
        self.merger_thread.start()

    def merge_success(self, output_path, total_pages):
        """合并成功处理"""
        self.progress_bar.setVisible(False)
        self.set_ui_enabled(True)

        # 显示成功消息
        file_name = os.path.basename(output_path)
        file_size = os.path.getsize(output_path)
        file_size_str = self.format_file_size(file_size)

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle('合并成功')
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(f'PDF文件已成功合并！')
        msg_box.setInformativeText(
            f'文件名: {file_name}\n'
            f'文件大小: {file_size_str}\n'
            f'总页数: {total_pages}页'
        )

        # 添加自定义按钮
        open_btn = msg_box.addButton('打开文件', QMessageBox.ActionRole)
        open_folder_btn = msg_box.addButton('打开文件夹', QMessageBox.ActionRole)
        close_btn = msg_box.addButton('关闭', QMessageBox.RejectRole)

        msg_box.exec_()

        clicked_button = msg_box.clickedButton()

        if clicked_button == open_btn:
            self.open_file(output_path)
        elif clicked_button == open_folder_btn:
            self.open_folder(output_path)

        self.statusBar().showMessage('PDF合并完成！', 5000)

    def merge_failed(self, error_message):
        """合并失败处理"""
        self.progress_bar.setVisible(False)
        self.set_ui_enabled(True)

        QMessageBox.critical(
            self,
            '合并失败',
            f'合并PDF时发生错误:\n{error_message}'
        )

        self.statusBar().showMessage('合并失败', 5000)

    # ========== 拆分功能相关方法 ==========

    def select_split_file(self):
        """选择要拆分的PDF文件"""
        file, _ = QFileDialog.getOpenFileName(
            self,
            '选择要拆分的PDF文件',
            self.settings.value("last_dir", ""),
            'PDF文件 (*.pdf)'
        )

        if file:
            self.settings.setValue("last_dir", os.path.dirname(file))
            self.split_file_path = file
            self.split_file_label.setText(os.path.basename(file))

            # 获取文件信息
            try:
                file_size = os.path.getsize(file)
                size_str = self.format_file_size(file_size)

                with open(file, 'rb') as f:
                    pdf_reader = PyPDF2.PdfReader(f)
                    total_pages = len(pdf_reader.pages)

                modified = datetime.fromtimestamp(os.path.getmtime(file)).strftime('%Y-%m-%d %H:%M')

                info_text = f"文件名: {os.path.basename(file)}\n"
                info_text += f"文件大小: {size_str}\n"
                info_text += f"总页数: {total_pages}页\n"
                info_text += f"修改时间: {modified}"

                self.split_info_label.setText(info_text)

                # 更新页数范围输入框的提示
                self.page_ranges_label.setText(f"总页数: {total_pages}页\n输入页数范围，每行一个范围，如：\n1-5\n6-10\n或单个页码：\n15")
                self.pages_per_file_spin.setMaximum(total_pages)

                # 更新预览
                self.update_split_preview(file)

                # 更新按钮状态
                self.update_split_button_state()

            except Exception as e:
                self.split_info_label.setText(f"无法读取文件信息: {str(e)}")

    def on_split_mode_changed(self):
        """拆分模式切换"""
        if self.mode_every_page.isChecked():
            self.every_page_widget.setVisible(True)
            self.page_ranges_widget.setVisible(False)
        else:
            self.every_page_widget.setVisible(False)
            self.page_ranges_widget.setVisible(True)

    def select_output_folder(self):
        """选择输出文件夹"""
        folder = QFileDialog.getExistingDirectory(
            self,
            '选择输出文件夹',
            self.settings.value("last_dir", "")
        )

        if folder:
            self.output_folder_path = folder
            self.output_folder_label.setText(folder)
            self.update_split_button_state()

    def parse_page_ranges(self, text, total_pages):
        """解析页数范围文本"""
        ranges = []
        lines = text.strip().split('\n')

        for line in lines:
            line = line.strip()
            if not line:
                continue

            if '-' in line:
                # 范围格式: 1-10
                try:
                    start, end = line.split('-')
                    start = int(start.strip()) - 1  # 转换为0-based索引
                    end = int(end.strip()) - 1  # 转换为0-based索引

                    if start < 0:
                        start = 0
                    if end >= total_pages:
                        end = total_pages - 1
                    if start <= end:
                        ranges.append(list(range(start, end + 1)))
                except:
                    pass
            else:
                # 单个页码
                try:
                    page = int(line.strip()) - 1  # 转换为0-based索引
                    if 0 <= page < total_pages:
                        ranges.append([page])
                except:
                    pass

        return ranges

    def split_pdf(self):
        """拆分PDF文件"""
        if not self.split_file_path:
            QMessageBox.warning(self, '警告', '请先选择要拆分的PDF文件')
            return

        if not self.output_folder_path:
            QMessageBox.warning(self, '警告', '请先选择输出文件夹')
            return

        try:
            # 获取总页数
            with open(self.split_file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                total_pages = len(pdf_reader.pages)

            split_mode = 'page' if self.mode_every_page.isChecked() else 'range'
            split_value = None

            if split_mode == 'page':
                pages_per_file = self.pages_per_file_spin.value()
                if pages_per_file <= 0:
                    QMessageBox.warning(self, '警告', '每几页必须大于0')
                    return
                split_value = pages_per_file

            else:  # range模式
                page_ranges_text = self.page_ranges_text.toPlainText()
                if not page_ranges_text.strip():
                    QMessageBox.warning(self, '警告', '请输入页数范围')
                    return

                split_value = self.parse_page_ranges(page_ranges_text, total_pages)
                if not split_value:
                    QMessageBox.warning(self, '警告', '没有有效的页数范围')
                    return

            # 确认拆分
            if split_mode == 'page':
                num_parts = (total_pages + pages_per_file - 1) // pages_per_file
                confirm_text = f"将拆分为 {num_parts} 个文件，每个文件 {pages_per_file} 页"
            else:
                confirm_text = f"将拆分为 {len(split_value)} 个文件，按指定的页数范围拆分"

            reply = QMessageBox.question(
                self,
                '确认拆分',
                f'{confirm_text}\n是否继续？',
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.No
            )

            if reply != QMessageBox.Yes:
                return

            # 禁用按钮并显示进度条
            self.set_ui_enabled(False)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self.statusBar().showMessage('正在拆分PDF...')

            # 创建并启动拆分线程
            self.splitter_thread = PDFSplitterThread(
                self.split_file_path,
                self.output_folder_path,
                split_mode,
                split_value
            )
            self.splitter_thread.progress_updated.connect(self.update_progress)
            self.splitter_thread.split_completed.connect(self.split_success)
            self.splitter_thread.split_failed.connect(self.split_failed)
            self.splitter_thread.start()

        except Exception as e:
            QMessageBox.critical(self, '错误', f'准备拆分时发生错误:\n{str(e)}')

    def split_success(self, output_files):
        """拆分成功处理"""
        self.progress_bar.setVisible(False)
        self.set_ui_enabled(True)

        # 显示成功消息
        msg_box = QMessageBox(self)
        msg_box.setWindowTitle('拆分成功')
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(f'PDF文件已成功拆分！')
        msg_box.setInformativeText(
            f'共生成 {len(output_files)} 个文件\n'
            f'保存位置: {self.output_folder_path}'
        )

        # 添加自定义按钮
        open_folder_btn = msg_box.addButton('打开文件夹', QMessageBox.ActionRole)
        close_btn = msg_box.addButton('关闭', QMessageBox.RejectRole)

        msg_box.exec_()

        clicked_button = msg_box.clickedButton()

        if clicked_button == open_folder_btn:
            self.open_folder(self.output_folder_path)

        self.statusBar().showMessage('PDF拆分完成！', 5000)

    def split_failed(self, error_message):
        """拆分失败处理"""
        self.progress_bar.setVisible(False)
        self.set_ui_enabled(True)

        QMessageBox.critical(
            self,
            '拆分失败',
            f'拆分PDF时发生错误:\n{error_message}'
        )

        self.statusBar().showMessage('拆分失败', 5000)

    # ========== 通用方法 ==========

    def format_file_size(self, size_bytes):
        """格式化文件大小"""
        for unit in ['B', 'KB', 'MB', 'GB']:
            if size_bytes < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} TB"

    def get_pdf_page_count(self, file_path):
        """获取PDF页数"""
        try:
            with open(file_path, 'rb') as f:
                pdf_reader = PyPDF2.PdfReader(f)
                return len(pdf_reader.pages)
        except:
            return 0

    def update_split_button_state(self):
        """更新拆分按钮状态"""
        has_file = bool(self.split_file_path)
        has_folder = bool(self.output_folder_path)
        self.split_button.setEnabled(has_file and has_folder)

    def on_selection_changed(self):
        """选中项变化时更新预览"""
        selected_items = self.file_list.selectedItems()
        if len(selected_items) == 1:
            file_path = selected_items[0].data(Qt.UserRole)
            self.update_preview(file_path)
        else:
            self.preview_label.setText("选择单个文件进行预览")
            self.preview_info.setText("")

    def on_item_double_clicked(self, item):
        """双击项目时在文件管理器中打开"""
        file_path = item.data(Qt.UserRole)
        if os.path.exists(file_path):
            os.startfile(os.path.dirname(file_path))

    def update_preview(self, file_path):
        """更新PDF预览"""
        try:
            # 使用PyMuPDF获取PDF预览
            doc = fitz.open(file_path)
            page = doc[0]
            zoom = 1.5
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # 转换为QPixmap
            img_data = pix.tobytes("ppm")
            pixmap = QPixmap()
            pixmap.loadFromData(img_data)

            # 缩放以适应标签
            scaled_pixmap = pixmap.scaled(400, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.preview_label.setPixmap(scaled_pixmap)

            # 显示文件信息
            file_size = os.path.getsize(file_path)
            size_str = self.format_file_size(file_size)
            pages = len(doc)
            modified = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M')

            info_text = f"{os.path.basename(file_path)}\n大小: {size_str} | 页数: {pages}页\n修改时间: {modified}"
            self.preview_info.setText(info_text)

            doc.close()

        except Exception as e:
            self.preview_label.setText(f"无法预览PDF文件\n错误: {str(e)}")
            self.preview_info.setText("")

    def update_split_preview(self, file_path):
        """更新拆分标签页的预览"""
        try:
            # 使用PyMuPDF获取PDF预览
            doc = fitz.open(file_path)
            page = doc[0]
            zoom = 1.5
            mat = fitz.Matrix(zoom, zoom)
            pix = page.get_pixmap(matrix=mat)

            # 转换为QPixmap
            img_data = pix.tobytes("ppm")
            pixmap = QPixmap()
            pixmap.loadFromData(img_data)

            # 缩放以适应标签
            scaled_pixmap = pixmap.scaled(400, 500, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            self.split_preview_label.setPixmap(scaled_pixmap)

            # 显示文件信息
            file_size = os.path.getsize(file_path)
            size_str = self.format_file_size(file_size)
            pages = len(doc)
            modified = datetime.fromtimestamp(os.path.getmtime(file_path)).strftime('%Y-%m-%d %H:%M')

            info_text = f"{os.path.basename(file_path)}\n大小: {size_str} | 页数: {pages}页\n修改时间: {modified}"
            self.split_preview_info.setText(info_text)

            doc.close()

        except Exception as e:
            self.split_preview_label.setText(f"无法预览PDF文件\n错误: {str(e)}")
            self.split_preview_info.setText("")

    def update_progress(self, value, message):
        """更新进度条"""
        self.progress_bar.setValue(value)
        self.statusBar().showMessage(message)

    def open_file(self, file_path):
        """打开文件"""
        try:
            webbrowser.open(file_path)
        except Exception as e:
            QMessageBox.warning(self, '警告', f'无法打开文件: {str(e)}')

    def open_folder(self, file_path):
        """打开文件所在文件夹"""
        try:
            folder_path = os.path.dirname(file_path)
            if sys.platform == 'win32':
                os.startfile(folder_path)
            elif sys.platform == 'darwin':
                os.system(f'open "{folder_path}"')
            else:
                os.system(f'xdg-open "{folder_path}"')
        except Exception as e:
            QMessageBox.warning(self, '警告', f'无法打开文件夹: {str(e)}')

    def update_button_state(self):
        """更新按钮状态"""
        has_files = len(self.pdf_files) > 0
        self.merge_button.setEnabled(has_files)
        self.clear_button.setEnabled(has_files)
        self.remove_button.setEnabled(has_files)
        self.move_up_button.setEnabled(has_files)
        self.move_down_button.setEnabled(has_files)
        self.move_top_button.setEnabled(has_files)
        self.move_bottom_button.setEnabled(has_files)
        self.apply_sort_button.setEnabled(has_files)

    def set_ui_enabled(self, enabled):
        """启用或禁用UI控件"""
        # 根据当前标签页决定启用哪些控件
        if self.current_tab == "merge":
            self.add_button.setEnabled(enabled)
            self.add_folder_button.setEnabled(enabled)
            self.remove_button.setEnabled(enabled and len(self.pdf_files) > 0)
            self.clear_button.setEnabled(enabled and len(self.pdf_files) > 0)
            self.merge_button.setEnabled(enabled and len(self.pdf_files) > 0)
            self.move_up_button.setEnabled(enabled and len(self.pdf_files) > 0)
            self.move_down_button.setEnabled(enabled and len(self.pdf_files) > 0)
            self.move_top_button.setEnabled(enabled and len(self.pdf_files) > 0)
            self.move_bottom_button.setEnabled(enabled and len(self.pdf_files) > 0)
            self.apply_sort_button.setEnabled(enabled and len(self.pdf_files) > 0)
            self.file_list.setEnabled(enabled)
            self.sort_combo.setEnabled(enabled)
        else:  # split tab
            self.split_file_button.setEnabled(enabled)
            self.mode_every_page.setEnabled(enabled)
            self.mode_page_ranges.setEnabled(enabled)
            self.pages_per_file_spin.setEnabled(enabled)
            self.page_ranges_text.setEnabled(enabled)
            self.output_folder_button.setEnabled(enabled)
            self.split_button.setEnabled(enabled and bool(self.split_file_path) and
                                         bool(self.output_folder_path))

    def restore_window_state(self):
        """恢复窗口状态"""
        geometry = self.settings.value("window_geometry")
        if geometry:
            self.restoreGeometry(geometry)

    def closeEvent(self, event):
        """关闭事件处理"""
        # 保存窗口状态
        self.settings.setValue("window_geometry", self.saveGeometry())
        event.accept()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("PDF工具 - 合并与拆分")
    app.setOrganizationName("PDFTools")

    # 同时设置应用程序图标
    try:
        app_icon = QIcon()
        # 创建简单的红色PDF图标
        for size in [16, 24, 32, 48, 64]:
            pixmap = QPixmap(size, size)
            pixmap.fill(Qt.transparent)

            painter = QPainter(pixmap)
            painter.setRenderHint(QPainter.Antialiasing)

            red_color = QColor(220, 50, 50)
            margin = size * 0.15
            doc_width = size - 2 * margin
            doc_height = doc_width * 1.2

            painter.setBrush(QBrush(red_color))
            painter.setPen(QPen(red_color.darker(130), max(1, size * 0.02)))
            painter.drawRoundedRect(int(margin), int(margin),
                                    int(doc_width), int(doc_height),
                                    int(size * 0.1), int(size * 0.1))

            fold_size = min(doc_width * 0.3, doc_height * 0.3)
            painter.setBrush(QBrush(red_color.darker(120)))
            fold_points = [
                QPoint(int(margin + doc_width - fold_size), int(margin)),
                QPoint(int(margin + doc_width), int(margin)),
                QPoint(int(margin + doc_width), int(margin + fold_size))
            ]
            painter.drawPolygon(fold_points)

            painter.setPen(QPen(Qt.white, max(1, size * 0.02)))
            font_size = int(size * 0.3)
            font = QFont("Arial", font_size, QFont.Bold)
            painter.setFont(font)
            text = "P"
            text_rect = painter.fontMetrics().boundingRect(text)
            text_x = int((size - text_rect.width()) / 2)
            text_y = int((size + text_rect.height()) / 2)
            painter.drawText(text_x, text_y, text)

            painter.end()
            app_icon.addPixmap(pixmap)

        app.setWindowIcon(app_icon)
    except Exception as e:
        print(f"设置应用程序图标失败: {e}")

    window = PDFToolsApp()
    window.show()

    sys.exit(app.exec_())


if __name__ == '__main__':
    main()