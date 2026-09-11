# HireHub

**O hub das oportunidades, seu próximo emprego começa aqui.**

Agregador público e gratuito de vagas. Coleta anúncios de seis plataformas de
recrutamento, normaliza tudo numa base própria e serve num só lugar — sem
cadastro, sem login, sem candidatura interna. O botão *Candidatar-se* leva para
a vaga original.

No ar em **http://163.176.175.26** — rodando numa VPS gratuita da Oracle Cloud,
em Python sem uma única dependência externa.

```
Coletar → Normalizar → Armazenar → Exibir → Redirecionar
```

O que o visitante vê é simples de propósito: entrei → pesquisei → encontrei →
cliquei → me candidatei. A complexidade fica nos bastidores.

---

## Como rodar

Não há nada para instalar. Python 3.9+ e só a biblioteca padrão.

```bash
python3 bin/coletar.py     # roda uma coleta (~2 a 10 min)
python3 bin/servir.py      # sobe o site em http://localhost:8080
```

Em ambiente **sem systemd** (Termux, contêiner sem init), o próprio servidor
pode agendar a coleta — nenhum dos ambientes tem cron:

```bash
python3 bin/servir.py --agendar
```

Em produção prefira o `hirehub-coleta.timer`: ele sobrevive ao site cair,
registra no journal e recupera a rodada perdida depois de um reboot.

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
| **InHire** | completa (~8.900) | 1 requisição por vaga | exige `data/inhire-tenants.json`; não tem busca global |
| **InfoJobs** | por cidade | 1 requisição por vaga | HTML raspado, sem API |
| **Vagas.com.br** | por cidade | 1 requisição por vaga | listagem raspada; detalhe em JSON-LD |
| **Trampos.co** | ~230 vagas | 1 requisição por vaga | API pública sem token; áreas criativas e digitais |
| **Sólides** | estatística | vem na listagem | **hoje devolve zero** — ver abaixo |

Só a **InHire** declara `cobertura_completa`. As demais entregam uma janela, e
por isso não marcam vaga como "saiu do ar" — ausência ali significa que
chegaram anúncios mais novos, não que o anúncio fechou.

### Vagas.com.br: JSON-LD em vez de raspagem, no detalhe

A listagem é HTML raspado (`<li class="vaga">`), mas cada página de vaga
publica um bloco **JSON-LD `JobPosting`** do schema.org, com `datePosted`,
descrição completa, empresa e localidade em campos nomeados. Marcação que
existe para os buscadores lerem muda muito menos que classe de CSS, então a
parte frágil fica restrita à listagem.

Vale procurar por esse bloco em qualquer fonte nova antes de partir para
raspagem — a função `_json_ld_jobposting` em `fontes/vagas.py` é genérica.

A listagem nacional (`/vagas-de-emprego`) é uma seleção curada de ~120 vagas; o
catálogo real só é alcançável por cidade. Medido: São Paulo tem 992 vagas
alcançáveis, 40 por página, paginação até o fim sem repetir.

**Ela está atrás de Cloudflare e não avisa antes de bloquear.** 968 páginas de
detalhe a 8 threads renderam um `429` com `Retry-After` de **24 horas**. Por
isso o conector declara tetos próprios (`threads = 2`,
`detalhes_por_execucao = 120`), calibrados para o enriquecimento ocupar cerca
de um minuto de tráfego a cada 6 horas: o acervo converge em alguns dias sem
incomodar a origem. Não suba esses números sem medir.

Os tetos da fonte são limites, nunca permissões — se a configuração global for
mais apertada, vale a global.

### Trampos.co: pequena, mas a única com API aberta

`https://trampos.co/api/oportunidades.json?page=N` devolve JSON paginado **sem
token, sem cabeçalho especial e sem cadastro** — a documentação fala em "API
para parceiros", mas o endereço responde aberto, e foi isso que decidiu a
entrada dela, não a documentação.

