import os
import telebot
from flask import Flask, request
import psycopg2
import google.generativeai as genai

# --- CONFIGURAÇÕES ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
DB_URI = os.environ.get('DB_URI')
GEMINI_KEY = os.environ.get('GEMINI_KEY')

# Inicialização rápida
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# Configura o Gemini apenas se a chave existir
if GEMINI_KEY:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-pro')

def get_db():
    return psycopg2.connect(DB_URI)

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

@app.route('/')
def index():
    return "Bot Financeiro Online!"

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text
    print(f"Recebido de {chat_id}: {text}")

    try:
        conn = get_db()
        cur = conn.cursor()
        # Busca o usuário pelo ID do Telegram que você inseriu manualmente
        cur.execute("SELECT name FROM users WHERE telegram_chat_id = %s", (str(chat_id),))
        user = cur.fetchone()
        
        if not user:
            bot.reply_to(message, f"Olá! Seu ID {chat_id} não está no banco. Cadastre-se primeiro.")
            conn.close()
            return

        # Se chegou aqui, o usuário existe!
        nome_usuario = user[0]
        
        # Chamada da IA protegida
        try:
            prompt = f"O usuário {nome_usuario} disse: '{text}'. Responda de forma curta e amigável confirmando que você é o assistente financeiro dele."
            response = model.generate_content(prompt)
            bot.reply_to(message, response.text)
        except Exception as ai_err:
            bot.reply_to(message, f"Oi {nome_usuario}! Recebi sua mensagem, mas tive um erro com a IA: {ai_err}")

        conn.close()
    except Exception as e:
        bot.reply_to(message, f"Erro de conexão com o banco: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))