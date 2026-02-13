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
                        "1. Gasto comum: {'action': 'add_expense', 'amount': float, 'category': str, 'description': str}\n"
                        "2. Relatórios de gastos: {'action': 'get_report', 'period': 'today'|'yesterday'|'week'|'month'}\n"
                        "3. Adicionar Fatura: {'action': 'add_bill', 'amount': float, 'description': str, 'month': str}\n"
                        "4. Listar Faturas: {'action': 'list_bills', 'month': str}\n"
                        "5. Pagar Fatura: {'action': 'pay_bill', 'description': str, 'month': str}\n"
                        "6. Total de Faturas: {'action': 'total_bills', 'period': 'next_month'|'current'}\n"
                        "Outros: {'action': 'chat'}"
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
        bahia_now = "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '3 hours')"
        
        # --- AÇÕES DE GASTOS COMUNS E RELATÓRIOS (MANTIDAS) ---
        if action == 'add_expense':
            cur.execute("INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                        (user[0], data['amount'], data['category'], data['description']))
            conn.commit()
            bot.reply_to(message, f"✅ Salvo, {user[1]}!\n💰 R$ {data['amount']:.2f} em {data['category']}")

        elif action == 'get_report':
            period = data.get('period', 'today')
            base_query = "SELECT SUM(amount) FROM transactions WHERE user_id = %s AND "
            if period == 'yesterday': query = base_query + f"date::date = ({bahia_now} - INTERVAL '1 day')::date"
            elif period == 'week': query = base_query + f"date >= date_trunc('week', {bahia_now})"
            elif period == 'month': query = base_query + f"date >= date_trunc('month', {bahia_now})"
            else: query = base_query + f"date::date = {bahia_now}::date"
            cur.execute(query, (user[0],))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"📊 {user[1]}, total de {period}: R$ {total:.2f}")

        # --- NOVAS AÇÕES: GESTÃO DE FATURAS (scheduled_expenses) ---
        elif action == 'add_bill':
            # Concatenamos o mês na descrição para facilitar a busca
            desc_completa = f"{data['description']} - {data['month']}"
            cur.execute("INSERT INTO scheduled_expenses (user_id, amount, description, is_active) VALUES (%s, %s, %s, true)",
                        (user[0], data['amount'], desc_completa))
            conn.commit()
            bot.reply_to(message, f"💳 Fatura {data['description']} ({data['month']}) de R$ {data['amount']:.2f} anotada!")

        elif action == 'list_bills':
            mes = data.get('month', '')
            cur.execute("SELECT description, amount FROM scheduled_expenses WHERE user_id = %s AND is_active = true AND description ILIKE %s",
                        (user[0], f"%{mes}%"))
            faturas = cur.fetchall()
            if faturas:
                lista = "\n".join([f"• {f[0]}: R$ {f[1]:.2f}" for f in faturas])
                bot.reply_to(message, f"⏳ **Faturas pendentes para {mes}:**\n{lista}")
            else:
                bot.reply_to(message, f"✅ Nenhuma fatura pendente encontrada para {mes}.")

        elif action == 'pay_bill':
            desc = data.get('description', '')
            mes = data.get('month', '')
            cur.execute("UPDATE scheduled_expenses SET is_active = false WHERE user_id = %s AND description ILIKE %s AND description ILIKE %s AND is_active = true",
                        (user[0], f"%{desc}%", f"%{mes}%"))
            conn.commit()
            bot.reply_to(message, f"✔️ Fatura {desc} de {mes} marcada como paga!")

        elif action == 'total_bills':
            cur.execute("SELECT SUM(amount) FROM scheduled_expenses WHERE user_id = %s AND is_active = true", (user[0],))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"💰 O valor total de faturas pendentes é: R$ {total:.2f}")
            
        else:
            bot.reply_to(message, f"Oi {user[1]}! Como posso ajudar?")

    except Exception as e:
        bot.reply_to(message, f"Erro: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)