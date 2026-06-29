from PySide6.QtCore import QTimer

from .core import clean_error_text, get_provider, save_config
from .workers import ModelListWorker


class SimpleModelBarMixin:
    """
    图片/视频等单配置区模型栏公共逻辑。

    使用方需要提供：
    - MODEL_CONFIG_SECTION，例如 "image" / "video"
    - FALLBACK_MODELS
    - self.bar
    - self.config
    - self.model_worker
    - self._pending_model_reload
    """

    MODEL_CONFIG_SECTION = ""

    def _model_config(self):
        return self.config.setdefault(self.MODEL_CONFIG_SECTION, {})

    def _set_model_config(self, **values):
        cfg = self._model_config()
        for key, value in values.items():
            if value is not None:
                cfg[key] = value

    def _current_model(self):
        return self.config.get(self.MODEL_CONFIG_SECTION, {}).get("model", "")

    def refresh_providers(self):
        current = self.config.get(self.MODEL_CONFIG_SECTION, {}).get("provider_id", "")
        self.bar.set_providers(self.config.get("providers", []), current)

    def on_provider_changed(self, pid):
        self._set_model_config(provider_id=pid)
        save_config(self.config)
        self.load_models()

    def on_model_changed(self, model):
        if model:
            self._set_model_config(model=model)
            save_config(self.config)

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

    def on_models_loaded(self, models):
        provider_id = self.bar.current_provider_id()
        if provider_id:
            cache = self.config.setdefault("model_cache", {})
            cache[provider_id] = [str(model) for model in (models or []) if str(model).strip()]
            save_config(self.config)
        self.bar.set_models(models, self._current_model())
        self.bar.set_status(f"已加载 {len(models)} 个模型")

    def on_models_failed(self, err):
        err = clean_error_text(err)
        self.bar.set_models(self.FALLBACK_MODELS, self._current_model())
        self.bar.set_status(f"加载失败：{err[:60]}")

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
