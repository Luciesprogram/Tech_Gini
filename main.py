
import os
import telebot
import google.generativeai as genai
import json

# load from Replit secrets / env
TELEGRAM_TOKEN = os.environ.get('TELEGRAM_TOKEN', '')
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY', '')

# Check if required environment variables are set
if not TELEGRAM_TOKEN:
    print("❌ Error: TELEGRAM_TOKEN environment variable not set!")
    print("Please add your Telegram bot token to the Secrets tab in Replit.")
    exit(1)

if not GEMINI_API_KEY:
    print("❌ Error: GEMINI_API_KEY environment variable not set!")
    print("Please add your Google Gemini API key to the Secrets tab in Replit.")
    exit(1)

# init
bot = telebot.TeleBot(TELEGRAM_TOKEN)
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")  # use the flash model

# Prompt template - exact prompt to send to Gemini
PROMPT_TEMPLATE = """You are an AI misinformation detector focused on India.
Analyze the following content and respond ONLY in valid JSON with these fields:
{{
 "result": "FAKE" or "REAL" or "UNSURE",
 "confidence": number_between_0_and_100,
 "reason": "one-sentence technical reason",
 "why_card_en": "short consumer-friendly explanation in English (1-2 short bullets)",
 "why_card_hi": "short consumer-friendly explanation in Hindi (1-2 short bullets)",
 "evidence": ["optional URL or short source text"]
}}
Content: \"\"\"{content}\"\"\"
Context: country=India, consider scams, phishing, deepfakes, and forged claims.
Return only JSON.
"""

def call_gemini(content):
    prompt = PROMPT_TEMPLATE.format(content=content.replace('"','\\"'))
    resp = model.generate_content(prompt)
    # response typically inside resp.text — parse safe
    text = resp.text.strip()
    try:
        # find first JSON object in text
        start = text.find('{')
        end = text.rfind('}')+1
        j = json.loads(text[start:end])
        return j
    except Exception as e:
        # fallback: return uncertain JSON
        return {"result":"UNSURE","confidence":40,"reason":"AI response parse failed","why_card_en":"Unable to determine","why_card_hi":"Niśchit nahi kar paaye","evidence":[]}

def color_from_result(j):
    res = j.get("result","UNSURE")
    conf = float(j.get("confidence",0))
    if res=="FAKE" and conf>=65:
        return "RED"
    if res=="REAL" and conf>=60:
        return "GREEN"
    return "YELLOW"

def send_safe_reply(message, text, parse_mode=None):
    """Send reply with error handling and retries"""
    import time
    for attempt in range(3):
        try:
            bot.reply_to(message, text, parse_mode=parse_mode)
            return True
        except Exception as e:
            print(f"Attempt {attempt + 1} failed: {e}")
            if attempt < 2:  # Don't sleep on last attempt
                time.sleep(2 ** attempt)  # Exponential backoff
    return False

# simple in-memory store (fine for demo)
bot_user_data = {}

# command to get complaint text - MUST BE BEFORE general handler
@bot.message_handler(commands=["complaint"])
def complaint_cmd(message):
    data = bot_user_data.get(message.from_user.id)
    if not data:
        send_safe_reply(message, "No recent red-flagged item found. Forward suspicious text first.")
        return
    send_safe_reply(message, "📝 Auto complaint text:\n\n" + data["last_complaint"])

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    text = message.text or ""
    # quick local heuristic: if text length < 5, ask for more
    if len(text.strip())<5:
        send_safe_reply(message, "Send the suspicious message text (copy paste SMS/forward).")
        return

    send_safe_reply(message, "🔎 Checking... please wait a moment.")
    
    try:
        j = call_gemini(text)
        color = color_from_result(j)
        # Build reply
        reply = ""
        if color=="RED":
            reply += "🚨 *Likely Misinformation* (Red Flag)\n"
        elif color=="YELLOW":
            reply += "⚠ *Unverified / Low Confidence*\n"
        else:
            reply += "✅ *Likely Safe* (Green)\n"

        reply += f"\n*Confidence:* {j.get('confidence')}%\n"
        reply += f"*Reason:* {j.get('reason')}\n\n"
        reply += "*Why (EN):* " + j.get("why_card_en","-") + "\n"
        reply += "*Why (HI):* " + j.get("why_card_hi","-") + "\n"
        
        # add action recommendation
        if color=="RED":
            # generate complaint text to paste to NCRP
            try:
                complaint_text = generate_complaint_text(text, j)
                reply += "\nYou can /complaint to generate auto complaint text to paste into NCRP.\n"
                bot_user_data[message.from_user.id] = {"last_complaint": complaint_text}
            except Exception as e:
                print(f"Failed to generate complaint: {e}")
                reply += "\n⚠️ Complaint generation temporarily unavailable.\n"
        
        send_safe_reply(message, reply, parse_mode="Markdown")
        
    except Exception as e:
        print(f"Error processing message: {e}")
        send_safe_reply(message, "❌ Sorry, I encountered an error analyzing this content. Please try again.")

def generate_complaint_text(content, j):
    # This prompt asks Gemini to format a complaint message suitable for NCRP form (demo)
    prompt = f"""
You are an assistant preparing a concise complaint for a cyber crime reporting portal (NCRP).
Write a short, formal complaint in English (3-6 sentences) describing the incident, containing:
- what the message/content was (paste below),
- why it is harmful/misleading (use evidence),
- request authorities to investigate.
Also provide a short evidence list (1-2 bullets).
Content: \"\"\"{content}\"\"\"
AI findings JSON: {json.dumps(j)}
Return only the complaint text.
"""
    resp = model.generate_content(prompt)
    return resp.text.strip()

print("🤖 Techgini Bot Running...")
bot.infinity_polling()
