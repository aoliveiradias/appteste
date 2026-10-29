# Resumo diário IA + Dev

Projeto de estudo: lê feeds RSS sobre desenvolvimento de software com IA e manda
uma lista de títulos + links no Telegram todo dia às 8h (horário de Brasília),
via GitHub Actions.

## Como funciona

- `feeds.yaml`: fontes. Adicione/remova à vontade. `filtrar: true` faz a fonte
  passar pelo filtro de palavras-chave (útil para fontes generalistas).
- `config.yaml`: janela de tempo, limites de itens e palavras-chave.
- `digest.py`: baixa os feeds, filtra as últimas ~26h, remove duplicados e envia.
  Se uma fonte falhar, as outras seguem e o nome dela aparece no rodapé.

A Anthropic não publica um feed RSS oficial, por isso ela não está na lista.

## Rodar localmente

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python digest.py --dry-run          # só imprime
.venv/bin/python digest.py --dry-run --hours 72
.venv/bin/python digest.py                    # envia (precisa do .env)
```

`.env` (não vai para o git):

```
TELEGRAM_BOT_TOKEN=123456:ABC...
TELEGRAM_CHAT_ID=123456789
```

## Configurar o Telegram

1. No Telegram, fale com o **@BotFather**, envie `/newbot` e siga os passos.
   Ele devolve o **token** do bot.
2. Abra a conversa com o seu bot e mande qualquer mensagem (ex.: `oi`).
3. No navegador, acesse `https://api.telegram.org/bot<TOKEN>/getUpdates` e
   procure `"chat":{"id": ...}`. Esse número é o **chat_id**.

## Configurar o GitHub Actions

1. Crie um repositório no GitHub e faça o push deste projeto.
2. Em **Settings → Secrets and variables → Actions → New repository secret**,
   crie `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
3. Em **Actions → Resumo diário IA + Dev → Run workflow**, rode uma vez para testar.

O agendamento do GitHub pode atrasar alguns minutos. Repositórios sem nenhuma
atividade por 60 dias têm os workflows agendados pausados; basta reativar na aba Actions.
