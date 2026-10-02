"""向导式小说框架创作。

这个模块只负责“新建小说项目”时的创作框架向导，不参与已有项目的导入、章节正文
生成或长期记忆处理。向导把用户提供的网文创作要求分成四步，每一步都接着前面已经确认的故事继续写，
每一步都由用户确认后才进入下一步。
"""

from __future__ import annotations

import json
import math
import time
import uuid
from copy import deepcopy

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
    QLabel, QListWidget, QListWidgetItem, QLineEdit, QMessageBox, QPlainTextEdit,
    QPushButton, QSpinBox, QStackedWidget, QVBoxLayout, QWidget,
)

from .core import now_str
from .workers import NovelAnalysisWorker


CREATION_WIZARD_STEPS = (
    ("premise", "故事定位"),
    ("bible", "小说圣经与世界规则"),
    ("story_assets", "人物、设定与伏笔"),
    ("stage_plan", "十万字阶段规划"),
)

COMMON_CREATION_RULES = """
你正在和作者一起搭建一部长篇网络小说。每次回答都要像作者正在讲这本书里的故事，而不是在讲写作方法。
1. 只写看得见、听得见、能让人物做出选择的内容：人物在哪里，眼前发生了什么，谁在说话，谁在犹豫，谁先出手，事情因此怎样改变。
2. 语言要自然、具体、有画面感，像成熟网文作者在讲下一段故事。少用空泛的大词，少用概念堆叠，不要把一大段剧情压成一句空话。
3. 写人物时，要让人物有自己的想法、脾气、欲望和顾虑。人物之间的态度要随着见闻、利益、误会、选择和结果而变化，不能一开始就把最后的关系说死。
4. 保留爽点、反差、悬念和人物反应。主角被轻视后，要靠具体行动让别人改变态度；但每次碰撞都要有当时的原因、场面和后果，不能复制同一套打脸场面。
5. 后面写到逐章故事时，平均两章左右可以安排一次新的碰撞：可能是路人、配角或对手误判主角、主动挑衅、争夺利益，也可能是旧关系重新靠近或彻底翻脸。每次都要换原因、换场景、换结果。
6. 默认不写受伤、重伤和养伤。遇到危险时，优先用躲避、交换、失去资源、暴露身份、关系破裂或局势变化来制造代价。
7. 结尾保持开放和带有余波，不把所有秘密、关系和世界问题一次说尽，也不要把结局写成人人满意。
8. 高武、玄幻、仙侠等题材，要从低到高写清完整的实力层次、能做到的事、做不到的事和自然变强的条件；前后不能突然越过已经写明的边界。
9. 人名要有特点、好读、好记，不用生僻字和笔画过多的字。
10. 不要复述作者的要求，不要解释你正在怎样写。除了约定的 JSON 内容，不要在前后添加其它文字。
""".strip()


