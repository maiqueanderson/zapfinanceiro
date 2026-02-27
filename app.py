import os
import telebot
from flask import Flask, request
import psycopg2
from groq import Groq
import json
from datetime import datetime, timedelta

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
                        "4. Fatura Simples ou Conta: {'action': 'add_bill', 'amount': float, 'description': str, 'month': 'MÊS EM PORTUGUÊS'}\n"
                        "5. Compra Parcelada: {'action': 'add_installment', 'total_amount': float, 'installments': int, 'description': str, 'card': str}\n"
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
        
        hoje = datetime.utcnow() - timedelta(hours=3)
        bahia_now = "(CURRENT_TIMESTAMP AT TIME ZONE 'UTC' - INTERVAL '3 hours')"

        meses_pt = {1: 'Janeiro', 2: 'Fevereiro', 3: 'Março', 4: 'Abril', 5: 'Maio', 6: 'Junho', 
                    7: 'Julho', 8: 'Agosto', 9: 'Setembro', 10: 'Outubro', 11: 'Novembro', 12: 'Dezembro'}

        # --- PADRONIZADOR DE CATEGORIAS PARA MAIÚSCULO ---
        if data:
            for key in ['category', 'old_category', 'new_category']:
                if data.get(key):
                    data[key] = str(data[key]).upper().strip()

        # --- TRADUTOR AUTOMÁTICO DE MESES ---
        if data and data.get('month'):
            mes_original = str(data['month']).lower().strip()
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

        # --- NOVAS FUNÇÕES DE GESTÃO DE CATEGORIAS ---
        if action == 'create_category':
            cat = data.get('category')
            # Registra uma meta zerada apenas para forçar a existência da categoria no banco
            cur.execute("""
                INSERT INTO category_goals (user_id, category, goal_amount) VALUES (%s, %s, 0)
                ON CONFLICT (user_id, category) DO NOTHING
            """, (user_id, cat))
            conn.commit()
            bot.reply_to(message, f"✅ Categoria **{cat}** criada com sucesso e pronta para uso!", parse_mode="Markdown")

        elif action == 'update_category':
            old_cat = data.get('old_category')
            new_cat = data.get('new_category')
            
            # Atualiza transações e metas antigas para o nome novo
            cur.execute("UPDATE transactions SET category = %s WHERE user_id = %s AND category ILIKE %s", (new_cat, user_id, f"%{old_cat}%"))
            trans_count = cur.rowcount
            
            cur.execute("UPDATE category_goals SET category = %s WHERE user_id = %s AND category ILIKE %s", (new_cat, user_id, f"%{old_cat}%"))
            goal_count = cur.rowcount
            
            conn.commit()
            if trans_count > 0 or goal_count > 0:
                bot.reply_to(message, f"✏️ Categoria **{old_cat}** alterada para **{new_cat}** com sucesso!", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ Não encontrei a categoria **{old_cat}** para alterar.", parse_mode="Markdown")

        elif action == 'delete_category':
            cat = data.get('category')
            
            # Move gastos para 'GERAL' e deleta a meta
            cur.execute("UPDATE transactions SET category = 'GERAL' WHERE user_id = %s AND category ILIKE %s", (user_id, f"%{cat}%"))
            trans_count = cur.rowcount
            
            cur.execute("DELETE FROM category_goals WHERE user_id = %s AND category ILIKE %s", (user_id, f"%{cat}%"))
            
            conn.commit()
            if trans_count > 0 or cur.rowcount > 0:
                bot.reply_to(message, f"🗑️ Categoria **{cat}** deletada!\n⚠️ *Para não bagunçar seus relatórios, os gastos antigos que estavam nela foram movidos para a categoria 'GERAL'.*", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ Não encontrei a categoria **{cat}** para deletar.", parse_mode="Markdown")


        # --- FUNÇÃO: APAGAR ÚLTIMO GASTO ---
        elif action == 'delete_last':
            cur.execute("SELECT id, amount, description FROM transactions WHERE user_id = %s ORDER BY id DESC LIMIT 1", (user_id,))
            last_tx = cur.fetchone()
            
            if last_tx:
                tx_id = last_tx[0]
                valor = last_tx[1]
                desc = last_tx[2]
                
                cur.execute("DELETE FROM transactions WHERE id = %s", (tx_id,))
                conn.commit()
                bot.reply_to(message, f"🗑️ **Último gasto apagado com sucesso!**\n\n💸 Descrição: {desc}\n💰 Valor: R$ {valor:.2f}\n\n⚠️ *Dica: Se este gasto havia descontado saldo de algum banco, lembre-se de adicionar o valor de volta manualmente (ex: 'Adicione {valor:.2f} no Nubank').*", parse_mode="Markdown")
            else:
                bot.reply_to(message, "Não encontrei nenhum gasto recente para apagar.")

        # --- FUNÇÃO: APAGAR CONTA/FATURA ---
        elif action == 'delete_bill':
            desc = data.get('description', '')
            mes = data.get('month', '')
            
            cur.execute("SELECT id, amount FROM scheduled_expenses WHERE user_id = %s AND description ILIKE %s AND description ILIKE %s",
                        (user_id, f"%{desc}%", f"%{mes}%"))
            res = cur.fetchone()
            
            if res:
                cur.execute("DELETE FROM scheduled_expenses WHERE id = %s", (res[0],))
                conn.commit()
                bot.reply_to(message, f"🗑️ A conta/fatura **'{desc}'** do mês de **{mes}** (R$ {res[1]:.2f}) foi excluída com sucesso!", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ Não encontrei nenhuma conta/fatura com o nome '{desc}' no mês de {mes} para apagar.")

        # --- FUNÇÃO: APAGAR BANCO ---
        elif action == 'delete_bank':
            banco = data.get('bank', '')
            
            cur.execute("DELETE FROM accounts WHERE user_id = %s AND bank_name ILIKE %s", (user_id, f"%{banco}%"))
            
            if cur.rowcount > 0:
                conn.commit()
                bot.reply_to(message, f"🏦 A conta do banco **{banco.capitalize()}** foi apagada com sucesso!", parse_mode="Markdown")
            else:
                bot.reply_to(message, f"❌ Não encontrei nenhum banco com o nome **{banco.capitalize()}** para apagar.")

        # --- FUNÇÃO: COMPRA PARCELADA ---
        elif action == 'add_installment':
            total = data.get('total_amount', 0.0)
            parcelas = data.get('installments', 1)
            desc = data.get('description', 'Compra')
            cartao = data.get('card', 'Cartão')
            
            valor_parcela = total / parcelas
            
            for i in range(parcelas):
                m = hoje.month + i + 1
                ano = hoje.year + (m - 1) // 12
                mes_num = (m - 1) % 12 + 1
                nome_mes_ano = f"{meses_pt[mes_num]}/{ano}"
                
                desc_completa = f"{desc} (Parcela {i+1}/{parcelas}) - Fatura {cartao} - {nome_mes_ano}"
                
                cur.execute("INSERT INTO scheduled_expenses (user_id, amount, description, is_active) VALUES (%s, %s, %s, true)",
                            (user_id, valor_parcela, desc_completa))
            
            conn.commit()
            bot.reply_to(message, f"💳 Compra parcelada de R$ {total:.2f} anotada!\nDividida em {parcelas}x de R$ {valor_parcela:.2f} no cartão {cartao}, começando a partir do próximo mês.")

        # --- AÇÕES DE GASTOS, RECEITAS E METAS ---
        elif action == 'add_income':
            bank = data.get('bank', 'Geral')
            cur.execute("""
                INSERT INTO accounts (user_id, bank_name, balance) VALUES (%s, %s, %s) 
                ON CONFLICT (user_id, bank_name) DO UPDATE SET balance = accounts.balance + EXCLUDED.balance
            """, (user_id, bank, data['amount']))
            conn.commit()
            bot.reply_to(message, f"💰 R$ {data['amount']:.2f} adicionados ao {bank}!")

        elif action == 'set_goal':
            cur.execute("""
                INSERT INTO category_goals (user_id, category, goal_amount) VALUES (%s, %s, %s)
                ON CONFLICT (user_id, category) DO UPDATE SET goal_amount = EXCLUDED.goal_amount
            """, (user_id, data['category'], data['amount']))
            conn.commit()
            bot.reply_to(message, f"🎯 Meta de R$ {data['amount']:.2f} para a categoria **{data['category']}** definida com sucesso!", parse_mode="Markdown")

        elif action == 'add_expense':
            cur.execute("INSERT INTO transactions (user_id, amount, category, description) VALUES (%s, %s, %s, %s)",
                        (user_id, data['amount'], data['category'], data['description']))
            if data.get('bank'):
                cur.execute("UPDATE accounts SET balance = balance - %s WHERE user_id = %s AND bank_name ILIKE %s",
                            (data['amount'], user_id, f"%{data['bank']}%"))
            conn.commit()
            
            reply_msg = f"✅ Gasto de R$ {data['amount']:.2f} salvo em {data['category']}!"

            cur.execute("SELECT goal_amount FROM category_goals WHERE user_id = %s AND category ILIKE %s", (user_id, f"%{data['category']}%"))
            goal_res = cur.fetchone()
            
            if goal_res:
                meta = goal_res[0]
                cur.execute(f"SELECT SUM(amount) FROM transactions WHERE user_id = %s AND category ILIKE %s AND date >= date_trunc('month', {bahia_now})", 
                            (user_id, f"%{data['category']}%"))
                total_gasto = cur.fetchone()[0] or 0
                diferenca = meta - total_gasto
                
                if diferenca >= 0:
                    reply_msg += f"\n🎯 Meta: Você ainda possui R$ {diferenca:.2f} para gastar nesta categoria."
                else:
                    reply_msg += f"\n⚠️ Atenção: Você ultrapassou R$ {abs(diferenca):.2f} da sua meta nesta categoria!"

            bot.reply_to(message, reply_msg)

        elif action == 'check_goal':
            cat = data.get('category')
            
            cur.execute("SELECT goal_amount FROM category_goals WHERE user_id = %s AND category ILIKE %s", (user_id, f"%{cat}%"))
            goal_res = cur.fetchone()
            
            if goal_res:
                meta = float(goal_res[0])
                
                cur.execute(f"SELECT SUM(amount) FROM transactions WHERE user_id = %s AND category ILIKE %s AND date >= date_trunc('month', {bahia_now})", 
                            (user_id, f"%{cat}%"))
                total_gasto = float(cur.fetchone()[0] or 0)
                
                restante = meta - total_gasto
                
                meta_fmt = f"{meta:.2f}".replace('.', ',')
                gasto_fmt = f"{total_gasto:.2f}".replace('.', ',')
                restante_fmt = f"{restante:.2f}".replace('.', ',')
                
                mensagem = f"🎯 **Resumo da Meta: {cat}**\n\n"
                mensagem += f"🔸 **Sua Meta:** R$ {meta_fmt}\n"
                mensagem += f"💸 **Total Gasto:** R$ {gasto_fmt}\n"
                
                if restante >= 0:
                    mensagem += f"✅ **Ainda pode gastar:** R$ {restante_fmt}"
                else:
                    mensagem += f"⚠️ **Passou da meta em:** R$ {abs(restante):.2f}".replace('.', ',')
                    
                bot.reply_to(message, mensagem, parse_mode="Markdown")
            else:
                bot.reply_to(message, f"Você ainda não definiu nenhuma meta para a categoria **{cat}**.")

        elif action == 'list_goals':
            # Agora busca apenas metas que têm valores reais (maior que zero)
            cur.execute("SELECT category, goal_amount FROM category_goals WHERE user_id = %s AND goal_amount > 0 ORDER BY category", (user_id,))
            metas = cur.fetchall()
            
            if metas:
                mensagem = "🎯 **Resumo de Todas as Metas:**\n\n"
                total_livre = 0.0
                
                for cat, meta in metas:
                    meta = float(meta)
                    cur.execute(f"SELECT SUM(amount) FROM transactions WHERE user_id = %s AND category ILIKE %s AND date >= date_trunc('month', {bahia_now})", 
                                (user_id, f"%{cat}%"))
                    gasto = float(cur.fetchone()[0] or 0)
                    restante = meta - gasto
                    
                    meta_str = f"{meta:.2f}".replace('.', ',')
                    restante_str = f"{restante:.2f}".replace('.', ',')
                    
                    mensagem += f"🔸 **{cat}** (Meta: R$ {meta_str})\n"
                    
                    if restante >= 0:
                        mensagem += f"✅ Resta: R$ {restante_str}\n\n"
                        total_livre += restante 
                    else:
                        mensagem += f"⚠️ Ultrapassou: -R$ {abs(restante):.2f}".replace('.', ',') + "\n\n"
                
                total_livre_str = f"{total_livre:.2f}".replace('.', ',')
                mensagem += f"✅ **Valor total a ser gasto em todas as metas:** R$ {total_livre_str}"
                
                bot.reply_to(message, mensagem, parse_mode="Markdown")
            else:
                bot.reply_to(message, "Você ainda não tem metas cadastradas.")

        # --- NOVAS FUNÇÕES: CATEGORIAS ---
        elif action == 'report_category':
            cat = data.get('category')
            period = data.get('period', 'month')
            
            query = f"SELECT SUM(amount) FROM transactions WHERE user_id = %s AND category ILIKE %s AND "
            if period == 'today':
                query += f"date::date = {bahia_now}::date"
                label = "hoje"
            elif period == 'week':
                query += f"date >= date_trunc('week', {bahia_now})"
                label = "esta semana"
            else:
                query += f"date >= date_trunc('month', {bahia_now})"
                label = "este mês"
            
            cur.execute(query, (user_id, f"%{cat}%"))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"🔍 Gastos com **{cat}** ({label}):\n💰 R$ {total:.2f}", parse_mode="Markdown")

        elif action == 'list_categories':
            # Busca todas as categorias (tanto dos gastos quanto das criadas sem gastos ainda)
            cur.execute("""
                SELECT DISTINCT category FROM (
                    SELECT category FROM transactions WHERE user_id = %s
                    UNION
                    SELECT category FROM category_goals WHERE user_id = %s
                ) AS cats ORDER BY category
            """, (user_id, user_id))
            cats = cur.fetchall()
            
            if cats:
                msg = "📂 **Suas categorias cadastradas:**\n" + "\n".join([f"• {c[0]}" for c in cats])
                bot.reply_to(message, msg, parse_mode="Markdown")
            else:
                bot.reply_to(message, "Você ainda não tem categorias registadas.")

        # --- GESTÃO DE CONTAS A PAGAR E FATURAS ---
        elif action == 'add_bill':
            cur.execute("INSERT INTO scheduled_expenses (user_id, amount, description, is_active) VALUES (%s, %s, %s, true)",
                        (user_id, data['amount'], f"{data['description']} - {data['month']}",))
            conn.commit()
            bot.reply_to(message, f"🧾 Conta/Fatura de {data['month']} anotada com sucesso!")

        elif action == 'list_bills':
            mes = data.get('month') or meses_pt[hoje.month]
            cur.execute("SELECT description, amount FROM scheduled_expenses WHERE user_id = %s AND is_active = true AND description ILIKE %s",
                        (user_id, f"%{mes}%"))
            faturas = cur.fetchall()
            if faturas:
                agrupado = {}
                total_mes = 0.0
                
                for desc, amount in faturas:
                    if " - Fatura " in desc:
                        chave = "Fatura " + desc.split(" - Fatura ")[1]
                    else:
                        chave = desc
                    
                    valor = float(amount)
                    agrupado[chave] = agrupado.get(chave, 0) + valor
                    total_mes += valor

                lista = "\n".join([f"• {k}: R$ {v:.2f}".replace('.', ',') for k, v in agrupado.items()])
                total_formatado = f"{total_mes:.2f}".replace('.', ',')
                
                mensagem = f"⏳ **Contas a pagar pendentes ({mes}):**\n{lista}\n\n✅ **Valor total a ser pago:** R$ {total_formatado}"
                bot.reply_to(message, mensagem, parse_mode="Markdown")
            else:
                bot.reply_to(message, f"✅ Nenhuma conta a pagar pendente para {mes}.")

        elif action == 'total_bills':
            mes = data.get('month') or meses_pt[hoje.month]
            cur.execute("SELECT SUM(amount) FROM scheduled_expenses WHERE user_id = %s AND is_active = true AND description ILIKE %s",
                        (user_id, f"%{mes}%"))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"💰 O valor total de contas a pagar pendentes para {mes} é:\nR$ {total:.2f}".replace('.', ','))

        elif action == 'pay_bill':
            desc, mes, bank = data.get('description', ''), data.get('month', ''), data.get('bank')
            cur.execute("SELECT SUM(amount) FROM scheduled_expenses WHERE user_id = %s AND description ILIKE %s AND description ILIKE %s AND is_active = true",
                        (user_id, f"%{desc}%", f"%{mes}%"))
            res = cur.fetchone()
            if res and res[0] is not None:
                total_pago = res[0]
                cur.execute("UPDATE scheduled_expenses SET is_active = false WHERE user_id = %s AND description ILIKE %s AND description ILIKE %s AND is_active = true",
                            (user_id, f"%{desc}%", f"%{mes}%"))
                if bank:
                    cur.execute("UPDATE accounts SET balance = balance - %s WHERE user_id = %s AND bank_name ILIKE %s",
                                (total_pago, user_id, f"%{bank}%"))
                conn.commit()
                bot.reply_to(message, f"✔️ Fatura/Conta paga com {bank}! O valor total de R$ {total_pago:.2f} foi descontado do seu saldo.")
            else:
                bot.reply_to(message, "Conta a pagar não encontrada.")

        elif action == 'update_bill':
            desc = data.get('description', '')
            mes = data.get('month', '')
            novo_valor = data.get('new_amount', 0.0)
            
            cur.execute("SELECT id FROM scheduled_expenses WHERE user_id = %s AND description ILIKE %s AND description ILIKE %s AND is_active = true",
                        (user_id, f"%{desc}%", f"%{mes}%"))
            res = cur.fetchone()
            
            if res:
                cur.execute("UPDATE scheduled_expenses SET amount = %s WHERE id = %s", (novo_valor, res[0]))
                conn.commit()
                bot.reply_to(message, f"✏️ O valor da fatura/conta '{desc}' de {mes} foi alterado para R$ {novo_valor:.2f}.")
            else:
                bot.reply_to(message, f"❌ Não encontrei nenhuma fatura ou conta pendente de '{desc}' no mês de {mes}.")

        # --- OUTROS RELATÓRIOS E SALDOS ---
        elif action == 'get_balance':
            cur.execute("SELECT bank_name, balance FROM accounts WHERE user_id = %s", (user_id,))
            rows = cur.fetchall()
            
            if rows:
                total_saldo = sum([float(r[1]) for r in rows])
                msg = "\n".join([f"🏦 {r[0]}: R$ {float(r[1]):.2f}".replace('.', ',') for r in rows])
                total_formatado = f"{total_saldo:.2f}".replace('.', ',')
                
                resposta = f"💰 **Seus Saldos:**\n{msg}\n\n✅ **Saldo total:** R$ {total_formatado}"
                bot.reply_to(message, resposta, parse_mode="Markdown")
            else:
                bot.reply_to(message, "Você ainda não tem saldos cadastrados nos bancos.")

        elif action == 'get_report':
            period = data.get('period', 'today')
            base_query = "SELECT SUM(amount) FROM transactions WHERE user_id = %s AND "
            
            if period == 'yesterday':
                query = base_query + f"date::date = ({bahia_now} - INTERVAL '1 day')::date"
                label = "ontem"
            elif period == 'week':
                query = base_query + f"date >= date_trunc('week', {bahia_now})"
                label = "esta semana"
            elif period == 'month':
                query = base_query + f"date >= date_trunc('month', {bahia_now})"
                label = "este mês"
            else:
                query = base_query + f"date::date = {bahia_now}::date"
                label = "hoje"
                
            cur.execute(query, (user_id,))
            total = cur.fetchone()[0] or 0
            bot.reply_to(message, f"📊 Total de {label}: R$ {total:.2f}")

        else:
            bot.reply_to(message, f"Oi Maique! Como posso ajudar?")

    except Exception as e:
        bot.reply_to(message, f"Erro: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    port = int(os.environ.get('PORT', 10000))
    app.run(host="0.0.0.0", port=port)