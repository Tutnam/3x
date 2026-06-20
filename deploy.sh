#!/usr/bin/env bash
#
# deploy.sh — первый запуск VPN-бота в Docker одной командой.
#
# Делает по порядку:
#   1. Проверяет наличие Docker и docker compose; если нет — ставит.
#   2. Включает и запускает демон Docker.
#   3. Поднимает бота: docker compose up -d --build.
#   4. Ждёт healthcheck и показывает статус.
#
# Запуск:   bash deploy.sh        (от root или через sudo — нужен доступ к Docker)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

ENV_FILE="$SCRIPT_DIR/src/.env"

if [ "$(id -u)" -eq 0 ]; then SUDO=""; else SUDO="sudo"; fi

log() { echo "$(date '+%H:%M:%S') | $*"; }
die() { echo "🛑 $*" >&2; exit 1; }

# Значение переменной из .env (со снятыми кавычками и комментарием), пусто если нет
get_env_value() {
    [ -f "$ENV_FILE" ] || return 0
    # `|| true` — отсутствие ключа не должно ронять скрипт под set -e/pipefail
    { grep -E "^$1=" "$ENV_FILE" || true; } | head -n1 | cut -d= -f2- | sed "s/^[\"']//; s/[\"'][[:space:]]*\$//; s/[[:space:]]*#.*\$//"
}

# Установка системного пакета через доступный пакетный менеджер
pkg_install() {
    local pkg="$1"
    if   command -v apt-get >/dev/null 2>&1; then $SUDO apt-get update -qq && $SUDO apt-get install -y "$pkg"
    elif command -v dnf     >/dev/null 2>&1; then $SUDO dnf install -y "$pkg"
    elif command -v yum     >/dev/null 2>&1; then $SUDO yum install -y "$pkg"
    elif command -v pacman  >/dev/null 2>&1; then $SUDO pacman -Sy --noconfirm "$pkg"
    elif command -v zypper  >/dev/null 2>&1; then $SUDO zypper install -y "$pkg"
    elif command -v apk     >/dev/null 2>&1; then $SUDO apk add "$pkg"
    else die "Не найден поддерживаемый пакетный менеджер для установки $pkg"
    fi
}

# ---------------------------------------------------------------------------
# 0. Пред-проверки
# ---------------------------------------------------------------------------
[ -f "$SCRIPT_DIR/docker-compose.yml" ] || die "Нет docker-compose.yml рядом со скриптом"
[ -f "$ENV_FILE" ] || die "Нет $ENV_FILE — сначала заполни конфиг (см. src/.env.example)"

SUB_PORT="$(get_env_value SUBSCRIPTION_PORT)"; SUB_PORT="${SUB_PORT:-35635}"
mkdir -p "$SCRIPT_DIR/backups"

# Том ./users.db монтируется как ФАЙЛ. Если файла нет — Docker создал бы на его
# месте ПАПКУ и сломал SQLite. Поэтому заранее создаём пустой файл: пустой файл —
# это валидная «новая» SQLite-БД, бот сам построит схему через init_db/create_all.
[ -e "$SCRIPT_DIR/users.db" ] || { touch "$SCRIPT_DIR/users.db"; log "ℹ️  Создан пустой users.db (чистый старт)"; }

# Миграция нужна только при апгрейде СТАРОЙ базы — на чистом старте её не запускаем
# (create_all сразу строит полную актуальную схему со всеми таблицами/колонками).

# ---------------------------------------------------------------------------
# 1. Docker + compose
# ---------------------------------------------------------------------------
if ! command -v docker >/dev/null 2>&1; then
    log "Docker не найден — устанавливаю..."
    command -v curl >/dev/null 2>&1 || pkg_install curl
    # Официальный установщик Docker (Debian/Ubuntu/CentOS/Fedora/…)
    if curl -fsSL https://get.docker.com -o /tmp/get-docker.sh; then
        $SUDO sh /tmp/get-docker.sh || die "Не удалось установить Docker через get.docker.com"
        rm -f /tmp/get-docker.sh
    else
        # Фолбэк на нативный пакет (напр. Arch/прочее, не покрытое скриптом)
        log "get.docker.com недоступен — пробую нативный пакет docker..."
        pkg_install docker || die "Не удалось установить Docker"
    fi
else
    log "✅ Docker уже установлен: $(docker --version)"
fi

# Демон Docker: включить и запустить (если есть systemd)
if command -v systemctl >/dev/null 2>&1; then
    $SUDO systemctl enable --now docker 2>/dev/null || true
fi

# Определяем команду compose: v2 (docker compose) предпочтительно, иначе legacy
if docker compose version >/dev/null 2>&1; then
    COMPOSE="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE="docker-compose"
else
    log "Плагин docker compose не найден — ставлю..."
    pkg_install docker-compose-plugin 2>/dev/null || pkg_install docker-compose || true
    if docker compose version >/dev/null 2>&1; then COMPOSE="docker compose"
    elif command -v docker-compose >/dev/null 2>&1; then COMPOSE="docker-compose"
    else die "Не удалось получить docker compose"
    fi
fi
log "✅ Использую: $COMPOSE"

# ---------------------------------------------------------------------------
# 2. Поднимаем бота в Docker
# ---------------------------------------------------------------------------
log "🚀 Сборка и запуск контейнера..."
$SUDO $COMPOSE up -d --build

# ---------------------------------------------------------------------------
# 3. Ждём healthcheck
# ---------------------------------------------------------------------------
log "⏳ Жду готовности /health (до ~40с)..."
HEALTHY=0
for _ in $(seq 1 20); do
    if curl -fsS "http://127.0.0.1:${SUB_PORT}/health" >/dev/null 2>&1; then
        HEALTHY=1; break
    fi
    sleep 2
done

echo
$SUDO $COMPOSE ps
echo
if [ "$HEALTHY" = 1 ]; then
    log "✅ Готово. Бот поднят и отвечает на /health (порт ${SUB_PORT})."
else
    log "⚠️  Контейнер запущен, но /health пока не ответил. Проверь логи:"
    log "    $COMPOSE logs --tail=50 bot"
fi
log "Логи в реальном времени:  $COMPOSE logs -f bot"
