import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from qfluentwidgets import setTheme, Theme, qconfig
from src.ui.main_window import MainWindow
from src.core.config_manager import ConfigManager # <--- 新增导入

if __name__ == '__main__':
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    
    # 【修改】读取配置中的主题
    config = ConfigManager()
    theme_mode = Theme.DARK if config.get_theme() == "Dark" else Theme.LIGHT
    qconfig.set(qconfig.themeMode, theme_mode)
    setTheme(theme_mode)

    font = QFont("Microsoft YaHei", 10) 
    app.setFont(font)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())