STEP_PROMPTS = {
    "premise": f"""{COMMON_CREATION_RULES}

现在先从作者给出的灵感出发，写出 5 个彼此完全不同的故事开头和长线走向。每个版本都要像一本真正能开始连载的网文：有好记的书名，有完整简介，有主角眼下的处境，有会一直逼着人物往前走的矛盾，有让人想知道下一步会怎样的人物关系，还有一个不会把所有事情说死的结尾方向。不要只写宣传口号，也不要只是换人名、换地点而沿用同一个故事。

只输出：{{
  "candidates": [
    {{
      "title": "书名",
      "genre": "类型",
      "audience": "男频或女频",
      "style": "风格",
      "one_sentence": "一句话故事钩子",
      "synopsis": "自然的完整故事简介",
      "protagonist": "主角初始处境、性格和最想得到的东西",
      "main_line": "贯穿全书、会越闹越大的矛盾",
      "relationship_engine": "人物之间的态度会怎样从轻视变成改观、靠近或仰望",
      "ending_direction": "开放式、非圆满的结局方向"
    }}
  ],
  "selected_index": 0
}}""",
    "bible": f"""{COMMON_CREATION_RULES}

接着已经选定的故事，把这个世界里真正会让人物做出选择的规矩写清楚。要写出故事想讲的东西、人物一直在争什么、主角和重要人物会怎样改变；也要写清力量、身份、资源、势力和日常生活的边界，以及打破规矩要付出的代价。高武、玄幻、仙侠等题材要从低到高列出完整实力层次，说明每一层能做到什么、做不到什么、怎样自然变强，后面不能突然冒出没有来由的新境界。不要堆只在名词表里好看的设定。

只输出：{{
  "bible": {{
    "core_setting": "核心设定",
    "reader_promise": "读者会一直想知道的事，以及让人愿意追下去的反差和悬念",
    "theme": "长期主题",
    "main_conflict": "主线矛盾",
    "relationship_foundation": "重要人物从怎样的关系开始，以后可能怎样改变",
    "ending_direction": "开放式、非圆满的结尾会留下什么",
    "hard_boundaries": "不能违背的写法、人物行为和结尾边界"
  }},
  "world_rules": {{
    "setting_overview": "世界的基本样貌",
    "power_system": "力量从哪里来、能做到什么；没有等级的题材写清能力边界",
    "levels": [{{"name": "境界或层级", "capability": "能做到什么", "limit": "不能做到什么", "promotion": "如何自然提升"}}],
    "rules": ["故事中不能随便改掉、会逼人物做选择的规矩"],
    "costs_and_limits": ["使用力量、获得资源或改变身份要付出的代价"],
    "factions": [{{"name": "势力", "position": "立场", "relationship_to_protagonist": "与主角的关系变化空间"}}],
    "geography_and_life": "重要地点、日常生活和人们习以为常的规矩"
  }}
}}""",
    "story_assets": f"""{COMMON_CREATION_RULES}

接着前面已经确定的故事，把会反复出现在后续情节里的角色、地方、势力、物件、规矩和暗线一起写出来。三部分要彼此牵连：人物的欲望、秘密和态度要受世界规矩与现实利益影响；地点、势力、物件和能力边界要能逼人物做选择；暗线要从人物藏着的事或读者看得见的细节中自然出现。不要把它们写成互不相干的名词堆，也不要提前把最后答案说出来。

每个重要人物都要有自己想得到或守住的东西，有现实阻力，有不愿让别人知道的部分，有能听出来的说话习惯，还要写清他和主角从哪里开始、以后可能怎样靠近或翻脸。主角弱小时可以被轻视或利用，但对方的态度变化必须有看得见的原因。

只补充后面真的会用到的地点、势力、组织、物品、能力规矩、制度和日常场景。实力层次要和前面说过的边界一致；不写必须靠受伤才能成立的安排。

每条暗线都要能落到一个具体细节上：它在哪里出现，人物当时怎样理解，后面会在哪一段故事里变得重要，最后会改变谁的判断或关系。可以留下没有完全揭开的余波，但不要只写一个空泛的神秘称呼。

只输出：{{
  "characters": [
    {{
      "name": "易读且有特点的名字",
      "role": "身份和故事位置",
      "goal": "当前真正想得到或守住的东西",
      "secret": "确实会影响后续的秘密；没有就留空",
      "voice": "稳定的说话语气、句式或措辞",
      "relationship_to_protagonist": "与主角的初始关系和可能的变化",
      "long_term_change": "这个人物后来会变成什么样",
      "notes": "后面写故事时不能忘记的事实"
    }}
  ],
  "relationship_map": [{{"from": "人物", "to": "人物", "initial_state": "初始关系", "turning_pressure": "什么会迫使关系改变", "possible_state": "可能走向"}}],
  "lore": [
    {{
      "name": "设定名称",
      "type": "地点、势力、物品、规则、制度、能力或其它",
      "description": "后面故事里会真正起作用的具体内容",
      "story_known": "人物当前知道到什么程度，未知部分不要提前写成答案",
      "relationship_effect": "它会怎样改变人物的选择和关系"
    }}
  ],
  "key_scenes": [{{"name": "场景", "atmosphere": "现场让人感到什么", "conflict_use": "适合发生的具体冲突"}}],
  "foreshadows": [
    {{
      "name": "伏笔名称",
      "status": "未埋",
      "setup_stage": "在哪一段故事里、通过什么细节出现",
      "payoff_stage": "在哪一段故事里发生变化，或继续藏下去",
      "description": "读者能看见的线索、人物当时的误解，以及后来会带来的变化",
      "revealed": "以后揭开时会改变什么；现在不要提前说破",
      "remaining_secret": "仍然可以留到后期的未知部分",
      "relationship_effect": "它会怎样让人物靠近、反目、低头或重新选择",
      "notes": "现在不能提前说破的部分"
    }}
  ]
}}""",
    "stage_plan": f"""{COMMON_CREATION_RULES}

现在把全书分成每段约 10 万字的连续故事。总字数和单章字数由作者输入决定；默认约 50 万字、每章约 3000 字，最后一段可以收下剩余字数。每一段都要写清人物身在什么地方、遇到了什么事、冲突怎样加深、人物关系怎样翻转、世界中哪些事实在故事里自然露出来、段尾留下什么具体变化。前后要接得上，不能把后面才该发生的事提前，也不能过早揭开后面的暗线。这里先写每段故事的大致走向，不写具体章节标题和逐章内容；逐章故事会由作者之后手动点击“AI生成章节规划”。

请确保 start_chapter/end_chapter 从第 1 章开始连续覆盖全书；按 target_words / average_chapter_words 推算章节范围，最后一段吸收余数。只输出：{{
  "stage_plan": [
    {{
      "id": "S01",
      "name": "阶段名",
      "start_chapter": 1,
      "end_chapter": 34,
      "target_words": 100000,
      "summary": "直接写这一段会发生的故事",
      "main_conflict": "真正逼人物做选择的矛盾",
      "relationship_changes": ["人物怎样从轻视、利用、平视到改变态度"],
      "character_changes": ["人物在这一段里具体变成什么样"],
      "world_reveals": ["故事进行中自然露出的世界事实"],
      "turning_points": ["关键转折"],
      "foreshadow_actions": ["这一段里暗线怎样出现、变化或暂时藏住"],
      "end_state": "这一段结束时人物、关系和局势变成什么样",
      "next_stage_hook": "接下来从什么新变化开始",
      "forbidden_reveals": "这一段不能提前说破的事"
    }}
  ],
  "global_direction": "全书从开头走到开放式结尾会发生什么变化",
  "chapter_plan_note": "后面逐章写故事时要守住的实力、关系和边界"
}}""",
}


def _as_text(value):
    return str(value or "").strip()


def _first_value(mapping, keys, default=""):
    if not isinstance(mapping, dict):
        return default
    for key in keys:
        value = mapping.get(key)
        if value not in (None, "", [], {}):
            return value
    return default


def _as_list(value):
    return value if isinstance(value, list) else []


