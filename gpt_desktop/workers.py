import asyncio
import gc
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from datetime import datetime
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from copy import deepcopy

import requests
from PySide6.QtCore import QThread, Signal

from .core import (
    VIDEO_DIR,
    api_url,
    ensure_thumbnail_cache,
    extract_api_error,
    image_file_to_base64,
    image_suffix_from_bytes,
    image_suffix_from_content_type,
    now_str,
    prepare_image_upload_file,
    requests_proxies,
    safe_response_text,
    safe_remove_file,
    save_base64_to_image,
    save_bytes_to_image,
)
from .novel_utils import _infer_foreshadow_status
from .novel_import import _normalize_ai_candidates


def post_json(session, url, headers, payload, timeout, proxies=None):
    r = session.post(url, headers=headers, json=payload, timeout=timeout, proxies=proxies)
    try:
        if r.status_code >= 400:
            raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")
        return r.json()
    finally:
        try:
            r.close()
        except Exception:
            pass


class ModelListWorker(QThread):
    result_ready = Signal(list)
    failed = Signal(str)

    def __init__(self, base_url, api_key, proxy_url="", proxy_mode="不使用代理"):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.proxy_url = str(proxy_url or "").strip()
        self.proxy_mode = str(proxy_mode or "不使用代理").strip()

    def _proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def run(self):
        try:
            if not self.base_url:
                raise Exception("请先选择厂商或设置中转地址。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")

            url = api_url(self.base_url, "/v1/models")
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            session = requests.Session()
            session.trust_env = False
            try:
                r = session.get(url, headers=headers, timeout=60, proxies=self._proxies())
                try:
                    if r.status_code >= 400:
                        raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")
                    data = r.json()
                finally:
                    try:
                        r.close()
                    except Exception:
                        pass
            finally:
                try:
                    session.close()
                except Exception:
                    pass
            models = sorted({item.get("id") for item in data.get("data", []) if item.get("id")})
            if not models:
                raise Exception("接口没有返回可用模型。")
            self.result_ready.emit(models)
        except Exception as e:
            self.failed.emit(str(e))


