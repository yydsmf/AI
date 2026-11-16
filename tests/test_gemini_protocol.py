import json
import unittest
from copy import deepcopy
from unittest.mock import patch

import gpt_desktop.workers as workers


MODEL = "gemini-2.5-flash"
BASE_URL = "https://gemini.test"
RESULT = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}


def native_payload(text="", reason="STOP", thought=""):
    parts = []
    if thought:
        parts.append({"thought": True, "text": thought})
    if text:
        parts.append({"text": text})
    candidate = {"content": {"role": "model", "parts": parts}}
    if reason is not None:
        candidate["finishReason"] = reason
    return {"candidates": [candidate], "modelVersion": MODEL}


def sse(payload):
    return "data: " + json.dumps(payload, ensure_ascii=False)


class Response:
    def __init__(self, data=None, lines=(), status=200):
        self.status_code = status
        self.headers = {}
        self.encoding = "utf-8"
        self.content = json.dumps(data or {}).encode("utf-8")
        self.data = data or {}
        self.lines = lines
        self.closed = False

    def json(self):
        return self.data

    def iter_lines(self, **kwargs):
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
        self.closed = False

    def post(self, url, **kwargs):
        self.calls.append((url, deepcopy(kwargs)))
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response

    get = post

    def close(self):
        self.closed = True


