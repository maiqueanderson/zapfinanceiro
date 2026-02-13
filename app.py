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
                        "Você é um extrator de dados financeiros. Retorne APENAS JSON.\n"
                        "1. Gasto: {'action': 'add_expense', 'amount': float, 'category': str, 'description': str}\n"
                        "2. Pergunta de quanto gastou: {'action': 'get_report', 'period': 'today' | 'yesterday' | 'week' | 'month'}\n"
                        "3. Outros: {'action': 'chat'}"
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

# --- ROTA QUE O RENDER PRECISA PARA STATUS 200 ---
@app.route('/')
def index():
    return "Bot Financeiro ZapFinanceiro Online!", 200

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return '', 200
    return '', 403

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
            bot.reply_to(message, "Usuário não encontrado.")
            return

        data = process_with_ai(text)
        action = data.get('action') if data else 'chat'
        
        if action == 'add_expense':
            cur.execute(
                "INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                (user[0], data['amount'], data['category'], data['description'])
            )
            conn.commit()
            bot.reply_to(message, f"✅ Salvo, {user[1]}!\n💰 R$ {data['amount']:.2f} em {data['category']}")
        
        elif action == 'get_report':
            period = data.get('period', 'today')
            base_query = "SELECT SUM(amount) FROM transactions WHERE user_id = %s AND "
            bahia_now = "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '3 hours')"
            
            if period == 'yesterday':
                query = base_query + f"date::date = ({bahia_now} - INTERVAL '1 day')::date"
                label = "ontem"
            elif period == 'week':
                query = base_query + f"date >= date_trunc('week', {bahia_now})"
                label = "esta semana"
            elif period == 'month':
                query = base_query + f"date >= date_trunc('month', {bahia_now})"
                label = "este mês"
            else:
                query = base_query + f"date::date = {bahia_now}::date"
                label = "hoje"

            cur.execute(query, (user[0],))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"📊 {user[1]}, seu gasto de {label} é:\n💰 R$ {total:.2f}")
            
        else:
            bot.reply_to(message, f"Oi {user[1]}! Como posso ajudar com suas finanças hoje?")

    except Exception as e:
        print(f"Erro: {e}")
        bot.reply_to(message, "Erro técnico. Tente novamente.")
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    # Garante que o Flask use a porta que o Render fornecer
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)