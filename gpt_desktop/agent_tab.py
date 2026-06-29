from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from .agent_attachment_actions import AgentAttachmentsMixin
from .agent_attachments import AgentAttachmentList
from .agent_chat_copy import AgentChatCopyMixin
from .agent_chat_flow import AgentChatFlowMixin
from .agent_chat_links import AgentChatLinksMixin
from .agent_chat_render import AgentChatRenderMixin
from .agent_chat_scroll import AgentChatScrollMixin
from .agent_conversation_state import AgentConversationStateMixin
from .agent_input_draft import AgentInputDraftMixin
from .agent_input_events import AgentInputEventsMixin
from .agent_message_actions import AgentMessageActionsMixin
from .agent_model_bar import AgentModelBarMixin
from .agent_sessions import AgentSessionMixin
from .widgets import ProviderModelBar, show_image_preview

# ============================================================
# 智能体 Tab
# ============================================================

class AgentTab(
    AgentChatScrollMixin,
    AgentChatCopyMixin,
    AgentChatFlowMixin,
    AgentChatLinksMixin,
    AgentChatRenderMixin,
    AgentConversationStateMixin,
    AgentInputDraftMixin,
    AgentInputEventsMixin,
    AgentModelBarMixin,
    AgentSessionMixin,
    AgentMessageActionsMixin,
    AgentAttachmentsMixin,
    QWidget,
):
    IMAGE_ATTACHMENT_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


    request_settings = Signal()

    USER_BG = "#2b2d34"
    USER_FG = "#f2f3f5"
    BOT_BG = "#22242b"
    BOT_FG = "#f0f1f3"
    LABEL_FG = "#b8beca"

    def __init__(self, config):
        super().__init__()
        self.config = config
        self._init_state()
        self._init_timers()

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(14)

        self._build_header(root)
        self._build_model_bar(root)
        self._build_chat_view(root)
        self._build_attachment_list(root)
        self._build_composer(root)
        self._connect_actions()
        self._finish_initial_load()

    def _init_state(self):
        # 多会话数据。
        # self.messages 始终代表当前打开会话的消息。
        self.sessions = []
        self.current_session_id = ""
        self.messages = []

        self.uploaded_images = []
        self.uploaded_files = []
        self.streaming_text = None
        self.worker = None
        self.model_worker = None
        self._pending_model_reload = False
        self._zombie_workers = []
        self._stopping_task = False
        self._agent_initial_scroll_done = False
        self._chat_bottom_lock = False
        self._chat_bottom_lock_reason = ""
        self._chat_bottom_lock_attempts = 0
        self._follow_streaming_output = True
        self._user_reading_chat_history = False
        self._restoring_agent_session_model_config = False
        self._pending_agent_session_model = ""
        self._chat_history_render_pending = False
        self._chat_incremental_render_target = 30
        self._suppress_resize_rerender_once = False
        self._preserve_chat_scroll_once = False
        self._chat_scroll_restore_token = 0
        self._streaming_doc_start = None
        # 聊天区只实际创建最近 30 条消息对应的 QWidget。
        # 更早消息仍保存在 self.messages / 历史文件中，但不参与 UI 控件创建。
        self.max_render_messages = 30

        # 流式输出增量刷新间隔。
        # 流式输出时只更新最后一个智能体气泡。
        self._chat_render_interval_ms = 140

        # 当前正在流式输出的 QLabel。
        # 流式过程中只更新它的文本，避免聊天区整体闪空。
        self._last_streaming_html = ""

    def _init_timers(self):
        self._render_timer = QTimer(self)
        self._render_timer.setSingleShot(True)
        self._render_timer.setInterval(self._chat_render_interval_ms)
        self._render_timer.timeout.connect(self._flush_streaming_bubble)

        self._chat_save_timer = QTimer(self)
        self._chat_save_timer.setSingleShot(True)
        self._chat_save_timer.timeout.connect(self.save_persistent_chat)

        self._draft_save_timer = QTimer(self)
        self._draft_save_timer.setSingleShot(True)
        self._draft_save_timer.timeout.connect(self.save_agent_input_draft)

        self._chat_resize_timer = QTimer(self)
        self._chat_resize_timer.setSingleShot(True)
        self._chat_resize_timer.timeout.connect(self._rerender_chat_after_resize)

    def _build_header(self, root):
        # 顶部标题行：右上角单独放置设置按钮，避免和常用操作误点
        title_row = QHBoxLayout()
        title = QLabel("智能体")
        title.setObjectName("section_title")
        title_row.addWidget(title)
        title_row.addStretch()

        self.agent_settings_btn = QPushButton("设置")
        self.agent_settings_btn.setObjectName("ghost")
        self.agent_settings_btn.setToolTip("API 厂商管理")
        title_row.addWidget(self.agent_settings_btn)
        root.addLayout(title_row)

    def _build_model_bar(self, root):
        # 厂商/模型条：新对话、清除上下文下移到这里，和厂商/模型/刷新对齐
        bar_row = QHBoxLayout()
        bar_row.setSpacing(8)

        self.bar = ProviderModelBar()
        bar_row.addWidget(self.bar, 1)

        self.session_list_btn = QPushButton("对话列表")
        self.session_list_btn.setObjectName("ghost")
        self.session_list_btn.setToolTip("打开历史会话列表，选择、重命名或删除会话")

        self.new_btn = QPushButton("新对话")
        self.new_btn.setObjectName("ghost")
        self.new_btn.setToolTip("开启一个全新的空会话，不会清空旧会话记录")

        self.clear_btn = QPushButton("清除上下文")
        self.clear_btn.setObjectName("ghost")
        self.clear_btn.setToolTip("清除当前上下文，避免后续回答继续引用旧内容")

        bar_row.addWidget(self.session_list_btn)
        bar_row.addWidget(self.new_btn)
        bar_row.addWidget(self.clear_btn)

        root.addLayout(bar_row)

    def _connect_model_bar_signals(self):
        self.bar.provider_changed.connect(self.on_provider_changed)
        self.bar.model_changed.connect(self.on_model_changed)
        self.bar.refresh_clicked.connect(self.load_models)
        self.bar.settings_clicked.connect(self.request_settings.emit)
        self.agent_settings_btn.clicked.connect(self.request_settings.emit)

    def _build_chat_view(self, root):
        # 聊天区：单个富文本阅读器，避免为每条消息创建大量 QWidget。
        self.chat_view = QTextBrowser()
        self.chat_view.setOpenExternalLinks(False)
        self.chat_view.setOpenLinks(False)
        self.chat_view.setProperty("agent_clean_copy_context_menu", True)
        self.chat_view.setContextMenuPolicy(Qt.CustomContextMenu)
        self.chat_view.customContextMenuRequested.connect(self.show_chat_context_menu_at)
        self.chat_view.anchorClicked.connect(self._on_chat_link_clicked)
        self.chat_view.setMouseTracking(True)
        self.chat_view.setFocusPolicy(Qt.StrongFocus)
        self.chat_view.installEventFilter(self)
        self.chat_view.viewport().setMouseTracking(True)
        self.chat_view.viewport().setFocusPolicy(Qt.StrongFocus)
        self.chat_view.viewport().setProperty("agent_clean_copy_context_menu", True)
        self.chat_view.viewport().installEventFilter(self)
        self.chat_view.setStyleSheet("""
            QTextBrowser {
                background-color: #15161a;
                border: 1px solid #25272e;
                border-radius: 10px;
                padding: 14px;
            }
        """)
        self.chat_view.document().setDefaultStyleSheet("""
            body { color:#e8e8ea; font-size:14px; line-height:1.58; }
            a { color:#8ab4f8; text-decoration:none; }
            .meta { font-weight:800; font-size:13px; padding:0 0 7px 0; }
            .meta-user { color:#8ab4f8; }
            .meta-assistant { color:#d7dce5; }
            .meta-error { color:#ff9aa2; }
            .msg-body { color:#edf0f5; }
            .actions { color:#8b8f99; font-size:12px; padding-top:8px; }
            .notice { color:#8b8f99; font-size:12px; text-align:center; }
            .attach-file { color:#d7dce5; font-size:12px; }
            img.thumb { margin:5px 6px 0 0; }
            pre { margin:0; }
            ul { margin-top:4px; margin-bottom:4px; }
        """)

        self.scroll_bottom_btn = QPushButton("↓", self.chat_view.viewport())
        self.scroll_bottom_btn.setFixedSize(38, 38)
        self.scroll_bottom_btn.setToolTip("回到最新消息")
        self.scroll_bottom_btn.setCursor(Qt.PointingHandCursor)
        self.scroll_bottom_btn.setFocusPolicy(Qt.NoFocus)
        self.scroll_bottom_btn.setStyleSheet("""
            QPushButton {
                background-color: rgba(26, 27, 32, 220);
                color: #dfe3ea;
                border: 1px solid rgba(37, 39, 46, 230);
                border-radius: 19px;
                font-size: 18px;
                font-weight: 800;
                padding: 0;
            }
            QPushButton:hover {
                background-color: rgba(42, 44, 51, 235);
                border-color: rgba(58, 60, 67, 245);
                color: #ffffff;
            }
            QPushButton:pressed {
                background-color: rgba(31, 32, 38, 245);
                border-color: rgba(74, 76, 83, 245);
            }
        """)
        self.scroll_bottom_btn.clicked.connect(self._scroll_to_latest_from_button)
        self.scroll_bottom_btn.hide()

        try:
            self._chat_scroll_bottom_connected = True
            vbar = self.chat_view.verticalScrollBar()
            vbar.rangeChanged.connect(self._on_chat_scroll_range_changed)
            vbar.valueChanged.connect(self._on_chat_scroll_value_changed)
        except Exception:
            pass

        root.addWidget(self.chat_view, 1)

    def _build_attachment_list(self, root):
        # 统一附件栏：图片和文件都显示在同一个区域。
        self.image_list = AgentAttachmentList(self)
        self.attachment_list = self.image_list
        self.image_list.preview_requested.connect(
            lambda p: show_image_preview(self, p, "附图预览")
        )
        self.image_list.item_removed.connect(self._on_image_removed)
        root.addWidget(self.image_list)

    def _build_composer(self, root):
        # 输入卡（高度减半）
        composer_card = QFrame()
        composer_card.setObjectName("card")
        composer = QVBoxLayout(composer_card)
        composer.setContentsMargins(12, 8, 12, 10)
        composer.setSpacing(6)

        self.input = QTextEdit()
        self.input.setPlaceholderText("输入对话内容，可粘贴或上传图片/文件。Enter 发送，Shift+Enter 换行。")
        self.input_min_height = 40
        self.input_max_height = 160
        self.input.setMinimumHeight(self.input_min_height)
        self.input.setMaximumHeight(self.input_max_height)
        self.input.setFixedHeight(self.input_min_height)
        self.input.setAcceptRichText(False)
        self.input.setAcceptDrops(True)
        self.input.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.input.setStyleSheet("QTextEdit { background: transparent; border: none; padding: 0; }")
        self.input.setToolTip("可拖拽文件到这里：图片会作为图片附件，普通文件会作为文件附件。")

        # 恢复上次退出前的智能体输入框草稿
        self.restore_agent_input_draft()
        self.input.textChanged.connect(self.schedule_agent_input_draft_save)
        self.input.textChanged.connect(self.adjust_input_height)
        self.input.installEventFilter(self)
        try:
            self.input.viewport().setAcceptDrops(True)
            self.input.viewport().installEventFilter(self)
        except Exception:
            pass
        composer.addWidget(self.input)

        composer_row = QHBoxLayout()
        composer_row.setSpacing(8)
        self.file_btn = QPushButton("文件")
        self.file_btn.setObjectName("ghost")
        self.file_btn.setMinimumHeight(28)
        self.file_btn.setMaximumWidth(58)
        composer_row.addWidget(self.file_btn)

        self.upload_btn = QPushButton("图片")
        self.upload_btn.setObjectName("ghost")
        self.upload_btn.setMinimumHeight(28)
        self.upload_btn.setMaximumWidth(58)
        composer_row.addWidget(self.upload_btn)

        composer_row.addStretch()

        hint = QLabel("Enter 发送 · Shift+Enter 换行")
        hint.setObjectName("hint")
        composer_row.addWidget(hint)

        self.stop_btn = QPushButton("中止")
        self.stop_btn.setObjectName("danger")
        self.stop_btn.setMinimumWidth(72)
        self.stop_btn.setMinimumHeight(30)
        self.stop_btn.setToolTip("中止当前智能体任务")
        self.stop_btn.setVisible(False)
        self.stop_btn.setEnabled(False)
        composer_row.addWidget(self.stop_btn)

        self.send_btn = QPushButton("发送")
        self.send_btn.setObjectName("primary")
        self.send_btn.setMinimumWidth(96)
        self.send_btn.setMinimumHeight(30)
        composer_row.addWidget(self.send_btn)
        composer.addLayout(composer_row)

        root.addWidget(composer_card)

    def _connect_actions(self):
        # 信号
        self._connect_model_bar_signals()
        self.send_btn.clicked.connect(self.send)
        self.stop_btn.clicked.connect(self.stop_current_task)
        self.session_list_btn.clicked.connect(self.open_conversation_list)
        self.new_btn.clicked.connect(self.new_chat)
        self.clear_btn.clicked.connect(self.clear_context)
        self.upload_btn.clicked.connect(self.upload_images)
        self.file_btn.clicked.connect(self.upload_files)

        paste = QAction("粘贴", self)
        paste.setShortcut("Ctrl+V")
        paste.triggered.connect(self.paste_image_from_clipboard)
        self.addAction(paste)

        for sc in ("Ctrl+Return", "Meta+Return"):
            act = QAction(self)
            act.setShortcut(sc)
            act.triggered.connect(self.send)
            self.addAction(act)

    def _finish_initial_load(self):
        self.refresh_providers()
        self.load_persistent_chat()
        self.bar.set_status("未刷新模型列表")
        QTimer.singleShot(0, self.adjust_input_height)
        QTimer.singleShot(0, self._render_chat_history_after_layout_ready)


# ============================================================
# 附件组件已拆分到 agent_attachments.py
# 视频生成页
# ============================================================