def normalize_creation_result(step, payload):
    """Normalize common model aliases without adding another AI call."""
    payload = deepcopy(payload) if isinstance(payload, dict) else {}
    if step == "premise":
        raw = _first_value(payload, ("candidates", "stories", "options", "简介候选"), [])
        candidates = []
        for item in _as_list(raw):
            if not isinstance(item, dict):
                continue
            candidate = {
                "title": _as_text(_first_value(item, ("title", "name", "book_title", "书名"))),
                "genre": _as_text(_first_value(item, ("genre", "类型"))),
                "audience": _as_text(_first_value(item, ("audience", "pov", "频段", "男频女频"))),
                "style": _as_text(_first_value(item, ("style", "风格"))),
                "one_sentence": _as_text(_first_value(item, ("one_sentence", "hook", "一句话简介"))),
                "synopsis": _as_text(_first_value(item, ("synopsis", "summary", "简介"))),
                "protagonist": _as_text(_first_value(item, ("protagonist", "hero", "主角"))),
                "main_line": _as_text(_first_value(item, ("main_line", "core_line", "主线"))),
                "relationship_engine": _as_text(_first_value(item, ("relationship_engine", "关系线"))),
                "ending_direction": _as_text(_first_value(item, ("ending_direction", "ending", "结局方向"))),
            }
            if candidate["title"] or candidate["synopsis"]:
                candidates.append(candidate)
        payload["candidates"] = candidates[:8]
        try:
            payload["selected_index"] = max(0, min(int(payload.get("selected_index", 0) or 0), max(0, len(candidates) - 1)))
        except Exception:
            payload["selected_index"] = 0
        return payload
    if step == "bible":
        bible = _first_value(payload, ("bible", "novel_bible", "小说圣经"), {})
        world_rules = _first_value(payload, ("world_rules", "world", "世界规则"), {})
        payload["bible"] = bible if isinstance(bible, (dict, str)) else str(bible)
        payload["world_rules"] = world_rules if isinstance(world_rules, (dict, str)) else str(world_rules)
        return payload
    if step == "story_assets":
        aliases = {
            "characters": ("characters", "people", "人物"),
            "lore": ("lore", "settings", "设定"),
            "foreshadows": ("foreshadows", "foreshadow_items", "clues", "伏笔"),
        }
        for key, keys in aliases.items():
            raw = _first_value(payload, keys, [])
            payload[key] = [deepcopy(item) for item in _as_list(raw) if isinstance(item, dict)]
        relationship_map = _first_value(
            payload,
            ("relationship_map", "relationships", "关系图", "关系地图"),
            [],
        )
        key_scenes = _first_value(
            payload,
            ("key_scenes", "scenes", "关键场景"),
            [],
        )
        payload["relationship_map"] = [
            deepcopy(item) for item in _as_list(relationship_map) if isinstance(item, dict)
        ]
        payload["key_scenes"] = [
            deepcopy(item) for item in _as_list(key_scenes) if isinstance(item, dict)
        ]
        return payload
    if step == "stage_plan":
        raw = _first_value(payload, ("stage_plan", "stages", "arcs", "阶段规划"), [])
        payload["stage_plan"] = [deepcopy(item) for item in _as_list(raw) if isinstance(item, dict)]
        return payload
    return payload


def pretty_json(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, indent=2)


def _format_value(value, indent=0):
    prefix = "  " * indent
    if isinstance(value, dict):
        lines = []
        for key, child in value.items():
            label = str(key)
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{label}：")
                lines.extend(_format_value(child, indent + 1))
            else:
                text = _as_text(child)
                if text:
                    lines.append(f"{prefix}{label}：{text}")
        return lines
    if isinstance(value, list):
        lines = []
        for index, child in enumerate(value, 1):
            if isinstance(child, dict):
                lines.append(f"{prefix}{index}.")
                lines.extend(_format_value(child, indent + 1))
            else:
                lines.append(f"{prefix}- {_as_text(child)}")
        return lines
    return [f"{prefix}{_as_text(value)}"] if _as_text(value) else []


def format_creation_text(value, title=""):
    lines = [title] if _as_text(title) else []
    lines.extend(_format_value(value))
    return "\n".join(line for line in lines if line).strip()


def normalize_stage_plan_ranges(stage_plan, total_words, average_chapter_words):
    """把阶段范围校正为连续覆盖全书的章节范围。"""
    source = [deepcopy(item) for item in stage_plan if isinstance(item, dict)]
    expected_count = max(1, int(math.ceil(max(1, int(total_words or 500000)) / 100000)))
    while len(source) < expected_count:
        index = len(source) + 1
        source.append({
            "name": f"阶段{index}",
            "summary": "承接上一阶段留下的新变化，继续让人物选择和关系变化把故事推向下一处未知。",
            "main_conflict": "上一阶段留下的后果继续逼近，人物必须作出新的选择。",
            "end_state": "局势出现新的变化，仍保留未完全解释的余波。",
        })
    source = source[:expected_count]
    bounds, _total_chapters = _stage_chapter_bounds(source, total_words, average_chapter_words)
    normalized = []
    for index, item in enumerate(source):
        if index >= len(bounds):
            break
        start, end = bounds[index]
        item["id"] = f"S{index + 1:02d}"
        item["start_chapter"] = start
        item["end_chapter"] = end
        target = 100000
        if index == len(bounds) - 1:
            target = max(1, int(total_words or 500000) - 100000 * index)
        item["target_words"] = target
        normalized.append(item)
    return normalized


def _stage_chapter_bounds(stage_plan, total_words, average_chapter_words):
    """按每 10 万字而不是平均分章数切分阶段。"""
    average_chapter_words = max(1, int(average_chapter_words or 3000))
    total_words = max(1, int(total_words or 500000))
    total_chapters = max(1, int(math.ceil(total_words / average_chapter_words)))
    count = max(1, int(math.ceil(total_words / 100000)))
    bounds = []
    current = 1
    remaining_chapters = total_chapters
    for index in range(count):
        remaining_stages = count - index
        if index == count - 1:
            size = remaining_chapters
        else:
            target_stage_words = min(100000, max(1, total_words - index * 100000))
            desired = int(math.ceil(target_stage_words / average_chapter_words))
            # 每个阶段至少保留一章，最后一阶段吸收因取整留下的余数。
            size = max(1, min(desired, remaining_chapters - (remaining_stages - 1)))
        end = min(total_chapters, current + size - 1)
        bounds.append((current, end))
        used = end - current + 1
        remaining_chapters -= used
        current = end + 1
    return bounds, total_chapters