class NovelAnalysisWorker(QThread):
    partial_ready = Signal(dict, int, int)
    result_ready = Signal(dict)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(
        self,
        base_url,
        api_key,
        model,
        text,
        proxy_url="",
        proxy_mode="不使用代理",
        max_concurrency=3,
        chunks=None,
        dossier="",
    ):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.text = str(text or "")
        self.dossier = str(dossier or "").strip()
        self.input_chunk_records = self._normalize_input_chunk_records(chunks)
        self.proxy_url = str(proxy_url or "").strip()
        self.proxy_mode = str(proxy_mode or "不使用代理").strip()
        self._stop_requested = False
        self._response = None
        self._active_responses = set()
        self._active_sessions = set()
        self._network_lock = threading.Lock()
        self._capability_lock = threading.Lock()
        self._analysis_response_format_supported = True
        self._analysis_stream_supported = True
        try:
            max_concurrency = int(max_concurrency or 3)
        except Exception:
            max_concurrency = 3
        self.max_concurrency = max(1, min(6, max_concurrency))
        self.retry_attempts = 3

    def _normalize_input_chunk_records(self, chunks):
        records = []
        for fallback_index, item in enumerate(chunks or [], 1):
            if isinstance(item, dict):
                text = str(item.get("text", "") or "").strip()
                label = item.get("index", fallback_index)
                total = item.get("total", 0)
            else:
                text = str(item or "").strip()
                label = fallback_index
                total = 0
            if not text:
                continue
            records.append({
                "text": text,
                "index": label if str(label or "").strip() else len(records) + 1,
                "total": total,
            })
        batch_total = len(records)
        for record in records:
            try:
                record_total = int(record.get("total", 0) or 0)
            except Exception:
                record_total = 0
            record["total"] = record_total if record_total > 0 else batch_total
        return records

    def _analysis_request_capabilities(self):
        with self._capability_lock:
            return self._analysis_response_format_supported, self._analysis_stream_supported

    def _set_analysis_response_format_supported(self, supported):
        with self._capability_lock:
            self._analysis_response_format_supported = bool(supported)

    def _set_analysis_stream_supported(self, supported):
        with self._capability_lock:
            self._analysis_stream_supported = bool(supported)

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        self._close_active_network_handles()

    def _proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def _new_session(self):
        session = requests.Session()
        session.trust_env = False
        with self._network_lock:
            self._active_sessions.add(session)
        return session

    def _close_active_network_handles(self):
        with self._network_lock:
            responses = list(self._active_responses)
            sessions = list(self._active_sessions)
            self._active_responses.clear()
            self._active_sessions.clear()
        for response in responses:
            try:
                response.close()
            except Exception:
                pass
        for session in sessions:
            try:
                session.close()
            except Exception:
                pass

    def _release_session(self, session):
        if session is None:
            return
        with self._network_lock:
            self._active_sessions.discard(session)

    def _register_response(self, response):
        if response is None:
            return
        with self._network_lock:
            self._active_responses.add(response)

    def _release_response(self, response):
        if response is None:
            return
        with self._network_lock:
            self._active_responses.discard(response)

    def _split_text_chunks(self, text, target_chars=4500, max_chars=6000):
        text = str(text or "").strip()
        if not text:
            return []
        blocks = [x.strip() for x in re.split(r"\n{2,}", text) if x.strip()]
        if not blocks:
            blocks = [text]
        chunks = []
        current = ""

        def flush():
            nonlocal current
            if current.strip():
                chunks.append(current.strip())
            current = ""

        for block in blocks:
            pieces = self._split_long_analysis_block(block, max_chars)
            for piece in pieces:
                candidate = f"{current}\n\n{piece}" if current else piece
                if current and len(candidate) > target_chars:
                    flush()
                    current = piece
                else:
                    current = candidate
                if len(current) >= max_chars:
                    flush()
        flush()
        return chunks

    def _split_long_analysis_block(self, text, max_chars):
        text = str(text or "").strip()
        if len(text) <= max_chars:
            return [text] if text else []
        parts = []
        current = ""
        for piece in re.split(r"([。！？；!?;]\s*)", text):
            if not piece:
                continue
            candidate = current + piece
            if current and len(candidate) > max_chars:
                parts.append(current.strip())
                current = piece
            else:
                current = candidate
        if current.strip():
            parts.append(current.strip())
        out = []
        for part in parts:
            while len(part) > max_chars:
                out.append(part[:max_chars].strip())
                part = part[max_chars:].strip()
            if part:
                out.append(part)
        return out

    def _parse_json_result(self, content):
        content = str(content or "").strip()
        if content.startswith("```"):
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:].strip()
            elif content.startswith("```"):
                content = content[3:].strip()
            if content.endswith("```"):
                content = content[:-3].strip()
        start = content.find("{")
        end = content.rfind("}")
        if start >= 0 and end > start:
            content = content[start:end + 1]
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            preview = content[:240].replace("\n", " ")
            raise ValueError(
                "AI 返回内容不是合法 JSON。请换一个更擅长结构化输出的模型，或减少导入文本后重试。"
                f"\n解析位置：第 {e.lineno} 行，第 {e.colno} 列。"
                f"\n返回预览：{preview}"
            )
        if not isinstance(data, dict):
            raise ValueError("AI 返回不是 JSON 对象。")
        return data

    def _analysis_prompt(self):
        return (
            "你是长篇小说资料整理助手。请从用户提供的小说/剧本文本片段中提取候选资料。\n"
            "你必须只输出一个合法 JSON 对象，不要 Markdown，不要解释，不要注释，不要尾随逗号。\n"
            "所有字符串里的换行、引号都必须正确 JSON 转义。\n"
            "要求：不要把一次性路人或普通名词过度提取；不确定就少提取。\n"
            "不要为了压缩结果而丢失会影响后续剧情、人物关系、地点道具、伏笔线索的信息。\n"
            "请按 20 万字左右长篇小说的连续性需求提取：优先保留后续章节必须继承的事实、"
            "人物目标/秘密/关系变化、地点/势力/物品规则、时间顺序和未回收伏笔；"
            "弱化一次性描写、普通动作和不会影响后文的临时信息。\n"
            "如果用户内容含有【已有项目档案】，它只作为合并和去重参考：同名、别称或同一线索不要重复新增，"
            "长期有效的人物变化才写入已有人物 notes，例如身份、目标、秘密、阵营、称呼、关系质变、长期伤势/物品或语言风格变化；"
            "普通章节行动、临时情绪、一次性互动和只在本章成立的关系推进，不要写入人物 notes，"
            "其中只有会影响后续章节继承的全局增量，才放入 project_materials.summary 或 timeline。"
            "稳定设定变化才写入 lore.description，例如长期有效的规则、制度、结构关系、地点/势力/物品属性、能力限制、固定渠道或所有权；"
            "本章出现、追问、调查、发送、发现线索、谁去问谁等临时推进，不要写入 lore.description，改放 timeline/summary/foreshadows；"
            "伏笔变化写入状态/章节；"
            "不要把已有档案里没有在本片段推进的信息当作新发现重复输出。\n"
            "如果这是长文分块的一部分，只提取本片段明确出现或能稳定判断的信息；"
            "没有明确全局增量时，project_materials 对应字段请留空字符串，不要为了填满结构写普通流水账。\n"
            "JSON 结构：{\n"
            '  "characters": [{"name":"","role":"","goal":"","secret":"","voice":"","notes":""}],\n'
            '  "lore": [{"name":"","type":"地点/势力/物品/规则/术语/事件/其他","description":""}],\n'
            '  "foreshadows": [{"name":"","status":"","setup_chapter":"","payoff_chapter":"","description":""}],\n'
            '  "project_materials": {"bible":"","world_rules":"","timeline":"","summary":""}\n'
            "}\n"
            "foreshadows.status 判定：只提出未来可能用到但尚未在片段中埋下的线索填“未埋”；"
            "片段中已经出现线索、异常、铺垫或悬念填“已埋”；片段中已经兑现、揭示、解释或回收填“已回收”；"
            "明确作废或不再使用的线索填“废弃”。能判断章节/分集标题时填写 setup_chapter/payoff_chapter。\n"
            "设定和伏笔不要原文重复：同一内容如果只是规则、制度、物品用途或客观设定，只放入 lore；"
            "如果它同时是规则和后续承诺，lore 写规则本身，foreshadows 改写成待验证/待回收的问题或结果，"
            "名称不要与 lore 完全相同，例如“试用条件”进设定，“能否完成试用条件”进伏笔。\n"
            "foreshadows 要求：只提取会跨章节影响后文的明确线索、承诺、谜题或待回收信息；"
            "普通悬念、单章情绪钩子、一次性疑问、普通信息差和氛围描写不要列为伏笔。"
            "每个片段优先提取最重要的跨章节伏笔；数量不固定，没有明确跨章节价值就返回空数组，"
            "不要为了凑数写普通悬念，也不要因为条数限制丢掉明确会影响后文的伏笔。\n"
            "characters.notes 要求：只写会影响后续多章的人物档案增量；如果只是本章发生了什么、短暂情绪或普通互动，就留空字符串。\n"
            "lore.description 要求：只写后续章节需要继承的稳定设定增量；如果只是本章动作、线索推进、调查过程或临时危机，就留空字符串。\n"
            "project_materials 要求：bible 写故事核心、主线矛盾、主要人物关系和风格基调；"
            "world_rules 写世界观、势力、制度、能力/道具规则；"
            "timeline 只记录关键转折、时间顺序变化、伏笔推进/回收、重要关系或长期状态变化；"
            "summary 只写对全局剧情有继承价值的简短状态变化；没有明确内容就留空字符串。"
            "两者都要精炼，但不要因为固定条数限制丢掉会影响后续章节继承的信息。"
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        user_text = (
            f"这是第 {chunk_index}/{total_chunks} 个文本片段。"
            "请只根据本片段提取候选，不要臆测其它片段。"
        )
        if self.dossier:
            user_text += "\n\n" + self.dossier
        return user_text + "\n\n【本片段】\n" + str(chunk_text or "")

    def _post_analysis_chunk(self, prompt, chunk_text, chunk_index, total_chunks, use_response_format=True):
        url = api_url(self.base_url, "/v1/chat/completions")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        user_text = self._chunk_user_text(chunk_text, chunk_index, total_chunks)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
        }
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        session = self._new_session()
        try:
            data = post_json(session, url, headers, payload, (10, 180), self._proxies())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return self._parse_json_result(content)
        finally:
            self._release_session(session)
            try:
                session.close()
            except Exception:
                pass

    def _post_analysis_chunk_stream(self, prompt, chunk_text, chunk_index, total_chunks, use_response_format=True):
        url = api_url(self.base_url, "/v1/chat/completions")
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "text/event-stream",
        }
        user_text = self._chunk_user_text(chunk_text, chunk_index, total_chunks)
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": prompt},
                {"role": "user", "content": user_text},
            ],
            "temperature": 0.2,
            "stream": True,
        }
        if use_response_format:
            payload["response_format"] = {"type": "json_object"}
        session = self._new_session()
        r = session.post(
            url,
            headers=headers,
            json=payload,
            stream=True,
            timeout=(10, 180),
            proxies=self._proxies(),
        )
        self._response = r
        self._register_response(r)
        try:
            if r.status_code >= 400:
                raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")

            full = ""
            first_piece = False
            r.encoding = "utf-8"
            for raw_line in r.iter_lines(decode_unicode=False):
                if self._stop_requested or self.isInterruptionRequested():
                    return {}
                if not raw_line:
                    continue
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("utf-8", errors="replace")
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except Exception:
                    continue
                if isinstance(data.get("error"), dict):
                    raise Exception(data["error"].get("message") or json.dumps(data["error"], ensure_ascii=False))
                if isinstance(data.get("error"), str) and data.get("error"):
                    raise Exception(data.get("error"))
                choices = data.get("choices") or []
                if not choices:
                    continue
                choice = choices[0] or {}
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                piece = (
                    delta.get("content")
                    or delta.get("reasoning_content")
                    or delta.get("reasoning")
                    or delta.get("text")
                    or message.get("content")
                    or choice.get("text")
                )
                if piece:
                    if not first_piece:
                        first_piece = True
                        self.progress.emit(f"正在接收候选分析 {chunk_index}/{total_chunks} 的流式结果...")
                    full += piece
            if not full.strip():
                raise Exception("AI 没有返回有效候选内容。")
            return self._parse_json_result(full)
        finally:
            try:
                r.close()
            except Exception:
                pass
            self._release_response(r)
            if self._response is r:
                self._response = None
            self._release_session(session)
            try:
                session.close()
            except Exception:
                pass

    def _is_retryable_analysis_error(self, error):
        msg = str(error or "").lower()
        retry_markers = (
            "524",
            "timeout",
            "timed out",
            "read timed out",
            "连接超时",
            "a timeout occurred",
            "temporarily unavailable",
            "bad gateway",
            "502",
            "503",
            "504",
            "response ended prematurely",
            "incomplete read",
            "chunkedencodingerror",
            "connection broken",
            "remote end closed connection",
            "protocolerror",
        )
        return any(marker in msg for marker in retry_markers)

    def _is_stream_unsupported_error(self, error):
        msg = str(error or "").lower()
        return "stream" in msg and (
            "support" in msg
            or "unsupported" in msg
            or "not support" in msg
            or "不支持" in msg
        )

    def _is_stream_transport_error(self, error):
        msg = str(error or "").lower()
        transport_markers = (
            "response ended prematurely",
            "incomplete read",
            "chunkedencodingerror",
            "connection broken",
            "remote end closed connection",
            "protocolerror",
        )
        return any(marker in msg for marker in transport_markers)

    def _analyze_chunk_resilient(self, prompt, chunk, label, total, use_response_format):
        response_format_supported, stream_supported = self._analysis_request_capabilities()
        use_response_format = bool(use_response_format and response_format_supported)
        try:
            if stream_supported:
                return self._post_analysis_chunk_stream(prompt, chunk, label, total, use_response_format), use_response_format
            return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
        except Exception as e:
            msg = str(e).lower()
            if use_response_format and ("response_format" in msg or "json_object" in msg):
                self._set_analysis_response_format_supported(False)
                self.progress.emit("当前接口不支持强制 JSON，已降级继续分块分析...")
                try:
                    if stream_supported:
                        return self._post_analysis_chunk_stream(prompt, chunk, label, total, False), False
                    return self._post_analysis_chunk(prompt, chunk, label, total, False), False
                except Exception as e2:
                    if self._is_stream_unsupported_error(e2):
                        self._set_analysis_stream_supported(False)
                        self.progress.emit("当前接口不支持流式候选分析，已自动退回普通分块请求...")
                        return self._post_analysis_chunk(prompt, chunk, label, total, False), False
                    if stream_supported and self._is_stream_transport_error(e2):
                        self._set_analysis_stream_supported(False)
                        self.progress.emit("流式候选分析连接提前结束，已切换为普通请求重试...")
                        return self._post_analysis_chunk(prompt, chunk, label, total, False), False
                    raise
            if self._is_stream_unsupported_error(e):
                self._set_analysis_stream_supported(False)
                self.progress.emit("当前接口不支持流式候选分析，已自动退回普通分块请求...")
                return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
            if stream_supported and self._is_stream_transport_error(e):
                self._set_analysis_stream_supported(False)
                self.progress.emit("流式候选分析连接提前结束，已切换为普通请求重试...")
                return self._post_analysis_chunk(prompt, chunk, label, total, use_response_format), use_response_format
            if self._is_retryable_analysis_error(e) and len(chunk) > 1800:
                parts = self._split_text_chunks(chunk, target_chars=max(1200, len(chunk) // 2), max_chars=max(1600, len(chunk) // 2 + 300))
                if len(parts) > 1:
                    merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
                    self.progress.emit(f"第 {label}/{total} 块响应过慢，已自动拆成 {len(parts)} 小块重试...")
                    current_response_format = use_response_format
                    for sub_index, part in enumerate(parts, 1):
                        if self._stop_requested or self.isInterruptionRequested():
                            return merged, current_response_format
                        self.progress.emit(f"正在分析候选 {label}/{total} 的小块 {sub_index}/{len(parts)}...")
                        parsed, current_response_format = self._analyze_chunk_resilient(
                            prompt,
                            part,
                            f"{label}.{sub_index}",
                            total,
                            current_response_format,
                        )
                        self._merge_analysis_result(merged, parsed)
                    return merged, current_response_format
            raise

    def _analyze_chunk_with_retries(self, prompt, chunk, label, total, use_response_format):
        attempts = max(1, int(self.retry_attempts or 1))
        current_response_format = use_response_format
        last_error = None
        for attempt in range(1, attempts + 1):
            if self._stop_requested or self.isInterruptionRequested():
                return {}, current_response_format
            try:
                return self._analyze_chunk_resilient(
                    prompt,
                    chunk,
                    label,
                    total,
                    current_response_format,
                )
            except Exception as e:
                last_error = e
                if attempt >= attempts or not self._is_retryable_analysis_error(e):
                    raise
                wait_seconds = min(8, 2 * attempt)
                self.progress.emit(f"第 {label}/{total} 块暂时失败，{wait_seconds} 秒后自动重试 {attempt + 1}/{attempts}...")
                deadline = time.time() + wait_seconds
                while time.time() < deadline:
                    if self._stop_requested or self.isInterruptionRequested():
                        return {}, current_response_format
                    time.sleep(0.2)
        raise last_error or Exception("候选分析失败。")

    def _merge_candidate_group(self, output, key, item, fields, append_fields=()):
        if not isinstance(item, dict):
            return
        name = str(item.get("name", "") or "").strip()
        if not name:
            return
        target = output.setdefault(key, [])

        def merge_source_label(target_item, source_label):
            source_label = str(source_label or "").strip()
            if not source_label:
                return
            old = str(target_item.get("_source_label", "") or "").strip()
            labels = [line.strip() for line in old.splitlines() if line.strip()]
            if source_label not in labels:
                labels.append(source_label)
            target_item["_source_label"] = "\n".join(labels)

        existing = None
        for old in target:
            if isinstance(old, dict) and str(old.get("name", "") or "").strip() == name:
                existing = old
                break
        if existing is None:
            data = {field: str(item.get(field, "") or "") for field in ("name",) + tuple(fields)}
            merge_source_label(data, item.get("_source_label", ""))
            if key == "foreshadows" and item.get("_status_explicit"):
                data["status"] = _infer_foreshadow_status({"status": data.get("status", "")}, preserve_manual=False)
            target.append(data)
            return

        merge_source_label(existing, item.get("_source_label", ""))

        for field in fields:
            if key == "foreshadows" and field == "status":
                if item.get("_status_explicit"):
                    existing["status"] = _infer_foreshadow_status(
                        {"status": item.get("status", "")},
                        preserve_manual=False,
                    )
                continue
            if key == "foreshadows" and field == "_status_explicit":
                if item.get("_status_explicit"):
                    existing["_status_explicit"] = True
                continue
            old = str(existing.get(field, "") or "").strip()
            new = str(item.get(field, "") or "").strip()
            if not new:
                continue
            if not old:
                existing[field] = new
            elif new == old or new in old:
                continue
            elif old in new:
                existing[field] = new
            elif field in append_fields:
                existing[field] = f"{old}\n补充：{new}"

    def _merge_analysis_result(self, output, data, source_label=""):
        data = _normalize_ai_candidates(data)
        source_label = str(source_label or "").strip()
        if source_label:
            for group_key in ("characters", "lore", "foreshadows"):
                for item in data.get(group_key, []) if isinstance(data.get(group_key, []), list) else []:
                    if isinstance(item, dict) and not str(item.get("_source_label", "") or "").strip():
                        item["_source_label"] = source_label
        output.setdefault("project_materials", {})
        for item in data.get("characters", []) if isinstance(data.get("characters", []), list) else []:
            self._merge_candidate_group(
                output,
                "characters",
                item,
                ("role", "goal", "secret", "voice", "notes"),
                append_fields=("notes",),
            )
        for item in data.get("lore", []) if isinstance(data.get("lore", []), list) else []:
            self._merge_candidate_group(
                output,
                "lore",
                item,
                ("type", "description"),
                append_fields=("description",),
            )
        materials = data.get("project_materials", {})
        if isinstance(materials, dict):
            target = output.setdefault("project_materials", {})
            for key in ("bible", "world_rules", "timeline", "summary"):
                old = str(target.get(key, "") or "").strip()
                new = str(materials.get(key, "") or "").strip()
                if not new:
                    continue
                if not old:
                    target[key] = new
                elif new == old or new in old:
                    continue
                elif old in new:
                    target[key] = new
                else:
                    target[key] = f"{old}\n\n补充：{new}"
        for item in data.get("foreshadows", []) if isinstance(data.get("foreshadows", []), list) else []:
            self._merge_candidate_group(
                output,
                "foreshadows",
                item,
                ("status", "setup_chapter", "payoff_chapter", "description"),
                append_fields=("description",),
            )

    def run(self):
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            chunk_records = deepcopy(self.input_chunk_records)
            text = self.text.strip()
            if not chunk_records:
                if not text:
                    raise Exception("没有可分析的正文。")
                chunks = self._split_text_chunks(text)
                chunk_records = [
                    {"text": chunk, "index": index, "total": len(chunks)}
                    for index, chunk in enumerate(chunks, 1)
                ]
            chunks = [record.get("text", "") for record in chunk_records]
            if not chunks:
                raise Exception("没有可分析的正文。")
            total = len(chunks)
            prompt = self._analysis_prompt()
            merged = {"characters": [], "lore": [], "foreshadows": [], "project_materials": {}}
            succeeded = 0
            processed = 0
            failed_chunks = []
            self.progress.emit(f"正在分块分析候选：共 {total} 块，并发 {self.max_concurrency}...")

            def submit_chunk(executor, index):
                record = chunk_records[index - 1]
                chunk = record.get("text", "")
                label = record.get("index", index)
                label_total = record.get("total", total) or total
                response_format_supported, _stream_supported = self._analysis_request_capabilities()
                return executor.submit(
                    self._analyze_chunk_with_retries,
                    prompt,
                    chunk,
                    label,
                    label_total,
                    response_format_supported,
                )

            with ThreadPoolExecutor(max_workers=max(1, int(self.max_concurrency or 1))) as executor:
                futures = {}
                next_index = 1
                while next_index <= total and len(futures) < self.max_concurrency:
                    futures[submit_chunk(executor, next_index)] = next_index
                    next_index += 1

                while futures:
                    if self._stop_requested or self.isInterruptionRequested():
                        for future in futures:
                            future.cancel()
                        return
                    done, _ = wait(list(futures.keys()), timeout=0.2, return_when=FIRST_COMPLETED)
                    if not done:
                        continue
                    for future in done:
                        index = futures.pop(future, None)
                        if index is None:
                            continue
                        try:
                            parsed, _response_format = future.result()
                        except Exception as e:
                            record = chunk_records[index - 1]
                            failed_chunks.append({
                                "index": record.get("index", index),
                                "total": record.get("total", total) or total,
                                "text": record.get("text", chunks[index - 1]),
                                "error": str(e),
                            })
                            processed += 1
                            partial = deepcopy(merged)
                            partial["_failed_chunks"] = deepcopy(failed_chunks)
                            partial["_chunk_total"] = total
                            partial["_chunk_succeeded"] = succeeded
                            self.partial_ready.emit(partial, processed, total)
                            error_preview = str(e).replace("\n", " ").strip()
                            if len(error_preview) > 160:
                                error_preview = error_preview[:160] + "..."
                            self.progress.emit(f"第 {index}/{total} 块分析失败：{error_preview}；已保留为待重试。")
                        else:
                            record = chunk_records[index - 1]
                            label = record.get("index", index)
                            label_total = record.get("total", total) or total
                            source_label = f"第 {label}/{label_total} 块"
                            self._merge_analysis_result(merged, parsed, source_label=source_label)
                            succeeded += 1
                            processed += 1
                            partial = deepcopy(merged)
                            partial["_failed_chunks"] = deepcopy(failed_chunks)
                            partial["_chunk_total"] = total
                            partial["_chunk_succeeded"] = succeeded
                            self.partial_ready.emit(partial, processed, total)
                            material_hits = sum(
                                1
                                for value in merged.get("project_materials", {}).values()
                                if str(value or "").strip()
                            )
                            self.progress.emit(
                                f"已处理 {processed}/{total}，成功 {succeeded} 块：人物 {len(merged['characters'])}，设定 {len(merged['lore'])}，伏笔 {len(merged['foreshadows'])}，资料草案 {material_hits}"
                            )
                        if next_index <= total:
                            futures[submit_chunk(executor, next_index)] = next_index
                            next_index += 1
            merged["_failed_chunks"] = failed_chunks
            merged["_chunk_total"] = total
            merged["_chunk_succeeded"] = succeeded
            self.result_ready.emit(merged)
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self.failed.emit(str(e))
        finally:
            self._close_active_network_handles()


class NovelWritingWorker(QThread):
    chunk = Signal(str)
    result_ready = Signal(str, str)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, base_url, api_key, model, action, context, proxy_url="", proxy_mode="不使用代理"):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.action = str(action or "")
        self.context = str(context or "")
        self.proxy_url = str(proxy_url or "").strip()
        self.proxy_mode = str(proxy_mode or "不使用代理").strip()
        self._session = requests.Session()
        self._session.trust_env = False
        self._stop_requested = False
        self._response = None

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        self._close_network_handles()

    def _close_network_handles(self):
        try:
            if self._response is not None:
                self._response.close()
        except Exception:
            pass
        finally:
            self._response = None
        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass

    def _proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def _draft_word_target(self):
        if self.action != "draft":
            return 0
        match = re.search(r"本次新增正文(?:参考)?目标：\s*约?\s*(\d{1,7})\s*字", self.context)
        if not match:
            match = re.search(r"本章扩写字数：\s*(\d{2,7})\s*字", self.context)
        if not match:
            return 0
        try:
            value = int(match.group(1))
        except Exception:
            return 0
        return value if value > 0 else 0

    def _max_tokens_for_request(self):
        if self.action == "outline":
            return 1200
        if self.action == "summary":
            return 1200
        return 0

    def _initial_progress_text(self):
        return {
            "draft": "正在扩写正文...",
            "outline": "正在生成章节提纲...",
            "summary": "正在提炼摘要/关键事实...",
            "script_to_novel": "正在改编为小说正文...",
            "novel_to_script": "正在改编为剧本...",
            "novel_to_storyboard": "正在生成分镜脚本...",
            "script_to_storyboard": "正在生成分镜脚本...",
        }.get(self.action, "正在请求 AI 写作助手...")

    def _editorial_quality_prompt(self):
        fiction_actions = {"draft", "script_to_novel"}
        outline_actions = {"outline"}
        summary_actions = {"summary"}
        adaptation_actions = {"novel_to_script", "novel_to_storyboard", "script_to_storyboard"}
        if self.action not in fiction_actions | outline_actions | summary_actions | adaptation_actions:
            return ""

        common = (
            "\n\n【统一创作与编辑标准】\n"
            "请以成熟的商业小说作者兼责任编辑标准完成本次任务，输出内容要达到可直接交付人工编辑审阅的稳定度。"
            "读起来应自然、连贯、有个人声音；不追求炫技，追求真实推进、人物行为合理、情绪有层次。"
            "信息要通过行动、对话、环境和细节自然出现，少用直接解释。"
            "每个角色都要有不同的说话方式、反应节奏和关注点。"
            "允许局部留白、轻微笨拙和不完全对称的句式，但整体必须成熟。"
            "先确定本次任务的唯一核心事件与情绪曲线，再明确每个角色的动机、阻力和转折，"
            "并检查人物、设定、时间线、伏笔、空间关系和因果链是否一致。"
        )
        if self.action in fiction_actions:
            return common + (
                "\n正文写作要求：中段必须出现一次意料之外但符合逻辑的小变化；"
                "至少写出 3 处具体可见细节、1 处声音或触感细节、1 处动作细节。"
                "对话要有潜台词，避免角色互相解释已经知道的事。"
                "不要写摘要式过场、百科式设定说明、空泛金句、重复句式、同义反复或模板化转折词堆叠。"
                "结尾要来自冲突本身，留下继续读下去的张力。"
                "如果资料提供本章扩写字数，只把它当作节奏和详略参考；优先保证完整小场景、冲突收束和正文质量，"
                "不要为了贴字数截断或省略关键结尾。"
            )
        if self.action in outline_actions:
            return common + (
                "\n提纲要求：输出短提纲，不写正文、不写对白、不写场景描写。"
                "控制在 6-10 条以内，每条 1-2 句；总长度尽量控制在 600-1200 字。"
                "只保留本章核心事件、情绪曲线、角色动机、阻力、小变化、关键细节、冲突收束点和结尾张力。"
                "如果资料里已有正文草稿，只反向整理正文已经发生的内容；不要补写正文没有出现的结尾、下一步计划或伏笔兑现。"
                "不要把资料复述成长篇分析，不要写空泛创作建议。"
            )
        if self.action in summary_actions:
            return common + (
                "\n摘要要求：只提炼已经在正文中发生、后续必须继承的事实。"
                "语言短而明确，不评价、不解释创作意图，不新增正文里没有发生的设定或伏笔。"
                "本章摘要保持简短，关键事实按完整事实逐条写；只保留会影响后文续写的变化。"
                "不要为了固定句数或条数删掉人物关系、伤势、物品、地点、线索、伏笔状态等必须继承的信息。"
            )
        return common + (
            "\n改编要求：保留原内容的核心事件、情绪推进、人物动机、空间关系和因果链；"
            "让不同角色保持可区分的说话方式和反应节奏。"
            "不要写摘要式过场、百科式设定说明、空泛金句或创作建议；输出必须符合当前改编格式。"
        )

    def _action_prompt(self):
        prompts = {
            "outline": (
                "你是长篇小说章节策划助手。请基于资料为当前章节生成可直接使用的章节提纲。\n"
                "要求：分成 6-10 个短剧情拍点，每条 1-2 句；"
                "写清本章目标、冲突、转折、情绪变化、结尾钩子；"
                "优先继承资料中的时间线、前文继承摘要、人物目标和关键事实；"
                "如果资料里已有正文草稿，提纲必须只概括正文已经写出来的内容，"
                "不要根据原提纲、后续规划或常规叙事补出正文没有发生的收尾、反转、下一步计划或伏笔兑现；"
                "总长度尽量控制在 600-1200 字，不要写正文、对白或长段场景描写。"
            ),
            "draft": (
                "你是长篇小说正文起草助手。请基于资料扩写当前章节正文草稿。\n"
                "要求：优先参考当前章节提纲，并结合已有正文草稿续写或补强；"
                "如果资料里已有正文草稿，只输出接在草稿末尾的新正文，不要重复、概括或重写已有正文；"
                "如果正文草稿为空，输出完整正文草稿；"
                "看到【续写承接点】时，优先从承接点的最后情绪、动作、场景和悬念自然接上；"
                "严格继承资料中的关键事实、时间线、人物目标、语言风格、伏笔状态和世界规则；"
                "只有【本章相关伏笔】里被本章标题、提纲或正文目标命中的伏笔，才可以在本章推进或回收；"
                "【开放伏笔队列】只用于提醒不要遗忘，除非当前章节明确安排，否则不要提前兑现或解释队列里的伏笔；"
                "参考【长篇进度 / 节奏】控制本章推进密度，避免开篇过早揭底、中段原地反复、后段新增大坑；"
                "参考【本章写作长度】里的本次新增正文目标安排详略，它是质量优先的参考目标，不是硬性字数要求；"
                "优先保证完整小场景、冲突收束和正文质量，不要为了贴字数截断或省略关键结尾；"
                "多用动作和对话推进，不要写解释性分析。"
                "只输出正文草稿，不输出标题、说明、分析或创作建议。"
            ),
            "summary": (
                "你是长篇小说连续性编辑。请基于当前章节正文提炼本章摘要。\n"
                "要求：同时参考当前章节提纲和正文草稿；记录已经发生且后续必须继承的事实，"
                "包括人物关系、线索、伏笔、伤势、物品、地点变化和情绪关系变化；不要评价。"
                "本章摘要保持简短，只概括核心事件和情绪转折。"
                "关键事实逐条写，每条只写一个可继承事实，删掉背景解释、重复信息和创作建议；"
                "条数不固定，重要连续性事实必须保留，不要为了压缩删掉会影响后文的变化。"
                "请严格输出三段：本章摘要：...；本章需继承的关键事实：...；"
                "本章关联人物：人物A、人物B（只列本章实际出现或被直接推动的人物；优先使用人物卡里的具体姓名，不要只写主角/反派/配角；没有则写无）"
            ),
            "script_to_novel": (
                "你是专业小说改编编辑。请把剧本改编成小说正文。\n"
                "要求：保留剧情、人物关系、关键对白和情绪推进；把场景、动作、对白转为自然叙事；"
                "输出可直接阅读的正文，不要输出说明、分析或创作建议。"
            ),
            "novel_to_script": (
                "你是专业影视剧本改编编辑。请把小说正文改编成可拍摄剧本。\n"
                "要求：按场景组织，写清场景、人物、动作和对白；保留关键剧情和人物动机；"
                "不要输出小说叙述腔、说明、分析或创作建议。"
            ),
            "novel_to_storyboard": (
                "你是专业分镜脚本设计师。请把小说正文改编成分镜脚本。\n"
                "要求：按镜号输出，包含景别、画面、动作、镜头运动、对白/旁白、音效/音乐、时长建议；"
                "保留剧情逻辑和关键情绪，不要输出说明、分析或创作建议。"
            ),
            "script_to_storyboard": (
                "你是专业分镜脚本设计师。请把剧本改编成分镜脚本。\n"
                "要求：按镜号输出，包含景别、画面、动作、镜头运动、对白/旁白、音效/音乐、时长建议；"
                "严格继承原剧本的场景、对白、动作和节奏，不要输出说明、分析或创作建议。"
            ),
        }
        prompt = prompts.get(self.action, prompts["outline"])
        return prompt + self._editorial_quality_prompt()

    def run(self):
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if not self.context.strip():
                raise Exception("没有可用的章节资料。")

            self.progress.emit(self._initial_progress_text())
            url = api_url(self.base_url, "/v1/chat/completions")
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": self._action_prompt()},
                    {"role": "user", "content": self.context[:60000]},
                ],
                "temperature": 0.65 if self.action in ("draft", "script_to_novel") else 0.35,
                "stream": True,
            }
            max_tokens = self._max_tokens_for_request()
            if max_tokens:
                payload["max_tokens"] = max_tokens
            r = self._session.post(
                url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=(10, 180),
                proxies=self._proxies(),
            )
            self._response = r
            if r.status_code >= 400:
                raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")

            full = ""
            finish_reason = ""
            r.encoding = "utf-8"
            for raw_line in r.iter_lines(decode_unicode=False):
                if self._stop_requested or self.isInterruptionRequested():
                    break
                if not raw_line:
                    continue
                try:
                    line = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    line = raw_line.decode("utf-8", errors="replace")
                line = line.strip()
                if not line.startswith("data:"):
                    continue
                data_str = line[5:].strip()
                if data_str == "[DONE]":
                    break
                try:
                    data = json.loads(data_str)
                except Exception:
                    continue
                if isinstance(data.get("error"), dict):
                    raise Exception(data["error"].get("message") or json.dumps(data["error"], ensure_ascii=False))
                if isinstance(data.get("error"), str) and data.get("error"):
                    raise Exception(data.get("error"))
                choices = data.get("choices") or []
                if not choices:
                    continue
                choice = choices[0] or {}
                if choice.get("finish_reason"):
                    finish_reason = str(choice.get("finish_reason") or "")
                delta = choice.get("delta") or {}
                message = choice.get("message") or {}
                piece = (
                    delta.get("content")
                    or delta.get("reasoning_content")
                    or delta.get("reasoning")
                    or delta.get("text")
                    or message.get("content")
                    or choice.get("text")
                )
                if piece:
                    full += piece
                    self.chunk.emit(piece)

            content = full.strip()
            if not content:
                if self._stop_requested or self.isInterruptionRequested():
                    self.result_ready.emit(self.action, "")
                    return
                reason_text = f" finish_reason={finish_reason}" if finish_reason else ""
                raise Exception(f"AI 没有返回有效内容。{reason_text}".strip())
            self.result_ready.emit(self.action, content)
        except Exception as e:
            if self._stop_requested or self.isInterruptionRequested():
                self.result_ready.emit(self.action, "")
            else:
                self.failed.emit(str(e))
        finally:
            self._close_network_handles()


