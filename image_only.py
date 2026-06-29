import os
import sys


os.environ.setdefault(
    "GPT_DESKTOP_APP_DIR",
    os.path.join(os.path.expanduser("~"), ".gpt_image_generator_app"),
)

from PySide6.QtWidgets import QApplication

from main import APP_STYLE, ImageOnlyWindow, install_chinese_context_menu


def main():
    app = QApplication(sys.argv)
    app.setStyleSheet(APP_STYLE)

    try:
        install_chinese_context_menu(app)
    except Exception as e:
        print("安装中文右键菜单失败:", e)

    win = ImageOnlyWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
