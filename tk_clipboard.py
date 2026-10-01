"""Windows/macOS 공통 Tk 입력란 단축키와 편집 메뉴."""

import tkinter as tk
from tkinter import ttk


def _mac_command_action(event):
    """Aqua는 입력기/네이티브 이벤트에 따라 keysym을 ??로 전달하기도 한다."""
    if not event.state & 0x08 or event.state & 0x14:  # Command, 제외: Control/Option
        return None
    actions = {"a": "select_all", "c": "copy", "v": "paste", "x": "cut"}
    action = actions.get(str(event.keysym).lower())
    if action:
        return action
    # Tk Aqua의 keycode: 하위 22비트 Unicode, 상위 8비트 물리 키 위치.
    # 가상/네이티브 텍스트 이벤트는 물리 키 없이 Unicode만 전달할 수 있다.
    code = int(event.keycode) & 0xffffffff
    action = actions.get(chr(code & 0x3fffff).lower()) if (code & 0x3fffff) <= 0x10ffff else None
    if action:
        return action
    if code == ord("ㅁ"):  # 두벌식 A: 물리 키 번호 0이므로 상위 비트도 0
        return "select_all"
    if code > 0xffffff:
        return {0: "select_all", 7: "cut", 8: "copy", 9: "paste"}.get(code >> 24)
    return None


def _editable(widget):
    return not isinstance(widget, tk.Listbox) and str(widget.cget("state")) == "normal"


def _selection(widget):
    if isinstance(widget, tk.Text):
        return widget.get("sel.first", "sel.last")
    if isinstance(widget, tk.Listbox):
        return "\n".join(widget.get(i) for i in widget.curselection())
    if widget.selection_present():
        return widget.get()[int(widget.index("sel.first")):int(widget.index("sel.last"))]
    return ""


def _delete_selection(widget):
    if isinstance(widget, tk.Text):
        if widget.tag_ranges("sel"):
            widget.delete("sel.first", "sel.last")
    elif widget.selection_present():
        widget.delete("sel.first", "sel.last")


def edit(widget, action):
    """읽기 전용 로그/목록은 복사·전체 선택만 허용한다."""
    if widget is None:
        return "break"
    try:
        if action in ("copy", "cut"):
            if action == "cut" and not _editable(widget):
                return "break"
            value = _selection(widget)
            if value:
                widget.clipboard_clear()
                widget.clipboard_append(value)
                if action == "cut":
                    _delete_selection(widget)
        elif action == "paste" and _editable(widget):
            value = widget.clipboard_get()
            _delete_selection(widget)
            if not isinstance(widget, tk.Text):
                value = value.replace("\r\n", " ").replace("\r", " ").replace("\n", " ")
            widget.insert("insert", value)
        elif action == "select_all":
            if isinstance(widget, tk.Text):
                widget.tag_add("sel", "1.0", "end-1c")
            elif isinstance(widget, tk.Listbox):
                widget.selection_set(0, "end")
            else:
                widget.selection_range(0, "end")
                widget.icursor("end")
    except tk.TclError:
        # 선택 영역이 없거나 클립보드에 텍스트가 없는 경우는 아무 것도 변경하지 않는다.
        pass
    return "break"


def install_clipboard_support(root):
    """입력란 생성 후 호출한다. 위젯 바인딩으로 기본 단축키의 중복 실행을 막는다."""
    supported = (tk.Entry, ttk.Entry, tk.Text, tk.Listbox)
    labels = (("잘라내기", "cut", "X"), ("복사", "copy", "C"),
              ("붙여넣기", "paste", "V"), ("전체 선택", "select_all", "A"))
    is_mac = root.tk.call("tk", "windowingsystem") == "aqua"
    modifier = "Command" if is_mac else "Ctrl"
    widgets = []

    def visit(parent):
        for widget in parent.winfo_children():
            if isinstance(widget, supported):
                widgets.append(widget)
            visit(widget)

    visit(root)

    last_editor = None

    def remember_editor(event):
        nonlocal last_editor
        if isinstance(event.widget, supported):
            last_editor = event.widget

    def focused_action(action):
        widget = root.focus_get()
        # Aqua의 네이티브 메뉴를 열거나 단축키로 메뉴 명령을 실행하면
        # focus_get()이 입력란 대신 메뉴/창을 반환할 수 있다.
        if not isinstance(widget, supported):
            widget = last_editor
        if isinstance(widget, supported):
            return edit(widget, action)

    if is_mac:
        # 위젯/클래스의 문자별 바인딩보다 먼저 실제 Command 이벤트를 처리한다.
        # root에도 붙여 네이티브 메뉴가 포커스를 창으로 옮긴 경우를 처리한다.
        command_tag = f"QAClipboardCommand:{root}"

        def command_key(event):
            action = _mac_command_action(event)
            if action:
                if isinstance(event.widget, supported):
                    return edit(event.widget, action)
                return focused_action(action)

        root.bind_class(command_tag, "<KeyPress>", command_key)
        for target in [root] + widgets:
            target.bindtags((command_tag,) + tuple(t for t in target.bindtags() if t != command_tag))

    menubar = tk.Menu(root)
    menu = tk.Menu(menubar, tearoff=False)
    for label, action, key in labels:
        menu.add_command(label=label, accelerator=f"{modifier}+{key}",
                         command=lambda a=action: focused_action(a))
    menubar.add_cascade(label="편집", menu=menu)
    root.configure(menu=menubar)

    for widget in widgets:
        widget.configure(exportselection=False)
        widget.bind("<FocusIn>", remember_editor, add=True)
        widget.bind("<Button-1>", remember_editor, add=True)
        context = tk.Menu(root, tearoff=False)
        for label, action, key in labels:
            context.add_command(label=label, command=lambda w=widget, a=action: edit(w, a))
            virtual = {"copy": "Copy", "cut": "Cut", "paste": "Paste", "select_all": "SelectAll"}[action]
            widget.bind(f"<<{virtual}>>", lambda event, a=action: edit(event.widget, a))
            for mod in (("Control", "Command") if is_mac else ("Control",)):
                for letter in (key.lower(), key):
                    widget.bind(f"<{mod}-Key-{letter}>", lambda event, a=action: edit(event.widget, a))

        def popup(event, w=widget, m=context):
            w.focus_set()
            for index, (_, action, _) in enumerate(labels):
                allowed = action not in ("cut", "paste") or _editable(w)
                m.entryconfigure(index, state="normal" if allowed else "disabled")
            try:
                m.tk_popup(event.x_root, event.y_root)
            finally:
                m.grab_release()
            return "break"

        widget.bind("<Button-3>", popup)
        if is_mac:
            widget.bind("<Button-2>", popup)
            widget.bind("<Control-Button-1>", popup)
