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

# Inicializa o Cliente Groq
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
                        "Retorne APENAS um objeto JSON puro com as chaves: "
                        "'action' (sempre 'add_expense'), 'amount' (float), "
                        "'category' (string simples) e 'description' (string). "
                        "Se o texto não for um gasto claro, retorne action: 'chat'."
                    )
                },
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"}
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"Erro no processamento da IA (Groq): {e}")
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
    return "Bot Financeiro ZapFinanceiro (Groq Edition) está Online!"

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text

    try:
        conn = get_db()
        cur = conn.cursor()
        
        # Busca o usuário pelo ID do Telegram
        cur.execute("SELECT id, name FROM users WHERE telegram_chat_id = %s", (int(chat_id),))
        user = cur.fetchone()
        
        if not user:
            bot.reply_to(message, f"Olá! Seu ID {chat_id} não foi encontrado no banco.")
            return

        # Processa a frase com o Groq
        data = process_with_ai(text)
        
        if data and data.get('action') == 'add_expense':
            cur.execute(
                "INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                (user[0], data['amount'], data['category'], data['description'])
            )
            conn.commit()
            bot.reply_to(message, f"✅ Salvo, {user[1]}!\n💰 R$ {data['amount']:.2f} em {data['category']}\n📝 {data['description']}")
        else:
            bot.reply_to(message, f"Oi {user[1]}! Como posso ajudar com suas finanças hoje?")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Erro geral: {e}")
        bot.reply_to(message, f"Erro técnico: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))