import asyncio
from app.database import init_db
from app.models import db_models  # noqa: F401 - ensure models are registered


async def main():
    await init_db()
    print("Database initialized.")


if __name__ == "__main__":
    asyncio.run(main())
