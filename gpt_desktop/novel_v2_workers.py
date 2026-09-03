import json
import re

from PySide6.QtCore import Signal

from .workers import NovelAnalysisWorker, NovelChapterPlanWorker, NovelWritingWorker


V2_AUDIT_CHECK_KEYS = (
    "pov_and_viewpoint",
    "causality",
    "character_consistency",
    "continuity",
    "prose_and_dialogue",
    "ending_drive",
)


def validate_v2_audit_result(data):
    if not isinstance(data, dict):
        raise ValueError("正文审校没有返回JSON对象。")
    decision = str(data.get("decision", "") or "").strip().lower()
    if decision not in {"pass", "repair", "replan"}:
        raise ValueError("正文审校缺少有效 decision。")
    checks = data.get("checks", {})
    if not isinstance(checks, dict):
        raise ValueError("正文审校缺少必填 checks。")
    missing = []
    failed = []
    for key in V2_AUDIT_CHECK_KEYS:
        item = checks.get(key, {})
        status = str(item.get("status", "") or "").strip().lower() if isinstance(item, dict) else ""
        if status not in {"pass", "fail"}:
            missing.append(key)
        elif status == "fail":
            failed.append(key)
    if missing:
        raise ValueError("正文审校未完成必填检查：" + "、".join(missing))
    if decision == "pass" and failed:
        raise ValueError("正文审校结论与失败检查矛盾：" + "、".join(failed))
    return decision


def validate_v2_pov_audit_result(data):
    if not isinstance(data, dict):
        raise ValueError("叙事人称专项审校没有返回JSON对象。")
    decision = str(data.get("decision", "") or "").strip().lower()
    if decision not in {"pass", "repair"}:
        raise ValueError("叙事人称专项审校缺少有效 decision。")
    if not str(data.get("expected_pov", "") or "").strip():
        raise ValueError("叙事人称专项审校缺少 expected_pov。")
    if str(data.get("observed_narration", "") or "").strip().lower() not in {"first", "third", "mixed", "unclear"}:
        raise ValueError("叙事人称专项审校缺少有效 observed_narration。")
    evidence = data.get("evidence", [])
    if not isinstance(evidence, list) or not any(str(item or "").strip() for item in evidence):
        raise ValueError("叙事人称专项审校缺少正文证据。")
    if decision == "repair" and not str(data.get("repair_instruction", "") or "").strip():
        raise ValueError("叙事人称专项审校要求修订但没有修订指令。")
    return decision


