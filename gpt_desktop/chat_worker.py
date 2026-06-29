import json

import requests
from PySide6.QtCore import QThread, Signal

from .core import (
    api_url,
    extract_api_error,
    image_file_to_base64,
    prepare_image_upload_file,
    read_uploaded_files_text,
    safe_remove_file,
)


class ChatWorker(QThread):
    chunk = Signal(str)
    result_ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, base_url, api_key, model, messages, pending_user_message=None):
        super().__init__()
        self.base_url = base_url
        self.api_key = api_key
        self.model = model
        self.messages = messages
        self.pending_user_message = pending_user_message
        self._stop_requested = False
        self._response = None
        self._session = requests.Session()

    def stop(self):
        """
        请求中止当前任务。
        重点：
        1. 设置停止标记；
        2. 关闭流式 response；
        3. 关闭 requests.Session，尽量打断还没返回响应头的请求。
        """
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

    def _build_pending_user_message(self):
        data = self.pending_user_message
        if not isinstance(data, dict):
            return None

        text = str(data.get("text", "") or "")
        uploaded_files = list(data.get("uploaded_files") or [])
        uploaded_images = list(data.get("uploaded_images") or [])

        final_text = text
        file_text = read_uploaded_files_text(uploaded_files)
        if file_text:
            final_text = (final_text + "\n\n" + file_text).strip()

        if not uploaded_images:
            return {"role": "user", "content": final_text}

        content = [{"type": "text", "text": final_text}]
        for pth in uploaded_images:
            upload_path = pth
            cleanup = False
            try:
                upload_path, mime, cleanup, message = prepare_image_upload_file(pth, "标准")
                b64 = image_file_to_base64(upload_path)
                content.append({
                    "type": "image_url",
                    "image_url": {"url": f"data:{mime};base64,{b64}"}
                })
            finally:
                try:
                    if cleanup:
                        safe_remove_file(upload_path)
                except Exception:
                    pass
        return {"role": "user", "content": content}

    def run(self):
        full = ""
        returned_model = self.model
        finish_reason = ""
        try:
            if not self.base_url or not self.api_key:
                raise Exception("请先在设置中添加并选择厂商。")

            url = api_url(self.base_url, "/v1/chat/completions")
            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            }
            messages = list(self.messages or [])
            pending_user_msg = self._build_pending_user_message()
            if pending_user_msg:
                messages.append(pending_user_msg)

            payload = {
                "model": self.model,
                "messages": messages,
                "temperature": 0.7,
                "stream": True,
            }
            # 不要用 timeout=600。
            # 单个 600 秒会导致接口卡住时很久无法释放。
            # 这里拆成：
            #   connect timeout = 10 秒
            #   read timeout    = 180 秒
            # 如果长时间没有任何流式数据，就抛出超时，避免无限“正在思考”。
            r = self._session.post(
                url,
                headers=headers,
                json=payload,
                stream=True,
                timeout=(10, 180),
            )
            self._response = r
            if r.status_code >= 400:
                raise Exception(f"接口错误 {r.status_code}：{extract_api_error(r)}")

            full = ""
            returned_model = self.model
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

                if data.get("model"):
                    returned_model = data["model"]

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

            if not full.strip() and not (self._stop_requested or self.isInterruptionRequested()):
                reason_text = f" finish_reason={finish_reason}" if finish_reason else ""
                raise Exception(f"接口没有返回可显示内容。{reason_text}".strip())

            self.result_ready.emit({
                "content": full,
                "request_model": self.model,
                "returned_model": returned_model,
                "stopped": bool(self._stop_requested or self.isInterruptionRequested()),
            })
        except Exception as e:
            if self._stop_requested or self.isInterruptionRequested():
                self.result_ready.emit({
                    "content": full,
                    "request_model": self.model,
                    "returned_model": returned_model,
                    "stopped": True,
                })
            else:
                self.failed.emit(str(e))
        finally:
            self._close_network_handles()
