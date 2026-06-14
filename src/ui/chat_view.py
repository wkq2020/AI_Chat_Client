import os
import json
import time
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSpacerItem, QSizePolicy, 
    QApplication, QMessageBox
)
from PySide6.QtCore import Qt, QTimer, QObject, Slot, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWebChannel import QWebChannel
from qfluentwidgets import isDarkTheme
from qfluentwidgets import (
    TextEdit, PrimaryPushButton, FluentIcon, ComboBox, 
    BodyLabel, SimpleCardWidget, SwitchButton, CaptionLabel,
    RoundMenu, Action, isDarkTheme, qconfig, Theme # 【新增】导入 Theme
)

from src.core.worker import LLMStreamWorker
from src.models import message_dao, session_dao
from src.core.config_manager import ConfigManager, BASE_DIR
from src.core.signal_bus import signal_bus

class ChatWebEngineView(QWebEngineView):
    def contextMenuEvent(self, event):
        event.ignore() 

class JSBridge(QObject):
    context_menu_requested = Signal(str, str) 
    def __init__(self, parent=None): super().__init__(parent)
    @Slot(str)
    def copyToClipboard(self, text): QApplication.clipboard().setText(text)
    @Slot(str, str)
    def triggerContextMenu(self, plain_text, markdown_text): self.context_menu_requested.emit(plain_text, markdown_text)

