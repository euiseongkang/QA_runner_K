"""실제 콤보박스의 세션·시트 표시와 TC 요청 연결을 검증한다."""
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

import qa_runner_k_gui as gui


def response(data):
    result = Mock()
    result.json.return_value = data
    return result


class EC2SessionTests(unittest.TestCase):
    def setUp(self):
        self.root = tk.Tk()
        self.addCleanup(self.root.destroy)
        with patch.object(gui.QAWorkerApp, '_load_local_config'), \
                patch.object(gui.QAWorkerApp, '_ensure_dashboard'), \
                patch.object(gui.QAWorkerApp, 'check_update_and_prompt'):
            self.app = gui.QAWorkerApp(self.root)
        self.app.log_msg = Mock()
        self.app.tc_source_var.set('ec2')
        self.app._on_tc_source_change()
        self.root.update()

    def test_session_dropdown_and_selection_request_correct_sheet_and_tc(self):
        app = self.app
        replies = [response([{'id': 11, 'name': '동일 이름'}, {'id': 12, 'name': '동일 이름'}]),
                   response([{'name': '첫 시트', 'total': 3}]),
                   response([{'name': '두번째 시트', 'total': 2}]),
                   response([{'id': 9, 'title': '선택한 세션 TC'}])]
        with patch.object(gui.requests, 'get', side_effect=replies) as get:
            app.load_sessions()
            values = app.session_combo['values']
            self.assertEqual(len(values), 2)
            self.assertNotEqual(values[0], values[1])
            self.assertEqual(app.session_var.get(), values[0])
            self.assertEqual(app.sheet_combo['values'], ('전체', '첫 시트'))
            app.session_var.set(values[1])
            app.session_combo.event_generate('<<ComboboxSelected>>')
            self.root.update()
            self.assertEqual(app.sheet_combo['values'], ('전체', '두번째 시트'))
            app.sheet_var.set('두번째 시트')
            app.load_tc_list()
            self.assertEqual(get.call_args_list[2].args[0], gui.DEFAULT_EC2_API + '/api/sessions/12/sheets')
            self.assertIn('/api/sessions/12/tcs?sheet=', get.call_args.args[0])
            self.assertEqual(app.tc_listbox.size(), 1)
            self.assertEqual(app.tc_data[0]['title'], '선택한 세션 TC')

    def test_empty_or_failed_reload_clears_old_selection_and_tc(self):
        app = self.app
        for result in (response([]), RuntimeError('network failed')):
            app.session_var.set('이전 세션')
            app.session_combo.configure(values=('이전 세션',))
            app.sheet_var.set('이전 시트')
            app.tc_data = [{'id': 1}]
            app.tc_listbox.insert('end', '이전 TC')
            with patch.object(gui.requests, 'get', side_effect=[result]):
                app.load_sessions()
            self.assertEqual(app.session_combo['values'], '')
            self.assertEqual(app.session_var.get(), '')
            self.assertEqual(app.sheet_var.get(), '')
            self.assertEqual(app.tc_data, [])
            self.assertEqual(app.tc_listbox.size(), 0)

    def test_sheet_failure_still_allows_all_tcs(self):
        app = self.app
        with patch.object(gui.requests, 'get', side_effect=[
                response([{'id': 1, 'name': '세션'}]), RuntimeError('sheets unavailable'), response([])]) as get:
            app.load_sessions()
            self.assertEqual(app.sheet_combo['values'], ('전체',))
            app.load_tc_list()
            self.assertEqual(get.call_args.args[0], gui.DEFAULT_EC2_API + '/api/sessions/1/tcs')


if __name__ == '__main__':
    unittest.main()
