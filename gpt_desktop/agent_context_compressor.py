import re


DEFAULT_CONTEXT_COMPRESSION = {
    "enabled": True,
    "trigger_tokens": 24000,
    "recent_budget_tokens": 16000,
    "summary_budget_chars": 8000,
}


def estimate_text_tokens(text):
    text = str(text or "")
    if not text:
        return 0
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    words = len(re.findall(r"[A-Za-z0-9_]+", text))
    other = max(0, len(text) - cjk - sum(len(x) for x in re.findall(r"[A-Za-z0-9_]+", text)))
    return int(cjk + words + other / 3)


def message_text(message):
    if not isinstance(message, dict):
        return ""
    content = message.get("content", "")
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text", "") or ""))
        return "\n".join(parts)
    return str(content or "")


def estimate_message_tokens(message):
    return estimate_text_tokens(message_text(message)) + 8


def estimate_messages_tokens(messages):
    return sum(estimate_message_tokens(msg) for msg in messages or [])


def _clean_line(text, limit=420):
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(text) > limit:
        return text[:limit].rstrip() + "..."
    return text


def _message_brief(message):
    role = "用户" if message.get("role") == "user" else "助手"
    text = _clean_line(message_text(message))
    return f"- {role}: {text}" if text else ""


def build_structured_summary(previous_summary, messages, budget_chars=8000):
    lines = []
    previous_summary = str(previous_summary or "").strip()
    if previous_summary:
        lines.append("【已有摘要】")
        lines.append(previous_summary)
        lines.append("")

    lines.append("【压缩的早期对话】")
    for msg in messages or []:
        if not isinstance(msg, dict) or msg.get("_local_status"):
            continue
        if msg.get("role") not in ("user", "assistant"):
            continue
        brief = _message_brief(msg)
        if brief:
            lines.append(brief)

    text = "\n".join(lines).strip()
    if len(text) > budget_chars:
        text = text[-budget_chars:].lstrip()
        text = "【较早摘要已截断，保留最近压缩内容】\n" + text
    return text


def compress_messages_for_api(messages, existing_summary="", config=None):
    cfg = dict(DEFAULT_CONTEXT_COMPRESSION)
    if isinstance(config, dict):
        cfg.update({k: v for k, v in config.items() if v is not None})

    if not cfg.get("enabled", True):
        return list(messages or []), existing_summary, False, 0

    trigger = int(cfg.get("trigger_tokens") or DEFAULT_CONTEXT_COMPRESSION["trigger_tokens"])
    recent_budget = int(cfg.get("recent_budget_tokens") or DEFAULT_CONTEXT_COMPRESSION["recent_budget_tokens"])
    summary_budget = int(cfg.get("summary_budget_chars") or DEFAULT_CONTEXT_COMPRESSION["summary_budget_chars"])

    clean_messages = list(messages or [])
    total_tokens = estimate_messages_tokens(clean_messages) + estimate_text_tokens(existing_summary)
    if total_tokens <= trigger:
        return clean_messages, existing_summary, False, total_tokens

    recent = []
    used = 0
    for msg in reversed(clean_messages):
        cost = estimate_message_tokens(msg)
        if recent and used + cost > recent_budget:
            break
        recent.append(msg)
        used += cost
    recent.reverse()

    old_count = max(0, len(clean_messages) - len(recent))
    old_messages = clean_messages[:old_count]
    summary = build_structured_summary(existing_summary, old_messages, summary_budget)

    packed = []
    if summary:
        packed.append({
            "role": "system",
            "content": (
                "以下是本会话较早内容的压缩摘要。它用于保持长期上下文，"
                "优先遵守摘要中的已定事实、用户偏好、角色设定、剧情进展和待办事项。\n\n"
                + summary
            ),
        })
    packed.extend(recent)
    return packed, summary, True, total_tokens
