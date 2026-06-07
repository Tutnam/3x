#!/usr/bin/env bash
#
# start-bot.sh — установка и запуск VPN-бота на Ubuntu-сервере.
#
# Что делает:
#   1. Обновляет пакеты системы (apt update && apt upgrade)
#   2. Ставит system-зависимости (python3, venv, pip) и screen, если их нет
#   3. Создаёт виртуальное окружение .venv (если ещё не создано)
#   4. Обновляет pip
#   5. Устанавливает Python-зависимости из requirements.txt
#   6. Спрашивает токен бота (BOT_TOKEN) и id админа (ADMINS) → пишет в src/.env
#   7. Настраивает автозапуск после перезагрузки сервера (cron @reboot)
#   8. Запускает бота в фоновой screen-сессии "mybot"
#
# Запуск:   bash start-bot.sh
#           (от root или через sudo — нужен доступ к apt)

set -euo pipefail

# --- Каталог проекта = каталог этого скрипта (без хардкода пути) ---------------
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

SCREEN_SESSION="mybot"
VENV_DIR="$SCRIPT_DIR/.venv"
ENV_FILE="$SCRIPT_DIR/src/.env"
LOG="/tmp/bot-startup.log"

# sudo нужен только если мы не root
if [ "$(id -u)" -eq 0 ]; then
    SUDO=""
else
    SUDO="sudo"
fi

log() { echo "$(date '+%Y-%m-%d %H:%M:%S') | $*" | tee -a "$LOG"; }

# Текущее значение переменной из .env (со снятыми кавычками)
get_env_value() {
    [ -f "$ENV_FILE" ] || return 0
    grep -E "^$1=" "$ENV_FILE" | head -n1 | cut -d= -f2- | sed "s/^[\"']//; s/[\"'][[:space:]]*$//"
}

# Записать/обновить переменную KEY='VALUE' в .env (заменяет существующую строку)
upsert_env() {
    local key="$1" val="$2"
    touch "$ENV_FILE"
    if grep -qE "^${key}=" "$ENV_FILE"; then
        grep -vE "^${key}=" "$ENV_FILE" > "${ENV_FILE}.tmp"
        mv "${ENV_FILE}.tmp" "$ENV_FILE"
    fi
    echo "${key}='${val}'" >> "$ENV_FILE"
}

# Запросить значение у пользователя и записать в .env.
# Если значение уже есть — пустой ввод оставляет его без изменений.
# Если значения нет — поле обязательное (повторяем запрос, пока не введут).
prompt_env() {
    local key="$1" label="$2" current input
    current="$(get_env_value "$key")"
    if [ -n "$current" ]; then
        read -rp "$label [Enter — оставить текущее]: " input
        if [ -n "$input" ]; then
            upsert_env "$key" "$input"
            log "$key обновлён"
        else
            log "$key оставлен без изменений"
        fi
    else
        while :; do
            read -rp "$label: " input
            [ -n "$input" ] && break
            echo "  Значение не может быть пустым, попробуйте ещё раз."
        done
        upsert_env "$key" "$input"
        log "$key записан"
    fi
}

log "=== Установка/запуск бота. user=$(whoami) dir=$SCRIPT_DIR ==="

# --- 1. Обновление пакетов системы --------------------------------------------
log "[1/8] Обновление списков пакетов и системы (apt update && upgrade)..."
export DEBIAN_FRONTEND=noninteractive
$SUDO apt-get update -y
$SUDO apt-get upgrade -y

# --- 2. system-зависимости + screen -------------------------------------------
log "[2/8] Проверка system-зависимостей (python3, venv, pip, screen)..."
$SUDO apt-get install -y python3 python3-venv python3-pip

if command -v screen >/dev/null 2>&1; then
    log "screen уже установлен: $(command -v screen)"
else
    log "screen не найден — устанавливаю..."
    $SUDO apt-get install -y screen
fi

# --- 3. Виртуальное окружение --------------------------------------------------
if [ -f "$VENV_DIR/bin/activate" ]; then
    log "[3/8] Виртуальное окружение уже существует: $VENV_DIR"
