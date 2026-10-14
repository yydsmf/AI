import os
import tempfile
import unittest
from copy import deepcopy
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import (
    QApplication, QDialogButtonBox, QFrame, QMessageBox, QPushButton, QToolButton,
)

from gpt_desktop import novel_creation_wizard as wizard, novel_storage
from gpt_desktop.app import ChineseContextMenuFilter
from gpt_desktop.novel_writing_tab import NovelWritingTab


_QT_APP = QApplication.instance() or QApplication([])


class NovelUIControlsTests(unittest.TestCase):
    def _style_picker(self, style_id, current=True):
        entries = wizard._character_style_choice_entries()
        option = wizard._character_style_choice_option_label(entries[0])
        dialog = wizard.CreationChoicePickerDialog(
            "自定义主角风格",
            wizard._character_style_choice_groups(),
            current_value=option if current else "",
            removable_options={option: style_id},
        )
        self.addCleanup(dialog.deleteLater)
        return dialog, option

    def _saved_style(self):
        return novel_storage.upsert_character_style(
            "谨慎，先观察再行动", "说话自然，少用总结句",
            name="主角", source_project="已删除的项目",
        )

    def test_style_picker_cancel_confirmation_keeps_favorite(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            novel_storage, "NOVEL_CHARACTER_STYLE_LIBRARY_FILE", os.path.join(tmp, "styles.json")
        ):
            style_id = self._saved_style()
            dialog, option = self._style_picker(style_id)
            choice = next(b for b in dialog.findChildren(QPushButton) if b.text() == option)
            self.assertTrue(choice.isChecked())
            removed = []
            dialog.style_removed.connect(removed.append)
            remove_button = dialog.findChild(QToolButton, f"remove_character_style_{style_id}")
            self.assertIsNotNone(remove_button)
            self.assertEqual(remove_button.toolTip(), "取消收藏")
            with patch.object(wizard.QMessageBox, "question", return_value=QMessageBox.No) as question:
                remove_button.click()
            self.assertEqual(question.call_args.args[-1], QMessageBox.No)
            self.assertEqual(len(novel_storage.load_character_style_library()), 1)
            self.assertEqual(removed, [])
            self.assertEqual(dialog.selected_values, [option])

    def test_confirmed_removal_clears_selection_but_keeps_generated_story(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            novel_storage, "NOVEL_CHARACTER_STYLE_LIBRARY_FILE", os.path.join(tmp, "styles.json")
        ):
            style_id = self._saved_style()
            dialog, option = self._style_picker(style_id)
            parent = wizard.NovelCreationWizardDialog.__new__(wizard.NovelCreationWizardDialog)
            parent.choice_values = {"protagonist_style": style_id}
            parent.choice_display_values = {"protagonist_style": "主角"}
            parent.choice_summary_buttons = {"protagonist_style": QPushButton("主角")}
            parent.choice_arrow_buttons = {}
            parent.premise_candidates = []
            parent.step_results = {"bible": {"characters": [{"personality": "谨慎"}]}}
            before = deepcopy(parent.step_results)
            saved = []
            parent._save_draft = lambda: saved.append(True)
            parent._on_choice_changed = lambda _key: None
            dialog.style_removed.connect(parent._on_character_style_removed)
            remove_button = dialog.findChild(QToolButton, f"remove_character_style_{style_id}")
            with patch.object(wizard.QMessageBox, "question", return_value=QMessageBox.Yes):
                remove_button.click()
            self.assertEqual(novel_storage.load_character_style_library(), [])
            self.assertTrue(remove_button.parentWidget().isHidden())
            self.assertEqual(dialog.selected_values, [])
            self.assertFalse(dialog._empty_label.isHidden())
            self.assertEqual(parent.choice_values, {})
            self.assertEqual(parent.choice_display_values, {})
            self.assertEqual(parent.choice_summary_buttons["protagonist_style"].text(), "点击选择")
            self.assertEqual(parent.step_results, before)
            self.assertEqual(saved, [True])

    def test_failed_style_removal_keeps_option_and_selection(self):
        with tempfile.TemporaryDirectory() as tmp, patch.object(
            novel_storage, "NOVEL_CHARACTER_STYLE_LIBRARY_FILE", os.path.join(tmp, "styles.json")
        ):
            style_id = self._saved_style()
            dialog, option = self._style_picker(style_id)
            removed = []
            dialog.style_removed.connect(removed.append)
            remove_button = dialog.findChild(QToolButton, f"remove_character_style_{style_id}")
            with patch.object(wizard.QMessageBox, "question", return_value=QMessageBox.Yes), \
                patch.object(wizard.QMessageBox, "warning") as warning, \
                patch.object(wizard, "remove_character_style", side_effect=OSError("write failed")):
                remove_button.click()
            warning.assert_called_once()
            self.assertEqual(removed, [])
            self.assertEqual(dialog.selected_values, [option])
            self.assertEqual(len(novel_storage.load_character_style_library()), 1)

    def test_other_choice_categories_have_no_remove_buttons(self):
        dialog = wizard.CreationChoicePickerDialog(
            "主题", {"分类": ("都市", "日常")}, current_value="都市", max_selections=2
        )
        self.addCleanup(dialog.deleteLater)
        self.assertEqual(dialog.findChildren(QToolButton), [])
        button = next(b for b in dialog.findChildren(QPushButton) if b.text() == "日常")
        button.click()
        self.assertEqual(dialog.selected_value, "都市、日常")

    def test_style_picker_cards_have_uniform_height_within_each_row(self):
        options = (
            "短标题\n性格/特点：短内容\n语言风格：短内容",
            "长标题\n性格/特点：第一行内容\n第二行内容\n第三行内容\n语言风格：较长的语言描述",
            "第三项\n性格/特点：短内容\n语言风格：短内容",
        )
        dialog = wizard.CreationChoicePickerDialog(
            "自定义主角风格",
            {"已收藏人物卡风格": options},
            removable_options={option: f"style-{index}" for index, option in enumerate(options)},
        )
        self.addCleanup(dialog.deleteLater)
        dialog.show()
        QApplication.processEvents()
        cards = dialog.findChildren(QFrame, "character_style_option")
        self.assertEqual(len(cards), 3)
        self.assertEqual(cards[0].height(), cards[1].height())
        self.assertNotEqual(cards[0].height(), cards[2].height())

    def test_standard_dialog_buttons_are_translated_to_chinese(self):
        message_box = QMessageBox()
        message_box.setStandardButtons(QMessageBox.Yes | QMessageBox.No | QMessageBox.Cancel)
        ChineseContextMenuFilter._translate_standard_button_texts(message_box)
        self.assertEqual(
            sorted(button.text() for button in message_box.buttons()),
            sorted(["确认", "取消", "取消"]),
        )

        button_box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        ChineseContextMenuFilter._translate_standard_button_texts(button_box)
        self.assertEqual(
            sorted(button.text() for button in button_box.buttons()),
            sorted(["确认", "取消"]),
        )

    def test_candidate_nav_is_hidden_without_changing_page_mapping(self):
        with patch("gpt_desktop.novel_writing_tab.ensure_novel_storage"), \
            patch.object(NovelWritingTab, "_log_novel_diagnostic"), \
            patch.object(NovelWritingTab, "refresh_providers"):
            tab = NovelWritingTab({"providers": [], "novel": {}}, background_runner=True)
        self.addCleanup(tab.deleteLater)
        tab._status_timer.stop()
        visible = [
            tab.nav_list.item(row).text() for row in range(tab.nav_list.count())
            if not tab.nav_list.item(row).isHidden()
        ]
        self.assertNotIn("候选", visible)
        self.assertIn("备注", visible)
        candidate_index = tab.page_indexes["候选"]
        self.assertIs(tab.tabs.widget(candidate_index), tab.import_candidates_tab)
        note_index = tab.page_indexes["备注"]
        tab.nav_list.setCurrentRow(tab._nav_row_for_page_index(note_index))
        self.assertEqual(tab.tabs.currentIndex(), note_index)


if __name__ == "__main__":
    unittest.main()
