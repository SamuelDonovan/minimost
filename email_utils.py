import logging
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

log = logging.getLogger(__name__)


def send_reset_email(to_addr: str, username: str, reset_link: str) -> bool:
    host     = os.environ.get("SMTP_HOST", "")
    port     = int(os.environ.get("SMTP_PORT", "587"))
    user     = os.environ.get("SMTP_USER", "")
    password = os.environ.get("SMTP_PASS", "")
    from_addr = os.environ.get("SMTP_FROM", user)

    if not host or not user:
        return False

    text_body = f"""Hi {username},

Someone requested a password reset for your MiniMost account.

If this was you, click the link below. It will delete your account so you can
sign up again with a new password — your message history will be preserved.

{reset_link}

This link expires in 1 hour. If you didn't request this, you can ignore this email.
"""

    html_body = f"""
<div style="font-family:sans-serif;max-width:480px;margin:auto;color:#ddd;background:#1e1e1e;padding:32px;border-radius:8px">
  <h2 style="margin:0 0 8px 0;font-size:1.4em">MiniMost</h2>
  <p>Hi <strong>{username}</strong>,</p>
  <p>Someone requested a password reset for your MiniMost account.</p>
  <p>Click the button below to delete your account so you can sign up again
     with a new password. Your message history will be preserved.</p>
  <p style="margin:24px 0">
    <a href="{reset_link}"
       style="background:#007acc;color:#fff;padding:10px 20px;border-radius:4px;text-decoration:none;font-size:14px">
      Reset my account
    </a>
  </p>
  <p style="font-size:12px;color:#888">
    This link expires in 1 hour. If you didn't request this, you can safely ignore this email.
  </p>
  <p style="font-size:12px;color:#666;word-break:break-all">
    Or copy this link: {reset_link}
  </p>
</div>
"""

    msg = MIMEMultipart("alternative")
    msg["Subject"] = "MiniMost – Reset your account"
    msg["From"]    = from_addr
    msg["To"]      = to_addr
    msg.attach(MIMEText(text_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port) as smtp:
                smtp.login(user, password)
                smtp.sendmail(from_addr, to_addr, msg.as_string())
        else:
            with smtplib.SMTP(host, port) as smtp:
                smtp.ehlo()
                smtp.starttls()
                smtp.login(user, password)
                smtp.sendmail(from_addr, to_addr, msg.as_string())
        log.info("Reset email sent to %s", to_addr)
        return True
    except Exception as e:
        log.error("Failed to send reset email to %s: %s", to_addr, e)
        return False
