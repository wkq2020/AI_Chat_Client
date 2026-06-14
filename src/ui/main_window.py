from PySide6.QtWidgets import QWidget, QHBoxLayout, QSplitter
from PySide6.QtCore import Qt
# 【核心修复】确保导入了 setTheme 和 Theme
from qfluentwidgets import isDarkTheme, qconfig, Theme, setTheme 
from src.ui.sidebar import Sidebar
from src.ui.chat_view import ChatView
from src.models import session_dao
from src.core.signal_bus import signal_bus
from src.core.config_manager import ConfigManager

class MainWindow(QWidget):
    def __init__(self):
        super().__init__()
        self.setObjectName("MainWindow")
        self.setWindowTitle("AI Chat Client - MVP")
        self.resize(1100, 750)
        
        self._init_ui()
        self._connect_signals()
        
        # 监听主题切换信号
        signal_bus.theme_changed.connect(self._on_theme_changed)
        
        # 初始化应用一次主题
        self.apply_theme_styles() 
        
        sessions = session_dao.get_all_sessions()
        if sessions:
            first_id = sessions[0]['id']
            self.sidebar.refresh_sessions(select_id=first_id)
            self.chat_view.load_session(first_id)

    def _on_theme_changed(self, theme_id):
        """当设置页切换主题时触发"""
        self.apply_theme_styles(theme_id)

    def apply_theme_styles(self, theme_id=None):
        """集中下发主题配置"""
        config_mgr = ConfigManager()
        if not theme_id:
            theme_id = config_mgr.config.get("current_theme", "default_dark")
            
        theme_config = config_mgr.get_current_theme_config()
        is_dark = theme_config.get("is_dark", True)
        
        # 联动 Fluent Widgets 的全局 Dark/Light 主题
        new_theme = Theme.DARK if is_dark else Theme.LIGHT
        if qconfig.theme != new_theme:  
            setTheme(new_theme)
            
        # 1. 更新主窗口背景
        main_bg = theme_config.get("main_bg", "#202020")
        handle_color = "#323232" if is_dark else "#e0e0e0"
        self.setStyleSheet(f"""
            #MainWindow {{ background-color: {main_bg}; }}
            QSplitter::handle {{ background-color: {handle_color}; }}
            QSplitter::handle:hover {{ background-color: #009faa; }}
        """)
        self.style().unpolish(self)
        self.style().polish(self)
        
        # 2. 下发给子组件
        if hasattr(self, 'sidebar'):
            self.sidebar.apply_theme(theme_config)
        if hasattr(self, 'chat_view'):
            self.chat_view.apply_theme(theme_config)

    def _init_ui(self):
        self.hBoxLayout = QHBoxLayout(self)
        self.hBoxLayout.setContentsMargins(0, 0, 0, 0)
        self.hBoxLayout.setSpacing(0)

        self.splitter = QSplitter(Qt.Horizontal)
        self.sidebar = Sidebar()
        self.chat_view = ChatView()

        self.splitter.addWidget(self.sidebar)
        self.splitter.addWidget(self.chat_view)

        self.splitter.setStretchFactor(0, 1)
        self.splitter.setStretchFactor(1, 3)
        self.splitter.setHandleWidth(2)
        self.hBoxLayout.addWidget(self.splitter)

    def _connect_signals(self):
        self.sidebar.newChatBtn.clicked.connect(self._create_new_session)
        self.sidebar.session_selected.connect(self._on_session_selected)

    def _create_new_session(self):
        new_id = session_dao.create_session("新对话")
        self.sidebar.refresh_sessions(select_id=new_id)
        self.chat_view.load_session(new_id)

    def _on_session_selected(self, session_id):
        self.chat_view.load_session(session_id)