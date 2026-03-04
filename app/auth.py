import os
import secrets
from datetime import datetime, timedelta, timezone
from jose import jwt, JWTError
from passlib.context import CryptContext
from sqlalchemy.orm import Session
from sqlalchemy import select
from app.models import User, RefreshSession

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

JWT_SECRET = os.getenv("JWT_SECRET", "change_me")
ACCESS_TOKEN_MINUTES = int(os.getenv("ACCESS_TOKEN_MINUTES", "20"))
REFRESH_TOKEN_DAYS = int(os.getenv("REFRESH_TOKEN_DAYS", "14"))

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return pwd_context.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    return pwd_context.verify(password, password_hash)


def create_access_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(minutes=ACCESS_TOKEN_MINUTES)
    payload = {
        "typ": "access",
        "sub": str(user.id),
        "role": user.role.value,
        "exp": int(exp.timestamp()),
        "iat": int(now.timestamp()),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)


def create_refresh_token(db: Session, user: User) -> str:
    now = datetime.now(timezone.utc)
    exp = now + timedelta(days=REFRESH_TOKEN_DAYS)
    token_id = secrets.token_hex(32)
    payload = {
        "typ": "refresh",
        "sub": str(user.id),
        "tid": token_id,
        "exp": int(exp.timestamp()),
        "iat": int(now.timestamp()),
    }
    token = jwt.encode(payload, JWT_SECRET, algorithm=ALGORITHM)
    db.add(RefreshSession(user_id=user.id, token_id=token_id, expires_at=exp, revoked=False))
    db.flush()
    return token


def decode_token(token: str) -> dict:
    return jwt.decode(token, JWT_SECRET, algorithms=[ALGORITHM])


def get_user_by_email(db: Session, email: str) -> User | None:
    return db.execute(select(User).where(User.email == email)).scalars().first()


def get_user_by_id(db: Session, user_id: int) -> User | None:
    return db.get(User, user_id)


def validate_refresh_and_rotate(db: Session, refresh_token: str) -> tuple[User, str, str]:
    try:
        payload = decode_token(refresh_token)
        if payload.get("typ") != "refresh":
            raise JWTError()
        user_id = int(payload.get("sub"))
        token_id = str(payload.get("tid"))
    except Exception:
        raise

    sess = db.execute(select(RefreshSession).where(RefreshSession.token_id == token_id)).scalars().first()
    if sess is None or sess.revoked:
        raise ValueError("revoked")
    if sess.expires_at.replace(tzinfo=timezone.utc) < datetime.now(timezone.utc):
        raise ValueError("expired")

    user = get_user_by_id(db, user_id)
    if user is None:
        raise ValueError("user")

    sess.revoked = True
    db.add(sess)
    access = create_access_token(user)
    new_refresh = create_refresh_token(db, user)
    return user, access, new_refresh