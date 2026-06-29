from PySide6.QtCore import QTimer

from .core import clean_error_text, get_provider, now_str, save_config
from .workers import ModelListWorker


class AgentModelBarMixin:
    """智能体厂商、模型列表加载和当前会话模型恢复。"""

    FALLBACK_MODELS = [
        "gpt-5.5", "gpt-5.5-mini", "gpt-4o", "gpt-4o-mini",
        "gpt-4.1", "gpt-4.1-mini", "gpt-4-turbo", "gpt-3.5-turbo",
    ]

    def refresh_providers(self):
        current = self.config.get("agent", {}).get("provider_id", "")
        self.bar.set_providers(self.config.get("providers", []), current)

    def on_provider_changed(self, pid):
        try:
            self._set_agent_config_model(provider_id=pid)

            sess = self._current_session()
            if isinstance(sess, dict):
                sess["provider_id"] = pid or ""

                if not self._restoring_agent_session_model_config:
                    sess["model"] = ""

                sess["updated_at"] = now_str()

            save_config(self.config)
            self._save_sessions_data()
        except Exception:
            pass

        try:
            self.load_models()
        except Exception:
            pass

    def on_model_changed(self, model):
        try:
            if not model:
                return

            sess = self._current_session()
            if isinstance(sess, dict):
                sess["provider_id"] = self.bar.current_provider_id() or sess.get("provider_id", "")
                sess["model"] = model
                sess["updated_at"] = now_str()

            self._set_agent_config_model(model=model)
            save_config(self.config)
            self._save_sessions_data()
        except Exception:
            pass

    def load_models(self):
        if self.model_worker is not None and self.model_worker.isRunning():
            self._pending_model_reload = True
            return

        provider = get_provider(self.config, self.bar.current_provider_id())
        if not provider:
            self.bar.set_models([], "")
            self.bar.set_status("未选择厂商")
            return
        self.bar.set_models_loading()
        self.bar.set_status("正在加载模型列表...")
        self.model_worker = ModelListWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            provider.get("proxy_url", ""),
            provider.get("proxy_mode", "提交和下载" if provider.get("proxy_url") else "不使用代理"),
        )
        self.model_worker.result_ready.connect(self.on_models_loaded)
        self.model_worker.failed.connect(self.on_models_failed)
        self.model_worker.finished.connect(self._cleanup_model_worker)
        self.model_worker.start()

    def _desired_model_for_bar(self):
        try:
            _provider_id, session_model = self.desired_session_model_config()
            return (
                self._pending_agent_session_model
                or session_model
                or self.config.get("agent", {}).get("model", "")
            )
        except Exception:
            return self.config.get("agent", {}).get("model", "")

    def _finish_model_restore(self):
        self._pending_agent_session_model = ""
        self._restoring_agent_session_model_config = False

    def on_models_loaded(self, models):
        try:
            self.bar.set_models(models, self._desired_model_for_bar())
            self.bar.set_status(f"已加载 {len(models)} 个模型")
            self.save_current_session_model_config(persist=True)
        except Exception:
            try:
                self.bar.set_models(models, self.config.get("agent", {}).get("model", ""))
                self.bar.set_status(f"已加载 {len(models)} 个模型")
            except Exception:
                pass
        finally:
            self._finish_model_restore()

    def on_models_failed(self, err):
        err = clean_error_text(err)
        try:
            self.bar.set_models(self.FALLBACK_MODELS, self._desired_model_for_bar())
            self.bar.set_status(f"加载失败：{err[:60]}")
            self.save_current_session_model_config(persist=True)
        except Exception:
            try:
                self.bar.set_models(self.FALLBACK_MODELS, self.config.get("agent", {}).get("model", ""))
                self.bar.set_status(f"加载失败：{err[:60]}")
            except Exception:
                pass
        finally:
            self._finish_model_restore()

    def _cleanup_model_worker(self):
        worker = self.sender()

        def cleanup():
            try:
                if self.model_worker is worker:
                    self.model_worker = None
                if worker is not None:
                    worker.deleteLater()
            except Exception:
                pass
            if self._pending_model_reload:
                self._pending_model_reload = False
                QTimer.singleShot(0, self.load_models)

        QTimer.singleShot(0, cleanup)

    def current_bar_provider_model(self):
        """
        获取当前界面上智能体栏的厂商和模型。
        """
        provider_id = ""
        model = ""

        try:
            provider_id = self.bar.current_provider_id() or ""
            model = self.bar.current_model() or ""
        except Exception:
            pass

        try:
            agent_cfg = self.config.setdefault("agent", {})
            if not provider_id:
                provider_id = agent_cfg.get("provider_id", "") or ""
            if not model:
                model = agent_cfg.get("model", "") or ""
        except Exception:
            pass

        return provider_id, model

    def ensure_session_model_fields(self):
        """
        兼容历史会话：如果没有 provider_id / model，则用当前全局智能体配置补上。
        """
        try:
            agent_cfg = self.config.setdefault("agent", {})
            fallback_provider = agent_cfg.get("provider_id", "") or ""
            fallback_model = agent_cfg.get("model", "") or ""

            for sess in list(self.sessions):
                if not isinstance(sess, dict):
                    continue
                sess.setdefault("provider_id", fallback_provider)
                sess.setdefault("model", fallback_model)
        except Exception:
            pass

    def save_current_session_model_config(self, persist=True):
        """
        把当前界面选择的厂商/模型保存到当前会话。
        """
        try:
            sess = self._current_session()
            if sess is None:
                return

            provider_id, model = self.current_bar_provider_model()

            if provider_id:
                sess["provider_id"] = provider_id

            if model:
                sess["model"] = model

            self._set_agent_config_model(provider_id, model)

            sess["updated_at"] = now_str()

            if persist:
                try:
                    self._save_sessions_data()
                except Exception:
                    pass

                try:
                    save_config(self.config)
                except Exception:
                    pass
        except Exception:
            pass

    def _set_agent_config_model(self, provider_id="", model=""):
        agent_cfg = self.config.setdefault("agent", {})
        if provider_id:
            agent_cfg["provider_id"] = provider_id
        if model:
            agent_cfg["model"] = model

    def desired_session_model_config(self):
        """
        返回当前会话期望恢复的 provider_id / model。
        """
        provider_id = ""
        model = ""

        try:
            sess = self._current_session()
            if isinstance(sess, dict):
                provider_id = sess.get("provider_id", "") or ""
                model = sess.get("model", "") or ""
        except Exception:
            pass

        try:
            agent_cfg = self.config.setdefault("agent", {})
            if not provider_id:
                provider_id = agent_cfg.get("provider_id", "") or ""
            if not model:
                model = agent_cfg.get("model", "") or ""
        except Exception:
            pass

        return provider_id, model

    def restore_session_model_config(self):
        """
        根据当前会话恢复厂商和模型。
        """
        try:
            provider_id, model = self.desired_session_model_config()

            self._restoring_agent_session_model_config = True
            self._pending_agent_session_model = model or ""

            self._set_agent_config_model(provider_id, model)

            try:
                save_config(self.config)
            except Exception:
                pass

            try:
                self.refresh_providers()
            except Exception:
                pass

            self._finish_model_restore()
            self.load_models()
        except Exception:
            try:
                self._finish_model_restore()
            except Exception:
                pass
