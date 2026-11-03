MARK

Setup

First make sure Python is installed.

Then go to the MARK folder:

cd MARK

Create a virtual environment:

python3 -m venv venv

Activate it:

source venv/bin/activate

Install the requirements:

pip install -r requirements.txt

Configure

Create a ".env" file in the main MARK folder.

Add your own configuration values there.

For example:

BOT_TOKEN=your_bot_token
OWNER_ID=your_telegram_id
API_ID=your_api_id
API_HASH=your_api_hash
DATABASE_URL=your_database_url

Make sure you replace the example values with your actual values.

Start

After everything is installed and configured, start MARK with:

python3 main.py

If you're already inside the virtual environment:

python main.py

That's it.

If you get an error while starting the bot, check the terminal output and fix the missing configuration or dependency.