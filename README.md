# Bot de passagens Brasil → EUA

Busca preços no Google Flights (via `fast-flights`), guarda o histórico e avisa no Telegram
quando o preço fica abaixo do alvo.

## 0. Primeira vez numa máquina nova

```powershell
copy config.exemplo.json config.json   # config.json não vai para o git (tem o token)
```
Depois siga "Reinstalar do zero" no fim deste arquivo.

## 1. Criar o bot no Telegram (5 min)

1. No Telegram, abra o **@BotFather** → `/newbot` → escolha um nome. Ele devolve um **token**.
2. Cole o token em `config.json` → `telegram.token`.
3. Você e sua mãe mandam um "oi" para o bot novo.
4. Rode `.venv\Scripts\python.exe buscar_passagens.py --descobrir-chat` — aparecem os `chat_id`.
5. No `config.json`:
   - `chat_ids_alerta`: os chat_ids de quem recebe as promoções (sua mãe, e você se quiser).
   - `chat_id_admin`: o seu — recebe avisos de erro e de "novo menor preço visto".

## 2. Ajustar a busca (`config.json`)

| Campo | O que é |
|---|---|
| `origens` / `destinos` | Códigos IATA. Ex.: GRU, VCP, GIG, BSB, CNF, REC → MCO, MIA, FLL, JFK, EWR |
| `datas_ida.de` / `ate` | Janela de datas de ida |
| `datas_ida.passo_dias` | Testa uma data a cada N dias (1 = todo dia, mais buscas) |
| `duracao_estadia_dias` | Dias de estadia, ex. `[14, 21]`. Use `[]` para só ida |
| `max_escalas` | `0` = só direto, `1`, ou `null` = qualquer |
| `preco_alvo` | Valor total em R$ (todos os passageiros) que dispara o alerta |
| `queda_minima_pct` | Depois de avisar, só avisa de novo se cair mais X% |
| `lembrete_horas` | ...ou se continuar barato depois de X horas |

Total de buscas = datas × origens × destinos × estadias. Mantenha abaixo de ~60.

## 3. Testar e agendar

```powershell
.venv\Scripts\python.exe buscar_passagens.py --teste     # busca e mostra a mensagem, não envia
.venv\Scripts\python.exe buscar_passagens.py             # execução real
powershell -ExecutionPolicy Bypass -File agendar.ps1     # roda 8h, 14h e 20h todo dia
```

O PC precisa estar ligado (se estiver desligado no horário, roda quando ligar).

## Arquivos gerados

- `historico.csv` — menor preço de cada combinação por consulta (abre no Excel)
- `estado.json` — último alerta enviado (evita repetir mensagem)
- `execucoes.log` — log de cada execução

## Reinstalar do zero

```powershell
uv venv --python 3.12 .venv
uv pip install --python .venv\Scripts\python.exe -r requirements.txt
```
