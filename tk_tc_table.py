"""TC 제목과 최근 실행 결과를 보여주는 선택 가능한 테이블."""
from tkinter import ttk


class TCTable(ttk.Treeview):
    def __init__(self, parent):
        super().__init__(parent, columns=('title', 'result'), show='headings',
                         selectmode='extended', height=15)
        self._row_ids = set()
        self.heading('title', text='TC')
        self.heading('result', text='실행결과')
        self.column('title', width=650, minwidth=200)
        self.column('result', width=110, minwidth=90, stretch=False, anchor='center')
        for result, color in [('PASS', '#16803c'), ('FAIL', '#c62828'), ('확인 필요', '#a66a00')]:
            self.tag_configure(result, foreground=color)

    # 실행 대상 선택과 목록 초기화의 기존 호출 규약을 유지한다.
    def delete(self, *items):
        if items == (0, 'end'):
            items = self._all_rows()
        if items:
            super().delete(*items)
            self._row_ids.difference_update(items)

    def curselection(self):
        selected = set(self.selection())
        return tuple(int(item) for item in self.get_children() if item in selected)

    def _all_rows(self):
        # 필터로 숨긴 행도 목록을 다시 불러올 때 삭제한다.
        return tuple(self._row_ids)

    def insert(self, parent, index, iid=None, **kwargs):
        item = super().insert(parent, index, iid=iid, **kwargs)
        self._row_ids.add(item)
        return item

    def select_set(self, first, last=None):
        rows = self.get_children()
        last = len(rows) - 1 if last == 'end' else (first if last is None else last)
        self.selection_add(rows[first:last + 1])

    def select_clear(self, first, last=None):
        self.selection_remove(self.selection())
