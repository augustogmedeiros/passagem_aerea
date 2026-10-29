"""Monitor de passagens aéreas (Google Flights via fast-flights) com alertas no Telegram.

Uso:
    python buscar_passagens.py                  # busca, salva histórico e envia alertas
    python buscar_passagens.py --teste          # busca e só imprime (não envia nada)
    python buscar_passagens.py --descobrir-chat # lista chat_ids de quem mandou mensagem ao bot
"""

import argparse
import csv
import json
import random
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

import requests
from fast_flights import FlightQuery, FlightsNotFound, Passengers, create_query, get_flights

PASTA = Path(__file__).resolve().parent
ARQ_CONFIG = PASTA / "config.json"
ARQ_ESTADO = PASTA / "estado.json"
ARQ_HISTORICO = PASTA / "historico.csv"
ARQ_LOG = PASTA / "execucoes.log"


def log(msg):
    linha = f"[{datetime.now():%Y-%m-%d %H:%M:%S}] {msg}"
    print(linha)
    with ARQ_LOG.open("a", encoding="utf-8") as f:
        f.write(linha + "\n")


def carregar_json(caminho, padrao):
    if not caminho.exists():
        return padrao
    return json.loads(caminho.read_text(encoding="utf-8"))


def salvar_json(caminho, dados):
    caminho.write_text(json.dumps(dados, ensure_ascii=False, indent=2), encoding="utf-8")


# ---------------------------------------------------------------- busca

def gerar_combinacoes(cfg):
    """Gera (origem, destino, ida, volta|None) para todas as datas da janela."""
    datas = cfg["datas_ida"]
    inicio = date.fromisoformat(datas["de"])
    fim = date.fromisoformat(datas["ate"])
    passo = timedelta(days=datas.get("passo_dias", 1))
    estadias = cfg.get("duracao_estadia_dias") or [None]  # vazio/null = só ida

    hoje = date.today()
    combos = []
    d = max(inicio, hoje + timedelta(days=1))
    while d <= fim:
        for origem in cfg["origens"]:
            for destino in cfg["destinos"]:
                for estadia in estadias:
                    volta = d + timedelta(days=estadia) if estadia else None
                    combos.append((origem, destino, d, volta))
        d += passo
    return combos


def montar_query(cfg, origem, destino, ida, volta):
    trechos = [FlightQuery(date=ida.isoformat(), from_airport=origem, to_airport=destino)]
    if volta:
        trechos.append(FlightQuery(date=volta.isoformat(), from_airport=destino, to_airport=origem))
    return create_query(
        flights=trechos,
        trip="round-trip" if volta else "one-way",
        seat=cfg.get("classe", "economy"),
        passengers=Passengers(adults=cfg.get("adultos", 1)),
        max_stops=cfg.get("max_escalas"),
        currency="BRL",
        language="pt-BR",
    )


def buscar(cfg, origem, destino, ida, volta, tentativas=2):
    query = montar_query(cfg, origem, destino, ida, volta)
    for tentativa in range(1, tentativas + 1):
        try:
            resultados = get_flights(query)
            return [
                {
                    "origem": origem,
                    "destino": destino,
                    "ida": ida.isoformat(),
                    "volta": volta.isoformat() if volta else None,
                    "preco": voo.price,
                    "cias": ", ".join(voo.airlines),
                    "escalas": len(voo.flights) - 1,
                    "duracao_min": sum(t.duration for t in voo.flights),
                    "link": query.url(),
                }
                for voo in resultados
                if voo.price  # às vezes vem 0 quando o Google não mostra preço
            ]
        except FlightsNotFound:
            return []
        except Exception as e:  # rede, bloqueio, mudança no HTML do Google...
            log(f"  erro {origem}->{destino} {ida} (tentativa {tentativa}): {e!r}")
            time.sleep(10 * tentativa)
    raise RuntimeError(f"falha ao buscar {origem}->{destino} {ida}")


