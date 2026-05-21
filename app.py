import os
import sys
import telebot
from flask import Flask, request
import psycopg2
from groq import Groq
import json
import traceback
from datetime import datetime, timedelta

# --- CONFIGURAÇÕES ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
DB_URI = os.environ.get('DB_URI')
GROQ_API_KEY = os.environ.get('GROQ_API_KEY')

client = Groq(api_key=GROQ_API_KEY)
bot = telebot.TeleBot(TOKEN, threaded=False)
app = Flask(__name__)

# --- MEMÓRIA TEMPORÁRIA PARA AÇÕES INCOMPLETAS ---
pending_user_actions = {}

def get_db():
    return psycopg2.connect(DB_URI, connect_timeout=60)

def process_with_ai(text):
    try:
        completion = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {
                    "role": "system", 
                    "content": (
                        "Você é um assistente financeiro. Retorne APENAS JSON.\n"
                        "1. Gasto (Dinheiro/Débito/Pix): {'action': 'add_expense', 'amount': float, 'category': str, 'description': str, 'bank': str}\n"
                        "2. Receita: {'action': 'add_income', 'amount': float, 'bank': str, 'description': str}\n"
                        "3. Saldo: {'action': 'get_balance', 'bank': str}\n"
                        "4. Fatura Simples ou Conta futura: {'action': 'add_bill', 'amount': float, 'description': str, 'month': 'MÊS EM PORTUGUÊS', 'category': str}\n"
                        "5. Compra Cartão de Crédito (1x ou Parcelado): {'action': 'add_credit_card_purchase', 'amount': float, 'installments': int, 'description': str, 'card': str, 'category': str}\n"
                        "6. Listar Contas/Faturas: {'action': 'list_bills', 'month': 'MÊS EM PORTUGUÊS'}\n"
                        "7. Total Contas/Faturas: {'action': 'total_bills', 'month': 'MÊS EM PORTUGUÊS'}\n"
                        "8. Pagar Conta/Fatura: {'action': 'pay_bill', 'description': str, 'month': 'MÊS EM PORTUGUÊS', 'bank': str}\n"
                        "9. Relatórios Gerais: {'action': 'get_report', 'period': 'today'|'yesterday'|'week'|'month'}\n"
                        "10. Relatório Categoria: {'action': 'report_category', 'category': str, 'period': 'today'|'week'|'month'}\n"
                        "11. Listar Categorias: {'action': 'list_categories'}\n"
                        "12. Definir Meta: {'action': 'set_goal', 'amount': float, 'category': str}\n"
                        "13. Alterar Valor de Fatura/Conta: {'action': 'update_bill', 'description': str, 'month': 'MÊS EM PORTUGUÊS', 'new_amount': float}\n"
                        "14. Consultar Meta Específica: {'action': 'check_goal', 'category': str}\n"
                        "15. Listar Todas as Metas: {'action': 'list_goals'}\n"
                        "16. Apagar Último Gasto: {'action': 'delete_last'}\n"
                        "17. Apagar Conta/Fatura: {'action': 'delete_bill', 'description': str, 'month': 'MÊS EM PORTUGUÊS'}\n"
                        "18. Apagar Banco: {'action': 'delete_bank', 'bank': str}\n"
                        "19. Criar Categoria: {'action': 'create_category', 'category': str}\n"
                        "20. Alterar Categoria: {'action': 'update_category', 'old_category': str, 'new_category': str}\n"
                        "21. Deletar Categoria: {'action': 'delete_category', 'category': str}\n"
                        "22. Informar Apenas o Banco: {'action': 'provide_bank', 'bank': str}\n"
                        "23. Criar Banco: {'action': 'create_bank', 'bank': str}\n"
                        "24. Alterar Banco: {'action': 'update_bank', 'old_bank': str, 'new_bank': str}\n"
                        "Outros: {'action': 'chat'}"
                    )
                },
                {"role": "user", "content": text}
            ],
            response_format={"type": "json_object"},
            timeout=15
        )
        return json.loads(completion.choices[0].message.content)
    except Exception as e:
        print(f"Erro na IA: {e}", flush=True)
        return None

@app.route('/')
def index():
    return "ZapFinanceiro Online!", 200

@app.route('/set_webhook')
def set_webhook_route():
    base_url = request.url_root.replace("http://", "https://")
    webhook_url = f"{base_url}{TOKEN}"
    bot.remove_webhook()
    bot.set_webhook(url=webhook_url)
    return f"✅ Conexão com o Telegram resetada com sucesso para: {webhook_url}", 200

