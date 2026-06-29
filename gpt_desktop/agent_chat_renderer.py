import html
import os

from PySide6.QtCore import QUrl

from .core import (
    format_file_size,
    hide_uploaded_file_content_for_display,
    md_to_html,
)


class AgentChatRenderer:
    """
    智能体聊天区 HTML 渲染器。

    只负责把消息数据转换成 QTextBrowser 可显示的 HTML，不处理点击事件、
    滚动状态、线程或网络请求。
    """

    def __init__(self, messages, max_render_messages=30, streaming_text=None):
        self.messages = messages if isinstance(messages, list) else []
        self.max_render_messages = int(max_render_messages or 30)
        self.streaming_text = streaming_text

    @staticmethod
    def extract_display_text(msg):
        """
        只负责聊天窗口显示。

        消息本体仍然保存完整内容，用于发给智能体；这里在界面显示时，
        把用户上传文件的源码全文隐藏成附件列表。
        """
        if not isinstance(msg, dict):
            return ""

        role = msg.get("role", "")
        content = msg.get("content", "")

        if isinstance(content, list):
            texts, imgs = [], 0
            for it in content:
                if isinstance(it, dict):
                    if it.get("type") == "text":
                        texts.append(it.get("text", ""))
                    elif it.get("type") == "image_url":
                        imgs += 1

            text = "\n".join(texts)

            if role == "user":
                text = hide_uploaded_file_content_for_display(text)

            if imgs:
                text += f"\n\n[已附加图片 {imgs} 张]"

            return text

        text = str(content)

        if role == "user":
            text = hide_uploaded_file_content_for_display(text)

        return text

    @staticmethod
    def display_text_with_balanced_code_fence(text):
        text = text or ""
        try:
            if text.count("```") % 2 == 1:
                return text + "\n```"
        except Exception:
            pass
        return text

    def action_links_html(self, index, role):
        if index is None:
            return ""
        try:
            local_status = False
            msg = self.messages[index]
            if isinstance(msg, dict):
                local_status = bool(msg.get("_local_status"))
        except Exception:
            local_status = False

        links = [
            f'<a href="app://copy/{index}">复制</a>',
        ]
        if role != "assistant" or not local_status:
            links.append(f'<a href="app://retry/{index}">重发</a>')
        links.append(f'<a href="app://delete/{index}">删除</a>')
        return '<div class="actions">' + ' &nbsp;|&nbsp; '.join(links) + '</div>'

    @staticmethod
    def message_table_html(box_html, actions_html="", align="left", role="assistant"):
        role = str(role or "assistant")
        if role == "user":
            bg = "#171c25"
            border = "#28364d"
        elif role == "error":
            bg = "#1e171b"
            border = "#3a2429"
        else:
            bg = "#181a20"
            border = "#292d36"
        return (
            '<table width="100%" cellspacing="0" cellpadding="0" border="0" '
            f'style="margin:0 0 18px 0; background-color:{bg}; border:1px solid {border};">'
            '<tr><td style="padding:12px 14px 12px 14px;">'
            f'{box_html}{actions_html}'
            '</td></tr></table>'
        )

    @staticmethod
    def message_attachments_html(msg, message_index=None):
        if not isinstance(msg, dict):
            return ""

        parts = []
        image_paths = msg.get("_uploaded_image_paths") or []
        file_paths = msg.get("_uploaded_file_paths") or []
        if not isinstance(image_paths, list):
            image_paths = []
        if not isinstance(file_paths, list):
            file_paths = []

        thumbs = []
        for i, path in enumerate([p for p in image_paths if isinstance(p, str) and p][:6]):
            if os.path.exists(path):
                safe_path = html.escape(QUrl.fromLocalFile(path).toString(), quote=True)
                title = html.escape(os.path.basename(path), quote=True)
                thumbs.append(
                    f'<a href="app://preview-image/{message_index}/{i}">'
                    f'<img class="thumb" src="{safe_path}" width="112" height="78" title="{title}"></a>'
                )
            else:
                thumbs.append('<span class="attach-file">图片缺失</span>')
        if thumbs:
            parts.append('<div>' + ''.join(thumbs) + '</div>')

        for path in [p for p in file_paths if isinstance(p, str) and p][:6]:
            name = os.path.basename(path) or str(path)
            try:
                size_text = format_file_size(os.path.getsize(path)) if os.path.exists(path) else "文件缺失"
            except Exception:
                size_text = ""
            parts.append(
                '<div class="attach-file" style="background-color:#181a20; border:1px solid #3a3d46; padding:6px 8px; margin-top:6px;">'
                f'{html.escape(name)} &nbsp; {html.escape(size_text)}'
                '</div>'
            )
        return ''.join(parts)

    def message_to_html(self, msg, index):
        role = msg.get("role", "") if isinstance(msg, dict) else ""
        if role not in ("user", "assistant"):
            return ""

        local_status = msg.get("_local_status")
        if local_status == "context_cleared":
            return (
                f'<a name="msg-{index}"></a>'
                '<div class="notice" style="'
                'text-align:center; margin:18px 0; padding:12px 18px; '
                'border-top:1px solid #30333b; border-bottom:1px solid #30333b; '
                'color:#aeb4c0;">'
                '<div style="font-weight:800; color:#d7dce5; margin-bottom:4px;">上下文已清除</div>'
                '<div style="font-size:12px;">此前聊天记录仍保留在界面中，智能体后续不会再读取这条提示之前的历史内容。</div>'
                '</div>'
            )
        if local_status == "context_compressed":
            detail = html.escape(str(msg.get("content", "") or "较早聊天已压缩为摘要，最近原文仍会保留。"))
            return (
                f'<a name="msg-{index}"></a>'
                '<div class="notice" style="'
                'text-align:center; margin:18px 0; padding:12px 18px; '
                'border-top:1px solid #30333b; border-bottom:1px solid #30333b; '
                'color:#aeb4c0;">'
                '<div style="font-weight:800; color:#d7dce5; margin-bottom:4px;">上下文已自动压缩</div>'
                f'<div style="font-size:12px;">{detail}</div>'
                '</div>'
            )

        is_error = bool(local_status) or str(msg.get("content", "")).lstrip().startswith("[请求失败]")
        display_role = "error" if is_error and role == "assistant" else role
        name = "你：" if role == "user" else "智能体："
        text = self.display_text_with_balanced_code_fence(self.extract_display_text(msg))
        body = md_to_html(text)
        attachments = self.message_attachments_html(msg, index) if role == "user" else ""
        actions = self.action_links_html(index, role)
        meta_class = "meta-error" if display_role == "error" else f"meta-{role}"
        box = (
            f'<a name="msg-{index}"></a>'
            f'<div class="meta {meta_class}">{name}</div>'
            f'<div class="msg-body">{body}{attachments}</div>'
        )
        return self.message_table_html(box, actions_html=actions, role=display_role)

    @staticmethod
    def chat_history_notice_html(hidden_count):
        if hidden_count <= 0:
            return ""
        return (
            '<div class="notice" style="border:1px solid #30333b; padding:7px 12px; margin-bottom:14px;">'
            f'已隐藏更早的 {hidden_count} 条消息，'
            '<a href="app://load-more">点击加载更早 30 条</a>'
            '</div>'
        )

    @staticmethod
    def streaming_html_from_text(text):
        if text is None:
            return ""

        if not text:
            return '<span style="color:#a1a7b3;"><i>正在思考...</i></span>'

        return md_to_html(text)

    def streaming_html(self):
        return self.streaming_html_from_text(self.streaming_text)

    @classmethod
    def streaming_message_html(cls, body, outer_margin=False):
        html_text = (
            '<div style="display:block; width:100%;">'
            + cls.message_table_html(
            '<div class="meta meta-assistant">智能体：</div>'
            f'<div class="msg-body">{body}</div>',
            role="assistant",
            )
            + '</div>'
        )
        if outer_margin:
            return f'<div style="margin:12px 14px 20px 14px;">{html_text}</div>'
        return html_text

    def render_chat_html(self, include_streaming=True):
        display_messages = self.messages[-self.max_render_messages:]
        hidden_count = max(0, len(self.messages) - len(display_messages))
        start_index = max(0, len(self.messages) - len(display_messages))

        parts = [
            '<html><head><meta charset="utf-8"></head>'
            '<body style="background:#15161a; color:#e8e8ea; margin:12px 14px 20px 14px;">'
        ]
        parts.append(self.chat_history_notice_html(hidden_count))

        has_message = False
        for offset, msg in enumerate(display_messages):
            chunk = self.message_to_html(msg, start_index + offset)
            if chunk:
                has_message = True
                parts.append(chunk)

        if include_streaming and self.streaming_text is not None:
            body = self.streaming_html_from_text(self.streaming_text)
            parts.append(self.streaming_message_html(body))
            has_message = True

        if not has_message:
            parts.append('<div style="color:#6a6c72; text-align:center; padding:40px;">开始一段新的对话吧</div>')

        parts.append('</body></html>')
        return ''.join(parts)
