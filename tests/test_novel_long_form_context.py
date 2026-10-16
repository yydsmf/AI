import json
import unittest
from copy import deepcopy

from gpt_desktop.novel_utils import (
    LONG_FORM_CONTEXT_SAFETY_MARGIN,
    LONG_FORM_CONTEXT_SOFT_LIMIT,
    LONG_FORM_COMPACT_DELTA_VERSION,
    LONG_FORM_MEMORY_FINALIZE_INDEX_LIMIT,
    LONG_FORM_MEMORY_IDENTITY_INDEX_LIMIT,
    LONG_FORM_RECONCILIATION_CONTEXT_LIMIT,
    LONG_FORM_SELECTION_INDEX_LIMIT,
    LONG_FORM_STAGE_REVIEW_SCOPE,
    NOVEL_AI_CONTEXT_LIMIT,
    STYLE_CARD_CACHE_VERSION,
    STYLE_SHEET_CACHE_VERSION,
    _append_ai_style_profile_to_context,
    _apply_character_string_canon,
    _character_identity_fields_from_item,
    _apply_long_form_memory_update,
    _apply_chapter_logic_repair_patches,
    _apply_chapter_prose_repair_patches,
    _build_chapter_ai_context,
    _build_chapter_logic_repair_context,
    _build_long_form_memory_finalize_context,
    _build_long_form_memory_reconcile_context,
    _build_long_form_selection_index,
    _build_long_form_state_directory,
    _build_long_form_memory_repair_context,
    _build_style_finalize_context,
    _format_style_cards,
    _compact_style_finalize_source_context,
    _build_style_baseline_context,
    _build_style_cards_context,
    _build_style_execution_context,
    _build_legacy_style_execution_context,
    _build_foreshadow_notes_draft,
    _build_project_summary_draft,
    _build_style_rewrite_context,
    _build_style_audit_context,
    _build_style_profile_request_context,
    _build_style_profile_units,
    _build_style_reference_profile,
    _build_style_rules_context,
    _build_style_sheet_context,
    _build_style_sheet_merge_context,
    _build_style_persona_context,
    _build_project_timeline_draft,
    _build_writing_check_text,
    _infer_foreshadow_status,
    _new_chapter,
    _promote_character_identity,
    _normalize_project,
    _parse_style_audit_result,
    _parse_style_cards_result,
    _parse_style_execution_result,
    _parse_style_finalize_result,
    _parse_long_form_memory_update,
    _parse_chapter_logic_repair_result,
    _parse_memory_repair_result,
    _parse_memory_reconciliation_result,
    _parse_style_technique_cards_result,
    _parse_style_voice_cards_result,
    _resolve_long_form_record_ref,
    _merge_long_form_memory_repair_patch,
    _merge_long_form_memory_repair_full,
    _merge_long_form_memory_reconciliation_patch,
    _normalize_long_form_reconciliation_patch,
    _normalize_foreshadow_code,
    _merge_long_form_state_patch,
    _memory_repair_patch_targets,
    _literalize_long_form_memory_evidence,
    _chapter_logic_audit_blocking_issues,
    _chapter_logic_audit_validation_errors,
    _normalize_long_form_state_aliases,
    _long_form_memory_sections,
    _long_form_character_identity_gaps_text,
    _long_form_update_contract_instructions,
    _normalize_long_form_event_storage_refs,
    _normalize_long_form_update_payload,
    _normalize_long_form_structural_refs,
    _validate_long_form_memory_update,
    _strip_internal_foreshadow_status_words,
    _normalize_semantic_style_archive,
    _select_style_reference_excerpts,
    _select_style_execution_cards,
    _style_draft_mismatch_reasons,
    _style_finalize_acceptance_errors,
    _style_finalize_error_is_hard,
    _style_finalize_preflight_targets,
    _repair_literal_count_claims,
    _style_cards_selected_by_plan,
    _style_candidate_rank,
    _style_candidate_needs_rescue,
    _style_native_vocabulary_text,
    _style_recent_vocabulary_usage_text,
)


class NovelLongFormContextTests(unittest.TestCase):
    def test_foreshadow_lifecycle_cleanup_removes_standalone_markers_only(self):
        value = (
            "未埋\n"
            "已埋\n"
            "本章首次埋设\n"
            "推进\n"
            "线索推进但未确认超常机制\n"
            "推进关系，但来源仍未知\n"
            "正文证据：她没有把这件事当成答案。"
        )

        cleaned = _strip_internal_foreshadow_status_words(value)

        self.assertNotIn("未埋", cleaned)
        self.assertNotIn("已埋", cleaned)
        self.assertNotIn("本章首次埋设", cleaned)
        self.assertNotIn("\n推进\n", f"\n{cleaned}\n")
        self.assertIn("线索推进但未确认超常机制", cleaned)
        self.assertIn("推进关系，但来源仍未知", cleaned)
        self.assertIn("正文证据：她没有把这件事当成答案。", cleaned)

    def test_narrative_strategy_profile_persists_but_is_excluded_from_runtime_chapter_context(self):
        male = self._project_with_current_chapter(_new_chapter(0))
        male["narrative_strategy_profile"] = {
            "version": "1",
            "audience_direction": "男频",
            "genre_world": "都市高武",
            "primary_story_engine": "能力成长与身份跃迁",
            "secondary_story_engine": "同伴关系",
            "core_reader_promise": "每章获得可见成长或局势反转",
            "satisfaction_currencies": ["能力突破", "身份认可"],
            "emotional_resonance_axes": ["守住同伴"],
            "chapter_variation_pool": ["危机反制", "资源争夺"],
            "low_exposition_strategy": "规则只在行动后果中露出",
        }
        female = deepcopy(male)
        female["narrative_strategy_profile"] = {
            "version": "1",
            "audience_direction": "女频",
            "genre_world": "古言甜宠",
            "primary_story_engine": "关系选择与身份重建",
            "secondary_story_engine": "家业成长",
            "core_reader_promise": "关系回应与尊严恢复同步兑现",
            "satisfaction_currencies": ["关系确认", "尊严恢复"],
            "emotional_resonance_axes": ["被理解与被选择"],
            "chapter_variation_pool": ["误解松动", "共同选择"],
            "low_exposition_strategy": "用人物选择代替背景说明",
        }

        normalized = _normalize_project(male)
        normalized_female = _normalize_project(female)

        self.assertEqual(
            normalized["narrative_strategy_profile"]["primary_story_engine"],
            "能力成长与身份跃迁",
        )
        self.assertEqual(
            normalized_female["narrative_strategy_profile"]["primary_story_engine"],
            "关系选择与身份重建",
        )
        for action in ("draft", "outline", "summary"):
            male_context = _build_chapter_ai_context(normalized, 0, action)
            female_context = _build_chapter_ai_context(normalized_female, 0, action)
            self.assertNotIn("【项目叙事策略画像】", male_context)
            self.assertNotIn("能力突破", male_context)
            self.assertNotIn("关系确认", female_context)
            self.assertEqual(male_context, female_context)

    def _project_with_current_chapter(self, current):
        return {
            "meta": {
                "title": "长篇测试",
                "genre": "古言",
                "style": "细腻",
                "pov": "第三人称",
                "target_words": "20万",
                "premise": "主角在权谋漩涡中查清旧案。",
            },
            "bible": "核心设定：旧案牵动三代人。",
            "world_rules": "规则：贵族名册不可伪造。",
            "timeline": "第1章旧案重启。",
            "summary": "阶段总结：主角已经进入王城。",
            "characters": [],
            "lore": [],
            "foreshadow_items": [],
            "chapters": [current],
        }

    def _context_section(self, context, title):
        marker = f"【{title}】\n"
        start = context.find(marker)
        self.assertNotEqual(start, -1, f"missing context section: {title}")
        start += len(marker)
        end = context.find("\n\n【", start)
        return context[start:] if end < 0 else context[start:end]

    def _strict_update(self, project, chapter_index=0):
        memory = project.get("long_form_memory", {}) if isinstance(project, dict) else {}
        return {
            "schema_version": 2,
            "base_revision": int(memory.get("revision", 0) or 0),
            "state_patch": {},
            "state_retirements": {},
            "state_lifecycle_review": {
                "scope": LONG_FORM_STAGE_REVIEW_SCOPE if (chapter_index + 1) % 10 == 0 else "current_chapter",
                "reviewed_object_keys": [],
                "reviewed_conflict_refs": [],
                "reviewed_task_refs": [],
                "notes": "已复核",
            },
            "fact_updates": [],
            "fact_lifecycle_review": {
                "scope": LONG_FORM_STAGE_REVIEW_SCOPE if (chapter_index + 1) % 10 == 0 else "current_chapter",
                "reviewed_refs": [],
                "notes": "已复核",
            },
            "long_term_events": [],
            "state_reconciliation": {
                "checked": True,
                "coverage_checks": {
                    "named_character_actions": True,
                    "state_changes": True,
                    "evidence_and_unknowns": True,
                    "mechanism_claims_match_body": True,
                    "rules_and_boundaries": True,
                    "foreshadow_and_ending": True,
                },
                "fact_refs": [],
                "character_refs": [],
                "lore_refs": [],
                "foreshadow_refs": [],
                "relationship_refs": [],
                "object_keys": [],
                "conflict_refs": [],
                "task_refs": [],
                "record_runtime_review": {
                    "reviewed_lore_refs": [],
                    "unchanged_lore_refs": [],
                    "reviewed_foreshadow_refs": [],
                    "unchanged_foreshadow_refs": [],
                },
                "resolved_contradictions": [],
                "notes": "已对账",
            },
            "state_delta": {},
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "current_chapter_character_refs": [],
            "stage_archive": None,
            "next_chapter_memory": {},
        }

    def test_compact_delta_expands_to_strict_v2_and_normalizes_alias_review(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "赵明启动城门禁制。"
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{
            "id": "lore-gate",
            "name": "城门禁制",
            "type": "规则",
        }]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 4,
            "state_snapshot": {},
            "active_facts": [],
            "stage_archives": [],
        }
        final_text = "赵明按下铜印，城门禁制随即亮起青光。"
        compact = {
            "schema_version": 2,
            "base_revision": 4,
            "compact_delta_version": LONG_FORM_COMPACT_DELTA_VERSION,
            "state_patch": {},
            "state_retirements": {},
            "fact_updates": [],
            "record_updates": {
                "characters": [],
                "lore": [{
                    "operation": "update",
                    "ref": "L001",
                    "state": "本章已经启动",
                    "evidence_quote": "城门禁制随即亮起青光",
                }],
            },
            "foreshadow_updates": [],
            "long_term_events": [{
                "event": "城门禁制被启动",
                "category": "ability_boundary",
                "evidence_quote": "城门禁制随即亮起青光",
                "storage": {
                    "fact_refs": [],
                    "character_refs": [],
                    "lore_refs": ["L001"],
                    "foreshadow_refs": [],
                    "object_keys": [],
                    "conflict_refs": [],
                    "task_refs": [],
                },
            }],
            "current_chapter_character_refs": [],
            "stage_archive": None,
            "next_chapter_memory": {
                "character_refs": [],
                "lore_refs": [],
                "foreshadow_refs": [],
                "fact_refs": [],
                "stage_archive_refs": [],
                "object_keys": [],
                "conflict_refs": [],
                "task_refs": [],
                "reason": "",
            },
            "verification": {
                "checked": True,
                "coverage_checks": {
                    "named_character_actions": True,
                    "state_changes": True,
                    "evidence_and_unknowns": True,
                    "mechanism_claims_match_body": True,
                    "rules_and_boundaries": True,
                    "foreshadow_and_ending": True,
                },
                # Deliberately use the real ID here while the update uses L001.
                "runtime_unchanged": {"lore_refs": ["lore-gate"], "foreshadow_refs": []},
                "resolved_contradictions": [],
                "notes": "已对账",
            },
        }

        normalized = _normalize_long_form_update_payload(project, 0, compact)

        self.assertNotIn("compact_delta_version", normalized)
        self.assertEqual(normalized["state_lifecycle_review"]["scope"], "current_chapter")
        self.assertEqual(
            normalized["state_reconciliation"]["record_runtime_review"]["unchanged_lore_refs"],
            [],
        )
        errors = _validate_long_form_memory_update(
            project,
            0,
            normalized,
            final_text=final_text,
            require_revision=True,
            require_evidence=True,
        )
        self.assertEqual(errors, [])

    def test_compact_delta_new_fact_is_stored_and_selected_for_next_chapter(self):
        current = _new_chapter(0)
        next_chapter = _new_chapter(1)
        next_chapter["outline"] = "下一章继续处理密信。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, next_chapter]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 2,
            "state_snapshot": {},
            "active_facts": [],
            "stage_archives": [],
        }
        final_text = "赵明把密信锁进铁匣，决定明早亲自送往王城。"
        compact = {
            "schema_version": 2,
            "base_revision": 2,
            "compact_delta_version": LONG_FORM_COMPACT_DELTA_VERSION,
            "state_patch": {},
            "state_retirements": {},
            "fact_updates": [{
                "operation": "add",
                "key": "NF1",
                "scope": "evidence:密信持有",
                "fact": "赵明已经把密信锁进铁匣",
                "evidence_quote": "赵明把密信锁进铁匣",
            }],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "long_term_events": [{
                "event": "密信被锁进铁匣并由赵明保管",
                "category": "evidence",
                "evidence_quote": "赵明把密信锁进铁匣",
                "storage": {
                    "fact_refs": ["NF1"],
                    "character_refs": [],
                    "lore_refs": [],
                    "foreshadow_refs": [],
                    "object_keys": [],
                    "conflict_refs": [],
                    "task_refs": [],
                },
            }],
            "current_chapter_character_refs": [],
            "stage_archive": None,
            "next_chapter_memory": {
                "character_refs": [],
                "lore_refs": [],
                "foreshadow_refs": [],
                "fact_refs": ["NF1"],
                "stage_archive_refs": [],
                "object_keys": [],
                "conflict_refs": [],
                "task_refs": [],
                "reason": "下一章继续处理密信",
            },
            "verification": {
                "checked": True,
                "coverage_checks": {
                    "named_character_actions": True,
                    "state_changes": True,
                    "evidence_and_unknowns": True,
                    "mechanism_claims_match_body": True,
                    "rules_and_boundaries": True,
                    "foreshadow_and_ending": True,
                },
                "runtime_unchanged": {"lore_refs": [], "foreshadow_refs": []},
                "resolved_contradictions": [],
                "notes": "已对账",
            },
        }

        normalized = _normalize_long_form_update_payload(project, 0, compact)
        errors = _validate_long_form_memory_update(
            project,
            0,
            normalized,
            final_text=final_text,
            require_revision=True,
            require_evidence=True,
        )
        self.assertEqual(errors, [])
        self.assertTrue(_apply_long_form_memory_update(project, 0, normalized))
        self.assertEqual(len(project["long_form_memory"]["active_facts"]), 1)
        fact_id = project["long_form_memory"]["active_facts"][0]["id"]
        self.assertTrue(fact_id.startswith("AF-"))
        self.assertIn(fact_id, project["chapters"][1]["memory_selection"]["fact_ids"])

    def test_compact_delta_new_state_keys_do_not_enter_existing_state_lifecycle(self):
        project = self._project_with_current_chapter(_new_chapter(0))
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 1,
            "state_snapshot": {},
            "active_facts": [],
            "stage_archives": [],
        }
        final_text = "赵明把密信锁进铁匣后，追兵已经逼近城门。"
        compact = {
            "schema_version": 2,
            "base_revision": 1,
            "compact_delta_version": LONG_FORM_COMPACT_DELTA_VERSION,
            "state_patch": {
                "object_states": [{
                    "key": "密信铁匣",
                    "name": "铁匣",
                    "state": "由赵明持有并已经上锁",
                }],
                "active_conflicts": [{
                    "id": "",
                    "key": "NCF1",
                    "conflict": "追兵已经逼近城门",
                }],
                "unresolved_tasks": [{
                    "id": "",
                    "key": "NTASK1",
                    "task": "明早把密信送往王城",
                }],
            },
            "state_retirements": {},
            "fact_updates": [],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "long_term_events": [{
                "event": "密信被锁入铁匣，同时追兵逼近",
                "category": "key_object",
                "evidence_quote": "赵明把密信锁进铁匣后，追兵已经逼近城门",
                "storage": {
                    "fact_refs": [],
                    "character_refs": [],
                    "lore_refs": [],
                    "foreshadow_refs": [],
                    "object_keys": ["密信铁匣"],
                    "conflict_refs": ["NCF1"],
                    "task_refs": ["NTASK1"],
                },
            }],
            "current_chapter_character_refs": [],
            "stage_archive": None,
            "next_chapter_memory": {},
            "verification": {
                "checked": True,
                "coverage_checks": {
                    "named_character_actions": True,
                    "state_changes": True,
                    "evidence_and_unknowns": True,
                    "mechanism_claims_match_body": True,
                    "rules_and_boundaries": True,
                    "foreshadow_and_ending": True,
                },
                "runtime_unchanged": {"lore_refs": [], "foreshadow_refs": []},
                "resolved_contradictions": [],
                "notes": "已对账",
            },
        }

        normalized = _normalize_long_form_update_payload(project, 0, compact)

        lifecycle = normalized["state_lifecycle_review"]
        self.assertEqual(lifecycle["reviewed_object_keys"], [])
        self.assertEqual(lifecycle["reviewed_conflict_refs"], [])
        self.assertEqual(lifecycle["reviewed_task_refs"], [])
        self.assertEqual(
            _validate_long_form_memory_update(
                project,
                0,
                normalized,
                final_text=final_text,
                require_revision=True,
                require_evidence=True,
            ),
            [],
        )

    def test_complete_v2_memory_update_remains_unchanged_and_valid(self):
        project = self._project_with_current_chapter(_new_chapter(0))
        project["long_form_memory"] = {"schema_version": "2", "revision": 3}
        update = self._strict_update(project)

        normalized = _normalize_long_form_update_payload(project, 0, update)

        self.assertEqual(normalized, update)
        self.assertEqual(
            _validate_long_form_memory_update(
                project,
                0,
                normalized,
                final_text="本章正文已经完成。",
                require_revision=True,
                require_evidence=True,
            ),
            [],
        )

    def test_memory_update_normalizes_common_model_state_aliases(self):
        current = _new_chapter(0)
        next_chapter = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, next_chapter]
        project["characters"] = [
            {"id": "character-one", "name": "甲"},
            {"id": "character-two", "name": "乙"},
        ]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {},
            "active_facts": [],
            "stage_archives": [],
        }
        final_text = "甲握住玉佩，乙允许验查，追兵逼近，明日必须查清来路。"
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "compact_delta_version": LONG_FORM_COMPACT_DELTA_VERSION,
            "state_patch": {
                "character_states": [{
                    "character_ref": "C001",
                    "status": "甲已经握住玉佩并准备验查。",
                }],
                "relationship_states": [{
                    "ref": "C001|C002",
                    "refs": [],
                    "status": "甲与乙暂时形成合作。",
                }],
                "object_states": [{
                    "object_key": "玉佩",
                    "name": "玉佩",
                    "status": "由甲持有。",
                }],
                "active_conflicts": [{
                    "key": "NCF1",
                    "title": "追兵逼近",
                    "status": "冲突仍在持续。",
                }],
                "unresolved_tasks": [{
                    "key": "NTASK1",
                    "title": "查清来路",
                    "status": "尚未完成。",
                }],
            },
            "state_retirements": {},
            "fact_updates": [],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "long_term_events": [{
                "event": "追兵逼近，甲必须查清来路。",
                "category": "plot",
                "evidence_quote": "追兵逼近",
                "storage": {
                    "fact_refs": [],
                    "character_refs": ["C001", "C002"],
                    "lore_refs": [],
                    "foreshadow_refs": [],
                    "object_keys": ["玉佩"],
                    "conflict_refs": ["NCF1"],
                    "task_refs": ["NTASK1"],
                },
            }],
            "current_chapter_character_refs": ["C001", "C002"],
            "stage_archive": None,
            "next_chapter_memory": {
                "character_refs": ["C001", "C002"],
                "lore_refs": [],
                "foreshadow_refs": [],
                "fact_refs": [],
                "stage_archive_refs": [],
                "object_keys": ["玉佩"],
                "conflict_refs": ["NCF1"],
                "task_refs": ["NTASK1"],
                "reason": "承接追兵线索。",
            },
            "verification": {
                "checked": True,
                "coverage_checks": {
                    "named_character_actions": True,
                    "state_changes": True,
                    "evidence_and_unknowns": True,
                    "mechanism_claims_match_body": True,
                    "rules_and_boundaries": True,
                    "foreshadow_and_ending": True,
                },
                "runtime_unchanged": {"lore_refs": [], "foreshadow_refs": []},
                "resolved_contradictions": [],
                "notes": "已复核",
            },
        }

        normalized = _normalize_long_form_structural_refs(
            project,
            0,
            _normalize_long_form_update_payload(project, 0, update),
        )

        self.assertEqual(normalized["state_patch"]["character_states"][0]["ref"], "C001")
        self.assertEqual(normalized["state_patch"]["character_states"][0]["state"], "甲已经握住玉佩并准备验查。")
        self.assertEqual(normalized["state_patch"]["relationship_states"][0]["refs"], ["C001", "C002"])
        self.assertEqual(normalized["state_patch"]["active_conflicts"][0]["conflict"], "冲突仍在持续。")
        self.assertEqual(normalized["state_patch"]["unresolved_tasks"][0]["task"], "尚未完成。")
        self.assertEqual(
            _validate_long_form_memory_update(
                project,
                0,
                normalized,
                final_text=final_text,
                require_revision=True,
                require_evidence=True,
            ),
            [],
        )

    def test_memory_update_normalizes_key_title_content_and_omitted_scope_aliases(self):
        current = _new_chapter(0)
        next_chapter = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, next_chapter]
        project["characters"] = [
            {"id": "character-one", "name": "甲"},
            {"id": "character-two", "name": "乙"},
        ]
        project["lore"] = [{"id": "lore-one", "name": "旧设定"}]
        project["foreshadow_items"] = []
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {},
            "active_facts": [],
            "stage_archives": [],
        }
        raw = {
            "schema_version": 2,
            "base_revision": 0,
            "compact_delta_version": LONG_FORM_COMPACT_DELTA_VERSION,
            "state_patch": {
                "character_states": [{"key": "C001", "status": "甲已握住玉佩。"}],
                "relationship_states": [{
                    "relationship_key": "NR_C001_C002_01",
                    "type": "create",
                    "state": "甲与乙开始合作。",
                }],
                "active_conflicts": [{
                    "conflict_key": "NCF_JADE_CASE",
                    "type": "create",
                    "state": "玉佩来路仍有争议。",
                }],
                "unresolved_tasks": [{
                    "task_key": "NTASK_FIND_JADE_SOURCE",
                    "type": "create",
                    "state": "需要查清玉佩来源。",
                }],
            },
            "fact_updates": [{
                "operation": "add",
                "fact_key": "NF001",
                "fact": "甲已经握住玉佩。",
                "evidence_quote": "甲握住\\n玉佩",
            }],
            "record_updates": {
                "characters": [],
                "lore": [{
                    "operation": "update",
                    "key": "L001",
                    "runtime_update": "旧设定在本章被重新确认。",
                    "evidence_quote": "旧设定",
                }],
            },
            "foreshadow_updates": [{
                "operation": "create",
                "foreshadow_key": "NT001",
                "stable_name": "玉佩背后的秘密",
                "content": "玉佩来源仍未揭示。",
                "status": "埋设",
                "evidence_quote": "玉佩背后的秘密",
            }],
            "long_term_events": [{
                "summary": "玉佩线索出现。",
                "evidence_quote": "甲握住玉佩",
                "storage": {
                    "fact_refs": ["NF001"],
                    "character_refs": ["C001"],
                    "lore_refs": [],
                    "foreshadow_refs": ["NT001"],
                    "object_keys": [],
                    "conflict_refs": [],
                    "task_refs": [],
                },
            }],
        }

        normalized = _normalize_long_form_update_payload(project, 0, raw)

        self.assertEqual(normalized["state_patch"]["character_states"][0]["ref"], "C001")
        self.assertEqual(
            normalized["state_patch"]["relationship_states"][0]["refs"],
            ["C001", "C002"],
        )
        self.assertEqual(normalized["state_patch"]["active_conflicts"][0]["id"], "")
        self.assertEqual(normalized["state_patch"]["active_conflicts"][0]["key"], "NCF_JADE_CASE")
        self.assertEqual(normalized["state_patch"]["unresolved_tasks"][0]["id"], "")
        self.assertEqual(
            normalized["state_patch"]["unresolved_tasks"][0]["key"],
            "NTASK_FIND_JADE_SOURCE",
        )
        self.assertEqual(normalized["record_updates"]["lore"][0]["ref"], "L001")
        self.assertEqual(
            normalized["record_updates"]["lore"][0]["state"],
            "旧设定在本章被重新确认。",
        )
        self.assertEqual(normalized["fact_updates"][0]["key"], "NF001")
        self.assertEqual(normalized["fact_updates"][0]["evidence_quote"], "甲握住\n玉佩")
        foreshadow = normalized["foreshadow_updates"][0]
        self.assertEqual(foreshadow["name"], "玉佩背后的秘密")
        self.assertEqual(foreshadow["description"], "玉佩来源仍未揭示。")
        self.assertEqual(foreshadow["key"], "NT001")
        self.assertEqual(foreshadow["status"], "已埋")
        self.assertTrue(foreshadow["revealed"])
        self.assertTrue(foreshadow["remaining_secret"])
        self.assertEqual(normalized["long_term_events"][0]["event"], "玉佩线索出现。")
        self.assertEqual(normalized["long_term_events"][0]["category"], "other")
        self.assertTrue(normalized["fact_updates"][0]["scope"].startswith("auto_fact:"))

    def test_memory_repair_parser_fixes_one_unambiguous_missing_json_quote(self):
        malformed = (
            '{"outline":"实际提纲","summary":"本章摘要","key_facts":["关键事实"],'
            '"long_form_memory":{"note":"她说，“别碰。”}}'
        )

        parsed = _parse_memory_repair_result(malformed)

        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["outline"], "实际提纲")
        self.assertEqual(parsed["summary"], "本章摘要")
        self.assertEqual(parsed["key_facts"], "1. 关键事实")
        self.assertEqual(parsed["memory_update"]["note"], "她说，“别碰。”")

    def test_memory_repair_parser_fixes_multiple_missing_evidence_quotes(self):
        malformed = (
            '{"outline":"实际提纲","summary":"本章摘要","key_facts":["关键事实"],'
            '"logic_audit":{"checked":true,"issues":[]},"long_form_memory":{'
            '"fact_updates":[{"evidence_quote":"“第一句。”},{"evidence_quote":"普通证据。"}]}}'
        )

        parsed = _parse_memory_repair_result(malformed)

        self.assertTrue(parsed["parsed"])
        self.assertEqual(
            [item["evidence_quote"] for item in parsed["memory_update"]["fact_updates"]],
            ["“第一句。”", "普通证据。"],
        )

    def test_memory_repair_parser_selects_real_json_after_placeholder_json(self):
        placeholder = {
            "long_form_memory_patch": {
                "replace": {
                    "record_updates": "返回该字段的完整替换值",
                    "state_reconciliation": "返回该字段的完整替换值",
                }
            }
        }
        actual = {
            "long_form_memory_patch": {
                "replace": {
                    "record_updates": {"characters": [], "lore": []},
                    "state_reconciliation": {"checked": True, "lore_refs": []},
                }
            }
        }

        parsed = _parse_memory_repair_result(
            json.dumps(placeholder, ensure_ascii=False)
            + "\n"
            + json.dumps(actual, ensure_ascii=False)
        )

        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["repair_mode"], "patch")
        self.assertEqual(
            parsed["memory_patch"]["replace"]["record_updates"],
            {"characters": [], "lore": []},
        )

    def test_memory_repair_parser_keeps_one_normal_json_unchanged(self):
        parsed = _parse_memory_repair_result(
            '{"long_form_memory_patch":{"replace":{"record_updates":{"characters":[]}}}}'
        )

        self.assertTrue(parsed["parsed"])
        self.assertEqual(
            parsed["memory_patch"]["replace"]["record_updates"],
            {"characters": []},
        )

    def test_memory_repair_parser_wraps_bare_replace_after_commentary_json(self):
        parsed = _parse_memory_repair_result(
            '{"commentary":"正在修复"}'
            '{"replace":{"record_updates":{"characters":[]},"state_reconciliation":{"checked":true}}}'
        )

        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["repair_mode"], "patch")
        self.assertEqual(
            parsed["memory_patch"]["replace"]["state_reconciliation"],
            {"checked": True},
        )

    def test_memory_repair_parser_wraps_direct_memory_fields(self):
        parsed = _parse_memory_repair_result(
            '{"state_reconciliation":{"checked":true,"lore_refs":[]},'
            '"next_chapter_memory":{"lore_refs":[]}}'
        )

        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["repair_mode"], "patch")
        self.assertEqual(
            parsed["memory_patch"]["replace"]["state_reconciliation"],
            {"checked": True, "lore_refs": []},
        )
        self.assertEqual(
            parsed["memory_patch"]["replace"]["next_chapter_memory"],
            {"lore_refs": []},
        )

    def test_memory_repair_parser_treats_logic_audit_only_result_as_patch(self):
        parsed = _parse_memory_repair_result(
            '{"logic_audit":{"checked":true,"issues":[]}}'
        )

        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["repair_mode"], "patch")
        self.assertTrue(parsed["logic_audit"]["checked"])

    def test_state_aliases_accept_kind_specific_record_ids(self):
        normalized = _normalize_long_form_state_aliases({
            "record_updates": {
                "characters": [{
                    "operation": "update",
                    "character_id": "C001",
                    "dynamic": "人物状态变化。",
                }],
                "lore": [{
                    "operation": "update",
                    "lore_id": "L001",
                    "dynamic": "设定状态变化。",
                }],
            },
        })

        self.assertEqual(normalized["record_updates"]["characters"][0]["ref"], "C001")
        self.assertEqual(normalized["record_updates"]["lore"][0]["ref"], "L001")

    def test_invalid_opaque_character_ref_uses_unique_exact_name_alias(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [{"id": "char-luo", "name": "罗东家"}]
        invalid_ref = "invented-character-id"

        normalized = _normalize_long_form_update_payload(project, 0, {
            "state_patch": {
                "character_states": [{
                    "character_id": invalid_ref,
                    "name": "罗东家",
                    "state": "本章退出谈判主导位置。",
                }],
            },
            "current_chapter_character_refs": [invalid_ref],
            "long_term_events": [{
                "event": "罗东家退出谈判主导位置。",
                "storage": {"character_refs": [invalid_ref]},
            }],
            "next_chapter_memory": {"character_refs": [invalid_ref]},
        })

        self.assertEqual(normalized["state_patch"]["character_states"][0]["ref"], "C001")
        self.assertEqual(normalized["current_chapter_character_refs"], ["C001"])
        self.assertEqual(
            normalized["long_term_events"][0]["storage"]["character_refs"],
            ["C001"],
        )
        self.assertEqual(normalized["next_chapter_memory"]["character_refs"], ["C001"])

    def test_state_aliases_accept_stable_ref_and_temp_key_variants(self):
        normalized = _normalize_long_form_state_aliases({
            "state_patch": {
                "character_states": [{"stable_ref": "C001", "runtime_update": "本章出场。"}],
            },
            "fact_updates": [{
                "operation": "add",
                "temp_key": "NF001",
                "fact": "新事实",
            }],
            "record_updates": {
                "characters": [{
                    "operation": "update",
                    "stable_ref": "C001",
                    "runtime": "人物状态变化。",
                }],
                "lore": [{
                    "operation": "update",
                    "stable_ref": "L001",
                    "runtime_update": "设定状态变化。",
                }],
            },
            "foreshadow_updates": [{
                "operation": "create",
                "temp_key": "NT001",
                "stable_name": "新伏笔",
                "status": "埋设",
                "progress": "本章发现线索仍有缺口。",
            }],
            "conflicts": [{
                "operation": "add",
                "key": "NCF001",
                "conflict": "冲突仍在继续。",
            }],
            "tasks": [{
                "operation": "add",
                "key": "NTASK001",
                "task": "需要继续核查。",
            }],
        })

        self.assertEqual(normalized["state_patch"]["character_states"][0]["ref"], "C001")
        self.assertEqual(normalized["fact_updates"][0]["key"], "NF001")
        self.assertEqual(normalized["record_updates"]["characters"][0]["ref"], "C001")
        self.assertEqual(
            normalized["record_updates"]["characters"][0]["state"],
            "人物状态变化。",
        )
        self.assertEqual(normalized["record_updates"]["lore"][0]["ref"], "L001")
        self.assertEqual(normalized["foreshadow_updates"][0]["key"], "NT001")
        self.assertEqual(
            normalized["foreshadow_updates"][0]["description"],
            "本章发现线索仍有缺口。",
        )
        self.assertTrue(normalized["foreshadow_updates"][0]["revealed"])
        self.assertTrue(normalized["foreshadow_updates"][0]["remaining_secret"])
        self.assertEqual(normalized["state_patch"]["active_conflicts"][0]["key"], "NCF001")
        self.assertEqual(normalized["state_patch"]["active_conflicts"][0]["id"], "")
        self.assertEqual(normalized["state_patch"]["unresolved_tasks"][0]["key"], "NTASK001")
        self.assertEqual(normalized["state_patch"]["unresolved_tasks"][0]["id"], "")

    def test_state_aliases_accept_generic_ref_for_existing_conflicts_and_tasks(self):
        normalized = _normalize_long_form_state_aliases({
            "state_patch": {
                "active_conflicts": [{
                    "ref": "CF-0006",
                    "id": "",
                    "operation": "update",
                    "conflict": "旧冲突已经推进。",
                }],
                "unresolved_tasks": [{
                    "ref": "TASK-0010",
                    "id": "",
                    "operation": "update",
                    "task": "旧任务进入下一阶段。",
                }],
            },
        })

        self.assertEqual(
            normalized["state_patch"]["active_conflicts"][0]["id"],
            "CF-0006",
        )
        self.assertEqual(
            normalized["state_patch"]["unresolved_tasks"][0]["id"],
            "TASK-0010",
        )

    def test_state_aliases_normalize_pipe_delimited_relationship_refs(self):
        normalized = _normalize_long_form_state_aliases({
            "state_patch": {
                "relationship_states": [
                    {"refs": "C001|C005", "state": "父女公开对立。"},
                    {"refs": ["C001|C008"], "state": "共同核验封条。"},
                ],
            },
        })

        relationships = normalized["state_patch"]["relationship_states"]
        self.assertEqual(relationships[0]["refs"], ["C001", "C005"])
        self.assertEqual(relationships[1]["refs"], ["C001", "C008"])

    def test_state_aliases_normalize_relationship_participants(self):
        normalized = _normalize_long_form_state_aliases({
            "state_patch": {
                "relationship_states": [{
                    "participants": ["C002", "C010"],
                    "refs": [],
                    "state": "二人因账本去向产生新的分歧。",
                }],
            },
        })

        self.assertEqual(
            normalized["state_patch"]["relationship_states"][0]["refs"],
            ["C002", "C010"],
        )

    def test_state_aliases_split_multiple_relationship_pairs_without_merging_them(self):
        normalized = _normalize_long_form_state_aliases({
            "state_patch": {
                "relationship_states": [{
                    "refs": "C001-C002,C001-C003",
                    "runtime_patch": "三人关系发生变化。",
                }],
            },
        })

        relationships = normalized["state_patch"]["relationship_states"]
        self.assertEqual(
            [item["refs"] for item in relationships],
            [["C001", "C002"], ["C001", "C003"]],
        )
        self.assertEqual(
            [item["state"] for item in relationships],
            ["三人关系发生变化。", "三人关系发生变化。"],
        )

    def test_state_aliases_accept_plural_relationship_refs(self):
        normalized = _normalize_long_form_state_aliases({
            "state_patch": {
                "relationship_states": [{
                    "relationship_refs": ["C001-C002", "C001-C003"],
                    "state": "三份婚书分别指向贺沉舟与三人。",
                }],
            },
        })

        relationships = normalized["state_patch"]["relationship_states"]
        self.assertEqual(
            [item["refs"] for item in relationships],
            [["C001", "C002"], ["C001", "C003"]],
        )

    def test_state_aliases_accept_runtime_patch_and_infer_only_real_updates(self):
        normalized = _normalize_long_form_state_aliases({
            "record_updates": {
                "characters": [
                    {"ref": "C001", "runtime_patch": "甲暂时离开港口。"},
                    {"ref": "C002"},
                ],
                "lore": [{"ref": "L001", "operational_state": "封锁仍在继续。"}],
            },
            "foreshadow_updates": [{
                "ref": "F001",
                "spatial_state": "线索仍指向旧码头。",
            }],
        })

        characters = normalized["record_updates"]["characters"]
        self.assertEqual(characters[0]["operation"], "update")
        self.assertEqual(characters[0]["state"], "甲暂时离开港口。")
        self.assertNotIn("operation", characters[1])
        self.assertEqual(normalized["record_updates"]["lore"][0]["operation"], "update")
        self.assertEqual(normalized["record_updates"]["lore"][0]["state"], "封锁仍在继续。")
        self.assertEqual(normalized["foreshadow_updates"][0]["operation"], "update")
        self.assertEqual(normalized["foreshadow_updates"][0]["state"], "线索仍指向旧码头。")

    def test_state_aliases_accept_current_dynamic_append(self):
        normalized = _normalize_long_form_state_aliases({
            "record_updates": {
                "characters": [{
                    "operation": "update",
                    "ref": "C001",
                    "current_dynamic_append": "甲在本章明确拒绝替同伴做决定。",
                    "evidence_quote": "拒绝替同伴做决定",
                }],
                "lore": [],
            },
        })

        item = normalized["record_updates"]["characters"][0]
        self.assertEqual(item["state"], "甲在本章明确拒绝替同伴做决定。")
        self.assertEqual(item["changes"], [item["state"]])

    def test_reconciliation_accepts_current_dynamic_append(self):
        project = self._project_with_current_chapter(_new_chapter(0))
        project["characters"] = [{"id": "char-c001", "name": "甲"}]
        normalized = _normalize_long_form_reconciliation_patch(project, {
            "record_updates": {
                "characters": [{
                    "operation": "update",
                    "ref": "char-c001",
                    "current_dynamic_append": "甲在本章明确拒绝替同伴做决定。",
                    "evidence_quote": "拒绝替同伴做决定",
                }],
                "lore": [],
            },
        })

        item = normalized["record_updates"]["characters"][0]
        self.assertEqual(item["state"], "甲在本章明确拒绝替同伴做决定。")

    def test_update_payload_expands_runtime_fields_and_safe_canonical_character_ref(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [
            {"id": "char-c001", "name": "贺知微"},
            {"id": "char-c002", "name": "林见夏"},
            {"id": "char-c003", "name": "周既白"},
        ]

        normalized = _normalize_long_form_update_payload(project, 0, {
            "record_updates": {
                "characters": [{
                    "operation": "create",
                    "key": "NC003",
                    "canonical_ref": "C003",
                    "name": "周既白",
                    "fields": {
                        "current_dynamic": "周既白记得类似场景，但不能确定发生次数。",
                    },
                    "evidence_quote": "只是每次细节都不一样。",
                }],
                "lore": [],
            },
        })

        item = normalized["record_updates"]["characters"][0]
        self.assertEqual(item["operation"], "update")
        self.assertEqual(item["ref"], "char-c003")
        self.assertEqual(
            item["state"],
            "周既白记得类似场景，但不能确定发生次数。",
        )
        self.assertEqual(item["changes"], [item["state"]])

        identity_update = _normalize_long_form_update_payload(project, 0, {
            "record_updates": {
                "characters": [{
                    "operation": "create",
                    "key": "NC003",
                    "canonical_ref": "C003",
                    "name": "周既白",
                    "canon": {"voice": "语气平静，回答简短直接"},
                }],
                "lore": [],
            },
        })["record_updates"]["characters"][0]
        self.assertEqual(identity_update["operation"], "update")
        self.assertEqual(identity_update["identity_patch"]["voice"], "语气平静，回答简短直接")
        self.assertEqual(identity_update["canon"], {})

    def test_canonical_character_ref_does_not_convert_on_name_mismatch(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [
            {"id": "char-c001", "name": "贺知微"},
            {"id": "char-c002", "name": "林见夏"},
            {"id": "char-c003", "name": "周既白"},
        ]

        normalized = _normalize_long_form_update_payload(project, 0, {
            "record_updates": {
                "characters": [{
                    "operation": "create",
                    "key": "NC003",
                    "canonical_ref": "C003",
                    "name": "周既白同学",
                    "fields": {"current_dynamic": "正文只确认他在场。"},
                }],
                "lore": [],
            },
        })

        item = normalized["record_updates"]["characters"][0]
        self.assertEqual(item["operation"], "create")
        self.assertNotIn("ref", item)

    def test_state_aliases_normalize_foreshadow_advance_operation(self):
        normalized = _normalize_long_form_state_aliases({
            "foreshadow_updates": [{
                "operation": "advance",
                "ref": "F005",
                "status": "已埋",
                "progress": "旧账本的残页出现新的朱砂印记。",
            }],
        })

        foreshadow = normalized["foreshadow_updates"][0]
        self.assertEqual(foreshadow["operation"], "update")
        self.assertEqual(foreshadow["ref"], "F005")

    def test_state_aliases_normalize_change_for_runtime_state_collections(self):
        normalized = _normalize_long_form_state_aliases({
            "state_patch": {
                "character_states": [{"ref": "C001", "change": "主角暂住听雨楼。"}],
                "relationship_states": [{
                    "participants": ["C001", "C002"],
                    "change": "二人恢复夫妻关系但仍分居。",
                }],
                "object_states": [{"key": "NOBJ-1", "change": "名册已交由御史台封存。"}],
                "active_conflicts": [{"id": "CF-1", "change": "孙氏去向仍待核验。"}],
                "unresolved_tasks": [{"id": "TASK-1", "change": "追查孙氏当前下落。"}],
            },
            "record_updates": {
                "characters": [
                    {"operation": "update", "ref": "C001", "change": "暂住听雨楼。"},
                    {"operation": "create", "key": "NC-1", "stable_name": "孙氏"},
                ],
                "lore": [{"operation": "update", "ref": "L001", "change": "御史台封存名册。"}],
            },
            "foreshadow_updates": [{
                "operation": "update",
                "ref": "F001",
                "change": "孙氏尚在人世的线索得到推进。",
            }],
            "long_term_events": [{
                "event": "孙氏接受官面保护。",
                "type": "证人保护与责任边界",
            }],
        })

        state_patch = normalized["state_patch"]
        self.assertEqual(state_patch["character_states"][0]["state"], "主角暂住听雨楼。")
        self.assertEqual(state_patch["relationship_states"][0]["refs"], ["C001", "C002"])
        self.assertEqual(state_patch["relationship_states"][0]["state"], "二人恢复夫妻关系但仍分居。")
        self.assertEqual(state_patch["object_states"][0]["state"], "名册已交由御史台封存。")
        self.assertEqual(state_patch["active_conflicts"][0]["conflict"], "孙氏去向仍待核验。")
        self.assertEqual(state_patch["unresolved_tasks"][0]["task"], "追查孙氏当前下落。")
        self.assertEqual(normalized["record_updates"]["characters"][0]["state"], "暂住听雨楼。")
        self.assertEqual(normalized["record_updates"]["characters"][1]["name"], "孙氏")
        self.assertEqual(normalized["record_updates"]["lore"][0]["state"], "御史台封存名册。")
        self.assertEqual(normalized["foreshadow_updates"][0]["state"], "孙氏尚在人世的线索得到推进。")
        self.assertEqual(normalized["long_term_events"][0]["category"], "other")

    def test_state_aliases_normalize_superseded_fact_and_recovered_foreshadow(self):
        normalized = _normalize_long_form_state_aliases({
            "fact_updates": [{
                "operation": "supersede",
                "key": "NF-087-002",
                "supersedes": "AF-0340",
                "fact": "公议已经举行。",
            }],
            "foreshadow_updates": [{
                "operation": "update",
                "ref": "F001",
                "status": "已回收",
                "progress": "封条断痕已确认来自二次开启。",
            }],
        })

        self.assertEqual(normalized["fact_updates"][0]["id"], "AF-0340")
        foreshadow = normalized["foreshadow_updates"][0]
        self.assertEqual(foreshadow["revealed"], "封条断痕已确认来自二次开启。")
        self.assertIn("remaining_secret", foreshadow)
        self.assertEqual(foreshadow["remaining_secret"], "")

    def test_state_patch_deduplicates_explicit_object_key_and_keeps_lore_link(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{"id": "lore-bottle", "name": "宫制药瓶"}]
        memory = {
            "state_snapshot": {
                "object_states": [
                    {
                        "lore_id": "lore-bottle",
                        "key": "NOBJ-CH53-002",
                        "name": "宫制药瓶",
                        "state": "药瓶刚刚出现。",
                    },
                    {
                        "lore_id": "",
                        "key": "NOBJ-CH53-002",
                        "name": "宫制药瓶",
                        "state": "药瓶形制已经验真。",
                    },
                ],
            },
        }

        _merge_long_form_state_patch(project, memory, chapter, 0, {}, {})

        objects = memory["state_snapshot"]["object_states"]
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["key"], "NOBJ-CH53-002")
        self.assertEqual(objects[0]["lore_id"], "lore-bottle")
        self.assertEqual(objects[0]["state"], "药瓶形制已经验真。")

    def test_state_aliases_backfill_empty_canonical_state_and_evidence_fields(self):
        normalized = _normalize_long_form_state_aliases({
            "state_patch": {
                "character_states": [{
                    "ref": "C001",
                    "state": "",
                    "runtime_update": "人物已经改为留守账房。",
                    "evidence_quote": "",
                    "evidence": "她把账房钥匙收进袖中",
                }],
                "relationship_states": [{
                    "refs": ["C001", "C002"],
                    "state": "",
                    "description": "二人暂时形成合作。",
                    "evidence_quote": "",
                    "quote": "这次我与你一道去",
                }],
                "object_states": [{
                    "key": "OBJ-ledger",
                    "state": "",
                    "status": "账册已经封存。",
                    "evidence_quote": "",
                    "evidence": "账册重新锁入木匣",
                }],
            },
            "fact_updates": [{
                "operation": "add",
                "key": "NF1",
                "fact": "账册已经封存。",
                "evidence_quote": "",
                "quote": "账册重新锁入木匣",
            }],
            "record_updates": {
                "characters": [{
                    "operation": "update",
                    "ref": "C001",
                    "state": "",
                    "runtime_update": "人物已经改为留守账房。",
                    "evidence_quote": "",
                    "evidence": "她把账房钥匙收进袖中",
                }],
                "lore": [],
            },
            "foreshadow_updates": [{
                "operation": "update",
                "ref": "F001",
                "state": "",
                "progress": "账册封条出现一道新断痕。",
                "evidence_quote": "",
                "quote": "封条上多了一道新断痕",
            }],
        })

        state_patch = normalized["state_patch"]
        self.assertEqual(state_patch["character_states"][0]["state"], "人物已经改为留守账房。")
        self.assertEqual(state_patch["character_states"][0]["evidence_quote"], "她把账房钥匙收进袖中")
        self.assertEqual(state_patch["relationship_states"][0]["state"], "二人暂时形成合作。")
        self.assertEqual(state_patch["relationship_states"][0]["evidence_quote"], "这次我与你一道去")
        self.assertEqual(state_patch["object_states"][0]["state"], "账册已经封存。")
        self.assertEqual(state_patch["object_states"][0]["evidence_quote"], "账册重新锁入木匣")
        self.assertEqual(normalized["fact_updates"][0]["evidence_quote"], "账册重新锁入木匣")
        self.assertEqual(normalized["record_updates"]["characters"][0]["state"], "人物已经改为留守账房。")
        self.assertEqual(
            normalized["record_updates"]["characters"][0]["evidence_quote"],
            "她把账房钥匙收进袖中",
        )
        self.assertEqual(normalized["foreshadow_updates"][0]["state"], "账册封条出现一道新断痕。")
        self.assertEqual(normalized["foreshadow_updates"][0]["evidence_quote"], "封条上多了一道新断痕")

    def test_state_aliases_treat_ncf_and_ntask_ids_as_new_temporary_keys(self):
        normalized = _normalize_long_form_state_aliases({
            "state_patch": {
                "active_conflicts": [{
                    "id": "NCF-CH56-001",
                    "conflict": "账册争夺尚未结束。",
                }],
                "unresolved_tasks": [{
                    "id": "NTASK-CH56-001",
                    "task": "追查封条断痕来源。",
                }],
            },
        })

        conflict = normalized["state_patch"]["active_conflicts"][0]
        task = normalized["state_patch"]["unresolved_tasks"][0]
        self.assertEqual(conflict["key"], "NCF-CH56-001")
        self.assertEqual(conflict["id"], "")
        self.assertEqual(task["key"], "NTASK-CH56-001")
        self.assertEqual(task["id"], "")

    def test_runtime_unchanged_refs_are_also_normalized_as_reviewed(self):
        normalized = _normalize_long_form_state_aliases({
            "state_reconciliation": {
                "record_runtime_review": {
                    "reviewed_lore_refs": ["L013"],
                    "unchanged_lore_refs": ["L007", "L020"],
                    "reviewed_foreshadow_refs": [],
                    "unchanged_foreshadow_refs": ["F008"],
                },
            },
        })

        runtime_review = normalized["state_reconciliation"]["record_runtime_review"]
        self.assertEqual(
            runtime_review["reviewed_lore_refs"],
            ["L013", "L007", "L020"],
        )
        self.assertEqual(runtime_review["reviewed_foreshadow_refs"], ["F008"])

        unchanged = _normalize_long_form_state_aliases({
            "record_updates": {
                "characters": [{"operation": "unchanged", "stable_ref": "C001"}],
                "lore": [],
            },
        })
        self.assertEqual(unchanged["record_updates"]["characters"], [])

    def test_runtime_conclusions_are_normalized_to_review_arrays(self):
        normalized = _normalize_long_form_state_aliases({
            "state_reconciliation": {
                "lore_refs": ["opaque-lore-ref"],
                "record_runtime_review": {
                    "runtime_conclusions": [
                        {"ref": "L011", "conclusion": "updated"},
                        {"ref": "L006", "conclusion": "unchanged"},
                        {"ref": "opaque-lore-ref", "conclusion": "updated"},
                        {"foreshadow_ref": "F008", "conclusion": "不变"},
                    ],
                },
            },
        })

        runtime_review = normalized["state_reconciliation"]["record_runtime_review"]
        self.assertEqual(
            runtime_review["reviewed_lore_refs"],
            ["L011", "L006", "opaque-lore-ref"],
        )
        self.assertEqual(runtime_review["unchanged_lore_refs"], ["L006"])
        self.assertEqual(runtime_review["reviewed_foreshadow_refs"], ["F008"])
        self.assertEqual(runtime_review["unchanged_foreshadow_refs"], ["F008"])
        self.assertEqual(len(runtime_review["runtime_conclusions"]), 4)

    def test_fact_state_alias_and_canonical_buried_foreshadow_are_normalized(self):
        normalized = _normalize_long_form_state_aliases({
            "fact_updates": [{
                "operation": "update",
                "fact_id": "AF-0028",
                "state": "白家副单已经完成双份封存",
            }],
            "foreshadow_updates": [{
                "operation": "update",
                "foreshadow_id": "F028",
                "status": "已埋",
                "progress": "副单末栏出现沈家旁支宅院",
                "description": "实际收货人与宅院用途仍未查明",
            }],
            "record_updates": {
                "characters": [],
                "lore": [{
                    "operation": "create",
                    "lore_ref": "NL-CH28-001",
                    "title": "宫中蜡料副单",
                    "new_state": "副单夹行记载小蜡三匣",
                }],
            },
        })

        fact = normalized["fact_updates"][0]
        self.assertEqual(fact["id"], "AF-0028")
        self.assertEqual(fact["fact"], "白家副单已经完成双份封存")
        foreshadow = normalized["foreshadow_updates"][0]
        self.assertEqual(foreshadow["ref"], "F028")
        self.assertEqual(foreshadow["revealed"], "副单末栏出现沈家旁支宅院")
        self.assertEqual(foreshadow["remaining_secret"], "实际收货人与宅院用途仍未查明")
        lore = normalized["record_updates"]["lore"][0]
        self.assertEqual(lore["key"], "NL-CH28-001")
        self.assertEqual(lore["name"], "宫中蜡料副单")
        self.assertEqual(lore["state"], "副单夹行记载小蜡三匣")
        self.assertNotIn("story_known", lore)

    def test_compact_review_omission_means_required_runtime_record_is_unchanged(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["foreshadow_items"] = [{
            "id": "foreshadow-a", "name": "副单收货地", "status": "已埋",
        }]
        project["long_form_memory"] = {
            "schema_version": "2", "revision": 0, "state_snapshot": {},
            "active_facts": [], "stage_archives": [],
        }
        update = self._strict_update(project)
        update["compact_delta_version"] = LONG_FORM_COMPACT_DELTA_VERSION
        update.pop("state_reconciliation")
        update.pop("state_lifecycle_review")
        update.pop("fact_lifecycle_review")
        update["long_term_events"] = [{
            "event": "副单收货地点仍待核验",
            "category": "foreshadow",
            "evidence_quote": "副单末栏出现沈家旁支宅院",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": ["foreshadow-a"], "object_keys": [],
                "conflict_refs": [], "task_refs": [],
            },
        }]
        update["verification"] = {
            "checked": True,
            "coverage_checks": {
                "named_character_actions": True,
                "state_changes": True,
                "evidence_and_unknowns": True,
                "mechanism_claims_match_body": True,
                "rules_and_boundaries": True,
                "foreshadow_and_ending": True,
            },
            "runtime_unchanged": {"lore_refs": [], "foreshadow_refs": []},
            "resolved_contradictions": [],
            "notes": "已复核，运行态未变化",
        }

        normalized = _normalize_long_form_update_payload(project, 0, update)

        runtime_review = normalized["state_reconciliation"]["record_runtime_review"]
        self.assertEqual(runtime_review["reviewed_foreshadow_refs"], ["foreshadow-a"])
        self.assertEqual(runtime_review["unchanged_foreshadow_refs"], ["foreshadow-a"])
        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, normalized,
                final_text="副单末栏出现沈家旁支宅院，实际用途仍待核验。",
                require_revision=True,
                require_evidence=True,
            ),
            [],
        )

    def test_unique_short_evidence_is_expanded_from_literal_body(self):
        body = "陆停舟的手指无力垂下。\n\n粮。\n\n陆停舟再没有动静。"
        normalized = _literalize_long_form_memory_evidence({
            "fact_updates": [{"evidence_quote": "粮。"}],
        }, body)

        quote = normalized["fact_updates"][0]["evidence_quote"]
        self.assertGreaterEqual(len("".join(quote.split())), 8)
        self.assertIn(quote, body)

    def test_noncontiguous_dialogue_evidence_salvages_unique_short_clause(self):
        body = (
            "车马管事低声道：少夫人，那次送得准时，周氏赏过我银子……\n\n"
            "他又说：我见过……接头人姓……\n\n话音突然断了。"
        )
        normalized = _literalize_long_form_memory_evidence({
            "fact_updates": [{
                "evidence_quote": "少夫人，那次送得准时，周氏赏过我银子……我见过……接头人姓……",
            }],
        }, body)

        quote = normalized["fact_updates"][0]["evidence_quote"]
        self.assertGreaterEqual(len("".join(quote.split())), 8)
        self.assertIn(quote, body)

    def test_fact_supersede_and_unrevealed_foreshadow_aliases_keep_identity(self):
        normalized = _normalize_long_form_state_aliases({
            "fact_updates": [{
                "operation": "supersede",
                "fact_ref": "AF-0005",
                "new_fact_key": "NF001",
                "fact": "事实已经推进。",
            }],
            "foreshadow_updates": [{
                "operation": "update",
                "ref_id": "F001",
                "status": "未埋",
                "state": "progressed",
                "update": "本章进一步推进线索。",
                "revealed": "线索已出现。",
                "unrevealed": "真相仍未明。",
            }],
        })

        fact = normalized["fact_updates"][0]
        self.assertEqual(fact["id"], "AF-0005")
        self.assertEqual(fact["key"], "NF001")
        self.assertEqual(normalized["foreshadow_updates"][0]["ref"], "F001")
        self.assertEqual(normalized["foreshadow_updates"][0]["status"], "已埋")
        self.assertEqual(
            normalized["foreshadow_updates"][0]["description"],
            "本章进一步推进线索。",
        )
        self.assertEqual(
            normalized["foreshadow_updates"][0]["remaining_secret"],
            "真相仍未明。",
        )

    def test_style_finalize_compacts_duplicate_context_but_keeps_continuity_and_style(self):
        redundant = "重复规划资料标记。" * 10000
        padding = "用于模拟长篇中后期资料增长。" * 2000
        original = "\n\n".join([
            "【当前章节】\n本章唯一章节标记：城门前的铜印。\n" + padding,
            "【当前状态快照】\n状态唯一标记：赵明仍持有密信。\n" + padding,
            "【剧情连续性参考】\n权限与证据边界唯一标记。\n" + padding,
            "【后章衔接点】\n下一章开头唯一衔接标记。\n" + padding,
            "【本章相关人物】\n人物唯一标记：赵明。\n" + padding,
            "【本章相关设定】\n设定唯一标记：城门禁制。\n" + padding,
            "【本章相关伏笔】\n伏笔唯一标记：缺失的半页账册。\n" + padding,
            "【正文风格参考】\n样本写法唯一标记：先写动作，再落到人物判断。\n" + padding,
            "【重复规划资料】\n" + redundant,
        ])

        compacted = _compact_style_finalize_source_context(
            original,
            style_reference="样本写法唯一标记：先写动作，再落到人物判断。",
        )

        for marker in (
            "本章唯一章节标记",
            "状态唯一标记",
            "权限与证据边界唯一标记",
            "下一章开头唯一衔接标记",
            "人物唯一标记",
            "设定唯一标记",
            "伏笔唯一标记",
            "样本写法唯一标记",
        ):
            self.assertIn(marker, compacted)
        self.assertNotIn("重复规划资料标记", compacted)
        self.assertLessEqual(len(compacted), 60000)
        self.assertLess(len(compacted), len(original) * 0.7)

    def test_style_finalize_preflight_reports_concrete_short_paragraph_merges(self):
        reference = "\n".join(
            "样本中的连续叙述段落会把现场反馈、人物判断和下一步动作放在同一段里。"
            "样本中的连续叙述段落会把现场反馈、人物判断和下一步动作放在同一段里。"
            for _ in range(10)
        )
        candidate = "\n".join("这是一个短段。" for _ in range(100))

        result = _style_finalize_preflight_targets(reference, candidate, output_target=600)

        self.assertIn("至少合并", result)
        self.assertIn("至少将", result)
        self.assertRegex(result, r"至少合并\d+个普通段")
        self.assertRegex(result, r"至少将\d+个普通短段并入")

    def _large_250_chapter_state_project(self):
        chapters = [_new_chapter(index) for index in range(250)]
        project = self._project_with_current_chapter(chapters[-1])
        project["chapters"] = chapters
        project["characters"] = [
            {"id": f"char-{index:03d}", "name": f"人物{index:03d}", "role": "长期人物"}
            for index in range(80)
        ]
        project["lore"] = [
            {"id": f"lore-{index:03d}", "name": f"设定{index:03d}", "type": "规则"}
            for index in range(90)
        ]
        project["foreshadow_items"] = [
            {
                "id": f"foreshadow-{index:03d}",
                "code": f"F{index + 1:04d}",
                "name": f"伏笔{index:03d}",
                "status": "已埋",
            }
            for index in range(70)
        ]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 249,
            "state_snapshot": {
                "story_time": "第250章结束时",
                "location": "王城",
                "character_states": [
                    {
                        "character_id": f"char-{index:03d}",
                        "name": f"人物{index:03d}",
                        "state": f"人物{index:03d}仍处于需要后文继承的长期动态状态",
                    }
                    for index in range(80)
                ],
                "relationship_states": [
                    {
                        "characters": [f"char-{index:03d}", f"char-{index + 1:03d}"],
                        "state": f"第{index:03d}组关系仍存在未解决变化",
                    }
                    for index in range(60)
                ],
                "object_states": [
                    {
                        "key": f"OBJ-{index + 1:04d}",
                        "name": f"关键物件{index + 1:04d}",
                        "state": f"第{index + 1:04d}件物品仍有跨章位置和归属约束",
                    }
                    for index in range(250)
                ],
                "active_conflicts": [
                    {
                        "id": f"CF-{index + 1:04d}",
                        "conflict": f"第{index + 1:04d}项冲突仍未解决并持续影响主线",
                    }
                    for index in range(100)
                ],
                "unresolved_tasks": [
                    {
                        "id": f"TASK-{index + 1:04d}",
                        "task": f"第{index + 1:04d}项任务仍待后续章节完成",
                    }
                    for index in range(130)
                ],
            },
            "active_facts": [
                {
                    "id": f"AF-{index + 1:04d}",
                    "scope": f"continuity:branch:{index + 1:04d}:precise_long_term_constraint",
                    "fact": f"第{index + 1:04d}条精确长期事实仍然有效",
                }
                for index in range(935)
            ],
            "stage_archives": [
                {
                    "id": f"SA-{index + 1:04d}",
                    "start_chapter_index": index * 10 + 1,
                    "end_chapter_index": index * 10 + 10,
                    "summary": f"第{index + 1}阶段摘要",
                }
                for index in range(24)
            ],
        }
        return project

    def test_outline_context_requests_compact_outline(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["text"] = "赵明在城门外看见旧案告示。"
        project = self._project_with_current_chapter(current)

        context = _build_chapter_ai_context(project, 0, "outline")

        self.assertIn("只输出短提纲", context)
        self.assertIn("6-10 条", context)
        self.assertIn("600-1200 字", context)
        self.assertIn("不要输出正文、对白或长段场景描写", context)
        self.assertIn("正文草稿为唯一事实来源", context)
        self.assertIn("正文没发生", context)

    def test_foreshadow_business_code_resolves_without_weakening_alias_checks(self):
        project = self._project_with_current_chapter(_new_chapter(0))
        project["foreshadow_items"] = [
            {
                "id": f"foreshadow-{index}",
                "code": f"F{index:04d}",
                "name": f"伏笔{index}",
            }
            for index in range(1, 21)
        ]

        self.assertEqual(
            _resolve_long_form_record_ref(project, "foreshadows", "F020"),
            "foreshadow-20",
        )
        self.assertEqual(
            _resolve_long_form_record_ref(project, "foreshadows", "F0020"),
            "foreshadow-20",
        )
        self.assertEqual(
            _resolve_long_form_record_ref(project, "foreshadows", "F9999"),
            "",
        )

    def test_foreshadow_alias_and_business_code_collision_is_rejected(self):
        project = self._project_with_current_chapter(_new_chapter(0))
        project["foreshadow_items"] = [
            {
                "id": f"foreshadow-{index}",
                "code": "F0020" if index == 1 else f"F{index + 100:04d}",
                "name": f"伏笔{index}",
            }
            for index in range(1, 21)
        ]

        self.assertEqual(
            _resolve_long_form_record_ref(project, "foreshadows", "F020"),
            "",
        )

    def test_reverse_context_uses_next_outline_only_for_ai_memory_selection(self):
        current = _new_chapter(0)
        current["title"] = "第一章 半枚虎符"
        current["outline"] = "主角拿到半枚虎符，后续第二章才追查来源。"
        current["text"] = "赵明只在门缝里看见半枚虎符。"
        future = _new_chapter(1)
        future["title"] = "第二章 虎符来源"
        future["outline"] = "第二章才揭晓虎符来自旧案内鬼。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, future]

        outline_context = _build_chapter_ai_context(project, 0, "outline")
        summary_context = _build_chapter_ai_context(project, 0, "summary")

        self.assertNotIn("【后续规划 / 边界】", outline_context)
        self.assertNotIn("第二章才揭晓虎符来自旧案内鬼", outline_context)
        self.assertIn("正文没有写到的内容不要写入摘要或关键事实", summary_context)
        self.assertNotIn("正文风格：口语化", outline_context)
        self.assertNotIn("正文风格：口语化", summary_context)
        self.assertNotIn("去 AI 味要求", outline_context)
        self.assertNotIn("去 AI 味要求", summary_context)
        self.assertNotIn("【后续规划 / 边界】", summary_context)
        self.assertIn("【AI资料更新与下一章选择索引】", summary_context)
        self.assertIn("第二章才揭晓虎符来自旧案内鬼", summary_context)
        self.assertIn("正文没有写到的内容不要写入摘要或关键事实", summary_context)

    def test_selection_index_has_stable_budget_and_keeps_selected_record_details(self):
        current = _new_chapter(0)
        current["memory_selection"] = {
            "character_ids": ["char-239"],
            "lore_ids": ["lore-239"],
            "foreshadow_ids": ["foreshadow-239"],
            "fact_ids": ["AF-0240"],
            "stage_archive_ids": ["SA-0024"],
        }
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {
                "id": f"char-{index}",
                "name": f"人物{index}",
                "role": f"第{index}号人物的永久身份说明" * 4,
            }
            for index in range(240)
        ]
        project["lore"] = [
            {
                "id": f"lore-{index}",
                "name": f"设定{index}",
                "type": "组织",
                "description": f"第{index}号设定的永久定义" * 4,
            }
            for index in range(240)
        ]
        project["foreshadow_items"] = [
            {
                "id": f"foreshadow-{index}",
                "code": f"F{index + 1:04d}",
                "name": f"伏笔{index}",
                "status": "已埋",
                "revealed": f"第{index}号伏笔已经公开的线索" * 4,
            }
            for index in range(240)
        ]
        project["long_form_memory"] = {
            "revision": 240,
            "active_facts": [
                {
                    "id": f"AF-{index + 1:04d}",
                    "scope": f"case:item:{index}",
                    "fact": f"第{index}号长期事实" * 8,
                }
                for index in range(240)
            ],
            "stage_archives": [
                {
                    "id": f"SA-{index + 1:04d}",
                    "start_chapter_index": index * 10 + 1,
                    "end_chapter_index": index * 10 + 10,
                    "summary": f"第{index + 1}阶段档案摘要" * 8,
                }
                for index in range(24)
            ],
        }

        index_text = _build_long_form_selection_index(
            project, 0, selection=current["memory_selection"]
        )

        self.assertLessEqual(len(index_text), LONG_FORM_SELECTION_INDEX_LIMIT)
        self.assertIn("当前章已选择记录详情", index_text)
        self.assertIn("人物239", index_text)
        self.assertIn("第239号人物的永久身份说明", index_text)
        self.assertIn("设定239", index_text)
        self.assertIn("伏笔239", index_text)
        self.assertIn("AF-0240", index_text)
        self.assertIn("SA-0024", index_text)
        self.assertIn("全量紧凑引用目录", index_text)

    def test_normalize_project_removes_legacy_foreshadow_handoff(self):
        chapter = _new_chapter(0)
        chapter["memory_selection"] = {
            "character_ids": ["char-a"],
            "foreshadow_ids": ["foreshadow-old"],
        }
        normalized = _normalize_project(self._project_with_current_chapter(chapter))
        self.assertNotIn("foreshadow_ids", normalized["chapters"][0]["memory_selection"])

    def test_normalize_project_does_not_guess_replace_prose_aliases(self):
        chapter = _new_chapter(0)
        chapter["text"] = "她离开L014后，没有回头。"
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{"id": "lore-a", "name": "影像社器材室", "type": "地点"}]
        normalized = _normalize_project(project)
        self.assertEqual(normalized["chapters"][0]["text"], chapter["text"])

    def test_selected_foreshadow_detail_restores_source_plan_and_history_boundary(self):
        current = _new_chapter(0)
        current["memory_selection"] = {
            "foreshadow_ids": ["foreshadow-selected"],
        }
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "id": "foreshadow-selected",
                "code": "F0016",
                "name": "离开校园后的身份焦虑",
                "status": "未埋",
                "description": "贺知微面对毕业与求职时发现路人甲身份不能解决现实压力。",
                "setup_chapter": "第64章",
                "payoff_chapter": "第106章",
                "revealed": "当前只确认她仍在寻找现实出口。",
                "remaining_secret": "她是否能回到穿书前的人生。",
            },
            {
                "id": "foreshadow-other",
                "code": "F0021",
                "name": "贺知微的存在感变弱",
                "status": "未埋",
                "description": "不应进入当前选中伏笔的详情。",
                "setup_chapter": "第83章",
                "payoff_chapter": "第140章",
            },
        ]
        project["long_form_memory"] = {
            "schema_version": 2,
            "revision": 7,
            "record_runtime": {
                "foreshadows": {
                    "foreshadow-selected": {
                        "state": "未埋",
                        "developments": [
                            {
                                "chapter_index": 4,
                                "changes": ["旧章节曾观察到相关线索"],
                            }
                        ],
                    }
                }
            },
            "active_facts": [],
            "stage_archives": [],
        }

        index_text = _build_long_form_selection_index(
            project, 0, selection=current["memory_selection"]
        )

        self.assertIn("伏笔原始说明：贺知微面对毕业与求职时发现路人甲身份不能解决现实压力。", index_text)
        self.assertIn("计划埋设：第64章", index_text)
        self.assertIn("计划回收：第106章", index_text)
        self.assertIn("历史运行观察（仅供参考，不能替代本章正文证据）", index_text)
        self.assertIn("旧章节曾观察到相关线索", index_text)
        self.assertNotIn("不应进入当前选中伏笔的详情", index_text)

    def test_draft_foreshadow_route_overrides_legacy_selection_and_open_queue(self):
        chapters = [_new_chapter(index) for index in range(3)]
        chapters[0]["title"] = "第一章 开场"
        chapters[1]["title"] = "第二章 当前"
        chapters[1]["outline"] = "本章推进当前冲突。"
        chapters[1]["memory_selection"] = {
            "foreshadow_ids": ["legacy-foreshadow"],
        }
        chapters[2]["title"] = "第三章 后续"
        project = self._project_with_current_chapter(chapters[1])
        project["chapters"] = chapters
        project["foreshadow_items"] = [
            {
                "id": "planned-foreshadow",
                "code": "F0001",
                "name": "当前正式线索",
                "setup_chapter": "第二章",
                "payoff_chapter": "第三章",
                "description": "本章应该正式出现的完整线索说明。",
            },
            {
                "id": "legacy-foreshadow",
                "code": "F0002",
                "name": "旧选择伏笔",
                "setup_chapter": "第十章",
                "payoff_chapter": "第二十章",
                "description": "不能因旧章节选择记录进入本章。",
            },
            {
                "id": "open-foreshadow",
                "code": "F0003",
                "name": "未到章节伏笔",
                "setup_chapter": "第八章",
                "payoff_chapter": "第十二章",
                "description": "未命中计划时不主动传入。",
            },
        ]

        context = _build_chapter_ai_context(project, 1, "draft")
        foreshadow_section = self._context_section(context, "本章相关伏笔")

        self.assertIn("当前正式线索", foreshadow_section)
        self.assertIn("本章阶段：正式埋设", foreshadow_section)
        self.assertIn("完整说明：本章应该正式出现的完整线索说明。", foreshadow_section)
        self.assertNotIn("旧选择伏笔", foreshadow_section)
        self.assertNotIn("未到章节伏笔", foreshadow_section)
        self.assertNotIn("开放伏笔队列", foreshadow_section)

    def test_memory_finalize_context_uses_current_route_not_legacy_foreshadow_selection(self):
        chapters = [_new_chapter(index) for index in range(3)]
        chapters[1]["title"] = "第二章 当前"
        chapters[1]["memory_selection"] = {"foreshadow_ids": ["legacy-foreshadow"]}
        project = self._project_with_current_chapter(chapters[1])
        project["chapters"] = chapters
        project["foreshadow_items"] = [
            {
                "id": "planned-foreshadow",
                "code": "F0001",
                "name": "当前正式线索",
                "status": "未埋",
                "setup_chapter": "第二章",
                "payoff_chapter": "第三章",
                "description": "当前路由必须传给整理的完整说明。",
            },
            {
                "id": "legacy-foreshadow",
                "code": "F0002",
                "name": "旧选择伏笔",
                "status": "已埋",
                "setup_chapter": "第十章",
                "payoff_chapter": "第二十章",
                "description": "旧选择不应作为当前整理的主动伏笔。",
            },
        ]

        context = _build_long_form_memory_finalize_context(
            project, 1, "正文中出现了当前正式线索的具体证据。"
        )
        selection_section = self._context_section(context, "AI资料更新与下一章选择索引")

        self.assertIn("当前路由必须传给整理的完整说明。", selection_section)
        self.assertIn("计划埋设：第二章", selection_section)
        self.assertNotIn("旧选择不应作为当前整理的主动伏笔。", selection_section)

    def test_memory_repair_and_reconcile_contexts_restore_current_route_details(self):
        current = _new_chapter(0)
        current["title"] = "第一章 当前"
        current["memory_selection"] = {"foreshadow_ids": ["legacy-foreshadow"]}
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "id": "planned-foreshadow",
                "code": "F0001",
                "name": "当前正式线索",
                "status": "未埋",
                "setup_chapter": "第一章",
                "payoff_chapter": "第二章",
                "description": "修复和对账都必须看到的完整说明。",
            },
            {
                "id": "legacy-foreshadow",
                "code": "F0002",
                "name": "旧选择伏笔",
                "status": "已埋",
                "setup_chapter": "第十章",
                "payoff_chapter": "第二十章",
                "description": "旧选择说明。",
            },
        ]
        update = self._strict_update(project)
        repair = _build_long_form_memory_repair_context(
            project,
            0,
            "正文中出现了当前正式线索的具体证据。",
            memory_update=update,
            validation_errors=["state_reconciliation.foreshadow_refs遗漏：F0001"],
        )
        reconcile = _build_long_form_memory_reconcile_context(
            project,
            0,
            "正文中出现了当前正式线索的具体证据。",
            update,
        )

        self.assertIn("修复和对账都必须看到的完整说明。", repair)
        self.assertIn("修复和对账都必须看到的完整说明。", reconcile)
        self.assertNotIn("旧选择说明。", repair)
        self.assertNotIn("旧选择说明。", reconcile)

    def test_draft_foreshadow_route_marks_same_setup_and_payoff_chapter(self):
        current = _new_chapter(0)
        current["title"] = "第一章 同时落点"
        current["outline"] = "本章完成一次短线索的出现和解释。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [{
            "code": "F0001",
            "name": "一次性线索",
            "setup_chapter": "第一章",
            "payoff_chapter": "第一章",
            "description": "同一章完成出现与解释。",
        }]

        context = _build_chapter_ai_context(project, 0, "draft")
        foreshadow_section = self._context_section(context, "本章相关伏笔")

        self.assertIn("正式埋设 + 正式回收", foreshadow_section)
        self.assertIn("计划埋设：第一章", foreshadow_section)
        self.assertIn("计划回收：第一章", foreshadow_section)

        compact_contract = _long_form_update_contract_instructions(project, 0, compact=True)
        self.assertIn("历史运行观察是旧章节的观察记录，不能替代本章最终正文证据", compact_contract)
        self.assertIn("本章伏笔是否更新必须以最终正文中的evidence_quote和当前正文语义为准", compact_contract)

    def test_selection_index_expands_past_15k_before_dropping_reference_coverage(self):
        current = _new_chapter(0)
        current["memory_selection"] = {
            "character_ids": ["char-0", "char-5", "char-10", "char-19"],
            "fact_ids": [f"AF-{index + 1:04d}" for index in range(379, 392)],
        }
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"id": f"char-{index}", "name": f"人物{index}", "role": f"人物{index}的稳定身份"}
            for index in range(20)
        ]
        project["lore"] = [
            {"id": f"lore-{index}", "name": f"设定{index}", "type": "组织"}
            for index in range(27)
        ]
        project["foreshadow_items"] = [
            {
                "id": f"foreshadow-{index}",
                "code": f"F{index + 1:04d}",
                "name": f"伏笔{index}",
                "status": "已埋",
            }
            for index in range(21)
        ]
        project["long_form_memory"] = {
            "revision": 99,
            "active_facts": [
                {
                    "id": f"AF-{index + 1:04d}",
                    "scope": f"medical_case:C001:branch_{index}:continuity_constraint",
                    "fact": f"第{index + 1}条仍需继承的精确事实，不能被后续宽泛概括覆盖。",
                }
                for index in range(392)
            ],
            "stage_archives": [
                {
                    "id": f"SA-{index + 1:04d}",
                    "start_chapter_index": index * 10 + 1,
                    "end_chapter_index": index * 10 + 10,
                    "summary": f"第{index + 1}阶段摘要",
                }
                for index in range(9)
            ],
        }

        index_text = _build_long_form_selection_index(project, 0)

        self.assertGreater(len(index_text), 15000)
        self.assertLessEqual(len(index_text), LONG_FORM_SELECTION_INDEX_LIMIT)
        self.assertNotIn("已按字符预算压缩省略", index_text)
        self.assertIn("人物20项，设定27项，伏笔21项，活跃事实392项，阶段档案9项", index_text)
        self.assertIn("C001=人物0", index_text)
        self.assertIn("C010=人物9", index_text)
        self.assertIn("C020=人物19", index_text)
        self.assertIn("L027=设定26", index_text)
        self.assertIn("F021=F0021|伏笔20", index_text)
        self.assertIn("AF-0001=medical_case:C001:branch_0:continuity_constraint", index_text)
        self.assertIn("AF-0392=medical_case:C001:branch_391:continuity_constraint", index_text)
        self.assertIn("SA-0009=第81-90章", index_text)

    def test_250_chapter_selection_index_keeps_every_reference_within_budget(self):
        project = self._large_250_chapter_state_project()

        index_text = _build_long_form_selection_index(project, 249)
        state_directory = _build_long_form_state_directory(project)

        self.assertLessEqual(len(index_text), LONG_FORM_SELECTION_INDEX_LIMIT)
        self.assertLessEqual(len(state_directory), 18000)
        self.assertIn(
            "活跃事实935项，阶段档案24项，人物状态80项，关系状态60项，"
            "物件状态250项，活跃冲突100项，未决任务130项",
            index_text,
        )
        for ref in (
            [f"AF-{index + 1:04d}" for index in range(935)]
            + [f"OBJ-{index + 1:04d}" for index in range(250)]
            + [f"CF-{index + 1:04d}" for index in range(100)]
            + [f"TASK-{index + 1:04d}" for index in range(130)]
        ):
            self.assertIn(ref, index_text)
        self.assertIn("C080", index_text)
        self.assertIn("F070", index_text)
        self.assertIn("SA-0024", index_text)
        self.assertIn("OBJ-0250", state_directory)
        self.assertIn("CF-0100", state_directory)
        self.assertIn("TASK-0130", state_directory)
        self.assertIn("OBJ-0250=关键物件0250", index_text)
        self.assertIn("CF-0100=第0100项冲突", index_text)
        self.assertIn("TASK-0130=第0130项任务", index_text)

    def test_250_chapter_memory_finalize_context_keeps_full_index_under_120k(self):
        project = self._large_250_chapter_state_project()
        final_text = "赵明核对完最后一页卷宗，确认旧案仍有三条线索需要继续追查。" * 30

        context = _build_long_form_memory_finalize_context(project, 249, final_text)
        index_section = self._context_section(context, "AI资料更新与下一章选择索引")

        self.assertLessEqual(
            len(context),
            NOVEL_AI_CONTEXT_LIMIT - LONG_FORM_CONTEXT_SAFETY_MARGIN + 16,
        )
        self.assertIn(final_text, context)
        self.assertIn("AF-0935", index_section)
        self.assertIn("OBJ-0250", index_section)
        self.assertIn("CF-0100", index_section)
        self.assertIn("TASK-0130", index_section)
        self.assertIn("C080=人物079", index_section)
        self.assertIn("L090=设定089", index_section)
        self.assertIn("F070=F0070｜伏笔069", index_section)
        self.assertLessEqual(
            len(index_section),
            LONG_FORM_MEMORY_FINALIZE_INDEX_LIMIT + LONG_FORM_MEMORY_IDENTITY_INDEX_LIMIT,
        )
        self.assertIn(
            f"state_lifecycle_review.scope必须为{LONG_FORM_STAGE_REVIEW_SCOPE}",
            context,
        )
        self.assertIn("全部未触及状态由程序原样继承，并按数量和SHA256核验", context)

    def test_memory_finalize_compact_index_keeps_selected_details_and_global_record_names(self):
        project = self._large_250_chapter_state_project()
        project["chapters"][249]["memory_selection"] = {
            "character_ids": ["char-079"],
            "lore_ids": ["lore-089"],
            "foreshadow_ids": ["foreshadow-069"],
            "fact_ids": ["AF-0935"],
            "stage_archive_ids": ["SA-0024"],
            "object_keys": ["OBJ-0250"],
            "conflict_ids": ["CF-0100"],
            "task_ids": ["TASK-0130"],
            "_restrict_state": True,
        }
        final_text = "赵明核对卷宗，确认最后一项任务仍需继续。" * 120

        context = _build_long_form_memory_finalize_context(project, 249, final_text)
        index_section = self._context_section(context, "AI资料更新与下一章选择索引")

        facts_section = self._context_section(context, "本章已选活跃事实详情")
        archive_section = self._context_section(context, "近期阶段档案")

        self.assertLess(len(context), 50000)
        self.assertIn("事实 AF-0935", index_section)
        self.assertIn("OBJ-0250", index_section)
        self.assertIn("CF-0100", index_section)
        self.assertIn("TASK-0130", index_section)
        self.assertIn("C080=人物079", index_section)
        self.assertIn("L090=设定089", index_section)
        self.assertIn("F070=F0070｜伏笔069", index_section)
        self.assertNotIn("AF-0001", index_section)
        self.assertNotIn("OBJ-0001", index_section)
        self.assertNotIn("CF-0001", index_section)
        self.assertNotIn("TASK-0001", index_section)
        self.assertNotIn("【本章已选状态详情】", context)
        self.assertIn("全局紧凑状态目录", index_section)
        self.assertNotIn("last_reviewed_at", index_section)
        self.assertNotIn("source_chapter_id", facts_section)
        self.assertNotIn("catalog_integrity", archive_section)
        self.assertIn("AF-0935｜", facts_section)
        self.assertIn("SA-0024", archive_section)
        self.assertNotIn("SA-0023", archive_section)

    def test_next_chapter_selection_persists_state_refs_and_only_expands_selected_details(self):
        current = _new_chapter(0)
        following = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, following]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {
                "object_states": [
                    {"key": "账册", "name": "账册", "state": "由赵明保管"},
                    {"key": "旧钥匙", "name": "旧钥匙", "state": "留在边城"},
                ],
                "active_conflicts": [
                    {"id": "CF-0001", "conflict": "追兵仍在逼近"},
                    {"id": "CF-0002", "conflict": "边城争端仍未解决"},
                ],
                "unresolved_tasks": [
                    {"id": "TASK-0001", "task": "核对账册"},
                    {"id": "TASK-0002", "task": "返回边城"},
                ],
            },
        }
        update = self._strict_update(project)
        update["next_chapter_memory"] = {
            "character_refs": [],
            "lore_refs": [],
            "foreshadow_refs": [],
            "fact_refs": [],
            "stage_archive_refs": [],
            "object_keys": ["账册"],
            "conflict_refs": ["CF-0001"],
            "task_refs": ["TASK-0001"],
            "reason": "下一章继续核账并躲避追兵",
        }

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        selection = project["chapters"][1]["memory_selection"]
        self.assertEqual(selection["object_keys"], ["账册"])
        self.assertEqual(selection["conflict_ids"], ["CF-0001"])
        self.assertEqual(selection["task_ids"], ["TASK-0001"])
        self.assertTrue(selection["_restrict_state"])
        sections = _long_form_memory_sections(project, selection)
        selected_snapshot = json.loads(sections["当前状态快照"])
        self.assertEqual([item["key"] for item in selected_snapshot["object_states"]], ["账册"])
        self.assertEqual([item["id"] for item in selected_snapshot["active_conflicts"]], ["CF-0001"])
        self.assertEqual([item["id"] for item in selected_snapshot["unresolved_tasks"]], ["TASK-0001"])
        self.assertIn("旧钥匙", sections["全局紧凑状态目录"])
        self.assertIn("CF-0002", sections["全局紧凑状态目录"])
        self.assertIn("TASK-0002", sections["全局紧凑状态目录"])

    def test_tenth_chapter_state_lifecycle_review_covers_and_retires_all_state_types(self):
        chapters = [_new_chapter(index) for index in range(11)]
        project = self._project_with_current_chapter(chapters[9])
        project["chapters"] = chapters
        project["chapters"][9]["memory_selection"] = {
            "object_keys": ["药瓶"],
            "conflict_ids": ["CF-0002"],
            "task_ids": ["TASK-0002"],
        }
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 9,
            "state_snapshot": {
                "object_states": [
                    {"key": "账册", "name": "账册", "state": "仍由赵明保管"},
                    {"key": "药瓶", "name": "药瓶", "state": "已经用完"},
                ],
                "active_conflicts": [
                    {"id": "CF-0001", "conflict": "旧案争端继续"},
                    {"id": "CF-0002", "conflict": "门口冲突已经结束"},
                ],
                "unresolved_tasks": [
                    {"id": "TASK-0001", "task": "继续追查旧案"},
                    {"id": "TASK-0002", "task": "完成现场急救"},
                ],
            },
        }
        update = self._strict_update(project, 9)
        update["state_retirements"] = {
            "object_keys": ["药瓶"],
            "conflict_ids": ["CF-0002"],
            "task_ids": ["TASK-0002"],
        }
        update["state_reconciliation"]["object_keys"] = ["药瓶"]
        update["state_reconciliation"]["conflict_refs"] = ["CF-0002"]
        update["state_reconciliation"]["task_refs"] = ["TASK-0002"]
        update["long_term_events"] = [{
            "event": "现场急救结束并退出已完成状态",
            "category": "task",
            "evidence_quote": "现场急救已经结束",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": ["药瓶"],
                "conflict_refs": ["CF-0002"], "task_refs": ["TASK-0002"],
            },
        }]
        update["stage_archive"] = {
            "summary": "前十章完成入城和现场急救。",
            "irreversible_facts": [],
            "relationship_changes": [],
            "unresolved_threads": ["旧案仍待追查"],
            "next_stage_entry": "继续核对账册。",
        }

        missing_errors = _validate_long_form_memory_update(
            project, 9, update, final_text="现场急救已经结束。",
            require_revision=True, require_evidence=True,
        )
        self.assertTrue(any("状态生命周期复核遗漏物件" in error for error in missing_errors))
        self.assertTrue(any("状态生命周期复核遗漏冲突" in error for error in missing_errors))
        self.assertTrue(any("状态生命周期复核遗漏任务" in error for error in missing_errors))

        update["state_lifecycle_review"] = {
            "scope": LONG_FORM_STAGE_REVIEW_SCOPE,
            "reviewed_object_keys": ["药瓶"],
            "reviewed_conflict_refs": ["CF-0002"],
            "reviewed_task_refs": ["TASK-0002"],
            "notes": "只复核本章触及并退出的状态",
        }
        self.assertEqual(
            _validate_long_form_memory_update(
                project, 9, update, final_text="现场急救已经结束。",
                require_revision=True, require_evidence=True,
            ),
            [],
        )
        self.assertTrue(_apply_long_form_memory_update(project, 9, update))
        snapshot = project["long_form_memory"]["state_snapshot"]
        self.assertEqual([item["key"] for item in snapshot["object_states"]], ["账册"])
        self.assertEqual([item["id"] for item in snapshot["active_conflicts"]], ["CF-0001"])
        self.assertEqual([item["id"] for item in snapshot["unresolved_tasks"]], ["TASK-0001"])
        self.assertEqual(
            project["chapters"][9]["state_lifecycle_review"]["scope"],
            LONG_FORM_STAGE_REVIEW_SCOPE,
        )
        self.assertTrue(project["chapters"][9]["memory_boundary_integrity"]["verified"])

    def test_chapter_context_prioritizes_linked_character_beyond_first_batch(self):
        current = _new_chapter(0)
        current["title"] = "第四十一章 风雪夜谈"
        current["outline"] = "主角向迟到主角追问旧案。"
        current["linked_characters"] = ["迟到主角"]
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].append({
            "name": "迟到主角",
            "role": "旧案关键证人",
            "goal": "保住证据",
            "secret": "知道名册被换过",
            "voice": "说话谨慎",
            "notes": "本章必须出现",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关人物】", context)
        self.assertIn("迟到主角", context)
        self.assertIn("旧案关键证人", context)
        self.assertNotIn("路人0", context)

    def test_chapter_draft_words_controls_draft_prompt_without_using_project_total(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        current["draft_words"] = "3000"
        project = self._project_with_current_chapter(current)
        project["meta"]["target_words"] = "20万"

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章写作长度】", context)
        self.assertIn("本章扩写字数：3000字", context)
        self.assertIn("本次新增正文参考目标：约3000字", context)
        self.assertIn("正文长度控制目标", context)
        self.assertIn("目标的85%-115%", context)
        self.assertIn("连续超出会破坏整书总字数和节奏", context)
        self.assertIn("不要为了贴字数牺牲完整场景", context)
        self.assertIn("正文风格：口语化、自然、有网文阅读感", context)
        self.assertIn("不要太工整、太书面、太像范文", context)
        self.assertIn("句子长短混用", context)
        self.assertIn("不要写成流水账", context)
        self.assertIn("不得写段尾总结、抽象情绪判断和万能反应动作", context)
        self.assertIn("不得用“沉默、皱眉、冷意、压迫感、空气安静、所有人愣住、下一秒”等模板化表达替代具体剧情", context)
        self.assertIn("【对白自然衔接】", context)
        self.assertIn("需要说明来由、指代或态度时，把意思说清楚", context)
        self.assertIn("场景描写优先用具体物件、动作和细节承载情绪", context)
        self.assertIn("不得用解释式、观点式和“金句式”抽象表达", context)
        self.assertIn("段落结构要有变化", context)
        self.assertNotIn("对白要有真人说话的不完整感", context)
        self.assertNotIn("对白不要每句都完整、漂亮、逻辑闭合", context)
        self.assertIn("场景细节要克制", context)
        self.assertIn("少量加入具体物件、声音、动作痕迹和环境反馈", context)
        self.assertIn("不要写无意义生活噪声", context)
        self.assertIn("优先让人物在具体环境里做事、被打断、受阻、临时反应", context)
        self.assertIn("完整收束确有必要时可以略微超出", context)
        self.assertIn("不得用重复解释、重复反应或同义对白扩充篇幅", context)
        self.assertNotIn("2970-3150字", context)
        self.assertNotIn("严格长度约束", context)
        self.assertIn("项目总目标字数：20万字", context)
        self.assertIn("不要把项目总字数当作单章输出字数", context)

    def test_draft_context_includes_full_raw_style_reference_only_for_draft(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        project = self._project_with_current_chapter(current)
        project["style_reference"] = "第一段样本文。\n\n第二段样本文，保留段落格式。"

        draft_context = _build_chapter_ai_context(project, 0, "draft")
        outline_context = _build_chapter_ai_context(project, 0, "outline")

        guidance = self._context_section(draft_context, "仿写使用说明")
        self.assertIn("【正文风格参考】", draft_context)
        self.assertIn("【仿写使用说明】", draft_context)
        self.assertIn("【正文自然表达边界】", draft_context)
        self.assertIn("第一段样本文。\n\n第二段样本文，保留段落格式。", draft_context)
        self.assertIn("完整原文", guidance)
        self.assertIn("当前项目资料是本章故事事实", guidance)
        self.assertIn("正文必须使用自然的网络小说叙述语言", draft_context)
        self.assertIn("不得出现策划术语、抽象形容", draft_context)
        self.assertIn("情绪和气氛必须通过人物当下的动作", draft_context)
        self.assertIn("不得把参考原文的人物、剧情、物件或句子带入当前正文", guidance)
        self.assertNotIn("空得很有存在感", draft_context)
        self.assertNotIn("沉默很有情绪", draft_context)
        self.assertIn("【正文语言要求】", guidance)
        self.assertIn("文学化意象、空泛比喻", draft_context)
        self.assertNotIn("比喻可以自由使用", guidance)
        expression_boundary = self._context_section(draft_context, "正文自然表达边界")
        self.assertLess(len(expression_boundary), 500)
        self.assertLessEqual(len(guidance), 1200)
        self.assertNotIn("【风格锁定规则】", draft_context)
        self.assertNotIn("【AI文风画像】", draft_context)
        self.assertNotIn("【作者原生用词池", draft_context)
        self.assertNotIn("【V4 人物与叙述声纹", draft_context)
        self.assertNotIn("【V4 条件性叙事技法", draft_context)
        self.assertNotIn("段落节奏骨架", draft_context)
        self.assertGreater(draft_context.rfind("【正文风格参考】"), draft_context.find("【当前章节】"))
        self.assertGreater(draft_context.rfind("【仿写使用说明】"), draft_context.find("【当前章节】"))
        self.assertGreater(draft_context.rfind("【正文自然表达边界】"), draft_context.rfind("【正文风格参考】"))
        self.assertNotIn("【正文风格参考】", outline_context)
        self.assertNotIn("【仿写使用说明】", outline_context)
        self.assertNotIn("【正文自然表达边界】", outline_context)

    def test_style_execution_context_keeps_chapter_after_task_mentions_style_headings(self):
        original = "\n\n".join([
            "【项目核心信息】\n书名：测试小说",
            (
                "【本次任务】\n"
                "以【仿写使用说明】和【正文风格参考】中的完整原样本作为写法来源。"
            ),
            "【当前章节】\n章节标题：房卡从掌心掉下来\n关联人物：沈知夏、林薇",
            "【世界观 / 规则】\n谎言成物需要女主亲耳听见谎言，且会带来耳鸣。",
            "【仿写使用说明】\n旧说明，不应在最终上下文重复保留。",
            "【正文风格参考】\n旧样本文本，不应在最终上下文重复保留。",
        ])

        context = _build_style_execution_context(
            original,
            style_reference="新样本文本。",
        )

        self.assertIn("【当前章节】", context)
        self.assertIn("房卡从掌心掉下来", context)
        self.assertIn("沈知夏、林薇", context)
        self.assertIn("【世界观 / 规则】", context)
        self.assertIn("新样本文本。", context)
        self.assertNotIn("旧说明，不应在最终上下文重复保留。", context)
        self.assertNotIn("旧样本文本，不应在最终上下文重复保留。", context)
        self.assertLess(context.find("【当前章节】"), context.rfind("【仿写使用说明】"))

    def test_draft_style_guidance_stays_simple_for_different_samples(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        current["draft_words"] = "3000"

        dense_project = self._project_with_current_chapter(current)
        dense_project["style_reference"] = "\n".join(
            f"短段落{i}。" for i in range(120)
        )
        long_project = self._project_with_current_chapter(dict(current))
        long_project["style_reference"] = "\n".join(
            (f"这是第{i}个长段落，" + "叙述持续展开，人物在环境中观察并作出判断，" * 8 + "事情才告一段落。")
            for i in range(10)
        )

        dense_context = _build_chapter_ai_context(dense_project, 0, "draft")
        long_context = _build_chapter_ai_context(long_project, 0, "draft")

        dense_guidance = self._context_section(dense_context, "仿写使用说明")
        long_guidance = self._context_section(long_context, "仿写使用说明")
        for guidance in (dense_guidance, long_guidance):
            self.assertGreaterEqual(len(guidance), 500)
            self.assertLessEqual(len(guidance), 1200)
            self.assertIn("完整原文", guidance)
            self.assertNotIn("段落排版指标", guidance)
            self.assertNotIn("语言画像", guidance)
        self.assertIn(dense_project["style_reference"], dense_context)
        self.assertIn(long_project["style_reference"], long_context)

    def test_full_author_sheet_contexts_cover_baseline_evidence_merge_persona_and_rules(self):
        reference = "\n\n".join(
            f"样本第{i}段，人物在场景中持续处理冲突并说明前因后果。" * 8
            for i in range(80)
        )
        units = _build_style_profile_units(reference, max_units=10, target_chars=2200)

        self.assertGreaterEqual(len(units), 5)
        self.assertLessEqual(len(units), 10)
        self.assertIn("样本第0段", units[0]["source"])
        self.assertIn("样本第79段", units[-1]["source"])

        units[0]["baseline"] = "普通基准正文。"
        units[0]["sheet"] = "语言与格式：作者保留长段铺陈。证据：原文。[1]"
        baseline_context = _build_style_baseline_context(units[0], 1, len(units))
        sheet_context = _build_style_sheet_context(units[0], 1, len(units))
        merge_context = _build_style_sheet_merge_context("旧档案", units[0]["sheet"], 2, len(units))
        persona_context = _build_style_persona_context("合并档案")
        rules_context = _build_style_rules_context(
            "【当前章节】\n主角进入神殿质问祭司。",
            "合并档案",
            "作者人格",
            reference,
        )

        self.assertIn("普通中文小说写法", baseline_context)
        self.assertIn("逐字证据", sheet_context)
        self.assertIn("叙述用词与句法声纹", sheet_context)
        self.assertIn("对白声纹", sheet_context)
        self.assertIn("3800至4800个中文字符", sheet_context)
        self.assertIn("此前合并档案", merge_context)
        self.assertIn("高频", merge_context)
        self.assertIn("稳定", merge_context)
        self.assertIn("局部", merge_context)
        self.assertIn("4800至6000个中文字符", merge_context)
        self.assertIn("第二人称", persona_context)
        self.assertIn("【叙述习惯词与句法声纹】", persona_context)
        self.assertIn("【功能角色说话方式】", persona_context)
        self.assertIn("本章文风执行规则", rules_context)
        self.assertLessEqual(len(rules_context), NOVEL_AI_CONTEXT_LIMIT)
        self.assertEqual(STYLE_SHEET_CACHE_VERSION, 3)

    def test_style_cards_are_exact_sample_excerpts_and_have_build_context(self):
        first_excerpt = (
            "就在这时，他先停下动作，重新看了一遍桌上的记录。"
            "如果前面的判断成立，那么真正需要核对的就不是结果，而是结果出现之前缺失的那一步。"
            "他没有急着下结论，只是把两份记录并到一起，随后让人重新做一次对照。"
            "第一轮结果出来之后，他又看了一遍时间和编号，确认两份记录并不是来自同一个环节。"
            "这一次，先前那个看似合理的解释反而成了最需要排除的可能。"
        )
        second_excerpt = (
            "“已经确认了吗？”他沉声问道。\n"
            "对面的人停顿了一下，低声回答：“还……还没有，只能确定其中一部分。”\n"
            "“那就只说确定的部分。”\n"
            "对面迅速翻动记录，又补充道：“使用时间已经对上了，但中间的交接编号还缺了两段。”\n"
            "他没有催促，只让对方先保留原始文件，再按编号重新核对一次。"
        )
        reference = first_excerpt + "\n\n" + second_excerpt
        raw = json.dumps({"cards": [{
            "category": "推理与解释",
            "title": "对照核验",
            "use_when": "人物根据证据逐步排除可能",
            "avoid_when": "高速动作场面",
            "voice_features": "如果……那么……；随后验证",
            "source_excerpt": first_excerpt,
        }, {
            "category": "专业角色对白",
            "title": "确定性边界",
            "use_when": "专业角色核对证据",
            "avoid_when": "日常闲聊",
            "voice_features": "短问、停顿、只确认已知部分",
            "source_excerpt": second_excerpt,
        }, {
            "category": "章节收束",
            "title": "伪造片段",
            "use_when": "无",
            "avoid_when": "无",
            "voice_features": "无",
            "source_excerpt": "这段文字并不存在于作者原文中。" * 8,
        }]}, ensure_ascii=False)

        cards = _parse_style_cards_result(raw, reference)
        context = _build_style_cards_context(reference, "证据档案", "作者人格")

        self.assertEqual(STYLE_CARD_CACHE_VERSION, 1)
        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["id"], "SC01")
        self.assertEqual(cards[0]["source_excerpt"], first_excerpt)
        self.assertNotIn("伪造片段", [card["title"] for card in cards])
        self.assertIn("【作者完整原文】", context)
        self.assertIn("逐字连续截取", context)
        self.assertIn(first_excerpt, context)

    def test_style_card_selection_keeps_only_one_card_per_function_dimension(self):
        excerpt = "这是一段用于测试功能片段选择的连续作者原文，包含足够长度来通过片段卡校验。" * 8
        cards = [
            {
                "id": "SC01",
                "category": "推理与解释",
                "title": "推理",
                "source_excerpt": excerpt + "甲",
            },
            {
                "id": "SC02",
                "category": "专业角色对白",
                "title": "专业对白",
                "source_excerpt": excerpt + "乙",
            },
            {
                "id": "SC03",
                "category": "权威角色命令",
                "title": "权威命令",
                "source_excerpt": excerpt + "丙",
            },
            {
                "id": "SC04",
                "category": "章节收束",
                "title": "具体收束",
                "source_excerpt": excerpt + "丁",
            },
        ]

        selected = _style_cards_selected_by_plan(
            cards,
            "主叙事模式：调查推理\nSC03用于命令，SC02用于说明，SC01用于显形，SC04用于章末。",
        )

        self.assertEqual([item["id"] for item in selected], ["SC03", "SC01", "SC04"])
        self.assertEqual(
            [item["category"] for item in selected],
            ["权威角色命令", "推理与解释", "章节收束"],
        )

    def test_format_style_cards_preserves_ids_after_subset_selection(self):
        excerpt = "这是一段用于测试文风卡编号稳定性的作者原文。" * 12
        cards = [
            {
                "id": "SC03",
                "category": "权威角色命令",
                "title": "冲突声纹",
                "source_excerpt": excerpt + "甲",
            },
            {
                "id": "SC07",
                "category": "日常口语与喜剧",
                "title": "口语声纹",
                "source_excerpt": excerpt + "乙",
            },
        ]

        formatted = _format_style_cards(cards)

        self.assertIn("【SC03｜权威角色命令｜冲突声纹】", formatted)
        self.assertIn("【SC07｜日常口语与喜剧｜口语声纹】", formatted)
        self.assertNotIn("【SC01｜", formatted)
        self.assertNotIn("【SC02｜", formatted)

    def test_short_chapter_finalize_keeps_conflict_voice_card_with_plot_card(self):
        first_excerpt = "第一张原文卡用于异常显形，连续展示人物看到反馈、形成判断并继续验证。" * 8
        second_excerpt = "第二张原文卡用于权威命令，连续展示命令对象、反馈状态和组织变化。" * 8
        cards = [
            {
                "category": "异常逐步显形",
                "title": "异常显形",
                "source_excerpt": first_excerpt,
            },
            {
                "category": "权威角色命令",
                "title": "权威命令",
                "source_excerpt": second_excerpt,
            },
        ]

        context = _build_style_finalize_context(
            "本章扩写字数：2000字",
            "",
            output_target=2000,
            include_memory=False,
            execution_text="1. 人物发现异常。\n2. 权威者下令处置。",
            style_plan="SC01用于异常显形，SC02用于权威命令。",
            style_cards=cards,
        )

        self.assertIn(first_excerpt, context)
        self.assertNotIn(second_excerpt, context)

    def test_male_style_only_selects_scene_matched_card(self):
        excerpt = "男频原文片段持续展示人物动作、对白停顿、冲突反应和自然口语节拍。" * 10
        cards = [
            {"id": "SC01", "category": "推理与解释", "title": "阶段推理", "source_excerpt": excerpt + "甲"},
            {
                "id": "SC06", "category": "群体反应", "title": "围观群体充当误会裁判",
                "use_when": "公开争执和澄清失败", "voice_features": "误会、反问和立场冲突",
                "source_excerpt": excerpt + "乙",
            },
            {
                "id": "SC07", "category": "日常口语与喜剧", "title": "半句撤回诱导补全",
                "use_when": "熟人闲谈和轻喜剧", "voice_features": "家常称呼、停顿和反差答案",
                "source_excerpt": excerpt + "丙",
            },
        ]

        selected = _style_cards_selected_by_plan(
            cards,
            "主叙事模式：调查推理\nSC01用于本章推理。",
            max_cards=1,
        )

        self.assertEqual([item["category"] for item in selected], ["推理与解释"])

    def test_female_style_only_selects_scene_matched_card(self):
        excerpt = "女频原文片段持续展示人物互呛、动作反制、接话方式和日常喜剧节拍。" * 10
        cards = [
            {"id": "SC01", "category": "异常逐步显形", "title": "异常揭晓", "source_excerpt": excerpt + "甲"},
            {
                "id": "SC03", "category": "权威角色命令", "title": "命令施压遭动作反制",
                "use_when": "对手施压和主角夺回控制", "voice_features": "礼貌打断、反击和拆台",
                "source_excerpt": excerpt + "乙",
            },
            {
                "id": "SC07", "category": "日常口语与喜剧", "title": "字面动作连续拆台",
                "use_when": "日常互呛和轻度冲突", "voice_features": "短句、反问和反差急停",
                "source_excerpt": excerpt + "丙",
            },
        ]

        selected = _style_cards_selected_by_plan(
            cards,
            "主叙事模式：信息揭示\nSC01用于异常揭晓。",
            max_cards=1,
        )

        self.assertEqual([item["category"] for item in selected], ["异常逐步显形"])

    def test_local_style_fingerprint_reports_lexical_and_dialogue_voice(self):
        reference = (
            "就在这时，他猛地回头，瞳孔骤然收缩，随后沉声开口。\n"
            "“等等，你怎么来了？”\n"
            "她下意识后退，脸色煞白，低声说道：“我……我不知道啊。”\n"
        ) * 80

        profile = _build_style_reference_profile(reference, 3000)

        self.assertIn("句首/推理框架", profile)
        self.assertIn("动作修饰词", profile)
        self.assertIn("生理/神态反应", profile)
        self.assertIn("说话标签", profile)
        self.assertIn("对白表达观察", profile)
        self.assertIn("对白高频口语/接话词", profile)

    def test_style_reference_space_is_reserved_in_large_context(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        project = self._project_with_current_chapter(current)
        project["style_reference"] = "风格样本唯一标记。" + "样本文字。" * 1200
        project["bible"] = "圣经资料。" * 3000
        project["world_rules"] = "世界规则。" * 3000
        project["timeline"] = "时间线资料。" * 3000
        project["summary"] = "摘要资料。" * 3000

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertLessEqual(len(context), NOVEL_AI_CONTEXT_LIMIT)
        self.assertIn("【仿写使用说明】", context)
        self.assertIn("【正文风格参考】", context)
        self.assertIn(project["style_reference"], context)
        self.assertNotIn("【作者原生用词池", context)

    def test_style_pipeline_can_use_more_than_legacy_59000_character_limit(self):
        original = "【当前章节资料】\n" + "人物、设定、伏笔和连续性资料。" * 4000
        profile = "作者文风画像。" * 800
        reference = "正文风格样本。" * 1600

        context = _build_style_rules_context(original, profile, "作者人格。" * 300, reference)

        self.assertGreater(len(context), 59000)
        self.assertLessEqual(len(context), NOVEL_AI_CONTEXT_LIMIT)
        self.assertIn("【作者写作档案】", context)
        self.assertIn("【与本章写作功能接近的原文证据】", context)

    def test_large_style_sample_keeps_complete_raw_text_in_draft_context(self):
        current = _new_chapter(0)
        current["title"] = "第一章 冲突"
        current["outline"] = "主角闯入神庙救人，质问祭司，并发现契约规则。"
        current["draft_words"] = "3000"
        project = self._project_with_current_chapter(current)
        paragraphs = ["样本开头唯一标记。"]
        for index in range(520):
            if index % 11 == 0:
                paragraphs.append(f"“这是第{index}次对白。”他说完以后，又直接问出了自己的问题。")
            elif index % 7 == 0:
                paragraphs.append("因为这件事已经发生，所以其中的身份、规则和后果都需要连续解释。" * 3)
            elif index % 5 == 0:
                paragraphs.append("他猛地转身冲了过去，抬手抓住对方，又向后退了两步。")
            else:
                paragraphs.append(f"这是样本中的普通叙述段{index}，如今事情仍在继续。")
        paragraphs.append("样本结尾唯一标记。")
        reference = "\n\n".join(paragraphs)
        project["style_reference"] = reference

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertGreater(len(reference), 8000)
        self.assertIn("样本开头唯一标记", context)
        self.assertIn("样本结尾唯一标记", context)
        self.assertIn(reference, context)
        self.assertIn("【仿写使用说明】", context)
        self.assertNotIn("代表片段", context)
        self.assertNotIn("【风格锁定规则】", context)
        self.assertNotIn("【AI文风画像】", context)
        full_fingerprint = _build_style_reference_profile(reference, 3000)
        self.assertIn("段落功能分布", full_fingerprint)
        self.assertIn("常见段落衔接", full_fingerprint)
        self.assertIn("段落节奏骨架", full_fingerprint)

    def test_large_style_excerpt_selector_preserves_start_end_and_budget(self):
        reference = "\n\n".join(
            ["开头标记。"]
            + [
                ("“对白。”人物继续说话。" if index % 4 == 0 else "因为规则如此，这是一段较长说明。" * 6)
                for index in range(400)
            ]
            + ["结尾标记。"]
        )

        excerpt = _select_style_reference_excerpts(reference, "冲突、对白和规则", 6000)
        fingerprint = _build_style_reference_profile(reference, 3000)

        self.assertLessEqual(len(excerpt), 6000)
        self.assertIn("开头标记", excerpt)
        self.assertIn("结尾标记", excerpt)
        self.assertIn("段落功能分布", fingerprint)
        self.assertIn("高频连接/判断词", fingerprint)

    def test_large_style_audit_uses_stratified_reference_without_losing_boundaries(self):
        reference = "\n\n".join(
            ["审校样本开头标记。"]
            + [
                ("“继续说话。”人物问出了新的问题。" if index % 3 == 0 else "普通叙述继续展开。" * 8)
                for index in range(500)
            ]
            + ["审校样本结尾标记。"]
        )
        candidate = "候选正文。" * 500

        context = _build_style_audit_context(reference, candidate, "完整画像", [])

        self.assertLessEqual(len(context), NOVEL_AI_CONTEXT_LIMIT)
        self.assertIn("从约", context)
        self.assertIn("完整样本分层选取", context)
        self.assertIn("审校样本开头标记", context)
        self.assertIn("审校样本结尾标记", context)
        self.assertIn(candidate, context)
        self.assertNotIn(reference, context)

    def test_style_mismatch_detects_fragmented_draft_and_builds_rewrite_context(self):
        reference = "\n".join(
            (f"样本第{i}段，" + "这是一段连续展开的叙述，用来交代人物关系、处境和事情的前因后果。" * 3)
            for i in range(20)
        )
        fragmented = "\n".join(f"短句{i}。" for i in range(180))

        reasons = _style_draft_mismatch_reasons(reference, fragmented)
        rewrite_context = _build_style_rewrite_context(
            "【当前章节】\n剧情资料。\n\n【风格锁定规则】\n动态规则。\n\n【正文风格参考】\n" + reference,
            fragmented,
            reasons,
        )

        self.assertTrue(any("段落密度偏差过大" in reason for reason in reasons))
        self.assertTrue(any("中长段不足" in reason for reason in reasons))
        self.assertIn("【首次正文，仅作为保留剧情的重写底稿】", rewrite_context)
        self.assertIn("【风格验收未通过：本次必须重写】", rewrite_context)
        self.assertIn("不得用简单合并换行应付验收", rewrite_context)
        self.assertIn("剧情资料", rewrite_context)
        self.assertIn("样本第0段", rewrite_context)
        self.assertLessEqual(len(rewrite_context), NOVEL_AI_CONTEXT_LIMIT)

    def test_style_profile_and_audit_context_keep_raw_sample_and_candidate(self):
        reference = "样本长段。" * 200
        candidate = "候选正文。" * 180
        profile_context = _build_style_profile_request_context(reference)
        draft_context = _append_ai_style_profile_to_context(
            "【当前章节】\n剧情。\n\n【风格锁定规则】\n规则。\n\n【正文风格参考】\n" + reference,
            '{"narrative_voice":"直接"}',
        )
        audit_context = _build_style_audit_context(
            reference,
            candidate,
            '{"narrative_voice":"直接"}',
            ["段落密度偏差过大"],
        )

        self.assertIn(reference, profile_context)
        self.assertIn("只分析写法，不分析或复述剧情", profile_context)
        self.assertIn("【AI文风画像】", draft_context)
        self.assertGreater(draft_context.find("【正文风格参考】"), draft_context.find("【AI文风画像】"))
        self.assertIn(reference, audit_context)
        self.assertIn(candidate, audit_context)
        self.assertIn("段落密度偏差过大", audit_context)
        self.assertIn("如果只是合并换行", audit_context)

    def test_style_finalize_context_and_parser_return_complete_chapter_bundle(self):
        reference = "\n".join(f"样本第{i}段，人物关系和事情缘由持续展开。" for i in range(80))
        draft = "\n".join(f"正文第{i}段，主角继续处理眼前冲突。" for i in range(70))
        context = _build_style_finalize_context(
            "【当前章节】\n剧情资料。\n本章扩写字数：3000字\n\n【正文风格参考】\n" + reference,
            draft,
            '{"narrative_voice":"直接"}',
            reference,
            ["对白字数占比不符"],
            3000,
        )
        returned = (
            "【终稿正文】\n终稿第一段。\n\n终稿第二段。\n\n"
            "【终稿验收】\n"
            '{"beat_evidence":[],"previous_chapter_repetition_check":true,'
            '"paragraph_structure_check":true}\n\n'
            "【实际提纲】\n1. 主角处理冲突。\n\n"
            "【本章摘要】\n主角完成处理。\n\n"
            "【本章需继承的关键事实】\n- 主角留在原地。\n\n"
            "【长篇记忆更新】\n"
            '{"long_form_memory":{"state_snapshot":{"story_time":"当夜","location":"原地"},'
            '"active_facts":[{"id":"fact-1","fact":"主角仍在原地"}],'
            '"state_delta":{"characters":[]},"stage_archive":null}}'
        )
        parsed = _parse_style_finalize_result(returned)

        self.assertIn("【终稿编辑任务】", context)
        self.assertNotIn("对白字数占比不符", context)
        self.assertNotIn("终稿正文控制在2550-3450字", context)
        self.assertIn("自然排版与句式跟随样本读感变化", context)
        self.assertNotIn("非对白35字以内单句短段占比", context)
        self.assertNotIn("beat_evidence", context)
        self.assertNotIn('"opening_continuation"', context)
        self.assertLessEqual(len(context), NOVEL_AI_CONTEXT_LIMIT)
        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["text"], "终稿第一段。\n\n终稿第二段。")
        self.assertTrue(parsed["acceptance"]["paragraph_structure_check"])
        self.assertIn("主角留在原地", parsed["key_facts"])
        self.assertEqual(parsed["memory_update"]["state_snapshot"]["location"], "原地")

        partial = _parse_style_finalize_result(
            "【终稿正文】\n只返回正文。\n\n"
            "【终稿验收】\n"
            '{"previous_chapter_repetition_check":true,"paragraph_structure_check":true}'
        )
        self.assertTrue(partial["parsed"])
        self.assertEqual(partial["text"], "只返回正文。")

    def test_body_only_style_finalize_context_does_not_mix_in_memory_transaction(self):
        reference = "\n".join(
            f"样本第{index}段，人物通过连续叙述和对白自然推进事情。"
            for index in range(80)
        )
        draft = "\n".join(
            f"初稿第{index}段，人物继续处理当前冲突。"
            for index in range(70)
        )
        context = _build_style_finalize_context(
            "【当前章节】\n剧情资料。\n本章扩写字数：3000字\n\n【正文风格参考】\n" + reference,
            draft,
            '{"narrative_voice":"直接"}',
            reference,
            ["段落密度偏差过大", "对白比例不足"],
            3000,
            memory_selection_index="不应进入纯正文终稿",
            project=self._project_with_current_chapter(_new_chapter(0)),
            chapter_index=0,
            include_memory=False,
        )

        self.assertLessEqual(len(context), NOVEL_AI_CONTEXT_LIMIT)
        self.assertIn("【终稿正文】", context)
        self.assertIn("本次只负责小说正文", context)
        self.assertNotIn("段落密度偏差过大", context)
        self.assertNotIn("对白比例不足", context)
        self.assertIn(draft, context)
        self.assertNotIn("【AI资料更新与下一章选择索引】", context)
        self.assertNotIn("【长篇记忆更新】", context)
        self.assertNotIn("不应进入纯正文终稿", context)
        self.assertIn("【终稿验收】", context)
        self.assertNotIn('"long_form_memory"', context)

    def test_style_finalize_severe_rescue_allows_whole_chapter_compression(self):
        reference = "\n".join(
            f"样本第{index}段把人物反应和事情结果自然写在一起。"
            for index in range(80)
        )
        candidate = "\n\n".join(
            f"第{index}个短段。" for index in range(180)
        )
        context = _build_style_finalize_context(
            "【当前章节】\n本章扩写字数：3000字",
            candidate,
            "你的习惯词包括：“立刻”。",
            reference + "她立刻离开。",
            [
                "终稿正文长度明显偏离目标：目标约3000字，终稿约5000字",
                "终稿结构同时向短碎方向漂移：段落密度偏高、短段比例偏高",
                "终稿原生词密度明显高于样本：立刻8次/软上沿1次",
            ],
            3000,
            project=self._project_with_current_chapter(_new_chapter(0)),
            chapter_index=0,
            include_memory=False,
            execution_text="1. 人物完成本章决定。",
            rescue_from_candidate=True,
        )

        self.assertIn("【终稿整章压缩补救】", context)
        self.assertIn("原来的无效换行", context)
        self.assertIn("不能只做少量同义改写", context)
        self.assertIn("重新统计【作者原生用词池】的全部词", context)
        self.assertIn("不能把删掉的超密词换成另一个原生词", context)

    def test_style_execution_builds_fact_ledger_and_keeps_backup_body_separate(self):
        reference = "\n".join(
            f"样本第{index}段，人物关系与事情缘由自然展开。随后人物继续核对新的线索。"
            for index in range(60)
        )
        card_excerpt = (
            "他没有立刻回答，而是重新看向门边留下的脚印。"
            "如果来客真正想拿走证据，就不会在最显眼的位置停留这么久。"
            "这说明对方还有别的目的，不过现在仍然只能把它当成一种判断。"
            "他随后收起桌上的文件，准备通过下一次动作验证。"
            "门外再次传来脚步声时，他没有抬头，只把最重要的那页记录压在手边。"
            "真正的答案还没有出现，但来客下一步会先碰什么，已经足够验证他的判断。"
        )
        style_cards = [{
            "id": "SC01",
            "category": "推理与解释",
            "title": "阶段判断后验证",
            "use_when": "依据现场证据形成暂时判断",
            "avoid_when": "高速战斗",
            "voice_features": "如果……就……；这说明；随后验证",
            "source_excerpt": card_excerpt,
        }]
        context = _build_legacy_style_execution_context(
            "【当前章节】\n本章扩写字数：2000字\n本章需要保全证据并制服来客。\n\n【正文风格参考】\n" + reference,
            "【作者人格】\n你使用连续叙述。",
            style_cards=style_cards,
            style_reference=reference,
        )
        style_plan = (
            "主叙事模式：调查推理\n"
            "选定片段卡：SC01，用于主角根据脚印核验证据。\n"
            "段落执行：普通说明段每段2至4句，非对白单句短段不得连续超过2段。\n"
            "角色声纹矩阵：主角用短问和阶段判断；来客先停顿再否认。"
        )
        returned = (
            "【剧情执行清单】\n"
            "1. 来客闯入，主角先保护证据。\n"
            "2. 主角制服来客，结尾收到融资冻结电话。\n\n"
            f"【本章声纹执行表】\n{style_plan}\n\n"
            "【备用正文草稿】\n来客撞开房门。主角先护住证据，随后制服来客。"
        )

        parsed = _parse_style_execution_result(returned)

        self.assertLessEqual(len(context), NOVEL_AI_CONTEXT_LIMIT)
        self.assertIn("【剧情执行稿任务】", context)
        self.assertIn("【AI文风画像】", context)
        self.assertIn("按自然场景转折列出唯一剧情拍点", context)
        self.assertNotIn("静默连续性边界", context)
        self.assertIn("不要把观察、验证、问答和结论拆成教程步骤", context)
        self.assertNotIn("【功能型原文片段库", context)
        self.assertIn("严格只输出以下三个分区", context)
        self.assertIn("只写1至2名核心人物的口吻", context)
        self.assertNotIn("完整样本结构软参考", context)
        self.assertIn("人物对白、冲突声纹、日常口语与喜剧习惯常驻执行", context)
        self.assertIn("不设置段落、短句或对白数量配额", context)
        self.assertIn("未决任务只用于防止连续性错误，不是本章待办清单", context)
        self.assertIn("当前章节提纲明确安排执行时", context)
        self.assertIn("项目中的连续性事实只用于防止写错，不是额外剧情拍点", context)
        self.assertTrue(parsed["parsed"])
        self.assertTrue(parsed["style_plan_parsed"])
        self.assertIn("融资冻结电话", parsed["execution"])
        self.assertIn("SC01", parsed["style_plan"])
        self.assertEqual(parsed["draft"], "来客撞开房门。主角先护住证据，随后制服来客。")

        finalize = _build_style_finalize_context(
            "【当前章节】\n本章需要保全证据并制服来客。\n\n【正文风格参考】\n" + reference,
            parsed["draft"],
            "【作者人格】\n你使用连续叙述。",
            reference,
            ["段落密度偏差过大"],
            2000,
            include_memory=False,
            execution_text=parsed["execution"],
            style_plan=parsed["style_plan"],
            style_cards=style_cards,
        )
        self.assertIn("剧情执行清单｜只继承事实与顺序，必须从零写作", finalize)
        self.assertIn("【文风重复与推进边界】", finalize)
        self.assertIn("新动作、新信息、新决定、新后果", finalize)
        self.assertIn("【本章声纹执行表｜必须逐项落实】", finalize)
        self.assertIn("【本章选定功能片段卡", finalize)
        self.assertIn(card_excerpt, finalize)
        self.assertNotIn("来客撞开房门。主角先护住证据", finalize)
        self.assertNotIn("【备用正文的本地检测结果", finalize)
        self.assertNotIn("【首轮终稿结构预检", finalize)
        self.assertIn("logic_continuity_check", finalize)
        self.assertIn("把相邻拍点组织成自然场景", finalize)
        self.assertNotIn("【输出前结构防漂移检查】", finalize)
        self.assertIn("段落排版指标已删除", finalize)
        self.assertIn("隐私规则或查询范围最多完整出现一处", finalize)

        medium = _build_legacy_style_execution_context("本章扩写字数：5000字")
        long = _build_legacy_style_execution_context("本章扩写字数：10000字")
        self.assertIn("自然数量的唯一剧情拍点", medium)
        self.assertIn("自然数量的唯一剧情拍点", long)

    def test_narrative_mode_blocks_procedural_cards_outside_investigation(self):
        def card(card_id, category, title):
            return {
                "id": card_id,
                "category": category,
                "title": title,
                "use_when": "适用场景",
                "avoid_when": "不适用场景",
                "voice_features": title,
                "source_excerpt": (f"{title}。人物立即作出反应并推动下一步变化。" * 12),
            }

        cards = [
            card("SC01", "推理与解释", "逐层推理"),
            card("SC02", "专业角色对白", "专业流程"),
            card("SC05", "异常逐步显形", "异常显形"),
            card("SC06", "群体反应", "冲突现场反应"),
            card("SC07", "日常口语与喜剧", "日常口语反差"),
        ]

        revealed = _style_cards_selected_by_plan(
            cards,
            "主叙事模式：信息揭示\n选定片段卡：SC01、SC02、SC05",
            max_cards=1,
        )
        investigated = _style_cards_selected_by_plan(
            cards,
            "主叙事模式：调查推理\n选定片段卡：SC01、SC02",
            max_cards=1,
        )

        self.assertEqual([item["id"] for item in revealed], ["SC05"])
        self.assertEqual([item["id"] for item in investigated], ["SC01"])

    def test_style_context_uses_entertainment_priority_without_forced_long_reasoning(self):
        reference = "人物先动手阻止，随后只用一句话点出危险。" * 80
        context = _build_style_execution_context(
            "【当前章节】\n本章扩写字数：2000字\n医院送来一批补品，主角发现异常。",
            (
                "【作者人格】\n【剧情组织人格】\n"
                "你每章都按观察—假说—检验—反馈—复盘—行动推进。\n"
                "【对白总体声纹】\n你的对白总体偏短、偏口语。\n"
                "【格式节奏与使用边界】\n你大量把时间、判断和动作拆成一行一句。\n"
                "【人物与场景人格】\n你高频让围观者承担群体反应。"
            ),
            style_reference=reference,
        )

        self.assertIn(reference, context)
        self.assertIn("【仿写使用说明】", context)
        self.assertIn("完整原样本", context)
        self.assertNotIn("【AI文风画像】", context)
        self.assertNotIn("【作者原生用词池", context)
        self.assertNotIn("【V4 人物与叙述声纹", context)
        self.assertNotIn("【V4 条件性叙事技法", context)
        self.assertNotIn("观察—假说—检验—反馈—复盘—行动", context)
        self.assertNotIn("你大量把", context)
        self.assertNotIn("你的对白总体偏短、偏口语", context)
        self.assertNotIn("你高频让", context)
        self.assertNotIn("专业流程才保留", context)
        self.assertNotIn("剧情执行清单", context)
        self.assertNotIn("备用正文草稿", context)

        finalize = _build_style_finalize_context(
            "【当前章节】\n本章扩写字数：2000字",
            "主角发现补品异常，当场叫停。",
            style_reference="人物先动手阻止，随后只用一句话点出危险。" * 80,
            output_target=2000,
            include_memory=False,
            execution_text="1. 主角发现异常并叫停补品。",
            style_plan="主叙事模式：信息揭示\n本章靠异常和人物反应推进。",
        )
        self.assertNotIn("本章已确定主叙事模式为", finalize)
        self.assertIn("【仿写终稿任务】", finalize)
        self.assertIn("段落排版指标已删除", finalize)
        self.assertNotIn("每1000字约", finalize)
        self.assertNotIn("15字以内短段", finalize)
        self.assertNotIn("段落节奏骨架", finalize)
        self.assertNotIn("至少两次用45至90字", finalize)

    def test_female_style_runtime_keeps_voice_without_forcing_comedy_or_group_reactions(self):
        reference = "她没有解释，只把称呼压得很轻，停了一下才接话。" * 80
        context = _build_style_execution_context(
            "【当前章节】\n本章扩写字数：2000字\n女主独自面对一场严肃告别。",
            (
                "【作者人格】\n"
                "【剧情组织人格】\n"
                "每个场景都安排连续拆台、围观群体反应和喜剧反差。\n"
                "【对白总体声纹】\n"
                "人物保留家常称呼、语气词、停顿和接话方式。"
            ),
            style_reference=reference,
        )

        self.assertIn(reference, context)
        self.assertIn("【仿写使用说明】", context)
        self.assertNotIn("每个场景都安排连续拆台", context)
        self.assertNotIn("围观群体反应和喜剧反差", context)
        self.assertNotIn("人物保留家常称呼、语气词、停顿和接话方式", context)
        self.assertNotIn("【V4 人物与叙述声纹", context)
        self.assertNotIn("【V4 条件性叙事技法", context)

    def test_style_execution_parser_selects_last_complete_restart(self):
        first = (
            "【剧情执行清单】\n第一版拍点。\n\n"
            "【本章声纹执行表】\n第一版声纹。\n\n"
            "【备用正文草稿】\n第一版正文写到一半"
        )
        second = (
            "【剧情执行清单】\n第二版拍点。\n\n"
            "【本章声纹执行表】\n第二版声纹。\n\n"
            "【备用正文草稿】\n第二版正文完成。"
        )

        parsed = _parse_style_execution_result(first + second)

        self.assertTrue(parsed["parsed"])
        self.assertTrue(parsed["style_plan_parsed"])
        self.assertEqual(parsed["complete_set_count"], 2)
        self.assertIn("第二版拍点", parsed["execution"])
        self.assertIn("第二版声纹", parsed["style_plan"])
        self.assertEqual(parsed["draft"], "第二版正文完成。")

    def test_style_execution_parser_keeps_previous_complete_restart_when_latest_is_incomplete(self):
        first = (
            "【剧情执行清单】\n第一版拍点。\n\n"
            "【本章声纹执行表】\n第一版声纹。\n\n"
            "【备用正文草稿】\n第一版正文完成。"
        )
        incomplete_restart = (
            "【剧情执行清单】\n第二版拍点。\n\n"
            "【本章声纹执行表】\n第二版声纹，尚未输出备用正文。"
        )

        parsed = _parse_style_execution_result(first + "\n\n" + incomplete_restart)

        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["complete_set_count"], 1)
        self.assertIn("第一版拍点", parsed["execution"])
        self.assertTrue(parsed["style_plan"].startswith("第一版声纹。"))
        self.assertIn("常驻人物语言声纹", parsed["style_plan"])
        self.assertEqual(parsed["draft"], "第一版正文完成。")

    def test_memory_finalize_context_focuses_on_final_body_and_event_coverage(self):
        current = _new_chapter(0)
        current["title"] = "第一章 夜袭"
        current["outline"] = "主角制服来客，保全调查资料。"
        next_chapter = _new_chapter(1)
        next_chapter["title"] = "第二章 融资冻结"
        next_chapter["outline"] = "女主回家处理融资危机。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, next_chapter]
        project["characters"] = [
            {"id": "char-a", "name": "赵明", "role": "主角"},
            {"id": "char-b", "name": "夏正霆", "role": "女主父亲"},
        ]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {
                "story_time": "当夜",
                "location": "别墅",
                "character_states": [],
                "relationship_states": [],
                "object_states": [],
                "active_conflicts": [],
                "unresolved_tasks": [],
                "notes": "",
            },
            "active_facts": [],
            "stage_archives": [],
        }
        final_text = (
            "赵明制服来客。唐棠检查监控后说，前段画面疑似已经被覆盖。"
            "夏正霆随后来电，告知主要融资全部冻结。"
        )

        context = _build_long_form_memory_finalize_context(project, 0, final_text)

        self.assertLessEqual(len(context), NOVEL_AI_CONTEXT_LIMIT)
        self.assertIn("【最终正文】", context)
        self.assertIn(final_text, context)
        self.assertIn("记录缺失/覆盖/删除/清空", context)
        self.assertIn("实际行动、说话、来电", context)
        self.assertIn("current_chapter_character_refs", context)
        self.assertIn("章首已经存在且章末没有变化的伤势", context)
        self.assertIn("只完成一次检测、汇报、送达或普通执行动作", context)
        self.assertIn("C002=夏正霆", context)
        self.assertIn("下一章边界（只用于选择需继承资料）", context)
        self.assertIn("女主回家处理融资危机", context)
        self.assertIn('"long_form_memory"', context)
        self.assertIn('"logic_audit"', context)
        self.assertIn("物件的存在、撤走、开合、损毁、移动和持有人", context)
        self.assertIn("不得把人物判断失误", context)
        self.assertIn("AI推理、提示词、输出要求", context)
        self.assertIn("无法确定或需要猜测剧情时不要修", context)

    def test_logic_audit_requires_ordered_literal_evidence_and_supports_local_patch(self):
        final_text = (
            "两扇屏风被撤下，厅中再无遮挡。\n\n"
            "采买管事急得扑向屏风边缘，想从后门逃走。"
        )
        audit = {
            "checked": True,
            "issues": [{
                "severity": "major",
                "category": "object_state",
                "earlier_quote": "两扇屏风被撤下",
                "later_quote": "采买管事急得扑向屏风边缘",
                "explanation": "屏风已经撤走，后文不能继续扑向其边缘。",
            }],
        }

        self.assertEqual(_chapter_logic_audit_validation_errors(final_text, audit), [])
        self.assertEqual(len(_chapter_logic_audit_blocking_issues(audit)), 1)
        patches = [{
            "issue_index": 1,
            "original_quote": "采买管事急得扑向屏风边缘",
            "replacement_text": "采买管事急得扑向后门",
        }]
        repaired, errors = _apply_chapter_logic_repair_patches(
            final_text, audit["issues"], patches
        )

        self.assertEqual(errors, [])
        self.assertIn("采买管事急得扑向后门", repaired)
        self.assertNotIn("扑向屏风边缘", repaired)

    def test_logic_repair_context_and_parser_only_exchange_exact_patches(self):
        chapter = _new_chapter(0)
        chapter["title"] = "管事互咬"
        project = self._project_with_current_chapter(chapter)
        final_text = "两扇屏风被撤下。\n采买管事扑向屏风边缘。"
        issues = [{
            "severity": "major",
            "category": "object_state",
            "earlier_quote": "两扇屏风被撤下",
            "later_quote": "采买管事扑向屏风边缘",
            "explanation": "已撤走的屏风不能再次被使用。",
        }]

        context = _build_chapter_logic_repair_context(project, 0, final_text, issues)
        parsed = _parse_chapter_logic_repair_result(json.dumps({
            "patches": [{
                "issue_index": 1,
                "original_quote": "采买管事扑向屏风边缘",
                "replacement_text": "采买管事扑向后门",
            }],
        }, ensure_ascii=False))

        self.assertIn("不重新审稿，不扩写、删减或重组其他段落", context)
        self.assertIn("不得补充解释、流程、总结、伏笔或新事件", context)
        self.assertNotIn("正文风格参考", context)
        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["patches"][0]["issue_index"], 1)

    def test_long_form_memory_update_is_parsed_and_applied_without_local_inference(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        response = (
            '{"summary":"收到密信","key_facts":["密信仍由赵明持有"],'
            '"linked_characters":["赵明"],"long_form_memory":{'
            '"state_snapshot":{"story_time":"雨夜","location":"城门",'
            '"character_states":[{"name":"赵明","state":"持有密信"}],'
            '"relationship_states":[],"object_states":[{"name":"密信","owner":"赵明"}],'
            '"active_conflicts":[],"unresolved_tasks":["查明寄信人"],"notes":""},'
            '"active_facts":[{"id":"fact-letter","fact":"密信由赵明持有"}],'
            '"state_delta":{"objects":[{"name":"密信","change":"转由赵明持有"}]},'
            '"stage_archive":null}}'
        )

        update = _parse_long_form_memory_update(response)
        changed = _apply_long_form_memory_update(project, 0, update)

        self.assertTrue(changed)
        memory = project["long_form_memory"]
        self.assertEqual(memory["state_snapshot"]["location"], "城门")
        self.assertEqual(memory["state_snapshot"]["as_of_chapter_index"], 1)
        self.assertEqual(memory["active_facts"][0]["id"], "AF-0001")
        self.assertEqual(memory["active_facts"][0]["source_chapter_id"], chapter["id"])
        self.assertEqual(project["chapters"][0]["state_delta"]["objects"][0]["name"], "密信")

    def test_ai_record_updates_and_next_chapter_selection_use_exact_ids(self):
        current = _new_chapter(0)
        current["id"] = "chapter-1"
        current["linked_characters"] = ["甲"]
        next_chapter = _new_chapter(1)
        next_chapter["id"] = "chapter-2"
        next_chapter["outline"] = "乙带着账册去旧仓库。"
        next_chapter["linked_characters"] = ["甲"]
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, next_chapter]
        project["characters"] = [
            {"id": "char-a", "name": "甲", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
            {"id": "char-b", "name": "乙", "role": "证人", "goal": "", "secret": "", "voice": "", "notes": ""},
        ]
        project["lore"] = [
            {"id": "lore-book", "name": "账册", "type": "物品", "description": "旧账册"},
            {"id": "lore-room", "name": "密室", "type": "地点", "description": "旧宅密室"},
        ]
        project["foreshadow_items"] = [
            {"id": "foreshadow-a", "code": "F0001", "name": "旧伤", "status": "已埋", "description": "甲的旧伤"},
            {"id": "foreshadow-b", "code": "F0002", "name": "账册缺页", "status": "已埋", "description": "账册缺少一页"},
        ]
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "state_patch": {"story_time": "当夜", "character_states": [{"ref": "C002", "state": "保护账册"}]},
            "state_retirements": {},
            "fact_updates": [],
            "current_chapter_character_refs": ["C002"],
            "record_updates": {
                "characters": [
                    {"operation": "update", "ref": "C002", "state": "仍在保护账册", "changes": ["决定带账册去旧仓库"]},
                    {"operation": "create", "key": "NC1", "name": "丙", "canon": {"role": "长期证人"}, "state": "首次出现"},
                ],
                "lore": [
                    {"operation": "create", "key": "NL1", "name": "青色锁链", "canon": {"type": "物品", "description": "跨章束缚主角"}, "state": "由丙持有"},
                    {"operation": "create", "key": "NL2", "name": "账册", "canon": {"description": "不得覆盖原定义"}, "state": "仍由乙保管"},
                ],
            },
            "foreshadow_updates": [
                {"operation": "update", "ref": "F002", "status": "已回收", "state": "缺页已找到"},
                {"operation": "create", "key": "NT1", "name": "F0003｜父母死亡真相", "status": "已埋", "canon": {"setup_chapter": "第一章"}},
                {"operation": "create", "key": "NT2", "name": "F0002｜账册缺页", "status": "已回收"},
            ],
            "next_chapter_memory": {
                "character_refs": ["C002"],
                "lore_refs": ["L001"],
                "foreshadow_refs": ["F002"],
                "fact_refs": [],
                "stage_archive_refs": [],
                "reason": "下一章由乙携带账册推进缺页线索",
            },
            "stage_archive": None,
        }

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        self.assertEqual(project["characters"][1]["goal"], "")
        self.assertEqual(project["long_form_memory"]["record_runtime"]["characters"]["char-b"]["state"], "仍在保护账册")
        self.assertEqual([item["name"] for item in project["characters"]].count("丙"), 1)
        self.assertEqual([item["name"] for item in project["lore"]].count("账册"), 1)
        self.assertEqual([item["name"] for item in project["lore"]].count("青色锁链"), 1)
        self.assertEqual([item["name"] for item in project["foreshadow_items"]].count("账册缺页"), 1)
        self.assertEqual([item["name"] for item in project["foreshadow_items"]].count("父母死亡真相"), 1)
        self.assertFalse(any(item["name"].startswith("F000") for item in project["foreshadow_items"]))
        self.assertEqual(project["chapters"][0]["linked_characters"], ["乙"])
        self.assertEqual(project["chapters"][0]["actual_linked_character_ids"], ["char-b"])
        selection = project["chapters"][1]["memory_selection"]
        character_names = {item["id"]: item["name"] for item in project["characters"]}
        lore_names = {item["id"]: item["name"] for item in project["lore"]}
        self.assertEqual(
            {character_names[item_id] for item_id in selection["character_ids"]},
            {"乙", "丙"},
        )
        self.assertEqual(
            {lore_names[item_id] for item_id in selection["lore_ids"]},
            {"账册", "青色锁链"},
        )
        self.assertNotIn("foreshadow_ids", selection)
        self.assertEqual(project["chapters"][1]["linked_characters"], ["甲"])

        context = _build_chapter_ai_context(project, 1, "draft")
        character_section = self._context_section(context, "本章相关人物")
        current_section = self._context_section(context, "当前章节")
        lore_section = self._context_section(context, "本章相关设定")
        foreshadow_section = self._context_section(context, "本章相关伏笔")
        self.assertIn("乙", character_section)
        self.assertIn("仍在保护账册", character_section)
        self.assertNotIn("甲", character_section)
        self.assertIn("本章有效关联人物：乙", current_section)
        self.assertIn("初始章节规划人物（仅弱参考", current_section)
        self.assertIn("甲", current_section)
        self.assertIn("账册", lore_section)
        self.assertNotIn("密室", lore_section)
        # Body expansion now follows the chapter plan route instead of the
        # previous chapter's memory-selection list.
        self.assertNotIn("账册缺页", foreshadow_section)
        self.assertNotIn("旧伤", foreshadow_section)

        summary_context = _build_chapter_ai_context(project, 0, "summary")
        self.assertIn("未出现在增量里的旧资料默认保留", summary_context)
        self.assertIn("真实ID由程序分配", summary_context)
        self.assertIn("不得改写导入的人物卡", summary_context)
        self.assertIn("人物卡：只为有明确姓名或稳定称谓", summary_context)
        self.assertIn("可直接使用本次新增的NC/NL/NT/NF临时key", summary_context)

    def test_unknown_record_reference_rejects_entire_memory_transaction(self):
        chapter = _new_chapter(0)
        chapter["id"] = "chapter-1"
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [
            {"id": "char-a", "name": "甲", "role": "主角", "goal": "查案", "secret": "旧案真相", "voice": "简短", "notes": "不可覆盖"},
        ]
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "state_patch": {"story_time": "当夜"},
            "state_retirements": {},
            "fact_updates": [],
            "record_updates": {
                "characters": [{"operation": "update", "ref": "C999", "state": "错误状态"}],
                "lore": [],
            },
            "foreshadow_updates": [],
            "current_chapter_character_refs": ["C001"],
            "stage_archive": None,
            "next_chapter_memory": {},
        }

        before = dict(project["characters"][0])
        self.assertFalse(_apply_long_form_memory_update(project, 0, update))
        self.assertEqual(project["characters"][0], before)
        self.assertEqual(project["chapters"][0]["memory_sync_status"], "failed")
        self.assertIn("未知记录", project["chapters"][0]["memory_sync_error"])

    def test_incremental_fact_updates_preserve_omitted_facts_and_archive_retired_fact(self):
        chapter = _new_chapter(0)
        chapter["id"] = "chapter-1"
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 3,
            "state_snapshot": {},
            "active_facts": [
                {"id": "AF-0001", "fact": "甲持有密信", "source_chapter_id": "old-1"},
                {"id": "AF-0002", "fact": "乙仍在城门", "source_chapter_id": "old-2"},
            ],
            "fact_history": [],
            "stage_archives": [],
            "record_runtime": {"characters": {}, "lore": {}, "foreshadows": {}},
            "update_journal": [],
        }
        update = {
            "schema_version": 2,
            "base_revision": 3,
            "state_patch": {"story_time": "次日"},
            "state_retirements": {},
            "fact_updates": [
                {"operation": "update", "id": "AF-0001", "fact": "甲已把密信交给丙"},
                {"operation": "retire", "id": "AF-0002", "reason": "乙已经离开城门"},
                {"operation": "add", "key": "NF1", "fact": "丙开始保管密信"},
            ],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "current_chapter_character_refs": [],
            "stage_archive": None,
            "next_chapter_memory": {},
        }

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        facts = {item["id"]: item["fact"] for item in project["long_form_memory"]["active_facts"]}
        self.assertEqual(facts["AF-0001"], "甲已把密信交给丙")
        self.assertNotIn("AF-0002", facts)
        self.assertEqual(facts["AF-0003"], "丙开始保管密信")
        history = project["long_form_memory"]["fact_history"]
        self.assertEqual([(item["id"], item["status"]) for item in history], [
            ("AF-0001", "revised"),
            ("AF-0002", "retired"),
        ])
        self.assertEqual(project["long_form_memory"]["revision"], 4)
        updated = next(item for item in project["long_form_memory"]["active_facts"] if item["id"] == "AF-0001")
        self.assertEqual(updated["source_chapter_id"], "old-1")
        self.assertEqual(updated["evidence_chapter_id"], chapter["id"])
        self.assertEqual(updated["evidence_chapter_index"], 1)

    def test_permanent_character_and_lore_fields_never_change_on_runtime_update(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [
            {"id": "char-a", "name": "甲", "role": "永久身份", "goal": "长期目标", "secret": "后台秘密", "voice": "固定语气", "notes": "行为边界"},
        ]
        project["lore"] = [
            {"id": "lore-a", "name": "九针", "type": "术法", "description": "共九式，越高阶负担越大"},
        ]
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "state_patch": {"story_time": "当夜"},
            "state_retirements": {},
            "fact_updates": [],
            "record_updates": {
                "characters": [{"operation": "update", "ref": "C001", "state": "本章受伤", "changes": ["右臂骨折"]}],
                "lore": [{"operation": "update", "ref": "L001", "state": "本章施展第三式", "changes": ["第三式复跳"]}],
            },
            "foreshadow_updates": [],
            "current_chapter_character_refs": ["C001"],
            "stage_archive": None,
            "next_chapter_memory": {},
        }
        character_before = dict(project["characters"][0])
        lore_before = dict(project["lore"][0])

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        self.assertEqual(project["characters"][0], character_before)
        self.assertEqual(project["lore"][0], lore_before)
        runtime = project["long_form_memory"]["record_runtime"]
        self.assertEqual(runtime["characters"]["char-a"]["state"], "本章受伤")
        self.assertEqual(runtime["lore"]["lore-a"]["state"], "本章施展第三式")

    def test_memory_update_is_idempotent_for_same_chapter_hash(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "state_patch": {"story_time": "当夜"},
            "state_retirements": {},
            "fact_updates": [{"operation": "add", "key": "NF1", "fact": "主角抵达城门"}],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "current_chapter_character_refs": [],
            "stage_archive": None,
            "next_chapter_memory": {},
        }

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        self.assertEqual(project["long_form_memory"]["revision"], 1)
        self.assertEqual(len(project["long_form_memory"]["active_facts"]), 1)
        self.assertEqual(len(project["long_form_memory"]["update_journal"]), 1)

    def test_parser_repairs_single_extra_closing_brace_and_root_level_memory_keys(self):
        raw = (
            '【长篇记忆更新】\n{"long_form_memory":{"schema_version":2,"base_revision":0,'
            '"state_patch":{"story_time":"当夜"},"state_retirements":{},"fact_updates":[]},'
            '"next_chapter_memory":{"character_refs":[]}}}'
        )

        update = _parse_long_form_memory_update(raw)

        self.assertEqual(update["schema_version"], 2)
        self.assertEqual(update["state_patch"]["story_time"], "当夜")
        self.assertEqual(update["next_chapter_memory"]["character_refs"], [])
        self.assertTrue(update["_parse_repaired"])

    def test_parser_keeps_compact_marker_and_verification_when_model_flattens_root(self):
        raw = json.dumps({
            "schema_version": 2,
            "base_revision": 0,
            "compact_delta_version": LONG_FORM_COMPACT_DELTA_VERSION,
            "state_patch": {},
            "verification": {"checked": True},
        }, ensure_ascii=False)

        update = _parse_long_form_memory_update(raw)

        self.assertEqual(update["compact_delta_version"], LONG_FORM_COMPACT_DELTA_VERSION)
        self.assertEqual(update["verification"]["checked"], True)

    def test_memory_repair_context_and_parser_use_version_two_contract(self):
        chapter = _new_chapter(0)
        chapter["title"] = "密信"
        project = self._project_with_current_chapter(chapter)
        context = _build_long_form_memory_repair_context(
            project,
            0,
            "赵明把密信交给周青。",
            validation_errors=["原JSON无效"],
        )
        response = (
            '{"outline":"1. 赵明交出密信。","summary":"赵明交出密信。",'
            '"key_facts":["密信由周青持有"],"long_form_memory":{'
            '"schema_version":2,"base_revision":0,"state_patch":{"story_time":"当夜"},'
            '"state_retirements":{},"fact_updates":[],"record_updates":{"characters":[],"lore":[]},'
            '"foreshadow_updates":[],"current_chapter_character_refs":[],"stage_archive":null,'
            '"next_chapter_memory":{}}}'
        )
        parsed = _parse_memory_repair_result(response)

        self.assertIn("版本2长篇记忆增量", context)
        self.assertIn("当前长篇记忆修订号：0", context)
        self.assertIn("保留原文全部中文引号、标点和换行", context)
        self.assertIn("不得把正文中的“对白”改成不带引号的对白", context)
        self.assertIn("找不到合格逐字证据时删除对应更新", context)
        self.assertIn("不能因为新增了一条更宽泛的概括而退役精确旧事实", context)
        self.assertIn("不得只因提纲或项目资料出现该名称", context)
        self.assertTrue(parsed["parsed"])
        self.assertIn("密信由周青持有", parsed["key_facts"])

    def test_memory_repair_patch_parser_and_merge_preserve_valid_fields(self):
        original = {
            "schema_version": 2,
            "base_revision": 50,
            "fact_updates": [{"operation": "add", "key": "NF1", "fact": "新事实"}],
            "fact_lifecycle_review": {
                "scope": "current_chapter",
                "reviewed_refs": ["NF1"],
            },
            "state_reconciliation": {"checked": False},
            "record_updates": {"characters": [{"operation": "update", "ref": "C001"}]},
        }
        raw = json.dumps({
            "long_form_memory_patch": {
                "replace": {
                    "fact_lifecycle_review": {
                        "scope": "current_chapter",
                        "reviewed_refs": ["AF-0001"],
                        "notes": "已复核",
                    },
                    "state_reconciliation": {
                        "checked": True,
                        "fact_refs": ["NF1"],
                        "relationship_refs": ["C001|C002"],
                    },
                    "unknown_field": "不得合并",
                }
            }
        }, ensure_ascii=False)

        parsed = _parse_memory_repair_result(raw)
        merged = _merge_long_form_memory_repair_patch(original, parsed["memory_patch"])

        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["repair_mode"], "patch")
        self.assertEqual(merged["fact_updates"], original["fact_updates"])
        self.assertEqual(merged["record_updates"], original["record_updates"])
        self.assertEqual(
            merged["fact_lifecycle_review"]["reviewed_refs"],
            ["AF-0001"],
        )
        self.assertEqual(
            merged["state_reconciliation"]["relationship_refs"],
            ["C001|C002"],
        )
        self.assertNotIn("unknown_field", merged)

    def test_logic_audit_repair_uses_bundle_only_patch_context(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        memory_update = self._strict_update(project)

        context = _build_long_form_memory_repair_context(
            project,
            0,
            "赵明进入王城并取出旧案卷宗。",
            outline="赵明进入王城。",
            summary="赵明取得旧案卷宗。",
            key_facts="赵明已经取得旧案卷宗。",
            logic_audit={},
            memory_update=memory_update,
            validation_errors=["logic_audit.checked必须为true"],
        )

        self.assertIn("【状态增量修复补丁】", context)
        self.assertIn("每个需要修复的字段直接填写真实、完整、可校验的对象或数组", context)
        self.assertIn("顶层使用long_form_memory_patch对象，其下使用replace对象", context)
        self.assertIn("只有清单中的required_object_keys才能进入object_keys", context)
        self.assertNotIn('"logic_audit":{"checked":true,"issues":[]}', context)
        self.assertNotIn("【待修复的原状态字段】", context)
        self.assertNotIn("【机械引用清单】", context)

    def test_memory_repair_patch_targets_include_cross_field_dependencies(self):
        targets = _memory_repair_patch_targets([
            "fact_updates第9项scope与旧事实不匹配，必须使用supersede",
        ])

        self.assertEqual(
            targets["memory_fields"],
            [
                "fact_updates",
                "fact_lifecycle_review",
                "long_term_events",
                "state_reconciliation",
            ],
        )

    def test_full_memory_repair_only_applies_direct_error_fields(self):
        original = {
            "foreshadow_updates": [{"ref": "", "operation": "update"}],
            "long_term_events": [{
                "event": "上一项任务完成",
                "storage": {"task_refs": ["TASK-0001"], "foreshadow_refs": ["F002"]},
            }],
        }
        repaired = {
            "foreshadow_updates": [{"record_ref": "F002", "operation": "update"}],
            "long_term_events": [{
                "event": "上一项任务完成",
                "storage": {"task_refs": [], "foreshadow_refs": ["F002"]},
            }],
        }

        merged = _merge_long_form_memory_repair_full(
            original,
            repaired,
            ["foreshadows更新第1项引用未知记录："],
        )

        self.assertEqual(merged["foreshadow_updates"], repaired["foreshadow_updates"])
        self.assertEqual(
            merged["long_term_events"][0]["storage"]["task_refs"],
            ["TASK-0001"],
        )
        targets = _memory_repair_patch_targets([
            "foreshadows更新第1项引用未知记录：",
        ])
        self.assertEqual(targets["direct_memory_fields"], ["foreshadow_updates"])
        self.assertIn("long_term_events", targets["memory_fields"])

    def test_foreshadow_update_accepts_record_ref_alias(self):
        normalized = _normalize_long_form_state_aliases({
            "foreshadow_updates": [{
                "record_ref": "F002",
                "operation": "update",
                "dynamic": "伏笔继续推进。",
            }],
        })

        self.assertEqual(normalized["foreshadow_updates"][0]["ref"], "F002")

    def test_known_reference_errors_use_compact_memory_patch_context(self):
        chapter = _new_chapter(0)
        chapter["title"] = "豪车堵门"
        chapter["outline"] = "富豪助理堵门争抢接诊资格。"
        chapter["memory_selection"] = {"fact_ids": ["AF-0001", "AF-0002"]}
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [
            {"id": "char-a", "name": "赵明"},
            {"id": "char-b", "name": "周青"},
        ]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "active_facts": [
                {"id": "AF-0001", "scope": "case:a", "fact": "事实甲"},
                {"id": "AF-0002", "scope": "case:b", "fact": "事实乙"},
            ],
        }
        update = self._strict_update(project)
        update["fact_updates"] = [{
            "operation": "add",
            "key": "NF1",
            "scope": "case:new",
            "fact": "新增事实",
            "evidence_quote": "富豪助理堵在门外",
        }]
        update["fact_lifecycle_review"]["reviewed_refs"] = ["NF1"]
        update["state_patch"] = {
            "relationship_states": [{
                "refs": ["C001", "C002"],
                "state": "共同守门",
            }]
        }
        update["state_reconciliation"]["fact_refs"] = ["NF1"]
        update["state_reconciliation"]["relationship_refs"] = ["C001+C002"]
        update["record_updates"] = {
            "characters": [{
                "operation": "update",
                "ref": "C001",
                "state": "不应整段进入补丁上下文" * 300,
            }],
            "lore": [],
        }
        context = _build_long_form_memory_repair_context(
            project,
            0,
            "富豪助理堵在门外，赵明和周青共同守门。",
            memory_update=update,
            validation_errors=[
                "事实生命周期复核引用未知ID：NF1",
                "事实生命周期复核遗漏：AF-0001、AF-0002",
                "state_reconciliation关系引用无效：C001+C002",
                "state_reconciliation.relationship_refs遗漏：C001|C002",
            ],
        )

        self.assertIn("【状态增量修复补丁】", context)
        self.assertIn('"required_existing_refs":["AF-0001","AF-0002"]', context)
        self.assertIn('"new_fact_keys_forbidden_here":["NF1"]', context)
        self.assertIn('"relationship_refs":["C001|C002"]', context)
        self.assertNotIn("不应整段进入补丁上下文", context)
        self.assertNotIn("只输出以下版本2长篇记忆增量", context)
        self.assertLess(len(context), 12000)

    def test_strict_validation_requires_literal_body_evidence(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "state_patch": {"story_time": "当夜"},
            "state_retirements": {},
            "fact_updates": [{"operation": "add", "key": "NF1", "fact": "密信已转交", "evidence_quote": "正文不存在的句子"}],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "current_chapter_character_refs": [],
            "stage_archive": None,
            "next_chapter_memory": {},
        }

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text="赵明把密信交给周青。", require_revision=True, require_evidence=True
        )

        self.assertTrue(any("逐字证据" in error for error in errors))

    def test_unique_dialogue_projection_is_replaced_with_literal_body_span(self):
        body = (
            "甲翻开病历。\n\n“但这些资料只能证明他受过伤。”\n\n"
            "“程序问题可以继续调查。”\n\n“但救治结果也必须完整记录。”"
        )
        update = {
            "fact_updates": [{
                "operation": "add",
                "key": "NF1",
                "fact": "病历只能证明受伤",
                "evidence_quote": "“这些资料只能证明他受过伤。”",
            }],
            "record_updates": {
                "characters": [{
                    "operation": "update",
                    "ref": "C001",
                    "evidence_quote": (
                        "程序问题可以继续调查。\n\n但救治结果也必须完整记录。"
                    ),
                }],
                "lore": [],
            },
        }

        normalized = _literalize_long_form_memory_evidence(update, body)

        fact_quote = normalized["fact_updates"][0]["evidence_quote"]
        character_quote = normalized["record_updates"]["characters"][0]["evidence_quote"]
        self.assertIn(fact_quote, body)
        self.assertIn(character_quote, body)
        self.assertEqual(fact_quote, "这些资料只能证明他受过伤。")
        self.assertIn("。”\n\n“但救治结果", character_quote)

    def test_unique_literal_clause_is_salvaged_when_subject_was_rewritten(self):
        body = (
            "他被护士和陈景舟固定在转运床上，呼吸支持管线没有断，"
            "便携监护的绿色曲线一跳一跳，像是把所有人的心口都拴在了屏幕上。"
        )
        update = {
            "fact_updates": [{
                "operation": "update",
                "id": "AF-0001",
                "evidence_quote": (
                    "冷秋白被固定在转运床上，呼吸支持管线没有断，"
                    "便携监护的绿色曲线一跳一跳，像是把所有人的心口都拴在了屏幕上。"
                ),
            }],
        }

        normalized = _literalize_long_form_memory_evidence(update, body)

        quote = normalized["fact_updates"][0]["evidence_quote"]
        self.assertEqual(quote, "像是把所有人的心口都拴在了屏幕上")
        self.assertIn(quote, body)

    def test_strict_validation_rejects_unknown_snapshot_and_retirement_references(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [
            {"id": "char-a", "name": "甲", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
        ]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {
                "character_states": [{"character_id": "char-a", "name": "甲", "state": "在城门"}],
                "relationship_states": [],
                "object_states": [],
                "active_conflicts": [{"id": "CF-0001", "conflict": "追兵仍在逼近"}],
                "unresolved_tasks": [],
            },
        }
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "state_patch": {
                "character_states": [{"ref": "C999", "state": "错误人物状态"}],
                "active_conflicts": [{"id": "CF-9999", "conflict": "错误冲突"}],
            },
            "state_retirements": {"task_ids": ["TASK-9999"]},
            "fact_updates": [],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "current_chapter_character_refs": ["C001"],
            "stage_archive": None,
            "next_chapter_memory": {},
        }

        self.assertFalse(_apply_long_form_memory_update(project, 0, update))
        error = project["chapters"][0]["memory_sync_error"]
        self.assertIn("未知人物", error)
        self.assertIn("未知ID", error)
        self.assertIn("退出任务ID不存在", error)
        self.assertEqual(project["long_form_memory"]["revision"], 0)

    def test_tenth_chapter_archive_can_be_selected_for_next_chapter_by_temporary_ref(self):
        chapters = [_new_chapter(index) for index in range(11)]
        project = self._project_with_current_chapter(chapters[9])
        project["chapters"] = chapters
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "state_patch": {},
            "state_retirements": {},
            "fact_updates": [],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "current_chapter_character_refs": [],
            "stage_archive": {
                "summary": "前十章完成主角回归并介入急救的阶段任务。",
                "irreversible_facts": ["主角已经回到现实世界"],
                "relationship_changes": [],
                "unresolved_threads": ["圣劫异常外力来源未明"],
                "next_stage_entry": "第十一章从医院门口冲突继续。",
            },
            "next_chapter_memory": {
                "character_refs": [],
                "lore_refs": [],
                "foreshadow_refs": [],
                "fact_refs": [],
                "stage_archive_refs": [],
                "reason": "承接前十章阶段成果",
            },
        }

        self.assertTrue(_apply_long_form_memory_update(project, 9, update))
        archives = project["long_form_memory"]["stage_archives"]
        self.assertEqual(len(archives), 1)
        self.assertEqual(archives[0]["id"], "SA-0001")
        self.assertEqual(project["chapters"][10]["memory_selection"]["stage_archive_ids"], ["SA-0001"])

    def test_next_chapter_selection_always_includes_facts_touched_by_current_update(self):
        current = _new_chapter(0)
        following = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, following]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 2,
            "active_facts": [{"id": "AF-0001", "fact": "旧事实", "source_chapter_id": "old"}],
        }
        update = {
            "schema_version": 2,
            "base_revision": 2,
            "state_patch": {},
            "state_retirements": {},
            "fact_updates": [
                {"operation": "update", "id": "AF-0001", "fact": "本章更新后的事实"},
                {"operation": "add", "key": "NF1", "fact": "本章新增事实"},
            ],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "current_chapter_character_refs": [],
            "stage_archive": None,
            "next_chapter_memory": {
                "character_refs": [],
                "lore_refs": [],
                "foreshadow_refs": [],
                "fact_refs": [],
                "stage_archive_refs": [],
            },
        }

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        self.assertEqual(
            project["chapters"][1]["memory_selection"]["fact_ids"],
            ["AF-0001", "AF-0002"],
        )

    def test_new_record_temp_refs_resolve_inside_same_state_transaction(self):
        current = _new_chapter(0)
        following = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, following]
        project["characters"] = [{"id": "char-a", "name": "甲"}]
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "state_patch": {
                "character_states": [{"ref": "NC1", "name": "乙", "state": "仍在客厅"}],
                "relationship_states": [{"refs": ["C001", "NC1"], "state": "首次对峙"}],
                "object_states": [{"lore_ref": "NL1", "name": "乙的病历", "state": "留在桌上"}],
            },
            "state_retirements": {},
            "fact_updates": [],
            "record_updates": {
                "characters": [{
                    "operation": "create", "key": "NC1", "name": "乙",
                    "state": "仍在客厅", "canon": {"role": "来客"},
                }],
                "lore": [{
                    "operation": "create", "key": "NL1", "name": "乙的病历",
                    "state": "留在桌上", "canon": {"type": "物品"},
                }],
            },
            "foreshadow_updates": [],
            "current_chapter_character_refs": ["C001", "NC1"],
            "stage_archive": None,
            "next_chapter_memory": {
                "character_refs": ["NC1"],
                "lore_refs": ["NL1"],
                "foreshadow_refs": [],
                "fact_refs": [],
                "stage_archive_refs": [],
            },
        }

        errors = _validate_long_form_memory_update(
            project, 0, update, require_revision=True
        )
        self.assertEqual(errors, [])
        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        new_character = next(item for item in project["characters"] if item["name"] == "乙")
        new_lore = next(item for item in project["lore"] if item["name"] == "乙的病历")
        snapshot = project["long_form_memory"]["state_snapshot"]
        self.assertTrue(any(
            item["character_id"] == new_character["id"]
            for item in snapshot["character_states"]
        ))
        self.assertTrue(any(
            set(item["characters"]) == {"char-a", new_character["id"]}
            for item in snapshot["relationship_states"]
        ))
        self.assertEqual(snapshot["object_states"][0]["lore_id"], new_lore["id"])
        next_selection = project["chapters"][1]["memory_selection"]
        self.assertIn(new_character["id"], next_selection["character_ids"])
        self.assertIn(new_lore["id"], next_selection["lore_ids"])

    def test_new_state_temp_refs_resolve_in_events_reconciliation_lifecycle_and_next_selection(self):
        current = _new_chapter(0)
        following = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, following]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {},
            "active_facts": [],
            "stage_archives": [],
        }
        update = self._strict_update(project)
        update["state_patch"] = {
            "active_conflicts": [{"key": "NCF1", "conflict": "对方已经封锁城门"}],
            "unresolved_tasks": [{"key": "NTASK1", "task": "天亮前找到备用入口"}],
        }
        update["state_reconciliation"]["conflict_refs"] = ["NCF1"]
        update["state_reconciliation"]["task_refs"] = ["NTASK1"]
        update["state_lifecycle_review"]["reviewed_conflict_refs"] = ["NCF1"]
        update["state_lifecycle_review"]["reviewed_task_refs"] = ["NTASK1"]
        update["long_term_events"] = [{
            "event": "城门封锁，备用入口成为下一步任务",
            "category": "task",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": [],
                "conflict_refs": ["NCF1"], "task_refs": ["NTASK1"],
            },
        }]
        update["next_chapter_memory"] = {
            "conflict_refs": ["NCF1"],
            "task_refs": ["NTASK1"],
        }

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        snapshot = project["long_form_memory"]["state_snapshot"]
        conflict_id = snapshot["active_conflicts"][0]["id"]
        task_id = snapshot["unresolved_tasks"][0]["id"]
        self.assertTrue(conflict_id.startswith("CF-"))
        self.assertTrue(task_id.startswith("TASK-"))
        self.assertEqual(
            project["chapters"][0]["state_lifecycle_review"]["reviewed_conflict_ids"],
            [conflict_id],
        )
        self.assertEqual(
            project["chapters"][0]["state_lifecycle_review"]["reviewed_task_ids"],
            [task_id],
        )
        event_storage = project["chapters"][0]["long_term_events"][0]["storage"]
        self.assertEqual(event_storage["conflict_ids"], [conflict_id])
        self.assertEqual(event_storage["task_ids"], [task_id])
        next_selection = project["chapters"][1]["memory_selection"]
        self.assertIn(conflict_id, next_selection["conflict_ids"])
        self.assertIn(task_id, next_selection["task_ids"])

    def test_empty_state_tasks_are_dropped_without_persisting_new_refs(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        update = self._strict_update(project)
        update["state_patch"] = {
            "unresolved_tasks": [{"key": "NTASK-EMPTY", "task": ""}],
        }
        update["state_reconciliation"]["task_refs"] = ["NTASK-EMPTY"]
        update["state_lifecycle_review"]["reviewed_task_refs"] = ["NTASK-EMPTY"]
        update["next_chapter_memory"] = {"task_refs": ["NTASK-EMPTY"]}
        update["long_term_events"] = [{
            "event": "空任务不应形成长期事件",
            "category": "task",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": [],
                "conflict_refs": [], "task_refs": ["NTASK-EMPTY"],
            },
        }]

        normalized = _normalize_long_form_update_payload(project, 0, update)

        self.assertEqual(normalized["state_patch"]["unresolved_tasks"], [])
        self.assertNotIn("NTASK-EMPTY", normalized["state_reconciliation"]["task_refs"])
        self.assertNotIn("NTASK-EMPTY", normalized["state_lifecycle_review"]["reviewed_task_refs"])
        self.assertNotIn("NTASK-EMPTY", normalized["next_chapter_memory"]["task_refs"])
        self.assertNotIn("NTASK-EMPTY", normalized["long_term_events"][0]["storage"]["task_refs"])

    def test_unbound_record_alias_is_not_accepted_as_object_key(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{"id": "L010", "name": "疑似设定"}]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {
                "object_states": [{"key": "L010", "name": "疑似物件", "state": "仍在现场"}],
            },
            "active_facts": [],
            "stage_archives": [],
        }
        update = self._strict_update(project)
        update["state_reconciliation"]["object_keys"] = ["L010"]

        normalized = _normalize_long_form_structural_refs(project, 0, update)
        errors = _validate_long_form_memory_update(
            project, 0, normalized, final_text="现场仍然保留疑似物件。",
            require_revision=True, require_evidence=True,
        )

        self.assertEqual(normalized["state_reconciliation"]["object_keys"], ["L010"])
        self.assertTrue(any("object_keys引用未知物件" in error for error in errors))

    def test_first_seen_explicit_object_lore_alias_gets_stable_object_key(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [
            {"id": f"lore-{index:02d}", "name": f"设定{index:02d}", "type": "规则"}
            for index in range(1, 11)
        ] + [{
            "id": "lore-box",
            "name": "婚书铜匣",
            "type": "物件",
            "description": "跨章持有的关键物件。",
        }]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {
                "object_states": [{
                    "key": "NO001",
                    "name": "装面钱的布袋",
                    "state": "仍由主角持有。",
                }],
            },
            "active_facts": [],
            "stage_archives": [],
        }
        update = self._strict_update(project)
        update["state_patch"] = {
            "object_states": [{
                "object_key": "L011",
                "state": "婚书铜匣由主角携带，八枚锁钉同时震响。",
                "evidence_quote": "婚书铜匣由主角携带",
            }],
        }
        update["state_reconciliation"]["object_keys"] = ["L011"]
        update["state_lifecycle_review"]["reviewed_object_keys"] = ["L011"]
        update["next_chapter_memory"]["object_keys"] = ["L011"]
        update["long_term_events"] = [{
            "event": "婚书铜匣继续由主角携带。",
            "category": "key_object",
            "evidence_quote": "婚书铜匣由主角携带",
            "storage": {"object_keys": ["L011"]},
        }]

        normalized = _normalize_long_form_structural_refs(project, 0, update)
        object_row = normalized["state_patch"]["object_states"][0]
        object_key = object_row["key"]
        self.assertNotEqual(object_key, "L011")
        self.assertTrue(object_key.startswith("NOBJ-NF"))
        self.assertEqual(object_row["lore_ref"], "L011")
        self.assertEqual(normalized["state_reconciliation"]["object_keys"], [object_key])
        self.assertEqual(normalized["state_lifecycle_review"]["reviewed_object_keys"], [object_key])
        self.assertEqual(normalized["next_chapter_memory"]["object_keys"], [object_key])
        self.assertEqual(
            normalized["long_term_events"][0]["storage"]["object_keys"],
            [object_key],
        )
        self.assertIn("L011", normalized["state_reconciliation"]["lore_refs"])
        self.assertIn("L011", normalized["long_term_events"][0]["storage"]["lore_refs"])

    def test_first_seen_object_alias_reuses_existing_lore_bound_key(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [
            {"id": f"lore-{index:02d}", "name": f"设定{index:02d}", "type": "规则"}
            for index in range(1, 11)
        ] + [{"id": "lore-box", "name": "婚书铜匣", "type": "物件"}]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 1,
            "state_snapshot": {
                "object_states": [
                    {
                        "key": "NO001",
                        "name": "装面钱的布袋",
                        "state": "上一章仍由主角持有。",
                    },
                    {
                        "key": "NO002",
                        "name": "婚书铜匣",
                        "lore_id": "lore-box",
                        "state": "上一章已经出现。",
                    },
                ],
            },
            "active_facts": [],
            "stage_archives": [],
        }
        update = self._strict_update(project)
        update["state_patch"] = {
            "object_states": [{
                "object_key": "L011",
                "state": "婚书铜匣仍由主角携带。",
                "evidence_quote": "婚书铜匣仍由主角携带",
            }],
        }
        update["state_reconciliation"]["object_keys"] = ["L011"]

        normalized = _normalize_long_form_structural_refs(project, 0, update)
        self.assertEqual(normalized["state_patch"]["object_states"][0]["key"], "NO002")
        self.assertEqual(normalized["state_reconciliation"]["object_keys"], ["NO002"])
        self.assertNotEqual("NO001", normalized["state_reconciliation"]["object_keys"][0])


    def test_tenth_chapter_rejects_empty_archive_and_unknown_archive_selection(self):
        chapters = [_new_chapter(index) for index in range(11)]
        project = self._project_with_current_chapter(chapters[9])
        project["chapters"] = chapters
        update = {
            "schema_version": 2,
            "base_revision": 0,
            "state_patch": {},
            "state_retirements": {},
            "fact_updates": [],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "current_chapter_character_refs": [],
            "stage_archive": {},
            "next_chapter_memory": {
                "character_refs": [],
                "lore_refs": [],
                "foreshadow_refs": [],
                "fact_refs": [],
                "stage_archive_refs": ["SA-9999"],
            },
        }

        errors = _validate_long_form_memory_update(
            project, 9, update, require_revision=True, require_evidence=True
        )

        self.assertTrue(any("stage_archive.summary为空" in error for error in errors))
        self.assertTrue(any("stage_archive.next_stage_entry为空" in error for error in errors))
        self.assertTrue(any("阶段档案引用无效" in error for error in errors))

    def test_memory_repair_context_uses_targeted_facts_and_state_partitions(self):
        chapters = [_new_chapter(index) for index in range(46)]
        current = chapters[44]
        current["title"] = "第四十五章 旧案复核"
        current["memory_selection"] = {
            "character_ids": ["char-keep"],
            "lore_ids": [],
            "foreshadow_ids": [],
            "fact_ids": ["AF-0005"],
            "stage_archive_ids": [],
        }
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters
        project["characters"] = [
            {"id": "char-keep", "name": "赵明", "role": "主角"},
            {"id": "char-drop", "name": "无关旧人", "role": "旧线人物"},
        ]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 44,
            "state_snapshot": {
                "story_time": "当夜",
                "location": "王城",
                "character_states": [
                    {"character_id": "char-keep", "name": "赵明", "state": "相关人物状态：正在查案"},
                    {"character_id": "char-drop", "name": "无关旧人", "state": "无关人物状态：仍在边城"},
                ],
                "relationship_states": [],
                "object_states": [],
                "active_conflicts": [],
                "unresolved_tasks": [],
            },
            "active_facts": [
                {
                    "id": f"AF-{index:04d}",
                    "scope": f"test:{index}",
                    "fact": f"长期事实内容第{index}条",
                    "source_chapter_index": 1,
                }
                for index in range(1, 201)
            ],
            "stage_archives": [],
        }

        context = _build_long_form_memory_repair_context(
            project,
            44,
            "赵明重新核对了旧案卷宗。",
            memory_update={
                "fact_updates": [{"operation": "update", "id": "AF-0005"}],
            },
            validation_errors=["AF-0005需要补充逐字证据"],
        )

        self.assertIn("长期事实内容第5条", context)
        self.assertIn("长期事实内容第200条", context)
        self.assertNotIn("长期事实内容第100条", context)
        self.assertIn("相关人物状态：正在查案", context)
        selected_snapshot = self._context_section(context, "当前状态快照")
        self.assertNotIn("无关人物状态：仍在边城", selected_snapshot)
        self.assertIn("C002=无关旧人｜无关人物状态：仍在边城", context)
        self.assertLessEqual(len(context), NOVEL_AI_CONTEXT_LIMIT)

    def test_large_stage_boundary_repair_context_uses_delta_and_catalog_hash(self):
        chapters = [_new_chapter(index) for index in range(50)]
        current = chapters[49]
        current["title"] = "第五十章 阶段复核"
        current["memory_selection"] = {"fact_ids": ["AF-0005"]}
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 49,
            "active_facts": [
                {
                    "id": f"AF-{index:04d}",
                    "scope": f"case:{index}",
                    "fact": f"阶段事实第{index}条",
                    "source_chapter_index": 1,
                }
                for index in range(1, 2001)
            ],
        }
        reviewed_refs = [f"AF-{index:04d}" for index in range(1, 2001)]

        context = _build_long_form_memory_repair_context(
            project,
            49,
            "赵明逐页核对卷宗，确认阶段证据仍然完整。" * 1200,
            memory_update={
                "fact_lifecycle_review": {
                    "scope": "stage_boundary_all_active",
                    "reviewed_refs": reviewed_refs,
                },
            },
            validation_errors=["阶段复核结果需要重新输出"],
        )

        self.assertIn("赵明逐页核对卷宗", context)
        self.assertIn("AF-0005", context)
        self.assertIn("阶段事实第5条", context)
        self.assertNotIn("AF-0001", context)
        self.assertNotIn("AF-2000", context)
        self.assertNotIn("阶段事实第2000条", context)
        self.assertIn('"facts":2000', context)
        self.assertIn('"sha256"', context)
        self.assertIn("fact_lifecycle_review", context)
        self.assertIn("long_term_events", context)
        self.assertIn("state_reconciliation", context)
        self.assertTrue(context.startswith("【任务】\n"))
        self.assertLessEqual(len(context), LONG_FORM_CONTEXT_SOFT_LIMIT)

    def test_fact_scope_change_requires_new_fact_without_cross_scope_replacement(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 3,
            "active_facts": [{
                "id": "AF-0001",
                "scope": "character:C001:medical_status",
                "fact": "赵明仍未脱离危险",
                "source_chapter_id": "old-chapter",
                "source_chapter_index": 1,
            }],
            "fact_history": [],
        }
        body = "赵明清点完药柜，确认三份药材仍由自己保管。"
        bad_update = self._strict_update(project)
        bad_update["fact_updates"] = [{
            "operation": "update",
            "id": "AF-0001",
            "scope": "object:medicine:inventory",
            "fact": "三份药材仍由赵明保管",
            "evidence_quote": "确认三份药材仍由自己保管",
        }]
        bad_update["fact_lifecycle_review"]["reviewed_refs"] = ["AF-0001"]
        bad_update["long_term_events"] = [{
            "event": "赵明确认药材库存",
            "category": "key_object",
            "evidence_quote": "确认三份药材仍由自己保管",
            "storage": {
                "fact_refs": ["AF-0001"], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": [], "conflict_refs": [], "task_refs": [],
            },
        }]
        bad_update["state_reconciliation"]["fact_refs"] = ["AF-0001"]

        errors = _validate_long_form_memory_update(
            project, 0, bad_update, final_text=body, require_revision=True, require_evidence=True
        )
        self.assertTrue(any("必须新增事实" in error for error in errors))

        bad_supersede = self._strict_update(project)
        bad_supersede["fact_updates"] = [{
            "operation": "supersede",
            "id": "AF-0001",
            "key": "NF1",
            "scope": "object:medicine:inventory",
            "fact": "三份药材仍由赵明保管",
            "reason": "原事实主题是人物病情，不能改写为药材库存",
            "evidence_quote": "确认三份药材仍由自己保管",
        }]
        bad_supersede["fact_lifecycle_review"]["reviewed_refs"] = ["AF-0001"]
        bad_supersede["long_term_events"] = [{
            "event": "赵明确认药材库存",
            "category": "key_object",
            "evidence_quote": "确认三份药材仍由自己保管",
            "storage": {
                "fact_refs": ["NF1"], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": [], "conflict_refs": [], "task_refs": [],
            },
        }]
        bad_supersede["state_reconciliation"]["fact_refs"] = ["NF1"]
        errors = _validate_long_form_memory_update(
            project, 0, bad_supersede, final_text=body, require_revision=True, require_evidence=True
        )
        self.assertTrue(any("supersede" in error and "必须新增事实" in error for error in errors))

        good_update = self._strict_update(project)
        good_update["fact_updates"] = [
            {
                "operation": "keep",
                "id": "AF-0001",
                "scope": "character:C001:medical_status",
                "fact": "赵明仍未脱离危险",
            },
            {
                "operation": "add",
                "key": "NF1",
                "scope": "object:medicine:inventory",
                "fact": "三份药材仍由赵明保管",
                "evidence_quote": "确认三份药材仍由自己保管",
            },
        ]
        good_update["fact_lifecycle_review"]["reviewed_refs"] = ["AF-0001"]
        good_update["long_term_events"] = deepcopy(bad_supersede["long_term_events"])
        good_update["state_reconciliation"]["fact_refs"] = ["AF-0001", "NF1"]
        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, good_update, final_text=body, require_revision=True, require_evidence=True
            ),
            [],
        )

        self.assertTrue(_apply_long_form_memory_update(project, 0, good_update))
        active_facts = project["long_form_memory"]["active_facts"]
        self.assertEqual([item["id"] for item in active_facts], ["AF-0001", "AF-0002"])
        self.assertEqual(project["long_form_memory"]["fact_history"], [])
        self.assertNotIn("supersedes_fact_id", active_facts[1])

    def test_event_storage_normalization_prunes_invalid_duplicates_without_semantic_assignment(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [{
            "id": "char-a", "name": "赵明", "role": "主角", "goal": "查案",
            "secret": "", "voice": "", "notes": "",
        }]
        body = "赵明清点完药柜，确认三份药材仍由自己保管。"
        update = self._strict_update(project)
        update["fact_updates"] = [{
            "operation": "add",
            "key": "NF1",
            "scope": "object:medicine:inventory",
            "fact": "三份药材仍由赵明保管",
            "evidence_quote": "确认三份药材仍由自己保管",
        }]
        update["record_updates"]["characters"] = [{
            "operation": "update",
            "ref": "C001",
            "state": "完成药柜清点",
            "changes": ["确认药材库存"],
            "evidence_quote": "赵明清点完药柜",
        }]
        update["long_term_events"] = [{
            "event": "赵明确认药材库存",
            "category": "key_object",
            "evidence_quote": "确认三份药材仍由自己保管",
            "storage": {
                "fact_refs": ["NF1", "NF1", "AF-9999"],
                "character_refs": ["C999", "C999"],
                "lore_refs": [], "foreshadow_refs": [], "object_keys": [],
                "conflict_refs": [], "task_refs": [],
            },
        }]
        update["state_reconciliation"]["fact_refs"] = ["NF1"]
        update["state_reconciliation"]["character_refs"] = ["C001"]

        normalized = _normalize_long_form_event_storage_refs(project, 0, update)

        storage = normalized["long_term_events"][0]["storage"]
        self.assertEqual(storage["fact_refs"], ["NF1"])
        self.assertEqual(storage["character_refs"], [])
        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, normalized, final_text=body,
                require_revision=True, require_evidence=True,
            ),
            [],
        )
        self.assertTrue(_apply_long_form_memory_update(project, 0, normalized))
        saved_fact_ids = project["chapters"][0]["long_term_events"][0]["storage"]["fact_ids"]
        self.assertEqual(saved_fact_ids, ["AF-0001"])
        self.assertNotIn("NF1", saved_fact_ids)

    def test_event_storage_restores_lore_and_object_links_with_unique_literal_evidence(self):
        chapter = _new_chapter(0)
        chapter["memory_selection"] = {
            "lore_ids": ["lore-a"],
            "object_keys": ["OBJ-1"],
        }
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{
            "id": "lore-a", "name": "旧账簿", "type": "证据",
        }]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {
                "object_states": [{
                    "key": "OBJ-1", "name": "旧账簿", "lore_id": "lore-a",
                    "state": "账簿仍处于封存状态",
                }],
            },
            "active_facts": [],
            "stage_archives": [],
        }
        update = self._strict_update(project)
        evidence = "旧账簿的封签已经断裂"
        update["record_updates"]["lore"] = [{
            "operation": "update",
            "ref": "lore-a",
            "state": "封签已经断裂",
            "changes": ["封签状态改变"],
            "evidence_quote": evidence,
        }]
        update["state_patch"] = {
            "object_states": [{
                "key": "OBJ-1",
                "lore_ref": "lore-a",
                "state": "封签已经断裂",
                "evidence_quote": evidence,
            }],
        }
        update["state_lifecycle_review"]["reviewed_object_keys"] = ["OBJ-1"]
        update["state_reconciliation"]["record_runtime_review"] = {
            "reviewed_lore_refs": ["lore-a"],
            "unchanged_lore_refs": [],
            "reviewed_foreshadow_refs": [],
            "unchanged_foreshadow_refs": [],
        }
        update["long_term_events"] = [{
            "event": "旧账簿封签断裂",
            "category": "key_object",
            "evidence_quote": evidence,
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": [],
                "conflict_refs": [], "task_refs": [],
            },
        }]

        normalized = _normalize_long_form_structural_refs(project, 0, update)

        storage = normalized["long_term_events"][0]["storage"]
        self.assertEqual(storage["lore_refs"], ["lore-a"])
        self.assertEqual(storage["object_keys"], ["OBJ-1"])
        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, normalized,
                final_text=evidence + "，姜晚棠立即重新封存。",
                require_revision=True,
                require_evidence=True,
            ),
            [],
        )

    def test_structural_refs_move_record_aliases_out_of_object_namespaces(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [
            {"id": f"lore-{index:02d}", "name": f"设定{index}"}
            for index in range(1, 11)
        ] + [{
            "id": "lore-card",
            "name": "谎言房卡",
        }]
        project["foreshadow_items"] = [{
            "id": "foreshadow-card",
            "name": "房卡来源",
        }]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 14,
            "state_snapshot": {
                "object_states": [{
                    "key": "OBJ-ROOM-CARD",
                    "name": "房卡实体",
                    "state": "仍在沈知夏手中",
                }],
            },
            "active_facts": [],
            "stage_archives": [],
        }
        update = self._strict_update(project)
        update["state_reconciliation"]["object_keys"] = [
            "L011",
            "F001",
            "OBJ-ROOM-CARD",
            "UNKNOWN-OBJECT",
        ]
        update["next_chapter_memory"] = {
            "object_keys": ["L011", "F001", "OBJ-ROOM-CARD"],
        }

        normalized = _normalize_long_form_structural_refs(project, 0, update)

        reconciliation = normalized["state_reconciliation"]
        self.assertEqual(
            reconciliation["object_keys"],
            ["OBJ-ROOM-CARD", "UNKNOWN-OBJECT"],
        )
        self.assertEqual(reconciliation["lore_refs"], ["L011"])
        self.assertEqual(reconciliation["foreshadow_refs"], ["F001"])
        self.assertEqual(
            normalized["next_chapter_memory"]["object_keys"],
            ["OBJ-ROOM-CARD"],
        )
        self.assertEqual(
            normalized["next_chapter_memory"]["lore_refs"],
            ["L011"],
        )
        self.assertEqual(
            normalized["next_chapter_memory"]["foreshadow_refs"],
            ["F001"],
        )

    def test_event_storage_uses_exact_evidence_anchor_only_for_one_event(self):
        chapter = _new_chapter(0)
        chapter["memory_selection"] = {
            "fact_ids": ["AF-0163"],
            "object_keys": ["NOBJ-CH39-003"],
        }
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 39,
            "state_snapshot": {
                "object_states": [{
                    "key": "NOBJ-CH39-003",
                    "name": "棠记开铺章程",
                    "state": "章程已在药铺公开",
                }],
            },
            "active_facts": [{
                "id": "AF-0163",
                "scope": "object:棠记开铺章程",
                "fact": "棠记开铺章程已经公开",
            }],
            "stage_archives": [],
        }
        update = self._strict_update(project)
        shared_evidence = "留样、平价售卖、开铺章程，是棠记自己的规矩"
        event_evidence = "救济可以合作，名声与责任不能混账"
        update["fact_updates"] = [{
            "operation": "update",
            "id": "AF-0163",
            "scope": "object:棠记开铺章程",
            "fact": "棠记开铺章程被确认为独立规则",
            "evidence_quote": shared_evidence,
        }]
        update["fact_lifecycle_review"]["reviewed_refs"] = ["AF-0163"]
        update["state_patch"] = {
            "object_states": [{
                "key": "NOBJ-CH39-003",
                "state": "章程被带到善宴并确认为棠记独立规则",
                "evidence_quote": shared_evidence,
            }],
        }
        update["state_lifecycle_review"]["reviewed_object_keys"] = ["NOBJ-CH39-003"]
        update["long_term_events"] = [{
            "event": "姜晚棠在善宴公开分清名声与责任",
            "category": "other",
            "evidence_quote": event_evidence,
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": ["NOBJ-CH39-003"],
                "conflict_refs": [], "task_refs": [],
            },
        }]

        normalized = _normalize_long_form_structural_refs(project, 0, update)

        self.assertEqual(
            normalized["long_term_events"][0]["storage"]["fact_refs"],
            ["AF-0163"],
        )
        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, normalized,
                final_text=event_evidence + "。" + shared_evidence + "。",
                require_revision=True,
                require_evidence=True,
            ),
            [],
        )

        ambiguous = deepcopy(update)
        ambiguous["long_term_events"].append({
            "event": "章程随后被送回棠记保存",
            "category": "key_object",
            "evidence_quote": "账房将四份册页重新收进木匣",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": ["NOBJ-CH39-003"],
                "conflict_refs": [], "task_refs": [],
            },
        })
        ambiguous = _normalize_long_form_structural_refs(project, 0, ambiguous)
        self.assertEqual(
            [
                event["storage"]["fact_refs"]
                for event in ambiguous["long_term_events"]
            ],
            [[], []],
        )

    def test_new_fact_temp_id_alias_is_normalized_to_key(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 40,
            "state_snapshot": {},
            "active_facts": [],
            "stage_archives": [],
        }
        update = self._strict_update(project)
        update["fact_updates"] = [{
            "operation": "add",
            "key": "",
            "temp_id": "NF-CH41-001",
            "scope": "evidence:sealed_letter",
            "fact": "密信封口出现新的断痕",
            "evidence_quote": "封口多了一道新断痕",
        }]

        normalized = _normalize_long_form_update_payload(project, 0, update)

        self.assertEqual(normalized["fact_updates"][0]["key"], "NF-CH41-001")

    def test_supersede_new_fact_key_wins_over_echoed_old_fact_id(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        normalized = _normalize_long_form_update_payload(project, 0, {
            "fact_updates": [{
                "operation": "supersede",
                "id": "AF-0063",
                "key": "AF-0063",
                "new_fact_key": "NF-0040",
            }],
        })

        fact_update = normalized["fact_updates"][0]
        self.assertEqual(fact_update["id"], "AF-0063")
        self.assertEqual(fact_update["key"], "NF-0040")

    def test_new_object_is_available_to_lifecycle_review(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {"object_states": []},
            "active_facts": [],
            "stage_archives": [],
        }
        update = self._strict_update(project)
        evidence = "黑色玉匣已经被林辰收进袖中"
        update["state_patch"] = {
            "object_states": [{
                "key": "OBJ-NEW-1",
                "name": "黑色玉匣",
                "state": "已被林辰收进袖中",
                "evidence_quote": evidence,
            }],
        }
        update["state_lifecycle_review"]["reviewed_object_keys"] = ["OBJ-NEW-1"]
        update["state_reconciliation"]["object_keys"] = ["OBJ-NEW-1"]
        update["long_term_events"] = [{
            "event": "林辰收起黑色玉匣",
            "category": "key_object",
            "evidence_quote": evidence,
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": ["OBJ-NEW-1"],
                "conflict_refs": [], "task_refs": [],
            },
        }]

        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, update,
                final_text=evidence + "。",
                require_revision=True,
                require_evidence=True,
            ),
            [],
        )

    def test_missing_handoff_uses_full_visible_state_for_evidenced_retirement(self):
        previous = _new_chapter(0)
        previous["memory_sync_status"] = "complete"
        previous["memory_revision"] = 1
        chapter = _new_chapter(1)
        chapter["memory_selection"] = {}
        project = self._project_with_current_chapter(chapter)
        project["chapters"] = [previous, chapter]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 1,
            "state_snapshot": {
                "unresolved_tasks": [{
                    "id": "TASK-0021",
                    "task": "亲自随第二批香料验货",
                }],
            },
            "active_facts": [],
            "stage_archives": [],
        }
        update = self._strict_update(project, 1)
        evidence = "姜晚棠已经完成第二批香料验货"
        update["state_retirements"] = {"task_ids": ["TASK-0021"]}
        update["state_lifecycle_review"]["reviewed_task_refs"] = ["TASK-0021"]
        update["state_reconciliation"]["task_refs"] = ["TASK-0021"]
        update["long_term_events"] = [{
            "event": "第二批香料验货完成",
            "category": "task",
            "evidence_quote": evidence,
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": [],
                "conflict_refs": [], "task_refs": ["TASK-0021"],
            },
        }]

        self.assertEqual(
            _validate_long_form_memory_update(
                project, 1, update,
                final_text=evidence + "，并保留全部验货记录。",
                require_revision=True,
                require_evidence=True,
            ),
            [],
        )

    def test_structural_normalization_completes_reconciliation_refs_without_ai(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {
                "active_conflicts": [{"id": "CF-0048", "conflict": "秦家报复仍在升级"}],
                "unresolved_tasks": [{"id": "TASK-0069", "task": "继续核验秦少锋后遗症"}],
            },
        }
        update = self._strict_update(project)
        update["state_patch"] = {
            "active_conflicts": [{
                "id": "CF-0048",
                "previous_conflict": "秦家报复仍在升级",
                "conflict": "秦家报复转向融资渠道",
            }],
            "unresolved_tasks": [{
                "id": "TASK-0069",
                "previous_task": "继续核验秦少锋后遗症",
                "task": "后遗症核验已经完成",
            }],
        }
        update["state_lifecycle_review"]["reviewed_conflict_refs"] = ["CF-0048"]
        update["state_lifecycle_review"]["reviewed_task_refs"] = ["TASK-0069"]
        update["long_term_events"] = [
            {
                "event": "秦家报复转向融资渠道",
                "category": "other",
                "evidence_quote": "秦家报复转向融资渠道",
                "storage": {
                    "fact_refs": [], "character_refs": [], "lore_refs": [],
                    "foreshadow_refs": [], "object_keys": [],
                    "conflict_refs": ["CF-0048"], "task_refs": [],
                },
            },
            {
                "event": "秦少锋后遗症核验完成",
                "category": "task",
                "evidence_quote": "后遗症核验已经完成",
                "storage": {
                    "fact_refs": [], "character_refs": [], "lore_refs": [],
                    "foreshadow_refs": [], "object_keys": [],
                    "conflict_refs": [], "task_refs": ["TASK-0069"],
                },
            },
        ]

        raw_errors = _validate_long_form_memory_update(
            project, 0, update, final_text="秦家报复转向融资渠道，后遗症核验已经完成。",
            require_revision=True, require_evidence=True,
        )
        self.assertIn("state_reconciliation.conflict_refs遗漏：CF-0048", raw_errors)
        self.assertIn("state_reconciliation.task_refs遗漏：TASK-0069", raw_errors)

        normalized = _normalize_long_form_structural_refs(project, 0, update)

        reconciliation = normalized["state_reconciliation"]
        self.assertEqual(reconciliation["conflict_refs"], ["CF-0048"])
        self.assertEqual(reconciliation["task_refs"], ["TASK-0069"])
        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, normalized, final_text="秦家报复转向融资渠道，后遗症核验已经完成。",
                require_revision=True, require_evidence=True,
            ),
            [],
        )

    def test_task_previous_text_accepts_only_a_long_exact_ellipsis_prefix(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        old_task = (
            "继续调查上游闸机、旧维护道和原始开闸者，并在不破坏封存证据的前提下"
            "维持通气、封堵和伤员救援，同时核验全部经手记录与联络节点；继续追查"
            "水运控制关系、临时换船手续、沿途行栈和全部封条编号。"
        )
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "state_snapshot": {
                "unresolved_tasks": [{"id": "TASK-0099", "task": old_task}],
            },
        }
        update = self._strict_update(project)
        update["state_patch"] = {
            "unresolved_tasks": [{
                "id": "TASK-0099",
                "previous_task": old_task[:84] + "…",
                "task": "继续救援伤员，并核验开闸者和全部经手记录。",
            }],
        }
        update["state_lifecycle_review"]["reviewed_task_refs"] = ["TASK-0099"]
        update["state_reconciliation"]["task_refs"] = ["TASK-0099"]
        update["long_term_events"] = [{
            "event": "救援与开闸调查继续推进",
            "category": "task",
            "evidence_quote": "继续救援伤员，并核验开闸者",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": [], "conflict_refs": [],
                "task_refs": ["TASK-0099"],
            },
        }]

        errors = _validate_long_form_memory_update(
            project,
            0,
            update,
            final_text="众人继续救援伤员，并核验开闸者和全部经手记录。",
            require_revision=True,
            require_evidence=True,
        )

        self.assertFalse(any("previous_task与旧状态不匹配" in error for error in errors))
        update["state_patch"]["unresolved_tasks"][0]["previous_task"] = (
            "继续调查另一处完全无关的记录和人员，并把错误内容扩展到足够长的八十个字符"
            "以证明校验不会仅凭省略号放行任何不相干文本。…"
        )
        errors = _validate_long_form_memory_update(
            project,
            0,
            update,
            final_text="众人继续救援伤员，并核验开闸者和全部经手记录。",
            require_revision=True,
            require_evidence=True,
        )
        self.assertTrue(any("previous_task与旧状态不匹配" in error for error in errors))

    def test_tenth_chapter_lifecycle_review_only_requires_selected_active_facts(self):
        chapters = [_new_chapter(index) for index in range(10)]
        project = self._project_with_current_chapter(chapters[9])
        project["chapters"] = chapters
        project["chapters"][9]["memory_selection"] = {"fact_ids": ["AF-0002"]}
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 9,
            "active_facts": [
                {"id": "AF-0001", "scope": "case:a", "fact": "事实甲"},
                {"id": "AF-0002", "scope": "case:b", "fact": "事实乙"},
            ],
        }
        update = self._strict_update(project, 9)
        update["fact_lifecycle_review"]["reviewed_refs"] = ["AF-0001"]
        update["stage_archive"] = {
            "summary": "前十章完成旧案重启。",
            "irreversible_facts": [],
            "relationship_changes": [],
            "unresolved_threads": ["真凶未明"],
            "next_stage_entry": "继续追查证人。",
        }

        errors = _validate_long_form_memory_update(
            project, 9, update, final_text="赵明继续追查旧案。", require_revision=True, require_evidence=True
        )

        self.assertTrue(any("事实生命周期复核遗漏" in error and "AF-0002" in error for error in errors))
        self.assertFalse(any("事实生命周期复核遗漏" in error and "AF-0001" in error for error in errors))

    def test_long_term_event_can_cover_multiple_direct_updates_without_duplicate_events(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        body = "赵明将旧案卷宗交给周青保管，周青答应长期作证。"
        update = self._strict_update(project)
        update["fact_updates"] = [{
            "operation": "add",
            "key": "NF1",
            "scope": "object:case_file:owner",
            "fact": "旧案卷宗由周青保管",
            "evidence_quote": "赵明将旧案卷宗交给周青保管",
        }]
        update["record_updates"]["characters"] = [{
            "operation": "create",
            "key": "NC1",
            "name": "周青",
            "state": "答应长期作证",
            "canon": {"role": "长期证人"},
            "evidence_quote": "周青答应长期作证",
        }]
        update["state_reconciliation"]["fact_refs"] = ["NF1"]
        update["state_reconciliation"]["character_refs"] = ["NC1"]
        update["long_term_events"] = [{
            "event": "赵明将旧案卷宗交给周青并取得长期作证承诺",
            "category": "commitment",
            "evidence_quote": "赵明将旧案卷宗交给周青保管，周青答应长期作证",
            "storage": {
                "fact_refs": ["NF1"], "character_refs": ["NC1"],
                "lore_refs": [], "foreshadow_refs": [], "object_keys": [],
                "conflict_refs": [], "task_refs": [],
            },
        }]

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=body, require_revision=True, require_evidence=True
        )

        self.assertEqual(errors, [])

    def test_long_term_event_coverage_accepts_real_record_ids_as_references(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [{"id": "char-a", "name": "赵明", "role": "查案人"}]
        body = "赵明决定继续追查旧案，并把卷宗留在身边。"
        update = self._strict_update(project)
        update["record_updates"]["characters"] = [{
            "operation": "update",
            "id": "char-a",
            "state": "继续追查旧案",
            "changes": ["决定继续追查"],
            "evidence_quote": "赵明决定继续追查旧案",
        }]
        update["long_term_events"] = [{
            "event": "赵明继续追查旧案",
            "category": "commitment",
            "evidence_quote": "赵明决定继续追查旧案",
            "storage": {
                "fact_refs": [], "character_refs": ["char-a"], "lore_refs": [],
                "foreshadow_refs": [], "object_keys": [], "conflict_refs": [], "task_refs": [],
            },
        }]
        update["state_reconciliation"]["character_refs"] = ["char-a"]

        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, update, final_text=body, require_revision=True, require_evidence=True
            ),
            [],
        )

    def test_new_lore_uses_literal_evidence_when_story_known_is_omitted(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        body = "赵明确认禁地日落后不得进入，并把规则写进案卷。"
        update = self._strict_update(project)
        update["record_updates"]["lore"] = [{
            "operation": "create",
            "key": "NL1",
            "name": "禁地规则",
            "state": "规则已经公开",
            "canon": {"type": "规则", "description": "日落后不得进入禁地"},
            "evidence_quote": "赵明确认禁地日落后不得进入",
        }]
        update["long_term_events"] = [{
            "event": "禁地规则公开",
            "category": "ability_boundary",
            "evidence_quote": "赵明确认禁地日落后不得进入",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": ["NL1"],
                "foreshadow_refs": [], "object_keys": [], "conflict_refs": [], "task_refs": [],
            },
        }]
        update["state_reconciliation"]["lore_refs"] = ["NL1"]

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=body, require_revision=True, require_evidence=True
        )

        self.assertFalse(any("缺少story_known" in error for error in errors))
        normalized = _normalize_long_form_update_payload(project, 0, update)
        self.assertEqual(
            normalized["record_updates"]["lore"][0]["story_known"],
            "赵明确认禁地日落后不得进入",
        )

    def test_ephemeral_actor_refs_do_not_block_memory_commit(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [{"id": "C001", "name": "赵明"}]
        update = self._strict_update(project)
        update["current_chapter_character_refs"] = ["C001", "前台经理"]
        update["state_reconciliation"]["character_refs"] = ["C001", "前台经理"]
        normalized = _normalize_long_form_update_payload(project, 0, update)

        self.assertEqual(normalized["current_chapter_character_refs"], ["C001"])
        self.assertEqual(normalized["state_reconciliation"]["character_refs"], ["C001"])

    def test_state_reconciliation_must_cover_new_conflict_and_task_keys(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        body = "追兵已经锁定赵明，他必须在天亮前离开王城。"
        update = self._strict_update(project)
        update["state_patch"] = {
            "active_conflicts": [{"key": "NCF1", "conflict": "追兵已经锁定赵明"}],
            "unresolved_tasks": [{"key": "NTASK1", "task": "天亮前离开王城"}],
        }
        update["long_term_events"] = [{
            "event": "赵明必须躲避追兵并离城",
            "category": "task",
            "evidence_quote": "他必须在天亮前离开王城",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [], "foreshadow_refs": [],
                "object_keys": [], "conflict_refs": ["NCF1"], "task_refs": ["NTASK1"],
            },
        }]

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=body, require_revision=True, require_evidence=True
        )

        self.assertTrue(any("state_reconciliation.conflict_refs遗漏" in error for error in errors))
        self.assertTrue(any("state_reconciliation.task_refs遗漏" in error for error in errors))

    def test_missing_new_task_key_does_not_create_empty_reconciliation_reference(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        update = self._strict_update(project)
        update["state_patch"] = {
            "unresolved_tasks": [{"id": "", "task": "继续核验来访者"}],
        }

        errors = _validate_long_form_memory_update(
            project,
            0,
            update,
            final_text="赵明决定继续核验来访者。",
            require_revision=True,
            require_evidence=True,
        )

        self.assertTrue(any("新增key缺失或重复" in error for error in errors))
        self.assertNotIn("state_reconciliation.task_refs遗漏：", errors)

    def test_draft_context_hides_author_secrets_but_exposes_story_known_and_due_reveal(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 旧钟"
        chapter["outline"] = "赵明检查禁地规则，并留意旧钟异响。"
        chapter["memory_selection"] = {
            "character_ids": ["char-a"],
            "lore_ids": ["lore-a"],
            "foreshadow_ids": ["foreshadow-a"],
            "fact_ids": [],
            "stage_archive_ids": [],
        }
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [{
            "id": "char-a", "name": "赵明", "role": "查案人", "goal": "查清旧案",
            "secret": "赵明其实是失踪皇子", "voice": "克制", "notes": "不轻信旁人",
        }]
        project["lore"] = [{
            "id": "lore-a", "name": "禁地规则", "type": "规则",
            "description": "完整答案：进入禁地的人都会被王后控制。",
            "story_known": "目前只知道日落后不得进入禁地。",
        }]
        project["foreshadow_items"] = [{
            "id": "foreshadow-a", "code": "F0001", "name": "旧钟异响", "status": "已埋",
            "setup_chapter": "第一章", "payoff_chapter": "第十章",
            "description": "旧钟钥匙藏在井底。", "revealed": "众人只听见旧钟在午夜响起。",
            "remaining_secret": "幕后指使者是王后。",
        }]

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertNotIn("赵明其实是失踪皇子", context)
        self.assertIn("目前只知道日落后不得进入禁地", context)
        self.assertNotIn("进入禁地的人都会被王后控制", context)
        self.assertNotIn("众人只听见旧钟在午夜响起", context)
        self.assertIn("旧钟钥匙藏在井底", context)
        self.assertNotIn("幕后指使者是王后", context)

        converted_context = _build_chapter_ai_context(project, 0, "script_to_novel")
        self.assertNotIn("赵明其实是失踪皇子", converted_context)
        self.assertNotIn("幕后指使者是王后", converted_context)
        self.assertIn("旧钟钥匙藏在井底", converted_context)

        chapter["outline"] = "本章回收旧钟异响，揭示旧钟钥匙。"
        chapter["title"] = "第十章 旧钟真相"
        project["foreshadow_items"][0]["payoff_chapter"] = "第十章"
        due_context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("旧钟钥匙藏在井底", due_context)
        self.assertNotIn("幕后指使者是王后", due_context)

    def test_recovered_foreshadow_atomically_records_payoff_and_reveal_boundary(self):
        chapter = _new_chapter(0)
        chapter["title"] = "真相"
        project = self._project_with_current_chapter(chapter)
        project["foreshadow_items"] = [{
            "id": "foreshadow-a", "code": "F0001", "name": "虎符去向", "status": "已埋",
            "setup_chapter": "序章", "payoff_chapter": "", "description": "虎符最终去向待揭示",
            "revealed": "", "remaining_secret": "",
        }]
        body = "赵明打开井底石匣，确认虎符一直藏在这里。"
        update = self._strict_update(project)
        update["foreshadow_updates"] = [{
            "operation": "update",
            "ref": "F001",
            "status": "已回收",
            "state": "虎符去向已经揭晓",
            "revealed": "虎符一直藏在井底石匣",
            "remaining_secret": "",
            "evidence_quote": "确认虎符一直藏在这里",
        }]
        update["long_term_events"] = [{
            "event": "虎符去向揭晓",
            "category": "foreshadow",
            "evidence_quote": "确认虎符一直藏在这里",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": ["F001"], "object_keys": [], "conflict_refs": [], "task_refs": [],
            },
        }]
        update["state_reconciliation"]["foreshadow_refs"] = ["F001"]
        update["state_reconciliation"]["record_runtime_review"] = {
            "reviewed_lore_refs": [],
            "unchanged_lore_refs": [],
            "reviewed_foreshadow_refs": ["F001"],
            "unchanged_foreshadow_refs": [],
        }

        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, update, final_text=body, require_revision=True, require_evidence=True
            ),
            [],
        )
        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        item = project["foreshadow_items"][0]
        self.assertEqual(item["status"], "已回收")
        self.assertIn("第 1 章", item["payoff_chapter"])
        self.assertEqual(item["revealed"], "虎符一直藏在井底石匣")
        self.assertEqual(item["remaining_secret"], "")

    def test_planted_foreshadow_atomically_records_setup_and_revealed_clue(self):
        chapter = _new_chapter(0)
        chapter["title"] = "钟声"
        project = self._project_with_current_chapter(chapter)
        project["foreshadow_items"] = [{
            "id": "foreshadow-a", "code": "F0001", "name": "午夜钟声", "status": "未埋",
            "setup_chapter": "", "payoff_chapter": "第十章", "description": "钟声来自密室机关",
            "revealed": "", "remaining_secret": "",
        }]
        body = "午夜时，赵明和周青都听见旧钟无风自鸣。"
        update = self._strict_update(project)
        update["foreshadow_updates"] = [{
            "operation": "update",
            "ref": "F001",
            "status": "已埋",
            "state": "午夜钟声已经出现",
            "evidence_quote": "赵明和周青都听见旧钟无风自鸣",
        }]
        update["long_term_events"] = [{
            "event": "午夜钟声伏笔已经埋设",
            "category": "foreshadow",
            "evidence_quote": "赵明和周青都听见旧钟无风自鸣",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": ["F001"], "object_keys": [], "conflict_refs": [], "task_refs": [],
            },
        }]
        update["state_reconciliation"]["foreshadow_refs"] = ["F001"]
        update["state_reconciliation"]["record_runtime_review"] = {
            "reviewed_lore_refs": [],
            "unchanged_lore_refs": [],
            "reviewed_foreshadow_refs": ["F001"],
            "unchanged_foreshadow_refs": [],
        }

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=body, require_revision=True, require_evidence=True
        )
        self.assertEqual(errors, [])
        normalized = _normalize_long_form_update_payload(project, 0, update)
        normalized_foreshadow = normalized["foreshadow_updates"][0]
        self.assertEqual(normalized_foreshadow["revealed"], "午夜钟声已经出现")
        self.assertIn("仍未揭示", normalized_foreshadow["remaining_secret"])

        update["foreshadow_updates"][0]["revealed"] = "赵明与周青听见旧钟在午夜无风自鸣"
        update["foreshadow_updates"][0]["remaining_secret"] = "钟声来源尚未揭示"
        self.assertEqual(
            _validate_long_form_memory_update(
                project, 0, update, final_text=body, require_revision=True, require_evidence=True
            ),
            [],
        )
        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        item = project["foreshadow_items"][0]
        self.assertEqual(item["status"], "已埋")
        self.assertIn("第 1 章", item["setup_chapter"])
        self.assertEqual(item["revealed"], "赵明与周青听见旧钟在午夜无风自鸣")
        self.assertEqual(item["remaining_secret"], "钟声来源尚未揭示")

    def test_static_story_layers_accumulate_without_overwriting_earlier_history(self):
        chapter = _new_chapter(79)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{
            "id": "lore-a",
            "name": "祖传药方",
            "type": "医术",
            "description": "永久定义：药方分为三层，完整答案不得由动态更新改写。",
            "story_known": "第七十六章公开：药方第一层可以止血。",
        }]
        project["foreshadow_items"] = [{
            "id": "foreshadow-a",
            "code": "F0001",
            "name": "药方夹层",
            "status": "已埋",
            "setup_chapter": "第76章",
            "payoff_chapter": "",
            "description": "永久计划：夹层最终指向失踪医案。",
            "revealed": "第七十六章公开：药方纸张存在夹层。",
            "remaining_secret": "夹层里的旧印章来源尚未揭示。",
        }]
        update = self._strict_update(project)
        update["record_updates"]["lore"] = [{
            "operation": "update",
            "ref": "L001",
            "state": "药方第二层已被验证",
            "story_known": "第八十章公开：药方第二层可暂缓毒发。",
            "changes": ["验证第二层药效"],
        }]
        update["foreshadow_updates"] = [{
            "operation": "update",
            "ref": "F001",
            "status": "已埋",
            "state": "夹层露出第二条线索",
            "setup_chapter": "第80章",
            "revealed": "第八十章公开：夹层边缘有夏氏旧印。",
            "remaining_secret": "旧印对应的持有人尚未揭示。",
        }]

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        lore = project["lore"][0]
        self.assertEqual(
            lore["description"],
            "永久定义：药方分为三层，完整答案不得由动态更新改写。",
        )
        self.assertIn("第七十六章公开：药方第一层可以止血。", lore["story_known"])
        self.assertIn("第八十章公开：药方第二层可暂缓毒发。", lore["story_known"])
        foreshadow = project["foreshadow_items"][0]
        self.assertEqual(foreshadow["setup_chapter"], "第76章")
        self.assertEqual(foreshadow["description"], "永久计划：夹层最终指向失踪医案。")
        self.assertIn("第七十六章公开：药方纸张存在夹层。", foreshadow["revealed"])
        self.assertIn("第八十章公开：夹层边缘有夏氏旧印。", foreshadow["revealed"])
        self.assertIn("夹层里的旧印章来源尚未揭示。", foreshadow["remaining_secret"])
        self.assertIn("旧印对应的持有人尚未揭示。", foreshadow["remaining_secret"])

        runtime = project["long_form_memory"]["record_runtime"]
        self.assertEqual(runtime["lore"]["lore-a"]["story_known"], lore["story_known"])
        self.assertEqual(
            runtime["foreshadows"]["foreshadow-a"]["revealed"],
            foreshadow["revealed"],
        )
        self.assertEqual(
            runtime["foreshadows"]["foreshadow-a"]["remaining_secret"],
            foreshadow["remaining_secret"],
        )

    def test_normalization_preserves_fact_history_beyond_one_thousand_versions(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 5,
            "fact_history": [
                {"id": f"AF-{index:04d}", "fact": f"历史事实{index}", "status": "revised"}
                for index in range(1, 1106)
            ],
        }
        update = {
            "schema_version": 2,
            "base_revision": 5,
            "state_patch": {"story_time": "次日"},
            "state_retirements": {},
            "fact_updates": [],
            "record_updates": {"characters": [], "lore": []},
            "foreshadow_updates": [],
            "current_chapter_character_refs": [],
            "stage_archive": None,
            "next_chapter_memory": {},
        }

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        self.assertEqual(len(project["long_form_memory"]["fact_history"]), 1105)

    def test_style_candidate_rank_prefers_fewer_local_style_mismatches(self):
        reference = "\n".join("这是连续铺陈的样本段落，人物关系与事情缘由在叙述中自然展开。" for _ in range(80))
        close = "\n".join("这是连续铺陈的候选段落，人物关系与事情缘由在叙述中自然展开。" for _ in range(80))
        fragmented = "\n".join(f"短句{i}。" for i in range(300))

        self.assertLess(_style_candidate_rank(reference, close), _style_candidate_rank(reference, fragmented))

    def test_style_rescue_is_reserved_for_unusable_or_extreme_output(self):
        reference = "样本文字。" * 300
        self.assertFalse(_style_candidate_needs_rescue(reference, "正常正文。" * 280, 2000))
        self.assertTrue(_style_candidate_needs_rescue(reference, "过短。" * 20, 2000))
        self.assertTrue(_style_candidate_needs_rescue(reference, "严重超长。" * 700, 2000))

    def test_style_audit_parser_requires_score_and_no_remaining_issues(self):
        passed = _parse_style_audit_result(
            '{"pass":true,"score":80,"summary":"接近","issues":[]}'
        )
        below_threshold = _parse_style_audit_result(
            '{"pass":true,"score":79,"summary":"尚有差异","issues":[]}'
        )
        failed = _parse_style_audit_result(
            "```json\n"
            '{"pass":true,"score":90,"summary":"仍有差异","issues":['
            '{"dimension":"段落","evidence":"偏碎","instruction":"增加长段"}]}'
            "\n```"
        )
        malformed = _parse_style_audit_result("不是JSON")

        self.assertTrue(passed["pass"])
        self.assertFalse(below_threshold["pass"])
        self.assertFalse(failed["pass"])
        self.assertEqual(failed["issues"][0]["instruction"], "增加长段")
        self.assertFalse(malformed["pass"])
        self.assertEqual(malformed["score"], 0)

    def test_chapter_draft_context_treats_legacy_planning_fields_as_reference(self):
        current = _new_chapter(0)
        current["title"] = "第一章 风雨入城"
        current["outline"] = (
            "所属阶段：强钩子阶段\n"
            "本章功能：开局爆点\n"
            "冲突强度：高\n"
            "铺垫比例：低，只允许事件中带出\n"
            "人物任务：快速建立主角行动风格\n"
            "主线任务：进入京城主线冲突\n"
            "伏笔任务：埋下风雨信号\n"
            "结尾钩子：旧案卷宗出现。\n\n"
            "本章目标：主角进入京城。"
        )
        project = self._project_with_current_chapter(current)

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("历史规划元数据只作参考", context)
        self.assertIn("不要逐项执行、解释或扩展成任务清单", context)
        self.assertNotIn("所属阶段：强钩子阶段", context)
        self.assertNotIn("本章功能：开局爆点", context)
        self.assertNotIn("冲突强度：高", context)
        self.assertNotIn("人物任务：快速建立主角行动风格", context)
        self.assertIn("快速建立主角行动风格", context)
        self.assertIn("旧提纲中若残留固定伏笔编号、伏笔任务或伏笔动作", context)
        self.assertNotIn("动态伏笔调度参考", context)
        self.assertNotIn("伏笔任务：埋下风雨信号", context)

    def test_global_note_is_private_and_not_in_chapter_ai_context(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        project = self._project_with_current_chapter(current)
        project["draft_note"] = "仅自己可见提醒：不要让这句进入 AI 写作上下文。"

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertNotIn("仅自己可见提醒", context)
        self.assertNotIn("不要让这句进入 AI 写作上下文", context)

    def test_blank_chapter_draft_words_does_not_expand_to_project_total(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        project = self._project_with_current_chapter(current)
        project["meta"]["target_words"] = "1万"

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("本章扩写字数：未填写", context)
        self.assertIn("不要根据项目总目标字数一次性写满", context)
        self.assertIn("项目总目标字数：1万字", context)

    def test_chapter_draft_words_uses_remaining_words_after_existing_body(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入城"
        current["outline"] = "主角入城调查旧案。"
        current["draft_words"] = "5000"
        current["text"] = "甲" * 2000
        project = self._project_with_current_chapter(current)

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("本章扩写字数：5000字", context)
        self.assertIn("当前正文长度：约2000字", context)
        self.assertIn("本次新增正文参考目标：约3000字", context)
        self.assertIn("正文长度控制目标", context)
        self.assertIn("目标的85%-115%", context)
        self.assertNotIn("2970-3150字", context)

    def test_chapter_context_ignores_core_role_words_without_exact_character_name(self):
        current = _new_chapter(0)
        current["title"] = "第十二章 入城"
        current["outline"] = "主角入城调查，反派暗中设局。"
        current["linked_characters"] = []
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].extend([
            {
                "name": "赵明",
                "role": "主角",
                "goal": "查清旧案",
                "secret": "不知道父亲曾改过证词",
                "voice": "克制直接",
                "notes": "",
            },
            {
                "name": "沈砚",
                "role": "反派",
                "goal": "阻止旧案翻出真相",
                "secret": "",
                "voice": "温和但带压迫感",
                "notes": "",
            },
        ])

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关人物】", context)
        current_section = self._context_section(context, "当前章节")
        character_section = self._context_section(context, "本章相关人物")
        self.assertIn("关联人物：", current_section)
        self.assertNotIn("关联人物：赵明", current_section)
        self.assertNotIn("赵明", character_section)
        self.assertNotIn("查清旧案", character_section)
        self.assertNotIn("沈砚", character_section)
        self.assertNotIn("阻止旧案翻出真相", character_section)
        self.assertNotIn("路人0", context)

    def test_chapter_context_prioritizes_relevant_lore_and_foreshadow(self):
        current = _new_chapter(0)
        current["title"] = "第四十六章 旧钟再响"
        current["outline"] = "主角进入琉璃塔，听见密室钟声。"
        project = self._project_with_current_chapter(current)
        project["lore"] = [
            {"name": f"普通地点{i}", "type": "地点", "description": "无关地点"}
            for i in range(45)
        ]
        project["lore"].append({
            "name": "琉璃塔",
            "type": "地点",
            "description": "旧案档案被藏在塔顶。",
        })
        project["foreshadow_items"] = [
            {
                "name": f"旧线索{i}",
                "status": "已回收",
                "setup_chapter": "第1章",
                "payoff_chapter": "第2章",
                "description": "已经处理。",
            }
            for i in range(45)
        ]
        project["foreshadow_items"].append({
            "name": "旧钟声",
            "status": "已埋",
            "setup_chapter": "第3章",
            "payoff_chapter": "第四十六章",
            "description": "钟声响起表示密室开启。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关设定】", context)
        self.assertIn("琉璃塔", context)
        self.assertNotIn("普通地点0", context)
        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("旧钟声", context)
        self.assertNotIn("旧线索0", context)

    def test_chapter_context_ignores_generic_stage_terms_without_exact_lore_name(self):
        current = _new_chapter(0)
        current["title"] = "第二十一章 回城"
        current["outline"] = "主角回到主舞台，在朝堂继续调查旧案。"
        project = self._project_with_current_chapter(current)
        project["lore"] = [
            {"name": f"普通地点{i}", "type": "地点", "description": "偏远地点，暂不影响主线。"}
            for i in range(35)
        ]
        project["lore"].append({
            "name": "王城",
            "type": "地点",
            "description": "故事主舞台，朝堂和旧案卷宗都在这里交汇。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关设定】", context)
        lore_section = self._context_section(context, "本章相关设定")
        self.assertNotIn("王城", lore_section)
        self.assertNotIn("故事主舞台", lore_section)
        self.assertNotIn("普通地点0", lore_section)

    def test_chapter_context_dedupes_reference_notes_without_touching_body_repetition(self):
        current = _new_chapter(0)
        current["title"] = "第十章 重复资料"
        current["outline"] = "赵明进入琉璃塔，准备回收虎符失踪。"
        current["text"] = "重复对白。\n重复对白。"
        current["summary"] = "摘要唯一事实。\n补充：摘要唯一事实。"
        current["key_facts"] = "关键唯一事实。\n补充：关键唯一事实。"
        project = self._project_with_current_chapter(current)
        project["bible"] = "圣经唯一事实。\n补充：圣经唯一事实。"
        project["world_rules"] = "规则唯一事实。\n补充：规则唯一事实。"
        project["characters"] = [
            {
                "name": "赵明",
                "role": "主角",
                "goal": "查清旧案",
                "secret": "",
                "voice": "",
                "notes": "人物唯一备注。\n补充：人物唯一备注。",
            }
        ]
        project["lore"] = [
            {
                "name": "琉璃塔",
                "type": "地点",
                "description": "设定唯一说明。\n补充：设定唯一说明。",
            }
        ]
        project["foreshadow_items"] = [
            {
                "name": "虎符失踪",
                "status": "已埋",
                "setup_chapter": "第十章",
                "payoff_chapter": "第二十章",
                "description": "伏笔唯一说明。\n补充：伏笔唯一说明。",
            }
        ]

        context = _build_chapter_ai_context(project, 0, "draft")

        for duplicated_line in (
            "圣经唯一事实。",
            "规则唯一事实。",
            "摘要唯一事实。",
            "关键唯一事实。",
            "人物唯一备注。",
            "设定唯一说明。",
            "伏笔唯一说明。",
        ):
            self.assertNotIn(f"补充：{duplicated_line}", context)
        self.assertEqual(context.count("圣经唯一事实。"), 1)
        self.assertEqual(context.count("规则唯一事实。"), 1)
        self.assertEqual(context.count("人物唯一备注。"), 1)
        self.assertEqual(context.count("伏笔唯一说明。"), 1)
        self.assertGreaterEqual(context.count("重复对白。"), 2)

    def test_chapter_context_prioritizes_payoff_keyword_foreshadow(self):
        current = _new_chapter(0)
        current["title"] = "第二十章 虎符真相"
        current["outline"] = "本章回收虎符失踪，揭晓兵权旧案。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"背景线索{i}",
                "status": "已埋",
                "setup_chapter": "第1章",
                "payoff_chapter": "",
                "description": "后续处理。",
            }
            for i in range(40)
        ]
        project["foreshadow_items"].append({
            "name": "虎符失踪",
            "status": "已埋",
            "setup_chapter": "第2章",
            "payoff_chapter": "第二十章",
            "description": "牵出兵权。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("虎符失踪", context)
        self.assertIn("牵出兵权", context)
        self.assertNotIn("背景线索0", context)

    def test_chapter_context_keeps_global_foreshadow_queue_with_matched_item(self):
        current = _new_chapter(0)
        current["title"] = "第二十章 虎符真相"
        current["outline"] = "本章回收虎符失踪，揭晓兵权旧案。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": "虎符失踪",
                "status": "已埋",
                "setup_chapter": "第2章",
                "payoff_chapter": "第二十章",
                "description": "牵出兵权。",
            },
            {
                "name": "密室旧钟",
                "status": "已埋",
                "setup_chapter": "第3章",
                "payoff_chapter": "第二十五章",
                "description": "后续开启地底密室。",
            },
        ]

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("虎符失踪", context)
        self.assertNotIn("开放伏笔队列", context)
        self.assertNotIn("密室旧钟", context)

    def test_chapter_context_prioritizes_actionable_open_foreshadow_queue_without_secret(self):
        current = _new_chapter(0)
        current["title"] = "第十章 暂避锋芒"
        current["outline"] = "本章处理人物关系，不直接回收伏笔。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"背景待处理{i}",
                "status": "已埋",
                "setup_chapter": "",
                "payoff_chapter": "",
                "description": "普通背景线索，暂不影响主线。",
            }
            for i in range(20)
        ]
        project["foreshadow_items"].append({
            "name": "终局密钥",
            "status": "已埋",
            "setup_chapter": "第九章",
            "payoff_chapter": "第二十五章",
            "description": "关系最终真相，不能遗忘。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertNotIn("开放伏笔队列", context)
        self.assertNotIn("终局密钥", context)
        self.assertNotIn("背景待处理0", context)

    def test_chapter_context_excludes_no_need_foreshadows_from_open_queue(self):
        current = _new_chapter(0)
        current["title"] = "第十章 暂避锋芒"
        current["outline"] = "本章处理人物关系，不直接回收伏笔。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": "白兔挂件去向",
                "status": "无需回收",
                "setup_chapter": "第三章",
                "payoff_chapter": "",
                "description": "低价值道具线，不影响主线。",
            },
            {
                "name": "终局密钥",
                "status": "已埋",
                "setup_chapter": "第九章",
                "payoff_chapter": "第二十五章",
                "description": "关系最终真相，不能遗忘。",
            },
        ]

        context = _build_chapter_ai_context(project, 0, "draft")
        foreshadow_section = self._context_section(context, "本章相关伏笔")

        self.assertNotIn("开放伏笔队列", foreshadow_section)
        self.assertNotIn("终局密钥", foreshadow_section)
        self.assertNotIn("白兔挂件去向", foreshadow_section)

    def test_chapter_context_prioritizes_due_open_foreshadow_queue(self):
        current = _new_chapter(39)
        current["title"] = "第四十章 风雪夜谈"
        current["outline"] = "本章处理人物关系，不直接回收伏笔。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"普通伏笔{i}",
                "status": "已埋",
                "setup_chapter": "第1章",
                "payoff_chapter": "",
                "description": "普通背景线索，暂不影响主线。",
            }
            for i in range(20)
        ]
        project["foreshadow_items"].append({
            "name": "临近回收伏笔",
            "status": "已埋",
            "setup_chapter": "第5章",
            "payoff_chapter": "第四十一章",
            "description": "临近当前章节，应该优先提醒。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertNotIn("开放伏笔队列", context)
        self.assertNotIn("动态伏笔调度参考", context)
        self.assertNotIn("临近回收伏笔", context)
        self.assertNotIn("普通伏笔0", context)

    def test_chapter_context_uses_full_planned_foreshadow_card_for_prelude(self):
        current = _new_chapter(9)
        current["title"] = "第十章 雨后总部"
        current["outline"] = "本章处理总部内斗，不直接回收伏笔。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": "旧手机匿名短信",
                "status": "已埋",
                "setup_chapter": "第十一章",
                "payoff_chapter": "第十二章",
                "description": (
                    "匿名短信不是普通威胁。"
                    "旧手机号码会指向景辰京城总部内部泄密者。"
                    "回收时必须确认陈景川没有按短信要求走正门。"
                ),
            }
        ]

        context = _build_chapter_ai_context(project, 0, "draft")
        foreshadow_section = self._context_section(context, "本章相关伏笔")

        self.assertIn("旧手机匿名短信", foreshadow_section)
        self.assertIn("本章阶段：前置铺垫", foreshadow_section)
        self.assertIn("计划埋设：第十一章", foreshadow_section)
        self.assertIn("计划回收：第十二章", foreshadow_section)
        self.assertIn("旧手机号码会指向景辰京城总部内部泄密者。", foreshadow_section)
        self.assertIn("回收时必须确认陈景川没有按短信要求走正门。", foreshadow_section)

    def test_chapter_context_prioritizes_foreshadow_alias_from_description(self):
        current = _new_chapter(0)
        current["title"] = "第十二章 密室开启"
        current["outline"] = "本章揭晓密室钟声，回收塔顶暗门线索。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"背景线索{i}",
                "status": "已埋",
                "setup_chapter": "第1章",
                "payoff_chapter": "",
                "description": "后续处理。",
            }
            for i in range(40)
        ]
        project["foreshadow_items"].append({
            "name": "旧钟声",
            "status": "已埋",
            "setup_chapter": "第十二章",
            "payoff_chapter": "",
            "description": "别称：密室钟声。钟声响起表示暗门开启。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("旧钟声", context)
        self.assertIn("密室钟声", context)

    def test_chapter_context_prioritizes_foreshadow_extended_alias_labels(self):
        current = _new_chapter(0)
        current["title"] = "第二十章 虎符真相"
        current["outline"] = "本章回收玄铁令，揭晓兵权旧案。"
        project = self._project_with_current_chapter(current)
        project["foreshadow_items"] = [
            {
                "name": f"背景线索{i}",
                "status": "已埋",
                "setup_chapter": "第1章",
                "payoff_chapter": "",
                "description": "后续处理。",
            }
            for i in range(40)
        ]
        project["foreshadow_items"].append({
            "name": "虎符失踪",
            "status": "已埋",
            "setup_chapter": "第3章",
            "payoff_chapter": "第二十章",
            "description": "代号：玄铁令。真名：半枚虎符。牵出兵权交易。",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关伏笔】", context)
        self.assertIn("虎符失踪", context)
        self.assertIn("玄铁令", context)
        self.assertNotIn("背景线索0", context)

    def test_chapter_context_prioritizes_character_honorific_aliases(self):
        current = _new_chapter(0)
        current["title"] = "第四十一章 暗阁旧卷"
        current["outline"] = "少主命阁主先生交出旧案卷宗。"
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].append({
            "name": "迟到主角",
            "role": "旧案证人",
            "goal": "保住旧卷",
            "secret": "知道名册被换过",
            "voice": "谨慎克制",
            "notes": "尊称：阁主先生\n头衔：少主",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关人物】", context)
        self.assertIn("迟到主角", context)
        self.assertIn("保住旧卷", context)
        self.assertNotIn("路人0", context)

    def test_chapter_context_splits_slash_alias_values(self):
        current = _new_chapter(0)
        current["title"] = "第四十一章 暗阁旧卷"
        current["outline"] = "阁主先生交出旧案卷宗。"
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].append({
            "name": "迟到主角",
            "role": "旧案证人",
            "goal": "保住旧卷",
            "secret": "知道名册被换过",
            "voice": "谨慎克制",
            "notes": "代号：玄鸦/阁主先生/少主",
        })

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【本章相关人物】", context)
        self.assertIn("迟到主角", context)
        self.assertIn("保住旧卷", context)
        self.assertNotIn("路人0", context)

    def test_chapter_context_keeps_old_facts_and_recent_summaries(self):
        chapters = []
        for index in range(60):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"近期摘要 {index + 1}"
            chapter["key_facts"] = f"早期事实 {index + 1}"
            chapters.append(chapter)
        current = _new_chapter(60)
        current["title"] = "章节61"
        current["outline"] = "收束旧案第一阶段。"
        chapters.append(current)
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 60, "draft")

        self.assertLessEqual(len(context), 56000)
        self.assertIn("【前文继承摘要】", context)
        self.assertIn("早期事实 1", context)
        self.assertIn("近期摘要 60", context)

    def test_chapter_context_previous_summary_keeps_mid_story_milestones(self):
        chapters = []
        for index in range(80):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"日常推进 {index + 1}。"
            chapter["key_facts"] = f"阶段事实 {index + 1}。"
            chapters.append(chapter)
        chapters[34]["title"] = "第三十五章 虎符真相"
        chapters[34]["summary"] = "虎符真相揭晓，旧案内鬼露出破绽。"
        chapters[34]["key_facts"] = "虎符失踪伏笔部分回收。"
        current = _new_chapter(80)
        current["title"] = "第八十一章 终局门前"
        current["outline"] = "主角整理旧案证据。"
        chapters.append(current)
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 80, "draft")

        self.assertIn("【前文继承摘要】", context)
        self.assertIn("虎符真相揭晓", context)
        self.assertIn("近期章节（优先继承）", context)
        self.assertIn("第80章 章节80", context)

    def test_chapter_context_inherits_unsummarized_body_excerpt(self):
        previous = _new_chapter(0)
        previous["title"] = "第十章 油纸包"
        previous["text"] = "赵明打开油纸包，发现半枚虎符和旧案缺页藏在一起。"
        current = _new_chapter(1)
        current["title"] = "第十一章 暗流"
        current["outline"] = "主角带着证据入城。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("【前文继承摘要】", context)
        self.assertIn("正文摘录", context)
        self.assertIn("半枚虎符和旧案缺页", context)

    def test_chapter_context_uses_chapter_memory_without_hidden_project_materials(self):
        first = _new_chapter(0)
        first["title"] = "第一章 旧案"
        first["summary"] = "主角发现旧案卷宗。"
        first["key_facts"] = "卷宗缺少最后一页。"
        first["linked_characters"] = ["赵明"]
        current = _new_chapter(1)
        current["title"] = "第二章 入城"
        current["outline"] = "主角入城调查。"
        project = self._project_with_current_chapter(current)
        project["timeline"] = ""
        project["summary"] = ""
        project["foreshadows"] = ""
        project["chapters"] = [first, current]
        project["foreshadow_items"] = [
            {
                "name": "虎符失踪",
                "status": "已埋",
                "setup_chapter": "第一章",
                "payoff_chapter": "第二十章",
                "description": "后续牵出兵权。",
            }
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertNotIn("自动章节顺序线", context)
        self.assertIn("卷宗缺少最后一页", context)
        self.assertNotIn("自动章节压缩", context)
        self.assertNotIn("开放伏笔队列", context)
        self.assertNotIn("虎符失踪", context)

    def test_chapter_context_inherits_recent_chapter_relevance_without_manual_links(self):
        previous = _new_chapter(0)
        previous["title"] = "第五十章 暗门"
        previous["summary"] = "迟到主角带主角进入琉璃塔。"
        previous["key_facts"] = "琉璃塔地底暗门开启，迟到主角暴露旧案证人身份。"
        previous["linked_characters"] = ["迟到主角"]
        current = _new_chapter(1)
        current["title"] = "第五十一章 地底旧卷"
        current["outline"] = "主角在暗门下寻找旧卷。"
        current["linked_characters"] = []
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]
        project["characters"] = [
            {"name": f"路人{i}", "role": "过场人物", "goal": "", "secret": "", "voice": "", "notes": ""}
            for i in range(35)
        ]
        project["characters"].append({
            "name": "迟到主角",
            "role": "旧案证人",
            "goal": "带主角找到旧卷",
            "secret": "曾经藏起证词",
            "voice": "谨慎克制",
            "notes": "",
        })
        project["lore"] = [
            {"name": f"普通地点{i}", "type": "地点", "description": "无关地点"}
            for i in range(35)
        ]
        project["lore"].append({
            "name": "琉璃塔",
            "type": "地点",
            "description": "旧案证据藏匿处。",
        })

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("【近几章连续性】", context)
        self.assertIn("迟到主角", context)
        self.assertIn("旧案证人", context)
        self.assertIn("琉璃塔", context)
        self.assertNotIn("旧案证据藏匿处", context)
        self.assertNotIn("曾经藏起证词", context)

    def test_chapter_context_includes_recent_character_and_lore_state(self):
        previous = _new_chapter(0)
        previous["title"] = "第五十章 暗门"
        previous["summary"] = "赵明和迟到主角进入琉璃塔。"
        previous["key_facts"] = "迟到主角暴露旧案证人身份；琉璃塔地底暗门已开启。"
        previous["linked_characters"] = ["赵明", "迟到主角"]
        current = _new_chapter(1)
        current["title"] = "第五十一章 地底旧卷"
        current["outline"] = "赵明追问迟到主角，并继续探索琉璃塔暗门。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]
        project["characters"] = [
            {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            {"name": "迟到主角", "role": "旧案证人", "goal": "保住旧卷", "secret": "", "voice": "", "notes": ""},
        ]
        project["lore"] = [
            {"name": "琉璃塔", "type": "地点", "description": "旧案证据藏匿处。"},
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("最近状态", context)
        self.assertIn("迟到主角暴露旧案证人身份", context)
        self.assertIn("琉璃塔地底暗门已开启", context)

    def test_chapter_context_infers_recent_character_state_without_manual_links(self):
        previous = _new_chapter(0)
        previous["title"] = "第五十章 暗门"
        previous["summary"] = "赵明和迟到主角进入琉璃塔。"
        previous["key_facts"] = "迟到主角暴露旧案证人身份，交出缺页卷宗。"
        previous["linked_characters"] = []
        current = _new_chapter(1)
        current["title"] = "第五十一章 地底旧卷"
        current["outline"] = "主角继续追问旧卷来源。"
        current["linked_characters"] = []
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]
        project["characters"] = [
            {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            {"name": "迟到主角", "role": "旧案证人", "goal": "保住旧卷", "secret": "", "voice": "", "notes": ""},
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("关联人物：赵明, 迟到主角", context)
        self.assertIn("最近状态", context)
        self.assertIn("迟到主角暴露旧案证人身份", context)
        self.assertIn("交出缺页卷宗", context)

    def test_chapter_context_infers_current_character_without_manual_links(self):
        current = _new_chapter(0)
        current["title"] = "第二十章 旧卷"
        current["outline"] = "主角追问旧卷来源。"
        current["text"] = "赵明刚把旧卷收起，迟到主角便按住了暗门。"
        current["linked_characters"] = []
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            {"name": "迟到主角", "role": "旧案证人", "goal": "保住旧卷", "secret": "", "voice": "", "notes": ""},
        ]

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("关联人物：赵明, 迟到主角", context)
        self.assertIn("查清旧案", context)
        self.assertIn("保住旧卷", context)

    def test_chapter_context_includes_current_tail_for_continuation(self):
        current = _new_chapter(0)
        current["title"] = "第六十章 雨夜追问"
        current["outline"] = "主角继续追问旧案。"
        current["text"] = "前文很多。\n\n迟到主角停在檐下，雨水顺着刀鞘往下淌。\n\n他低声说：钥匙不在我这里。"
        project = self._project_with_current_chapter(current)

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【续写承接点】", context)
        self.assertIn("当前正文结尾原文", context)
        self.assertIn("钥匙不在我这里", context)
        self.assertIn("优先承接【续写承接点】", context)

    def test_chapter_context_includes_previous_chapter_tail_for_new_chapter(self):
        previous = _new_chapter(0)
        previous["title"] = "第六十章 雨夜追问"
        previous["text"] = "前文很多。\n\n迟到主角把油纸包放到桌上。\n\n纸包里露出半枚虎符。"
        current = _new_chapter(1)
        current["title"] = "第六十一章 半枚虎符"
        current["outline"] = "主角确认虎符来源。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertIn("【续写承接点】", context)
        self.assertIn("上一章「第六十章 雨夜追问」结尾", context)
        self.assertIn("纸包里露出半枚虎符", context)
        self.assertIn("自然承接上一章", context)
        self.assertIn("已发布正文", context)
        self.assertIn("禁止原样或同义重写", context)
        self.assertIn("从动作造成的新结果或新阻力开始", context)

    def test_chapter_context_includes_next_chapter_head_when_rewriting_empty_middle_chapter(self):
        previous = _new_chapter(0)
        previous["title"] = "第一章 任务开启"
        previous["text"] = "系统面板弹出，赵明看见第一个任务。"
        current = _new_chapter(1)
        current["title"] = "第二章 NPC任务窗口开业"
        current["outline"] = "赵明完成任务窗口开业，结尾接到第三章的抢首杀。"
        next_chapter = _new_chapter(2)
        next_chapter["title"] = "第三章 校花刷好感"
        next_chapter["text"] = "清晨，校门口已经围满了人。校花林雪站在人群外，盯着赵明刚亮起的NPC任务窗口。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current, next_chapter]

        context = _build_chapter_ai_context(project, 1, "draft")
        anchor = self._context_section(context, "后章衔接点")

        self.assertIn("下一章「第三章 校花刷好感」开头原文", anchor)
        self.assertIn("校花林雪站在人群外", anchor)
        self.assertIn("只用于当前章结尾对齐", anchor)
        self.assertIn("本章结尾必须自然接到下一章开头", context)

    def test_chapter_context_skips_next_chapter_head_when_current_body_exists(self):
        current = _new_chapter(0)
        current["title"] = "第二章 已有正文"
        current["outline"] = "继续写任务窗口。"
        current["text"] = "赵明已经把任务窗口打开。"
        next_chapter = _new_chapter(1)
        next_chapter["title"] = "第三章 后续"
        next_chapter["text"] = "第三章开头不应进入续写中的第二章上下文。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, next_chapter]

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertNotIn("【后章衔接点】", context)

    def test_outline_and_summary_do_not_include_next_chapter_anchor(self):
        current = _new_chapter(0)
        current["title"] = "第二章 空正文"
        current["outline"] = "补第二章。"
        next_chapter = _new_chapter(1)
        next_chapter["title"] = "第三章 后续"
        next_chapter["text"] = "第三章开头只给扩写正文参考。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, next_chapter]

        outline_context = _build_chapter_ai_context(project, 0, "outline")
        summary_context = _build_chapter_ai_context(project, 0, "summary")

        self.assertNotIn("【后章衔接点】", outline_context)
        self.assertNotIn("【后章衔接点】", summary_context)

    def test_chapter_context_keeps_previous_ending_state_beyond_last_three_paragraphs(self):
        previous = _new_chapter(0)
        previous["title"] = "第八章 雨后赴约"
        previous["text"] = (
            "前文铺垫。" * 260
            + "\n\n雨停了，路面反着冷光，雨后的长街空旷得只剩车灯。"
            + "\n\n陈景川收起手机。"
            + "\n\n他看向景辰京城总部的方向。"
            + "\n\n“去。”"
            + "\n\n他顿了顿，眼底冷意沉下去。"
            + "\n\n“但不是按他说的去。”"
        )
        current = _new_chapter(1)
        current["title"] = "第九章 京城总部"
        current["outline"] = "陈景川赶往景辰京城总部。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]

        context = _build_chapter_ai_context(project, 1, "draft")
        continuation = self._context_section(context, "续写承接点")

        self.assertIn("雨停了", continuation)
        self.assertIn("雨后的长街", continuation)
        self.assertIn("但不是按他说的去", continuation)
        self.assertIn("时间、天气、地点、人物位置", continuation)

    def test_summary_context_requires_chapter_ending_state_in_key_facts(self):
        current = _new_chapter(0)
        current["title"] = "第八章 雨后赴约"
        current["outline"] = "陈景川收到匿名短信，决定赴约。"
        current["text"] = "陈景川收到短信。\n\n雨停了，雨后的长街空旷。\n\n他决定去，但不是按对方要求去。"
        project = self._project_with_current_chapter(current)

        context = _build_chapter_ai_context(project, 0, "summary")

        self.assertIn("章节结尾的时间、天气、地点、人物位置和未完成动作", context)
        self.assertIn("雨停", context)
        self.assertIn("必须写入关键事实", context)
        self.assertIn("连续性备忘录", context)
        self.assertIn("不写剧情复述", context)
        self.assertIn("事实完整、表达短", context)
        self.assertIn("【当前状态快照】", context)
        self.assertIn('"long_form_memory"', context)
        self.assertIn("stage_archive必须为null", context)

    def test_chapter_context_keeps_current_chapter_when_materials_are_huge(self):
        previous = _new_chapter(0)
        previous["title"] = "第六十章 雨夜追问"
        previous["text"] = "上一章厚重正文。" * 1200 + "\n\n纸包里露出半枚虎符。"
        previous["summary"] = "上一章摘要。" * 600
        previous["key_facts"] = "上一章关键事实。" * 600
        current = _new_chapter(1)
        current["title"] = "第六十一章 半枚虎符"
        current["outline"] = (
            "必须保留的当前章提纲。"
            + " ".join(f"角色{i}" for i in range(24))
            + " "
            + " ".join(f"地点{i}" for i in range(28))
            + " "
            + " ".join(f"伏笔{i}" for i in range(30))
        )
        current["text"] = "当前章已有正文。" * 1000 + "\n\n必须保留的当前正文尾巴。"
        project = self._project_with_current_chapter(current)
        project["bible"] = "小说圣经资料。" * 2000
        project["world_rules"] = "世界规则资料。" * 1600
        project["timeline"] = "时间线资料。" * 2000
        project["summary"] = "全局摘要资料。" * 2000
        project["chapters"] = [previous, current]
        project["characters"] = [
            {
                "name": f"角色{i}",
                "role": "重要人物" + "身份资料。" * 40,
                "goal": "人物目标。" * 40,
                "secret": "人物秘密。" * 40,
                "voice": "语言风格。" * 40,
                "notes": "",
            }
            for i in range(24)
        ]
        project["lore"] = [
            {"name": f"地点{i}", "type": "地点", "description": "设定说明。" * 120}
            for i in range(28)
        ]
        project["foreshadow_items"] = [
            {
                "name": f"伏笔{i}",
                "status": "已埋",
                "setup_chapter": "第10章",
                "payoff_chapter": "",
                "description": "伏笔说明。" * 120,
            }
            for i in range(30)
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        self.assertLessEqual(len(context), 56000)
        self.assertIn("【当前章节】", context)
        self.assertIn("必须保留的当前章提纲", context)
        self.assertIn("必须保留的当前正文尾巴", context)
        self.assertIn("【续写承接点】", context)
        self.assertIn("纸包里露出半枚虎符", context)

    def test_chapter_context_excludes_hidden_timeline_and_summary(self):
        current = _new_chapter(0)
        current["title"] = "第八十章 终局前夜"
        current["outline"] = "主角整理所有线索，准备进入终局法庭。"
        project = self._project_with_current_chapter(current)
        project["timeline"] = "\n".join(f"时间线资料 {index}。" for index in range(1, 700))
        project["summary"] = "\n".join(f"全局摘要资料 {index}。" for index in range(1, 700))

        context = _build_chapter_ai_context(project, 0, "draft")
        self.assertNotIn("【时间线】", context)
        self.assertNotIn("【全局摘要 / 日志】", context)
        self.assertNotIn("时间线资料 1", context)
        self.assertNotIn("全局摘要资料 1", context)

    def test_chapter_context_auto_memories_exclude_future_written_facts(self):
        previous = _new_chapter(0)
        previous["title"] = "第一章 入局"
        previous["summary"] = "主角收到匿名信。"
        previous["key_facts"] = "匿名信仍由主角保管。"
        current = _new_chapter(1)
        current["title"] = "第二章 追查"
        current["outline"] = "主角调查匿名信来源。"
        future = _new_chapter(2)
        future["title"] = "第三章 真相"
        future["text"] = "未来正文揭晓管家就是寄信人。"
        future["summary"] = "管家承认寄出匿名信。"
        future["key_facts"] = "匿名信寄件人已经确认是管家。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current, future]

        context = _build_chapter_ai_context(project, 1, "draft")

        previous_section = self._context_section(context, "前文继承摘要")
        self.assertIn("主角收到匿名信", previous_section)
        self.assertNotIn("管家承认寄出匿名信", previous_section)
        self.assertNotIn("匿名信寄件人已经确认是管家", previous_section)

    def test_long_project_draft_caps_duplicate_previous_summary_at_five_thousand_chars(self):
        chapters = []
        for index in range(120):
            chapter = _new_chapter(index)
            chapter["title"] = f"第{index + 1}章 旧案推进"
            chapter["text"] = f"第{index + 1}章正文已经完成。"
            chapter["summary"] = f"第{index + 1}章摘要：" + "旧案线索继续推进。" * 30
            chapter["key_facts"] = f"第{index + 1}章关键事实：" + "该事实已经进入长期记忆。" * 30
            chapters.append(chapter)
        current = _new_chapter(120)
        current["title"] = "第121章 继续追查"
        current["outline"] = "主角依据最新证据继续追查。"
        chapters.append(current)
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 120, "draft")
        previous_section = self._context_section(context, "前文继承摘要")

        self.assertLessEqual(len(previous_section), 5000)
        self.assertIn("第120章摘要", previous_section)
        self.assertNotIn("第1章摘要", previous_section)

    def test_chapter_context_includes_long_form_progress_rhythm(self):
        chapters = []
        for index in range(40):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["text"] = "正文" * 2000
            chapter["summary"] = f"摘要 {index + 1}"
            chapter["key_facts"] = f"事实 {index + 1}"
            chapters.append(chapter)
        current = _new_chapter(40)
        current["title"] = "章节41"
        current["outline"] = "主角准备回收关键伏笔。"
        chapters.append(current)
        project = self._project_with_current_chapter(current)
        project["meta"]["target_words"] = "20万"
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 40, "draft")

        self.assertIn("【长篇进度 / 节奏】", context)
        self.assertIn("项目总目标规模：20万字", context)
        self.assertIn("当前进度字数：160000 / 200000 字，约 80.0%", context)
        self.assertIn("自动判断阶段：故事接近收束", context)
        self.assertIn("集中处理正在发酵的冲突", context)
        self.assertIn("控制本章推进密度", context)

    def test_chapter_context_includes_future_plan_boundary(self):
        current = _new_chapter(0)
        current["title"] = "第一章 半枚虎符"
        current["outline"] = "主角拿到半枚虎符，但还不能知道来源。"
        chapters = [current]
        for index in range(1, 6):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            chapters.append(chapter)
        chapters[1]["outline"] = "第二章继续追查虎符来源，只做铺垫。"
        chapters[5]["key_facts"] = "第六章揭晓虎符真相，确认旧案内鬼。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【后续规划参考】", context)
        self.assertIn("后续近章规划", context)
        self.assertIn("当前章只能铺垫", context)
        self.assertIn("虎符来源", context)
        self.assertIn("远期回收/转折锚点", context)
        self.assertIn("虎符真相", context)
        self.assertNotIn("【时间线】", context)

    def test_chapter_context_does_not_treat_prior_outline_only_plan_as_occurred(self):
        first = _new_chapter(0)
        first["title"] = "第一章 雨后入城"
        first["text"] = "赵明在雨停后进入王城。"
        first["summary"] = "赵明雨后入城。"
        planned = _new_chapter(1)
        planned["title"] = "第二章 计划夜探"
        planned["outline"] = "AI 章节规划：第二章韩乌会在老宅偷听，并拿走密信。"
        current = _new_chapter(2)
        current["title"] = "第三章 当前写作"
        current["outline"] = "赵明继续调查旧案。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [first, planned, current]

        context = _build_chapter_ai_context(project, 2, "draft")

        recent_section = self._context_section(context, "近几章连续性")
        previous_section = self._context_section(context, "前文继承摘要")
        self.assertIn("雨后入城", recent_section)
        self.assertNotIn("韩乌会在老宅偷听", recent_section)
        self.assertNotIn("拿走密信", previous_section)
        self.assertNotIn("【时间线】", context)
        self.assertNotIn("【全局摘要 / 日志】", context)

    def test_character_recent_state_ignores_prior_outline_only_plan(self):
        planned = _new_chapter(0)
        planned["title"] = "第一章 计划韩乌"
        planned["outline"] = "AI 章节规划：韩乌在老宅偷听，并拿走密信。"
        current = _new_chapter(1)
        current["title"] = "第二章 当前写作"
        current["outline"] = "韩乌正式出场。"
        current["linked_characters"] = ["韩乌"]
        project = self._project_with_current_chapter(current)
        project["chapters"] = [planned, current]
        project["characters"] = [
            {"name": "韩乌", "role": "暗线人物", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""}
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        character_section = self._context_section(context, "本章相关人物")
        self.assertIn("韩乌", character_section)
        self.assertNotIn("最近状态", character_section)
        self.assertNotIn("老宅偷听", context)
        self.assertNotIn("拿走密信", context)

    def test_lore_recent_state_ignores_prior_outline_only_plan(self):
        planned = _new_chapter(0)
        planned["title"] = "第一章 计划地点"
        planned["outline"] = "AI 章节规划：琉璃塔将在本章坍塌，密室钟声被毁。"
        current = _new_chapter(1)
        current["title"] = "第二章 当前写作"
        current["outline"] = "主角进入琉璃塔。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = [planned, current]
        project["lore"] = [
            {"name": "琉璃塔", "type": "地点", "description": "旧案档案被藏在塔顶。"}
        ]

        context = _build_chapter_ai_context(project, 1, "draft")

        lore_section = self._context_section(context, "本章相关设定")
        self.assertIn("琉璃塔", lore_section)
        self.assertNotIn("最近状态", lore_section)
        self.assertNotIn("密室钟声被毁", context)

    def test_chapter_context_future_boundary_keeps_final_milestone(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入局"
        current["outline"] = "主角只拿到第一条线索。"
        chapters = [current]
        for index in range(1, 40):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            if index >= 5:
                chapter["key_facts"] = f"第{index + 1}章回收阶段线索 {index + 1}。"
            chapters.append(chapter)
        chapters[-1]["title"] = "第四十章 终局真相"
        chapters[-1]["key_facts"] = "结局揭晓旧案最终真相，确认真正内鬼。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("远期回收/转折锚点", context)
        self.assertIn("第四十章 终局真相", context)
        self.assertIn("最终真相", context)

    def test_chapter_context_future_boundary_keeps_parentage_milestone(self):
        current = _new_chapter(0)
        current["title"] = "第一章 入局"
        current["outline"] = "主角只拿到第一条线索。"
        chapters = [current]
        for index in range(1, 40):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            chapters.append(chapter)
        chapters[-1]["title"] = "第四十章 身世夜谈"
        chapters[-1]["key_facts"] = "结局揭晓赵明亲生父亲，确认旧案血脉真相。"
        project = self._project_with_current_chapter(current)
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("远期回收/转折锚点", context)
        self.assertIn("第四十章 身世夜谈", context)
        self.assertIn("亲生父亲", context)

    def test_chapter_context_keeps_balanced_previous_summary_for_long_projects(self):
        chapters = []
        for index in range(70):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"日常推进 {index + 1}。"
            chapter["key_facts"] = f"阶段事实 {index + 1}。"
            chapters.append(chapter)
        chapters[0]["title"] = "第一章 旧案"
        chapters[0]["summary"] = "赵明发现旧案卷宗。"
        chapters[0]["key_facts"] = "卷宗缺少最后一页。"
        chapters[34]["title"] = "第三十五章 虎符真相"
        chapters[34]["summary"] = "虎符真相揭晓，旧案内鬼露出破绽。"
        chapters[34]["key_facts"] = "虎符失踪伏笔部分回收。"
        current = _new_chapter(70)
        current["title"] = "第七十一章 终局门前"
        current["outline"] = "众人抵达终局法庭。"
        chapters.append(current)
        project = self._project_with_current_chapter(current)
        project["timeline"] = ""
        project["chapters"] = chapters

        context = _build_chapter_ai_context(project, 70, "draft")

        self.assertNotIn("自动章节顺序线", context)
        self.assertIn("第1章 第一章 旧案", context)
        self.assertIn("卷宗缺少最后一页", context)
        self.assertIn("虎符真相揭晓", context)
        self.assertIn("第七十一章 终局门前", context)

    def test_chapter_context_keeps_saved_archive_notes_without_semantic_filtering(self):
        current = _new_chapter(0)
        current["title"] = "第一章 邮件泄露"
        current["outline"] = "沈慕白追查慕白资本的泄露责任链，旧钟声只作为线索出现。"
        project = self._project_with_current_chapter(current)
        project["characters"] = [
            {
                "name": "沈慕白",
                "role": "主角",
                "goal": "查清泄露责任链",
                "secret": "",
                "voice": "",
                "notes": "沈慕白对信息泄露极度敏感，会优先追查责任链。\n本章沈慕白追问泄露范围。",
            }
        ]
        project["lore"] = [
            {
                "name": "慕白资本",
                "type": "组织",
                "description": "慕白资本控制多条融资渠道，是沈家资本布局的核心工具。\n本章项目资料发往慕白资本邮箱。",
                "story_known": "慕白资本控制多条融资渠道，是沈家资本布局的核心工具。\n本章项目资料发往慕白资本邮箱。",
            }
        ]
        project["foreshadow_items"] = [
            {
                "name": "旧钟声",
                "status": "已埋",
                "setup_chapter": "第一章",
                "payoff_chapter": "第十章",
                "description": "旧钟声代表密室开启，已埋，待在琉璃塔章节回收。\n本章又提到旧钟声。\n主角看到新线索后很震惊。",
                "revealed": "旧钟声代表密室开启，已埋，待在琉璃塔章节回收。\n本章又提到旧钟声。\n主角看到新线索后很震惊。",
            }
        ]

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("沈慕白对信息泄露极度敏感", context)
        self.assertIn("慕白资本控制多条融资渠道", context)
        self.assertIn("旧钟声代表密室开启", context)
        self.assertIn("本章沈慕白追问泄露范围", context)
        self.assertIn("本章项目资料发往慕白资本邮箱", context)
        self.assertIn("本章又提到旧钟声", context)
        self.assertIn("主角看到新线索后很震惊", context)

    def test_long_form_check_reports_context_maintenance_gaps(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["text"] = "正文"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "world_rules": "",
            "timeline": "",
            "summary": "",
            "characters": [],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "foreshadow_items": [],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("阶段摘要暂缺", check_text)
        self.assertNotIn("系统会自动压缩成全局摘要", check_text)
        self.assertNotIn("时间线暂缺", check_text)
        self.assertNotIn("系统会按章节顺序生成草稿", check_text)
        self.assertIn("缺少摘要/关键事实", check_text)
        self.assertIn("应用 AI 正文后会自动补", check_text)
        self.assertIn("没有关联人物", check_text)
        self.assertIn("可用 AI 摘要按本章实际内容补齐，或手动填写", check_text)
        self.assertIn("人物卡为空", check_text)
        self.assertIn("摘要/事实覆盖：0/20", check_text)
        self.assertIn("关联人物覆盖：0/20", check_text)
        self.assertIn("后续规划覆盖：0/19", check_text)
        self.assertIn("后续章节规划较少", check_text)

    def test_long_form_check_groups_completed_chapters_missing_summary_fields(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["status"] = "已完成"
            chapter["text"] = "正文"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("标记已完成但缺少本章摘要", check_text)
        self.assertIn("长篇可优先补关键转折章", check_text)
        self.assertIn("标记已完成但缺少需继承的关键事实", check_text)
        self.assertIn("建议优先补人物关系", check_text)
        self.assertIn("等 20 章", check_text)
        self.assertEqual(check_text.count("标记已完成但缺少本章摘要"), 1)
        self.assertEqual(check_text.count("标记已完成但缺少需继承的关键事实"), 1)

    def test_short_form_check_keeps_precise_completed_chapter_summary_warnings(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 旧案"
        chapter["status"] = "已完成"
        chapter["text"] = "正文"
        project = {
            "meta": {"target_words": "3万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("第 1 章「第一章 旧案」标记已完成，但缺少本章摘要", check_text)
        self.assertIn("第 1 章「第一章 旧案」标记已完成，但缺少需继承的关键事实", check_text)

    def test_long_form_check_does_not_guess_future_reveal_from_keywords(self):
        current = _new_chapter(0)
        current["title"] = "第一章 半枚虎符"
        current["text"] = "赵明提前知道虎符真相。"
        future = _new_chapter(1)
        future["title"] = "第二章 真相"
        future["outline"] = "第二章揭晓虎符真相。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [current, future],
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("可能提前写到第二章 真相的", check_text)
        self.assertNotIn("提前兑现后续规划", check_text)

    def test_long_form_check_does_not_guess_distant_future_reveal_from_keywords(self):
        chapters = []
        current = _new_chapter(0)
        current["title"] = "第一章 入局"
        current["text"] = "赵明提前说破沈砚真实身份。"
        chapters.append(current)
        for index in range(1, 39):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            chapters.append(chapter)
        future = _new_chapter(39)
        future["title"] = "第四十章 身份真相"
        future["outline"] = "第四十章揭晓沈砚真实身份，确认他是旧案内鬼。"
        chapters.append(future)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"},
                {"name": "沈砚", "role": "反派", "goal": "隐藏旧案身份", "voice": "温和"},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("可能提前写到第四十章 身份真相的", check_text)
        self.assertNotIn("提前兑现后续规划", check_text)

    def test_long_form_check_does_not_guess_future_parentage_reveal_from_keywords(self):
        chapters = []
        current = _new_chapter(0)
        current["title"] = "第一章 入局"
        current["text"] = "赵明提前知道沈砚是亲生父亲。"
        chapters.append(current)
        for index in range(1, 39):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = f"阶段推进 {index + 1}。"
            chapters.append(chapter)
        future = _new_chapter(39)
        future["title"] = "第四十章 身世夜谈"
        future["outline"] = "第四十章揭晓沈砚亲生父亲身份，确认旧案血脉真相。"
        chapters.append(future)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"},
                {"name": "沈砚", "role": "反派", "goal": "隐藏旧案身份", "voice": "温和"},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("可能提前写到第四十章 身世夜谈的", check_text)
        self.assertNotIn("提前兑现后续规划", check_text)

    def test_long_form_check_does_not_nag_outline_only_future_chapters(self):
        chapters = []
        for index in range(24):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["status"] = "大纲"
            chapter["outline"] = f"第 {index + 1} 章剧情拍点。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("还没有正文", check_text)
        self.assertNotIn("缺少章节提纲", check_text)

    def test_writing_check_keeps_warning_for_active_chapter_without_text(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 旧案"
        chapter["status"] = "写作中"
        chapter["outline"] = "主角发现旧案。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("标记为写作中/已完成但没有正文", check_text)

    def test_long_form_check_counts_auto_detected_character_links(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["text"] = "赵明在王城调查旧案。"
            chapter["summary"] = "赵明继续调查旧案。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("关联人物覆盖：20/20", check_text)
        self.assertNotIn("没有关联人物", check_text)

    def test_long_form_check_ignores_core_role_words_without_exact_character_name(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = "主角在王城调查旧案。"
            chapter["summary"] = "主角继续调查旧案。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "克制", "notes": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("关联人物覆盖：0/20", check_text)
        self.assertIn("没有关联人物", check_text)

    def test_long_form_check_does_not_count_global_core_character_without_chapter_signal(self):
        chapters = []
        for index in range(20):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["outline"] = "剧情拍点推进。"
            chapter["summary"] = "旧案线继续推进。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "克制", "notes": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("关联人物覆盖：0/20", check_text)
        self.assertIn("没有关联人物", check_text)

    def test_writing_check_only_requires_details_for_core_or_frequent_characters(self):
        chapters = []
        for index in range(9):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = "赵明继续调查旧案。"
            chapter["text"] = "赵明在王城追查线索。"
            if index == 0:
                chapter["text"] += " 李路人递来茶盏。"
            chapters.append(chapter)
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
                {"name": "李路人", "role": "路人", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": chapters,
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("核心/高频人物「赵明」缺少人物目标", check_text)
        self.assertIn("核心/高频人物「赵明」缺少语言风格", check_text)
        self.assertNotIn("人物「李路人」缺少人物目标", check_text)
        self.assertNotIn("人物「李路人」缺少语言风格", check_text)

    def test_writing_check_accepts_linked_character_aliases(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第十章 代号现身"
        chapter["summary"] = "玄鸦交出旧案卷宗，陌生人旁听。"
        chapter["linked_characters"] = ["玄鸦", "陌生人"]
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {
                    "name": "迟到主角",
                    "role": "旧案证人",
                    "goal": "保住证据",
                    "voice": "谨慎",
                    "notes": "代号：玄鸦",
                },
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("关联人物「玄鸦」不在人物卡里", check_text)
        self.assertIn("关联人物「陌生人」不在人物卡里", check_text)

    def test_writing_check_accepts_linked_character_honorific_aliases(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第十章 尊称现身"
        chapter["summary"] = "阁主先生交出旧案卷宗。"
        chapter["linked_characters"] = ["阁主先生"]
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {
                    "name": "迟到主角",
                    "role": "旧案证人",
                    "goal": "保住证据",
                    "voice": "谨慎",
                    "notes": "尊称：阁主先生",
                },
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertNotIn("关联人物「阁主先生」不在人物卡里", check_text)

    def test_writing_check_warns_character_alias_duplicates(self):
        chapter = _new_chapter(0)
        chapter["summary"] = "玄鸦交出旧案卷宗。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [
                {
                    "name": "迟到主角",
                    "role": "旧案证人",
                    "goal": "保住证据",
                    "voice": "谨慎",
                    "notes": "代号：玄鸦",
                },
                {"name": "玄鸦", "role": "密探", "goal": "", "voice": ""},
            ],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("人物「迟到主角」和「玄鸦」疑似同一人/别称", check_text)

    def test_writing_check_warns_lore_alias_duplicates(self):
        chapter = _new_chapter(0)
        chapter["summary"] = "赵明进入白塔。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [
                {"name": "琉璃塔", "type": "地点", "description": "别称：白塔。旧案证据藏匿处。"},
                {"name": "白塔", "type": "地点", "description": "塔顶藏有旧案卷宗。"},
            ],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("设定「琉璃塔」和「白塔」疑似同一设定/别称", check_text)

    def test_writing_check_warns_foreshadow_alias_duplicates(self):
        chapter = _new_chapter(0)
        chapter["summary"] = "赵明拿到半枚虎符。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角", "goal": "查清旧案", "voice": "克制"}],
            "lore": [{"name": "王城", "type": "地点", "description": "故事主舞台"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第一章",
                    "payoff_chapter": "",
                    "description": "别称：半枚虎符。牵出兵权。",
                },
                {
                    "name": "半枚虎符",
                    "status": "已埋",
                    "setup_chapter": "第一章",
                    "payoff_chapter": "",
                    "description": "后续牵出兵权交易。",
                },
            ],
            "chapters": [chapter],
        }

        check_text = _build_writing_check_text(project)

        self.assertIn("伏笔「虎符失踪」和「半枚虎符」疑似同一线索/别称", check_text)

    def test_project_summary_draft_collects_chapter_facts_and_active_foreshadows(self):
        chapters = []
        for index in range(14):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"摘要 {index + 1}"
            chapter["key_facts"] = f"事实 {index + 1}"
            chapter["text"] = "赵明继续在王城调查旧案。"
            chapters.append(chapter)
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": chapters,
            "characters": [
                {
                    "name": "赵明",
                    "role": "主角",
                    "goal": "查清旧案",
                    "secret": "藏着旧伤",
                    "voice": "克制",
                    "notes": "",
                }
            ],
            "lore": [
                {"name": "王城", "type": "地点", "description": "旧案调查的主舞台。"},
            ],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "第20章",
                    "description": "",
                }
            ],
        }

        text = _build_project_summary_draft(project)

        self.assertIn("阶段摘要草稿", text)
        self.assertIn("近期章节", text)
        self.assertIn("事实 1", text)
        self.assertIn("事实 14", text)
        self.assertIn("高频人物快照", text)
        self.assertIn("赵明", text)
        self.assertIn("出现 14 章", text)
        self.assertIn("高频设定快照", text)
        self.assertIn("王城", text)
        self.assertIn("旧案调查的主舞台", text)
        self.assertIn("未完成伏笔", text)
        self.assertIn("虎符失踪", text)

    def test_project_summary_draft_ignores_core_role_words_without_exact_character_name(self):
        chapters = []
        for index in range(14):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = "主角继续调查旧案。"
            chapter["key_facts"] = "主角保留缺页卷宗。"
            chapters.append(chapter)
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": chapters,
            "characters": [
                {
                    "name": "赵明",
                    "role": "主角",
                    "goal": "查清旧案",
                    "secret": "",
                    "voice": "克制",
                    "notes": "",
                }
            ],
        }

        text = _build_project_summary_draft(project)

        self.assertNotIn("高频人物快照", text)
        self.assertNotIn("赵明｜出现 14 章", text)

    def test_project_summary_draft_keeps_mid_story_milestones_in_long_projects(self):
        chapters = []
        for index in range(70):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"日常推进 {index + 1}。"
            chapter["key_facts"] = f"阶段事实 {index + 1}。"
            chapters.append(chapter)
        chapters[0]["title"] = "第一章 旧案"
        chapters[0]["summary"] = "赵明发现旧案卷宗。"
        chapters[0]["key_facts"] = "卷宗缺少最后一页。"
        chapters[34]["title"] = "第三十五章 虎符真相"
        chapters[34]["summary"] = "虎符真相揭晓，旧案内鬼露出破绽。"
        chapters[34]["key_facts"] = "虎符失踪伏笔部分回收。"
        chapters[69]["title"] = "第七十章 终局门前"
        chapters[69]["summary"] = "众人抵达终局法庭。"
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": chapters,
        }

        text = _build_project_summary_draft(project)

        self.assertIn("阶段摘要草稿", text)
        self.assertIn("近期章节", text)
        self.assertIn("卷宗缺少最后一页", text)
        self.assertIn("虎符真相揭晓", text)
        self.assertIn("第七十章 终局门前", text)

    def test_project_summary_draft_keeps_complete_key_fact_units(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 雨后"
        chapter["summary"] = "陈景川收到匿名短信。"
        chapter["key_facts"] = (
            "陈景川收到匿名短信并决定赴约。"
            "雨停了，景辰京城总部外的长街进入雨后状态。"
            "陈景川手里仍握着匿名号码发来的旧手机。"
        )
        project = {"meta": {"title": "长篇测试"}, "chapters": [chapter]}

        text = _build_project_summary_draft(project)

        self.assertIn("雨停了，景辰京城总部外的长街进入雨后状态。", text)
        self.assertIn("陈景川手里仍握着匿名号码发来的旧手机。", text)
        self.assertNotIn("单条事实过长", text)
        self.assertNotIn("已裁剪", text)

    def test_project_summary_draft_uses_body_excerpt_when_summary_missing(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 油纸包"
        chapter["text"] = "赵明打开油纸包，发现半枚虎符和旧案缺页藏在一起。"
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": [chapter],
        }

        text = _build_project_summary_draft(project)

        self.assertIn("阶段摘要草稿", text)
        self.assertIn("正文摘录", text)
        self.assertIn("半枚虎符和旧案缺页", text)

    def test_project_summary_draft_prioritizes_actionable_late_foreshadow(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 旧案"
        chapter["summary"] = "主角发现旧案卷宗。"
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": [chapter],
            "foreshadow_items": [
                {
                    "name": f"普通伏笔{i}",
                    "status": "已埋",
                    "setup_chapter": "",
                    "payoff_chapter": "",
                    "description": "普通背景线索，暂不影响主线。",
                }
                for i in range(80)
            ],
        }
        project["foreshadow_items"].append({
            "name": "终局密钥",
            "status": "已埋",
            "setup_chapter": "第十章",
            "payoff_chapter": "第五十章",
            "description": "关系最终真相，必须在后期回收。",
        })

        text = _build_project_summary_draft(project)

        self.assertIn("未完成伏笔", text)
        self.assertIn("终局密钥", text)
        self.assertIn("第五十章", text)
        self.assertLess(text.index("终局密钥"), text.index("普通伏笔0"))

    def test_project_timeline_draft_collects_written_chapter_order_and_linked_characters(self):
        first = _new_chapter(0)
        first["title"] = "第一章 旧案"
        first["summary"] = "主角发现旧案卷宗。"
        first["key_facts"] = "卷宗缺少最后一页。"
        first["linked_characters"] = ["赵明"]
        second = _new_chapter(1)
        second["title"] = "第二章 入城"
        second["outline"] = "主角入城，遇见线人。"
        project = {"chapters": [first, second]}

        text = _build_project_timeline_draft(project)

        self.assertIn("时间线草稿", text)
        self.assertIn("第一章 旧案", text)
        self.assertIn("卷宗缺少最后一页", text)
        self.assertIn("人物：赵明", text)
        self.assertNotIn("第二章 入城", text)
        self.assertNotIn("提纲：主角入城", text)

    def test_project_timeline_draft_uses_body_excerpt_when_summary_missing(self):
        first = _new_chapter(0)
        first["title"] = "第一章 油纸包"
        first["text"] = "赵明打开油纸包，发现半枚虎符和旧案缺页藏在一起。"
        project = {"chapters": [first]}

        text = _build_project_timeline_draft(project)

        self.assertIn("时间线草稿", text)
        self.assertIn("正文摘录", text)
        self.assertIn("半枚虎符和旧案缺页", text)

    def test_project_timeline_draft_uses_auto_detected_characters(self):
        first = _new_chapter(0)
        first["title"] = "第一章 旧案"
        first["summary"] = "赵明发现旧案卷宗。"
        first["text"] = "赵明在王城找到旧案卷宗。"
        project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "", "secret": "", "voice": "", "notes": ""},
            ],
            "lore": [
                {"name": "王城", "type": "地点", "description": "故事主舞台"},
            ],
            "chapters": [first],
        }

        text = _build_project_timeline_draft(project)

        self.assertIn("人物：赵明", text)
        self.assertIn("设定：王城", text)

    def test_project_timeline_draft_ignores_core_role_words_without_exact_character_name(self):
        first = _new_chapter(0)
        first["title"] = "第一章 旧案"
        first["summary"] = "主角发现旧案卷宗。"
        first["key_facts"] = "主角拿到缺页卷宗。"
        project = {
            "characters": [
                {"name": "赵明", "role": "主角", "goal": "查清旧案", "secret": "", "voice": "", "notes": ""},
            ],
            "chapters": [first],
        }

        text = _build_project_timeline_draft(project)

        self.assertNotIn("人物：赵明", text)

    def test_project_timeline_draft_uses_lore_alias_from_description(self):
        first = _new_chapter(0)
        first["title"] = "第一章 白塔钟声"
        first["summary"] = "赵明进入白塔，发现旧案卷宗。"
        project = {
            "lore": [
                {"name": "琉璃塔", "type": "地点", "description": "别称：白塔。旧案证据藏匿处。"},
            ],
            "chapters": [first],
        }

        text = _build_project_timeline_draft(project)

        self.assertIn("设定：琉璃塔", text)

    def test_project_timeline_draft_ignores_generic_stage_terms_without_exact_lore_name(self):
        first = _new_chapter(0)
        first["title"] = "第一章 回城"
        first["outline"] = "主角回到主舞台，在朝堂继续调查旧案。"
        project = {
            "lore": [
                *[
                    {"name": f"普通设定{i}", "type": "地点", "description": "偏远地点，暂不影响主线。"}
                    for i in range(35)
                ],
                {"name": "王城", "type": "地点", "description": "故事主舞台，朝堂和旧案卷宗都在这里交汇。"},
            ],
            "chapters": [first],
        }

        text = _build_project_timeline_draft(project)

        self.assertNotIn("设定：王城", text)
        self.assertNotIn("普通设定0", text)

    def test_project_summary_draft_ignores_lore_activity_from_generic_stage_terms(self):
        chapters = []
        for index in range(14):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"摘要 {index + 1}"
            chapter["key_facts"] = f"事实 {index + 1}"
            chapter["text"] = "主角回到主舞台，在朝堂继续调查旧案。"
            chapters.append(chapter)
        project = {
            "meta": {"title": "长篇测试", "premise": "旧案重启。"},
            "chapters": chapters,
            "lore": [
                {"name": "王城", "type": "地点", "description": "故事主舞台，朝堂和旧案卷宗都在这里交汇。"},
            ],
        }

        text = _build_project_summary_draft(project)

        self.assertNotIn("高频设定快照", text)
        self.assertNotIn("王城｜地点｜出现 14 章", text)

    def test_project_timeline_draft_compresses_long_projects_with_milestones(self):
        chapters = []
        for index in range(70):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"日常推进 {index + 1}。"
            chapter["key_facts"] = f"阶段事实 {index + 1}。"
            chapters.append(chapter)
        chapters[0]["title"] = "第一章 旧案"
        chapters[0]["summary"] = "赵明发现旧案卷宗。"
        chapters[0]["key_facts"] = "卷宗缺少最后一页。"
        chapters[34]["title"] = "第三十五章 虎符真相"
        chapters[34]["summary"] = "虎符真相揭晓，旧案内鬼露出破绽。"
        chapters[34]["key_facts"] = "虎符失踪伏笔部分回收。"
        chapters[69]["title"] = "第七十章 终局门前"
        chapters[69]["summary"] = "众人抵达终局法庭。"
        project = {"chapters": chapters}

        text = _build_project_timeline_draft(project)

        self.assertIn("第一章 旧案", text)
        self.assertIn("卷宗缺少最后一页", text)
        self.assertIn("虎符真相揭晓", text)
        self.assertIn("第七十章 终局门前", text)
        self.assertNotIn("已平衡压缩", text)

    def test_project_timeline_draft_does_not_cut_recent_fact_mid_sentence(self):
        chapters = []
        for index in range(60):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"短摘要{index + 1}。"
            chapter["key_facts"] = f"短事实{index + 1}。"
            chapters.append(chapter)
        chapters[-1]["title"] = "第六十章 雨后"
        chapters[-1]["summary"] = "陈景川抵达景辰京城总部。"
        chapters[-1]["key_facts"] = (
            "雨停了，景辰京城总部外的长街进入雨后状态。"
            "陈景川没有按匿名短信要求进入正门，而是转向地下车库。"
        )
        project = {"chapters": chapters}

        text = _build_project_timeline_draft(project)

        self.assertIn("雨停了，景辰京城总部外的长街进入雨后状态。", text)
        self.assertIn("陈景川没有按匿名短信要求进入正门，而是转向地下车库。", text)
        self.assertNotIn("地下车", text.replace("地下车库", ""))

    def test_project_timeline_draft_keeps_many_short_recent_lines_by_budget(self):
        chapters = []
        for index in range(80):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = f"短摘要{index + 1}。"
            chapter["key_facts"] = f"短事实{index + 1}。"
            chapters.append(chapter)
        project = {"chapters": chapters}

        text = _build_project_timeline_draft(project)

        self.assertIn("章节50", text)
        self.assertIn("章节80", text)

    def test_active_snapshots_keep_complete_character_and_lore_facts(self):
        chapters = []
        for index in range(14):
            chapter = _new_chapter(index)
            chapter["title"] = f"章节{index + 1}"
            chapter["summary"] = "陈景川在景辰京城总部推进调查。"
            chapter["text"] = "陈景川来到景辰京城总部。"
            chapters.append(chapter)
        project = {
            "chapters": chapters,
            "characters": [
                {
                    "name": "陈景川",
                    "role": "主角",
                    "goal": "查清景辰京城总部内部泄密。雨停后必须从地下车库进入。",
                    "secret": "匿名短信来自旧手机。这个秘密暂时不能告诉团队。",
                    "voice": "说话克制，命令短促。",
                    "notes": "",
                }
            ],
            "lore": [
                {
                    "name": "景辰京城总部",
                    "type": "地点",
                    "description": "雨停后总部正门仍被监控覆盖。地下车库是陈景川选择的入口。",
                }
            ],
        }

        text = _build_project_summary_draft(project)

        self.assertIn("雨停后必须从地下车库进入。", text)
        self.assertIn("匿名短信来自旧手机。", text)
        self.assertIn("地下车库是陈景川选择的入口。", text)
        self.assertNotIn("地下车……", text)

    def test_foreshadow_notes_draft_groups_structured_items(self):
        project = {
            "foreshadow_items": [
                {
                    "code": "F0001",
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "第20章",
                    "description": "读者以为只是偷盗。",
                    "notes": "命中编号：F0001\n建议说明：这是给用户看的审计备注。",
                },
                {
                    "code": "F0002",
                    "name": "旧钟声",
                    "status": "已回收",
                    "setup_chapter": "第3章",
                    "payoff_chapter": "第12章",
                    "description": "密室开启。",
                },
            ]
        }

        text = _build_foreshadow_notes_draft(project)

        self.assertIn("伏笔汇总草稿", text)
        self.assertIn("已埋：", text)
        self.assertIn("F0001｜虎符失踪", text)
        self.assertIn("虎符失踪", text)
        self.assertIn("第2章 -> 第20章", text)
        self.assertIn("已回收：", text)
        self.assertIn("旧钟声", text)
        self.assertNotIn("这是给用户看的审计备注", text)

    def test_foreshadow_notes_draft_limits_large_resolved_groups(self):
        project = {
            "foreshadow_items": [
                {
                    "name": f"待回收伏笔{i}",
                    "status": "已埋",
                    "setup_chapter": f"第{i + 1}章",
                    "payoff_chapter": "",
                    "description": "后续处理。",
                }
                for i in range(3)
            ] + [
                {
                    "name": f"已回收线索{i}",
                    "status": "已回收",
                    "setup_chapter": f"第{i + 1}章",
                    "payoff_chapter": f"第{i + 2}章",
                    "description": "已经处理。",
                }
                for i in range(20)
            ]
        }

        text = _build_foreshadow_notes_draft(project)

        self.assertIn("待回收伏笔0", text)
        self.assertIn("已回收线索19", text)
        self.assertIn("已回收线索0", text)
        self.assertNotIn("另有 12 条已回收伏笔已省略", text)

    def test_foreshadow_notes_draft_prioritizes_actionable_buried_items(self):
        project = {
            "foreshadow_items": [
                {
                    "name": f"普通已埋伏笔{i}",
                    "status": "已埋",
                    "setup_chapter": "",
                    "payoff_chapter": "",
                    "description": "普通背景线索，暂不影响主线。",
                }
                for i in range(45)
            ]
        }
        project["foreshadow_items"].append({
            "name": "终局密钥",
            "status": "已埋",
            "setup_chapter": "第十章",
            "payoff_chapter": "第五十章",
            "description": "关系最终真相，必须在后期回收。",
        })

        text = _build_foreshadow_notes_draft(project)

        self.assertIn("已埋：", text)
        self.assertIn("终局密钥", text)
        self.assertIn("第十章 -> 第五十章", text)
        self.assertLess(text.index("终局密钥"), text.index("普通已埋伏笔0"))
        self.assertIn("普通已埋伏笔44", text)

    def test_foreshadow_notes_draft_keeps_complete_description_units(self):
        project = {
            "foreshadow_items": [
                {
                    "name": "旧手机匿名短信",
                    "status": "已埋",
                    "setup_chapter": "第八章",
                    "payoff_chapter": "第十二章",
                    "description": (
                        "匿名短信不是普通威胁。"
                        "旧手机号码会指向景辰京城总部内部泄密者。"
                        "回收时必须确认陈景川没有按短信要求走正门。"
                    ),
                }
            ]
        }

        text = _build_foreshadow_notes_draft(project)

        self.assertIn("旧手机号码会指向景辰京城总部内部泄密者。", text)
        self.assertIn("回收时必须确认陈景川没有按短信要求走正门。", text)
        self.assertNotIn("内部泄……", text)

    def test_infer_foreshadow_status_only_normalizes_explicit_status(self):
        buried = {
            "name": "虎符失踪",
            "setup_chapter": "第二章",
            "description": "第十章待揭晓，尚未解释真相。",
        }
        unburied = {
            "name": "暗门机关",
            "description": "后期未兑现，真相未明。",
        }
        resolved = {
            "name": "旧钟声",
            "description": "密室钟声的真相揭晓，机关已经解开。",
        }
        explicit_buried = {"name": "虎符失踪", "status": "待回收", "description": "第十章待揭晓。"}
        explicit_resolved = {"name": "旧钟声", "status": "已兑现", "description": "密室钟声的真相揭晓。"}
        explicit_no_need = {"name": "白兔挂件", "status": "不必回收", "description": "低价值道具线。"}

        self.assertEqual(_infer_foreshadow_status(buried), "未埋")
        self.assertEqual(_infer_foreshadow_status(unburied), "未埋")
        self.assertEqual(_infer_foreshadow_status(resolved), "未埋")
        self.assertEqual(_infer_foreshadow_status(explicit_buried), "已埋")
        self.assertEqual(_infer_foreshadow_status(explicit_resolved), "已回收")
        self.assertEqual(_infer_foreshadow_status(explicit_no_need), "无需回收")

    def test_writing_check_does_not_infer_foreshadow_payoff_from_chapter_facts(self):
        chapter = _new_chapter(19)
        chapter["title"] = "第二十章 虎符真相"
        chapter["summary"] = "虎符失踪的真相揭晓。"
        chapter["key_facts"] = "虎符失踪在本章回收，确认牵出兵权。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "虎符", "type": "物品", "description": "兵权信物"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "",
                    "description": "后续牵出兵权。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「虎符失踪」可能已在", text)
        self.assertIn("伏笔「虎符失踪」已埋，但还没有填写回收章节", text)

    def test_writing_check_does_not_treat_unresolved_payoff_wording_as_recovered(self):
        chapter = _new_chapter(9)
        chapter["title"] = "第十章 虎符疑云"
        chapter["summary"] = "虎符失踪仍待揭晓。"
        chapter["key_facts"] = "虎符失踪尚未解释，真相未明。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "虎符", "type": "物品", "description": "兵权信物"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "",
                    "description": "后续牵出兵权。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「虎符失踪」可能已在", text)
        self.assertIn("伏笔「虎符失踪」已埋，但还没有填写回收章节", text)

    def test_writing_check_does_not_infer_foreshadow_payoff_from_unsummarized_body(self):
        chapter = _new_chapter(19)
        chapter["title"] = "第二十章 雨夜"
        chapter["text"] = "赵明终于回收虎符失踪这条线索，揭晓虎符真相，确认牵出兵权。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "虎符", "type": "物品", "description": "兵权信物"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已埋",
                    "setup_chapter": "第2章",
                    "payoff_chapter": "",
                    "description": "后续牵出兵权。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「虎符失踪」可能已在", text)
        self.assertIn("伏笔「虎符失踪」已埋，但还没有填写回收章节", text)

    def test_writing_check_does_not_infer_foreshadow_setup_from_unsummarized_body(self):
        chapter = _new_chapter(1)
        chapter["title"] = "第二章 雨夜"
        chapter["text"] = "赵明发现虎符失踪，暗中留下半枚虎符作为线索。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "虎符", "type": "物品", "description": "兵权信物"}],
            "foreshadow_items": [
                {
                    "name": "虎符失踪",
                    "status": "已回收",
                    "setup_chapter": "",
                    "payoff_chapter": "第二十章",
                    "description": "后续牵出兵权。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「虎符失踪」可能已在", text)
        self.assertIn("伏笔「虎符失踪」已回收，但缺少埋设章节记录", text)

    def test_writing_check_does_not_infer_foreshadow_payoff_from_alias(self):
        chapter = _new_chapter(11)
        chapter["title"] = "第十二章 密室开启"
        chapter["summary"] = "密室钟声的真相揭晓。"
        chapter["key_facts"] = "密室钟声在本章回收，确认暗门已经开启。"
        project = {
            "meta": {"target_words": "20万", "premise": "旧案重启。"},
            "bible": "小说圣经",
            "characters": [{"name": "赵明", "role": "主角"}],
            "lore": [{"name": "琉璃塔", "type": "地点", "description": "旧案证据藏匿处"}],
            "foreshadow_items": [
                {
                    "name": "旧钟声",
                    "status": "已埋",
                    "setup_chapter": "第3章",
                    "payoff_chapter": "",
                    "description": "别称：密室钟声。钟声响起表示暗门开启。",
                }
            ],
            "chapters": [chapter],
        }

        text = _build_writing_check_text(project)

        self.assertNotIn("伏笔「旧钟声」可能已在", text)
        self.assertIn("伏笔「旧钟声」已埋，但还没有填写回收章节", text)

    def test_stage_boundary_locally_preserves_untouched_catalog_and_saves_hashes(self):
        chapters = [_new_chapter(index) for index in range(10)]
        project = self._project_with_current_chapter(chapters[9])
        project["chapters"] = chapters
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 9,
            "active_facts": [
                {"id": "AF-0001", "scope": "case:a", "fact": "事实甲"},
                {"id": "AF-0002", "scope": "case:b", "fact": "事实乙"},
            ],
            "state_snapshot": {
                "character_states": [{"character_id": "char-a", "state": "继续查案"}],
                "object_states": [{"key": "账册", "name": "账册", "state": "仍在柜中"}],
                "active_conflicts": [{"id": "CF-0007", "conflict": "旧案争端持续"}],
                "unresolved_tasks": [{"id": "TASK-0008", "task": "继续核对账册"}],
            },
        }
        update = self._strict_update(project, 9)
        update["stage_archive"] = {
            "summary": "阶段状态保持稳定。",
            "irreversible_facts": [],
            "relationship_changes": [],
            "unresolved_threads": ["旧案仍待调查"],
            "next_stage_entry": "继续核对账册。",
        }

        self.assertTrue(_apply_long_form_memory_update(project, 9, update))

        integrity = project["chapters"][9]["memory_boundary_integrity"]
        self.assertTrue(integrity["verified"])
        self.assertEqual(integrity["before"]["counts"], integrity["after"]["counts"])
        self.assertEqual(integrity["before"]["sha256"], integrity["after"]["sha256"])
        archive = project["long_form_memory"]["stage_archives"][-1]
        self.assertEqual(archive["catalog_integrity"]["after"]["sha256"], integrity["after"]["sha256"])

    def test_stage_boundary_hash_changes_when_same_fact_id_content_changes(self):
        chapters = [_new_chapter(index) for index in range(10)]
        project = self._project_with_current_chapter(chapters[9])
        project["chapters"] = chapters
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 9,
            "active_facts": [{
                "id": "AF-0001", "scope": "case:a", "fact": "旧案仍未查明",
            }],
        }
        update = self._strict_update(project, 9)
        update["fact_updates"] = [{
            "operation": "update",
            "id": "AF-0001",
            "scope": "case:a",
            "fact": "旧案已经确认由内鬼篡改",
            "evidence_quote": "旧案已经确认由内鬼篡改",
        }]
        update["fact_lifecycle_review"]["reviewed_refs"] = ["AF-0001"]
        update["stage_archive"] = {
            "summary": "旧案取得进展。",
            "irreversible_facts": ["旧案由内鬼篡改"],
            "relationship_changes": [],
            "unresolved_threads": [],
            "next_stage_entry": "追查内鬼。",
        }

        self.assertTrue(_apply_long_form_memory_update(project, 9, update))

        integrity = project["chapters"][9]["memory_boundary_integrity"]
        self.assertTrue(integrity["verified"])
        self.assertEqual(integrity["before"]["counts"], integrity["after"]["counts"])
        self.assertEqual(integrity["before"]["hash_version"], 2)
        self.assertNotEqual(integrity["before"]["sha256"], integrity["after"]["sha256"])

    def test_same_scope_fact_update_retains_prior_details_in_active_context(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "active_facts": [{
                "id": "AF-0001",
                "scope": "patient:unknown:identity_evidence",
                "fact": "四类身份数据库全空，衣物材质不属于已知现代生产体系。",
                "evidence": "四个库，全空。衣服也不是现代生产体系的材料。",
                "evidence_chapter_index": 1,
            }],
        }
        update = self._strict_update(project)
        update["fact_updates"] = [{
            "operation": "update",
            "id": "AF-0001",
            "scope": "patient:unknown:identity_evidence",
            "fact": "病人身份数据库无记录，仍然无法登记。",
            "evidence_quote": "身份数据库无记录，无法登记",
        }]
        update["fact_lifecycle_review"]["reviewed_refs"] = ["AF-0001"]

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        active = project["long_form_memory"]["active_facts"][0]
        self.assertEqual(active["fact"], "病人身份数据库无记录，仍然无法登记。")
        self.assertIn("四类身份数据库全空", active["continuity_details"][0]["fact"])
        sections = _long_form_memory_sections(
            project,
            {"fact_ids": ["AF-0001"], "_restrict_facts": True, "_compact_facts": True},
        )
        self.assertIn("同主题既有证据细节", sections["活跃连续性事实"])
        self.assertIn("衣物材质不属于已知现代生产体系", sections["活跃连续性事实"])

    def test_legacy_fact_history_restores_prior_details_in_active_context(self):
        chapter = _new_chapter(1)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 1,
            "active_facts": [{
                "id": "AF-0001",
                "scope": "patient:unknown:identity_evidence",
                "fact": "病人身份数据库无记录，仍然无法登记。",
                "evidence_chapter_index": 2,
            }],
            "fact_history": [{
                "id": "AF-0001",
                "scope": "patient:unknown:identity_evidence",
                "fact": "四类身份数据库全空，衣物材质不属于已知现代生产体系。",
                "evidence": "四个库，全空。衣服也不是现代生产体系的材料。",
                "evidence_chapter_index": 1,
            }],
        }

        sections = _long_form_memory_sections(
            project,
            {"fact_ids": ["AF-0001"], "_restrict_facts": True, "_compact_facts": True},
        )

        self.assertIn("病人身份数据库无记录", sections["活跃连续性事实"])
        self.assertIn("同主题既有证据细节", sections["活跃连续性事实"])
        self.assertIn("四类身份数据库全空", sections["活跃连续性事实"])
        self.assertIn("衣物材质不属于已知现代生产体系", sections["活跃连续性事实"])

    def test_outline_named_lore_requires_runtime_review_outcome(self):
        chapter = _new_chapter(0)
        chapter["outline"] = "本章涉及设定：生命方舟基金会；主线任务：揭示其技术路线。"
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{
            "id": "lore-ark",
            "name": "生命方舟基金会",
            "type": "势力",
        }]
        project["long_form_memory"] = {"schema_version": "2", "revision": 0}
        update = self._strict_update(project)
        final_text = "赫尔曼只谈自己的研究，生命方舟基金会本章没有新增公开信息。"

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=final_text,
            require_revision=True, require_evidence=True,
        )

        self.assertTrue(any("提纲或长期事件设定运行态未复核" in error for error in errors))
        self.assertTrue(any("lore_refs遗漏提纲或长期事件引用" in error for error in errors))

        update["state_reconciliation"]["lore_refs"] = ["lore-ark"]
        update["state_reconciliation"]["record_runtime_review"] = {
            "reviewed_lore_refs": ["lore-ark"],
            "unchanged_lore_refs": ["lore-ark"],
            "reviewed_foreshadow_refs": [],
            "unchanged_foreshadow_refs": [],
        }
        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=final_text,
            require_revision=True, require_evidence=True,
        )
        self.assertFalse(any("提纲或长期事件" in error for error in errors), errors)

    def test_long_term_events_must_cover_changed_fact_and_lore_refs(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{"id": "lore-a", "name": "旧案卷宗", "type": "证据"}]
        project["long_form_memory"] = {"schema_version": "2", "revision": 0}
        update = self._strict_update(project)
        update["fact_updates"] = [{
            "operation": "add",
            "key": "NF1",
            "scope": "case:ledger:evidence",
            "fact": "旧案卷宗出现新的批注。",
            "evidence_quote": "旧案卷宗出现新的批注",
        }]
        update["record_updates"]["lore"] = [{
            "operation": "update",
            "ref": "lore-a",
            "key": "",
            "name": "旧案卷宗",
            "state": "新增批注已经公开。",
            "story_known": "新增批注已经公开。",
            "canon": {},
            "evidence_quote": "旧案卷宗出现新的批注",
        }]
        update["state_reconciliation"]["fact_refs"] = ["NF1"]
        update["state_reconciliation"]["lore_refs"] = ["lore-a"]
        update["state_reconciliation"]["record_runtime_review"] = {
            "reviewed_lore_refs": ["lore-a"],
            "unchanged_lore_refs": [],
            "reviewed_foreshadow_refs": [],
            "unchanged_foreshadow_refs": [],
        }
        final_text = "赵明发现旧案卷宗出现新的批注。"

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=final_text,
            require_revision=True, require_evidence=True,
        )
        self.assertTrue(any("storage.fact_refs遗漏" in error for error in errors))
        self.assertTrue(any("storage.lore_refs遗漏" in error for error in errors))

        update["long_term_events"] = [{
            "event": "旧案卷宗出现新的批注",
            "category": "evidence",
            "evidence_quote": "旧案卷宗出现新的批注",
            "storage": {
                "fact_refs": ["NF1"], "character_refs": [],
                "lore_refs": ["lore-a"], "foreshadow_refs": [],
                "object_keys": [], "conflict_refs": [], "task_refs": [],
            },
        }]
        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=final_text,
            require_revision=True, require_evidence=True,
        )
        self.assertFalse(any("long_term_events.storage" in error for error in errors), errors)

    def test_long_term_event_storage_is_inherited_by_next_chapter_selection(self):
        chapters = [_new_chapter(0), _new_chapter(1)]
        project = self._project_with_current_chapter(chapters[0])
        project["chapters"] = chapters
        project["characters"] = [{"id": "char-a", "name": "赵明"}]
        project["lore"] = [{"id": "lore-a", "name": "旧案卷宗", "type": "证据"}]
        project["foreshadow_items"] = [{
            "id": "foreshadow-a", "name": "失踪账页", "status": "已埋",
        }]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 0,
            "active_facts": [{"id": "AF-0001", "scope": "case:a", "fact": "账页仍失踪"}],
            "state_snapshot": {
                "object_states": [{"key": "旧案卷宗", "name": "旧案卷宗", "state": "由赵明保管"}],
                "active_conflicts": [{"id": "CF-0001", "conflict": "旧案争端持续"}],
                "unresolved_tasks": [{"id": "TASK-0001", "task": "继续寻找账页"}],
            },
        }
        update = self._strict_update(project)
        update["long_term_events"] = [{
            "event": "赵明继续保管卷宗并追查失踪账页",
            "category": "evidence",
            "evidence_quote": "赵明继续保管卷宗",
            "storage": {
                "fact_refs": ["AF-0001"],
                "character_refs": ["char-a"],
                "lore_refs": ["lore-a"],
                "foreshadow_refs": ["foreshadow-a"],
                "object_keys": ["旧案卷宗"],
                "conflict_refs": ["CF-0001"],
                "task_refs": ["TASK-0001"],
            },
        }]

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        selection = project["chapters"][1]["memory_selection"]
        self.assertIn("char-a", selection["character_ids"])
        self.assertIn("lore-a", selection["lore_ids"])
        self.assertNotIn("foreshadow_ids", selection)
        self.assertIn("AF-0001", selection["fact_ids"])
        self.assertIn("旧案卷宗", selection["object_keys"])
        self.assertIn("CF-0001", selection["conflict_ids"])
        self.assertIn("TASK-0001", selection["task_ids"])

    def test_long_term_lore_event_requires_explicit_runtime_review_outcome(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{"id": "lore-a", "name": "黑色石片", "type": "关键物"}]
        project["long_form_memory"] = {"schema_version": "2", "revision": 0}
        update = self._strict_update(project)
        update["long_term_events"] = [{
            "event": "黑色石片研究权限上收",
            "category": "key_object",
            "evidence_quote": "黑色石片研究权限已经上收九处",
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": ["lore-a"],
                "foreshadow_refs": [], "object_keys": [], "conflict_refs": [],
                "task_refs": [],
            },
        }]
        update["state_reconciliation"]["lore_refs"] = ["lore-a"]
        final_text = "陆九川确认，黑色石片研究权限已经上收九处。"

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=final_text,
            require_revision=True, require_evidence=True,
        )

        self.assertTrue(any("设定运行态未复核" in error for error in errors))
        update["state_reconciliation"]["record_runtime_review"] = {
            "reviewed_lore_refs": ["lore-a"],
            "unchanged_lore_refs": ["lore-a"],
            "reviewed_foreshadow_refs": [],
            "unchanged_foreshadow_refs": [],
        }
        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=final_text,
            require_revision=True, require_evidence=True,
        )
        self.assertFalse(any("运行态" in error for error in errors), errors)

    def test_memory_update_requires_mechanism_claim_body_check(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {"schema_version": "2", "revision": 0}
        update = self._strict_update(project)
        update["state_reconciliation"]["coverage_checks"].pop(
            "mechanism_claims_match_body"
        )

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text="本章没有长期变化。",
            require_revision=True, require_evidence=True,
        )

        self.assertTrue(any("mechanism_claims_match_body" in error for error in errors))

    def test_style_finalize_acceptance_requires_every_beat_and_sample_structure(self):
        reference = "\n".join(
            f"样本第{index}段连续说明人物行动和事情结果。"
            for index in range(40)
        )
        body_lines = [
            f"正文第{index}段继续推进人物行动和事情结果。"
            for index in range(38)
        ]
        body_lines[5] = "赵明进入仓库，并在墙后找到了暗格。"
        body_lines[28] = "暗格打开以后，里面只剩下半页账册。"
        body = "\n".join(body_lines)
        execution = (
            "1. 赵明进入仓库并找到暗格。\n"
            "2. 暗格内只有半页账册。\n"
            "静默继承边界：旧案卷宗仍由赵明保管。"
        )
        acceptance = {
            "beat_evidence": [{
                "beat": 1,
                "evidence_quote": "赵明进入仓库，并在墙后找到了暗格",
            }],
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
            "paragraph_structure_check": True,
        }

        errors = _style_finalize_acceptance_errors(
            execution, body, acceptance, reference, len(body)
        )
        self.assertEqual(errors, [])

        acceptance["beat_evidence"].append({
            "beat": 2,
            "evidence_quote": "暗格打开以后，里面只剩下半页账册",
        })
        errors = _style_finalize_acceptance_errors(
            execution, body, acceptance, reference, len(body)
        )
        self.assertEqual(errors, [])

        errors = _style_finalize_acceptance_errors(
            execution,
            body,
            acceptance,
            reference,
            len(body),
            style_plan="角色声纹矩阵：赵明只使用短问。",
        )
        self.assertEqual(errors, [])
        acceptance["role_voice_attribution_check"] = True
        self.assertEqual(
            _style_finalize_acceptance_errors(
                execution,
                body,
                acceptance,
                reference,
                len(body),
                style_plan="角色声纹矩阵：赵明只使用短问。",
            ),
            [],
        )

        acceptance.pop("logic_continuity_check")
        errors = _style_finalize_acceptance_errors(
            execution, body, acceptance, reference, len(body)
        )
        self.assertEqual(errors, [])
        acceptance["logic_continuity_check"] = True

        acceptance.pop("paragraph_structure_check")
        errors = _style_finalize_acceptance_errors(
            execution, body, acceptance, reference, len(body)
        )
        self.assertEqual(errors, [])

        fragmented = "\n".join(f"短段推进{index}。" for index in range(100))
        errors = _style_finalize_acceptance_errors(
            execution, fragmented, acceptance, reference, len(fragmented)
        )
        self.assertTrue(any("段落密度" in error or "短段" in error for error in errors))

    def test_style_finalize_acceptance_blocks_published_boundary_replay(self):
        previous = _new_chapter(0)
        previous["text"] = "医生刚把手收回。\n\n“他还没死。”\n\n滴——"
        current = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]
        execution = "1. 章首新增变量：护士循声查看监护屏，并发现新的血氧变化。"
        repeated_body = "滴——监护仪再次响起。\n\n护士猛地抬头，顺着声音看向监护屏。"
        acceptance = {
            "beat_evidence": [{
                "beat": 1,
                "evidence_quote": "护士猛地抬头，顺着声音看向监护屏",
            }],
            "opening_continuation": {
                "first_new_sentence": "滴——监护仪再次响起",
                "new_action_or_result": "监护仪发出新的报警",
            },
            "timeline_commitment_check": {
                "prior_deadline_or_promise": "无",
                "current_schedule": "无",
                "compatible": True,
            },
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
            "paragraph_structure_check": True,
        }

        errors = _style_finalize_acceptance_errors(
            execution,
            repeated_body,
            acceptance,
            project=project,
            chapter_index=1,
        )

        self.assertTrue(any("章首承接重复上一章已发布结尾" in error for error in errors))

        clean_body = "护士猛地抬头，顺着蜂鸣声看向监护屏。\n\n屏幕上的血氧数值突然开始回升。"
        acceptance["beat_evidence"][0]["evidence_quote"] = "护士猛地抬头，顺着蜂鸣声看向监护屏"
        acceptance["opening_continuation"] = {
            "first_new_sentence": "护士猛地抬头，顺着蜂鸣声看向监护屏",
            "new_action_or_result": "护士对声音作出新反应并发现血氧回升",
        }
        timeline_check = acceptance.pop("timeline_commitment_check")
        errors = _style_finalize_acceptance_errors(
            execution,
            clean_body,
            acceptance,
            project=project,
            chapter_index=1,
        )
        self.assertEqual(errors, [])
        acceptance["timeline_commitment_check"] = timeline_check
        errors = _style_finalize_acceptance_errors(
            execution,
            clean_body,
            acceptance,
            project=project,
            chapter_index=1,
        )
        self.assertEqual(errors, [])

    def test_style_finalize_acceptance_does_not_force_voice_scenes_or_evidence(self):
        execution = "1. 赵明拒绝对方索要账册，并当场指出问题。"
        body = (
            "“把账册交出来。”\n\n"
            "赵明把账册按回桌上。\n\n"
            "“不是，你当我看不懂这点把戏？”\n\n"
            "对面的人顿时噎住。"
        )
        acceptance = {
            "beat_evidence": [{
                "beat": 1,
                "evidence_quote": "赵明把账册按回桌上",
            }],
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
            "paragraph_structure_check": True,
            "role_voice_attribution_check": True,
        }
        style_plan = "【常驻人物语言声纹｜每章静默执行】只校准实际说话人物。"

        errors = _style_finalize_acceptance_errors(
            execution,
            body,
            acceptance,
            "样本文风。",
            style_plan=style_plan,
        )

        self.assertEqual(errors, [])
        self.assertNotIn("mandatory_voice_evidence", acceptance)

    def test_style_finalize_acceptance_keeps_procedural_and_mechanical_checks_hard(self):
        execution = "1. 赵明当场拒绝对方，把账册按回桌上。"
        body = (
            "赵明把账册按回桌上。\n\n"
            "“这件事到此为止。”\n\n"
            "对方刚要开口，门外已经有人推门进来。"
        )
        acceptance = {
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
        }

        self.assertEqual(
            _style_finalize_acceptance_errors(execution, body, acceptance),
            [],
        )

        acceptance["procedural_expansion_check"] = False
        errors = _style_finalize_acceptance_errors(execution, body, acceptance)
        self.assertTrue(any("办案式流程明显扩张" in error for error in errors))

        acceptance["procedural_expansion_check"] = True
        acceptance["mechanical_prose_check"] = False
        errors = _style_finalize_acceptance_errors(execution, body, acceptance)
        self.assertTrue(any("机械感明显" in error for error in errors))

    def test_style_finalize_acceptance_ignores_legacy_voice_evidence(self):
        execution = "1. 裴明拒绝对方插手路线，并接受损耗责任。"
        body = (
            "裴明按住路单。\n\n"
            "“裴家的船，裴家自己选人，您最好别问。”\n\n"
            "这话听着客气，其实是在拒绝她插手。\n\n"
            "姜禾点头。\n\n"
            "“不问路线。赔船，我也不问。”\n\n"
            "裴明的笑意当场卡住。"
        )
        acceptance = {
            "beat_evidence": [{
                "beat": 1,
                "evidence_quote": "裴家的船，裴家自己选人",
            }],
            "mandatory_voice_evidence": {"legacy": "ignored"},
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
            "paragraph_structure_check": True,
            "role_voice_attribution_check": True,
        }

        self.assertEqual(
            _style_finalize_acceptance_errors(
                execution,
                body,
                acceptance,
                "样本文风。",
                style_plan="【常驻人物语言声纹｜每章静默执行】只校准实际说话人物。",
            ),
            [],
        )

    def test_style_native_vocabulary_uses_only_phrases_extracted_from_profile(self):
        reference = "弹幕问尊嘟假嘟。她气笑了，好嘛，事情继续。与此同时，旁人离开。"
        profile = "你的习惯词包括：“尊嘟假嘟”“气笑了”“好嘛”。"

        vocabulary = _style_native_vocabulary_text(profile, reference)

        self.assertIn("以下3项", vocabulary)
        self.assertIn("尊嘟假嘟", vocabulary)
        self.assertIn("气笑了", vocabulary)
        self.assertIn("好嘛", vocabulary)
        self.assertNotIn("与此同时", vocabulary)
        self.assertIn("字当前文风样本", vocabulary)
        self.assertIn("低频场景词", vocabulary)
        self.assertIn("尊嘟假嘟×1", vocabulary)
        self.assertIn("好嘛×1", vocabulary)
        self.assertIn("不能把低频词变成每章固定口头禅", vocabulary)
        self.assertIn("优先保留这些原词", vocabulary)
        self.assertIn("不设最低数量", vocabulary)

    def test_style_native_vocabulary_uses_real_sample_frequency_tiers(self):
        reference = ("她直接回绝，又直接离开。" * 12) + "好嘛，事情又变了。"
        profile = "你的习惯词包括：“直接”“好嘛”。"

        vocabulary = _style_native_vocabulary_text(profile, reference)

        self.assertIn("高复现原词：直接×24", vocabulary)
        self.assertIn("低频场景词：好嘛×1", vocabulary)
        self.assertIn("任何一项的正文密度都不得明显高于完整样本", vocabulary)

        scaled = _style_native_vocabulary_text(
            profile,
            reference,
            output_target=5000,
        )
        self.assertRegex(scaled, r"直接×24（约5000字单章通常0-\d+次）")
        self.assertIn("好嘛×1（约5000字单章通常0-1次）", scaled)
        self.assertIn("软密度上沿，不是禁词或硬配额", scaled)

    def test_style_finalize_acceptance_reports_only_clear_native_word_overuse(self):
        reference = (
            ("她看清情况以后才作决定。" * 900)
            + ("她立刻停下。" * 10)
            + ("她直接回绝。" * 30)
            + "好嘛。"
        )
        profile = "你的习惯词包括：“立刻”“直接”“好嘛”。"

        def density_errors(text):
            errors = _style_finalize_acceptance_errors(
                "",
                text,
                {},
                reference,
                1000,
                profile_text=profile,
            )
            return [
                error for error in errors
                if error.startswith("终稿原生词密度明显高于样本")
            ]

        natural = ("她想清楚以后继续往前走。" * 75) + "好嘛。她立刻停下。"
        self.assertEqual(density_errors(natural), [])

        within_high_frequency_band = (
            ("她想清楚以后继续往前走。" * 72)
            + ("她直接回绝。" * 4)
        )
        self.assertEqual(density_errors(within_high_frequency_band), [])

        overused = (
            ("她想清楚以后继续往前走。" * 72)
            + "好嘛。好嘛。好嘛。好嘛。"
        )
        errors = density_errors(overused)
        self.assertEqual(len(errors), 1)
        self.assertIn("好嘛4次/软上沿1次", errors[0])
        self.assertIn("保留语义必要处", errors[0])

    def test_style_native_vocabulary_splits_grouped_voice_terms_and_skips_evidence(self):
        reference = (
            "随后他继续向前，然后停下，再然后转身。突然灯灭，紧接着门响。"
            "顿时众人安静，下一瞬间又恢复喧闹。不会吧，不对，事情还有变化。"
            "红色纸片落在任务目标旁。"
        ) * 4
        profile = (
            "【作者人格】\n"
            "【叙述习惯词与句法声纹】\n"
            "你的高频连接词是：“随后／然后／再然后＋动作”“突然／紧接着＋刺激”。"
            "状态重判使用：“顿时／瞬间”。\n"
            "【对白总体声纹】\n"
            "证据不足时使用：“不会吧……／……不对”。\n"
            "【功能角色说话方式】\n"
            "一线汇报采用：“地点／目标＋发现情况＋请求行动”。\n"
            "【证据化作者写作档案】\n"
            "逐字证据：“红色纸片”“任务”。"
        )

        vocabulary = _style_native_vocabulary_text(profile, reference)

        for phrase in ("随后", "然后", "再然后", "突然", "紧接着", "顿时", "瞬间", "不会吧", "不对"):
            self.assertIn(phrase + "×4", vocabulary)
        self.assertNotIn("红色纸片", vocabulary)
        self.assertNotIn("任务×", vocabulary)
        self.assertNotIn("目标×", vocabulary)

    def test_recent_style_vocabulary_usage_is_soft_density_context(self):
        chapters = [_new_chapter(index) for index in range(4)]
        chapters[0]["text"] = "好嘛。她直接回绝。"
        chapters[1]["text"] = "好嘛。她直接离开。"
        chapters[2]["text"] = "好嘛。她直接关门。"
        project = self._project_with_current_chapter(chapters[-1])
        project["chapters"] = chapters
        reference = "好嘛。" + ("她直接回绝，又直接离开。" * 20)
        profile = "你的习惯词包括：“好嘛”、“直接”。"

        usage = _style_recent_vocabulary_usage_text(
            project, 3, profile, reference
        )

        self.assertIn("已完成第1-3章", usage)
        self.assertIn("好嘛：完整样本1次", usage)
        self.assertIn("第1章1次、第2章1次、第3章1次", usage)
        self.assertIn("不是禁词表", usage)
        self.assertIn("不设置单词使用上限", usage)
        self.assertIn("不能机械替换", usage)

        execution_context = _build_style_execution_context(
            "【当前章节】\n本章扩写字数：2000字",
            profile_text=profile,
            style_reference=reference,
            project=project,
            chapter_index=3,
        )
        finalize_context = _build_style_finalize_context(
            "【当前章节】\n本章扩写字数：2000字",
            "她准备推门。",
            profile_text=profile,
            style_reference=reference,
            project=project,
            chapter_index=3,
            execution_text="1. 她推门进入。",
        )
        self.assertNotIn("【最近章节原生用词密度｜只作软校准】", execution_context)
        self.assertIn(reference, execution_context)
        self.assertIn("【最近章节原生用词密度｜只作软校准】", finalize_context)

    def test_style_context_requires_explicit_cross_location_transition(self):
        context = _build_style_execution_context(
            "【当前章节】\n本章扩写字数：2000字",
            style_reference="人物观察现场以后再作决定。" * 80,
        )

        self.assertIn("项目资料中已经确定的人名、时间、地点、关系、物件、编号、人物状态和已发生事件", context)
        self.assertIn("保持原样延续", context)
        self.assertIn("人物观察现场以后再作决定。" * 80, context)
        self.assertNotIn("如需切换时空", context)
        finalize_context = _build_style_finalize_context(
            "【当前章节】\n本章扩写字数：2000字",
            "人物观察现场以后再作决定。",
            style_reference="人物观察现场以后再作决定。" * 80,
            include_memory=False,
            execution_text="1. 人物作出本章决定。",
        )
        self.assertIn("当前提纲未明确安排的事项必须保持未决", finalize_context)
        self.assertIn("【自然表达边界】", finalize_context)
        self.assertIn("正文必须使用自然的网络小说叙述语言", finalize_context)
        self.assertIn("不得出现策划术语、抽象形容", finalize_context)
        self.assertIn("情绪和气氛必须通过人物当下的动作", finalize_context)
        self.assertNotIn("空得很有存在感", finalize_context)

    def test_direct_style_context_uses_source_cards_without_procedural_routing(self):
        def card(card_id, category, title):
            return {
                "id": card_id,
                "category": category,
                "title": title,
                "use_when": "适用场景",
                "avoid_when": "不适用场景",
                "voice_features": title,
                "source_excerpt": (f"{title}。人物停了一下，顺着对方的话接下去，场面却没有停。" * 10),
            }

        cards = [
            card("SC01", "推理与解释", "核验过程"),
            card("SC02", "专业角色对白", "专业追问"),
            card("SC03", "日常口语与喜剧", "口语接话"),
            card("SC04", "章节收束", "动作收束"),
        ]
        chapter_context = "【当前章节】\n本章扩写字数：2000字\n家宴上，女主决定当众拒绝对方。"
        selected = _select_style_execution_cards(cards, chapter_context, max_cards=3)
        selected_ids = [item["id"] for item in selected]
        context = _build_style_execution_context(
            chapter_context,
            style_cards=cards,
            style_reference="她看了对方一眼，没急着说话，先把人晾在原地。" * 80,
        )

        self.assertNotIn("SC01", selected_ids)
        self.assertNotIn("SC02", selected_ids)
        self.assertIn("SC03", selected_ids)
        self.assertIn("【仿写使用说明】", context)
        self.assertIn("她看了对方一眼，没急着说话，先把人晾在原地。" * 80, context)
        self.assertIn("【小说正文直写】", context)
        self.assertNotIn("【本章选中的原文片段卡", context)
        self.assertNotIn("人物反应必须承接上一段已经成立的外显状态和人物立场", context)
        self.assertNotIn("“笑不出来了”不是禁用词", context)
        self.assertNotIn("【剧情执行稿任务】", context)
        self.assertNotIn("【备用正文草稿】", context)

    def test_v4_voice_cards_parse_array_and_chinese_field_aliases(self):
        style_reference = (
            "少年抬手拦住门，声音压得很低。"
            "别急，先看看他们到底想让谁站出来。"
            "旁边的人冷笑一声：想屁吃呢，这账轮不到你替他们背。"
        ) * 20
        raw = json.dumps([
            {
                "id": "VC01",
                "标题": "低声拦门",
                "归属": "主角近身对白",
                "声纹": "短句压住场面，先拦动作再给判断。",
                "适用场景": "主角在危急前一秒制止同伴。",
                "边界": "不要写成流程核验或长篇解释。",
                "原文证据": "少年抬手拦住门，声音压得很低。",
            },
            {
                "id": "VC02",
                "标题": "口语反顶",
                "归属": "同伴或主角反击对白",
                "声纹": "用口语短句把锅推回去。",
                "适用场景": "对方试图甩锅或压人时。",
                "边界": "不要每章硬塞吵架。",
                "原文证据": "想屁吃呢，这账轮不到你替他们背。",
            },
        ], ensure_ascii=False)

        cards = _parse_style_voice_cards_result(raw, style_reference)

        self.assertEqual(len(cards), 2)
        self.assertEqual(cards[0]["title"], "低声拦门")
        self.assertEqual(cards[1]["owner"], "同伴或主角反击对白")

    def test_v4_technique_cards_parse_named_payload_aliases(self):
        style_reference = (
            "门外脚步声一停，屋里所有人都跟着闭了嘴。"
            "她没有解释，只把盒子往桌上一推。"
        ) * 20
        raw = json.dumps({
            "条件性叙事技法卡": [{
                "id": "TC01",
                "标题": "动作压场",
                "触发条件": "场面已经僵住，需要用动作而不是解释推进。",
                "写法": "先写外部动静让气氛收紧，再用一个动作改变局面。",
                "边界": "不要展开办案式核验。",
                "证据": "她没有解释，只把盒子往桌上一推。",
            }]
        }, ensure_ascii=False)

        cards = _parse_style_technique_cards_result(raw, style_reference)

        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["title"], "动作压场")
        self.assertIn("动作", cards[0]["use_method"])

    def test_direct_style_context_injects_semantic_archive_without_sample_names_as_facts(self):
        style_reference = (
            "谢弥抬眼，慢吞吞来了句：好嘛，这事还能这么玩。"
            "围观的人一下噎住，场面忽然安静。"
        ) * 80
        semantic_archive = {
            "style_archive_schema": "semantic_voice_v4",
            "semantic_archive_version": 4,
            "runtime_voice_pack": "贴近主视角的口语化判断，不写成长篇讲理。",
            "native_vocabulary_cards": [{
                "term": "好嘛",
                "meaning": "用于发现局面荒唐后的短促接话。",
                "emotional_temperature": "轻微无语，带吐槽感。",
                "speaker_or_viewpoint": "主视角或贴近主视角旁白。",
                "use_when": "角色发现对方逻辑离谱但暂时不急着长篇解释。",
                "sentence_position": "多在短句句首或反应句开头。",
                "natural_collocations": "好嘛，这下更热闹了。",
                "avoid_when": "沉重生死场景或正式告别时不用。",
                "source_evidence": "谢弥抬眼，慢吞吞来了句：好嘛，这事还能这么玩。",
            }],
            "voice_cards": [{
                "id": "VC01",
                "title": "主视角短促吐槽",
                "owner": "谢弥",
                "voice_features": "短句反应，口语吐槽，不自证。",
                "use_when": "主视角被离谱局面顶到眼前时。",
                "avoid_when": "不要为了展示吐槽新增对白。",
                "source_evidence": "谢弥抬眼，慢吞吞来了句：好嘛，这事还能这么玩。",
            }],
            "technique_cards": [{
                "id": "TC01",
                "title": "围观噎住",
                "trigger": "现场已有围观者且一句话改变气氛。",
                "use_method": "只写一次群体反应，立刻回到人物选择。",
                "avoid_when": "没有公开场面时不用。",
                "source_evidence": "围观的人一下噎住，场面忽然安静。",
            }],
        }
        context = _build_style_execution_context(
            "【当前章节】\n本章扩写字数：2000字\n女主准备拒绝家族安排。",
            profile_text="旧画像",
            style_reference=style_reference,
            semantic_archive=semantic_archive,
        )

        self.assertIn(style_reference, context)
        self.assertIn("【仿写使用说明】", context)
        self.assertNotIn("【作者原生用词池", context)
        self.assertNotIn("【V4 人物与叙述声纹", context)
        self.assertNotIn("【V4 条件性叙事技法", context)
        self.assertNotIn("【好嘛】真义", context)

    def test_direct_style_context_keeps_already_normalized_semantic_archive(self):
        style_reference = (
            "谢弥抬眼，慢吞吞来了句：好嘛，这事还能这么玩。"
            "围观的人一下噎住，场面忽然安静。"
        ) * 80
        raw_archive = {
            "style_archive_schema": "semantic_voice_v4",
            "semantic_archive_version": 4,
            "runtime_voice_pack": "贴近主视角的口语化判断，不写成长篇讲理。",
            "native_vocabulary_cards": [{
                "term": "好嘛",
                "meaning": "用于发现局面荒唐后的短促接话。",
                "emotional_temperature": "轻微无语，带吐槽感。",
                "speaker_or_viewpoint": "主视角或贴近主视角旁白。",
                "use_when": "角色发现对方逻辑离谱但暂时不急着长篇解释。",
                "sentence_position": "多在短句句首或反应句开头。",
                "natural_collocations": "好嘛，这下更热闹了。",
                "avoid_when": "沉重生死场景或正式告别时不用。",
                "source_evidence": "谢弥抬眼，慢吞吞来了句：好嘛，这事还能这么玩。",
            }],
            "voice_cards": [{
                "id": "VC01",
                "title": "主视角短促吐槽",
                "owner": "谢弥",
                "voice_features": "短句反应，口语吐槽，不自证。",
                "use_when": "主视角被离谱局面顶到眼前时。",
                "avoid_when": "不要为了展示吐槽新增对白。",
                "source_evidence": "谢弥抬眼，慢吞吞来了句：好嘛，这事还能这么玩。",
            }],
            "technique_cards": [{
                "id": "TC01",
                "title": "围观噎住",
                "trigger": "现场已有围观者且一句话改变气氛。",
                "use_method": "只写一次群体反应，立刻回到人物选择。",
                "avoid_when": "没有公开场面时不用。",
                "source_evidence": "围观的人一下噎住，场面忽然安静。",
            }],
        }
        normalized_archive = _normalize_semantic_style_archive(raw_archive, style_reference)
        context = _build_style_execution_context(
            "【当前章节】\n本章扩写字数：2000字\n女主准备拒绝家族安排。",
            profile_text="旧画像",
            style_reference=style_reference,
            semantic_archive=normalized_archive,
        )

        self.assertIn(style_reference, context)
        self.assertIn("【仿写使用说明】", context)
        self.assertNotIn("【作者原生用词池", context)
        self.assertNotIn("【V4 人物与叙述声纹", context)
        self.assertNotIn("【V4 条件性叙事技法", context)
        self.assertNotIn("【好嘛】真义", context)

    def test_chapter_prose_repair_patches_only_accept_small_unique_replacements(self):
        body = "夏晚晴抬眼看他，没急着接话。\n\n她把杯子放回桌上，转身就走。"
        repaired, errors = _apply_chapter_prose_repair_patches(body, [{
            "before": "夏晚晴抬眼看他，没急着接话。",
            "after": "夏晚晴抬眼看他，指尖在杯沿轻敲了一下。",
            "reason": "补足动作承接",
        }])
        self.assertEqual(errors, [])
        self.assertIn("指尖在杯沿轻敲", repaired)
        self.assertNotIn("没急着接话", repaired)

        duplicate, duplicate_errors = _apply_chapter_prose_repair_patches(
            "这句话需要重复出现。\n\n这句话需要重复出现。",
            [{
                "before": "这句话需要重复出现。",
                "after": "这句话已经改过。",
                "reason": "删除重复",
            }],
        )
        self.assertEqual(duplicate, "这句话需要重复出现。\n\n这句话需要重复出现。")
        self.assertIn("逐字且唯一出现", duplicate_errors[0])

        oversized, oversized_errors = _apply_chapter_prose_repair_patches(
            "甲" * 901,
            [{
                "before": "甲" * 901,
                "after": "乙",
                "reason": "压缩段落",
            }],
        )
        self.assertEqual(oversized, "甲" * 901)
        self.assertIn("替换范围过大", oversized_errors[0])

        _, too_many_errors = _apply_chapter_prose_repair_patches(body, [{}] * 4)
        self.assertEqual(too_many_errors, ["正文局部修补最多只能包含3项"])

        _, structured_errors = _apply_chapter_prose_repair_patches(body, [{
            "before": "她把杯子放回桌上，转身就走。",
            "after": "【修补说明】她把杯子放回桌上。",
            "reason": "保留动作",
        }])
        self.assertIn("混入了分析或结构化内容", structured_errors[0])

    def test_style_finalize_context_omits_metrics_for_unseen_rejected_candidate(self):
        reference = "\n".join(
            f"人物看清第{index}处变化以后，才作出下一步决定。"
            for index in range(80)
        )
        candidate = "\n\n".join(
            f"“第{index}项核完了吗？”\n\n“核完了。”"
            for index in range(80)
        )

        context = _build_style_finalize_context(
            "【当前章节】\n本章扩写字数：2000字",
            candidate,
            style_reference=reference,
            local_reasons=_style_draft_mismatch_reasons(reference, candidate, 2000),
            output_target=2000,
            include_memory=False,
            execution_text="1. 人物完成现场核验。",
            style_plan="常驻人物语言声纹。",
        )

        self.assertNotIn("【本章首要编辑动作】", context)
        self.assertNotIn("【备用正文的本地检测结果", context)
        self.assertNotIn("【首轮终稿结构预检", context)
        self.assertIn("人物口吻", context)
        self.assertNotRegex(context, r"至少将\d+字普通对白改写为人物化叙述")
        self.assertNotRegex(context, r"对白总字数不得超过约\d+字")
        self.assertIn("【仿写终稿任务】", context)
        self.assertIn("根据【剧情执行清单】从零写出完整终稿", context)

    def test_memory_update_normalizes_created_foreshadow_ref_as_temporary_key(self):
        chapter = _new_chapter(0)
        chapter["text"] = "账目最终指向御前长期药材采买。"
        project = self._project_with_current_chapter(chapter)
        update = self._strict_update(project, 0)
        update["foreshadow_updates"] = [{
            "ref": "NT-001-001",
            "operation": "create",
            "name": "药材采买真实用途",
            "status": "已埋",
            "dynamic": "真实用途仍待核验。",
            "evidence_quote": "御前长期药材采买",
        }]
        update["state_reconciliation"]["foreshadow_refs"] = ["NT-001-001"]
        update["next_chapter_memory"]["foreshadow_refs"] = ["NT-001-001"]
        for event in update["long_term_events"]:
            event.setdefault("storage", {})["foreshadow_refs"] = ["NT-001-001"]

        normalized = _normalize_long_form_update_payload(project, 0, update)

        self.assertEqual(normalized["foreshadow_updates"][0]["key"], "NT-001-001")
        errors = _validate_long_form_memory_update(
            project,
            0,
            normalized,
            final_text=chapter["text"],
            require_revision=True,
            require_evidence=True,
        )
        self.assertFalse(any(
            "新增key缺失或重复" in error
            or "引用未知记录：NT-001-001" in error
            or "foreshadows引用无效：NT-001-001" in error
            for error in errors
        ))

    def test_style_finalize_acceptance_flags_excessive_functional_dialogue(self):
        reference = "\n".join(
            f"人物观察现场变化，并根据第{index}项结果作出新的决定。"
            for index in range(60)
        )
        body = "\n".join(
            f"“第{index}项已经核完，请继续登记下一项结果。”"
            for index in range(60)
        )

        errors = _style_finalize_acceptance_errors(
            "",
            body,
            {},
            reference,
        )

        self.assertTrue(any("对白字数占比明显高于样本" in error for error in errors))

    def test_style_finalize_acceptance_flags_large_length_drift(self):
        reference = "\n".join(
            f"样本第{index}段会把动作、判断和后果自然写在一起。"
            for index in range(80)
        )
        body = "正文内容" * 1800

        errors = _style_finalize_acceptance_errors(
            "",
            body,
            {},
            reference,
            output_target=5000,
        )

        self.assertTrue(any("正文长度明显偏离目标" in error for error in errors))

    def test_deictic_literal_count_claims_are_normalized_before_memory_finalize(self):
        body = (
            "“知夏，我不知道是谁要害我们。”\n\n"
            "来了。\n\n"
            "又是“害我们”。\n\n"
            "这四个字用得很妙。"
        )

        repaired, issues = _repair_literal_count_claims(body)

        self.assertEqual(len(issues), 1)
        self.assertIn("这几个字用得很妙。", repaired)
        self.assertNotIn("这四个字用得很妙。", repaired)

    def test_deictic_literal_count_claims_do_not_infer_an_earlier_quote(self):
        body = (
            "主视觉叫“长久”。\n\n"
            "副标题是顾承泽选的：余生只你一人。\n\n"
            "当初他发来这八个字的时候，沈知夏盯着手机沉默了三秒。"
        )

        repaired, issues = _repair_literal_count_claims(body)

        self.assertEqual(len(issues), 1)
        self.assertIn("当初他发来这几个字的时候", repaired)
        self.assertNotIn("这八个字", repaired)

    def test_deictic_literal_count_claims_handle_arabic_and_that_forms(self):
        body = "这二个字，那3个字，还有这两个字，都写得很扎眼。"

        repaired, issues = _repair_literal_count_claims(body)

        self.assertEqual(len(issues), 3)
        self.assertEqual(repaired, "这几个字，那几个字，还有这几个字，都写得很扎眼。")

    def test_general_or_single_literal_count_claims_are_left_unchanged(self):
        body = "这个标题一共六个字。这一个字写得很重。那一个字也不能动。"

        repaired, issues = _repair_literal_count_claims(body)

        self.assertEqual(issues, [])
        self.assertEqual(repaired, body)

    def test_style_fragmentation_guard_catches_paragraph_and_dialogue_drift_together(self):
        reference = "\n".join(
            (
                f"样本第{index}段，人物先看清现场变化，再根据已经发生的结果作出决定。"
                "叙述会把反应、判断和下一步动作自然放在同一段里。"
            )
            for index in range(40)
        )
        candidate_lines = ["“可以。”" for _ in range(60)]
        candidate_lines.extend(f"人物停下第{index}步。" for index in range(40))
        candidate = "\n".join(candidate_lines)

        reasons = _style_draft_mismatch_reasons(reference, candidate, len(candidate))
        errors = _style_finalize_acceptance_errors("", candidate, {}, reference)

        self.assertTrue(any("结构多项同时向短碎方向漂移" in reason for reason in reasons))
        self.assertTrue(any("终稿结构同时向短碎方向漂移" in error for error in errors))

    def test_style_finalize_preflight_reports_centered_dialogue_merge_targets(self):
        reference = "\n".join(
            (
                f"样本第{index}段，人物先处理眼前变化，再顺着结果采取下一步行动。"
                + ("“先看结果再说。”" if index % 4 == 0 else "")
            )
            for index in range(60)
        )
        candidate = "\n".join(
            f"“第{index}项可以了吗？”\n“可以。”"
            for index in range(70)
        )

        result = _style_finalize_preflight_targets(
            reference,
            candidate,
            output_target=len(candidate),
        )

        self.assertIn("交付时保持", result)
        self.assertIn("轮对白", result)
        self.assertIn("短对白", result)
        self.assertIn("功能台词并入动作或相邻完整表达", result)

    def test_style_finalize_preflight_never_adds_dialogue_to_quiet_candidate(self):
        reference = "\n".join(
            f"“第{index}件事现在就处理。”人物随即转身安排后续动作。"
            for index in range(60)
        )
        candidate = "\n".join(
            (
                f"人物处理完第{index}处变化以后，顺着现场留下的结果继续向前。"
                "他没有额外解释，只把下一步行动落实下来。"
            )
            for index in range(12)
        )

        result = _style_finalize_preflight_targets(
            reference,
            candidate,
            output_target=len(candidate),
        )

        self.assertNotIn("增加对白", result)
        self.assertNotIn("补足对白", result)
        self.assertNotIn("拆分段落", result)

    def test_style_finalize_edits_structurally_valid_candidate_in_place(self):
        reference = "\n".join(
            f"样本第{index}段把人物反应、现场变化和下一步行动自然写在同一段里。"
            for index in range(60)
        )
        candidate_lines = [
            f"正文第{index}段把人物反应、现场变化和下一步行动自然写在同一段里。"
            for index in range(60)
        ]
        candidate_lines[10] = "赵明核完账册，确认封签已经断裂，随后把证据收回手边。"
        candidate = "\n".join(candidate_lines)

        context = _build_style_finalize_context(
            "【当前章节】\n本章扩写字数：2000字",
            candidate,
            style_reference=reference,
            local_reasons=[],
            output_target=len(candidate),
            include_memory=False,
            execution_text="1. 赵明核对账册并确认封签断裂。",
            style_plan="核心声纹人物：赵明使用简短判断。",
        )

        self.assertIn("【结构已通过的备用正文底稿", context)
        self.assertIn(candidate, context)
        self.assertIn("【合格底稿轻量校准】", context)
        self.assertIn("不得为了留下修改痕迹而拆段", context)
        self.assertIn("允许原样保留合格内容", context)
        self.assertIn("自然段落", context)
        self.assertNotIn("终稿不得增加非空段落数", context)
        self.assertNotIn("【剧情执行清单｜只继承事实与顺序，必须从零写作】", context)

    def test_style_finalize_acceptance_blocks_non_dialogue_single_sentence_drift(self):
        reference = "\n".join(
            (
                f"样本第{index}段先写现场变化，再写人物判断，最后让动作自然落到下一步。"
                "这些内容放在同一个连续段落里。"
            )
            for index in range(40)
        )
        candidate_lines = [
            f"正文第{index}段先写现场变化，再写人物判断，最后让动作自然落到下一步。"
            for index in range(40)
        ]
        for index in range(40):
            candidate_lines.extend([
                f"人物看了第{index}眼。",
                f"他随后走了第{index}步。",
            ])
        candidate = "\n".join(candidate_lines)

        errors = _style_finalize_acceptance_errors("", candidate, {}, reference)

        self.assertTrue(any("非对白短单句段" in error for error in errors))

    def test_style_finalize_acceptance_requires_opening_evidence_only_for_new_later_chapter(self):
        first = _new_chapter(0)
        first_project = self._project_with_current_chapter(first)
        execution = "1. 主角推开诊室门并看见病床。"
        body = "主角推开诊室门，第一眼便看见病床上的人。"
        acceptance = {
            "beat_evidence": [{"beat": 1, "evidence_quote": "主角推开诊室门，第一眼便看见病床上的人"}],
            "previous_chapter_repetition_check": True,
            "logic_continuity_check": True,
            "paragraph_structure_check": True,
        }

        self.assertEqual(
            _style_finalize_acceptance_errors(
                execution,
                body,
                acceptance,
                project=first_project,
                chapter_index=0,
            ),
            [],
        )

        previous = _new_chapter(0)
        previous["text"] = "门外忽然传来一声闷响。"
        current = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]
        errors = _style_finalize_acceptance_errors(
            execution,
            body,
            acceptance,
            project=project,
            chapter_index=1,
        )
        self.assertEqual(errors, [])

        current["text"] = "本章已经写出的开头。"
        self.assertEqual(
            _style_finalize_acceptance_errors(
                execution,
                body,
                acceptance,
                project=project,
                chapter_index=1,
            ),
            [],
        )

    def test_retired_conflict_and_task_ids_are_never_reissued(self):
        previous = _new_chapter(0)
        previous["state_reconciliation"] = {
            "conflict_ids": ["CF-0009"],
            "task_ids": ["TASK-0012"],
        }
        current = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [previous, current]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 1,
            "state_snapshot": {
                "active_conflicts": [{"id": "CF-0008", "conflict": "旧冲突"}],
                "unresolved_tasks": [{"id": "TASK-0011", "task": "旧任务"}],
            },
        }
        update = self._strict_update(project, 1)
        update["state_patch"] = {
            "active_conflicts": [{"id": "", "key": "NCF1", "conflict": "新冲突"}],
            "unresolved_tasks": [{"id": "", "key": "NTASK1", "task": "新任务"}],
        }

        self.assertTrue(_apply_long_form_memory_update(project, 1, update))

        snapshot = project["long_form_memory"]["state_snapshot"]
        self.assertIn("CF-0010", {item["id"] for item in snapshot["active_conflicts"]})
        self.assertIn("TASK-0013", {item["id"] for item in snapshot["unresolved_tasks"]})
        self.assertIn("CF-0009", project["long_form_memory"]["issued_state_ids"]["conflicts"])
        self.assertIn("TASK-0012", project["long_form_memory"]["issued_state_ids"]["tasks"])

    def test_object_state_mentioning_another_lore_name_keeps_its_explicit_key(self):
        current = _new_chapter(2)
        current["memory_selection"] = {"object_keys": ["NOBJ-NF2"]}
        project = self._project_with_current_chapter(current)
        project["lore"] = [
            {"id": "lore-crystal", "name": "异兽晶核", "type": "关键物件"},
            {"id": "lore-echo", "name": "深海回波", "type": "异常线索"},
        ]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 2,
            "state_snapshot": {
                "object_states": [{
                    "key": "NOBJ-NF2",
                    "name": "异兽晶核",
                    "lore_ref": "lore-crystal",
                    "state": "晶核仍在金属箱内，正与塔内回波产生反应。",
                }],
            },
            "issued_state_ids": {"objects": ["NOBJ-NF1", "NOBJ-NF2"]},
        }
        update = self._strict_update(project, 2)
        update["compact_delta_version"] = LONG_FORM_COMPACT_DELTA_VERSION
        update["state_patch"] = {
            "object_states": [{
                "key": "NOBJ-NF2",
                "state": "沈砚秋继续携带晶核箱；箱内暗红光增强，深海回波再次出现在海面。",
                "evidence_quote": "箱内暗红光增强，深海回波再次出现在海面。",
            }],
        }
        update["long_term_events"] = [{
            "event": "晶核箱随沈砚秋移动，深海回波再次出现。",
            "evidence_quote": "晶核箱随沈砚秋移动，深海回波再次出现。",
            "storage": {"object_keys": ["NOBJ-NF2"]},
        }]
        update["next_chapter_memory"] = {"object_keys": ["NOBJ-NF2"]}

        normalized = _normalize_long_form_update_payload(project, 2, update)

        object_state = normalized["state_patch"]["object_states"][0]
        self.assertEqual(object_state["key"], "NOBJ-NF2")
        self.assertEqual(
            _resolve_long_form_record_ref(project, "lore", object_state["lore_ref"]),
            "lore-crystal",
        )
        self.assertEqual(
            normalized["long_term_events"][0]["storage"]["object_keys"],
            ["NOBJ-NF2"],
        )
        self.assertEqual(normalized["next_chapter_memory"]["object_keys"], ["NOBJ-NF2"])

    def test_different_object_reusing_existing_key_gets_new_permanent_key(self):
        current = _new_chapter(0)
        current["memory_selection"] = {"object_keys": ["NOBJ-NF1"]}
        following = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, following]
        project["lore"] = [
            {"id": "lore-order", "name": "棠记首张半年长单", "type": "关键物件"},
            {"id": "lore-contract", "name": "棠记产权及经营契约文书", "type": "关键物件"},
            {"id": "lore-copy", "name": "旧订单副本", "type": "关键物件"},
        ]
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 5,
            "state_snapshot": {
                "object_states": [
                    {
                        "key": "NOBJ-NF6",
                        "name": "棠记首张半年长单",
                        "lore_ref": "lore-order",
                        "state": "已收首月定银，未来半年按月交付。",
                    },
                    {
                        "key": "NOBJ-NF7",
                        "name": "棠记产权及经营契约文书",
                        "lore_ref": "lore-contract",
                        "state": "产权文书及长期采购契约均已落印生效。",
                    },
                ],
                "active_conflicts": [],
                "unresolved_tasks": [],
            },
            "issued_state_ids": {
                "objects": [f"NOBJ-NF{index}" for index in range(1, 8)],
                "conflicts": [],
                "tasks": [],
            },
        }
        update = self._strict_update(project)
        update["state_patch"] = {
            "object_states": [{
                "key": "NOBJ-NF6",
                "name": "NOBJ-NF6",
                "lore_ref": "lore-copy",
                "state": "姜晚棠现持有旧订单副本，记载香料与麻袋同车交往永丰货栈。",
            }],
        }
        update["state_lifecycle_review"]["reviewed_object_keys"] = ["NOBJ-NF6"]
        update["state_reconciliation"]["object_keys"] = ["NOBJ-NF6"]
        update["long_term_events"] = [{
            "event": "姜晚棠取得旧订单副本。",
            "storage": {"object_keys": ["NOBJ-NF6"]},
        }]
        update["state_delta"] = {
            "objects": [{"object_key": "NOBJ-NF6", "change": "取得旧订单副本"}],
        }
        update["next_chapter_memory"] = {
            "object_keys": ["NOBJ-NF6"],
            "reason": "下一章继续查验旧订单。",
        }

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        objects = {
            item["key"]: item
            for item in project["long_form_memory"]["state_snapshot"]["object_states"]
        }
        self.assertEqual(objects["NOBJ-NF6"]["name"], "棠记首张半年长单")
        self.assertEqual(objects["NOBJ-NF7"]["name"], "棠记产权及经营契约文书")
        self.assertEqual(objects["NOBJ-NF8"]["name"], "旧订单副本")
        self.assertIn("NOBJ-NF8", project["long_form_memory"]["issued_state_ids"]["objects"])
        chapter = project["chapters"][0]
        self.assertEqual(chapter["long_term_events"][0]["storage"]["object_keys"], ["NOBJ-NF8"])
        self.assertEqual(chapter["state_reconciliation"]["object_keys"], ["NOBJ-NF8"])
        self.assertEqual(chapter["state_lifecycle_review"]["reviewed_object_keys"], ["NOBJ-NF8"])
        self.assertEqual(chapter["state_delta"]["objects"][0]["object_key"], "NOBJ-NF8")
        self.assertIn("NOBJ-NF8", project["chapters"][1]["memory_selection"]["object_keys"])

    def test_placeholder_name_update_keeps_matching_object_identity(self):
        current = _new_chapter(0)
        project = self._project_with_current_chapter(current)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 3,
            "state_snapshot": {
                "object_states": [{
                    "key": "NOBJ-NF6",
                    "name": "棠记首张半年长单",
                    "state": "已收首月定银，未来半年按月交付。",
                }],
                "active_conflicts": [],
                "unresolved_tasks": [],
            },
            "issued_state_ids": {
                "objects": ["NOBJ-NF6"],
                "conflicts": [],
                "tasks": [],
            },
        }
        update = self._strict_update(project)
        update["state_patch"] = {
            "object_states": [{
                "key": "NOBJ-NF6",
                "name": "NOBJ-NF6",
                "state": "半年长单已完成首月交付，下一批仍按原约履行。",
            }],
        }
        update["state_lifecycle_review"]["reviewed_object_keys"] = ["NOBJ-NF6"]
        update["state_reconciliation"]["object_keys"] = ["NOBJ-NF6"]

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        objects = project["long_form_memory"]["state_snapshot"]["object_states"]
        self.assertEqual(len(objects), 1)
        self.assertEqual(objects[0]["key"], "NOBJ-NF6")
        self.assertEqual(objects[0]["name"], "棠记首张半年长单")
        self.assertIn("已完成首月交付", objects[0]["state"])

    def test_new_character_temp_ref_is_mapped_before_fact_scope_is_saved(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {"schema_version": "2", "revision": 0}
        update = self._strict_update(project)
        update["record_updates"]["characters"] = [{
            "operation": "create",
            "key": "NC1",
            "name": "苏小满",
            "state": "术后观察中",
        }]
        update["fact_updates"] = [{
            "operation": "add",
            "key": "NF1",
            "scope": "character:NC1:medical_status",
            "fact": "苏小满仍需术后观察",
        }]

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        saved = project["long_form_memory"]["active_facts"][0]
        self.assertEqual(saved["scope"], "character:C001:medical_status")
        self.assertNotIn("NC1", saved["scope"])

    def test_character_create_accepts_string_canon_without_leaving_an_empty_card(self):
        current = _new_chapter(0)
        following = _new_chapter(1)
        project = self._project_with_current_chapter(current)
        project["chapters"] = [current, following]
        update = self._strict_update(project)
        update["record_updates"]["characters"] = [{
            "operation": "create",
            "key": "NC1",
            "stable_name": "小吴",
            "canon": "曾跟着张莉工作的助理；本章被直接指向转发录制安排，动机尚未确认。",
            "state": "被直接指向转发录制安排，具体内容和动机尚未确认。",
            "evidence_quote": "小吴已经把它送到了张莉手里。",
        }]
        update["current_chapter_character_refs"] = ["NC1"]

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        created = next(item for item in project["characters"] if item["name"] == "小吴")
        self.assertEqual(created["role"], "曾跟着张莉工作的助理")
        self.assertEqual(
            created["notes"],
            "曾跟着张莉工作的助理；本章被直接指向转发录制安排，动机尚未确认。",
        )
        self.assertTrue(any(str(value or "").strip() for value in created.values()))

        existing = {
            "id": "existing-character",
            "name": "魏管事",
            "role": "",
            "goal": "已有目标",
            "secret": "",
            "voice": "",
            "notes": "",
        }
        project["characters"].append(existing)
        _apply_character_string_canon(
            existing,
            "玄铁宗外门管事，魏骁之父。本章处理月例争议。",
        )
        self.assertEqual(existing["role"], "玄铁宗外门管事，魏骁之父")
        self.assertEqual(existing["goal"], "已有目标")
        self.assertIn("本章处理月例争议", existing["notes"])

    def test_temporary_character_can_be_promoted_without_changing_record_id(self):
        chapter = _new_chapter(0)
        chapter["text"] = "顾沉舟认输后，转身离开擂台。"
        project = self._project_with_current_chapter(chapter)
        existing = {
            "id": "temporary-character",
            "name": "内门弟子（姓名未明）",
            "role": "玄铁宗内门弟子",
            "goal": "",
            "secret": "",
            "voice": "",
            "notes": "玄铁宗内门弟子；姓名、修为和来意未明",
        }
        project["characters"] = [existing]
        update = self._strict_update(project)
        update["record_updates"]["characters"] = [{
            "operation": "update",
            "ref": existing["id"],
            "name": "顾沉舟",
            "canon": {
                "role": "玄铁宗内门弟子，入门不到两年",
                "goal": "查清内门大比背后的异常",
                "voice": "说话简短直接",
                "notes": "正式姓名已进入宗门名册",
            },
            "state": "正式姓名已明确并承认挑战失败。",
            "changes": ["正式姓名由临时称谓升级为顾沉舟"],
            "evidence_quote": "顾沉舟认输后",
        }]
        update["current_chapter_character_refs"] = [existing["id"]]

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        promoted = project["characters"][0]
        self.assertEqual(promoted["id"], "temporary-character")
        self.assertEqual(promoted["name"], "顾沉舟")
        self.assertEqual(promoted["role"], "玄铁宗内门弟子，入门不到两年")
        self.assertEqual(promoted["goal"], "查清内门大比背后的异常")
        self.assertEqual(promoted["voice"], "说话简短直接")
        self.assertIn("正式姓名已进入宗门名册", promoted["notes"])
        self.assertIn("旧名：内门弟子（姓名未明）", promoted["notes"])

    def test_character_identity_fields_accept_legacy_top_level_and_nested_shapes(self):
        self.assertEqual(
            _character_identity_fields_from_item({
                "role": "宗门管事",
                "goal": "保住儿子的外门位置",
                "secret": "曾私下替人改过名册",
                "voice": "先客气后强硬",
            }),
            {
                "role": "宗门管事",
                "goal": "保住儿子的外门位置",
                "secret": "曾私下替人改过名册",
                "voice": "先客气后强硬",
            },
        )
        self.assertEqual(
            _character_identity_fields_from_item({
                "canon": {"goal": "守住擂台名次", "voice": "说话干脆"},
                "identity_patch": {"secret": "曾败给主角"},
            }),
            {"goal": "守住擂台名次", "voice": "说话干脆", "secret": "曾败给主角"},
        )
        self.assertEqual(
            _character_identity_fields_from_item({
                "canon": {
                    "role": "仅新增时填写",
                    "goal": "正文明确的目标；无证据留空",
                    "voice": "正文中足够明显的语言/口吻特征；证据不足留空",
                }
            }),
            {},
        )

    def test_character_update_backfills_empty_identity_fields_without_overwriting_existing(self):
        chapter = _new_chapter(0)
        chapter["text"] = "魏管事压低声音道：‘先把月例补上，别让外门乱起来。’"
        project = self._project_with_current_chapter(chapter)
        existing = {
            "id": "character-1",
            "name": "魏管事",
            "role": "玄铁宗外门管事",
            "goal": "保住儿子的外门位置",
            "secret": "",
            "voice": "",
            "notes": "魏骁之父",
        }
        project["characters"] = [existing]
        update = self._strict_update(project)
        update["record_updates"]["characters"] = [{
            "operation": "update",
            "ref": existing["id"],
            "state": "本章承认月例处理有误并要求补发。",
            "identity_patch": {
                "goal": "想继续维持外门月例的控制权",
                "secret": "曾私下替儿子从新人月例中扣取好处",
                "voice": "先客气施压，受阻后转为冷硬",
            },
            "evidence_quote": "魏管事压低声音道",
        }]
        update["current_chapter_character_refs"] = [existing["id"]]

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        saved = project["characters"][0]
        self.assertEqual(saved["goal"], "保住儿子的外门位置；想继续维持外门月例的控制权")
        self.assertEqual(saved["secret"], "曾私下替儿子从新人月例中扣取好处")
        self.assertEqual(saved["voice"], "先客气施压，受阻后转为冷硬")

    def test_long_form_contract_lists_empty_identity_fields_for_current_characters(self):
        chapter = _new_chapter(0)
        chapter["actual_linked_character_ids"] = ["character-one", "character-two"]
        project = self._project_with_current_chapter(chapter)
        project["characters"] = [
            {
                "id": "character-one",
                "name": "甲",
                "role": "修士",
                "goal": "",
                "secret": "",
                "voice": "",
            },
            {
                "id": "character-two",
                "name": "乙",
                "role": "护卫",
                "goal": "守住城门",
                "secret": "",
                "voice": "命令式",
            },
        ]

        gaps = _long_form_character_identity_gaps_text(project, 0)
        self.assertIn("C001/甲：goal,secret,voice", gaps)
        self.assertIn("C002/乙：secret", gaps)
        self.assertIn("identity_patch", gaps)
        self.assertIn("没有直接证据的字段保持空", gaps)

        compact_contract = _long_form_update_contract_instructions(project, 0, compact=True)
        full_contract = _long_form_update_contract_instructions(project, 0, compact=False)
        for contract in (compact_contract, full_contract):
            self.assertIn("本章空缺人物字段定向检查", contract)
            self.assertIn("C001/甲：goal,secret,voice", contract)
            self.assertIn("人物字段必须独立判断", contract)

    def test_character_create_maps_top_level_identity_fields_into_card(self):
        chapter = _new_chapter(0)
        chapter["text"] = "宁川抬手压住碎石，冷声让众人退开。"
        project = self._project_with_current_chapter(chapter)
        update = self._strict_update(project)
        update["record_updates"]["characters"] = [{
            "operation": "create",
            "key": "NC1",
            "name": "宁川",
            "role": "青岳宗护道修士",
            "goal": "护住宗门弟子并夺取遗迹机缘",
            "secret": "真实境界高于公开说法",
            "voice": "少言，命令式",
            "state": "在遗迹入口以山岳力量压制碎石。",
            "evidence_quote": "宁川抬手压住碎石",
        }]
        update["current_chapter_character_refs"] = ["NC1"]

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))
        saved = next(item for item in project["characters"] if item["name"] == "宁川")
        self.assertEqual(saved["role"], "青岳宗护道修士")
        self.assertEqual(saved["goal"], "护住宗门弟子并夺取遗迹机缘")
        self.assertEqual(saved["secret"], "真实境界高于公开说法")
        self.assertEqual(saved["voice"], "少言，命令式")

    def test_fact_retirement_requires_selected_id_exact_scope_and_previous_fact(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 3,
            "active_facts": [{
                "id": "AF-0001",
                "scope": "asset:clinic:ownership",
                "fact": "诊所产权不存在重大限制",
            }],
        }
        update = self._strict_update(project)
        update["fact_updates"] = [{
            "operation": "retire",
            "id": "AF-0001",
            "scope": "asset:clinic:ownership",
            "previous_fact": "诊所产权不存在重大限制",
            "reason": "产权限制已经出现",
            "evidence_quote": "产权登记新增了抵押限制",
        }]
        update["fact_lifecycle_review"]["reviewed_refs"] = ["AF-0001"]
        update["state_reconciliation"]["fact_refs"] = ["AF-0001"]
        body = "产权登记新增了抵押限制，旧结论已经失效。"

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=body,
            require_revision=True, require_evidence=True,
        )
        self.assertTrue(any("退出事实未进入本章选择" in error for error in errors))

        chapter["memory_selection"] = {"fact_ids": ["AF-0001"]}
        update["fact_updates"][0]["scope"] = "task:clinic:ownership"
        update["fact_updates"][0]["previous_fact"] = "另一条事实"
        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=body,
            require_revision=True, require_evidence=True,
        )
        self.assertTrue(any("scope与旧事实不匹配" in error for error in errors))
        self.assertTrue(any("previous_fact与旧事实不匹配" in error for error in errors))

    def test_new_evidence_batch_cannot_create_duplicate_lore_name(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [{
            "id": "lore-live-old",
            "name": "别墅院门连续直播原始记录",
            "type": "跨章关键物件",
        }]
        project["long_form_memory"] = {"schema_version": "2", "revision": 0}
        update = self._strict_update(project)
        update["record_updates"]["lore"] = [{
            "operation": "create",
            "key": "NL1",
            "name": "别墅院门连续直播原始记录",
            "story_known": "本章出现新一轮直播记录。",
            "state": "新一轮直播待保全",
            "evidence_quote": "新一轮直播已经开始",
        }]
        normalized = _normalize_long_form_structural_refs(project, 0, update)

        errors = _validate_long_form_memory_update(
            project, 0, normalized, final_text="新一轮直播已经开始。",
            require_revision=True, require_evidence=True,
        )
        self.assertTrue(any("新增名称与已有记录" in error for error in errors))

    def test_style_finalize_contains_plot_acceptance_and_previous_two_chapter_dedup(self):
        chapters = [_new_chapter(index) for index in range(3)]
        chapters[0].update({"title": "旧案出现", "summary": "主角取得卷宗。", "text": "他拿到了旧案卷宗。"})
        chapters[1].update({"title": "证人开口", "summary": "证人交代线索。", "text": "证人说出了仓库地址。"})
        chapters[2]["outline"] = (
            "人物任务：赵明核对仓库。\n主线任务：找到失踪账册。\n"
            "必须发生：赵明进入仓库并找到暗格。\n结尾钩子：暗格内只有半页账册。"
        )
        project = self._project_with_current_chapter(chapters[2])
        project["chapters"] = chapters

        context = _build_style_finalize_context(
            "【当前章节资料】\n第三章资料",
            "赵明来到仓库。",
            project=project,
            chapter_index=2,
            include_memory=False,
            execution_text=(
                "1. 赵明进入仓库并找到暗格。\n"
                "2. 暗格内只有半页账册。\n"
                "静默继承边界：旧案卷宗仍由赵明保管。"
            ),
        )

        self.assertIn("【终稿剧情验收清单】", context)
        self.assertIn("【本章唯一剧情执行清单】", context)
        self.assertIn("赵明进入仓库并找到暗格", context)
        self.assertNotIn("人物任务：赵明核对仓库", context)
        self.assertIn("前两章已完成内容", context)
        self.assertIn("主角取得卷宗", context)
        self.assertIn("证人交代线索", context)
        self.assertIn("不得复演已经完成的冲突、解释、对话结论或结尾钩子", context)
        self.assertIn("【章首承接硬验收】", context)
        self.assertIn("上一章已发布结尾的最后三段", context)
        self.assertIn('"opening_continuation"', context)
        self.assertIn("first_new_sentence", context)
        self.assertIn("章首新增变量", context)
        self.assertIn('"timeline_commitment_check"', context)
        self.assertIn("前文期限或承诺", context)
        self.assertIn('"timeline_commitment_check"', context)
        self.assertNotIn("摘要：主角取得卷宗", context)
        self.assertNotIn("关键事实：", context)

    def test_draft_context_exposes_permission_threshold_and_evidence_boundaries(self):
        chapter = _new_chapter(0)
        chapter["title"] = "第一章 会诊"
        chapter["outline"] = "夏晚晴申请查看病例，赵明判断能否开始治疗。"
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 3,
            "state_snapshot": {
                "character_states": [{"character_id": "char-a", "name": "夏晚晴", "state": "尚未获得病例权限"}],
                "active_conflicts": [{"id": "CF-0001", "conflict": "治疗条件尚未满足"}],
                "unresolved_tasks": [{"id": "TASK-0001", "task": "核实脑图来源"}],
            },
            "active_facts": [{"id": "AF-0001", "scope": "evidence:brain_map", "fact": "脑图来源仍未核实"}],
        }
        chapter["memory_selection"] = {"fact_ids": ["AF-0001"]}

        context = _build_chapter_ai_context(project, 0, "draft")

        self.assertIn("【剧情连续性参考】", context)
        self.assertIn("资料未确认的内容继续保持未确认", context)
        self.assertIn("新能力、授权或物品不能凭空获得", context)
        self.assertIn("现实流程完整不等于剧情完整", context)
        self.assertIn("脑图来源仍未核实", context)
        self.assertIn("提纲与已发生事实冲突时保留", context)

    def test_style_checks_detect_excess_single_sentence_short_paragraphs(self):
        reference = "\n".join(("这是一段连续说明文字，保持相对完整的叙述结构和信息顺序。" * 2) for _ in range(30))
        draft = "\n".join(f"短句{i}。" for i in range(100))

        reasons = _style_draft_mismatch_reasons(reference, draft)

        self.assertTrue(any("短单句段过多" in reason for reason in reasons))

    def test_memory_finalize_contract_is_strict_incremental_and_bounded(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        context = _build_long_form_memory_finalize_context(project, 0, "赵明完成了本章调查。")

        self.assertIn("这是严格增量，不是全量总结", context)
        self.assertIn("fact_updates最多12项", context)
        self.assertIn("long_term_events最多8项", context)
        self.assertLessEqual(len(context), NOVEL_AI_CONTEXT_LIMIT)

    def test_boundary_reconciliation_context_and_parser_only_return_corrections(self):
        chapters = [_new_chapter(index) for index in range(10)]
        project = self._project_with_current_chapter(chapters[-1])
        project["chapters"] = chapters
        project["long_form_memory"] = {
            "schema_version": "2",
            "revision": 9,
            "state_snapshot": {"active_conflicts": [], "unresolved_tasks": []},
            "active_facts": [],
        }
        update = self._strict_update(project, 9)
        update["stage_archive"] = {
            "summary": "阶段总结",
            "irreversible_facts": [],
            "relationship_changes": [],
            "unresolved_threads": [],
            "next_stage_entry": "进入下一阶段",
        }

        context = _build_long_form_memory_reconcile_context(
            project, 9, "赵明确认资料来源仍然未知。", update
        )
        parsed = _parse_memory_reconciliation_result(
            '{"base_revision":9,"corrections":{"fact_updates":[],"state_patch":{}}}'
        )

        self.assertLessEqual(len(context), LONG_FORM_RECONCILIATION_CONTEXT_LIMIT)
        self.assertIn("只审查第十章边界的状态语义", context)
        self.assertIn("只返回能由最终正文逐字证实", context)
        self.assertIn('每项必须填写operation:"update"、ref和evidence_quote', context)
        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["corrections"]["fact_updates"], [])

    def test_reconciliation_patch_preserves_original_delta_and_replaces_same_fact(self):
        original = {
            "schema_version": 2,
            "base_revision": 9,
            "state_patch": {"location": "华京"},
            "fact_updates": [{"operation": "keep", "id": "AF-0001"}],
            "fact_lifecycle_review": {"scope": LONG_FORM_STAGE_REVIEW_SCOPE, "reviewed_refs": ["AF-0001"]},
            "state_lifecycle_review": {
                "scope": LONG_FORM_STAGE_REVIEW_SCOPE,
                "reviewed_object_keys": [], "reviewed_conflict_refs": [], "reviewed_task_refs": [],
            },
            "state_reconciliation": {
                "checked": True, "coverage_checks": {}, "fact_refs": ["AF-0001"],
                "character_refs": [], "lore_refs": [], "foreshadow_refs": [],
                "relationship_refs": [], "object_keys": [], "conflict_refs": [], "task_refs": [],
                "resolved_contradictions": [],
            },
            "stage_archive": {"summary": "保留原阶段档案", "next_stage_entry": "继续调查"},
        }
        patch = {
            "fact_updates": [{
                "operation": "update", "id": "AF-0001", "scope": "trip:beijing",
                "fact": "赵明已经抵达华京", "evidence_quote": "赵明已经抵达华京",
            }],
            "state_patch": {"story_time": "当夜"},
        }

        merged = _merge_long_form_memory_reconciliation_patch(original, patch)

        self.assertEqual(merged["fact_updates"][0]["operation"], "update")
        self.assertEqual(merged["state_patch"]["location"], "华京")
        self.assertEqual(merged["state_patch"]["story_time"], "当夜")
        self.assertEqual(merged["stage_archive"]["summary"], "保留原阶段档案")

    def test_foreshadow_code_does_not_extract_uuid_fragment(self):
        self.assertEqual(_normalize_foreshadow_code("F003"), "F0003")
        self.assertEqual(_normalize_foreshadow_code("F003｜旧线索"), "F0003")
        self.assertEqual(
            _normalize_foreshadow_code("7b4cbaee-f7b1-4c2a-9d10-628de15cf000"),
            "",
        )
        self.assertEqual(_normalize_foreshadow_code("abcF003"), "")

    def test_reconciliation_patch_merges_long_term_event_storage(self):
        original = {
            "long_term_events": [{
                "event_key": "LTE-0060-02",
                "event": "完整玉佩对应中央地域线索与非王朝旧印",
                "category": "other",
                "evidence_quote": "物件已经损坏",
                "storage": {
                    "fact_refs": ["AF-0001"],
                    "object_keys": ["NO002"],
                },
            }],
        }
        patch = {
            "long_term_events": [{
                "event_key": "LTE-0060-02",
                "storage": {"object_keys": ["OBJ-002"]},
            }],
        }

        merged = _merge_long_form_memory_reconciliation_patch(original, patch)
        self.assertEqual(len(merged["long_term_events"]), 1)
        self.assertEqual(
            merged["long_term_events"][0]["storage"]["object_keys"],
            ["OBJ-002"],
        )
        self.assertEqual(
            merged["long_term_events"][0]["storage"]["fact_refs"],
            ["AF-0001"],
        )
        self.assertEqual(
            _merge_long_form_memory_reconciliation_patch(merged, patch),
            merged,
        )

    def test_reconciliation_patch_matches_lte_ordinal_to_existing_event_key(self):
        original = {
            "long_term_events": [
                {"event_key": "EV-CH60-ARCHIVE-ROUTE", "event": "路线证据", "storage": {}},
                {"event_key": "EV-CH60-SEAL-SOUL", "event": "青黑旧印", "storage": {"object_keys": ["NO002"]}},
                {"event_key": "EV-CH60-FORGET", "event": "忘天机坐标", "storage": {}},
            ],
        }
        patch = {
            "long_term_events": [{
                "event_key": "LTE-0060-02",
                "storage": {"object_keys": ["OBJ-002"]},
            }],
        }

        merged = _merge_long_form_memory_reconciliation_patch(original, patch)
        self.assertEqual(len(merged["long_term_events"]), 3)
        self.assertEqual(
            merged["long_term_events"][1]["event_key"],
            "EV-CH60-SEAL-SOUL",
        )
        self.assertEqual(
            merged["long_term_events"][1]["storage"]["object_keys"],
            ["OBJ-002"],
        )

    def test_reconciliation_patch_preserves_new_fact_lifecycle(self):
        original = {
            "fact_updates": [{
                "operation": "add",
                "key": "NF-0060-03",
                "scope": "chapter:60",
                "fact": "旧档案存在缺页",
                "evidence_quote": "档案缺了一页",
            }],
        }
        patch = {
            "fact_updates": [{
                "operation": "update",
                "key": "NF-0060-03",
                "fact": "旧档案确认存在缺页",
                "evidence_quote": "确认缺了一页",
            }],
        }

        merged = _merge_long_form_memory_reconciliation_patch(original, patch)
        self.assertEqual(len(merged["fact_updates"]), 1)
        self.assertEqual(merged["fact_updates"][0]["operation"], "add")
        self.assertEqual(merged["fact_updates"][0]["key"], "NF-0060-03")
        self.assertEqual(merged["fact_updates"][0]["fact"], "旧档案确认存在缺页")

    def test_reconciliation_normalizes_missing_operations_and_short_refs_before_merge(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["lore"] = [
            {"id": f"lore-{index}", "name": f"设定{index}"}
            for index in range(1, 6)
        ]
        project["foreshadow_items"] = [
            {"id": "f-1", "code": "F0001", "name": "伏笔一"},
            {"id": "f-2", "code": "F0002", "name": "伏笔二"},
            {"id": "f-3", "code": "F0003", "name": "伏笔三"},
        ]
        patch = {
            "record_updates": {
                "lore": [{
                    "lore_id": "L005",
                    "update": "设定在本章表现出新的限制。",
                    "evidence_quote": "新的限制",
                }],
            },
            "foreshadow_updates": [{
                "id": "F003",
                "update": "伏笔出现新的直接证据。",
                "evidence_quote": "直接证据",
            }],
        }

        normalized = _normalize_long_form_reconciliation_patch(project, patch)
        lore_update = normalized["record_updates"]["lore"][0]
        foreshadow_update = normalized["foreshadow_updates"][0]
        self.assertEqual(lore_update["operation"], "update")
        self.assertEqual(lore_update["ref"], "lore-5")
        self.assertEqual(lore_update["state"], "设定在本章表现出新的限制。")
        self.assertEqual(foreshadow_update["operation"], "update")
        self.assertEqual(foreshadow_update["ref"], "f-3")
        self.assertEqual(foreshadow_update["state"], "伏笔出现新的直接证据。")

        original = {
            "schema_version": 2,
            "base_revision": 0,
            "foreshadow_updates": [],
            "record_updates": {"characters": [], "lore": []},
            "long_term_events": [{
                "event": "伏笔三出现新证据。",
                "evidence_quote": "直接证据",
                "storage": {"foreshadow_refs": ["f-3"]},
            }],
            "state_reconciliation": {"foreshadow_refs": []},
        }
        merged = _merge_long_form_memory_reconciliation_patch(
            original, patch, project=project
        )
        merged = _normalize_long_form_structural_refs(project, 0, merged)
        self.assertEqual(merged["foreshadow_updates"][0]["operation"], "update")
        self.assertEqual(merged["foreshadow_updates"][0]["ref"], "f-3")
        self.assertEqual(
            merged["long_term_events"][0]["storage"]["foreshadow_refs"],
            ["f-3"],
        )

    def test_legacy_reconciliation_patch_passes_full_validation_after_normalization(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["foreshadow_items"] = [{
            "id": "f-3", "code": "F0003", "name": "玉佩线索",
        }]
        project["long_form_memory"] = {
            "schema_version": "2", "revision": 0,
            "state_snapshot": {}, "active_facts": [],
        }
        final_text = "石台上的玉佩线索在本章得到直接证据。"
        original = self._strict_update(project, 0)
        original["long_term_events"] = [{
            "event": "玉佩线索在本章得到直接证据",
            "category": "foreshadow",
            "evidence_quote": final_text,
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": ["f-3"], "object_keys": [],
                "conflict_refs": [], "task_refs": [],
            },
        }]
        original["state_reconciliation"]["foreshadow_refs"] = ["f-3"]
        original["state_reconciliation"]["record_runtime_review"] = {
            "reviewed_lore_refs": [],
            "unchanged_lore_refs": [],
            "reviewed_foreshadow_refs": ["f-3"],
            "unchanged_foreshadow_refs": [],
        }
        # This is the legacy shape observed in the failed real response.
        legacy_patch = {
            "foreshadow_updates": [{
                "id": "F003",
                "update": "完整玉佩线索已经得到直接证据。",
                "evidence_quote": final_text,
            }],
        }

        merged = _merge_long_form_memory_reconciliation_patch(
            original, legacy_patch, project=project
        )
        errors = _validate_long_form_memory_update(
            project, 0, merged, final_text=final_text,
            require_revision=True, require_evidence=True,
        )

        self.assertEqual(errors, [])
        self.assertEqual(
            merged["foreshadow_updates"][0]["ref"], "f-3"
        )
        self.assertEqual(
            merged["long_term_events"][0]["storage"]["foreshadow_refs"],
            ["f-3"],
        )

    def test_reconciliation_keeps_evidence_bound_to_final_chapter(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["foreshadow_items"] = [{
            "id": "f-1", "code": "F0001", "name": "旧线索",
        }]
        project["long_form_memory"] = {
            "schema_version": "2", "revision": 0,
            "state_snapshot": {}, "active_facts": [],
        }
        final_text = "本章发生了明确的当前事实。"
        update = self._strict_update(project, 0)
        update["foreshadow_updates"] = [{
            "operation": "update",
            "ref": "f-1",
            "state": "旧线索在本章得到推进。",
            # This is deliberately only available in an earlier chapter.
            "evidence_quote": "上一章才出现的证据",
        }]
        update["long_term_events"] = [{
            "event": "旧线索在本章得到推进",
            "category": "foreshadow",
            "evidence_quote": final_text,
            "storage": {
                "fact_refs": [], "character_refs": [], "lore_refs": [],
                "foreshadow_refs": ["f-1"], "object_keys": [],
                "conflict_refs": [], "task_refs": [],
            },
        }]
        update["state_reconciliation"]["foreshadow_refs"] = ["f-1"]
        update["state_reconciliation"]["record_runtime_review"] = {
            "reviewed_lore_refs": [],
            "unchanged_lore_refs": [],
            "reviewed_foreshadow_refs": ["f-1"],
            "unchanged_foreshadow_refs": [],
        }

        errors = _validate_long_form_memory_update(
            project, 0, update, final_text=final_text,
            require_revision=True, require_evidence=True,
        )

        self.assertTrue(any("foreshadows更新第1项缺少正文逐字证据" in error for error in errors))

    def test_reconciliation_prompt_marks_recent_chapters_as_non_evidence(self):
        chapters = [_new_chapter(index) for index in range(10)]
        project = self._project_with_current_chapter(chapters[-1])
        project["chapters"] = chapters
        update = self._strict_update(project, 9)

        context = _build_long_form_memory_reconcile_context(
            project, 9, "当前章正文证据", update
        )

        self.assertIn("证据来源有严格分区", context)
        self.assertIn("禁止从其中复制任何证据", context)
        self.assertIn("仅供比对，禁止作为证据", context)

    def test_memory_finalize_parser_repairs_one_missing_root_delimiter(self):
        response = {
            "logic_audit": {"checked": True, "issues": []},
            "prose_review": {"checked": True, "issues": []},
            "repair_patches": [],
            "outline": "本章提纲",
            "summary": "本章摘要",
            "key_facts": ["本章事实"],
            "long_form_memory": {
                "schema_version": 2,
                "base_revision": 29,
                "state_patch": {},
            },
        }
        raw = json.dumps(response, ensure_ascii=False)[:-1]

        parsed = _parse_memory_repair_result(raw)

        self.assertTrue(parsed["parsed"])
        self.assertEqual(parsed["repair_mode"], "full")
        self.assertEqual(parsed["outline"], "本章提纲")
        self.assertEqual(parsed["summary"], "本章摘要")
        self.assertEqual(parsed["key_facts"], "1. 本章事实")
        self.assertEqual(parsed["memory_update"]["base_revision"], 29)

    def test_reconciliation_does_not_guess_unknown_reference_operation(self):
        project = self._project_with_current_chapter(_new_chapter(0))
        patch = {
            "foreshadow_updates": [{
                "id": "F999",
                "update": "无法对应到已有伏笔。",
                "evidence_quote": "无法对应",
            }],
        }

        normalized = _normalize_long_form_reconciliation_patch(project, patch)
        item = normalized["foreshadow_updates"][0]
        self.assertEqual(item.get("id"), "F999")
        self.assertNotIn("operation", item)

    def test_saved_state_delta_resolves_new_conflict_and_task_temp_refs(self):
        chapter = _new_chapter(0)
        project = self._project_with_current_chapter(chapter)
        project["long_form_memory"] = {"schema_version": "2", "revision": 0}
        update = self._strict_update(project)
        update["state_patch"] = {
            "active_conflicts": [{"key": "NCF1", "conflict": "追兵已经锁定赵明"}],
            "unresolved_tasks": [{"key": "NTASK1", "task": "天亮前离开王城"}],
        }
        update["state_delta"] = {
            "conflicts": [
                {"conflict_ref": "NCF1", "change": "新增"},
                {"id": "NCF1", "change": "同步引用"},
            ],
            "tasks": [
                {"task_ref": "NTASK1", "change": "新增"},
                {"key": "NTASK1", "change": "同步引用"},
            ],
        }

        self.assertTrue(_apply_long_form_memory_update(project, 0, update))

        stored = json.dumps(project["chapters"][0]["state_delta"], ensure_ascii=False)
        self.assertNotIn("NCF1", stored)
        self.assertNotIn("NTASK1", stored)
        self.assertIn("CF-0001", stored)
        self.assertIn("TASK-0001", stored)


if __name__ == "__main__":
    unittest.main()
