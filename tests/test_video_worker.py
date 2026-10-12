import json
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from gpt_desktop.workers import VideoWorker


_QT_APP = QApplication.instance() or QApplication([])


class _FakeResponse:
    def __init__(self, data=None, status_code=200, content=b"", headers=None, chunks=None):
        self._data = data
        self.status_code = status_code
        self.content = content or json.dumps(data or {}, ensure_ascii=False).encode("utf-8")
        self.headers = headers or {}
        self.chunks = list(chunks or [])
        self.closed = False

    def json(self):
        return self._data

    def raise_for_status(self):
        if self.status_code >= 400:
            raise Exception(f"HTTP {self.status_code}")

    def iter_content(self, chunk_size=1024 * 1024):
        yield from self.chunks

    def close(self):
        self.closed = True


class H3VideoWorkerTests(unittest.TestCase):
    def make_worker(self, **kwargs):
        values = {
            "base_url": "https://www.xcmapi.com/v1",
            "api_key": "key",
            "model": "h3",
            "prompt": "镜头平滑向前推进",
            "width": 1280,
            "height": 720,
            "num_frames": 81,
            "frame_rate": 24,
            "image_refs": ["https://example.com/first.png"],
            "duration": 8,
            "aspect_ratio": "16:9",
            "resolution": "720p",
            "last_frame_url": "https://example.com/last.png",
            "reference_image_urls": ["https://example.com/ref.png"],
            "voice_ids": ["eve", "leo"],
        }
        values.update(kwargs)
        return VideoWorker(**values)

    def test_h3_create_uses_documented_payload_and_generations_endpoint(self):
        worker = self.make_worker()
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _FakeResponse({"request_id": "req_h3_1", "status": "queued"})

        worker._request = fake_request
        response = worker._create_task()

        self.assertEqual(response["request_id"], "req_h3_1")
        self.assertEqual(calls[0][0], "POST")
        self.assertEqual(calls[0][1], "https://www.xcmapi.com/v1/videos/generations")
        payload = calls[0][2]["json"]
        self.assertEqual(payload["model"], "h3")
        self.assertEqual(payload["prompt"], "镜头平滑向前推进")
        self.assertEqual(payload["duration"], 8)
        self.assertEqual(payload["aspect_ratio"], "16:9")
        self.assertEqual(payload["resolution"], "720p")
        self.assertEqual(payload["image"], {"url": "https://example.com/first.png"})
        self.assertEqual(payload["last_frame"], {"url": "https://example.com/last.png"})
        self.assertEqual(payload["reference_images"], [{"url": "https://example.com/ref.png"}])
        self.assertEqual(payload["reference_audios"], [{"voice_id": "eve"}, {"voice_id": "leo"}])

    def test_h3_text_to_video_uses_base_videos_endpoint(self):
        worker = self.make_worker(
            image_refs=[],
            last_frame_url="",
            reference_image_urls=[],
            voice_ids=[],
        )
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _FakeResponse({"request_id": "req_h3_text", "status": "queued"})

        worker._request = fake_request
        worker._create_task()

        self.assertEqual(calls[0][1], "https://www.xcmapi.com/v1/videos")
        payload = calls[0][2]["json"]
        self.assertEqual(payload["model"], "h3")
        self.assertEqual(payload["duration"], 8)
        self.assertEqual(payload["aspect_ratio"], "16:9")
        self.assertEqual(payload["resolution"], "720p")
        self.assertNotIn("image", payload)
        self.assertNotIn("reference_images", payload)
        self.assertNotIn("reference_audios", payload)

    def test_h3_query_polls_documented_endpoint_until_completed(self):
        worker = self.make_worker()
        worker.VIDEO_QUERY_MIN_INTERVAL = 0
        responses = [
            _FakeResponse({"request_id": "req_h3_2", "status": "in_progress", "progress": 40}),
            _FakeResponse({"request_id": "req_h3_2", "status": "completed"}),
        ]
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return responses.pop(0)

        worker._request = fake_request
        with mock.patch.object(worker, "_sleep_with_stop"):
            result = worker._query_h3_result("req_h3_2")

        self.assertEqual(result["status"], "completed")
        self.assertEqual([call[1] for call in calls], [
            "https://www.xcmapi.com/v1/videos/req_h3_2",
            "https://www.xcmapi.com/v1/videos/req_h3_2",
        ])

    def test_h3_content_download_saves_local_mp4(self):
        worker = self.make_worker()
        with tempfile.TemporaryDirectory() as tmp:
            calls = []

            def fake_request(method, url, **kwargs):
                calls.append((method, url, kwargs))
                return _FakeResponse(chunks=[b"mp4", b"-data"])

            worker._request = fake_request
            with mock.patch("gpt_desktop.workers.VIDEO_DIR", tmp):
                path = worker._download_h3_content("req_h3_3")

            self.assertEqual(calls[0][1], "https://www.xcmapi.com/v1/videos/req_h3_3/content")
            self.assertTrue(path.endswith(".mp4"))
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"mp4-data")

    def test_h3_extracts_nested_video_url(self):
        worker = self.make_worker()
        self.assertEqual(
            worker._extract_video_url({"status": "completed", "video": {"url": "https://cdn.example.com/out.mp4"}}),
            "https://cdn.example.com/out.mp4",
        )

    def test_h3_run_falls_back_to_result_url_when_content_download_fails(self):
        worker = self.make_worker()
        responses = [
            _FakeResponse({"request_id": "req_h3_4", "status": "queued"}),
            _FakeResponse({"request_id": "req_h3_4", "status": "completed", "video": {"url": "https://cdn.example.com/out.mp4"}}),
            _FakeResponse({"error": "content unavailable"}, status_code=404),
            _FakeResponse(chunks=[b"fallback-mp4"]),
        ]
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return responses.pop(0)

        worker._request = fake_request
        worker.VIDEO_QUERY_MIN_INTERVAL = 0
        results = []
        failures = []
        worker.result_ready.connect(results.append)
        worker.failed.connect(failures.append)
        with tempfile.TemporaryDirectory() as tmp, mock.patch("gpt_desktop.workers.VIDEO_DIR", tmp), mock.patch.object(worker, "_sleep_with_stop"):
            worker.run()

        self.assertEqual(failures, [])
        self.assertEqual(results[0]["video_url"], "https://cdn.example.com/out.mp4")
        self.assertEqual([url for _method, url, _kwargs in calls], [
            "https://www.xcmapi.com/v1/videos/generations",
            "https://www.xcmapi.com/v1/videos/req_h3_4",
            "https://www.xcmapi.com/v1/videos/req_h3_4/content",
            "https://cdn.example.com/out.mp4",
        ])

    def test_non_h3_create_keeps_legacy_endpoint_and_payload(self):
        worker = self.make_worker(
            model="agnes-video-v2.0",
            image_refs=[],
            reference_image_urls=[],
            voice_ids=[],
        )
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _FakeResponse({"video_id": "legacy_1"})

        worker._request = fake_request
        worker._create_task()

        self.assertEqual(calls[0][1], "https://www.xcmapi.com/v1/videos")
        self.assertIn("width", calls[0][2]["json"])
        self.assertNotIn("duration", calls[0][2]["json"])


