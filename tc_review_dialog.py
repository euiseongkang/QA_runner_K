"""확인 필요 TC를 검토하고 AI 제안을 확인한 뒤 명시적으로 저장한다."""
import threading
import json
import tkinter as tk
from tkinter import ttk, messagebox

from tk_clipboard import install_clipboard_support
from tk_scrollable import ScrollableFrame
from tc_optimization import parse_detail_proposal, details_unchanged
from ai_stream import OptimizationProgress


def format_tc_for_copy(tc, unsaved=False):
    """대화에 붙여넣을 수 있도록 현재 TC의 값과 실행 기록만 선별한다."""
    lines = ['[QA 테스트케이스 검토 요청]',
             '아래 TC에서 문구 개선이 필요한 부분과 프로그램 실행·판정 로직의 문제를 구분해 분석해주세요.', '',
             '[TC 정보]']
    for key, label in (('tc_id', 'TC 번호'), ('title', 'TC 제목'),
                       ('priority', '우선순위'), ('sheet_name', '시트')):
        lines.append(f'{label}: {str(tc.get(key) or "").strip() or "없음"}')
    lines.append('편집 상태: ' + ('미저장 변경사항 포함' if unsaved else '변경사항 없음'))
    if unsaved:
        lines.append('최근 실행결과·사유는 현재 수정 내용으로 재실행한 결과가 아닐 수 있습니다.')
    for key, label in (('precondition', '사전조건'), ('steps', '테스트 절차'),
                       ('expected', '예상 결과'), ('note', '비고'),
                       ('last_result', '최근 실행결과'), ('last_reason', '최근 실행 사유'),
                       ('optimization_error', '최근 최적화 오류'),
                       ('optimization_diagnostics', '최근 최적화 수신 상태'),
                       ('optimization_partial', '중간 응답 일부 — 최종 결과 아님')):
        lines.extend(['', f'[{label}]', str(tc.get(key) or '').strip() or '없음'])
    return '\n'.join(lines)


