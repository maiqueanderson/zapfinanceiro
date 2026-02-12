import os
import telebot
from flask import Flask, request
import psycopg2
import google.generativeai as genai
import json

# --- CONFIGURAÇÕES ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
DB_URI = os.environ.get('DB_URI')
GEMINI_KEY = os.environ.get('GEMINI_KEY')

# Configura IA
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

def get_db():
    return psycopg2.connect(DB_URI)

def process_with_ai(text):
    prompt = f"""
    Extraia dados financeiros desta frase para JSON.
    Frase: "{text}"
    Formato JSON esperado: {{"action": "add_expense", "amount": 0.00, "category": "Mercado", "description": "compras"}}
    Se não for um gasto, responda apenas: {{"action": "chat"}}
    """
    try:
        response = model.generate_content(prompt)
        clean_json = response.text.replace('```json', '').replace('```', '')
        return json.loads(clean_json)
    except:
        return None

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return '', 200

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM users WHERE telegram_chat_id = %s", (int(chat_id),))
        user = cur.fetchone()
        
        if not user:
            bot.reply_to(message, "Usuário não encontrado.")
            return

        # Processa com IA
        data = process_with_ai(text)
        
        if data and data.get('action') == 'add_expense':
            cur.execute("INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                        (user[0], data['amount'], data['category'], data['description']))
            conn.commit()
            bot.reply_to(message, f"✅ Salvo, {user[1]}!\n💰 R$ {data['amount']} em {data['category']}")
        else:
            bot.reply_to(message, f"Oi {user[1]}! Como posso ajudar com suas finanças hoje?")

        cur.close()
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"Erro: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))