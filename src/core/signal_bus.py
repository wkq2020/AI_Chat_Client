from PySide6.QtCore import QObject, Signal

class SignalBus(QObject):
    config_updated = Signal()
    theme_changed = Signal(str) # 【新增】传递 theme_id
    
signal_bus = SignalBus()
