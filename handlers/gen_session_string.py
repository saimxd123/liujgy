import os
import asyncio
from pyrogram import Client


API_ID = 37548478
API_HASH = os.getenv("API_HASH", "")

async def main():


    async with Client(
        name="my_session",
        api_id=API_ID,
        api_hash=API_HASH,
    ) as app:


        session_string = await app.export_session_string()
        print("\n✅ New SESSION_STRING:\n")
        print(session_string)
        print("\n📌 Copy this string and paste it into your .env / config.py")

        with open("session_string.txt", "w") as f:
            f.write(session_string)
        print("✅ Also saved to session_string.txt")

if __name__ == "__main__":
    asyncio.run(main())