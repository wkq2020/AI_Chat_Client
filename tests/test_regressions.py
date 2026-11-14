import json
import os
from pathlib import Path
import shutil
import sqlite3
import threading
import time
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
TEST_DATA_DIR = ROOT / "data" / "test-runtime"
shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)
os.environ["AI_CHAT_DATA_DIR"] = str(TEST_DATA_DIR)
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_OPENGL", "software")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu")

import httpx
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMessageBox

from src.core import config_manager, secret_store
from src.core.config_manager import ConfigManager
from src.core.llm_client import build_chat_completions_url, normalize_usage, stream_chat
from src.models import message_dao, session_dao
from src.models.database import get_connection
from src.ui.chat_view import ChatView
from src.ui.main_window import MainWindow
from src.ui.settings_dialog import SettingsDialog


class LocalAPIServer:
    def __init__(self, status=200, delay=0, error_text="bad request", usage=None):
        self.status = status
        self.delay = delay
        self.error_text = error_text
        self.usage = usage
        self.requests = []
        api = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                payload = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                api.requests.append({
                    "path": self.path,
                    "payload": payload,
                    "authorization": self.headers.get("Authorization"),
                })
                if api.status != 200:
                    body = api.error_text.encode("utf-8")
                    self.send_response(api.status)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return

                answer = f"answer-{len(api.requests)}"
                usage = api.usage or {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12}
                first = "data: " + json.dumps({"choices": [{"delta": {"content": answer}}]}) + "\n\n"
                last = "data: " + json.dumps({"choices": [], "usage": usage}) + "\n\ndata: [DONE]\n\n"
                try:
                    self.send_response(200)
                    self.send_header("Content-Type", "text/event-stream")
                    if not api.delay:
                        body = (first + last).encode("ascii")
                        self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    if api.delay:
                        self.wfile.write(first.encode("ascii"))
                        self.wfile.flush()
                        time.sleep(api.delay)
                        self.wfile.write(last.encode("ascii"))
                        self.wfile.flush()
                    else:
                        self.wfile.write(body)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *args):
                pass

        self.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    @property
    def base_url(self):
        return f"http://127.0.0.1:{self.server.server_port}"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *args):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


