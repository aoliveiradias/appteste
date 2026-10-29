"""Resumo diário de notícias de IA + desenvolvimento de software, enviado no Telegram."""

from __future__ import annotations

import argparse
import calendar
import html
import os
import re
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

# O Python do macOS usa LibreSSL e o urllib3 avisa disso a cada execução; é inofensivo aqui.
warnings.filterwarnings("ignore", message="urllib3 v2 only supports OpenSSL")

import feedparser  # noqa: E402
import requests  # noqa: E402
import yaml

BASE_DIR = Path(__file__).resolve().parent
USER_AGENT = "ai-dev-digest/1.0 (projeto de estudo; leitor de RSS)"
TELEGRAM_LIMIT = 4000  # o limite real é 4096; deixa folga


def load_yaml(name: str):
    with open(BASE_DIR / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_dotenv(path: Path) -> None:
    """Lê um .env simples (CHAVE=valor) sem sobrescrever variáveis já definidas."""
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def normalize_url(url: str) -> str:
    """Remove parâmetros de rastreamento, fragmento e barra final para deduplicar."""
    parts = urlsplit(url.strip())
    query = [(k, v) for k, v in parse_qsl(parts.query) if not k.lower().startswith("utm_")]
    path = parts.path.rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, urlencode(query), ""))


def entry_timestamp(entry) -> float | None:
    parsed = entry.get("published_parsed") or entry.get("updated_parsed")
    if not parsed:
        return None
    return calendar.timegm(parsed)


def fetch_feeds(feeds: list[dict]) -> tuple[list[dict], list[str]]:
    """Baixa todas as fontes. Uma fonte com erro não derruba as outras."""
    items, failures = [], []
    for feed in feeds:
        try:
            resp = requests.get(feed["url"], headers={"User-Agent": USER_AGENT}, timeout=20)
            resp.raise_for_status()
            parsed = feedparser.parse(resp.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError(f"feed inválido: {parsed.bozo_exception}")
        except Exception as exc:  # noqa: BLE001 - qualquer falha vira aviso no rodapé
            print(f"[erro] {feed['nome']}: {exc}", file=sys.stderr)
            failures.append(feed["nome"])
            continue

        for entry in parsed.entries:
            link = entry.get("link")
            title = (entry.get("title") or "").strip()
            if not link or not title:
                continue
            items.append(
                {
                    "titulo": title,
                    "link": link,
                    "resumo": entry.get("summary", ""),
                    "ts": entry_timestamp(entry),
                    "fonte": feed["nome"],
                    "categoria": feed["categoria"],
                    "filtrar": feed.get("filtrar", False),
                }
            )
        print(f"[ok] {feed['nome']}: {len(parsed.entries)} itens", file=sys.stderr)
    return items, failures


def build_keyword_regex(keywords: list[str]) -> re.Pattern:
    alternatives = "|".join(re.escape(k) for k in keywords)
    return re.compile(rf"(?<!\w)(?:{alternatives})(?!\w)", re.IGNORECASE)


def filter_items(items: list[dict], cfg: dict, hours: float) -> list[dict]:
    cutoff = time.time() - hours * 3600
    keyword_re = build_keyword_regex(cfg["palavras_chave"])
    blocked = cfg.get("palavras_bloqueadas") or []
    blocked_re = build_keyword_regex(blocked) if blocked else None
    seen, per_source, result = set(), {}, []

    for item in sorted(items, key=lambda i: i["ts"] or 0, reverse=True):
        if item["ts"] is None or item["ts"] < cutoff:
            continue
        text = f"{item['titulo']} {item['resumo']}"
        if blocked_re and blocked_re.search(text):
            continue
        if item["filtrar"] and not keyword_re.search(text):
            continue
        key = normalize_url(item["link"])
        if key in seen:
            continue
        if per_source.get(item["fonte"], 0) >= cfg["max_por_fonte"]:
            continue
        seen.add(key)
        per_source[item["fonte"]] = per_source.get(item["fonte"], 0) + 1
        result.append(item)
        if len(result) >= cfg["max_total"]:
            break
    return result


def format_message(items: list[dict], failures: list[str], category_order: list[str]) -> list[str]:
    """Monta a mensagem em HTML do Telegram, dividida em partes de até TELEGRAM_LIMIT."""
    today = datetime.now(timezone.utc).astimezone().strftime("%d/%m/%Y")
    # Cada "unidade" (texto, categoria) nunca é quebrada entre mensagens; o título
    # da categoria vai junto com o primeiro item para não ficar sozinho no fim de uma
    # parte, e é repetido quando a categoria continua na parte seguinte.
    units = [(f"<b>🤖 IA + Dev — {today}</b>", None)]

    if not items:
        units.append(("\nNada novo nas últimas horas.", None))
    for category in category_order:
        group = [i for i in items if i["categoria"] == category]
        if not group:
            continue
        for n, item in enumerate(group):
            href = html.escape(item["link"], quote=True)
            title = html.escape(item["titulo"])
            line = f'• <a href="{href}">{title}</a> — <i>{html.escape(item["fonte"])}</i>'
            if n == 0:
                line = f"\n<b>{html.escape(category)}</b>\n{line}"
            units.append((line, category))

    if failures:
        units.append((f"\n<i>⚠️ Não consegui ler: {html.escape(', '.join(failures))}</i>", None))

    chunks, current = [], ""
    for unit, category in units:
        if current and len(current) + len(unit) + 1 > TELEGRAM_LIMIT:
            chunks.append(current.rstrip())
            current = ""
            unit = unit.lstrip("\n")
            if category and not unit.startswith("<b>"):
                unit = f"<b>{html.escape(category)} (cont.)</b>\n{unit}"
        current += unit + "\n"
    if current.strip():
        chunks.append(current.rstrip())
    return chunks


def send_telegram(token: str, chat_id: str, text: str) -> None:
    resp = requests.post(
        f"https://api.telegram.org/bot{token}/sendMessage",
        json={
            "chat_id": chat_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        },
        timeout=20,
    )
    if not resp.ok:
        raise RuntimeError(f"Telegram respondeu {resp.status_code}: {resp.text}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="imprime a mensagem sem enviar")
    parser.add_argument("--hours", type=float, help="janela de tempo em horas (padrão: config.yaml)")
    args = parser.parse_args()

    load_dotenv(BASE_DIR / ".env")
    feeds = load_yaml("feeds.yaml")
    cfg = load_yaml("config.yaml")

    items, failures = fetch_feeds(feeds)
    selected = filter_items(items, cfg, args.hours or cfg["janela_horas"])
    category_order = list(dict.fromkeys(f["categoria"] for f in feeds))
    chunks = format_message(selected, failures, category_order)

    if args.dry_run:
        print("\n\n---\n\n".join(chunks))
        return 0

    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID (ou use --dry-run).", file=sys.stderr)
        return 1

    for chunk in chunks:
        send_telegram(token, chat_id, chunk)
    print(f"Enviado: {len(selected)} itens em {len(chunks)} mensagem(ns).", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