@app.route(f'/{TOKEN}', methods=['POST'])
def webhook():
    json_string = request.get_data().decode('utf-8')
    update = telebot.types.Update.de_json(json_string)
    bot.process_new_updates([update])
    return '', 200

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    global pending_user_actions
    chat_id = message.chat.id
    text = message.text or ""
    conn = None

    try:
        conn = get_db()
        cur = conn.cursor()
        cur.execute("SELECT id, name FROM users WHERE telegram_chat_id = %s", (int(chat_id),))
        user = cur.fetchone()
        
        # Como limpamos a tabela users com TRUNCATE, se seu user_id=1 sumiu do bot, nós auto-cadastramos para você não travar
        if not user:
            cur.execute("INSERT INTO users (id, name, email, password, telegram_chat_id) VALUES (1, 'Maique Anderson', 'maique@anilox.design', '123456', %s) ON CONFLICT DO NOTHING", (int(chat_id),))
            conn.commit()
            user_id = 1
        else:
            user_id = user[0]
        
        data = process_with_ai(text)
        action = data.get('action') if data else 'chat'

        # --- BLINDAGEM CONTRA VALORES VAZIOS E PADRONIZAÇÃO MAIÚSCULA ---
        if data:
            for key, value in data.items():
                if value is None:
                    data[key] = ""
                elif isinstance(value, str):
                    data[key] = value.strip()
            
            for key in ['category', 'old_category', 'new_category', 'bank', 'old_bank', 'new_bank', 'card']:
                if data.get(key):
                    data[key] = data[key].upper()

        if user_id in pending_user_actions:
            if action == 'provide_bank' or action == 'chat':
                banco_informado = data.get('bank') if (action == 'provide_bank' and data.get('bank')) else text.strip()
                pending_data = pending_user_actions.pop(user_id)
                pending_data['bank'] = banco_informado.upper()
                data = pending_data
                action = data.get('action')
            else:
                pending_user_actions.pop(user_id, None)
        
        hoje = datetime.utcnow() - timedelta(hours=3)
        bahia_now = "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '3 hours')"

        meses_pt = {1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho', 
                    7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'}
        
        meses_num = {v.lower(): k for k, v in meses_pt.items()}

        if data and data.get('month'):
            mes_original = str(data['month']).lower()
            traducao_meses = {
                'january': 'Janeiro', 'february': 'Fevereiro', 'march': 'Março', 'april': 'Abril',
                'may': 'Maio', 'june': 'Junho', 'july': 'Julho', 'august': 'Agosto',
                'september': 'Setembro', 'october': 'Outubro', 'november': 'Novembro', 'december': 'Dezembro',
                'jan': 'Janeiro', 'feb': 'Fevereiro', 'mar': 'Março', 'apr': 'Abril',
                'jun': 'Junho', 'jul': 'Julho', 'aug': 'Agosto', 'sep': 'Setembro',
                'oct': 'Outubro', 'nov': 'Novembro', 'dec': 'Dezembro'
            }
            if mes_original in traducao_meses:
                data['month'] = traducao_meses[mes_original]
            else:
                data['month'] = mes_original.capitalize()

        # --- GESTÃO DE BANCOS ---
        if action == 'create_bank':
            banco = data.get('bank')
            cur.execute("""
                INSERT INTO accounts (user_id, bank_name, balance) VALUES (%s, %s, 0)
            """, (user_id, banco))
            conn.commit()
            bot.reply_to(message, f"✅ Banco **{banco}** criado com sucesso e pronto para uso!", parse_mode="Markdown")

        elif action == 'update_bank':
            old_bank = data.get('old_bank')
            new_bank = data.get('new_bank')
            cur.execute("UPDATE accounts SET bank_name = %s WHERE user_id = %s AND bank_name ILIKE %s", (new_bank, user_id, f"%{old_bank}%"))
            if cur.rowcount > 0:
                conn.commit()
                bot.reply_to(message, f"✏️ O banco **{old_bank}** foi alterado para **{new_bank}** com sucesso!", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ Não encontrei o banco **{old_bank}** para alterar.", parse_mode="Markdown")

        elif action == 'delete_bank':
            banco = data.get('bank', '')
            cur.execute("DELETE FROM accounts WHERE user_id = %s AND bank_name ILIKE %s", (user_id, f"%{banco}%"))
            if cur.rowcount > 0:
                conn.commit()
                bot.reply_to(message, f"🏦 A conta do banco **{banco}** foi apagada com sucesso!", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ Não encontrei nenhum banco com o nome **{banco}** para apagar.", parse_mode="Markdown")

        # --- GESTÃO DE CATEGORIAS ---
        elif action == 'create_category':
            cat = data.get('category')
            cur.execute("INSERT INTO categories (user_id, name, type) VALUES (%s, %s, 'expense')", (user_id, cat))
            conn.commit()
            bot.reply_to(message, f"✅ Categoria **{cat}** criada com sucesso e pronta para uso!", parse_mode="Markdown")

        elif action == 'update_category':
            old_cat = data.get('old_category')
            new_cat = data.get('new_category')
            cur.execute("UPDATE transactions SET category = %s WHERE user_id = %s AND category ILIKE %s", (new_cat, user_id, f"%{old_cat}%"))
            trans_count = cur.rowcount
            cur.execute("UPDATE categories SET name = %s WHERE user_id = %s AND name ILIKE %s", (new_cat, user_id, f"%{old_cat}%"))
            conn.commit()
            if trans_count > 0 or cur.rowcount > 0:
                bot.reply_to(message, f"✏️ Categoria **{old_cat}** alterada para **{new_cat}** com sucesso!", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ Não encontrei a categoria **{old_cat}** para alterar.", parse_mode="Markdown")

        elif action == 'delete_category':
            cat = data.get('category')
            cur.execute("UPDATE transactions SET category = 'GERAL' WHERE user_id = %s AND category ILIKE %s", (user_id, f"%{cat}%"))
            cur.execute("DELETE FROM categories WHERE user_id = %s AND name ILIKE %s", (user_id, f"%{cat}%"))
            conn.commit()
            bot.reply_to(message, f"🗑️ Categoria **{cat}** deletada!\n⚠️ *Os gastos antigos foram movidos para a categoria 'GERAL'.*", parse_mode="Markdown")

        # --- FUNÇÃO: APAGAR ÚLTIMO GASTO ---
        elif action == 'delete_last':
            cur.execute("SELECT id, amount, description FROM transactions WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
            last_tx = cur.fetchone()
            if last_tx:
                tx_id, valor, desc = last_tx
                cur.execute("DELETE FROM transactions WHERE id = %s", (tx_id,))
                conn.commit()
                bot.reply_to(message, f"🗑️ **Último gasto apagado com sucesso!**\n\n💸 Descrição: {desc}\n💰 Valor: R$ {valor:.2f}\n\n⚠️ *Dica: Se este gasto descontou saldo do banco, lembre-se de adicionar o valor de volta manualmente.*", parse_mode="Markdown")
            else:
                bot.reply_to(message, "Não encontrei nenhum gasto recente para apagar.")

        # --- FUNÇÃO CORRIGIDA: APAGAR CONTA/FATURA ---
        elif action == 'delete_bill':
            desc = data.get('description', '')
            mes = data.get('month', '')
            if not mes:
                mes = meses_pt[hoje.month]
            mes_alvo = meses_num.get(mes.lower(), hoje.month)
            
            cur.execute("""
                DELETE FROM unpaid_bills 
                WHERE user_id = %s AND description ILIKE %s AND EXTRACT(MONTH FROM due_date) = %s
            """, (user_id, f"%{desc}%", mes_alvo))
            
            if cur.rowcount > 0:
                conn.commit()
                bot.reply_to(message, f"🗑️ A conta **'{desc}'** do mês de **{mes}** foi excluída!", parse_mode="Markdown")
            else:
                cur.execute("""
                    DELETE FROM scheduled_expenses 
                    WHERE user_id = %s AND description ILIKE %s AND EXTRACT(MONTH FROM due_date) = %s
                """, (user_id, f"%{desc}%", mes_alvo))
                if cur.rowcount > 0:
                    conn.commit()
                    bot.reply_to(message, f"🗑️ A fatura/compra **'{desc}'** do mês de **{mes}** foi excluída!", parse_mode="Markdown")
                else:
                    bot.reply_to(message, f"❌ Não encontrei nenhuma conta ou fatura '{desc}' em {mes} para apagar.")

        # --- FUNÇÃO CORRIGIDA: COMPRA CARTÃO DE CRÉDITO (TABELA: scheduled_expenses) ---
        elif action == 'add_credit_card_purchase':
            total = float(data.get('amount', 0.0))
            parcelas = int(data.get('installments') or 1)
            if parcelas < 1: parcelas = 1
            cartao = data.get('card', 'CARTÃO DE CRÉDITO')
            desc_original = data.get('description', 'Compra Cartão')
            
            valor_parcela = total / parcelas
            
            for i in range(parcelas):
                mes_futuro = hoje.month + i + 1
                ano_futuro = ServerAno = hoje.year + (mes_futuro - 1) // 12
                mes_num = (mes_futuro - 1) % 12 + 1
                
                vencimento = datetime(ano_futuro, mes_num, 10)
                nova_desc = f"{desc_original} ({i+1}/{parcelas})"
                
                # Inserção correta na tabela scheduled_expenses recriada
                cur.execute("""
                    INSERT INTO scheduled_expenses (user_id, amount, description, is_active, card_name, due_date) 
                    VALUES (%s, %s, %s, true, %s, %s)
                """, (user_id, valor_parcela, nova_desc, cartao, vencimento))
            
            conn.commit()
            if parcelas == 1:
                bot.reply_to(message, f"💳 Compra à vista de R$ {total:.2f} no cartão {cartao} lançada com sucesso!", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"💳 Compra parcelada de R$ {total:.2f} anotada! Lançada em {parcelas}x de R$ {valor_parcela:.2f} na fatura.", parse_mode="Markdown")

        # --- AÇÕES DE GASTOS, RECEITAS E METAS ---
        elif action == 'add_income':
            bank = data.get('bank', 'GERAL')
            cur.execute("""
                INSERT INTO accounts (user_id, bank_name, balance) VALUES (%s, %s, %s) 
                ON CONFLICT (user_id, bank_name) DO UPDATE SET balance = accounts.balance + EXCLUDED.balance
            """, (user_id, bank, data['amount']))
            conn.commit()
            bot.reply_to(message, f"💰 R$ {data['amount']:.2f} adicionados ao {bank}!")

        elif action == 'set_goal':
            cur.execute("""
                INSERT INTO category_goals (user_id, category, goal_amount) VALUES (%s, %s, %s)
                ON CONFLICT (category) DO UPDATE SET goal_amount = EXCLUDED.goal_amount
            """, (user_id, data['category'], data['amount']))
            conn.commit()
            bot.reply_to(message, f"🎯 Meta de R$ {data['amount']:.2f} para a categoria **{data['category']}** definida com sucesso!", parse_mode="Markdown")

        elif action == 'add_expense':
            if not data.get('bank') or data.get('bank') == '':
                pending_user_actions[user_id] = data
                bot.reply_to(message, "🏦 Você esqueceu de me dizer o banco! De qual banco devo descontar esse gasto?")
                return

            cur.execute("INSERT INTO transactions (user_id, amount, category, description, type) VALUES (%s, %s, %s, %s, 'expense')",
                        (user_id, data['amount'], data['category'], data['description']))
            cur.execute("UPDATE accounts SET balance = balance - %s WHERE user_id = %s AND bank_name ILIKE %s",
                        (data['amount'], user_id, f"%{data['bank']}%"))
            conn.commit()
            
            reply_msg = f"✅ Gasto de R$ {data['amount']:.2f} salvo em {data['category']} descontado do {data['bank']}!"
            bot.reply_to(message, reply_msg)

        elif action == 'check_goal':
            cat = data.get('category', '')
            cur.execute("SELECT goal_amount FROM category_goals WHERE user_id = %s AND category ILIKE %s", (user_id, f"%{cat}%"))
            goal_res = cur.fetchone()
            if goal_res:
                meta = float(goal_res[0])
                cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id = %s AND category ILIKE %s AND date >= date_trunc('month', CURRENT_DATE)", (user_id, f"%{cat}%"))
                total_gasto = float(cur.fetchone()[0] or 0)
                restante = meta - total_gasto
                
                mensagem = f"🎯 **Resumo da Meta: {cat}**\n\n🔸 **Sua Meta:** R$ {meta:.2f}\n💸 **Total Gasto:** R$ {total_gasto:.2f}\n"
                mensagem += f"✅ **Ainda pode gastar:** R$ {restante:.2f}" if restante >= 0 else f"⚠️ **Passou da meta em:** R$ {abs(restante):.2f}"
                bot.reply_to(message, mensagem.replace('.', ','), parse_mode="Markdown")
            else:
                bot.reply_to(message, f"Você ainda não definiu nenhuma meta para a categoria **{cat}**.")

        # --- NOVAS FUNÇÕES COMPATÍVEIS ---
        elif action == 'list_goals':
            cur.execute("SELECT category, goal_amount FROM category_goals WHERE user_id = %s AND goal_amount > 0 ORDER BY category", (user_id,))
            metas = cur.fetchall()
            if metas:
                mensagem = "🎯 **Resumo de Todas as Metas:**\n\n"
                total_livre = 0.0
                for cat, meta in metas:
                    meta = float(meta)
                    cur.execute("SELECT SUM(amount) FROM transactions WHERE user_id = %s AND category ILIKE %s AND date >= date_trunc('month', CURRENT_DATE)", (user_id, f"%{cat}%"))
                    gasto = float(cur.fetchone()[0] or 0)
                    restante = meta - gasto
                    mensagem += f"🔸 **{cat}** (Meta: R$ {meta:.2f})\n"
                    if restante >= 0:
                        mensagem += f"✅ Resta: R$ {restante:.2f}\n\n"
                        total_livre += restante
                    else:
                        mensagem += f"⚠️ Ultrapassou: -R$ {abs(restante):.2f}\n\n"
                mensagem += f"✅ **Valor total a ser gasto em todas as metas:** R$ {total_livre:.2f}"
                bot.reply_to(message, mensagem.replace('.', ','), parse_mode="Markdown")
            else:
                bot.reply_to(message, "Você ainda não tem metas cadastradas.")

        # --- GESTÃO ADAPTADA: ADICIONAR CONTA A PAGAR (TABELA: unpaid_bills) ---
        elif action == 'add_bill':
            mes = data.get('month') or meses_pt[hoje.month]
            categoria = data.get('category', 'GERAL')
            mes_alvo = meses_num.get(mes.lower(), hoje.month)
            vencimento = datetime(hoje.year, mes_alvo, 10)
            
            cur.execute("""
                INSERT INTO unpaid_bills (user_id, amount, category, description, due_date, is_paid) 
                VALUES (%s, %s, %s, %s, %s, false)
            """, (user_id, data['amount'], categoria, data['description'], vencimento))
            conn.commit()
            bot.reply_to(message, f"🧾 Conta/Fatura de {data['month']} anotada com sucesso e visível no seu Dashboard!")

        # --- GESTÃO ADAPTADA: LISTAR CONTAS A PAGAR (UNIFICADO) ---
        elif action == 'list_bills':
            mes = data.get('month') or meses_pt[hoje.month]
            mes_alvo = meses_num.get(mes.lower(), hoje.month)
            
            # Busca contas em unpaid_bills
            cur.execute("SELECT description, amount FROM unpaid_bills WHERE user_id = %s AND is_paid = false AND EXTRACT(MONTH FROM due_date) = %s", (user_id, mes_alvo))
            contas = cur.fetchall()
            
            # Busca parcelas de cartão em scheduled_expenses
            cur.execute("SELECT description, amount, card_name FROM scheduled_expenses WHERE user_id = %s AND is_active = true AND EXTRACT(MONTH FROM due_date) = %s", (user_id, mes_alvo))
            cartoes = cur.fetchall()
            
            if contas or cartoes:
                total_mes = 0.0
                mensagem = f"⏳ **Contas a pagar pendentes ({mes}):**\n"
                for desc, amount in contas:
                    mensagem += f"• {desc}: R$ {float(amount):.2f}\n"
                    total_mes += float(amount)
                for desc, amount, card in cartoes:
                    mensagem += f"• [{card}] {desc}: R$ {float(amount):.2f}\n"
                    total_mes += float(amount)
                
                mensagem += f"\n✅ **Valor total a ser pago:** R$ {total_mes:.2f}"
                bot.reply_to(message, mensagem.replace('.', ','), parse_mode="Markdown")
            else:
                bot.reply_to(message, f"✅ Nenhuma conta a pagar pendente para {mes}.")

        # --- OUTROS RELATÓRIOS E SALDOS ---
        elif action == 'get_balance':
            cur.execute("SELECT bank_name, balance FROM accounts WHERE user_id = %s ORDER BY bank_name", (user_id,))
            rows = cur.fetchall()
            if rows:
                total_saldo = sum([float(r[1]) for r in rows])
                msg = "\n".join([f"🏦 {r[0]}: R$ {float(r[1]):.2f}".replace('.', ',') for r in rows])
                resposta = f"💰 **Seus Saldos:**\n{msg}\n\n✅ **Saldo total:** R$ {total_saldo:.2f}".replace('.', ',')
                bot.reply_to(message, resposta, parse_mode="Markdown")
            else:
                bot.reply_to(message, "Você ainda não tem saldos cadastrados nos bancos.")

        else:
            bot.reply_to(message, f"Oi Maique! Como posso ajudar?")

    except Exception as e:
        erro_msg = traceback.format_exc()
        print(f"Erro Crítico: {erro_msg}", flush=True)
        bot.reply_to(message, "Oops! Houve um erro interno de estrutura. Tente novamente!")
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)