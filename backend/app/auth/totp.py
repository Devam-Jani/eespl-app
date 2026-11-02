"""Two-step login with an authenticator app (TOTP, RFC 6238: 6 digits, 30 seconds, SHA-1, as
Google and Microsoft Authenticator expect). The secret is kept encrypted with DATA_KEY; the QR code
is drawn on our server (reportlab), so the secret never goes to a third party."""

import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote

from cryptography.fernet import Fernet, InvalidToken

from app import branding
from app.config import settings

ISSUER = branding.PRODUCT_NAME
STEP = 30


def new_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def _fernet() -> Fernet:
    raw = settings.data_key.get_secret_value() if settings.data_key else settings.jwt_secret
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(("totp:" + raw).encode()).digest()))


def seal(secret: str) -> str:
    return _fernet().encrypt(secret.encode()).decode()


def unseal(sealed: str) -> str | None:
    try:
        return _fernet().decrypt(sealed.encode()).decode()
    except InvalidToken:
        return None


def code_at(secret: str, at: float, step: int = STEP) -> str:
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", int(at // step)), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    value = struct.unpack(">I", digest[offset : offset + 4])[0] & 0x7FFFFFFF
    return f"{value % 1_000_000:06d}"


def verify(secret: str, code: str, at: float | None = None) -> bool:
    """The code of now, or of the 30 seconds before or after (a phone's clock may drift)."""
    code = (code or "").strip().replace(" ", "")
    if not code.isdigit() or len(code) != 6:
        return False
    at = time.time() if at is None else at
    return any(hmac.compare_digest(code_at(secret, at + d * STEP), code) for d in (-1, 0, 1))


def uri(secret: str, account: str) -> str:
    return f"otpauth://totp/{quote(ISSUER)}:{quote(account)}?secret={secret}&issuer={quote(ISSUER)}&digits=6&period={STEP}"


def qr_svg(text: str) -> str:
    """The QR code as SVG, drawn here."""
    from reportlab.graphics import renderSVG  # noqa: PLC0415
    from reportlab.graphics.barcode.qr import QrCodeWidget  # noqa: PLC0415
    from reportlab.graphics.shapes import Drawing  # noqa: PLC0415

    w = QrCodeWidget(text)
    x1, y1, x2, y2 = w.getBounds()
    d = Drawing(220, 220, transform=[220.0 / (x2 - x1), 0, 0, 220.0 / (y2 - y1), 0, 0])
    d.add(w)
    return renderSVG.drawToString(d)