else
    log "[3/8] Создаю виртуальное окружение: $VENV_DIR"
    python3 -m venv "$VENV_DIR"
fi

# shellcheck disable=SC1091
source "$VENV_DIR/bin/activate"
log "venv активирован: python=$(which python)"

# --- 4. Обновление pip --------------------------------------------------------
log "[4/8] Обновление pip..."
python -m pip install --upgrade pip

# --- 5. Установка зависимостей -------------------------------------------------
if [ -f "$SCRIPT_DIR/requirements.txt" ]; then
    log "[5/8] Установка зависимостей из requirements.txt..."
    pip install -r "$SCRIPT_DIR/requirements.txt"
else
    log "[5/8] requirements.txt не найден — пропускаю установку зависимостей"
fi

# --- 6. Настройка .env (BOT_TOKEN, ADMINS) ------------------------------------
log "[6/8] Настройка .env (токен бота и id администратора)..."

# Если .env ещё нет — создаём из примера (если он есть)
if [ ! -f "$ENV_FILE" ] && [ -f "$SCRIPT_DIR/src/.env.example" ]; then
    cp "$SCRIPT_DIR/src/.env.example" "$ENV_FILE"
    log "Создан $ENV_FILE из .env.example"
fi

if [ -t 0 ]; then
    # API-ключ (токен) Telegram-бота от @BotFather
    prompt_env "BOT_TOKEN" "Введите API-ключ (токен) бота от @BotFather"
    # Telegram ID администратора (можно несколько через запятую)
    prompt_env "ADMINS" "Введите Telegram ID администратора (несколько — через запятую)"
else
    log "Неинтерактивный запуск — пропускаю ввод BOT_TOKEN/ADMINS, использую текущий .env"
fi

# --- 7. Автозапуск после перезагрузки (cron @reboot) --------------------------
log "[7/8] Настройка автозапуска после перезагрузки сервера..."

# Гарантируем, что демон cron установлен и включён (для срабатывания @reboot)
$SUDO apt-get install -y cron
$SUDO systemctl enable --now cron 2>/dev/null || $SUDO systemctl enable --now crond 2>/dev/null || true

SCREEN_BIN="$(command -v screen || echo /usr/bin/screen)"
CRON_TAG="# vpn-bot-autostart ($SCREEN_SESSION)"
# Команда автозапуска: поднять бота в screen (без переустановки зависимостей)
CRON_LINE="@reboot cd $SCRIPT_DIR && $SCREEN_BIN -dmS $SCREEN_SESSION $VENV_DIR/bin/python src/app.py $CRON_TAG"

# Идемпотентно: удаляем прежнюю запись автозапуска бота и добавляем актуальную
( crontab -l 2>/dev/null | grep -vF "$CRON_TAG"; echo "$CRON_LINE" ) | crontab -
log "✅ Автозапуск настроен (crontab @reboot). Текущая запись:"
crontab -l 2>/dev/null | grep -F "$CRON_TAG" | tee -a "$LOG"

# --- 8. Запуск бота в screen --------------------------------------------------
log "[8/8] Запуск бота в screen-сессии '$SCREEN_SESSION'..."

# Если сессия уже запущена — останавливаем её перед перезапуском
if screen -list 2>/dev/null | grep -q "\.${SCREEN_SESSION}[[:space:]]"; then
    log "Сессия '$SCREEN_SESSION' уже запущена — перезапускаю..."
    screen -S "$SCREEN_SESSION" -X quit || true
    sleep 1
fi

cd "$SCRIPT_DIR"
screen -dmS "$SCREEN_SESSION" "$VENV_DIR/bin/python" src/app.py

if screen -list 2>/dev/null | grep -q "\.${SCREEN_SESSION}[[:space:]]"; then
    log "✅ Бот запущен. Подключиться к консоли: screen -r $SCREEN_SESSION (выход: Ctrl+A, D)"
else
    log "🛑 Не удалось запустить screen-сессию '$SCREEN_SESSION'. Смотрите $LOG"
    exit 1
fi
