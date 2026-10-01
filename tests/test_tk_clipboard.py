"""실제 Tk 위젯/클립보드 검증. 데스크톱 GUI 접근이 필요하다."""

import tkinter as tk
from tkinter import ttk
import unittest
from types import SimpleNamespace

from tk_clipboard import edit, install_clipboard_support, _mac_command_action


class MacKeyDecodingTests(unittest.TestCase):
    def test_unknown_keysym_unicode_event(self):
        for key, action in (("a", "select_all"), ("c", "copy"), ("v", "paste"), ("x", "cut")):
            self.assertEqual(_mac_command_action(SimpleNamespace(state=8, keysym="??", keycode=ord(key))), action)

    def test_korean_input_physical_key(self):
        for code, action in ((0, "select_all"), (7, "cut"), (8, "copy"), (9, "paste")):
            # A의 물리 코드는 0이며 한글 ㅁ의 Unicode가 하위 비트에 담긴다.
            event = SimpleNamespace(state=8, keysym="??", keycode=(code << 24) | ord("ㅁ"))
            self.assertEqual(_mac_command_action(event), action)

    def test_other_modifiers_are_not_intercepted(self):
        for state in (0, 4, 8 | 4, 8 | 16):
            self.assertIsNone(_mac_command_action(SimpleNamespace(state=state, keysym="a", keycode=97)))


class ClipboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.root = tk.Tk()
        cls.root.withdraw()
        try:
            cls.original_clipboard = cls.root.clipboard_get()
        except tk.TclError:
            cls.original_clipboard = None

    @classmethod
    def tearDownClass(cls):
        cls.root.clipboard_clear()
        if cls.original_clipboard is not None:
            cls.root.clipboard_append(cls.original_clipboard)
        cls.root.update()
        cls.root.destroy()

    def setUp(self):
        self.frame = ttk.Frame(self.root)
        self.entry = ttk.Entry(self.frame)
        self.secret = ttk.Entry(self.frame, show="*")
        self.combo = ttk.Combobox(self.frame, values=["Claude", "OpenAI"], state="readonly")
        self.log = tk.Text(self.frame)
        self.log.insert("1.0", "로그 내용")
        self.log.configure(state="disabled")
        self.items = tk.Listbox(self.frame)
        self.items.insert("end", "TC 1", "TC 2")
        self.frame.pack()
        for widget in (self.entry, self.secret, self.combo, self.log, self.items):
            widget.pack()
        self.root.deiconify()
        self.root.update()
        install_clipboard_support(self.root)
        self.addCleanup(self.frame.destroy)

    def set_clipboard(self, value):
        self.root.clipboard_clear()
        self.root.clipboard_append(value)

    def test_paste_replaces_selection_once(self):
        self.entry.insert(0, "before")
        self.entry.selection_range(0, "end")
        self.set_clipboard("테스트 URL")
        self.entry.event_generate("<<Paste>>")
        self.assertEqual(self.entry.get(), "테스트 URL")

    def test_mac_command_copy_and_paste(self):
        if self.root.tk.call("tk", "windowingsystem") != "aqua":
            self.skipTest("macOS Aqua 단축키 검증")
        self.entry.insert(0, "맥북 복사 테스트")
        self.entry.selection_range(0, "end")
        self.entry.focus_force()
        self.root.update()
        self.entry.event_generate("<Command-KeyPress-c>")
        self.assertEqual(self.root.clipboard_get(), "맥북 복사 테스트")
        self.secret.focus_force()
        self.root.update()
        self.secret.event_generate("<Command-KeyPress-v>")
        self.assertEqual(self.secret.get(), "맥북 복사 테스트")

    def test_unknown_keysym_command_select_all(self):
        if self.root.tk.call("tk", "windowingsystem") != "aqua":
            self.skipTest("macOS Aqua 단축키 검증")
        self.entry.insert(0, "실제 이벤트 경로")
        self.entry.focus_force()
        self.root.update()
        self.entry.event_generate("<KeyPress>", keycode=97, state=8)
        self.assertTrue(self.entry.selection_present())
        self.assertEqual(self.entry.index("sel.last"), len(self.entry.get()))

    def test_menu_targets_last_input_after_focus_moves_to_window(self):
        self.entry.insert(0, "메뉴 복사 테스트")
        self.entry.selection_range(0, "end")
        self.entry.focus_force()
        self.root.update()
        self.root.focus_force()
        self.root.update()
        menubar = self.root.nametowidget(self.root.cget("menu"))
        menu = self.root.nametowidget(menubar.entrycget(0, "menu"))
        menu.invoke(1)
        self.assertEqual(self.root.clipboard_get(), "메뉴 복사 테스트")
        self.secret.focus_force()
        self.root.update()
        self.root.focus_force()
        self.root.update()
        menu.invoke(2)
        self.assertEqual(self.secret.get(), "메뉴 복사 테스트")

    def test_masked_entry_supports_paste_and_cut(self):
        self.set_clipboard("dummy-api-key")
        self.secret.event_generate("<<Paste>>")
        self.secret.event_generate("<<SelectAll>>")
        self.secret.event_generate("<<Cut>>")
        self.assertEqual(self.secret.get(), "")
        self.assertEqual(self.root.clipboard_get(), "dummy-api-key")

    def test_disabled_log_copy_without_edit(self):
        self.log.event_generate("<<SelectAll>>")
        self.log.event_generate("<<Copy>>")
        self.assertEqual(self.root.clipboard_get(), "로그 내용")
        self.set_clipboard("replacement")
        self.log.event_generate("<<Paste>>")
        self.log.event_generate("<<Cut>>")
        self.assertEqual(self.log.get("1.0", "end-1c"), "로그 내용")

    def test_tc_list_copies_selected_rows(self):
        self.items.event_generate("<<SelectAll>>")
        self.items.event_generate("<<Copy>>")
        self.assertEqual(self.root.clipboard_get(), "TC 1\nTC 2")

    def test_readonly_combobox_cannot_be_pasted_into(self):
        self.combo.set("Claude")
        self.set_clipboard("OpenAI")
        edit(self.combo, "paste")
        self.assertEqual(self.combo.get(), "Claude")
