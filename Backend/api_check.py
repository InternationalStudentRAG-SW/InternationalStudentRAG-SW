from openai import OpenAI
from dotenv import load_dotenv
import os

load_dotenv("Backend/.env")
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
r = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role":"user","content":"hi"}])
print(r)