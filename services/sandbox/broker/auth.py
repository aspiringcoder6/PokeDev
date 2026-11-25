"""
Minimal authentication for the Sandbox Kit broker.

- Users stored in broker/auth.db (SQLite)
- Passwords hashed with PBKDF2-HMAC-SHA256 (stdlib only)
- Session tokens: HMAC-SIGNED stateless tokens (payload.signature),
  12h validity, stored client-side and sent as Bearer header.
- First registered user becomes ADMIN, everyone else USER.
- Registration restricted to Viettel emails (@viettel.com.vn).
"""

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import smtplib
import sqlite3
import time
from email.mime.text import MIMEText
from typing import Optional, Tuple

AUTH_DB_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "auth.db"
)
ALLOWED_EMAIL_DOMAIN = "@viettel.com.vn"
TOKEN_TTL_SECONDS = 12 * 3600
CODE_TTL_SECONDS = 10 * 60
CODE_MAX_ATTEMPTS = 5

# Signing secret: persists in auth.db meta so restarts keep tokens valid
_SECRET: Optional[bytes] = None


def _get_secret() -> bytes:
    global _SECRET
    if _SECRET:
        return _SECRET
    conn = _conn()
    conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT)")
    row = conn.execute("SELECT value FROM meta WHERE key='secret'").fetchone()
    if row:
        _SECRET = row[0].encode()
    else:
        _SECRET = os.urandom(32).hex().encode()
        conn.execute("INSERT INTO meta (key, value) VALUES ('secret', ?)", (_SECRET.decode(),))
        conn.commit()
    conn.close()
    return _SECRET


def _conn() -> sqlite3.Connection:
    conn = sqlite3.connect(AUTH_DB_PATH)
    conn.execute(
        """CREATE TABLE IF NOT EXISTS users (
               email TEXT PRIMARY KEY,
               password_hash TEXT NOT NULL,
               role TEXT NOT NULL DEFAULT 'user',
               created_at TEXT NOT NULL,
               verified INTEGER NOT NULL DEFAULT 0
           )"""
    )
    # Migration for pre-verification databases
    try:
        conn.execute("ALTER TABLE users ADD COLUMN verified INTEGER NOT NULL DEFAULT 0")
        conn.execute("UPDATE users SET verified = 1")  # legacy accounts trusted
    except sqlite3.OperationalError:
        pass
    conn.execute(
        """CREATE TABLE IF NOT EXISTS verifications (
               email TEXT PRIMARY KEY,
               code_hash TEXT NOT NULL,
               expires_at REAL NOT NULL,
               attempts INTEGER NOT NULL DEFAULT 0
           )"""
    )
    return conn


def _hash_password(password: str, salt: bytes) -> str:
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 390_000)
    return salt.hex() + "$" + digest.hex()


def _verify_password(password: str, stored: str) -> bool:
    try:
        salt_hex, hash_hex = stored.split("$", 1)
        candidate = hashlib.pbkdf2_hmac(
            "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), 390_000
        )
        return hmac.compare_digest(candidate.hex(), hash_hex)
    except (ValueError, TypeError):
        return False


def validate_email(email: str) -> Optional[str]:
    """Returns an error message, or None when the email is acceptable."""
    if not email or "@" not in email:
        return "Email is required."
    email = email.strip().lower()
    if not email.endswith(ALLOWED_EMAIL_DOMAIN):
        return f"Only {ALLOWED_EMAIL_DOMAIN} emails are allowed."
    local = email.split("@")[0]
    if not local or any(ch in local for ch in " /\\;:"):
        return "Invalid email format."
    return None


