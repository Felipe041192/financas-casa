"""Lógica compartilhada com o app do computador (gerado a partir do financas.py)."""
import calendar
import hashlib
import re
import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN
from types import SimpleNamespace

import psycopg2
from psycopg2 import errors as pg_erros
from psycopg2.extras import execute_values

APP_NOME = "Finanças Casa"
MESES = ["Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho", "Julho",
         "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro"]
VERDE, VERMELHO, AMARELO = "#7bd88f", "#ff6b6b", "#ffd166"

SCHEMA = """
CREATE TABLE IF NOT EXISTS usuarios (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    login TEXT NOT NULL UNIQUE,
    senha_hash TEXT NOT NULL,
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE TABLE IF NOT EXISTS categorias (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL,
    tipo CHAR(1) NOT NULL CHECK (tipo IN ('R','D')),
    UNIQUE (nome, tipo)
);
CREATE TABLE IF NOT EXISTS cartoes (
    id SERIAL PRIMARY KEY,
    nome TEXT NOT NULL UNIQUE,
    limite NUMERIC(12,2) NOT NULL DEFAULT 0,
    dia_fechamento INT NOT NULL CHECK (dia_fechamento BETWEEN 1 AND 31),
    dia_vencimento INT NOT NULL CHECK (dia_vencimento BETWEEN 1 AND 31)
);
CREATE TABLE IF NOT EXISTS lancamentos (
    id SERIAL PRIMARY KEY,
    tipo CHAR(1) NOT NULL CHECK (tipo IN ('R','D')),
    descricao TEXT NOT NULL,
    categoria_id INT REFERENCES categorias(id),
    valor NUMERIC(12,2) NOT NULL,
    data DATE NOT NULL,
    pago BOOLEAN NOT NULL DEFAULT FALSE,
    data_pagamento DATE,
    cartao_id INT REFERENCES cartoes(id),
    fatura DATE,
    grupo TEXT,
    parcela INT NOT NULL DEFAULT 1,
    total_parcelas INT NOT NULL DEFAULT 1,
    usuario_id INT REFERENCES usuarios(id),
    criado_em TIMESTAMPTZ NOT NULL DEFAULT now()
);
CREATE INDEX IF NOT EXISTS ix_lanc_data ON lancamentos (data);
CREATE INDEX IF NOT EXISTS ix_lanc_fatura ON lancamentos (cartao_id, fatura);
CREATE TABLE IF NOT EXISTS orcamentos (
    categoria_id INT PRIMARY KEY REFERENCES categorias(id) ON DELETE CASCADE,
    limite NUMERIC(12,2) NOT NULL
);
CREATE TABLE IF NOT EXISTS metas (
    id SERIAL PRIMARY KEY,
    descricao TEXT NOT NULL,
    valor_alvo NUMERIC(12,2) NOT NULL,
    valor_atual NUMERIC(12,2) NOT NULL DEFAULT 0,
    prazo DATE
);
"""

CATEGORIAS_PADRAO = (
    [(n, "R") for n in ("Salário", "Renda extra", "Rendimentos", "Outras receitas")]
    + [(n, "D") for n in ("Moradia", "Mercado", "Alimentação fora", "Contas (luz, água, internet)",
                          "Transporte", "Saúde", "Educação", "Lazer", "Vestuário", "Outras despesas")]
)


# ----------------------------------------------------------------- utilidades
def add_meses(d, n):
    total = d.month - 1 + n
    ano, mes = d.year + total // 12, total % 12 + 1
    return date(ano, mes, min(d.day, calendar.monthrange(ano, mes)[1]))


def fim_mes(d):
    return date(d.year, d.month, calendar.monthrange(d.year, d.month)[1])


def dia_no_mes(mes, dia):
    return date(mes.year, mes.month, min(dia, calendar.monthrange(mes.year, mes.month)[1]))