def salvar_historico(ofertas):
    novo = not ARQ_HISTORICO.exists()
    agora = datetime.now().isoformat(timespec="minutes")
    # guarda só a mais barata de cada combinação para o CSV não explodir
    melhores = {}
    for o in ofertas:
        chave = (o["origem"], o["destino"], o["ida"], o["volta"])
        if chave not in melhores or o["preco"] < melhores[chave]["preco"]:
            melhores[chave] = o
    with ARQ_HISTORICO.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f, delimiter=";")
        if novo:
            w.writerow(["consulta", "origem", "destino", "ida", "volta", "preco", "cias", "escalas"])
        for o in melhores.values():
            w.writerow([agora, o["origem"], o["destino"], o["ida"], o["volta"] or "", o["preco"], o["cias"], o["escalas"]])


# ---------------------------------------------------------------- telegram

def telegram(cfg, chat_id, texto):
    token = cfg["telegram"]["token"]
    r = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={"chat_id": chat_id, "text": texto, "parse_mode": "HTML", "disable_web_page_preview": True},
        timeout=20,
    )
    if not r.ok:
        log(f"  falha no Telegram ({chat_id}): {r.status_code} {r.text}")


def descobrir_chat(cfg):
    token = cfg["telegram"]["token"]
    r = requests.get(f"https://api.telegram.org/bot{token}/getUpdates", timeout=20).json()
    if not r.get("result"):
        print("Nenhuma mensagem encontrada. Mande um 'oi' para o bot no Telegram e rode de novo.")
        return
    vistos = set()
    for upd in r["result"]:
        chat = (upd.get("message") or upd.get("my_chat_member") or {}).get("chat")
        if chat and chat["id"] not in vistos:
            vistos.add(chat["id"])
            nome = chat.get("first_name") or chat.get("title") or ""
            print(f"chat_id = {chat['id']}  ({nome} @{chat.get('username', '')})")


def fmt_reais(valor):
    return "R$ " + f"{valor:,.0f}".replace(",", ".")


def fmt_data(iso):
    return date.fromisoformat(iso).strftime("%d/%m/%Y")


def fmt_oferta(o):
    escalas = "voo direto" if o["escalas"] == 0 else f"{o['escalas']} escala(s)"
    horas = f"{o['duracao_min'] // 60}h{o['duracao_min'] % 60:02d}"
    datas = f"ida {fmt_data(o['ida'])}" + (f", volta {fmt_data(o['volta'])}" if o["volta"] else "")
    return (
        f"<b>{fmt_reais(o['preco'])}</b> — {o['origem']} → {o['destino']}\n"
        f"{datas}\n"
        f"{o['cias']} · {escalas} · {horas} voando na ida (sem contar conexão)\n"
        f"<a href=\"{o['link']}\">Ver no Google Flights</a>"
    )


def mensagem_alerta(cfg, top, motivo):
    pax = cfg.get("adultos", 1)
    tipo = "ida e volta" if top[0]["volta"] else "só ida"
    cab = {
        "novo": "✈️ <b>Passagem abaixo do preço alvo!</b>",
        "caiu": "📉 <b>O preço caiu ainda mais!</b>",
        "lembrete": "⏰ <b>Ainda está barato</b>",
    }[motivo]
    corpo = "\n\n".join(fmt_oferta(o) for o in top)
    return (
        f"{cab}\n"
        f"Preço total ({tipo}, {pax} adulto(s)). Alvo: {fmt_reais(cfg['preco_alvo'])}\n\n"
        f"{corpo}\n\n"
        f"<i>Os preços mudam rápido — confira no site antes de comprar.</i>"
    )


# ---------------------------------------------------------------- regras de alerta

def decidir_alerta(cfg, estado, melhor):
    """Retorna o motivo do alerta ou None. Evita mandar a mesma oferta várias vezes."""
    if melhor["preco"] > cfg["preco_alvo"]:
        return None
    ultimo = estado.get("ultimo_alerta")
    if not ultimo:
        return "novo"
    queda = cfg.get("queda_minima_pct", 5) / 100
    if melhor["preco"] <= ultimo["preco"] * (1 - queda):
        return "caiu"
    horas = (datetime.now() - datetime.fromisoformat(ultimo["quando"])).total_seconds() / 3600
    if horas >= cfg.get("lembrete_horas", 48):
        return "lembrete"
    return None