class EdgeTTSWorker(QThread):
    result_ready = Signal(str)
    failed = Signal(str)
    progress = Signal(str)

    def __init__(self, text, output_path, voice="zh-CN-XiaoxiaoNeural", rate="+0%"):
        super().__init__()
        self.text = str(text or "")
        self.output_path = str(output_path or "")
        self.voice = str(voice or "zh-CN-XiaoxiaoNeural")
        self.rate = str(rate or "+0%")

    async def _save_audio(self):
        import edge_tts

        communicate = edge_tts.Communicate(self.text, self.voice, rate=self.rate)
        await communicate.save(self.output_path)

    def run(self):
        try:
            if not self.text.strip():
                raise Exception("没有可朗读的文本。")
            if not self.output_path:
                raise Exception("没有可用的音频临时路径。")
            self.progress.emit("正在生成 Edge TTS 语音...")
            asyncio.run(self._save_audio())
            if not os.path.exists(self.output_path) or os.path.getsize(self.output_path) <= 0:
                raise Exception("Edge TTS 没有生成有效音频。")
            self.result_ready.emit(self.output_path)
        except ModuleNotFoundError:
            self.failed.emit("缺少 edge-tts 依赖，请先安装 edge-tts。")
        except Exception as e:
            self.failed.emit(str(e))


