"""Finanças Casa — versão web (celular e computador). Usa o mesmo banco do app do computador."""
import hashlib
import hmac
import time
import uuid
from datetime import date
from decimal import Decimal

import pandas as pd
import psycopg2
import streamlit as st

import nucleo as N

st.set_page_config(page_title="Finanças Casa", page_icon="💰", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
.block-container {padding-top: 1.4rem; padding-bottom: 3rem;}
@media (max-width: 640px) {.block-container {padding-left: .7rem; padding-right: .7rem;}}
.card-t {color: #9aa0a6; font-size: .85rem;}
.card-v {font-size: 1.7rem; font-weight: 700; line-height: 1.25;}
.card-d {color: #9aa0a6; font-size: .8rem;}
</style>""", unsafe_allow_html=True)

TELAS = ["Lançamentos", "Contas a pagar", "Cartões", "Metas", "Relatório mensal", "Conselheiro", "Configurações"]
COR = {"vermelho": N.VERMELHO, "amarelo": N.AMARELO, "verde": N.VERDE}
DIAS_LOGADO = 60


# ----------------------------------------------------------------- infra
@st.cache_resource
def _preparar(dsn):
    N.Banco(dsn).preparar()
    return True


def db():
    dsn = st.secrets["DSN"]
    _preparar(dsn)
    if "db" not in st.session_state:
        st.session_state.db = N.Banco(dsn)
    return st.session_state.db


def rodar(fn, ok=None):
    """Executa uma ação; mostra erro amigável ou recarrega a tela com mensagem de sucesso."""
    try:
        fn()
    except N.pg_erros.ForeignKeyViolation:
        st.error("Este registro está em uso e não pode ser excluído.")
        return
    except N.pg_erros.UniqueViolation:
        st.error("Já existe um cadastro com esse nome.")
        return
    except psycopg2.Error as e:
        st.error(f"Erro no banco de dados: {e}")
        return
    except ValueError as e:
        st.error(str(e))
        return
    if ok:
        st.session_state.flash = ok
    st.rerun()


def tabela(linhas, colunas, key, altura=None):
    """Tabela com seleção de uma linha; devolve o índice selecionado ou None."""
    df = pd.DataFrame(linhas, columns=colunas)
    kw = {"height": altura} if altura else {}
    ev = st.dataframe(df, hide_index=True, on_select="rerun", selection_mode="single-row", key=key, **kw)
    sel = ev.selection.rows if ev is not None else []
    return sel[0] if sel else None


def categorias(tipo):
    return {n: i for i, n in db().todos("SELECT id, nome FROM categorias WHERE tipo = %s ORDER BY nome", (tipo,))}


def mes():
    return st.session_state.mes


def nome_mes(m):
    return f"{N.MESES[m.month - 1]}/{m.year}"


def data_padrao():
    hoje = date.today()
    return hoje if (hoje.year, hoje.month) == (mes().year, mes().month) else mes()


def texto_obrigatorio(txt, campo):
    txt = (txt or "").strip()
    if not txt:
        raise ValueError(f"Informe {campo}.")
    return txt


def valor_positivo(txt, campo="o valor"):
    if not (txt or "").strip():
        raise ValueError(f"Informe {campo}.")
    v = N.parse_valor(txt)
    if v <= 0:
        raise ValueError("O valor deve ser maior que zero.")
    return v


# ----------------------------------------------------------------- login
def _assinatura(uid, exp, senha_hash):
    chave = (st.secrets.get("CHAVE", "") + st.secrets["DSN"] + senha_hash).encode()
    return hmac.new(chave, f"{uid}.{exp}".encode(), hashlib.sha256).hexdigest()[:40]


def gerar_token(uid, senha_hash):
    exp = int(time.time()) + DIAS_LOGADO * 86400
    return f"{uid}.{exp}.{_assinatura(uid, exp, senha_hash)}"


def usuario_atual():
    u = st.session_state.get("usuario")
    if u:
        return u
    tok = st.query_params.get("t")
    if not tok:
        return None
    try:
        uid, exp, sig = tok.split(".")
        if int(exp) < time.time():
            return None
        r = db().um("SELECT id, nome, login, senha_hash FROM usuarios WHERE id = %s", (int(uid),))
        if r and hmac.compare_digest(sig, _assinatura(int(uid), int(exp), r[3])):
            st.session_state.usuario = {"id": r[0], "nome": r[1], "login": r[2]}
            return st.session_state.usuario
    except (ValueError, psycopg2.Error):
        pass
    return None


def entrar(login, senha):
    r = db().um("SELECT id, nome, login, senha_hash FROM usuarios WHERE login = %s", (login.strip().lower(),))
    if not r or not N.confere_senha(senha, r[3]):
        raise ValueError("Usuário ou senha incorretos.")
    st.session_state.usuario = {"id": r[0], "nome": r[1], "login": r[2]}
    st.query_params["t"] = gerar_token(r[0], r[3])


def tela_login():
    primeiro = db().um("SELECT COUNT(*) FROM usuarios")[0] == 0
    _, meio, _ = st.columns([1, 2, 1])
    with meio:
        st.title("💰 Finanças Casa")
        if primeiro:
            st.caption("Primeiro acesso: crie o usuário administrador.")
            with st.form("f_primeiro"):
                nome = st.text_input("Seu nome", key="p_nome")
                login = st.text_input("Usuário", key="p_login")
                senha = st.text_input("Senha", type="password", key="p_senha")
                senha2 = st.text_input("Confirme a senha", type="password", key="p_senha2")
                if st.form_submit_button("Criar e entrar", type="primary", width="stretch"):
                    def criar():
                        n = texto_obrigatorio(nome, "seu nome")
                        lg = texto_obrigatorio(login, "o usuário").lower()
                        if len(senha) < 4:
                            raise ValueError("A senha deve ter pelo menos 4 caracteres.")
                        if senha != senha2:
                            raise ValueError("As senhas não conferem.")
                        db().exe("INSERT INTO usuarios (nome, login, senha_hash) VALUES (%s, %s, %s)",
                                 (n, lg, N.hash_senha(senha)))
                        entrar(lg, senha)
                    rodar(criar)
        else:
            st.caption("Entre com o mesmo usuário e senha do app do computador.")
            with st.form("f_login"):
                login = st.text_input("Usuário", key="l_login")
                senha = st.text_input("Senha", type="password", key="l_senha")
                if st.form_submit_button("Entrar", type="primary", width="stretch"):
                    rodar(lambda: entrar(login, senha))
        st.caption("📱 No celular: depois de entrar, use **Adicionar à tela inicial** no menu do navegador "
                   f"para abrir já conectado (vale por {DIAS_LOGADO} dias).")


def sair():
    st.session_state.pop("usuario", None)
    st.query_params.clear()


# ----------------------------------------------------------------- cabeçalho
def _mudar_mes(n):
    st.session_state.mes = N.add_meses(st.session_state.mes, n)


def cabecalho(u):
    a, b = st.columns([3, 1], vertical_alignment="center")
    a.markdown(f"### 💰 Finanças Casa  \n<span class='card-t'>Olá, {u['nome']}</span>", unsafe_allow_html=True)
    b.button("Sair", on_click=sair, key="b_sair", width="stretch")
    c1, c2, c3 = st.columns([1, 3, 1], vertical_alignment="center")
    c1.button("◀", on_click=_mudar_mes, args=(-1,), key="b_ant", width="stretch")
    c2.markdown(f"<div style='text-align:center;font-weight:700;font-size:1.15rem'>{nome_mes(mes())}</div>",
                unsafe_allow_html=True)
    c3.button("▶", on_click=_mudar_mes, args=(1,), key="b_prox", width="stretch")


# ----------------------------------------------------------------- lançamentos
def inserir_lancamentos(tipo, desc, valor, data, cat_id, repetir, pago, uid):
    desc = texto_obrigatorio(desc, "a descrição")
    valor = valor_positivo(valor)
    if cat_id is None:
        raise ValueError("Escolha a categoria.")
    grupo = uuid.uuid4().hex if repetir > 1 else None
    linhas = []
    for i in range(repetir):
        p = pago and i == 0
        linhas.append((tipo, desc, cat_id, valor, N.add_meses(data, i), p, date.today() if p else None,
                       grupo, i + 1, repetir, uid))
    db().lote("INSERT INTO lancamentos (tipo, descricao, categoria_id, valor, data, pago, data_pagamento, grupo, "
              "parcela, total_parcelas, usuario_id) VALUES %s", linhas)


def pg_lancamentos(u):
    with st.expander("➕ Novo lançamento"):
        tipo_txt = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True, key="nl_tipo")
        tipo = "R" if tipo_txt == "Receita" else "D"
        cats = categorias(tipo)
        with st.form("f_nl", clear_on_submit=True):
            desc = st.text_input("Descrição", key="nl_desc")
            valor = st.text_input("Valor (R$)", placeholder="0,00", key="nl_valor")
            data = st.date_input("Data / vencimento", value=data_padrao(), format="DD/MM/YYYY", key="nl_data")
            cat = st.selectbox("Categoria", list(cats), key="nl_cat")
            rep = st.number_input("Repetir por quantos meses", 1, 120, 1, key="nl_rep")
            pago = st.checkbox("Já recebido" if tipo == "R" else "Já pago", key="nl_pago")
            if st.form_submit_button("Salvar", type="primary"):
                rodar(lambda: inserir_lancamentos(tipo, desc, valor, data, cats.get(cat), int(rep), pago, u["id"]),
                      "Lançamento salvo.")

    hoje = date.today()
    rows = db().todos(
        """SELECT l.id, l.data, l.descricao, c.nome, l.tipo, l.valor, l.pago, l.parcela, l.total_parcelas, u.nome,
                  l.grupo, l.categoria_id
           FROM lancamentos l LEFT JOIN categorias c ON c.id = l.categoria_id
           LEFT JOIN usuarios u ON u.id = l.usuario_id
           WHERE l.cartao_id IS NULL AND l.data BETWEEN %s AND %s ORDER BY l.data, l.id""",
        (mes(), N.fim_mes(mes())))
    if not rows:
        st.info("Nenhum lançamento neste mês.")
        return
    linhas = []
    for _id, d, desc, cat, tipo, valor, pago, parc, tot, usu, _g, _c in rows:
        if pago:
            sit = "✅ Recebido" if tipo == "R" else "✅ Pago"
        elif d < hoje:
            sit = "🔴 Atrasado"
        else:
            sit = "⏳ Pendente"
        linhas.append((N.dbr(d), desc, cat or "", "Receita" if tipo == "R" else "Despesa", N.brl(valor), sit,
                       f"{parc}/{tot}" if tot > 1 else "", usu or ""))
    st.caption("Toque em uma linha para editar, marcar como pago ou excluir.")
    i = tabela(linhas, ["Data", "Descrição", "Categoria", "Tipo", "Valor", "Situação", "Repetição", "Lançado por"],
               "t_lanc")
    if i is None:
        return
    lid, d, desc, cat, tipo, valor, pago, parc, tot, _u, grupo, cat_id = rows[i]
    st.markdown(f"**Selecionado:** {desc} — {N.brl(valor)} — {N.dbr(d)}")
    c1, c2 = st.columns(2)
    rotulo = ("Marcar como pendente" if pago else ("Marcar como recebido" if tipo == "R" else "Marcar como pago"))
    if c1.button(rotulo, key=f"b_pago_{lid}", width="stretch"):
        rodar(lambda: db().exe("UPDATE lancamentos SET pago = NOT pago, data_pagamento = CASE WHEN pago THEN NULL "
                               "ELSE %s END WHERE id = %s", (date.today(), lid)), "Situação atualizada.")
    with c2.popover("🗑️ Excluir", width="stretch"):
        modo = st.radio("O que excluir?", ["Só este", "Este e os próximos"], key=f"r_exc_{lid}") if grupo else "Só este"
        if st.button("Confirmar exclusão", type="primary", key=f"b_exc_{lid}"):
            if modo == "Só este":
                rodar(lambda: db().exe("DELETE FROM lancamentos WHERE id = %s", (lid,)), "Lançamento excluído.")
            else:
                rodar(lambda: db().exe("DELETE FROM lancamentos WHERE grupo = %s AND parcela >= %s", (grupo, parc)),
                      "Lançamentos excluídos.")
    with st.expander("✏️ Editar"):
        cats = categorias(tipo)
        nomes = list(cats)
        with st.form(f"f_ed_{lid}"):
            e_desc = st.text_input("Descrição", value=desc)
            e_valor = st.text_input("Valor (R$)", value=N.num(valor))
            e_data = st.date_input("Data / vencimento", value=d, format="DD/MM/YYYY")
            e_cat = st.selectbox("Categoria", nomes, index=nomes.index(cat) if cat in nomes else 0)
            e_pago = st.checkbox("Já recebido" if tipo == "R" else "Já pago", value=pago)
            if st.form_submit_button("Salvar alterações", type="primary"):
                def salvar():
                    dd = texto_obrigatorio(e_desc, "a descrição")
                    vv = valor_positivo(e_valor)
                    db().exe("UPDATE lancamentos SET descricao = %s, valor = %s, data = %s, categoria_id = %s, "
                             "pago = %s, data_pagamento = CASE WHEN %s THEN COALESCE(data_pagamento, %s) ELSE NULL "
                             "END WHERE id = %s",
                             (dd, vv, e_data, cats[e_cat], e_pago, e_pago, date.today(), lid))
                rodar(salvar, "Lançamento alterado.")


# ----------------------------------------------------------------- contas a pagar
def itens_contas_pagar(m):
    hoje, ini, fim = date.today(), m, N.fim_mes(m)
    itens = []
    for lid, d, desc, cat, valor in db().todos(
            """SELECT l.id, l.data, l.descricao, c.nome, l.valor FROM lancamentos l
               LEFT JOIN categorias c ON c.id = l.categoria_id
               WHERE l.tipo = 'D' AND NOT l.pago AND l.cartao_id IS NULL
                 AND (l.data BETWEEN %s AND %s OR l.data < %s)""", (ini, fim, hoje)):
        itens.append((d, ("L", lid), desc, cat or "", valor))
    for cid, nome, dia_venc, fatura, total in db().todos(
            """SELECT k.id, k.nome, k.dia_vencimento, l.fatura, SUM(l.valor) FROM lancamentos l
               JOIN cartoes k ON k.id = l.cartao_id WHERE NOT l.pago
               GROUP BY k.id, k.nome, k.dia_vencimento, l.fatura"""):
        venc = N.dia_no_mes(fatura, dia_venc)
        if ini <= venc <= fim or venc < hoje:
            itens.append((venc, ("F", cid, fatura), f"Fatura {nome} — {nome_mes(fatura)}", "Cartão de crédito", total))
    itens.sort(key=lambda x: (x[0], x[2]))
    return itens


def pagar_fatura(cid, fatura):
    db().exe("UPDATE lancamentos SET pago = TRUE, data_pagamento = %s WHERE cartao_id = %s AND fatura = %s "
             "AND NOT pago", (date.today(), cid, fatura))


def pg_contas_pagar(u):
    hoje = date.today()
    itens = itens_contas_pagar(mes())
    ini, fim = mes(), N.fim_mes(mes())
    total_mes = sum((v for d, _k, _d, _c, v in itens if ini <= d <= fim), Decimal(0))
    atrasado = sum((v for d, _k, _d, _c, v in itens if d < hoje), Decimal(0))
    c1, c2 = st.columns(2)
    c1.metric(f"A pagar em {nome_mes(mes())}", N.brl(total_mes), border=True)
    c2.metric("Atrasado", N.brl(atrasado), border=True)
    if not itens:
        st.success("Nada pendente neste mês. 🎉")
        return
    linhas = []
    for venc, _k, desc, cat, valor in itens:
        dias = (venc - hoje).days
        sit = (f"🔴 Atrasada há {-dias} dia(s)" if dias < 0 else "🟡 Vence hoje" if dias == 0
               else f"Vence em {dias} dia(s)")
        linhas.append((N.dbr(venc), desc, cat, N.brl(valor), sit))
    st.caption("Toque em uma conta para marcá-la como paga.")
    i = tabela(linhas, ["Vencimento", "Descrição", "Categoria", "Valor", "Situação"], "t_contas")
    if i is None:
        return
    _v, chave, desc, _c, valor = itens[i]
    st.markdown(f"**Selecionado:** {desc} — {N.brl(valor)}")
    if chave[0] == "L":
        if st.button("✅ Marcar como pago", type="primary", key="b_cp_pagar"):
            rodar(lambda: db().exe("UPDATE lancamentos SET pago = TRUE, data_pagamento = %s WHERE id = %s",
                                   (date.today(), chave[1])), "Conta paga.")
    elif st.button("✅ Marcar a fatura inteira como paga", type="primary", key="b_cp_fatura"):
        rodar(lambda: pagar_fatura(chave[1], chave[2]), "Fatura paga.")


# ----------------------------------------------------------------- cartões
def validar_cartao(nome, limite, fech, venc):
    return (texto_obrigatorio(nome, "o nome do cartão"), N.parse_valor(limite or "0"), int(fech), int(venc))


def form_cartao(key, valores=None, cid=None):
    v = valores or {"nome": "", "limite": "", "fech": 1, "venc": 10}
    with st.form(key, clear_on_submit=cid is None):
        nome = st.text_input("Nome do cartão", value=v["nome"])
        limite = st.text_input("Limite (R$)", value=v["limite"], placeholder="0,00")
        c1, c2 = st.columns(2)
        fech = c1.number_input("Dia de fechamento", 1, 31, int(v["fech"]))
        venc = c2.number_input("Dia de vencimento", 1, 31, int(v["venc"]))
        if st.form_submit_button("Salvar cartão", type="primary"):
            def salvar():
                dados = validar_cartao(nome, limite, fech, venc)
                if cid is None:
                    db().exe("INSERT INTO cartoes (nome, limite, dia_fechamento, dia_vencimento) "
                             "VALUES (%s, %s, %s, %s)", dados)
                else:
                    db().exe("UPDATE cartoes SET nome = %s, limite = %s, dia_fechamento = %s, dia_vencimento = %s "
                             "WHERE id = %s", dados + (cid,))
                st.session_state.cartao_sel = dados[0]
            rodar(salvar, "Cartão salvo.")


def lancar_compra(cartao, desc, valor, data, cat_id, parcelas, uid):
    cid, _nome, _lim, fech, venc = cartao
    desc = texto_obrigatorio(desc, "a descrição")
    valor = valor_positivo(valor, "o valor total")
    if cat_id is None:
        raise ValueError("Escolha a categoria.")
    primeira = N.mes_fatura(data, fech, venc)
    partes = N.dividir(valor, parcelas)
    grupo = uuid.uuid4().hex if parcelas > 1 else None
    db().lote("INSERT INTO lancamentos (tipo, descricao, categoria_id, valor, data, pago, data_pagamento, cartao_id, "
              "fatura, grupo, parcela, total_parcelas, usuario_id) VALUES %s",
              [("D", desc, cat_id, partes[i], data, False, None, cid, N.add_meses(primeira, i), grupo, i + 1,
                parcelas, uid) for i in range(parcelas)])
    return primeira


def pg_cartoes(u):
    cartoes = db().todos("SELECT id, nome, limite, dia_fechamento, dia_vencimento FROM cartoes ORDER BY nome")
    if not cartoes:
        st.info("Cadastre seu primeiro cartão.")
        form_cartao("f_cartao_novo")
        return
    nomes = [c[1] for c in cartoes]
    padrao = st.session_state.get("cartao_sel")
    sel = st.selectbox("Cartão", nomes, index=nomes.index(padrao) if padrao in nomes else 0, key="cb_cartao")
    st.session_state.cartao_sel = sel
    cartao = cartoes[nomes.index(sel)]
    cid, nome, limite, fech, venc = cartao
    usado = db().um("SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE cartao_id = %s AND NOT pago", (cid,))[0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Limite", N.brl(limite), border=True)
    c2.metric("Usado", N.brl(usado), border=True)
    c3.metric("Disponível", N.brl(limite - usado), border=True)
    st.caption(f"Fecha dia {fech} · Vence dia {venc}")

    rows = db().todos(
        """SELECT l.id, l.data, l.descricao, cat.nome, l.parcela, l.total_parcelas, l.valor, l.pago, l.grupo
           FROM lancamentos l LEFT JOIN categorias cat ON cat.id = l.categoria_id
           WHERE l.cartao_id = %s AND l.fatura = %s ORDER BY l.data, l.id""", (cid, mes()))
    total = sum((r[6] for r in rows), Decimal(0))
    paga = bool(rows) and all(r[7] for r in rows)
    st.markdown(f"#### Fatura de {nome_mes(mes())}: {N.brl(total)}"
                f"{' — ✅ PAGA' if paga else ''}  \n<span class='card-t'>Vence em "
                f"{N.dbr(N.dia_no_mes(mes(), venc))}</span>", unsafe_allow_html=True)

    a, b = st.columns(2)
    with a.expander("🛒 Nova compra"):
        cats = categorias("D")
        with st.form("f_compra", clear_on_submit=True):
            desc = st.text_input("Descrição", key="cp_desc")
            valor = st.text_input("Valor total (R$)", placeholder="0,00", key="cp_valor")
            data = st.date_input("Data da compra", value=date.today(), format="DD/MM/YYYY", key="cp_data")
            cat = st.selectbox("Categoria", list(cats), key="cp_cat")
            parc = st.number_input("Parcelas", 1, 48, 1, key="cp_parc")
            if st.form_submit_button("Lançar compra", type="primary"):
                def comprar():
                    p = lancar_compra(cartao, desc, valor, data, cats.get(cat), int(parc), u["id"])
                    st.session_state.flash = f"Compra lançada. Primeira parcela na fatura de {nome_mes(p)}."
                rodar(comprar)
    if rows and not paga:
        with b.popover("✅ Pagar fatura", width="stretch"):
            st.write(f"Marcar a fatura de {nome_mes(mes())} do {nome} como paga?")
            if st.button("Confirmar", type="primary", key="b_pagar_fat"):
                rodar(lambda: pagar_fatura(cid, mes()), "Fatura paga.")

    if rows:
        linhas = [(N.dbr(d), desc, cat or "", f"{p}/{t}" if t > 1 else "", N.brl(v))
                  for _i, d, desc, cat, p, t, v, _pg, _g in rows]
        i = tabela(linhas, ["Data", "Descrição", "Categoria", "Parcela", "Valor"], "t_fatura")
        if i is not None:
            lid, _d, desc, _c, _p, tot, valor, _pg, grupo = rows[i]
            with st.popover(f"🗑️ Excluir “{desc}”"):
                modo = st.radio("O que excluir?", ["Todas as parcelas", "Só esta"], key=f"r_excc_{lid}") \
                    if grupo else "Só esta"
                if st.button("Confirmar exclusão", type="primary", key=f"b_excc_{lid}"):
                    if modo == "Só esta":
                        rodar(lambda: db().exe("DELETE FROM lancamentos WHERE id = %s", (lid,)), "Compra excluída.")
                    else:
                        rodar(lambda: db().exe("DELETE FROM lancamentos WHERE grupo = %s", (grupo,)),
                              "Compra excluída.")
    else:
        st.info("Nenhuma compra nesta fatura.")

    with st.expander("⚙️ Editar este cartão"):
        form_cartao(f"f_cartao_ed_{cid}", {"nome": nome, "limite": N.num(limite), "fech": fech, "venc": venc}, cid)
    with st.expander("➕ Cadastrar outro cartão"):
        form_cartao("f_cartao_novo")


# ----------------------------------------------------------------- metas
def pg_metas(u):
    with st.expander("➕ Nova meta"):
        with st.form("f_meta", clear_on_submit=True):
            desc = st.text_input("Descrição", key="mt_desc")
            alvo = st.text_input("Valor alvo (R$)", placeholder="0,00", key="mt_alvo")
            atual = st.text_input("Já guardado (R$)", value="0", key="mt_atual")
            prazo = st.date_input("Prazo (opcional)", value=None, format="DD/MM/YYYY", key="mt_prazo")
            if st.form_submit_button("Salvar meta", type="primary"):
                def salvar():
                    db().exe("INSERT INTO metas (descricao, valor_alvo, valor_atual, prazo) VALUES (%s, %s, %s, %s)",
                             (texto_obrigatorio(desc, "a descrição"), valor_positivo(alvo, "o valor alvo"),
                              N.parse_valor(atual or "0"), prazo))
                rodar(salvar, "Meta criada.")
    rows = db().todos("SELECT id, descricao, valor_alvo, valor_atual, prazo FROM metas "
                      "ORDER BY prazo NULLS LAST, descricao")
    if not rows:
        st.info("Nenhuma meta cadastrada.")
        return
    linhas = []
    for _id, desc, alvo, atual, prazo in rows:
        pct = atual / alvo * 100 if alvo else 0
        linhas.append(((("✅ " if atual >= alvo else "") + desc), N.brl(alvo), N.brl(atual),
                       N.brl(max(alvo - atual, 0)), f"{pct:.0f}%", N.dbr(prazo)))
    st.caption("Toque em uma meta para guardar/retirar valor, editar ou excluir.")
    i = tabela(linhas, ["Meta", "Valor alvo", "Guardado", "Falta", "Progresso", "Prazo"], "t_metas")
    if i is None:
        return
    mid, desc, alvo, atual, prazo = rows[i]
    st.markdown(f"**Selecionada:** {desc}")
    st.progress(min(float(atual / alvo), 1.0) if alvo else 0.0)
    c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")
    valor = c1.text_input("Valor (R$)", placeholder="0,00", key=f"mv_{mid}")
    for col, rot, sinal in ((c2, "Guardar", 1), (c3, "Retirar", -1)):
        if col.button(rot, key=f"b_mv_{sinal}_{mid}", width="stretch"):
            rodar(lambda s=sinal: db().exe("UPDATE metas SET valor_atual = GREATEST(valor_atual + %s, 0) WHERE id = %s",
                                           (valor_positivo(valor) * s, mid)), "Meta atualizada.")
    with st.expander("✏️ Editar"):
        with st.form(f"f_meta_ed_{mid}"):
            e_desc = st.text_input("Descrição", value=desc)
            e_alvo = st.text_input("Valor alvo (R$)", value=N.num(alvo))
            e_atual = st.text_input("Já guardado (R$)", value=N.num(atual))
            e_prazo = st.date_input("Prazo (opcional)", value=prazo, format="DD/MM/YYYY")
            if st.form_submit_button("Salvar alterações", type="primary"):
                rodar(lambda: db().exe("UPDATE metas SET descricao = %s, valor_alvo = %s, valor_atual = %s, prazo = %s "
                                       "WHERE id = %s", (texto_obrigatorio(e_desc, "a descrição"),
                                                         valor_positivo(e_alvo, "o valor alvo"),
                                                         N.parse_valor(e_atual or "0"), e_prazo, mid)),
                      "Meta alterada.")
    with st.popover("🗑️ Excluir meta"):
        if st.button("Confirmar exclusão", type="primary", key=f"b_exm_{mid}"):
            rodar(lambda: db().exe("DELETE FROM metas WHERE id = %s", (mid,)), "Meta excluída.")


# ----------------------------------------------------------------- relatório
def pg_relatorio(u):
    ini = mes()
    rows = db().todos(
        """SELECT l.tipo, COALESCE(c.nome, '(sem categoria)'), SUM(l.valor),
                  SUM(CASE WHEN l.pago THEN l.valor ELSE 0 END)
           FROM lancamentos l LEFT JOIN categorias c ON c.id = l.categoria_id
           WHERE (l.cartao_id IS NULL AND l.data BETWEEN %s AND %s)
              OR (l.cartao_id IS NOT NULL AND l.fatura = %s)
           GROUP BY 1, 2 ORDER BY 1 DESC, 3 DESC""", (ini, N.fim_mes(ini), ini))
    tot = {"R": Decimal(0), "D": Decimal(0)}
    real = {"R": Decimal(0), "D": Decimal(0)}
    for tipo, _c, valor, pago in rows:
        tot[tipo] += valor
        real[tipo] += pago
    saldo = tot["R"] - tot["D"]
    c1, c2, c3 = st.columns(3)
    c1.metric("Receitas do mês", N.brl(tot["R"]), border=True)
    c1.caption(f"Recebido: {N.brl(real['R'])}")
    c2.metric("Despesas do mês", N.brl(tot["D"]), border=True)
    c2.caption(f"Pago: {N.brl(real['D'])}")
    c3.metric("Saldo do mês", N.brl(saldo), border=True)
    c3.caption(f"Realizado até agora: {N.brl(real['R'] - real['D'])}")
    st.markdown("##### Por categoria")
    st.caption("Despesas de cartão entram no mês da fatura.")
    if not rows:
        st.info("Nenhum lançamento neste mês.")
        return
    linhas = [(cat, "Receita" if tipo == "R" else "Despesa", N.brl(valor),
               (f"{valor / tot[tipo] * 100:.1f}%".replace(".", ",") if tot[tipo] else "0%"))
              for tipo, cat, valor, _p in rows]
    st.dataframe(pd.DataFrame(linhas, columns=["Categoria", "Tipo", "Valor", "% do total"]), hide_index=True)


# ----------------------------------------------------------------- conselheiro
def card(container, titulo, valor, detalhe, cor):
    container.markdown(
        f"<div class='card-t'>{titulo}</div><div class='card-v' style='color:{COR.get(cor, 'inherit')}'>{valor}</div>"
        f"<div class='card-d'>{detalhe}</div>", unsafe_allow_html=True)


def pg_conselheiro(u):
    cons = N.Conselheiro(db(), mes())
    alertas, serie, orcamentos = cons.calcular()
    st.markdown("##### Indicadores do mês")
    titulos = (("poup", "Taxa de poupança"), ("fixos", "Gastos fixos"), ("cartao", "Uso do limite dos cartões"),
               ("parc", "Parcelas a vencer"), ("atraso", "Contas atrasadas"), ("media", "Despesas x média"))
    for linha in (titulos[:3], titulos[3:]):
        for col, (chave, titulo) in zip(st.columns(3), linha):
            valor, detalhe, cor = cons.cards[chave]
            card(col.container(border=True), titulo, valor, detalhe, cor)

    st.markdown("##### Alertas e orientações")
    ordem = {"vermelho": 0, "amarelo": 1, "verde": 2}
    caixa = {"vermelho": st.error, "amarelo": st.warning, "verde": st.success}
    for sev, texto in sorted(alertas, key=lambda x: ordem[x[0]]):
        caixa[sev](texto)

    st.markdown("##### Últimos 6 meses")
    df = pd.DataFrame({"Mês": [s[0] for s in serie], "Receitas": [float(s[1]) for s in serie],
                       "Despesas": [float(s[2]) for s in serie]})
    st.bar_chart(df, x="Mês", y=["Receitas", "Despesas"], color=[N.VERDE, N.VERMELHO], stack=False, sort=False,
                 x_label="", y_label="R$")
    st.caption("Saldo: " + "  ·  ".join(f"{s[0]} {N.brl(s[1] - s[2])}" for s in serie if s[1] or s[2]))

    st.markdown("##### Orçamento por categoria")
    with st.expander("➕ Definir limite de uma categoria"):
        cats = categorias("D")
        with st.form("f_orc", clear_on_submit=True):
            cat = st.selectbox("Categoria", list(cats), key="orc_cat")
            lim = st.text_input("Limite por mês (R$)", placeholder="0,00", key="orc_lim")
            if st.form_submit_button("Salvar limite", type="primary"):
                rodar(lambda: db().exe("INSERT INTO orcamentos (categoria_id, limite) VALUES (%s, %s) "
                                       "ON CONFLICT (categoria_id) DO UPDATE SET limite = EXCLUDED.limite",
                                       (cats[cat], valor_positivo(lim, "o limite"))), "Limite salvo.")
    if not orcamentos:
        st.info("Nenhum limite definido. Ex.: Mercado até R$ 1.200 por mês.")
        return
    linhas = []
    for _cid, nome, limite, gasto in orcamentos:
        pct = gasto / limite * 100 if limite else 0
        icone = "🔴 " if pct >= 100 else "🟡 " if pct >= 80 else ""
        linhas.append((icone + nome, N.brl(limite), N.brl(gasto), N.brl(limite - gasto), f"{pct:.0f}%"))
    i = tabela(linhas, ["Categoria", "Limite mensal", "Gasto no mês", "Disponível", "% usado"], "t_orc")
    if i is not None:
        cid, nome, _l, _g = orcamentos[i]
        if st.button(f"Remover limite de {nome}", key=f"b_rm_orc_{cid}"):
            rodar(lambda: db().exe("DELETE FROM orcamentos WHERE categoria_id = %s", (cid,)), "Limite removido.")


# ----------------------------------------------------------------- configurações
def pg_config(u):
    esq, dir_ = st.columns(2)
    with esq:
        st.markdown("##### Usuários")
        st.dataframe(pd.DataFrame(db().todos("SELECT nome, login FROM usuarios ORDER BY nome"),
                                  columns=["Nome", "Usuário"]), hide_index=True)
        with st.expander("➕ Novo usuário"):
            with st.form("f_usu", clear_on_submit=True):
                nome = st.text_input("Nome", key="nu_nome")
                login = st.text_input("Usuário", key="nu_login")
                s1 = st.text_input("Senha", type="password", key="nu_s1")
                s2 = st.text_input("Confirme a senha", type="password", key="nu_s2")
                if st.form_submit_button("Criar usuário", type="primary"):
                    def criar():
                        n = texto_obrigatorio(nome, "o nome")
                        lg = texto_obrigatorio(login, "o usuário").lower()
                        if len(s1) < 4:
                            raise ValueError("A senha deve ter pelo menos 4 caracteres.")
                        if s1 != s2:
                            raise ValueError("As senhas não conferem.")
                        db().exe("INSERT INTO usuarios (nome, login, senha_hash) VALUES (%s, %s, %s)",
                                 (n, lg, N.hash_senha(s1)))
                    rodar(criar, "Usuário criado.")
        with st.expander("🔑 Trocar minha senha"):
            with st.form("f_senha", clear_on_submit=True):
                atual = st.text_input("Senha atual", type="password", key="ts_atual")
                n1 = st.text_input("Nova senha", type="password", key="ts_n1")
                n2 = st.text_input("Confirme a nova senha", type="password", key="ts_n2")
                if st.form_submit_button("Trocar senha", type="primary"):
                    def trocar():
                        h = db().um("SELECT senha_hash FROM usuarios WHERE id = %s", (u["id"],))[0]
                        if not N.confere_senha(atual, h):
                            raise ValueError("Senha atual incorreta.")
                        if len(n1) < 4:
                            raise ValueError("A nova senha deve ter pelo menos 4 caracteres.")
                        if n1 != n2:
                            raise ValueError("As senhas não conferem.")
                        novo = N.hash_senha(n1)
                        db().exe("UPDATE usuarios SET senha_hash = %s WHERE id = %s", (novo, u["id"]))
                        st.query_params["t"] = gerar_token(u["id"], novo)
                    rodar(trocar, "Senha alterada.")
    with dir_:
        st.markdown("##### Categorias")
        rows = db().todos("SELECT id, nome, tipo FROM categorias ORDER BY tipo DESC, nome")
        i = tabela([(n, "Receita" if t == "R" else "Despesa") for _i, n, t in rows], ["Categoria", "Tipo"], "t_cat")
        if i is not None:
            cid, nome, _t = rows[i]
            if st.button(f"🗑️ Excluir categoria “{nome}”", key=f"b_exc_cat_{cid}"):
                rodar(lambda: db().exe("DELETE FROM categorias WHERE id = %s", (cid,)), "Categoria excluída.")
        with st.expander("➕ Nova categoria"):
            with st.form("f_cat", clear_on_submit=True):
                nome = st.text_input("Nome", key="nc_nome")
                tipo = st.radio("Tipo", ["Despesa", "Receita"], horizontal=True, key="nc_tipo")
                if st.form_submit_button("Criar categoria", type="primary"):
                    rodar(lambda: db().exe("INSERT INTO categorias (nome, tipo) VALUES (%s, %s)",
                                           (texto_obrigatorio(nome, "o nome"), "R" if tipo == "Receita" else "D")),
                          "Categoria criada.")


# ----------------------------------------------------------------- principal
PAGINAS = {"Lançamentos": pg_lancamentos, "Contas a pagar": pg_contas_pagar, "Cartões": pg_cartoes,
           "Metas": pg_metas, "Relatório mensal": pg_relatorio, "Conselheiro": pg_conselheiro,
           "Configurações": pg_config}


def main():
    if "DSN" not in st.secrets:
        st.error("Falta configurar o segredo DSN (string de conexão do Neon) nas configurações do app.")
        st.stop()
    try:
        db()
    except Exception as e:  # noqa: BLE001
        st.error(f"Não foi possível conectar ao banco: {e}")
        st.stop()
    u = usuario_atual()
    if not u:
        tela_login()
        return
    if "mes" not in st.session_state:
        hoje = date.today()
        st.session_state.mes = date(hoje.year, hoje.month, 1)
    cabecalho(u)
    tela = st.selectbox("Tela", TELAS, key="tela", label_visibility="collapsed")
    flash = st.session_state.pop("flash", None)
    if flash:
        st.success(flash)
    PAGINAS[tela](u)


main()
