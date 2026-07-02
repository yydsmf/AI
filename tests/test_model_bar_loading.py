import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gpt_desktop.agent_model_bar import AgentModelBarMixin
from gpt_desktop.model_bar_mixin import SimpleModelBarMixin
from gpt_desktop.model_list_loader import ModelListRequestPool
from gpt_desktop.native_workflow import WorkflowScene
from gpt_desktop.workers import ModelListWorker


_QT_APP = QApplication.instance() or QApplication([])


class _FakeSignal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, *args):
        for callback in list(self.callbacks):
            callback(*args)


class _FakeWorker:
    def __init__(self, *args):
        self.args = args
        self.result_ready = _FakeSignal()
        self.failed = _FakeSignal()
        self.finished = _FakeSignal()
        self.started = False
        self.stopped = False
        self.running = True

    def isRunning(self):
        return self.running

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True
        self.running = False

    def deleteLater(self):
        self.deleted = True


class _FakeBar:
    def __init__(self, provider_id):
        self.provider_id = provider_id
        self.models = []
        self.current = ""
        self.status = ""

    def current_provider_id(self):
        return self.provider_id

    def current_model(self):
        return self.current

    def set_models(self, models, current):
        self.models = list(models or [])
        self.current = current

    def set_models_loading(self):
        self.models = ["正在加载模型..."]

    def set_status(self, text):
        self.status = text


class _FakeModelTab(SimpleModelBarMixin):
    MODEL_CONFIG_SECTION = "image"
    FALLBACK_MODELS = ["fallback-model"]

    def __init__(self):
        self.config = {
            "providers": [
                {"id": "p1", "base_url": "https://p1.test", "api_key": "k1"},
                {"id": "p2", "base_url": "https://p2.test", "api_key": "k2"},
            ],
            "image": {"provider_id": "p1", "model": ""},
            "model_cache": {},
        }
        self.bar = _FakeBar("p1")
        self.model_worker = None
        self._pending_model_reload = False


class _FakeAgentTab(AgentModelBarMixin):
    def __init__(self):
        self.config = {
            "providers": [
                {"id": "p1", "base_url": "https://p1.test", "api_key": "k1"},
            ],
            "agent": {"provider_id": "p1", "model": "global-agent-model"},
            "model_cache": {},
        }
        self.bar = _FakeBar("p1")
        self.model_worker = None
        self._pending_model_reload = False
        self._restoring_agent_session_model_config = False
        self._pending_agent_session_model = ""
        self.sessions = [{"id": "s1", "provider_id": "p1", "model": "session-model"}]

    def _current_session(self):
        return self.sessions[0]

    def _save_sessions_data(self):
        self.saved_sessions = True


class _FakeWorkflowNode:
    def __init__(self, node_id, provider_id="p1", node_type="text_to_image"):
        self.data = {
            "id": node_id,
            "provider_id": provider_id,
            "model": "",
            "type": node_type,
        }
        self.model_combo = object()
        self.models = []

    def set_model_options(self, models, current_model=None, keep_current=True):
        self.models = list(models or [])
        self.current_model = current_model
        self.keep_current = keep_current


class ModelListWorkerTests(unittest.TestCase):
    def test_model_list_worker_uses_ten_second_timeout(self):
        worker = ModelListWorker("https://api.test", "key", provider_id="provider", request_id="req")
        response = mock.Mock()
        response.status_code = 200
        response.json.return_value = {"data": [{"id": "model-a"}]}
        session = mock.Mock()
        session.get.return_value = response

        with mock.patch("gpt_desktop.workers.requests.Session", return_value=session):
            worker.run()

        self.assertEqual(session.get.call_args.kwargs["timeout"], 10)


