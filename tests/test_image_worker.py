import os
import json
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gpt_desktop.workers import ImageWorker


_QT_APP = QApplication.instance() or QApplication([])


class _FakeResponse:
    def __init__(self, data, status_code=200, content=None, headers=None):
        self._data = data
        self.status_code = status_code
        if content is None:
            content = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.content = content
        self.headers = headers or {"Content-Type": "image/png"}
        self.closed = False

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def close(self):
        self.closed = True


class ToapisOfficialImageWorkerTests(unittest.TestCase):
    def make_worker(self, refs=None, size="2048*2048", model="gpt-image-2"):
        worker = ImageWorker(
            "https://toapis.com",
            "key",
            model,
            size,
            "高",
            "1",
            "一只蓝色人偶站在导演台上",
            refs or [],
        )
        worker.TOAPIS_TASK_INITIAL_WAIT_SECONDS = 0
        worker.TOAPIS_TASK_POLL_SECONDS = 0
        worker.TOAPIS_TASK_MAX_SECONDS = 1
        return worker

    def test_official_task_timeout_allows_slow_generation_jobs(self):
        self.assertGreaterEqual(ImageWorker.TOAPIS_TASK_MAX_SECONDS, 600)

    def test_official_text_to_image_uses_generation_task_payload(self):
        worker = self.make_worker(size="3840*2160（横屏4K）")
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _FakeResponse({"id": "task_1", "status": "queued"})

        worker._request = fake_request
        response = worker._post_image_request({"Authorization": "Bearer key"})

        self.assertEqual(response.json()["id"], "task_1")
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "https://toapis.com/v1/images/generations")
        payload = calls[0][2]["json"]
        self.assertEqual(payload["model"], "gpt-image-2")
        self.assertEqual(payload["size"], "16:9")
        self.assertEqual(payload["resolution"], "4k")
        self.assertEqual(payload["response_format"], "url")
        self.assertEqual(payload["quality"], "high")
        self.assertNotIn("image_urls", payload)

    def test_official_multi_reference_uses_uploads_then_generation_image_urls(self):
        with tempfile.NamedTemporaryFile(suffix=".png") as fp:
            fp.write(b"fake")
            fp.flush()
            worker = self.make_worker(refs=[fp.name, "https://example.com/ref.png"])
            calls = []

            def fake_request(method, url, **kwargs):
                calls.append((method, url, kwargs))
                if url.endswith("/v1/uploads/images"):
                    return _FakeResponse({"data": {"url": "https://cdn.example.com/uploaded.png"}})
                return _FakeResponse({"id": "task_2", "status": "queued"})

            worker._request = fake_request
            response = worker._post_image_request({"Authorization": "Bearer key"})

        self.assertEqual(response.json()["id"], "task_2")
        self.assertEqual(calls[0][1], "https://toapis.com/v1/uploads/images")
        self.assertEqual(calls[1][1], "https://toapis.com/v1/images/generations")
        payload = calls[1][2]["json"]
        self.assertEqual(
            payload["image_urls"],
            ["https://cdn.example.com/uploaded.png", "https://example.com/ref.png"],
        )

    def test_official_task_poll_extracts_completed_result_items(self):
        worker = self.make_worker()
        calls = []
        responses = [
            _FakeResponse({"id": "task_3", "status": "running", "progress": 50}),
            _FakeResponse({"id": "task_3", "status": "completed", "result": {"data": [{"url": "https://example.com/out.png"}]}}),
        ]

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return responses.pop(0)

        worker._request = fake_request
        items = worker._poll_toapis_official_task("task_3", {"Authorization": "Bearer key"})

        self.assertEqual(items, [{"url": "https://example.com/out.png"}])
        self.assertEqual(len(calls), 2)
        self.assertTrue(all(call[1] == "https://toapis.com/v1/images/generations/task_3" for call in calls))

    def test_official_task_poll_does_not_repeat_same_progress_log(self):
        worker = self.make_worker()
        messages = []
        worker.progress.connect(messages.append)
        responses = [
            _FakeResponse({"id": "task_3b", "status": "in_progress", "progress": 10}),
            _FakeResponse({"id": "task_3b", "status": "in_progress", "progress": 10}),
            _FakeResponse({"id": "task_3b", "status": "in_progress", "progress": 10}),
            _FakeResponse({"id": "task_3b", "status": "completed", "result": {"data": [{"url": "https://example.com/out.png"}]}}),
        ]

        def fake_request(method, url, **kwargs):
            return responses.pop(0)

        worker._request = fake_request
        items = worker._poll_toapis_official_task("task_3b", {"Authorization": "Bearer key"})

        status_messages = [message for message in messages if message.startswith("任务状态")]
        self.assertEqual(items, [{"url": "https://example.com/out.png"}])
        self.assertEqual(status_messages.count("任务状态：in_progress 10%"), 1)
        self.assertIn("任务状态：completed", status_messages)

    def test_official_run_saves_polled_image_url(self):
        worker = self.make_worker()
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "POST":
                return _FakeResponse({"id": "task_4", "status": "queued"})
            if url.endswith("/task_4"):
                return _FakeResponse({"id": "task_4", "status": "completed", "result": {"data": [{"url": "https://example.com/out.png"}]}})
            return _FakeResponse({}, content=b"png-data")

        results = []
        failures = []
        worker._request = fake_request
        worker.result_ready.connect(results.append)
        worker.failed.connect(failures.append)

        with mock.patch("gpt_desktop.workers.save_bytes_to_image", return_value="/tmp/generated.png"):
            worker.run()

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["images"], ["/tmp/generated.png"])
        self.assertIn(("GET", "https://example.com/out.png"), [(method, url) for method, url, _ in calls])

    def test_other_provider_edit_keeps_url_response_format(self):
        worker = ImageWorker(
            "https://api.example.com",
            "key",
            "gpt-image-2",
            "1024*1024",
            "自动",
            "1",
            "prompt",
            ["/tmp/ref.png"],
        )

        with mock.patch.object(worker, "_post_with_response_format_fallback") as fallback:
            fallback.return_value = _FakeResponse({"data": []})
            worker._post_image_request({"Authorization": "Bearer key"})

        post_func, data = fallback.call_args.args
        self.assertEqual(data["size"], "1024x1024")
        self.assertEqual(data["response_format"], "url")

    def test_other_provider_generation_keeps_url_response_format(self):
        worker = ImageWorker(
            "https://api.example.com",
            "key",
            "gpt-image-2.5-sunburst",
            "1024*1024",
            "低",
            "1",
            "prompt",
            [],
        )

        with mock.patch.object(worker, "_post_with_response_format_fallback") as fallback:
            fallback.return_value = _FakeResponse({"data": []})
            worker._post_image_request({"Authorization": "Bearer key"})

        _post_func, payload = fallback.call_args.args
        self.assertEqual(payload["response_format"], "url")

    def test_dxmcs_generation_requests_embedded_image_data(self):
        worker = ImageWorker(
            "https://api.dxmcs.xin/",
            "key",
            "gpt-image-2.5-sunburst",
            "1024*1024",
            "低",
            "1",
            "prompt",
            [],
        )

        with mock.patch.object(worker, "_post_with_response_format_fallback") as fallback:
            fallback.return_value = _FakeResponse({"data": []})
            worker._post_image_request({"Authorization": "Bearer key"})

        _post_func, payload = fallback.call_args.args
        self.assertEqual(payload["response_format"], "b64_json")

    def test_embedded_image_format_falls_back_to_url_when_unsupported(self):
        worker = ImageWorker(
            "https://api.example.com",
            "key",
            "image-model",
            "1024*1024",
            "自动",
            "1",
            "prompt",
            [],
        )
        calls = []
        messages = []
        worker.progress.connect(messages.append)

        def post_func(payload):
            calls.append(dict(payload))
            if payload.get("response_format") == "b64_json":
                return _FakeResponse(
                    {"error": {"message": "response_format b64_json is not supported"}},
                    status_code=400,
                )
            return _FakeResponse({"data": [{"url": "https://example.com/out.png"}]})

        response = worker._post_with_response_format_fallback(
            post_func,
            {"model": "image-model", "response_format": "b64_json"},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual([call["response_format"] for call in calls], ["b64_json", "url"])
        self.assertIn("接口不支持内嵌图片数据，已自动改用 URL 返回重试...", messages)

    def test_run_prefers_embedded_image_and_does_not_download_returned_url(self):
        worker = ImageWorker(
            "https://api.dxmcs.xin",
            "key",
            "gpt-image-2.5-sunburst",
            "1024*1024",
            "低",
            "1",
            "prompt",
            [],
        )
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            if method == "GET":
                raise AssertionError("返回 b64_json 时不应请求图片 URL")
            return _FakeResponse({
                "data": [{
                    "b64_json": "aW1hZ2UtYnl0ZXM=",
                    "url": "http://156.238.224.67:13000/unreachable.png",
                }]
            })

        results = []
        failures = []
        worker._request = fake_request
        worker.result_ready.connect(results.append)
        worker.failed.connect(failures.append)

        with mock.patch(
            "gpt_desktop.workers.save_base64_to_image",
            return_value="/tmp/generated-from-base64.png",
        ) as save_base64:
            worker.run()

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["images"], ["/tmp/generated-from-base64.png"])
        self.assertEqual([method for method, _url, _kwargs in calls], ["POST"])
        save_base64.assert_called_once_with("aW1hZ2UtYnl0ZXM=", ".png")

    def test_failed_image_request_emits_diagnostics_without_api_key(self):
        worker = ImageWorker(
            "https://api.example.com",
            "secret-key",
            "gpt-image-2",
            "1024*1024",
            "自动",
            "1",
            "prompt",
            [],
        )
        messages = []
        failures = []
        worker.progress.connect(messages.append)
        worker.failed.connect(failures.append)
        worker._request = lambda *args, **kwargs: _FakeResponse({"error": {"message": "gateway timeout"}}, status_code=504)

        worker.run()

        joined = "\n".join(messages)
        self.assertTrue(failures)
        self.assertIn("接口诊断：POST https://api.example.com/v1/images/generations，HTTP 504", joined)
        self.assertIn("gateway timeout", joined)
        self.assertNotIn("secret-key", joined)

    def test_failed_image_request_emits_connection_exception_diagnostics(self):
        worker = ImageWorker(
            "https://api.example.com",
            "secret-key",
            "gpt-image-2",
            "1024*1024",
            "自动",
            "1",
            "prompt",
            [],
        )
        messages = []
        failures = []
        worker.progress.connect(messages.append)
        worker.failed.connect(failures.append)

        def fail_request(*args, **kwargs):
            raise Exception("Remote end closed connection without response")

        worker._request = fail_request
        worker.run()

        joined = "\n".join(messages)
        self.assertTrue(failures)
        self.assertIn("接口诊断：POST https://api.example.com/v1/images/generations", joined)
        self.assertIn("接口异常：Remote end closed connection without response", joined)
        self.assertNotIn("secret-key", joined)


if __name__ == "__main__":
    unittest.main()
