"""SMTP STARTTLS email verification delivery. No vendor account baked into code.

Tokens are kept out of logs and HTTP JSON. URL uses a fragment so the token
is not transmitted to the web server by the initial page GET.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage
from urllib.parse import quote


class SMTPVerificationSender:
    def __init__(self, *, host, port, username, password, sender, origin):
        if (not host or any(c.isspace() for c in host) or not host.replace("-", "").replace(".", "").isalnum()
                or not isinstance(port, int) or port < 1 or port > 65535
                or not username or not password or not sender
                or any(c in sender for c in "\r\n") or "@" not in sender
                or not origin.startswith(("https://", "http://"))):
            raise ValueError("SMTP requires a trusted host, STARTTLS credentials, From address and origin")
        self.host, self.port, self.username = host, port, username
        self._password = password
        self.sender, self.origin = sender, origin.rstrip("/")

    @classmethod
    def from_environment(cls, *, origin):
        host = os.environ.get("ARENA_SMTP_HOST", "").strip()
        port_text = os.environ.get("ARENA_SMTP_PORT", "587")
        if not port_text.isdigit():
            raise ValueError("ARENA_SMTP_PORT must be numeric")
        return cls(host=host, port=int(port_text),
                   username=os.environ.get("ARENA_SMTP_USER", ""),
                   password=os.environ.get("ARENA_SMTP_PASSWORD", ""),
                   sender=os.environ.get("ARENA_SMTP_FROM", ""), origin=origin)

    def _deliver(self, recipient, token, *, purpose):
        if (not isinstance(recipient, str) or "@" not in recipient or
                any(c in recipient for c in "\r\n<>") or len(recipient) > 254):
            raise ValueError("Invalid email recipient")
        if not isinstance(token, str) or len(token) != 43:
            raise ValueError("Invalid delivery token")
        if purpose not in ("verify-email", "reset-password"):
            raise ValueError("Unsupported mail purpose")
        address = self.origin + "/#" + purpose + "=" + quote(token, safe="")
        message = EmailMessage()
        message["From"], message["To"] = self.sender, recipient
        message["Subject"] = ("NEON ARENA — Verify your Player email" if purpose == "verify-email"
                              else "NEON ARENA — Reset your Player password")
        if purpose == "verify-email":
            body = "Activate your Player account within 24 hours:"
        else:
            body = "Reset your Player password within 30 minutes:"
        message.set_content(body + "\n\n" + address +
                            "\n\nIf you did not request this, ignore this message.\n")
        # TLS certificate verification required. No fallback to plaintext SMTP.
        with smtplib.SMTP(self.host, self.port, timeout=10) as smtp:
            smtp.ehlo()
            smtp.starttls(context=ssl.create_default_context())
            smtp.ehlo()
            smtp.login(self.username, self._password)
            smtp.send_message(message)

    def send(self, recipient, token):
        self._deliver(recipient, token, purpose="verify-email")

    def send_password_reset(self, recipient, token):
        self._deliver(recipient, token, purpose="reset-password")
