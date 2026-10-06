import json
from dataclasses import replace

from isbn_bot.cli import main
from isbn_bot.notifications import send_digest


def test_digest_uses_tls_and_marks_only_sent_alerts(settings, state, monkeypatch):
    interactions = []
    class SMTP:
        def __init__(self, host, port, **kwargs):
            interactions.append(("connect", host, port))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def ehlo(self):
            pass
        def starttls(self, **kwargs):
            interactions.append(("tls",))
        def login(self, user, password):
            interactions.append(("login", user))
        def send_message(self, message):
            interactions.append(("send", str(message)))
    monkeypatch.setattr("isbn_bot.notifications.smtplib.SMTP", SMTP)
    settings = replace(settings, mail_host="smtp.example.org", mail_from="bot@example.org", mail_to="operator@example.org",
                       mail_user="bot", mail_password="SECRET")
    state.alert("TEST", "Pas de secret dans ce message")
    assert send_digest(settings, state, [], {"test": True})
    assert any(i[0] == "tls" for i in interactions)
    assert "SECRET" not in next(i[1] for i in interactions if i[0] == "send")
    assert state.db.execute("SELECT sent_at FROM alerts").fetchone()[0]


def test_demo_command_runs_without_network_or_credentials(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("La démo doit rester hors ligne")
    monkeypatch.setattr("requests.Session.request", forbidden)
    assert main(["demo", "--output", str(tmp_path / "demo")]) == 0
    data = json.loads((tmp_path / "demo/report.json").read_text())
    assert data["demo"] and data["cases"][0]["diff"]
