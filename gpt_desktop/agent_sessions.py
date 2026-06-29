import re
import uuid

from .core import (
    AGENT_HISTORY_FILE,
    AGENT_SESSIONS_FILE,
    load_json_file,
    now_str,
    save_json_file,
)


class AgentSessionMixin:
    """智能体会话加载、保存和上下文截断。"""

    def _make_session(self, title=None, messages=None):
        """
        创建一个会话对象。
        """
        t = now_str()
        provider_id, model = self.current_bar_provider_model()
        return {
            "id": uuid.uuid4().hex,
            "title": title or f"新对话 {t}",
            "custom_title": False,
            "created_at": t,
            "updated_at": t,
            "messages": messages or [],
            "provider_id": provider_id,
            "model": model,
            "context_summary": "",
            "context_summary_source_count": 0,
        }

    def _normalize_loaded_sessions_data(self, data):
        if not isinstance(data, dict) or not isinstance(data.get("sessions"), list):
            return None

        sessions = [x for x in data.get("sessions", []) if isinstance(x, dict)]
        for sess in sessions:
            sess.setdefault("context_summary", "")
            sess.setdefault("context_summary_source_count", 0)
        current_id = data.get("current_session_id", "") or ""

        if not sessions:
            sess = self._make_session()
            sessions = [sess]
            current_id = sess["id"]

        valid_ids = {x.get("id") for x in sessions}
        if current_id not in valid_ids:
            current_id = sessions[0].get("id", "")

        return {
            "version": 1,
            "current_session_id": current_id,
            "sessions": sessions,
        }

    def _migrate_legacy_agent_history(self):
        old_messages = load_json_file(AGENT_HISTORY_FILE, [])
        if not isinstance(old_messages, list):
            old_messages = []

        if old_messages:
            sess = self._make_session("旧会话", old_messages)
        else:
            sess = self._make_session()

        return {
            "version": 1,
            "current_session_id": sess["id"],
            "sessions": [sess],
        }

    def _load_sessions_data(self):
        """
        读取多会话数据。

        兼容历史格式：
        - 如果 agent_sessions.json 不存在；
        - 但 agent_history.json 存在；
        - 则自动把历史迁移为一个会话。
        """
        data = load_json_file(AGENT_SESSIONS_FILE, None)
        normalized = self._normalize_loaded_sessions_data(data)
        if normalized is not None:
            return normalized

        return self._migrate_legacy_agent_history()

    def _save_sessions_data(self):
        """
        保存多会话数据。
        """
        try:
            data = {
                "version": 1,
                "current_session_id": self.current_session_id,
                "sessions": self.sessions,
            }
            save_json_file(AGENT_SESSIONS_FILE, data)
        except Exception:
            pass

    def _save_legacy_current_history_copy(self, messages):
        """
        保存当前会话的轻量兼容副本。
        """
        save_json_file(AGENT_HISTORY_FILE, messages)

    def _current_session(self):
        """
        返回当前打开的会话对象。
        """
        for sess in self.sessions:
            if sess.get("id") == self.current_session_id:
                return sess
        return None

    def _serialize_messages_for_save(self, messages):
        """
        保存到磁盘前，对消息做轻量化处理。

        说明：
        - 文本完整保存；
        - 图片内容不保存 base64；
        - 上传文件正文不保存；
        - 但会保存附件本地路径元数据，供“重新提交”时重新读取。
        """
        safe = []

        for msg in messages:
            if not isinstance(msg, dict):
                continue

            role = msg.get("role", "")
            content = msg.get("content", "")

            out = {"role": role}

            if isinstance(content, list):
                texts, imgs = [], 0

                for it in content:
                    if isinstance(it, dict):
                        if it.get("type") == "text":
                            texts.append(it.get("text", ""))
                        elif it.get("type") == "image_url":
                            imgs += 1

                t = "\n".join(texts)
                if imgs:
                    t += f"\n[已附加图片 {imgs} 张]"

                out["content"] = t
            else:
                out["content"] = content

            # 保留重新提交所需的轻量元数据。
            # 注意：只保存路径和原始输入文字，不保存文件全文和图片 base64。
            for key in ("_resubmit_text", "_uploaded_file_paths", "_uploaded_image_paths", "_local_status"):
                if key in msg:
                    try:
                        out[key] = msg.get(key)
                    except Exception:
                        pass

            safe.append(out)

        return safe

    def _auto_title_from_messages(self, messages):
        """
        从首条用户消息自动生成会话标题。
        仅用于用户没有自定义名称的会话。
        """
        try:
            for msg in messages:
                if not isinstance(msg, dict):
                    continue
                if msg.get("role") != "user":
                    continue

                text = self._extract_display_text(msg).strip()
                text = re.sub(r"\s+", " ", text)
                if text:
                    return text[:28] + ("..." if len(text) > 28 else "")
        except Exception:
            pass

        return ""

    def _update_current_session_messages(self, messages_for_save):
        """
        把当前 self.messages 同步到当前会话。
        """
        sess = self._current_session()

        if sess is None:
            sess = self._make_session()
            self.sessions.insert(0, sess)
            self.current_session_id = sess["id"]

        sess["messages"] = messages_for_save
        sess["updated_at"] = now_str()

        # 用户没有自定义名称时，根据第一条用户消息自动命名，方便查找。
        if not sess.get("custom_title"):
            title = self._auto_title_from_messages(messages_for_save)
            if title:
                sess["title"] = title

    def get_context_cutoff(self):
        """
        获取当前会话的上下文截断点。
        context_cutoff 表示发给模型时从 self.messages[context_cutoff:] 开始读取。
        """
        try:
            sess = self._current_session()
            if not isinstance(sess, dict):
                return 0

            return self._clamp_message_index(sess.get("context_cutoff", 0))
        except Exception:
            return 0

    def set_context_cutoff(self, cutoff):
        """
        设置当前会话的上下文截断点，并持久化。
        """
        try:
            cutoff = self._clamp_message_index(cutoff)

            sess = self._current_session()
            if not isinstance(sess, dict):
                return

            sess["context_cutoff"] = cutoff
            sess["updated_at"] = now_str()

            try:
                self._save_sessions_data()
            except Exception:
                pass

            try:
                self._save_legacy_current_history_copy(self._serialize_messages_for_save(self.messages))
            except Exception:
                pass
        except Exception:
            pass
