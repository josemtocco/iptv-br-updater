#!/usr/bin/env python3
"""
IPTV-BR Updater
---------------
Baixa listas M3U de fontes publicas/legais, valida cada stream ao vivo
e gera listas limpas:

  playlists/canais_br_todos.m3u      -> todos os canais coletados (dedup)
  playlists/canais_br_estaveis.m3u   -> apenas canais que passaram no teste
  playlists/report.md                -> relatorio da ultima execucao

Uso:
  python update_playlist.py --config sources.yaml --workers 40 --timeout 8

Dependencias: requests, PyYAML  (veja requirements.txt)
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import os
import re
import sys
import urllib.parse

try:
    import requests
except ImportError:
    sys.exit("Falta a dependencia 'requests'. Rode: pip install -r requirements.txt")

try:
    import yaml
except ImportError:
    sys.exit("Falta a dependencia 'PyYAML'. Rode: pip install -r requirements.txt")


HERE = os.path.dirname(os.path.abspath(__file__))
UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
EXTINF_RE = re.compile(r'^#EXTINF:', re.IGNORECASE)
NAME_RE = re.compile(r',(.+)$')
ATTR_RE = re.compile(r'([a-zA-Z0-9_-]+)="([^"]*)"')


class Channel:
    """Uma entrada de canal (metadados + URL do stream)."""

    __slots__ = ("name", "url", "attrs", "extra", "group", "source", "ok", "detail")

    def __init__(self, name, url, attrs, extra, source):
        self.name = name.strip()
        self.url = url.strip()
        self.attrs = attrs            # dict de atributos tvg-*
        self.extra = extra            # linhas extras (#EXTVLCOPT etc.)
        self.group = attrs.get("group-title", "")
        self.source = source
        self.ok = None                # resultado do health-check
        self.detail = ""

    def key(self):
        """Chave de deduplicacao: nome normalizado."""
        n = self.name.lower()
        n = re.sub(r'\s*\(.*?\)', '', n)           # remove (720p) etc.
        n = re.sub(r'\[.*?\]', '', n)              # remove [Not 24/7] etc.
        n = re.sub(r'[^a-z0-9]+', '', n)
        return n

    def to_m3u(self):
        attr_str = "".join(f' {k}="{v}"' for k, v in self.attrs.items())
        lines = [f'#EXTINF:-1{attr_str},{self.name}']
        lines.extend(self.extra)
        lines.append(self.url)
        return "\n".join(lines)


def parse_m3u(text, source):
    """Converte o texto de uma lista M3U em objetos Channel."""
    channels = []
    lines = [l.rstrip("\n") for l in text.splitlines()]
    i = 0
    while i < len(lines):
        line = lines[i].strip()
        if EXTINF_RE.match(line):
            attrs = dict(ATTR_RE.findall(line))
            m = NAME_RE.search(line)
            name = m.group(1).strip() if m else "Sem nome"
            extra = []
            j = i + 1
            # captura linhas auxiliares (#EXTVLCOPT, #EXTGRP ...) ate a URL
            while j < len(lines):
                nxt = lines[j].strip()
                if not nxt:
                    j += 1
                    continue
                if nxt.startswith("#") and not nxt.startswith("#EXTINF"):
                    extra.append(nxt)
                    j += 1
                    continue
                break
            if j < len(lines) and not lines[j].strip().startswith("#"):
                url = lines[j].strip()
                if url:
                    channels.append(Channel(name, url, attrs, extra, source))
                i = j + 1
                continue
        i += 1
    return channels


def download(url, timeout):
    r = requests.get(url, headers={"User-Agent": UA}, timeout=timeout)
    r.raise_for_status()
    return r.text


def host_of(url):
    try:
        return urllib.parse.urlparse(url).hostname or ""
    except Exception:
        return ""


def is_blocked(ch, blocklist):
    """True se o canal cair em um dominio/palavra da blocklist (anti-pirata)."""
    hay = (ch.url + " " + ch.name + " " + ch.group).lower()
    return any(b.lower() in hay for b in blocklist)


def health_check(ch, timeout):
    """Verifica se o stream responde. Marca ch.ok e ch.detail.
    Considera OK quando: status 200 e (content-type de HLS OU corpo e um
    manifesto #EXTM3U)."""
    headers = {"User-Agent": UA}
    for e in ch.extra:
        if "http-referrer=" in e:
            headers["Referer"] = e.split("http-referrer=", 1)[1].strip()
        if "http-user-agent=" in e:
            headers["User-Agent"] = e.split("http-user-agent=", 1)[1].strip()
    try:
        r = requests.get(ch.url, headers=headers, timeout=timeout,
                         stream=True, allow_redirects=True)
        code = r.status_code
        ctype = r.headers.get("Content-Type", "").lower()
        body = ""
        try:
            body = next(r.iter_content(2048)).decode("utf-8", "ignore")
        except Exception:
            body = ""
        r.close()
        if code == 200 and ("mpegurl" in ctype or "#EXTM3U" in body
                            or "#EXTINF" in body or "video" in ctype
                            or "octet-stream" in ctype):
            ch.ok = True
            ch.detail = f"200 {ctype or 'ok'}"
        else:
            ch.ok = False
            ch.detail = f"HTTP {code} ctype={ctype or '?'}"
    except Exception as exc:
        ch.ok = False
        ch.detail = type(exc).__name__
    return ch


def dedup(channels):
    """Remove duplicados por nome, preferindo os que passaram no teste e https."""
    best = {}
    for ch in channels:
        k = ch.key()
        if not k:
            continue
        cur = best.get(k)
        if cur is None:
            best[k] = ch
            continue
        # criterio: ok > nao-testado > falhou ; depois https > http
        def score(c):
            s = 0
            if c.ok is True:
                s += 4
            elif c.ok is None:
                s += 2
            if c.url.startswith("https"):
                s += 1
            return s
        if score(ch) > score(cur):
            best[k] = ch
    return list(best.values())


def write_m3u(path, channels, header_note):
    out = ["#EXTM3U", f"# {header_note}",
           f"# Gerado em: {dt.datetime.now().isoformat(timespec='seconds')}",
           f"# Total de canais: {len(channels)}", ""]
    for ch in sorted(channels, key=lambda c: (c.group.lower(), c.name.lower())):
        out.append(ch.to_m3u())
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(out) + "\n")


