import os
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

# DeepSeek
DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEEPSEEK_API_KEY = os.getenv("DEEPSEEK_API_KEY")
deepseek_client = OpenAI(base_url=DEEPSEEK_BASE_URL, api_key=DEEPSEEK_API_KEY)

# Telegram
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHATID")

# Model
LLM_MODEL = "deepseek-v4-pro"  # or os.getenv("LLM_MODEL", "deepseek-v4-pro")