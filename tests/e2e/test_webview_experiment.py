"""End-to-end run of the WhatsApp webview experiment (experiments/whatsapp-webview) against a fake bridge.

The backend runs as a real process and its page in a real headless Chromium, as the captain would open it from the
message's button. It proves our side of the round trip, not how WhatsApp presents the page: that needs a person.

  1. `server.py open` sends the opening message through the bridge's experiment route, to the recipient given at
     start; the page shows the run id, and «Guardar» stores the value and the bot confirms in that chat, quoting
     the opening message. The page reports the confirmation once the bridge took it.
  2. The page's retry of the same submission is processed once; another submission on a saved form is refused.
  3. A wrong capability, the capability of another session and an expired session store nothing.
  4. With the bridge down after «Guardar», the data is saved and the confirmation is pending; it is delivered,
     once, when the bridge is back.
  5. A page closed without «Guardar» leaves only its auxiliary events: no submission and no message from the bot.
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

import pytest
import requests

from fake_servers import FakeWhatsApp

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
EXPERIMENT = REPO / "experiments" / "whatsapp-webview"
NODE = shutil.which("node")
RECIPIENT = "593990000001"
CHAT = f"{RECIPIENT}@s.whatsapp.net"


def _chromium() -> str | None:
    if found := os.environ.get("E2E_CHROMIUM") or shutil.which("chromium") or shutil.which("google-chrome"):
        return found
    cache = Path.home() / ".cache" / "ms-playwright"
    shells = sorted(cache.glob("chromium_headless_shell-*/chrome-*/chrome-headless-shell"))
    return str(shells[-1]) if shells else None


CHROMIUM = _chromium()


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


class Browser:
    def __init__(self):
        self._proc = subprocess.Popen([NODE, str(HERE / "browser.mjs"), CHROMIUM], stdin=subprocess.PIPE,
                                      stdout=subprocess.PIPE, text=True)

    def _call(self, **cmd):
        self._proc.stdin.write(json.dumps(cmd) + "\n")
        self._proc.stdin.flush()
        answer = json.loads(self._proc.stdout.readline())
        assert "error" not in answer, answer
        return answer

    def open(self, url: str) -> str:
        return self._call(op="open", url=url)["id"]

    def eval(self, page: str, expr: str):
        return self._call(op="eval", id=page, expr=expr)["value"]

    def wait_text(self, page: str, selector: str, needle: str, timeout: float = 20) -> str:
        end = time.time() + timeout
        text = ""
        while time.time() < end:
            text = self.eval(page, f"document.querySelector({json.dumps(selector)})?.textContent || ''")
            if needle in text:
                return text
            time.sleep(0.2)
        raise AssertionError(f"{selector} never said «{needle}»; it says «{text}»")

    def fill_and_save(self, page: str, value: str) -> None:
        self.wait_text(page, "#run", "r")
        self.eval(page, "new Promise(r => { const t = setInterval(() => { if (!document.querySelector('#form').hidden)"
                        " { clearInterval(t); r(true); } }, 50); })")
        self.eval(page, f"document.querySelector('#value').value = {json.dumps(value)};"
                        "document.querySelector('#save').click(); true")

    def close(self, page: str) -> None:
        self._call(op="close", id=page)

    def quit(self):
        self._proc.stdin.close()
        self._proc.wait(timeout=10)


@pytest.mark.skipif(not NODE or not CHROMIUM, reason="needs Node and a Chromium")
def test_webview_experiment(tmp_path):
    state = tmp_path / "state"
    port, admin_port = _free_port(), _free_port()
    public = f"http://127.0.0.1:{port}"
    stand_in = tmp_path / "bridge.js"
    stand_in.write_text("// stand-in\n")

    with FakeWhatsApp(stand_in) as bridge:
        server = subprocess.Popen(
            [sys.executable, str(EXPERIMENT / "server.py"), "--state", str(state), "serve", "--public-url", public,
             "--recipient", RECIPIENT, "--bridge", bridge.base, "--port", str(port), "--admin-port", str(admin_port)],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        browser = Browser()
        try:
            assert "public" in server.stdout.readline()

            def open_session(variant="cta_url", ttl=600) -> tuple[str, str]:
                since = len(bridge.sent)
                out = subprocess.run([sys.executable, str(EXPERIMENT / "server.py"), "--state", str(state), "open",
                                      "--variant", variant, "--ttl-seconds", str(ttl)],
                                     capture_output=True, text=True, check=True).stdout
                opened = json.loads(out)
                [sent] = [m for m in bridge.sent[since:] if m["path"] == "experiment/webview/send"]
                assert sent["chatId"] == CHAT and sent["variant"] == variant
                assert opened["sessionId"] in sent["text"] and sent["messageId"] == opened["messageId"]
                assert "#c=" not in out, "the capability never leaves the server but in the message"
                return opened["sessionId"], sent["url"]

            def confirmations(run_id: str) -> list[dict]:
                return [m for m in bridge.messages_to(CHAT) if run_id in m["message"]]

            def capability(url: str) -> str:
                return urlsplit(url).fragment.removeprefix("c=")

            def api(run_id: str, action: str, **body):
                return requests.post(f"{public}/api/demo/sessions/{run_id}/{action}", json=body, timeout=10)

            # 1. the round trip
            run, url = open_session()
            assert url.startswith(f"{public}/demo?s={run}#c=")
            page = browser.open(url)
            assert browser.wait_text(page, "#run", run) == run
            assert browser.eval(page, "location.hash") == "", "the page drops the capability from the address bar"
            browser.fill_and_save(page, "hola desde la prueba")
            browser.wait_text(page, "#status", "El bot ya te confirmó en el chat")
            [confirmation] = confirmations(run)
            assert "hola desde la prueba" in confirmation["message"]
            assert confirmation["replyTo"] == bridge.sent[0]["messageId"], "it answers the opening message"

            # 2. retries: the same submission once, another one refused
            submission = browser.eval(page, f"sessionStorage.getItem('sub:{run}')")
            again = api(run, "submit", capability=capability(url), submissionId=submission, value="hola desde la prueba")
            assert again.status_code == 200 and again.json()["duplicate"] is True
            other = api(run, "submit", capability=capability(url), submissionId="otra-submission-123", value="x")
            assert other.status_code == 409
            time.sleep(3)  # a worker round
            assert len(confirmations(run)) == 1

            # 3. what stores nothing
            run_b, url_b = open_session()
            assert api(run_b, "submit", capability="wrong" * 8, submissionId="sub-wrong-000", value="x").status_code == 403
            assert api(run_b, "submit", capability=capability(url), submissionId="sub-cross-000", value="x").status_code == 403
            run_c, url_c = open_session(ttl=1)
            time.sleep(1.5)
            page_c = browser.open(url_c)
            browser.wait_text(page_c, "#status", "caducó")
            assert api(run_c, "submit", capability=capability(url_c), submissionId="sub-late-0000",
                       value="tarde").status_code == 410
            status_b = requests.get(f"{public}/api/demo/sessions/{run_b}/status",
                                    headers={"Authorization": f"Bearer {capability(url_b)}"}, timeout=10).json()
            assert status_b["saved"] is False

            # 4. the bridge falls after «Guardar»
            run_d, url_d = open_session()
            bridge.failing.add("send")
            page_d = browser.open(url_d)
            browser.fill_and_save(page_d, "con el puente caído")
            browser.wait_text(page_d, "#status", "Confirmación del bot pendiente")
            time.sleep(5)  # the worker keeps trying while the bridge is down
            assert confirmations(run_d) == []
            bridge.failing.discard("send")
            browser.wait_text(page_d, "#status", "El bot ya te confirmó en el chat", timeout=20)
            time.sleep(3)
            assert len(confirmations(run_d)) == 1
            report = subprocess.run([sys.executable, str(EXPERIMENT / "server.py"), "--state", str(state), "report"],
                                    capture_output=True, text=True, check=True).stdout
            line = next(l for l in report.splitlines() if l.startswith(run_d))
            assert "saved=yes" in line and "confirmation=sent after" in line and "after 1 attempt" not in line

            # 5. closed without «Guardar»
            run_e, url_e = open_session()
            page_e = browser.open(url_e)
            browser.wait_text(page_e, "#run", run_e)
            browser.eval(page_e, "document.querySelector('#value').value = 'nunca guardado'; true")
            browser.close(page_e)
            time.sleep(3)
            line = next(l for l in subprocess.run(
                [sys.executable, str(EXPERIMENT / "server.py"), "--state", str(state), "report"],
                capture_output=True, text=True, check=True).stdout.splitlines() if l.startswith(run_e))
            assert "load" in line and "pagehide" in line, line
            assert "saved=no" in line and "confirmation=-" in line
            assert confirmations(run_e) == []
        finally:
            browser.quit()
            server.terminate()
            logs = server.communicate(timeout=10)[1]
    assert "#c=" not in logs and "capability" not in logs.lower(), "the server log never holds a capability"
