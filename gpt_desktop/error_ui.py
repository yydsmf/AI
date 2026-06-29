from PySide6.QtWidgets import QMessageBox

from .core import clean_error_text, now_str


def show_generation_error(widget, title, err, status=None, log_func=None):
    """
    统一生成/API 失败展示：
    - 清理错误文本；
    - 状态栏显示短状态；
    - 任务日志记录完整错误；
    - 弹窗显示完整错误。
    """
    cleaned = clean_error_text(err)
    status_text = status or title

    try:
        if hasattr(widget, "bar"):
            widget.bar.set_status(status_text)
    except Exception:
        pass

    if log_func is not None:
        try:
            log_func(f"[{now_str()}] 失败：{cleaned}")
        except Exception:
            pass

    try:
        QMessageBox.critical(widget, title, cleaned)
    except Exception:
        pass

    return cleaned