class ImageWorker(QThread):
    progress = Signal(str)
    result_ready = Signal(dict)
    failed = Signal(str)
    REQUEST_TIMEOUT = 600

    SIZE_MAP = {
        "自动": "auto",
        "4096*4096": "4096x4096",
        "3840*3840（4K）": "3840x3840",
        "3840*2160（横屏4K）": "3840x2160",
        "3840*1920（2:1 4K）": "3840x1920",
        "2160*3840（竖屏4K）": "2160x3840",
        "2880*2880": "2880x2880",
        "2048*2048": "2048x2048",
        "2560*1440": "2560x1440",
        "2048*1024": "2048x1024",
        "1024*1536（竖屏）": "1024x1536",
        "1536*1024（横屏）": "1536x1024",
        "1024*1024": "1024x1024",
    }
    QUALITY_MAP = {"自动": "auto", "低": "low", "中": "medium", "高": "high"}

    def __init__(self, base_url, api_key, model, size, quality, n, prompt, refs, proxy_url="", upload_optimization="高质量", proxy_mode="仅下载图片"):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.size = size
        self.quality = quality
        self.n = n
        self.prompt = prompt
        self.refs = list(refs or [])
        self.proxy_url = str(proxy_url or "").strip()
        self.upload_optimization = str(upload_optimization or "高质量").strip()
        self.proxy_mode = str(proxy_mode or "仅下载图片").strip()
        self._stop_requested = False
        self._session = requests.Session()
        self._session.trust_env = False
        self._response = None

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        self._close_network_handles()

    def _close_network_handles(self):
        try:
            if self._response is not None:
                self._response.close()
        except Exception:
            pass
        finally:
            self._response = None

        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass
        finally:
            self._session = None

    def _raise_if_stopped(self):
        if self._stop_requested or self.isInterruptionRequested():
            raise Exception("任务已中止")

    def _submit_proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def _download_proxies(self):
        if self.proxy_mode in ("仅下载图片", "提交和下载"):
            return requests_proxies(self.proxy_url)
        return None

    def _request(self, method, url, **kwargs):
        """
        图片生成请求必须显式控制代理。
        requests 在 macOS 上可能读取系统代理；这里关闭 trust_env，避免“仅下载图片”
        模式下提交接口仍被系统代理接管。
        """
        self._raise_if_stopped()
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        self._response = self._session.request(method, url, **kwargs)
        self._raise_if_stopped()
        return self._response

    def _response_format_not_supported(self, resp):
        if resp is None or resp.status_code != 400:
            return False
        text = safe_response_text(resp).lower()
        return (
            "response_format" in text
            and (
                "not supported" in text
                or "unsupported" in text
                or "unsupportedparamserror" in text
                or "drop_params" in text
                or ("invalid" in text and "url" in text)
            )
        )

    def _post_json_image_request(self, url, headers, payload):
        return self._request(
            "POST",
            url,
            headers={**headers, "Content-Type": "application/json"},
            json=payload,
            timeout=self.REQUEST_TIMEOUT,
            proxies=self._submit_proxies(),
        )

    def _post_multipart_image_request(self, url, headers, data):
        files = []
        opened = []
        temp_paths = []
        try:
            for p in self.refs:
                self._raise_if_stopped()
                upload_path, mime, cleanup, message = prepare_image_upload_file(p, self.upload_optimization)
                if message:
                    self.progress.emit(f"已压缩参考图上传副本：{message}")
                if cleanup:
                    temp_paths.append(upload_path)
                f = open(upload_path, "rb")
                opened.append(f)
                files.append(("image[]", (os.path.basename(upload_path), f, mime)))
            return self._request(
                "POST",
                url,
                headers=headers,
                data=data,
                files=files,
                timeout=self.REQUEST_TIMEOUT,
                proxies=self._submit_proxies(),
            )
        finally:
            for f in opened:
                try:
                    f.close()
                except Exception:
                    pass
            for path in temp_paths:
                safe_remove_file(path)

    def _post_with_response_format_fallback(self, post_func, payload_or_data):
        first = post_func(payload_or_data)
        if not self._response_format_not_supported(first):
            return first

        try:
            first.close()
        except Exception:
            pass

        retry_payload = dict(payload_or_data)
        current_format = retry_payload.get("response_format")
        if current_format == "url":
            retry_payload["response_format"] = "b64_json"
            self.progress.emit("接口不支持 URL 返回，已自动改用 b64_json 重试...")
            second = post_func(retry_payload)
            if not self._response_format_not_supported(second):
                return second
            try:
                second.close()
            except Exception:
                pass

        retry_payload.pop("response_format", None)
        self.progress.emit("接口不支持 response_format，已自动移除该参数重试...")
        return post_func(retry_payload)

    def _is_agnes_image_21_flash(self):
        model = str(self.model or "").strip().lower()
        base_url = str(self.base_url or "").strip().lower()
        return "agnes-image-2.1-flash" in model or "apihub.agnes-ai.com" in base_url

    def _agnes_ref_to_data_uri_or_url(self, ref):
        text = str(ref or "").strip()
        if not text:
            return ""
        if text.startswith(("http://", "https://")):
            return text
        if text.lower().startswith("data:image/") and "base64," in text.lower():
            return text
        if not os.path.exists(text):
            return ""

        upload_path, mime, cleanup, message = prepare_image_upload_file(text, self.upload_optimization)
        try:
            if message:
                self.progress.emit(f"已压缩参考图上传副本：{message}")
            b64 = image_file_to_base64(upload_path)
            mime = mime or mimetypes.guess_type(upload_path or "")[0] or "image/png"
            return f"data:{mime};base64,{b64}"
        finally:
            if cleanup:
                safe_remove_file(upload_path)

    def _post_agnes_image_21_flash_request(self, headers):
        url = api_url(self.base_url, "/v1/images/generations")
        payload = {
            "model": self.model,
            "prompt": self.prompt,
            "size": self.SIZE_MAP.get(self.size, "auto"),
            "extra_body": {"response_format": "url"},
        }

        try:
            count = int(self.n)
            if count > 1:
                payload["n"] = count
        except Exception:
            pass

        if self.refs:
            images = []
            for ref in self.refs:
                value = self._agnes_ref_to_data_uri_or_url(ref)
                if value:
                    images.append(value)
            if not images:
                raise Exception("图生图参考图无效。请使用本地图片、可访问的公网图片 URL，或 Data URI Base64。")
            payload["image"] = images

        first = self._post_json_image_request(url, headers, payload)
        if self.refs and first.status_code in (400, 422):
            try:
                first.close()
            except Exception:
                pass
            retry_payload = dict(payload)
            images = retry_payload.pop("image", None)
            retry_extra = dict(payload.get("extra_body") or {})
            retry_extra["image"] = images
            retry_payload["extra_body"] = retry_extra
            self.progress.emit("接口未接受顶层 image，已自动改用 extra_body.image 重试...")
            return self._post_json_image_request(url, headers, retry_payload)

        return first

    def _save_image_result_item(self, item, idx, total):
        if not isinstance(item, dict):
            return ""

        b64_text = item.get("b64_json")
        if isinstance(b64_text, str) and b64_text.strip():
            return save_base64_to_image(b64_text, ".png")

        url_text = item.get("url")
        if not url_text and isinstance(item.get("image_url"), dict):
            url_text = item.get("image_url", {}).get("url")
        if isinstance(url_text, str):
            url_text = url_text.strip()
        else:
            url_text = ""

        if url_text.lower().startswith("data:image/") and "base64," in url_text.lower():
            return save_base64_to_image(url_text, ".png")

        if url_text.startswith(("http://", "https://")):
            self.progress.emit(f"正在下载图片 {idx}/{total}...")
            self.progress.emit(f"图片下载地址：{url_text}")
            primary_proxies = self._download_proxies()
            try:
                img_resp = self._request("GET", url_text, timeout=self.REQUEST_TIMEOUT, proxies=primary_proxies)
            except Exception as e:
                fallback_proxies = None if primary_proxies else requests_proxies(self.proxy_url)
                if fallback_proxies != primary_proxies:
                    try:
                        self.progress.emit("首次下载失败，正在切换代理策略重试下载...")
                        img_resp = self._request("GET", url_text, timeout=self.REQUEST_TIMEOUT, proxies=fallback_proxies)
                    except Exception as retry_e:
                        raise Exception(
                            f"图片已生成，但下载失败：{retry_e}\n"
                            f"首次错误：{e}\n下载地址：{url_text}\n"
                            f"可复制该地址到浏览器或下载工具重试。"
                        )
                else:
                    raise Exception(f"图片已生成，但下载失败：{e}\n下载地址：{url_text}\n可复制该地址到浏览器或下载工具重试。")
            try:
                img_resp.raise_for_status()
                suffix = image_suffix_from_content_type(img_resp.headers.get("Content-Type"))
                suffix = image_suffix_from_bytes(img_resp.content, suffix)
                return save_bytes_to_image(img_resp.content, suffix)
            except Exception as e:
                raise Exception(f"图片已生成，但保存下载内容失败：{e}\n下载地址：{url_text}\n可复制该地址到浏览器或下载工具重试。")
            finally:
                try:
                    img_resp.close()
                except Exception:
                    pass

        return ""

    def _post_image_request(self, headers):
        if self._is_agnes_image_21_flash():
            return self._post_agnes_image_21_flash_request(headers)

        if not self.refs:
            url = api_url(self.base_url, "/v1/images/generations")
            payload = {
                "model": self.model,
                "prompt": self.prompt,
                "n": int(self.n),
                "size": self.SIZE_MAP.get(self.size, "auto"),
                "quality": self.QUALITY_MAP.get(self.quality, "auto"),
                "response_format": "url",
            }
            return self._post_with_response_format_fallback(
                lambda data: self._post_json_image_request(url, headers, data),
                payload,
            )

        url = api_url(self.base_url, "/v1/images/edits")
        data = {
            "model": self.model,
            "prompt": self.prompt,
            "n": str(int(self.n)),
            "size": self.SIZE_MAP.get(self.size, "auto"),
            "quality": self.QUALITY_MAP.get(self.quality, "auto"),
            "response_format": "url",
        }
        return self._post_with_response_format_fallback(
            lambda form_data: self._post_multipart_image_request(url, headers, form_data),
            data,
        )

    def run(self):
        try:
            if not self.base_url or not self.api_key:
                raise Exception("请先在设置中添加并选择厂商。")

            headers = {"Authorization": f"Bearer {self.api_key}"}
            self.progress.emit("正在提交任务...")
            if self._submit_proxies():
                self.progress.emit("提交请求代理：已启用")
            else:
                self.progress.emit("提交请求代理：未启用")

            r = self._post_image_request(headers)
            self._raise_if_stopped()

            if r.status_code >= 400:
                raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")

            self.progress.emit("正在解析图片结果...")
            resp = r.json()
            try:
                r.close()
            except Exception:
                pass

            images = []
            data_items = resp.get("data", [])
            if not isinstance(data_items, list):
                data_items = []

            for idx, item in enumerate(data_items, start=1):
                self._raise_if_stopped()
                if not isinstance(item, dict):
                    continue

                saved_path = self._save_image_result_item(item, idx, len(data_items))
                if saved_path:
                    images.append(saved_path)

                try:
                    item["b64_json"] = ""
                    if isinstance(item.get("url"), str) and item.get("url", "").startswith("data:image/"):
                        item["url"] = ""
                except Exception:
                    pass

            try:
                resp.clear()
                data_items.clear()
                del resp
                del data_items
                gc.collect()
            except Exception:
                pass

            if not images:
                raise Exception("接口没有返回图片。请检查中转接口返回格式。")

            self.progress.emit("正在加入图片预览区...")

            self.result_ready.emit({
                "time": now_str(),
                "prompt": self.prompt,
                "refs": list(self.refs or []),
                "images": images,
                "model": self.model,
                "size": self.size,
                "quality": self.quality,
                "n": self.n,
            })
        except Exception as e:
            if self._stop_requested or self.isInterruptionRequested():
                self.failed.emit("任务已中止")
            else:
                self.failed.emit(str(e))
        finally:
            self._close_network_handles()


