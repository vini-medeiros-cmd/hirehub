#!/usr/bin/env bash
#
# Instalação do HireHub numa VPS Oracle Cloud com Oracle Linux 9.
#
#   curl -fsSL https://raw.githubusercontent.com/vini-medeiros-cmd/hirehub/master/deploy/instalar.sh | bash
#
# ...ou, o que dá para conferir antes de executar:
#
#   git clone https://github.com/vini-medeiros-cmd/hirehub.git /tmp/hirehub
#   sudo bash /tmp/hirehub/deploy/instalar.sh
#
# É idempotente: rodar de novo atualiza o código e reaplica a configuração,
# sem duplicar usuário, swap nem regra de firewall.
#
# NÃO faz duas coisas de propósito, porque nenhuma das duas é decisão do
# script: liberar 80/443 na Security List da VCN (é no console da Oracle) e
# emitir o certificado TLS (depende do domínio já apontar para este IP).
set -euo pipefail

REPO="${HIREHUB_REPO:-https://github.com/vini-medeiros-cmd/hirehub.git}"
DESTINO="/opt/hirehub"
USUARIO="hirehub"
SWAP_GB=2

passo() { printf '\n\033[1;34m==>\033[0m %s\n' "$1"; }
aviso() { printf '\033[1;33m !\033[0m %s\n' "$1"; }

[[ $EUID -eq 0 ]] || { echo "Rode com sudo."; exit 1; }

# Este script é a PRIMEIRA coisa a rodar numa VPS recém-criada, e a confusão
# mais fácil de cometer é executá-lo na própria máquina em vez de na instância
# — basta o SSH cair sem você perceber. Antes desta checagem, o sintoma era um
# "dnf: comando não encontrado" que não explicava nada. Ele criaria usuário de
# sistema, swap e serviços na máquina errada se o gerenciador de pacotes
# coincidisse.
if ! command -v dnf &>/dev/null; then
  cat >&2 <<AVISO

  ERRO: este script é para Oracle Linux / RHEL, e aqui não existe 'dnf'.

  Sistema detectado: $(. /etc/os-release 2>/dev/null && echo "$PRETTY_NAME" || uname -s)
  Máquina:           $(hostname)

  Você está rodando na SUA máquina em vez da VPS? Conecte primeiro:

      ssh -i SUA_CHAVE opc@SEU_IP

  e confira que o prompt virou algo como [opc@hirehub ~]\$ antes de continuar.

AVISO
  exit 1
fi

passo "Conferindo o Python (o piso do projeto é 3.9)"
python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    sys.exit(f"Python {sys.version.split()[0]} é antigo demais. Instale o 3.9+.")
print(f"  Python {sys.version.split()[0]} — ok")
PY

# O SWAP VEM ANTES DOS PACOTES, e isso não é detalhe de ordem: o próprio dnf é
# um programa Python que carrega os metadados dos repositórios na memória, e
# numa E2.1.Micro (1 GB, sem swap de fábrica) ele trava no primeiro
# `dnf install` — sem erro, sem sair, só parado. Foi o que aconteceu na
# primeira instalação real.
#
# Em shapes maiores (A1.Flex) o bloco simplesmente não se aplica.
if [[ $(free -m | awk '/^Mem:/{print $2}') -lt 2048 ]] && ! swapon --show | grep -q .; then
  passo "Criando ${SWAP_GB} GB de swap (memória baixa e nenhum swap ativo)"
  fallocate -l "${SWAP_GB}G" /swapfile
  chmod 600 /swapfile
  mkswap -q /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
  free -m | awk '/^Swap:/{printf "  swap ativo: %s MB\n", $2}'
fi

# UM PACOTE POR VEZ, e não os três de uma tacada.
#
# Medido numa E2.1.Micro (945 MB, com 944 MB de swap já ativos): o dnf foi
# morto pelo OOM killer instalando os três juntos. Ele é um programa Python que
# carrega os metadados de TODOS os repositórios do Oracle Linux na memória, e o
# pico cresce com o tamanho da transação. Um de cada vez cabe.
#
# `install_weak_deps=False` corta os "Recommends", que aqui só trazem peso.
# `max_parallel_downloads=1` evita vários downloads simultâneos na memória.
# Sem `-q`: na primeira execução isso leva minutos, e em silêncio não dá para
# distinguir trabalho de travamento — a diferença importa para quem está
# olhando a tela.
passo "Pacotes (um por vez; a primeira vez baixa os metadados e demora)"
for pacote in git nginx policycoreutils-python-utils; do
  echo "  --- $pacote"
  rpm -q "$pacote" &>/dev/null && { echo "  já instalado"; continue; }
  dnf install -y \
      --setopt=install_weak_deps=False \
      --setopt=max_parallel_downloads=1 \
      "$pacote"
done

passo "Usuário de serviço e código"
id -u "$USUARIO" &>/dev/null || useradd -r -s /sbin/nologin -d "$DESTINO" "$USUARIO"

# De onde vem o código: da cópia em que este script está, se ele foi executado
# de dentro de uma, ou do GitHub. A primeira forma é o que permite instalar sem
# depender do repositório ser público — basta um scp da pasta e rodar o script
# de dentro dela.
ORIGEM="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd || true)"
if [[ -n "$ORIGEM" && -f "$ORIGEM/bin/coletar.py" && "$ORIGEM" != "$DESTINO" ]]; then
  echo "  copiando de $ORIGEM"
  mkdir -p "$DESTINO"
  # tar em vez de cp -a: exclui .git e cache, e — o que importa — NÃO carrega
  # o banco. Assim reinstalar por cima nunca apaga as vagas já coletadas no
  # destino, que levam minutos para voltar.
  tar -C "$ORIGEM" --exclude=.git --exclude=__pycache__ \
      --exclude='data/*.db' --exclude='data/*.db-wal' --exclude='data/*.db-shm' \
      --exclude='data/cache' -cf - . | tar -C "$DESTINO" -xf -
