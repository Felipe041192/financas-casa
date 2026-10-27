"""Finanças Casa — versão web (celular e computador). Usa o mesmo banco do app do computador."""
import hashlib
import hmac
import html
import time
import uuid
from datetime import date
from decimal import Decimal

import pandas as pd
import psycopg2
import streamlit as st

import nucleo as N

st.set_page_config(page_title="Finanças Casa", page_icon="💰", layout="centered", initial_sidebar_state="collapsed")

VERDE, VERMELHO, AMARELO = "#2fbf71", "#e5484d", "#f5a524"
COR = {"vermelho": VERMELHO, "amarelo": AMARELO, "verde": VERDE}
DIAS_LOGADO = 60
NAV = {"Início": ":material/insights:", "Lançamentos": ":material/receipt_long:", "Contas": ":material/event:",
       "Cartões": ":material/credit_card:", "Metas": ":material/flag:", "Relatório": ":material/bar_chart:",
       "Ajustes": ":material/settings:"}

st.markdown("""<style>
.block-container {padding-top: 1.2rem; padding-bottom: 4rem; max-width: 1000px;}
@media (max-width: 640px) {.block-container {padding-left: .75rem; padding-right: .75rem; padding-top: .8rem;}}
header[data-testid="stHeader"] {display: none;}
.st-key-tela div[data-testid="stButtonGroup"] > div {flex-wrap: nowrap !important; overflow-x: auto; scrollbar-width: none;}
.st-key-tela div[data-testid="stButtonGroup"] > div::-webkit-scrollbar {display: none;}
.st-key-tela div[data-testid="stButtonGroup"] button {white-space: nowrap; flex: 1 0 auto;}
div[data-testid="stColumn"] {min-width: 0 !important;}
div[data-testid="stColumn"] button {min-width: 0 !important; padding-left: .3rem; padding-right: .3rem;}
.marca {font-size: 1.35rem; font-weight: 800; letter-spacing: -.01em;}
.ola {opacity: .6; font-size: .85rem;}
.mes {text-align: center; font-weight: 700; font-size: 1.1rem;}
.sec {font-weight: 700; font-size: 1.05rem; margin: 1.2rem 0 .5rem;}
.cards {display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; margin-bottom: .4rem;}
.cards.c2 {grid-template-columns: repeat(2, 1fr);}
@media (max-width: 640px) {.cards {grid-template-columns: repeat(2, 1fr);} .cards.c3m {grid-template-columns: repeat(3, 1fr);}}
.card {background: rgba(128,128,128,.08); border: 1px solid rgba(128,128,128,.22); border-radius: 14px; padding: 12px 14px;}
.card .t {opacity: .65; font-size: .78rem;}
.card .v {font-size: 1.45rem; font-weight: 800; line-height: 1.25; white-space: nowrap;}
.card .d {opacity: .6; font-size: .74rem; margin-top: 3px; line-height: 1.3;}
@media (max-width: 640px) {.card .v {font-size: 1.15rem;} .card {padding: 10px 11px;}
  .cards.c3m {gap: 6px;} .cards.c3m .card {padding: 8px 8px;} .cards.c3m .v {font-size: .95rem;}}
.alerta {border-left: 4px solid; background: rgba(128,128,128,.08); border-radius: 10px; padding: 9px 13px;
         margin-bottom: 7px; font-size: .9rem; line-height: 1.35;}
.sub {opacity: .62; font-size: .8rem;}
.val {text-align: right; font-weight: 700; white-space: nowrap;}
.barra {background: rgba(128,128,128,.22); border-radius: 6px; height: 8px; overflow: hidden; margin: 4px 0 2px;}
.barra > div {height: 100%; border-radius: 6px;}
.linha-cat {margin-bottom: 10px;}
.linha-cat .topo {display: flex; justify-content: space-between; font-size: .9rem;}
div[data-testid="stVerticalBlockBorderWrapper"] {border-radius: 12px;}
</style>""", unsafe_allow_html=True)


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


def esc(t):
    return html.escape(str(t or "")).replace("$", "&#36;")


def md(texto):
    st.markdown(texto.replace("$", "&#36;"), unsafe_allow_html=True)


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


def escolher_categoria(cats, key, atual=None):
    nomes = list(cats)
    return st.pills("Categoria", nomes, default=atual if atual in nomes else None, key=key)


def precisa(cat):
    if not cat:
        raise ValueError("Escolha a categoria.")
    return cat


