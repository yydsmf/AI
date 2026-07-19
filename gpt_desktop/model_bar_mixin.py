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

    def _models_by_provider(self):
        cfg = self._model_config()
        raw = cfg.get("model_by_provider", {})
        if not isinstance(raw, dict):
            raw = {}
        normalized = {
            str(provider_id): str(model).strip()
            for provider_id, model in raw.items()
            if str(provider_id).strip() and str(model).strip()
        }
        current_provider = str(cfg.get("provider_id", "") or "").strip()
        current_model = str(cfg.get("model", "") or "").strip()
        if current_provider and current_model and current_provider not in normalized:
            normalized[current_provider] = current_model
        cfg["model_by_provider"] = normalized
        return normalized

    def _saved_model_for_provider(self, provider_id):
        provider_id = str(provider_id or "").strip()
        if not provider_id:
            return ""
        cfg = self._model_config()
        model = str(self._models_by_provider().get(provider_id, "") or "").strip()
        if not model and str(cfg.get("provider_id", "") or "") == provider_id:
            model = str(cfg.get("model", "") or "").strip()
        cached = [
            str(item).strip()
            for item in self.config.get("model_cache", {}).get(provider_id, [])
            if str(item).strip()
        ]
        if cached and model not in cached:
            return ""
        return model

    def _remember_active_model(self, provider_id, model):
        provider_id = str(provider_id or "").strip()
        model = str(model or "").strip()
        cfg = self._model_config()
        if provider_id:
            cfg["provider_id"] = provider_id
        cfg["model"] = model
        if provider_id and model:
            self._models_by_provider()[provider_id] = model

    def _current_model(self):
        provider_id = ""
        if hasattr(self, "bar") and hasattr(self.bar, "current_provider_id"):
            provider_id = self.bar.current_provider_id()
        if not provider_id:
            provider_id = self._model_config().get("provider_id", "")
        return self._saved_model_for_provider(provider_id)

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
        cfg = self._model_config()
        previous_provider = str(cfg.get("provider_id", "") or "").strip()
        previous_model = self.bar.current_model() or str(cfg.get("model", "") or "").strip()
        if previous_provider and previous_model:
            self._models_by_provider()[previous_provider] = previous_model
        target_model = str(self._models_by_provider().get(str(pid or ""), "") or "").strip()
        cached = [
            str(item).strip()
            for item in self.config.get("model_cache", {}).get(str(pid or ""), [])
            if str(item).strip()
        ]
        if cached and target_model not in cached:
            target_model = ""
        self._set_model_config(provider_id=pid, model=target_model)
        save_config(self.config)
        self.load_models()

    def on_model_changed(self, model):
        if model:
            provider_id = self.bar.current_provider_id()
            self._remember_active_model(provider_id, model)
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
        models = [str(model).strip() for model in (models or []) if str(model).strip()]
        if provider_id:
            cache = self.config.setdefault("model_cache", {})
            cache[provider_id] = list(models)
        selected = self._saved_model_for_provider(provider_id)
        if selected not in models:
            selected = models[0] if models else ""
        self.bar.set_models(models, selected)
        self._remember_active_model(provider_id, selected)
        save_config(self.config)
        self.bar.set_status(f"已加载 {len(models)} 个模型")

    def on_models_failed(self, provider_id, request_id, err):
        if not self._is_current_model_request(provider_id, request_id):
            return
        err = clean_error_text(err)
        cached = [
            str(model).strip()
            for model in self.config.get("model_cache", {}).get(provider_id, [])
            if str(model).strip()
        ]
        options = cached or [str(model).strip() for model in self.FALLBACK_MODELS if str(model).strip()]
        selected = self._saved_model_for_provider(provider_id)
        if selected and selected not in options and not cached:
            options.insert(0, selected)
        if selected not in options:
            selected = options[0] if options else ""
        self.bar.set_models(options, selected)
        self._remember_active_model(provider_id, selected)
        save_config(self.config)
        prefix = "加载失败，已使用该厂商缓存" if cached else "加载失败"
        self.bar.set_status(f"{prefix}：{err[:60]}")
