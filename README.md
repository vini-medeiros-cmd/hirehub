# HireHub

**O hub das oportunidades, seu próximo emprego começa aqui.**

Agregador público e gratuito de vagas. Coleta anúncios de quatro plataformas de
recrutamento, normaliza tudo numa base própria e serve num só lugar — sem
cadastro, sem login, sem candidatura interna. O botão *Candidatar-se* leva para
a vaga original.

```
Coletar → Normalizar → Armazenar → Exibir → Redirecionar
```

O que o visitante vê é simples de propósito: entrei → pesquisei → encontrei →
cliquei → me candidatei. A complexidade fica nos bastidores.

---

## Como rodar

Não há nada para instalar. Python 3.11+ e só a biblioteca padrão.

```bash
python3 bin/coletar.py     # roda uma coleta (~2 a 10 min)
python3 bin/servir.py      # sobe o site em http://localhost:8080
```

Para coletar de uma fonte só, útil ao mexer num conector:

```bash
python3 bin/coletar.py gupy
```

### Por que sem dependências

O alvo é a VPS gratuita da Oracle Cloud, e nenhum problema deste projeto pede
mais do que a stdlib resolve. `http.server` serve páginas prontas, `sqlite3`
filtra dezenas de milhares de linhas em milissegundos e `urllib` fala com as
APIs. Sem `pip install`, o deploy é `git pull` + `systemctl restart`, e não
existe árvore de dependências para envelhecer entre um deploy e o próximo.

---

## Fontes

Cada plataforma é um **conector independente** em `hirehub/fontes/`. Adicionar
uma fonte é criar um arquivo lá e decorar a classe com `@registrar` — o núcleo
não muda, porque a descoberta varre o pacote em vez de consultar uma lista
escrita à mão.

| Fonte | Cobertura | Descrição da vaga | Observação |
|---|---|---|---|
| **Gupy** | 10.000 mais recentes | vem na listagem | teto de paginação da API (`offset + limit ≤ 10.000`) |
| **InHire** | completa (~8.800) | 1 requisição por vaga | exige `data/inhire-tenants.json`; não tem busca global |
| **InfoJobs** | por cidade | 1 requisição por vaga | HTML raspado, sem API |
| **Sólides** | estatística | vem na listagem | **hoje devolve zero** — ver abaixo |

### Sólides: sem retorno desde 03/09/2026

O endpoint responde `200` com `success: true` e `count: 0` para qualquer
combinação de `take`, `page` e `search`. Não é limite de taxa nem falta de
cabeçalho — foi testado com `Origin` e `Referer` do próprio portal. A API não
quebrou, ela esvaziou.

O conector segue no ar de propósito: `/status` mostra **Sem retorno** em vez de
esconder o problema, e no dia em que a API voltar, a coleta volta sozinha. Era
a única fonte que publicava salário.

### Atualizando a lista de empresas da InHire

A InHire não tem busca global nem diretório público: cada empresa é um
subdomínio e a API só responde por tenant. A lista **é** a fonte.

```bash
python3 bin/atualizar-tenants.py    # descobre via Wayback + urlscan e valida
```

Vale rodar mensalmente, conforme empresas entram e saem da plataforma.

---

## Configuração

Tudo tem padrão e o projeto roda sem nenhum arquivo de config. Para ajustar,
crie `data/hirehub.config.json`:

```json
{
  "gupy_termos": [],
  "solides_paginas": 150,
  "infojobs_paginas_por_cidade": 3,
  "detalhes_por_execucao": 400,
  "esquecer_apos_dias": 60,
  "threads": 6,
  "intervalo_horas": 6
}
```

`detalhes_por_execucao` merece atenção. As descrições da InHire e do InfoJobs
custam uma requisição por vaga, então cada rodada busca só um lote e o cache
(que é o próprio banco) converge ao longo das execuções. Para popular a base
de uma vez — vale a pena logo depois do primeiro `coletar.py` —, suba o número:

```json
{ "detalhes_por_execucao": 4000 }
```

`gupy_termos` abre uma janela ADICIONAL de 10.000 vagas por termo, para
alcançar anúncios mais antigos de uma área específica.

---

## Como está montado