class ThumbnailWorker(QThread):
    thumbnail_ready = Signal(str, str)
    finished_path = Signal(str)

    def __init__(self, paths, width=210, height=210):
        super().__init__()
        self.paths = list(paths or [])
        self.width = int(width)
        self.height = int(height)

    def run(self):
        seen = set()
        for path in self.paths:
            if not isinstance(path, str) or path in seen:
                continue
            seen.add(path)
            try:
                cache_path = ensure_thumbnail_cache(path, self.width, self.height)
                if cache_path:
                    self.thumbnail_ready.emit(path, cache_path)
            except Exception:
                pass

        for path in seen:
            try:
                self.finished_path.emit(path)
            except Exception:
                pass


class VideoWorker(QThread):
    progress = Signal(str)
    result_ready = Signal(dict)
    failed = Signal(str)

    DONE_STATUSES = {"completed", "succeeded", "success", "done", "finished"}
    FAILED_STATUSES = {"failed", "error", "cancelled", "canceled", "timeout"}
    VIDEO_QUERY_MIN_INTERVAL = 8
    _video_query_lock = threading.Lock()
    _last_video_query_at = 0.0

    def __init__(self, base_url, api_key, model, prompt, width, height, num_frames, frame_rate, image_refs=None, proxy_url="", proxy_mode="仅下载图片"):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.prompt = prompt
        self.width = int(width)
        self.height = int(height)
        self.num_frames = int(num_frames)
        self.frame_rate = int(frame_rate)
        self.image_refs = [str(x).strip() for x in (image_refs or []) if str(x).strip()]
        self.proxy_url = str(proxy_url or "").strip()
        self.proxy_mode = str(proxy_mode or "仅下载图片").strip()
        self._stop_requested = False
        self._session = requests.Session()
        self._session.trust_env = False
        self._response = None

    def stop(self):
        self._stop_requested = True
        try:
            self.requestInterruption()
        except Exception:
            pass
        self._close_network_handles()

    def _close_network_handles(self):
        try:
            if self._response is not None:
                self._response.close()
        except Exception:
            pass
        finally:
            self._response = None
        try:
            if self._session is not None:
                self._session.close()
        except Exception:
            pass

    def _raise_if_stopped(self):
        if self._stop_requested or self.isInterruptionRequested():
            raise Exception("任务已中止")

    def _sleep_with_stop(self, seconds):
        end_time = time.monotonic() + max(0, float(seconds or 0))
        while True:
            self._raise_if_stopped()
            remaining = end_time - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(0.2, remaining))

    def _wait_for_video_query_slot(self):
        while True:
            self._raise_if_stopped()
            with VideoWorker._video_query_lock:
                now = time.monotonic()
                wait = VideoWorker._last_video_query_at + VideoWorker.VIDEO_QUERY_MIN_INTERVAL - now
                if wait <= 0:
                    VideoWorker._last_video_query_at = now
                    return
            self._sleep_with_stop(min(wait, 1))

    def _submit_proxies(self):
        if self.proxy_mode == "提交和下载":
            return requests_proxies(self.proxy_url)
        return None

    def _download_proxies(self):
        if self.proxy_mode in ("仅下载图片", "提交和下载"):
            return requests_proxies(self.proxy_url)
        return None

    def _request(self, method, url, **kwargs):
        self._raise_if_stopped()
        if self._session is None:
            self._session = requests.Session()
            self._session.trust_env = False
        self._response = self._session.request(method, url, **kwargs)
        self._raise_if_stopped()
        return self._response

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

    def _extract_dict(self, data):
        if isinstance(data, dict):
            inner = data.get("data")
            if isinstance(inner, dict):
                return inner
            return data
        return {}

    def _extract_video_id(self, data):
        found = []

        def collect(obj):
            if isinstance(obj, dict):
                value = obj.get("video_id")
                if value:
                    found.append(str(value))
                    return
                for key in ("data", "output", "result"):
                    collect(obj.get(key))
            elif isinstance(obj, list):
                for item in obj:
                    collect(item)

        collect(data)
        if found:
            return found[0]
        return ""

    def _extract_status(self, data):
        obj = self._extract_dict(data)
        value = obj.get("status") or obj.get("state")
        return str(value or "").strip().lower()

    def _extract_error(self, data):
        obj = self._extract_dict(data)
        err = obj.get("error") or obj.get("message") or obj.get("fail_reason") or obj.get("reason")
        if isinstance(err, dict):
            return err.get("message") or json.dumps(err, ensure_ascii=False)
        return str(err or "").strip()

    def _extract_video_url(self, data):
        candidates = []

        def collect(obj):
            if isinstance(obj, dict):
                for key in (
                    "video_url",
                    "videoUrl",
                    "url",
                    "output_url",
                    "download_url",
                    "file_url",
                    "media_url",
                    "result_url",
                    "output_video_url",
                    "remixed_from_video_id",
                ):
                    value = obj.get(key)
                    if isinstance(value, str) and value.strip():
                        candidates.append(value.strip())
                for key in ("data", "output", "outputs", "videos", "result"):
                    collect(obj.get(key))
            elif isinstance(obj, list):
                for item in obj:
                    collect(item)
            elif isinstance(obj, str) and obj.strip().startswith(("http://", "https://")):
                candidates.append(obj.strip())

        collect(data)
        for value in candidates:
            if value.startswith(("http://", "https://")):
                return value
        return candidates[0] if candidates else ""

    def _create_task(self):
        payload = {
            "model": self.model,
            "prompt": self.prompt,
            "width": self.width,
            "height": self.height,
            "num_frames": self.num_frames,
            "frame_rate": self.frame_rate,
        }
        images = self._video_image_values()
        if len(images) == 1:
            payload["image"] = images[0]
        elif len(images) > 1:
            payload["extra_body"] = {"image": images}

        r = self._request(
            "POST",
            api_url(self.base_url, "/v1/videos"),
            headers=self._headers(),
            json=payload,
            timeout=(30, 120),
            proxies=self._submit_proxies(),
        )
        try:
            if r.status_code >= 400:
                raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")
            return r.json()
        finally:
            try:
                r.close()
            except Exception:
                pass

    def _video_image_values(self):
        values = []
        for ref in self.image_refs:
            self._raise_if_stopped()
            if ref.startswith(("http://", "https://")):
                values.append(ref)
                continue

            if os.path.exists(ref):
                mime = mimetypes.guess_type(ref)[0] or ""
                if not mime.startswith("image/"):
                    raise Exception(f"参考文件不是图片：{os.path.basename(ref)}")
                values.append(image_file_to_base64(ref))
                continue

            cleaned = ref
            if cleaned.lower().startswith("data:image/") and "base64," in cleaned.lower():
                cleaned = cleaned.split(",", 1)[1].strip()
            if cleaned:
                values.append(cleaned)
                continue

            raise Exception(f"参考图不存在或格式不支持：{ref}")

        return values

    def _query_video_result(self, video_id):
        url = api_url(self.base_url, "/agnesapi")
        deadline = time.time() + 60 * 30
        interval = 5
        last_status = ""
        last_progress = None
        not_ready_reported = False
        completed_without_url_count = 0

        while time.time() < deadline:
            self._raise_if_stopped()
            self._wait_for_video_query_slot()
            r = self._request(
                "GET",
                url,
                headers=self._headers(),
                params={"video_id": video_id},
                timeout=(10, 60),
                proxies=self._submit_proxies(),
            )
            wait_after_error = 0
            try:
                if r.status_code >= 400:
                    err_text = extract_api_error(r)
                    err_lower = str(err_text).lower()
                    if r.status_code == 400 and "task_not_exist" in err_lower:
                        if not not_ready_reported:
                            self.progress.emit("视频结果暂未就绪，继续查询...")
                            not_ready_reported = True
                        wait_after_error = interval
                    elif r.status_code == 429 or "rate limit" in err_lower:
                        retry_after = 0
                        try:
                            retry_after = int(r.headers.get("Retry-After", "0") or 0)
                        except Exception:
                            retry_after = 0
                        interval = min(60, max(15, interval * 2, retry_after))
                        self.progress.emit(f"视频状态查询触发限流，已降频等待 {interval} 秒...")
                        wait_after_error = interval
                    if not wait_after_error:
                        raise Exception(f"查询视频结果失败 {r.status_code}：{err_text}")
                    data = None
                else:
                    data = r.json()
            finally:
                try:
                    r.close()
                except Exception:
                    pass
            if wait_after_error:
                self._sleep_with_stop(wait_after_error)
                continue

            video_url = self._extract_video_url(data)
            status = self._extract_status(data)
            obj = self._extract_dict(data)
            progress = obj.get("progress") if isinstance(obj, dict) else None
            if status != last_status or progress != last_progress:
                if progress is not None:
                    self.progress.emit(f"视频生成状态：{status or '处理中'}，进度 {progress}%")
                elif status:
                    self.progress.emit(f"视频生成状态：{status}")
                last_status = status
                last_progress = progress

            if video_url and (not status or status in self.DONE_STATUSES):
                return data

            if status in self.DONE_STATUSES:
                completed_without_url_count += 1
                if completed_without_url_count >= 6:
                    keys = []
                    try:
                        obj_keys = list(obj.keys()) if isinstance(obj, dict) else []
                        keys = obj_keys[:12]
                    except Exception:
                        keys = []
                    raise Exception(f"视频已完成，但接口没有返回可下载视频地址。返回字段：{keys}")

            if status in self.FAILED_STATUSES:
                detail = self._extract_error(data)
                raise Exception(detail or f"视频生成失败：{status}")

            self._sleep_with_stop(interval)

        raise Exception("视频结果查询超时。")

    def _download_video(self, video_url):
        if not video_url.startswith(("http://", "https://")):
            raise Exception("接口返回的视频地址不是可下载 URL。")
        self.progress.emit("正在下载视频...")
        r = self._request(
            "GET",
            video_url,
            stream=True,
            timeout=(10, 900),
            proxies=self._download_proxies(),
        )
        try:
            r.raise_for_status()
            day = datetime.now().strftime("%Y-%m-%d")
            video_dir = os.path.join(VIDEO_DIR, day)
            os.makedirs(video_dir, exist_ok=True)
            name = f"{uuid.uuid4().hex}.mp4"
            path = os.path.join(video_dir, name)
            with open(path, "wb") as f:
                for chunk in r.iter_content(chunk_size=1024 * 1024):
                    self._raise_if_stopped()
                    if chunk:
                        f.write(chunk)
            if not os.path.exists(path) or os.path.getsize(path) <= 0:
                safe_remove_file(path)
                raise ValueError("视频文件保存后为空。")
            return path
        finally:
            try:
                r.close()
            except Exception:
                pass

    def run(self):
        try:
            if not self.base_url or not self.api_key:
                raise Exception("请先在设置中添加并选择厂商。")
            if not self.prompt.strip():
                raise Exception("请输入视频提示词。")

            self.progress.emit("正在创建视频任务...")
            created = self._create_task()
            video_id = self._extract_video_id(created)

            if not video_id:
                raise Exception("接口没有返回 video_id，当前已禁用旧 task_id 查询逻辑。")

            self.progress.emit(f"视频生成已提交：{video_id}")
            result = self._query_video_result(video_id)
            video_url = self._extract_video_url(result)

            if not video_url:
                raise Exception("视频生成完成，但接口没有返回 video_url。")

            local_path = self._download_video(video_url)
            self.result_ready.emit({
                "time": now_str(),
                "prompt": self.prompt,
                "model": self.model,
                "width": self.width,
                "height": self.height,
                "num_frames": self.num_frames,
                "frame_rate": self.frame_rate,
                "video_id": video_id,
                "video_url": video_url,
                "video": local_path,
                "image_refs": list(self.image_refs),
            })
        except Exception as e:
            if self._stop_requested or self.isInterruptionRequested():
                self.failed.emit("任务已中止")
            else:
                self.failed.emit(str(e))
        finally:
            self._close_network_handles()
