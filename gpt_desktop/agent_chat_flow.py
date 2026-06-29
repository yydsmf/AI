from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QMessageBox

from .chat_worker import ChatWorker
from .agent_context_compressor import compress_messages_for_api
from .core import clean_error_text, get_provider
from .error_ui import show_generation_error


class AgentChatFlowMixin:
    """智能体发送、流式接收、中止和 worker 生命周期管理。"""

    def _messages_for_api(self, messages):
        """
        清理发给 API 的历史消息。

        self.messages 里可能有 _resubmit_text / _uploaded_file_paths 等本地元数据。
        这些字段不能发给 API，否则部分接口会报错。
        """
        clean = []
        source_messages = messages or []

        try:
            if source_messages is self.messages:
                source_messages = source_messages[self.get_context_cutoff():]
        except Exception:
            pass

        for msg in source_messages:
            if not isinstance(msg, dict):
                continue
            if msg.get("_local_status"):
                continue
            role = msg.get("role")
            content = msg.get("content", "")
            if role == "assistant" and str(content).strip() in (
                "[任务已中止]",
                "【上下文已清除】",
            ):
                continue
            if role in ("user", "assistant", "system"):
                clean.append({"role": role, "content": content})
        return clean

    def _context_compression_config(self):
        cfg = self.config.setdefault("agent", {})
        compression = cfg.get("context_compression", {})
        if not isinstance(compression, dict):
            compression = {}
        merged = {
            "enabled": compression.get("enabled", True),
            "trigger_tokens": compression.get("trigger_tokens", 24000),
            "recent_budget_tokens": compression.get("recent_budget_tokens", 16000),
            "summary_budget_chars": compression.get("summary_budget_chars", 8000),
            "min_new_messages": compression.get("min_new_messages", 10),
        }
        cfg["context_compression"] = merged
        return merged

    def _prepare_history_messages_for_api(self):
        history_messages = self._messages_for_api(self.messages)
        try:
            sess = self._current_session()
            existing_summary = sess.get("context_summary", "") if isinstance(sess, dict) else ""
            packed, summary, changed, total_tokens = compress_messages_for_api(
                history_messages,
                existing_summary=existing_summary,
                config=self._context_compression_config(),
            )
            if changed and isinstance(sess, dict):
                last_count = int(sess.get("context_summary_source_count", 0) or 0)
                min_new = int(self._context_compression_config().get("min_new_messages", 10) or 10)
                should_update_notice = len(history_messages) - last_count >= min_new or not sess.get("context_summary")
                if should_update_notice:
                    sess["context_summary"] = summary
                    sess["context_summary_source_count"] = len(history_messages)
                    self.messages.append({
                        "role": "assistant",
                        "content": f"较早聊天已压缩为摘要，估算上下文长度约 {total_tokens}。",
                        "_local_status": "context_compressed",
                    })
                    self._save_sessions_data()
                    self.bar.set_status(f"已自动压缩上下文，估算长度 {total_tokens}")
            return packed
        except Exception:
            return history_messages

    def send(self):
        if self.worker and self.worker.isRunning():
            return

        self.save_current_session_model_config(persist=False)

        text = self.input.toPlainText().strip()
        if not text and not self.uploaded_images and not self.uploaded_files:
            QMessageBox.warning(self, "提示", "请输入内容，或上传图片/文件。")
            return

        provider = get_provider(self.config, self.bar.current_provider_id())
        if not provider:
            QMessageBox.warning(self, "提示", "请先在设置中添加并选择厂商。")
            return

        model = self.bar.current_model()
        if not model:
            QMessageBox.warning(self, "提示", "请选择模型，或点击刷新加载列表。")
            return

        self._set_agent_config_model(model=model)

        # 关键修复：
        # 1. api_user_msg：只用于本次 API 请求，包含完整文件内容和图片 base64。
        # 2. display_user_msg：用于聊天界面和历史保存，只包含附件摘要，不包含完整文件内容。
        # 3. send_messages 必须先用旧历史 + api_user_msg 构造。
        # 4. self.messages 里只能 append display_user_msg，不能 append api_user_msg。
        history_messages = self._prepare_history_messages_for_api()

        display_user_msg = self.build_user_message(
            text,
            include_uploaded_file_content=False,
            include_uploaded_images=False
        )

        pending_user_message = {
            "text": self._strip_uploaded_file_note(text),
            "uploaded_files": list(self.uploaded_files),
            "uploaded_images": list(self.uploaded_images),
        }

        send_messages = [
            {
                "role": "system",
                "content": (
                    f"当前应用选择的模型名称是：{model}。"
                    f"如果用户询问你是什么模型，可以说明当前请求使用的模型 ID 是 {model}。"
                )
            },
        ] + history_messages

        # 只保存/显示摘要版，避免文件全文进入会话历史。
        self.messages.append(display_user_msg)

        self.input.clear()
        self.adjust_input_height()
        self.clear_all_attachments(show_status=False)

        self._stopping_task = False
        self._follow_streaming_output = True
        self._user_reading_chat_history = False
        self.streaming_text = ""
        self._append_outgoing_chat_widgets(display_user_msg)
        self._set_receiving_controls()
        self.bar.set_status("正在生成回复...")

        self.worker = ChatWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            send_messages,
            pending_user_message=pending_user_message,
        )
        self.worker.chunk.connect(self.on_chunk)
        self.worker.result_ready.connect(self.on_reply)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(lambda *_args, w=self.worker: self._cleanup_finished_worker(w))
        self.worker.start()
        self.schedule_agent_input_draft_save(120)
        self.schedule_persistent_chat_save(250)

    def _request_worker_stop(self, worker):
        try:
            if worker is None:
                return
            if hasattr(worker, "stop"):
                worker.stop()
            else:
                worker.requestInterruption()
        except Exception:
            pass

    def stop_current_task(self):
        """
        立即中止当前智能体任务。

        行为：
        1. 点击“中止”后，UI 立即恢复；
        2. 断开旧 worker 的信号，避免旧请求之后返回又污染当前界面；
        3. 后台旧线程放入 _zombie_workers 保持引用，防止 QThread destroyed while running；
        4. 请求 worker 停止，等待网络句柄关闭后自然退出。
        """
        if not self.worker:
            return

        old_worker = self.worker
        self.worker = None
        self._stopping_task = False

        # 断开旧 worker 信号，避免旧请求后续返回影响 UI
        try:
            old_worker.chunk.disconnect(self.on_chunk)
        except Exception:
            pass
        try:
            old_worker.result_ready.disconnect(self.on_reply)
        except Exception:
            pass
        try:
            old_worker.failed.disconnect(self.on_failed)
        except Exception:
            pass

        self._request_worker_stop(old_worker)

        # 保留引用，避免线程还没结束时对象被销毁
        try:
            self._zombie_workers.append(old_worker)
            old_worker.finished.connect(lambda *_args, w=old_worker: self._cleanup_zombie_worker(w))
            old_worker.failed.connect(lambda *_args, w=old_worker: self._cleanup_zombie_worker(w))
        except Exception:
            pass

        QTimer.singleShot(800, lambda w=old_worker: self._check_stopped_worker_later(w))

        # UI 立即恢复
        partial = ""
        if self.streaming_text is not None:
            partial = self.streaming_text.strip()

        stopped_content = (partial + "\n\n[任务已中止]") if partial else "[任务已中止]"

        self.messages.append({
            "role": "assistant",
            "content": stopped_content,
            "_local_status": "stopped",
        })
        self.schedule_persistent_chat_save(120)

        self._reset_send_controls()

        self._replace_streaming_chat_widget(stopped_content, should_follow_output=True)
        self.bar.set_status("任务已中止，可以重新发送")

    def _check_stopped_worker_later(self, worker):
        """
        停止后只做软检查，不再 terminate QThread。
        requests 句柄关闭后线程通常会自行退出；UI 已经提前恢复。
        """
        try:
            if worker and worker.isRunning():
                self._request_worker_stop(worker)
                QTimer.singleShot(3000, lambda w=worker: self._check_stopped_worker_later(w))
        except Exception:
            pass

    def _cleanup_zombie_worker(self, worker):
        """
        清理已经结束的旧 worker 引用。
        """
        try:
            if worker in self._zombie_workers:
                self._zombie_workers.remove(worker)
        except Exception:
            pass

        try:
            if worker is not None:
                worker.deleteLater()
        except Exception:
            pass

    def _cleanup_finished_worker(self, worker):
        """
        当前智能体 worker 真正退出线程后再释放 QThread 对象。
        """
        try:
            if self.worker is worker:
                self.worker = None
            if worker is not None:
                worker.deleteLater()
        except Exception:
            pass

    def _is_current_worker_signal(self):
        """
        防止旧请求排队回调污染当前会话。
        如果信号来源不是当前 worker，就只清理旧引用，不更新 UI 和消息。
        """
        try:
            sender = self.sender()
        except Exception:
            sender = None

        if sender is None:
            return True

        if sender is self.worker:
            return True

        self._cleanup_zombie_worker(sender)
        return False

    def on_chunk(self, piece):
        """
        收到流式片段。

        这里只追加文本，然后启动定时器更新最后一个智能体气泡。
        """
        if not self._is_current_worker_signal():
            return

        if self.streaming_text is None:
            self.streaming_text = ""
        self.streaming_text += piece

        self._schedule_streaming_render()

    def on_reply(self, result):
        if not self._is_current_worker_signal():
            return

        self._reset_send_controls()

        content = result.get("content", "")
        returned_model = result.get("returned_model", "")
        stopped = bool(result.get("stopped")) or self._stopping_task
        should_follow_output = bool(self._follow_streaming_output)

        if content:
            msg = {"role": "assistant", "content": content}
            if stopped:
                content = content.rstrip() + "\n\n[任务已中止]"
                msg["content"] = content
                msg["_local_status"] = "stopped"
            self.messages.append(msg)

        self._stopping_task = False
        self.schedule_persistent_chat_save(250)
        if content:
            self.streaming_text = None
            self._last_streaming_html = ""
            self._streaming_doc_start = None
            self._finalize_streaming_chat_widget(content, should_follow_output=should_follow_output)
        else:
            self._reset_streaming_state()
            self.render_chat()
            if should_follow_output:
                self.scroll_chat_to_bottom_later(force=True)

        if stopped:
            self.bar.set_status("任务已中止")
        else:
            self.bar.set_status(f"完成 · 模型：{returned_model}" if returned_model else "完成")

    def on_failed(self, err):
        if not self._is_current_worker_signal():
            return

        err = clean_error_text(err)
        lower_err = err.lower()
        silent_stop_error = any(x in lower_err for x in (
            "request aborted",
            "operation canceled",
            "operation cancelled",
            "cancelled",
            "canceled",
            "closed",
            "connection aborted",
            "bad file descriptor",
        ))

        self._reset_send_controls()
        self._stopping_task = False
        partial = ""
        if self.streaming_text is not None:
            partial = self.streaming_text.strip()
        if partial:
            suffix = "[任务已中止]" if silent_stop_error else "[请求失败，以上为已接收的部分内容]"
            failed_content = partial + "\n\n" + suffix
            self.messages.append({
                "role": "assistant",
                "content": failed_content,
                "_local_status": "stopped" if silent_stop_error else "failed",
            })
            self.schedule_persistent_chat_save(250)
            self._replace_streaming_chat_widget(
                failed_content,
                should_follow_output=bool(self._follow_streaming_output),
            )
        else:
            self._reset_streaming_state()

        if silent_stop_error:
            self.bar.set_status("任务已中止")
            return

        if not partial:
            failed_content = f"[请求失败]\n\n{err}"
            self.messages.append({
                "role": "assistant",
                "content": failed_content,
                "_local_status": "failed",
            })
            self.schedule_persistent_chat_save(250)
            self.render_chat(force=True)
            self.scroll_chat_to_bottom_later(force=True)
        show_generation_error(self, "请求失败", err, status="请求失败")