# ----------------------------------------------------------------- componentes visuais
def cards(itens, classe=""):
    """itens: (titulo, valor, detalhe, cor)."""
    h = "".join(f"<div class='card'><div class='t'>{esc(t)}</div>"
                f"<div class='v' style='color:{COR.get(c, c or 'inherit')}'>{esc(v)}</div>"
                f"<div class='d'>{esc(d)}</div></div>" for t, v, d, c in itens)
    st.markdown(f"<div class='cards {classe}'>{h}</div>", unsafe_allow_html=True)


def secao(t):
    st.markdown(f"<div class='sec'>{esc(t)}</div>", unsafe_allow_html=True)


def barra(pct, cor):
    return f"<div class='barra'><div style='width:{max(min(pct, 100), 0):.0f}%;background:{cor}'></div></div>"


def linha(titulo, sub, valor, cor, key, icone=":material/more_horiz:", ajuda=None):
    """Item de lista com botão de ação; devolve True se o botão foi tocado."""
    with st.container(border=True):
        a, b, c = st.columns([6, 3.2, 1.3], vertical_alignment="center", wrap=False, gap="small")
        a.markdown(f"**{esc(titulo)}**  \n<span class='sub'>{sub.replace('$', '&#36;')}</span>",
                   unsafe_allow_html=True)
        b.markdown(f"<div class='val' style='color:{cor}'>{esc(valor)}</div>", unsafe_allow_html=True)
        return c.button("", icon=icone, key=key, help=ajuda, width="stretch")


def botoes(lista):
    """Linha de botões lado a lado; devolve o índice do tocado ou None."""
    with st.container(horizontal=True):
        for i, (rot, tipo, *ic) in enumerate(lista):
            if st.button(rot, type=tipo, key=f"acao_{st.session_state.tela}_{i}", icon=ic[0] if ic else None):
                return i
    return None


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
    st.markdown("<div style='height:6vh'></div><div class='marca' style='text-align:center;font-size:1.8rem'>"
                "💰 Finanças Casa</div>", unsafe_allow_html=True)
    with st.container(border=True):
        if primeiro:
            st.caption("Primeiro acesso: crie o usuário administrador.")
            with st.form("f_primeiro", border=False):
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
            with st.form("f_login", border=False):
                login = st.text_input("Usuário", key="l_login")
                senha = st.text_input("Senha", type="password", key="l_senha")
                if st.form_submit_button("Entrar", type="primary", width="stretch"):
                    rodar(lambda: entrar(login, senha))
    st.caption(f"📱 No celular, depois de entrar use **Adicionar à tela inicial** no menu do navegador para abrir "
               f"já conectado (vale por {DIAS_LOGADO} dias).")


def sair():
    st.session_state.pop("usuario", None)
    st.query_params.clear()


# ----------------------------------------------------------------- topo
def _mudar_mes(n):
    st.session_state.mes = N.add_meses(st.session_state.mes, n)


def topo(u):
    a, b = st.columns([5, 2], vertical_alignment="center", wrap=False)
    a.markdown(f"<span class='marca'>💰 Finanças Casa</span><br><span class='ola'>Olá, {esc(u['nome'])}</span>",
               unsafe_allow_html=True)
    with b.container(horizontal=True, horizontal_alignment="right"):
        st.button("Sair", on_click=sair, key="b_sair", type="tertiary", icon=":material/logout:")
    st.segmented_control("Tela", list(NAV), format_func=lambda k: f"{NAV[k]} {k}", key="tela", required=True,
                         label_visibility="collapsed", width="stretch")
    c1, c2, c3 = st.columns([1, 3, 1], vertical_alignment="center", wrap=False)
    c1.button("", icon=":material/chevron_left:", on_click=_mudar_mes, args=(-1,), key="b_ant", width="stretch")
    c2.markdown(f"<div class='mes'>{nome_mes(mes())}</div>", unsafe_allow_html=True)
    c3.button("", icon=":material/chevron_right:", on_click=_mudar_mes, args=(1,), key="b_prox", width="stretch")


# ================================================================= INÍCIO (conselheiro)
@st.dialog("Limite mensal da categoria")
def dlg_orcamento():
    cats = categorias("D")
    with st.form("f_orc", border=False):
        cat = escolher_categoria(cats, "orc_cat")
        lim = st.text_input("Limite por mês (R$)", placeholder="0,00", key="orc_lim")
        if st.form_submit_button("Salvar limite", type="primary", width="stretch"):
            rodar(lambda: db().exe("INSERT INTO orcamentos (categoria_id, limite) VALUES (%s, %s) "
                                   "ON CONFLICT (categoria_id) DO UPDATE SET limite = EXCLUDED.limite",
                                   (cats[precisa(cat)], valor_positivo(lim, "o limite"))), "Limite salvo.")


