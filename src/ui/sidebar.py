import os
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidgetItem, QMenu, QInputDialog
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QPainter, QPixmap
from qfluentwidgets import PushButton, ListWidget, FluentIcon, SubtitleLabel, setFont
from src.models import session_dao
from src.core.config_manager import BASE_DIR
from src.ui.settings_dialog import SettingsDialog

class Sidebar(QWidget):
    session_selected = Signal(str) 

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("Sidebar") 
        self.setMinimumWidth(220)
        self.setMaximumWidth(350)
        
        # 初始化背景绘制相关的属性，防止 paintEvent 提前触发时报错
        self._bg_pixmap = None 
        self._sidebar_bg_color = "#202020" # 默认底色
        
        self._init_ui()
        self.refresh_sessions()

    def apply_theme(self, config):
        """应用主题配置到侧边栏"""
        bg_image = config.get("sidebar_bg_image", "")
        self._sidebar_bg_color = config.get("sidebar_bg", "#202020") 
        text_color = config.get("text_color", "#e0e0e0")
        
        # 1. 加载背景图到 QPixmap
        if bg_image:
            abs_path = os.path.join(BASE_DIR, bg_image).replace('\\', '/')
            if os.path.exists(abs_path):
                self._bg_pixmap = QPixmap(abs_path)
            else:
                self._bg_pixmap = None
        else:
            self._bg_pixmap = None
            
        self.update() # 强制触发重绘

        # 2. 设置内部组件的 QSS
        qss = f"""
            #Sidebar, #Sidebar > QWidget {{ background-color: transparent; }}
            QLabel, SubtitleLabel, BodyLabel {{ color: {text_color}; background: transparent; }}
            QListWidget {{ background-color: transparent; border: none; }}
            QListWidget::item {{ color: {text_color}; background-color: transparent; border-radius: 4px; padding: 8px; }}
            QListWidget::item:selected {{ background-color: rgba(128, 128, 128, 0.3); }}
            QPushButton {{ background-color: transparent; color: {text_color}; border: none; }}
        """
        self.setStyleSheet(qss)

    def paintEvent(self, event):
        """重写绘制事件，手动实现 CSS "background-size: cover" 效果"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        
        # 1. 先绘制纯色底色
        painter.fillRect(self.rect(), self._sidebar_bg_color)
        
        # 2. 如果有背景图，绘制图片 (等比缩放 + 居中裁剪)
        if self._bg_pixmap and not self._bg_pixmap.isNull():
            pix_w = self._bg_pixmap.width()
            pix_h = self._bg_pixmap.height()
            w = self.width()
            h = self.height()

            if w > 0 and h > 0 and pix_w > 0 and pix_h > 0:
                scale = max(w / pix_w, h / pix_h)
                new_w = int(pix_w * scale)
                new_h = int(pix_h * scale)

                x = (w - new_w) // 2
                y = (h - new_h) // 2
                
                painter.drawPixmap(x, y, new_w, new_h, self._bg_pixmap)
                
        painter.end()

    def _init_ui(self):
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(16, 20, 16, 20)
        self.vBoxLayout.setSpacing(12)

        self.titleLabel = SubtitleLabel("会话列表")
        setFont(self.titleLabel, 18)
        self.vBoxLayout.addWidget(self.titleLabel)

        self.newChatBtn = PushButton(FluentIcon.ADD, "新建对话")
        self.newChatBtn.setFixedHeight(40)
        self.vBoxLayout.addWidget(self.newChatBtn)

        self.chatList = ListWidget()
        self.chatList.setStyleSheet("""
            QListWidget { border: none; background-color: transparent; }
            QListWidget::item { border-radius: 4px; padding: 8px; }
        """)
        self.chatList.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chatList.customContextMenuRequested.connect(self._show_context_menu)
        self.chatList.itemClicked.connect(self._on_item_clicked)
        
        self.vBoxLayout.addWidget(self.chatList)
        
        self.settingsBtn = PushButton(FluentIcon.SETTING, "设置")
        self.settingsBtn.clicked.connect(self._open_settings)
        self.vBoxLayout.addWidget(self.settingsBtn)

    def refresh_sessions(self, select_id=None):
        self.chatList.clear()
        sessions = session_dao.get_all_sessions()
        for sess in sessions:
            item = QListWidgetItem(sess['title'])
            item.setData(Qt.UserRole, sess['id']) 
            self.chatList.addItem(item)
            if select_id and sess['id'] == select_id:
                self.chatList.setCurrentItem(item)

    def _on_item_clicked(self, item):
        session_id = item.data(Qt.UserRole)
        self.session_selected.emit(session_id)

    def _show_context_menu(self, pos):
        item = self.chatList.itemAt(pos)
        if not item: return
            
        menu = QMenu(self)
        rename_action = menu.addAction("重命名")
        delete_action = menu.addAction("删除")
        
        action = menu.exec(self.chatList.mapToGlobal(pos))
        session_id = item.data(Qt.UserRole)
        
        if action == rename_action:
            new_title, ok = QInputDialog.getText(self, "重命名", "请输入新名称:", text=item.text())
            if ok and new_title.strip():
                session_dao.update_session_title(session_id, new_title.strip())
                self.refresh_sessions(select_id=session_id)
        elif action == delete_action:
            # 【修复】检查是否删除的是当前查看的会话
            current_item = self.chatList.currentItem()
            was_current = current_item and current_item.data(Qt.UserRole) == session_id
            
            session_dao.delete_session(session_id)
            
            if self.chatList.count() == 0:
                # 列表已空，通知 ChatView 清空
                self.session_selected.emit("")
            elif was_current:
                # 【修复】删除的是当前查看的会话，自动切换到列表第一个
                self.refresh_sessions()
                first_item = self.chatList.item(0)
                if first_item:
                    self.chatList.setCurrentItem(first_item)
                    self.session_selected.emit(first_item.data(Qt.UserRole))
            else:
                # 删除的不是当前会话，只刷新列表即可
                current_id = current_item.data(Qt.UserRole) if current_item else None
                self.refresh_sessions(select_id=current_id)

    def _open_settings(self):
        dialog = SettingsDialog(self)
        dialog.exec()