elif [[ -d "$DESTINO/.git" ]]; then
  echo "  atualizando do GitHub"
  git -C "$DESTINO" fetch --quiet origin
  git -C "$DESTINO" reset --hard --quiet origin/HEAD
else
  # Aqui cai tanto a instalação nova (destino não existe) quanto a que veio de
  # um `scp` e por isso NÃO é um checkout git. O `git clone` direto no destino
  # falha no segundo caso — "already exists and is not an empty directory" —, e
  # foi assim que a primeira atualização real quebrou.
  #
  # Clonar num temporário e copiar por cima resolve os dois, preserva o banco
  # (que não vem no tar) e deixa o destino sendo um checkout de verdade, para a
  # próxima atualização ser um `git fetch` barato.
  echo "  clonando de $REPO"
  TEMP="$(mktemp -d)"
  trap 'rm -rf "$TEMP"' EXIT
  git clone --quiet "$REPO" "$TEMP/repo" || {
    echo >&2 "
  Não consegui clonar $REPO.

  Se o repositório for PRIVADO, a VPS não tem como acessá-lo. Duas saídas:
    1. torne-o público no GitHub, ou
    2. copie a pasta da sua máquina e rode o script de dentro dela:

       # na sua máquina
       tar czf /tmp/hirehub.tgz --exclude=.git --exclude='data/*.db' .
       scp -i SUA_CHAVE /tmp/hirehub.tgz opc@SEU_IP:/tmp/
       # na VPS
       mkdir -p /tmp/hirehub && tar xzf /tmp/hirehub.tgz -C /tmp/hirehub
       sudo bash /tmp/hirehub/deploy/instalar.sh
"
    exit 1
  }
  mkdir -p "$DESTINO"
  # O .git VAI junto, ao contrário da cópia local: é o que transforma o destino
  # num checkout e barateia as próximas atualizações.
  tar -C "$TEMP/repo" --exclude=__pycache__ \
      --exclude='data/*.db' --exclude='data/*.db-wal' --exclude='data/*.db-shm' \
      --exclude='data/cache' -cf - . | tar -C "$DESTINO" -xf -
fi
chown -R "$USUARIO:$USUARIO" "$DESTINO"
# O Nginx roda como outro usuário e lê /static direto do disco.
chmod -R o+rX "$DESTINO/web/static"

passo "Serviços systemd"
install -m 644 "$DESTINO"/deploy/hirehub-web.service /etc/systemd/system/
install -m 644 "$DESTINO"/deploy/hirehub-coleta.service /etc/systemd/system/
install -m 644 "$DESTINO"/deploy/hirehub-coleta.timer /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now hirehub-web.service hirehub-coleta.timer

passo "Nginx"
install -m 644 "$DESTINO"/deploy/nginx.conf /etc/nginx/conf.d/hirehub.conf
nginx -t
systemctl enable --now nginx
systemctl reload nginx

# O SELinux do Oracle Linux vem enforcing e bloqueia as duas coisas que o Nginx
# precisa fazer aqui. Sem isto o site responde 502 e os estáticos 403 — com o
# `nginx -t` jurando que está tudo certo, que é o que torna esse erro confuso.
passo "SELinux"
setsebool -P httpd_can_network_connect 1
semanage fcontext -a -t httpd_sys_content_t "${DESTINO}/web/static(/.*)?" 2>/dev/null || true
restorecon -R "$DESTINO/web/static"

passo "Firewall da instância"
firewall-cmd --permanent --add-service=http --add-service=https >/dev/null
firewall-cmd --reload >/dev/null

passo "Primeira coleta (alguns minutos; o site sobe vazio até ela terminar)"
sudo -u "$USUARIO" python3 "$DESTINO/bin/coletar.py" || \
  aviso "A coleta falhou. O site já está no ar; rode de novo depois com:
     sudo -u $USUARIO python3 $DESTINO/bin/coletar.py"

IP=$(curl -fsS --max-time 5 https://checkip.amazonaws.com 2>/dev/null || echo "SEU_IP")
cat <<FIM

$(passo "Pronto")
  Site local:  $(curl -fsS -o /dev/null -w '%{http_code}' http://127.0.0.1:8080/ || echo 'sem resposta') em http://127.0.0.1:8080
  Site externo: http://${IP}

  SE NÃO ABRIR DE FORA — e só nesse caso — falta liberar as portas no console
  da Oracle. O script não tem como fazer isso nem como conferir daqui dentro:

    Networking > VCN > Security Lists > Ingress Rules
    TCP 80 e 443 para 0.0.0.0/0

  O sintoma é específico: responde em 127.0.0.1 e dá timeout pelo IP público.

  Depois, com o domínio já apontando para ${IP}:
    sudo dnf install -y epel-release && sudo dnf install -y certbot python3-certbot-nginx
    sudo certbot --nginx -d SEUDOMINIO
    sudo sed -i 's|HIREHUB_URL=.*|HIREHUB_URL=https://SEUDOMINIO|' /etc/systemd/system/hirehub-web.service
    sudo systemctl daemon-reload && sudo systemctl restart hirehub-web

  Acompanhar:
    systemctl list-timers hirehub-coleta.timer
    journalctl -u hirehub-coleta.service -n 50
FIM