class TCDetailDialog:
    """원본과 달라진 항목이 있을 때 명시적으로 저장한다."""
    EDITABLE = ('title', 'priority', 'sheet_name', 'precondition', 'steps', 'expected')

    def __init__(self, root, tc, sheets=(), save=None, on_saved=None, optimize=None):
        self.root, self.save_callback, self.on_saved = root, save, on_saved
        self.saving = False
        self.optimizing = False
        self.optimize_callback = optimize
        self.optimization_dialog = None
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
        self.optimize_button = ttk.Button(buttons, text='최적화', command=self.optimize,
                                          state='normal' if optimize else 'disabled')
        self.optimize_button.pack(side='left')
        self.copy_button = ttk.Button(buttons, text='복사', command=self.copy)
        self.copy_button.pack(side='left', padx=(6, 0))
        self.copy_status = ttk.Label(buttons, text='')
        self.copy_status.pack(side='left', padx=6)
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
        self.window.protocol('WM_DELETE_WINDOW', lambda: None if self.saving or self.optimizing else self.window.destroy())
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
        self.save_button.configure(state='normal' if changed and self.save_callback and not self.saving and not self.optimizing else 'disabled')

    def copy(self):
        if self.saving or self.optimizing:
            return
        values = self.values()
        for key in ('tc_id', 'note', 'last_result', 'last_reason'):
            widget = self.fields[key]
            values[key] = (widget.get('1.0', 'end-1c') if isinstance(widget, tk.Text) else widget.get()).strip()
        values['optimization_error'] = getattr(self.optimization_dialog, 'last_error', '')
        progress = getattr(self.optimization_dialog, 'stream_progress', None)
        if isinstance(progress, OptimizationProgress):
            state = progress.snapshot()
            values['optimization_partial'] = state.pop('preview', '')
            values['optimization_diagnostics'] = json.dumps(state,ensure_ascii=False,indent=2)
        text = format_tc_for_copy(values, unsaved=self.values() != self.original)
        try:
            # 상세 창을 닫아도 실행 중인 메인 창이 클립보드 소유권을 유지한다.
            self.root.clipboard_clear()
            self.root.clipboard_append(text)
        except tk.TclError:
            self.copy_status.configure(text='복사 실패')
            messagebox.showerror('TC 복사', '클립보드에 복사하지 못했습니다. 다시 시도하세요.', parent=self.window)
            return
        self.copy_status.configure(text='복사 완료')

    def optimize(self):
        if self.saving or self.optimizing or not self.optimize_callback:
            return
        values = self.values()
        if not values['steps']:
            messagebox.showerror('TC 최적화', '테스트 절차를 먼저 입력하세요.', parent=self.window)
            return
        try:
            work = self.optimize_callback(values)
        except Exception as error:
            messagebox.showerror('TC 최적화', str(error), parent=self.window)
            return
        self.optimizing = True
        self._refresh_save()
        self.optimize_button.configure(state='disabled')
        self.copy_button.configure(state='disabled')
        self.close_button.configure(state='disabled')
        self.window.configure(cursor='watch')
        for key in self.EDITABLE:
            self.fields[key].configure(state='disabled')

        def finish(proposal):
            self.optimizing = False
            self.window.configure(cursor='')
            for key in self.EDITABLE:
                self.fields[key].configure(state='readonly' if key in ('priority', 'sheet_name') else 'normal')
            if proposal is not None:
                for key in ('precondition', 'steps', 'expected'):
                    self.fields[key].delete('1.0', 'end')
                    self.fields[key].insert('1.0', proposal[key])
                label = '기본 교정' if proposal.get('correction_only') else 'AI 제안'
                self.status.configure(text=f'{label}을 적용했습니다. [저장]을 눌러야 원본에 반영됩니다.')
            elif getattr(self.optimization_dialog, 'no_changes', False):
                self.status.configure(text='변경이 필요 없습니다. 입력 내용은 유지됩니다.')
            else:
                self.status.configure(text='최적화를 취소했습니다. 입력 내용은 유지됩니다.')
            self.optimize_button.configure(state='normal')
            self.copy_button.configure(state='normal')
            self.close_button.configure(state='normal')
            self._refresh_save()
            self.window.grab_set()

        self.optimization_dialog = TCOptimizationDialog(self.window, values, work, finish)

    def save(self):
        values = self.values()
        if self.saving or self.optimizing or values == self.original or not self.save_callback:
            return
        if any(not values[key] for key in ('title', 'steps', 'expected')):
            messagebox.showerror('TC 저장', 'TC 제목·테스트 절차·예상 결과는 필수입니다.', parent=self.window)
            return
        self.saving = True
        self._refresh_save()
        self.close_button.configure(state='disabled')
        self.optimize_button.configure(state='disabled')
        self.copy_button.configure(state='disabled')
        self.status.configure(text='저장 중...')
        for key in self.EDITABLE:
            self.fields[key].configure(state='disabled')
        def finish(result=None, error=None):
            self.saving = False
            for key in self.EDITABLE:
                self.fields[key].configure(state='readonly' if key in ('priority', 'sheet_name') else 'normal')
            self.close_button.configure(state='normal')
            self.optimize_button.configure(state='normal' if self.optimize_callback else 'disabled')
            self.copy_button.configure(state='normal')
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