São ~230 vagas cobrindo três semanas, em design, produto, marketing e
tecnologia. Entra por complementar o catálogo onde as generalistas são fracas,
não por volume. A listagem já traz `published_at`, o que a Vagas.com.br e o
InfoJobs só entregam com uma requisição por vaga.

### Plataformas avaliadas e descartadas

Registro completo das 19 plataformas testadas contra o endpoint real, para
ninguém reinvestigar. Avaliadas entre 03 e 08/09/2026.

**Bloqueadas pela própria plataforma** — decisão delas, não nossa:

| Plataforma | O que responde | Motivo |
|---|---|---|
| **Catho** | — | `robots.txt` proíbe `/buscar/vagas/`, a própria busca. A API existe mas só para integradores aprovados, agindo em nome de um usuário cadastrado |
| **Indeed** | — | `robots.txt` proíbe `/empregos/BR/` e `/emprego/`. A API pública foi descontinuada em 2024 |
| **Jobbol** | `403` | Cloudflare com desafio de navegador. Nega até o `sitemap_alljobs.xml.gz` que o próprio `robots.txt` autoriza. Passar disso seria burlar proteção anti-bot |
| **Jooble** | `403` | exige chave de API |
| **Abler** | `401` | exige autenticação |
| **Recrutei** | — | API com Bearer Token, e é administrativa do recrutador. Sem mural público por empresa (testados `vagas.`, `carreiras.` e `/vagas`) |
| **Glassdoor** | — | programa de parceiros fechado para novas inscrições desde 2021 (não chegou a ser testado tecnicamente) |

**Tecnicamente inviáveis** — abertas, mas o formato não permite:

| Plataforma | O que impede |
|---|---|
| **BNE** | 1,7 milhão de vagas e JSON-LD com salário no detalhe, mas renderiza **uma vaga por página**, mesmo na busca por cidade. Coletar exigiria uma requisição por vaga |
| **Trabalha Brasil** | sem JSON-LD e sem API; só raspagem pesada de HTML |
| **Empregos.com.br** | listagem acessível, mas a página de detalhe recusou as requisições |
| **Programathor** | `406` para cliente HTTP |
| **Coodesh**, **Remotar**, **99jobs** | `404` nos endpoints prováveis; o modelo da Coodesh é redirecionar o candidato ao site de origem |

**ATS por empresa** — funcionam, mas exigiriam lista de tenants própria, como a
InHire tem. Viável, é trabalho de descoberta à parte:

| Plataforma | Situação |
|---|---|
| **Ashby** | API pública e limpa, confirmada funcionando (142 vagas numa empresa de teste) |
| **Greenhouse** | API pública, responde por *board token* de cada empresa |
| **Lever**, **Workable** | API pública por empresa; os endpoints de exemplo testados deram `404` |
| **Quickin** | `robots.txt` permissivo; não aprofundado |

O peso da adoção no Brasil é o que despriorizou esse grupo: fora de startups,
pouca empresa brasileira usa Greenhouse, Lever ou Ashby.

Catho e Indeed ficam de fora por decisão delas, não nossa: são as duas maiores
do país e o `robots.txt` de ambas bloqueia justamente as páginas de vaga.

### Sólides: sem saída, investigado até o fim

O endpoint responde `200` com `success: true` e `count: 0` para qualquer
combinação de `take`, `page` e `search`. Não é limite de taxa nem falta de
cabeçalho — testado com `Origin` e `Referer` do próprio portal. **O portal foi
reescrito em Next.js e a API antiga saiu do ar junto com o site antigo.**

O catálogo continua existindo: 73.031 vagas em `/vagas/todas`, com salário e
descrição completa visíveis na página. Duas coisas impedem aproveitá-lo:

1. **A listagem é montada por JavaScript.** Por HTTP puro vem 1 card; no
   navegador, 12. Raspar exigiria navegador headless — e o projeto inteiro se
   sustenta em não ter dependências.
