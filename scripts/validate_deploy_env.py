from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Mapping
from pathlib import PurePosixPath

REQUIRED_SETTINGS = (
    "KB_APP_ENV",
    "KB_AUTH_SECRET_KEY",
    "KB_PLATFORM_USERNAME",
    "KB_PLATFORM_PASSWORD",
    "KB_ADMIN_API_KEY",
    "KB_DATABASE_URL",
    "KB_DOCS_DIR",
    "KB_RAW_DIR",
    "KB_KB_DIR",
    "KB_EMBEDDING_PROVIDER",
    "KB_ANSWER_PROVIDER",
    "KB_EMBEDDING_DIMENSION",
)

LOCAL_DEFAULTS = {
    "KB_AUTH_SECRET_KEY": {"local-auth-secret"},
    "KB_PLATFORM_USERNAME": {"student"},
    "KB_PLATFORM_PASSWORD": {"student-password"},
    "KB_ADMIN_API_KEY": {"local-admin-key"},
}

SUPPORTED_PROVIDERS = {"fake", "openai"}


def collect_deploy_env_errors(
    env: Mapping[str, str],
    *,
    allow_fake_providers: bool = False,
) -> list[str]:
    errors: list[str] = []
    for key in REQUIRED_SETTINGS:
        if not env.get(key):
            errors.append(f"{key} is required.")

    app_env = env.get("KB_APP_ENV", "")
    if app_env not in {"production", "staging"}:
        errors.append("KB_APP_ENV must be production or staging.")

    auth_secret = env.get("KB_AUTH_SECRET_KEY", "")
    if auth_secret and len(auth_secret) < 32:
        errors.append("KB_AUTH_SECRET_KEY must be at least 32 characters.")

    for key, blocked_values in LOCAL_DEFAULTS.items():
        if env.get(key) in blocked_values:
            errors.append(f"{key} must not use the local development default.")

    for key in ("KB_DOCS_DIR", "KB_RAW_DIR", "KB_KB_DIR"):
        value = env.get(key)
        if value and not PurePosixPath(value).is_absolute():
            errors.append(f"{key} must be an absolute path.")
    runtime_paths = {
        env.get("KB_DOCS_DIR"),
        env.get("KB_RAW_DIR"),
        env.get("KB_KB_DIR"),
    }
    if None not in runtime_paths and "" not in runtime_paths and len(runtime_paths) < 3:
        errors.append("KB_DOCS_DIR, KB_RAW_DIR, and KB_KB_DIR must be distinct paths.")

    if env.get("KB_EMBEDDING_DIMENSION") != "1536":
        errors.append("KB_EMBEDDING_DIMENSION must be 1536 for the current schema.")

    for key in ("KB_EMBEDDING_PROVIDER", "KB_ANSWER_PROVIDER"):
        provider = env.get(key, "")
        if provider and provider not in SUPPORTED_PROVIDERS:
            errors.append(f"{key} must be one of: {', '.join(sorted(SUPPORTED_PROVIDERS))}.")
        if provider == "fake" and not allow_fake_providers:
            errors.append(f"{key} must not be fake for production deploys.")

    if (
        env.get("KB_EMBEDDING_PROVIDER") == "openai"
        or env.get("KB_ANSWER_PROVIDER") == "openai"
    ) and not env.get("OPENAI_API_KEY"):
        errors.append("OPENAI_API_KEY is required when an OpenAI provider is enabled.")

    return errors


def load_env_file(path: str) -> dict[str, str]:
    values: dict[str, str] = {}
    with open(path, encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip().strip("\"'")
    return values


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Validate production deploy environment.")
    parser.add_argument("--env-file", help="Optional KEY=VALUE file to validate.")
    parser.add_argument(
        "--allow-fake-providers",
        action="store_true",
        help="Permit fake providers for local CI smoke checks only.",
    )
    namespace = parser.parse_args(argv)

    env = dict(os.environ)
    if namespace.env_file:
        env.update(load_env_file(namespace.env_file))

    errors = collect_deploy_env_errors(
        env,
        allow_fake_providers=namespace.allow_fake_providers,
    )
    if errors:
        print("Deploy environment validation failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1

    print("Deploy environment validation passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