def build_chapter_plan_foundation(framework):
    """将向导确认内容投影到已有章节规划可识别的基础字段。"""
    framework = framework if isinstance(framework, dict) else {}
    premise = framework.get("premise", {}) if isinstance(framework.get("premise"), dict) else {}
    bible = framework.get("bible", {}) if isinstance(framework.get("bible"), dict) else {}
    world_rules = framework.get("world_rules", {}) if isinstance(framework.get("world_rules"), dict) else {}
    stages = framework.get("stage_plan", []) if isinstance(framework.get("stage_plan"), list) else []
    total_words = int(framework.get("total_words", 500000) or 500000)
    average_words = int(framework.get("average_chapter_words", 3000) or 3000)
    bounds, total_chapters = _stage_chapter_bounds(stages, total_words, average_words)
    profile = {
        "version": "creation_wizard_v1",
        "audience_direction": _as_text(premise.get("audience", "")),
        "genre_world": _as_text(premise.get("genre", "")),
        "core_reader_promise": _as_text(premise.get("one_sentence", "")) or _as_text(bible.get("reader_promise", "")),
        "primary_story_engine": "通过人物处境、利益和认知变化推动关系从俯视、平视到仰望，再由新的选择打破既有关系。",
        "secondary_story_engine": _as_text(premise.get("relationship_engine", "")),
        "planning_grammar": "每一段都要有具体场景、人物选择、关系变化和阶段末的新状态；不把后续资料写成当前人物的任务清单。",
        "pacing_strategy": "以关系反转、具体冲突、反差和悬念形成阅读推动，避免固定句式和重复打脸。",
        "low_exposition_strategy": "世界规则只在人物选择和冲突需要时出现，以场景和行动带出。",
        "forbidden_drift": "不要写受伤养伤；不要提前回收后期伏笔；不要把开放式结局写成所有问题圆满解决。",
        "satisfaction_currencies": ["关系天平翻转", "具体反差", "身份或认知揭开", "人物主动选择"],
        "emotional_resonance_axes": ["被轻视后的反转", "靠近与反目", "仰望之后仍然留下的未知"],
        "chapter_variation_pool": ["人物碰撞", "利益交换", "误会反转", "公开选择", "新规则显形"],
    }
    arcs = []
    for index, stage in enumerate(stages, 1):
        stage = stage if isinstance(stage, dict) else {}
        start, end = bounds[index - 1] if index - 1 < len(bounds) else (1, total_chapters)
        # 不直接信任模型返回的范围，避免阶段重叠、跳章或没有覆盖全书。
        arc = {
            "start_chapter": max(1, start),
            "end_chapter": max(max(1, start), end),
            "name": _as_text(stage.get("name", "")) or f"阶段{index}",
            "macro_phase": _as_text(stage.get("summary", "")),
            "source_stage": _as_text(stage.get("name", "")),
            "dominant_line": _as_text(stage.get("main_conflict", "")),
            "supporting_lines": "；".join(_as_text(item) for item in stage.get("relationship_changes", []) if _as_text(item)),
            "relationship_goal": "；".join(_as_text(item) for item in stage.get("relationship_changes", []) if _as_text(item)),
            "end_state": _as_text(stage.get("end_state", "")),
            "goal": _as_text(stage.get("summary", "")),
            "main_conflict": _as_text(stage.get("main_conflict", "")),
            "turning_points": "；".join(_as_text(item) for item in stage.get("turning_points", []) if _as_text(item)),
            "reader_payoff": "；".join(_as_text(item) for item in stage.get("relationship_changes", []) if _as_text(item)),
            "emotional_arc": _as_text(stage.get("end_state", "")),
            "pacing_pattern": "具体冲突与关系变化交替推进，不使用固定章节模板。",
            "exposition_compression": "只在人物选择需要时带出世界信息。",
            "variation_plan": "；".join(_as_text(item) for item in stage.get("world_reveals", []) if _as_text(item)),
            "forbidden": _as_text(stage.get("forbidden_reveals", "")),
        }
        arcs.append(arc)
    summary = _as_text(framework.get("global_direction", "")) or _as_text(premise.get("synopsis", ""))
    core_mainline = _as_text(premise.get("main_line", "")) or _as_text(bible.get("main_conflict", ""))
    ending = _as_text(premise.get("ending_direction", "")) or _as_text(bible.get("ending_direction", ""))
    boundaries = _as_text(bible.get("hard_boundaries", "")) or "不写受伤剧情；结局保持开放、非圆满。"
    return {
        "summary": summary,
        "core_mainline": core_mainline,
        "ending_promise": ending,
        "global_hard_boundaries": boundaries,
        "target_words": total_words,
        "average_chapter_words": average_words,
        "total_chapter_count": total_chapters,
        "existing_chapter_count": 0,
        "narrative_strategy_profile": profile,
        "creative_intent_contract": {
            "primary_line": core_mainline,
            "core_relationships": _as_text(premise.get("relationship_engine", "")),
            "stage_progression": "；".join(_as_text(item.get("name", "")) for item in stages if isinstance(item, dict)),
            "reading_experience": _as_text(premise.get("one_sentence", "")),
            "ending_boundaries": ending,
            "source": "creation_wizard",
            "version": "1",
        },
        "arcs": arcs,
    }


