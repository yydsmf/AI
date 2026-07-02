from .core import clean_error_text, save_config
from .model_list_loader import ModelListRequestPool
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
    MODEL_REQUEST_KEY = "model_bar"

    def _model_config(self):
        return self.config.setdefault(self.MODEL_CONFIG_SECTION, {})

    def _set_model_config(self, **values):
        cfg = self._model_config()
        for key, value in values.items():
            if value is not None:
                cfg[key] = value

    def _current_model(self):
        return self.config.get(self.MODEL_CONFIG_SECTION, {}).get("model", "")

    def _model_request_id(self):
        return getattr(self, "_model_request_id", "")

    def _model_loader(self):
        loader = getattr(self, "_model_list_loader", None)
        if loader is None:
            loader = ModelListRequestPool(
                self.config,
                owner=self,
                worker_attr="model_worker",
                worker_factory=ModelListWorker,
            )
            self._model_list_loader = loader
        return loader

    def _stop_running_model_worker(self):
        self._model_loader().stop(self.MODEL_REQUEST_KEY)

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
        provider_id = self.bar.current_provider_id()
        self._pending_model_reload = False
        self._model_loader().start(
            provider_id,
            key=self.MODEL_REQUEST_KEY,
            replace=True,
            on_started=self._on_model_request_started,
            on_loaded=self.on_models_loaded,
            on_failed=self.on_models_failed,
            on_missing_provider=self._on_model_provider_missing,
        )

    def _on_model_request_started(self, provider_id, request_id):
        self._model_request_id = request_id
        self.bar.set_models_loading()
        self.bar.set_status("正在加载模型列表...")

    def _on_model_provider_missing(self, provider_id):
        self._model_request_id = ""
        self.bar.set_models([], "")
        self.bar.set_status("未选择厂商")

    def _is_current_model_request(self, provider_id, request_id):
        return self._model_loader().is_current(
            self.MODEL_REQUEST_KEY, provider_id, request_id
        ) or (
            str(provider_id or "") == str(self.bar.current_provider_id() or "")
            and str(request_id or "") == str(getattr(self, "_model_request_id", "") or "")
        )

    def on_models_loaded(self, provider_id, request_id, models):
        if not self._is_current_model_request(provider_id, request_id):
            return
        if provider_id:
            cache = self.config.setdefault("model_cache", {})
            cache[provider_id] = [str(model) for model in (models or []) if str(model).strip()]
            save_config(self.config)
        self.bar.set_models(models, self._current_model())
        self.bar.set_status(f"已加载 {len(models)} 个模型")

    def on_models_failed(self, provider_id, request_id, err):
        if not self._is_current_model_request(provider_id, request_id):
            return
        err = clean_error_text(err)
        self.bar.set_models(self.FALLBACK_MODELS, self._current_model())
        self.bar.set_status(f"加载失败：{err[:60]}")