@st.dialog("Remover limite")
def dlg_rm_orcamento(cid, nome):
    md(f"Remover o limite de **{esc(nome)}**?")
    if st.button("Remover", type="primary", width="stretch", key="b_rm_orc"):
        rodar(lambda: db().exe("DELETE FROM orcamentos WHERE categoria_id = %s", (cid,)), "Limite removido.")


def pg_inicio(u):
    cons = N.Conselheiro(db(), mes())
    alertas, serie, orcamentos = cons.calcular()
    titulos = (("poup", "Taxa de poupança"), ("fixos", "Gastos fixos"), ("cartao", "Limite dos cartões"),
               ("parc", "Parcelas a vencer"), ("atraso", "Contas atrasadas"), ("media", "Despesas x média"))
    cards([(t,) + cons.cards[k] for k, t in titulos])

    secao("🧭 Conselheiro")
    ordem = {"vermelho": 0, "amarelo": 1, "verde": 2}
    st.markdown("".join(f"<div class='alerta' style='border-color:{COR[s]}'>{esc(t)}</div>"
                        for s, t in sorted(alertas, key=lambda x: ordem[x[0]])), unsafe_allow_html=True)

    secao("📈 Últimos 6 meses")
    df = pd.DataFrame({"Mês": [s[0] for s in serie], "Receitas": [float(s[1]) for s in serie],
                       "Despesas": [float(s[2]) for s in serie]})
    st.bar_chart(df, x="Mês", y=["Receitas", "Despesas"], color=[VERDE, VERMELHO], stack=False, sort=False,
                 x_label="", y_label="", height=260)
    saldos = [f"{s[0]}: <b style='color:{VERDE if s[1] >= s[2] else VERMELHO}'>{esc(N.brl(s[1] - s[2]))}</b>"
              for s in serie if s[1] or s[2]]
    if saldos:
        st.markdown("<span class='sub'>Saldo — " + " · ".join(saldos) + "</span>", unsafe_allow_html=True)

    secao("🎯 Orçamento por categoria")
    if st.button("Definir limite", icon=":material/add:", key="b_orc"):
        dlg_orcamento()
    if not orcamentos:
        st.caption("Nenhum limite definido. Ex.: Mercado até R$ 1.200 por mês.")
    for cid, nome, limite, gasto in orcamentos:
        pct = float(gasto / limite * 100) if limite else 0
        cor = VERMELHO if pct >= 100 else AMARELO if pct >= 80 else VERDE
        if linha(nome, f"{N.brl(gasto)} de {N.brl(limite)} · restam {N.brl(limite - gasto)}" + barra(pct, cor),
                 f"{pct:.0f}%", cor, f"rm_orc_{cid}", ":material/close:", "Remover limite"):
            dlg_rm_orcamento(cid, nome)


# ================================================================= LANÇAMENTOS
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


def _form_novo(tipo, uid):
    cats = categorias(tipo)
    with st.form(f"f_nl_{tipo}", border=False):
        desc = st.text_input("Descrição", key=f"nl_desc_{tipo}")
        valor = st.text_input("Valor (R$)", placeholder="0,00", key=f"nl_valor_{tipo}")
        cat = escolher_categoria(cats, f"nl_cat_{tipo}")
        a, b = st.columns(2)
        data = a.date_input("Data / vencimento", value=data_padrao(), format="DD/MM/YYYY", key=f"nl_data_{tipo}")
        rep = b.number_input("Repetir (meses)", 1, 120, 1, key=f"nl_rep_{tipo}")
        pago = st.toggle("Já recebido" if tipo == "R" else "Já pago", key=f"nl_pago_{tipo}")
        if st.form_submit_button("Salvar", type="primary", width="stretch"):
            rodar(lambda: inserir_lancamentos(tipo, desc, valor, data, cats.get(cat), int(rep), pago, uid),
                  "Lançamento salvo.")


@st.dialog("Nova despesa")
def dlg_nova_despesa(uid):
    _form_novo("D", uid)


@st.dialog("Nova receita")
def dlg_nova_receita(uid):
    _form_novo("R", uid)