def register_user(email: str, password: str) -> Tuple[bool, str, Optional[dict]]:
    """Creates an UNVERIFIED user + sends a verification code.
    Returns (ok, message, info). info['verified'] = False means check email."""
    email = email.strip().lower()
    err = validate_email(email)
    if err:
        return False, err, None
    if not password or len(password) < 8:
        return False, "Password must be at least 8 characters.", None

    conn = _conn()
    try:
        existing = conn.execute(
            "SELECT email, verified FROM users WHERE email = ?", (email,)
        ).fetchone()
        if existing and existing[1]:
            return False, "This email is already registered.", None

        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        role = "admin" if count == 0 else "user"

        if not existing:
            salt = os.urandom(16)
            conn.execute(
                "INSERT INTO users (email, password_hash, role, created_at, verified) VALUES (?, ?, ?, ?, 0)",
                (email, _hash_password(password, salt), role, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
            )
        conn.commit()
        # New or unverified registration (re-)sends the code
        send_ok, send_msg = issue_verification_code(email)
        info = {"email": email, "role": role, "verified": False}
        if not send_ok:
            return True, "Account created but the verification email could NOT be sent (SMTP not configured).", info
        return True, "Verification code sent to your email (valid 10 minutes).", info
    finally:
        conn.close()


# --- Email verification ------------------------------------------------------

def issue_verification_code(email: str) -> Tuple[bool, str]:
    """Generate a 6-digit code, store its hash, email it. Returns (sent, message)."""
    email = (email or "").strip().lower()
    code = f"{secrets.randbelow(1_000_000):06d}"
    code_hash = hashlib.sha256((code + _get_secret().decode()).encode()).hexdigest()
    expires = time.time() + CODE_TTL_SECONDS

    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO verifications (email, code_hash, expires_at, attempts)
               VALUES (?, ?, ?, 0)
               ON CONFLICT(email) DO UPDATE SET
                 code_hash = excluded.code_hash,
                 expires_at = excluded.expires_at,
                 attempts = 0""",
            (email, code_hash, expires),
        )
        conn.commit()
    finally:
        conn.close()

    sent = _send_email(
        email,
        "vAiPlatform Sandbox Manager - Ma xac thuc",
        f"Ma xac thuc cua ban la: {code}\n\nMa co hieu luc 10 phut.\n"
        f"Neu ban khong yeu cau ma nay, bo qua email nay.",
    )
    if sent:
        return True, "sent"
    # Dev fallback: no SMTP configured -> expose code in broker log only
    logger = logging.getLogger("Broker")
    logger.info(f"[Auth] SMTP not configured. Verification code for {email}: {code}")
    return False, f"SMTP not configured. Dev code for {email}: {code} (see broker log)"


def verify_code(email: str, code: str) -> Tuple[bool, str, Optional[dict]]:
    """Check the 6-digit code; marks the user verified. Returns (ok, message, user)."""
    email = (email or "").strip().lower()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT code_hash, expires_at, attempts FROM verifications WHERE email = ?", (email,)
        ).fetchone()
        if not row:
            return False, "No verification pending. Register again.", None
        code_hash, expires_at, attempts = row
        if expires_at < time.time():
            conn.execute("DELETE FROM verifications WHERE email = ?", (email,))
            conn.commit()
            return False, "Code expired. Request a new one.", None
        if attempts >= CODE_MAX_ATTEMPTS:
            return False, "Too many attempts. Request a new code.", None

        candidate = hashlib.sha256(((code or "") + _get_secret().decode()).encode()).hexdigest()
        if not hmac.compare_digest(candidate, code_hash):
            conn.execute("UPDATE verifications SET attempts = attempts + 1 WHERE email = ?", (email,))
            conn.commit()
            return False, f"Wrong code ({CODE_MAX_ATTEMPTS - attempts - 1} attempts left).", None

        conn.execute("DELETE FROM verifications WHERE email = ?", (email,))
        conn.execute("UPDATE users SET verified = 1 WHERE email = ?", (email,))
        role_row = conn.execute("SELECT role FROM users WHERE email = ?", (email,)).fetchone()
        conn.commit()
        return True, "Email verified.", {"email": email, "role": role_row[0] if role_row else "user"}
    finally:
        conn.close()


def is_verified(email: str) -> bool:
    conn = _conn()
    try:
        row = conn.execute("SELECT verified FROM users WHERE email = ?", ((email or "").strip().lower(),)).fetchone()
        return bool(row and row[0])
    finally:
        conn.close()


def _send_email(to: str, subject: str, body: str) -> bool:
    """SMTP via env: SMTP_HOST, SMTP_PORT (587 STARTTLS / 465 SSL), SMTP_USER, SMTP_PASS, SMTP_FROM."""
    host = os.environ.get("SMTP_HOST")
    if not host:
        return False
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    from_addr = os.environ.get("SMTP_FROM", user or "noreply@viettel.com.vn")

    msg = MIMEText(body, "plain", "utf-8")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to

    try:
        if port == 465:
            with smtplib.SMTP_SSL(host, port, timeout=15) as smtp:
                if user and password:
                    smtp.login(user, password)
                smtp.sendmail(from_addr, [to], msg.as_string())
        else:
            with smtplib.SMTP(host, port, timeout=15) as smtp:
                smtp.starttls()
                if user and password:
                    smtp.login(user, password)
                smtp.sendmail(from_addr, [to], msg.as_string())
        return True
    except Exception as e:
        import logging
        logging.getLogger("Broker").warning(f"[Auth] SMTP send failed: {e}")
        return False


def verify_user(email: str, password: str) -> Optional[dict]:
    """Returns {'email', 'role'} when credentials match, else None."""
    email = (email or "").strip().lower()
    conn = _conn()
    try:
        row = conn.execute(
            "SELECT password_hash, role FROM users WHERE email = ?", (email,)
        ).fetchone()
        if not row or not _verify_password(password, row[0]):
            return None
        return {"email": email, "role": row[1]}
    finally:
        conn.close()


def user_count() -> int:
    conn = _conn()
    try:
        return conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
    finally:
        conn.close()


def upsert_external_user(email: str) -> dict:
    """Find-or-create a user from an external identity (GitHub).
    Emails verified by the provider are trusted (verified=1)."""
    email = (email or "").strip().lower()
    conn = _conn()
    try:
        row = conn.execute("SELECT role, verified FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            if not row[1]:
                conn.execute("UPDATE users SET verified = 1 WHERE email = ?", (email,))
                conn.commit()
            return {"email": email, "role": row[0]}
        count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        role = "admin" if count == 0 else "user"
        conn.execute(
            "INSERT INTO users (email, password_hash, role, created_at, verified) VALUES (?, ?, ?, ?, 1)",
            (email, "!external-oauth", role, time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())),
        )
        conn.commit()
        return {"email": email, "role": role}
    finally:
        conn.close()


# --- Session tokens (HMAC-signed, stateless) --------------------------------

def issue_token(email: str, role: str) -> str:
    payload = {
        "email": email,
        "role": role,
        "exp": int(time.time()) + TOKEN_TTL_SECONDS,
    }
    body = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    signature = hmac.new(_get_secret(), body.encode(), hashlib.sha256).hexdigest()
    return f"vai_{body}.{signature}"


def verify_token(token: str) -> Optional[dict]:
    """Returns {email, role} when valid and unexpired, else None."""
    if not token or not token.startswith("vai_"):
        return None
    token = token[4:]
    try:
        body, signature = token.rsplit(".", 1)
    except ValueError:
        return None
    expected = hmac.new(_get_secret(), body.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(expected, signature):
        return None
    padded = body + "=" * (-len(body) % 4)
    try:
        payload = json.loads(base64.urlsafe_b64decode(padded))
    except (ValueError, json.JSONDecodeError):
        return None
    if payload.get("exp", 0) < time.time():
        return None
    return {"email": payload.get("email"), "role": payload.get("role")}