class SeedanceVideoWorkerTests(unittest.TestCase):
    def make_worker(self, **kwargs):
        values = {
            "base_url": "https://api.tcvps.cn",
            "api_key": "key",
            "model": "seedance-2.0-900-特惠",
            "prompt": "镜头平滑向前推进",
            "width": 1280,
            "height": 720,
            "num_frames": 81,
            "frame_rate": 24,
            "image_refs": ["https://example.com/first.png"],
            "duration": 5,
            "aspect_ratio": "16:9",
            "ratio": "16:9",
            "resolution": "720p",
            "seedance_video_urls": ["https://example.com/ref.mp4"],
            "seedance_audio_urls": ["https://example.com/ref.wav"],
            "seedance_material_urls": ["https://example.com/material.json"],
        }
        values.update(kwargs)
        return VideoWorker(**values)

    def test_seedance_create_uses_ratio_and_media_on_v1_videos(self):
        worker = self.make_worker()
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _FakeResponse({"id": "seed_1", "status": "queued"})

        worker._request = fake_request
        response = worker._create_task()

        self.assertEqual(response["id"], "seed_1")
        self.assertEqual(calls[0][1], "https://api.tcvps.cn/v1/videos")
        payload = calls[0][2]["json"]
        self.assertEqual(payload["model"], "seedance-2.0-900-特惠")
        self.assertEqual(payload["duration"], 5)
        self.assertEqual(payload["ratio"], "16:9")
        self.assertEqual(payload["resolution"], "720p")
        self.assertEqual(payload["images"], ["https://example.com/first.png"])
        self.assertEqual(payload["videos"], ["https://example.com/ref.mp4"])
        self.assertEqual(payload["audios"], ["https://example.com/ref.wav"])
        self.assertEqual(payload["materials"], ["https://example.com/material.json"])
        self.assertNotIn("aspect_ratio", payload)
        self.assertNotIn("width", payload)
        self.assertNotIn("num_frames", payload)

    def test_seedance_25_allows_30_seconds(self):
        worker = self.make_worker(model="seedance-2.5-900-特惠", duration=30)
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _FakeResponse({"task_id": "seed_30", "status": "queued"})

        worker._request = fake_request
        worker._create_task()
        self.assertEqual(calls[0][2]["json"]["duration"], 30)

    def test_seedance_933_supports_1080p(self):
        worker = self.make_worker(
            model="seedance-2.0-933-特惠",
            resolution="1080p",
            seedance_video_urls=[],
            seedance_audio_urls=[],
            seedance_material_urls=[],
        )
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return _FakeResponse({"video_id": "seed_1080", "status": "queued"})

        worker._request = fake_request
        worker._create_task()
        self.assertEqual(calls[0][2]["json"]["resolution"], "1080p")

    def test_seedance_mini_720p_rejects_more_than_12_seconds(self):
        worker = self.make_worker(model="seedance2.0-mini-A", duration=13)
        with self.assertRaisesRegex(Exception, "12"):
            worker._create_task()

    def test_seedance_query_and_content_download_use_documented_endpoints(self):
        worker = self.make_worker(
            image_refs=[],
            seedance_video_urls=[],
            seedance_audio_urls=[],
            seedance_material_urls=[],
        )
        worker.VIDEO_QUERY_MIN_INTERVAL = 0
        responses = [
            _FakeResponse({"id": "seed_2", "status": "processing", "progress": 20}),
            _FakeResponse({"id": "seed_2", "status": "completed"}),
        ]
        calls = []

        def fake_request(method, url, **kwargs):
            calls.append((method, url, kwargs))
            return responses.pop(0)

        worker._request = fake_request
        with mock.patch.object(worker, "_sleep_with_stop"):
            result = worker._query_unified_result("seed_2")
        self.assertEqual(result["status"], "completed")
        self.assertEqual([call[1] for call in calls], [
            "https://api.tcvps.cn/v1/videos/seed_2",
            "https://api.tcvps.cn/v1/videos/seed_2",
        ])

        with tempfile.TemporaryDirectory() as tmp:
            calls.clear()
            worker._request = lambda method, url, **kwargs: (
                calls.append((method, url, kwargs)) or _FakeResponse(chunks=[b"mp4", b"-seedance"])
            )
            with mock.patch("gpt_desktop.workers.VIDEO_DIR", tmp):
                path = worker._download_video_content("seed_2")
            self.assertEqual(calls[0][1], "https://api.tcvps.cn/v1/videos/seed_2/content")
            with open(path, "rb") as f:
                self.assertEqual(f.read(), b"mp4-seedance")


if __name__ == "__main__":
    unittest.main()