class ChatView(QWidget):
    session_created = Signal(str) 

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ChatView")
        
        self.current_session_id = None 
        self.config = ConfigManager()  
        
        self.is_page_loaded = False
        self.pending_session_id = None
        self.current_models = [] 
        
        # 【核心重构】多会话独立状态字典，彻底隔离每个会话的数据
        self.session_states = {} 
        
        self.flush_timer = QTimer(self)
        self.flush_timer.setInterval(50) 
        self.flush_timer.timeout.connect(self._flush_token_buffer)
        
        # 【新增】System Prompt 防抖保存定时器 (停止输入 500ms 后自动保存)
        self.sys_prompt_timer = QTimer(self)
        self.sys_prompt_timer.setSingleShot(True)
        self.sys_prompt_timer.setInterval(500)
        self.sys_prompt_timer.timeout.connect(self._save_system_prompt)
        
        self._init_ui()
        self.web_view.loadFinished.connect(self._on_page_loaded)
        self.bridge.context_menu_requested.connect(self._show_context_menu)

        # 【新增】监听配置更新和主题更新
        signal_bus.config_updated.connect(self._on_config_updated)
        qconfig.themeChanged.connect(self.apply_html_theme)

    def _get_default_state(self):
        return {
            "full_text": "", "thinking_text": "", "buffer": "", "thinking_buffer": "",
            "usage": None, "cached_tokens": 0, "is_generating": False, 
            "worker": None, "start_time": 0, "show_thinking": False
        }

    def _init_ui(self):
        self.vBoxLayout = QVBoxLayout(self)
        self.vBoxLayout.setContentsMargins(20, 20, 20, 20)
        self.vBoxLayout.setSpacing(12)

        self.topLayout = QHBoxLayout()
        self.modelLabel = BodyLabel("当前模型:")
        self.modelCombo = ComboBox()
        self.modelCombo.setFixedWidth(180)
        self.topLayout.addWidget(self.modelLabel)
        self.topLayout.addWidget(self.modelCombo)
        self.topLayout.addSpacerItem(QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum))
        self.vBoxLayout.addLayout(self.topLayout)

        self.messageArea = SimpleCardWidget()
        self.messageLayout = QVBoxLayout(self.messageArea)
        self.messageLayout.setContentsMargins(0, 0, 0, 0)
        self.web_view = ChatWebEngineView() 
        self.web_view.setStyleSheet("border: none; background: transparent;")
        self.channel = QWebChannel()
        self.bridge = JSBridge(self)
        self.channel.registerObject("bridge", self.bridge)
        self.web_view.page().setWebChannel(self.channel)
        html_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '../../assets/web/chat.html'))
        if os.name == 'nt': html_path = html_path.replace('\\', '/')
        self.web_view.setUrl(f"file:///{html_path}?v={int(time.time())}")
        self.messageLayout.addWidget(self.web_view)
        self.vBoxLayout.addWidget(self.messageArea, 1) 

        self.sysPromptLabel = BodyLabel("⚙️ 系统指令 (System Prompt):")
        self.vBoxLayout.addWidget(self.sysPromptLabel)
        self.sysPromptBox = TextEdit()
        self.sysPromptBox.setPlaceholderText("设定 AI 的角色、背景知识或行为准则... (长文本将自动触发上下文缓存)")
        self.sysPromptBox.setFixedHeight(70)
        self.sysPromptBox.textChanged.connect(self._update_context_label)
        self.sysPromptBox.textChanged.connect(self._on_sys_prompt_changed) # 【新增】绑定防抖保存信号
        self.vBoxLayout.addWidget(self.sysPromptBox)

        self.optionLayout = QHBoxLayout()
        self.optionLayout.setSpacing(15)
        self.optionLayout.addWidget(BodyLabel("💡 思考"))
        self.thinkingSwitch = SwitchButton()
        self.thinkingSwitch.setChecked(False) 
        self.optionLayout.addWidget(self.thinkingSwitch)
        
        # 【新增】思考参数控制组件 (默认隐藏)
        self.thinkingParamLabel = BodyLabel("")
        self.thinkingParamLabel.setVisible(False)
        self.optionLayout.addWidget(self.thinkingParamLabel)
        
        self.thinkingParamCombo = ComboBox()
        self.thinkingParamCombo.setFixedWidth(100)
        self.thinkingParamCombo.setVisible(False)
        self.optionLayout.addWidget(self.thinkingParamCombo)
        self.optionLayout.addWidget(BodyLabel("🌐 联网")); self.searchSwitch = SwitchButton(); self.optionLayout.addWidget(self.searchSwitch)
        self.optionLayout.addWidget(BodyLabel("✍️ 续写")); self.partialSwitch = SwitchButton(); self.optionLayout.addWidget(self.partialSwitch)
        self.optionLayout.addWidget(BodyLabel("💾 缓存")); self.cacheSwitch = SwitchButton(); self.optionLayout.addWidget(self.cacheSwitch)
        self.optionLayout.addStretch()
        self.vBoxLayout.addLayout(self.optionLayout)

        self.contextLabel = CaptionLabel("📊 上下文预估: 0 Tokens")
        self.contextLabel.setStyleSheet("color: #888; padding: 0 2px;")
        self.vBoxLayout.addWidget(self.contextLabel)

        self.bottomLayout = QHBoxLayout()
        self.bottomLayout.setSpacing(10)
        self.inputBox = TextEdit()
        self.inputBox.setPlaceholderText("输入你的问题... (Enter 发送, Shift+Enter 换行)")
        self.inputBox.setFixedHeight(90)
        self.inputBox.keyPressEvent = self._custom_key_press
        self.inputBox.textChanged.connect(self._update_context_label)
        self.sendBtn = PrimaryPushButton(FluentIcon.SEND, "发送")
        self.sendBtn.setFixedSize(80, 90)
        self.sendBtn.clicked.connect(self._on_send_clicked)
        self.bottomLayout.addWidget(self.inputBox, 1)
        self.bottomLayout.addWidget(self.sendBtn)
        self.vBoxLayout.addLayout(self.bottomLayout)
        
        self._update_context_label()
        self._update_model_list() 
        self.modelCombo.currentIndexChanged.connect(self._on_model_changed)


    def _show_context_menu(self, plain_text, markdown_text):
        menu = RoundMenu(parent=self)
        menu.addAction(Action(FluentIcon.COPY, "复制整条回复", triggered=lambda: self._copy_text(plain_text)))
        menu.addAction(Action(FluentIcon.CODE, "复制为 Markdown", triggered=lambda: self._copy_text(markdown_text)))
        menu.addSeparator()
        menu.addAction(Action(FluentIcon.SYNC, "重新生成", triggered=self._handle_regenerate))
        menu.exec(QCursor.pos(), ani=True)

    def _copy_text(self, text): QApplication.clipboard().setText(text)

    def _handle_regenerate(self):
        if not self.current_session_id: return
        state = self.session_states.get(self.current_session_id)
        if state and state["is_generating"]: return
        messages = message_dao.get_messages_by_session(self.current_session_id)
        last_user_msg = next((m['content'] for m in reversed(messages) if m['role'] == 'user'), None)
        if last_user_msg: self._do_send_message(last_user_msg, is_regenerate=True)

    def _update_context_label(self):
        input_text = self.inputBox.toPlainText()
        sys_text = self.sysPromptBox.toPlainText()
        
        # 1. 估算当前输入和系统指令
        input_tokens = len(input_text) // 2 if len(input_text) > 1 else (1 if input_text else 0)
        sys_tokens = len(sys_text) // 2 if len(sys_text) > 1 else 0
        
        # =====================================================================
        # 【核心修复】始终从数据库读取历史消息来计算，确保刚打开时不为 0，且避免与 usage 重复计算
        # =====================================================================
        history_tokens = 0
        if self.current_session_id:
            history = message_dao.get_messages_by_session(self.current_session_id)
            history_tokens = sum(len(m['content']) for m in history) // 2
            
        # 2. 计算总 Token (三者独立相加，绝不重复)
        total_tokens = history_tokens + sys_tokens + input_tokens
        
        # 3. 缓存状态判断 (稳定前缀 = 历史 + 系统指令)
        cache_status = ""
        if self.cacheSwitch.isChecked() and self.cacheSwitch.isEnabled():
            stable_tokens = history_tokens + sys_tokens
            if stable_tokens >= 1024: 
                cache_status = " | <span style='color: #4ade80;'>💾 缓存就绪</span>"
            else: 
                cache_status = f" | <span style='color: #facc15;'>⚠️ 稳定前缀 {stable_tokens} (需≥1024)</span>"
                
        # 4. 更新 UI
        self.contextLabel.setText(
            f"📊 上下文预估: {total_tokens:,} Tokens (历史: {history_tokens:,} + 指令: {sys_tokens:,} + 输入: {input_tokens:,}){cache_status}"
        )
    def apply_theme(self, config):
        """应用主题配置到聊天区 (修复 JS 引号冲突)"""
        input_bg = config.get("input_bg", "#282828")
        text_color = config.get("text_color", "#e0e0e0")
        
        # 1. 更新 Qt 原生组件 (输入框、标签) 的样式
        self.setStyleSheet(f"""
            #ChatView {{ background-color: transparent; }}
            TextEdit {{ background-color: {input_bg}; color: {text_color}; border: 1px solid rgba(128,128,128,0.2); border-radius: 8px; }}
            BodyLabel, CaptionLabel, SubtitleLabel {{ color: {text_color}; background: transparent; }}
        """)
        
        # 2. 处理图片绝对路径 (【修复】只保留纯路径，不带 url())
        chat_bg = config.get("chat_bg_image", "")
        chat_bg_path = ""
        if chat_bg:
            abs_path = os.path.join(BASE_DIR, chat_bg).replace('\\', '/')
            if os.path.exists(abs_path):
                chat_bg_path = f"file:///{abs_path}"
            else:
                print(f"⚠️ [WARNING] 找不到聊天背景图: {abs_path}")
                
        # 3. 直接执行 JS 注入 CSS 变量 (【修复】在 JS 内部拼接 url，避免引号冲突)
        overlay_color = config.get("overlay_color", "rgba(0,0,0,0)")
        bubble_user_bg = config.get("bubble_user_bg", "#2c5282")
        bubble_ai_bg = config.get("bubble_ai_bg", "#333333")
        is_dark = config.get("is_dark", True)
        
        # 将布尔值转为 JS 的 true/false 字符串
        is_dark_js = "true" if is_dark else "false"
        
        js_inject = f"""
            (function() {{
                var root = document.documentElement;
                // 【修复】在 JS 内部安全地拼接 url('...')
                var bgPath = '{chat_bg_path}';
                var bgUrl = bgPath ? "url('" + bgPath + "')" : 'none';
                
                root.style.setProperty('--chat-bg-image', bgUrl);
                root.style.setProperty('--overlay-color', '{overlay_color}');
                root.style.setProperty('--bubble-user-bg', '{bubble_user_bg}');
                root.style.setProperty('--bubble-ai-bg', '{bubble_ai_bg}');
                root.style.setProperty('--text-color', '{text_color}');
                
                if ({is_dark_js}) {{
                    root.style.setProperty('--bg-color', '#282828');
                    root.style.setProperty('--bubble-ai-border', '#444');
                    root.style.setProperty('--code-bg', '#1e1e1e');
                    root.style.setProperty('--inline-code-bg', '#444');
                    root.style.setProperty('--thinking-bg', '#222');
                    root.style.setProperty('--thinking-border', '#555');
                    root.style.setProperty('--thinking-text', '#aaa');
                    root.style.setProperty('--thinking-header', '#ccc');
                }} else {{
                    root.style.setProperty('--bg-color', '#f9f9f9');
                    root.style.setProperty('--bubble-ai-border', '#e0e0e0');
                    root.style.setProperty('--code-bg', '#f6f8fa');
                    root.style.setProperty('--inline-code-bg', '#e0e0e0');
                    root.style.setProperty('--thinking-bg', '#f0f0f0');
                    root.style.setProperty('--thinking-border', '#ccc');
                    root.style.setProperty('--thinking-text', '#555');
                    root.style.setProperty('--thinking-header', '#333');
                }}
            }})();
        """
        self.web_view.page().runJavaScript(js_inject)
    def _on_page_loaded(self, ok):
        if ok:
            self.is_page_loaded = True
            # 页面加载完后，立刻应用一次当前主题
            self.apply_theme(self.config.get_current_theme_config()) 
            
            if self.pending_session_id is not None:
                sid = self.pending_session_id
                self.pending_session_id = None
                QTimer.singleShot(150, lambda: self._do_load_session(sid))

    def apply_html_theme(self, theme=None):
        """【修复】直接根据传入的 theme 参数判断 HTML 主题"""
        if not self.is_page_loaded: return
        
        is_dark = (theme == Theme.DARK) if theme else isDarkTheme()
        
        if is_dark:
            js_theme = """
                document.documentElement.style.setProperty('--bg-color', '#282828');
                document.documentElement.style.setProperty('--text-color', '#e0e0e0');
                document.documentElement.style.setProperty('--bubble-ai-bg', '#333333');
                document.documentElement.style.setProperty('--bubble-ai-border', '#444');
                document.documentElement.style.setProperty('--code-bg', '#1e1e1e');
                document.documentElement.style.setProperty('--inline-code-bg', '#444');
                document.documentElement.style.setProperty('--thinking-bg', '#222');
                document.documentElement.style.setProperty('--thinking-border', '#555');
                document.documentElement.style.setProperty('--thinking-text', '#aaa');
                document.documentElement.style.setProperty('--thinking-header', '#ccc');
            """
        else:
            js_theme = """
                document.documentElement.style.setProperty('--bg-color', '#f9f9f9');
                document.documentElement.style.setProperty('--text-color', '#000000');
                document.documentElement.style.setProperty('--bubble-ai-bg', '#ffffff');
                document.documentElement.style.setProperty('--bubble-ai-border', '#e0e0e0');
                document.documentElement.style.setProperty('--code-bg', '#f6f8fa');
                document.documentElement.style.setProperty('--inline-code-bg', '#e0e0e0');
                document.documentElement.style.setProperty('--thinking-bg', '#f0f0f0');
                document.documentElement.style.setProperty('--thinking-border', '#ccc');
                document.documentElement.style.setProperty('--thinking-text', '#555');
                document.documentElement.style.setProperty('--thinking-header', '#333');
            """
        self.web_view.page().runJavaScript(js_theme)

    def _on_config_updated(self):
        """【新增】当设置页保存配置后，实时刷新模型下拉框和开关状态"""
        # 重新从 config_manager 读取最新配置
        self.config = ConfigManager() 
        self._update_model_list()

    def _custom_key_press(self, event):
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            if event.modifiers() & Qt.ShiftModifier: self.inputBox.insertPlainText("\n")
            else:
                if self.sendBtn.text() == "停止": self._on_stop_clicked()
                elif self.sendBtn.isEnabled(): self._on_send_clicked()
        else: TextEdit.keyPressEvent(self.inputBox, event)

    def _call_js(self, func_name, *args):
        args_str = ",".join([json.dumps(arg) if not isinstance(arg, (int, float, bool)) else str(arg).lower() if isinstance(arg, bool) else str(arg) for arg in args])
        self.web_view.page().runJavaScript(f"{func_name}({args_str});")

    def _update_model_list(self):
        self.modelCombo.clear()
        current_api = self.config.get_current_api()
        self.current_models = current_api.get("models", []) if current_api else []
        display_names = [m.get('name') or m.get('id') for m in self.current_models]
        self.modelCombo.addItems(display_names)
        self._on_model_changed(self.modelCombo.currentIndex())

    def _get_current_model_dict(self):
        idx = self.modelCombo.currentIndex()
        return self.current_models[idx] if 0 <= idx < len(self.current_models) else None

    def _on_model_changed(self, index):
        model_dict = self._get_current_model_dict()
        if not model_dict: return
        caps = model_dict.get('capabilities', [])
        self._update_switch_state(self.thinkingSwitch, 'reasoning' in caps, "当前模型不支持深度思考")
        self._update_switch_state(self.searchSwitch, 'search' in caps, "当前模型不支持联网搜索")
        self._update_switch_state(self.partialSwitch, 'partial' in caps, "当前模型不支持前缀续写")
        self._update_switch_state(self.cacheSwitch, 'cache' in caps, "当前模型不支持显式上下文缓存")
        # 【新增/替换】思考参数下拉框动态渲染
        thinking_control = model_dict.get('thinking_control', 'none')
        if thinking_control == 'deepseek' and 'reasoning' in caps:
            self.thinkingParamLabel.setText("强度:")
            self.thinkingParamLabel.setVisible(True)
            self.thinkingParamCombo.clear()
            self.thinkingParamCombo.addItems(["high", "max"])
            self.thinkingParamCombo.setCurrentText("high")
            self.thinkingParamCombo.setVisible(True)
        elif thinking_control == 'qwen' and 'reasoning' in caps:
            self.thinkingParamLabel.setText("预算:")
            self.thinkingParamLabel.setVisible(True)
            self.thinkingParamCombo.clear()
            self.thinkingParamCombo.addItems(["auto", "1024", "2048", "4096", "8192"])
            self.thinkingParamCombo.setCurrentText("4096")
            self.thinkingParamCombo.setVisible(True)
        else:
            self.thinkingParamLabel.setVisible(False)
            self.thinkingParamCombo.setVisible(False)

    def _update_switch_state(self, switch, enabled, tooltip):
        switch.setEnabled(enabled)
        if not enabled: switch.setChecked(False); switch.setToolTip(f"⚠️ {tooltip}")
        else: switch.setToolTip("") 

    # =====================================================================
    # 【核心重构】会话切换：不杀 Worker，实现后台静默与无缝续传
    # =====================================================================
    def load_session(self, session_id):
        # 1. 停止旧会话的 UI 渲染定时器 (但不杀 Worker，让它在后台继续跑)
        if self.flush_timer.isActive():
            self.flush_timer.stop()
            
        # 2. 切换 ID
        self.current_session_id = session_id
        
        # =====================================================================
        # 【核心修复】如果 HTML 页面还没加载完，先暂存 ID，绝对不能直接调用 JS！
        # =====================================================================
        if not self.is_page_loaded:
            self.pending_session_id = session_id
            return
            
        # 3. 加载历史 UI
        self._do_load_session(session_id)
        
        # 4. 【核心】续点续传：检查新会话是否有后台生成的数据
        if session_id and session_id in self.session_states:
            state = self.session_states[session_id]
            if state["is_generating"]:
                self._set_stop_button_state()
                self._call_js("startAiMessage")
                if state["thinking_text"] and state["show_thinking"]:
                    self._call_js("appendAiThinking", state["thinking_text"])
                if state["full_text"]:
                    self._call_js("appendAiToken", state["full_text"])
                state["buffer"] = ""
                state["thinking_buffer"] = ""
                self.flush_timer.start()
            else:
                self._reset_send_button()
        else:
            self._reset_send_button()

    def _on_sys_prompt_changed(self):
        """当系统指令文本框内容改变时，重置防抖定时器"""
        if self.current_session_id:
            self.sys_prompt_timer.start()

    def _save_system_prompt(self):
        """防抖定时器触发，将系统指令静默保存到数据库"""
        if self.current_session_id:
            prompt = self.sysPromptBox.toPlainText()
            session_dao.update_system_prompt(self.current_session_id, prompt)

    def _do_load_session(self, session_id):
        if not session_id:
            self._call_js("loadHistory", []) 
            # 清空系统指令框 (阻断信号防止触发保存)
            self.sysPromptBox.blockSignals(True)
            self.sysPromptBox.clear()
            self.sysPromptBox.blockSignals(False)
            self._update_context_label()
            return
            
        # 【核心新增】获取会话详情，加载专属的 System Prompt
        session_info = session_dao.get_session_by_id(session_id)
        sys_prompt = session_info.get('system_prompt', '') if session_info else ''
        
        # 更新系统指令框 (阻断信号，防止加载数据时触发保存和重复计算)
        self.sysPromptBox.blockSignals(True)
        self.sysPromptBox.setPlainText(sys_prompt)
        self.sysPromptBox.blockSignals(False)
        
        # 加载消息历史
        messages = message_dao.get_messages_by_session(session_id)
        self._call_js("loadHistory", messages)
        
        # 更新上下文预估 (因为 sysPromptBox 内容变了，需要重新计算)
        self._update_context_label()

    def _on_send_clicked(self):
        text = self.inputBox.toPlainText().strip()
        if not text: return
        self.inputBox.clear()
        self._do_send_message(text, is_regenerate=False)

    def _do_send_message(self, text, is_regenerate=False):
        current_api = self.config.get_current_api()
        if not current_api: QMessageBox.warning(self, "配置错误", "请先在左下角【设置】中添加并配置 API！"); return
        current_model_dict = self._get_current_model_dict()
        if not current_model_dict: QMessageBox.warning(self, "配置错误", "当前 API 下没有配置任何可用模型！"); return
            
        API_KEY = current_api["api_key"]
        BASE_URL = current_api["base_url"]
        model = current_model_dict.get('id')

        if not self.current_session_id:
            self.current_session_id = session_dao.create_session(text[:20])
            self.session_created.emit(self.current_session_id) 
            
        if not is_regenerate:
            self._call_js("addUserMessage", text)
            message_dao.add_message(self.current_session_id, "user", text)
        
        # 初始化/重置当前会话的 state
        if self.current_session_id not in self.session_states:
            self.session_states[self.current_session_id] = self._get_default_state()
        state = self.session_states[self.current_session_id]
        
        state["full_text"] = ""
        state["thinking_text"] = ""
        state["buffer"] = ""
        state["thinking_buffer"] = ""
        state["is_generating"] = True
        state["usage"] = None
        state["cached_tokens"] = 0
        state["start_time"] = time.time()
        state["show_thinking"] = self.thinkingSwitch.isChecked() and self.thinkingSwitch.isEnabled()
        
        self._call_js("startAiMessage")
        
        enable_search = self.searchSwitch.isChecked() and self.searchSwitch.isEnabled()
        sys_prompt = self.sysPromptBox.toPlainText().strip()
        history = message_dao.get_messages_by_session(self.current_session_id)
        
        def estimate_tokens(t): return len(t) // 2
        is_cache_enabled = self.cacheSwitch.isChecked() and self.cacheSwitch.isEnabled()
        MAX_BREAKPOINTS = 4
        MIN_CACHE_TOKENS = 1024
        cache_breakpoints = 0
        messages = []
        
        if sys_prompt:
            sys_content = sys_prompt
            if is_cache_enabled and estimate_tokens(sys_prompt) >= MIN_CACHE_TOKENS and cache_breakpoints < MAX_BREAKPOINTS:
                sys_content = [{"type": "text", "text": sys_prompt, "cache_control": {"type": "ephemeral"}}]
                cache_breakpoints += 1
            messages.append({"role": "system", "content": sys_content})
            
        raw_messages = [{"role": m["role"], "content": m["content"]} for m in history]
        if is_cache_enabled:
            accumulated_tokens = 0
            start_idx = len(raw_messages) - 2
            end_idx = max(-1, len(raw_messages) - 16) 
            for i in range(start_idx, end_idx, -1):
                msg = raw_messages[i]
                content_text = msg["content"]
                accumulated_tokens += estimate_tokens(content_text)
                if accumulated_tokens >= MIN_CACHE_TOKENS or i == end_idx + 1:
                    if cache_breakpoints < MAX_BREAKPOINTS:
                        msg["content"] = [{"type": "text", "text": content_text, "cache_control": {"type": "ephemeral"}}]
                        cache_breakpoints += 1
                        break
            messages.extend(raw_messages)
        else:
            messages = raw_messages

        is_partial = self.partialSwitch.isChecked() and self.partialSwitch.isEnabled()
        if is_partial:
            partial_sys = {"role": "system", "content": "你是一个纯粹的文本/代码续写引擎。请无缝续写用户提供的文本。绝对不要回答问题，不要添加任何解释、问候、前缀或后缀，不要重复用户的输入。直接输出续写的内容。"}
            messages.insert(0, partial_sys)
            
        # 【修复】安全清理旧 Worker：停止线程 + 断开信号 + 释放引用，防止竞态和内存泄漏
        self._cleanup_worker(state.get("worker"))
            
        # 【新增】构建思考控制参数配置
        thinking_config = None
        model_dict = self._get_current_model_dict()
        thinking_control = model_dict.get('thinking_control', 'none') if model_dict else 'none'
        
        if thinking_control in ['deepseek', 'qwen']:
            is_thinking_on = self.thinkingSwitch.isChecked() and self.thinkingSwitch.isEnabled()
            ctrl_val = self.thinkingParamCombo.currentText() if self.thinkingParamCombo.isVisible() else None
            
            thinking_config = {
                "protocol": thinking_control,
                "enabled": is_thinking_on,
                "value": ctrl_val
            }
                
        # 将 thinking_config 传给 Worker
        worker = LLMStreamWorker(API_KEY, BASE_URL, model, messages, self.current_session_id, enable_search, thinking_config)
        state["worker"] = worker
        
        worker.thinking_received.connect(self._on_thinking_received) 
        worker.token_received.connect(self._on_token_received)
        worker.usage_received.connect(self._on_usage_received) 
        worker.stream_finished.connect(self._on_stream_finished)
        worker.error_occurred.connect(self._on_error_occurred)
        worker.start()
        
        self._set_stop_button_state()

    def _cleanup_worker(self, worker):
        """【修复】安全停止 Worker 并释放资源，防止竞态条件和内存泄漏"""
        if worker is None:
            return
        # 1. 通知线程停止
        if worker.isRunning():
            worker.stop()
            # 等待线程结束，最多 3 秒，防止卡死在 httpx 阻塞中
            worker.wait(3000)
        # 2. 断开所有信号，防止旧 Worker 的信号继续触发 slot
        try:
            worker.thinking_received.disconnect()
            worker.token_received.disconnect()
            worker.usage_received.disconnect()
            worker.stream_finished.disconnect()
            worker.error_occurred.disconnect()
        except (RuntimeError, TypeError):
            pass
        # 3. 标记为稍后删除，让 Qt 事件循环安全回收 QThread 对象
        worker.deleteLater()

    def _set_stop_button_state(self):
        self.sendBtn.setText("停止")
        self.sendBtn.setIcon(FluentIcon.CLOSE)
        try: self.sendBtn.clicked.disconnect()
        except RuntimeError: pass
        self.sendBtn.clicked.connect(self._on_stop_clicked)

    def _reset_send_button(self):
        self.sendBtn.setText("发送")
        self.sendBtn.setIcon(FluentIcon.SEND)
        try: self.sendBtn.clicked.disconnect()
        except RuntimeError: pass
        self.sendBtn.clicked.connect(self._on_send_clicked)
        self.sendBtn.setEnabled(True)

    def _on_stop_clicked(self):
        """【修复】停止生成时紧急保存已生成的部分内容到数据库"""
        if self.current_session_id and self.current_session_id in self.session_states:
            state = self.session_states[self.current_session_id]
            if state["worker"] and state["worker"].isRunning():
                state["worker"].stop()
                # 紧急保存已生成的部分内容，防止数据丢失
                if state["full_text"]:
                    message_dao.add_message(self.current_session_id, "assistant", state["full_text"])
                state["is_generating"] = False
        self.sendBtn.setEnabled(False)
        # 【修复】安全网：如果 Worker 线程卡在 httpx 阻塞中无法触发 stream_finished，
        # 3.5 秒后强制重置 UI，防止按钮永远卡在“停止”状态
        QTimer.singleShot(3500, self._force_reset_ui_after_stop)

    def _force_reset_ui_after_stop(self):
        """【修复】安全网：当 Worker 线程卡死无法触发 stream_finished 时，强制恢复 UI"""
        if not self.current_session_id: return
        state = self.session_states.get(self.current_session_id)
        if state and not state["is_generating"]:
            # 已经正常结束了，无需处理
            return
        # Worker 卡死，强制重置
        if state:
            state["is_generating"] = False
            if self.flush_timer.isActive(): self.flush_timer.stop()
            self._flush_token_buffer()
            self._call_js("finishAiMessage")
            # 强制清理卡死的 Worker
            worker = state.get("worker")
            if worker:
                worker.stop()
                worker.wait(1000)
                self._cleanup_worker(worker)
                state["worker"] = None
        self._reset_send_button()

    # =====================================================================
    # 【核心重构】信号接收器：数据存入独立 State，按需渲染 UI
    # =====================================================================
    def _on_thinking_received(self, token: str, session_id: str):
        if session_id not in self.session_states: return
        state = self.session_states[session_id]
        state["thinking_text"] += token
        state["thinking_buffer"] += token
        if session_id == self.current_session_id and state["show_thinking"]:
            if not self.flush_timer.isActive(): self.flush_timer.start()

    def _on_token_received(self, token: str, session_id: str):
        if session_id not in self.session_states: return
        state = self.session_states[session_id]
        state["full_text"] += token
        state["buffer"] += token
        if session_id == self.current_session_id:
            if not self.flush_timer.isActive(): self.flush_timer.start()

    def _flush_token_buffer(self):
        if not self.current_session_id: return
        state = self.session_states.get(self.current_session_id)
        if not state: return
        
        if state["thinking_buffer"] and state["show_thinking"]:
            self._call_js("appendAiThinking", state["thinking_buffer"])
            state["thinking_buffer"] = ""
        if state["buffer"]:
            self._call_js("appendAiToken", state["buffer"])
            state["buffer"] = ""

    def _on_usage_received(self, usage_data: dict, session_id: str):
        if session_id not in self.session_states: return
        state = self.session_states[session_id]
        state["usage"] = usage_data
        cached = 0
        if "prompt_tokens_details" in usage_data and usage_data["prompt_tokens_details"]:
            cached = usage_data["prompt_tokens_details"].get("cached_tokens", 0)
        elif "cache_read_input_tokens" in usage_data:
            cached = usage_data.get("cache_read_input_tokens", 0)
        state["cached_tokens"] = cached
        if session_id == self.current_session_id:
            self._update_context_label()

    def _on_stream_finished(self, session_id: str):
        if session_id not in self.session_states: return
        state = self.session_states[session_id]
        
        # 【修复】防止 _on_stop_clicked 已经保存过的重复存库
        if state["full_text"] and state["is_generating"]:
            message_dao.add_message(session_id, "assistant", state["full_text"])
            
        state["is_generating"] = False
        
        # 【修复】异步清理 Worker 资源，释放 QThread 内存
        if state.get("worker"):
            state["worker"].deleteLater()
            state["worker"] = None
        
        # 2. 只有当前会话才更新 UI
        if session_id == self.current_session_id:
            if self.flush_timer.isActive(): self.flush_timer.stop()
            self._flush_token_buffer() 
            
            self._call_js("finishAiMessage")
            elapsed = time.time() - state["start_time"] if state["start_time"] > 0 else 0
            self._reset_send_button()
            self._call_js("showMeta", state["usage"], elapsed, state["cached_tokens"])
            self._update_context_label()

    def _on_error_occurred(self, error_msg: str, session_id: str):
        if session_id not in self.session_states: return
        state = self.session_states[session_id]
        
        # 【修复】错误时也紧急保存已生成的部分内容
        if state["full_text"] and state["is_generating"]:
            message_dao.add_message(session_id, "assistant", state["full_text"])
        state["is_generating"] = False
        
        # 【修复】异步清理 Worker 资源
        if state.get("worker"):
            state["worker"].deleteLater()
            state["worker"] = None
        
        if session_id == self.current_session_id:
            if self.flush_timer.isActive(): self.flush_timer.stop()
            self._flush_token_buffer()
            self._call_js("showError", error_msg)
            self._reset_send_button()
