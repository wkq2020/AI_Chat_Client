from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout, QListWidgetItem, 
    QMessageBox, QWidget, QGroupBox
)
from PySide6.QtCore import Qt
from qfluentwidgets import (
    PushButton, ListWidget, LineEdit, ComboBox, SubtitleLabel, BodyLabel, 
    PrimaryPushButton, FluentIcon, CheckBox, isDarkTheme, setTheme, Theme, qconfig
)
from src.core.config_manager import ConfigManager, THEMES
from src.core.signal_bus import signal_bus

class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("设置中心")
        self.resize(750, 550)
        
        self.config = ConfigManager()
        self.current_models = [] 
        
        self._init_ui()
        self._load_data()
        
        # 【新增】监听全局主题变化，实时刷新弹窗自身的样式
        qconfig.themeChanged.connect(self.apply_theme_styles)
        self.apply_theme_styles() # 初始化时应用一次

    def apply_theme_styles(self):
        """【新增】提取样式逻辑，支持热更新"""
        bg_color = "#202020" if isDarkTheme() else "#f9f9f9"
        text_color = "#e0e0e0" if isDarkTheme() else "#000000"
        border_color = "#383838" if isDarkTheme() else "#e0e0e0"
        
        self.setStyleSheet(f"""
            SettingsDialog {{ background-color: {bg_color}; color: {text_color}; }}
            QGroupBox {{
                background-color: transparent; border: 1px solid {border_color};
                border-radius: 8px; margin-top: 12px; padding-top: 12px; color: {text_color};
            }}
            QGroupBox::title {{
                subcontrol-origin: margin; subcontrol-position: top left;
                left: 10px; padding: 0 5px; color: {text_color};
            }}
            QLabel {{ color: {text_color}; }}
        """)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        
        preset_layout = QHBoxLayout()
        preset_layout.addWidget(BodyLabel("外观预设:"))
        self.theme_preset_combo = ComboBox()
        self.theme_preset_combo.addItems([t["name"] for t in THEMES.values()])
        self.theme_preset_combo.currentIndexChanged.connect(self._on_preset_changed)
        preset_layout.addWidget(self.theme_preset_combo)
        preset_layout.addStretch()
        layout.addLayout(preset_layout)
        
        layout.addWidget(SubtitleLabel("API 配置管理"))
        api_list_layout = QHBoxLayout()
        self.api_list = ListWidget()
        self.api_list.setMaximumWidth(180)
        self.api_list.currentRowChanged.connect(self._on_api_selected)
        api_list_layout.addWidget(self.api_list)
        right_widget = QWidget()
        right_layout = QVBoxLayout(right_widget)
        form_widget = QWidget()
        form_layout = QFormLayout(form_widget)
        self.name_edit = LineEdit()
        self.url_edit = LineEdit()
        self.key_edit = LineEdit()
        self.key_edit.setEchoMode(LineEdit.Password)
        form_layout.addRow("配置名称:", self.name_edit)
        form_layout.addRow("Base URL:", self.url_edit)
        form_layout.addRow("API Key:", self.key_edit)
        right_layout.addWidget(form_widget)
        model_group = QGroupBox("模型与能力配置")
        model_layout = QVBoxLayout(model_group)
        model_list_layout = QHBoxLayout()
        self.model_list = ListWidget()
        self.model_list.setMaximumHeight(120)
        self.model_list.currentRowChanged.connect(self._on_model_selected)
        model_list_layout.addWidget(self.model_list)
        model_btn_layout = QVBoxLayout()
        self.add_model_btn = PushButton(FluentIcon.ADD, "添加")
        self.add_model_btn.clicked.connect(self._add_model)
        self.del_model_btn = PushButton(FluentIcon.DELETE, "删除")
        self.del_model_btn.clicked.connect(self._del_model)
        model_btn_layout.addWidget(self.add_model_btn)
        model_btn_layout.addWidget(self.del_model_btn)
        model_btn_layout.addStretch()
        model_list_layout.addLayout(model_btn_layout)
        model_layout.addLayout(model_list_layout)
        self.model_detail_widget = QWidget()
        detail_layout = QFormLayout(self.model_detail_widget)
        self.model_id_edit = LineEdit()
        self.model_id_edit.setPlaceholderText("API 请求用的 ID，如 deepseek-chat")
        self.model_name_edit = LineEdit()
        self.model_name_edit.setPlaceholderText("界面显示的名称，如 DeepSeek V3")
        detail_layout.addRow("模型 ID:", self.model_id_edit)
        detail_layout.addRow("显示名称:", self.model_name_edit)
        cap_layout = QHBoxLayout()
        self.cap_reasoning = CheckBox("深度思考")
        self.cap_search = CheckBox("联网搜索")
        self.cap_partial = CheckBox("前缀续写")
        self.cap_cache = CheckBox("上下文缓存")
        self.cap_vision = CheckBox("视觉识别")
        cap_layout.addWidget(self.cap_reasoning)
        cap_layout.addWidget(self.cap_search)
        cap_layout.addWidget(self.cap_partial)
        cap_layout.addWidget(self.cap_cache)
        cap_layout.addWidget(self.cap_vision)
        detail_layout.addRow("支持能力:", cap_layout)
        # 【新增】思考控制协议选择
        control_layout = QHBoxLayout()
        control_layout.addWidget(BodyLabel("思考控制协议:"))
        self.thinking_control_combo = ComboBox()
        self.thinking_control_combo.addItems([
            "无 (普通模型)", 
            "DeepSeek 协议 (强度控制)", 
            "通义千问 协议 (预算控制)"
        ])
        self.thinking_control_combo.setFixedWidth(200)
        control_layout.addWidget(self.thinking_control_combo)
        control_layout.addStretch()
        detail_layout.addRow(control_layout)
        self.model_detail_widget.setVisible(False)
        model_layout.addWidget(self.model_detail_widget)
        right_layout.addWidget(model_group)
        btn_layout = QHBoxLayout()
        self.add_api_btn = PushButton(FluentIcon.ADD, "新增 API")
        self.add_api_btn.clicked.connect(self._add_new_api)
        self.save_api_btn = PrimaryPushButton(FluentIcon.SAVE, "保存 API 配置")
        self.save_api_btn.clicked.connect(self._save_current_api)
        self.delete_api_btn = PushButton(FluentIcon.DELETE, "删除 API")
        self.delete_api_btn.clicked.connect(self._delete_current_api)
        btn_layout.addWidget(self.add_api_btn)
        btn_layout.addWidget(self.save_api_btn)
        btn_layout.addWidget(self.delete_api_btn)
        right_layout.addLayout(btn_layout)
        api_list_layout.addWidget(right_widget)
        layout.addLayout(api_list_layout)
        close_btn = PushButton("关闭")
        close_btn.clicked.connect(self.accept)
        layout.addWidget(close_btn)

    def _load_data(self):
        # 回显外观预设
        current_theme_id = self.config.config.get("current_theme", "default_dark")
        theme_ids = list(THEMES.keys())
        if current_theme_id in theme_ids:
            self.theme_preset_combo.setCurrentIndex(theme_ids.index(current_theme_id))
            
        self._refresh_api_list()

    def _refresh_api_list(self, select_id=None):
        self.api_list.clear()
        apis = self.config.get_apis()
        for api in apis:
            item = QListWidgetItem(api['name'])
            item.setData(100, api['id']) 
            self.api_list.addItem(item)
            if select_id == api['id']:
                self.api_list.setCurrentItem(item)
        if not apis:
            self._clear_form()

    def _on_api_selected(self, row):
        if row < 0: self._clear_form(); return
        item = self.api_list.item(row)
        api_id = item.data(100)
        api = next((a for a in self.config.get_apis() if a['id'] == api_id), None)
        if api:
            self.name_edit.setText(api['name'])
            self.url_edit.setText(api['base_url'])
            self.key_edit.setText(api['api_key'])
            self.current_models = api.get('models', [])
            self._refresh_model_list()

    def _clear_form(self):
        self.name_edit.clear(); self.url_edit.clear(); self.key_edit.clear()
        self.current_models = []; self._refresh_model_list()

    def _refresh_model_list(self, select_idx=None):
        self.model_list.clear()
        for m in self.current_models: self.model_list.addItem(m.get('name') or m.get('id'))
        if select_idx is not None and select_idx < self.model_list.count(): self.model_list.setCurrentRow(select_idx)
        elif self.model_list.count() > 0: self.model_list.setCurrentRow(0)
        else: self.model_detail_widget.setVisible(False)

    def _on_model_selected(self, row):
        if row < 0 or row >= len(self.current_models): self.model_detail_widget.setVisible(False); return
        self.model_detail_widget.setVisible(True)
        model = self.current_models[row]
        self.model_id_edit.setText(model.get('id', ''))
        self.model_name_edit.setText(model.get('name', ''))
        caps = model.get('capabilities', [])
        self.cap_reasoning.setChecked('reasoning' in caps)
        self.cap_search.setChecked('search' in caps)
        self.cap_partial.setChecked('partial' in caps)
        self.cap_cache.setChecked('cache' in caps)
        self.cap_vision.setChecked('vision' in caps)
        # 【新增】读取思考控制协议并映射到 UI
        ctrl = model.get('thinking_control', 'none')
        if ctrl == 'deepseek':
            self.thinking_control_combo.setCurrentText("DeepSeek 协议 (强度控制)")
        elif ctrl == 'qwen':
            self.thinking_control_combo.setCurrentText("通义千问 协议 (预算控制)")
        else:
            self.thinking_control_combo.setCurrentText("无 (普通模型)")

    def _save_model_detail(self):
        row = self.model_list.currentRow()
        if row < 0 or row >= len(self.current_models): return
        model = self.current_models[row]
        model['id'] = self.model_id_edit.text().strip()
        model['name'] = self.model_name_edit.text().strip() or model['id']
        caps = []
        if self.cap_reasoning.isChecked(): caps.append('reasoning')
        if self.cap_search.isChecked(): caps.append('search')
        if self.cap_partial.isChecked(): caps.append('partial')
        if self.cap_cache.isChecked(): caps.append('cache')
        if self.cap_vision.isChecked(): caps.append('vision')
        model['capabilities'] = caps
        # 【新增】保存思考控制协议 (从 UI 映射回底层值)
        ctrl_text = self.thinking_control_combo.currentText()
        if "DeepSeek" in ctrl_text:
            model['thinking_control'] = 'deepseek'
        elif "千问" in ctrl_text:
            model['thinking_control'] = 'qwen'
        else:
            model['thinking_control'] = 'none'
        self.model_list.item(row).setText(model['name'])

    def _add_model(self):
        self._save_model_detail()
        new_model = {"id": "new-model", "name": "新模型", "capabilities": []}
        self.current_models.append(new_model)
        self._refresh_model_list(select_idx=len(self.current_models)-1)

    def _del_model(self):
        row = self.model_list.currentRow()
        if row >= 0: self.current_models.pop(row); self._refresh_model_list()

    def _add_new_api(self):
        self.api_list.clearSelection(); self._clear_form(); self.name_edit.setFocus()

    def _save_current_api(self):
        self._save_model_detail()
        name = self.name_edit.text().strip()
        url = self.url_edit.text().strip()
        key = self.key_edit.text().strip()
        if not name or not url: QMessageBox.warning(self, "警告", "名称和 Base URL 不能为空！"); return
        valid_models = [m for m in self.current_models if m.get('id')]
        current_item = self.api_list.currentItem()
        if current_item:
            api_id = current_item.data(100)
            self.config.update_api(api_id, name, url, key, valid_models)
            self._refresh_api_list(select_id=api_id)
        else:
            api_id = self.config.add_api(name, url, key)
            self.config.update_api(api_id, name, url, key, valid_models)
            self._refresh_api_list(select_id=api_id)
            
        # 【核心新增】保存成功后，广播配置更新信号，通知主界面刷新！
        signal_bus.config_updated.emit()
        QMessageBox.information(self, "成功", "配置已保存并实时生效！")

    def _delete_current_api(self):
        current_item = self.api_list.currentItem()
        if not current_item: return
        self.config.delete_api(current_item.data(100))
        self._refresh_api_list()
        signal_bus.config_updated.emit() # 删除也广播

    def _on_theme_changed(self, theme):
        self.config.set_theme(theme)
        # 【核心新增】直接调用 Fluent 的主题切换，无需重启！
        new_theme = Theme.DARK if theme == "Dark" else Theme.LIGHT
        setTheme(new_theme)

    def _on_preset_changed(self, index):
        theme_ids = list(THEMES.keys())
        if 0 <= index < len(theme_ids):
            theme_id = theme_ids[index]
            self.config.set_current_theme(theme_id)
            # 广播主题切换信号，主窗口会立刻响应并热更新 (包含 setTheme)
            signal_bus.theme_changed.emit(theme_id)