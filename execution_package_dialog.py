"""로컬 실행 패키지의 승인 상태와 학습 정답을 관리하는 화면."""
import math
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox
from tkinter.scrolledtext import ScrolledText

import execution_package
import results_store


class ExecutionPackageDialog:
    def __init__(self, parent, root):
        self.root = root
        self.window = tk.Toplevel(parent)
        self.window.title('실행 패키지 · 학습 승인 관리')
        self.window.geometry('1100x820')
        self.records, self.images = {}, []
        header = ttk.Frame(self.window, padding=8)
        header.pack(fill='x')
        ttk.Label(header, text='새 실행은 기본 승인됩니다. 특이 사례는 선택 후 미승인으로 변경하세요.').pack(anchor='w')
        ttk.Label(header, text=f'저장 위치: {root}', wraplength=1000).pack(anchor='w')
        controls = ttk.Frame(self.window, padding=8)
        controls.pack(fill='x')
        self.result_filter = tk.StringVar(value='전체')
        self.review_filter = tk.StringVar(value='전체')
        for label, variable, values in (('결과', self.result_filter, ('전체', 'PASS', 'FAIL', '확인 필요')),
                                         ('승인', self.review_filter, ('전체', '승인', '미승인', '검토 대기'))):
            ttk.Label(controls, text=label).pack(side='left', padx=4)
            combo = ttk.Combobox(controls, textvariable=variable, values=values, state='readonly', width=10)
            combo.pack(side='left')
            combo.bind('<<ComboboxSelected>>', lambda event: self.refresh())
        ttk.Button(controls, text='새로고침', command=self.refresh).pack(side='left', padx=8)
        ttk.Button(controls, text='표시된 전체 선택', command=lambda: self.tree.selection_set(self.tree.get_children())).pack(side='left')
        ttk.Button(controls, text='선택 승인', command=lambda: self.set_approval(True)).pack(side='left', padx=8)
        ttk.Button(controls, text='선택 미승인', command=lambda: self.set_approval(False)).pack(side='left')
        export_controls = ttk.Frame(self.window, padding=(8, 0, 8, 8))
        export_controls.pack(fill='x')
        self.export_button = ttk.Button(export_controls, text='학습 데이터 내보내기', command=self.export_training)
        self.export_button.pack(side='left')
        ttk.Label(export_controls, text='전체 승인 패키지 → finetuning/JSONL · 현재 필터/선택과 무관 · 편집 내용은 먼저 저장하세요.').pack(side='left', padx=8)
        from finetuning_setup import show_model_guidance
        ttk.Button(export_controls, text='권장 학습 모델 / 설치 안내',
                   command=lambda: show_model_guidance(self.window)).pack(side='left')
        pane = ttk.Panedwindow(self.window, orient='vertical')
        pane.pack(fill='both', expand=True, padx=8)
        listing = ttk.Frame(pane)
        pane.add(listing, weight=1)
        self.tree = ttk.Treeview(listing, columns=('time', 'tc', 'title', 'result', 'approval', 'source'),
                                 show='headings', selectmode='extended', height=8)
        for key, text, width in (('time', '실행 시각(UTC)', 195), ('tc', 'TC', 55), ('title', '제목', 320),
                                  ('result', '실행 결과', 95), ('approval', '학습 승인', 90), ('source', '승인 방식', 90)):
            self.tree.heading(key, text=text)
            self.tree.column(key, width=width, stretch=key == 'title')
        self.tree.pack(side='left', fill='both', expand=True)
        scroll = ttk.Scrollbar(listing, orient='vertical', command=self.tree.yview)
        scroll.pack(side='right', fill='y')
        self.tree.configure(yscrollcommand=scroll.set)
        self.tree.bind('<<TreeviewSelect>>', self.show_selected)
        detail = ttk.Frame(pane)
        pane.add(detail, weight=3)
        tabs = ttk.Notebook(detail)
        tabs.pack(fill='both', expand=True)
        self.evidence = ScrolledText(tabs, height=12, wrap='word')
        tabs.add(self.evidence, text='실행 결과·동작·사유')
        self.original = ScrolledText(tabs, height=12, wrap='word')
        tabs.add(self.original, text='실행 당시 TC 원문')
        editor = ttk.Frame(tabs, padding=6)
        tabs.add(editor, text='학습 정답 편집')
        self.fields = {}
        for key, title in (('precondition', '사전조건'), ('steps', '테스트 절차'), ('expected', '예상 결과')):
            ttk.Label(editor, text=title).pack(anchor='w')
            text = ScrolledText(editor, height=4, wrap='word')
            text.pack(fill='both', expand=True)
            self.fields[key] = text
        self.shots = {}
        for name, title in (('before', '실행 전 화면'), ('after', '실행 후 화면')):
            frame = ttk.Frame(tabs)
            tabs.add(frame, text=title)
            label = ttk.Label(frame, text='패키지를 선택하세요.')
            label.pack(fill='both', expand=True)
            self.shots[name] = label
        footer = ttk.Frame(self.window, padding=8)
        footer.pack(fill='x')
        ttk.Label(footer, text='검토 / 일괄 변경 사유').pack(side='left')
        self.reason = tk.StringVar()
        ttk.Entry(footer, textvariable=self.reason).pack(side='left', fill='x', expand=True, padx=8)
        self.approved = tk.BooleanVar(value=True)
        ttk.Checkbutton(footer, text='학습 승인', variable=self.approved).pack(side='left')
        ttk.Button(footer, text='정답 및 사유 저장', command=self.save).pack(side='left', padx=8)
        self.status = ttk.Label(self.window, padding=8)
        self.status.pack(fill='x')
        self.refresh()

    @staticmethod
    def approval_label(record):
        review = record['review']
        return '승인' if review.get('approved_for_training') else '검토 대기' if review.get('status') == 'pending' else '미승인'

    def export_training(self):
        from finetuning_export import export_packages
        destination = results_store.get_finetuning_export_root()
        self.export_button.configure(state='disabled')
        self.window.configure(cursor='watch')
        self.window.update_idletasks()
        try:
            path, report = export_packages(self.root, destination)
        except (OSError, ValueError) as error:
            messagebox.showerror('학습 데이터 내보내기', str(error), parent=self.window)
        else:
            counts = report['splits']
            text = (f"승인 자료 {report['exported']}건 저장\n"
                    f"train {counts['train']} · valid {counts['valid']} · test {counts['test']}\n"
                    f"중복 제외 {report['duplicates']} · 미승인 제외 {report['unapproved']}\n"
                    f"정답 형식 오류 {len(report['invalid'])} · 읽기 실패 {len(report['read_errors'])}\n\n{path}\n\n"
                    + '\n'.join(report['notes']))
            self.status.configure(text=f'학습 데이터 저장 완료: {path}')
            messagebox.showinfo('학습 데이터 내보내기 완료', text, parent=self.window)
        finally:
            self.export_button.configure(state='normal')
            self.window.configure(cursor='')

    def refresh(self):
        rows, errors = execution_package.list_packages(self.root)
        self.tree.delete(*self.tree.get_children())
        self.records = {}
        for record in rows:
            execution, tc, review = record['execution'], record['tc'], record['review']
            approved = self.approval_label(record)
            if self.result_filter.get() not in ('전체', execution['result']):
                continue
            if self.review_filter.get() not in ('전체', approved):
                continue
            item = self.tree.insert('', 'end', values=(execution.get('finished_at'), tc.get('tc_id', tc.get('tc_no', '')),
                tc.get('title', ''), execution['result'], approved,
                '기본 승인' if review.get('approval_source') == 'automatic' else '검토' if review.get('human_reviewed') else '미검토'))
            self.records[item] = record
        self.reason.set('')
        for text in (self.evidence, self.original, *self.fields.values()):
            self.set_text(text, '', readonly=text in (self.evidence, self.original))
        self.images = []
        for label in self.shots.values():
            label.configure(image='', text='패키지를 선택하세요.')
        self.status.configure(text=f'표시 {len(self.records)}건 / 전체 {len(rows)}건' + (f' · 읽기 실패 {len(errors)}건: {errors[0]}' if errors else ''))

    @staticmethod
    def set_text(widget, value, readonly=False):
        widget.configure(state='normal')
        widget.delete('1.0', 'end')
        widget.insert('1.0', value)
        if readonly:
            widget.configure(state='disabled')

    def show_selected(self, event=None):
        selected = self.tree.selection()
        if len(selected) != 1:
            self.status.configure(text=f'{len(selected)}건 선택 · 일괄 승인/미승인 가능 · 정답 편집은 한 건을 선택하세요.')
            return
        record = self.records[selected[0]]
        execution, tc, review = record['execution'], record['tc'], record['review']
        self.reason.set(review.get('review_reason') or '')
        self.approved.set(bool(review.get('approved_for_training')))
        corrected = review.get('corrected_tc') or tc
        for key, widget in self.fields.items():
            self.set_text(widget, corrected.get(key) or '')
        self.set_text(self.original, '\n\n'.join(f'{title}\n{tc.get(key, "")}' for key, title in
            (('precondition', '사전조건'), ('steps', '테스트 절차'), ('expected', '예상 결과'))), True)
        trace = record['actions'].get('trace', [])
        details = [f"실행 결과: {execution['result']}", f"판정 사유: {execution.get('reason', '')}",
                   f"학습 승인: {self.approval_label(record)}", '', '실제 동작']
        details += [f"{r['index']}. {r['status']} · {r['action'].get('description', r['action'].get('type', ''))}"
                    + (f" · {r['error']}" if r.get('error') else '') for r in trace]
        details += ['', '기록 오류', *(execution.get('errors') or ['없음'])]
        self.set_text(self.evidence, '\n'.join(details), True)
        self.images = []
        for name, label in self.shots.items():
            label.configure(image='', text='수집된 스크린샷이 없습니다.')
            relative = execution.get('screenshots', {}).get(name)
            if not relative:
                continue
            try:
                path = (Path(record['path']) / relative).resolve()
                path.relative_to(Path(record['path']).resolve())
                image = tk.PhotoImage(file=str(path), master=self.window)
                scale = max(1, math.ceil(image.width() / 1000), math.ceil(image.height() / 470))
                image = image.subsample(scale, scale)
                self.images.append(image)
                label.configure(image=image, text='')
            except (ValueError, OSError, tk.TclError):
                label.configure(text='스크린샷을 표시하지 못했습니다.')
        self.status.configure(text=record['path'])

    def set_approval(self, approved):
        selected = self.tree.selection()
        if not selected:
            return
        failures = []
        for item in selected:
            record = self.records[item]
            try:
                execution_package.update_review(self.root, record['path'], approved,
                    self.reason.get().strip() or record['review'].get('review_reason', ''))
            except (ValueError, OSError) as error:
                failures.append(str(error))
        self.refresh()
        self.status.configure(text=f'{len(selected)-len(failures)}건 ' + ('승인' if approved else '미승인') + ' 처리 완료')
        if failures:
            messagebox.showerror('학습 승인', f'{len(failures)}건 저장 실패: {failures[0]}', parent=self.window)

    def save(self):
        selected = self.tree.selection()
        if len(selected) != 1:
            messagebox.showinfo('학습 정답', '편집할 패키지 한 건을 선택하세요.', parent=self.window)
            return
        try:
            execution_package.update_review(self.root, self.records[selected[0]]['path'], self.approved.get(),
                self.reason.get().strip(), {key: widget.get('1.0', 'end-1c') for key, widget in self.fields.items()})
        except (ValueError, OSError) as error:
            messagebox.showerror('학습 정답 저장', str(error), parent=self.window)
            return
        self.refresh()
        self.status.configure(text='학습 정답·검토 사유·승인 상태를 저장했습니다. 실행 당시 TC와 판정은 유지됩니다.')
