"""Immediate alerts: config-driven trigger rules, delivered by email/terminal.

A rule fires when EVERY group in `all_of` matches (each group is an
any-of list of terms; '*' wildcards allowed), e.g.

  - name: nyrstar-insolvency
    all_of:
      - [Nyrstar, "Hobart smelter"]
      - ["liquidat*", "administrat*", "receiver*", insolven*]
"""

import json
import smtplib
from email.message import EmailMessage

from tasmon.config import Config, compile_terms
from tasmon.ingest import now_iso


class AlertEngine:
    def __init__(self, cfg: Config, conn):
        self.cfg = cfg
        self.conn = conn
        self.rules = []
        for rule in cfg.alert_rules:
            self.rules.append({
                "name": rule["name"],
                "groups": [compile_terms(group) for group in rule["all_of"]],
            })

    def check_items(self, item_ids: list[int]) -> list[dict]:
        """Evaluate rules against newly ingested items; deliver on match."""
        fired = []
        for item_id in item_ids:
            row = self.conn.execute(
                "SELECT * FROM items WHERE id = ?", (item_id,)).fetchone()
            if not row:
                continue
            haystack = (row["title"] or "") + "\n" + (row["fulltext"] or "")
            for rule in self.rules:
                if all(any(p.search(haystack) for p in group)
                       for group in rule["groups"]):
                    already = self.conn.execute(
                        "SELECT 1 FROM alerts_sent WHERE item_id = ? AND rule = ?",
                        (item_id, rule["name"])).fetchone()
                    if already:
                        continue
                    self._deliver(rule["name"], dict(row))
                    self.conn.execute(
                        "INSERT INTO alerts_sent (item_id, rule, sent_at, channel) "
                        "VALUES (?, ?, ?, ?)",
                        (item_id, rule["name"], now_iso(), self.cfg.alert_channel))
                    self.conn.commit()
                    fired.append({"rule": rule["name"], "item": dict(row)})
        return fired

    def _deliver(self, rule_name: str, item: dict):
        subject = f"[tasmon ALERT: {rule_name}] {item['title']}"
        body = (f"Rule: {rule_name}\n"
                f"Title: {item['title']}\n"
                f"Source: {item['source_name']}\n"
                f"Published: {item['published_at'] or 'unknown'}\n"
                f"Link: {item['url']}\n")
        wl = json.loads(item["watchlist_hits"] or "[]")
        if wl:
            body += "Watchlist: " + ", ".join(h["entity"] for h in wl) + "\n"
        print(f"\n*** ALERT ({rule_name}) ***\n{body}")
        if self.cfg.alert_channel == "email":
            try:
                send_email(self.cfg, subject, body)
            except Exception as e:  # noqa: BLE001
                print(f"!! alert email failed ({e}); alert shown above only")


def send_email(cfg: Config, subject: str, body: str):
    email_cfg = cfg.email
    if not email_cfg.get("smtp_host"):
        raise RuntimeError("email not configured (email.smtp_host missing)")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = email_cfg["from"]
    msg["To"] = email_cfg["to"]
    msg.set_content(body)
    port = int(email_cfg.get("smtp_port", 587))
    host = email_cfg["smtp_host"]
    password = cfg.smtp_password()
    if email_cfg.get("use_ssl"):
        server = smtplib.SMTP_SSL(host, port, timeout=30)
    else:
        server = smtplib.SMTP(host, port, timeout=30)
    try:
        if not email_cfg.get("use_ssl"):
            server.starttls()
        if email_cfg.get("username") and password:
            server.login(email_cfg["username"], password)
        server.send_message(msg)
    finally:
        server.quit()
