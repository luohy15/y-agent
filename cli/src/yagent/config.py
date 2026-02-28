"""Config module - loads settings, initializes DB lazily."""

_config = None
_db_initialized = False


def get_config():
    """Load config and initialize DB on first access."""
    global _config, _db_initialized
    if _config is None:
        from yagent.settings import load_config
        _config = load_config()
    if not _db_initialized and _config.get('database_url'):
        from storage.database.base import init_db
        init_db(_config['database_url'])
        _db_initialized = True
    return _config


# Lazy proxy for backward compatibility with `from yagent.config import config`
class _LazyConfig:
    def __getitem__(self, key):
        return get_config()[key]

    def __contains__(self, key):
        return key in get_config()

    def get(self, key, default=None):
        return get_config().get(key, default)


config = _LazyConfig()
