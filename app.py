import os
import telebot
from flask import Flask, request
import psycopg2

# --- CONFIGURAÇÕES ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
DB_URI = os.environ.get('DB_URI')

bot = telebot.TeleBot(TOKEN, threaded=False) # threaded=False evita que o Render derrube o processo
app = Flask(__name__)

def get_db():
    return psycopg2.connect(DB_URI)

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        json_string = request.get_data().decode('utf-8')
        update = telebot.types.Update.de_json(json_string)
        bot.process_new_updates([update])
        return ''
    return '', 403

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    print(f"Mensagem de: {chat_id}") # Isso aparecerá no log do Render

    try:
        conn = get_db()
        cur = conn.cursor()
        # Busca o ID que você inseriu manualmente (8451570682)
        cur.execute("SELECT name FROM users WHERE telegram_chat_id = %s", (str(chat_id),))
        user = cur.fetchone()
        
        if user:
            bot.reply_to(message, f"Olá {user[0]}! Agora eu te reconheço. O banco de dados está conectado!")
        else:
            bot.reply_to(message, f"ID {chat_id} não encontrado. Cadastre-se no banco.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Erro no banco: {e}")
        bot.reply_to(message, "Conectei, mas houve um erro no banco de dados.")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))