_CONTEXT_LABELS = {
    "author_input": "作者刚才说的想法",
    "inspiration": "灵感和暂定想法",
    "temporary_title": "暂定书名",
    "genre": "故事类型",
    "audience": "读者方向",
    "style": "希望采用的叙述味道",
    "total_words": "预计总字数",
    "average_chapter_words": "每章大约字数",
    "no_injury": "必须守住的写法",
    "ending": "结尾倾向",
    "confirmed": "前面已经确认的故事资料",
    "premise": "已经选定的故事",
    "selected": "已经选定的版本",
    "candidates": "其它备选版本",
    "title": "书名",
    "one_sentence": "故事钩子",
    "synopsis": "故事简介",
    "protagonist": "主角眼下的处境和想要的东西",
    "main_line": "贯穿全书的矛盾",
    "relationship_engine": "人物关系怎样变化",
    "ending_direction": "结尾留下的方向",
    "bible": "故事的核心",
    "novel_bible": "故事的核心",
    "core_setting": "故事真正要讲的东西",
    "reader_promise": "读者会一直想知道的事",
    "theme": "故事想说的话",
    "main_conflict": "最重要的矛盾",
    "relationship_foundation": "重要人物关系的起点",
    "hard_boundaries": "必须守住的边界",
    "world_rules": "世界里的规矩",
    "world": "世界里的规矩",
    "setting_overview": "这个世界的样子",
    "power_system": "力量和能力的规矩",
    "levels": "实力层次",
    "name": "名字",
    "capability": "这一层能做到的事",
    "limit": "这一层做不到的事",
    "promotion": "怎样自然变强",
    "rules": "不能随便改变的规矩",
    "costs_and_limits": "使用力量和获得资源要付出的代价",
    "factions": "势力",
    "position": "立场",
    "relationship_to_protagonist": "和主角的关系",
    "geography_and_life": "重要地点和日常生活",
    "story_assets": "人物、地方和暗线",
    "characters": "人物",
    "role": "身份和故事位置",
    "goal": "想得到或守住的东西",
    "secret": "藏着的事",
    "voice": "说话的习惯",
    "long_term_change": "以后会怎样改变",
    "notes": "后面不能忘记的事实",
    "relationship_map": "人物之间的关系",
    "from": "关系中的一方",
    "to": "关系中的另一方",
    "initial_state": "现在的关系",
    "turning_pressure": "什么事情会逼他们改变",
    "possible_state": "以后可能变成什么样",
    "lore": "会在故事里起作用的设定",
    "type": "属于哪一类",
    "description": "具体内容",
    "story_known": "人物现在知道多少",
    "relationship_effect": "它会怎样改变人物关系",
    "key_scenes": "适合发生故事的地方",
    "atmosphere": "现场的感觉",
    "conflict_use": "这里适合发生的冲突",
    "foreshadows": "埋在故事里的暗线",
    "status": "现在的状态",
    "setup_stage": "暗线从哪里出现",
    "payoff_stage": "暗线什么时候发生变化",
    "revealed": "以后揭开的事实",
    "remaining_secret": "还藏着的部分",
    "stage_plan": "全书分段故事",
    "stages": "全书分段故事",
    "arcs": "全书分段故事",
    "id": "编号",
    "start_chapter": "从第几章开始",
    "end_chapter": "到第几章结束",
    "target_words": "这一段大约字数",
    "summary": "这一段会发生的故事",
    "relationship_changes": "人物关系怎样变化",
    "character_changes": "人物怎样变化",
    "world_reveals": "故事里自然露出的世界事实",
    "turning_points": "关键转折",
    "foreshadow_actions": "暗线怎样出现或变化",
    "end_state": "这一段结束时的人物和局势",
    "next_stage_hook": "接下来从什么变化开始",
    "forbidden_reveals": "暂时不能揭开的事",
    "global_direction": "从开头走到结尾的变化",
    "chapter_plan_note": "后面逐章写故事时要守住的边界",
}

_CONTEXT_OMIT_KEYS = {
    "schema_version", "source", "completed_at", "selected_index", "version",
}


def _context_label(key):
    key = str(key)
    if key in _CONTEXT_LABELS:
        return _CONTEXT_LABELS[key]
    return key.replace("_", " ")


def _render_context_value(value, indent=0, label=None):
    """把内部资料改写成自然的故事资料，避免把字段名原样塞给模型。"""
    prefix = "  " * indent
    lines = []
    if isinstance(value, dict):
        if label:
            lines.append(f"{prefix}{label}：")
            indent += 1
            prefix = "  " * indent
        for key, child in value.items():
            if key in _CONTEXT_OMIT_KEYS or child in (None, "", [], {}):
                continue
            child_label = _context_label(key)
            if key == "candidates" and value.get("selected"):
                continue
            lines.extend(_render_context_value(child, indent, child_label))
        return lines
    if isinstance(value, list):
        if label:
            lines.append(f"{prefix}{label}：")
            indent += 1
            prefix = "  " * indent
        for index, child in enumerate(value, 1):
            if child in (None, "", [], {}):
                continue
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{index}.")
                lines.extend(_render_context_value(child, indent + 1))
            else:
                lines.append(f"{prefix}- {_as_text(child)}")
        return lines
    text = _as_text(value)
    if not text:
        return lines
    if label:
        lines.append(f"{prefix}{label}：{text}")
    else:
        lines.append(f"{prefix}{text}")
    return lines


def format_creation_context(context):
    context = context if isinstance(context, dict) else {}
    lines = [
        "下面是作者已经说过、或在前面亲自确认过的故事资料。",
        "只沿着这些资料往下写，不替作者改掉题材、人物选择、结尾方向和必须守住的边界。",
        "把它当成作者脑海里已经存在的故事，不要逐条复述资料；直接写出人物和事情。",
    ]
    lines.extend(_render_context_value(context))
    return "\n".join(lines)


class NovelCreationWorker(NovelAnalysisWorker):
    """复用现有结构化请求、流式回退和重试机制的单步向导 worker。"""

    def __init__(self, base_url, api_key, model, step, context, proxy_url="", proxy_mode="不使用代理"):
        self.creation_step = str(step or "").strip()
        self.creation_context = deepcopy(context if isinstance(context, dict) else {})
        text = format_creation_context(self.creation_context)
        super().__init__(
            base_url,
            api_key,
            model,
            text,
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
        )
        self.retry_attempts = 3

    def _analysis_prompt(self):
        return STEP_PROMPTS.get(self.creation_step, COMMON_CREATION_RULES)

    def _analysis_progress_label(self):
        return "新建向导"

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        return format_creation_context(self.creation_context)

    def _allow_retry_chunk_split(self):
        return False

    def run(self):
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if self.creation_step not in dict(CREATION_WIZARD_STEPS):
                raise Exception("未知的新建向导步骤。")
            self.progress.emit(f"正在生成：{dict(CREATION_WIZARD_STEPS).get(self.creation_step, self.creation_step)}")
            parsed, _response_format = self._analyze_chunk_with_retries(
                self._analysis_prompt(),
                self._chunk_user_text(self.text, 1, 1),
                1,
                1,
                True,
            )
            if self._stop_requested or self.isInterruptionRequested():
                return
            normalized = normalize_creation_result(self.creation_step, parsed)
            self.result_ready.emit(normalized)
        except Exception as exc:
            if not self._stop_requested and not self.isInterruptionRequested():
                self.failed.emit(str(exc))
        finally:
            self._close_active_network_handles()


