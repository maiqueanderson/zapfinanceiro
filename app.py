elif action == 'list_bills':
            # Garantimos que existe um mês para pesquisar, senão usamos o mês atual
            mes = data.get('month') or datetime.now().strftime('%B')
            
            try:
                # Consulta otimizada: buscamos apenas faturas ativas do usuário
                cur.execute(
                    "SELECT description, amount FROM scheduled_expenses WHERE user_id = %s AND is_active = true AND description ILIKE %s",
                    (user_id, f"%{mes}%")
                )
                faturas = cur.fetchall()
                
                if faturas:
                    # Usamos uma lista simples para evitar processamento pesado de strings
                    lista = [f"• {f[0]}: R$ {f[1]:.2f}" for f in faturas]
                    resposta = f"⏳ **Faturas pendentes ({mes}):**\n" + "\n".join(lista)
                    bot.reply_to(message, resposta, parse_mode="Markdown")
                else:
                    bot.reply_to(message, f"🙌 Não encontrei faturas pendentes para {mes}.")
            except Exception as e:
                print(f"Erro ao listar faturas: {e}")
                bot.reply_to(message, "Houve um erro ao buscar suas faturas.")