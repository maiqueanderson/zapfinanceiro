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
                        "Você é um assistente financeiro. Extraia a intenção do usuário em JSON.\n"
                        "Ações disponíveis:\n"
                        "1. 'add_expense': Gasto realizado (amount, category, description).\n"
                        "2. 'report_today': Quanto gastei hoje.\n"
                        "3. 'report_month': Quanto gastei no mês.\n"
                        "4. 'report_category': Quanto gastei na categoria X (category).\n"
                        "5. 'top_category': Categoria que mais gastei no mês.\n"
                        "6. 'add_bill': Adicionar conta a pagar (amount, description, due_day).\n"
                        "7. 'list_bills': Listar contas ainda não pagas.\n"
                        "8. 'pay_bill': Marcar uma conta específica como paga (description).\n"
                        "Retorne apenas JSON puro."
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

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    chat_id = message.chat.id
    text = message.text

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM users WHERE telegram_chat_id = %s", (int(chat_id),))
        user = cur.fetchone()
        
        if not user:
            bot.reply_to(message, "Usuário não encontrado.")
            return

        user_id = user[0]
        data = process_with_ai(text)
        action = data.get('action')

        # --- RELATÓRIOS ---
        if action == 'report_today':
            cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id = %s AND date::date = CURRENT_DATE", (user_id,))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"💰 Total gasto hoje: R$ {total:.2f}")

        elif action == 'report_month':
            cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id = %s AND date_trunc('month', date) = date_trunc('month', CURRENT_DATE)", (user_id,))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"📊 Total gasto este mês: R$ {total:.2f}")

        elif action == 'report_category':
            cat = data.get('category')
            cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id = %s AND category ILIKE %s", (user_id, f"%{cat}%"))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"🔍 Total em {cat}: R$ {total:.2f}")

        elif action == 'top_category':
            cur.execute("""
                SELECT category, SUM(amount) as total FROM transactions 
                WHERE user_id = %s AND date_trunc('month', date) = date_trunc('month', CURRENT_DATE)
                GROUP BY category ORDER BY total DESC LIMIT 1
            """, (user_id,))
            res = cur.fetchone()
            if res:
                bot.reply_to(message, f"🏆 Categoria com maior gasto: {res[0]} (R$ {res[1]:.2f})")
            else:
                bot.reply_to(message, "Ainda não há gastos registrados este mês.")

        # --- GESTÃO DE CONTAS (scheduled_expenses) ---
        elif action == 'add_bill':
            # is_active = true significa que a conta está pendente
            cur.execute("INSERT INTO scheduled_expenses (user_id, amount, description, due_day, is_active) VALUES (%s, %s, %s, %s, true)",
                        (user_id, data['amount'], data['description'], data.get('due_day', 1)))
            conn.commit()
            bot.reply_to(message, f"✅ Conta '{data['description']}' de R$ {data['amount']:.2f} adicionada às contas a pagar.")

        elif action == 'list_bills':
            cur.execute("SELECT description, amount, due_day FROM scheduled_expenses WHERE user_id = %s AND is_active = true", (user_id,))
            bills = cur.fetchall()
            if bills:
                msg = "⏳ **Contas Pendentes:**\n" + "\n".join([f"• {b[0]}: R$ {b[1]:.2f} (Dia {b[2]})" for b in bills])
                bot.reply_to(message, msg, parse_mode="Markdown")
            else:
                bot.reply_to(message, "🙌 Nenhuma conta pendente!")

        elif action == 'pay_bill':
            desc = data.get('description')
            cur.execute("UPDATE scheduled_expenses SET is_active = false WHERE user_id = %s AND description ILIKE %s AND is_active = true", (user_id, f"%{desc}%"))
            conn.commit()
            bot.reply_to(message, f"✔️ Conta '{desc}' marcada como paga!")

        # --- ADICIONAR GASTO COMUM ---
        elif action == 'add_expense':
            cur.execute("INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                        (user_id, data['amount'], data['category'], data['description']))
            conn.commit()
            bot.reply_to(message, f"✅ Gasto de R$ {data['amount']:.2f} salvo!")

        else:
            bot.reply_to(message, f"Oi {user[1]}! Como posso ajudar nas suas finanças hoje?")

        cur.close()
        conn.close()
    except Exception as e:
        bot.reply_to(message, f"Erro: {e}")

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return '', 200

@app.route('/')
def index():
    return "ZapFinanceiro Pro Online!"

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get('PORT', 5000)))