class NovelCreationWizardDialog(QDialog):
    """新建小说项目的四步确认向导。"""

    def __init__(self, ai_selection, project_name_hint="", parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建小说：AI 创作框架向导")
        self.setMinimumSize(980, 720)
        self.resize(1120, 820)
        self.ai_selection = ai_selection if callable(ai_selection) else (lambda: (None, "", "请选择模型。"))
        self.project_name_hint = _as_text(project_name_hint)
        self.worker = None
        self.current_step_index = 0
        self.step_results = {}
        self.premise_candidates = []
        self.premise_selected_index = 0
        self._premise_loading_index = -1
        self._build_ui()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)
        header = QHBoxLayout()
        self.step_label = QLabel()
        self.step_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(self.step_label, 1)
        self.status_label = QLabel("先填写故事灵感，再点击“AI生成当前步骤”。")
        self.status_label.setWordWrap(True)
        header.addWidget(self.status_label, 2)
        root.addLayout(header)

        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self._build_premise_page()
        for step, title in CREATION_WIZARD_STEPS[1:]:
            self._build_json_page(step, title)

        buttons = QDialogButtonBox()
        self.back_btn = buttons.addButton("上一步", QDialogButtonBox.ActionRole)
        self.next_btn = buttons.addButton("确认并下一步", QDialogButtonBox.AcceptRole)
        self.cancel_btn = buttons.addButton("取消", QDialogButtonBox.RejectRole)
        self.back_btn.clicked.connect(self._go_back)
        self.next_btn.clicked.connect(self._go_next)
        self.cancel_btn.clicked.connect(self.reject)
        root.addWidget(buttons)
        self._refresh_step_ui()

    def _add_page_header(self, layout, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #555; padding: 4px 0;")
        layout.addWidget(label)

    def _build_premise_page(self):
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setSpacing(8)
        self._add_page_header(layout, "这一页先确定故事方向。AI 会给出 5 份不同的书名和简介，你可以选择并修改其中一份，再进入小说圣经。")
        form = QFormLayout()
        self.inspiration_edit = QPlainTextEdit()
        self.inspiration_edit.setPlaceholderText("输入灵感、想写的主角、场景、爽点或已有想法，可留空让 AI 自由发挥。")
        self.inspiration_edit.setMaximumHeight(100)
        if self.project_name_hint:
            self.inspiration_edit.setPlainText(self.project_name_hint)
        form.addRow("灵感/暂定名：", self.inspiration_edit)
        self.genre_edit = QLineEdit()
        self.genre_edit.setPlaceholderText("例如：都市异能、玄幻、古言、科幻悬疑")
        form.addRow("类型：", self.genre_edit)
        self.audience_combo = QComboBox()
        self.audience_combo.addItems(["男频", "女频", "不限"])
        form.addRow("频段：", self.audience_combo)
        self.style_edit = QLineEdit()
        self.style_edit.setPlaceholderText("例如：轻快爽文、克制悬疑、细腻情感")
        form.addRow("风格：", self.style_edit)
        numbers = QHBoxLayout()
        self.target_words_spin = QSpinBox()
        self.target_words_spin.setRange(10000, 3000000)
        self.target_words_spin.setSingleStep(10000)
        self.target_words_spin.setValue(500000)
        self.target_words_spin.setSuffix(" 字")
        numbers.addWidget(QLabel("总字数"))
        numbers.addWidget(self.target_words_spin)
        self.average_words_spin = QSpinBox()
        self.average_words_spin.setRange(1000, 20000)
        self.average_words_spin.setSingleStep(500)
        self.average_words_spin.setValue(3000)
        self.average_words_spin.setSuffix(" 字/章")
        numbers.addWidget(QLabel("单章"))
        numbers.addWidget(self.average_words_spin)
        numbers.addStretch(1)
        form.addRow("规模：", numbers)
        layout.addLayout(form)
        self.premise_generate_btn = QPushButton("AI生成 5 份故事简介")
        self.premise_generate_btn.clicked.connect(self._generate_current)
        layout.addWidget(self.premise_generate_btn)
        body = QHBoxLayout()
        self.candidate_list = QListWidget()
        self.candidate_list.setMinimumWidth(230)
        self.candidate_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.candidate_list.currentRowChanged.connect(self._on_candidate_changed)
        body.addWidget(self.candidate_list)
        editor = QFormLayout()
        self.title_edit = QLineEdit()
        self.one_sentence_edit = QLineEdit()
        self.candidate_genre_edit = QLineEdit()
        self.candidate_style_edit = QLineEdit()
        self.synopsis_edit = QPlainTextEdit()
        self.synopsis_edit.setMinimumHeight(130)
        self.protagonist_edit = QPlainTextEdit()
        self.protagonist_edit.setMinimumHeight(80)
        self.main_line_edit = QPlainTextEdit()
        self.main_line_edit.setMinimumHeight(80)
        self.relationship_edit = QPlainTextEdit()
        self.relationship_edit.setMinimumHeight(80)
        self.ending_edit = QPlainTextEdit()
        self.ending_edit.setMinimumHeight(80)
        for label, widget in (
            ("书名：", self.title_edit), ("一句话钩子：", self.one_sentence_edit),
            ("类型：", self.candidate_genre_edit), ("风格：", self.candidate_style_edit),
            ("完整简介：", self.synopsis_edit), ("主角：", self.protagonist_edit),
            ("主线：", self.main_line_edit), ("关系变化：", self.relationship_edit),
            ("结局方向：", self.ending_edit),
        ):
            editor.addRow(label, widget)
        body.addLayout(editor, 1)
        layout.addLayout(body, 1)
        self.stack.addWidget(page)

    def _build_json_page(self, step, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        self._add_page_header(layout, f"AI 会结合前面已经确认的资料生成{title}。右侧内容是结构化结果，可以直接修改；确认后才会写入新项目。")
        generate_btn = QPushButton(f"AI生成{title}")
        generate_btn.clicked.connect(self._generate_current)
        layout.addWidget(generate_btn)
        editor = QPlainTextEdit()
        editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
        editor.setPlaceholderText("点击上面的按钮生成结构化内容。确认前可以直接编辑 JSON。")
        layout.addWidget(editor, 1)
        self.json_editors = getattr(self, "json_editors", {})
        self.json_generate_buttons = getattr(self, "json_generate_buttons", {})
        self.json_editors[step] = editor
        self.json_generate_buttons[step] = generate_btn
        self.stack.addWidget(page)

    def _refresh_step_ui(self):
        step, title = CREATION_WIZARD_STEPS[self.current_step_index]
        self.step_label.setText(f"第 {self.current_step_index + 1}/{len(CREATION_WIZARD_STEPS)} 步：{title}")
        self.stack.setCurrentIndex(self.current_step_index)
        self.back_btn.setEnabled(self.current_step_index > 0 and self.worker is None)
        self.next_btn.setEnabled(self.worker is None)
        self.next_btn.setText("确认并创建项目" if self.current_step_index == len(CREATION_WIZARD_STEPS) - 1 else "确认并下一步")
        if self.current_step_index == 0:
            self.status_label.setText("先生成并选择一份故事方向。")
        elif step in self.step_results:
            self.status_label.setText("当前步骤已有结果，可以重新生成或直接编辑后确认。")
        else:
            self.status_label.setText("请点击 AI 生成当前步骤。")

    def _context_for_step(self, step):
        context = {
            "author_input": {
                "inspiration": self.inspiration_edit.toPlainText().strip(),
                "temporary_title": self.project_name_hint,
                "genre": self.genre_edit.text().strip(),
                "audience": self.audience_combo.currentText().strip(),
                "style": self.style_edit.text().strip(),
                "total_words": self.target_words_spin.value(),
                "average_chapter_words": self.average_words_spin.value(),
                "no_injury": True,
                "ending": "开放式、非圆满",
            },
            "confirmed": deepcopy(self.step_results),
        }
        premise = self._current_premise() if step != "premise" else {}
        if premise:
            context["confirmed_novel_name"] = _as_text(premise.get("title", ""))
        if step != "premise":
            context["selected_premise"] = premise
        return context

    def _current_premise(self):
        self._save_current_candidate()
        if not self.premise_candidates:
            return {}
        index = max(0, min(self.premise_selected_index, len(self.premise_candidates) - 1))
        return deepcopy(self.premise_candidates[index])

    def _save_current_candidate(self):
        if not self.premise_candidates or self._premise_loading_index >= 0:
            return
        index = self.premise_selected_index
        if index < 0 or index >= len(self.premise_candidates):
            return
        item = self.premise_candidates[index]
        item.update({
            "title": self.title_edit.text().strip(),
            "one_sentence": self.one_sentence_edit.text().strip(),
            "genre": self.candidate_genre_edit.text().strip(),
            "style": self.candidate_style_edit.text().strip(),
            "synopsis": self.synopsis_edit.toPlainText().strip(),
            "protagonist": self.protagonist_edit.toPlainText().strip(),
            "main_line": self.main_line_edit.toPlainText().strip(),
            "relationship_engine": self.relationship_edit.toPlainText().strip(),
            "ending_direction": self.ending_edit.toPlainText().strip(),
        })

    def _load_candidate(self, index):
        if index < 0 or index >= len(self.premise_candidates):
            return
        self._premise_loading_index = index
        item = self.premise_candidates[index]
        self.title_edit.setText(_as_text(item.get("title")))
        self.one_sentence_edit.setText(_as_text(item.get("one_sentence")))
        self.candidate_genre_edit.setText(_as_text(item.get("genre")))
        self.candidate_style_edit.setText(_as_text(item.get("style")))
        self.synopsis_edit.setPlainText(_as_text(item.get("synopsis")))
        self.protagonist_edit.setPlainText(_as_text(item.get("protagonist")))
        self.main_line_edit.setPlainText(_as_text(item.get("main_line")))
        self.relationship_edit.setPlainText(_as_text(item.get("relationship_engine")))
        self.ending_edit.setPlainText(_as_text(item.get("ending_direction")))
        self._premise_loading_index = -1

    def _on_candidate_changed(self, index):
        if self._premise_loading_index >= 0:
            return
        self._save_current_candidate()
        if index >= 0:
            self.premise_selected_index = index
            self._load_candidate(index)

    def _generate_current(self):
        if self.worker is not None:
            return
        step = CREATION_WIZARD_STEPS[self.current_step_index][0]
        provider, model, error = self.ai_selection()
        if error:
            QMessageBox.warning(self, "新建向导", error)
            return
        context = self._context_for_step(step)
        if step == "premise":
            context["author_input"]["genre"] = self.genre_edit.text().strip()
        self.worker = NovelCreationWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            step,
            context,
            provider.get("proxy_url", ""),
            provider.get("proxy_mode", "提交和下载" if provider.get("proxy_url") else "不使用代理"),
        )
        self.worker.result_ready.connect(self._on_ai_result)
        self.worker.failed.connect(self._on_ai_failed)
        self.worker.progress.connect(self.status_label.setText)
        self.worker.finished.connect(self._cleanup_worker)
        self._set_running(True)
        self.worker.start()

    def _set_running(self, running):
        running = bool(running)
        self.premise_generate_btn.setEnabled(not running)
        for button in getattr(self, "json_generate_buttons", {}).values():
            button.setEnabled(not running)
        self.back_btn.setEnabled(not running and self.current_step_index > 0)
        self.next_btn.setEnabled(not running)
        self.cancel_btn.setEnabled(not running)
        if running:
            self.status_label.setText("AI 正在生成当前步骤，请稍候……")

    def _on_ai_result(self, result):
        step = CREATION_WIZARD_STEPS[self.current_step_index][0]
        result = normalize_creation_result(step, result)
        self.step_results[step] = deepcopy(result)
        if step == "premise":
            self._save_current_candidate()
            self.premise_candidates = result.get("candidates", [])
            self.premise_selected_index = max(0, min(int(result.get("selected_index", 0) or 0), max(0, len(self.premise_candidates) - 1)))
            self.candidate_list.clear()
            for index, item in enumerate(self.premise_candidates, 1):
                text = _as_text(item.get("title")) or f"方向 {index}"
                self.candidate_list.addItem(QListWidgetItem(text))
            if self.premise_candidates:
                # setCurrentRow 会触发 currentRowChanged，先屏蔽旧编辑器内容的回写，
                # 再把本次生成的候选加载到编辑器。
                self._premise_loading_index = self.premise_selected_index
                self.candidate_list.setCurrentRow(self.premise_selected_index)
                self._load_candidate(self.premise_selected_index)
            self.status_label.setText(f"已生成 {len(self.premise_candidates)} 份故事方向，请选择并编辑。")
        else:
            editor = self.json_editors.get(step)
            if editor is not None:
                editor.setPlainText(pretty_json(result))
            self.status_label.setText("已生成当前步骤，确认前可以编辑。")
        self._set_running(False)

    def _on_ai_failed(self, error):
        self.status_label.setText(f"生成失败：{error}")
        QMessageBox.warning(self, "新建向导生成失败", str(error))
        self._set_running(False)

    def _cleanup_worker(self):
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_running(False)
        self._refresh_step_ui()

    def _read_current_step(self):
        step = CREATION_WIZARD_STEPS[self.current_step_index][0]
        if step == "premise":
            self._save_current_candidate()
            if not self.premise_candidates:
                raise ValueError("请先生成至少一份故事方向。")
            candidate = self._current_premise()
            candidate["genre"] = candidate.get("genre") or self.genre_edit.text().strip()
            candidate["style"] = candidate.get("style") or self.style_edit.text().strip()
            candidate["audience"] = candidate.get("audience") or self.audience_combo.currentText().strip()
            if not candidate.get("title") or not candidate.get("synopsis"):
                raise ValueError("书名和完整简介不能为空。")
            self.premise_candidates[self.premise_selected_index] = deepcopy(candidate)
            self.step_results[step] = {
                "candidates": deepcopy(self.premise_candidates),
                "selected_index": self.premise_selected_index,
                "selected": candidate,
            }
            return
        editor = self.json_editors.get(step)
        if editor is None:
            raise ValueError("当前步骤编辑器不存在。")
        text = editor.toPlainText().strip()
        if not text:
            raise ValueError("请先生成当前步骤内容。")
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError(f"当前步骤不是合法 JSON：第 {exc.lineno} 行，第 {exc.colno} 列。") from exc
        normalized = normalize_creation_result(step, value)
        if step == "story_assets":
            missing = [
                label for key, label in (
                    ("characters", "人物"),
                    ("lore", "设定"),
                    ("foreshadows", "伏笔"),
                )
                if not normalized.get(key)
            ]
            if missing:
                raise ValueError(f"当前步骤缺少：{'、'.join(missing)}。")
        elif step == "stage_plan" and not normalized.get(step):
            raise ValueError("当前步骤至少需要一条内容。")
        if step == "stage_plan":
            normalized["stage_plan"] = normalize_stage_plan_ranges(
                normalized.get("stage_plan", []),
                self.target_words_spin.value(),
                self.average_words_spin.value(),
            )
        if step == "bible" and not normalized.get("bible"):
            raise ValueError("小说圣经不能为空。")
        if step == "bible" and not normalized.get("world_rules"):
            raise ValueError("世界规则不能为空。")
        self.step_results[step] = normalized

    def _go_back(self):
        if self.worker is not None or self.current_step_index <= 0:
            return
        self.current_step_index -= 1
        self._refresh_step_ui()

    def _go_next(self):
        if self.worker is not None:
            return
        try:
            self._read_current_step()
        except ValueError as exc:
            QMessageBox.warning(self, "新建向导", str(exc))
            return
        if self.current_step_index < len(CREATION_WIZARD_STEPS) - 1:
            self.current_step_index += 1
            self._refresh_step_ui()
            return
        self.accept()

    def result_payload(self):
        self._save_current_candidate()
        premise_result = self.step_results.get("premise", {})
        selected = premise_result.get("selected", {}) if isinstance(premise_result, dict) else {}
        bible_result = self.step_results.get("bible", {})
        assets_result = deepcopy(self.step_results.get("story_assets", {}))
        stage_result = deepcopy(self.step_results.get("stage_plan", {}))
        if isinstance(stage_result, dict):
            stage_result["stage_plan"] = normalize_stage_plan_ranges(
                stage_result.get("stage_plan", []),
                self.target_words_spin.value(),
                self.average_words_spin.value(),
            )
        framework = {
            "schema_version": 1,
            "source": "creation_wizard",
            "premise": deepcopy(selected),
            "premise_candidates": deepcopy(premise_result.get("candidates", [])),
            "bible": deepcopy(bible_result.get("bible", {})),
            "world_rules": deepcopy(bible_result.get("world_rules", {})),
            "characters": deepcopy(assets_result.get("characters", [])),
            "lore": deepcopy(assets_result.get("lore", [])),
            "foreshadows": deepcopy(assets_result.get("foreshadows", [])),
            "relationship_map": deepcopy(assets_result.get("relationship_map", [])),
            "key_scenes": deepcopy(assets_result.get("key_scenes", [])),
            "stage_plan": deepcopy(stage_result.get("stage_plan", [])),
            "global_direction": _as_text(stage_result.get("global_direction", "")),
            "chapter_plan_note": _as_text(stage_result.get("chapter_plan_note", "")),
            "total_words": self.target_words_spin.value(),
            "average_chapter_words": self.average_words_spin.value(),
            "completed_at": now_str(),
        }
        # Keep the confirmed book name as an explicit project-level value as
        # well as inside premise, so every later wizard step can reference it.
        framework["novel_name"] = _as_text(selected.get("title", ""))
        framework["chapter_plan_foundation"] = build_chapter_plan_foundation(framework)
        state = {
            "schema_version": 1,
            "status": "complete",
            "current_step": "complete",
            "stage_unit_words": 100000,
            "steps": {step: {"status": "confirmed"} for step, _title in CREATION_WIZARD_STEPS},
            "updated_at": now_str(),
        }
        return {"creation_framework": framework, "creation_wizard_state": state}

    def closeEvent(self, event):
        if self.worker is not None:
            try:
                self.worker.stop()
                self.worker.wait(2000)
            except Exception:
                pass
            event.ignore()
            self.worker = None
            self._set_running(False)
            return
        super().closeEvent(event)
