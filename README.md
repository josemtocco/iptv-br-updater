# IPTV-BR Updater

Projeto que coleta canais de TV brasileiros de **fontes publicas/legais**,
**valida cada stream ao vivo** e gera listas `.m3u` limpas — com
**atualizacao periodica automatica**.

## O que ele faz

1. Baixa listas M3U das fontes definidas em `sources.yaml`
   (por padrao: `iptv-org` e `Free-TV/IPTV` — projetos abertos no GitHub).
2. Remove duplicados (mantendo a melhor versao de cada canal) e aplica uma
   **blocklist anti-pirata** (descarta Premiere, Telecine, HBO, SporTV etc.).
3. Testa cada URL ao vivo (HTTP + verificacao de manifesto HLS).
4. Gera as listas:
   - `playlists/canais_br_todos.m3u` — tudo que foi coletado (dedup).
   - `playlists/canais_br_estaveis.m3u` — **somente os canais no ar**.
   - `playlists/report.md` — relatorio da ultima execucao.

## Como rodar localmente

> Precisa de Python 3.9+ e acesso a internet.

```bash
pip install -r requirements.txt
python update_playlist.py --workers 40 --timeout 8
```

ou simplesmente:

```bash
bash run.sh
```

Opcoes uteis:

| Flag          | Padrao | Descricao                                   |
|---------------|--------|---------------------------------------------|
| `--workers`   | 40     | validacoes simultaneas                      |
| `--timeout`   | 8      | timeout por stream (segundos)               |
| `--no-check`  | off    | so coleta e deduplica, sem testar os streams|
| `--config`    | sources.yaml | arquivo de configuracao               |
| `--outdir`    | playlists | pasta de saida                          |

## Atualizacao periodica (3 opcoes)

### Opcao A — GitHub Actions (recomendado, sem servidor)

Ja incluso em `.github/workflows/update-playlist.yml`.
Suba este projeto para um repositorio GitHub e pronto: ele roda
**todo dia as 06:00 UTC** e faz commit das listas atualizadas.

Como usar os links no seu player (apos o 1o commit):

```
https://raw.githubusercontent.com/SEU_USUARIO/SEU_REPO/main/playlists/canais_br_estaveis.m3u
```

Voce tambem pode rodar manualmente na aba **Actions -> Run workflow**.

### Opcao B — cron no seu Linux/Mac

```bash
crontab -e
# roda todo dia as 03:00
0 3 * * * cd /caminho/para/iptv-br-updater && /usr/bin/bash run.sh >> cron.log 2>&1
```

### Opcao C — Agendador de Tarefas do Windows

Crie uma tarefa que execute diariamente:

```
python C:\caminho\iptv-br-updater\update_playlist.py
```

## Como adicionar mais canais / fontes

Edite `sources.yaml`:

- **`sources`**: adicione URLs de outras listas M3U publicas.
- **`only_groups`**: para manter so certos grupos (ex.: publicos, cultura).
- **`blocklist`**: termos para descartar (anti-pirata / adulto / lixo).

## Aviso legal

Este projeto usa apenas **fontes publicas de canais abertos, educativos,
governamentais e FAST (gratuitos com anuncios)**. A `blocklist` existe
justamente para evitar canais fechados redistribuidos ilegalmente.
Nao use este projeto para acessar conteudo pirata.

Streams de IPTV mudam de endereco com frequencia — por isso a validacao
automatica: canais fora do ar sao removidos da lista `estaveis` a cada rodada.