@st.dialog("Lançamento")
def dlg_lancamento(lid):
    r = db().um("""SELECT l.tipo, l.descricao, l.valor, l.data, c.nome, l.pago, l.grupo, l.parcela, l.total_parcelas
                   FROM lancamentos l LEFT JOIN categorias c ON c.id = l.categoria_id WHERE l.id = %s""", (lid,))
    if not r:
        st.warning("Este lançamento não existe mais.")
        return
    tipo, desc, valor, d, cat, pago, grupo, parc, tot = r
    md(f"**{esc(desc)}** — {N.brl(valor)}  \n<span class='sub'>{N.dbr(d)} · {esc(cat)}"
       f"{f' · {parc}/{tot}' if tot > 1 else ''}</span>")
    rot = "Marcar como pendente" if pago else ("Marcar como recebido" if tipo == "R" else "Marcar como pago")
    if st.button(rot, type="primary", width="stretch", key="dl_pago", icon=":material/check_circle:"):
        rodar(lambda: db().exe("UPDATE lancamentos SET pago = NOT pago, data_pagamento = CASE WHEN pago THEN NULL "
                               "ELSE %s END WHERE id = %s", (date.today(), lid)), "Situação atualizada.")
    st.divider()
    cats = categorias(tipo)
    with st.form("f_ed_lanc", border=False):
        e_desc = st.text_input("Descrição", value=desc)
        e_valor = st.text_input("Valor (R$)", value=N.num(valor))
        e_cat = escolher_categoria(cats, "ed_cat", cat)
        e_data = st.date_input("Data / vencimento", value=d, format="DD/MM/YYYY")
        if st.form_submit_button("Salvar alterações", width="stretch"):
            rodar(lambda: db().exe("UPDATE lancamentos SET descricao = %s, valor = %s, data = %s, categoria_id = %s "
                                   "WHERE id = %s", (texto_obrigatorio(e_desc, "a descrição"), valor_positivo(e_valor),
                                                     e_data, cats[precisa(e_cat)], lid)), "Lançamento alterado.")
    st.divider()
    modo = st.radio("Excluir", ["Só este", "Este e os próximos"], horizontal=True, key="dl_modo") if grupo else "Só este"
    if st.button("Excluir", width="stretch", key="dl_exc", icon=":material/delete:"):
        if modo == "Só este":
            rodar(lambda: db().exe("DELETE FROM lancamentos WHERE id = %s", (lid,)), "Lançamento excluído.")
        else:
            rodar(lambda: db().exe("DELETE FROM lancamentos WHERE grupo = %s AND parcela >= %s", (grupo, parc)),
                  "Lançamentos excluídos.")


def pg_lancamentos(u):
    acao = botoes([("Despesa", "primary", ":material/remove:"), ("Receita", "secondary", ":material/add:")])
    if acao == 0:
        dlg_nova_despesa(u["id"])
    elif acao == 1:
        dlg_nova_receita(u["id"])
    hoje = date.today()
    rows = db().todos(
        """SELECT l.id, l.data, l.descricao, c.nome, l.tipo, l.valor, l.pago, l.parcela, l.total_parcelas, u.nome
           FROM lancamentos l LEFT JOIN categorias c ON c.id = l.categoria_id
           LEFT JOIN usuarios u ON u.id = l.usuario_id
           WHERE l.cartao_id IS NULL AND l.data BETWEEN %s AND %s ORDER BY l.data, l.id""",
        (mes(), N.fim_mes(mes())))
    rec = sum((r[5] for r in rows if r[4] == "R"), Decimal(0))
    desp = sum((r[5] for r in rows if r[4] == "D"), Decimal(0))
    cards([("Receitas", N.brl(rec), "", VERDE), ("Despesas", N.brl(desp), "sem cartão", VERMELHO),
           ("Saldo", N.brl(rec - desp), "", VERDE if rec >= desp else VERMELHO)], "c3m")
    if not rows:
        st.info("Nenhum lançamento neste mês.")
        return
    for lid, d, desc, cat, tipo, valor, pago, parc, tot, usu in rows:
        if pago:
            sit = "✅ recebido" if tipo == "R" else "✅ pago"
        elif d < hoje:
            sit = "🔴 atrasado"
        else:
            sit = "⏳ pendente"
        sub = f"{N.dbr(d)[:5]} · {esc(cat)} · {sit}{f' · {parc}/{tot}' if tot > 1 else ''}"
        sinal = "+ " if tipo == "R" else "− "
        if linha(desc, sub, sinal + N.brl(valor), VERDE if tipo == "R" else "inherit", f"lc_{lid}"):
            dlg_lancamento(lid)