def top_ofertas(ofertas, n=3):
    """As n mais baratas, sem repetir a mesma combinação de datas/aeroportos."""
    vistas, top = set(), []
    for o in sorted(ofertas, key=lambda o: o["preco"]):
        chave = (o["origem"], o["destino"], o["ida"], o["volta"])
        if chave not in vistas:
            vistas.add(chave)
            top.append(o)
        if len(top) == n:
            break
    return top


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--teste", action="store_true", help="não envia Telegram nem altera o estado")
    ap.add_argument("--descobrir-chat", action="store_true")
    args = ap.parse_args()

    cfg = carregar_json(ARQ_CONFIG, None)
    if cfg is None:
        sys.exit("config.json não encontrado.")

    if args.descobrir_chat:
        descobrir_chat(cfg)
        return

    combos = gerar_combinacoes(cfg)
    limite = cfg.get("max_buscas_por_execucao", 60)
    if len(combos) > limite:
        log(f"{len(combos)} combinações; limitando a {limite} (aumente o passo_dias ou o limite)")
        combos = combos[:limite]
    log(f"Iniciando {len(combos)} buscas")

    ofertas, falhas = [], 0
    for i, (origem, destino, ida, volta) in enumerate(combos):
        if i:
            time.sleep(random.uniform(3, 7))  # ritmo "humano" para não ser bloqueado
        try:
            achadas = buscar(cfg, origem, destino, ida, volta)
        except RuntimeError as e:
            falhas += 1
            log(f"  {e}")
            continue
        ofertas.extend(achadas)
        menor = min((o["preco"] for o in achadas), default=None)
        log(f"  {origem}->{destino} {ida}{' / ' + str(volta) if volta else ''}: "
            f"{fmt_reais(menor) if menor else 'sem resultados'}")

    admin = cfg["telegram"].get("chat_id_admin")
    if not ofertas:
        log(f"Nenhuma oferta encontrada ({falhas} falhas)")
        if falhas and not args.teste and admin:
            telegram(cfg, admin, f"⚠️ Bot de passagens: todas as buscas falharam ({falhas}). "
                                 f"Pode ser bloqueio ou mudança no Google Flights — veja execucoes.log.")
        return

    top = top_ofertas(ofertas)
    melhor = top[0]
    log(f"Melhor: {fmt_reais(melhor['preco'])} {melhor['origem']}->{melhor['destino']} "
        f"{melhor['ida']} {melhor['cias']}")

    if args.teste:
        print("\n--- mensagem que seria enviada ---\n")
        print(mensagem_alerta(cfg, top, "novo"))
        return

    salvar_historico(ofertas)
    estado = carregar_json(ARQ_ESTADO, {})

    # aviso só para você (admin) quando aparece um novo mínimo histórico,
    # mesmo acima do alvo — ajuda a calibrar o preco_alvo
    minimo = estado.get("menor_preco_visto")
    if admin and (minimo is None or melhor["preco"] < minimo):
        telegram(cfg, admin, "🔎 Novo menor preço já visto pelo bot:\n\n" + fmt_oferta(melhor))
    if minimo is None or melhor["preco"] < minimo:
        estado["menor_preco_visto"] = melhor["preco"]

    motivo = decidir_alerta(cfg, estado, melhor)
    if motivo:
        texto = mensagem_alerta(cfg, top, motivo)
        for chat_id in cfg["telegram"]["chat_ids_alerta"]:
            telegram(cfg, chat_id, texto)
        estado["ultimo_alerta"] = {"preco": melhor["preco"], "quando": datetime.now().isoformat()}
        log(f"Alerta enviado ({motivo})")
    elif estado.get("ultimo_alerta") and melhor["preco"] > cfg["preco_alvo"]:
        # a promoção acabou: zera para que a próxima queda gere um alerta "novo"
        del estado["ultimo_alerta"]

    salvar_json(ARQ_ESTADO, estado)


if __name__ == "__main__":
    main()
