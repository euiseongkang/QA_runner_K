"""작은 화면에서도 설정과 실행 버튼에 접근할 수 있는 Tkinter 스크롤 영역."""
import math
import tkinter as tk
from tkinter import ttk


class ScrollableFrame(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent)
        self.canvas = tk.Canvas(self, highlightthickness=0,
                                width=min(960, max(320, parent.winfo_screenwidth() - 100)),
                                height=min(760, max(240, parent.winfo_screenheight() - 160)))
        self.vertical = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.horizontal = ttk.Scrollbar(self, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=self.vertical.set, xscrollcommand=self.horizontal.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        self.vertical.grid(row=0, column=1, sticky="ns")
        self.horizontal.grid(row=1, column=0, sticky="ew")
        self.rowconfigure(0, weight=1)
        self.columnconfigure(0, weight=1)
        self.content = ttk.Frame(self.canvas)
        self.window = self.canvas.create_window(0, 0, window=self.content, anchor="nw")
        self.content.bind("<Configure>", self._resize)
        self.canvas.bind("<Configure>", self._resize)
        for sequence in ("<MouseWheel>", "<Shift-MouseWheel>", "<Button-4>", "<Button-5>"):
            parent.bind(sequence, self._wheel, add="+")

    def _resize(self, event=None):
        self.canvas.itemconfigure(self.window,
                                  width=max(self.content.winfo_reqwidth(), self.canvas.winfo_width()),
                                  height=max(self.content.winfo_reqheight(), self.canvas.winfo_height()))
        self.canvas.configure(scrollregion=self.canvas.bbox(self.window))

    def _wheel(self, event):
        widget = event.widget
        # TC 목록·로그·콤보박스는 자신의 기본 휠 동작을 유지한다.
        if widget.winfo_class() in ("Text", "Listbox", "Treeview", "TCombobox", "Scrollbar", "TScrollbar"):
            return
        while widget is not None and widget is not self:
            widget = getattr(widget, "master", None)
        if widget is None:
            return
        if getattr(event, "num", None) in (4, 5):
            steps = -1 if event.num == 4 else 1
        else:
            delta = event.delta
            if not delta:
                return
            scale = 1 if self.tk.call("tk", "windowingsystem") == "aqua" else 120
            steps = -int(math.copysign(max(1, abs(delta) / scale), delta))
        scroll = self.canvas.xview_scroll if event.state & 1 else self.canvas.yview_scroll
        scroll(steps, "units")
        return "break"