# ================================================================= CONTAS A PAGAR
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


@st.dialog("Confirmar pagamento")
def dlg_pagar(chave, desc, valor):
    md(f"Marcar **{esc(desc)}** ({N.brl(valor)}) como paga?")
    if st.button("Confirmar pagamento", type="primary", width="stretch", key="b_conf_pag"):
        if chave[0] == "L":
            rodar(lambda: db().exe("UPDATE lancamentos SET pago = TRUE, data_pagamento = %s WHERE id = %s",
                                   (date.today(), chave[1])), "Conta paga.")
        else:
            rodar(lambda: pagar_fatura(chave[1], chave[2]), "Fatura paga.")


def pg_contas(u):
    hoje = date.today()
    itens = itens_contas_pagar(mes())
    ini, fim = mes(), N.fim_mes(mes())
    total_mes = sum((v for d, _k, _d, _c, v in itens if ini <= d <= fim), Decimal(0))
    atrasado = sum((v for d, _k, _d, _c, v in itens if d < hoje), Decimal(0))
    cards([(f"A pagar em {N.MESES[ini.month - 1]}", N.brl(total_mes), f"{len(itens)} conta(s) na lista", None),
           ("Atrasado", N.brl(atrasado), "pague primeiro" if atrasado else "nada em atraso",
            VERMELHO if atrasado else VERDE)], "c2")
    if not itens:
        st.success("Nada pendente neste mês. 🎉")
        return
    for venc, chave, desc, cat, valor in itens:
        dias = (venc - hoje).days
        sit = (f"🔴 atrasada há {-dias} dia(s)" if dias < 0 else "🟡 vence hoje" if dias == 0
               else f"vence em {dias} dia(s)")
        k = "_".join(str(x) for x in chave)
        if linha(desc, f"{N.dbr(venc)[:5]} · {esc(cat)} · {sit}", N.brl(valor),
                 VERMELHO if dias < 0 else "inherit", f"cp_{k}", ":material/check:", "Marcar como pago"):
            dlg_pagar(chave, desc, valor)


# ================================================================= CARTÕES
def validar_cartao(nome, limite, fech, venc):
    return (texto_obrigatorio(nome, "o nome do cartão"), N.parse_valor(limite or "0"), int(fech), int(venc))


@st.dialog("Cartão")
def dlg_cartao(cid=None, valores=None):
    v = valores or {"nome": "", "limite": "", "fech": 1, "venc": 10}
    with st.form("f_cartao", border=False):
        nome = st.text_input("Nome do cartão", value=v["nome"])
        limite = st.text_input("Limite (R$)", value=v["limite"], placeholder="0,00")
        a, b = st.columns(2)
        fech = a.number_input("Dia de fechamento", 1, 31, int(v["fech"]))
        venc = b.number_input("Dia de vencimento", 1, 31, int(v["venc"]))
        if st.form_submit_button("Salvar cartão", type="primary", width="stretch"):
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


@st.dialog("Nova compra no cartão")
def dlg_compra(cartao, uid):
    cats = categorias("D")
    st.caption(f"Cartão {cartao[1]}")
    with st.form("f_compra", border=False):
        desc = st.text_input("Descrição", key="cp_desc")
        valor = st.text_input("Valor total (R$)", placeholder="0,00", key="cp_valor")
        cat = escolher_categoria(cats, "cp_cat")
        a, b = st.columns(2)
        data = a.date_input("Data da compra", value=date.today(), format="DD/MM/YYYY", key="cp_data")
        parc = b.number_input("Parcelas", 1, 48, 1, key="cp_parc")
        if st.form_submit_button("Lançar compra", type="primary", width="stretch"):
            def comprar():
                p = lancar_compra(cartao, desc, valor, data, cats.get(cat), int(parc), uid)
                st.session_state.flash = f"Compra lançada. Primeira parcela na fatura de {nome_mes(p)}."
            rodar(comprar)


@st.dialog("Pagar fatura")
def dlg_pagar_fatura(cid, nome):
    md(f"Marcar a fatura de **{nome_mes(mes())}** do **{esc(nome)}** como paga?")
    if st.button("Confirmar", type="primary", width="stretch", key="b_pagar_fat"):
        rodar(lambda: pagar_fatura(cid, mes()), "Fatura paga.")


