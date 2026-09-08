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

passo "Conferindo o Python (o piso do projeto é 3.9)"
python3 - <<'PY'
import sys
if sys.version_info < (3, 9):
    sys.exit(f"Python {sys.version.split()[0]} é antigo demais. Instale o 3.9+.")
print(f"  Python {sys.version.split()[0]} — ok")
PY

passo "Pacotes"
dnf install -y -q git nginx policycoreutils-python-utils

# 1 GB sem swap é o padrão da E2.1.Micro. A coleta tem pico medido de ~203 MB,
# mas o kernel precisa de para onde correr quando o Nginx, o SQLite e o VACUUM
# coincidem. Em shapes maiores (A1.Flex) este trecho é inofensivo: só pula.
if [[ $(free -m | awk '/^Mem:/{print $2}') -lt 2048 ]] && ! swapon --show | grep -q .; then
  passo "Criando ${SWAP_GB} GB de swap (memória baixa e nenhum swap ativo)"
  fallocate -l "${SWAP_GB}G" /swapfile
  chmod 600 /swapfile
  mkswap -q /swapfile
  swapon /swapfile
  grep -q '^/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' >> /etc/fstab
fi

passo "Usuário de serviço e código"
id -u "$USUARIO" &>/dev/null || useradd -r -s /sbin/nologin -d "$DESTINO" "$USUARIO"
if [[ -d "$DESTINO/.git" ]]; then
  git -C "$DESTINO" fetch --quiet origin
  git -C "$DESTINO" reset --hard --quiet origin/HEAD
else
  rm -rf "$DESTINO"
  git clone --quiet "$REPO" "$DESTINO"
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

  FALTA VOCÊ FAZER, no console da Oracle:
    Networking > VCN > Security Lists > Ingress Rules
    libere TCP 80 e 443 para 0.0.0.0/0

  Se o site não abrir de fora mas responder em 127.0.0.1, é isso.

  Depois, com o domínio já apontando para ${IP}:
    sudo dnf install -y epel-release && sudo dnf install -y certbot python3-certbot-nginx
    sudo certbot --nginx -d SEUDOMINIO
    sudo sed -i 's|HIREHUB_URL=.*|HIREHUB_URL=https://SEUDOMINIO|' /etc/systemd/system/hirehub-web.service
    sudo systemctl daemon-reload && sudo systemctl restart hirehub-web

  Acompanhar:
    systemctl list-timers hirehub-coleta.timer
    journalctl -u hirehub-coleta.service -n 50
FIM