class GeminiProtocolTests(unittest.TestCase):
    def setUp(self):
        self.cache_key = workers._novel_protocol_cache_key(BASE_URL, MODEL)
        workers._NOVEL_GEMINI_PROTOCOL_OVERRIDES.discard(self.cache_key)
        self.addCleanup(workers._NOVEL_GEMINI_PROTOCOL_OVERRIDES.discard, self.cache_key)

    def analysis_worker(self, session):
        worker = workers.NovelAnalysisWorker(BASE_URL, "key", MODEL, "story context")
        worker._new_session = lambda: session
        return worker

    def writing_worker(self, session, action="outline"):
        worker = workers.NovelWritingWorker(BASE_URL, "key", MODEL, action, "story context")
        worker._session.close()
        worker._session = session
        return worker

    def test_native_request_handles_root_version_and_model_resource_names(self):
        for base in (BASE_URL, BASE_URL + "/v1beta/", BASE_URL + "/v1"):
            with self.subTest(base=base):
                url, headers, payload, protocol = workers._build_novel_generation_request(
                    base, "key", "models/" + MODEL, "system", "user", stream=False,
                    max_tokens=16000, temperature=0.2, reasoning_effort="high", response_format=True,
                )
                self.assertEqual(protocol, "gemini")
                self.assertEqual(url, f"{BASE_URL}/v1beta/models/{MODEL}:generateContent")
                self.assertEqual(headers["x-goog-api-key"], "key")
                self.assertNotIn("Authorization", headers)
                self.assertEqual(payload["systemInstruction"], {"parts": [{"text": "system"}]})
                self.assertEqual(payload["contents"], [{"role": "user", "parts": [{"text": "user"}]}])
                self.assertEqual(payload["generationConfig"], {
                    "temperature": 0.2, "maxOutputTokens": 28672, "responseMimeType": "application/json",
                    "thinkingConfig": {"thinkingBudget": 24576},
                })
                self.assertNotIn("reasoning_effort", payload)
                self.assertNotIn("response_format", payload)
                self.assertNotIn("stream", payload)

    def test_modern_native_gemini_high_is_independent_of_stream_and_alias(self):
        for model in ("gemini-3.1-pro", "gemini-3.8-flash-high", "models/gemini-4-hydrogen"):
            for stream in (False, True):
                with self.subTest(model=model, stream=stream):
                    _, _, payload, _ = workers._build_novel_generation_request(
                        BASE_URL, "key", model, "system", "user", stream=stream,
                        reasoning_effort="high",
                    )
                    self.assertEqual(payload["generationConfig"]["thinkingConfig"], {"thinkingLevel": "HIGH"})
                    self.assertGreaterEqual(payload["generationConfig"]["maxOutputTokens"], 16384)
                    self.assertNotIn("reasoning_effort", payload)

    def test_gemini_keeps_high_when_caller_requests_xhigh(self):
        for protocol in ("gemini", "openai"):
            for stream in (False, True):
                with self.subTest(protocol=protocol, stream=stream):
                    _, _, payload, _ = workers._build_novel_generation_request(
                        BASE_URL, "key", "models/gemini-3.8-flash-high", "system", "user",
                        stream=stream, reasoning_effort="xhigh", protocol=protocol,
                    )
                    if protocol == "gemini":
                        self.assertEqual(
                            payload["generationConfig"]["thinkingConfig"],
                            {"thinkingLevel": "HIGH"},
                        )
                        self.assertNotIn("reasoning_effort", payload)
                    else:
                        self.assertEqual(payload["reasoning_effort"], "high")

    def test_modern_gemini_omits_temperature_on_both_transports(self):
        models = (
            "gemini-3.5-flash-lite", "gemini-3.5-flash_lite-preview",
            "gemini-3.6-flash", "models/GEMINI-3.8-flash-high", "gemini-4-pro",
            "gemini-flash-latest", "gemini-pro",
        )
        for model in models:
            for protocol in ("gemini", "openai"):
                for stream in (False, True):
                    with self.subTest(model=model, protocol=protocol, stream=stream):
                        _, _, payload, _ = workers._build_novel_generation_request(
                            BASE_URL, "key", model, "system", "user", stream=stream,
                            temperature=0.2, reasoning_effort="high", protocol=protocol,
                        )
                        self.assertNotIn("temperature", payload)
                        config = payload.get("generationConfig", {})
                        self.assertNotIn("temperature", config)
                        if protocol == "gemini" and "latest" not in model and model != "gemini-pro":
                            self.assertEqual(config["thinkingConfig"], {"thinkingLevel": "HIGH"})
                        elif protocol == "openai":
                            self.assertEqual(payload["reasoning_effort"], "high")

    def test_legacy_gemini_preserves_requested_temperature(self):
        for model in (
            "gemini-1.5-pro", "gemini-2.0-flash", "models/gemini-2.5-pro",
            "gemini-3-pro-preview", "gemini-3.1-pro", "gemini-3.5-flash",
        ):
            for protocol in ("gemini", "openai"):
                for stream in (False, True):
                    with self.subTest(model=model, protocol=protocol, stream=stream):
                        _, _, payload, _ = workers._build_novel_generation_request(
                            BASE_URL, "key", model, "system", "user", stream=stream,
                            temperature=0.2, protocol=protocol,
                        )
                        config = payload["generationConfig"] if protocol == "gemini" else payload
                        self.assertEqual(config["temperature"], 0.2)

    def test_modern_gemini_workers_omit_temperature_after_protocol_fallback(self):
        model = "gemini-3.8-flash"
        cache_key = workers._novel_protocol_cache_key(BASE_URL, model)
        self.addCleanup(workers._NOVEL_GEMINI_PROTOCOL_OVERRIDES.discard, cache_key)
        for mode in ("stream", "nonstream", "writing"):
            with self.subTest(mode=mode):
                workers._NOVEL_GEMINI_PROTOCOL_OVERRIDES.discard(cache_key)
                text = "<NOVEL_OUTPUT_START>Result.<NOVEL_OUTPUT_END>" if mode == "writing" else json.dumps(RESULT)
                if mode == "nonstream":
                    success = Response({"choices": [{"message": {"content": text}}]})
                else:
                    success = Response(lines=[sse({
                        "choices": [{"delta": {"content": text}, "finish_reason": "stop"}],
                    }), "data: [DONE]"])
                session = Session(Response({"error": {"message": "route not found"}}, status=404), success)
                if mode == "writing":
                    worker = workers.NovelWritingWorker(BASE_URL, "key", model, "outline", "context")
                    worker._session.close()
                    worker._session = session
                    errors = []
                    worker.failed.connect(errors.append)
                    worker.run()
                    self.assertEqual(errors, [])
                else:
                    worker = workers.NovelAnalysisWorker(BASE_URL, "key", model, "context")
                    worker._new_session = lambda: session
                    method = worker._post_analysis_chunk_stream if mode == "stream" else worker._post_analysis_chunk
                    self.assertEqual(method("system", "user", 1, 1), RESULT)
                self.assertEqual(len(session.calls), 2)
                native, compatible = (call[1]["json"] for call in session.calls)
                self.assertNotIn("temperature", native["generationConfig"])
                self.assertEqual(native["generationConfig"]["thinkingConfig"], {"thinkingLevel": "HIGH"})
                self.assertNotIn("temperature", compatible)
                self.assertEqual(compatible["reasoning_effort"], "high")
                self.assertEqual(worker.diagnostics["protocol_fallback"], "openai")

    def test_gemini_openai_workers_keep_high_on_explicit_compatible_endpoint(self):
        base = "https://generativelanguage.googleapis.com/v1beta/openai"
        for worker in (
            workers.NovelAnalysisWorker(base, "key", MODEL, "context"),
            workers.NovelWritingWorker(base, "key", MODEL, "memory_reconcile", "context"),
        ):
            with self.subTest(worker=type(worker).__name__):
                self.assertEqual(worker.api_protocol, "openai")
                self.assertEqual(worker._reasoning_effort_for_request(), "high")

    def test_native_usage_supports_google_cached_token_field(self):
        usage = workers._normalize_novel_usage({
            "usageMetadata": {
                "promptTokenCount": 2400,
                "candidatesTokenCount": 24,
                "totalTokenCount": 2424,
                "cachedContentTokenCount": 2048,
            }
        })
        self.assertEqual(usage["cached_input_tokens"], 2048)
        self.assertEqual(usage["cache_status"], "hit")
        self.assertTrue(usage["cache_reported"])

        sdk_usage = workers._normalize_novel_usage({
            "usage": {
                "input_tokens": 2400,
                "output_tokens": 24,
                "total_tokens": 2424,
                "total_cached_tokens": 2048,
            }
        })
        self.assertEqual(sdk_usage["cached_input_tokens"], 2048)
        self.assertEqual(sdk_usage["cache_status"], "hit")

    def test_streaming_request_uses_sse_and_preserves_relay_prefix(self):
        url, headers, payload, protocol = workers._build_novel_generation_request(
            BASE_URL + "/google/v1beta", "key", MODEL, "system", "user", stream=True,
        )
        self.assertEqual(url, f"{BASE_URL}/google/v1beta/models/{MODEL}:streamGenerateContent?alt=sse")
        self.assertEqual(headers["Accept"], "text/event-stream")
        self.assertEqual(protocol, "gemini")
        self.assertNotIn("generationConfig", payload)

    def test_explicit_google_openai_endpoint_keeps_compatibility_protocol(self):
        base = "https://generativelanguage.googleapis.com/v1beta/openai/"
        url, headers, payload, protocol = workers._build_novel_generation_request(
            base, "key", MODEL, "system", "user", stream=True,
        )
        self.assertEqual(protocol, "openai")
        self.assertEqual(url, base + "chat/completions")
        self.assertEqual(headers["Authorization"], "Bearer key")
        self.assertIn("messages", payload)

    def test_response_joins_text_parts_and_excludes_thoughts_and_other_candidates(self):
        payload = native_payload("visible", thought="internal reasoning")
        payload["candidates"][0]["content"]["parts"].extend([
            {"text": " result", "thoughtSignature": "opaque"}, {"inlineData": {"data": "hidden"}},
        ])
        payload["candidates"].append(native_payload("other candidate")["candidates"][0])
        normalized = workers._normalize_novel_response_payload(payload)
        self.assertEqual(normalized["content"], "visible result")
        self.assertEqual(normalized["reasoning"], "internal reasoning")
        self.assertEqual(normalized["finish_reason"], "stop")
        self.assertTrue(normalized["done"])
        self.assertEqual(len(normalized["reasoning_fields"]), 1)

    def test_analysis_stream_waits_for_final_finish_reason_without_done_marker(self):
        response = Response(lines=[
            sse(native_payload(json.dumps(RESULT), reason=None, thought="internal")),
            sse(native_payload()),
        ])
        session = Session(response)
        worker = self.analysis_worker(session)
        self.assertEqual(worker._post_analysis_chunk_stream("system", "user", 1, 1), RESULT)
        self.assertEqual(worker.diagnostics["finish_reason"], "stop")
        self.assertEqual(worker.diagnostics["response_models"], [MODEL])
        self.assertEqual(worker.diagnostics["attempts"][0]["reasoning_chars"], len("internal"))
        self.assertTrue(worker.diagnostics["attempts"][0]["received_done"])
        self.assertTrue(response.closed)
        self.assertTrue(session.closed)

    def test_analysis_nonstream_accepts_native_json_result(self):
        session = Session(Response(native_payload(json.dumps(RESULT), thought="internal")))
        worker = self.analysis_worker(session)
        self.assertEqual(worker._post_analysis_chunk("system", "user", 1, 1), RESULT)
        self.assertEqual(worker.diagnostics["response_models"], [MODEL])
        self.assertEqual(worker.diagnostics["finish_reason"], "stop")
        self.assertTrue(session.calls[0][0].endswith(":generateContent"))
        self.assertEqual(session.calls[0][1]["json"]["generationConfig"]["responseMimeType"], "application/json")

    def test_analysis_rejects_truncated_blocked_and_unfinished_native_results(self):
        for stream in (False, True):
            for reason in ("MAX_TOKENS", "SAFETY", "RECITATION", None):
                with self.subTest(stream=stream, reason=reason):
                    payload = native_payload(json.dumps(RESULT), reason=reason)
                    response = Response(lines=[sse(payload)]) if stream else Response(payload)
                    worker = self.analysis_worker(Session(response))
                    method = worker._post_analysis_chunk_stream if stream else worker._post_analysis_chunk
                    with self.assertRaises(ValueError):
                        method("system", "user", 1, 1)
                    self.assertEqual(worker.diagnostics["attempts"][0]["outcome"], "error")

    def test_prompt_block_reports_reason_without_candidates(self):
        worker = self.analysis_worker(Session(Response(lines=[sse({"promptFeedback": {"blockReason": "SAFETY"}})])))
        with self.assertRaisesRegex(ValueError, "safety"):
            worker._post_analysis_chunk_stream("system", "user", 1, 1)

    def test_transport_failure_cannot_accept_gemini_json_before_finish_reason(self):
        session = Session(Response(lines=[
            sse(native_payload(json.dumps(RESULT), reason=None)),
            ConnectionError("response ended prematurely"),
        ]))
        worker = self.analysis_worker(session)
        with self.assertRaises(Exception):
            worker._post_analysis_chunk_stream("system", "user", 1, 1)
        self.assertNotEqual(worker.diagnostics["attempts"][0]["outcome"], "success")

    def test_writing_stream_keeps_visible_text_and_native_request_shape(self):
        session = Session(Response(lines=[sse(native_payload(
            "<NOVEL_OUTPUT_START>Result.<NOVEL_OUTPUT_END>", thought="internal",
        ))]))
        worker = self.writing_worker(session)
        errors, results, pieces = [], [], []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda action, text: results.append((action, text)))
        worker.chunk.connect(pieces.append)
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(results, [("outline", "Result.")])
        self.assertEqual("".join(pieces), "Result.")
        self.assertEqual(worker.diagnostics["api_protocol"], "gemini")
        self.assertEqual(worker.diagnostics["response_model"], MODEL)
        self.assertEqual(worker.diagnostics["ignored_reasoning_chars"], len("internal"))
        url, request = session.calls[0]
        self.assertTrue(url.endswith(":streamGenerateContent?alt=sse"))
        self.assertEqual(request["headers"]["x-goog-api-key"], "key")
        self.assertNotIn("reasoning_effort", request["json"])

    def test_writing_rejects_native_output_limit(self):
        worker = self.writing_worker(Session(Response(lines=[sse(native_payload(
            "<NOVEL_OUTPUT_START>Result.<NOVEL_OUTPUT_END>", reason="MAX_TOKENS",
        ))])))
        errors, results = [], []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.run()
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("max_tokens", worker.diagnostics["finish_reason"])

    def test_missing_native_route_falls_back_and_is_remembered_for_all_workers(self):
        for mode in ("stream", "nonstream", "writing"):
            with self.subTest(mode=mode):
                workers._NOVEL_GEMINI_PROTOCOL_OVERRIDES.discard(self.cache_key)
                text = "<NOVEL_OUTPUT_START>Result.<NOVEL_OUTPUT_END>" if mode == "writing" else json.dumps(RESULT)
                compatible = {"choices": [{"message": {"content": text}}]}
                if mode != "nonstream":
                    compatible = {"choices": [{"delta": {"content": text}, "finish_reason": "stop"}]}
                    success = Response(lines=[sse(compatible), "data: [DONE]"])
                else:
                    success = Response(compatible)
                missing = Response({"error": {"message": "route not found"}}, status=404)
                session = Session(missing, success)
                if mode == "writing":
                    worker = self.writing_worker(session)
                    errors = []
                    worker.failed.connect(errors.append)
                    worker.run()
                    self.assertEqual(errors, [])
                else:
                    worker = self.analysis_worker(session)
                    method = worker._post_analysis_chunk_stream if mode == "stream" else worker._post_analysis_chunk
                    self.assertEqual(method("system", "user", 1, 1), RESULT)
                self.assertEqual(len(session.calls), 2)
                self.assertIn(":", session.calls[0][0].split("/models/")[-1])
                self.assertEqual(session.calls[1][0], BASE_URL + "/v1/chat/completions")
                self.assertEqual(session.calls[1][1]["headers"]["Authorization"], "Bearer key")
                self.assertEqual(session.calls[1][1]["json"]["reasoning_effort"], "high")
                self.assertEqual(worker.diagnostics["protocol_fallback"], "openai")
                self.assertEqual(worker.api_protocol, "openai")
                self.assertEqual(workers._novel_api_protocol(BASE_URL, MODEL), "openai")
                self.assertTrue(missing.closed)

    def test_fallback_url_removes_native_version_from_relay_base(self):
        url, _, _, _ = workers._build_novel_generation_request(
            BASE_URL + "/relay/v1beta", "key", MODEL, "system", "user", stream=True, protocol="openai",
        )
        self.assertEqual(url, BASE_URL + "/relay/v1/chat/completions")

    def test_auth_quota_and_missing_model_do_not_change_protocol(self):
        errors = (
            (401, "invalid API key"), (403, "permission denied"), (429, "quota exceeded"),
            (404, "model not found"),
            (404, "models/gemini-unknown is not found for API version v1beta, or is not supported for generateContent. Call ListModels."),
        )
        for status, message in errors:
            with self.subTest(status=status, message=message):
                session = Session(Response({"error": {"message": message}}, status=status))
                worker = self.analysis_worker(session)
                with self.assertRaises(Exception):
                    worker._post_analysis_chunk_stream("system", "user", 1, 1)
                self.assertEqual(len(session.calls), 1)
                self.assertEqual(workers._novel_api_protocol(BASE_URL, MODEL), "gemini")

    def test_analysis_json_mode_can_fall_back_without_changing_protocol(self):
        session = Session(
            Response({"error": {"message": "responseMimeType is unsupported"}}, status=400),
            Response(lines=[sse(native_payload(json.dumps(RESULT)))]),
        )
        worker = self.analysis_worker(session)
        result, json_mode = worker._request_analysis_chunk_with_capability_fallback("system", "user", 1, 1, True)
        self.assertEqual(result, RESULT)
        self.assertFalse(json_mode)
        self.assertEqual(worker.api_protocol, "gemini")
        self.assertIn("responseMimeType", session.calls[0][1]["json"]["generationConfig"])
        self.assertNotIn("responseMimeType", session.calls[1][1]["json"]["generationConfig"])
        self.assertEqual(session.calls[1][1]["json"]["generationConfig"]["temperature"], 0.2)

    def test_writing_json_mode_can_fall_back_without_losing_other_settings(self):
        session = Session(
            Response({"error": {"message": "responseMimeType is unsupported"}}, status=400),
            Response(lines=[sse(native_payload('{"summary":"result"}'))]),
        )
        worker = self.writing_worker(session, action="memory_finalize")
        errors, results = [], []
        worker.failed.connect(errors.append)
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.run()
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 1)
        self.assertTrue(worker.diagnostics["json_response_format_fallback"])
        first = session.calls[0][1]["json"]["generationConfig"]
        second = session.calls[1][1]["json"]["generationConfig"]
        self.assertEqual(first["responseMimeType"], "application/json")
        self.assertNotIn("responseMimeType", second)
        self.assertEqual(second["maxOutputTokens"], first["maxOutputTokens"])
        self.assertEqual(worker.api_protocol, "gemini")

    def test_writing_native_json_transport_fallback_is_cached(self):
        first_session = Session(
            ConnectionError("Remote end closed connection without response"),
            Response(lines=[sse(native_payload('{"summary":"result"}'))]),
        )
        first = self.writing_worker(first_session, action="memory_finalize")
        key = first._json_transport_fallback_key()
        workers.NovelWritingWorker._json_transport_fallback_endpoints.discard(key)
        self.addCleanup(workers.NovelWritingWorker._json_transport_fallback_endpoints.discard, key)
        errors = []
        first.failed.connect(errors.append)
        first.run()
        self.assertEqual(errors, [])
        self.assertTrue(first.diagnostics["json_response_format_transport_fallback"])
        self.assertIn("responseMimeType", first_session.calls[0][1]["json"]["generationConfig"])
        self.assertNotIn("responseMimeType", first_session.calls[1][1]["json"]["generationConfig"])

        cached_session = Session(Response(lines=[sse(native_payload('{"summary":"result"}'))]))
        cached = self.writing_worker(cached_session, action="memory_finalize")
        cached.failed.connect(errors.append)
        cached.run()
        self.assertEqual(errors, [])
        self.assertTrue(cached.diagnostics["json_response_format_cached_fallback"])
        self.assertEqual(len(cached_session.calls), 1)
        self.assertNotIn("responseMimeType", cached_session.calls[0][1]["json"]["generationConfig"])


