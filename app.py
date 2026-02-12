import os
import telebot
from flask import Flask, request
import psycopg2
import google.generativeai as genai
import json
import traceback

# --- CONFIGURAÇÕES ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
DB_URI = os.environ.get('DB_URI')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
WEBHOOK_URL = os.environ.get('RENDER_EXTERNAL_URL')

# LOGS DE INICIALIZAÇÃO (Agora fora do if __main__)
print(f"--- SERVIDOR INICIADO ---")
print(f"WEBHOOK_URL: {WEBHOOK_URL}")

# Configura IA e Bot
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')
bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# CONFIGURAÇÃO DO WEBHOOK (Fora do if __main__ para o Gunicorn ler)
if WEBHOOK_URL and TOKEN:
    webhook_path = f"{WEBHOOK_URL}/{TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_path)
    print(f"Webhook configurado para: {webhook_path}")

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
    return "Servidor Online! Cadastre seu ID no banco de dados."

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    print(f"MENSAGEM RECEBIDA: {message.text}")
    chat_id = message.chat.id
    
    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE telegram_chat_id = %s", (str(chat_id),))
        user = cur.fetchone()
        
        if not user:
            bot.reply_to(message, f"Você não está cadastrado. Seu ID é {chat_id}")
            return

        bot.reply_to(message, "Processando com IA...")
        # Lógica da IA aqui...
        
        conn.close()
    except Exception as e:
        print(f"ERRO: {e}")
        bot.reply_to(message, "Erro ao processar.")

# Mantenha o if apenas para testes locais, o Render não usará isso
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)