class TCOptimizationDialog:
    """UI를 멈추지 않고 명시적인 적용으로만 부모의 입력란을 변경한다."""
    def __init__(self, parent, before, work, finished):
        self.parent, self.finished = parent, finished
        self.before, self.proposal = before, None
        self.last_error = ''
        self.stream_progress = getattr(work, 'progress', None)
        if not isinstance(self.stream_progress, OptimizationProgress):
            self.stream_progress = None
        self.stream_poll = None
        self.stream_finished = False
        self.closed = False
        self.window = tk.Toplevel(parent)
        self.window.title('AI TC 최적화')
        self.window.transient(parent)
        self.window.geometry('780x620')
        self.window.configure(cursor='watch')
        self.window.columnconfigure(0, weight=1)
        self.window.rowconfigure(2, weight=1)
        self.window.minsize(360, 240)
        self.status = ttk.Label(self.window, text='현재 AI최적화 진행 중 입니다...', padding=12,
                                wraplength=740)
        self.status.grid(row=0, column=0, sticky='ew')
        response_timeout = getattr(work, 'response_timeout', None)
        if isinstance(response_timeout, (int, float)):
            self.status.configure(text='현재 AI최적화 진행 중 입니다...\n'
                                  f'응답 대기: 요청당 {response_timeout}초 · 품질 보완 요청 시 추가 대기합니다.')
        self.status.bind('<Configure>', lambda event: self.status.configure(wraplength=max(1, event.width - 24)))
        self.progress = ttk.Progressbar(self.window, mode='indeterminate')
        self.progress.grid(row=1, column=0, sticky='ew', padx=12, pady=6)
        self.progress.start(12)
        area = ScrollableFrame(self.window)
        area.grid(row=2, column=0, sticky='nsew')
        self.content = area.content
        if self.stream_progress is not None:
            stream_frame = ttk.LabelFrame(self.content, text='수신 중 응답 · 진단용 (최종 결과 아님)', padding=8)
            stream_frame.pack(fill='x',padx=12,pady=6)
            self.stream_status = ttk.Label(stream_frame,text='모델 응답을 기다리는 중입니다.',wraplength=700)
            self.stream_status.pack(fill='x')
            self.stream_text = tk.Text(stream_frame,height=10,width=65,wrap='word',state='disabled')
            self.stream_text.pack(fill='x')
            ttk.Button(stream_frame,text='중간 응답·진단 복사',command=self.copy_stream).pack(anchor='w',pady=4)
        self.buttons = ttk.Frame(self.window, padding=12)
        # 창이 작아지면 스크롤 영역만 줄이고 적용·취소 버튼 행은 확보한다.
        self.buttons.grid(row=3, column=0, sticky='ew')
        self.apply_button = ttk.Button(self.buttons, text='적용', command=self.apply, state='disabled')
        self.apply_button.pack(side='right', padx=6)
        self.cancel_button = ttk.Button(self.buttons, text='취소', command=self.cancel)
        self.cancel_button.pack(side='right')
        self.window.protocol('WM_DELETE_WINDOW', self.cancel)
        install_clipboard_support(self.window)
        self.window.grab_set()

        def complete(proposal=None, error=None):
            if self.closed:
                return
            self.stream_finished = True
            self._show_stream_progress()
            self.progress.stop()
            self.progress.grid_remove()
            self.window.configure(cursor='')
            self.parent.configure(cursor='')
            if error:
                self.last_error = str(error)
                self.status.configure(text='⚠ 품질 검증 · 최적화 결과를 적용할 수 없습니다. 입력 내용은 유지됩니다.')
                messagebox.showerror('TC 최적화', error, parent=self.window)
                return
            self.proposal = proposal
            self.no_changes = details_unchanged(before, proposal)
            basic = proposal.get('correction_only', False)
            rule_completion = proposal.get('rule_completion', False)
            badge = '✓ 실행 규칙 보완' if rule_completion else ('✓ 기본 교정' if basic else '✓ 품질 검증')
            if self.no_changes:
                self.status.configure(text=badge + ' · 변경이 필요 없습니다. 입력 내용은 유지됩니다.')
                review = ttk.LabelFrame(self.content, text=badge, padding=10)
                review.pack(fill='x', padx=12, pady=8)
                ttk.Label(review, text=proposal.get('review_reason', '원문과 동일한 결과입니다.'),
                          wraplength=560).pack(fill='x')
                self.cancel_button.configure(text='닫기')
                return
            self.status.configure(text=(badge + ' · 변경 전후를 확인한 뒤 [적용]을 누르세요.' if rule_completion else
                                       badge + ' · 기본 교정 결과를 확인한 뒤 [적용]을 누르세요.' if basic else
                                       '✓ 품질 검증 · AI 최적화가 완료되었습니다. 변경 전후를 확인한 뒤 [적용]을 누르세요.'))
            if proposal.get('review_reason'):
                review = ttk.LabelFrame(self.content, text=badge, padding=10)
                review.pack(fill='x', padx=12, pady=8)
                ttk.Label(review, text=proposal['review_reason'], wraplength=560).pack(fill='x')
            for key, label in (('precondition', '사전조건'), ('steps', '테스트 절차'), ('expected', '예상 결과')):
                frame = ttk.LabelFrame(self.content, text=label, padding=6)
                frame.pack(fill='x', padx=12, pady=5)
                for title, text in (('변경 전', before[key]),
                                    ('실행 규칙 보완' if rule_completion else '기본 교정' if basic else 'AI 제안', proposal[key])):
                    ttk.Label(frame, text=title).pack(anchor='w')
                    widget = tk.Text(frame, height=5, wrap='word', width=65)
                    widget.insert('1.0', text)
                    widget.configure(state='disabled')
                    widget.pack(fill='x')
            install_clipboard_support(self.window)
            self.apply_button.configure(state='normal')

        def worker():
            try:
                proposal = parse_detail_proposal(json.dumps(work(), ensure_ascii=False))
                callback = lambda: complete(proposal=proposal)
            except Exception as error:
                callback = lambda message=str(error): complete(error=message)
            try:
                # 부모 팝업이 닫혀도 네트워크 작업의 늦은 응답으로 새 창을 만들지 않는다.
                parent.after(0, callback)
            except (RuntimeError, tk.TclError):
                pass
        self._poll_stream_progress()
        threading.Thread(target=worker, daemon=True).start()

    def _show_stream_progress(self):
        if self.stream_progress is None or self.closed:
            return
        state = self.stream_progress.snapshot()
        sources = ('RAG 미사용' if state.get('provider') == 'Ollama' else f"검색 근거 {state['sources']}개")
        self.stream_status.configure(text=f"{state['phase']} · 경과 {state['elapsed']}초 / 전체 제한 {state['total_timeout']}초\n"
                                     f"요청 {state['request']}회 · 응답 {state['chars']}자 · 추론 {state['reasoning_chars']}자 · "
                                     f"{sources} · 종료 신호: {state['finish_reason'] or '아직 없음'}")
        text = state['preview']
        if self.stream_text.get('1.0','end-1c') != text:
            self.stream_text.configure(state='normal')
            self.stream_text.delete('1.0','end')
            self.stream_text.insert('1.0',text)
            self.stream_text.configure(state='disabled')
            self.stream_text.see('end')

    def _poll_stream_progress(self):
        if self.closed or self.stream_progress is None:
            return
        self._show_stream_progress()
        if not self.stream_finished:
            self.stream_poll = self.window.after(250,self._poll_stream_progress)

    def copy_stream(self):
        if self.stream_progress is None:
            return
        state = self.stream_progress.snapshot()
        preview = state.pop('preview','')
        text = ('[최적화 스트림 진단]\n' + json.dumps(state,ensure_ascii=False,indent=2) +
                '\n\n[중간 응답 — 최종 결과 아님]\n' + (preview or '없음'))
        try:
            self.parent.clipboard_clear()
            self.parent.clipboard_append(text)
        except tk.TclError:
            messagebox.showerror('진단 복사','클립보드에 복사하지 못했습니다.',parent=self.window)

    def apply(self):
        if not self.closed and self.proposal is not None:
            self._close(self.proposal)

    def cancel(self):
        if not self.closed:
            self._close(None)

    def _close(self, proposal):
        self.closed = True
        if self.stream_poll is not None:
            self.window.after_cancel(self.stream_poll)
        if self.stream_progress is not None and not self.stream_finished:
            self.stream_progress.cancelled.set()
        self.progress.stop()
        self.window.destroy()
        self.finished(proposal)


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
