import json
import uuid

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from .core import now_str

# ============================================================
# 通用组件
# ============================================================

class ConversationListDialog(QDialog):
    """
    智能体多会话列表。

    功能：
    1. 查看历史会话；
    2. 选择一个会话继续对话；
    3. 自定义会话名称；
    4. 新建空会话；
    5. 删除不需要的会话。
    """

    def __init__(self, sessions, current_session_id="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("对话列表")
        self.resize(620, 520)

        # 深拷贝，避免用户点取消时直接改动外部数据
        try:
            self.sessions = json.loads(json.dumps(sessions or [], ensure_ascii=False))
        except Exception:
            self.sessions = [dict(x) for x in (sessions or []) if isinstance(x, dict)]

        self.current_session_id = current_session_id or ""
        self.selected_session_id = current_session_id or ""

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 20, 20, 20)
        root.setSpacing(12)

        title = QLabel("对话列表")
        title.setObjectName("section_title")
        root.addWidget(title)

        hint = QLabel("选择一个会话继续对话，也可以给会话自定义名称，方便以后查找。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        body = QHBoxLayout()
        body.setSpacing(14)

        # 左侧会话列表
        left_card = QFrame()
        left_card.setObjectName("card")
        left = QVBoxLayout(left_card)
        left.setContentsMargins(12, 12, 12, 12)
        left.setSpacing(10)

        list_title = QLabel("历史会话")
        list_title.setObjectName("sub_title")
        left.addWidget(list_title)

        self.list_widget = QListWidget()
        left.addWidget(self.list_widget, 1)

        list_btn_row = QHBoxLayout()
        self.new_btn = QPushButton("+ 新建")
        self.delete_btn = QPushButton("删除")
        self.delete_btn.setObjectName("danger")
        list_btn_row.addWidget(self.new_btn)
        list_btn_row.addWidget(self.delete_btn)
        list_btn_row.addStretch()
        left.addLayout(list_btn_row)

        # 右侧详情
        right_card = QFrame()
        right_card.setObjectName("card")
        right = QVBoxLayout(right_card)
        right.setContentsMargins(16, 16, 16, 16)
        right.setSpacing(10)

        detail_title = QLabel("会话详情")
        detail_title.setObjectName("sub_title")
        right.addWidget(detail_title)

        name_label = QLabel("会话名称")
        name_label.setObjectName("field_label")
        right.addWidget(name_label)

        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("例如：项目需求讨论 / API 调试 / 文案修改")
        right.addWidget(self.name_input)

        self.save_name_btn = QPushButton("保存名称")
        self.save_name_btn.setObjectName("primary")
        right.addWidget(self.save_name_btn)

        self.meta_label = QLabel("")
        self.meta_label.setObjectName("hint")
        self.meta_label.setWordWrap(True)
        right.addWidget(self.meta_label)

        right.addStretch()

        body.addWidget(left_card, 2)
        body.addWidget(right_card, 3)
        root.addLayout(body, 1)

        bottom = QHBoxLayout()
        bottom.addStretch()
        self.cancel_btn = QPushButton("取消")
        self.open_btn = QPushButton("打开此会话")
        self.open_btn.setObjectName("primary")
        bottom.addWidget(self.cancel_btn)
        bottom.addWidget(self.open_btn)
        root.addLayout(bottom)

        self.list_widget.currentRowChanged.connect(self.on_select)
        self.save_name_btn.clicked.connect(self.save_current_name)
        self.new_btn.clicked.connect(self.create_session)
        self.delete_btn.clicked.connect(self.delete_current_session)
        self.cancel_btn.clicked.connect(self.reject)
        self.open_btn.clicked.connect(self.accept_selected)

        self.refresh_list()

        # 默认选中当前会话
        target_row = 0
        for i, sess in enumerate(self.sessions):
            if sess.get("id") == self.current_session_id:
                target_row = i
                break

        if self.sessions:
            self.list_widget.setCurrentRow(target_row)
        else:
            self.create_session()

    def _session_display_title(self, sess):
        title = (sess.get("title") or "").strip() or "未命名会话"
        count = len(sess.get("messages") or [])
        updated = sess.get("updated_at") or ""
        if sess.get("id") == self.current_session_id:
            return f"▶ 当前｜{title}    ({count} 条)    {updated}"
        return f"　　{title}    ({count} 条)    {updated}"

    def refresh_list(self):
        self.list_widget.blockSignals(True)
        self.list_widget.clear()

        # 最近更新的会话排前面
        try:
            self.sessions.sort(key=lambda x: x.get("updated_at", ""), reverse=True)
        except Exception:
            pass

        current_row = -1

        for row, sess in enumerate(self.sessions):
            item = QListWidgetItem(self._session_display_title(sess))
            sid = sess.get("id", "")
            item.setData(Qt.UserRole, sid)

            title = (sess.get("title") or "").strip() or "未命名会话"
            item.setToolTip(
                f"会话：{title}\n"
                f"ID：{sid}\n"
                f"消息数：{len(sess.get('messages') or [])}\n"
                f"创建时间：{sess.get('created_at', '')}\n"
                f"更新时间：{sess.get('updated_at', '')}"
            )

            if sid == self.current_session_id:
                current_row = row
                try:
                    item.setBackground(QColor("#1f6feb"))
                    item.setForeground(QColor("#ffffff"))
                except Exception:
                    pass

            self.list_widget.addItem(item)

        self.list_widget.blockSignals(False)

        if current_row >= 0:
            try:
                self.list_widget.scrollToItem(self.list_widget.item(current_row))
            except Exception:
                pass

    def _current_session(self):
        item = self.list_widget.currentItem()
        if not item:
            return None

        sid = item.data(Qt.UserRole)
        for sess in self.sessions:
            if sess.get("id") == sid:
                return sess

        return None

    def _persist_to_parent(self):
        try:
            parent = self.parent()
            required = ("sessions", "current_session_id", "_save_sessions_data")
            if parent is None or not all(hasattr(parent, name) for name in required):
                return

            parent.sessions = json.loads(json.dumps(self.sessions or [], ensure_ascii=False))
            if self.selected_session_id:
                parent.current_session_id = self.selected_session_id
            parent._save_sessions_data()
        except Exception:
            pass

    def on_select(self, row):
        sess = self._current_session()
        if not sess:
            self.name_input.clear()
            self.meta_label.setText("")
            self.delete_btn.setEnabled(False)
            self.open_btn.setEnabled(False)
            return

        self.delete_btn.setEnabled(True)
        self.open_btn.setEnabled(True)

        self.name_input.blockSignals(True)
        self.name_input.setText(sess.get("title", ""))
        self.name_input.blockSignals(False)

        created = sess.get("created_at", "")
        updated = sess.get("updated_at", "")
        count = len(sess.get("messages") or [])
        state = "当前正在打开的会话" if sess.get("id") == self.current_session_id else "历史会话"
        self.meta_label.setText(
            f"状态：{state}\n"
            f"创建时间：{created}\n"
            f"更新时间：{updated}\n"
            f"消息数量：{count}\n"
            f"会话 ID：{sess.get('id', '')}"
        )

    def save_current_name(self):
        sess = self._current_session()
        if not sess:
            return

        name = self.name_input.text().strip()
        if not name:
            QMessageBox.warning(self, "提示", "会话名称不能为空。")
            return

        sess["title"] = name
        sess["custom_title"] = True
        sess["updated_at"] = now_str()
        self.selected_session_id = sess.get("id", "")
        self._persist_to_parent()
        self.refresh_list()

        # 重新选中刚刚修改的会话
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item and item.data(Qt.UserRole) == sess.get("id"):
                self.list_widget.setCurrentRow(i)
                break

        QMessageBox.information(self, "完成", "会话名称已保存。")

    def create_session(self):
        t = now_str()
        sess = {
            "id": uuid.uuid4().hex,
            "title": f"新对话 {t}",
            "custom_title": False,
            "created_at": t,
            "updated_at": t,
            "messages": [],
        }
        self.sessions.insert(0, sess)
        self.selected_session_id = sess["id"]
        self._persist_to_parent()
        self.refresh_list()
        self.list_widget.setCurrentRow(0)

    def delete_current_session(self):
        sess = self._current_session()
        if not sess:
            return

        if len(self.sessions) <= 1:
            QMessageBox.warning(self, "提示", "至少需要保留一个会话。")
            return

        ret = QMessageBox.warning(
            self,
            "删除会话",
            f"确定要删除会话：{sess.get('title', '未命名会话')}？\n\n此操作不可恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No
        )
        if ret != QMessageBox.Yes:
            return

        sid = sess.get("id")
        self.sessions = [x for x in self.sessions if x.get("id") != sid]

        if self.selected_session_id == sid:
            self.selected_session_id = self.sessions[0].get("id", "") if self.sessions else ""

        self._persist_to_parent()
        self.refresh_list()
        self.list_widget.setCurrentRow(0 if self.sessions else -1)

    def accept_selected(self):
        sess = self._current_session()
        if not sess:
            QMessageBox.warning(self, "提示", "请选择一个会话。")
            return

        self.selected_session_id = sess.get("id", "")
        self.accept()

    def get_result(self):
        return self.sessions, self.selected_session_id
