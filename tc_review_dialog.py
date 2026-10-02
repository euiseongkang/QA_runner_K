"""확인 필요 TC를 검토하고 AI 제안을 확인한 뒤 명시적으로 저장한다."""
import threading
import tkinter as tk
from tkinter import ttk, messagebox

from tk_clipboard import install_clipboard_support
from tk_scrollable import ScrollableFrame


class TCDetailDialog:
    """원본과 달라진 항목이 있을 때 명시적으로 저장한다."""
    EDITABLE = ('title', 'priority', 'sheet_name', 'precondition', 'steps', 'expected')

    def __init__(self, root, tc, sheets=(), save=None, on_saved=None):
        self.root, self.save_callback, self.on_saved = root, save, on_saved
        self.saving = False
        self.window = tk.Toplevel(root)
        self.window.title('TC 상세정보')
        self.window.transient(root)
        area = ScrollableFrame(self.window)
        area.pack(fill='both', expand=True)
        self.fields = {}
        number_row = ttk.Frame(area.content, padding=8)
        number_row.pack(fill='x')
        ttk.Label(number_row, text='TC 번호').pack(side='left', padx=(0, 8))
        number = ttk.Entry(number_row)
        number.insert(0, str(tc.get('tc_id') or ''))
        number.configure(state='readonly')
        number.pack(side='left', fill='x', expand=True)
        self.fields['tc_id'] = number
        for key, label, height in [
            ('title', 'TC 제목', 2),
            ('priority', '우선순위', 1), ('sheet_name', '시트', 1),
            ('precondition', '사전조건', 3), ('steps', '테스트 절차', 5),
            ('expected', '예상 결과', 4), ('note', '비고', 2),
            ('last_result', '최근 실행결과', 1), ('last_reason', '최근 실행 사유', 4),
        ]:
            frame = ttk.LabelFrame(area.content, text=label, padding=6)
            frame.pack(fill='x', padx=8, pady=3)
            value = str(tc.get(key) or '')
            if key in ('priority', 'sheet_name'):
                options = ('미지정', 'P1', 'P2', 'P3', 'P4') if key == 'priority' else tuple(sheets)
                options = tuple(dict.fromkeys((*options, value)))
                widget = ttk.Combobox(frame, values=options, state='readonly')
                widget.set(value)
            elif key == 'title':
                widget = ttk.Entry(frame)
                widget.insert(0, value)
            else:
                widget = tk.Text(frame, height=height, width=75, wrap='word')
                widget.insert('1.0', value)
                if key in ('note', 'last_result', 'last_reason'):
                    widget.configure(state='disabled')
            widget.pack(fill='x')
            self.fields[key] = widget
        self.original = self.values()
        self.status = ttk.Label(area.content, text='변경 후 [저장]을 누르면 원본에 반영됩니다.', padding=8)
        self.status.pack(anchor='w')
        buttons = ttk.Frame(self.window, padding=8)
        buttons.pack(fill='x')
        self.close_button = ttk.Button(buttons, text='닫기', command=self.window.destroy)
        self.close_button.pack(side='right')
        self.save_button = ttk.Button(buttons, text='저장', command=self.save, state='disabled')
        self.save_button.pack(side='right', padx=6)
        self.variables = []
        for key in self.EDITABLE:
            widget = self.fields[key]
            if isinstance(widget, tk.Text):
                widget.edit_modified(False)
                widget.bind('<<Modified>>', self._modified)
            else:
                var = tk.StringVar(self.window, value=widget.get())
                widget.configure(textvariable=var)
                var.trace_add('write', lambda *args: self._refresh_save())
                self.variables.append(var)
        self.window.protocol('WM_DELETE_WINDOW', lambda: None if self.saving else self.window.destroy())
        install_clipboard_support(self.window)
        self.window.grab_set()

    def values(self):
        return {key: (self.fields[key].get('1.0', 'end-1c') if isinstance(self.fields[key], tk.Text)
                      else self.fields[key].get()).strip() for key in self.EDITABLE}

    def _modified(self, event):
        if event.widget.edit_modified():
            event.widget.edit_modified(False)
            self._refresh_save()

    def _refresh_save(self):
        changed = self.values() != self.original
        self.save_button.configure(state='normal' if changed and self.save_callback and not self.saving else 'disabled')

    def save(self):
        values = self.values()
        if self.saving or values == self.original or not self.save_callback:
            return
        if any(not values[key] for key in ('title', 'steps', 'expected')):
            messagebox.showerror('TC 저장', 'TC 제목·테스트 절차·예상 결과는 필수입니다.', parent=self.window)
            return
        self.saving = True
        self._refresh_save()
        self.close_button.configure(state='disabled')
        self.status.configure(text='저장 중...')
        for key in self.EDITABLE:
            self.fields[key].configure(state='disabled')
        def finish(result=None, error=None):
            self.saving = False
            for key in self.EDITABLE:
                self.fields[key].configure(state='readonly' if key in ('priority', 'sheet_name') else 'normal')
            self.close_button.configure(state='normal')
            if error:
                self.status.configure(text='저장 요청을 완료하지 못했습니다.')
                messagebox.showerror('TC 저장', error, parent=self.window)
            else:
                if self.on_saved:
                    self.on_saved(values, result)
                self.original = dict(values)
                self.status.configure(text='저장했습니다. 수정한 TC는 다시 실행해 결과를 확인하세요.')
                for key in ('last_result', 'last_reason'):
                    self.fields[key].configure(state='normal')
                    self.fields[key].delete('1.0', 'end')
                    self.fields[key].configure(state='disabled')
            self._refresh_save()
        def worker():
            try:
                result = self.save_callback(values)
            except Exception as error:
                self.root.after(0, lambda message=str(error): finish(error=message))
            else:
                self.root.after(0, lambda: finish(result=result))
        threading.Thread(target=worker, daemon=True).start()