class NovelV2WritingWorker(NovelWritingWorker):
    def _v2_word_target(self):
        match = re.search(r"本次正文目标：\s*(\d{1,7})\s*字", self.context)
        if not match:
            match = re.search(r"本次新增正文(?:参考)?目标：\s*约?\s*(\d{1,7})\s*字", self.context)
        if not match:
            match = re.search(r"本章扩写字数：\s*(\d{2,7})\s*字", self.context)
        return int(match.group(1)) if match else 0

    def _max_tokens_for_request(self):
        if self.action in {"draft", "length_repair"}:
            target = self._v2_word_target()
            if target:
                return max(1400, min(15000, int(target * 1.2)))
        if self.action == "length_repair_segment":
            return 2200
        return {
            "execution_outline": 1600,
            "outline_repair": 1600,
            "audit": 5000,
            "postwrite": 9000,
            "completion_audit": 7000,
        }.get(self.action, super()._max_tokens_for_request())

    def _initial_progress_text(self):
        return {
            "execution_outline": "正在生成当前章执行提纲...",
            "outline_repair": "正在压缩当前章执行提纲...",
            "audit": "正在审校正文质量...",
            "targeted_repair": "正在按审校意见定向修订正文...",
            "length_repair": "正在按篇幅预算压缩正文...",
            "postwrite": "正在提炼实写提纲并更新项目状态...",
            "completion_audit": "正在执行全书完结审计...",
        }.get(self.action, super()._initial_progress_text())

    @staticmethod
    def prompt_for_action(action):
        prompts = {
            "execution_outline": (
                "你是长篇小说的章节执行编辑。请基于给定的章节任务、最新状态、近期实写记忆和伏笔债务，"
                "为当前章生成可直接指导正文写作的执行提纲。\n"
                "要求：正文质量优先；安排5至6个连续场景拍点，写清每个场景的角色动机、阻力、信息变化、"
                "情绪变化、因果承接和出场/退场状态；明确本章核心冲突、关键转折和结尾推动。"
                "正文总目标约为800至1200字，绝对不得超过1500字；每个拍点只写执行所需的增量信息，"
                "资料很丰富时应取舍和合并，不得通过增加小标题、备选方案或逐项复述来扩张篇幅。"
                "只能使用资料中已有的事实和设定；开放伏笔不是硬任务，只有在不破坏人物动机和本章主线时才安排。"
                "不要写对白成稿，不要写正文，不要解释你的工作方法。只输出执行提纲。"
            ),
            "outline_repair": (
                "你是长篇小说章节提纲编辑。请压缩资料中的现有执行提纲，保留5至6个连续场景拍点、"
                "角色动机、阻力、信息变化、因果承接、关键转折和结尾推动；合并重复说明、备选方案和过细操作。"
                "压缩后以900至1400字为目标，绝对不得超过1500字。"
                "只能压缩和重组现有执行提纲，不得改变章节任务、增加情节或输出正文。只输出压缩后的执行提纲。"
            ),
            "draft": (
                "你是成熟的商业长篇小说作者。请严格依据当前章节任务和执行提纲写出完整正文。\n"
                "正文质量优先于字数：因果必须清楚，人物行动必须有具体动机，冲突要通过行动、选择、对话和细节推进。"
                "项目指定的叙事人称和视角边界是硬约束，必须从第一句到最后一句保持一致；"
                "第三人称正文不得把叙述写成第一人称，第一人称只能出现在角色对白、引文或文本内材料中。"
                "同时保持项目文风，继承上一章结尾的时间、地点、人物位置、伤势、物品和未完成动作。"
                "不要复述项目资料，不要用大段说明替代场景，不要让角色互相解释双方都知道的信息。"
                "执行提纲用于控制方向，但语言必须自然，不能写成逐条扩写。"
                "先依据当前项目的定位呈现题材类型与读者阅读感；再依据文风档案进行仿写，优先复刻其中的习惯用词、口语、句式松紧、"
                "对白接法、叙述节奏和情绪落点。项目资料负责故事定位、人物事实和剧情方向，样本文风负责表达层的落笔方式。"
                "情绪和判断可以从视线、表情、呼吸/声音、姿态、手部动作、位移、道具互动、环境或他人反应中选择贴合现场的表现。"
                "例如‘他意识到危险’，可以写成‘眼神停了一下，身体向后撤，右手扣紧桌沿’，再让动作带出对白、选择或结果。"
                "以资料中的本章扩写字数或本段参考目标为本次篇幅预算，优先写到目标的90%至110%，"
                "不得超过目标的120%；接近上限时应压缩次要描写和重复反应，在预算内完整收束当前任务，"
                "不得再增加非必要场景。"
                "如果用户资料中存在【长章节分段任务】，只输出指定的下一段正文，并从已有正文末尾自然续写；"
                "不要重复已有正文，不要提前压缩后续场景，只有最后一段负责完成本章结尾。"
                "伏笔动作只有真正出现在正文中才算完成；不要为了处理伏笔牺牲本章冲突。"
                "只输出正文，不输出标题、提纲、分析、评分或创作说明。"
            ),
            "audit": (
                "你是独立的长篇小说责任编辑。请审校当前章完整正文，不要改写正文。"
                "以正文质量为第一标准，同时检查章节任务完成度、因果链、人物一致性、时间地点连续性、"
                "叙事人称与视角边界、冲突有效性、节奏、重复、说明性写法、对白潜台词、结尾推动和伏笔是否真实落地。"
                "叙事人称是硬约束：必须对照项目指定人称检查非对白叙述；第三人称正文写成第一人称属于major问题。\n"
                "限知视角直接断言当前视角人物无法确认的他人内心、记忆或未表达判断，同样属于major问题，必须repair；"
                "不能因为只有一两处就降为minor。\n"
                "必须只输出一个合法JSON对象，不要Markdown，不要额外文字。结构如下："
                '{"decision":"pass|repair|replan","overall":"一句话结论","issues":['
                '{"severity":"critical|major|minor","category":"类型","evidence":"正文证据或位置",'
                '"instruction":"可直接执行的修改要求"}],'
                '"checks":{"pov_and_viewpoint":{"status":"pass|fail","evidence":"人称和视角证据"},'
                '"causality":{"status":"pass|fail","evidence":"因果证据"},'
                '"character_consistency":{"status":"pass|fail","evidence":"人物证据"},'
                '"continuity":{"status":"pass|fail","evidence":"时间地点状态证据"},'
                '"prose_and_dialogue":{"status":"pass|fail","evidence":"叙事与对白证据"},'
                '"ending_drive":{"status":"pass|fail","evidence":"结尾推动证据"}},'
                '"repair_instruction":"合并后的定向修订要求"}。'
                "六项checks必须逐项填写；任一项为fail时decision不得为pass，并须在issues中给出对应证据和修订要求。"
                "只有影响可读性、因果、人物或章节任务的真实问题才要求repair；轻微偏好不能触发重写。"
                "核心设定或章节方向根本矛盾时才用replan。"
            ),
            "pov_audit": (
                "你是叙事人称与视角边界专项审校员。不要评价剧情、文风优劣或篇幅，只完成机械式人称核对。"
                "先读取项目指定叙事人称，再检查完整正文的非对白叙述实际使用第一人称、第三人称还是混合人称。"
                "角色对白、引文、邮件、录音和文内材料中的‘我’不算第一人称叙述；"
                "但叙述者持续用‘我’描述自己的动作、感受和判断，就是第一人称叙述。"
                "项目要求第三人称而正文非对白叙述持续使用第一人称时，decision必须为repair，不能因正文写得好而放行。\n"
                "必须只输出合法JSON对象，不要Markdown或额外文字："
                '{"decision":"pass|repair","expected_pov":"项目要求",'
                '"observed_narration":"first|third|mixed|unclear",'
                '"evidence":["至少两处非对白叙述原文"],'
                '"reason":"对比结论","repair_instruction":"不改变剧情事实的具体人称修订要求"}。'
            ),
            "targeted_repair": (
                "你是长篇小说修订作者。请根据审校意见对当前章做一次定向修订。"
                "保留没有问题的情节、文风和有效表达，只修复审校明确指出的问题；不得擅自增加新主线、新设定或新伏笔。"
                "输出修订后的完整正文，不输出修改说明、标题、提纲或分析。"
            ),
            "length_repair": (
                "你是长篇小说的篇幅编辑。请把当前章完整正文压缩到资料末尾指定的允许字数范围内。"
                "保留本章任务、完整因果链、人物动机、关键行动、有效对白、必要细节、转折和结尾推动；"
                "优先合并重复反应、同义解释、冗长过渡和不改变结果的次要描写。"
                "不得删除造成后续状态变化的事实，不得新增情节、设定或伏笔，不得把场景改写成摘要。"
                "以目标的95%至105%为最佳落点，绝对不得超过允许上限。"
                "只输出压缩后的完整正文，不输出标题、字数、修改说明、提纲或分析。"
            ),
            "length_repair_segment": (
                "你是长篇小说的精简编辑。资料只包含当前章的一段原文，请在不改变事件顺序、因果、人物选择、"
                "证据状态和叙事视角的前提下大幅精简。删除重复解释、同义限制、重复保全动作、往返中没有新增信息的"
                "条款和不改变结果的反应；同一规则只保留一次。不得新增情节、设定、对白或说明。"
                "严格遵守资料末尾的本段字数范围，只输出压缩后的本段正文，不输出标题、字数、分析或修改说明。"
            ),
            "postwrite": (
                "你是长篇小说连续性总编。请只根据最终正文生成写后资料和状态变化；计划提纲只能用于核对任务，"
                "正文没有发生的内容绝不能写入事实、状态或伏笔结果。\n"
                "必须只输出一个合法JSON对象，不要Markdown，不要额外文字。结构如下："
                '{"actual_outline":"按真实场景顺序写成的实写提纲",'
                '"summary":"简短章节摘要","key_facts":["后续必须继承的事实"],'
                '"linked_character_ids":["人物ID"],"linked_lore_ids":["设定ID"],'
                '"state_snapshot":{"story_time":"","location":"","active_conflicts":[],'
                '"character_states":[],"relationship_states":[],"unresolved_tasks":[],"notes":""},'
                '"state_delta":{"characters":[],"relationships":[],"lore":[],"plot_tasks":[]},'
                '"foreshadow_updates":[{"id":"现有伏笔ID或空","operation":"create|reinforce|partial_payoff|payoff|discard|none",'
                '"name":"","canonical_summary":"","status":"未埋|已埋|已回收|无需回收|废弃",'
                '"priority":"必须处理|高|常规|低|休眠","horizon":"下一窗口|当前阶段|后期|开放结局",'
                '"evidence":"正文中的直接证据"}],'
                '"record_updates":{"characters":[{"operation":"create|update|none","id":"已有人物ID或空",'
                '"name":"新增人物姓名；临时人物升级时填写正文明确的正式姓名",'
                '"fields":{"role":"","goal":"","secret":"","voice":"","notes":""},'
                '"evidence":"正文证据"}],"lore":[{"operation":"create|update|none","id":"已有设定ID或空",'
                '"name":"","fields":{"type":"","description":""},"evidence":"正文证据"}]}}。'
                "只更新正文有明确证据的记录；同一伏笔优先使用已有ID，短期悬念和一次性程序细节不要创建长期伏笔。"
                "如果正文给已有的姓名未明或临时称谓人物补出正式姓名，必须沿用原人物ID并用update填写name，保留原卡和运行态，不能create重复人物。"
                "人物和设定优先更新已有ID；只有后续会持续使用且现有资料确实没有对应记录时才create。"
                "一次性路人、临时物品、气氛细节和本章即可消化的信息只放关键事实，不创建长期记录。"
                "必须逐项检查正文中新出现或发生长期变化的内容，不能只写进state_snapshot、unresolved_tasks或state_delta而漏掉长期档案。"
                "人物卡只为有明确姓名或稳定称谓、后续会再次出场或持续影响关系/主线的具体人物create；无名群体和单章路人不建卡。"
                "设定卡用于后续仍会约束剧情的规则、能力体系、势力、地点、长期持有物或跨章关键物件；"
                "现有设定无对应记录时必须create，不能只放进状态快照。"
                "伏笔用于正文新提出并承诺后续解释、揭晓、验证或回收的身份、真相、秘密、异常、因果链、关键物件去向或未来危险；"
                "现有伏笔无对应记录时必须create，推进或兑现时必须用准确ID更新。"
                "未解真相不能只放unresolved_tasks，跨章关键物件不能只放状态，持续角色不能只放character_states；分类不互斥。"
                "state_snapshot表示章节结束时的完整当前状态；必须继承未变化的现有状态，并明确移除已经结束的冲突或任务。"
                "关键事实必须包含章节结尾的时间、地点、人物位置、伤势、物品归属和未完成动作。"
            ),
            "completion_audit": (
                "你是长篇小说完结总审编辑。请根据全书实写记忆、当前状态和伏笔账本判断小说是否具备完结条件。"
                "计划提纲不算正文事实；记录状态过期时，要结合实写记忆判断是否已经实际回收。"
                "必须区分真正未完成的主线、重复伏笔记录、无需独立回收的程序细节和可以保留的开放结局。\n"
                "必须只输出合法JSON对象，不要Markdown或额外文字。结构如下："
                '{"decision":"ready|not_ready","overall":"结论",'
                '"must_close":[{"id":"伏笔或剧情任务ID","reason":"未完成原因","suggestion":"最小修复方向"}],'
                '"open_endings":[{"id":"ID","reason":"为什么可作为开放结局"}],'
                '"discarded":[{"id":"ID","reason":"为什么无需继续"}],'
                '"stale_records":[{"id":"ID","actual_status":"实际状态","evidence":"实写章节证据"}],'
                '"contradictions":[{"description":"矛盾","evidence":"证据","suggestion":"修复方向"}],'
                '"missing_character_arcs":[{"character_id":"ID","reason":"未兑现之处"}],'
                '"repair_plan":[{"priority":"高|中|低","task":"需要补写或调整的任务"}]}。'
                "只有影响主线承诺、核心人物弧线、关键因果或明确长期伏笔的问题才阻止完结。"
            ),
        }
        return prompts.get(str(action or ""), "")

    def _action_prompt(self):
        prompt = self.prompt_for_action(self.action)
        if prompt:
            return prompt
        return super()._action_prompt()


