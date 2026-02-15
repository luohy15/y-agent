"""Admin Lambda handler for database administration tasks."""

import json
import os

def lambda_handler(event, context):
    """Handle admin actions dispatched by CloudWatch schedules or manual invocation.

    Supported actions:
        init_db: Initialize database tables
    """
    action = event.get("action", "")
    print(f"[admin] action={action} event={json.dumps(event)}")

    if action == "init_db":
        from storage.database.base import init_db, init_tables
        database_url = os.getenv("DATABASE_URL_DEV", os.getenv("DATABASE_URL"))
        init_db(database_url)
        init_tables()
        return {"status": "ok", "action": action}

    return {"status": "error", "message": f"Unknown action: {action}"}


if __name__ == "__main__":
    result = lambda_handler({"action": "init_db"}, None)
    # result = lambda_handler({"action": "init_vm_config"}, None)
    print(result)