2. **Não existe link para a vaga individual.** O título não é link, o card não
   é clicável, e o único destino é a raiz do mural da empresa, que também é
   renderizado por JavaScript.

O segundo ponto é o que encerra a discussão: mesmo pagando o preço de um
navegador headless, o botão *Candidatar-se* não teria para onde apontar além da
página inicial da empresa. Link não confiável não entra, e essa regra vale para
todas as fontes.

O conector fica no ar porque `/status` dizendo **Sem retorno** é informação
honesta, e porque no dia em que houver uma API nova a volta custa trocar uma
URL. Era a única fonte que publicava salário — hoje a Trampos.co cobre parte
disso.

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
  "infojobs_cidades": [],
  "vagas_paginas_por_cidade": 5,
  "vagas_cidades": [],
  "trampos_paginas": 30,
  "detalhes_por_execucao": 400,
  "esquecer_apos_dias": 120,
  "threads": 6,
  "intervalo_horas": 6,
  "intervalo_por_fonte": { "solides": 24 }
}
```

`intervalo_por_fonte` dá cadência própria a uma fonte sem precisar de um
agendador separado: a rodada continua sendo de 6 em 6 horas e a fonte adiada
simplesmente não participa. A Sólides está em 24h porque hoje devolve zero —
insistir de 6 em 6 gasta 126s de cada coleta e bate numa API de terceiro à toa.
Uma fonte adiada não é tocada, nem o marco de "no ar" dela, então as vagas que
ela já trouxe continuam listadas normalmente.

Pedir a fonte pelo nome ignora o intervalo, porque é execução manual:

```bash
python3 bin/coletar.py solides    # roda agora, mesmo dentro das 24h
```

`infojobs_cidades` define a cobertura dessa fonte: o InfoJobs não tem busca
nacional — cada URL cai numa cidade por geolocalização —, então a lista **é** o
alcance. Vazio usa o padrão do conector (capitais e polos). Para acrescentar:

```json
{ "infojobs_cidades": [["sao-paulo", "sp"], ["macae", "rj"], ["natal", "rn"]] }
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

### Quanto demora

Medido em 03/09/2026, com `threads: 8`, numa conexão doméstica:

| Etapa | Tempo |
|---|---|
| Gupy (10.000 vagas) | 26 s |
| InfoJobs (2 páginas × 12 cidades × 2 modalidades) | 6 s |
| InHire (448 empresas) | 48 s |
| Sólides (30 páginas, todas vazias) | 126 s |
| Enriquecimento | ~12 detalhes/s |
| **Coleta completa com 4.000 detalhes** | **~10 min** |

Com o padrão de 400 detalhes por execução, uma rodada leva 3 a 4 minutos. O
enriquecimento é gravado a cada 250 itens, então um processo interrompido perde
no máximo um lote — o resto já está no banco e a execução seguinte continua de
onde parou.

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

### Regras de negócio

Valem para todas as fontes, e são o que o sistema garante independentemente de
qual plataforma quebrar:

1. **Nunca há filtro de cargo na coleta.** Puxa tudo que a API permite; a
   peneira acontece depois, em SQL, na hora da busca — não no navegador.
2. **Nada é apagado por ficar velho**, só depois de `esquecer_apos_dias`
   (padrão: 120). A base vira um arquivo histórico que as plataformas não
   oferecem: a Gupy, por exemplo, só deixa alcançar as 10.000 mais recentes.
3. **Vaga que sumiu não some na hora — sai do ar.** Continua listada e marcada,
   para não desaparecer antes de alguém ter visto. O filtro "só as no ar" vem
   ligado; a página da vaga abre mesmo assim, com aviso antes do botão.
4. **Só a Sólides publica salário.** Nas outras três o campo fica vazio.
5. **A coleta é isolada do site.** Roda como serviço separado — se travar ou
   estourar memória, o site continua respondendo.