class NovelV2StructuredWorker(NovelAnalysisWorker):
    chunk = Signal(str)
    result_ready = Signal(str, str)

    def __init__(self, base_url, api_key, model, action, context, proxy_url="", proxy_mode="不使用代理"):
        super().__init__(
            base_url,
            api_key,
            model,
            context,
            proxy_url=proxy_url,
            proxy_mode=proxy_mode,
            max_concurrency=1,
        )
        self.action = str(action or "")

    def _analysis_prompt(self):
        prompt = NovelV2WritingWorker.prompt_for_action(self.action)
        if not prompt:
            raise ValueError(f"不支持的结构化新版小说任务：{self.action}")
        return prompt

    def _chunk_user_text(self, chunk_text, chunk_index, total_chunks):
        return str(chunk_text or "")

    def _allow_retry_chunk_split(self):
        return False

    def run(self):
        try:
            if not self.base_url:
                raise ValueError("请先选择厂商。")
            if not self.api_key:
                raise ValueError("请先设置 API Key。")
            if not self.model:
                raise ValueError("请选择模型。")
            if not self.text.strip():
                raise ValueError("没有可用的任务上下文。")
            self.progress.emit(
                {
                    "audit": "正在审校正文质量...",
                    "postwrite": "正在生成写后结构化资料...",
                    "completion_audit": "正在执行全书完结审计...",
                }.get(self.action, "正在处理结构化小说任务...")
            )
            response_format_supported, _stream_supported = self._analysis_request_capabilities()
            parsed, _response_format = self._analyze_chunk_with_retries(
                self._analysis_prompt(),
                self.text,
                1,
                1,
                response_format_supported,
            )
            if self._stop_requested or self.isInterruptionRequested():
                return
            content = json.dumps(parsed, ensure_ascii=False)
            self.result_ready.emit(self.action, content)
        except Exception as e:
            if not self._stop_requested and not self.isInterruptionRequested():
                self.failed.emit(str(e))
        finally:
            self._close_active_network_handles()


