"""Immutable deployment settings from the environment and an optional .env file."""
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Mapping, Optional, Tuple
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values
from dotenv.parser import parse_stream

from .paths import PROJECT_ROOT, project_path

DEFAULTS = {
    "TG_API_ID": "", "TG_API_HASH": "", "TG_PHONE": "",
    "TG_BOT_TOKEN": "", "TG_ADMIN_IDS": "", "TG_PROXY_URL": "",
    "DB_PATH": "config/forwarder.db", "SESSION_PATH": "forwarder.session",
    "WEB_HOST": "127.0.0.1", "WEB_PORT": "10082", "WEB_INITIAL_PASSWORD": "",
}


class StartupConfigurationError(ValueError):
    """A deployment variable is missing or invalid; messages never contain secrets."""


def read_env_file(path):
    """Reject ambiguous or malformed files instead of silently skipping settings."""
    path = Path(path)
    if not path.is_file():
        return {}
    names = set()
    with path.open(encoding="utf-8") as handle:
        for binding in parse_stream(handle):
            if binding.error:
                raise StartupConfigurationError(f"Invalid .env syntax at line {binding.original.line}")
            if binding.key in names:
                raise StartupConfigurationError(f"Duplicate .env variable: {binding.key}")
            if binding.key:
                names.add(binding.key)
    return dotenv_values(path, interpolate=False)


@dataclass(frozen=True)
class StartupConfig:
    api_id: int
    api_hash: str = field(repr=False)
    phone: str = field(repr=False)
    bot_token: str = field(default="", repr=False)
    admin_ids: Tuple[int, ...] = ()
    db_path: Path = PROJECT_ROOT / "config/forwarder.db"
    session_path: Path = PROJECT_ROOT / "forwarder.session"
    web_host: str = "127.0.0.1"
    web_port: int = 10082
    proxy_url: str = field(default="", repr=False)
    initial_password: str = field(default="", repr=False)
    env_file: Path = PROJECT_ROOT / ".env"
    sources: Mapping[str, str] = field(default_factory=dict, repr=False, compare=False)

    @classmethod
    def load(cls, env_file=None, *, environ=None, project_root=PROJECT_ROOT):
        env_file = project_path(env_file or ".env", project_root)
        file_values = read_env_file(env_file)
        environment = os.environ if environ is None else environ
        values, sources = {}, {}
        for name, default in DEFAULTS.items():
            if name in environment:
                values[name], sources[name] = environment[name], "environment"
            elif name in file_values:
                values[name], sources[name] = file_values[name] or "", ".env"
            else:
                values[name], sources[name] = default, "default"
        return cls.from_values(values, env_file=env_file, sources=sources, project_root=project_root)

    @classmethod
    def from_values(cls, values, *, env_file=None, sources=None, project_root=PROJECT_ROOT):
        values = dict(DEFAULTS, **values)
        for name, value in values.items():
            if name in DEFAULTS and (not isinstance(value, str) or "\x00" in value):
                raise StartupConfigurationError(f"{name} must be a string without NUL characters")

        def integer(name, low, high):
            raw = values[name].strip()
            if not re.fullmatch(r"[0-9]+", raw) or not low <= int(raw) <= high:
                raise StartupConfigurationError(f"{name} must be an integer between {low} and {high}")
            return int(raw)
        api_id = integer("TG_API_ID", 1, 2**31 - 1)
        api_hash = values["TG_API_HASH"].strip()
        if not re.fullmatch(r"[a-fA-F0-9]{32}", api_hash):
            raise StartupConfigurationError("TG_API_HASH must contain 32 hexadecimal characters")
        phone = values["TG_PHONE"].strip()
        if not re.fullmatch(r"\+[1-9][0-9]{6,14}", phone):
            raise StartupConfigurationError("TG_PHONE must be an international phone number beginning with +")
        token = values["TG_BOT_TOKEN"].strip()
        if token and not re.fullmatch(r"[0-9]+:[A-Za-z0-9_-]{20,}", token):
            raise StartupConfigurationError("TG_BOT_TOKEN has an invalid format")
        admins = values["TG_ADMIN_IDS"].strip()
        if admins and not re.fullmatch(r"[1-9][0-9]*(?:\s*,\s*[1-9][0-9]*)*", admins):
            raise StartupConfigurationError("TG_ADMIN_IDS must be comma-separated positive integers")
        admin_ids = tuple(dict.fromkeys(int(value.strip()) for value in admins.split(","))) if admins else ()
        if token and not admin_ids:
            raise StartupConfigurationError("TG_ADMIN_IDS is required when TG_BOT_TOKEN is configured")
        host = values["WEB_HOST"].strip()
        if not host or re.search(r"\s|[/\\]", host):
            raise StartupConfigurationError("WEB_HOST must be a hostname or IP address")
        paths = {}
        for name in ("DB_PATH", "SESSION_PATH"):
            if not values[name].strip():
                raise StartupConfigurationError(f"{name} cannot be empty")
            path = project_path(values[name].strip(), project_root)
            if name == "SESSION_PATH" and not str(path).endswith(".session"):
                path = path.with_name(path.name + ".session")
            if path.is_dir():
                raise StartupConfigurationError(f"{name} must refer to a file")
            paths[name] = path
        if paths["DB_PATH"] == paths["SESSION_PATH"]:
            raise StartupConfigurationError("DB_PATH and SESSION_PATH must differ")
        proxy_url = values["TG_PROXY_URL"].strip()
        parse_proxy(proxy_url)
        return cls(
            api_id=api_id, api_hash=api_hash, phone=phone, bot_token=token,
            admin_ids=admin_ids, db_path=paths["DB_PATH"], session_path=paths["SESSION_PATH"],
            web_host=host, web_port=integer("WEB_PORT", 1, 65535), proxy_url=proxy_url,
            initial_password=values["WEB_INITIAL_PASSWORD"],
            env_file=project_path(env_file or ".env", project_root),
            sources=MappingProxyType(dict(sources or {})),
        )

    @property
    def proxy(self):
        return parse_proxy(self.proxy_url)

    def public_info(self):
        """Expose configuration provenance and status, never credential values."""
        visible = {"TG_API_ID": self.api_id, "TG_ADMIN_IDS": list(self.admin_ids),
            "DB_PATH": str(self.db_path), "SESSION_PATH": str(self.session_path),
            "WEB_HOST": self.web_host, "WEB_PORT": self.web_port}
        configured = {"TG_API_HASH": bool(self.api_hash), "TG_PHONE": bool(self.phone),
            "TG_BOT_TOKEN": bool(self.bot_token), "TG_PROXY_URL": bool(self.proxy_url)}
        return {"env_file": str(self.env_file), "fields": {
            name: {"source": self.sources.get(name, "default"),
                **({"value": value} if name in visible else {"configured": value})}
            for name, value in {**visible, **configured}.items()
        }}


def parse_proxy(value: str) -> Optional[dict]:
    if not value:
        return None
    try:
        parsed = urlsplit(value)
        if parsed.scheme not in ("socks5", "socks4", "http") or not parsed.hostname or not parsed.port:
            raise ValueError()
        if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
            raise ValueError()
        return {"proxy_type": parsed.scheme, "addr": parsed.hostname, "port": parsed.port,
            "rdns": True, "username": unquote(parsed.username) if parsed.username else None,
            "password": unquote(parsed.password) if parsed.password else None}
    except ValueError:
        raise StartupConfigurationError("TG_PROXY_URL must be a socks5, socks4 or http URL with host and port") from None