6. **Agendamento sem cron.** Nenhum dos ambientes tem cron; quem agenda é o
   `hirehub-coleta.timer` do systemd (ou o `--agendar`, abaixo). A rodada é de
   6 em 6 horas e cada fonte decide se participa — a Sólides está em 24h por
   estar sem retorno (`intervalo_por_fonte`).
7. **Link não confiável nunca aparece.** Vaga sem link clicável garantido é
   descartada na coleta em vez de ser exibida quebrada — é o caso das vagas da
   Sólides com id alfanumérico, vindas de integrações externas via ATS.
8. **Uma fonte que falha não derruba as outras** nem esconde as vagas dela: o
   marco de "no ar" é por fonte, então uma coleta ruim da InHire não apaga do
   site as 8.900 vagas que ela já tinha trazido.

### Decisões que valem saber

**A base acumula.** Cada coleta acrescenta; nada é substituído.

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

Escrito para **Oracle Linux 9**, que é o que a instância roda. O `python3` dele
é 3.9 e atende o piso — confira antes de qualquer coisa, porque no Oracle Linux
8 o padrão é 3.6 e não serve:

```bash
python3 --version
```

### Instalação

Um comando, com o script de `deploy/`. O Oracle Linux minimal **não traz git**,
então o script vem por `curl` — ele instala o resto sozinho:

```bash
curl -fsSL https://raw.githubusercontent.com/vini-medeiros-cmd/hirehub/master/deploy/instalar.sh -o /tmp/instalar.sh
sudo bash /tmp/instalar.sh
```

Ele recusa rodar fora do Oracle Linux, dizendo qual máquina detectou — a
confusão fácil aqui é a sessão SSH cair sem você perceber e o script rodar na
sua própria máquina.

<details>
<summary>Ou passo a passo, se preferir conferir cada etapa</summary>

```bash
sudo dnf install -y git nginx
sudo useradd -r -s /sbin/nologin -d /opt/hirehub hirehub   # em Debian: /usr/sbin/nologin
sudo git clone <repo> /opt/hirehub
sudo chown -R hirehub:hirehub /opt/hirehub
# O Nginx serve /static direto do disco e roda como outro usuário; sem o bit de
# leitura para "outros", os estáticos voltam 403 e o site abre sem CSS.
sudo chmod -R o+rX /opt/hirehub/web/static

sudo cp deploy/hirehub-*.service deploy/hirehub-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now hirehub-web.service hirehub-coleta.timer

sudo cp deploy/nginx.conf /etc/nginx/conf.d/hirehub.conf   # em Debian: sites-available + symlink
sudo nginx -t && sudo systemctl enable --now nginx
```

Falta ainda o SELinux e o firewall, abaixo — o script cuida dos dois.

</details>

### Sem domínio

Funciona, e para uso pessoal é o suficiente: aponte o `HIREHUB_URL` para o IP.

```bash
sudo sed -i 's|HIREHUB_URL=.*|HIREHUB_URL=http://SEU.IP|' /etc/systemd/system/hirehub-web.service
sudo systemctl daemon-reload && sudo systemctl restart hirehub-web
```

Fica em HTTP puro, e aqui isso protege pouco de qualquer forma: o HireHub não
tem login, não recebe currículo e não guarda nada de quem visita. O que passa
pela rede é uma lista pública de vagas.

Duas consequências que valem saber:

* **O IP precisa ser estável.** Na Oracle, o público vem como *Ephemeral* e
  desaparece com a instância. Converter para *Reserved* não custa e evita ter
  de reconfigurar tudo depois.
* **Não haverá indexação real.** Buscadores praticamente não indexam IP nu, e
  o `sitemap.xml` fica decorativo. Se um dia quiser isso sem gastar, um
  subdomínio gratuito (DuckDNS e afins) resolve o nome *e* destrava o
  Let's Encrypt.

