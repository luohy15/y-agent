"""Configuration loading from environment variables."""

import os

from dotenv import load_dotenv


def load_config():
    """Load configuration from environment variables."""
    load_dotenv()

    home = os.path.expanduser(os.environ.get("Y_AGENT_HOME", "~/.y-agent"))
    os.makedirs(home, exist_ok=True)

    database_url = os.getenv("DATABASE_URL_DEV", os.getenv("DATABASE_URL"))
    if not database_url:
        raise RuntimeError(
            "DATABASE_URL environment variable is required. "
            "Set it to a PostgreSQL connection string, e.g. "
            "DATABASE_URL=postgresql://localhost/yagent"
        )

    cfg = {
        # Storage
        "database_url": database_url,
        "openrouter_import_dir": os.path.join(home, "openrouter_import"),
        "openrouter_import_history": os.path.join(home, "openrouter_import_history.jsonl"),
        "tmp_dir": os.path.join(home, "tmp"),

        # Other settings
        "s3_bucket": os.environ.get("Y_AGENT_S3_BUCKET", ""),
        "cloudfront_distribution_id": os.environ.get("Y_AGENT_CLOUDFRONT_DISTRIBUTION_ID", ""),
        "proxy_host": os.environ.get("Y_AGENT_PROXY_HOST", ""),
        "proxy_port": os.environ.get("Y_AGENT_PROXY_PORT", ""),
        "print_speed": int(os.environ.get("Y_AGENT_PRINT_SPEED", "1000")),
    }

    # Set up proxy settings if configured
    proxy_host = cfg.get("proxy_host")
    proxy_port = cfg.get("proxy_port")
    if proxy_host and proxy_port:
        os.environ["http_proxy"] = f"http://{proxy_host}:{proxy_port}"
        os.environ["https_proxy"] = f"http://{proxy_host}:{proxy_port}"

    return cfg