```
hirehub/
├── bin/                 coletar.py · servir.py · atualizar-tenants.py
├── hirehub/
│   ├── config.py        caminhos, padrões, identidade
│   ├── net.py           HTTP com retry; falha vira None, nunca exceção solta
│   ├── texto.py         normalização: modalidade, local, datas, HTML → texto
│   ├── db.py            esquema, gravação e as consultas do site
│   ├── coleta.py        orquestrador: lock, isolamento por fonte, poda
│   └── fontes/          um arquivo por plataforma, auto-registrados
├── web/
│   ├── servidor.py      rotas e HTTP
│   ├── paginas.py       HTML server-rendered
│   └── static/          CSS, fontes auto-hospedadas, logo
├── deploy/              systemd + nginx
└── data/                banco, cache e a lista de empresas da InHire
```

### Decisões que valem saber

**A base acumula.** Cada coleta acrescenta; nada é substituído. Isso dá um
histórico que as próprias APIs não devolvem — a Gupy, por exemplo, só deixa ver
as 10.000 vagas mais recentes. Vagas que sumiram da origem são removidas depois
de `esquecer_apos_dias` (padrão: 60).

**Uma fonte que falha não derruba as outras.** Cada conector roda no seu try, e
o erro vai para a tabela `fontes`, que alimenta `/status`. Um scraping quebrado
vira um aviso no site, não uma coleta perdida.

**O carimbo de "no ar" só é gravado no fim.** Marcar antes deixaria o catálogo
inteiro fora do ar durante os minutos da coleta — e permanentemente, se o
processo morresse no meio.

**A busca ignora acento.** As colunas `busca_titulo` e `busca_local` guardam a
forma normalizada, porque o `LIKE` do SQLite compara byte a byte: sem isso,
quem digita "macae" não acha "Macaé".

**Nada de HTML de terceiros na página.** As descrições vêm de quatro
plataformas com marcação arbitrária. Guardamos texto puro e escapamos tudo na
renderização. O site também não tem `<script>` próprio: é navegável sem
JavaScript, o que importa num agregador que precisa ser indexável.

**As fontes tipográficas são auto-hospedadas.** Um `<link>` para o Google Fonts
é render-blocking — a primeira pintura passaria a depender da latência de um
terceiro, e o IP de quem visita vazaria para um domínio que não é nosso. São
4 arquivos, ~120 KB.

---

## Deploy (VPS Oracle Cloud, sempre gratuita)

```bash
sudo useradd -r -s /usr/sbin/nologin -d /opt/hirehub hirehub
sudo git clone <repo> /opt/hirehub
sudo chown -R hirehub:hirehub /opt/hirehub

sudo cp deploy/hirehub-*.service deploy/hirehub-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hirehub-web.service hirehub-coleta.timer

sudo cp deploy/nginx.conf /etc/nginx/sites-available/hirehub
sudo ln -s /etc/nginx/sites-available/hirehub /etc/nginx/sites-enabled/
sudo certbot --nginx -d hirehub.com.br
sudo nginx -t && sudo systemctl reload nginx
```

Primeira coleta na mão, para o site não subir vazio:

```bash
sudo -u hirehub python3 /opt/hirehub/bin/coletar.py
```

Acompanhando depois:

```bash
systemctl list-timers hirehub-coleta.timer
journalctl -u hirehub-coleta.service -n 50
```

Ajuste `HIREHUB_URL` (ou `SITE["url"]` em `config.py`) para o domínio real —
é o que entra nas URLs canônicas, no sitemap e no `robots.txt`.

---

## Fora do escopo

Login, cadastro, favoritos, perfil, currículo, candidatura interna, chat,
mensagens, área do candidato. Nenhum dado pessoal é coletado ou armazenado, e é
essa ausência que mantém o produto simples.

## Origem

O motor de coleta nasceu como o **Radar de Vagas** da intranet da TV box
(`tvbox-intranet/intranet/radar.py`), onde rodava em ~1 GB de RAM. O HireHub o
destaca dali como produto próprio: os conectores viraram módulos independentes
com registro automático, a base ganhou descrição e página de detalhes, o status
por fonte virou página pública e a intranet deu lugar a um site público.
