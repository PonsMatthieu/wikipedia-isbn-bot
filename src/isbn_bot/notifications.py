import smtplib
import ssl
from email.message import EmailMessage


def send_digest(settings, state, new_ids: list[int], metrics: dict):
    if not settings.mail_host or not settings.mail_to:
        return False
    pending = state.db.execute("SELECT * FROM alerts WHERE sent_at IS NULL ORDER BY id LIMIT 30").fetchall()
    if not new_ids and not pending:
        return False
    if not settings.mail_from:
        raise ValueError("MAIL_FROM est obligatoire pour les notifications")
    message = EmailMessage()
    message["Subject"] = f"Bot ISBN : {len(new_ids)} proposition(s), {len(pending)} alerte(s)"
    message["From"] = settings.mail_from
    message["To"] = settings.mail_to
    content = ["Rapport du bot ISBN", "", str(metrics), ""]
    for finding_id in new_ids[:30]:
        row = state.finding(finding_id)
        import json
        page, finding = json.loads(row["page_json"]), json.loads(row["finding_json"])
        content.extend([f"Proposition #{finding_id} : {page['title']}",
                        f"ISBN actuel : {finding['field']['raw_value']}",
                        f"ISBN proposé : {finding.get('candidate_isbn') or 'aucun'}", row["diff"], ""])
    content.extend(f"{a['code']} : {a['message']}" for a in pending)
    message.set_content("\n".join(content))
    ctx = ssl.create_default_context()
    constructor = smtplib.SMTP_SSL if settings.mail_security == "ssl" else smtplib.SMTP
    kwargs = {"timeout": 30}
    if settings.mail_security == "ssl":
        kwargs["context"] = ctx
    with constructor(settings.mail_host, settings.mail_port, **kwargs) as smtp:
        if settings.mail_security == "starttls":
            smtp.ehlo()
            smtp.starttls(context=ctx)
            smtp.ehlo()
        if settings.mail_user:
            smtp.login(settings.mail_user, settings.mail_password)
        smtp.send_message(message)
    from .state import now
    with state.db:
        state.db.executemany("UPDATE alerts SET sent_at=? WHERE id=?", [(now(), a["id"]) for a in pending])
    return True
