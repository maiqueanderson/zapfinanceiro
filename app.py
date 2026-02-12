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
model = genai.GenerativeModel('gemini-1.5-flash-latest')

bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

def get_db():
    return psycopg2.connect(DB_URI)

def process_with_ai(text):
    prompt = f"""
    Atue como um extrator de dados financeiros para JSON.
    Frase do usuário: "{text}"
    
    Regras de extração:
    1. Se houver um valor numérico e um item/local, defina "action" como "add_expense".
    2. Converta o valor para número decimal em "amount" (ex: 18,70 vira 18.70).
    3. Identifique uma categoria simples (ex: Mercado, Feira, Lazer, Transporte) em "category".
    4. Coloque o item em "description".
    5. Se não identificar um gasto, defina "action" como "chat".

    Formato esperado:
    {{"action": "add_expense", "amount": 0.00, "category": "Tipo", "description": "Item"}}
    """
    try:
        response = model.generate_content(prompt)
        # Limpeza para garantir que apenas o JSON seja lido
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_text)
    except Exception as e:
        print(f"Erro no processamento da IA: {e}")
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
    return "Bot Financeiro ZapFinanceiro está Online!"

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
            bot.reply_to(message, f"Olá! Seu ID {chat_id} não foi encontrado. Por favor, cadastre-se no banco de dados.")
            return

        # Processa a frase com o Gemini
        data = process_with_ai(text)
        
        if data and data.get('action') == 'add_expense':
            # Insere a transação no banco de dados
            cur.execute(
                "INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                (user[0], data['amount'], data['category'], data['description'])
            )
            conn.commit()
            bot.reply_to(message, f"✅ Salvo, {user[1]}!\n💰 R$ {data['amount']:.2f} em {data['category']}\n📝 {data['description']}")
        else:
            bot.reply_to(message, f"Oi {user[1]}! Como posso ajudar com suas finanças hoje? Tente algo como 'Gastei 18,70 na feira'.")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"Erro geral: {e}")
        bot.reply_to(message, f"Desculpe, tive um problema técnico: {e}")

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))