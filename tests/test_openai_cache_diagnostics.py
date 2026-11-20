import json
import unittest
from copy import deepcopy

import gpt_desktop.workers as workers


MODEL = "gpt-5.6-sol"
BASE_URL = "https://provider.example/v1"
RESULT = {
    "characters": [],
    "lore": [],
    "foreshadows": [],
    "project_materials": {},
}


def sse(payload):
    return "data: " + json.dumps(payload, ensure_ascii=False)


class Response:
    def __init__(self, data=None, lines=(), status=200):
        self.status_code = status
        self.headers = {}
        self.encoding = "utf-8"
        self.data = data or {}
        self.content = json.dumps(self.data, ensure_ascii=False).encode("utf-8")
        self.lines = tuple(lines)
        self.closed = False

    def json(self):
        return self.data

    def iter_lines(self, **_kwargs):
        for line in self.lines:
            if isinstance(line, Exception):
                raise line
            yield line.encode("utf-8")

    def close(self):
        self.closed = True


class Session:
    trust_env = False

    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def post(self, url, **kwargs):
        self.calls.append((url, deepcopy(kwargs)))
        return self.responses.pop(0)

    def close(self):
        pass


def openai_stream_lines(text, cached_tokens=0):
    return [
        sse({
            "id": "chunk-1",
            "model": MODEL,
            "choices": [{"delta": {"content": text}, "finish_reason": None}],
        }),
        sse({
            "id": "chunk-2",
            "model": MODEL,
            "choices": [{"delta": {}, "finish_reason": "stop"}],
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": cached_tokens},
            },
        }),
        "data: [DONE]",
    ]


class OpenAICacheDiagnosticsTests(unittest.TestCase):
    def analysis_worker(self, session):
        worker = workers.NovelAnalysisWorker(
            BASE_URL,
            "key",
            MODEL,
            "story context",
        )
        worker._new_session = lambda: session
        return worker

    def writing_worker(self, session):
        worker = workers.NovelWritingWorker(
            BASE_URL,
            "key",
            MODEL,
            "outline",
            "story context",
        )
        worker._session.close()
        worker._session = session
        return worker

    def test_normalizes_openai_cached_tokens(self):
        usage = workers._normalize_novel_usage({
            "usage": {
                "prompt_tokens": 100,
                "completion_tokens": 20,
                "total_tokens": 120,
                "prompt_tokens_details": {"cached_tokens": 80},
            }
        })

        self.assertEqual(usage["cached_input_tokens"], 80)
        self.assertEqual(usage["cache_status"], "hit")
        self.assertTrue(usage["cache_reported"])

    def test_normalizes_cache_write_without_mislabeling_it_as_a_hit(self):
        usage = workers._normalize_novel_usage({
            "usage": {
                "input_tokens": 100,
                "cache_creation_input_tokens": 100,
            }
        })
        self.assertEqual(usage["cache_write_input_tokens"], 100)
        self.assertEqual(usage["cache_status"], "write")

    def test_analysis_stream_records_cache_usage_after_finish_chunk(self):
        session = Session(Response(lines=openai_stream_lines(json.dumps(RESULT), 80)))
        worker = self.analysis_worker(session)

        self.assertEqual(worker._post_analysis_chunk_stream("system", "user", 1, 1), RESULT)
        self.assertEqual(worker.diagnostics["cache_status"], "hit")
        self.assertEqual(worker.diagnostics["cached_input_tokens"], 80)
        self.assertEqual(worker.diagnostics["attempts"][0]["usage"]["cached_input_tokens"], 80)
        self.assertTrue(session.calls[0][1]["json"]["stream_options"]["include_usage"])
        self.assertNotIn("prompt_cache_options", session.calls[0][1]["json"])
        self.assertNotIn("prompt_cache_key", session.calls[0][1]["json"])
        self.assertTrue(
            session.calls[0][1]["json"]["messages"][0]["content"].startswith("system")
        )

    def test_analysis_stream_retries_without_unsupported_cache_options(self):
        first = Response(
            {"error": {"message": "Unknown parameter: stream_options"}},
            status=400,
        )
        second = Response(lines=openai_stream_lines(json.dumps(RESULT), 0))
        session = Session(first, second)
        worker = self.analysis_worker(session)

        self.assertEqual(worker._post_analysis_chunk_stream("system", "user", 1, 1), RESULT)
        self.assertTrue(worker.diagnostics["prompt_cache_options_fallback"])
        self.assertIn("stream_options", session.calls[0][1]["json"])
        self.assertNotIn("stream_options", session.calls[1][1]["json"])
        self.assertNotIn("prompt_cache_options", session.calls[1][1]["json"])
        fallback_system = session.calls[1][1]["json"]["messages"][0]["content"]
        self.assertIsInstance(fallback_system, str)
        self.assertIn("system", fallback_system)

    def test_xcmapi_uses_documented_chat_shape_without_cache_extensions(self):
        url, _headers, payload, protocol = workers._build_novel_generation_request(
            "https://xcmapi.org/v1",
            "key",
            MODEL,
            "system",
            "user",
            stream=True,
        )

        self.assertEqual(protocol, "openai")
        self.assertEqual(url, "https://xcmapi.org/v1/chat/completions")
        self.assertNotIn("stream_options", payload)
        self.assertNotIn("prompt_cache_options", payload)
        self.assertNotIn("prompt_cache_key", payload)
        self.assertEqual(payload["messages"][0], {"role": "system", "content": "system"})

    def test_other_openai_relays_keep_stream_usage_extension(self):
        _, _, payload, protocol = workers._build_novel_generation_request(
            "https://provider.example/v1",
            "key",
            MODEL,
            "system",
            "user",
            stream=True,
        )

        self.assertEqual(protocol, "openai")
        self.assertEqual(payload["stream_options"], {"include_usage": True})

    def test_writing_stream_records_cache_usage(self):
        session = Session(Response(lines=openai_stream_lines(
            "<NOVEL_OUTPUT_START>Result.<NOVEL_OUTPUT_END>",
            80,
        )))
        worker = self.writing_worker(session)
        errors = []
        results = []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, text: results.append((action, text)))

        worker.run()

        self.assertEqual(errors, [])
        self.assertEqual(results, [("outline", "Result.")])
        self.assertEqual(worker.diagnostics["cache_status"], "hit")
        self.assertEqual(worker.diagnostics["cached_input_tokens"], 80)


if __name__ == "__main__":
    unittest.main()