class TCReviewDialog:
    def __init__(self, root, tc, reason, optimize, save, ai_available):
        self.root = root
        self.window = tk.Toplevel(root)
        self.window.title('TC 검토 및 최적화')
        self.window.transient(root)
        area = ScrollableFrame(self.window)
        area.pack(fill='both', expand=True)
        content = area.content
        ttk.Label(content, text=f"[{tc.get('priority', '')}] {tc['tc_id']} | {tc['title']}",
                  padding=8).pack(anchor='w')
        self.fields = {}
        for field, label in [('steps', '테스트 절차'), ('expected', '예상 결과')]:
            frame = ttk.LabelFrame(content, text=label, padding=6)
            frame.pack(fill='both', expand=True, padx=8, pady=4)
            ttk.Label(frame, text='원본').pack(anchor='w')
            original = tk.Text(frame, height=3, width=85, wrap='word')
            original.insert('1.0', tc.get(field, ''))
            original.configure(state='disabled')
            original.pack(fill='x')
            ttk.Label(frame, text='저장할 문구 (직접 수정 가능)').pack(anchor='w')
            editor = tk.Text(frame, height=5, width=85, wrap='word')
            editor.insert('1.0', tc.get(field, ''))
            editor.pack(fill='both', expand=True)
            self.fields[field] = editor
        ttk.Label(content, text='가장 최근 실행 사유', padding=(8, 0)).pack(anchor='w')
        reason_text = tk.Text(content, height=4, width=85, wrap='word')
        reason_text.insert('1.0', reason or '저장된 사유가 없습니다.')
        reason_text.configure(state='disabled')
        reason_text.pack(fill='x', padx=8)
        self.status = ttk.Label(content, text='최적화 문구를 확인한 뒤 [저장]을 눌러야 원본에 반영됩니다.')
        self.status.pack(anchor='w', padx=8, pady=6)
        buttons = ttk.Frame(content, padding=8)
        buttons.pack(fill='x')
        self.optimize_button = ttk.Button(buttons, text='최적화', command=lambda: self.optimize(optimize))
        self.optimize_button.pack(side='left')
        if not ai_available:
            self.optimize_button.configure(state='disabled')
            self.status.configure(text='AI Provider의 API Key를 설정하면 최적화할 수 있습니다. 직접 편집·저장은 가능합니다.')
        self.save_button = ttk.Button(buttons, text='저장', command=lambda: self.save(save))
        self.save_button.pack(side='left', padx=6)
        ttk.Button(buttons, text='닫기', command=self.window.destroy).pack(side='right')
        self.ai_available = ai_available
        self.reason = reason
        self.tc = dict(tc)
        install_clipboard_support(self.window)
        self.window.grab_set()

    def values(self):
        return {key: widget.get('1.0', 'end-1c').strip() for key, widget in self.fields.items()}

    def _background(self, work, success):
        self.optimize_button.configure(state='disabled')
        self.save_button.configure(state='disabled')
        for widget in self.fields.values():
            widget.configure(state='disabled')
        def finish(value=None, error=None):
            if not self.window.winfo_exists():
                return
            self.save_button.configure(state='normal')
            self.optimize_button.configure(state='normal' if self.ai_available else 'disabled')
            for widget in self.fields.values():
                widget.configure(state='normal')
            if error:
                self.status.configure(text='실패했습니다. 원본은 변경하지 않았습니다.')
                messagebox.showerror('TC 편집', error, parent=self.window)
            else:
                success(value)
        def worker():
            try:
                value = work()
            except Exception as error:
                self.root.after(0, lambda message=str(error): finish(error=message))
            else:
                self.root.after(0, lambda: finish(value=value))
        threading.Thread(target=worker, daemon=True).start()

    def optimize(self, callback):
        values = self.values()
        self.status.configure(text='AI 최적화 제안을 생성하고 있습니다...')
        def show(proposal):
            for key, widget in self.fields.items():
                widget.delete('1.0', 'end')
                widget.insert('1.0', proposal[key])
            self.status.configure(text='원본과 비교하고 검증 의도가 유지되는지 확인한 뒤 [저장]을 누르세요.')
        self._background(lambda: callback(dict(self.tc, **values), self.reason), show)

    def save(self, callback):
        values = self.values()
        if not values['steps'] or not values['expected']:
            messagebox.showerror('TC 편집', '테스트 절차와 예상 결과를 모두 입력하세요.', parent=self.window)
            return
        self.status.configure(text='TC를 저장하고 있습니다...')
        def saved(value):
            messagebox.showinfo('TC 편집', '저장했습니다. 다시 실행해 결과를 확인하세요.', parent=self.window)
            self.window.destroy()
        self._background(lambda: callback(**values), saved)
