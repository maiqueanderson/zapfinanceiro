import os
import telebot
from flask import Flask, request
import psycopg2
from groq import Groq
import json
from datetime import datetime

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
                        "Você é um assistente financeiro. Retorne APENAS JSON.\n"
                        "1. Gasto: {'action': 'add_expense', 'amount': float, 'category': str, 'description': str, 'bank': str}\n"
                        "2. Receita: {'action': 'add_income', 'amount': float, 'bank': str, 'description': str}\n"
                        "3. Saldo: {'action': 'get_balance', 'bank': str}\n"
                        "4. Fatura: {'action': 'add_bill', 'amount': float, 'description': str, 'month': str}\n"
                        "5. Listar Faturas: {'action': 'list_bills', 'month': str}\n"
                        "6. Pagar Fatura: {'action': 'pay_bill', 'description': str, 'month': str, 'bank': str}\n"
                        "7. Relatórios: {'action': 'get_report', 'period': 'today'|'yesterday'|'week'|'month'}\n"
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
    return "ZapFinanceiro Online!", 200

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
            bot.reply_to(message, "Usuário não cadastrado.")
            return

        user_id = user[0]
        data = process_with_ai(text)
        action = data.get('action') if data else 'chat'
        bahia_now = "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '3 hours')"

        # --- AÇÕES DE GASTOS E RECEITAS ---
        if action == 'add_income':
            bank = data.get('bank', 'Geral')
            cur.execute("""
                INSERT INTO accounts (user_id, bank_name, balance) VALUES (%s, %s, %s) 
                ON CONFLICT (user_id, bank_name) DO UPDATE SET balance = accounts.balance + EXCLUDED.balance
            """, (user_id, bank, data['amount']))
            conn.commit()
            bot.reply_to(message, f"💰 R$ {data['amount']:.2f} adicionados ao {bank}!")

        elif action == 'add_expense':
            cur.execute("INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                        (user_id, data['amount'], data['category'], data['description']))
            if data.get('bank'):
                cur.execute("UPDATE accounts SET balance = balance - %s WHERE user_id = %s AND bank_name ILIKE %s",
                            (data['amount'], user_id, f"%{data['bank']}%"))
            conn.commit()
            bot.reply_to(message, f"✅ Gasto de R$ {data['amount']:.2f} salvo!")

        # --- GESTÃO DE FATURAS ---
        elif action == 'add_bill':
            cur.execute("INSERT INTO scheduled_expenses (user_id, amount, description, is_active) VALUES (%s, %s, %s, true)",
                        (user_id, data['amount'], f"{data['description']} - {data['month']}",))
            conn.commit()
            bot.reply_to(message, f"💳 Fatura de {data['month']} anotada!")

        elif action == 'list_bills':
            mes = data.get('month') or datetime.now().strftime('%B')
            cur.execute("SELECT description, amount FROM scheduled_expenses WHERE user_id = %s AND is_active = true AND description ILIKE %s",
                        (user_id, f"%{mes}%"))
            faturas = cur.fetchall()
            if faturas:
                lista = "\n".join([f"• {f[0]}: R$ {f[1]:.2f}" for f in faturas])
                bot.reply_to(message, f"⏳ **Faturas pendentes ({mes}):**\n{lista}")
            else:
                bot.reply_to(message, f"✅ Nenhuma fatura pendente para {mes}.")

        elif action == 'pay_bill':
            desc, mes, bank = data.get('description', ''), data.get('month', ''), data.get('bank')
            cur.execute("SELECT amount FROM scheduled_expenses WHERE user_id = %s AND description ILIKE %s AND description ILIKE %s AND is_active = true",
                        (user_id, f"%{desc}%", f"%{mes}%"))
            res = cur.fetchone()
            if res:
                cur.execute("UPDATE scheduled_expenses SET is_active = false WHERE user_id = %s AND description ILIKE %s AND description ILIKE %s",
                            (user_id, f"%{desc}%", f"%{mes}%"))
                if bank:
                    cur.execute("UPDATE accounts SET balance = balance - %s WHERE user_id = %s AND bank_name ILIKE %s",
                                (res[0], user_id, f"%{bank}%"))
                conn.commit()
                bot.reply_to(message, f"✔️ Fatura paga com {bank}!")
            else:
                bot.reply_to(message, "Fatura não encontrada.")

        # --- OUTROS ---
        elif action == 'get_balance':
            cur.execute("SELECT bank_name, balance FROM accounts WHERE user_id = %s", (user_id,))
            rows = cur.fetchall()
            msg = "\n".join([f"🏦 {r[0]}: R$ {r[1]:.2f}" for r in rows]) if rows else "Nenhum saldo."
            bot.reply_to(message, f"Saldos:\n{msg}")

        elif action == 'get_report':
            cur.execute(f"SELECT SUM(amount) FROM transactions WHERE user_id = %s AND date::date = {bahia_now}::date", (user_id,))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"📊 Total de hoje: R$ {total:.2f}")

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