import os
import unittest
import tempfile
import tkinter as tk
from unittest.mock import Mock, patch

import qa_runner_k_gui as gui
import results_store
import dashboard_server


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

    def test_explicit_server_choice_opens_team_tc_page(self):
        app = self.make_app()
        app.dashboard_target_var = Mock(get=Mock(return_value="server"))
        app.open_tc_dashboard()
        app._open_browser.assert_called_once_with(gui.TEAM_DASHBOARD_URL + "tcs")
        app._ensure_dashboard.assert_not_called()

    def test_explicit_server_choice_loads_authenticated_tc(self):
        app = self.make_app()
        app.dashboard_target_var = Mock(get=Mock(return_value="server"))
        response = Mock(status_code=200)
        response.json.return_value = [{"id": 4, "title": "서버 TC", "enabled": 1},
                                      {"id": 5, "title": "제외 TC", "enabled": 0}]
        with patch.object(gui.requests, "get", return_value=response) as get, \
                patch.object(results_store, "list_custom_tcs") as local:
            app._load_tcs_from_custom()
            get.assert_called_once_with(gui.TEAM_DASHBOARD_URL + "api/tcs",
                                        headers={"Authorization": "Bearer existing-token"}, timeout=10)
            local.assert_not_called()
        self.assertEqual([tc["title"] for tc in app.tc_data], ["서버 TC"])

    def test_failed_remote_load_does_not_keep_old_local_tc(self):
        app = self.make_app()
        app.dashboard_target_var = Mock(get=Mock(return_value="server"))
        app.tc_data = [{"id": "custom:local"}]
        app.api_token_var.get.return_value = ""
        with patch.object(gui.requests, "get") as get:
            app._load_tcs_from_custom()
            get.assert_not_called()
        self.assertEqual(app.tc_data, [])

    def test_switch_clears_dashboard_tc_and_blocks_switch_during_run(self):
        app = self.make_app()
        app.dashboard_target_var = Mock(get=Mock(return_value="server"))
        app.tc_source_var = Mock(get=Mock(return_value="custom"))
        app.running = False
        app._on_dashboard_target_change()
        self.assertEqual(app.tc_data, [])
        self.assertEqual(app._dashboard_target, "server")
        app.running = True
        app.dashboard_target_var.get.return_value = "local"
        app._on_dashboard_target_change()
        app.dashboard_target_var.set.assert_called_once_with("server")


class ServerTCAPITests(unittest.TestCase):
    def test_token_required_and_only_enabled_tcs_are_requested(self):
        with tempfile.TemporaryDirectory() as folder, \
                patch.dict(os.environ, {"QA_RUNNER_K_API_TOKEN": "test-token", "QA_RUNNER_K_RETAIN_DAYS": "0"}), \
                patch.object(results_store, "list_custom_tcs", return_value=[{"id": 1}]) as rows:
            path = os.path.join(folder, "test.db")
            client = dashboard_server.create_app(db_path=path).test_client()
            self.assertEqual(client.get("/api/tcs").status_code, 401)
            rows.assert_not_called()
            response = client.get("/api/tcs", headers={"Authorization": "Bearer test-token"})
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json, [{"id": 1}])
            rows.assert_called_once_with(only_enabled=True, db_path=path)


class DashboardTargetUITests(unittest.TestCase):
    def test_selector_only_shows_for_dashboard_tc_in_source_mode(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        with patch.object(gui.QAWorkerApp, "_load_local_config"), \
                patch.object(gui.QAWorkerApp, "_ensure_dashboard"), \
                patch.object(gui.QAWorkerApp, "check_update_and_prompt"):
            app = gui.QAWorkerApp(root)
        self.assertEqual(app.dashboard_target_var.get(), "local")
        self.assertEqual(app.dashboard_target_frame.winfo_manager(), "")
        app.tc_source_var.set("custom")
        app._on_tc_source_change()
        root.update_idletasks()
        self.assertEqual(app.dashboard_target_frame.winfo_manager(), "pack")
        header = app.dashboard_target_frame.master
        self.assertEqual(header.master.cget("labelwidget"), str(header))
        app.tc_source_var.set("ec2")
        app._on_tc_source_change()
        self.assertEqual(app.dashboard_target_frame.winfo_manager(), "")

    def test_frozen_exe_keeps_existing_source_ui(self):
        root = tk.Tk()
        self.addCleanup(root.destroy)
        with patch.object(gui.sys, "frozen", True, create=True), \
                patch.object(gui.QAWorkerApp, "_load_local_config"), \
                patch.object(gui.QAWorkerApp, "_ensure_dashboard"), \
                patch.object(gui.QAWorkerApp, "check_update_and_prompt"):
            app = gui.QAWorkerApp(root)
        self.assertIsNone(app.dashboard_target_var)
        self.assertIsNone(app.dashboard_target_frame)
        self.assertFalse(app._uses_server_dashboard())


if __name__ == "__main__":
    unittest.main()
