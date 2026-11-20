"""Provider-neutral cache context sections for the isolated novel candidate.

The novel workflow keeps one logical context, but each protocol serializes the
stable and dynamic portions differently.  This module deliberately does not
send provider-specific cache extensions; it only preserves an exact stable
prefix and exposes diagnostics for the request builder.
"""

from __future__ import annotations

import hashlib


CACHE_CONTEXT_SCHEMA_VERSION = "novel-cache-context-v3"
CACHE_STABLE_END_MARKER = "【缓存稳定资料结束】"
CACHE_STABLE_START_MARKER = "【缓存固定资料】"
CACHE_DYNAMIC_START_MARKER = "【本轮动态资料】"


class CacheContext(str):
    """String-compatible context with transport-only cache sections.

    The visible string remains in the workflow's original order.  Protocol
    adapters can still read the stable and dynamic sections without exposing
    cache bookkeeping markers to the model or older callers.
    """

    def __new__(cls, visible_value, stable_value, dynamic_value):
        instance = str.__new__(cls, str(visible_value or ""))
        instance._cache_stable = str(stable_value or "")
        instance._cache_dynamic = str(dynamic_value or "")
        return instance


def _marked_sections(stable_value="", dynamic_value=""):
    stable = str(stable_value or "").strip()
    dynamic = str(dynamic_value or "").strip()
    if not stable:
        return "", dynamic
    marked_stable = "\n".join((CACHE_STABLE_START_MARKER, stable, CACHE_STABLE_END_MARKER))
    return marked_stable, dynamic


def build_cache_context(stable_value="", dynamic_value="", visible_value=None):
    """Build one marked context while preserving the stable prefix exactly.

    The stable part is deliberately emitted before the end marker so compatible
    relays can reuse one exact prefix.  Dynamic material is appended only when
    present; an empty dynamic section never creates a second user turn.
    """
    marked_stable, dynamic = _marked_sections(stable_value, dynamic_value)
    if not marked_stable:
        return str(visible_value if visible_value is not None else dynamic)
    marked_value = marked_stable
    if dynamic:
        marked_value = "\n\n".join((marked_value, CACHE_DYNAMIC_START_MARKER + "\n" + dynamic))
    visible = marked_value if visible_value is None else str(visible_value or "")
    return CacheContext(visible, marked_stable, dynamic)


def split_cache_context(value):
    """Split a marked text envelope without changing either text portion."""
    if isinstance(value, CacheContext):
        stable = value._cache_stable
        dynamic = value._cache_dynamic
        return {
            "marked": bool(stable),
            "stable": stable,
            "dynamic": dynamic,
            "stable_chars": len(stable),
            "dynamic_chars": len(dynamic),
        }
    text = str(value or "")
    marker = CACHE_STABLE_END_MARKER
    if marker not in text:
        return {
            "marked": False,
            "stable": "",
            "dynamic": text,
            "stable_chars": 0,
            "dynamic_chars": len(text),
        }
    stable, dynamic = text.split(marker, 1)
    stable = stable + marker
    dynamic = dynamic.lstrip("\r\n")
    if dynamic.startswith(CACHE_DYNAMIC_START_MARKER):
        dynamic = dynamic[len(CACHE_DYNAMIC_START_MARKER):].lstrip("\r\n")
    return {
        "marked": True,
        "stable": stable,
        "dynamic": dynamic,
        "stable_chars": len(stable),
        "dynamic_chars": len(dynamic),
    }


def append_cache_dynamic(value, extra):
    """Append retry/error material without moving the stable prefix."""
    text = str(value or "")
    addition = str(extra or "").strip()
    if not addition:
        return text
    sections = split_cache_context(text)
    if not sections["marked"]:
        return "\n\n".join(part for part in (text, addition) if part)

    stable = sections["stable"]
    if stable.startswith(CACHE_STABLE_START_MARKER):
        stable = stable[len(CACHE_STABLE_START_MARKER):]
    if CACHE_STABLE_END_MARKER in stable:
        stable = stable.rsplit(CACHE_STABLE_END_MARKER, 1)[0]
    stable = stable.strip()
    dynamic = "\n\n".join(
        part for part in (sections["dynamic"], addition) if part
    )
    visible_value = None
    if isinstance(value, CacheContext) and CACHE_STABLE_START_MARKER not in text:
        visible_value = "\n\n".join(part for part in (text, addition) if part)
    return build_cache_context(stable, dynamic, visible_value=visible_value)


def cache_context_diagnostics(value):
    """Return stable/dynamic sizes and hashes for request diagnostics."""
    sections = split_cache_context(value)
    stable = sections["stable"]
    dynamic = sections["dynamic"]

    def digest(text):
        return hashlib.sha256(str(text or "").encode("utf-8", errors="replace")).hexdigest()

    return {
        "cache_context_schema": CACHE_CONTEXT_SCHEMA_VERSION,
        "cache_context_marked": bool(sections["marked"]),
        "cache_stable_chars": int(sections["stable_chars"]),
        "cache_dynamic_chars": int(sections["dynamic_chars"]),
        "cache_stable_sha256": digest(stable),
        "cache_dynamic_sha256": digest(dynamic),
    }


def anthropic_user_content(value):
    """Serialize stable and dynamic text as Claude content blocks."""
    sections = split_cache_context(value)
    if not sections["marked"]:
        return str(value or "")
    blocks = [
        {
            "type": "text",
            "text": sections["stable"],
            "cache_control": {"type": "ephemeral"},
        }
    ]
    if sections["dynamic"]:
        blocks.append({"type": "text", "text": sections["dynamic"]})
    return blocks


def openai_user_messages(value):
    """Serialize the stable prefix and dynamic tail as separate user turns."""
    sections = split_cache_context(value)
    if not sections["marked"]:
        return [{"role": "user", "content": str(value or "")}]
    messages = [{"role": "user", "content": sections["stable"]}]
    if sections["dynamic"]:
        messages.append({"role": "user", "content": sections["dynamic"]})
    return messages


def gemini_user_parts(value):
    """Serialize the boundary as same-turn Gemini text parts.

    Consecutive user contents are not used here because some native Gemini
    gateways require alternating roles.  Same-turn parts preserve the exact
    visible text while keeping the stable prefix at the front of the request.
    """
    sections = split_cache_context(value)
    if not sections["marked"]:
        return [{"text": str(value or "")}]
    parts = [{"text": sections["stable"]}]
    if sections["dynamic"]:
        parts.append({"text": sections["dynamic"]})
    return parts
