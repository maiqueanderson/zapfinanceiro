import os
import telebot
from flask import Flask, request, render_template_string
import psycopg2
import google.generativeai as genai
import json
import traceback # Importante para ver detalhes do erro

# --- CONFIGURAÇÕES ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
DB_URI = os.environ.get('DB_URI')
GEMINI_KEY = os.environ.get('GEMINI_KEY')
WEBHOOK_URL = os.environ.get('RENDER_EXTERNAL_URL')

# LOG INICIAL (Para garantir que as variáveis existem)
print("--- INICIANDO SERVIDOR ---")
print(f"Token detectado: {'SIM' if TOKEN else 'NÃO'}")
print(f"Banco detectado: {'SIM' if DB_URI else 'NÃO'}")
print(f"Gemini detectado: {'SIM' if GEMINI_KEY else 'NÃO'}")

# Configura IA
try:
    genai.configure(api_key=GEMINI_KEY)
    model = genai.GenerativeModel('gemini-pro')
except Exception as e:
    print(f"ERRO AO CONFIGURAR IA: {e}")

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)

# --- CONEXÃO BANCO ---
def get_db():
    try:
        conn = psycopg2.connect(DB_URI)
        return conn
    except Exception as e:
        print(f"ERRO FATAL DE CONEXÃO COM BANCO: {e}")
        return None

# --- INTELIGÊNCIA ARTIFICIAL ---
def process_with_ai(text):
    print(f"Enviando para IA: {text}")
    prompt = f"""
    Extraia dados financeiros desta frase para JSON.
    Frase: "{text}"
    Formato JSON esperado: {{"action": "add_expense"|"report", "amount": 0.00, "category": "X", "description": "Y"}}
    """
    try:
        response = model.generate_content(prompt)
        print(f"Resposta bruta da IA: {response.text}") # LOG DA RESPOSTA
        clean_json = response.text.replace('```json', '').replace('```', '')
        return json.loads(clean_json)
    except Exception as e:
        print(f"ERRO NA IA: {e}") # AQUI VAMOS PEGAR O ERRO
        return None

# --- ROTA DO SITE ---
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
        if not conn:
            return "Erro de conexão com o banco."
            
        cur = conn.cursor()
        try:
            cur.execute("INSERT INTO users (name, telegram_chat_id) VALUES (%s, %s)", (nome, chat_id))
            conn.commit()
            return "Cadastrado com sucesso!"
        except Exception as e:
            return f"Erro ao salvar: {e}"
        finally:
            conn.close()
    return render_template_string(HTML_CADASTRO)

# --- ROTA WEBHOOK ---
@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    try:
        json_str = request.get_data().decode('UTF-8')
        update = telebot.types.Update.de_json(json_str)
        bot.process_new_updates([update])
        return 'OK', 200
    except Exception as e:
        print(f"ERRO NO WEBHOOK: {e}")
        return 'ERROR', 500

# --- LÓGICA DO BOT ---
@bot.message_handler(func=lambda message: True)
def handle_message(message):
    print(f"--- MENSAGEM RECEBIDA: {message.text} ---") # LOG IMPORTANTE
    
    chat_id = message.chat.id
    text = message.text
    
    conn = get_db()
    if not conn:
        print("Falha ao conectar no banco dentro da mensagem")
        bot.reply_to(message, "Erro de sistema: Banco de dados inacessível.")
        return

    try:
        cur = conn.cursor()
        cur.execute("SELECT id FROM users WHERE telegram_chat_id = %s", (str(chat_id),))
        user = cur.fetchone()
        
        if not user:
            print(f"Usuário {chat_id} não encontrado.")
            bot.reply_to(message, f"Você não está cadastrado. Seu ID é {chat_id}. Cadastre-se no site: {WEBHOOK_URL}")
            conn.close()
            return

        print("Usuário encontrado. Chamando IA...")
        data = process_with_ai(text)
        
        if data and data.get('action') == 'add_expense':
            print(f"Salvando gasto: {data}")
            cur.execute("INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                        (user[0], data['amount'], data['category'], data['description']))
            conn.commit()
            bot.reply_to(message, f"💸 Gasto de R$ {data['amount']} em {data['category']} salvo!")
        
        elif data and data.get('action') == 'report':
            bot.reply_to(message, "Gerando relatório... (Em breve)")
        
        else:
            print("IA não retornou ação válida ou deu erro.")
            bot.reply_to(message, "Não entendi. Tente algo como: 'Gastei 10 reais em pão'.")

    except Exception as e:
        print("ERRO CRÍTICO NO PROCESSAMENTO:")
        traceback.print_exc() # Imprime o erro completo
        bot.reply_to(message, f"Erro interno: {e}")
    finally:
        if conn:
            conn.close()

if __name__ == "__main__":
    # Garante que o Webhook está setado ao iniciar
    print("Setando Webhook...")
    bot.remove_webhook()
    bot.set_webhook(url=f"{WEBHOOK_URL}/{TOKEN}")
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))