import os
import telebot # Biblioteca 'pyTelegramBotAPI' é mais simples para Webhooks
from flask import Flask, request, render_template_string
import psycopg2
import google.generativeai as genai
import json

# --- CONFIGURAÇÕES (Pegamos das variáveis de ambiente do Render) ---
TOKEN = os.environ.get('8446507464:AAE26eYolqfO8zyVP3dzhnLT-UOL6Mc3tJE')
DB_URI = os.environ.get('postgresql://postgres:Mm81892461!@db.avurslqfeiqybuiyukyv.supabase.co:5432/postgres')
GEMINI_KEY = os.environ.get('AIzaSyAAwP0zwc9AbDFwdRgTlv1FkY8T5np49BU')
WEBHOOK_URL = os.environ.get('RENDER_EXTERNAL_URL') # O Render cria isso sozinho

# Configura IA
genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel('gemini-pro')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- CONEXÃO BANCO ---
def get_db():
    return psycopg2.connect(DB_URI)

# --- INTELIGÊNCIA ARTIFICIAL ---
def process_with_ai(text):
    prompt = f"""
    Extraia dados financeiros desta frase para JSON.
    Frase: "{text}"
    Formato JSON esperado: {{"action": "add_expense"|"report", "amount": 0.00, "category": "X", "description": "Y"}}
    """
    try:
        response = model.generate_content(prompt)
        clean_json = response.text.replace('```json', '').replace('```', '')
        return json.loads(clean_json)
    except:
        return None

# --- ROTA DO SITE (CADASTRO) ---
# Um HTML simples dentro do Python para não precisar de arquivos extras
HTML_CADASTRO = """
<html>
<body>
    <h2>Cadastro Financeiro</h2>
    <form method="POST">
        Nome: <input type="text" name="nome"><br>
        ID Telegram: <input type="text" name="chat_id"><br>
        <input type="submit" value="Cadastrar">
    </form>
</body>
</html>
"""

@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        nome = request.form.get('nome')
        chat_id = request.form.get('chat_id')
        
        conn = get_db()
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (name, telegram_chat_id) VALUES (%s, %s)", (nome, chat_id))
            conn.commit()
            return "Cadastrado com sucesso!"
        except Exception as e:
            return f"Erro: {e}"
        finally:
            conn.close()
    return render_template_string(HTML_CADASTRO)

# --- ROTA QUE O TELEGRAM CHAMA (WEBHOOK) ---
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    json_str = request.get_data().decode('UTF-8')
    update = telebot.types.Update.de_json(json_str)
    bot.process_new_updates([update])
    return 'OK', 200

# --- LÓGICA DO BOT ---
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text
    
    # 1. Verifica usuário
    conn = get_db()
    cur = conn.cursor()
    cur.execute("SELECT id FROM users WHERE telegram_chat_id = %s", (str(chat_id),))
    user = cur.fetchone()
    
    if not user:
        bot.reply_to(message, f"Você não está cadastrado. Seu ID é {chat_id}. Vá no site e cadastre-se.")
        conn.close()
        return

    # 2. Processa com IA
    data = process_with_ai(text)
    
    if data and data.get('action') == 'add_expense':
        cur.execute("INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                    (user[0], data['amount'], data['category'], data['description']))
        conn.commit()
        bot.reply_to(message, f"💸 Gasto de R$ {data['amount']} em {data['category']} salvo!")
    
    elif data and data.get('action') == 'report':
        # Lógica de relatório aqui...
        bot.reply_to(message, "Gerando relatório...")
    
    else:
        bot.reply_to(message, "Não entendi. Tente 'Gastei 10 reais em pão'.")

    conn.close()

# Configuração para o Render rodar o Webhook ao iniciar
if __name__ == "__main__":
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))