@st.dialog("Compra")
def dlg_item_compra(lid):
    r = db().um("SELECT descricao, valor, grupo, parcela, total_parcelas FROM lancamentos WHERE id = %s", (lid,))
    if not r:
        st.warning("Esta compra não existe mais.")
        return
    desc, valor, grupo, parc, tot = r
    md(f"**{esc(desc)}** — {N.brl(valor)}{f' · parcela {parc}/{tot}' if tot > 1 else ''}")
    modo = st.radio("Excluir", ["Todas as parcelas", "Só esta"], horizontal=True, key="ic_modo") if grupo else "Só esta"
    if st.button("Excluir", type="primary", width="stretch", key="ic_exc", icon=":material/delete:"):
        if modo == "Só esta":
            rodar(lambda: db().exe("DELETE FROM lancamentos WHERE id = %s", (lid,)), "Compra excluída.")
        else:
            rodar(lambda: db().exe("DELETE FROM lancamentos WHERE grupo = %s", (grupo,)), "Compra excluída.")


def pg_cartoes(u):
    cartoes = db().todos("SELECT id, nome, limite, dia_fechamento, dia_vencimento FROM cartoes ORDER BY nome")
    if not cartoes:
        st.info("Cadastre seu primeiro cartão.")
        if st.button("Cadastrar cartão", type="primary", icon=":material/add:", key="b_1cartao"):
            dlg_cartao()
        return
    nomes = [c[1] for c in cartoes]
    if st.session_state.get("cartao_sel") not in nomes:
        st.session_state.cartao_sel = nomes[0]
    sel = st.segmented_control("Cartão", nomes, key="cartao_sel", required=True, label_visibility="collapsed")
    cartao = cartoes[nomes.index(sel)]
    cid, nome, limite, fech, venc = cartao
    usado = db().um("SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE cartao_id = %s AND NOT pago", (cid,))[0]
    rows = db().todos(
        """SELECT l.id, l.data, l.descricao, cat.nome, l.parcela, l.total_parcelas, l.valor, l.pago
           FROM lancamentos l LEFT JOIN categorias cat ON cat.id = l.categoria_id
           WHERE l.cartao_id = %s AND l.fatura = %s ORDER BY l.data, l.id""", (cid, mes()))
    total = sum((r[6] for r in rows), Decimal(0))
    paga = bool(rows) and all(r[7] for r in rows)
    pct = float(usado / limite * 100) if limite else 0
    cor_uso = VERDE if pct <= 30 else AMARELO if pct < 80 else VERMELHO
    cards([(f"Fatura de {N.MESES[mes().month - 1]}", N.brl(total),
            ("✅ paga" if paga else f"vence {N.dbr(N.dia_no_mes(mes(), venc))}"), VERDE if paga else None),
           ("Limite disponível", N.brl(limite - usado), f"{pct:.0f}% usado de {N.brl(limite)}", cor_uso)], "c2")
    st.markdown(barra(pct, cor_uso) + f"<span class='sub'>Fecha dia {fech} · vence dia {venc}</span>",
                unsafe_allow_html=True)
    lista = [("Compra", "primary", ":material/add_shopping_cart:")] + ([("Pagar fatura", "secondary")] if rows and not paga else []) + \
            [("Editar cartão", "tertiary"), ("Novo cartão", "tertiary")]
    acao = botoes(lista)
    if acao is not None:
        rot = lista[acao][0]
        if rot == "Compra":
            dlg_compra(cartao, u["id"])
        elif rot == "Pagar fatura":
            dlg_pagar_fatura(cid, nome)
        elif rot == "Editar cartão":
            dlg_cartao(cid, {"nome": nome, "limite": N.num(limite), "fech": fech, "venc": venc})
        else:
            dlg_cartao()
    if not rows:
        st.caption("Nenhuma compra nesta fatura.")
    for lid, d, desc, cat, p, t, v, _pg in rows:
        if linha(desc, f"{N.dbr(d)} · {esc(cat)}{f' · {p}/{t}' if t > 1 else ''}", N.brl(v), "inherit", f"ic_{lid}"):
            dlg_item_compra(lid)