class SimpleModelBarMixinTests(unittest.TestCase):
    def test_switching_provider_stops_running_model_request(self):
        tab = _FakeModelTab()
        old_worker = _FakeWorker()
        tab.model_worker = old_worker
        created = []

        def make_worker(*args):
            worker = _FakeWorker(*args)
            created.append(worker)
            return worker

        with mock.patch("gpt_desktop.model_bar_mixin.ModelListWorker", side_effect=make_worker):
            tab.bar.provider_id = "p2"
            tab.load_models()

        self.assertTrue(old_worker.stopped)
        self.assertEqual(created[-1].args[4], "p2")
        self.assertTrue(created[-1].started)

    def test_stale_model_result_does_not_override_current_provider(self):
        tab = _FakeModelTab()
        tab._model_request_id = "new-request"
        tab.bar.provider_id = "p2"
        tab.bar.set_models(["current-loading"], "")

        tab.on_models_loaded("p1", "old-request", ["old-model"])

        self.assertEqual(tab.bar.models, ["current-loading"])

    def test_current_model_result_updates_cache_and_ui(self):
        tab = _FakeModelTab()
        tab._model_request_id = "request"
        tab.bar.provider_id = "p2"

        with mock.patch("gpt_desktop.model_bar_mixin.save_config"):
            tab.on_models_loaded("p2", "request", ["model-b"])

        self.assertEqual(tab.bar.models, ["model-b"])
        self.assertEqual(tab.config["model_cache"]["p2"], ["model-b"])
        self.assertIn("已加载", tab.bar.status)


class ModelListRequestPoolTests(unittest.TestCase):
    def test_replacing_request_stops_old_worker_and_ignores_stale_result(self):
        config = {
            "providers": [
                {"id": "p1", "base_url": "https://p1.test", "api_key": "k1"},
                {"id": "p2", "base_url": "https://p2.test", "api_key": "k2"},
            ],
            "model_cache": {},
        }
        created = []
        loaded = []

        def make_worker(*args):
            worker = _FakeWorker(*args)
            created.append(worker)
            return worker

        pool = ModelListRequestPool(config, worker_factory=make_worker)
        first_request = pool.start("p1", key="bar", on_loaded=lambda *args: loaded.append(args))
        second_request = pool.start("p2", key="bar", on_loaded=lambda *args: loaded.append(args))

        self.assertTrue(created[0].stopped)
        with mock.patch("gpt_desktop.model_list_loader.save_config"):
            created[0].result_ready.emit("p1", first_request, ["old-model"])
            created[1].result_ready.emit("p2", second_request, ["new-model"])

        self.assertEqual(len(loaded), 1)
        self.assertEqual(loaded[0][2], ["new-model"])
        self.assertEqual(config["model_cache"]["p2"], ["new-model"])


class AgentModelBarMixinTests(unittest.TestCase):
    def test_loaded_models_restore_session_model_and_save_session(self):
        tab = _FakeAgentTab()
        created = []

        def make_worker(*args):
            worker = _FakeWorker(*args)
            created.append(worker)
            return worker

        with mock.patch("gpt_desktop.agent_model_bar.ModelListWorker", side_effect=make_worker):
            tab.load_models()

        request_id = created[0].args[5]
        with mock.patch("gpt_desktop.model_list_loader.save_config"), mock.patch(
            "gpt_desktop.agent_model_bar.save_config"
        ):
            created[0].result_ready.emit("p1", request_id, ["session-model", "other-model"])

        self.assertEqual(tab.bar.models, ["session-model", "other-model"])
        self.assertEqual(tab.bar.current, "session-model")
        self.assertEqual(tab.sessions[0]["model"], "session-model")
        self.assertTrue(getattr(tab, "saved_sessions", False))


class WorkflowModelLoadingTests(unittest.TestCase):
    def test_scene_shares_one_request_for_nodes_with_same_provider(self):
        config = {
            "providers": [{"id": "p1", "base_url": "https://p1.test", "api_key": "k1"}],
            "image": {"provider_id": "p1", "model": ""},
            "model_cache": {},
        }
        scene = WorkflowScene(config=config, load_defaults=False)
        created = []

        def make_worker(*args):
            worker = _FakeWorker(*args)
            created.append(worker)
            return worker

        scene.model_loader.worker_factory = make_worker
        node_a = _FakeWorkflowNode("a")
        node_b = _FakeWorkflowNode("b")
        scene.nodes = {"a": node_a, "b": node_b}

        scene.request_models_for_node(node_a)
        scene.request_models_for_node(node_b)

        self.assertEqual(len(created), 1)
        with mock.patch("gpt_desktop.model_list_loader.save_config"), mock.patch(
            "gpt_desktop.native_workflow.save_config"
        ):
            created[0].result_ready.emit("p1", created[0].args[5], ["model-a"])

        self.assertEqual(node_a.models, ["model-a"])
        self.assertEqual(node_b.models, ["model-a"])
        self.assertEqual(config["model_cache"]["p1"], ["model-a"])


if __name__ == "__main__":
    unittest.main()
