import os
import unittest
from unittest.mock import Mock, patch

import qa_runner_k_gui as gui
import results_store


class ExistingUserCompatibilityTests(unittest.TestCase):
    def make_app(self):
        app = gui.QAWorkerApp.__new__(gui.QAWorkerApp)
        app.team_url_var = Mock(get=Mock(return_value=gui.TEAM_DASHBOARD_URL))
        app.api_token_var = Mock(get=Mock(return_value="existing-token"))
        app.tc_listbox = Mock()
        app.log_msg = Mock()
        app.tc_data = []
        app._ensure_dashboard = Mock()
        app._dashboard_url = Mock(return_value="http://127.0.0.1:8765/tcs")
        app._open_browser = Mock()
        return app

    def test_saved_team_url_does_not_change_tc_management(self):
        app = self.make_app()
        app.open_tc_dashboard()
        app._ensure_dashboard.assert_called_once()
        app._open_browser.assert_called_once_with("http://127.0.0.1:8765/tcs")

    def test_tc_loading_stays_local_even_with_team_url_token_and_environment(self):
        app = self.make_app()
        row = {"id": 7, "title": "로컬 TC", "steps": "절차", "expected": "결과"}
        with patch.dict(os.environ, {"QA_RUNNER_K_TEAM_DASHBOARD_URL": gui.TEAM_DASHBOARD_URL}), \
                patch.object(gui.requests, "get") as get, \
                patch.object(results_store, "list_custom_tcs", return_value=[row]) as local:
            app._load_tcs_from_custom()
            local.assert_called_once_with(only_enabled=True)
            get.assert_not_called()
        self.assertEqual(app.tc_data[0]["id"], "custom:7")

    def test_team_dashboard_shortcut_keeps_existing_url(self):
        app = self.make_app()
        app.open_dashboard()
        app._open_browser.assert_called_once_with(gui.TEAM_DASHBOARD_URL)
        app._ensure_dashboard.assert_not_called()

    def test_windows_dashboard_startup_arguments_keep_working(self):
        with patch.object(gui.sys, "argv", ["QA_Runner_K.exe", "/dashboard", "--startup"]), \
                patch("dashboard_app.main") as dashboard:
            gui.main()
            dashboard.assert_called_once_with(open_browser=False, minimized=True)


if __name__ == "__main__":
    unittest.main()