# ================================================================= METAS
@st.dialog("Meta")
def dlg_meta(mid=None):
    v = {"descricao": "", "alvo": "", "atual": "0", "prazo": None}
    if mid is not None:
        r = db().um("SELECT descricao, valor_alvo, valor_atual, prazo FROM metas WHERE id = %s", (mid,))
        if not r:
            st.warning("Esta meta não existe mais.")
            return
        v = {"descricao": r[0], "alvo": N.num(r[1]), "atual": N.num(r[2]), "prazo": r[3]}
        md(f"**{esc(r[0])}** — guardado {N.brl(r[2])} de {N.brl(r[1])}")
        a, b, c = st.columns([2, 1, 1], vertical_alignment="bottom")
        valor = a.text_input("Valor (R$)", placeholder="0,00", key="mt_mov")
        for col, rot, sinal in ((b, "Guardar", 1), (c, "Retirar", -1)):
            if col.button(rot, key=f"mt_b{sinal}", width="stretch", type="primary" if sinal > 0 else "secondary"):
                rodar(lambda s=sinal: db().exe("UPDATE metas SET valor_atual = GREATEST(valor_atual + %s, 0) "
                                               "WHERE id = %s", (valor_positivo(valor) * s, mid)), "Meta atualizada.")
        st.divider()
    with st.form("f_meta", border=False):
        desc = st.text_input("Descrição", value=v["descricao"])
        a, b = st.columns(2)
        alvo = a.text_input("Valor alvo (R$)", value=v["alvo"], placeholder="0,00")
        atual = b.text_input("Já guardado (R$)", value=v["atual"])
        prazo = st.date_input("Prazo (opcional)", value=v["prazo"], format="DD/MM/YYYY")
        if st.form_submit_button("Salvar meta" if mid is None else "Salvar alterações", type="primary",
                                 width="stretch"):
            dados = lambda: (texto_obrigatorio(desc, "a descrição"), valor_positivo(alvo, "o valor alvo"),  # noqa: E731
                             N.parse_valor(atual or "0"), prazo)
            if mid is None:
                rodar(lambda: db().exe("INSERT INTO metas (descricao, valor_alvo, valor_atual, prazo) "
                                       "VALUES (%s, %s, %s, %s)", dados()), "Meta criada.")
            else:
                rodar(lambda: db().exe("UPDATE metas SET descricao = %s, valor_alvo = %s, valor_atual = %s, "
                                       "prazo = %s WHERE id = %s", dados() + (mid,)), "Meta alterada.")
    if mid is not None and st.button("Excluir meta", key="mt_exc", icon=":material/delete:", width="stretch"):
        rodar(lambda: db().exe("DELETE FROM metas WHERE id = %s", (mid,)), "Meta excluída.")


def pg_metas(u):
    if botoes([("Nova meta", "primary", ":material/add:")]) == 0:
        dlg_meta()
    rows = db().todos("SELECT id, descricao, valor_alvo, valor_atual, prazo FROM metas "
                      "ORDER BY prazo NULLS LAST, descricao")
    if not rows:
        st.info("Nenhuma meta cadastrada. Ex.: Viagem — R$ 10.000 até dezembro.")
        return
    hoje = date.today()
    for mid, desc, alvo, atual, prazo in rows:
        pct = float(atual / alvo * 100) if alvo else 0
        falta = max(alvo - atual, 0)
        info = f"{N.brl(atual)} de {N.brl(alvo)}"
        if falta and prazo and prazo >= hoje:
            n = max((prazo.year - hoje.year) * 12 + prazo.month - hoje.month, 1)
            info += f" · guardar {N.brl(falta / n)}/mês até {N.dbr(prazo)}"
        elif prazo:
            info += f" · prazo {N.dbr(prazo)}"
        cor = VERDE if pct >= 100 else "inherit"
        if linha(("✅ " if pct >= 100 else "") + desc, info + barra(pct, VERDE), f"{pct:.0f}%", cor, f"mt_{mid}"):
            dlg_meta(mid)


# ================================================================= RELATÓRIO
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
    cards([("Receitas", N.brl(tot["R"]), f"recebido {N.brl(real['R'])}", VERDE),
           ("Despesas", N.brl(tot["D"]), f"pago {N.brl(real['D'])}", VERMELHO),
           ("Saldo", N.brl(saldo), f"realizado {N.brl(real['R'] - real['D'])}", VERDE if saldo >= 0 else VERMELHO)],
          "c3m")
    if not rows:
        st.info("Nenhum lançamento neste mês.")
        return
    for tipo, titulo, cor in (("D", "Despesas por categoria", VERMELHO), ("R", "Receitas por categoria", VERDE)):
        itens = [r for r in rows if r[0] == tipo]
        if not itens:
            continue
        secao(titulo)
        h = ""
        for _t, cat, valor, _p in itens:
            pct = float(valor / tot[tipo] * 100) if tot[tipo] else 0
            h += (f"<div class='linha-cat'><div class='topo'><span>{esc(cat)}</span>"
                  f"<span><b>{esc(N.brl(valor))}</b> <span class='sub'>{pct:.0f}%</span></span></div>{barra(pct, cor)}</div>")
        st.markdown(h, unsafe_allow_html=True)
    st.caption("Compras no cartão entram no mês da fatura.")


