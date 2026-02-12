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
        
        # Ajuste aqui: Convertendo explicitamente para int para bater com o int8 do banco
        cur.execute("SELECT name FROM users WHERE telegram_chat_id = %s", (int(chat_id),))
        user = cur.fetchone()
        
        if user:
            # Resposta personalizada usando o nome 'Maique' que está no seu banco
            bot.reply_to(message, f"Olá {user[0]}! Agora o banco de dados está lendo seus dados perfeitamente! ✅")
        else:
            bot.reply_to(message, f"ID {chat_id} não encontrado. Cadastre-se no banco.")
        
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Erro no banco: {e}")
        # Retorna o erro exato para o Telegram para sabermos o que aconteceu
        bot.reply_to(message, f"Erro técnico no banco: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))