import argparse
import getpass

from sqlalchemy import select

from app.ai.gemini import inspect_model_catalog
from app.db import SessionLocal
from app.models import User
from app.security import hash_password


def create_user(email: str, name: str, role: str) -> None:
    with SessionLocal() as db:
        normalized = email.lower().strip()
        existing = db.scalar(select(User).where(User.email == normalized))
        if existing:
            raise SystemExit("An account already uses that email")
        password = getpass.getpass("Administrator password (6+ characters): ")
        if len(password) < 6:
            raise SystemExit("Password must contain at least 6 characters")
        user = User(email=normalized, full_name=name.strip(), password_hash=hash_password(password), role=role)
        db.add(user)
        db.commit()
        print(f"Created {role} account for {normalized}")


def main() -> None:
    parser = argparse.ArgumentParser(prog="campusai")
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create-user", help="Create a staff account interactively")
    create.add_argument("--email", required=True)
    create.add_argument("--name", required=True)
    create.add_argument("--role", required=True, choices=("administrator", "placement_officer"))
    model_check = commands.add_parser("gemini-model-check", help="Read Gemini model metadata without generating content")
    model_check.add_argument("--model", default=None, help="Model name; defaults to GEMINI_MODEL")
    model_check.add_argument("--service", choices=("chat", "resume"), default="chat",
                             help="Which server-side Gemini key to check (chat or resume)")
    args = parser.parse_args()
    if args.command == "create-user":
        create_user(args.email, args.name, args.role)
    elif args.command == "gemini-model-check":
        try:
            result = inspect_model_catalog(args.model, service=args.service)
        except RuntimeError as exc:
            raise SystemExit(f"Read-only Gemini model check failed: {exc}") from None
        for key, value in result.items():
            print(f"{key.upper()}={value}")


if __name__ == "__main__":
    main()
