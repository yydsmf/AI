"""向导式小说框架创作。

这个模块只负责“新建小说项目”时的创作框架向导，不参与已有项目的导入、章节正文
生成或长期记忆处理。向导把用户提供的网文创作要求分成三步，每一步都接着前面已经确认的故事继续写，
每一步都由用户确认后才进入下一步。
"""

from __future__ import annotations

import ast
import json
import math
import os
import re
import time
import uuid
from copy import deepcopy

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView, QApplication, QDialog, QDialogButtonBox, QFrame,
    QGridLayout, QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QLineEdit,
    QMessageBox, QPlainTextEdit, QPushButton, QScrollArea, QSizePolicy, QSpinBox,
    QStackedWidget, QStyle, QToolButton, QVBoxLayout, QWidget,
)

from .core import HISTORY_DIR, load_json_file, now_str, safe_remove_file, save_json_file
from .novel_storage import load_character_style_library, remove_character_style
from .novel_utils import (
    _core_motive_progression_guidance,
    _entity_naming_guidance,
    _normalize_foreshadow_code,
    _procedural_plot_guard_guidance,
    _terminal_window_bounds,
)
from .workers import NovelAnalysisWorker


CREATION_WIZARD_DRAFT_FILE = os.path.join(
    HISTORY_DIR,
    "novel_creation_wizard_draft.json",
)
CREATION_WIZARD_DRAFT_DIR = os.path.join(
    HISTORY_DIR,
    "novel_creation_wizard_drafts",
)
CREATION_WIZARD_DRAFT_INDEX_FILE = os.path.join(
    CREATION_WIZARD_DRAFT_DIR,
    "index.json",
)
CREATION_WIZARD_NAME_HISTORY_FILE = os.path.join(
    HISTORY_DIR,
    "novel_creation_wizard_name_history.json",
)
CREATION_WIZARD_NAME_HISTORY_LIMIT = 160
CREATION_WIZARD_NAME_REFERENCE_LIMIT = 36
NOVEL_AUTOSAVE_DRAFT_FILE = os.path.join(
    HISTORY_DIR,
    "novel_draft.json",
)


def _screen_available_geometry(widget):
    screen = widget.screen() if widget is not None else None
    if screen is None and widget is not None:
        parent = widget.parentWidget()
        screen = parent.screen() if parent is not None else None
    if screen is None:
        app = QApplication.instance()
        screen = app.primaryScreen() if app is not None else None
    if screen is None:
        return None
    geometry = screen.availableGeometry()
    return geometry if geometry.isValid() else None


def _fit_dialog_to_screen(
    dialog,
    width_ratio=0.86,
    height_ratio=0.84,
    minimum_width=720,
    minimum_height=520,
    maximum_width=1440,
    maximum_height=980,
):
    """按当前屏幕工作区给对话框一个可调整的初始尺寸。"""
    geometry = _screen_available_geometry(dialog)
    if geometry is None:
        dialog.setMinimumSize(minimum_width, minimum_height)
        return

    # Reserve space for the native title bar and the macOS Dock/menu area.
    # ``availableGeometry`` is not equally precise on every platform, so keep
    # a little extra room instead of letting the bottom edge touch the screen.
    safe_width = max(320, geometry.width() - 32)
    safe_height = max(260, geometry.height() - 48)
    minimum_width = min(int(minimum_width), safe_width)
    minimum_height = min(int(minimum_height), safe_height)
    width = min(
        safe_width,
        int(geometry.width() * float(width_ratio)),
        int(maximum_width),
    )
    height = min(
        safe_height,
        int(geometry.height() * float(height_ratio)),
        int(maximum_height),
    )
    width = max(minimum_width, width)
    height = max(minimum_height, height)
    dialog.setMinimumSize(minimum_width, minimum_height)
    dialog.setMaximumSize(safe_width, safe_height)
    dialog.resize(width, height)
    dialog.move(
        geometry.left() + max(0, (geometry.width() - dialog.width()) // 2),
        geometry.top() + max(0, (geometry.height() - dialog.height()) // 2),
    )


CREATION_WIZARD_STEPS = (
    ("premise", "故事定位"),
    ("bible", "故事底盘"),
    ("stage_plan", "十万字阶段规划"),
)

CREATION_CHOICE_GROUPS = {
    "audience": {
        "读者方向": ("男频", "女频", "男女皆宜"),
    },
    "genre": {
        "奇幻仙侠": (
            "西方奇幻", "东方仙侠", "传统玄幻", "玄幻脑洞", "都市修真",
        ),
        "都市题材": (
            "都市高武", "都市种田", "都市脑洞", "都市日常", "战神赘婿",
        ),
        "历史与军事": (
            "抗战谍战", "历史古代", "历史脑洞",
        ),
        "悬疑灵异": (
            "悬疑灵异", "悬疑脑洞",
        ),
        "科幻末世": (
            "科幻末世",
        ),
        "衍生与其他": (
            "男频衍生", "动漫衍生", "游戏体育",
        ),
    },
    "theme": {
        "题材方向": (
            "衍生", "影视", "天灾", "第四天灾", "规则怪谈", "克苏鲁",
            "都市异能", "末日求生", "灵气复苏", "高武世界", "异世大陆",
            "东方玄幻", "综漫", "奇幻仙侠",
        ),
        "时代与背景": (
            "古代", "清朝", "宋朝", "架空", "都市", "玄幻", "历史", "武侠",
        ),
        "叙事与氛围": (
            "仕途", "第一人称", "赛博朋克", "搞笑轻松", "悬疑", "谍战",
            "断层", "武将", "国运", "开局", "体育",
        ),
    },
    "protagonist_route": {
        "开局状态": (
            "开局无敌", "从底层崛起", "重生归来",
            "觉醒金手指", "被迫入局", "身份反转",
        ),
        "故事走法": (
            "升级变强", "经营势力", "解谜破局",
            "感情牵引", "群像共行", "幕后布局",
        ),
    },
    "protagonist_style": {},
    "style": {
        "故事驱动": (
            "复仇逆袭", "权谋博弈", "冒险探索", "经营建设",
            "探案追凶", "成长治愈", "末日求生", "身份揭秘",
        ),
        "爽感节奏": (
            "热血升级", "轻松爽文", "逆袭翻盘",
            "无敌流", "高燃冒险",
        ),
        "氛围情绪": (
            "温暖治愈", "轻喜剧", "细腻情感",
            "诡异压迫", "暗黑悬疑", "史诗厚重", "现实克制",
        ),
        "叙事节奏": (
            "快节奏连载", "慢热沉浸", "群像推进",
            "日常铺陈", "多线交织",
        ),
    },
    "length": {
        "作品长度": ("30万字", "50万字", "100万字+"),
    },
    "chapter_words": {
        "单章字数": ("1000字", "2000字", "3000字", "5000字", "8000字", "10000字"),
    },
}

CREATION_CHOICE_DEFAULTS = {
    "audience": "男频",
    "genre": "都市脑洞",
    "theme": "",
    "protagonist_route": "觉醒金手指",
    "protagonist_style": "",
    "style": "热血升级",
    "length": "50万字",
    "chapter_words": "3000字",
}

CREATION_CHOICE_TITLES = {
    "audience": "读者方向",
    "genre": "主分类",
    "theme": "主题（最多选2项）",
    "protagonist_route": "主角起点",
    "protagonist_style": "自定义主角风格",
    "style": "风格与节奏",
    "length": "预计篇幅",
    "chapter_words": "单章字数",
}

CREATION_CHOICE_HINTS = {
    "audience": "先选读者方向，AI会据此调整人物关系和推进节奏。",
    "genre": "主分类只能选择一项，分类详情会在弹窗内滚动查看。",
    "theme": "主题最多选择两项，用来补充世界背景、叙事视角或阅读感觉。",
    "protagonist_route": "主角从什么状态开始，会决定第一章的抓力。",
    "protagonist_style": "从人物卡收藏中选择主角的性格/特点和语言风格，只继承表达底色。",
    "style": "分类很多，选一个最想保留的主感觉即可。",
    "length": "只是规划参考，后续可以继续调整。",
    "chapter_words": "章节总数和阶段边界会按这个字数计算，后面仍可调整。",
}


def _character_style_choice_label(item):
    item = item if isinstance(item, dict) else {}
    name = _as_text(item.get("name")) or _as_text(item.get("source_character")) or "未命名人物风格"
    source_project = _as_text(item.get("source_project"))
    return f"{name}（{source_project}）" if source_project else name


def _wrap_character_style_option_text(value, width=18):
    value = _as_text(value)
    if not value:
        return ""
    return "\n".join(value[index:index + width] for index in range(0, len(value), width))


def _character_style_choice_option_label(item):
    """Show enough style content in the picker while keeping the summary short."""
    item = item if isinstance(item, dict) else {}
    lines = [_wrap_character_style_option_text(_character_style_choice_label(item))]
    personality = _wrap_character_style_option_text(item.get("personality"))
    voice = _wrap_character_style_option_text(item.get("voice"))
    if personality:
        lines.append(f"性格/特点：{personality}")
    if voice:
        lines.append(f"语言风格：{voice}")
    return "\n".join(lines)


CHARACTER_STYLE_NONE_OPTION = "不使用自定义风格"


def _character_style_choice_entries():
    return [
        item for item in load_character_style_library()
        if isinstance(item, dict)
        and (_as_text(item.get("personality")) or _as_text(item.get("voice")))
    ]


def _character_style_choice_groups():
    entries = _character_style_choice_entries()
    return {
        "已收藏人物卡风格": tuple(
            [CHARACTER_STYLE_NONE_OPTION]
            + [_character_style_choice_option_label(item) for item in entries]
        )
    }


def _character_style_id_for_selected(selected):
    """Recover a library ID when reopening a completed project as a draft."""
    selected = selected if isinstance(selected, dict) else {}
    selected_label = _as_text(selected.get("protagonist_style"))
    custom_style = selected.get("custom_protagonist_style", {})
    custom_style = custom_style if isinstance(custom_style, dict) else {}
    personality = _as_text(custom_style.get("personality"))
    voice = _as_text(custom_style.get("voice"))
    for item in _character_style_choice_entries():
        if selected_label and _character_style_choice_label(item) == selected_label:
            return _as_text(item.get("id"))
        if (
            personality
            and voice
            and _as_text(item.get("personality")) == personality
            and _as_text(item.get("voice")) == voice
        ):
            return _as_text(item.get("id"))
    return ""


CREATION_CUSTOM_PROTAGONIST_STYLE_GUIDANCE = """
如果作者选择了 custom_protagonist_style，只把其中的人物性格/特点和语言风格作为主角的长期表达底色；不要复制收藏人物的姓名、身份、目标、秘密、关系、经历、原项目设定或具体剧情。故事事实仍以作者灵感和当前题材为准，收藏风格只影响主角怎样观察、反应、选择和说话，让新的主角在自己的处境中自然表现出相近的底色。
""".strip()

CREATION_PROCEDURAL_PLOT_GUARD = _procedural_plot_guard_guidance().strip()
CREATION_ENTITY_NAMING_GUIDANCE = _entity_naming_guidance().strip()
CREATION_CORE_MOTIVE_GUIDANCE = _core_motive_progression_guidance().strip()


def _creation_entity_naming_guidance(context):
    """Shared creation rules already contain the generic naming contract."""
    return ""


CREATION_LORE_TYPE_GUIDANCE = """
设定类型按实际资料归类：地点是城市、建筑、区域、房间、道路、遗迹等实际空间；日常场景是反复出现的生活场所和生活落点；物件是婚书、文件、武器、遗物、芯片、信件等具体物品；势力是家族、公司、学校、军部、机构、联盟、组织等主体；规则是能力体系、权限、警报等级和世界运行方式等长期成立的规则；制度是公示、约束、管理办法和社会秩序等长期运行的制度；异常线索是暂时无法解释的现象、信号、印记和异常记录。
只有同一条资料同时具备两种真实属性时，才使用组合类型“物件与规则”“势力与制度”或“地点与异常边界”等；组合类型仍写在同一个 type 字段中。不能把规则、制度、势力或物件归为地点，type 只写实体类别，不写剧情作用、评价或编辑说明。
""".strip()


CREATION_CHARACTER_PROFILE_GUIDANCE = """
人物卡只保存能够跨场景继承的人物底色，不保存某一章的剧情。把“人物性格/特点”和“语言风格”分开：人物性格/特点写长期稳定的性格类别，例如搞笑、优柔寡断、好胜、敏感、嘴硬或爱操心；语言风格写可迁移的表达类别，例如话多、喜欢开玩笑、无厘头、爱打岔、绕弯或直白。每项用一到几个词或短句说清即可，不要展开成剧情段落。
姓名字段只填写人物的正式姓名，不要把称呼、亲属关系、身份、职位或身份说明拼在姓名前面；例如“陶大姑陶秀兰”应拆成姓名“陶秀兰”，把“陶大姑”写入身份和故事位置。身份字段可以保留完整、自然的说明，不要为了拆分姓名而压缩成单一标签。
语言风格可以保留“话多”等正常表达特征，但不得生成“话少、寡言、惜字如金、解释型、反问多、连续反问、质问式、审问式、对抗式、命令式、攻击性强、强硬压迫”等标签。限制“话少”是为了避免正文模型把它误读成短句、半句、连续回击或只用反问，进而把普通交流写成对抗式问答；也不要把人物语言写成围绕质问、反驳、施压、试探或争夺解释权展开的对抗话术，这类内容不能作为人物卡的语言风格结论。
人物性格/特点、语言风格和人物备注都不能写固定笑点、固定口头禅、固定动作套路、具体食物或道具、具体地点、某次出场桥段、某章发生的行为、临时情绪或一次性反应，也不要写“遇到某件事就……”的固定触发模式。这样的内容属于章节剧情、正文事实或当时的关系变化，不属于人物卡。备注只保留稳定身份、长期关系底色、持续有效的秘密和确实会影响后文的长期变化；如果一条内容只因为某件事发生过一次才成立，就不要放入人物卡。语言分类可以随关系、情绪和压力自然变化，不把人物锁成每次都重复同一种说法。
""".strip()


CREATION_FORESHADOW_CLOSURE_GUIDANCE = """
伏笔必须是能够在正文中验收的单一闭环，不是世界观百科、人物成长方向或整本书的抽象主题。每条伏笔只保留一个核心问题、一个核心承诺和一个可观察的回收结果：现在出现的具体线索是什么，人物当前怎样误解或理解，后面哪一次具体行动/对话/对抗会给出答案，以及答案会让谁的判断、关系、资源、身份或局势发生什么可见变化。不要把“身份真相、幕后势力、三年前往事、力量来源、未来世界”捆成一条伏笔，也不要用“完整真相仍未知”“后续影响仍未知”“来源和机制仍未揭示”把多条问题塞进同一条记录；这些内容应拆成独立伏笔，或留在小说圣经/世界规则/人物长期资料中。
普通伏笔的揭示结果必须能直接回答这条线索提出的核心问题，并在场景中留下明确结果；普通伏笔的 remaining_secret 填“无”或只写不影响本部闭环的余波。只有真正贯穿全书核心矛盾、结尾仍需要保留余味的少量主线谜团，才允许 payoff_stage 写“结尾保留”，且不能把普通伏笔批量标成长期伏笔。普通伏笔优先安排在 setup_stage 之后的后续阶段完成回收；同阶段回收只适用于短线且能在一个连续场景内完整闭合的线索。
判断一条候选是否合格时，必须能够用一句话写出“回收章发生什么、谁做了什么、读者确认了什么、当场产生什么结果”。写不出这四点，就不要生成伏笔，应改放到主线、人物、设定或阶段事件中。伏笔数量服从故事需要，宁可少一条，也不要为了达到数量要求生成宽泛、重复或无法验收的线索。
""".strip()


CREATION_ENDING_DIRECTION_GUIDANCE = """
结尾方向不是“开放式结尾任务”，也不是下一卷预告，而是本部结局的方向性契约。先明确本部最后要落地的结果：核心动机的具体目标怎样完成、失败、转化或付出代价，核心矛盾最终形成什么可见结果，主要关系如何落定，主角最终处于什么位置。结局可以圆满、遗憾、代价胜利、关系暂未完全定型或留下适合题材的余味，结果形态由故事本身决定，不套固定模板；但不能让主角必须完成的事情、核心对手、核心真相或本部主要关系停在“以后再说”。
允许保留的余味只能是不影响本部闭环的内容，例如人物之后的选择、世界仍有更大空间、关系中的情绪余波或读者可以自行想象的未来；不得把新敌人、新任务、新规则、新目的地、下一卷承诺或必须继续追问的重大真相写成最后阶段的待办事项。结尾方向应同时写清“本部已经得到的结果”和“结果之后仍可存在的余味”，前者优先于后者。
""".strip()


CREATION_INSPIRATION_FACT_GUIDANCE = """
作者灵感中明确写出的事实都属于故事底盘的一部分，要完整吸收并保留事实含义。人物身份、人生阶段、职业或学业状态、关系状态、时间顺序、已经发生的事件、具体地点、关键限制、爽点和结局方向，都要在后续资料中继续体现；与主角处境、故事开场和主线直接相关的关键事实，要在每个故事方向的简介中自然写出来，不能只留在主角字段或资料字段里。人物字段、故事引子、简介、主线和关系线表达同一事实时，要保持同一时间、身份和因果关系。五个方向可以用不同的场景、人物选择、冲突形状和推进方式呈现这些事实，差异继续来自故事本身；作者没有明确的部分保留自由创作空间。
""".strip()


COMMON_CREATION_RULES = f"""
你正在和作者一起搭建一部长篇网络小说。外层 JSON 只是程序读取用的容器，不能在 JSON 之外添加解释、Markdown 或注释。
1. 沿着作者已经说过和已经确认的故事继续写，稳住题材、主角、核心悬念、人物关系和结尾方向。作者灵感中的题材组合、人物身份、关系状态、具体情节、场景、爽点和节奏要求都要进入故事；第一步的主分类、主题、读者方向、主角起点和风格选择是创作底色。
2. 资料具体而有根，人物、地点、物件、选择、结果和长期成立的事实彼此照应；剧情节点只写当前故事真正需要的细节，让重要变化能够被看见、听见或感受到。
3. 人物的愿望、顾虑、秘密和关系变化随着事情自然显现；故事可以由人物、关系、环境、事件、欲望、秘密或题材规则推动，不要求所有题材使用同一套冲突顺序。
4. 小说圣经、世界规则、人物、设定和伏笔各自承担不同作用：圣经托住整本书，世界规则说明长期运转方式，人物承载选择和关系，设定提供反复使用的生活落点，伏笔保留线索和后续变化。
5. 危险和代价优先落到躲避、交换、资源变化、身份暴露、关系破裂、空间变化和局势改变上；身体伤势随题材和现场需要自然出现。
6. 实力体系跟随题材本身生长：明确需要修炼、境界或能力层次的故事，在设定库里展开来源、层次、边界和成长条件；普通都市、言情、悬疑、灵异、现实和没有明确力量体系的科幻，把重点放在人物处境、规则边界和具体事件上。
7. {CREATION_CORE_MOTIVE_GUIDANCE}
8. {CREATION_ENDING_DIRECTION_GUIDANCE}
9. {CREATION_CHARACTER_PROFILE_GUIDANCE}
10. {CREATION_FORESHADOW_CLOSURE_GUIDANCE}
11. {CREATION_CUSTOM_PROTAGONIST_STYLE_GUIDANCE}
12. 不使用“短促直接”“温和克制”“冷淡”“命令式”这几类语言风格，其它可以正常使用。
13. {CREATION_PROCEDURAL_PLOT_GUARD}
14. {CREATION_ENTITY_NAMING_GUIDANCE}
15. 字段值直接写具体内容，保持清楚、稳定、方便后续执行；内容呈现为作者自己的故事底稿，各资料类别各自承担作用，同一段剧情只放在最合适的位置。
16. JSON 只作为程序读取的容器：保持紧凑，不用 Markdown、缩进、空行或多余空格；压缩外壳，不压缩事实、人物数量、设定数量、伏笔数量或故事内容。
17. {CREATION_INSPIRATION_FACT_GUIDANCE}
""".strip()


STEP_PROMPTS = {
    "premise": f"""{COMMON_CREATION_RULES}

现在先从作者给出的灵感出发，写出 5 个彼此真正不同、可以直接开始连载的故事方向。每个方向的简介都从一个正在发生的强冲突切入：让主角在具体场面里立刻遇到会改变处境的压力、对抗、失控或突发事件，并让这次冲突留下清楚的现实后果，把故事推向后面。冲突的形状由题材、灵感、人物关系和风格自然决定，不套固定顺序，不把简介写成资料清单或策划说明。简介要求用自然的网络小说叙述语言风格，不要出现策划术语、抽象形容、办案式风格、编辑式说明、编辑式总结之类的词。简介字数软要求为 300 字左右。
每个方向的 m“贯穿全书的矛盾”要让读者看懂主角为什么非行动不可、要到达什么具体结果、失败会失去什么、什么自然节点会让代价加重或机会改变，并体现主要反差轴；这些是核心动机的验收维度，不是固定句式、固定顺序或每项各写一段，可以根据题材合并在人物关系、秘密、选择、资源限制或现场后果里。不能只写“赚钱、变强、复仇、逆天改命”这类抽象愿望，也不要为了凑齐维度给所有故事硬加金额、倒计时、强敌或升级路线。核心动机要能被拆成连续阶段目标：解决当前阻碍后，结果打开下一道更具体的阻碍或更高代价，不能每个方向只剩一串互不相干的事件。
这里的 m 是候选故事的核心动机主线契约，不是另起一条“主线矛盾”：下游会把它统一保存为 core_motive。关系线、主题和阶段冲突都只能围绕这条核心动机展开，不能各自提出另一项主角必须完成的总任务。

先完整吸收作者灵感和全部选择，再开始写。五个方向都使用灵感中的核心内容，但各自从不同的人物选择、现实压力、关系变化或题材机制长出自己的故事；差异要来自故事本身，不靠只换名字、地点或几句设定。五个方向可以采用完全不同的剧情发动方式，不要求统一的冲突顺序、固定的网文结构或相同的推进节奏。

如果作者已经明确提供了书名，五个方向的书名必须原样使用这个书名，不改字、不换说法、不另起书名；五个方向的差异来自人物选择、现实压力、关系变化和剧情走法。只有作者没有明确提供书名时，才为五个方向分别拟题。五个方向都要像真正不同的小说来写人：每个方向的主角都要有明确姓名，主角姓名不能重复，也不能只是换一个字；重要配角的姓名也尽量错开。不要连续使用同一个姓氏、相同的姓名节奏或同一套常见网文姓名模板，要让姓名随着题材、时代、人物身份、男频或女频方向和故事气质自然变化。名字要好读、好记、有辨识度，不为了变化硬塞生僻字；简介、主角字段和人物关系里使用同一个姓名，不能前后改名。
命名参考中的姓名和姓氏来自本地已经创建过的其它项目，只用来帮助这次换一套自然的命名方式：不要直接复用其中的姓名，不要只改一个字，也不要连续沿用同一批姓氏和姓名节奏。参考为空时，也要主动避开最常见的固定网文姓名模板；仍然以符合题材、时代、人物身份和故事气质为先，不要为了不同而使用生硬或生僻的名字。

下面示例中的空对象只是为了避免重复占篇幅，实际返回时 1、2、3、4、5 五个槽位都必须各自完整填写十个字段，不能返回空对象，也不能把多个故事合并到一个槽位。

每个方向的 e“结尾方向”必须先写本部核心动机、核心矛盾、主要关系和主角最终处境的明确落点，再写可选的余味。余味可以是遗憾、代价、关系暂未完全定型或世界仍有空间，但不能把新敌人、新任务、下一卷承诺或必须由后续回答的重大问题当成本部结尾内容。

只输出一个合法 JSON 对象。不要使用可变长度的候选数组，改用固定的五个编号对象：{{"c":{{"1":{{"t":"书名","g":"类型","a":"读者方向","y":"风格","h":"一句话故事引子","d":"故事简介，约300字","p":"主角初始处境、性格和最想得到的东西","m":"核心动机主线","r":"人物关系长线变化","e":"结尾方向（本部结果与余波）"}},"2":{{}},"3":{{}},"4":{{}},"5":{{}}}},"s":0}}。c 只能有 1、2、3、4、5 五个键，不能增加第6个方向，也不能漏掉任何一个方向；每个方向都必须完整填写，不要输出 Markdown、解释或其它键。""",
    "bible": f"""{COMMON_CREATION_RULES}

现在和作者一起把已经选定的故事底盘搭好。下面的“已经选定的故事”是唯一的故事来源：稳住它的主角、处境、地点、核心悬念、主要关系和结尾方向，再补足长篇故事继续生长所需要的事实。新增人物、新势力和新秘密都要服务于原来的主线，并在后续事件中拥有具体作用。

这一次要把小说圣经、世界规则、人物、设定和伏笔一起写出来，但五部分各自回答不同的问题：
这一步只根据已经选定的故事和作者偏好搭建底盘，后面的阶段规划会读取这里的完整资料。这里写整本书的骨架和长期事实，让后面的场景自然长出来；剧情细节留到阶段和章节中由人物经历展开。
小说圣经回答“这整本书最核心的东西是什么”。其中的主线矛盾字段必须承担一条可执行的核心动机契约：主角为什么非走下去、要在什么期限或机会窗口内完成什么具体目标、失败会失去什么、谁或什么在阻挡，以及主角的开局处境与终局目标/对手/代价之间有什么大反差。再把这条大目标拆成会自然延伸的阶段目标，让每个阶段都是同一件事的下一道阻碍或更高代价。这里的长期问题要写成随着人物一次次选择不断变深的具体事情，不写“读者会……”或编辑式的阅读说明，也不承担章节剧情复述。
结尾方向字段必须写成“本部结果与余波”：先说明核心动机的最终结果、核心矛盾的解决或代价、主要关系的落点和主角最终处境，再说明哪些内容可以作为不影响本部闭环的余味。可以保留情绪、关系或世界层面的开放感，但不得把新的敌人、任务、规则、目的地、下一卷承诺或必须继续回答的核心真相写成结尾依赖；结尾方向不是要求最后一章继续留悬念。
这里不再把“主线矛盾”和“核心动机”当成两条并列主线：固定输出中的第4项 main_conflict 只是兼容字段，内容就是唯一的 core_motive 主线契约。它要同时包含主角必须完成的具体目标、阻碍目标的对手或结构、失败代价、期限/机会窗口和持续反差；后续系统会把它投影到 core_motive，不要再另写一条不同的总目标。
其中的“主题”只回答这条故事最终要讨论或留下的人的命题、价值冲突和情感认识；主题字段只提炼意义，不能把核心动机换一种说法再写一遍。主题不要直接重复具体任务、金额、期限、对手、资源缺口或“主角必须完成某事”等执行信息；这些内容只写进主线矛盾。主题可以从核心动机中提炼意义，但不能替代核心动机，也不能反过来要求主角围绕抽象观点行动。

世界规则回答“这个世界怎样运转”。它写日常生活、空间和社会关系、异常或力量从哪里来、什么条件会让它发生、人物要为触碰它付出什么，以及不同人物会怎样应对。它只写长期成立的运行方式；没有明确力量体系的题材，世界规则就围绕空间、社会、异常和代价展开；明确有修炼或境界的题材，再写力量来源和总边界，详细层次统一放进设定库里的“规则”条目。

人物回答“这些人各自想得到或守住什么”。人物的欲望、顾虑、秘密、人物性格/特点、语言风格和与主角的关系，都要在原故事里找到根，并能在具体场景中推动选择。人物卡中的性格、语言和备注只保留长期资料，不写固定笑点、固定口头禅、具体道具或食物、固定动作、某章行为、出场桥段和临时反应；人物之间怎样靠近、利用、误会或翻脸，交给阶段和章节中的具体事情表现，不要把场景行为塞回人物卡。设定库统一收录后面会反复用到的地点、物件、制度、势力、能力边界和日常场景。伏笔写成现在能看见的线索、人物当下的理解，以及它在后续阶段会怎样改变判断、关系和行动；把正式故事内容写进 description、revealed 和 remaining_secret，notes 留空。普通伏笔必须能够在后续某个具体场景中完整回答一个明确问题，不能只写“真相更大”“影响深远”“未来会揭开”这类宽泛方向。

{CREATION_LORE_TYPE_GUIDANCE}

选定故事尚未确定的部分，保留为人物正在面对的问题、线索和可能解释；从故事自然延伸出来、后面反复会用到的人物、地点、势力、物件、制度和暗线，都补足为可落地的故事资料。字段值以清楚、稳定、方便后续执行为先，简介字段保持可公开发布的自然网络小说语言，其余内容像作者自己的故事底稿一样具体易读。

只输出一个合法 JSON 对象，使用短键和固定顺序数组：{{"b":["核心设定","读者承诺","主题","核心动机契约（主线矛盾）","人物关系底子","结尾方向","硬边界"],"w":["世界概况","力量或能力体系","长期规则数组","代价限制数组","地理与生活"],"c":[["姓名","身份和故事位置","当前目标","秘密","人物性格/特点","语言风格","害怕失去什么、与主角的长期关系底色和长期变化"]],"l":[["名称","类型","具体内容","人物当前知道多少"]],"f":[["编号","名称","埋设阶段","回收阶段","读者能看到的线索及后续变化","揭开后会改变什么","仍未揭开的部分"]]}}。实际输出时：b固定7项，其中第4项“核心动机契约（主线矛盾）”必须完整承载唯一的 core_motive 主线；w固定5项，c每项固定7项，l每项固定4项，f每项固定7项；人物字段只写长期资料，具体剧情动作留给阶段和章节；空内容保留空字符串占位，资料数量和文字事实完整保留。""",
    "story_assets": f"""{COMMON_CREATION_RULES}

接着前面已经确定的故事，把后面真的会反复出现的人物、地方、势力、物件、规矩和暗线写出来。每一项都要落到人物看得见、摸得着的生活里，并且在某一次选择中起作用；线索的意义随着人物行动、关系变化和局势变化逐步显现。

每个重要人物都要有自己想得到或守住的东西，有现实阻力，有不愿让别人知道的部分，也要有人物性格/特点和语言风格。人物性格/特点写长期稳定的性格底色，语言风格写可迁移的表达分类和习惯；性格、语言和 notes 都不写具体事件、食物、地点、道具、固定笑点、固定动作、固定口头禅、某一次剧情反应或固定触发模式。请把人物害怕失去什么、与主角的长期关系底色和会影响后文的长期变化，写进人物的 notes；具体怎样牵制、靠近、利用、误会或翻脸，要通过后面的场景和事件表现，不要提前写成人物卡里的动作脚本。

人物说明不要只停在身份标签：每个人的“身份和故事位置”以及“害怕失去什么、与主角的长期关系底色和长期变化”各用一两句写清正式身份、所属关系和与相近人物的区别；人物是组织代表时，要把“这个人”和“他代表的组织”分开写。具体剧情行为不要写进人物卡。

只补充后面真的会用到的地点、势力、组织、物品、能力规矩、制度、日常生活和反复出现的场景落点，统一写入 lore。身体代价随题材和现场需要自然出现。明确需要修炼、境界或能力层次的题材，在 lore 中建立“能力体系/规则”设定，并把详细层次、能做到什么、做不到什么和提升条件写进 description；悬疑、灵异、言情、现实和普通都市故事把设定落在空间、生活、社会关系和异常边界上。

{CREATION_LORE_TYPE_GUIDANCE}

设定的“具体内容”不要只写一个名词或口号，用一两句说明它是什么实体、正式名称、与人物或其它势力的关系、实际作用范围，以及和相近实体的区别。人物集合、势力集合、家族数量和婚约对象分别写清，不用含糊简称代替正式名称；没有资料依据的隶属、联姻和组织规模不要自行补成事实。

每条暗线都要落到一个具体细节上：它第一次怎样出现，人物当时怎样理解，后来会怎样改变某个人的判断或关系。每条暗线只保留一个核心问题和一个可观察的回收结果；揭示结果必须能直接回答这个问题并在场景中留下明确变化，不要把多个真相、幕后原因或未来方向合并成一条。线索可以保留不影响本部闭环的余波，正式故事内容全部写进 description、revealed 和 remaining_secret；notes 留空。

伏笔的说明用一两句写清线索实际指向的正式人物、势力、设定或关系：现在已经出现什么，人物目前怎样理解，后面会改变什么；同时必须能补出“回收时谁做了什么、读者确认了什么、当场留下什么结果”。当前只保留阶段位置，不提前写具体章号，也不要把人物或势力的基本身份重复伪装成伏笔。不能写成“某人真正身份”“某势力幕后目的”“某事件完整真相”这种没有单一验收点的宽泛标题；这类内容必须拆成一个具体问题，或留在主线、设定、人物长期资料中。

只输出一个合法 JSON 对象，使用短键和固定顺序数组：{{"c":[["姓名","身份和故事位置","当前目标","秘密","人物性格/特点","语言风格","害怕失去什么、与主角的长期关系底色和长期变化"]],"l":[["名称","类型","具体内容","人物当前知道多少"]],"f":[["编号","名称","埋设阶段","回收阶段","读者能看到的线索及后续变化","揭开后会改变什么","仍未揭开的部分"]]}}。c每项固定7项，l每项固定4项，f每项固定7项；人物字段只写长期资料，具体剧情动作留给阶段和章节；资料数量和文字事实完整保留。""",
}


STAGE_PLAN_OBJECT_OUTPUT_RULES = """
这次使用对象协议，阶段和事件按字段名归位；只返回一个合法 JSON 对象。
短键含义如下：k=全书底盘契约（其中的核心动机是唯一执行主线），s=当前阶段对象，f=当前阶段实际发生的伏笔端点。阶段对象中 i=阶段编号，n=阶段名称，r=章节范围，b=开始状态，e=按顺序发生的场景事件对象数组，x=结束状态，y=带入下一阶段的事实。状态对象中 t=时间，l=地点，c=人物状态，k=已经发生并被人物掌握的事实，q=仍会推动人物行动的问题。事件对象中 i=事件编号，r=允许章节范围，a=关联资料，p=前置条件，h=可直接扩写的场景事件，o=直接结果，d=实际状态变化。伏笔端点对象中 i=伏笔编号，k=setup或payoff，e=承载这个端点的事件编号，d=这一次在场景中发生的具体变化；一次只写一个端点。
每个 h 都要像一段可以直接扩写的剧情节点：只写这件事真正需要的故事事实，必要时交代人物、场景、动作、阻力、选择或结果，尽量不用固定清单式要求，不为凑齐项目硬塞字段。剧情发动机由题材和人物处境决定，可以是正面碰撞、追逐逃避、关系变化、欲望争夺、环境失控、能力试探、秘密暴露或其它自然发生的压力；相邻事件要让人物处境产生新的变化，不把这些方式排成固定轮换。资料只有在人物正在做事、被迫应对或关系发生变化时进入场景。
当前阶段发生的正式伏笔端点，都在承载事件的 a 中加入一次“F编号/setup”或“F编号/payoff”，并在 f 中用同一事件编号 e 关联。setup写线索第一次进入人物生活，payoff写线索在场景中产生决定性变化；同一条伏笔在其它事件中继续出现、深化、造成后果是正常的，这些事件只把它作为普通关联资料或写出“F编号”，不要重复标成正式 setup/payoff。程序以正式端点为准，再把后续事件中的具体变化交给章节规划继续使用；阶段之间允许继续铺开同一条暗线，程序会依据事件 r 的章节范围落下具体章号。
实际返回的 f 使用单端点格式，例如 {"i":"F06","k":"payoff","e":"E04","d":"人物在现场做出选择后，线索改变了什么"}。全书契约保留长期事实、世界运行方式、人物底色和结尾方向；伏笔通过 setup 与 payoff 表达它在场景中的进入、变化和意义显现。

返回结构示例（示例中的空数组和空字段实际可以省略）：{"v":"4","k":{"f":["不能改变的长期事实"],"w":["长期世界运行方式"],"c":["人物底色"],"e":["结尾方向"]},"s":{"i":"S05","n":"阶段名称","r":[137,167],"b":{"t":"时间","l":"地点","c":["人物处境"],"k":["已经发生并被人物掌握的事实"],"q":["仍会推动人物行动的问题"]},"e":[{"i":"E01","r":[137,140],"a":["F01/setup","关联资料"],"p":["前置条件"],"h":"时间、地点、人物、压力、动作、阻力、选择和现场结果组成的场景事件","o":"直接结果","d":["人物、关系、情绪或局势发生的实际变化"]}],"x":{"t":"结束时间","l":"结束地点","c":["结束时人物处境"],"k":["结束时已经发生的事实"],"q":["带入下一阶段的问题"]},"y":["带入下一阶段的事实"]},"f":[{"i":"F01","k":"setup","e":"E01","d":"线索在现场第一次出现并改变人物选择"}]}}。本次只生成当前阶段一个 s 对象，不要返回其它阶段；有意义的事实不能省略。
""".strip()

STEP_PROMPTS["stage_plan"] = f"""{COMMON_CREATION_RULES}

现在根据已经选定的故事和完整故事底盘，制作唯一的十万字阶段规划。这里的内容是给后续章节规划和正文扩写读取的执行资料，不是发布简介，也不需要写成文学化段落。总字数和单章字数完全按照作者输入；章节总数按 total_words / average_chapter_words 向上取整，最后一章吸收余数。每约十万字为一个阶段，阶段从第1章连续覆盖到最后一章，事件范围按顺序衔接。全书始终围绕唯一的 core_motive 推进：主角为了完成具体目标主动采取行动，剧情阻碍这条行动链，主角付出代价解决当前问题，结果再打开下一道目标；不能把阶段写成主角被动不断遇到新事情。
阶段字段不要抢全书主线：阶段的 main_conflict 只写本阶段阻碍核心动机的具体问题、门槛、对手动作或代价升级；阶段 summary/end_state 要说明本阶段目标如何推进，以及结果打开的下一阶段目标。不要在每个阶段重新发明一条“主角真正要做的事”，也不要把主题、人物关系或伏笔名称填成阶段主线。

阶段规划固定事实、顺序、状态和阶段推进，但剧情推进以场景为单位。每个事件写清本次真正发生、会影响后续的故事事实；时间、地点、人物、动作、阻力、选择、关系变化和结果等内容，只在当前事件确实需要时补充。事件之间通过人物正在做的事和已经发生的变化自然衔接。先判断这一事件真正由什么推动，再选择最适合题材的场景：人物对抗、关系变化、现场危机、公开行动、利益争夺、环境压力或信息出现都可以成为主发动机。相邻事件主动更换主发动机、场景目标和压力来源，让人物、关系、空间和局势持续变化。
同一事件如果覆盖数章，只承担一次明确的转折；前面的章节让事情发生，后面的章节写它造成的新反应、新选择、新损失、新关系变化或新阻力，不要把同一场谈话、同一份材料或同一个结论反复当成新的剧情。对都市灵异、惊悚、悬疑、情感等题材，声音、空间、物件、生活压力、人物之间的隐瞒和现场失控持续进入剧情；对其它题材，使用该题材自己的场景压力和人物对抗。故事的关键变化要发生在人物正在经历的场面里，而不是停在解释性结论上。

伏笔端点使用底盘已有编号或名称，关联到本阶段实际发生的事件；setup写线索第一次进入人物生活，payoff写线索在场景中完成单一核心问题的回答，并留下具体行动、对白、证据、关系结果或局势结果。payoff不能只写“进一步揭示”“冲突升级”“确认重要”“出现新线索”或“人物意识到事情不简单”，这些只是推进，不是回收。同一条伏笔可以在多个事件中继续出现、深化或影响人物选择，但正式 setup/payoff 只各自标记一次；后续事件用普通关联资料或“F编号”承接，不把每次提及都写成新的正式端点。阶段之间允许继续铺开同一条暗线，程序会依据事件的允许章节范围落下具体章号，模型只负责事件顺序和端点归属，不写具体章号。

{STAGE_PLAN_OBJECT_OUTPUT_RULES}
"""


def _compact_stage_plan_prompt(prompt):
    """让阶段事件只返回实际变化，避免每个事件重复六类空结构。"""
    text = str(prompt or "")
    text = text.replace(
        '["时间变化","地点变化数组","认知变化数组","关系变化数组","物件变化数组","新增问题数组"]',
        '"实际发生的状态变化"',
    )
    text = text.replace(
        '["时间变化数组","地点变化数组","认知变化数组","关系变化数组","物件变化数组","新增问题数组"]',
        '"实际发生的状态变化"',
    )
    text = text.replace(
        "状态变化固定6项",
        "状态变化只保留真正发生的事实，没有变化不写",
    )
    text = text.replace(
        "事件固定8项",
        "事件保留必要事实，状态变化只写实际变化",
    )
    if "实际发生的状态变化" in text and "没有变化不写" not in text:
        text += "\n状态变化只写真正发生的变化；没有变化的类别不要补空数组，也不要重复上一事件。"
    return text


def _as_text(value):
    return str(value or "").strip()


def _extract_requested_title(value):
    """Read a title only when the author marked it as a title explicitly."""
    text = _as_text(value)
    if not text:
        return ""

    # A standalone 《书名》 is unambiguous, and is common when authors paste
    # the title together with tags or a short introduction.
    bracketed = re.match(
        r"^\s*(《[^》]{1,120}》)(?=\s*(?:标签|题材|类型|简介|故事简介|灵感|风格)\s*[:：=]|\s*$)",
        text,
    )
    if bracketed:
        return _as_text(bracketed.group(1))

    # Keep the rest of the one-line inspiration free-form.  Only labels such
    # as “书名：” or “标题：” turn a part of it into a fixed title.
    labeled = re.search(
        r"(?:书名|作品名|小说名|标题)\s*[:：=]\s*"
        r"(?P<title>《[^》]{1,120}》|.*?)"
        r"(?=\s*(?:标签|题材|类型|简介|故事简介|灵感|风格|主角|读者方向|篇幅|字数)\s*[:：=]|$)",
        text,
    )
    if not labeled:
        return ""
    title = _as_text(labeled.group("title"))
    return title.strip(" \t,，;；|。")


def _creation_requested_title(inspiration, project_name_hint=""):
    """Return the author's fixed title without treating free-form inspiration as one."""
    text = _as_text(inspiration)
    title = _extract_requested_title(text)
    if title:
        return title
    hint = _as_text(project_name_hint)
    # A draft opened with a project hint starts with that exact text in the
    # inspiration field.  Do not use the hint after the author replaces it
    # with a different free-form inspiration.
    if hint and text == hint:
        return hint
    return ""


def _creation_merge_display_parts(*values):
    """Merge visible labels while keeping the longer, more informative part."""
    parts = []
    for value in values:
        for item in re.split(r"[，,、；;|/]+", _as_text(value)):
            item = item.strip()
            if not item:
                continue
            replaced = False
            for index, existing in enumerate(parts):
                if item == existing or item in existing:
                    replaced = True
                    break
                if existing in item:
                    parts[index] = item
                    replaced = True
                    break
            if not replaced:
                parts.append(item)
    return "，".join(parts)


def _creation_audience_label(value):
    text = _as_text(value)
    if "女频" in text and "男频" in text:
        return "男女皆宜"
    if "女频" in text:
        return "女频"
    if "男频" in text:
        return "男频"
    return text


def creation_meta_display_values(premise, existing_genre="", existing_style=""):
    """Project wizard choices into the two compact metadata fields in the main UI.

    The complete choices remain in ``creation_framework.premise``.  These two
    values are only the readable summary shown in the project header.
    """
    premise = premise if isinstance(premise, dict) else {}
    genre = _creation_merge_display_parts(
        _creation_audience_label(premise.get("audience")),
        premise.get("genre"),
        premise.get("theme"),
        existing_genre,
    )
    style = _creation_merge_display_parts(
        premise.get("style"),
        premise.get("story_engine"),
        existing_style,
    )
    return {"genre": genre, "style": style}


def _creation_name_key(value):
    """Normalize a name only for de-duplication; keep the displayed name intact."""
    return re.sub(r"[\s·•．.\-—_]+", "", _as_text(value)).lower()


def _creation_clean_name(value):
    value = _as_text(value).strip(" \t\r\n\"'“”‘’「」『』：:，,。；;、()（）[]【】")
    if not value or len(value) > 16:
        return ""
    if value in {"主角", "男主", "女主", "人物", "主角姓名", "姓名"}:
        return ""
    return value


def _creation_premise_name(value):
    """Extract only the likely protagonist name from a premise field.

    The first-step schema intentionally keeps protagonist as a natural sentence,
    so this is a small history hint rather than a rewrite of the model result.
    """
    text = _as_text(value)
    if not text:
        return ""
    patterns = (
        r"(?:主角|男主|女主)(?:的名字|姓名|叫作|叫做|叫|是)?[：:\s]*([\u4e00-\u9fff]{2,4})",
        r"(?:名字|姓名)[：:\s]*([\u4e00-\u9fff]{2,4})",
    )
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return _creation_clean_name(match.group(1))
    match = re.match(r"[\"“‘「『]?([\u4e00-\u9fff]{2,4})(?=是|为|叫|，|。|；|：|,|:|;|、|\s|$)", text)
    if match:
        return _creation_clean_name(match.group(1))
    age_pattern = r"(?:\d{1,3}|[零一二三四五六七八九十百千万]{1,5})岁"
    for length in range(2, 5):
        prefix = text[:length]
        suffix = text[length:].lstrip()
        if re.match(age_pattern, suffix):
            return _creation_clean_name(prefix)
    match = re.match(r"[\"“‘「『]?([\u4e00-\u9fff]{2,4})(?=[，。；：,:;、\s\d岁]|$)", text)
    return _creation_clean_name(match.group(1)) if match else ""


def _creation_character_names(records):
    if not isinstance(records, list):
        return []
    marked = []
    fallback = []
    for item in records:
        if not isinstance(item, dict):
            continue
        name = _creation_clean_name(item.get("name"))
        if not name:
            continue
        fallback.append(name)
        role = _as_text(item.get("role"))
        if any(marker in role for marker in ("主角", "男主", "女主")):
            marked.append(name)
    return marked or fallback[:1]


def _creation_project_protagonist_names(payload):
    if not isinstance(payload, dict):
        return []
    names = _creation_character_names(payload.get("characters"))
    if names:
        return names
    framework = payload.get("creation_framework")
    if isinstance(framework, dict):
        names = _creation_character_names(framework.get("characters"))
    return names


def _creation_history_records(payload):
    if not isinstance(payload, dict):
        return []
    records = payload.get("records", [])
    if not isinstance(records, list):
        return []
    result = []
    for item in records:
        if isinstance(item, dict):
            name = _creation_clean_name(item.get("name"))
        else:
            name = _creation_clean_name(item)
        if name:
            result.append({
                "name": name,
                "created_at_ns": int(item.get("created_at_ns", 0) or 0)
                if isinstance(item, dict)
                else 0,
            })
    return result


def _bootstrap_creation_name_history():
    """Index existing projects once, without loading their story text into AI context."""
    data = load_json_file(CREATION_WIZARD_NAME_HISTORY_FILE, {})
    if not isinstance(data, dict):
        data = {}
    records = _creation_history_records(data)
    if data.get("project_scan_complete"):
        return records

    project_dir = os.path.join(HISTORY_DIR, "novel_projects")
    try:
        paths = [
            os.path.join(project_dir, name)
            for name in os.listdir(project_dir)
            if name.endswith(".json") and not name.startswith(".")
        ]
    except OSError:
        paths = []
    paths.sort(
        key=lambda path: os.path.getmtime(path) if os.path.exists(path) else 0,
        reverse=True,
    )
    for path in paths:
        payload = load_json_file(path, {})
        for name in _creation_project_protagonist_names(payload):
            records.append({"name": name, "created_at_ns": 0})

    draft_dir = CREATION_WIZARD_DRAFT_DIR
    try:
        draft_paths = [
            os.path.join(draft_dir, name)
            for name in os.listdir(draft_dir)
            if name.startswith("draft-") and name.endswith(".json")
        ]
    except OSError:
        draft_paths = []
    for path in draft_paths:
        payload = load_json_file(path, {})
        candidates = payload.get("premise_candidates", []) if isinstance(payload, dict) else []
        for candidate in candidates if isinstance(candidates, list) else []:
            if isinstance(candidate, dict):
                name = _creation_premise_name(candidate.get("protagonist"))
                if name:
                    records.append({"name": name, "created_at_ns": 0})
        step_results = payload.get("step_results", {}) if isinstance(payload, dict) else {}
        bible = step_results.get("bible", {}) if isinstance(step_results, dict) else {}
        for name in _creation_character_names(bible.get("characters") if isinstance(bible, dict) else []):
            records.append({"name": name, "created_at_ns": 0})

    data["schema_version"] = 1
    data["project_scan_complete"] = True
    data["records"] = records[-CREATION_WIZARD_NAME_HISTORY_LIMIT:]
    save_json_file(CREATION_WIZARD_NAME_HISTORY_FILE, data)
    return _creation_history_records(data)


def _creation_name_references(current_names=None):
    records = _bootstrap_creation_name_history()
    data = load_json_file(CREATION_WIZARD_NAME_HISTORY_FILE, {})
    records.extend(_creation_history_records(data))
    ordered = []
    seen = set()
    for item in list(current_names or []) + list(reversed(records)):
        name = _creation_clean_name(item.get("name") if isinstance(item, dict) else item)
        key = _creation_name_key(name)
        if not name or not key or key in seen:
            continue
        seen.add(key)
        ordered.append(name)
        if len(ordered) >= CREATION_WIZARD_NAME_REFERENCE_LIMIT:
            break
    surnames = []
    surname_seen = set()
    for name in ordered:
        surname = name[0] if len(name) >= 2 and re.match(r"[\u4e00-\u9fff]", name[0]) else ""
        if surname and surname not in surname_seen:
            surname_seen.add(surname)
            surnames.append(surname)
    result = {}
    if ordered:
        result["recent_protagonist_names"] = ordered
    if surnames:
        result["recent_surnames"] = surnames[:18]
    return result


def remember_creation_wizard_names(names, source="premise"):
    values = []
    seen = set()
    for value in names if isinstance(names, (list, tuple, set)) else [names]:
        name = _creation_clean_name(value)
        key = _creation_name_key(name)
        if name and key and key not in seen:
            seen.add(key)
            values.append(name)
    if not values:
        return
    data = load_json_file(CREATION_WIZARD_NAME_HISTORY_FILE, {})
    if not isinstance(data, dict):
        data = {}
    records = _creation_history_records(data)
    created_at_ns = time.time_ns()
    existing = {_creation_name_key(item.get("name")): item for item in records}
    for name in values:
        existing[_creation_name_key(name)] = {
            "name": name,
            "source": _as_text(source) or "premise",
            "created_at_ns": created_at_ns,
        }
    data["schema_version"] = 1
    data["project_scan_complete"] = bool(data.get("project_scan_complete"))
    data["records"] = list(existing.values())[-CREATION_WIZARD_NAME_HISTORY_LIMIT:]
    save_json_file(CREATION_WIZARD_NAME_HISTORY_FILE, data)


def _creation_wizard_draft_path(draft_id):
    safe_id = re.sub(r"[^A-Za-z0-9_.-]+", "_", _as_text(draft_id)).strip("._")
    if not safe_id:
        return ""
    return os.path.join(CREATION_WIZARD_DRAFT_DIR, f"draft-{safe_id}.json")


def _new_creation_wizard_draft_id():
    # Creation time is the visible identity rule; the short suffix only
    # prevents collisions when two projects are created in one clock tick.
    return f"{time.time_ns()}-{uuid.uuid4().hex[:8]}"


def _creation_wizard_index():
    data = load_json_file(CREATION_WIZARD_DRAFT_INDEX_FILE, {})
    if not isinstance(data, dict):
        data = {}
    drafts = data.get("drafts", [])
    data["drafts"] = [item for item in drafts if isinstance(item, dict)] if isinstance(drafts, list) else []
    data.setdefault("schema_version", 1)
    data.setdefault("legacy_migrated", False)
    return data


def _creation_wizard_step_summary(payload):
    try:
        step_index = max(
            0,
            min(
                int(payload.get("current_step_index", 0) or 0),
                len(CREATION_WIZARD_STEPS) - 1,
            ),
        )
    except (TypeError, ValueError):
        step_index = 0
    step, title = CREATION_WIZARD_STEPS[step_index]
    results = payload.get("step_results", {})
    result = results.get(step, {}) if isinstance(results, dict) else {}
    state = result.get("_generation_state", {}) if isinstance(result, dict) else {}
    status = _as_text(state.get("status")).lower() if isinstance(state, dict) else ""
    if step == "bible" and status == "partial":
        completed = state.get("completed_batches", []) if isinstance(state, dict) else []
        return "故事底盘 · 第二批" if "bible_core" in completed else "故事底盘 · 第一批"
    if step == "stage_plan":
        stage_plan = result.get("stage_plan", []) if isinstance(result, dict) else []
        first_missing, _stage_by_index = _stage_plan_progress(
            stage_plan,
            _expected_stage_count(payload.get("target_words", 500000)),
        )
        if first_missing is not None:
            return f"十万字阶段规划 · 第{first_missing + 1}阶段"
        if status == "partial":
            # Keep the old fallback for malformed/legacy drafts whose stage
            # records cannot be inspected, but never prefer a stale complete
            # counter when actual stage content says otherwise.
            try:
                next_stage = int(state.get("next_stage_index", 0) or 0) + 1
            except (TypeError, ValueError):
                next_stage = 1
            return f"十万字阶段规划 · 第{next_stage}阶段"
    if isinstance(result, dict) and result:
        return f"{title} · 已保存"
    return title


def _creation_wizard_summary(payload):
    payload = payload if isinstance(payload, dict) else {}
    try:
        step_index = max(
            0,
            min(
                int(payload.get("current_step_index", 0) or 0),
                len(CREATION_WIZARD_STEPS) - 1,
            ),
        )
    except (TypeError, ValueError):
        step_index = 0
    premise_result = payload.get("step_results", {}).get("premise", {})
    candidates = premise_result.get("candidates", []) if isinstance(premise_result, dict) else []
    try:
        selected_index = int(premise_result.get("selected_index", 0) or 0)
    except (TypeError, ValueError):
        selected_index = 0
    selected = (
        candidates[selected_index]
        if isinstance(candidates, list) and 0 <= selected_index < len(candidates)
        and isinstance(candidates[selected_index], dict)
        else {}
    )
    title = (
        _as_text(selected.get("title"))
        or _as_text(payload.get("project_name_hint"))
        or "未命名项目"
    )
    created_at = _as_text(payload.get("created_at")) or "创建时间未知"
    try:
        created_at_ns = int(payload.get("created_at_ns", 0) or 0)
    except (TypeError, ValueError):
        created_at_ns = 0
    completion_status = _as_text(payload.get("completion_status")).lower()
    is_completed = completion_status in {"completed", "complete", "已完成"} or bool(
        _as_text(payload.get("completed_at"))
    )
    return {
        "draft_id": _as_text(payload.get("draft_id")),
        "title": title,
        "created_at": created_at,
        "created_at_ns": created_at_ns,
        "updated_at": _as_text(payload.get("updated_at")),
        "step": _creation_wizard_step_summary(payload),
        "current_step_index": step_index,
        "completion_status": "completed" if is_completed else "in_progress",
        "status_label": "已完成" if is_completed else "进行中",
        "completed_at": _as_text(payload.get("completed_at")),
        "imported_project_path": _as_text(payload.get("imported_project_path")),
    }


def _save_creation_wizard_index(index):
    index = index if isinstance(index, dict) else {"schema_version": 1, "drafts": []}
    index["schema_version"] = 1
    index["drafts"] = [item for item in index.get("drafts", []) if isinstance(item, dict)]
    save_json_file(CREATION_WIZARD_DRAFT_INDEX_FILE, index)


def _migrate_legacy_creation_wizard_draft():
    """Move the former single draft into the multi-draft store once."""
    index = _creation_wizard_index()
    if index.get("legacy_migrated"):
        return index
    index["legacy_migrated"] = True
    legacy = load_json_file(CREATION_WIZARD_DRAFT_FILE, {})
    if isinstance(legacy, dict) and (
        legacy.get("premise_candidates")
        or legacy.get("step_results")
        or _as_text(legacy.get("inspiration"))
    ):
        try:
            created_ns = int(os.stat(CREATION_WIZARD_DRAFT_FILE).st_mtime_ns)
        except (OSError, AttributeError):
            created_ns = time.time_ns()
        draft_id = f"{created_ns}-{uuid.uuid4().hex[:8]}"
        migrated = deepcopy(legacy)
        migrated["draft_id"] = draft_id
        migrated["created_at"] = _as_text(migrated.get("created_at")) or now_str()
        migrated["created_at_ns"] = int(migrated.get("created_at_ns", created_ns) or created_ns)
        migrated["updated_at"] = now_str()
        path = _creation_wizard_draft_path(draft_id)
        save_json_file(path, migrated)
        index["drafts"] = [
            item for item in index.get("drafts", [])
            if _as_text(item.get("draft_id")) != draft_id
        ]
        index["drafts"].append(_creation_wizard_summary(migrated))
    _save_creation_wizard_index(index)
    return index


def list_creation_wizard_drafts():
    """Return saved wizard projects, including completed records."""
    _migrate_legacy_creation_wizard_draft()
    index = _creation_wizard_index()
    records = {}
    for item in index.get("drafts", []):
        draft_id = _as_text(item.get("draft_id"))
        if draft_id:
            records[draft_id] = deepcopy(item)
    try:
        names = os.listdir(CREATION_WIZARD_DRAFT_DIR)
    except OSError:
        names = []
    for name in names:
        if not name.startswith("draft-") or not name.endswith(".json"):
            continue
        payload = load_json_file(os.path.join(CREATION_WIZARD_DRAFT_DIR, name), {})
        if not isinstance(payload, dict):
            continue
        summary = _creation_wizard_summary(payload)
        draft_id = _as_text(summary.get("draft_id"))
        if draft_id:
            records[draft_id] = summary
    return sorted(
        records.values(),
        key=lambda item: (
            int(item.get("created_at_ns", 0) or 0),
            _as_text(item.get("draft_id")),
        ),
        reverse=True,
    )


def create_creation_wizard_draft(project_name_hint=""):
    created_at_ns = time.time_ns()
    draft_id = f"{created_at_ns}-{uuid.uuid4().hex[:8]}"
    payload = {
        "schema_version": 3,
        "draft_id": draft_id,
        "created_at": now_str(),
        "created_at_ns": created_at_ns,
        "updated_at": now_str(),
        "project_name_hint": _as_text(project_name_hint),
        "current_step_index": 0,
        "choice_values": {},
        "inspiration": "",
        "target_words": 500000,
        "average_words": 3000,
        "premise_candidates": [],
        "premise_selected_index": 0,
        "step_results": {},
    }
    save_creation_wizard_draft(payload)
    return draft_id


def load_creation_wizard_draft(draft_id):
    _migrate_legacy_creation_wizard_draft()
    path = _creation_wizard_draft_path(draft_id)
    data = load_json_file(path, {}) if path else {}
    return data if isinstance(data, dict) else {}


def save_creation_wizard_draft(payload):
    _migrate_legacy_creation_wizard_draft()
    payload = deepcopy(payload) if isinstance(payload, dict) else {}
    draft_id = _as_text(payload.get("draft_id")) or _new_creation_wizard_draft_id()
    payload["draft_id"] = draft_id
    payload.setdefault("created_at", now_str())
    payload.setdefault("created_at_ns", time.time_ns())
    payload["updated_at"] = now_str()
    path = _creation_wizard_draft_path(draft_id)
    if not path:
        return ""
    save_json_file(path, payload)
    index = _creation_wizard_index()
    index["legacy_migrated"] = True
    summaries = [
        item for item in index.get("drafts", [])
        if _as_text(item.get("draft_id")) != draft_id
    ]
    summaries.append(_creation_wizard_summary(payload))
    index["drafts"] = summaries
    _save_creation_wizard_index(index)
    return path


def delete_creation_wizard_draft(draft_id):
    path = _creation_wizard_draft_path(draft_id)
    if path:
        safe_remove_file(path)
    index = _creation_wizard_index()
    index["drafts"] = [
        item for item in index.get("drafts", [])
        if _as_text(item.get("draft_id")) != _as_text(draft_id)
    ]
    _save_creation_wizard_index(index)


def mark_creation_wizard_draft_completed(draft_id, project_path="", result_payload=None):
    """Keep a finished wizard draft as a completed, inspectable archive."""
    draft_id = _as_text(draft_id)
    if not draft_id:
        return ""
    payload = load_creation_wizard_draft(draft_id)
    if not isinstance(payload, dict) or not payload:
        return ""
    payload["completion_status"] = "completed"
    payload["completed_at"] = now_str()
    project_path = _as_text(project_path)
    if project_path:
        payload["imported_project_path"] = os.path.abspath(project_path)
    if isinstance(result_payload, dict):
        payload["completed_result_payload"] = deepcopy(result_payload)
    return save_creation_wizard_draft(payload)


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


def _strip_leading_field_label(value, labels):
    """去掉模型把字段提示词重复写进正文的情况。"""
    text = _as_text(value)
    if not text:
        return ""
    for label in labels:
        label = _as_text(label).rstrip("：:")
        if not label:
            continue
        prefix = label + "："
        if text.startswith(prefix):
            return text[len(prefix):].lstrip()
        prefix = label + ":"
        if text.startswith(prefix):
            return text[len(prefix):].lstrip()
    return text


def _clean_character_notes(value):
    text = _as_text(value)
    if not text:
        return ""
    empty_labels = {"害怕失去：", "害怕失去:", "与主角关系：", "与主角关系:", "长期变化：", "长期变化:"}
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip() and line.strip() not in empty_labels
    ]
    return "\n".join(lines).strip()


def _has_creation_content(value):
    if isinstance(value, dict):
        return any(_has_creation_content(child) for child in value.values())
    if isinstance(value, (list, tuple, set)):
        return any(_has_creation_content(child) for child in value)
    return bool(_as_text(value))


def _creation_stage_index(value):
    """Return the zero-based stage index encoded by an id such as ``S03``."""
    match = re.fullmatch(r"S[_-]?(\d{1,4})", _as_text(value).upper())
    if not match:
        return -1
    try:
        return max(0, int(match.group(1)) - 1)
    except (TypeError, ValueError):
        return -1


def _stage_has_meaningful_content(stage):
    """A stage is complete only when every saved event is executable."""
    if not isinstance(stage, dict) or not _as_text(stage.get("name")):
        return False
    events = stage.get("ordered_events", [])
    if not isinstance(events, list) or not events:
        return False
    for event_index, event in enumerate(events, 1):
        if not (
            isinstance(event, dict)
            and _as_text(event.get("event"))
            and _as_text(event.get("result"))
        ):
            return False
        event_id = _as_text(event.get("id")).upper()
        match = re.search(r"E[_-]?(\d+)$", event_id)
        if match is None or int(match.group(1)) != event_index:
            return False
    return True


def _validate_stage_batch_events(stage, stage_index, spec):
    """Reject a structurally incomplete stage before it can replace saved data."""
    if not isinstance(stage, dict):
        raise ValueError(f"第{stage_index + 1}阶段没有返回有效的阶段结构，本次未保存。")
    events = stage.get("ordered_events", [])
    if not isinstance(events, list) or not events:
        raise ValueError(
            f"第{stage_index + 1}阶段没有返回完整的剧情事件，本次未保存；请重新生成。"
        )

    start_chapter = int(spec.get("start_chapter", 0) or 0)
    end_chapter = int(spec.get("end_chapter", 0) or 0)
    problems = []
    # ``allowed_chapters`` is an anchor window, not an exclusive slice.  The
    # next event may begin inside the previous window (for example [1, 2]
    # followed by [2, 4]); only a backwards range or an uncovered chapter
    # should make the stage invalid.
    previous_start = start_chapter
    previous_end = start_chapter - 1
    for event_index, event in enumerate(events, 1):
        label = f"第{event_index}个事件"
        if not isinstance(event, dict):
            problems.append(f"{label}不是有效事件结构")
            continue
        if not _as_text(event.get("event")):
            problems.append(f"{label}缺少具体事件")
        if not _as_text(event.get("result")):
            problems.append(f"{label}缺少直接结果")
        event_id = _as_text(event.get("id")).upper()
        event_match = re.search(r"E[_-]?(\d+)$", event_id)
        if event_match is None or int(event_match.group(1)) != event_index:
            problems.append(f"{label}的编号不连续，应为E{event_index:02d}")
        allowed = event.get("allowed_chapters", [])
        if not isinstance(allowed, (list, tuple)) or len(allowed) < 2:
            problems.append(f"{label}缺少允许章节范围")
            continue
        try:
            allowed_start = int(allowed[0])
            allowed_end = int(allowed[1])
        except (TypeError, ValueError):
            problems.append(f"{label}的章节范围不是有效整数")
            continue
        if (
            allowed_start < start_chapter
            or allowed_end > end_chapter
            or allowed_start > allowed_end
        ):
            problems.append(
                f"{label}超出本阶段第{start_chapter}—{end_chapter}章范围"
            )
        else:
            if event_index == 1 and allowed_start != start_chapter:
                problems.append(
                    f"{label}没有从本阶段第{start_chapter}章开始"
                )
            elif event_index > 1 and allowed_start < previous_start:
                problems.append(
                    f"{label}的起始章节早于前一个事件，事件顺序倒退"
                )
            elif event_index > 1 and allowed_start > previous_end + 1:
                problems.append(
                    f"{label}与前一个事件之间存在未覆盖章节"
                )
            if event_index > 1 and allowed_end < previous_end:
                problems.append(
                    f"{label}的结束章节早于前一个事件，事件范围倒退"
                )
            previous_start = allowed_start
            previous_end = max(previous_end, allowed_end)

    if previous_end != end_chapter:
        problems.append(
            f"事件范围没有完整覆盖本阶段第{start_chapter}—{end_chapter}章"
        )

    if problems:
        detail = "；".join(problems[:4])
        if len(problems) > 4:
            detail += f"；另有{len(problems) - 4}处问题"
        raise ValueError(
            f"第{stage_index + 1}阶段返回内容不完整：{detail}。"
            "本次未保存当前阶段，请重新生成。"
        )


def _stage_plan_progress(stage_plan, stage_count):
    """Return the first missing stage without trusting list position or state."""
    try:
        stage_count = max(0, int(stage_count))
    except (TypeError, ValueError):
        stage_count = 0
    by_index = {}
    positional = []
    for item in stage_plan if isinstance(stage_plan, list) else []:
        if not isinstance(item, dict):
            continue
        index = _creation_stage_index(item.get("id"))
        if 0 <= index < stage_count:
            previous = by_index.get(index)
            if previous is None or (
                _stage_has_meaningful_content(item)
                and not _stage_has_meaningful_content(previous)
            ):
                by_index[index] = item
        else:
            positional.append(item)

    # Only use positional fallback for records with no usable stage id.  A
    # record explicitly marked S04 must never be moved into the S02 slot.
    free_indexes = [index for index in range(stage_count) if index not in by_index]
    for item, index in zip(positional, free_indexes):
        by_index[index] = item

    first_missing = next(
        (
            index
            for index in range(stage_count)
            if not _stage_has_meaningful_content(by_index.get(index))
        ),
        None,
    )
    return first_missing, by_index


_EXPLICIT_POWER_GENRE_MARKERS = (
    "玄幻", "仙侠", "修真", "高武", "武侠", "武道", "魔法",
    "异世界", "西幻", "奇幻", "灵气", "修炼", "境界",
)


def story_requires_explicit_power_levels(*values):
    """只对明确存在修炼/境界体系的题材保留详细能力层次。"""
    text_parts = []
    for value in values:
        if isinstance(value, dict):
            text_parts.extend(str(item) for item in value.values())
        elif isinstance(value, (list, tuple, set)):
            text_parts.extend(str(item) for item in value)
        elif value not in (None, ""):
            text_parts.append(str(value))
    text = " ".join(text_parts).lower()
    return any(marker.lower() in text for marker in _EXPLICIT_POWER_GENRE_MARKERS)


def _normalize_ability_system(value, allow_power_levels):
    if not isinstance(value, dict) or not allow_power_levels:
        return {
            "enabled": False,
            "name": "",
            "description": "",
            "levels": [],
            "limits": [],
        }
    levels = []
    for item in _as_list(value.get("levels")):
        if not isinstance(item, dict):
            continue
        levels.append({
            "name": _as_text(_first_value(item, ("name", "level", "境界", "层次"))),
            "capability": _as_text(_first_value(item, ("capability", "能做到", "能力"))),
            "limit": _as_text(_first_value(item, ("limit", "不能做到", "边界"))),
            "promotion": _as_text(_first_value(item, ("promotion", "提升", "如何变强"))),
        })
    return {
        "enabled": bool(value.get("enabled", bool(levels))),
        "name": _as_text(_first_value(value, ("name", "title", "名称", "体系名称"))),
        "description": _as_text(_first_value(value, ("description", "summary", "说明"))),
        "levels": levels,
        "limits": [
            _as_text(item)
            for item in _as_list(value.get("limits"))
            if _as_text(item)
        ],
    }


_BIBLE_FIELDS = (
    "core_setting",
    "reader_promise",
    "theme",
    "main_conflict",
    "relationship_foundation",
    "ending_direction",
    "hard_boundaries",
)

_BIBLE_FIELD_ALIASES = {
    "core_setting": (
        "core_setting", "story_core", "core", "核心设定", "故事核心",
        "小说核心", "核心内容", "故事真正要讲的东西",
    ),
    "reader_promise": (
        "reader_promise", "core_reader_promise", "读者承诺", "读者期待",
        "读者追问", "读者会一直追问", "读者会一直想知道的事",
        "读者关心的问题",
    ),
    "theme": ("theme", "主题", "故事主题", "故事想留下的东西", "故事想说的话"),
    "main_conflict": (
        "main_conflict", "core_conflict", "主线矛盾", "核心冲突",
        "主要矛盾", "最重要的矛盾",
    ),
    "relationship_foundation": (
        "relationship_foundation", "relationship_base", "关系基础", "人物关系",
        "人物关系底子", "重要人物关系的起点",
    ),
    "ending_direction": (
        "ending_direction", "ending", "结尾方向", "结局方向",
        "结尾留下的方向",
    ),
    "hard_boundaries": (
        "hard_boundaries", "boundaries", "硬边界", "必须守住的边界",
        "不能改变的事实", "不能违背的写法",
    ),
}

_WORLD_RULE_FIELD_ALIASES = {
    "setting_overview": (
        "setting_overview", "overview", "世界概况", "世界样貌",
        "这个世界的样子", "世界的基本样貌", "世界规则概况", "时代背景",
    ),
    "power_system": (
        "power_system", "ability_rules", "力量体系", "能力规则",
        "能力边界", "力量和能力的边界", "力量和能力的规矩",
    ),
    "geography_and_life": (
        "geography_and_life", "geography", "daily_life", "地理与生活",
        "地点和生活", "重要地点和日常生活", "空间和日常生活",
    ),
}

_CHARACTER_FIELD_ALIASES = {
    "name": ("name", "character_name", "姓名", "人物"),
    "role": (
        "role", "identity", "身份", "人物身份", "角色", "角色定位",
    ),
    "goal": (
        "goal", "desire", "want", "目标", "人物目标", "想要",
    ),
    "secret": (
        "secret", "hidden_secret", "秘密", "隐藏秘密", "隐瞒",
    ),
    "personality": (
        "personality", "traits", "character_traits", "character_personality",
        "人物性格", "人物特点", "性格特点", "人物性格/特点", "性格/特点",
    ),
    "voice": (
        "voice", "speech", "language_style", "speaking_style", "tone",
        "语言风格", "说话风格", "说话方式", "口吻", "语气",
    ),
    "notes": ("notes", "备注", "人物备注", "后续注意"),
}

_CHARACTER_NAME_ROLE_MARKERS = (
    "董事长", "继承人", "经纪人", "负责人", "未婚夫", "未婚妻", "经纪",
    "大伯母", "大伯父", "继父", "继母", "养父", "养母", "祖父", "祖母",
    "外公", "外婆", "爷爷", "奶奶", "姑姑", "姑妈", "舅舅", "舅妈",
    "叔叔", "婶婶", "伯伯", "父亲", "母亲", "爸爸", "妈妈", "丈夫", "妻子",
    "前夫", "前妻", "老公", "老婆", "大姑", "二姑", "三姑", "小姑",
    "大姨", "二姨", "三姨", "小姨", "大叔", "二叔", "三叔", "小叔",
    "大伯", "二伯", "三伯", "婶母", "姨母", "舅父", "伯父", "伯母",
    "堂哥", "堂姐", "表哥", "表姐", "哥哥", "姐姐", "弟弟", "妹妹",
    "兄长", "师兄", "师姐", "师弟", "师妹", "师父", "师傅", "长辈", "亲戚",
    "家长", "儿子", "女儿", "前辈", "后辈", "太太", "夫人", "先生", "小姐",
    "少爷", "公子", "姑娘", "掌门", "长老", "皇后", "皇帝", "王爷", "公主",
    "太子", "殿下", "大人", "将军", "统领", "老师", "班主任", "校长", "医生",
    "护士", "律师", "法官", "警察", "记者", "老板", "经理", "总监", "董事",
    "秘书", "助理", "管家", "保姆", "司机", "店长", "店员", "邻居", "同学",
    "同事", "朋友", "闺蜜", "教练", "编辑", "作者", "导演", "演员", "教授",
    "院长", "主任", "院士", "专家", "顾问", "保镖", "掌柜", "代表", "的人",
    "父", "母", "姑", "姨", "叔", "舅", "伯", "婶",
)


def _split_character_name_role_prefix(name, role):
    """Split an obvious title/identity prefix from a formal Chinese name.

    This deliberately accepts only prefixes ending in a known relationship or
    role marker. A standalone title such as ``陶大姑`` and ordinary names are
    left untouched.
    """
    name = _as_text(name)
    role = _as_text(role)
    if not name:
        return name, role
    markers = tuple(sorted(_CHARACTER_NAME_ROLE_MARKERS, key=len, reverse=True))
    # Three-character names are the common case. Trying them before two- and
    # four-character names avoids treating a shorter marker inside a longer
    # identity description as the boundary.
    for name_length in (3, 2, 4):
        if len(name) <= name_length:
            continue
        prefix = name[:-name_length]
        formal_name = name[-name_length:]
        if not all("一" <= char <= "龥" for char in formal_name):
            continue
        if not any(prefix.endswith(marker) for marker in markers):
            continue
        break
    else:
        return name, role
    prefix = prefix.strip(" \t\r\n:：,，、-/")
    if not prefix or not formal_name:
        return name, role
    if prefix not in role:
        role = "，".join(part for part in (prefix, role) if part)
    return formal_name, role

_LORE_FIELD_ALIASES = {
    "name": ("name", "title", "名称", "设定名"),
    "type": ("type", "category", "类别", "类型"),
    "description": ("description", "detail", "具体内容", "具体情况", "说明"),
    "story_known": (
        "story_known", "known", "已知情况", "人物已知", "人物现在知道多少",
    ),
}

_FORESHADOW_FIELD_ALIASES = {
    "code": ("code", "id", "编号", "伏笔编号"),
    "name": ("name", "title", "名称", "伏笔"),
    "status": ("status", "状态"),
    "setup_stage": (
        "setup_stage", "埋设阶段", "埋下阶段", "出现阶段",
        "暗线出现的位置",
    ),
    "payoff_stage": (
        "payoff_stage", "回收阶段", "变化阶段", "暗线发生变化的位置",
    ),
    "setup_chapter": (
        "setup_chapter", "setup", "埋设章节", "埋下章节",
    ),
    "payoff_chapter": (
        "payoff_chapter", "payoff", "回收章节", "揭示章节",
    ),
    "description": ("description", "detail", "具体内容", "线索", "暗线"),
    "revealed": ("revealed", "reveal", "揭示结果", "揭开后", "以后揭开的事实"),
    "remaining_secret": (
        "remaining_secret", "unknown", "剩余秘密", "仍未揭开", "还藏着的部分",
    ),
    "notes": ("notes", "备注", "后续注意"),
}


def _normalize_text_list(value):
    return [
        _as_text(item)
        for item in _as_list(value)
        if _as_text(item)
    ]


def _normalize_world_rule_list(value, labels=()):
    """Read a world-rule list from either JSON arrays or compact text.

    The wizard asks for fixed-position arrays to keep responses small. Some
    models still put the numbered items into one string in that array slot,
    e.g. ``"长期规则数组：1.... 2...."``. Treating that valid content as an
    empty list made the UI report a false "missing rules" error. This helper
    only expands that transport quirk; it does not invent or discard facts.
    """
    if isinstance(value, (list, tuple)):
        return [
            _as_text(item)
            for item in value
            if _as_text(item)
        ]
    text = _as_text(value)
    if not text:
        return []
    text = _strip_leading_field_label(text, labels)
    matches = list(
        re.finditer(
            r"(?:^|[\s；;。！？!?])(?:\d+)[.、)）:]\s*",
            text,
        )
    )
    if len(matches) >= 2:
        items = []
        for index, match in enumerate(matches):
            start = match.end()
            end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
            item = text[start:end].strip(" \t\r\n；;、")
            if item:
                items.append(item)
        if items:
            return items
    return [text]


def _normalize_text_record(value, fields, aliases):
    if isinstance(value, str):
        return {
            fields[0]: _strip_leading_field_label(
                value,
                aliases.get(fields[0], (fields[0],)),
            )
        } if fields else {}
    if not isinstance(value, dict):
        return {}
    return {
        field: _strip_leading_field_label(
            _first_value(value, aliases.get(field, (field,))),
            aliases.get(field, (field,)),
        )
        for field in fields
    }


def _normalize_record_list(value, fields, aliases):
    records = []
    for item in _as_list(value):
        if isinstance(item, dict):
            records.append(_normalize_text_record(item, fields, aliases))
    return records


def _append_note(notes, value):
    notes = _as_text(notes)
    value = _as_text(value)
    if not value or value in notes:
        return notes
    return "\n".join(part for part in (notes, value) if part).strip()


def _clean_chapter_plan_note(value):
    """Keep only a human-readable planning note, never transport metadata."""
    text = _as_text(value)
    if not text:
        return ""
    # Older drafts could contain a transport row serialized by a previous
    # endpoint-matching bug. Drop only those generated diagnostic lines; keep
    # all other user/model planning notes intact.
    text = "\n".join(
        line for line in text.splitlines()
        if "未识别的伏笔章位记录：" not in line
    ).strip()
    if not text:
        return ""
    if text.startswith(("{", "[")):
        return ""
    if any(token in text for token in ("'range'", "'stage'", "'cadence'", "'boundary'", '"range"')):
        return ""
    return text


def _expand_character_transport(item):
    """Expand the character transport shape while accepting the old six-slot form."""
    if isinstance(item, dict):
        return _expand_transport_aliases(
            _compact_record(
                item,
                ("name", "role", "goal", "secret", "personality", "voice", "notes"),
            ),
            {
                "n": "name",
                "r": "role",
                "g": "goal",
                "s": "secret",
                "p": "personality",
                "v": "voice",
                "q": "notes",
            },
        )
    if isinstance(item, (list, tuple)):
        fields = (
            ("name", "role", "goal", "secret", "personality", "voice", "notes")
            if len(item) >= 7
            else ("name", "role", "goal", "secret", "voice", "notes")
        )
        return _compact_record(item, fields)
    return {}


def _split_mixed_bible_asset_transport(value):
    """Separate asset rows when a model puts c/l/f rows in one c array.

    The compact bible-assets contract uses three top-level arrays.  A model can
    still return a valid JSON object with every row under ``c``; the row shapes
    retain enough field markers to recover the intended groups without changing
    any story content.
    """
    groups = {"characters": [], "lore": [], "foreshadows": []}
    for item in _as_list(value):
        if not isinstance(item, (dict, list, tuple)):
            continue
        if isinstance(item, (list, tuple)):
            # Positional rows are unambiguous in the requested compact schema:
            # characters have 7 slots, lore 4, and foreshadows 7.  Keep the
            # code/stage shape ahead of the character shape because both
            # characters and foreshadows use seven slots.
            first = _as_text(item[0]) if item else ""
            stage_slots = " ".join(
                _as_text(item[index])
                for index in (2, 3)
                if index < len(item)
            )
            if re.fullmatch(r"[Ff]\d+", first) or stage_slots.count("阶段") >= 2:
                groups["foreshadows"].append(item)
            elif len(item) == 4:
                groups["lore"].append(item)
            else:
                # Keep the longest character form as the default for legacy
                # short rows.
                groups["characters"].append(item)
            continue

        keys = {str(key) for key in item}
        # f rows carry the stable id and the two stage positions.  These
        # markers do not occur together in character or lore rows.
        if (
            {"i", "a", "b", "u"}.issubset(keys)
            or {"code", "setup_stage", "payoff_stage", "remaining_secret"}.issubset(keys)
        ):
            groups["foreshadows"].append(item)
            continue
        # l rows carry the type and the amount of the story known by the
        # characters.  The compact character row has neither marker.
        if "t" in keys or "k" in keys or "type" in keys or "story_known" in keys:
            groups["lore"].append(item)
            continue
        groups["characters"].append(item)
    return groups


def _normalize_character_record(value):
    if not isinstance(value, dict):
        return {}
    record = _normalize_text_record(
        value,
        ("name", "role", "goal", "secret", "personality", "voice", "notes"),
        _CHARACTER_FIELD_ALIASES,
    )
    record["name"], record["role"] = _split_character_name_role_prefix(
        record.get("name"),
        record.get("role"),
    )
    record["notes"] = _clean_character_notes(record.get("notes"))
    optional_notes = (
        ("害怕失去：", ("fear", "fears", "害怕", "害怕失去")),
        (
            "与主角关系：",
            ("relationship_to_protagonist", "relationship", "与主角关系"),
        ),
        ("长期变化：", ("long_term_change", "arc", "character_arc", "长期变化")),
    )
    for label, aliases in optional_notes:
        detail = _as_text(_first_value(value, aliases))
        if detail:
            record["notes"] = _append_note(record.get("notes"), label + detail)
    return record


def _normalize_lore_record(value):
    if not isinstance(value, dict):
        return {}
    raw_description = _first_value(
        value,
        _LORE_FIELD_ALIASES["description"],
    )
    if isinstance(raw_description, (list, tuple, dict)):
        if isinstance(raw_description, dict):
            raw_description = [
                child
                for child in raw_description.values()
                if child not in (None, "", [], {})
            ]
        detail_parts = []
        for child in raw_description if isinstance(raw_description, (list, tuple)) else (raw_description,):
            if isinstance(child, dict):
                child_text = "；".join(
                    _as_text(item)
                    for item in child.values()
                    if _as_text(item)
                )
            elif isinstance(child, (list, tuple)):
                child_text = "；".join(_as_text(item) for item in child if _as_text(item))
            else:
                child_text = _as_text(child)
            if child_text:
                detail_parts.append(child_text)
        value = deepcopy(value)
        value["description"] = "；".join(detail_parts)
    record = _normalize_text_record(
        value,
        ("name", "type", "description", "story_known"),
        _LORE_FIELD_ALIASES,
    )
    relationship_effect = _as_text(
        _first_value(value, ("relationship_effect", "effect", "关系影响"))
    )
    if relationship_effect:
        record["description"] = _append_note(
            record.get("description"),
            relationship_effect,
        )
    # Some providers understand the requested realm list more reliably when
    # it is returned as a small nested list.  Keep the formal project schema
    # unchanged, but fold that list into the ordinary lore description before
    # it reaches the rest of the application.
    levels = _first_value(value, ("levels", "power_levels", "实力层次", "境界", "等级"), [])
    if isinstance(levels, list) and levels:
        level_lines = []
        for item in levels:
            if isinstance(item, dict):
                name = _as_text(_first_value(item, ("name", "level", "境界", "层次")))
                detail = "；".join(
                    part for part in (
                        _as_text(_first_value(item, ("description", "capability", "说明", "能做到"))),
                        _as_text(_first_value(item, ("limit", "不能做到", "边界"))),
                        _as_text(_first_value(item, ("promotion", "提升", "突破"))),
                    ) if part
                )
                if name:
                    level_lines.append(f"{name}：{detail}" if detail else name)
            elif _as_text(item):
                level_lines.append(_as_text(item))
        if level_lines:
            record["description"] = _append_note(
                record.get("description"),
                "实力层次：" + "；".join(level_lines),
            )
    return record


def _normalize_foreshadow_record(value, stage_count=None):
    if not isinstance(value, dict):
        return {}
    record = _normalize_text_record(
        value,
        (
            "code", "name", "status", "setup_stage", "payoff_stage",
            "setup_chapter", "payoff_chapter",
            "description", "revealed", "remaining_secret", "notes",
        ),
        _FORESHADOW_FIELD_ALIASES,
    )
    record["code"] = _normalize_foreshadow_code(record.get("code"))
    # 第二步只确定阶段，不应把“第八阶段”这样的文本放进主程序的
    # 具体章节字段。旧草稿如果曾经把阶段写进 setup_chapter/payoff_chapter，
    # 这里也一并搬回独立的阶段字段，避免后续再把数字 8 当成第 8 章。
    for stage_key, chapter_key in (
        ("setup_stage", "setup_chapter"),
        ("payoff_stage", "payoff_chapter"),
    ):
        stage_value = _as_text(record.get(stage_key))
        chapter_value = _as_text(record.get(chapter_key))
        if not stage_value and "阶段" in chapter_value:
            stage_value = chapter_value
            record[chapter_key] = ""
        record[stage_key] = _normalize_creation_stage_ref(
            stage_value,
            stage_count,
        )

    # 伏笔的故事性内容属于“说明”。notes 是主程序给用户留下的
    # 体检/合并备注，不能让向导把正式内容写到那里。
    generated_notes = _as_text(record.get("notes"))
    if generated_notes:
        record["description"] = _append_note(
            record.get("description"),
            generated_notes,
        )
    relationship_effect = _as_text(
        _first_value(value, ("relationship_effect", "effect", "关系影响"))
    )
    if relationship_effect:
        record["description"] = _append_note(
            record.get("description"),
            relationship_effect,
        )
    record["notes"] = ""
    # 向导只是在搭建后续故事材料，正文尚未写到任何一条伏笔。
    # 模型返回的状态不能覆盖主程序按正文事实维护的状态。
    record["status"] = "未埋"
    return record


def _legacy_relationship_notes(value):
    notes_by_character = {}
    relationships = _first_value(
        value,
        ("relationship_map", "relationships", "关系图", "关系地图"),
        [],
    )
    for item in _as_list(relationships):
        if not isinstance(item, dict):
            continue
        source = _as_text(_first_value(item, ("from", "source", "人物一")))
        target = _as_text(_first_value(item, ("to", "target", "人物二")))
        if not source or not target:
            continue
        details = "；".join(
            part for part in (
                _as_text(_first_value(item, ("initial_state", "initial", "初始关系"))),
                _as_text(_first_value(item, ("turning_pressure", "pressure", "转折压力"))),
                _as_text(_first_value(item, ("possible_state", "future_state", "可能变化"))),
            ) if part
        )
        text = f"与{target}的关系"
        if details:
            text += "：" + details
        notes_by_character[source] = _append_note(notes_by_character.get(source, ""), text)
    return notes_by_character


def _legacy_scene_lore(value):
    records = []
    scenes = _first_value(value, ("key_scenes", "scenes", "关键场景"), [])
    for item in _as_list(scenes):
        if not isinstance(item, dict):
            continue
        name = _as_text(_first_value(item, ("name", "title", "名称", "场景")))
        if not name:
            continue
        description = "；".join(
            part for part in (
                _as_text(_first_value(item, ("atmosphere", "mood", "氛围", "现场感觉"))),
                _as_text(_first_value(item, ("conflict_use", "use", "冲突用途", "适合发生的冲突"))),
            ) if part
        )
        records.append({
            "name": name,
            "type": "地点",
            "description": description,
            "story_known": "",
        })
    return records


def _ability_system_lore(value, allow_power_levels):
    ability_system = _normalize_ability_system(value, allow_power_levels)
    levels = ability_system.get("levels", [])
    if not ability_system.get("enabled") or not levels:
        return None
    description_parts = [_as_text(ability_system.get("description"))]
    for item in levels:
        if not isinstance(item, dict):
            continue
        level_name = _as_text(item.get("name"))
        details = "；".join(
            part for part in (
                _as_text(item.get("capability")),
                _as_text(item.get("limit")),
                _as_text(item.get("promotion")),
            ) if part
        )
        if level_name:
            description_parts.append(f"{level_name}：{details}" if details else level_name)
    limits = [
        _as_text(item)
        for item in ability_system.get("limits", [])
        if _as_text(item)
    ]
    if limits:
        description_parts.append("不能越过的边界：" + "；".join(limits))
    return {
        "name": _as_text(ability_system.get("name")) or "能力体系",
        "type": "规则",
        "description": "\n".join(part for part in description_parts if part).strip(),
        "story_known": "",
    }


def _has_ordered_power_lore(lore):
    """判断设定库中是否已有可供后续章节执行的实力层次记录。"""
    if not isinstance(lore, list):
        return False
    text = " ".join(
        _as_text(item.get("name")) + " " + _as_text(item.get("description"))
        for item in lore
        if isinstance(item, dict)
    )
    if not text:
        return False
    has_system_word = any(
        word in text
        for word in ("境界", "武道等级", "实力体系", "实力层次", "能力层次", "修炼层次")
    )
    ordered_names = re.findall(
        r"(?<![一二三四五六七八九十])([\u4e00-\u9fff]{1,10}(?:境|阶|级))(?!界)",
        text,
    )
    ordered_names = {
        item for item in ordered_names
        if item not in {"境界", "阶段", "等级", "层次"}
    }
    named_levels = {
        item for item in re.findall(
            r"(?:武者|武师|宗师|大宗师|武王|武皇|武帝|天人|圣人|神境)",
            text,
        )
    }
    has_order = len(ordered_names) >= 2 or bool(
        re.search(r"(?:一|二|三|四|五|六|七|八|九|十)[阶境级段层]", text)
        or re.search(r"\d+\s*[阶境级段层]", text)
        or re.search(r"从低到高|境界依次|境界分为|层次依次", text)
        or len(named_levels) >= 2
    )
    return has_system_word and has_order


def _normalize_bible(value):
    return _normalize_text_record(value, _BIBLE_FIELDS, _BIBLE_FIELD_ALIASES)


def _legacy_faction_lore(value):
    """把旧版世界规则里的势力迁移到主程序的设定库。"""
    records = []
    for item in _as_list(value):
        if not isinstance(item, dict):
            continue
        name = _as_text(_first_value(item, ("name", "名称", "势力", "组织")))
        if not name:
            continue
        position = _as_text(
            _first_value(item, ("position", "stance", "立场", "想守住或争夺"))
        )
        relation = _as_text(
            _first_value(
                item,
                (
                    "relationship_to_protagonist",
                    "relationship",
                    "与主角关系",
                    "对主角的态度",
                ),
            )
        )
        description = "\n".join(
            part for part in (
                position,
                f"与主角的关系：{relation}" if relation else "",
            ) if part
        ).strip()
        records.append({
            "name": name,
            "type": "势力",
            "description": description,
            "story_known": _as_text(
                _first_value(item, ("story_known", "known", "人物已知"))
            ),
        })
    return records


def _normalize_world_rules(value):
    if isinstance(value, str):
        return {
            "setting_overview": _strip_leading_field_label(
                value,
                _WORLD_RULE_FIELD_ALIASES["setting_overview"],
            ),
            "power_system": "",
            "geography_and_life": "",
            "rules": [],
            "costs_and_limits": [],
        }
    if not isinstance(value, dict):
        return {}
    return {
        **_normalize_text_record(value, tuple(_WORLD_RULE_FIELD_ALIASES), _WORLD_RULE_FIELD_ALIASES),
        "rules": _normalize_world_rule_list(
            _first_value(value, ("rules", "规矩", "规则", "长期规则数组"), []),
            ("rules", "规矩", "规则", "长期规则数组"),
        ),
        "costs_and_limits": _normalize_world_rule_list(
            _first_value(
                value,
                ("costs_and_limits", "costs", "代价和限制", "代价限制数组"),
                [],
            ),
            ("costs_and_limits", "costs", "代价和限制", "代价限制数组"),
        ),
    }


def _normalize_story_assets_fields(
    payload,
    allow_power_levels,
    foreshadow_stage_count=None,
):
    payload = payload if isinstance(payload, dict) else {}
    characters = _first_value(payload, ("characters", "people", "人物"), [])
    lore = _first_value(payload, ("lore", "settings", "设定"), [])
    foreshadows = _first_value(
        payload,
        ("foreshadows", "foreshadow_items", "clues", "伏笔"),
        [],
    )
    ability_system = _first_value(
        payload,
        ("ability_system", "能力体系", "力量体系"),
        {},
    )
    world_rules = payload.get("world_rules", {})
    if allow_power_levels and isinstance(world_rules, dict):
        legacy_levels = _first_value(
            world_rules,
            ("levels", "实力层次", "境界", "等级"),
            [],
        )
        if (
            isinstance(legacy_levels, list)
            and legacy_levels
            and (
                not isinstance(ability_system, dict)
                or not _as_list(ability_system.get("levels"))
            )
        ):
            ability_system = {
                "enabled": True,
                "name": "能力体系",
                "description": _as_text(
                    _first_value(world_rules, ("power_system", "力量体系", "能力规则"))
                ),
                "levels": legacy_levels,
                "limits": _first_value(
                    world_rules,
                    ("costs_and_limits", "代价和限制", "limits", "边界"),
                    [],
                ),
            }
    legacy_factions = _first_value(payload, ("factions", "势力"), [])
    if not legacy_factions and isinstance(world_rules, dict):
        legacy_factions = _first_value(world_rules, ("factions", "势力"), [])
    relationship_notes = _legacy_relationship_notes(payload)
    normalized_characters = []
    for item in _as_list(characters):
        record = _normalize_character_record(item)
        if not record:
            continue
        name = _as_text(record.get("name"))
        if name in relationship_notes:
            record["notes"] = _append_note(record.get("notes"), relationship_notes[name])
        normalized_characters.append(record)

    normalized_lore = [
        _normalize_lore_record(item)
        for item in _as_list(lore)
        if isinstance(item, dict)
    ]
    existing_lore_names = {
        _as_text(item.get("name"))
        for item in normalized_lore
        if isinstance(item, dict)
    }
    for item in _legacy_scene_lore(payload):
        if item["name"] not in existing_lore_names:
            normalized_lore.append(item)
            existing_lore_names.add(item["name"])
    for item in _legacy_faction_lore(legacy_factions):
        name = _as_text(item.get("name"))
        if not name:
            continue
        if name not in existing_lore_names:
            normalized_lore.append(item)
            existing_lore_names.add(name)
        else:
            for existing in normalized_lore:
                if _as_text(existing.get("name")) == name:
                    existing["type"] = "势力"
                    existing["description"] = _append_note(
                        existing.get("description"),
                        item.get("description"),
                    )
                    existing["story_known"] = (
                        _as_text(existing.get("story_known"))
                        or _as_text(item.get("story_known"))
                    )
                    break
    ability_lore = _ability_system_lore(ability_system, allow_power_levels)
    if ability_lore and ability_lore["name"] not in existing_lore_names:
        normalized_lore.append(ability_lore)

    normalized_foreshadows = []
    for index, item in enumerate(_as_list(foreshadows), 1):
        if not isinstance(item, dict):
            continue
        record = _normalize_foreshadow_record(
            item,
            stage_count=foreshadow_stage_count,
        )
        if not _as_text(record.get("code")):
            record["code"] = f"F{index:04d}"
        normalized_foreshadows.append(record)

    return {
        "characters": normalized_characters,
        "lore": normalized_lore,
        "foreshadows": normalized_foreshadows,
    }


def _normalize_stage_text_list(value):
    if isinstance(value, str):
        values = value.replace("；", "\n").replace(";", "\n").splitlines()
    else:
        values = _as_list(value)
    return [_as_text(item) for item in values if _as_text(item)]


_STAGE_EVENT_TRANSPORT_FIELDS = (
    "id", "allowed_chapters", "references", "preconditions",
    "event", "result", "state_delta",
)


def _parse_compact_stage_event(value):
    """Read one short-protocol event array without evaluating arbitrary text."""
    candidate = value
    if isinstance(candidate, str):
        text = candidate.strip()
        if not (text.startswith("[") and text.endswith("]")):
            return None
        try:
            candidate = ast.literal_eval(text)
        except (SyntaxError, ValueError):
            return None
    if not isinstance(candidate, (list, tuple)) or len(candidate) < 5:
        return None
    event_id = _as_text(candidate[0]).upper()
    if not re.fullmatch(r"(?:(?:S|STAGE)[_-]?\d{1,4}[_-]?)?E[_-]?\d{1,4}", event_id):
        return None
    return list(candidate)


def _normalize_transport_stage_event(value, fallback_id=""):
    """Normalize a dict or compact event array into the regular event schema."""
    if isinstance(value, dict):
        return _normalize_stage_event(value, fallback_id)
    compact = _parse_compact_stage_event(value)
    if compact is None:
        return {}
    return _normalize_stage_event(
        _compact_record(compact, _STAGE_EVENT_TRANSPORT_FIELDS),
        fallback_id,
    )


def _stage_event_content_score(event):
    if not isinstance(event, dict):
        return 0
    return sum(
        1
        for key, value in event.items()
        if key != "id" and value not in (None, "", [], {})
    )


def _restore_stage_events_from_carry_over(value, stage_index):
    """Recover event arrays that were accidentally placed in carry_over.

    Some short-protocol responses put the ordered event arrays in the next
    positional slot.  Keep ordinary carry-over text untouched, but recover
    only values that have an unambiguous event id such as ``E01``.
    """
    compact_outer = _parse_compact_stage_event(value)
    if compact_outer is not None:
        values = [compact_outer]
    elif isinstance(value, str):
        values = _normalize_stage_text_list(value)
    else:
        values = _as_list(value)

    recovered = []
    carry = []
    for event_index, raw in enumerate(values, 1):
        event = _normalize_transport_stage_event(
            raw,
            f"S{stage_index + 1:02d}-E{event_index:02d}",
        )
        if event:
            recovered.append(event)
            continue
        text = _as_text(raw)
        if text:
            carry.append(text)
    return recovered, carry


def _normalize_stage_state(value):
    """Normalize a stage entry/exit state without exposing implementation keys to users."""
    if not isinstance(value, dict):
        return {}
    aliases = {
        "time": ("time", "t", "时间"),
        "location": ("location", "l", "地点", "当前位置"),
        "character_states": ("character_states", "c", "人物状态", "人物处境"),
        "known_facts": ("known_facts", "k", "已知事实", "人物知道"),
        "open_threads": ("open_threads", "q", "未解决问题", "开放问题"),
    }
    result = {}
    for key, names in aliases.items():
        raw = _first_value(value, names, [])
        if key in {"character_states", "known_facts", "open_threads"}:
            items = _normalize_stage_text_list(raw)
            if items:
                result[key] = items
        else:
            text = _as_text(raw)
            if text:
                result[key] = text
    return result


def _normalize_stage_event(value, fallback_id=""):
    if not isinstance(value, dict):
        return {}
    allowed = _first_value(
        value,
        ("allowed_chapters", "chapter_range", "r", "允许章节"),
        [],
    )
    if isinstance(allowed, str):
        numbers = [int(item) for item in re.findall(r"\d+", allowed)]
        allowed = numbers[:2]
    elif isinstance(allowed, (tuple, list)):
        parsed = []
        for item in allowed[:2]:
            try:
                parsed.append(int(item))
            except (TypeError, ValueError):
                continue
        allowed = parsed
    else:
        allowed = []
    state_delta = _first_value(
        value,
        ("state_delta", "状态变化", "changes", "变化", "d"),
        {},
    )
    if isinstance(state_delta, str):
        state_delta = {"summary": _as_text(state_delta)}
    elif isinstance(state_delta, list):
        # New transport format: one short list/string of actual changes. The
        # normalized project format still keeps a dict so existing readers
        # can consume it without carrying six empty categories per event.
        if len(state_delta) == 6 and any(isinstance(item, (list, dict)) for item in state_delta):
            state_delta = _compact_record(
                state_delta,
                (
                    "time_advance", "location_changes", "knowledge_changes",
                    "relationship_changes", "object_changes", "new_open_threads",
                ),
            )
        else:
            state_delta = {
                "summary": "；".join(_as_text(item) for item in state_delta if _as_text(item)),
            }
    if not isinstance(state_delta, dict):
        state_delta = {}
    delta = {
        "summary": _as_text(_first_value(state_delta, ("summary", "变化事实", "实际变化"))),
        "time_advance": _as_text(_first_value(state_delta, ("time_advance", "时间变化"))),
        "location_changes": _normalize_stage_text_list(
            _first_value(state_delta, ("location_changes", "地点变化"), [])
        ),
        "knowledge_changes": _normalize_stage_text_list(
            _first_value(state_delta, ("knowledge_changes", "认知变化"), [])
        ),
        "relationship_changes": _normalize_stage_text_list(
            _first_value(state_delta, ("relationship_changes", "关系变化"), [])
        ),
        "object_changes": _normalize_stage_text_list(
            _first_value(state_delta, ("object_changes", "物件变化"), [])
        ),
        "new_open_threads": _normalize_stage_text_list(
            _first_value(state_delta, ("new_open_threads", "新增问题"), [])
        ),
    }
    delta = {key: value for key, value in delta.items() if value not in ("", [], {})}
    raw_event_id = _as_text(_first_value(value, ("id", "event_id", "i", "事件编号")))
    compact_event_id = re.sub(r"\s+", "", raw_event_id.upper())
    event_match = re.fullmatch(
        r"(?:STAGE[_-]?|S[_-]?)(\d{1,4})[_-]?E[_-]?(\d{1,4})",
        compact_event_id,
    )
    if event_match:
        event_id = (
            f"S{int(event_match.group(1)):02d}-E"
            f"{int(event_match.group(2)):02d}"
        )
    else:
        bare_event_match = re.fullmatch(r"E[_-]?(\d{1,4})", compact_event_id)
        if bare_event_match:
            event_id = f"E{int(bare_event_match.group(1)):02d}"
        else:
            # Stage events are internal planning anchors.  Older responses
            # often used a bare number such as "1", which is ambiguous across
            # stages.  The normalized fallback is the stable identifier used
            # everywhere else.
            event_id = str(fallback_id or "").strip().upper()
    result = {
        "id": event_id,
        "allowed_chapters": allowed,
        "references": _normalize_stage_text_list(
            _first_value(value, ("references", "refs", "a", "关联资料"), [])
        ),
        "preconditions": _normalize_stage_text_list(
            _first_value(value, ("preconditions", "p", "前置条件"), [])
        ),
        "event": _as_text(_first_value(value, ("event", "h", "事件", "发生什么"))),
        "result": _as_text(_first_value(value, ("result", "o", "结果", "事件结果"))),
        "state_delta": delta,
    }
    return {key: child for key, child in result.items() if child not in ("", [], {})}


def _normalize_stage_book_contract(value):
    if not isinstance(value, dict):
        return {}
    result = {}
    for key, aliases in {
        "hard_facts": ("hard_facts", "硬事实", "不能改变的事实"),
        "world_invariants": ("world_invariants", "长期规则", "世界不变量"),
        "character_boundaries": ("character_boundaries", "人物边界"),
        "ending_boundaries": ("ending_boundaries", "结尾边界"),
    }.items():
        items = _normalize_stage_text_list(_first_value(value, aliases, []))
        if items:
            result[key] = items
    return result


def _compact_record(value, fields):
    """把固定顺序数组还原为主程序继续使用的字段对象。"""
    if isinstance(value, dict):
        return deepcopy(value)
    if not isinstance(value, list):
        return {}
    return {
        field: deepcopy(value[index])
        for index, field in enumerate(fields)
        if index < len(value)
    }


def _expand_transport_aliases(value, aliases):
    """Expand short transport keys without changing already named fields."""
    if not isinstance(value, dict):
        return deepcopy(value)
    result = deepcopy(value)
    for short_key, field_name in aliases.items():
        if field_name not in result and short_key in value:
            result[field_name] = deepcopy(value[short_key])
    return result


def _expand_stage_state_transport(value):
    if isinstance(value, dict):
        return _expand_transport_aliases(
            value,
            {
                "t": "time",
                "l": "location",
                "c": "character_states",
                "k": "known_facts",
                "q": "open_threads",
            },
        )
    if isinstance(value, list):
        return _compact_record(
            value,
            ("time", "location", "character_states", "known_facts", "open_threads"),
        )
    return deepcopy(value)


def _expand_stage_event_transport(value):
    if isinstance(value, dict):
        return _expand_transport_aliases(
            value,
            {
                "i": "id",
                "r": "allowed_chapters",
                "a": "references",
                "p": "preconditions",
                "h": "event",
                "o": "result",
                "d": "state_delta",
            },
        )
    if isinstance(value, list):
        return _compact_record(value, _STAGE_EVENT_TRANSPORT_FIELDS)
    return deepcopy(value)


def _expand_stage_object_transport(value):
    """Expand the named-field single-stage protocol into project fields."""
    if isinstance(value, list):
        value = _compact_record(
            value,
            (
                "id", "name", "start_chapter", "end_chapter", "target_words",
                "entry_state", "ordered_events", "exit_state", "carry_over",
            ),
        )
    if not isinstance(value, dict):
        return {}

    stage = _expand_transport_aliases(
        value,
        {
            "i": "id",
            "n": "name",
            "b": "entry_state",
            "e": "ordered_events",
            "x": "exit_state",
            "y": "carry_over",
        },
    )
    chapter_range = value.get("r", stage.get("chapter_range"))
    if isinstance(chapter_range, dict):
        chapter_range = [
            chapter_range.get("a", chapter_range.get("start")),
            chapter_range.get("b", chapter_range.get("end")),
        ]
    if isinstance(chapter_range, (list, tuple)):
        if "start_chapter" not in stage and len(chapter_range) >= 1:
            stage["start_chapter"] = deepcopy(chapter_range[0])
        if "end_chapter" not in stage and len(chapter_range) >= 2:
            stage["end_chapter"] = deepcopy(chapter_range[1])
    stage["entry_state"] = _expand_stage_state_transport(
        stage.get("entry_state", {})
    )
    stage["exit_state"] = _expand_stage_state_transport(
        stage.get("exit_state", {})
    )
    raw_events = stage.get("ordered_events", [])
    if isinstance(raw_events, list):
        stage["ordered_events"] = [
            _expand_stage_event_transport(item)
            for item in raw_events
            if isinstance(item, (dict, list))
        ]
    stage["carry_over"] = deepcopy(stage.get("carry_over", []))
    # The short keys are transport-only.  Leaving them beside the expanded
    # fields duplicates every stage in the next continuity handoff and lets
    # later normalizers read two versions of the same fact.
    for key in ("i", "n", "b", "e", "x", "y", "r"):
        stage.pop(key, None)
    return stage


def _expand_stage_contract_transport(value):
    if isinstance(value, list):
        return _compact_record(
            value,
            (
                "hard_facts", "world_invariants", "character_boundaries",
                "ending_boundaries",
            ),
        )
    if isinstance(value, dict):
        return _expand_transport_aliases(
            value,
            {
                "f": "hard_facts",
                "w": "world_invariants",
                "c": "character_boundaries",
                "e": "ending_boundaries",
            },
        )
    return {}


def _expand_foreshadow_transport(value):
    if isinstance(value, list):
        return _compact_record(
            value,
            (
                "code", "name", "endpoint_kind", "endpoint_chapter",
                "endpoint_event", "setup_chapter", "payoff_chapter",
                "setup_event", "payoff_event", "endpoint_event_id",
            ),
        )
    if isinstance(value, dict):
        result = _expand_transport_aliases(
            value,
            {
                "i": "code",
                "n": "name",
                "k": "endpoint_kind",
                "e": "endpoint_event_id",
                "c": "endpoint_chapter",
                "d": "endpoint_event",
                "a": "setup_chapter",
                "b": "payoff_chapter",
                "u": "setup_event",
                "v": "payoff_event",
            },
        )
        # The old protocol used a/b/u/v for both endpoints.  Keep those
        # fields readable while allowing new responses to carry one endpoint
        # at a time through k/c/d.
        return result
    return {}


_PREMISE_SLOT_KEYS = ("1", "2", "3", "4", "5")
_PREMISE_CANDIDATE_ALIASES = {
    "t": "title",
    "g": "genre",
    "a": "audience",
    "y": "style",
    "h": "one_sentence",
    "d": "synopsis",
    "p": "protagonist",
    "m": "main_line",
    "r": "relationship_engine",
    "e": "ending_direction",
}


def _expand_premise_candidate_transport(value):
    if isinstance(value, dict):
        return _expand_transport_aliases(value, _PREMISE_CANDIDATE_ALIASES)
    if isinstance(value, list):
        return _compact_record(
            value,
            (
                "title", "genre", "audience", "style", "one_sentence", "synopsis",
                "protagonist", "main_line", "relationship_engine", "ending_direction",
            ),
        )
    return {}


def _premise_transport_items(value):
    """Read the new five-slot contract and report structural violations."""
    if isinstance(value, dict):
        extra_keys = [key for key in value if str(key) not in _PREMISE_SLOT_KEYS]
        missing_keys = [key for key in _PREMISE_SLOT_KEYS if key not in value]
        items = [value[key] for key in _PREMISE_SLOT_KEYS if key in value]
        error = ""
        if extra_keys or missing_keys:
            parts = []
            if missing_keys:
                parts.append("缺少方向 " + ",".join(missing_keys))
            if extra_keys:
                parts.append("出现未定义方向 " + ",".join(str(key) for key in extra_keys))
            error = "；".join(parts)
        return items, error
    if isinstance(value, list):
        return value, "" if len(value) == 5 else f"返回了 {len(value)} 个方向，应为 5 个"
    return [], "没有返回五个固定故事方向"


def _bind_requested_title(result, requested_title):
    """Keep an explicitly supplied book title identical in every candidate."""
    requested_title = _as_text(requested_title)
    if not requested_title or not isinstance(result, dict):
        return result
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return result
    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate["title"] = requested_title
    return result


def _expand_creation_transport(step, payload):
    """展开向导专用的短键/定长数组协议，不改变正式保存字段。"""
    data = deepcopy(payload) if isinstance(payload, dict) else {}
    if step == "premise" and "candidates" not in data and isinstance(data.get("c"), (dict, list)):
        raw_items, protocol_error = _premise_transport_items(data.get("c"))
        data["candidates"] = [
            _expand_premise_candidate_transport(item)
            for item in raw_items
            if isinstance(item, (list, dict))
        ]
        if protocol_error:
            data["_candidate_protocol_error"] = protocol_error
        if "s" in data and "selected_index" not in data:
            data["selected_index"] = data.get("s", 0)
        return data

    if step == "bible":
        if "bible" not in data and isinstance(data.get("b"), list):
            data["bible"] = _compact_record(data["b"], _BIBLE_FIELDS)
        elif "bible" not in data and isinstance(data.get("b"), dict):
            data["bible"] = _expand_transport_aliases(
                data["b"],
                {
                    "c": "core_setting",
                    "r": "reader_promise",
                    "t": "theme",
                    "m": "main_conflict",
                    "p": "relationship_foundation",
                    "e": "ending_direction",
                    "h": "hard_boundaries",
                },
            )
        if "world_rules" not in data and isinstance(data.get("w"), list):
            data["world_rules"] = _compact_record(
                data["w"],
                (
                    "setting_overview", "power_system", "rules",
                    "costs_and_limits", "geography_and_life",
                ),
            )
        elif "world_rules" not in data and isinstance(data.get("w"), dict):
            data["world_rules"] = _expand_transport_aliases(
                data["w"],
                {
                    "s": "setting_overview",
                    "p": "power_system",
                    "r": "rules",
                    "c": "costs_and_limits",
                    "g": "geography_and_life",
                },
            )
        if isinstance(data.get("c"), list):
            mixed_groups = _split_mixed_bible_asset_transport(data.get("c", []))
            if "characters" not in data:
                data["characters"] = [
                    _expand_character_transport(item)
                    for item in mixed_groups["characters"]
                    if isinstance(item, (list, dict))
                ]
            if "lore" not in data and mixed_groups["lore"]:
                data["lore"] = [
                    _expand_transport_aliases(
                        _compact_record(
                            item,
                            ("name", "type", "description", "story_known"),
                        ),
                        {
                            "n": "name",
                            "t": "type",
                            "d": "description",
                            "k": "story_known",
                        },
                    )
                    for item in mixed_groups["lore"]
                    if isinstance(item, (list, dict))
                ]
            if "foreshadows" not in data and mixed_groups["foreshadows"]:
                data["foreshadows"] = [
                    _expand_transport_aliases(
                        _compact_record(
                            item,
                            (
                                "code", "name", "setup_stage", "payoff_stage",
                                "description", "revealed", "remaining_secret",
                            ),
                        ),
                        {
                            "i": "code",
                            "n": "name",
                            "a": "setup_stage",
                            "b": "payoff_stage",
                            "d": "description",
                            "r": "revealed",
                            "u": "remaining_secret",
                        },
                    )
                    for item in mixed_groups["foreshadows"]
                    if isinstance(item, (list, dict))
                ]
        if "lore" not in data and isinstance(data.get("l"), list):
            data["lore"] = [
                _expand_transport_aliases(
                    _compact_record(
                        item,
                        ("name", "type", "description", "story_known"),
                    ),
                    {
                        "n": "name",
                        "t": "type",
                        "d": "description",
                        "k": "story_known",
                    },
                )
                for item in data.get("l", [])
                if isinstance(item, (list, dict))
            ]
        if "foreshadows" not in data and isinstance(data.get("f"), list):
            data["foreshadows"] = [
                _expand_transport_aliases(
                    _compact_record(
                        item,
                        (
                            "code", "name", "setup_stage", "payoff_stage",
                            "description", "revealed", "remaining_secret",
                        ),
                    ),
                    {
                        "i": "code",
                        "n": "name",
                        "a": "setup_stage",
                        "b": "payoff_stage",
                        "d": "description",
                        "r": "revealed",
                        "u": "remaining_secret",
                    },
                )
                for item in data.get("f", [])
                if isinstance(item, (list, dict))
            ]
        return data

    if step == "stage_plan":
        if "planning_schema_version" not in data and "v" in data:
            data["planning_schema_version"] = data.get("v", "2")
        if "stage_skeleton" not in data and isinstance(data.get("g"), list):
            data["stage_skeleton"] = data.get("g", [])
        if "book_contract" not in data and isinstance(data.get("k"), (dict, list)):
            data["book_contract"] = _expand_stage_contract_transport(data["k"])
        if "chapter_plan_note" not in data and "n" in data:
            data["chapter_plan_note"] = _clean_chapter_plan_note(data.get("n", ""))
        if "foreshadow_schedule" not in data and isinstance(data.get("f"), list):
            data["foreshadow_schedule"] = [
                _expand_foreshadow_transport(item)
                for item in data.get("f", [])
                if isinstance(item, (list, dict))
            ]
        if "stage_plan" not in data and isinstance(data.get("s"), dict):
            data["stage_plan"] = [_expand_stage_object_transport(data["s"])]
        elif "stage_plan" not in data and isinstance(data.get("s"), list):
            state_fields = ("time", "location", "character_states", "known_facts", "open_threads")
            delta_fields = (
                "time_advance", "location_changes", "knowledge_changes",
                "relationship_changes", "object_changes", "new_open_threads",
            )
            event_fields = (
                "id", "allowed_chapters", "references", "preconditions",
                "event", "result", "state_delta",
            )
            stage_fields = (
                "id", "name", "start_chapter", "end_chapter", "target_words",
                "entry_state", "ordered_events", "exit_state", "carry_over",
            )
            stages = []
            for raw_stage in data.get("s", []):
                stage = _compact_record(raw_stage, stage_fields)
                for state_key in ("entry_state", "exit_state"):
                    if isinstance(stage.get(state_key), list):
                        stage[state_key] = _compact_record(stage[state_key], state_fields)
                events = []
                for raw_event in stage.get("ordered_events", []) if isinstance(stage.get("ordered_events"), list) else []:
                    event = _compact_record(raw_event, event_fields)
                    if isinstance(event.get("state_delta"), list):
                        if len(event["state_delta"]) == 6 and any(
                            isinstance(item, (list, dict)) for item in event["state_delta"]
                        ):
                            event["state_delta"] = _compact_record(
                                event["state_delta"], delta_fields
                            )
                        else:
                            event["state_delta"] = {
                                "summary": "；".join(
                                    _as_text(item)
                                    for item in event["state_delta"]
                                    if _as_text(item)
                                )
                            }
                    elif isinstance(event.get("state_delta"), str):
                        event["state_delta"] = {"summary": _as_text(event["state_delta"])}
                    events.append(event)
                stage["ordered_events"] = events
                stages.append(stage)
            data["stage_plan"] = stages
        return data

    return data


def normalize_creation_result(
    step,
    payload,
    allow_power_levels=False,
    pad_stage_plan=True,
    foreshadow_stage_count=None,
    total_words=500000,
    average_chapter_words=3000,
):
    """Normalize model aliases into the fixed wizard schema."""
    payload = _expand_creation_transport(step, payload)
    if step == "premise":
        raw = _first_value(payload, ("candidates", "stories", "options", "简介候选"), [])
        raw_items, inferred_protocol_error = _premise_transport_items(raw)
        protocol_error = _as_text(
            payload.get("_candidate_protocol_error")
        ) or inferred_protocol_error
        candidates = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            item = _expand_premise_candidate_transport(item)
            candidate = {
                "title": _as_text(_first_value(item, ("title", "name", "book_title", "书名"))),
                "genre": _as_text(_first_value(item, ("genre", "类型"))),
                "audience": _as_text(_first_value(item, ("audience", "pov", "频段", "男频女频"))),
                "style": _as_text(_first_value(item, ("style", "风格"))),
                "one_sentence": _as_text(_first_value(item, ("one_sentence", "hook", "一句话简介"))),
                "synopsis": _as_text(_first_value(item, ("synopsis", "summary", "简介"))),
                "protagonist": _as_text(_first_value(item, ("protagonist", "hero", "主角"))),
                "main_line": _as_text(_first_value(
                    item,
                    ("core_motive", "main_motive", "main_line", "core_line", "核心动机", "核心动机主线", "主线"),
                )),
                "relationship_engine": _as_text(_first_value(item, ("relationship_engine", "关系线"))),
                "ending_direction": _as_text(_first_value(item, ("ending_direction", "ending", "结局方向"))),
            }
            if candidate["title"] or candidate["synopsis"]:
                candidates.append(candidate)
        try:
            selected_index = int(payload.get("selected_index", 0) or 0)
        except Exception:
            selected_index = 0
        result = {
            "candidates": candidates,
            "selected_index": max(0, min(selected_index, max(0, len(candidates) - 1))),
        }
        if protocol_error:
            result["_candidate_protocol_error"] = protocol_error
        return result
    if step == "bible":
        bible = _normalize_bible(
            _first_value(payload, ("bible", "novel_bible", "小说圣经"), {})
        )
        if not bible.get("main_conflict"):
            fallback_motive = _as_text(
                _first_value(
                    payload,
                    ("core_motive", "main_motive", "核心动机", "主角核心动机"),
                    "",
                )
            )
            if fallback_motive:
                bible["main_conflict"] = fallback_motive
        result = {
            "bible": bible,
            "world_rules": _normalize_world_rules(
                _first_value(payload, ("world_rules", "world", "世界规则"), {})
            ),
        }
        result.update(
            _normalize_story_assets_fields(
                payload,
                allow_power_levels,
                foreshadow_stage_count=foreshadow_stage_count,
            )
        )
        return result
    if step == "story_assets":
        return _normalize_story_assets_fields(
            payload,
            allow_power_levels,
            foreshadow_stage_count=foreshadow_stage_count,
        )
    if step == "stage_plan":
        raw = _first_value(payload, ("stage_plan", "stages", "arcs", "阶段规划"), [])
        normalized = (
            normalize_stage_plan_ranges(
                raw,
                total_words,
                average_chapter_words,
                expected_count=(None if pad_stage_plan else len(raw)),
                pad_missing=pad_stage_plan,
            )
            if _as_list(raw) else []
        )
        contract = _normalize_stage_book_contract(
            _first_value(payload, ("book_contract", "planning_contract", "全书契约"), {})
        )
        return {
            "planning_schema_version": _as_text(
                _first_value(payload, ("planning_schema_version", "schema_version"), "2")
            ) or "2",
            "stage_skeleton": _normalize_stage_skeleton(
                _first_value(
                    payload,
                    ("stage_skeleton", "skeleton", "full_book_skeleton", "全书阶段骨架"),
                    [],
                ),
                total_words,
                average_chapter_words,
            ),
            "book_contract": contract,
            "stage_plan": normalized,
            "foreshadow_schedule": _normalize_foreshadow_schedule(
                _first_value(
                    payload,
                    ("foreshadow_schedule", "foreshadow_plan", "伏笔安排", "伏笔章位"),
                    [],
                )
            ),
            "chapter_plan_note": _clean_chapter_plan_note(
                _first_value(payload, ("chapter_plan_note", "章节规划提示"))
            ),
        }
    return deepcopy(payload)


def creation_wizard_payload_from_project_draft(project):
    """从尚未写入正式项目的自动草稿中恢复已完成的向导结果。

    向导完成后，旧流程可能先把结构化框架写入 ``novel_draft.json``，
    但还没来得及补齐项目元信息就被重启。这里仅在元信息仍是空白时恢复，
    不会把已有正式项目重新当成一次新建。
    """
    if not isinstance(project, dict):
        return {}
    meta = project.get("meta", {})
    if not isinstance(meta, dict):
        meta = {}
    if (
        _as_text(meta.get("title")) not in {"", "未命名小说"}
        or _as_text(meta.get("genre"))
        or _as_text(meta.get("style"))
        or _as_text(meta.get("premise"))
    ):
        return {}

    framework = project.get("creation_framework", {})
    if not isinstance(framework, dict):
        return {}
    state = project.get("creation_wizard_state", {})
    if isinstance(state, dict):
        status = _as_text(state.get("status")).lower()
        if status and status not in {"complete", "confirmed"}:
            return {}
    candidates = [
        deepcopy(item)
        for item in framework.get("premise_candidates", [])
        if isinstance(item, dict)
    ]
    if not candidates:
        return {}

    selected = framework.get("premise", {})
    if not isinstance(selected, dict):
        selected = {}
    selected = deepcopy(selected)
    if not _as_text(selected.get("title")) or not _as_text(selected.get("synopsis")):
        selected = deepcopy(candidates[0])
    if not _as_text(selected.get("title")) or not _as_text(selected.get("synopsis")):
        return {}

    recovered_framework = deepcopy(framework)
    recovered_framework["premise"] = selected
    recovered_framework["premise_candidates"] = candidates
    recovered_framework["novel_name"] = (
        _as_text(recovered_framework.get("novel_name"))
        or _as_text(selected.get("title"))
    )
    try:
        recovered_framework["total_words"] = max(
            10000,
            int(recovered_framework.get("total_words", meta.get("target_words", 500000)) or 500000),
        )
    except (TypeError, ValueError):
        recovered_framework["total_words"] = 500000
    try:
        recovered_framework["average_chapter_words"] = max(
            1000,
            int(recovered_framework.get("average_chapter_words", 3000) or 3000),
        )
    except (TypeError, ValueError):
        recovered_framework["average_chapter_words"] = 3000

    recovered_state = deepcopy(state) if isinstance(state, dict) else {}
    if not recovered_state:
        recovered_state = {
            "schema_version": 1,
            "status": "complete",
            "current_step": "complete",
        }
    return {
        "creation_framework": recovered_framework,
        "creation_wizard_state": recovered_state,
    }


def creation_wizard_draft_from_project_draft(project):
    """把自动草稿中的完整框架还原为向导可继续编辑的草稿。"""
    payload = creation_wizard_payload_from_project_draft(project)
    if not payload:
        return {}
    framework = payload["creation_framework"]
    candidates = deepcopy(framework.get("premise_candidates", []))
    selected = deepcopy(framework.get("premise", {}))
    try:
        selected_index = max(
            0,
            min(candidates.index(selected), max(0, len(candidates) - 1)),
        )
    except ValueError:
        selected_index = 0
    try:
        total_words = int(framework.get("total_words", 500000) or 500000)
    except (TypeError, ValueError):
        total_words = 500000
    try:
        average_words = int(framework.get("average_chapter_words", 3000) or 3000)
    except (TypeError, ValueError):
        average_words = 3000

    def length_choice(value):
        if value >= 1000000:
            return "100万字+"
        if value >= 500000:
            return "50万字"
        return "30万字"

    chapter_choice = f"{average_words}字"
    if chapter_choice not in CREATION_CHOICE_GROUPS["chapter_words"]["单章字数"]:
        chapter_choice = CREATION_CHOICE_DEFAULTS["chapter_words"]
    step_results = {
        "premise": {
            "candidates": deepcopy(candidates),
            "selected_index": selected_index,
            "selected": deepcopy(selected),
        },
        "stage_plan": {
            "stage_skeleton": deepcopy(framework.get("stage_skeleton", [])),
            "stage_plan": deepcopy(framework.get("stage_plan", [])),
            "foreshadow_schedule": deepcopy(framework.get("foreshadow_schedule", [])),
            "chapter_plan_note": _as_text(framework.get("chapter_plan_note")),
        },
        "bible": {
            "bible": deepcopy(framework.get("bible", {})),
            "world_rules": deepcopy(framework.get("world_rules", {})),
            "characters": deepcopy(framework.get("characters", [])),
            "lore": deepcopy(framework.get("lore", [])),
            "foreshadows": deepcopy(framework.get("foreshadows", [])),
        },
    }
    return {
        "schema_version": 2,
        "project_name_hint": _as_text(selected.get("title")),
        "current_step_index": len(CREATION_WIZARD_STEPS) - 1,
        "choice_values": {
            "audience": _as_text(selected.get("audience")) or CREATION_CHOICE_DEFAULTS["audience"],
            "genre": _as_text(selected.get("genre")) or CREATION_CHOICE_DEFAULTS["genre"],
            "theme": _as_text(selected.get("theme")),
            "protagonist_route": (
                _as_text(selected.get("protagonist_route"))
                or CREATION_CHOICE_DEFAULTS["protagonist_route"]
            ),
            "protagonist_style": _character_style_id_for_selected(selected),
            "style": _as_text(selected.get("style")) or CREATION_CHOICE_DEFAULTS["style"],
            "length": length_choice(total_words),
            "chapter_words": chapter_choice,
        },
        # The selected synopsis is generated story material, not the author's
        # original inspiration.  Do not put it back into the editable input.
        "inspiration": "",
        "target_words": total_words,
        "average_words": average_words,
        "premise_candidates": candidates,
        "premise_selected_index": selected_index,
        "step_results": step_results,
        "updated_at": now_str(),
    }


def pretty_json(value):
    return json.dumps(value if value is not None else {}, ensure_ascii=False, indent=2)


def _format_value(value, indent=0, label_overrides=None):
    prefix = "  " * indent
    label_overrides = label_overrides if isinstance(label_overrides, dict) else {}
    if isinstance(value, dict):
        lines = []
        for key, child in value.items():
            label = label_overrides.get(key, _context_label(key))
            if isinstance(child, (dict, list)):
                lines.append(f"{prefix}{label}：")
                lines.extend(_format_value(child, indent + 1, label_overrides))
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
                lines.extend(_format_value(child, indent + 1, label_overrides))
            else:
                lines.append(f"{prefix}- {_as_text(child)}")
        return lines
    return [f"{prefix}{_as_text(value)}"] if _as_text(value) else []


def format_creation_text(value, title="", label_overrides=None):
    lines = [title] if _as_text(title) else []
    lines.extend(_format_value(value, label_overrides=label_overrides))
    return "\n".join(line for line in lines if line).strip()


def migrate_creation_bible_display_text(value, has_core_motive=False):
    """Rename the legacy Bible label without changing the stored story text."""
    text = _as_text(value)
    if not text or not has_core_motive:
        return text
    migrated = []
    changed = False
    for line in text.splitlines():
        match = re.match(r"^(\s*)主线矛盾([：:])", line)
        if match:
            line = (
                f"{match.group(1)}核心动机契约（主线矛盾）{match.group(2)}"
                + line[match.end():]
            )
            changed = True
        migrated.append(line)
    return "\n".join(migrated) if changed else text


def _flatten_preview_text(value):
    if isinstance(value, dict):
        parts = []
        for child in value.values():
            parts.extend(_flatten_preview_text(child))
        return parts
    if isinstance(value, (list, tuple)):
        parts = []
        for child in value:
            parts.extend(_flatten_preview_text(child))
        return parts
    text = _as_text(value)
    return [text] if text else []


def _preview_field(mapping, key):
    if not isinstance(mapping, dict):
        return ""
    return " ".join(_flatten_preview_text(mapping.get(key))).strip()


def _format_bible_section_body(result):
    result = result if isinstance(result, dict) else {}
    bible = result.get("bible", {})
    bible_lines = []
    bible_labels = {
        "core_setting": "核心设定",
        "main_conflict": "核心动机契约（主线矛盾）",
        "relationship_foundation": "人物关系底子",
        "reader_promise": "持续悬念",
        "theme": "故事想留下的东西",
        "ending_direction": "结尾方向",
        "hard_boundaries": "必须守住的边界",
    }
    if not isinstance(bible, dict):
        text = _as_text(bible)
        if text:
            bible_lines.append(text)
    else:
        for key in (
            "core_setting", "main_conflict", "relationship_foundation",
            "reader_promise", "theme", "ending_direction", "hard_boundaries",
        ):
            text = _preview_field(bible, key)
            if text:
                bible_lines.append(f"{bible_labels.get(key, key)}：\n{text}")
    return "\n\n".join(bible_lines).strip() or "这部分还没有生成有效内容。"


def _format_world_rules_section_body(result):
    result = result if isinstance(result, dict) else {}
    world_rules = result.get("world_rules", {})
    world_lines = []
    if not isinstance(world_rules, dict):
        text = _as_text(world_rules)
        if text:
            world_lines.append(text)
    else:
        setting = _preview_field(world_rules, "setting_overview")
        geography = _preview_field(world_rules, "geography_and_life")
        power = _preview_field(world_rules, "power_system")
        if setting:
            world_lines.append(f"世界概况：\n{setting}")
        if geography:
            world_lines.append(f"地点和日常生活：\n{geography}")
        if power:
            world_lines.append(f"能力边界：\n{power}")

        rules = [
            _as_text(item)
            for item in world_rules.get("rules", [])
            if _as_text(item)
        ]
        if rules:
            world_lines.append("长期规则：")
            world_lines.extend(f"・{item}" for item in rules)

        costs = [
            _as_text(item)
            for item in world_rules.get("costs_and_limits", [])
            if _as_text(item)
        ]
        if costs:
            world_lines.append("代价和限制：")
            world_lines.extend(f"・{item}" for item in costs)
    return "\n\n".join(world_lines).strip() or "这部分还没有生成有效内容。"


def _format_characters_section_body(result):
    result = result if isinstance(result, dict) else {}
    characters = result.get("characters", [])
    if not characters:
        return "这部分还没有生成有效内容。"
    lines = [f"共 {len(characters)} 名主要人物"]
    for item in characters:
        if not isinstance(item, dict):
            continue
        name = _as_text(item.get("name")) or "未命名人物"
        lines.append(f"・{name}")
        for label, key in (
            ("身份", "role"),
            ("人物目标", "goal"),
            ("隐藏秘密", "secret"),
            ("人物性格/特点", "personality"),
            ("语言风格", "voice"),
            ("长期备注", "notes"),
        ):
            value = _as_text(item.get(key))
            if value:
                lines.append(f"  {label}：{value}")
    return "\n".join(lines).strip()


def _format_lore_section_body(result):
    result = result if isinstance(result, dict) else {}
    lore = result.get("lore", [])
    if not lore:
        return "这部分还没有生成有效内容。"
    lines = [f"共 {len(lore)} 项设定"]
    for item in lore:
        if not isinstance(item, dict):
            continue
        name = _as_text(item.get("name")) or "未命名设定"
        kind = _as_text(item.get("type"))
        description = _as_text(item.get("description"))
        known = _as_text(item.get("story_known"))
        detail = "；".join(part for part in (kind, description) if part)
        lines.append(f"・{name}" + (f"：{detail}" if detail else ""))
        if known:
            lines.append(f"  人物已知：{known}")
    return "\n".join(lines).strip()


def _format_foreshadows_section_body(result):
    result = result if isinstance(result, dict) else {}
    foreshadows = result.get("foreshadows", [])
    if not foreshadows:
        return "这部分还没有生成有效内容。"
    lines = [f"共 {len(foreshadows)} 条伏笔"]
    for item in foreshadows:
        if not isinstance(item, dict):
            continue
        code = _as_text(item.get("code"))
        name = _as_text(item.get("name")) or "未命名伏笔"
        description = _as_text(item.get("description"))
        title = " ".join(part for part in (code, name) if part)
        lines.append(f"・{title}" + (f"：{description}" if description else ""))
        status = _as_text(item.get("status"))
        if status:
            lines.append(f"  状态：{status}")
        setup_chapter = _as_text(item.get("setup_chapter"))
        setup_stage = _as_text(item.get("setup_stage"))
        if setup_chapter:
            lines.append(f"  埋设章节：{setup_chapter}")
        elif setup_stage:
            lines.append(f"  埋设阶段：{setup_stage}")
        payoff_chapter = _as_text(item.get("payoff_chapter"))
        payoff_stage = _as_text(item.get("payoff_stage"))
        if payoff_chapter:
            lines.append(f"  回收章节：{payoff_chapter}")
        elif payoff_stage:
            lines.append(f"  回收阶段：{payoff_stage}")
        for label, key in (
            ("揭示结果", "revealed"),
            ("仍未揭开", "remaining_secret"),
            ("备注", "notes"),
        ):
            value = _as_text(item.get(key))
            if value:
                lines.append(f"  {label}：{value}")
    return "\n".join(lines).strip()


def _format_bible_sections(result):
    result = result if isinstance(result, dict) else {}
    return {
        "bible": ("小说圣经", _format_bible_section_body(result)),
        "world_rules": ("世界规则", _format_world_rules_section_body(result)),
        "characters": ("人物", _format_characters_section_body(result)),
        "lore": ("设定库", _format_lore_section_body(result)),
        "foreshadows": ("伏笔", _format_foreshadows_section_body(result)),
    }


def _format_story_assets_preview(result):
    sections = _format_bible_sections(result)
    return "\n\n".join(
        f"{title}\n\n{body}"
        for key in ("characters", "lore", "foreshadows")
        for title, body in (sections[key],)
    ).strip()


def _format_bible_preview(result):
    sections = _format_bible_sections(result)
    return "\n\n".join(
        f"{title}\n\n{body}"
        for key in ("bible", "world_rules", "characters", "lore", "foreshadows")
        for title, body in (sections[key],)
    ).strip()


def _format_stage_state_preview(value):
    if not isinstance(value, dict):
        return ""
    labels = {
        "time": "时间",
        "location": "地点",
        "character_states": "人物处境",
        "known_facts": "已经知道",
        "open_threads": "尚未解决",
    }
    lines = []
    summary = _as_text(value.get("summary"))
    if summary:
        lines.append(summary)
    for key, label in labels.items():
        child = value.get(key)
        if isinstance(child, list):
            text = "；".join(_as_text(item) for item in child if _as_text(item))
        else:
            text = _as_text(child)
        if text:
            lines.append(f"{label}：{text}")
    return "；".join(lines)


def _format_stage_plan_preview(result):
    lines = []
    skeleton = result.get("stage_skeleton", [])
    if isinstance(skeleton, list) and skeleton:
        skeleton_lines = ["全书阶段骨架："]
        for index, item in enumerate(skeleton, 1):
            if not isinstance(item, dict):
                continue
            stage_id = _as_text(item.get("id")) or f"S{index:02d}"
            name = _as_text(item.get("name")) or f"阶段{index}"
            start = _as_text(item.get("start_chapter"))
            end = _as_text(item.get("end_chapter"))
            range_text = f"（第{start}—{end}章）" if start and end else ""
            skeleton_lines.append(f"{stage_id} · {name}{range_text}")
            summary = _as_text(item.get("summary"))
            if summary:
                skeleton_lines.append(f"  主线变化：{summary}")
            turns = _normalize_stage_text_list(item.get("turning_points", []))
            if turns:
                skeleton_lines.append("  关键转折：" + "；".join(turns))
            end_state = _as_text(item.get("end_state"))
            if end_state:
                skeleton_lines.append(f"  阶段结束：{end_state}")
        if len(skeleton_lines) > 1:
            lines.append("\n".join(skeleton_lines))
    contract = result.get("book_contract", {})
    contract_labels = (
        ("hard_facts", "全书固定事实"),
        ("world_invariants", "长期成立的规则"),
        ("character_boundaries", "人物不能随意改变的边界"),
        ("ending_boundaries", "结尾必须守住的边界"),
    )
    if isinstance(contract, dict):
        for key, label in contract_labels:
            values = _normalize_stage_text_list(contract.get(key, []))
            if values:
                lines.append(f"{label}：\n" + "\n".join(f"・{item}" for item in values))
    for index, item in enumerate(result.get("stage_plan", []), 1):
        if not isinstance(item, dict):
            continue
        if not _stage_has_meaningful_content(item):
            continue
        name = _as_text(item.get("name")) or f"阶段{index}"
        start = _as_text(item.get("start_chapter"))
        end = _as_text(item.get("end_chapter"))
        header = f"第 {start}-{end} 章 · {name}" if start and end else name
        block = [header]
        entry = _format_stage_state_preview(item.get("entry_state", {}))
        if entry:
            block.append(f"开始时：{entry}")
        conflict = _as_text(item.get("main_conflict"))
        if conflict:
            block.append(f"本阶段阻碍核心动机的问题：{conflict}")
        events = item.get("ordered_events", [])
        if isinstance(events, list) and events:
            block.append("按顺序发生：")
            for event_index, event in enumerate(events, 1):
                if not isinstance(event, dict):
                    continue
                event_text = _as_text(event.get("event"))
                result_text = _as_text(event.get("result"))
                allowed = event.get("allowed_chapters", [])
                allowed_text = ""
                if isinstance(allowed, list) and len(allowed) >= 2:
                    allowed_text = f"（第{allowed[0]}—{allowed[1]}章之间）"
                if event_text:
                    block.append(f"{event_index}. {event_text}{allowed_text}")
                if result_text:
                    block.append(f"   结果：{result_text}")
                delta = event.get("state_delta", {})
                delta_text = _format_stage_state_preview(delta)
                if delta_text:
                    block.append(f"   变化：{delta_text}")
        summary = _as_text(item.get("summary"))
        if summary and not events:
            block.append(f"阶段内容：{summary}")
        exit_state = _format_stage_state_preview(item.get("exit_state", {}))
        if exit_state:
            block.append(f"结束时：{exit_state}")
        carry = _normalize_stage_text_list(item.get("carry_over", []))
        if carry:
            block.append("带入下一阶段：" + "；".join(carry))
        lines.append("\n".join(block))
    note = _clean_chapter_plan_note(result.get("chapter_plan_note"))
    if note:
        lines.append(f"章节规划要守住：\n{note}")
    return "\n\n".join(lines).strip()


def format_creation_preview(step, result):
    """给向导展示可读的完整摘要，完整结构仍保存在 step_results。"""
    result = result if isinstance(result, dict) else {}
    if step == "bible":
        return _format_bible_preview(result)
    if step == "story_assets":
        return _format_story_assets_preview(result) or "AI 已生成故事人物、设定和暗线。"
    if step == "stage_plan":
        return _format_stage_plan_preview(result) or "AI 还没有生成有效的阶段规划。"
    return format_creation_text(result)


def _expected_stage_count(total_words):
    try:
        return max(1, int(math.ceil(max(1, int(total_words or 500000)) / 100000)))
    except (TypeError, ValueError):
        return 5


def normalize_stage_plan_ranges(
    stage_plan,
    total_words,
    average_chapter_words,
    expected_count=None,
    pad_missing=True,
):
    """把阶段范围校正为连续覆盖全书的章节范围。"""
    source = [deepcopy(item) for item in stage_plan if isinstance(item, dict)]
    if expected_count is None:
        expected_count = _expected_stage_count(total_words)
    else:
        try:
            expected_count = max(0, int(expected_count))
        except (TypeError, ValueError):
            expected_count = len(source)
    # A partial response may contain only S04.  The old implementation used
    # list position as the stage identity, so a later retry could silently
    # turn S04 into S02.  Keep explicit ids in their original slots and use
    # the full book stage count for chapter bounds even when placeholders are
    # not returned to the caller.
    explicit_slots = {}
    unassigned = []
    for item in source:
        slot = _creation_stage_index(item.get("id"))
        if 0 <= slot < max(expected_count, _expected_stage_count(total_words)):
            if slot not in explicit_slots:
                explicit_slots[slot] = item
            else:
                unassigned.append(item)
        else:
            unassigned.append(item)
    logical_count = max(
        expected_count,
        _expected_stage_count(total_words),
        (max(explicit_slots) + 1) if explicit_slots else 0,
    )
    free_slots = [index for index in range(logical_count) if index not in explicit_slots]
    for item, slot in zip(unassigned, free_slots):
        explicit_slots[slot] = item
    if pad_missing:
        for index in range(logical_count):
            explicit_slots.setdefault(index, {"id": f"S{index + 1:02d}"})
    bounds, _total_chapters = _stage_chapter_bounds(
        [{} for _ in range(logical_count)],
        total_words,
        average_chapter_words,
    )
    normalized = []
    for index in sorted(explicit_slots):
        item = explicit_slots[index]
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
        item["entry_state"] = _normalize_stage_state(
            _first_value(item, ("entry_state", "start_state", "进入状态"), {})
        )
        item["exit_state"] = _normalize_stage_state(
            _first_value(item, ("exit_state", "end_state_detail", "离开状态"), {})
        )
        raw_events = _first_value(
            item,
            ("ordered_events", "events", "event_nodes", "事件节点"),
            [],
        )
        events = []
        for event_index, event in enumerate(_as_list(raw_events), 1):
            normalized_event = _normalize_transport_stage_event(
                event,
                f"S{index + 1:02d}-E{event_index:02d}",
            )
            if normalized_event:
                event_id = _canonical_stage_event_id(
                    normalized_event.get("id"),
                    index,
                )
                if event_id:
                    normalized_event["id"] = event_id
                events.append(normalized_event)
        recovered_events, carry_over = _restore_stage_events_from_carry_over(
            _first_value(item, ("carry_over", "carryover", "带入下一阶段"), []),
            index,
        )
        event_indexes = {
            _as_text(event.get("id")).upper(): event_index
            for event_index, event in enumerate(events)
            if _as_text(event.get("id"))
        }
        for recovered in recovered_events:
            event_id = _as_text(recovered.get("id")).upper()
            if event_id and event_id in event_indexes:
                existing_index = event_indexes[event_id]
                existing = events[existing_index]
                if _stage_event_content_score(recovered) > _stage_event_content_score(existing):
                    events[existing_index] = recovered
            elif recovered:
                event_indexes[event_id] = len(events)
                events.append(recovered)
        item["ordered_events"] = events
        item["carry_over"] = carry_over
        # Legacy fields remain available to old project readers, but all new
        # planning requests use the structured fields above as the source of truth.
        for key in (
            "name", "summary", "main_conflict", "relationship_changes",
            "character_changes", "world_reveals", "turning_points",
            "foreshadow_actions", "end_state", "next_stage_hook",
        ):
            if isinstance(item.get(key), list):
                item[key] = _normalize_stage_text_list(item.get(key))
            elif key in item:
                item[key] = _as_text(item.get(key))
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


def _creation_stage_batch_specs(total_words, average_chapter_words):
    """Return deterministic ten-thousand-word stage batches for the wizard."""
    stage_count = _expected_stage_count(total_words)
    bounds, total_chapters = _stage_chapter_bounds(
        [{} for _ in range(stage_count)],
        total_words,
        average_chapter_words,
    )
    specs = []
    for index, (start_chapter, end_chapter) in enumerate(bounds):
        target_words = 100000
        if index == stage_count - 1:
            target_words = max(
                1,
                int(total_words or 500000) - 100000 * index,
            )
        specs.append({
            "number": index + 1,
            "id": f"S{index + 1:02d}",
            "total_stages": stage_count,
            "start_chapter": start_chapter,
            "end_chapter": end_chapter,
            "target_words": target_words,
            "total_chapters": total_chapters,
        })
    return specs


def _normalize_stage_skeleton(value, total_words=500000, average_chapter_words=3000):
    """Normalize the compact whole-book stage anchor without changing stage data."""
    if isinstance(value, dict):
        value = _first_value(value, ("stages", "items", "g", "阶段"), [])
    raw_items = _as_list(value)
    if not raw_items:
        return []
    specs = _creation_stage_batch_specs(total_words, average_chapter_words)
    by_index = {}
    for position, raw in enumerate(raw_items):
        if isinstance(raw, (list, tuple)):
            raw = _compact_record(
                raw,
                ("id", "name", "summary", "turning_points", "end_state"),
            )
        if not isinstance(raw, dict):
            continue
        raw_id = _as_text(_first_value(raw, ("id", "stage_id", "阶段编号", "i")))
        stage_index = _creation_stage_index(raw_id)
        if stage_index < 0:
            stage_index = position if position < len(specs) else -1
        if not 0 <= stage_index < len(specs) or stage_index in by_index:
            continue
        turning_points = _normalize_stage_text_list(
            _first_value(raw, ("turning_points", "turns", "关键转折", "转折"), [])
        )
        row = {
            "id": specs[stage_index]["id"],
            "name": _as_text(_first_value(raw, ("name", "title", "阶段名称"))),
            "start_chapter": specs[stage_index]["start_chapter"],
            "end_chapter": specs[stage_index]["end_chapter"],
            "target_words": specs[stage_index]["target_words"],
            "summary": _as_text(
                _first_value(raw, ("summary", "core_conflict", "main_line", "阶段主线"))
            ),
            "turning_points": turning_points,
            "end_state": _as_text(
                _first_value(raw, ("end_state", "ending_state", "阶段结束", "结束状态"))
            ),
        }
        if row["name"] or row["summary"] or row["turning_points"] or row["end_state"]:
            by_index[stage_index] = row
    return [by_index[index] for index in sorted(by_index)]


def _compact_stage_plan_handoff(stage_plan):
    """给下一阶段保留连续性事实，去掉重复的空分类和展示字段。"""
    compacted = []
    for stage in stage_plan if isinstance(stage_plan, list) else []:
        if not isinstance(stage, dict):
            continue
        row = {}
        for key in ("id", "name", "start_chapter", "end_chapter"):
            value = stage.get(key)
            if value not in (None, "", [], {}):
                row[key] = deepcopy(value)
        for key in ("entry_state", "exit_state", "carry_over"):
            value = stage.get(key)
            if value not in (None, "", [], {}):
                row[key] = deepcopy(value)
        events = []
        for event in stage.get("ordered_events", []) if isinstance(stage.get("ordered_events"), list) else []:
            if not isinstance(event, dict):
                continue
            event_row = {}
            for key in (
                "id", "allowed_chapters", "references", "preconditions",
                "event", "result", "state_delta",
            ):
                value = event.get(key)
                if key == "state_delta" and isinstance(value, dict):
                    value = {
                        child_key: deepcopy(child_value)
                        for child_key, child_value in value.items()
                        if child_value not in (None, "", [], {})
                    }
                if value not in (None, "", [], {}):
                    event_row[key] = value
            if event_row:
                events.append(event_row)
        if events:
            row["ordered_events"] = events
        if row:
            compacted.append(row)
    return compacted


def _merge_foreshadow_schedule_rows(existing, incoming, total_chapters=0):
    """Merge stage-local setup/payoff rows without losing earlier endpoints."""
    rows = _normalize_foreshadow_schedule(existing, total_chapters)
    incoming_rows = _normalize_foreshadow_schedule(incoming, total_chapters)
    indexes = {}
    for index, row in enumerate(rows):
        key = _as_text(row.get("code")).upper() or _as_text(row.get("name"))
        if key:
            indexes[key] = index
    for row in incoming_rows:
        key = _as_text(row.get("code")).upper() or _as_text(row.get("name"))
        if not key:
            continue
        if key not in indexes:
            indexes[key] = len(rows)
            rows.append(deepcopy(row))
            continue
        target = rows[indexes[key]]
        for field in (
            "code", "name", "setup_chapter", "payoff_chapter",
            "setup_event_id", "payoff_event_id", "setup_event", "payoff_event",
        ):
            value = _as_text(row.get(field))
            if value:
                if (
                    field == "payoff_chapter"
                    and _as_text(target.get(field)) == "结尾保留"
                    and value != "结尾保留"
                ):
                    continue
                target[field] = value
    return rows


def build_chapter_plan_foundation(framework):
    """将向导确认内容投影到已有章节规划可识别的基础字段。"""
    framework = framework if isinstance(framework, dict) else {}
    premise = framework.get("premise", {}) if isinstance(framework.get("premise"), dict) else {}
    bible = framework.get("bible", {}) if isinstance(framework.get("bible"), dict) else {}
    world_rules = framework.get("world_rules", {}) if isinstance(framework.get("world_rules"), dict) else {}
    stages = framework.get("stage_plan", []) if isinstance(framework.get("stage_plan"), list) else []
    book_contract = _normalize_stage_book_contract(framework.get("book_contract", {}))
    total_words = int(framework.get("total_words", 500000) or 500000)
    average_words = int(framework.get("average_chapter_words", 3000) or 3000)
    bounds, total_chapters = _stage_chapter_bounds(stages, total_words, average_words)
    terminal_bounds = _terminal_window_bounds(total_chapters)
    framework_core_motive = _as_text(framework.get("core_motive", ""))
    bible_main_conflict = _as_text(bible.get("main_conflict", ""))
    premise_mainline = _as_text(premise.get("main_line", ""))
    premise_core_motive = _as_text(premise.get("core_motive", "")) or premise_mainline
    # Bible.main_conflict is the completed, user-confirmed core-motive
    # contract.  The premise value is only a fallback for older or partial
    # projects where the second step has not supplied it yet.
    core_motive = framework_core_motive or bible_main_conflict or premise_core_motive
    core_mainline = core_motive
    relationship_engine = _as_text(premise.get("relationship_engine", ""))
    reading_experience = _as_text(premise.get("one_sentence", "")) or _as_text(bible.get("reader_promise", ""))
    profile = {
        "version": "creation_wizard_v1",
        "audience_direction": _as_text(premise.get("audience", "")),
        "genre_world": _as_text(premise.get("genre", "")),
        "core_reader_promise": reading_experience,
        "core_motive": core_motive,
        "primary_story_engine": (
            "由核心动机驱动：主角为了完成具体目标主动行动，阻碍、代价和结果把故事推向下一阶段。"
            if core_motive else
            "让人物在具体事情里作出选择，并承担选择带来的变化。"
        ),
        "secondary_story_engine": relationship_engine,
        "planning_grammar": "每一段都写人物正在经历的事情、当下的选择和事情留下的变化，不把后面的故事提前塞进当前内容。",
        "pacing_strategy": "按照题材本身的快慢推进，让悬念、情绪、行动和结果自然交替，不套固定场面。",
        "low_exposition_strategy": "只在人物看见、听见或需要作出选择时带出世界信息。",
        "story_direction": "让人物在具体事情里持续作出选择，保持题材的核心读感，让伏笔随着人物行动和关系变化逐步显出意义，结尾先形成本部明确结果，再保留不影响闭环的余波。",
        "satisfaction_currencies": ["具体事情带来的结果", "人物选择造成的变化", "身份或认知被揭开", "本部结果落地后的余波"],
        "emotional_resonance_axes": ["人物在现实压力下的选择", "靠近、疏远或反目", "核心结果落地后仍可保留的情绪或背景余波"],
        "chapter_variation_pool": ["现实阻力", "人物选择", "利益交换", "新信息出现", "关系发生变化"],
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
            "story_direction": "；".join(
                value for value in (
                    _as_text(stage.get("summary", "")),
                    _as_text(stage.get("main_conflict", "")),
                    _as_text(stage.get("end_state", "")),
                ) if value
            ),
            "core_motive": core_motive,
        }
        arcs.append(arc)
    summary = _as_text(premise.get("synopsis", ""))
    ending = _as_text(premise.get("ending_direction", "")) or _as_text(bible.get("ending_direction", ""))
    boundaries = _as_text(bible.get("hard_boundaries", "")) or (
        "本部核心矛盾和主角当前目标在结尾形成明确结果；可以保留不影响本部结局的续作余味。"
    )
    return {
        "planning_schema_version": _as_text(framework.get("planning_schema_version", "2")) or "2",
        "summary": summary,
        "core_mainline": core_mainline,
        "core_motive": core_motive,
        "ending_promise": ending,
        "global_hard_boundaries": boundaries,
        "target_words": total_words,
        "average_chapter_words": average_words,
        "total_chapter_count": total_chapters,
        "existing_chapter_count": 0,
        "terminal_window": {
            "start_chapter": terminal_bounds[0],
            "end_chapter": terminal_bounds[1],
            "chapter_count": terminal_bounds[1] - terminal_bounds[0] + 1,
            "source": "creation_wizard",
        } if terminal_bounds else {},
        "narrative_strategy_profile": profile,
        "creative_intent_contract": {
            "primary_line": core_motive,
            "core_motive": core_motive,
            "core_relationships": _as_text(premise.get("relationship_engine", "")),
            "stage_progression": "；".join(_as_text(item.get("name", "")) for item in stages if isinstance(item, dict)),
            "reading_experience": _as_text(premise.get("one_sentence", "")),
            "ending_boundaries": ending,
            "source": "creation_wizard",
            "version": "1",
        },
        "book_contract": book_contract,
        "stage_skeleton": deepcopy(framework.get("stage_skeleton", [])),
        "structured_stages": deepcopy(stages),
        "arcs": arcs,
    }


_CONTEXT_LABELS = {
    "author_input": "作者刚才说的想法",
    "inspiration": "灵感和暂定想法",
    "temporary_title": "暂定书名",
    "genre": "故事类型",
    "audience": "读者方向",
    "style": "希望采用的叙述味道",
    "protagonist_route": "主角的起点",
    "story_engine": "故事推进的感觉",
    "length": "预计篇幅",
    "total_words": "预计总字数",
    "average_chapter_words": "每章大约字数",
    "chapter_words": "单章字数",
    "no_injury": "必须守住的写法",
    "ending": "结尾倾向",
    "confirmed": "前面已经确认的故事资料",
    "generation_batch": "这次生成的部分",
    "previous_stage_plan": "前面已经完成的阶段",
    "previous_foreshadow_schedule": "前面已经确定的暗线位置",
    "current_foreshadow_endpoints": "本阶段会进入场景并产生变化的暗线端点",
    "current_stage": "这一次要生成的阶段",
    "number": "阶段编号",
    "total_stages": "阶段总数",
    "start_chapter": "开始章节",
    "end_chapter": "结束章节",
    "target_words": "这一阶段字数",
    "total_chapters": "全书总章数",
    "premise": "已经选定的故事",
    "selected": "已经选定的版本",
    "candidates": "其它备选版本",
    "stage_summary": "这一段故事",
    "end_state": "这一段结束时的变化",
    "next_hook": "下一段从什么变化开始",
    "next_stage_hook": "下一段从什么变化开始",
    "title": "书名",
    "one_sentence": "故事钩子",
    "synopsis": "故事简介",
    "protagonist": "主角眼下的处境和想要的东西",
    "main_line": "核心动机主线（旧字段）",
    "core_motive": "核心动机主线",
    "relationship_engine": "人物关系怎样变化",
    "ending_direction": "本部结尾方向（结果与余波）",
    "bible": "故事的核心",
    "novel_bible": "故事的核心",
    "core_setting": "核心设定",
    "reader_promise": "持续悬念",
    "theme": "主题",
    "main_conflict": "核心动机契约（主线矛盾）",
    "relationship_foundation": "人物关系底子",
    "hard_boundaries": "必须守住的边界",
    "world_rules": "世界里的规矩",
    "world": "世界里的规矩",
    "setting_overview": "世界概况",
    "power_system": "能力边界",
    "ability_system": "故事里的能力边界",
    "description": "说明",
    "limits": "不能越过的边界",
    "levels": "实力层次",
    "narrative_strategy_profile": "这本书的写法",
    "creative_intent_contract": "作者想写的故事",
    "primary_story_engine": "故事怎样被往前推",
    "secondary_story_engine": "人物关系怎样变化",
    "core_reader_promise": "读者会一直追问的事",
    "planning_grammar": "故事继续往前走的写法",
    "pacing_strategy": "故事快慢的感觉",
    "low_exposition_strategy": "世界信息怎样自然出现",
    "story_direction": "故事方向",
    "satisfaction_currencies": "故事里的具体回响",
    "emotional_resonance_axes": "人物情绪的变化",
    "chapter_variation_pool": "故事里可以出现的变化",
    "name": "名字",
    "capability": "这一层能做到的事",
    "limit": "这一层做不到的事",
    "promotion": "怎样自然变强",
    "rules": "不能随便改变的规矩",
    "costs_and_limits": "使用力量和获得资源要付出的代价",
    "factions": "势力",
    "position": "立场",
    "relationship_to_protagonist": "和主角的关系",
    "geography_and_life": "地点和日常生活",
    "story_assets": "人物、地方和暗线",
    "characters": "人物",
    "role": "身份和故事位置",
    "goal": "想得到或守住的东西",
    "secret": "藏着的事",
    "personality": "人物性格/特点",
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
    "story_known": "人物已知",
    "relationship_effect": "它会怎样改变人物关系",
    "key_scenes": "适合发生故事的地方",
    "atmosphere": "现场的感觉",
    "conflict_use": "这里适合发生的冲突",
    "foreshadows": "埋在故事里的暗线",
    "status": "现在的状态",
    "setup_chapter": "暗线出现的位置",
    "payoff_chapter": "暗线发生变化的位置",
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
    "open_threads": "仍在发展的线索",
    "chapter_plan_note": "后面逐章写故事时要守住的边界",
}

_CONTEXT_OMIT_KEYS = {
    "schema_version", "source", "completed_at", "selected_index", "version", "enabled",
    "_generation_state", "completed_batches", "next_batch", "next_stage_index",
    "generation_batch",
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
    """Serialize wizard input without repeating a human-readable field tree.

    The model still receives the complete confirmed facts, but the transport
    envelope no longer expands every dictionary into labels, list numbers and
    indentation.  Only the outer, repetitive wrapper keys use short aliases;
    story records keep their semantic field names so the model can read them
    without a second schema table.
    """
    context = context if isinstance(context, dict) else {}
    compact_keys = {
        "author_input": "a",
        "selected_premise": "p",
        "confirmed": "c",
        "generation_batch": "b",
        "current_stage": "s",
        "previous_stage_plan": "h",
        "previous_foreshadow_schedule": "f",
        "naming_reference": "n",
    }
    transport = {
        compact_keys.get(key, key): deepcopy(value)
        for key, value in context.items()
        if value not in (None, "", [], {})
    }
    return (
        "下面是作者已经说过、或在前面亲自确认过的故事资料。"
        "只沿着这些资料往下写，不替作者改掉题材、人物选择、结尾方向和必须守住的边界。"
        "输入 JSON 中 a=作者输入，p=已选故事，c=前面确认的资料，b=本次批次，"
        "s=当前阶段，h=前面阶段，f=暗线位置，n=命名参考；其余字段按原名读取。"
        "a.inspiration 是作者亲自写下的完整灵感原文，里面的书名、标签、简介、人物、关系、情节、场景、爽点和节奏要求都要逐项吸收；"
        "a.requested_title 是作者已经明确确定的书名；只要它非空，后续返回中的书名必须原样保留，不能改写、缩写或另起书名；"
        "a 里的主分类、主题、读者方向、风格和主角起点是硬要求，不要只在标签里提到，也不要用相似题材替换。"
        "不要逐条复述资料，直接写出人物和事情。\n"
        + json.dumps(transport, ensure_ascii=False, separators=(",", ": "))
    )


def _creation_scale_requirements(total_words):
    """Return the minimum long-form material counts derived from stage count."""
    try:
        total_words = max(1, int(total_words or 500000))
    except (TypeError, ValueError):
        total_words = 500000
    stage_count = _expected_stage_count(total_words)
    minimum = stage_count * 5
    if stage_count >= 10:
        size_label = "100万字以上"
    elif stage_count == 5:
        size_label = "约50万字"
    elif stage_count == 3:
        size_label = "约30万字"
    else:
        size_label = f"约{stage_count * 10}万字"
    ranges = {
        "characters": (minimum, minimum),
        "lore": (minimum, minimum),
        # Foreshadow count is a quality-guided reference, not a hard quota.
        # A smaller set of closed, usable lines is preferable to filler clues.
        "foreshadows": (0, 0),
    }
    return size_label, ranges


def _creation_scale_shortfalls(result, total_words):
    _size_label, ranges = _creation_scale_requirements(total_words)
    result = result if isinstance(result, dict) else {}
    labels = {
        "characters": "主要人物",
        "lore": "设定",
    }
    shortfalls = []
    for key in ("characters", "lore"):
        minimum = ranges[key][0]
        value = result.get(key, [])
        count = len(value) if isinstance(value, list) else 0
        if count < minimum:
            shortfalls.append(f"{labels[key]} {count}/{minimum}")

    # Do not reject a story because it has fewer foreshadows in a stage.
    # Count is intentionally advisory; endpoint validity is checked separately.
    return shortfalls


def _creation_scale_guidance(total_words):
    """根据阶段数给故事底盘提供资料最低数量。"""
    size_label, ranges = _creation_scale_requirements(total_words)
    stage_count = _expected_stage_count(total_words)
    characters = ranges["characters"][0]
    lore = ranges["lore"][0]
    return f"""
这不是只够写开头几章的简介，而是预计写到{size_label}、分为{stage_count}个十万字阶段的整本长篇底盘。数量是后续阶段规划和章节规划的最低资料规模，不要只列主角和少量配角，也不要把同一项换名字重复填写：
- 每个阶段至少准备5名能在该阶段发挥作用的人物，全书人物最低{characters}名；人物要覆盖主角身边的人、对手、关键势力代表、现实生活中的牵连人物和后期可能改变立场的人。
- 每个阶段至少准备5项会在该阶段反复起作用的设定，全书设定最低{lore}项；统一写入 lore，覆盖地点、场景落点、物件、势力、制度、日常生活和题材本身的能力边界。
- 按每个阶段的故事需要准备能够真正落地的伏笔；每条都必须是单一问题、单一答案、单一结果的可回收闭环。
- 伏笔数量只是建议参考，不是硬性配额。质量优先、数量不够时不硬凑；写不出具体回收场景的内容放回主线、人物或设定，不要为了数量拆出宽泛伏笔。
人物和设定数量是最低参考，不是上限；伏笔不设阶段硬配额。所有资料都必须从作者灵感和已经选定的故事自然长出来，不要为了凑数添加没有根的名词。
这些内容都必须从作者灵感和已经选定的故事自然长出来。人物、设定和伏笔之间要互相牵连，但不要把它们写成重复的剧情简介。故事简介仍然需要自然、可读、可以公开发布；其余字段以清楚、稳定、方便后续执行为先。
""".strip()


def _creation_foreshadow_distribution_guidance(total_words):
    """Tell the model to distribute only story-supported foreshadows."""
    return (
        "伏笔按故事需要分布，不要求每个阶段必须有固定数量，也不要求为了覆盖阶段而新增无根线索。"
        "每条伏笔的 setup_stage 只填写一个明确阶段；如果某阶段没有自然成立的伏笔，可以为空，不要硬凑。"
        "每个阶段已有的伏笔中，大多数应是普通可回收闭环，payoff_stage 不能写成结尾保留；"
        "结尾保留只用于真正贯穿全书核心矛盾的少量主线谜团，整本原则上不超过伏笔总数的五分之一。"
        "输出前逐条检查 f 的 setup_stage、核心问题和回收结果；质量优先，数量不足不补造宽泛线索。"
    )


def _creation_foreshadow_stage_guidance(total_words):
    """给故事底盘安排阶段级伏笔位置，不提前锁死具体章节。"""
    try:
        total_words = max(1, int(total_words or 500000))
    except (TypeError, ValueError):
        total_words = 500000
    stage_count = max(1, int(math.ceil(total_words / 100000)))
    return f"""
本书预计按每约十万字分为 {stage_count} 个阶段。第二步先为每条伏笔安排“从哪个阶段进入故事、在哪个后续阶段完整回收”，setup_stage 和 payoff_stage 填写阶段位置，范围为“第1阶段”到“第{stage_count}阶段”；普通伏笔的 payoff_stage 表示核心问题已经在具体场景中得到答案、责任或原因已经明确、并产生了可观察的直接结果，不能只表示线索再次出现、局势升级或部分揭示。普通伏笔优先让 setup_stage 早于 payoff_stage；只有短线且能在一个连续场景内闭合的伏笔才允许同阶段回收。仍然留到结尾的暗线，payoff_stage 写“结尾保留”，但只允许少量真正贯穿全书核心矛盾的主线谜团使用。具体章号由第三步结合阶段边界、总字数和单章字数落下，因此第二步只保留阶段参考。
""".strip()


def _creation_total_chapters(total_words, average_chapter_words):
    try:
        total_words = max(1, int(total_words or 500000))
    except (TypeError, ValueError):
        total_words = 500000
    try:
        average_chapter_words = max(1, int(average_chapter_words or 3000))
    except (TypeError, ValueError):
        average_chapter_words = 3000
    return max(1, int(math.ceil(total_words / average_chapter_words)))


def _creation_chapter_number(value):
    """Read one concrete chapter number from a wizard planning field."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (int, float)):
        try:
            number = int(value)
        except (TypeError, ValueError):
            return 0
        return number if number > 0 else 0
    text = _as_text(value)
    if not text:
        return 0
    match = re.search(r"(?:第\s*)?(\d{1,4})\s*(?:章|回|节)?", text)
    if match:
        try:
            number = int(match.group(1))
        except (TypeError, ValueError):
            return 0
        return number if number > 0 else 0
    chinese_digits = {
        "零": 0, "〇": 0, "一": 1, "二": 2, "两": 2, "三": 3,
        "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
    }
    match = re.search(r"第\s*([零〇一二两三四五六七八九十百千万]+)\s*[章回节]?", text)
    if not match:
        return 0
    raw = match.group(1)
    if raw == "十":
        return 10
    if "十" in raw:
        left, _, right = raw.partition("十")
        tens = chinese_digits.get(left, 1) if left else 1
        ones = chinese_digits.get(right, 0) if right else 0
        return tens * 10 + ones
    if "百" in raw or "千" in raw or "万" in raw:
        units = {"十": 10, "百": 100, "千": 1000, "万": 10000}
        total = 0
        current = 0
        for char in raw:
            if char in chinese_digits:
                current = chinese_digits[char]
            elif char in units:
                total += (current or 1) * units[char]
                current = 0
        return total + current
    return chinese_digits.get(raw, 0)


def _normalize_creation_stage_ref(value, stage_count=0):
    """Normalize a second-step stage reference without treating it as a chapter."""
    if isinstance(value, bool):
        return ""
    text = _as_text(value)
    if not text:
        return ""
    if text in {"结尾保留", "结尾开放", "不回收", "暂不回收", "保留到结尾"}:
        return "结尾保留"
    number = _creation_chapter_number(value)
    if number <= 0:
        return ""
    try:
        stage_count = int(stage_count or 0)
    except (TypeError, ValueError):
        stage_count = 0
    if stage_count and number > stage_count:
        return ""
    return f"第{number}阶段"


def _foreshadow_stage_shortfalls(foreshadows, stage_count):
    """Find missing or out-of-range stage references from the second step."""
    missing = []
    for record in foreshadows if isinstance(foreshadows, list) else []:
        if not isinstance(record, dict):
            continue
        setup = _normalize_creation_stage_ref(
            record.get("setup_stage"),
            stage_count,
        )
        payoff = _normalize_creation_stage_ref(
            record.get("payoff_stage"),
            stage_count,
        )
        setup_number = _creation_chapter_number(setup)
        payoff_number = _creation_chapter_number(payoff)
        # A foreshadow can be introduced and resolved within one ten-thousand-word
        # stage. It only becomes invalid when the payoff is placed in an earlier stage.
        valid_payoff = payoff == "结尾保留" or (
            setup_number > 0 and payoff_number >= setup_number
        )
        if setup_number <= 0 or not valid_payoff:
            missing.append(
                _as_text(record.get("code"))
                or _as_text(record.get("name"))
            )
    return missing


def _normalize_creation_chapter_ref(value, total_chapters=0):
    text = _as_text(value)
    if not text:
        return ""
    # 阶段参考只能在 setup_stage/payoff_stage 中存在，不能被解析成同号章节。
    if "阶段" in text:
        return ""
    if text in {"结尾保留", "结尾开放", "不回收", "暂不回收", "保留到结尾"}:
        return "结尾保留"
    # A range is not a chapter assignment. Leave it empty so validation can
    # request one concrete chapter instead of silently choosing one endpoint.
    if re.search(
        r"(?:\d|[一二三四五六七八九十百千万零〇])\s*(?:至|到|[-—])\s*"
        r"(?:\d|[一二三四五六七八九十百千万零〇])",
        text,
    ):
        return ""
    number = _creation_chapter_number(value)
    if number <= 0:
        return ""
    if total_chapters:
        number = min(number, int(total_chapters))
    return f"第{number}章"


def _normalize_foreshadow_endpoint_kind(value):
    text = _as_text(value).lower()
    if text in {"setup", "set", "埋设", "埋下", "出现", "起点"}:
        return "setup"
    if text in {"payoff", "resolve", "reveal", "回收", "揭示", "兑现", "终点"}:
        return "payoff"
    return ""


def _foreshadow_key(value):
    if not isinstance(value, dict):
        return ""
    code = _normalize_foreshadow_code(value.get("code"))
    if code:
        return code
    return _as_text(value.get("name"))


def _foreshadow_lookup_key(value):
    """Build the same lookup key for baseline and transport rows."""
    if not isinstance(value, dict):
        return ""
    code = _normalize_foreshadow_code(value.get("code"))
    if code:
        return code
    return _as_text(value.get("name"))


def _normalize_stage_event_foreshadow_refs(event):
    """Normalize legacy F1/F01 references without changing their meaning."""
    if not isinstance(event, dict):
        return
    references = event.get("references", [])
    was_list = isinstance(references, list)
    values = references if was_list else ([references] if references else [])
    normalized = []
    for reference in values:
        text = _as_text(reference)
        if text:
            text = re.sub(
                r"(?<![A-Z0-9])F0*\d{1,7}(?![A-Z0-9])",
                lambda match: _normalize_foreshadow_code(match.group(0))
                or match.group(0),
                text,
                flags=re.IGNORECASE,
            )
            normalized.append(text)
    if normalized:
        event["references"] = normalized if was_list else normalized[0]


def _stage_index_from_ref(value, stage_count=0):
    normalized = _normalize_creation_stage_ref(value, stage_count)
    if normalized == "结尾保留":
        return -1
    number = _creation_chapter_number(normalized)
    return number - 1 if number > 0 else -1


def _foreshadow_stage_requirements(foreshadows, stage_specs):
    """Return the exact setup/payoff endpoint required in each stage."""
    specs = stage_specs if isinstance(stage_specs, list) else []
    requirements = {index: [] for index in range(len(specs))}
    stage_count = len(specs)
    for record in foreshadows if isinstance(foreshadows, list) else []:
        if not isinstance(record, dict):
            continue
        key = _foreshadow_key(record)
        if not key:
            continue
        name = _as_text(record.get("name"))
        setup_index = _stage_index_from_ref(record.get("setup_stage"), stage_count)
        if 0 <= setup_index < stage_count:
            requirements[setup_index].append({
                "key": key,
                "code": _as_text(record.get("code")),
                "name": name,
                "kind": "setup",
                "stage_index": setup_index,
            })
        payoff_stage = _normalize_creation_stage_ref(
            record.get("payoff_stage"),
            stage_count,
        )
        payoff_index = (
            stage_count - 1
            if payoff_stage == "结尾保留"
            else _stage_index_from_ref(payoff_stage, stage_count)
        )
        if 0 <= payoff_index < stage_count:
            requirements[payoff_index].append({
                "key": key,
                "code": _as_text(record.get("code")),
                "name": name,
                "kind": "payoff",
                "stage_index": payoff_index,
                "tail_reserved": payoff_stage == "结尾保留",
            })
    return requirements


def _foreshadow_endpoint_in_stage(value, kind, requirement, stage_specs, total_chapters=0):
    text = _normalize_creation_chapter_ref(value, total_chapters)
    if kind == "payoff" and requirement.get("tail_reserved"):
        return "结尾保留" if text == "结尾保留" else ""
    chapter = _creation_chapter_number(text)
    try:
        stage_index = int(requirement.get("stage_index", -1))
    except (TypeError, ValueError):
        stage_index = -1
    if chapter <= 0 or not (0 <= stage_index < len(stage_specs)):
        return ""
    spec = stage_specs[stage_index]
    start = int(spec.get("start_chapter", 0) or 0)
    end = int(spec.get("end_chapter", 0) or 0)
    if start <= chapter <= end:
        return f"第{chapter}章"
    return ""


def _canonical_stage_event_id(value, stage_index=-1):
    """Normalize a stage event reference without using list position as identity."""
    text = re.sub(r"\s+", "", _as_text(value).upper())
    if not text:
        return ""
    match = re.fullmatch(r"(?:STAGE[_-]?(\d{1,4})|S[_-]?(\d{1,4}))[_-]?E[_-]?(\d{1,4})", text)
    if match:
        stage_number = int(match.group(1) or match.group(2))
        event_number = int(match.group(3))
        return f"S{stage_number:02d}-E{event_number:02d}"
    match = re.fullmatch(r"E[_-]?(\d{1,4})", text)
    if match and int(stage_index) >= 0:
        return f"S{int(stage_index) + 1:02d}-E{int(match.group(1)):02d}"
    return ""


def _stage_event_anchor_chapter(event, stage_spec, event_index=0, event_count=1):
    """Pick one stable chapter from an event's range.

    The model owns the event range.  The program only chooses the first
    chapter in that range, so an endpoint is never re-planned independently
    from the event that actually contains it.
    """
    if not isinstance(event, dict) or not isinstance(stage_spec, dict):
        return ""
    try:
        stage_start = int(stage_spec.get("start_chapter", 0) or 0)
        stage_end = int(stage_spec.get("end_chapter", 0) or 0)
    except (TypeError, ValueError):
        return ""
    if stage_start <= 0 or stage_end < stage_start:
        return ""
    allowed = event.get("allowed_chapters", [])
    try:
        allowed_start = int(allowed[0])
        allowed_end = int(allowed[1]) if len(allowed) > 1 else allowed_start
    except (TypeError, ValueError, IndexError):
        allowed_start = allowed_end = 0
    if allowed_start > 0 and allowed_end >= allowed_start:
        start = max(stage_start, allowed_start)
        end = min(stage_end, allowed_end)
        if start <= end:
            return f"第{start}章"
    try:
        event_count = max(1, int(event_count or 1))
        event_index = max(0, min(int(event_index or 0), event_count - 1))
    except (TypeError, ValueError):
        event_index, event_count = 0, 1
    chapter = stage_start + int(
        (stage_end - stage_start) * event_index / max(1, event_count - 1)
    )
    return f"第{max(stage_start, min(stage_end, chapter))}章"


def _stage_event_endpoint_detail(event):
    if not isinstance(event, dict):
        return ""
    return "；".join(
        part for part in (
            _as_text(event.get("event")),
            _as_text(event.get("result")),
        ) if part
    )


def _event_references_endpoint(event, requirement):
    """Only use explicit endpoint markers for automatic event association.

    A bare foreshadow name is ordinary story material.  It may legitimately
    appear in several events as a continuing clue or consequence, so it must
    not be promoted to a formal setup/payoff endpoint by itself.
    """
    if not isinstance(event, dict) or not isinstance(requirement, dict):
        return False
    code = _normalize_foreshadow_code(requirement.get("code"))
    kind = _as_text(requirement.get("kind")).lower()
    kind_token = kind.upper()
    references = event.get("references", [])
    references = references if isinstance(references, list) else [references]
    for reference in references:
        text = _as_text(reference)
        upper = text.upper()
        referenced_codes = {
            _normalize_foreshadow_code(match.group(0))
            for match in re.finditer(r"(?<![A-Z0-9])F0*\d{1,7}(?!\d)", upper)
        }
        if code and code in referenced_codes:
            if (
                not kind_token
                or kind_token in upper
                or kind == "setup" and "埋" in text
                or kind == "payoff" and "回" in text
            ):
                return True
    return False


def _derive_stage_endpoint_rows(
    result,
    stage_index,
    stage_specs,
    foreshadows,
    total_chapters=0,
):
    """Attach required endpoints to generated events before schedule merge.

    The stage baseline decides which endpoint belongs here.  The response only
    identifies the event that carries it; chapter placement is derived from
    that event's allowed range.  This removes the fragile second decision in
    which the model had to keep stage, event and exact chapter synchronized.
    """
    specs = stage_specs if isinstance(stage_specs, list) else []
    if not (0 <= int(stage_index) < len(specs)):
        return []
    raw_stages = result.get("stage_plan", []) if isinstance(result, dict) else []
    stages = [item for item in raw_stages if isinstance(item, dict)]
    target_id = _as_text(specs[stage_index].get("id")).upper()
    stage = next(
        (
            item for item in stages
            if _as_text(item.get("id")).upper() == target_id
        ),
        stages[0] if stages else {},
    )
    raw_events = stage.get("ordered_events", []) if isinstance(stage, dict) else []
    events = [item for item in raw_events if isinstance(item, dict)]
    event_lookup = {}
    for index, event in enumerate(events):
        _normalize_stage_event_foreshadow_refs(event)
        event_id = _canonical_stage_event_id(event.get("id"), stage_index)
        if not event_id:
            event_id = f"S{int(stage_index) + 1:02d}-E{index + 1:02d}"
        event["id"] = event_id
        event_lookup[event_id] = (index, event)
        event_lookup[f"E{index + 1:02d}"] = (index, event)

    incoming = _normalize_foreshadow_schedule(result.get("foreshadow_schedule", []), total_chapters)
    requirements = _foreshadow_stage_requirements(foreshadows, specs).get(int(stage_index), [])
    requirement_by_key = {
        (_normalize_foreshadow_code(item.get("code")) or _as_text(item.get("name"))): item
        for item in requirements
    }
    resolved = []
    # A single foreshadow may legitimately have both its setup and payoff in
    # the same stage.  Include the endpoint kind in the deduplication key so
    # the second endpoint is not silently discarded.
    resolved_keys = set()

    def row_key(row):
        return _foreshadow_lookup_key(row)

    def find_requirement(row):
        key = row_key(row)
        requirement = requirement_by_key.get(key)
        if requirement:
            return requirement
        for candidate in requirements:
            if (
                _normalize_foreshadow_code(candidate.get("code"))
                == _normalize_foreshadow_code(row.get("code"))
                and _as_text(candidate.get("kind")) == _as_text(row.get("endpoint_kind"))
            ):
                return candidate
        return None

    def find_event(row, requirement):
        event_ref = _canonical_stage_event_id(
            row.get("endpoint_event_id"),
            stage_index,
        )
        if event_ref and event_ref in event_lookup:
            event_index, event = event_lookup[event_ref]
            # Keep the two compact transport locations synchronized.  When a
            # response names an event in f but omits the matching Fxx/setup or
            # Fxx/payoff marker in the event references, preserve the endpoint
            # and add the missing marker instead of losing the association.
            code = _as_text(requirement.get("code"))
            kind = _as_text(requirement.get("kind")).lower()
            marker = f"{code}/{kind}" if code and kind else ""
            references = event.get("references", [])
            references = list(references) if isinstance(references, list) else ([references] if references else [])
            if marker and not any(_as_text(item).upper() == marker.upper() for item in references):
                references.insert(0, marker)
                event["references"] = references
            return event_index, event
        for index, event in enumerate(events):
            if _event_references_endpoint(event, requirement):
                return index, event
        return None

    for row in incoming:
        kind = _normalize_foreshadow_endpoint_kind(row.get("endpoint_kind"))
        requirement = find_requirement(row) if kind else None
        if not requirement:
            resolved.append(row)
            continue
        key = _normalize_foreshadow_code(requirement.get("code")) or _as_text(requirement.get("name"))
        resolved_key = (key, kind)
        if resolved_key in resolved_keys:
            continue
        event_match = find_event(row, requirement)
        if event_match:
            event_index, event = event_match
            row["endpoint_event_id"] = _as_text(event.get("id"))
            row["endpoint_chapter"] = _stage_event_anchor_chapter(
                event,
                specs[stage_index],
                event_index,
                len(events),
            )
            row["endpoint_event"] = row.get("endpoint_event") or _stage_event_endpoint_detail(event)
        resolved.append(row)
        resolved_keys.add(resolved_key)

    # If f was omitted, recover it from the explicit Fxx/setup or Fxx/payoff
    # token required in the event references.  This is reconstruction from the
    # generated event, not a fabricated chapter or a blanket acceptance rule.
    for requirement in requirements:
        key = _normalize_foreshadow_code(requirement.get("code")) or _as_text(requirement.get("name"))
        kind = _normalize_foreshadow_endpoint_kind(requirement.get("kind"))
        resolved_key = (key, kind)
        if resolved_key in resolved_keys or requirement.get("tail_reserved"):
            continue
        for event_index, event in enumerate(events):
            if not _event_references_endpoint(event, requirement):
                continue
            resolved.append({
                "code": _as_text(requirement.get("code")),
                "name": _as_text(requirement.get("name")),
                "endpoint_kind": kind,
                "endpoint_event_id": _as_text(event.get("id")),
                "endpoint_chapter": _stage_event_anchor_chapter(
                    event,
                    specs[stage_index],
                    event_index,
                    len(events),
                ),
                "endpoint_event": _stage_event_endpoint_detail(event),
            })
            resolved_keys.add(resolved_key)
            break
    return resolved


def _canonicalize_foreshadow_schedule(
    foreshadows,
    schedule,
    stage_specs,
    total_chapters=0,
    strict=False,
):
    """Project schedule rows onto the second-step foreshadowing baseline.

    The baseline owns endpoint stage placement.  A stage response may only
    fill the endpoint that belongs to the current stage; stale legacy fields
    outside that stage are ignored during migration instead of becoming a
    false chapter assignment.
    """
    baseline = [item for item in foreshadows if isinstance(item, dict)]
    by_key = {
        _foreshadow_lookup_key(item): item
        for item in baseline
        if _foreshadow_lookup_key(item)
    }
    requirements = _foreshadow_stage_requirements(baseline, stage_specs)
    requirement_by_key = {}
    for rows in requirements.values():
        for requirement in rows:
            requirement_key = (
                _normalize_foreshadow_code(requirement.get("code"))
                or _as_text(requirement.get("name"))
            )
            requirement_by_key.setdefault(requirement_key, {})[
                requirement["kind"]
            ] = requirement

    canonical = {}
    for item in baseline:
        key = _foreshadow_lookup_key(item)
        if not key:
            continue
        canonical[key] = {
            "code": _normalize_foreshadow_code(item.get("code")) or _as_text(item.get("code")),
            "name": _as_text(item.get("name")),
            "setup_chapter": "",
            "payoff_chapter": "",
            "setup_event_id": "",
            "payoff_event_id": "",
            "setup_event": "",
            "payoff_event": "",
        }

    errors = []
    notes = []
    rows = _normalize_foreshadow_schedule(schedule, total_chapters)

    def assign(target, kind, value, detail, event_id, requirement, explicit):
        if not requirement:
            if explicit and value:
                errors.append(
                    f"{target.get('code') or target.get('name') or '未知伏笔'}的{kind}端点不在第二步确定的阶段内"
                )
            elif value:
                notes.append(
                    f"旧伏笔章位未采用：{target.get('code') or target.get('name') or '未知伏笔'}的{kind}端点为{_as_text(value)}，与第二步阶段位置不一致"
                )
            return
        normalized = _foreshadow_endpoint_in_stage(
            value,
            kind,
            requirement,
            stage_specs,
            total_chapters,
        )
        if not normalized:
            if explicit and value:
                errors.append(
                    f"{target.get('code') or target.get('name') or '未知伏笔'}的{kind}章位不在所属阶段范围内"
                )
            elif value:
                notes.append(
                    f"旧伏笔章位未采用：{target.get('code') or target.get('name') or '未知伏笔'}的{kind}端点为{_as_text(value)}，不在所属阶段范围内"
                )
            return
        target[f"{kind}_chapter"] = normalized
        if event_id:
            target[f"{kind}_event_id"] = _as_text(event_id)
        if detail:
            target[f"{kind}_event"] = _as_text(detail)

    for row in rows:
        key = _foreshadow_lookup_key(row)
        target = canonical.get(key)
        explicit_kind = _normalize_foreshadow_endpoint_kind(row.get("endpoint_kind"))
        endpoint_value = row.get("endpoint_chapter")
        endpoint_detail = row.get("endpoint_event")
        endpoint_event_id = row.get("endpoint_event_id")
        has_legacy_endpoint = any(
            _as_text(row.get(field))
            for field in (
                "setup_chapter", "payoff_chapter", "setup_event", "payoff_event",
            )
        )
        if target is None:
            # Keep a readable diagnostic, not the transport JSON. The strict
            # repair path still fails and retries; stage content is untouched.
            identity = _as_text(row.get("code")) or _as_text(row.get("name")) or "未命名伏笔"
            if has_legacy_endpoint or explicit_kind:
                endpoint = "埋设" if explicit_kind == "setup" else "回收" if explicit_kind == "payoff" else "章位"
                notes.append(
                    f"阶段规划返回的伏笔“{identity}”{endpoint}定位未能对应第二步确认的伏笔，未写入正式章位。"
                )
            if strict:
                errors.append(
                    f"{identity}不是第二步确认的伏笔"
                )
            continue

        requirements_for_key = requirement_by_key.get(key, {})
        if explicit_kind:
            assign(
                target,
                explicit_kind,
                endpoint_value,
                endpoint_detail,
                endpoint_event_id,
                requirements_for_key.get(explicit_kind),
                True,
            )
            continue

        # Legacy a/b rows are accepted only for migration.  Each endpoint is
        # checked against its own baseline stage, so F06's stale b=47 cannot
        # overwrite the real S04 payoff endpoint.
        assign(
            target,
            "setup",
            row.get("setup_chapter"),
            row.get("setup_event"),
            row.get("setup_event_id"),
            requirements_for_key.get("setup"),
            False,
        )
        assign(
            target,
            "payoff",
            row.get("payoff_chapter"),
            row.get("payoff_event"),
            row.get("payoff_event_id"),
            requirements_for_key.get("payoff"),
            False,
        )

    # A tail-reserved payoff is a second-step decision, not something the
    # model needs to rediscover in the final stage response.
    for key, target in canonical.items():
        payoff_requirement = requirement_by_key.get(key, {}).get("payoff")
        if payoff_requirement and payoff_requirement.get("tail_reserved"):
            target["payoff_chapter"] = "结尾保留"
    return [item for item in canonical.values()], notes, errors


def _normalize_foreshadow_schedule(value, total_chapters=0):
    raw_items = value if isinstance(value, list) else []
    normalized = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        code = _as_text(
            _first_value(
                item,
                ("code", "foreshadow_code", "id", "i", "编号", "伏笔编号"),
            )
        )
        code = _normalize_foreshadow_code(code) or code
        name = _as_text(
            _first_value(item, ("name", "title", "n", "伏笔名称", "名称"))
        )
        endpoint_kind = _normalize_foreshadow_endpoint_kind(
            _first_value(item, ("endpoint_kind", "kind", "k", "端点类型", "端点"))
        )
        endpoint_event_id = _as_text(
            _first_value(
                item,
                (
                    "endpoint_event_id", "event_id", "e",
                    "关联事件", "事件编号",
                ),
            )
        )
        endpoint_chapter = _first_value(
            item,
            ("endpoint_chapter", "chapter", "c", "具体章节", "章节"),
        )
        endpoint_event = _as_text(
            _first_value(item, ("endpoint_event", "detail", "d", "端点内容", "内容"))
        )
        setup_event_id = _as_text(
            _first_value(item, ("setup_event_id", "setup_event_ref", "埋设事件编号"))
        )
        payoff_event_id = _as_text(
            _first_value(item, ("payoff_event_id", "payoff_event_ref", "回收事件编号"))
        )
        normalized.append({
            "code": code,
            "name": name,
            "endpoint_kind": endpoint_kind,
            "endpoint_event_id": endpoint_event_id if endpoint_kind else "",
            "endpoint_chapter": _normalize_creation_chapter_ref(
                endpoint_chapter,
                total_chapters,
            ) if endpoint_kind else "",
            "endpoint_event": endpoint_event if endpoint_kind else "",
            "setup_chapter": _normalize_creation_chapter_ref(
                _first_value(item, ("setup_chapter", "setup", "埋设章节", "埋下章节")),
                total_chapters,
            ),
            "payoff_chapter": _normalize_creation_chapter_ref(
                _first_value(item, ("payoff_chapter", "payoff", "回收章节", "揭示章节")),
                total_chapters,
            ),
            "setup_event_id": setup_event_id,
            "payoff_event_id": payoff_event_id,
            "setup_event": _as_text(_first_value(item, ("setup_event", "setup_detail", "埋设内容"))),
            "payoff_event": _as_text(_first_value(item, ("payoff_event", "payoff_detail", "回收内容"))),
        })
    return normalized


def _apply_foreshadow_schedule(foreshadows, schedule, total_chapters=0):
    records = [deepcopy(item) for item in foreshadows if isinstance(item, dict)]
    rows = _normalize_foreshadow_schedule(schedule, total_chapters)
    by_code = {
        _normalize_foreshadow_code(item.get("code")): item
        for item in rows if _as_text(item.get("code"))
    }
    by_name = {
        _as_text(item.get("name")): item
        for item in rows if _as_text(item.get("name"))
    }
    for record in records:
        match = by_code.get(_normalize_foreshadow_code(record.get("code")))
        if match is None:
            match = by_name.get(_as_text(record.get("name")))
        if not match:
            continue
        setup = _as_text(match.get("setup_chapter"))
        payoff = _as_text(match.get("payoff_chapter"))
        setup_number = _creation_chapter_number(setup)
        payoff_number = _creation_chapter_number(payoff)
        valid_payoff = payoff == "结尾保留" or (
            setup_number > 0 and payoff_number >= setup_number
        )
        if setup_number > 0:
            record["setup_chapter"] = setup
        if valid_payoff:
            record["payoff_chapter"] = payoff
    return records


def _restore_foreshadow_stage_baseline(foreshadows):
    """Keep the second-step foreshadow records at stage granularity.

    Concrete chapter placement belongs to the third-step schedule and to the
    final project payload.  Older drafts may have received those chapter
    fields while a stage batch was being generated, so clear them only when
    the corresponding stage fields are present and preserve all story data.
    """
    restored = []
    for item in foreshadows if isinstance(foreshadows, list) else []:
        if not isinstance(item, dict):
            continue
        record = deepcopy(item)
        if _as_text(record.get("setup_stage")):
            record["setup_chapter"] = ""
        if _as_text(record.get("payoff_stage")):
            record["payoff_chapter"] = ""
        restored.append(record)
    return restored


def _stage_foreshadow_shortfalls(foreshadows, schedule, stage_specs, total_chapters=0):
    """Return missing endpoint records grouped by the stage that owns them."""
    specs = stage_specs if isinstance(stage_specs, list) else []
    requirements = _foreshadow_stage_requirements(foreshadows, specs)
    rows = _normalize_foreshadow_schedule(schedule, total_chapters)
    by_key = {_foreshadow_lookup_key(row): row for row in rows if _foreshadow_lookup_key(row)}
    missing = []
    for stage_index, required_rows in requirements.items():
        for requirement in required_rows:
            row = by_key.get(requirement["key"])
            chapter = row.get(f"{requirement['kind']}_chapter") if row else ""
            normalized = _foreshadow_endpoint_in_stage(
                chapter,
                requirement["kind"],
                requirement,
                specs,
                total_chapters,
            )
            if not normalized:
                missing.append({
                    "stage_index": stage_index,
                    "kind": requirement["kind"],
                    "code": requirement.get("code") or requirement.get("name"),
                    "name": requirement.get("name", ""),
                })
    return missing


def _foreshadow_schedule_shortfalls(
    foreshadows,
    schedule,
    total_chapters=0,
    stage_specs=None,
):
    if isinstance(stage_specs, list):
        return [
            item.get("code") or item.get("name")
            for item in _stage_foreshadow_shortfalls(
                foreshadows,
                schedule,
                stage_specs,
                total_chapters,
            )
        ]
    records = [item for item in foreshadows if isinstance(item, dict)]
    rows = _normalize_foreshadow_schedule(schedule, total_chapters)
    by_code = {
        _as_text(item.get("code")).upper(): item
        for item in rows if _as_text(item.get("code"))
    }
    by_name = {
        _as_text(item.get("name")): item
        for item in rows if _as_text(item.get("name"))
    }
    missing = []
    for record in records:
        match = by_code.get(_as_text(record.get("code")).upper())
        if match is None:
            match = by_name.get(_as_text(record.get("name")))
        if not match:
            missing.append(_as_text(record.get("code")) or _as_text(record.get("name")))
            continue
        setup_number = _creation_chapter_number(match.get("setup_chapter"))
        payoff = _as_text(match.get("payoff_chapter"))
        payoff_number = _creation_chapter_number(payoff)
        if setup_number <= 0 or (payoff != "结尾保留" and payoff_number <= setup_number):
            missing.append(_as_text(record.get("code")) or _as_text(record.get("name")))
    return missing


def _creation_foreshadow_chapter_guidance(total_words, average_chapter_words):
    total_chapters = _creation_total_chapters(total_words, average_chapter_words)
    return f"""
本书按当前输入预计共 {total_chapters} 章。阶段规划只把每个暗线端点关联到当前阶段中的一个事件，程序会根据事件的允许章节范围稳定落下具体章号，章号覆盖第1章到第{total_chapters}章。暗线先进入人物生活，再在后续行动和关系变化中产生新的意义；需要留到结尾的线索由程序保留为“结尾保留”。
""".strip()


class NovelCreationWorker(NovelAnalysisWorker):
    """复用现有结构化请求、流式回退和重试机制的向导批次 worker。"""

    def __init__(
        self,
        base_url,
        api_key,
        model,
        step,
        context,
        proxy_url="",
        proxy_mode="不使用代理",
        batch_kind="",
        stage_index=0,
    ):
        self.creation_step = str(step or "").strip()
        self.creation_batch = str(batch_kind or "").strip()
        try:
            self.stage_index = max(0, int(stage_index or 0))
        except (TypeError, ValueError):
            self.stage_index = 0
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
        # One initial request plus three retries.  Wizard requests are small,
        # independent generation tasks, so every failed attempt follows the
        # same 10s / 20s / 30s schedule instead of using error-specific gaps.
        self.retry_attempts = 4

    def _is_retryable_analysis_error(self, error):
        """Retry every failed API/JSON response for this wizard request.

        The wizard validates the fixed schema after the worker returns. API
        transport, provider compatibility, malformed JSON and output-limit
        failures all deserve the same retry budget here; incomplete results
        are still never emitted as a successful result.
        """
        return True

    def _analysis_retry_wait_seconds(self, error, attempt):
        try:
            attempt = max(1, int(attempt or 1))
        except (TypeError, ValueError):
            attempt = 1
        return attempt * 10

    def _analysis_retry_progress_text(self, error, label, total, wait_seconds, next_attempt, attempts):
        return (
            f"{label}/{total} 本次生成失败，{wait_seconds}秒后自动重试 "
            f"{next_attempt - 1}/3（共3次重试）..."
        )

    def _analysis_prompt(self):
        prompt = STEP_PROMPTS.get(self.creation_step, COMMON_CREATION_RULES)
        author_input = self.creation_context.get("author_input", {})
        total_words = author_input.get("total_words", 500000) if isinstance(author_input, dict) else 500000
        try:
            total_words = max(1, int(total_words or 500000))
        except (TypeError, ValueError):
            total_words = 500000
        average_chapter_words = (
            author_input.get("average_chapter_words", 3000)
            if isinstance(author_input, dict) else 3000
        )
        try:
            average_chapter_words = max(1, int(average_chapter_words or 3000))
        except (TypeError, ValueError):
            average_chapter_words = 3000
        total_chapters = _creation_total_chapters(total_words, average_chapter_words)
        terminal_bounds = _terminal_window_bounds(total_chapters)
        power_levels_guidance = ""
        if story_requires_explicit_power_levels(
            author_input,
            self.creation_context.get("selected_premise", {}),
        ):
            power_levels_guidance = """
当前题材明确属于高武、玄幻、仙侠、修真、武道或其它有力量层次的题材。设定数组 l 里必须有一条独立的实力体系条目，不能只在世界规则的力量体系里一笔带过，也不能只写主角有多强。这条条目仍然使用 l 的原有四个位置：名称、类型、具体内容、人物当前知道多少；名称可以写成“高武境界体系”或贴合本书的实力体系，类型固定写“规则”。
具体内容按从低到高写出一套清楚、够用的境界顺序，每个境界只用一到两句话，说明这一层主要能做到什么、边界在哪里，以及通常靠什么提升。境界数量按故事需要安排，不要把同一层拆成大量重复小级别；主角当前大致处在哪一层、普通武者、武帝和更高层次与主角的差距，也要在这条条目里说清楚。每个境界的描述要成为后面阶段和正文可以反复使用的事实，不要只写“存在境界划分”或“力量来自气血真元”，不要把境界体系留给阶段规划。
如果使用嵌套数组表达境界，也必须把最终完整内容同时写入这条 l 条目的“具体内容”，这样程序会按主程序现有 lore 字段保存。
""".strip()
        if self.creation_batch == "bible_core":
            prompt = f"""{COMMON_CREATION_RULES}

只根据作者已经选定的故事，生成小说圣经和世界规则。小说圣经写整本书的核心矛盾、人物关系底子、贯穿全书并会随着人物选择不断变深的问题、主题、结尾方向和长期事实，让后面的阶段和场景都有清楚的根。主线矛盾字段必须完整承载核心动机契约：主角为什么非行动不可、要完成什么可验收的具体目标、期限或机会窗口是什么、失败会失去什么、阻碍来自谁或什么，以及开局与终局之间的主要反差；不能只写“赚钱、变强、复仇”这类抽象方向。主题字段只提炼这条故事要讨论的人性命题、价值冲突或情感认识，不重复具体任务、金额、期限、资源缺口、对手或执行步骤；不能用主题代替主线矛盾，也不能让主题变成另一条主线。还要写出解决当前目标后会自然打开的下一道具体阻碍或更高代价，保证后续阶段是在推进同一条主线，而不是不断换题。世界规则写世界长期怎样运转、日常生活、地点和社会关系、异常或能力的来源、触发条件、作用边界和代价；普通都市、灵异、悬疑、情感和现实题材，把规则落在空间、社会、异常与人物处境上；明确有修炼或境界的题材，再写力量来源和总边界，详细层次留给下一批的设定记录。

世界规则的五个位置都要形成可执行的事实：世界概况交代长期环境，力量或能力体系交代来源与总边界，长期规则数组写会反复成立的运行方式，代价限制数组写人物触碰这些规则后会承担的现实后果，地理与生活写人物平常真正会走进的地方和生活压力。每条规则都能影响人物选择，数组写实际内容，不用空泛的分类名。

“长期规则数组”和“代价限制数组”都要写出实际条目，通常各有三到六条；不要为了省字留空，也不要把它们只写进世界概况或能力边界。高武、玄幻、仙侠、修真和武道题材要写清修炼、资源、宗门秩序、越级或使用力量会遇到的现实代价；其它题材则写这个世界会反复成立的生活、空间、社会或异常规则。

这是预计写到{_creation_scale_requirements(total_words)[0]}的长篇，资料要足够支撑后续人物、设定、伏笔和阶段规划，让人物在不同阶段拥有新的处境和选择。伏笔位置此时只写阶段参考，不写具体章号。小说简介保持自然网络小说语言；reader_promise 也直接写故事会持续制造的悬念、压力和选择，不对读者说“读者会”“读者将”或“本书将”，不写编辑式说明。其余内容以清楚、稳定、方便后续执行为先。

只返回一个合法 JSON 对象，不能有 Markdown 或解释。为了避免字段名称混进正文，b 和 w 使用短键对象，不使用定长内容数组：
{{"b":{{"c":"小说圣经的核心内容","r":"读者承诺","t":"主题","m":"主线矛盾","p":"人物关系底子","e":"结尾方向","h":"必须守住的边界"}},"w":{{"s":"世界概况","p":"力量或能力体系的来源与总边界","r":["长期规则一","长期规则二"],"c":["代价限制一","代价限制二"],"g":"地理与生活"}}}}
b 只能使用 c、r、t、m、p、e、h；w 只能使用 s、p、r、c、g。键名只是程序标记，不能把“小说圣经的核心内容”“世界概况”等示例文字原样返回；每个值必须直接写这本小说的实际内容。不要输出人物、设定或伏笔。"""
        elif self.creation_batch == "bible_assets":
            prompt = f"""{COMMON_CREATION_RULES}

读取作者已经选定的故事，以及前一批已经生成的小说圣经和世界规则，补齐人物、设定和伏笔。所有人物目标、关键设定和伏笔都必须服务于已经确认的核心动机：它们要帮助主角完成目标、制造阻碍、抬高代价、改变资源/关系/信息/时间窗口，或在阶段转换时打开下一道具体目标；不能各自发展成脱离主线的独立故事。人物要分别写身份、想得到或守住的东西、秘密、人物性格/特点、语言风格，以及害怕失去什么、与主角的长期关系底色和长期变化。人物性格/特点写长期稳定的性格底色，语言风格写可迁移的表达分类和习惯；人物性格、语言风格和 notes 都不要落到具体事件、食物、地点、道具、固定笑点、固定动作、固定口头禅、某一次剧情反应或固定触发模式上。具体怎样牵制、靠近、利用、误会或翻脸，留给后面的阶段和章节在场景中表现。设定库统一收录后面反复会用到的地点、物件、势力、制度、日常场景和能力边界。明确有修炼、境界或力量层次的题材，在设定的规则条目里写详细层次；其它题材把设定落在空间、生活、社会关系和异常边界上。伏笔围绕主线冲突、重要人物关系和关键设定展开，但每条只保留一个核心问题和一个可验收的回收结果：写清当前可见的具体线索、人物当前理解、回收时谁做了什么、读者确认了什么、当场产生什么后果，notes留空，状态统一为未埋。普通伏笔的 remaining_secret 填“无”或只写不影响本部闭环的余波；只有少量真正贯穿全书核心矛盾的长期主线谜团才允许保留核心未解部分。

{CREATION_LORE_TYPE_GUIDANCE}

人物说明不能只写一个身份标签：c.r写正式身份和故事位置，c.q用一两句补清所属关系、与主角的牵制以及和相近人物的区别；人物是某个组织、家族或势力的代表时，人物姓名与组织正式名称分别保留。设定说明不能只写名词：l.d用一两句写清实体类型、正式名称、关联人物或势力、作用范围和与相近实体的区别。伏笔说明用一两句写清它指向的正式人物、势力、设定或关系，以及线索现在出现的内容和后续会改变的判断；每条必须能够单独回答一个问题，不得把身份、幕后势力、历史经过、力量来源和未来世界合并在一条伏笔中；三类说明都直接写故事资料，不写字段解释或编辑总结。

{power_levels_guidance}

{_creation_scale_guidance(total_words)}

这是预计写到{_creation_scale_requirements(total_words)[0]}的长篇，按故事需要补足资料，不要把简介换个说法重复输出，也不要为了凑数量添加无根名词。伏笔数量是执行规模的参考，不是把抽象问题拆成很多条的硬任务；无法写出明确回收场景的内容不要放进 f。伏笔位置此时只写第几阶段，不写具体章号。{_creation_foreshadow_stage_guidance(total_words)}
{_creation_foreshadow_distribution_guidance(total_words)}

只返回一个合法 JSON 对象，不能有 Markdown 或解释。顶层必须同时返回 c、l、f 三个键：c 只能放人物，l 只能放设定，f 只能放伏笔；即使资料很多，也不能把 l 或 f 的记录追加到 c 数组。为了避免字段名称混进内容，c、l、f 都使用短键对象，不使用定长内容数组：
{{"c":[{{"n":"姓名","r":"身份和故事位置","g":"当前目标","s":"秘密","p":"人物性格/特点","v":"语言风格","q":"害怕失去什么、与主角的长期关系底色和长期变化"}}],"l":[{{"n":"名称","t":"类型","d":"具体内容","k":"人物当前知道多少"}}],"f":[{{"i":"编号","n":"名称","a":"埋设阶段","b":"回收阶段","d":"读者能看到的线索及后续变化","r":"揭开后会改变什么","u":"仍未揭开的部分"}}]}}
c 中每项只能使用 n、r、g、s、p、v、q；l 中每项只能使用 n、t、d、k；f 中每项只能使用 i、n、a、b、d、r、u。键名只是程序标记，不能把“姓名”“身份和故事位置”等示例文字原样返回；每个值必须直接写这本小说的实际内容。只输出 c、l、f，不要重复输出 b 或 w。人物、设定和伏笔数量要达到长篇规模要求。{("高武、玄幻、仙侠、修真、武道题材的 l 中必须包含一条按从低到高排列的实力体系条目；它要使用 l 的四个字段写完整境界内容，每个境界一到两句话。" if power_levels_guidance else "")}"""
            prompt += """

补充方向：让人物、设定和伏笔都能在后续场景中落地。伏笔的阶段位置表示它如何进入人物生活、如何在行动和关系变化中逐步显出意义；让线索从当前理解出发，在后续重要事件、人物关系和关键转折中逐步显出新的意义。"""
        elif self.creation_batch == "stage_skeleton":
            stage_specs = _creation_stage_batch_specs(
                total_words,
                average_chapter_words,
            )
            stage_count = len(stage_specs)
            stage_ranges = "；".join(
                f"{item['id']}（第{item['start_chapter']}—{item['end_chapter']}章）"
                for item in stage_specs
            )
            skeleton_shape = ",".join(
                f'["{item["id"]}","阶段名称","这一阶段的主线变化",["关键转折一","关键转折二"],"阶段结束时的人物和局势"]'
                for item in stage_specs
            )
            prompt = f"""{COMMON_CREATION_RULES}

读取作者选定的故事和完整故事底盘，在正式生成十万字阶段规划前，先建立一份简短的全书阶段骨架。它只负责固定每个阶段的主线变化、关键转折和阶段结束状态，不写章节细纲，不写事件数组，不安排具体伏笔章位，也不重复小说圣经、世界规则和人物设定。每个阶段都必须回答同一条核心动机在本阶段推进了什么：主角当前要完成的具体目标是什么、为了目标主动做了什么、遇到的主要阻碍或代价是什么、阶段结束后得到或失去什么，以及这个结果如何打开下一阶段更具体的目标。阶段不是互不相干的事件集合，也不能每阶段重新换一条主线。先从本阶段故事真正会发生的变化出发，再确定阶段转折；转折方式由题材、人物关系、环境和事件自然决定，不要求各阶段使用同一种推进顺序。阶段数量和章节范围完全按照作者输入；每个阶段写一条清楚的主线变化、两到四个关键转折和一条结束状态，内容要能让后面的阶段规划沿着同一条故事发展，避免阶段之间方向漂移，尽量不用固定清单式要求。

本书总字数为{total_words}字，按每十万字划分为{stage_count}个阶段。必须恰好返回{stage_count}项，不能少一项，也不能多出额外阶段；阶段编号和章节范围固定为：{stage_ranges}。即使某一阶段的故事暂时不如其它阶段集中，也必须为该阶段写出属于它的主线变化、关键转折和结束状态，不能把相邻阶段合并，也不能提前结束全书。

第一阶段的开头要有强冲突前三章，并把冲突落到人物、场景、行为、动作、情绪和结果上。第1章直接让主角进入正在发生的具体冲突；第2章承接上一章的后果，让冲突升级并出现改变判断的反转；第3章让主角主动选择或反击，并承担已经发生的直接后果，形成必须继续追读的新局面。这里写宏观走向即可，具体冲突和表现方式结合题材自由发挥；不要先铺完背景，也不要用抽象概括代替人物正在经历的现场。最后一个阶段的结束状态要让本部主线、主角当前目标和主要关系形成看得见的结果；可以留下不影响本部结局的续作余味，但不能把本部核心矛盾和主角必须完成的事情推给下一部。

只返回一个合法 JSON 对象：{{"g":[{skeleton_shape}]}}。g 必须严格按上述编号顺序覆盖全部{stage_count}个阶段，每项固定五个位置；不要返回章节事件、伏笔内容、代码、Markdown 或其它字段。"""
        elif self.creation_batch == "stage_endpoint_repair":
            current_stage = self.creation_context.get("current_stage", {})
            stage_number = (
                current_stage.get("number", self.stage_index + 1)
                if isinstance(current_stage, dict) else self.stage_index + 1
            )
            total_stages = (
                current_stage.get("total_stages", "")
                if isinstance(current_stage, dict) else ""
            )
            missing = self.creation_context.get("missing_foreshadow_endpoints", [])
            missing_codes = [
                _normalize_foreshadow_code(item.get("code"))
                or _as_text(item.get("code") or item.get("name"))
                for item in missing if isinstance(item, dict)
            ]
            missing_text = "、".join(code for code in missing_codes if code) or "指定伏笔"
            prompt = f"""{COMMON_CREATION_RULES}

读取已经完成的第{stage_number}/{total_stages or '?'}阶段规划和第二步确认的伏笔阶段位置，只补齐当前阶段缺失的伏笔正式端点，不重新生成阶段规划，不改写已有事件，不增加新的伏笔。当前需要补齐：{missing_text}。

请根据已有事件的实际内容，为每一项选择一个真正承载这次变化的事件：setup 表示线索在场景中第一次进入人物生活，payoff 表示线索在场景中完成单一核心问题的回答，并产生具体行动、对白、证据、关系结果或局势结果。payoff不能只写推进、部分揭示、冲突升级、再次出现或留下新的问题；如果已有事件只能继续铺垫，就不要把它标成正式 payoff。返回的 e 必须使用已有事件编号，d 写这次在场景中发生的具体变化；只补当前缺失项目，不能把同一伏笔的普通延续重复当成正式端点。

只返回一个合法 JSON 对象：{{"f":[{{"i":"{missing_codes[0] if missing_codes else 'F0001'}","k":"setup或payoff","e":"S{stage_number:02d}-E01","d":"这次在场景中发生的具体变化"}}]}}。i 必须逐字复制上面给出的精确伏笔编号（包括 F 和前导零），不能改成其它格式；只返回当前缺失项目。不要返回阶段规划、章节号、Markdown、解释或其它字段。"""
        elif self.creation_batch == "stage_plan_stage":
            current_stage = self.creation_context.get("current_stage", {})
            stage_number = current_stage.get("number", self.stage_index + 1) if isinstance(current_stage, dict) else self.stage_index + 1
            start_chapter = current_stage.get("start_chapter", "") if isinstance(current_stage, dict) else ""
            end_chapter = current_stage.get("end_chapter", "") if isinstance(current_stage, dict) else ""
            target_stage_words = current_stage.get("target_words", 100000) if isinstance(current_stage, dict) else 100000
            total_stages = current_stage.get("total_stages", "") if isinstance(current_stage, dict) else ""
            first_stage = self.stage_index == 0
            opening_guidance = ""
            try:
                opening_stage = (
                    first_stage
                    and int(start_chapter or 0) <= 3 <= int(end_chapter or 0)
                )
            except (TypeError, ValueError):
                opening_stage = False
            if opening_stage:
                opening_guidance = (
                    "\n\n这是全书第一阶段，前3章是开篇重点。请在事件数组中为第1、2、3章分别留下"
                    "能够落地且前后相扣的现场冲突节点；第一个事件的 allowed_chapters 必须是 [1,1]，第二个事件必须是 [2,2]，第三个事件必须是 [3,3]，不能使用重叠范围，也不能把三章合成一个背景事件。"
                    "每个节点都写清人物、场景、行为、动作、情绪变化和结果。第1章直接进入强冲突，第2章承接后果并升级冲突、产生反转，第3章让主角主动选择或反击并承担直接后果；"
                    "三章前后相扣，具体冲突和表现方式结合题材自由发挥，背景和规则随着现场行动自然出现，不用抽象概括代替人物冲突。"
                )
            genre_text = " ".join(
                str(value or "")
                for value in (
                    author_input.get("genre", "") if isinstance(author_input, dict) else "",
                    self.creation_context.get("selected_premise", {}).get("genre", "")
                    if isinstance(self.creation_context.get("selected_premise", {}), dict)
                    else "",
                )
            )
            subject_guidance = ""
            if story_requires_explicit_power_levels(genre_text):
                subject_guidance = (
                    "本题材是高武或武道宗门故事，阶段推进优先落在宗门经营、上门挑战、战斗试探、资源争夺、修炼比试、"
                    "人物争执和当场选择上；世界规则和制度只有在人物正在争取、对抗或付出代价时进入场景，"
                    "连续事件要主动更换推进方式。"
                )
            final_stage_guidance = ""
            try:
                is_final_stage = int(stage_number) == int(total_stages)
            except (TypeError, ValueError):
                is_final_stage = False
            try:
                stage_start_number = int(start_chapter or 0)
                stage_end_number = int(end_chapter or 0)
            except (TypeError, ValueError):
                stage_start_number, stage_end_number = 0, 0
            terminal_overlap = None
            if terminal_bounds and stage_start_number and stage_end_number:
                overlap_start = max(stage_start_number, terminal_bounds[0])
                overlap_end = min(stage_end_number, terminal_bounds[1])
                if overlap_start <= overlap_end:
                    terminal_overlap = (overlap_start, overlap_end)
            if terminal_overlap:
                final_stage_guidance = (
                    f"\n\n当前阶段范围为第{stage_start_number}-{stage_end_number}章，"
                    f"其中第{terminal_overlap[0]}-{terminal_overlap[1]}章属于按全书总章节数计算的最后5章收尾窗口（全书共{total_chapters}章）。"
                    "收尾窗口只是内容规划约束，不改变当前阶段的起止章节、全书阶段数量、后续章节规划批次或任何章节数量；"
                    "不得为了收尾另增章节、另起过渡章或把当前阶段范围改写成其它章数。"
                    "窗口内沿着已经发生的核心冲突、人物选择和关系变化完成实际结果，不再开启新的主要任务、主要敌人、组织、力量体系、世界规则或下一卷主线，"
                    "也不要把新的未解释信息、未知对手、未知目的地或未来承诺写成等待后续章节回答的悬念。"
                    "每个窗口章节都要有已经发生的行动和结果；最后一章落到具体动作、对白、关系结果或已经成立的生活状态。"
                )
            elif is_final_stage:
                final_stage_guidance = (
                    "\n\n这是全书最后一个十万字阶段。阶段后部必须沿着已经发生的冲突、人物选择和关系变化完成收束："
                    "把核心矛盾推到最终选择并写出实际结果，让主要人物的关系、读者承诺、普通伏笔和主角最终处境有清楚落点。"
                    "续作只能保留不影响当前结局的背景余波，不把本部必须解决的事情留给下一部。"
                    "最后几章不要再开需要后续章节解决的主线、重大反转、重要人物、新的世界规则或等待回答的悬念；要把结局写成具体场景中的行动、结果和已经成立的生活状态，"
                    "不要用突然跳过多年的概括、作者总结或一句抽象结论代替过程。倒数第二章可以把冲突推到临界点，最后一章再完成最后选择、结果和余味。"
                )
            stage_progression_guidance = (
                "本阶段后部只沿着已经发生的冲突、人物选择和关系变化完成窗口内的直接结果；"
                "收尾窗口内不再打开下一道需要后续章节回答的主线目标、主要敌人、未知信息或悬念，"
                "最后一章在固定章节位置内形成核心矛盾、主要关系和主角最终处境的实际结果。"
                if terminal_overlap else
                "本阶段解决或暂时解决当前目标后，要在 x/y 或事件结果中留下下一阶段可执行的具体目标、缺口或更高代价，不能只写‘局势继续发展’。"
            )
            prompt = f"""{COMMON_CREATION_RULES}

读取作者选定的故事、完整故事底盘、全书阶段骨架和已经完成的前面阶段，只生成当前第{stage_number}/{total_stages or '?'}阶段，范围为第{start_chapter}章到第{end_chapter}章。全书阶段骨架只负责提供本阶段的方向和结束状态，不要把骨架中的摘要和转折原样重复成另一份总规划；当前阶段的具体内容以本次事件和人物处境为准。前面阶段的结束状态、带入内容和仍在推动人物的问题是连续性依据。当前阶段必须沿着核心动机继续：先明确主角本阶段要完成的具体目标，再让事件围绕主角的行动、阻碍、选择、代价和结果展开；{stage_progression_guidance}阶段规划使用结构化表达，写清人物真正正在经历的事情、事件顺序、直接结果和状态变化；字段服务于故事事实，尽量不用固定清单式要求，不把每个事件套成同一张检查表。

输入资料中的 current_foreshadow_endpoints 是本阶段自然发生的正式暗线端点清单。每一项落到一个当前事件中；kind=setup 写线索怎样第一次进入人物生活，kind=payoff 写线索怎样在现场完成一个明确问题的回答，并产生可观察的直接结果。payoff不能只写推进、部分揭示、再次出现、冲突升级、确认“事情不简单”或留下新的问题；如果当前事件只能继续铺垫，就不能把它当成正式 payoff。清单为空时，场景仍然沿着人物和主线自然推进。同一条伏笔在其它事件里继续出现、深化或产生后果是正常的，但正式端点只在真正承担该变化的事件中标记一次；后续事件用普通关联资料或“F编号”继续承接，不重复写“F编号/setup”或“F编号/payoff”。承载正式端点的事件 references 加入对应标记，让程序可以把端点和事件稳定对应起来。

阶段内的事件以场景为核心：在需要的地方写清本次真正发生的事实，尽量不用固定清单式要求，不为凑齐项目逐项重复。每个事件的 allowed_chapters 是这个事件可以使用的章节容量：一章范围写一个主要场面和直接结果，跨数章的范围写同一条连续冲突在这些章节里的升级、选择和后果。事件正文必须与自己的章节容量相称，不要把多个独立地点、多个独立对手、多个完整高潮或下一阶段内容塞进一个短范围；事件里有多个动作时，要把它们组织成同一条连续事情，不能靠扩大 allowed_chapters 之外的范围来容纳。相邻事件从人物目标和现场结果自然长出新的推进方式，让人物行动、关系变化、空间压力、利益变化、能力试探、秘密暴露或突发后果带来变化，不套固定轮换。伏笔只在实际发生的阶段返回，一次只返回一个当前正式端点；f中的每项写 i、k、e、d，其中 k 为 setup 或 payoff，e 是承载它的事件编号，d 是这一次在场景中发生的具体变化。后续事件可以继续写同一条线索的新增影响，但不重复返回同一种正式端点。程序会依据事件范围落下具体章号。{("同时返回全书长期事实 k。" if first_stage else "本阶段沿用前面已经确认的长期事实。")}

            {opening_guidance}{subject_guidance}{final_stage_guidance}

{STAGE_PLAN_OBJECT_OUTPUT_RULES}
"""
        if self.creation_step == "stage_plan":
            prompt = _compact_stage_plan_prompt(prompt)
        retry_feedback = _as_text(
            self.creation_context.get("generation_retry_feedback")
        ).strip()
        if retry_feedback:
            prompt += (
                "\n\n上一轮返回已经到达程序，但未通过结构或资料完整性校验。"
                "本次只根据下面的错误反馈修正缺口，仍然返回完整的当前批次 JSON；"
                "不要解释错误，也不要只返回缺失项：\n"
                + retry_feedback[:2000]
            )
        project_entity_guidance = _creation_entity_naming_guidance(self.creation_context)
        if project_entity_guidance:
            prompt += "\n\n" + project_entity_guidance
        prompt += (
            "\n\n最终只返回紧凑合法 JSON：不使用 Markdown、缩进、空行或多余空格；"
            "可省略空字符串、空数组和没有内容的可选字段，但不得删减任何有意义的事实或资料数量。"
        )
        return prompt

    def _analysis_progress_label(self):
        if self.creation_batch == "stage_skeleton":
            return "全书阶段骨架"
        if self.creation_batch == "stage_endpoint_repair":
            return f"第{self.stage_index + 1}阶段伏笔定位"
        if self.creation_batch == "stage_plan_stage":
            return f"第{self.stage_index + 1}阶段"
        if self.creation_batch == "bible_core":
            return "小说圣经、世界规则"
        if self.creation_batch == "bible_assets":
            return "人物、设定、伏笔"
        if self.creation_step == "premise":
            return "5个故事方向"
        return "当前步骤"

    def _max_tokens_for_request(self):
        if self.creation_batch == "stage_skeleton":
            return 8000
        if self.creation_batch == "stage_endpoint_repair":
            return 6000
        if self.creation_batch == "bible_core":
            return 16000
        if self.creation_batch == "bible_assets":
            return 22000
        if self.creation_batch == "stage_plan_stage":
            return 16000
        return {
            "premise": 12000,
            "bible": 50000,
            "story_assets": 12000,
            "stage_plan": 36000,
        }.get(self.creation_step, 8000)

    def _analysis_retry_progress_text(self, error, label, total, wait_seconds, next_attempt, attempts):
        if self._is_stream_read_failure(error):
            return f"第 {label}/{total} 块流式响应中途断开，{wait_seconds} 秒后自动重试 {next_attempt}/{attempts}..."
        return super()._analysis_retry_progress_text(
            error, label, total, wait_seconds, next_attempt, attempts
        )

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        return format_creation_context(self.creation_context)

    def _allow_retry_chunk_split(self):
        return False

    def _generation_progress_text(self, total_words):
        if self.creation_step == "premise":
            return "正在生成：5个故事方向"
        if self.creation_batch == "stage_skeleton":
            return "正在生成：全书阶段骨架"
        if self.creation_batch == "stage_endpoint_repair":
            return f"正在补齐：第{self.stage_index + 1}阶段伏笔定位"
        if self.creation_batch == "bible_core":
            return "正在生成：小说圣经、世界规则"
        if self.creation_batch == "bible_assets":
            return "正在生成：人物、设定、伏笔"
        if self.creation_batch == "stage_plan_stage":
            total_stages = _expected_stage_count(total_words)
            return f"正在生成：第{self.stage_index + 1}阶段（共{total_stages}个阶段）"
        return f"正在生成：{dict(CREATION_WIZARD_STEPS).get(self.creation_step, self.creation_step)}"

    def run(self):
        started = self._start_analysis_diagnostics()
        try:
            if not self.base_url:
                raise Exception("请先选择厂商。")
            if not self.api_key:
                raise Exception("请先设置 API Key。")
            if not self.model:
                raise Exception("请选择模型。")
            if self.creation_step not in dict(CREATION_WIZARD_STEPS):
                raise Exception("未知的新建向导步骤。")
            author_input = self.creation_context.get("author_input", {})
            try:
                total_words = max(
                    1,
                    int(
                        author_input.get("total_words", 500000)
                        if isinstance(author_input, dict)
                        else 500000
                    ),
                )
            except (TypeError, ValueError):
                total_words = 500000
            self.progress.emit(self._generation_progress_text(total_words))
            parsed, _response_format = self._analyze_chunk_with_retries(
                self._analysis_prompt(),
                self._chunk_user_text(self.text, 1, 1),
                1,
                1,
                True,
            )
            if self._stop_requested or self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("stopped", started)
                return
            normalized = normalize_creation_result(
                self.creation_step,
                parsed,
                allow_power_levels=story_requires_explicit_power_levels(
                    self.creation_context.get("author_input", {}),
                    self.creation_context.get("selected_premise", {}),
                ),
                pad_stage_plan=self.creation_batch not in {
                    "stage_plan_stage",
                    "stage_endpoint_repair",
                },
                total_words=(
                    author_input.get("total_words", 500000)
                    if isinstance(author_input, dict) else 500000
                ),
                average_chapter_words=(
                    author_input.get("average_chapter_words", 3000)
                    if isinstance(author_input, dict) else 3000
                ),
            )
            if self.creation_step == "premise":
                _bind_requested_title(
                    normalized,
                    (
                        _as_text(author_input.get("requested_title"))
                        if isinstance(author_input, dict) else ""
                    )
                    or _creation_requested_title(
                        author_input.get("inspiration", "")
                        if isinstance(author_input, dict) else "",
                        author_input.get("temporary_title", "")
                        if isinstance(author_input, dict) else "",
                    ),
                )
            self._finalize_analysis_diagnostics("success", started)
            self.result_ready.emit(normalized)
        except Exception as exc:
            if not self._stop_requested and not self.isInterruptionRequested():
                self._finalize_analysis_diagnostics("error", started, exc)
                self.failed.emit(str(exc))
            else:
                self._finalize_analysis_diagnostics("stopped", started)
        finally:
            self._close_active_network_handles()


class CreationChoicePickerDialog(QDialog):
    """弹出式偏好选择器，避免把大量分类长期铺在向导首屏。"""

    style_removed = Signal(str)

    def __init__(
        self, title, groups, current_value="", max_selections=1, parent=None,
        removable_options=None,
    ):
        super().__init__(parent)
        self.setWindowTitle(f"选择{title}")
        _fit_dialog_to_screen(
            self,
            width_ratio=0.56,
            height_ratio=0.66,
            minimum_width=460,
            minimum_height=330,
            maximum_width=900,
            maximum_height=720,
        )
        self.max_selections = max(1, int(max_selections or 1))
        self.selected_value = ""
        self.selected_values = []
        self._selection_label = None
        self._removable_options = dict(removable_options or {})
        self._empty_label = None
        self._is_style_picker = removable_options is not None
        self._build_ui(groups if isinstance(groups, dict) else {}, current_value)

    def _build_ui(self, groups, current_value):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)
        if self.max_selections > 1:
            hint_text = (
                f"可选择 1—{self.max_selections} 项；选满 {self.max_selections} 项后自动确认，"
                "只选一项时请点击“确认”。分类较多时可以在窗口内滚动查看。"
            )
        else:
            hint_text = "选择一项即可返回向导；分类较多时可以在窗口内滚动查看。"
        hint = QLabel(hint_text)
        hint.setStyleSheet("color: #9da3ad;")
        hint.setWordWrap(True)
        root.addWidget(hint)

        current_values = (
            [str(current_value)] if self.max_selections == 1 and current_value
            else self._split_values(current_value)
        )
        self.selected_values = current_values[: self.max_selections]
        if self.max_selections > 1:
            self._selection_label = QLabel()
            self._selection_label.setStyleSheet("color: #86b6df;")
            root.addWidget(self._selection_label)
            self._refresh_selection_label()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(2, 2, 8, 2)
        layout.setSpacing(12)
        seen_options = set()
        column_count = 2 if self._is_style_picker else 3
        for group_title, options in groups.items():
            title = QLabel(str(group_title))
            title.setStyleSheet("font-size: 13px; font-weight: 600; color: #e3e6eb;")
            layout.addWidget(title)
            grid = QGridLayout()
            grid.setContentsMargins(0, 0, 0, 0)
            grid.setHorizontalSpacing(7)
            grid.setVerticalSpacing(7)
            display_index = 0
            row_widgets = {}
            for option in options if isinstance(options, (list, tuple)) else ():
                option = str(option)
                if option in seen_options:
                    continue
                seen_options.add(option)
                button = QPushButton(option)
                button.setCheckable(True)
                line_count = max(1, option.count("\n") + 1)
                button.setMinimumHeight(max(40, 14 + line_count * 20))
                button.setCursor(Qt.PointingHandCursor)
                button.setToolTip(option.replace("\n", " "))
                button.setStyleSheet(
                    """
                    QPushButton {
                        color: #d9dde4;
                        background: #22252b;
                        border: 1px solid #3a3f49;
                        border-radius: 5px;
                        padding: 7px 10px;
                        text-align: left;
                    }
                    QPushButton:hover {
                        background: #2b3038;
                        border-color: #687488;
                    }
                    QPushButton:checked {
                        color: #ffffff;
                        background: #315d86;
                        border-color: #6da4d8;
                    }
                    """
                )
                if option in self.selected_values:
                    button.setChecked(True)
                if self.max_selections > 1:
                    button.clicked.connect(
                        lambda checked=False, value=option, choice_button=button: self._toggle(
                            value, checked, choice_button
                        )
                    )
                else:
                    button.clicked.connect(
                        lambda _checked=False, value=option: self._select(value)
                    )
                option_widget = button
                style_id = self._removable_options.get(option)
                if style_id:
                    option_widget = QFrame()
                    option_widget.setObjectName("character_style_option")
                    option_widget.setStyleSheet(
                        "QFrame#character_style_option {"
                        "background: #22252b; border: 1px solid #3a3f49; border-radius: 5px;"
                        "}"
                    )
                    option_widget.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
                    option_layout = QHBoxLayout(option_widget)
                    option_layout.setContentsMargins(4, 4, 4, 4)
                    option_layout.setSpacing(3)
                    button.setStyleSheet(
                        "QPushButton { color: #d9dde4; background: transparent; border: 0;"
                        "padding: 3px 5px; text-align: left; }"
                        "QPushButton:hover { color: #ffffff; background: #2b3038; }"
                        "QPushButton:checked { color: #ffffff; background: #315d86; }"
                    )
                    button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                    option_layout.addWidget(button)
                    remove_button = QToolButton()
                    remove_button.setObjectName(f"remove_character_style_{style_id}")
                    remove_button.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
                    remove_button.setFixedSize(28, 28)
                    remove_button.setAutoRaise(True)
                    remove_button.setStyleSheet(
                        "QToolButton { background: transparent; border: none; padding: 0; }"
                        "QToolButton:hover { background: #2b3038; border: none; border-radius: 4px; }"
                        "QToolButton:pressed { background: #315d86; border: none; border-radius: 4px; }"
                    )
                    remove_button.setCursor(Qt.PointingHandCursor)
                    remove_button.setToolTip("取消收藏")
                    remove_button.setAccessibleName("取消收藏")
                    remove_button.clicked.connect(
                        lambda _checked=False, value=option, sid=style_id, widget=option_widget:
                        self._remove_style(value, sid, widget)
                    )
                    option_layout.addWidget(remove_button, 0, Qt.AlignVCenter)
                row, column = divmod(display_index, 3)
                if self._is_style_picker:
                    row, column = divmod(display_index, column_count)
                row_widgets.setdefault(row, []).append(option_widget)
                grid.addWidget(option_widget, row, column)
                display_index += 1
            if self._is_style_picker:
                for widgets in row_widgets.values():
                    row_height = max(widget.sizeHint().height() for widget in widgets)
                    for widget in widgets:
                        widget.setFixedHeight(row_height)
            for column in range(column_count):
                grid.setColumnStretch(column, 1)
            layout.addLayout(grid)
        if self._is_style_picker:
            self._empty_label = QLabel("暂无收藏")
            self._empty_label.setVisible(not self._removable_options)
            layout.addWidget(self._empty_label)
        layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll, 1)

        button_flags = QDialogButtonBox.Cancel
        if self.max_selections > 1:
            button_flags |= QDialogButtonBox.Ok
        buttons = QDialogButtonBox(button_flags)
        if self.max_selections > 1:
            buttons.button(QDialogButtonBox.Ok).setText("确认")
            buttons.accepted.connect(self._accept_multiple)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    @staticmethod
    def _split_values(value):
        values = []
        for item in re.split(r"[、,，]", str(value or "")):
            item = item.strip()
            if item and item not in values:
                values.append(item)
        return values

    def _refresh_selection_label(self):
        if self._selection_label is not None:
            selected = "、".join(self.selected_values) or "未选择"
            self._selection_label.setText(
                f"已选 {len(self.selected_values)}/{self.max_selections}：{selected}"
            )

    def _toggle(self, value, checked, button):
        value = str(value or "").strip()
        if not value:
            return
        if checked:
            if value in self.selected_values:
                return
            if len(self.selected_values) >= self.max_selections:
                button.setChecked(False)
                return
            self.selected_values.append(value)
        else:
            self.selected_values = [item for item in self.selected_values if item != value]
        self._refresh_selection_label()
        if len(self.selected_values) >= self.max_selections:
            self.selected_value = "、".join(self.selected_values[: self.max_selections])
            self.accept()

    def _accept_multiple(self):
        self.selected_value = "、".join(self.selected_values)
        self.accept()

    def _select(self, value):
        self.selected_value = str(value or "").strip()
        self.selected_values = [self.selected_value] if self.selected_value else []
        if self.selected_value:
            self.accept()

    def _remove_style(self, option, style_id, widget):
        answer = QMessageBox.question(
            self,
            "取消收藏",
            "确定取消收藏这个人物风格吗？\n不会修改已生成的故事或人物卡内容。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            removed = remove_character_style(style_id)
        except Exception:
            QMessageBox.warning(self, "取消收藏失败", "收藏未能删除，请稍后重试。")
            return
        if not removed:
            QMessageBox.warning(self, "取消收藏失败", "该人物风格未能从收藏列表中移除，请稍后重试。")
            return
        self._removable_options.pop(option, None)
        self.selected_values = [value for value in self.selected_values if value != option]
        if self.selected_value == option:
            self.selected_value = ""
        self._refresh_selection_label()
        widget.hide()
        widget.deleteLater()
        if self._empty_label is not None:
            self._empty_label.setVisible(not self._removable_options)
        self.style_removed.emit(style_id)


class CreationSectionedPreview(QWidget):
    """第三步的五类资料预览，按主程序栏目分开显示。"""

    _SECTION_SPECS = (
        "bible",
        "world_rules",
        "characters",
        "lore",
        "foreshadows",
    )

    def __init__(self, parent=None):
        super().__init__(parent)
        self.title_labels = {}
        self.editors = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(2, 2, 8, 8)
        content_layout.setSpacing(10)

        for key in self._SECTION_SPECS:
            title = _format_bible_sections({})[key][0]
            section = QFrame()
            section.setObjectName("creation_preview_section")
            section.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            section.setStyleSheet(
                """
                QFrame#creation_preview_section {
                    background: #171a1f;
                    border: 1px solid #363c47;
                    border-radius: 5px;
                }
                QLabel#creation_preview_section_title {
                    color: #f0f2f5;
                    font-size: 14px;
                    font-weight: 600;
                }
                QPlainTextEdit#creation_preview_section_editor {
                    color: #d9dde4;
                    background: #111317;
                    border: 0;
                    border-top: 1px solid #2b3039;
                    padding: 8px;
                }
                """
            )
            section_layout = QVBoxLayout(section)
            section_layout.setContentsMargins(12, 10, 12, 10)
            section_layout.setSpacing(8)

            title_label = QLabel(title)
            title_label.setObjectName("creation_preview_section_title")
            section_layout.addWidget(title_label)

            editor = QPlainTextEdit()
            editor.setObjectName("creation_preview_section_editor")
            editor.setReadOnly(True)
            editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            editor.setMinimumHeight(96)
            editor.setPlaceholderText("生成后会在这里显示。")
            section_layout.addWidget(editor)

            self.title_labels[key] = title_label
            self.editors[key] = editor
            content_layout.addWidget(section)

        content_layout.addStretch(1)
        scroll.setWidget(content)
        root.addWidget(scroll)
        self.clear()

    def _update_editor_heights(self):
        available_height = max(0, int(self.height()))
        if available_height <= 0:
            return
        base_height = max(112, min(320, int(available_height * 0.30)))
        compact_height = max(96, int(base_height * 0.86))
        for key in ("bible", "world_rules"):
            editor = self.editors.get(key)
            if editor is not None:
                editor.setMinimumHeight(compact_height)
        for key in ("characters", "lore", "foreshadows"):
            editor = self.editors.get(key)
            if editor is not None:
                editor.setMinimumHeight(base_height)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_editor_heights()

    def set_result(self, result):
        sections = _format_bible_sections(result)
        result = result if isinstance(result, dict) else {}
        for key in self._SECTION_SPECS:
            title, body = sections[key]
            value = result.get(key)
            if key in {"characters", "lore", "foreshadows"}:
                count = len(value) if isinstance(value, list) else 0
                title = f"{title}（{count}）"
            self.title_labels[key].setText(title)
            self.editors[key].setPlainText(body)

    def clear(self):
        empty = {
            key: []
            for key in self._SECTION_SPECS
            if key in {"characters", "lore", "foreshadows"}
        }
        empty.update({"bible": {}, "world_rules": {}})
        self.set_result(empty)


class NovelCreationWizardDialog(QDialog):
    """新建小说项目的三步确认向导。"""

    draft_saved = Signal(str)

    def __init__(self, ai_selection, project_name_hint="", parent=None, draft_id=""):
        super().__init__(parent)
        # macOS keeps the minimize control disabled for a child QDialog even
        # when WindowMinimizeButtonHint is present. Treat the wizard as an
        # independent top-level window so it can be minimized while its worker
        # continues running; the QDialog API is still used for accept/reject.
        window_flags = self.windowFlags()
        window_flags &= ~Qt.Dialog
        window_flags |= (
            Qt.Window
            | Qt.WindowTitleHint
            | Qt.WindowSystemMenuHint
            | Qt.WindowMinimizeButtonHint
            | Qt.WindowCloseButtonHint
        )
        self.setWindowFlags(window_flags)
        self.setWindowTitle("新建小说：AI 创作框架向导")
        _fit_dialog_to_screen(
            self,
            width_ratio=0.88,
            height_ratio=0.86,
            minimum_width=720,
            minimum_height=520,
            maximum_width=1600,
            maximum_height=1080,
        )
        self.ai_selection = ai_selection if callable(ai_selection) else (lambda: (None, "", "请选择模型。"))
        self.project_name_hint = _as_text(project_name_hint)
        self.draft_id = _as_text(draft_id) or _new_creation_wizard_draft_id()
        self.created_at = ""
        self.created_at_ns = 0
        self.completion_status = ""
        self.completed_at = ""
        self.imported_project_path = ""
        self.completed_result_payload = {}
        self.worker = None
        self._active_batch_kind = ""
        self._active_stage_index = -1
        self._pending_batch_kind = ""
        self._pending_stage_index = -1
        self._pending_retry_delay_ms = 0
        self._retrying_same_request = False
        self._generation_retry_count = 0
        self._generation_failed = False
        self.current_step_index = 0
        self.step_results = {}
        self.premise_candidates = []
        self.premise_selected_index = 0
        self._premise_loading_index = -1
        self.choice_values = {}
        self.choice_display_values = {}
        self.choice_summary_buttons = {}
        self.choice_arrow_buttons = {}
        self.choice_widgets = []
        self.json_editors = {}
        self.json_generate_buttons = {}
        self.json_clear_buttons = {}
        self._status_text = "先输入一点灵感，再点选你喜欢的故事方向。"
        self._received_chars = 0
        self._status_step_index = -1
        self._last_worker_error = ""
        self._draft_restoring = True
        self.target_words_spin = QSpinBox()
        self.target_words_spin.setRange(10000, 3000000)
        self.target_words_spin.setValue(500000)
        self.average_words_spin = QSpinBox()
        self.average_words_spin.setRange(1000, 20000)
        self.average_words_spin.setValue(3000)
        self._build_ui()
        self._connect_draft_signals()
        self._draft_restoring = False
        self._load_draft()

    def _refit_to_screen(self):
        if not self.isVisible():
            return
        _fit_dialog_to_screen(
            self,
            width_ratio=0.88,
            height_ratio=0.82,
            minimum_width=720,
            minimum_height=520,
            maximum_width=1600,
            maximum_height=1080,
        )

    def showEvent(self, event):
        super().showEvent(event)
        # The first layout pass can increase the dialog height after the
        # constructor has positioned it. Refit after Qt has created the native
        # window frame, then check once more after macOS finishes its layout.
        QTimer.singleShot(0, self._refit_to_screen)
        QTimer.singleShot(120, self._refit_to_screen)

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(14, 14, 14, 14)
        root.setSpacing(8)
        header = QHBoxLayout()
        self.step_label = QLabel()
        self.step_label.setStyleSheet("font-size: 16px; font-weight: bold;")
        header.addWidget(self.step_label, 1)
        self.status_label = QLabel(self._status_text)
        self.status_label.setObjectName("novel_status_current")
        self.status_label.setWordWrap(True)
        self.status_label.setMinimumHeight(32)
        self.status_label.setMaximumHeight(52)
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
        self._update_responsive_controls()
        self._refresh_step_ui()

    def _connect_draft_signals(self):
        self.inspiration_edit.textChanged.connect(self._save_draft)
        self.target_words_spin.valueChanged.connect(self._on_generation_scope_changed)
        self.average_words_spin.valueChanged.connect(self._on_generation_scope_changed)

    def _draft_payload(self):
        return {
            "schema_version": 3,
            "draft_id": self.draft_id,
            "created_at": self.created_at or now_str(),
            "created_at_ns": self.created_at_ns or time.time_ns(),
            "project_name_hint": self.project_name_hint,
            "current_step_index": self.current_step_index,
            "choice_values": deepcopy(self.choice_values),
            "inspiration": self.inspiration_edit.text(),
            "target_words": self.target_words_spin.value(),
            "average_words": self.average_words_spin.value(),
            "premise_candidates": deepcopy(self.premise_candidates),
            "premise_selected_index": self.premise_selected_index,
            "step_results": deepcopy(self.step_results),
            "completion_status": self.completion_status,
            "completed_at": self.completed_at,
            "imported_project_path": self.imported_project_path,
            "completed_result_payload": deepcopy(self.completed_result_payload),
            "updated_at": now_str(),
        }

    def _save_draft(self, *_args):
        if getattr(self, "_draft_restoring", False):
            return
        try:
            payload = self._draft_payload()
            payload["updated_at"] = now_str()
            save_creation_wizard_draft(payload)
            self.draft_saved.emit(self.draft_id)
        except Exception as exc:
            # 草稿保存失败不能打断向导；正式生成结果仍保留在当前窗口中。
            print("保存新建向导草稿失败：", exc)

    def _invalidate_steps_from(self, step):
        """前置资料变化后，清掉依赖它的结果，避免不同故事版本混用。"""
        step_names = [name for name, _title in CREATION_WIZARD_STEPS]
        try:
            start_index = step_names.index(step)
        except ValueError:
            return
        if step == "stage_plan":
            bible_result = self.step_results.get("bible")
            if isinstance(bible_result, dict):
                bible_result["foreshadows"] = _restore_foreshadow_stage_baseline(
                    bible_result.get("foreshadows", [])
                )
                self.step_results["bible"] = bible_result
                self._set_preview_result("bible", bible_result)
        for name in step_names[start_index:]:
            self.step_results.pop(name, None)
            editor = self.json_editors.get(name)
            if editor is not None:
                editor.clear()

    def _clear_step_content(self, step):
        """Clear one wizard step and the results that depend on it."""
        if self.worker is not None:
            return
        step_titles = dict(CREATION_WIZARD_STEPS)
        if step not in step_titles:
            return

        has_content = bool(self.step_results.get(step))
        if step == "premise":
            has_content = has_content or bool(self.premise_candidates)
        if not has_content:
            self._refresh_step_ui()
            return

        answer = QMessageBox.question(
            self,
            "清空本步内容",
            f"确定清空“{step_titles[step]}”吗？\n"
            "这一步及后面依赖它的内容都会被清除，第一步的灵感和选择会保留。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return

        if step == "premise":
            self._invalidate_steps_from("premise")
            self.premise_candidates = []
            self.premise_selected_index = 0
            self._show_empty_candidate_list()
            self.premise_result_frame.setVisible(False)
        else:
            self._invalidate_steps_from(step)

        self._save_draft()
        self._refresh_step_ui()

    def _on_generation_scope_changed(self, *_args):
        if not getattr(self, "_draft_restoring", False) and self.premise_candidates:
            self._invalidate_steps_from("bible")
        self._save_draft()

    def _load_draft(self):
        draft = load_creation_wizard_draft(self.draft_id)
        if not isinstance(draft, dict):
            draft = {}
        self.created_at = _as_text(draft.get("created_at")) or now_str()
        try:
            self.created_at_ns = int(draft.get("created_at_ns", 0) or 0)
        except (TypeError, ValueError):
            self.created_at_ns = 0
        self.project_name_hint = _as_text(
            draft.get("project_name_hint")
        ) or self.project_name_hint
        self.completion_status = _as_text(draft.get("completion_status"))
        self.completed_at = _as_text(draft.get("completed_at"))
        self.imported_project_path = _as_text(draft.get("imported_project_path"))
        saved_completed_payload = draft.get("completed_result_payload", {})
        self.completed_result_payload = (
            deepcopy(saved_completed_payload)
            if isinstance(saved_completed_payload, dict) else {}
        )
        self._draft_restoring = True
        try:
            saved_choices = draft.get("choice_values", {})
            if not isinstance(saved_choices, dict):
                saved_choices = {}
            for key in CREATION_CHOICE_DEFAULTS:
                value = _as_text(saved_choices.get(key))
                if value:
                    self._set_choice(key, value)

            if "inspiration" in draft:
                self.inspiration_edit.setText(_as_text(draft.get("inspiration")))

            try:
                self.target_words_spin.setValue(
                    max(self.target_words_spin.minimum(), min(
                        self.target_words_spin.maximum(),
                        int(draft.get("target_words", self.target_words_spin.value()) or self.target_words_spin.value()),
                    ))
                )
            except (TypeError, ValueError):
                pass
            try:
                self.average_words_spin.setValue(
                    max(self.average_words_spin.minimum(), min(
                        self.average_words_spin.maximum(),
                        int(draft.get("average_words", self.average_words_spin.value()) or self.average_words_spin.value()),
                    ))
                )
            except (TypeError, ValueError):
                pass
            # 旧版草稿没有单独保存“单章字数”按钮；用已保存的数值补回显示，
            # 这样旧草稿的阶段边界不会因为界面升级而悄悄改变。
            saved_chapter_words = _as_text(saved_choices.get("chapter_words"))
            if not saved_chapter_words:
                self._set_choice("chapter_words", f"{self.average_words_spin.value()}字")
            else:
                try:
                    saved_value = int(saved_chapter_words.replace("字", "").replace(",", "").strip())
                except (TypeError, ValueError):
                    saved_value = 0
                if saved_value != self.average_words_spin.value():
                    self._set_choice("chapter_words", f"{self.average_words_spin.value()}字")

            candidates = draft.get("premise_candidates", [])
            self.premise_candidates = [
                deepcopy(item) for item in candidates if isinstance(item, dict)
            ] if isinstance(candidates, list) else []
            try:
                self.premise_selected_index = max(
                    0,
                    min(
                        int(draft.get("premise_selected_index", 0) or 0),
                        max(0, len(self.premise_candidates) - 1),
                    ),
                )
            except (TypeError, ValueError):
                self.premise_selected_index = 0

            saved_results = draft.get("step_results", {})
            self.step_results = {}
            legacy_assets = {}
            allowed_steps = {name for name, _title in CREATION_WIZARD_STEPS}
            if isinstance(saved_results, dict):
                for step, result in saved_results.items():
                    if step == "story_assets":
                        legacy_assets = normalize_creation_result(
                            "story_assets",
                            result,
                            allow_power_levels=self._allow_power_levels(),
                        )
                        continue
                    if step not in allowed_steps:
                        continue
                    normalized = self._normalize_step_result(step, result)
                    if step == "bible" and isinstance(normalized, dict):
                        # A previous version projected third-step chapter
                        # placement into the second-step baseline.  Restore
                        # the intended stage-only representation when opening
                        # such a draft.
                        normalized["foreshadows"] = _restore_foreshadow_stage_baseline(
                            normalized.get("foreshadows", [])
                        )
                    self.step_results[step] = normalized
            if legacy_assets:
                bible_result = self.step_results.get("bible", {})
                if not isinstance(bible_result, dict):
                    bible_result = {}
                for key in ("characters", "lore", "foreshadows"):
                    if not bible_result.get(key) and legacy_assets.get(key):
                        bible_result[key] = deepcopy(legacy_assets[key])
                self.step_results["bible"] = self._normalize_step_result("bible", bible_result)
                self.step_results["bible"]["foreshadows"] = _restore_foreshadow_stage_baseline(
                    self.step_results["bible"].get("foreshadows", [])
                )
            if self.premise_candidates:
                self._populate_candidate_list()
            else:
                self._show_empty_candidate_list()

            premise_result = self.step_results.get("premise")
            if not premise_result and self.premise_candidates:
                self.step_results["premise"] = {
                    "candidates": deepcopy(self.premise_candidates),
                    "selected_index": self.premise_selected_index,
                }
            elif isinstance(premise_result, dict):
                premise_result["candidates"] = deepcopy(self.premise_candidates)
                premise_result["selected_index"] = self.premise_selected_index

            selected_premise = self._current_premise()
            if selected_premise:
                self.step_results.setdefault("premise", {})
                self.step_results["premise"]["selected"] = deepcopy(selected_premise)

            for step, _title in CREATION_WIZARD_STEPS[1:]:
                result = self.step_results.get(step)
                if result:
                    if step == "stage_plan":
                        # A previous run may have advanced the counter after a
                        # valid JSON shell was returned. Recalculate progress
                        # from the actual stage events while restoring.
                        self._sync_stage_generation_state(result)
                    self._set_preview_result(step, result)

            try:
                saved_step_index = max(
                    0,
                    min(
                        int(draft.get("current_step_index", 0) or 0),
                        len(CREATION_WIZARD_STEPS) - 1,
                    ),
                )
            except (TypeError, ValueError):
                saved_step_index = 0
            # 旧版向导的步骤顺序不同。恢复时以已经存在的结果为准，
            # 避免把旧的阶段规划当成当前故事底盘。
            if self.premise_candidates and saved_step_index > 0:
                if "bible" not in self.step_results:
                    saved_step_index = 1
                elif _as_text(self._generation_state("bible").get("status")).lower() == "partial":
                    saved_step_index = 1
                elif "stage_plan" not in self.step_results:
                    # A saved bible result is not automatically confirmable.
                    # Re-run the same validation used by the Next button so a
                    # malformed result cannot reopen directly on stage plans.
                    bible_error = self._bible_validation_error(
                        self.step_results.get("bible", {})
                    )
                    saved_step_index = 1 if bible_error else 2
                elif _as_text(self._generation_state("stage_plan").get("status")).lower() == "partial":
                    saved_step_index = 2
                else:
                    saved_step_index = min(saved_step_index, len(CREATION_WIZARD_STEPS) - 1)
            self.current_step_index = saved_step_index
            self._refresh_step_ui()
        finally:
            self._draft_restoring = False

    def _populate_candidate_list(self):
        target_index = max(
            0,
            min(self.premise_selected_index, len(self.premise_candidates) - 1),
        )
        self.premise_selected_index = target_index
        self.candidate_list.blockSignals(True)
        try:
            self.candidate_list.clear()
            for index, item in enumerate(self.premise_candidates, 1):
                text = _as_text(item.get("title")) or f"方向 {index}"
                self.candidate_list.addItem(QListWidgetItem(text))
            if self.premise_candidates:
                self.candidate_list.setCurrentRow(target_index)
        finally:
            self.candidate_list.blockSignals(False)
        if self.premise_candidates:
            self._load_candidate(target_index)
            self.premise_result_frame.setVisible(True)

    def _clear_candidate_preview(self):
        self.candidate_title_label.clear()
        self.candidate_meta_label.clear()
        self.candidate_hook_label.clear()
        self.candidate_synopsis_preview.clear()

    def _show_empty_candidate_list(self, message="故事列表"):
        self.candidate_list.clear()
        placeholder = QListWidgetItem(message)
        placeholder.setFlags(Qt.NoItemFlags)
        self.candidate_list.addItem(placeholder)
        self._clear_candidate_preview()

    def clear_draft(self):
        delete_creation_wizard_draft(self.draft_id)

    def _add_page_header(self, layout, text):
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: #9da3ad; padding: 2px 0 8px;")
        layout.addWidget(label)

    def _selected_choice(self, key):
        return str(self.choice_values.get(key, "") or "").strip()

    def _selected_choice_display(self, key):
        value = self._selected_choice(key)
        if key == "protagonist_style" and value:
            for item in _character_style_choice_entries():
                if _as_text(item.get("id")) == value:
                    return _character_style_choice_label(item)
        return str(self.choice_display_values.get(key, "") or value or "").strip()

    def _selected_choice_picker_value(self, key):
        value = self._selected_choice(key)
        if key == "protagonist_style" and value:
            for item in _character_style_choice_entries():
                if _as_text(item.get("id")) == value:
                    return _character_style_choice_option_label(item)
        return self._selected_choice_display(key)

    def _selected_custom_protagonist_style(self):
        selected_id = self._selected_choice("protagonist_style")
        if not selected_id:
            return {}
        for item in _character_style_choice_entries():
            if _as_text(item.get("id")) != selected_id:
                continue
            style = {
                "personality": _as_text(item.get("personality")),
                "voice": _as_text(item.get("voice")),
            }
            return {key: value for key, value in style.items() if value}
        return {}

    def _choice_groups(self, key):
        if key == "protagonist_style":
            return _character_style_choice_groups()
        return CREATION_CHOICE_GROUPS.get(key, {})

    def _allow_power_levels(self):
        premise = self._current_premise()
        return story_requires_explicit_power_levels(
            self._selected_choice("genre"),
            premise.get("genre", "") if isinstance(premise, dict) else "",
            premise.get("synopsis", "") if isinstance(premise, dict) else "",
            premise.get("main_line", "") if isinstance(premise, dict) else "",
        )

    def _normalize_step_result(self, step, payload):
        payload = payload if isinstance(payload, dict) else {}
        generation_state = deepcopy(payload.get("_generation_state", {}))
        is_partial_stage = (
            step == "stage_plan"
            and isinstance(generation_state, dict)
            and _as_text(generation_state.get("status")).lower() == "partial"
        )
        result = normalize_creation_result(
            step,
            payload,
            allow_power_levels=self._allow_power_levels() if step in {"bible", "story_assets"} else False,
            pad_stage_plan=not is_partial_stage,
            foreshadow_stage_count=(
                _expected_stage_count(self.target_words_spin.value())
                if step == "bible" else None
            ),
            total_words=self.target_words_spin.value(),
            average_chapter_words=self.average_words_spin.value(),
        )
        # AI 返回的阶段范围可能沿用了默认篇幅；向导的用户选择才是最终边界。
        if step == "stage_plan" and isinstance(result, dict):
            total_chapters = _creation_total_chapters(
                self.target_words_spin.value(),
                self.average_words_spin.value(),
            )
            result["stage_plan"] = normalize_stage_plan_ranges(
                result.get("stage_plan", []),
                self.target_words_spin.value(),
                self.average_words_spin.value(),
                expected_count=(
                    len(result.get("stage_plan", []))
                    if is_partial_stage else None
                ),
                pad_missing=not is_partial_stage,
            )
            result["foreshadow_schedule"] = _normalize_foreshadow_schedule(
                result.get("foreshadow_schedule", []),
                total_chapters,
            )
        if generation_state:
            result["_generation_state"] = generation_state
        return result

    def _generation_state(self, step):
        result = self.step_results.get(step, {})
        if not isinstance(result, dict):
            return {}
        state = result.get("_generation_state", {})
        return deepcopy(state) if isinstance(state, dict) else {}

    def _canonicalize_stage_schedule(self, result, strict=False):
        """Rebuild the stage schedule from the second-step foreshadow baseline."""
        if not isinstance(result, dict):
            return [], []
        bible_result = self.step_results.get("bible", {})
        foreshadows = (
            bible_result.get("foreshadows", [])
            if isinstance(bible_result, dict) else []
        )
        if not isinstance(foreshadows, list) or not foreshadows:
            return [], []
        specs = self._stage_specs()
        total_chapters = _creation_total_chapters(
            self.target_words_spin.value(),
            self.average_words_spin.value(),
        )
        derived_rows = []
        for position, stage in enumerate(
            result.get("stage_plan", [])
            if isinstance(result.get("stage_plan", []), list) else []
        ):
            if not isinstance(stage, dict):
                continue
            stage_index = _creation_stage_index(stage.get("id"))
            if stage_index < 0:
                stage_index = position
            derived_rows.extend(
                _derive_stage_endpoint_rows(
                    {
                        "stage_plan": [stage],
                        "foreshadow_schedule": [],
                    },
                    stage_index,
                    specs,
                    foreshadows,
                    total_chapters,
                )
            )
        schedule_input = []
        schedule_input.extend(
            result.get("foreshadow_schedule", [])
            if isinstance(result.get("foreshadow_schedule", []), list) else []
        )
        schedule_input.extend(derived_rows)
        schedule, notes, errors = _canonicalize_foreshadow_schedule(
            foreshadows,
            schedule_input,
            specs,
            total_chapters,
            strict=strict,
        )
        result["foreshadow_schedule"] = schedule
        result["chapter_plan_note"] = _clean_chapter_plan_note(
            result.get("chapter_plan_note", "")
        )
        for note in notes:
            result["chapter_plan_note"] = _append_note(
                _clean_chapter_plan_note(result.get("chapter_plan_note", "")),
                note,
            )
        if errors and strict:
            raise ValueError("阶段规划返回了不属于当前伏笔阶段的章位：" + "；".join(errors[:6]))
        return schedule, errors

    def _sync_stage_generation_state(self, result):
        """Rebuild stage progress from saved content, never from a stale counter."""
        if not isinstance(result, dict):
            return None
        specs = self._stage_specs()
        skeleton = _normalize_stage_skeleton(
            result.get("stage_skeleton", []),
            self.target_words_spin.value(),
            self.average_words_spin.value(),
        )
        if skeleton:
            result["stage_skeleton"] = skeleton
        skeleton_complete = len(skeleton) == len(specs)
        self._canonicalize_stage_schedule(result, strict=False)
        first_missing_stage, _by_index = _stage_plan_progress(
            result.get("stage_plan", []),
            len(specs),
        )
        foreshadow_missing = _stage_foreshadow_shortfalls(
            self.step_results.get("bible", {}).get("foreshadows", [])
            if isinstance(self.step_results.get("bible", {}), dict) else [],
            result.get("foreshadow_schedule", []),
            specs,
            _creation_total_chapters(
                self.target_words_spin.value(),
                self.average_words_spin.value(),
            ),
        )
        first_missing_endpoint = min(
            (
                item.get("stage_index", len(specs))
                for item in foreshadow_missing
                if isinstance(item, dict)
            ),
            default=None,
        )
        # Existing completed projects may predate the compact skeleton. Keep
        # their already complete stage plan usable; new generation runs still
        # request a skeleton before the first stage batch.
        complete = first_missing_stage is None and not foreshadow_missing
        result["_generation_state"] = {
            "schema_version": 1,
            "status": "complete" if complete else "partial",
            "skeleton_complete": skeleton_complete,
            # Stage content decides which stage is generated next. Missing
            # foreshadow endpoints are repaired separately and must never
            # point the whole-stage request back to an already saved stage.
            "next_stage_index": (
                len(specs) if first_missing_stage is None else first_missing_stage
            ),
            "next_endpoint_stage_index": (
                len(specs) if first_missing_endpoint is None else first_missing_endpoint
            ),
            "stage_count": len(specs),
            "missing_foreshadow_endpoints": [
                {
                    "stage_index": item.get("stage_index"),
                    "kind": item.get("kind"),
                    "code": item.get("code"),
                    "name": item.get("name", ""),
                }
                for item in foreshadow_missing
            ],
            "updated_at": now_str(),
        }
        # Endpoint warnings describe an incomplete intermediate merge.  Once
        # every stage and every endpoint is present, a later retry or a stale
        # legacy row must not leave an obsolete warning in the completed draft.
        if complete:
            result["foreshadow_endpoint_warnings"] = []
        return first_missing_stage

    def _merge_stage_skeleton(self, result):
        """Save the compact whole-book anchor before any stage batch runs."""
        skeleton = _normalize_stage_skeleton(
            result.get("stage_skeleton", []) if isinstance(result, dict) else [],
            self.target_words_spin.value(),
            self.average_words_spin.value(),
        )
        specs = self._stage_specs()
        if len(skeleton) != len(specs):
            raise ValueError(
                f"全书阶段骨架没有覆盖全部阶段：收到{len(skeleton)}个，需要{len(specs)}个。"
            )
        current = deepcopy(self.step_results.get("stage_plan", {}))
        if not isinstance(current, dict):
            current = {}
        current["stage_skeleton"] = skeleton
        current.setdefault("stage_plan", [])
        current["_generation_state"] = {
            "schema_version": 1,
            "status": "partial",
            "skeleton_complete": True,
            "next_stage_index": 0,
            "stage_count": len(specs),
            "missing_foreshadow_endpoints": [],
            "updated_at": now_str(),
        }
        self.step_results["stage_plan"] = current

    def _stage_specs(self):
        return _creation_stage_batch_specs(
            self.target_words_spin.value(),
            self.average_words_spin.value(),
        )

    def _next_generation_batch(self, step):
        state = self._generation_state(step)
        if step == "premise":
            return "premise", -1
        if step == "bible":
            if not state:
                return "bible_core", -1
            if _as_text(state.get("status")).lower() == "complete":
                result = self.step_results.get("bible", {})
                if isinstance(result, dict) and _creation_scale_shortfalls(
                    result,
                    self.target_words_spin.value(),
                ):
                    return "bible_assets", -1
                return "bible_core", -1
            completed = state.get("completed_batches", [])
            if "bible_core" not in completed:
                return "bible_core", -1
            return "bible_assets", -1
        if step == "stage_plan":
            specs = self._stage_specs()
            result = self.step_results.get("stage_plan", {})
            if isinstance(result, dict):
                self._sync_stage_generation_state(result)
                state = self._generation_state(step)
                if not result.get("stage_skeleton"):
                    return "stage_skeleton", -1
                if _as_text(state.get("status")).lower() == "partial":
                    first_missing, stages_by_index = _stage_plan_progress(
                        result.get("stage_plan", []),
                        len(specs),
                    )
                    missing_endpoints = state.get("missing_foreshadow_endpoints", [])
                    # A saved stage is the only stage whose endpoint can be
                    # repaired now.  Repair it before opening the next stage,
                    # so later stages receive the complete continuity handoff.
                    completed_stage_indexes = {
                        index for index, stage in stages_by_index.items()
                        if _stage_has_meaningful_content(stage)
                    }
                    completed_endpoint_indexes = [
                        int(item.get("stage_index"))
                        for item in missing_endpoints
                        if isinstance(item, dict)
                        and str(item.get("stage_index", "")).lstrip("-").isdigit()
                        and int(item.get("stage_index")) in completed_stage_indexes
                    ]
                    if completed_endpoint_indexes:
                        return "stage_endpoint_repair", min(completed_endpoint_indexes)
                    next_index = int(state.get("next_stage_index", 0) or 0)
                    if next_index < len(specs):
                        return "stage_plan_stage", next_index
                    endpoint_index = int(
                        state.get("next_endpoint_stage_index", len(specs))
                        or len(specs)
                    )
                    if endpoint_index < len(specs):
                        return "stage_endpoint_repair", endpoint_index
            first_missing, _by_index = _stage_plan_progress(
                result.get("stage_plan", []) if isinstance(result, dict) else [],
                len(specs),
            )
            if first_missing is None:
                state = self._generation_state(step)
                endpoint_index = int(
                    state.get("next_endpoint_stage_index", len(specs)) or len(specs)
                )
                if endpoint_index < len(specs):
                    return "stage_endpoint_repair", endpoint_index
                return "stage_plan_stage", 0
            return "stage_plan_stage", min(first_missing, max(0, len(specs) - 1))
        return "", -1

    def _set_choice(self, key, value):
        value = str(value or "").strip()
        display_value = value
        if key == "protagonist_style":
            selected_item = next(
                (
                    item for item in _character_style_choice_entries()
                    if _as_text(item.get("id")) == value
                    or _character_style_choice_label(item) == value
                    or _character_style_choice_option_label(item) == value
                ),
                None,
            )
            if selected_item is not None:
                value = _as_text(selected_item.get("id"))
                display_value = _character_style_choice_label(selected_item)
            else:
                self.choice_values.pop(key, None)
                self.choice_display_values.pop(key, None)
                button = self.choice_summary_buttons.get(key)
                if button is not None:
                    button.setText("点击选择")
                self._save_draft()
                return
        if key == "theme":
            theme_values = []
            for item in re.split(r"[、,，]", value):
                item = item.strip()
                if item and item not in theme_values:
                    theme_values.append(item)
            value = "、".join(theme_values[:2])
        elif not value:
            return
        previous = self._selected_choice(key)
        self.choice_values[key] = value
        self.choice_display_values[key] = display_value
        button = self.choice_summary_buttons.get(key)
        if button is not None:
            button.setText(display_value or "点击选择")
        arrows = self.choice_arrow_buttons.get(key, ())
        if arrows:
            if key == "theme":
                tooltip = f"{CREATION_CHOICE_TITLES.get(key, key)}：打开多选窗口"
                arrows[0].setToolTip(tooltip)
                arrows[1].setToolTip(tooltip)
            else:
                arrows[0].setToolTip(f"{CREATION_CHOICE_TITLES.get(key, key)}：上一个选项")
                arrows[1].setToolTip(f"{CREATION_CHOICE_TITLES.get(key, key)}：下一个选项")
        if previous and previous != value and self.premise_candidates:
            self._invalidate_steps_from("stage_plan")
        self._on_choice_changed(key)
        self._save_draft()

    def _choice_options(self, key):
        groups = self._choice_groups(key)
        options = []
        seen = set()
        for values in groups.values():
            if isinstance(values, (list, tuple)):
                for value in values:
                    value = str(value)
                    if value not in seen:
                        seen.add(value)
                        options.append(value)
        return options

    def _step_choice(self, key, delta):
        if key == "theme":
            self._open_choice_picker(key)
            return
        options = self._choice_options(key)
        if not options:
            return
        current = self._selected_choice_picker_value(key)
        try:
            index = options.index(current)
        except ValueError:
            index = 0
        next_index = (index + int(delta)) % len(options)
        self._set_choice(key, options[next_index])

    def _add_choice_selector(self, grid, key, row_index, column_index):
        cell = QFrame()
        cell.setFrameShape(QFrame.StyledPanel)
        cell.setStyleSheet(
            "QFrame { background: #1b1d22; border: 1px solid #363b45; border-radius: 5px; }"
        )
        cell_layout = QHBoxLayout(cell)
        cell_layout.setContentsMargins(8, 6, 8, 6)
        cell_layout.setSpacing(6)
        title = QLabel(CREATION_CHOICE_TITLES.get(key, key))
        title.setMinimumWidth(66)
        title.setStyleSheet("font-size: 13px; font-weight: 600; color: #e3e6eb;")
        title.setToolTip(CREATION_CHOICE_HINTS.get(key, ""))
        cell_layout.addWidget(title)

        selector_frame = QFrame()
        selector_frame.setObjectName(f"choice_selector_{key}")
        selector_frame.setMinimumHeight(32)
        selector_frame.setStyleSheet(
            f"""
            QFrame#choice_selector_{key} {{
                background: #315d86;
                border: 1px solid #6da4d8;
                border-radius: 5px;
            }}
            """
        )
        selector_layout = QHBoxLayout(selector_frame)
        selector_layout.setContentsMargins(0, 0, 0, 0)
        selector_layout.setSpacing(0)

        button = QPushButton()
        button.setMinimumHeight(32)
        button.setText("点击选择")
        button.setCursor(Qt.PointingHandCursor)
        button.setToolTip("点击打开完整选项")
        button.setStyleSheet(
            """
            QPushButton {
                color: #ffffff;
                background: transparent;
                border: 0;
                border-radius: 0;
                padding: 6px 8px;
                text-align: left;
            }
            QPushButton:hover {
                background: #3b6e9c;
            }
            """
        )
        self.choice_summary_buttons[key] = button
        self.choice_widgets.append(button)
        button.clicked.connect(lambda _checked=False, choice_key=key: self._open_choice_picker(choice_key))

        arrow_layout = QVBoxLayout()
        arrow_layout.setContentsMargins(0, 0, 0, 0)
        arrow_layout.setSpacing(0)
        up_button = QToolButton()
        up_button.setArrowType(Qt.UpArrow)
        up_button.setAutoRaise(True)
        up_button.setFixedSize(18, 15)
        up_button.setStyleSheet(
            """
            QToolButton {
                color: #d9dde4;
                background: transparent;
                border: 0;
                border-left: 1px solid #3a3f49;
            }
            QToolButton:hover {
                background: #315d86;
            }
            """
        )
        up_button.clicked.connect(lambda choice_key=key: self._step_choice(choice_key, -1))
        down_button = QToolButton()
        down_button.setArrowType(Qt.DownArrow)
        down_button.setAutoRaise(True)
        down_button.setFixedSize(18, 15)
        down_button.setStyleSheet(
            """
            QToolButton {
                color: #d9dde4;
                background: transparent;
                border: 0;
                border-left: 1px solid #3a3f49;
            }
            QToolButton:hover {
                background: #315d86;
            }
            """
        )
        down_button.clicked.connect(lambda choice_key=key: self._step_choice(choice_key, 1))
        arrow_layout.addWidget(up_button)
        arrow_layout.addWidget(down_button)
        self.choice_arrow_buttons[key] = (up_button, down_button)
        self.choice_widgets.extend((up_button, down_button))
        selector_layout.addWidget(button, 1)
        selector_layout.addLayout(arrow_layout)
        cell_layout.addWidget(selector_frame, 1)
        default = CREATION_CHOICE_DEFAULTS.get(key)
        self._set_choice(key, default)
        grid.addWidget(cell, row_index, column_index)

    def _open_choice_picker(self, key):
        removable_options = None
        if key == "protagonist_style":
            removable_options = {
                _character_style_choice_option_label(item): _as_text(item.get("id"))
                for item in _character_style_choice_entries()
            }
        dialog = CreationChoicePickerDialog(
            CREATION_CHOICE_TITLES.get(key, key),
            self._choice_groups(key),
            current_value=self._selected_choice_picker_value(key),
            max_selections=2 if key == "theme" else 1,
            parent=self,
            removable_options=removable_options,
        )
        if key == "protagonist_style":
            dialog.style_removed.connect(self._on_character_style_removed)
        if dialog.exec() == QDialog.Accepted:
            if key == "theme" or dialog.selected_value:
                self._set_choice(key, dialog.selected_value)

    def _on_character_style_removed(self, style_id):
        if self._selected_choice("protagonist_style") == style_id:
            self._set_choice("protagonist_style", "")

    def _on_choice_changed(self, key):
        if key == "length":
            values = {
                "30万字": 300000,
                "50万字": 500000,
                "100万字+": 1000000,
            }
            self.target_words_spin.setValue(values.get(self._selected_choice(key), 500000))
        elif key == "chapter_words":
            raw_value = self._selected_choice(key).replace("字", "").replace(",", "").strip()
            try:
                chapter_words = int(raw_value)
            except (TypeError, ValueError):
                chapter_words = 3000
            self.average_words_spin.setValue(
                max(self.average_words_spin.minimum(), min(
                    self.average_words_spin.maximum(),
                    chapter_words,
                ))
            )
        self._save_draft()

    def _build_premise_page(self):
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        layout = QVBoxLayout()
        layout.setContentsMargins(2, 2, 2, 2)
        layout.setSpacing(7)
        self.inspiration_edit = QLineEdit()
        self.inspiration_edit.setPlaceholderText(
            "可选：书名：……；标签：……；简介：……；也可以直接输入一段灵感"
        )
        if self.project_name_hint:
            self.inspiration_edit.setText(self.project_name_hint)
        preferences_frame = QFrame()
        preferences_frame.setObjectName("creation_preferences")
        preferences_frame.setFrameShape(QFrame.NoFrame)
        preferences_frame.setStyleSheet(
            "QFrame#creation_preferences { background: transparent; border: none; }"
        )
        preferences_frame.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        preferences_layout = QVBoxLayout(preferences_frame)
        preferences_layout.setContentsMargins(8, 8, 8, 8)
        preferences_layout.setSpacing(7)
        preferences_title = QLabel("故事灵感")
        preferences_title.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Fixed)
        preferences_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #e3e6eb;")
        preferences_layout.addWidget(preferences_title)
        preferences_layout.addWidget(self.inspiration_edit)
        choice_grid = QGridLayout()
        choice_grid.setContentsMargins(0, 0, 0, 0)
        choice_grid.setHorizontalSpacing(7)
        choice_grid.setVerticalSpacing(7)
        for column in range(3):
            choice_grid.setColumnStretch(column, 1)
        for index, key in enumerate(
            (
                "audience", "genre", "theme", "protagonist_route",
                "protagonist_style", "style", "length", "chapter_words",
            )
        ):
            row_index, column_index = divmod(index, 3)
            self._add_choice_selector(choice_grid, key, row_index, column_index)
        preferences_layout.addLayout(choice_grid)

        self.premise_generate_btn = QPushButton("AI 生成 5 个故事方向")
        self.premise_generate_btn.setMinimumHeight(38)
        self.premise_generate_btn.clicked.connect(self._generate_current)
        premise_actions = QHBoxLayout()
        premise_actions.setSpacing(8)
        premise_actions.addWidget(self.premise_generate_btn, 1)
        self.premise_clear_btn = QPushButton("清空本步内容")
        self.premise_clear_btn.setMinimumHeight(38)
        self.premise_clear_btn.clicked.connect(
            lambda _checked=False: self._clear_step_content("premise")
        )
        premise_actions.addWidget(self.premise_clear_btn)
        preferences_layout.addLayout(premise_actions)
        layout.addWidget(preferences_frame)
        layout.addSpacing(14)

        self.premise_result_frame = QFrame()
        self.premise_result_frame.setObjectName("creation_results")
        self.premise_result_frame.setFrameShape(QFrame.NoFrame)
        self.premise_result_frame.setStyleSheet(
            "QFrame#creation_results { background: transparent; border: none; }"
        )
        result_layout = QVBoxLayout(self.premise_result_frame)
        result_layout.setContentsMargins(8, 8, 8, 8)
        result_layout.setSpacing(6)
        result_title = QLabel("故事方向（生成后直接在这里选择）")
        result_title.setStyleSheet("font-size: 13px; font-weight: 600; color: #e3e6eb;")
        result_layout.addWidget(result_title)
        body = QHBoxLayout()
        body.setSpacing(8)
        self.candidate_list = QListWidget()
        self.candidate_list.setSizePolicy(
            QSizePolicy.Preferred,
            QSizePolicy.Expanding,
        )
        self.candidate_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.candidate_list.currentRowChanged.connect(self._on_candidate_changed)
        placeholder = QListWidgetItem("故事列表")
        placeholder.setFlags(Qt.NoItemFlags)
        self.candidate_list.addItem(placeholder)
        body.addWidget(self.candidate_list)
        preview = QVBoxLayout()
        preview.setSpacing(6)
        self.candidate_title_label = QLabel()
        self.candidate_title_label.setStyleSheet("font-size: 16px; font-weight: 600; color: #f0f2f5;")
        self.candidate_title_label.setWordWrap(True)
        preview.addWidget(self.candidate_title_label)
        self.candidate_meta_label = QLabel()
        self.candidate_meta_label.setStyleSheet("color: #86b6df;")
        self.candidate_meta_label.setWordWrap(True)
        preview.addWidget(self.candidate_meta_label)
        self.candidate_hook_label = QLabel()
        self.candidate_hook_label.setStyleSheet("color: #d9dde4; font-weight: 600;")
        self.candidate_hook_label.setWordWrap(True)
        preview.addWidget(self.candidate_hook_label)
        self.candidate_synopsis_preview = QPlainTextEdit()
        self.candidate_synopsis_preview.setReadOnly(True)
        self.candidate_synopsis_preview.setSizePolicy(
            QSizePolicy.Expanding,
            QSizePolicy.Expanding,
        )
        self.candidate_synopsis_preview.setMinimumHeight(96)
        self.candidate_synopsis_preview.setPlaceholderText("选择左侧故事方向后，这里会显示简介。")
        preview.addWidget(self.candidate_synopsis_preview, 1)
        body.addLayout(preview, 1)
        result_layout.addLayout(body, 1)
        layout.addWidget(self.premise_result_frame, 1)
        # Keep the first-step controls anchored at the top when the result
        # area is hidden after clearing the generated story directions.
        layout.addStretch(1)
        page_layout.addLayout(layout)
        page_scroll = QScrollArea()
        page_scroll.setWidgetResizable(True)
        page_scroll.setFrameShape(QFrame.NoFrame)
        page_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        page_scroll.setWidget(page)
        self.stack.addWidget(page_scroll)

    def _build_json_page(self, step, title):
        page = QWidget()
        layout = QVBoxLayout(page)
        header_text = (
            "生成后会按小说圣经、世界规则、人物、设定库、伏笔分别显示，"
            "每一栏都对应主程序里的资料栏目。确认后才会写入新项目。"
            if step == "bible"
            else f"AI 会根据前面已经确认的灵感和选择自动生成{title}。这里展示可读摘要，确认后才会写入新项目。"
        )
        self._add_page_header(
            layout,
            header_text,
        )
        generate_btn = QPushButton(f"AI 生成{title}")
        generate_btn.clicked.connect(self._generate_current)
        clear_btn = QPushButton("清空本步内容")
        clear_btn.clicked.connect(
            lambda _checked=False, current_step=step: self._clear_step_content(current_step)
        )
        action_layout = QHBoxLayout()
        action_layout.setSpacing(8)
        action_layout.addWidget(generate_btn, 1)
        action_layout.addWidget(clear_btn)
        layout.addLayout(action_layout)
        if step == "bible":
            editor = CreationSectionedPreview()
        else:
            editor = QPlainTextEdit()
            editor.setReadOnly(True)
            editor.setLineWrapMode(QPlainTextEdit.WidgetWidth)
            editor.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
            editor.setPlaceholderText("点击上面的按钮生成内容。你不需要填写 JSON。")
        layout.addWidget(editor, 1)
        self.json_editors = getattr(self, "json_editors", {})
        self.json_generate_buttons = getattr(self, "json_generate_buttons", {})
        self.json_clear_buttons = getattr(self, "json_clear_buttons", {})
        self.json_editors[step] = editor
        self.json_generate_buttons[step] = generate_btn
        self.json_clear_buttons[step] = clear_btn
        self.stack.addWidget(page)

    def _update_responsive_controls(self):
        candidate_list = getattr(self, "candidate_list", None)
        if candidate_list is not None:
            list_width = max(170, min(300, int(self.width() * 0.22)))
            candidate_list.setMinimumWidth(list_width)
            candidate_list.setMaximumWidth(list_width)
        synopsis = getattr(self, "candidate_synopsis_preview", None)
        if synopsis is not None:
            synopsis.setMinimumHeight(max(88, min(180, int(self.height() * 0.14))))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_responsive_controls()

    def _set_preview_result(self, step, result):
        editor = self.json_editors.get(step)
        if editor is None:
            return
        if step == "bible" and hasattr(editor, "set_result"):
            editor.set_result(result)
        else:
            editor.setPlainText(format_creation_preview(step, result))

    def _refresh_step_ui(self):
        # 接收字符数属于当前步骤和当前请求的临时状态。切换步骤时不能把
        # 上一步的数字拼到新的状态提示后面；同一步刷新则保留实时进度。
        if self._status_step_index != self.current_step_index:
            self._received_chars = 0
            self._status_step_index = self.current_step_index
        step, title = CREATION_WIZARD_STEPS[self.current_step_index]
        self.step_label.setText(f"第 {self.current_step_index + 1}/{len(CREATION_WIZARD_STEPS)} 步：{title}")
        self.stack.setCurrentIndex(self.current_step_index)
        self.back_btn.setEnabled(self.current_step_index > 0 and self.worker is None)
        self.next_btn.setEnabled(self.worker is None and self._current_step_ready())
        self.next_btn.setText("确认并创建项目" if self.current_step_index == len(CREATION_WIZARD_STEPS) - 1 else "确认并下一步")
        if self.current_step_index == 0:
            self._set_status_text("先输入一点灵感，再选择题材和阅读感觉。")
        elif step in self.step_results:
            state = self._generation_state(step)
            if step == "stage_plan":
                self._sync_stage_generation_state(self.step_results[step])
                state = self._generation_state(step)
                if not self.step_results[step].get("stage_skeleton"):
                    self._set_status_text("点击生成后会先整理全书阶段骨架，再按十万字阶段依次生成。")
                elif _as_text(state.get("status")).lower() == "partial":
                    next_batch, next_index = self._next_generation_batch("stage_plan")
                    if next_batch == "stage_endpoint_repair":
                        self._set_status_text(
                            f"当前阶段正文已保存，点击生成会先补齐第{next_index + 1}阶段的伏笔定位。"
                        )
                    elif next_batch == "stage_plan_stage" and next_index < len(self._stage_specs()):
                        self._set_status_text(
                            f"当前步骤已保存部分内容，点击生成会继续第{next_index + 1}阶段。"
                        )
                    else:
                        self._set_status_text("当前步骤已保存部分内容，请点击生成继续未完成批次。")
                else:
                    self._set_status_text("当前步骤已有完整阶段规划，可以重新生成或直接确认。")
            elif _as_text(state.get("status")).lower() == "partial":
                if step == "bible":
                    self._set_status_text("当前步骤已保存第一批资料，点击生成会继续第二批。")
                else:
                    next_index = int(state.get("next_stage_index", 0) or 0)
                    if next_index < len(self._stage_specs()):
                        self._set_status_text(
                            f"当前步骤已保存前面阶段，点击生成会继续第{next_index + 1}阶段。"
                        )
                    else:
                        endpoint_index = int(
                            state.get("next_endpoint_stage_index", len(self._stage_specs()))
                            or len(self._stage_specs())
                        )
                        self._set_status_text(
                            f"阶段正文已生成，点击生成会补齐第{endpoint_index + 1}阶段的伏笔定位。"
                            if endpoint_index < len(self._stage_specs())
                            else "当前步骤已保存部分内容，请点击生成继续未完成批次。"
                        )
            else:
                if step == "bible":
                    bible_error = self._bible_validation_error(self.step_results.get("bible", {}))
                    if bible_error:
                        self._set_status_text(bible_error)
                    else:
                        self._set_status_text("当前步骤已有 AI 结果，可以重新生成或直接确认。")
                else:
                    self._set_status_text("当前步骤已有 AI 结果，可以重新生成或直接确认。")
        else:
            self._set_status_text("请点击 AI 生成当前步骤。")

    def _current_step_ready(self):
        step = CREATION_WIZARD_STEPS[self.current_step_index][0]
        if step == "premise":
            return bool(self.premise_candidates)
        if step == "bible":
            result = self.step_results.get("bible", {})
            state = self._generation_state("bible")
            return (
                isinstance(result, dict)
                and _as_text(state.get("status")).lower() in {"", "complete"}
                and not self._bible_validation_error(result)
            )
        if step == "stage_plan":
            result = self.step_results.get(step, {})
            if not isinstance(result, dict):
                return False
            self._sync_stage_generation_state(result)
            if _as_text(self._generation_state(step).get("status")).lower() == "partial":
                return False
            first_missing, _by_index = _stage_plan_progress(
                result.get("stage_plan", []),
                len(self._stage_specs()),
            )
            return first_missing is None
        return step in self.step_results

    def _bible_validation_error(self, result):
        """Return the confirmation error shared by generation, navigation and restore."""
        normalized = self._normalize_step_result("bible", result)
        missing = [
            label for key, label in (
                ("bible", "小说圣经"),
                ("world_rules", "世界规则"),
                ("characters", "人物"),
                ("lore", "设定"),
                ("foreshadows", "伏笔"),
            )
            if not _has_creation_content(normalized.get(key))
        ]
        if missing:
            return f"当前故事底盘缺少：{'、'.join(missing)}。请重新生成完整故事底盘。"
        stage_shortfalls = _foreshadow_stage_shortfalls(
            normalized.get("foreshadows", []),
            _expected_stage_count(self.target_words_spin.value()),
        )
        if stage_shortfalls:
            stage_count = _expected_stage_count(self.target_words_spin.value())
            return (
                "伏笔阶段位置无效或超出本书阶段范围："
                + "、".join(stage_shortfalls[:12])
                + f"。本书只有第1至第{stage_count}阶段，请重新生成故事底盘。"
            )
        scale_shortfalls = _creation_scale_shortfalls(
            normalized,
            self.target_words_spin.value(),
        )
        if scale_shortfalls:
            return (
                "故事底盘资料数量未达到按阶段计算的最低要求："
                + "、".join(scale_shortfalls)
                + "。请重新生成故事底盘。"
            )
        return ""

    def _set_status_text(self, text):
        self._status_text = str(text or "")
        suffix = ""
        if self._received_chars > 0:
            suffix = f"；已接收字符：{self._received_chars}"
        display_text = self._status_text + suffix
        self.status_label.setText(display_text)
        self.status_label.setToolTip(display_text)

    def _on_worker_progress(self, text):
        self._set_status_text(text)

    def _on_worker_output_chars(self, count):
        try:
            self._received_chars = max(0, int(count or 0))
        except (TypeError, ValueError):
            return
        self._set_status_text(self._status_text)

    def _context_for_step(self, step, retry_feedback=""):
        inspiration = self.inspiration_edit.text().strip()
        requested_title = _creation_requested_title(
            inspiration,
            self.project_name_hint,
        )
        genre = self._selected_choice("genre")
        context = {
            "author_input": {
                "inspiration": inspiration,
                "requested_title": requested_title,
                "temporary_title": requested_title or self.project_name_hint,
                "genre": genre,
                "theme": self._selected_choice("theme"),
                "audience": self._selected_choice("audience"),
                "style": self._selected_choice("style"),
                "protagonist_route": self._selected_choice("protagonist_route"),
                "length": self._selected_choice("length"),
                "total_words": self.target_words_spin.value(),
                "average_chapter_words": self.average_words_spin.value(),
                "no_injury": True,
                "ending": "本部结果明确，结局形态由故事本身决定，可保留不影响闭环的余味",
            },
        }
        custom_protagonist_style = self._selected_custom_protagonist_style()
        if step in {"premise", "bible"} and custom_protagonist_style:
            # Only the reusable personality and voice are sent to the model;
            # source names and the original character's story data stay local.
            context["author_input"]["custom_protagonist_style"] = custom_protagonist_style
        if step == "premise":
            current_names = [
                _creation_premise_name(item.get("protagonist"))
                for item in self.premise_candidates
                if isinstance(item, dict)
            ]
            context["naming_reference"] = _creation_name_references(current_names)
        premise = self._current_premise() if step != "premise" else {}
        if step != "premise":
            context["selected_premise"] = premise
        if step == "bible":
            context["confirmed"] = {
                # Only the selected candidate is authoritative. It is already
                # carried once as selected_premise; do not send a second copy.
            }
            batch_kind, _stage_index = self._next_generation_batch("bible")
            context["generation_batch"] = batch_kind
            if batch_kind == "bible_assets":
                bible_result = self.step_results.get("bible", {})
                if isinstance(bible_result, dict):
                    context["confirmed"]["bible"] = {
                        "bible": deepcopy(bible_result.get("bible", {})),
                        "world_rules": deepcopy(bible_result.get("world_rules", {})),
                    }
        elif step == "stage_plan":
            batch_kind, stage_index = self._next_generation_batch("stage_plan")
            specs = self._stage_specs()
            current_stage = specs[stage_index] if 0 <= stage_index < len(specs) else {}
            stage_result = self.step_results.get("stage_plan", {})
            context["confirmed"] = {
                "bible": deepcopy(self.step_results.get("bible", {})),
            }
            context["generation_batch"] = batch_kind
            if isinstance(stage_result, dict) and stage_result.get("stage_skeleton"):
                context["confirmed"]["stage_skeleton"] = deepcopy(
                    stage_result.get("stage_skeleton", [])
                )
            context["current_stage"] = deepcopy(current_stage)
            bible_result = self.step_results.get("bible", {})
            bible_foreshadows = (
                bible_result.get("foreshadows", [])
                if isinstance(bible_result, dict) else []
            )
            if batch_kind == "stage_plan_stage":
                endpoint_requirements = _foreshadow_stage_requirements(
                    bible_foreshadows,
                    specs,
                )
                context["current_foreshadow_endpoints"] = [
                    {
                        "code": item.get("code") or item.get("name"),
                        "name": item.get("name", ""),
                        "kind": item.get("kind"),
                        "stage": item.get("stage_index", 0) + 1,
                        "use": (
                            "让这条线索在人物生活中第一次出现，改变当下的行动或关系"
                            if item.get("kind") == "setup"
                            else "让这条线索在现场产生新的事实，改变人物的行动、关系或局势"
                        ),
                    }
                    for item in endpoint_requirements.get(stage_index, [])
                ]
            elif batch_kind == "stage_endpoint_repair":
                state = self._generation_state("stage_plan")
                missing = [
                    item for item in state.get("missing_foreshadow_endpoints", [])
                    if isinstance(item, dict)
                    and int(item.get("stage_index", -1) or -1) == stage_index
                ]
                context["missing_foreshadow_endpoints"] = [
                    {
                        "code": item.get("code") or item.get("name"),
                        "name": item.get("name", ""),
                        "kind": item.get("kind", ""),
                    }
                    for item in missing
                ]
                current_stage_plan = []
                for item in stage_result.get("stage_plan", []) if isinstance(stage_result, dict) else []:
                    if not isinstance(item, dict):
                        continue
                    item_index = _creation_stage_index(item.get("id"))
                    if item_index == stage_index:
                        current_stage_plan.append(deepcopy(item))
                        break
                context["confirmed"]["current_stage_plan"] = current_stage_plan
            if isinstance(stage_result, dict):
                _first_missing, stages_by_index = _stage_plan_progress(
                    stage_result.get("stage_plan", []),
                    len(specs),
                )
                previous_stages = [
                    deepcopy(stages_by_index[index])
                    for index in sorted(stages_by_index)
                    if index < stage_index
                    and _stage_has_meaningful_content(stages_by_index[index])
                ]
                context["confirmed"]["previous_stage_plan"] = deepcopy(
                    _compact_stage_plan_handoff(previous_stages)
                )
                context["confirmed"]["previous_foreshadow_schedule"] = deepcopy(
                    [
                        row for row in stage_result.get("foreshadow_schedule", [])
                        if isinstance(row, dict)
                        and (
                            _creation_chapter_number(row.get("setup_chapter")) > 0
                            and _creation_chapter_number(row.get("setup_chapter"))
                            <= int(current_stage.get("end_chapter", 0) or 0)
                            or _creation_chapter_number(row.get("payoff_chapter")) > 0
                            and _creation_chapter_number(row.get("payoff_chapter"))
                            <= int(current_stage.get("end_chapter", 0) or 0)
                            or _as_text(row.get("payoff_chapter")) == "结尾保留"
                        )
                    ]
                )
        retry_feedback = _as_text(retry_feedback).strip()
        if retry_feedback:
            context["generation_retry_feedback"] = retry_feedback[:2000]
        return context

    def _current_premise(self):
        if not self.premise_candidates:
            return {}
        index = max(0, min(self.premise_selected_index, len(self.premise_candidates) - 1))
        return deepcopy(self.premise_candidates[index])

    def _save_current_candidate(self):
        # 故事方向改为只读预览，避免用户在第一步重新填写一份策划案。
        return

    def _load_candidate(self, index):
        if index < 0 or index >= len(self.premise_candidates):
            return
        self._premise_loading_index = index
        item = self.premise_candidates[index]
        self.candidate_title_label.setText(_as_text(item.get("title")) or f"方向 {index + 1}")
        meta = " · ".join(
            part for part in (
                _as_text(item.get("audience")),
                _as_text(item.get("genre")) or self._selected_choice("genre"),
                self._selected_choice("theme"),
                _as_text(item.get("style")) or self._selected_choice("style"),
            ) if part
        )
        self.candidate_meta_label.setText(meta)
        self.candidate_hook_label.setText(_as_text(item.get("one_sentence")))
        self.candidate_synopsis_preview.setPlainText(_as_text(item.get("synopsis")))
        self._premise_loading_index = -1

    def _on_candidate_changed(self, index):
        if self._premise_loading_index >= 0:
            return
        if index >= 0:
            previous = self.premise_selected_index
            self.premise_selected_index = index
            self._load_candidate(index)
            if previous != index:
                self._invalidate_steps_from("bible")
            self._save_draft()

    def _generate_current(self):
        if self.worker is not None:
            return
        retrying_same_request = bool(self._retrying_same_request)
        retry_feedback = (
            self._last_worker_error
            if retrying_same_request or self._generation_failed
            else ""
        )
        self._retrying_same_request = False
        if not retrying_same_request:
            self._generation_retry_count = 0
        step = CREATION_WIZARD_STEPS[self.current_step_index][0]
        batch_kind, stage_index = self._next_generation_batch(step)
        if not batch_kind:
            return
        if step == "stage_plan" and batch_kind == "stage_plan_stage":
            # A queued continuation can carry an older stage index while the
            # previous result has already been merged. Recompute from the
            # saved stages immediately before opening the request so a
            # completed S02 can never be requested again merely because a
            # stale pending index still says 1. If the first missing stage is
            # the current one, keep it eligible for a genuine retry caused by
            # incomplete events or unresolved foreshadow endpoints.
            stage_result = self.step_results.get("stage_plan", {})
            if isinstance(stage_result, dict):
                self._sync_stage_generation_state(stage_result)
                specs = self._stage_specs()
                first_missing, _stage_by_index = _stage_plan_progress(
                    stage_result.get("stage_plan", []),
                    len(specs),
                )
                if first_missing is None:
                    self._set_status_text("阶段规划已经覆盖全部阶段，可以直接确认创建项目。")
                    self._refresh_step_ui()
                    return
                if stage_index < first_missing:
                    stage_index = first_missing
        state = self._generation_state(step)
        provider, model, error = self.ai_selection()
        if error:
            QMessageBox.warning(self, "新建向导", error)
            return
        if step == "bible" and batch_kind == "bible_core" and state.get("status") == "complete":
            self._invalidate_steps_from("stage_plan")
            self.step_results.pop("bible", None)
            editor = self.json_editors.get("bible")
            if editor is not None:
                editor.clear()
        elif step == "stage_plan" and state.get("status") == "complete":
            self.step_results.pop("stage_plan", None)
            editor = self.json_editors.get("stage_plan")
            if editor is not None:
                editor.clear()
        context = self._context_for_step(step, retry_feedback=retry_feedback)
        self.worker = NovelCreationWorker(
            provider.get("base_url", ""),
            provider.get("api_key", ""),
            model,
            step,
            context,
            provider.get("proxy_url", ""),
            provider.get("proxy_mode", "提交和下载" if provider.get("proxy_url") else "不使用代理"),
            batch_kind=batch_kind,
            stage_index=stage_index,
        )
        self.worker.diagnostic_request_id = (
            f"creation-wizard-{step}-{batch_kind or step}-{uuid.uuid4().hex[:12]}"
        )
        self.worker.diagnostic_stage = f"{step}:{batch_kind or step}"
        self.worker.diagnostic_project_path = _creation_wizard_draft_path(self.draft_id)
        self.worker.diagnostic_project_title = _as_text(
            self._current_premise().get("title")
        )
        self.worker.capture_raw_model_output = True
        self.worker.raw_model_output_metadata = {
            "creation_step": step,
            "creation_batch": batch_kind,
            "stage_index": int(stage_index) if stage_index is not None else -1,
            "draft_id": self.draft_id,
            "draft_created_at": self.created_at,
        }
        self.worker.result_ready.connect(self._on_ai_result)
        self.worker.failed.connect(self._on_ai_failed)
        self.worker.progress.connect(self._on_worker_progress)
        self.worker.output_chars.connect(self._on_worker_output_chars)
        self.worker.finished.connect(self._cleanup_worker)
        self._active_batch_kind = batch_kind
        self._active_stage_index = stage_index
        self._pending_batch_kind = ""
        self._pending_stage_index = -1
        self._pending_retry_delay_ms = 0
        self._generation_failed = False
        self._last_worker_error = ""
        self._received_chars = 0
        self._set_status_text("AI 正在连接并准备生成，请稍候……")
        self._save_draft()
        self._set_running(True)
        self.worker.start()

    def _merge_bible_batch(self, result, batch_kind):
        """Merge one story-base batch while keeping the other batch intact."""
        result = result if isinstance(result, dict) else {}
        if batch_kind == "bible_core" and not all(
            _has_creation_content(result.get(key))
            for key in ("bible", "world_rules")
        ):
            raise ValueError("第一批没有同时收到完整的小说圣经和世界规则。")
        if batch_kind == "bible_assets" and any(
            not isinstance(result.get(key), list) or not result.get(key)
            for key in ("characters", "lore", "foreshadows")
        ):
            raise ValueError("第二批没有同时收到完整的人物、设定和伏笔。")
        if batch_kind == "bible_assets":
            shortfalls = _creation_scale_shortfalls(
                result,
                self.target_words_spin.value(),
            )
            if shortfalls:
                raise ValueError(
                    "第二批资料数量没有达到按阶段计算的最低要求："
                    + "、".join(shortfalls)
                    + "。请重新生成第二批人物、设定和伏笔。"
                )
        current = deepcopy(self.step_results.get("bible", {}))
        if not isinstance(current, dict):
            current = {}
        if batch_kind == "bible_core":
            for key in ("bible", "world_rules"):
                if _has_creation_content(result.get(key)):
                    current[key] = deepcopy(result.get(key))
        elif batch_kind == "bible_assets":
            for key in ("characters", "lore", "foreshadows"):
                if isinstance(result.get(key), list):
                    current[key] = deepcopy(result.get(key))

        if batch_kind == "bible_core":
            world_rules = current.get("world_rules", {})
            if not isinstance(world_rules, dict):
                raise ValueError("第一批世界规则没有形成可执行的规则资料。")
            if not _normalize_text_list(world_rules.get("rules", [])):
                raise ValueError("第一批世界规则缺少长期规则条目，请重新生成这一批。")
            if not _normalize_text_list(world_rules.get("costs_and_limits", [])):
                raise ValueError("第一批世界规则缺少代价限制条目，请重新生成这一批。")

        if batch_kind == "bible_assets" and self._allow_power_levels():
            if not _has_ordered_power_lore(current.get("lore", [])):
                raise ValueError(
                    "当前题材需要一条按顺序说明的实力体系，但设定库中没有形成可执行的境界记录；"
                    "本次资料未写入，请重新生成第二批。"
                )

        completed = [
            str(item)
            for item in current.get("_generation_state", {}).get("completed_batches", [])
            if str(item)
        ] if isinstance(current.get("_generation_state"), dict) else []
        if batch_kind and batch_kind not in completed:
            completed.append(batch_kind)
        complete = all(item in completed for item in ("bible_core", "bible_assets"))
        current["_generation_state"] = {
            "schema_version": 1,
            "status": "complete" if complete else "partial",
            "completed_batches": completed,
            "next_batch": "" if complete else "bible_assets",
            "updated_at": now_str(),
        }
        if complete:
            bible_error = self._bible_validation_error(current)
            if bible_error:
                raise ValueError(bible_error)
        self.step_results["bible"] = current
        if complete:
            self._invalidate_steps_from("stage_plan")

    def _merge_stage_batch(self, result, stage_index):
        """Merge one stage and its local foreshadow endpoints in order."""
        specs = self._stage_specs()
        if stage_index < 0 or stage_index >= len(specs):
            raise ValueError("当前阶段编号无效，无法继续保存阶段规划。")
        spec = specs[stage_index]
        current = deepcopy(self.step_results.get("stage_plan", {}))
        if not isinstance(current, dict):
            current = {}
        incoming_stages = result.get("stage_plan", []) if isinstance(result, dict) else []
        incoming_stages = [item for item in incoming_stages if isinstance(item, dict)]
        if not incoming_stages:
            raise ValueError(f"第{stage_index + 1}阶段没有收到有效内容。")
        selected = None
        for item in incoming_stages:
            if _as_text(item.get("id")).upper() == spec["id"]:
                selected = deepcopy(item)
                break
        if selected is None:
            selected = deepcopy(
                incoming_stages[stage_index]
                if len(incoming_stages) > stage_index else incoming_stages[0]
            )
        # Normalize this response against the whole book, then force it into
        # the requested slot. A compact response may carry a stale S01 id;
        # the API batch's stage_index is authoritative here.
        normalized_selected = normalize_stage_plan_ranges(
            [selected],
            self.target_words_spin.value(),
            self.average_words_spin.value(),
            expected_count=len(specs),
            pad_missing=False,
        )
        if not normalized_selected:
            raise ValueError(f"第{stage_index + 1}阶段没有收到有效内容，当前批次未保存。")
        selected = normalized_selected[0]
        selected["id"] = spec["id"]
        selected["start_chapter"] = spec["start_chapter"]
        selected["end_chapter"] = spec["end_chapter"]
        selected["target_words"] = spec["target_words"]
        events = selected.get("ordered_events", [])
        endpoint_event_aliases = {}
        if isinstance(events, list):
            for event_index, event in enumerate(events, 1):
                if not isinstance(event, dict):
                    continue
                raw_event_id = _as_text(event.get("id"))
                normalized_raw_id = re.sub(r"\s+", "", raw_event_id.upper())
                event_match = re.search(r"E[_-]?(\d+)", normalized_raw_id)
                local_event_id = f"{spec['id']}-E{event_index:02d}"
                # Event numbers are local to one stage. Models sometimes use
                # chapter-like ids (S02-E21) or continue numbering from the
                # previous stage (E21-E30); both must map to the stable local
                # ids used by validation and the saved project.
                aliases = {
                    normalized_raw_id,
                    local_event_id.upper(),
                    f"E{event_index:02d}",
                }
                if event_match:
                    event_number = int(event_match.group(1))
                    aliases.add(f"E{event_number:02d}")
                    aliases.add(f"{spec['id']}-E{event_number:02d}".upper())
                for alias in aliases:
                    if alias:
                        endpoint_event_aliases[alias] = local_event_id
                event["id"] = local_event_id
                allowed = event.get("allowed_chapters", [])
                if isinstance(allowed, list) and len(allowed) >= 2:
                    try:
                        allowed_start, allowed_end = int(allowed[0]), int(allowed[1])
                    except (TypeError, ValueError):
                        allowed_start = allowed_end = 0
                    if (
                        allowed_start < spec["start_chapter"]
                        or allowed_end > spec["end_chapter"]
                        or allowed_start > allowed_end
                    ):
                        raise ValueError(
                            f"第{stage_index + 1}阶段事件 {event['id']} 超出了本阶段允许的第"
                            f"{spec['start_chapter']}—{spec['end_chapter']}章范围。"
                        )
        if not _stage_has_meaningful_content(selected):
            raise ValueError(
                f"第{stage_index + 1}阶段返回的是空结构或不完整内容，当前批次未保存；请重新生成。"
            )
        _validate_stage_batch_events(selected, stage_index, spec)

        # Merge by stable stage id. Never normalize the combined sparse list
        # by its length, because S04 must stay S04 when S02/S03 are missing.
        stage_by_index = {}
        for position, item in enumerate(current.get("stage_plan", [])):
            if not isinstance(item, dict):
                continue
            item_index = _creation_stage_index(item.get("id"))
            if not (0 <= item_index < len(specs)):
                item_index = position if position < len(specs) else -1
            if item_index < 0:
                continue
            stage_by_index[item_index] = deepcopy(item)
        stage_by_index[stage_index] = selected
        existing_stages = []
        for index in sorted(stage_by_index):
            item = stage_by_index[index]
            item["id"] = specs[index]["id"]
            item["start_chapter"] = specs[index]["start_chapter"]
            item["end_chapter"] = specs[index]["end_chapter"]
            item["target_words"] = specs[index]["target_words"]
            existing_stages.append(item)
        current["stage_plan"] = existing_stages
        total_chapters = _creation_total_chapters(
            self.target_words_spin.value(),
            self.average_words_spin.value(),
        )
        bible_result = self.step_results.get("bible", {})
        bible_foreshadows = (
            bible_result.get("foreshadows", [])
            if isinstance(bible_result, dict) else []
        )
        # Resolve the new event-anchored endpoint protocol before merging.  A
        # model response no longer needs to guess an independent chapter; the
        # event range and the second-step stage baseline determine it here.
        # Derive endpoints from the same locally-renumbered stage that will
        # be saved.  Translate transport ids such as E21/S02-E21 first so a
        # valid model response cannot lose its setup/payoff association.
        endpoint_result = deepcopy(result) if isinstance(result, dict) else {}
        endpoint_stages = endpoint_result.get("stage_plan", [])
        if isinstance(endpoint_stages, list):
            endpoint_stage = None
            for item in endpoint_stages:
                if isinstance(item, dict) and _as_text(item.get("id")).upper() == spec["id"]:
                    endpoint_stage = item
                    break
            if endpoint_stage is None and endpoint_stages:
                endpoint_stage = endpoint_stages[0]
            if endpoint_stage is not None:
                endpoint_stage = deepcopy(selected)
                endpoint_result["stage_plan"] = [endpoint_stage]
        endpoint_schedule = endpoint_result.get("foreshadow_schedule", [])
        if isinstance(endpoint_schedule, list):
            for row in endpoint_schedule:
                if not isinstance(row, dict):
                    continue
                raw_endpoint_id = re.sub(
                    r"\s+", "", _as_text(row.get("endpoint_event_id")).upper()
                )
                mapped_endpoint_id = endpoint_event_aliases.get(raw_endpoint_id)
                if mapped_endpoint_id:
                    row["endpoint_event_id"] = mapped_endpoint_id
        stage_endpoint_rows = _derive_stage_endpoint_rows(
            endpoint_result,
            stage_index,
            specs,
            bible_foreshadows,
            total_chapters,
        )
        # Persist any endpoint marker recovered from an explicit f event id in
        # the stage copy that is about to be saved as well.
        endpoint_markers = {
            (
                _as_text(row.get("endpoint_event_id")),
                _as_text(row.get("code")),
                _normalize_foreshadow_endpoint_kind(row.get("endpoint_kind")),
            )
            for row in stage_endpoint_rows
            if _as_text(row.get("endpoint_event_id")) and _as_text(row.get("code"))
        }
        for event in selected.get("ordered_events", []) if isinstance(selected.get("ordered_events"), list) else []:
            event_id = _as_text(event.get("id"))
            for endpoint_event_id, code, kind in endpoint_markers:
                if endpoint_event_id != event_id or not kind:
                    continue
                marker = f"{code}/{kind}"
                references = event.get("references", [])
                references = list(references) if isinstance(references, list) else ([references] if references else [])
                if not any(_as_text(item).upper() == marker.upper() for item in references):
                    references.insert(0, marker)
                    event["references"] = references
        combined_schedule = []
        combined_schedule.extend(
            current.get("foreshadow_schedule", [])
            if isinstance(current.get("foreshadow_schedule", []), list) else []
        )
        combined_schedule.extend(
            stage_endpoint_rows
        )
        canonical_schedule, schedule_notes, schedule_errors = _canonicalize_foreshadow_schedule(
            bible_foreshadows,
            combined_schedule,
            specs,
            total_chapters,
            strict=False,
        )
        current["foreshadow_schedule"] = canonical_schedule
        current_missing = [
            item for item in _stage_foreshadow_shortfalls(
                bible_foreshadows,
                current.get("foreshadow_schedule", []),
                specs,
                total_chapters,
            )
            if item.get("stage_index") == stage_index
        ]
        endpoint_warnings = [
            item for item in current.get("foreshadow_endpoint_warnings", [])
            if isinstance(item, dict) and item.get("stage_index") != stage_index
        ]
        if schedule_errors or current_missing:
            endpoint_warnings.append({
                "stage_index": stage_index,
                "errors": list(schedule_errors[:8]),
                "missing": [
                    {
                        "code": item.get("code"),
                        "name": item.get("name"),
                        "kind": item.get("kind"),
                    }
                    for item in current_missing
                ],
                "updated_at": now_str(),
            })
        current["foreshadow_endpoint_warnings"] = endpoint_warnings
        if isinstance(result, dict):
            if stage_index == 0:
                contract = _normalize_stage_book_contract(result.get("book_contract", {}))
                if contract:
                    current["book_contract"] = contract
                note = _clean_chapter_plan_note(result.get("chapter_plan_note"))
                if note:
                    current["chapter_plan_note"] = note
            for note in schedule_notes:
                current["chapter_plan_note"] = _append_note(
                    _clean_chapter_plan_note(current.get("chapter_plan_note", "")),
                    note,
                )
            current["planning_schema_version"] = (
                _as_text(result.get("planning_schema_version", "2")) or "2"
            )
        self._sync_stage_generation_state(current)
        self.step_results["stage_plan"] = current

        # Keep the second-step baseline stage-only.  Concrete chapter numbers
        # remain in the third-step foreshadow_schedule and are projected into
        # the final project only after the whole wizard is confirmed.

    def _merge_stage_endpoint_repair(self, result, stage_index):
        """Merge only missing foreshadow endpoints into an existing stage.

        A completed stage must never be regenerated just because one of its
        setup/payoff markers was absent.  This request only identifies the
        existing event that carries the missing endpoint; the stage text and
        the second-step foreshadow baseline remain unchanged.
        """
        specs = self._stage_specs()
        if stage_index < 0 or stage_index >= len(specs):
            raise ValueError("当前伏笔定位阶段编号无效，本次未保存。")

        current = deepcopy(self.step_results.get("stage_plan", {}))
        if not isinstance(current, dict):
            current = {}
        stage_by_index = {}
        for position, item in enumerate(current.get("stage_plan", [])):
            if not isinstance(item, dict):
                continue
            item_index = _creation_stage_index(item.get("id"))
            if not (0 <= item_index < len(specs)):
                item_index = position if position < len(specs) else -1
            if item_index >= 0:
                stage_by_index[item_index] = deepcopy(item)

        existing_stage = stage_by_index.get(stage_index)
        if not _stage_has_meaningful_content(existing_stage):
            raise ValueError(
                f"第{stage_index + 1}阶段正文尚未保存，不能单独补齐伏笔定位；请先生成该阶段。"
            )

        bible_result = self.step_results.get("bible", {})
        bible_foreshadows = (
            bible_result.get("foreshadows", [])
            if isinstance(bible_result, dict) else []
        )
        total_chapters = _creation_total_chapters(
            self.target_words_spin.value(),
            self.average_words_spin.value(),
        )
        missing_before = [
            item for item in _stage_foreshadow_shortfalls(
                bible_foreshadows,
                current.get("foreshadow_schedule", []),
                specs,
                total_chapters,
            )
            if isinstance(item, dict) and item.get("stage_index") == stage_index
        ]
        if not missing_before:
            # The response may have arrived after another state refresh already
            # completed the endpoint.  Do not issue a second repair merge.
            self._sync_stage_generation_state(current)
            self.step_results["stage_plan"] = current
            return

        incoming_schedule = (
            result.get("foreshadow_schedule", [])
            if isinstance(result, dict) else []
        )
        if not isinstance(incoming_schedule, list) or not incoming_schedule:
            raise ValueError("伏笔定位补充请求没有返回有效端点，本次未保存。")

        # Resolve the compact i/k/e/d response against the already saved
        # events.  _derive_stage_endpoint_rows also adds the stable endpoint
        # marker to the matching event reference when the model omitted it.
        stage_copy = deepcopy(existing_stage)
        derived_rows = _derive_stage_endpoint_rows(
            {
                "stage_plan": [stage_copy],
                "foreshadow_schedule": incoming_schedule,
            },
            stage_index,
            specs,
            bible_foreshadows,
            total_chapters,
        )
        if not derived_rows:
            raise ValueError("伏笔定位补充请求没有找到可关联的现有事件，本次未保存。")

        combined_schedule = []
        combined_schedule.extend(
            current.get("foreshadow_schedule", [])
            if isinstance(current.get("foreshadow_schedule", []), list) else []
        )
        combined_schedule.extend(derived_rows)
        canonical_schedule, schedule_notes, schedule_errors = _canonicalize_foreshadow_schedule(
            bible_foreshadows,
            combined_schedule,
            specs,
            total_chapters,
            strict=True,
        )
        if schedule_errors:
            raise ValueError(
                "伏笔定位补充结果与第二步阶段位置不一致："
                + "；".join(schedule_errors[:6])
                + "。本次未保存。"
            )

        # Check the result before mutating the saved state.  A partial repair
        # must be retried as a repair request, never accepted as a complete
        # stage and never used to trigger a full-stage regeneration.
        repaired_missing = [
            item for item in _stage_foreshadow_shortfalls(
                bible_foreshadows,
                canonical_schedule,
                specs,
                total_chapters,
            )
            if isinstance(item, dict) and item.get("stage_index") == stage_index
        ]
        if repaired_missing:
            labels = "、".join(
                f"{item.get('code') or item.get('name') or '未命名伏笔'}"
                f"/{'埋设' if item.get('kind') == 'setup' else '回收'}"
                for item in repaired_missing
            )
            raise ValueError(
                f"第{stage_index + 1}阶段伏笔定位仍不完整（{labels}），本次未保存阶段内容；请重新补齐。"
            )

        stage_by_index[stage_index] = stage_copy
        current["stage_plan"] = [
            stage_by_index[index]
            for index in sorted(stage_by_index)
            if 0 <= index < len(specs)
        ]
        current["foreshadow_schedule"] = canonical_schedule
        current["foreshadow_endpoint_warnings"] = [
            item for item in current.get("foreshadow_endpoint_warnings", [])
            if not (
                isinstance(item, dict)
                and item.get("stage_index") == stage_index
            )
        ]
        for note in schedule_notes:
            current["chapter_plan_note"] = _append_note(
                _clean_chapter_plan_note(current.get("chapter_plan_note", "")),
                note,
            )
        self._sync_stage_generation_state(current)
        self.step_results["stage_plan"] = current

    def _set_running(self, running):
        running = bool(running)
        self.premise_generate_btn.setEnabled(not running)
        self.premise_clear_btn.setEnabled(not running)
        for button in getattr(self, "json_generate_buttons", {}).values():
            button.setEnabled(not running)
        for button in getattr(self, "json_clear_buttons", {}).values():
            button.setEnabled(not running)
        for button in self.choice_widgets:
            button.setEnabled(not running)
        self.inspiration_edit.setEnabled(not running)
        self.back_btn.setEnabled(not running and self.current_step_index > 0)
        self.next_btn.setEnabled(not running and self._current_step_ready())
        self.cancel_btn.setEnabled(not running)
        if running:
            self._set_status_text(self._active_generation_status())

    def _active_generation_status(self):
        """Return the visible label for the exact wizard batch in progress."""
        step = CREATION_WIZARD_STEPS[self.current_step_index][0]
        if step == "premise":
            return "正在生成：5个故事方向"
        if self._active_batch_kind == "bible_core":
            return "正在生成：小说圣经、世界规则"
        if self._active_batch_kind == "bible_assets":
            return "正在生成：人物、设定、伏笔"
        if self._active_batch_kind == "stage_plan_stage":
            total_stages = len(self._stage_specs())
            return f"正在生成：第{self._active_stage_index + 1}阶段（共{total_stages}个阶段）"
        if self._active_batch_kind == "stage_endpoint_repair":
            return f"正在补齐：第{self._active_stage_index + 1}阶段伏笔定位"
        if self._active_batch_kind == "stage_skeleton":
            return "正在生成：全书阶段骨架"
        return "AI 正在生成当前步骤，请稍候……"

    def _schedule_generation_retry(self, error, batch_kind="", stage_index=-1):
        """Retry a failed post-response validation without saving bad content."""
        retry_number = int(self._generation_retry_count or 0) + 1
        detail = str(error or "返回内容未通过当前步骤校验。").strip()
        if retry_number <= 3:
            self._generation_retry_count = retry_number
            self._pending_batch_kind = batch_kind or self._active_batch_kind
            self._pending_stage_index = (
                stage_index if stage_index is not None and stage_index >= 0
                else self._active_stage_index
            )
            self._pending_retry_delay_ms = retry_number * 10 * 1000
            self._retrying_same_request = True
            self._generation_failed = False
            self._last_worker_error = (
                f"本次生成失败：{detail}；{retry_number * 10}秒后自动重试 "
                f"{retry_number}/3。"
            )
            self._set_status_text(self._last_worker_error)
            self._set_running(False)
            return True

        self._generation_failed = True
        self._pending_batch_kind = ""
        self._pending_stage_index = -1
        self._pending_retry_delay_ms = 0
        self._retrying_same_request = False
        self._last_worker_error = (
            f"生成失败：{detail}；已自动重试3次，请点击 AI 生成重试。"
        )
        self._set_status_text(self._last_worker_error)
        self._set_running(False)
        return False

    def _on_ai_result(self, result):
        step = CREATION_WIZARD_STEPS[self.current_step_index][0]
        batch_kind = self._active_batch_kind
        stage_index = self._active_stage_index
        try:
            if batch_kind in {"stage_plan_stage", "stage_endpoint_repair"}:
                partial_payload = deepcopy(result) if isinstance(result, dict) else {}
                partial_payload["_generation_state"] = {"status": "partial"}
                result = self._normalize_step_result(step, partial_payload)
            else:
                result = self._normalize_step_result(step, result)
        except Exception as exc:
            self._schedule_generation_retry(str(exc), batch_kind, stage_index)
            return
        if step == "premise":
            author_input = self._context_for_step("premise").get("author_input", {})
            _bind_requested_title(
                result,
                author_input.get("requested_title", "")
                if isinstance(author_input, dict) else "",
            )
            candidates = [
                deepcopy(item)
                for item in result.get("candidates", [])
                if isinstance(item, dict)
            ]
            protocol_error = _as_text(result.get("_candidate_protocol_error"))
            if protocol_error or len(candidates) != 5:
                detail = protocol_error or f"这次返回了 {len(candidates)} 个方向，应为 5 个"
                if self.premise_candidates:
                    self._set_status_text(
                        f"这次故事方向的返回结构不完整（{detail}），暂不替换上一组结果，请重新生成。"
                    )
                else:
                    self._show_empty_candidate_list("这次没有收到符合五个固定方向的结果，请重新生成")
                    self._set_status_text(
                        f"这次故事方向的返回结构不完整（{detail}），请重新生成。"
                    )
                self._schedule_generation_retry(detail, batch_kind, stage_index)
                return
            self._invalidate_steps_from("bible")
            self.step_results[step] = deepcopy(result)
            self.premise_candidates = candidates
            self.step_results[step]["candidates"] = deepcopy(self.premise_candidates)
            self.premise_selected_index = max(
                0,
                min(
                    int(result.get("selected_index", 0) or 0),
                    len(self.premise_candidates) - 1,
                ),
            )
            self.step_results[step]["selected_index"] = self.premise_selected_index
            self._populate_candidate_list()
            remember_creation_wizard_names(
                [
                    _creation_premise_name(item.get("protagonist"))
                    for item in self.premise_candidates
                    if isinstance(item, dict)
                ],
                source="premise",
            )
            self._set_status_text(f"已生成 {len(self.premise_candidates)} 份故事方向，请选择一份。")
        else:
            try:
                if step == "bible":
                    self._merge_bible_batch(result, batch_kind)
                elif step == "stage_plan":
                    if batch_kind == "stage_skeleton":
                        self._merge_stage_skeleton(result)
                    elif batch_kind == "stage_endpoint_repair":
                        self._merge_stage_endpoint_repair(result, stage_index)
                    else:
                        self._merge_stage_batch(result, stage_index)
                if step == "bible" and batch_kind == "bible_assets":
                    remember_creation_wizard_names(
                        _creation_character_names(result.get("characters", [])),
                        source="bible",
                    )
            except Exception as exc:
                self._schedule_generation_retry(str(exc), batch_kind, stage_index)
                return
            merged = deepcopy(self.step_results.get(step, {}))
            self._set_preview_result(step, merged)

            state = self._generation_state(step)
            if state.get("status") == "partial":
                if step == "bible":
                    next_label = "第二批：人物、设定、伏笔"
                    self._pending_batch_kind = "bible_assets"
                    self._pending_stage_index = -1
                else:
                    next_batch, next_index = self._next_generation_batch(step)
                    self._pending_batch_kind = next_batch
                    self._pending_stage_index = next_index
                    if next_batch == "stage_endpoint_repair":
                        next_label = f"补齐第{next_index + 1}阶段的伏笔定位"
                    elif next_batch == "stage_plan_stage":
                        next_label = (
                            f"第{next_index + 1}阶段"
                            if batch_kind != "stage_skeleton"
                            else "第1阶段"
                        )
                    else:
                        next_label = "未完成的阶段"
                self._set_status_text(f"已保存当前批次，接下来生成{next_label}。")
            else:
                shortfalls = (
                    _creation_scale_shortfalls(merged, self.target_words_spin.value())
                    if step == "bible" else []
                )
                if shortfalls:
                    self._set_status_text(
                        "已生成；资料数量低于建议参考值："
                        + "、".join(shortfalls)
                        + "；可以直接确认，也可以重新生成故事底盘。"
                    )
                else:
                    self._set_status_text("已生成当前步骤，可以直接确认进入下一步。")
        self._save_draft()
        self._set_running(False)

    def _on_ai_failed(self, error):
        raw_error = str(error or "生成失败。")
        raw_error_lower = raw_error.lower()
        if "流式响应在结果完成前中断" in raw_error:
            message = (
                raw_error
                + "\n这表示模型还没有返回完整结果，程序没有把这次不完整响应写入当前批次；"
                "已经完成的前一批或前一阶段仍然保留。"
            )
        elif "gateway request timed out" in raw_error_lower:
            message = (
                "上游网关等待模型输出超时（gateway request timed out）。\n"
                "这不是小说内容检查失败，而是本次连接在结果完成前被网关关闭；"
                "重新生成会重新发起完整请求。"
            )
        else:
            message = raw_error
        self._last_worker_error = (
            f"生成失败：{message}\n已自动重试3次，请点击 AI 生成重试。"
        )
        self._generation_failed = True
        self._pending_batch_kind = ""
        self._pending_stage_index = -1
        self._pending_retry_delay_ms = 0
        self._retrying_same_request = False
        self._generation_retry_count = 0
        state = self._generation_state(CREATION_WIZARD_STEPS[self.current_step_index][0])
        if state.get("status") == "partial":
            continuation = "已完成的批次已经保存，下次点击生成会从未完成批次继续。"
            message += "\n" + continuation
            self._last_worker_error += "；已完成批次已保存，下次生成会继续未完成批次"
        self._set_status_text(self._last_worker_error)
        self._save_draft()
        self._set_running(False)

    def _cleanup_worker(self):
        worker = self.worker
        self.worker = None
        if worker is not None:
            worker.deleteLater()
        self._set_running(False)
        self._refresh_step_ui()
        pending = bool(self._pending_batch_kind) and not self._generation_failed
        pending_delay_ms = max(0, int(self._pending_retry_delay_ms or 0))
        self._pending_batch_kind = ""
        self._pending_stage_index = -1
        self._pending_retry_delay_ms = 0
        if pending:
            QTimer.singleShot(pending_delay_ms, self._generate_current)
            return
        if self._last_worker_error:
            self._set_status_text(self._last_worker_error)

    def _read_current_step(self):
        step = CREATION_WIZARD_STEPS[self.current_step_index][0]
        if step == "premise":
            if not self.premise_candidates:
                raise ValueError("请先生成至少一份故事方向。")
            candidate = self._current_premise()
            candidate["genre"] = self._selected_choice("genre")
            candidate["theme"] = self._selected_choice("theme")
            candidate["style"] = candidate.get("style") or self._selected_choice("style")
            candidate["audience"] = candidate.get("audience") or self._selected_choice("audience")
            candidate["protagonist_route"] = (
                candidate.get("protagonist_route")
                or self._selected_choice("protagonist_route")
            )
            candidate["story_engine"] = (
                candidate.get("story_engine")
                or self._selected_choice("style")
            )
            if not candidate.get("title") or not candidate.get("synopsis"):
                raise ValueError("书名和完整简介不能为空。")
            self.premise_candidates[self.premise_selected_index] = deepcopy(candidate)
            self.step_results[step] = {
                "candidates": deepcopy(self.premise_candidates),
                "selected_index": self.premise_selected_index,
                "selected": candidate,
            }
            return
        if step not in self.step_results:
            raise ValueError("请先点击 AI 生成当前步骤。")
        generation_state = self._generation_state(step)
        if _as_text(generation_state.get("status")).lower() == "partial":
            if step == "bible":
                raise ValueError("故事底盘还在生成中，请先点击 AI 生成完成第二批人物、设定和伏笔。")
            raise ValueError("阶段规划还在生成中，请先点击 AI 生成完成剩余阶段。")
        normalized = self._normalize_step_result(step, self.step_results.get(step, {}))
        if step == "bible":
            bible_error = self._bible_validation_error(normalized)
            if bible_error:
                raise ValueError(bible_error)
        elif step == "stage_plan" and not normalized.get(step):
            raise ValueError("当前步骤至少需要一条内容。")
        if step == "stage_plan":
            normalized["stage_plan"] = normalize_stage_plan_ranges(
                normalized.get("stage_plan", []),
                self.target_words_spin.value(),
                self.average_words_spin.value(),
            )
            total_chapters = _creation_total_chapters(
                self.target_words_spin.value(),
                self.average_words_spin.value(),
            )
            bible_result = self.step_results.get("bible", {})
            bible_foreshadows = (
                bible_result.get("foreshadows", [])
                if isinstance(bible_result, dict) else []
            )
            canonical_schedule, _schedule_notes, _schedule_errors = _canonicalize_foreshadow_schedule(
                bible_foreshadows,
                normalized.get("foreshadow_schedule", []),
                self._stage_specs(),
                total_chapters,
                strict=True,
            )
            if _schedule_errors:
                raise ValueError(
                    "阶段规划中的伏笔章位与第二步底盘不一致："
                    + "；".join(_schedule_errors[:6])
                    + "。请重新生成对应阶段。"
                )
            normalized["foreshadow_schedule"] = canonical_schedule
            if len(normalized.get("stage_plan", [])) < len(self._stage_specs()):
                raise ValueError("阶段规划尚未覆盖全部十万字阶段，请继续生成。")
            missing_schedule = _stage_foreshadow_shortfalls(
                bible_foreshadows,
                normalized.get("foreshadow_schedule", []),
                self._stage_specs(),
                total_chapters,
            )
            if missing_schedule:
                missing_labels = [
                    f"{item.get('code') or item.get('name') or '未命名伏笔'}"
                    f"（第{int(item.get('stage_index', 0)) + 1}阶段{('埋设' if item.get('kind') == 'setup' else '回收')}）"
                    for item in missing_schedule
                ]
                raise ValueError(
                    "阶段规划没有为全部伏笔确定具体章位："
                    + "、".join(missing_labels[:12])
                    + "。请重新生成阶段规划。"
                )
        self.step_results[step] = normalized

    def _go_back(self):
        if self.worker is not None or self.current_step_index <= 0:
            return
        self.current_step_index -= 1
        self._save_draft()
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
            self._save_draft()
            self._refresh_step_ui()
            return
        self._save_draft()
        self.accept()

    def result_payload(self):
        self._save_current_candidate()
        premise_result = self.step_results.get("premise", {})
        selected = (
            deepcopy(premise_result.get("selected", {}))
            if isinstance(premise_result, dict)
            else {}
        )
        if not isinstance(selected, dict):
            selected = {}
        if not selected.get("title") or not selected.get("synopsis"):
            candidates = (
                premise_result.get("candidates", [])
                if isinstance(premise_result, dict)
                else []
            )
            if not isinstance(candidates, list) or not candidates:
                candidates = self.premise_candidates
            if isinstance(candidates, list) and candidates:
                index = max(0, min(self.premise_selected_index, len(candidates) - 1))
                candidate = candidates[index]
                if isinstance(candidate, dict):
                    selected = deepcopy(candidate)
        if selected:
            selected["genre"] = self._selected_choice("genre")
            selected["theme"] = self._selected_choice("theme")
            selected["style"] = selected.get("style") or self._selected_choice("style")
            selected["audience"] = selected.get("audience") or self._selected_choice("audience")
            selected["protagonist_route"] = (
                selected.get("protagonist_route")
                or self._selected_choice("protagonist_route")
            )
            selected["protagonist_style"] = self._selected_choice_display("protagonist_style")
            custom_protagonist_style = self._selected_custom_protagonist_style()
            if custom_protagonist_style:
                selected["custom_protagonist_style"] = custom_protagonist_style
            else:
                selected.pop("custom_protagonist_style", None)
            selected["story_engine"] = (
                selected.get("story_engine")
                or self._selected_choice("style")
            )
        bible_result = self.step_results.get("bible", {})
        assets_result = deepcopy(bible_result) if isinstance(bible_result, dict) else {}
        # 兼容仍停留在旧版本向导草稿中的独立 story_assets。
        legacy_assets = self.step_results.get("story_assets", {})
        if isinstance(legacy_assets, dict):
            for key in ("characters", "lore", "foreshadows"):
                if not assets_result.get(key) and legacy_assets.get(key):
                    assets_result[key] = deepcopy(legacy_assets[key])
        stage_result = deepcopy(self.step_results.get("stage_plan", {}))
        if isinstance(stage_result, dict):
            stage_result["stage_plan"] = normalize_stage_plan_ranges(
                stage_result.get("stage_plan", []),
                self.target_words_spin.value(),
                self.average_words_spin.value(),
            )
            self._canonicalize_stage_schedule(stage_result, strict=True)
        total_chapters = _creation_total_chapters(
            self.target_words_spin.value(),
            self.average_words_spin.value(),
        )
        foreshadow_schedule = (
            _normalize_foreshadow_schedule(
                stage_result.get("foreshadow_schedule", []),
                total_chapters,
            ) if isinstance(stage_result, dict) else []
        )
        bible_result = deepcopy(bible_result) if isinstance(bible_result, dict) else {}
        bible_result["foreshadows"] = _apply_foreshadow_schedule(
            bible_result.get("foreshadows", []),
            foreshadow_schedule,
            total_chapters,
        )
        for foreshadow in bible_result.get("foreshadows", []):
            if isinstance(foreshadow, dict):
                foreshadow.pop("setup_stage", None)
                foreshadow.pop("payoff_stage", None)
        assets_result["foreshadows"] = deepcopy(bible_result.get("foreshadows", []))
        framework = {
            "schema_version": 2,
            "source": "creation_wizard",
            "premise": deepcopy(selected),
            "premise_candidates": deepcopy(premise_result.get("candidates", [])),
            "bible": deepcopy(bible_result.get("bible", {})),
            "world_rules": deepcopy(bible_result.get("world_rules", {})),
            "characters": deepcopy(assets_result.get("characters", [])),
            "lore": deepcopy(assets_result.get("lore", [])),
            "foreshadows": deepcopy(assets_result.get("foreshadows", [])),
            "stage_skeleton": deepcopy(stage_result.get("stage_skeleton", [])),
            "stage_plan": deepcopy(stage_result.get("stage_plan", [])),
            "foreshadow_schedule": deepcopy(foreshadow_schedule),
            "planning_schema_version": _as_text(
                stage_result.get("planning_schema_version", "2")
            ) or "2",
            "book_contract": _normalize_stage_book_contract(
                stage_result.get("book_contract", {})
            ),
            "chapter_plan_note": _clean_chapter_plan_note(
                stage_result.get("chapter_plan_note", "")
            ),
            "total_words": self.target_words_spin.value(),
            "average_chapter_words": self.average_words_spin.value(),
            "completed_at": now_str(),
        }
        # Store one canonical project-level mainline.  The fixed premise/Bible
        # field names remain readable for old drafts, but downstream planning no
        # longer has to choose between several competing line fields.
        framework["core_motive"] = _as_text(
            build_chapter_plan_foundation(framework).get("core_motive", "")
        )
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

    def reject(self):
        if self.worker is None:
            self._save_draft()
        super().reject()

    def closeEvent(self, event):
        if self.worker is not None:
            self._save_draft()
            self._generation_failed = True
            self._pending_batch_kind = ""
            self._pending_stage_index = -1
            try:
                self.worker.stop()
                self.worker.wait(2000)
            except Exception:
                pass
            event.ignore()
            self.worker = None
            self._set_running(False)
            return
        self._save_draft()
        super().closeEvent(event)


class NovelCreationWorkspaceDialog(QDialog):
    """管理向导项目及其完成后的可查看记录。"""

    new_draft_requested = Signal()
    draft_open_requested = Signal(str)

    def __init__(self, open_draft_ids=None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("新建小说：向导项目")
        _fit_dialog_to_screen(
            self,
            width_ratio=0.52,
            height_ratio=0.62,
            minimum_width=520,
            minimum_height=420,
            maximum_width=820,
            maximum_height=760,
        )
        self._open_draft_ids = open_draft_ids if callable(open_draft_ids) else (lambda: set())
        self._build_workspace_ui()
        self.refresh()

    def _build_workspace_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(10)

        title = QLabel("向导项目")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        root.addWidget(title)

        hint = QLabel("向导内容会按项目独立保存；导入完成后仍保留原始灵感和三步资料，并在列表中标记为已完成。")
        hint.setObjectName("hint")
        hint.setWordWrap(True)
        root.addWidget(hint)

        self.draft_list = QListWidget()
        self.draft_list.setSelectionMode(QAbstractItemView.SingleSelection)
        self.draft_list.itemDoubleClicked.connect(self._open_selected)
        root.addWidget(self.draft_list, 1)

        actions = QHBoxLayout()
        self.new_btn = QPushButton("新建项目")
        self.open_btn = QPushButton("打开选中")
        self.delete_btn = QPushButton("删除记录")
        self.refresh_btn = QPushButton("刷新")
        self.new_btn.clicked.connect(self.new_draft_requested)
        self.open_btn.clicked.connect(self._open_selected)
        self.delete_btn.clicked.connect(self._delete_selected)
        self.refresh_btn.clicked.connect(self.refresh)
        actions.addWidget(self.new_btn)
        actions.addWidget(self.open_btn)
        actions.addWidget(self.delete_btn)
        actions.addStretch(1)
        actions.addWidget(self.refresh_btn)
        root.addLayout(actions)

    def _selected_draft_id(self):
        item = self.draft_list.currentItem()
        return _as_text(item.data(Qt.UserRole)) if item is not None else ""

    def _open_selected(self, *_args):
        draft_id = self._selected_draft_id()
        if draft_id:
            self.draft_open_requested.emit(draft_id)

    def _delete_selected(self):
        draft_id = self._selected_draft_id()
        if not draft_id:
            return
        if draft_id in set(self._open_draft_ids() or set()):
            QMessageBox.information(self, "无法删除", "这个项目正在打开，请先关闭它的向导窗口。")
            return
        item = self.draft_list.currentItem()
        title = item.text().splitlines()[0] if item is not None else "这个项目"
        answer = QMessageBox.question(
            self,
            "删除向导记录",
            f"确定删除“{title}”吗？\n删除后不能恢复。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        delete_creation_wizard_draft(draft_id)
        self.refresh()

    def refresh(self, *_args):
        selected_id = self._selected_draft_id()
        self.draft_list.blockSignals(True)
        try:
            self.draft_list.clear()
            records = list_creation_wizard_drafts()
            selected_row = -1
            for row, record in enumerate(records):
                title = _as_text(record.get("title")) or "未命名项目"
                status_label = _as_text(record.get("status_label")) or "进行中"
                step = _as_text(record.get("step")) or "故事定位"
                created_at = _as_text(record.get("created_at")) or "创建时间未知"
                item = QListWidgetItem(
                    f"{title}\n{status_label} · {step} · 创建于 {created_at}"
                )
                item.setData(Qt.UserRole, _as_text(record.get("draft_id")))
                if _as_text(record.get("completion_status")) == "completed":
                    item.setForeground(QColor("#4CAF50"))
                imported_path = _as_text(record.get("imported_project_path"))
                imported_line = f"\n导入项目：{imported_path}" if imported_path else ""
                item.setToolTip(
                    f"创建时间：{created_at}\n最近保存：{_as_text(record.get('updated_at'))}"
                    f"{imported_line}"
                )
                self.draft_list.addItem(item)
                if _as_text(record.get("draft_id")) == selected_id:
                    selected_row = row
            if selected_row >= 0:
                self.draft_list.setCurrentRow(selected_row)
            elif self.draft_list.count():
                self.draft_list.setCurrentRow(0)
            has_items = self.draft_list.count() > 0
            self.open_btn.setEnabled(has_items)
            self.delete_btn.setEnabled(has_items)
        finally:
            self.draft_list.blockSignals(False)