def write_report(path, sources, total, stable, failed, elapsed):
    lines = [
        "# Relatorio de atualizacao - IPTV BR", "",
        f"- Data: {dt.datetime.now().isoformat(timespec='seconds')}",
        f"- Tempo de execucao: {elapsed:.1f}s",
        f"- Canais coletados (dedup): {total}",
        f"- Canais estaveis (passaram): {stable}",
        f"- Canais fora do ar: {failed}",
        "", "## Fontes", "",
    ]
    for s in sources:
        lines.append(f"- {s}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def main():
    ap = argparse.ArgumentParser(description="Atualiza listas M3U de TV BR")
    ap.add_argument("--config", default=os.path.join(HERE, "sources.yaml"))
    ap.add_argument("--outdir", default=os.path.join(HERE, "playlists"))
    ap.add_argument("--workers", type=int, default=40)
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--no-check", action="store_true",
                    help="nao faz health-check (so coleta e dedup)")
    args = ap.parse_args()

    with open(args.config, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    sources = cfg.get("sources", [])
    blocklist = cfg.get("blocklist", [])
    allow_groups = [g.lower() for g in cfg.get("only_groups", [])]

    os.makedirs(args.outdir, exist_ok=True)
    t0 = dt.datetime.now()

    all_ch = []
    for src in sources:
        try:
            txt = download(src, args.timeout)
            got = parse_m3u(txt, src)
            print(f"[fonte] {src} -> {len(got)} canais")
            all_ch.extend(got)
        except Exception as e:
            print(f"[erro ] {src}: {e}")

    # filtro anti-pirata e filtro de grupos (opcional)
    all_ch = [c for c in all_ch if not is_blocked(c, blocklist)]
    if allow_groups:
        all_ch = [c for c in all_ch
                  if any(g in c.group.lower() for g in allow_groups)]

    all_ch = dedup(all_ch)
    print(f"[dedup] {len(all_ch)} canais unicos")

    stable = all_ch
    if not args.no_check:
        with cf.ThreadPoolExecutor(max_workers=args.workers) as ex:
            futs = [ex.submit(health_check, c, args.timeout) for c in all_ch]
            for _ in cf.as_completed(futs):
                pass
        stable = [c for c in all_ch if c.ok]
        print(f"[check] {len(stable)}/{len(all_ch)} canais no ar")

    write_m3u(os.path.join(args.outdir, "canais_br_todos.m3u"), all_ch,
              "Todos os canais coletados (fontes publicas/legais)")
    write_m3u(os.path.join(args.outdir, "canais_br_estaveis.m3u"), stable,
              "Apenas canais verificados ao vivo")

    elapsed = (dt.datetime.now() - t0).total_seconds()
    write_report(os.path.join(args.outdir, "report.md"), sources,
                 len(all_ch), len(stable), len(all_ch) - len(stable), elapsed)
    print(f"[ok   ] concluido em {elapsed:.1f}s")


if __name__ == "__main__":
    main()
