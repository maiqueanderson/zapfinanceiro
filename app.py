import os
import telebot
from flask import Flask, request
import psycopg2
from groq import Groq
import json

# --- CONFIGURAÇÕES ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
DB_URI = os.environ.get('DB_URI')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

client = Groq(api_key=GROQ_API_KEY)
bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

def get_db():
    return psycopg2.connect(DB_URI)

def process_with_ai(text):
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Você é um extrator de dados financeiros. "
                        "Analise a frase e retorne APENAS um objeto JSON puro.\n"
                        "1. Se for um gasto: {'action': 'add_expense', 'amount': float, 'category': str, 'description': str}\n"
                        "2. Se perguntar quanto gastou: {'action': 'get_report'}\n"
                        "3. Caso contrário: {'action': 'chat'}"
                    )
                },
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"Erro IA: {e}")
        return None

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return '', 403

@app.route('/')
def index():
    return "Bot Financeiro ZapFinanceiro Online!"

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text
    conn = None

    try:
        conn = get_db()
        cur = conn.cursor()
        
        cur.execute("SELECT id, name FROM users WHERE telegram_chat_id = %s", (int(chat_id),))
        user = cur.fetchone()
        
        if not user:
            bot.reply_to(message, f"Olá! Seu ID {chat_id} não foi encontrado.")
            return

        data = process_with_ai(text)
        action = data.get('action') if data else 'chat'
        
        if action == 'add_expense':
            # O banco preenche a data automaticamente conforme configuramos no Supabase
            cur.execute(
                "INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                (user[0], data['amount'], data['category'], data['description'])
            )
            conn.commit()
            bot.reply_to(message, f"✅ Salvo, {user[1]}!\n💰 R$ {data['amount']:.2f} em {data['category']}")
        
        elif action == 'get_report':
            # Filtra os gastos usando o dia atual no fuso de Salvador
            cur.execute(
                """
                SELECT SUM(amount) FROM transactions 
                WHERE user_id = %s 
                AND date::date = (CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '3 hours')::date
                """, 
                (user[0],)
            )
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"📊 {user[1]}, seu total de hoje é:\n💰 R$ {total:.2f}")
            
        else:
            bot.reply_to(message, f"Oi {user[1]}! Como posso ajudar?")

    except Exception as e:
        print(f"Erro: {e}")
        bot.reply_to(message, "Tive um problema técnico. Tente novamente em instantes.")
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 5000))
    app.run(host="0.0.0.0", port=port)