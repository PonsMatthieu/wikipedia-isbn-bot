import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

AVAILABLE_SOURCES = ("bnf", "sudoc", "openlibrary", "googlebooks")

def boolean(name: str, default: bool = False) -> bool:
    value = os.getenv(name, str(default)).strip().lower()
    if value not in {"1", "0", "true", "false", "yes", "no"}:
        raise ValueError(f"{name} doit valoir true ou false")
    return value in {"1", "true", "yes"}


@dataclass(frozen=True)
class Settings:
    data_dir: Path
    report_dir: Path
    wiki_api: str = "https://fr.wikipedia.org/w/api.php"
    category: str = "Catégorie:Page avec ISBN invalide"
    operator: str = "Mésange_Futée"
    user_agent: str = "MesangeISBNBot/0.1 (https://fr.wikipedia.org/wiki/Utilisateur:M%C3%A9sange_Fut%C3%A9e)"
    mode: str = "DRY_RUN"
    write_enabled: bool = False
    community_approved: bool = False
    bot_login: str = ""
    bot_password: str = ""
    bot_account: str = ""
    sources: tuple[str, ...] = ("bnf", "sudoc", "openlibrary")
    google_key: str = ""
    max_pages: int = 20
    max_edits: int = 3
    request_delay: float = 1.1
    timeout: float = 30
    max_retries: int = 4
    mail_host: str = ""
    mail_port: int = 587
    mail_security: str = "starttls"
    mail_user: str = ""
    mail_password: str = ""
    mail_from: str = ""
    mail_to: str = ""

    @property
    def db_path(self) -> Path:
        return self.data_dir / "state.sqlite3"

    @property
    def stop_file(self) -> Path:
        return self.data_dir / "STOP"

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        # Variables injectées par Toolforge prioritaires sur un éventuel fichier.
        if env_file is not None:
            load_dotenv(env_file, override=False)
        else:
            load_dotenv(Path.cwd() / ".env", override=False)
        root = Path(os.getenv("BOT_DATA_DIR") or (
            str(Path(os.environ["TOOL_DATA_DIR"]) / "isbn-bot")
            if os.getenv("TOOL_DATA_DIR") else "data"
        )).expanduser().resolve()
        mode = os.getenv("BOT_MODE", "DRY_RUN").upper()
        if mode not in {"DRY_RUN", "REVIEW_ONLY"}:
            raise ValueError("BOT_MODE accepte DRY_RUN ou REVIEW_ONLY dans cette V1")
        sources = tuple(s.strip() for s in os.getenv("BOT_SOURCES", "bnf,sudoc,openlibrary").split(",") if s.strip())
        if not sources or set(sources) - set(AVAILABLE_SOURCES):
            raise ValueError("BOT_SOURCES doit contenir bnf, sudoc, openlibrary et/ou googlebooks")
        settings = cls(
            data_dir=root,
            report_dir=Path(os.getenv("BOT_REPORT_DIR") or root / "reports").expanduser().resolve(),
            wiki_api=os.getenv("WIKI_API", cls.wiki_api),
            category=os.getenv("WIKI_CATEGORY", cls.category),
            operator=os.getenv("BOT_OPERATOR", cls.operator),
            user_agent=os.getenv("BOT_USER_AGENT", cls.user_agent),
            mode=mode,
            write_enabled=boolean("BOT_WRITE_ENABLED"),
            community_approved=boolean("BOT_COMMUNITY_APPROVED"),
            bot_login=os.getenv("WIKI_BOT_LOGIN", ""),
            bot_password=os.getenv("WIKI_BOT_PASSWORD", ""),
            bot_account=os.getenv("WIKI_BOT_ACCOUNT", ""),
            sources=tuple(dict.fromkeys(sources)),
            google_key=os.getenv("GOOGLE_BOOKS_API_KEY", ""),
            max_pages=int(os.getenv("BOT_MAX_PAGES", "20")),
            max_edits=int(os.getenv("BOT_MAX_EDITS", "3")),
            request_delay=float(os.getenv("BOT_REQUEST_DELAY", "1.1")),
            timeout=float(os.getenv("BOT_TIMEOUT", "30")),
            max_retries=int(os.getenv("BOT_MAX_RETRIES", "4")),
            mail_host=os.getenv("MAIL_HOST", ""),
            mail_port=int(os.getenv("MAIL_PORT", "587")),
            mail_security=os.getenv("MAIL_SECURITY", "starttls"),
            mail_user=os.getenv("MAIL_USER", ""),
            mail_password=os.getenv("MAIL_PASSWORD", ""),
            mail_from=os.getenv("MAIL_FROM", ""),
            mail_to=os.getenv("MAIL_TO", ""),
        )
        if settings.max_pages < 1 or settings.max_edits < 1 or settings.request_delay < 0:
            raise ValueError("Limites de pages/éditions positives ; délai non négatif")
        if settings.timeout <= 0 or not 1 <= settings.max_retries <= 8:
            raise ValueError("Timeout positif et BOT_MAX_RETRIES entre 1 et 8")
        if settings.mail_security not in {"starttls", "ssl"}:
            raise ValueError("MAIL_SECURITY doit être starttls ou ssl")
        return settings