### Com domínio

TLS: o certbot vem do EPEL no Oracle Linux.

```bash
sudo dnf install -y epel-release
sudo dnf install -y certbot python3-certbot-nginx
sudo certbot --nginx -d hirehub.com.br
```

### As três pegadinhas da Oracle Cloud

Derrubam mais deploy do que qualquer bug de código. As duas primeiras dão o
mesmo sintoma: nada responde de fora, mas `curl localhost` funciona.

**1. Security List da VCN** — libere 80 e 443 no console
(*Networking → VCN → Security Lists → Ingress Rules*). Nenhum comando na
máquina substitui isso.

**2. Firewall da instância** — as imagens sobem bloqueando tudo menos SSH:

```bash
# Oracle Linux
sudo firewall-cmd --permanent --add-service=http --add-service=https
sudo firewall-cmd --reload
# Ubuntu (as imagens da Oracle trazem regras iptables, não só o ufw)
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

**3. SELinux (só no Oracle Linux)** — vem *enforcing* e bloqueia exatamente as
duas coisas que o Nginx precisa fazer aqui. O sintoma é diferente das
anteriores: **502** no site e **403** nos estáticos, com `nginx -t` dizendo que
está tudo certo.

```bash
# deixa o Nginx conectar no Python da 8080 (sem isto: 502)
sudo setsebool -P httpd_can_network_connect 1
# rotula os estáticos como conteúdo servível (sem isto: 403, site sem CSS)
sudo dnf install -y policycoreutils-python-utils
sudo semanage fcontext -a -t httpd_sys_content_t "/opt/hirehub/web/static(/.*)?"
sudo restorecon -Rv /opt/hirehub/web/static
```

Não desligue o SELinux para contornar. Se algo ainda for bloqueado,
`sudo ausearch -m avc -ts recent` diz o quê.

### Se a instância for a VM.Standard.E2.1.Micro (1 GB)

Ela não vem com swap, e 1 GB é apertado para Oracle Linux 9 + Nginx + a coleta
(pico medido de 203 MB). Crie 2 GB de swap para o kernel ter para onde correr:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

Desligue também os plugins do Oracle Cloud Agent que não usa (*Instance →
Oracle Cloud Agent*): num box de 1 GB eles chegam a comer 150 MB. Bastam
*Compute Instance Monitoring* e *Compute Instance Run Command*.

Se o shape **VM.Standard.A1.Flex** (Ampere/ARM) estiver disponível na sua
região, ele também é sempre gratuito e entrega até 4 OCPU e 24 GB — folga
absurda para este projeto. O código é Python puro, roda em ARM sem ajuste.

### Primeira coleta

Na mão, para o site não subir vazio:

```bash
sudo -u hirehub python3 /opt/hirehub/bin/coletar.py
```

Vale rodar o backfill de descrições logo em seguida, com
`detalhes_por_execucao` alto (veja *Configuração*).

### Recursos

Medido: pico de **203 MB** de RSS na coleta, ~87 MB de banco com 21 mil vagas.
Os `MemoryMax` das unidades (768 MB na coleta, 512 MB no site) têm folga
confortável até no shape x86 de 1 GB. O `VACUUM` ao fim da coleta chega a
dobrar o arquivo temporariamente — reserve o dobro do banco em disco.

### Acompanhando

```bash
systemctl list-timers hirehub-coleta.timer
journalctl -u hirehub-coleta.service -n 50
journalctl -u hirehub-web.service -f
```

Se `journalctl` mostrar `tzdata ausente`, o site está usando UTC-3 fixo — está
correto para o horário de Brasília, mas `dnf install tzdata` restaura o fuso
oficial.

**Ajuste `HIREHUB_URL`** no `hirehub-web.service` para o domínio real: é o que
entra nas URLs canônicas, no sitemap e no `robots.txt`.

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