def wait_until(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while not predicate():
        if time.monotonic() >= deadline:
            raise AssertionError("Timed out waiting for condition")
        QApplication.processEvents()
        QTest.qWait(20)
    QApplication.processEvents()


def run_js(view, script):
    result = []
    view.web_view.page().runJavaScript(script, 0, result.append)
    wait_until(lambda: bool(result))
    return result[0]


def close_chat(view):
    view.shutdown()
    view.close()
    view.deleteLater()
    QApplication.processEvents()


def close_window(window):
    window.close()
    window.deleteLater()
    QApplication.processEvents()


class RegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self):
        ConfigManager._instance = None
        self.addCleanup(setattr, ConfigManager, "_instance", None)
        for path in (config_manager.CONFIG_PATH, f"{config_manager.CONFIG_PATH}.tmp"):
            try:
                os.remove(path)
            except FileNotFoundError:
                pass

        conn = get_connection()
        conn.execute("DELETE FROM messages")
        conn.execute("DELETE FROM sessions")
        conn.commit()
        conn.close()

        self.secrets = {}
        patches = [
            patch.object(secret_store, "set_api_key", side_effect=lambda api_id, key: self.secrets.__setitem__(api_id, key)),
            patch.object(secret_store, "get_api_key", side_effect=lambda api_id: self.secrets.get(api_id, "")),
            patch.object(secret_store, "delete_api_key", side_effect=lambda api_id: self.secrets.pop(api_id, None)),
        ]
        for patcher in patches:
            patcher.start()
            self.addCleanup(patcher.stop)
        self.config = ConfigManager()

    def configure_api(self, base_url, name="first"):
        api_id = self.config.add_api(name, base_url, "test-key")
        self.config.update_api(api_id, name, base_url, "test-key", [
            {"id": "demo-model", "name": "Demo", "capabilities": [], "thinking_control": "none"}
        ])
        return api_id

    def test_base_url_normalization(self):
        self.assertEqual(
            build_chat_completions_url("https://api.example.com"),
            "https://api.example.com/v1/chat/completions",
        )
        self.assertEqual(
            build_chat_completions_url("https://api.example.com/v1/"),
            "https://api.example.com/v1/chat/completions",
        )
        self.assertEqual(
            build_chat_completions_url("https://api.example.com/v1/chat/completions"),
            "https://api.example.com/v1/chat/completions",
        )

    def test_stream_url_usage_and_error_body(self):
        malicious = "<img src=x onerror=alert(1)>"
        usage = {
            "prompt_tokens": malicious,
            "completion_tokens": "2",
            "total_tokens": -1,
            "prompt_tokens_details": {"cached_tokens": malicious},
        }
        with LocalAPIServer(usage=usage) as server:
            chunks = list(stream_chat("test-key", f"{server.base_url}/v1", "demo", [], "session"))
        self.assertEqual(server.requests[0]["path"], "/v1/chat/completions")
        self.assertEqual(server.requests[0]["authorization"], "Bearer test-key")
        self.assertEqual([chunk["type"] for chunk in chunks], ["content", "usage"])
        normalized = chunks[-1]["data"]
        self.assertEqual(normalized["prompt_tokens"], 0)
        self.assertEqual(normalized["completion_tokens"], 2)
        self.assertEqual(normalized["total_tokens"], 0)
        self.assertEqual(normalized["prompt_tokens_details"]["cached_tokens"], 0)
        self.assertEqual(normalize_usage({"prompt_tokens_details": []})["prompt_tokens_details"], {})

        with LocalAPIServer(status=400, error_text="provider error details") as server:
            with self.assertRaises(httpx.HTTPStatusError) as raised:
                list(stream_chat("key", server.base_url, "demo", [], "session"))
        self.assertIn("provider error details", raised.exception.response.text)

    def test_api_selection_updates_current_api(self):
        self.configure_api("http://127.0.0.1:1", "first")
        self.config.add_api("second", "http://127.0.0.1:2", "second-key")
        dialog = SettingsDialog()
        self.addCleanup(dialog.deleteLater)
        dialog.api_list.setCurrentRow(1)
        self.assertEqual(dialog.api_list.currentItem().text(), "second")
        self.assertEqual(self.config.get_current_api()["name"], "second")
        dialog.close()

    def test_keys_are_migrated_out_of_config(self):
        api_id = self.config.add_api("secure", "https://example.com", "secret-value")
        with open(config_manager.CONFIG_PATH, encoding="utf-8") as file:
            self.assertNotIn("secret-value", file.read())
        self.assertEqual(self.secrets[api_id], "secret-value")
        self.assertEqual(self.config.get_current_api()["api_key"], "secret-value")

        legacy = {
            "theme": "Dark",
            "current_theme": "default_dark",
            "current_api_id": "legacy-id",
            "apis": [{"id": "legacy-id", "name": "legacy", "base_url": "https://example.com", "api_key": "legacy-secret", "models": []}],
        }
        with open(config_manager.CONFIG_PATH, "w", encoding="utf-8") as file:
            json.dump(legacy, file)
        ConfigManager._instance = None
        migrated = ConfigManager()
        self.assertEqual(self.secrets["legacy-id"], "legacy-secret")
        self.assertEqual(migrated.get_current_api()["api_key"], "legacy-secret")
        with open(config_manager.CONFIG_PATH, encoding="utf-8") as file:
            self.assertNotIn("legacy-secret", file.read())

    def test_system_prompt_and_regenerate_use_correct_messages(self):
        with LocalAPIServer() as server:
            self.configure_api(server.base_url)
            view = ChatView()
            self.addCleanup(close_chat, view)
            session_id = session_dao.create_session()
            view.load_session(session_id)
            view.sysPromptBox.setPlainText("SYSTEM_MARKER")
            view.inputBox.setPlainText("first question")
            view._on_send_clicked()
            wait_until(lambda: len(server.requests) == 1 and not view.session_states[session_id]["is_generating"])

            first_messages = server.requests[0]["payload"]["messages"]
            self.assertEqual([message["role"] for message in first_messages], ["system", "user"])
            self.assertEqual(first_messages[0]["content"], "SYSTEM_MARKER")

            view._handle_regenerate()
            wait_until(lambda: len(server.requests) == 2 and not view.session_states[session_id]["is_generating"])
            regenerated = server.requests[1]["payload"]["messages"]
            self.assertEqual([message["role"] for message in regenerated], ["system", "user"])
            self.assertEqual(regenerated[-1]["content"], "first question")
            self.assertNotIn("answer-1", json.dumps(regenerated))
            stored = message_dao.get_messages_by_session(session_id)
            self.assertEqual([message["role"] for message in stored], ["user", "assistant"])
            self.assertEqual(stored[-1]["content"], "answer-2")

    def test_delete_active_session_stops_worker_and_prevents_orphans(self):
        with LocalAPIServer(delay=0.8) as server:
            self.configure_api(server.base_url)
            window = MainWindow()
            self.addCleanup(close_window, window)
            window.sidebar.newChatBtn.click()
            view = window.chat_view
            session_id = view.current_session_id
            view.inputBox.setPlainText("delete while streaming")
            view._on_send_clicked()
            wait_until(lambda: view.session_states[session_id]["full_text"] == "answer-1")
            worker = view.session_states[session_id]["worker"]

            window.sidebar._delete_session(session_id)
            self.assertFalse(view.current_session_id)
            self.assertNotIn(session_id, view.session_states)
            self.assertFalse(worker.isRunning())
            self.assertEqual(window.sidebar.chatList.count(), 0)
            deadline = time.monotonic() + 1
            wait_until(lambda: time.monotonic() >= deadline)
            conn = get_connection()
            count = conn.execute("SELECT COUNT(*) FROM messages WHERE session_id = ?", (session_id,)).fetchone()[0]
            conn.close()
            self.assertEqual(count, 0)

    def test_auto_created_session_appears_in_sidebar(self):
        with LocalAPIServer() as server:
            self.configure_api(server.base_url)
            window = MainWindow()
            self.addCleanup(close_window, window)
            window.chat_view.inputBox.setPlainText("create a session")
            window.chat_view._on_send_clicked()
            session_id = window.chat_view.current_session_id
            self.assertIsNotNone(session_id)
            self.assertEqual(window.sidebar.chatList.count(), 1)
            wait_until(lambda: not window.chat_view.session_states[session_id]["is_generating"])

    def test_system_prompt_is_flushed_before_session_switch(self):
        view = ChatView()
        self.addCleanup(close_chat, view)
        first = session_dao.create_session()
        second = session_dao.create_session()
        view.load_session(first)
        view.sysPromptBox.setPlainText("PROMPT_A")
        view.load_session(second)
        self.assertEqual(session_dao.get_session_by_id(first)["system_prompt"], "PROMPT_A")
        self.assertEqual(session_dao.get_session_by_id(second)["system_prompt"], "")

    def test_stop_fallback_restores_send_button(self):
        view = ChatView()
        self.addCleanup(close_chat, view)
        session_id = session_dao.create_session()
        view.load_session(session_id)
        state = view._get_default_state()
        state["stop_requested"] = True
        view.session_states[session_id] = state
        view.sendBtn.setEnabled(False)
        view._force_reset_ui_after_stop(session_id, None)
        self.assertTrue(view.sendBtn.isEnabled())
        self.assertFalse(state["stop_requested"])

    def test_foreign_keys_message_order_and_replacement(self):
        session_id = session_dao.create_session()
        message_dao.add_message(session_id, "user", "question")
        message_dao.add_message(session_id, "assistant", "old")
        message_dao.replace_last_assistant(session_id, "new")
        messages = message_dao.get_messages_by_session(session_id)
        self.assertEqual([message["role"] for message in messages], ["user", "assistant"])
        self.assertEqual(messages[-1]["content"], "new")
        with self.assertRaises(sqlite3.IntegrityError):
            message_dao.add_message("missing-session", "assistant", "orphan")

    def test_invalid_configuration_does_not_clear_input(self):
        view = ChatView()
        self.addCleanup(close_chat, view)
        view.inputBox.setPlainText("keep this text")
        with patch.object(QMessageBox, "warning"):
            view._on_send_clicked()
        self.assertEqual(view.inputBox.toPlainText(), "keep this text")

    def test_shutdown_persists_partial_response(self):
        view = ChatView()
        session_id = session_dao.create_session()
        view.load_session(session_id)
        state = view._get_default_state()
        state["is_generating"] = True
        state["full_text"] = "partial response"
        view.session_states[session_id] = state
        view.shutdown()
        messages = message_dao.get_messages_by_session(session_id)
        self.assertEqual(messages, [{"role": "assistant", "content": "partial response"}])
        view.close()
        view.deleteLater()

    def test_webengine_treats_untrusted_fields_as_text(self):
        view = ChatView()
        self.addCleanup(close_chat, view)
        view.show()
        wait_until(lambda: view.is_page_loaded)
        payload = "<img src=x onerror=\"document.body.dataset.reviewXss='executed'\">"
        usage = json.dumps({"prompt_tokens": payload, "completion_tokens": 1, "total_tokens": 2})
        error = json.dumps(payload)
        user = json.dumps(payload)
        run_js(view, f"addUserMessage({user}); startAiMessage(); finishAiMessage(); showMeta({usage}, 1.0, 0); startAiMessage(); showError({error});")
        QTest.qWait(300)
        self.assertEqual(run_js(view, "document.body.dataset.reviewXss || 'not-executed'"), "not-executed")
        self.assertEqual(run_js(view, "document.querySelectorAll('.message img').length"), 0)
        self.assertIn(payload, run_js(view, "document.querySelector('.ai-message:last-child .bubble').textContent"))
        self.assertIn("0 提示", run_js(view, "document.querySelector('.usage-info').textContent"))

    def test_flush_interval_adapts_to_response_length(self):
        view = ChatView()
        self.addCleanup(close_chat, view)
        state = view._get_default_state()
        state["full_text"] = "x" * 100
        view._update_flush_interval(state)
        self.assertEqual(view.flush_timer.interval(), 50)
        state["full_text"] = "x" * 10000
        view._update_flush_interval(state)
        self.assertEqual(view.flush_timer.interval(), 120)
        state["full_text"] = "x" * 40000
        view._update_flush_interval(state)
        self.assertEqual(view.flush_timer.interval(), 250)


def tearDownModule():
    QApplication.processEvents()
    shutil.rmtree(TEST_DATA_DIR, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