def mes_fatura(compra, fechamento, vencimento):
    """Mês (dia 1) da fatura em que a compra cai — a fatura é identificada pelo mês do vencimento."""
    m = date(compra.year, compra.month, 1)
    if compra.day >= fechamento:      # comprou no dia do fechamento ou depois: vai para o próximo ciclo
        m = add_meses(m, 1)
    if vencimento <= fechamento:      # vencimento cai no mês seguinte ao fechamento
        m = add_meses(m, 1)
    return m


def parse_valor(txt):
    s = str(txt).replace("R$", "").replace(" ", "").strip()
    if "," in s:
        s = s.replace(".", "").replace(",", ".")
    elif re.fullmatch(r"-?\d{1,3}(\.\d{3})+", s):   # 10.000 / 1.500.000 = separador de milhar
        s = s.replace(".", "")
    try:
        v = Decimal(s).quantize(Decimal("0.01"))
    except InvalidOperation:
        raise ValueError(f"Valor inválido: {txt!r}")
    if not v.is_finite():
        raise ValueError(f"Valor inválido: {txt!r}")
    return v


def parse_data(txt):
    txt = str(txt).strip()
    for fmt in ("%d/%m/%Y", "%d/%m/%y", "%d%m%Y"):
        try:
            return datetime.strptime(txt, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Data inválida: {txt!r} (use dd/mm/aaaa)")


def parse_int(txt, nome, minimo, maximo):
    try:
        n = int(str(txt).strip())
    except ValueError:
        raise ValueError(f"{nome}: informe um número inteiro.")
    if not minimo <= n <= maximo:
        raise ValueError(f"{nome}: use um número entre {minimo} e {maximo}.")
    return n


def brl(v):
    s = f"{Decimal(v or 0):,.2f}"
    return "R$ " + s.replace(",", "X").replace(".", ",").replace("X", ".")


def num(v):
    return f"{Decimal(v or 0):.2f}".replace(".", ",")


def dbr(d):
    return d.strftime("%d/%m/%Y") if d else ""


def dividir(total, n):
    base = (total / n).quantize(Decimal("0.01"), rounding=ROUND_DOWN)
    partes = [base] * n
    partes[-1] = total - base * (n - 1)
    return partes


def hash_senha(senha, salt=None):
    salt = salt or secrets.token_hex(16)
    h = hashlib.pbkdf2_hmac("sha256", senha.encode(), salt.encode(), 200_000).hex()
    return f"{salt}${h}"


def confere_senha(senha, armazenado):
    salt = armazenado.split("$", 1)[0]
    return secrets.compare_digest(hash_senha(senha, salt), armazenado)


# ---------------------------------------------------------------------- banco
class Banco:
    def __init__(self, dsn):
        self.dsn = dsn
        self.conn = None

    def _rodar(self, fn):
        for tentativa in range(2):
            try:
                if self.conn is None or self.conn.closed:
                    self.conn = psycopg2.connect(self.dsn, connect_timeout=20)
                    self.conn.autocommit = True
                with self.conn.cursor() as cur:
                    return fn(cur)
            except (psycopg2.OperationalError, psycopg2.InterfaceError):
                try:
                    if self.conn is not None:
                        self.conn.close()
                except Exception:  # noqa: BLE001
                    pass
                self.conn = None
                if tentativa:
                    raise

    def exe(self, sql, p=()):
        self._rodar(lambda c: c.execute(sql, p))

    def um(self, sql, p=()):
        def f(c):
            c.execute(sql, p)
            return c.fetchone()
        return self._rodar(f)

    def todos(self, sql, p=()):
        def f(c):
            c.execute(sql, p)
            return c.fetchall()
        return self._rodar(f)

    def lote(self, sql, linhas):
        self._rodar(lambda c: execute_values(c, sql, linhas))

    def preparar(self):
        self.exe(SCHEMA)
        if not self.um("SELECT 1 FROM categorias LIMIT 1"):
            self.lote("INSERT INTO categorias (nome, tipo) VALUES %s ON CONFLICT DO NOTHING", CATEGORIAS_PADRAO)


# ---------------------------------------------------------------- conselheiro
class Conselheiro:
    """Mesmas regras da aba Conselheiro do app do computador."""

    def __init__(self, db, mes):
        self.db = db
        self.p = SimpleNamespace(mes=mes)
        self.cards = {}

    def _card(self, chave, valor, detalhe, cor=None):
        self.cards[chave] = (valor, detalhe, cor)

    def calcular(self):
        mes, hoje = self.p.mes, date.today()
        ini6 = add_meses(mes, -5)
        meses = [add_meses(ini6, i) for i in range(6)]
        anteriores = [add_meses(mes, -i) for i in (1, 2, 3)]
        tot = {m: {"R": Decimal(0), "D": Decimal(0)} for m in meses}
        cat_mes = {}   # (mes, categoria_id) -> valor (despesas)
        nomes = {}
        for m, tipo, cid, nome, valor in self.db.todos(
                """SELECT COALESCE(l.fatura, date_trunc('month', l.data)::date), l.tipo, l.categoria_id,
                          COALESCE(c.nome, '(sem categoria)'), SUM(l.valor)
                   FROM lancamentos l LEFT JOIN categorias c ON c.id = l.categoria_id
                   WHERE COALESCE(l.fatura, date_trunc('month', l.data)::date) BETWEEN %s AND %s
                   GROUP BY 1, 2, 3, 4""", (ini6, mes)):
            tot[m][tipo] += valor
            if tipo == "D":
                cat_mes[(m, cid)] = cat_mes.get((m, cid), Decimal(0)) + valor
                nomes[cid] = nome
        R, D = tot[mes]["R"], tot[mes]["D"]
        hist = [m for m in anteriores if m in tot and (tot[m]["R"] or tot[m]["D"])]
        media_r = sum(tot[m]["R"] for m in hist) / len(hist) if hist else None
        media_d = sum(tot[m]["D"] for m in hist) / len(hist) if hist else None
        renda_base = R or media_r or Decimal(0)

        fixos = self.db.um("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos WHERE tipo = 'D' AND cartao_id IS NULL
                              AND total_parcelas > 1 AND data BETWEEN %s AND %s""", (mes, fim_mes(mes)))[0]
        cartoes = self.db.todos("""SELECT k.nome, k.limite, COALESCE(SUM(l.valor) FILTER (WHERE NOT l.pago), 0)
                                   FROM cartoes k LEFT JOIN lancamentos l ON l.cartao_id = k.id
                                   GROUP BY k.id, k.nome, k.limite ORDER BY k.nome""")
        futuras = self.db.um("""SELECT COALESCE(SUM(valor), 0) FROM lancamentos
                                WHERE cartao_id IS NOT NULL AND NOT pago AND fatura > %s""", (mes,))[0]
        atrasos = list(self.db.todos("""SELECT valor FROM lancamentos WHERE tipo = 'D' AND NOT pago
                                        AND cartao_id IS NULL AND data < %s""", (hoje,)))
        for dia_venc, fatura, total in self.db.todos(
                """SELECT k.dia_vencimento, l.fatura, SUM(l.valor) FROM lancamentos l JOIN cartoes k ON k.id = l.cartao_id
                   WHERE NOT l.pago GROUP BY k.id, k.dia_vencimento, l.fatura"""):
            if dia_no_mes(fatura, dia_venc) < hoje:
                atrasos.append((total,))
        metas = self.db.todos("SELECT descricao, valor_alvo, valor_atual, prazo FROM metas")
        orc = self.db.todos("""SELECT o.categoria_id, c.nome, o.limite FROM orcamentos o
                               JOIN categorias c ON c.id = o.categoria_id ORDER BY c.nome""")

        alertas = []
        self._indicadores(R, D, fixos, cartoes, futuras, renda_base, atrasos, media_d)
        self._alertas(alertas, mes, hoje, R, D, fixos, cartoes, futuras, renda_base, atrasos,
                      cat_mes, nomes, hist, metas, orc)
        serie = [(f"{MESES[m.month - 1][:3]}/{m.year % 100:02d}", tot[m]["R"], tot[m]["D"]) for m in meses]
        orcamentos = [(cid, nome, limite, cat_mes.get((mes, cid), Decimal(0))) for cid, nome, limite in orc]
        return alertas, serie, orcamentos

    # ---------- indicadores
    def _indicadores(self, R, D, fixos, cartoes, futuras, renda_base, atrasos, media_d):
        if R > 0:
            pct = (R - D) / R * 100
            self._card("poup", f"{pct:.0f}%", f"Sobra {brl(R - D)} da renda do mês. Referência: 20% ou mais.",
                       "verde" if pct >= 20 else "amarelo" if pct >= 0 else "vermelho")
            pf = fixos / R * 100
            self._card("fixos", f"{pf:.0f}%", f"{brl(fixos)} em despesas que se repetem todo mês. Ideal: até 50% da renda.",
                       "verde" if pf <= 50 else "amarelo" if pf <= 70 else "vermelho")
        else:
            self._card("poup", "—", "Sem receitas lançadas neste mês.")
            self._card("fixos", "—", f"{brl(fixos)} em despesas fixas. Lance as receitas para ver o percentual.")
        limite = sum((c[1] for c in cartoes), Decimal(0))
        usado = sum((c[2] for c in cartoes), Decimal(0))
        if limite > 0:
            pu = usado / limite * 100
            self._card("cartao", f"{pu:.0f}%", f"{brl(usado)} usados de {brl(limite)}. Ideal: até 30%.",
                       "verde" if pu <= 30 else "amarelo" if pu < 80 else "vermelho")
        else:
            self._card("cartao", "—", "Nenhum cartão com limite cadastrado.")
        if renda_base > 0:
            pp = futuras / renda_base * 100
            self._card("parc", brl(futuras), f"Parcelas de cartão das próximas faturas. Equivale a {pp:.0f}% "
                                             f"de uma renda mensal.",
                       "verde" if pp <= 30 else "amarelo" if pp <= 100 else "vermelho")
        else:
            self._card("parc", brl(futuras), "Parcelas de cartão das próximas faturas.")
        total_atraso = sum((a[0] for a in atrasos), Decimal(0))
        self._card("atraso", str(len(atrasos)), f"Somando {brl(total_atraso)}." if atrasos else "Nenhuma conta em atraso.",
                   "vermelho" if atrasos else "verde")
        if media_d:
            var = (D - media_d) / media_d * 100
            self._card("media", f"{var:+.0f}%", f"{brl(D)} neste mês. Média dos meses anteriores: {brl(media_d)}.",
                       "verde" if var <= 0 else "amarelo" if var <= 15 else "vermelho")
        else:
            self._card("media", "—", "Ainda não há histórico dos meses anteriores para comparar.")

    # ---------- orientações
    def _alertas(self, a, mes, hoje, R, D, fixos, cartoes, futuras, renda_base, atrasos,
                 cat_mes, nomes, hist, metas, orc):
        nome_mes = f"{MESES[mes.month - 1]}/{mes.year}"
        if not R and not D:
            a.append(("amarelo", f"Não há lançamentos em {nome_mes}. Lance receitas e despesas para receber a análise."))
            return
        gastos_mes = sorted(((v, nomes[c]) for (m, c), v in cat_mes.items() if m == mes), reverse=True)
        if not R:
            a.append(("amarelo", f"Não há receitas lançadas em {nome_mes}. Lance-as para que a análise fique completa."))
        elif D > R:
            maior = f" O maior gasto é {gastos_mes[0][1]} ({brl(gastos_mes[0][0])}); comece revendo esse item." \
                if gastos_mes else ""
            a.append(("vermelho", f"As despesas ({brl(D)}) superam as receitas ({brl(R)}) em {brl(D - R)}.{maior}"))
        else:
            pct = (R - D) / R * 100
            if pct < 10:
                a.append(("amarelo", f"Você vai guardar só {pct:.0f}% da renda. Tente chegar a 10% e depois aos 20% "
                                     f"da regra 50/30/20 (50% necessidades, 30% desejos, 20% poupança)."))
            elif pct < 20:
                a.append(("amarelo", f"Bom caminho: sobram {pct:.0f}% da renda. A referência da regra 50/30/20 "
                                     f"é guardar 20%."))
            else:
                a.append(("verde", f"Ótimo: sobram {pct:.0f}% da renda ({brl(R - D)}). Direcione esse valor para "
                                   f"suas metas ou para uma reserva de emergência."))
        if atrasos:
            total = sum((x[0] for x in atrasos), Decimal(0))
            a.append(("vermelho", f"{len(atrasos)} conta(s) atrasada(s) somando {brl(total)}. Atraso gera multa e juros; "
                                  f"priorize quitá-las (aba Contas a pagar)."))
        if R:
            pf = fixos / R * 100
            if pf > 50:
                a.append(("vermelho" if pf > 70 else "amarelo",
                          f"Os gastos fixos consomem {pf:.0f}% da renda. Acima de 50% sobra pouca folga; vale "
                          f"renegociar contratos como internet, planos e assinaturas."))
        for nome, limite, usado in cartoes:
            if limite > 0:
                pu = usado / limite * 100
                if pu >= 50:
                    a.append(("vermelho" if pu >= 80 else "amarelo",
                              f"O cartão {nome} está com {pu:.0f}% do limite usado. Evite novas compras nele até "
                              f"pagar as próximas faturas."))
        if renda_base > 0 and futuras > renda_base * Decimal("0.3"):
            a.append(("amarelo", f"Já existem {brl(futuras)} em parcelas futuras no cartão "
                                 f"({futuras / renda_base * 100:.0f}% de uma renda mensal). Evite novos parcelamentos."))
        if hist:
            acima = []
            for valor, cid in ((v, c) for (m, c), v in cat_mes.items() if m == mes):
                media = sum((cat_mes.get((h, cid), Decimal(0)) for h in hist), Decimal(0)) / len(hist)
                if media > 0 and valor > media * Decimal("1.3") and valor - media >= 50:
                    acima.append((valor - media, nomes[cid], valor, media))
            for _dif, nome, valor, media in sorted(acima, reverse=True)[:3]:
                a.append(("amarelo", f"{nome}: {brl(valor)} neste mês, {(valor - media) / media * 100:.0f}% acima "
                                     f"da sua média ({brl(media)})."))
        for cid, nome, limite in orc:
            gasto = cat_mes.get((mes, cid), Decimal(0))
            if limite > 0:
                pct = gasto / limite * 100
                if pct >= 100:
                    a.append(("vermelho", f"Orçamento de {nome} estourado: {brl(gasto)} de {brl(limite)} ({pct:.0f}%)."))
                elif pct >= 80:
                    a.append(("amarelo", f"Orçamento de {nome} quase no limite: {pct:.0f}% usado, restam "
                                         f"{brl(limite - gasto)}."))
        sobra = R - D if R else None
        for desc, alvo, atual, prazo in metas:
            falta = alvo - atual
            if falta <= 0 or not prazo:
                continue
            if prazo < hoje:
                a.append(("vermelho", f"Meta {desc}: o prazo venceu e ainda faltam {brl(falta)}. Defina um novo prazo "
                                      f"ou aumente os depósitos."))
                continue
            n = max((prazo.year - hoje.year) * 12 + prazo.month - hoje.month, 1)
            nec = falta / n
            if sobra is not None and nec > sobra:
                a.append(("amarelo", f"Meta {desc}: é preciso guardar {brl(nec)} por mês até {dbr(prazo)}, mas a sobra "
                                     f"prevista deste mês é {brl(sobra)}."))
            else:
                a.append(("verde", f"Meta {desc}: guarde {brl(nec)} por mês até {dbr(prazo)} para chegar lá."))
        if not any(s in ("vermelho", "amarelo") for s, _ in a):
            a.append(("verde", "Nenhum ponto de atenção neste mês."))