class NovelV2RollingPlanWorker(NovelChapterPlanWorker):
    def __init__(self, *args, detailed_chapter_count=5, **kwargs):
        super().__init__(*args, **kwargs)
        self.detailed_chapter_count = max(1, min(self.chapter_count, int(detailed_chapter_count or 5)))

    def _analysis_prompt(self):
        return (
            "你是长篇小说的滚动规划总编。请根据项目当前真实状态规划后续章节。"
            "必须只输出一个合法JSON对象，不要Markdown、解释、注释或尾随逗号。\n"
            f"本次规划未来{self.chapter_count}章，其中前{self.detailed_chapter_count}章写成可执行的详细章节任务，"
            "其余章节只确定方向、因果和阶段作用，后续会根据真实正文刷新。"
            "不得把计划当成已经发生的事实；必须优先遵守状态快照、实写提纲和关键事实。"
            "伏笔必须使用资料中给出的稳定ID；开放伏笔不是硬任务，不得为了回收而破坏人物动机。"
            "只有名称不同但实际指向同一叙事承诺的记录才能列入伏笔合并；不确定时不要合并。"
            "收束阶段减少新增长期主线和伏笔，优先兑现已有承诺。\n"
            "JSON结构："
            '{"summary":"本窗口总体推进",'
            '"book_plan":{"ending_direction":"结局方向和最终选择",'
            '"major_phases":[{"name":"阶段名","range":"大致篇幅或章节范围","goal":"阶段目标","turning_point":"阶段转折"}],'
            '"character_arcs":[{"character_id":"人物ID","arc":"人物弧线终点"}],'
            '"nonnegotiable_payoffs":[{"id":"伏笔或剧情承诺ID","payoff":"必须兑现内容"}]},'
            '"checkpoint":{"progress":"已完成进展","deviations":"与旧计划偏差","pacing":"节奏判断"},'
            '"foreshadow_maintenance":{"merge_groups":[{"canonical_id":"保留ID","duplicate_ids":["重复ID"],'
            '"canonical_summary":"合并后的简短标准描述","confidence":"high|medium|low","reason":"重复依据"}],'
            '"status_updates":[{"id":"伏笔ID","status":"未埋|已埋|已回收|无需回收|废弃",'
            '"evidence":"实写记忆中的依据","confidence":"high|medium|low"}]},'
            '"chapters":[{"index":1,"title":"不含章号的标题","target_words":"3000",'
            '"detail_level":"detailed|direction","narrative_stage":"强钩子阶段|主线扩展阶段|收束升级阶段",'
            '"chapter_function":"","conflict_intensity":"","setup_ratio":"","character_task":"",'
            '"mainline_task":"","chapter_task":"本章存在的理由、核心冲突、转折和出口",'
            '"outline":"详细章写场景方向；方向章只写因果路线","character_ids":[],"lore_ids":[],'
            '"foreshadow_actions":[{"id":"伏笔ID","action":"setup|reinforce|partial_payoff|payoff|hold",'
            '"reason":"为什么适合本章"}],"ending_hook":"","forbidden":""}]}。'
            f"chapters必须输出{self.chapter_count}项，index从1连续递增。"
        )

    def _normalize_plan(self, data):
        normalized = super()._normalize_plan(data)
        raw_chapters = data.get("chapters", []) if isinstance(data, dict) else []
        raw_chapters = raw_chapters if isinstance(raw_chapters, list) else []
        for index, chapter in enumerate(normalized.get("chapters", [])):
            raw = raw_chapters[index] if index < len(raw_chapters) and isinstance(raw_chapters[index], dict) else {}
            detail_level = str(raw.get("detail_level", "") or "").strip().lower()
            if detail_level not in {"detailed", "direction"}:
                detail_level = "detailed" if index < self.detailed_chapter_count else "direction"
            actions = raw.get("foreshadow_actions", [])
            actions = [item for item in actions if isinstance(item, dict)] if isinstance(actions, list) else []
            foreshadow_ids = []
            for item in actions:
                item_id = str(item.get("id", "") or "").strip()
                if item_id and item_id not in foreshadow_ids:
                    foreshadow_ids.append(item_id)
            chapter.update(
                {
                    "detail_level": detail_level,
                    "chapter_task": str(raw.get("chapter_task", "") or chapter.get("outline", "")).strip(),
                    "character_ids": self._string_list(raw.get("character_ids", [])),
                    "lore_ids": self._string_list(raw.get("lore_ids", [])),
                    "foreshadow_actions": actions,
                    "foreshadows": foreshadow_ids,
                }
            )
        checkpoint = data.get("checkpoint", {}) if isinstance(data, dict) else {}
        normalized["checkpoint"] = checkpoint if isinstance(checkpoint, dict) else {}
        maintenance = data.get("foreshadow_maintenance", {}) if isinstance(data, dict) else {}
        normalized["foreshadow_maintenance"] = maintenance if isinstance(maintenance, dict) else {}
        book_plan = data.get("book_plan", {}) if isinstance(data, dict) else {}
        normalized["book_plan"] = book_plan if isinstance(book_plan, dict) else {}
        normalized["detailed_chapter_count"] = self.detailed_chapter_count
        return normalized