# ================================================================= AJUSTES
@st.dialog("Novo usuário")
def dlg_usuario():
    with st.form("f_usu", border=False):
        nome = st.text_input("Nome", key="nu_nome")
        login = st.text_input("Usuário", key="nu_login")
        s1 = st.text_input("Senha", type="password", key="nu_s1")
        s2 = st.text_input("Confirme a senha", type="password", key="nu_s2")
        if st.form_submit_button("Criar usuário", type="primary", width="stretch"):
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


@st.dialog("Trocar minha senha")
def dlg_senha(uid):
    with st.form("f_senha", border=False):
        atual = st.text_input("Senha atual", type="password", key="ts_atual")
        n1 = st.text_input("Nova senha", type="password", key="ts_n1")
        n2 = st.text_input("Confirme a nova senha", type="password", key="ts_n2")
        if st.form_submit_button("Trocar senha", type="primary", width="stretch"):
            def trocar():
                h = db().um("SELECT senha_hash FROM usuarios WHERE id = %s", (uid,))[0]
                if not N.confere_senha(atual, h):
                    raise ValueError("Senha atual incorreta.")
                if len(n1) < 4:
                    raise ValueError("A nova senha deve ter pelo menos 4 caracteres.")
                if n1 != n2:
                    raise ValueError("As senhas não conferem.")
                novo = N.hash_senha(n1)
                db().exe("UPDATE usuarios SET senha_hash = %s WHERE id = %s", (novo, uid))
                st.query_params["t"] = gerar_token(uid, novo)
            rodar(trocar, "Senha alterada.")


@st.dialog("Nova categoria")
def dlg_categoria():
    with st.form("f_cat", border=False):
        nome = st.text_input("Nome", key="nc_nome")
        tipo = st.segmented_control("Tipo", ["Despesa", "Receita"], default="Despesa", key="nc_tipo")
        if st.form_submit_button("Criar categoria", type="primary", width="stretch"):
            rodar(lambda: db().exe("INSERT INTO categorias (nome, tipo) VALUES (%s, %s)",
                                   (texto_obrigatorio(nome, "o nome"), "R" if tipo == "Receita" else "D")),
                  "Categoria criada.")


@st.dialog("Excluir categoria")
def dlg_exc_categoria(cid, nome):
    md(f"Excluir a categoria **{esc(nome)}**? Só é possível se não houver lançamentos nela.")
    if st.button("Excluir", type="primary", width="stretch", key="b_exc_cat"):
        rodar(lambda: db().exe("DELETE FROM categorias WHERE id = %s", (cid,)), "Categoria excluída.")


def pg_ajustes(u):
    secao("👤 Usuários")
    acao = botoes([("Novo usuário", "secondary"), ("Trocar minha senha", "secondary")])
    if acao == 0:
        dlg_usuario()
    elif acao == 1:
        dlg_senha(u["id"])
    st.markdown(" · ".join(f"**{esc(n)}** <span class='sub'>({esc(lg)})</span>"
                           for n, lg in db().todos("SELECT nome, login FROM usuarios ORDER BY nome")),
                unsafe_allow_html=True)
    secao("🏷️ Categorias")
    if st.button("Nova categoria", icon=":material/add:", key="b_nova_cat"):
        dlg_categoria()
    st.caption("Toque em uma categoria para excluí-la.")
    for tipo, titulo in (("D", "Despesas"), ("R", "Receitas")):
        cats = categorias(tipo)
        escolha = st.pills(titulo, list(cats), key=f"pill_cat_{tipo}")
        if escolha:
            st.session_state.pop(f"pill_cat_{tipo}", None)
            dlg_exc_categoria(cats[escolha], escolha)


# ================================================================= principal
PAGINAS = {"Início": pg_inicio, "Lançamentos": pg_lancamentos, "Contas": pg_contas, "Cartões": pg_cartoes,
           "Metas": pg_metas, "Relatório": pg_relatorio, "Ajustes": pg_ajustes}


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
    if st.session_state.get("tela") not in PAGINAS:
        st.session_state.tela = "Início"
    topo(u)
    flash = st.session_state.pop("flash", None)
    if flash:
        st.toast(flash, icon="✅")
    PAGINAS[st.session_state.tela](u)


main()