class GeminiModelListTests(unittest.TestCase):
    def run_worker(self, base, session):
        worker = workers.ModelListWorker(base, "key", provider_id="provider", request_id="request")
        results, errors = [], []
        worker.result_ready.connect(lambda *args: results.append(args))
        worker.failed.connect(lambda *args: errors.append(args))
        with patch.object(workers.requests, "Session", return_value=session):
            worker.run()
        return results, errors

    def test_native_list_handles_pagination_and_filters_embedding_models(self):
        for base in ("https://generativelanguage.googleapis.com", BASE_URL + "/v1beta/"):
            with self.subTest(base=base):
                first = Response({"models": [
                    {"name": "models/" + MODEL, "supportedGenerationMethods": ["generateContent"]},
                    {"name": "models/embedding", "supportedGenerationMethods": ["embedContent"]},
                ], "nextPageToken": "next"})
                second = Response({"models": [
                    {"name": "models/" + MODEL}, {"name": "models/gemini-2.5-pro"},
                ]})
                session = Session(first, second)
                results, errors = self.run_worker(base, session)
                self.assertEqual(errors, [])
                self.assertEqual(results, [("provider", "request", [MODEL, "gemini-2.5-pro"])])
                self.assertEqual(session.calls[0][0], base.rstrip("/") + ("/models" if base.rstrip("/").endswith("/v1beta") else "/v1beta/models"))
                self.assertEqual(session.calls[1][1]["params"], {"pageToken": "next"})
                self.assertEqual(session.calls[0][1]["headers"]["x-goog-api-key"], "key")
                self.assertTrue(first.closed and second.closed and session.closed)

    def test_native_list_reads_all_pages_without_silent_five_page_limit(self):
        pages = [Response({"models": [{"name": f"models/gemini-test-{index}"}],
                           **({"nextPageToken": str(index + 1)} if index < 6 else {})}) for index in range(7)]
        session = Session(*pages)
        results, errors = self.run_worker(BASE_URL + "/v1beta", session)
        self.assertEqual(errors, [])
        self.assertEqual(len(results[0][2]), 7)
        self.assertEqual(len(session.calls), 7)

    def test_relay_with_missing_openai_models_route_uses_native_list(self):
        session = Session(
            Response({"error": {"message": "route not found"}}, status=404),
            Response({"models": [{"name": "models/" + MODEL}]}),
        )
        results, errors = self.run_worker(BASE_URL, session)
        self.assertEqual(errors, [])
        self.assertEqual(results[0][2], [MODEL])
        self.assertEqual(session.calls[0][0], BASE_URL + "/v1/models")
        self.assertEqual(session.calls[1][0], BASE_URL + "/v1beta/models")

    def test_model_list_auth_error_is_not_retried_as_another_protocol(self):
        session = Session(Response({"error": {"message": "invalid API key"}}, status=401))
        results, errors = self.run_worker(BASE_URL, session)
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertEqual(len(session.calls), 1)

    def test_explicit_google_openai_model_list_endpoint_is_preserved(self):
        session = Session(Response({"data": [{"id": MODEL}]}))
        base = "https://generativelanguage.googleapis.com/v1beta/openai"
        results, errors = self.run_worker(base, session)
        self.assertEqual(errors, [])
        self.assertEqual(results[0][2], [MODEL])
        self.assertEqual(session.calls[0][0], base + "/models")
        self.assertEqual(session.calls[0][1]["headers"]["Authorization"], "Bearer key")

    def test_repeated_page_token_reports_error_instead_of_returning_partial_list(self):
        session = Session(*[Response({"models": [{"name": "models/" + MODEL}], "nextPageToken": "same"}) for _ in range(2)])
        results, errors = self.run_worker(BASE_URL + "/v1beta", session)
        self.assertEqual(results, [])
        self.assertEqual(len(errors), 1)
        self.assertIn("pageToken", errors[0][2])
        self.assertEqual(len(session.calls), 2)


if __name__ == "__main__":
    unittest.main()
