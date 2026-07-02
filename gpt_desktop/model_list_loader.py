import uuid

from .core import clean_error_text, get_provider, save_config
from .workers import ModelListWorker


def normalize_model_names(models):
    result = []
    for model in models or []:
        model = str(model or "").strip()
        if model and model not in result:
            result.append(model)
    return result


def save_model_cache(config, provider_id, models):
    provider_id = str(provider_id or "").strip()
    if not provider_id:
        return []
    normalized = normalize_model_names(models)
    config.setdefault("model_cache", {})[provider_id] = list(normalized)
    save_config(config)
    return normalized


class ModelListRequestPool:
    """
    Shared model-list request manager.

    It owns the transport concerns only: start, stop, stale-result guard, worker
    cleanup and cache write. Callers still decide how selected models are saved.
    """

    def __init__(
        self,
        config,
        owner=None,
        worker_attr="",
        worker_map_attr="",
        worker_factory=None,
    ):
        self.config = config if config is not None else {}
        self.owner = owner
        self.worker_attr = worker_attr
        self.worker_map_attr = worker_map_attr
        self.worker_factory = worker_factory or ModelListWorker
        self.requests = {}

    def start(
        self,
        provider_id,
        *,
        key=None,
        replace=True,
        on_started=None,
        on_loaded=None,
        on_failed=None,
        on_missing_provider=None,
        on_finished=None,
    ):
        provider_id = str(provider_id or "").strip()
        key = str(key if key is not None else provider_id)
        if replace:
            self.stop(key)
        elif key in self.requests:
            return None

        provider = get_provider(self.config, provider_id)
        if not provider:
            if on_missing_provider:
                on_missing_provider(provider_id)
            return None

        request_id = uuid.uuid4().hex
        worker = self.worker_factory(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            provider.get("proxy_url", ""),
            provider.get("proxy_mode", "提交和下载" if provider.get("proxy_url") else "不使用代理"),
            provider_id,
            request_id,
        )
        self.requests[key] = {
            "provider_id": provider_id,
            "request_id": request_id,
            "worker": worker,
            "on_loaded": on_loaded,
            "on_failed": on_failed,
            "on_finished": on_finished,
        }
        self._set_owner_worker(key, worker)

        worker.result_ready.connect(
            lambda pid, rid, models, request_key=key: self._handle_loaded(request_key, pid, rid, models)
        )
        worker.failed.connect(
            lambda pid, rid, err, request_key=key: self._handle_failed(request_key, pid, rid, err)
        )
        worker.finished.connect(
            lambda request_key=key, request_worker=worker: self._cleanup(request_key, request_worker)
        )

        if on_started:
            on_started(provider_id, request_id)
        worker.start()
        return request_id

    def stop(self, key=None):
        if key is None:
            keys = list(self.requests)
        else:
            keys = [str(key)]

        stopped = False
        for request_key in keys:
            record = self.requests.pop(request_key, None)
            if not record:
                continue
            self._stop_worker(record.get("worker"))
            self._clear_owner_worker(request_key, record.get("worker"))
            stopped = True

        if not stopped and key is not None:
            worker = self._owner_worker()
            if worker is not None:
                self._stop_worker(worker)
                self._clear_owner_worker(str(key), worker)

    def is_current(self, key, provider_id, request_id):
        record = self.requests.get(str(key))
        return bool(
            record
            and str(provider_id or "") == str(record.get("provider_id") or "")
            and str(request_id or "") == str(record.get("request_id") or "")
        )

    def _handle_loaded(self, key, provider_id, request_id, models):
        if not self.is_current(key, provider_id, request_id):
            return
        normalized = save_model_cache(self.config, provider_id, models)
        callback = self.requests.get(str(key), {}).get("on_loaded")
        if callback:
            callback(provider_id, request_id, normalized)

    def _handle_failed(self, key, provider_id, request_id, err):
        if not self.is_current(key, provider_id, request_id):
            return
        callback = self.requests.get(str(key), {}).get("on_failed")
        if callback:
            callback(provider_id, request_id, clean_error_text(err))

    def _cleanup(self, key, worker):
        record = self.requests.get(str(key))
        if record and record.get("worker") is worker:
            self.requests.pop(str(key), None)
            callback = record.get("on_finished")
            self._clear_owner_worker(str(key), worker)
            if callback:
                callback()
        else:
            self._clear_owner_worker(str(key), worker)

        try:
            if worker is not None and hasattr(worker, "deleteLater"):
                worker.deleteLater()
        except Exception:
            pass

    def _stop_worker(self, worker):
        if worker is None:
            return
        try:
            if hasattr(worker, "stop"):
                worker.stop()
            else:
                worker.requestInterruption()
        except Exception:
            pass

    def _owner_worker(self):
        if self.owner is None or not self.worker_attr:
            return None
        return getattr(self.owner, self.worker_attr, None)

    def _set_owner_worker(self, key, worker):
        if self.owner is None:
            return
        if self.worker_attr:
            setattr(self.owner, self.worker_attr, worker)
        if self.worker_map_attr:
            worker_map = getattr(self.owner, self.worker_map_attr, None)
            if isinstance(worker_map, dict):
                worker_map[str(key)] = worker

    def _clear_owner_worker(self, key, worker):
        if self.owner is None:
            return
        if self.worker_attr and getattr(self.owner, self.worker_attr, None) is worker:
            setattr(self.owner, self.worker_attr, None)
        if self.worker_map_attr:
            worker_map = getattr(self.owner, self.worker_map_attr, None)
            if isinstance(worker_map, dict) and worker_map.get(str(key)) is worker:
                worker_map.pop(str(key), None)
