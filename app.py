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
                        "Ações possíveis:\n"
                        "1. 'add_expense': Gasto realizado (amount, category, description).\n"
                        "2. 'report_today': Quanto gastei hoje.\n"
                        "3. 'report_month': Quanto gastei no mês.\n"
                        "4. 'report_category': Quanto gastei na categoria X (category).\n"
                        "5. 'top_category': Categoria que mais gastei no mês.\n"
                        "6. 'add_bill': Conta a pagar (amount, description).\n"
                        "7. 'list_bills': Ver contas pendentes.\n"
                        "8. 'pay_bill': Marcar conta como paga (description).\n"
                        "Retorne apenas o JSON puro."
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
            bot.reply_to(message, "Usuário não cadastrado.")
            return

        user_id = user[0]
        data = process_with_ai(text)
        action = data.get('action')

        # 1. ADICIONAR GASTO
        if action == 'add_expense':
            cur.execute("INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                        (user_id, data['amount'], data['category'], data['description']))
            conn.commit()
            bot.reply_to(message, f"✅ Gasto de R$ {data['amount']:.2f} em {data['category']} salvo!")

        # 2. TOTAL HOJE
        elif action == 'report_today':
            cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id = %s AND date = CURRENT_DATE", (user_id,))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"📅 Total gasto hoje: R$ {total:.2f}")

        # 3. TOTAL MÊS
        elif action == 'report_month':
            cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id = %s AND date_trunc('month', date) = date_trunc('month', CURRENT_DATE)", (user_id,))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"📊 Total gasto este mês: R$ {total:.2f}")

        # 4. GASTO POR CATEGORIA
        elif action == 'report_category':
            cat = data.get('category')
            cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id = %s AND category ILIKE %s", (user_id, f"%{cat}%"))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"🔍 Total em {cat}: R$ {total:.2f}")

        # 5. MAIOR GASTO (TOP CATEGORIA)
        elif action == 'top_category':
            cur.execute("""
                SELECT category, SUM(amount) as total FROM transactions 
                WHERE user_id = %s AND date_trunc('month', date) = date_trunc('month', CURRENT_DATE)
                GROUP BY category ORDER BY total DESC LIMIT 1
            """, (user_id,))
            res = cur.fetchone()
            if res:
                bot.reply_to(message, f"🏆 Você mais gastou com {res[0]} este mês: R$ {res[1]:.2f}")
            else:
                bot.reply_to(message, "Ainda não tenho dados suficientes.")

        # 6. ADICIONAR CONTA A PAGAR
        elif action == 'add_bill':
            # Vamos usar a tabela scheduled_expenses para contas a pagar (status false = pendente)
            cur.execute("INSERT INTO scheduled_expenses (user_id, amount, description, status) VALUES (%s, %s, %s, false)",
                        (user_id, data['amount'], data['description']))
            conn.commit()
            bot.reply_to(message, f"📝 Conta '{data['description']}' de R$ {data['amount']:.2f} anotada!")

        # 7. LISTAR CONTAS PENDENTES
        elif action == 'list_bills':
            cur.execute("SELECT description, amount FROM scheduled_expenses WHERE user_id = %s AND status = false", (user_id,))
            bills = cur.fetchall()
            if bills:
                msg = "📌 Contas pendentes:\n" + "\n".join([f"- {b[0]}: R$ {b[1]:.2f}" for b in bills])
                bot.reply_to(message, msg)
            else:
                bot.reply_to(message, "✅ Nenhuma conta pendente!")

        # 8. PAGAR CONTA
        elif action == 'pay_bill':
            desc = data.get('description')
            cur.execute("UPDATE scheduled_expenses SET status = true WHERE user_id = %s AND description ILIKE %s AND status = false", (user_id, f"%{desc}%"))
            conn.commit()
            bot.reply_to(message, f"✔️ Conta '{desc}' marcada como paga!")

        else:
            bot.reply_to(message, f"Oi {user[1]}! Como posso ajudar?")

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