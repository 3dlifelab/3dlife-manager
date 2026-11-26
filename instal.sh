#!/bin/bash
set -Eeuo pipefail

# ============================================================================
# Скрипт установки Flask + Vue.js приложения на Raspberry Pi
# ============================================================================

# Цвета для вывода
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Функция для вывода сообщений
log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# ============================================================================
# КОНФИГУРАЦИЯ (измените под себя)
# ============================================================================

# Имя пользователя, от которого будет работать приложение
APP_USER="artpro"

# Пути
BACKEND_DIR="/home/$APP_USER/3dlife-manager-backend/"
FRONTEND_DIR="/var/www/3dlife-manager"
VENV_DIR="/home/$APP_USER/3dlife-manager-backend/wifi-manager-env"
SYSTEMD_SERVICE_FILE="./service/wifi-manager.service"

BACKEND_SOURCE_DIR="./backend"

# Путь к dist/ папке фронтенда (собранной через npm run build)
FRONTEND_DIST_PATH="./frontend/dist"

# Путь к вашему готовому nginx-конфигу
YOUR_NGINX_CONFIG="./service/3dlife-manager"
CONFIG_FILENAME="3dlife-manager"

# Имя вашего Flask-приложения (файл:переменная)
FLASK_APP="app:app"


# ============================================================================
# ШАГ 1: Проверка прав root
# ============================================================================

if [ "$EUID" -ne 0 ]; then
    log_error "Этот скрипт должен быть запущен с правами root (sudo)"
    exit 1
fi

cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
for required_file in "$BACKEND_SOURCE_DIR/requirements.txt" "$SYSTEMD_SERVICE_FILE" \
    "$YOUR_NGINX_CONFIG" "$FRONTEND_DIST_PATH/index.html"; do
    if [ ! -f "$required_file" ]; then
        log_error "Файл не найден: $required_file"
        log_error "Для установки используйте распакованный релиз с готовым фронтендом"
        exit 1
    fi
done

if ! systemctl is-active --quiet NetworkManager.service; then
    log_error "Для менеджера Wi-Fi требуется запущенный NetworkManager"
    exit 1
fi
log_info "Начинаем установку..."

# ============================================================================
# ШАГ 2: Установка системных пакетов
# ============================================================================

log_info "Шаг 1: Установка системных пакетов..."

apt update

# Базовые утилиты
apt install -y build-essential pkg-config libsystemd-dev iproute2

# Python и venv
apt install -y python3 python3-pip python3-venv python3-dev

# Nginx
apt install -y nginx

# Демон Polkit для авторизации запросов к NetworkManager
apt install -y polkitd


log_info "Системные пакеты установлены"

# ============================================================================
# ШАГ 3: Создание пользователя и настройка групп
# ============================================================================

log_info "Шаг 2: Создание пользователя $APP_USER..."

if id "$APP_USER" &>/dev/null; then
    log_warn "Пользователь $APP_USER уже существует"
else
    useradd -m -s /bin/bash "$APP_USER"
    log_info "Пользователь $APP_USER создан"
fi


# ============================================================================
# ШАГ 4: Создание директорий
# ============================================================================

log_info "Шаг 3: Создание директорий..."

mkdir -p "$BACKEND_DIR"
mkdir -p "$(dirname "$VENV_DIR")"

chown -R "$APP_USER:$APP_USER" "$BACKEND_DIR"

log_info "Директории созданы"

# ============================================================================
# ШАГ 5: Настройка Polkit
# ============================================================================

log_info "Шаг 4: Настройка Polkit для NetworkManager..."

POLKIT_RULE_FILE="/etc/polkit-1/rules.d/50-nm-network.rules"

cat > "$POLKIT_RULE_FILE" << EOF
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0 && subject.user === "$APP_USER") {
        return polkit.Result.YES;
    }
});
EOF

systemctl restart polkit

log_info "Polkit настроен"

# ============================================================================
# ШАГ 6: Установка Backend (Python venv + пакеты)
# ============================================================================

log_info "Шаг 5: Установка Backend..."

# Проверяем, есть ли backend в репозитории
if [ ! -d "$BACKEND_SOURCE_DIR" ]; then
    log_error "Директория backend не найдена: $BACKEND_SOURCE_DIR"
    log_error "Убедитесь, что вы запускаете скрипт из корня репозитория"
    exit 1
fi

# Проверяем, есть ли requirements.txt
if [ ! -f "$BACKEND_SOURCE_DIR/requirements.txt" ]; then
    log_error "Файл requirements.txt не найден в $BACKEND_SOURCE_DIR"
    exit 1
fi

# Копируем код из репозитория в целевую директорию
log_info "Копирование кода из $BACKEND_SOURCE_DIR в $BACKEND_DIR..."
mkdir -p "$BACKEND_DIR"
cp -r "$BACKEND_SOURCE_DIR"/* "$BACKEND_DIR/"

# Передаем права пользователю приложения
chown -R "$APP_USER:$APP_USER" "$BACKEND_DIR"

log_info "Код скопирован"

# Создаем виртуальное окружение от имени пользователя приложения
log_info "Создание виртуального окружения..."
runuser -u "$APP_USER" -- python3 -m venv "$VENV_DIR"

# Обновляем pip
log_info "Обновление pip..."
runuser -u "$APP_USER" -- "$VENV_DIR/bin/pip" install --upgrade pip

# Устанавливаем зависимости
log_info "Установка зависимостей Python..."
runuser -u "$APP_USER" -- "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt"


log_info "Backend установлен"
# ============================================================================
# ШАГ 7: Установка systemd-сервиса (используем ваш готовый файл)
# ============================================================================

log_info "Шаг 6: Установка systemd-сервиса..."

# Строго проверяем наличие вашего готового файла сервиса
if [ ! -f "$SYSTEMD_SERVICE_FILE" ]; then
    log_error "Файл сервиса не найден: $SYSTEMD_SERVICE_FILE"
    log_error "Пожалуйста, положите ваш готовый .service файл в директорию со скриптом"
    log_error "и убедитесь, что переменная SYSTEMD_SERVICE_FILE в начале скрипта указывает на него."
    exit 1
fi

# Копируем ваш готовый файл в директорию systemd
cp "$SYSTEMD_SERVICE_FILE" /etc/systemd/system/

# Перезагружаем демон systemd, чтобы он увидел новый файл
systemctl daemon-reload

# Включаем автозагрузку и запускаем сервис
systemctl enable wifi-manager
systemctl restart wifi-manager

# Небольшая пауза, чтобы сервис успел инициализироваться перед проверкой
sleep 2

if systemctl is-active --quiet wifi-manager; then
    log_info "Systemd-сервис успешно установлен и запущен"
else
    log_error "Не удалось запустить сервис wifi-manager"
    log_error "Проверьте логи: journalctl -u wifi-manager -n 20"
    exit 1
fi

# ============================================================================
# ШАГ 8: Установка Frontend
# ============================================================================

log_info "Шаг 7: Установка Frontend..."

# Подготавливаем новую версию до замены действующего каталога.
TEMP_DIR=$(mktemp -d /var/www/.3dlife-manager.XXXXXX)
trap 'rm -rf -- "$TEMP_DIR"' EXIT
mkdir "$TEMP_DIR/dist"
cp -a -- "$FRONTEND_DIST_PATH/." "$TEMP_DIR/dist/"
chown -R root:root "$TEMP_DIR/dist"
chmod -R u=rwX,go=rX "$TEMP_DIR/dist"

BACKUP_DIR=""
if [ -d "$FRONTEND_DIR" ]; then
    BACKUP_DIR=$(mktemp -d /var/www/.3dlife-manager-backup.XXXXXX)
    mv -- "$FRONTEND_DIR" "$BACKUP_DIR/dist"
fi
if ! mv -T -- "$TEMP_DIR/dist" "$FRONTEND_DIR"; then
    if [ -n "$BACKUP_DIR" ]; then
        mv -T -- "$BACKUP_DIR/dist" "$FRONTEND_DIR"
    fi
    exit 1
fi
if [ -n "$BACKUP_DIR" ]; then
    log_info "Резервная копия: $BACKUP_DIR/dist"
fi

# ============================================================================
# ШАГ 9: Настройка Nginx (используем ваш готовый конфиг)
# ============================================================================

log_info "Шаг 8: Настройка Nginx..."

# Имя вашего файла конфигурации (убедитесь, что он заканчивается на .conf)
# Если ваш файл называется просто "3dlife-manager", переименуйте его в "3dlife-manager.conf"
 

# Пути
NGINX_AVAILABLE="/etc/nginx/sites-available/$CONFIG_FILENAME"
NGINX_ENABLED="/etc/nginx/sites-enabled/$CONFIG_FILENAME"

# 1. Проверяем наличие исходного файла конфига
if [ ! -f "$YOUR_NGINX_CONFIG" ]; then
    log_error "Файл nginx-конфига не найден: $YOUR_NGINX_CONFIG"
    log_error "Пожалуйста, проверьте путь к файлу в начале скрипта."
    exit 1
fi

# 2. Копируем ваш готовый конфиг в папку sites-available
log_info "Копирование конфигурации в $NGINX_AVAILABLE..."
cp "$YOUR_NGINX_CONFIG" "$NGINX_AVAILABLE"

# 3. Создаем СИМВОЛИЧЕСКУЮ ССЫЛКУ на КОНКРЕТНЫЙ ФАЙЛ (не на папку!)
log_info "Активация конфигурации..."
ln -sf "$NGINX_AVAILABLE" "$NGINX_ENABLED"

# 5. Проверяем синтаксис Nginx
log_info "Проверка синтаксиса Nginx..."
if nginx -t; then
    systemctl restart nginx
    log_info "Nginx успешно настроен и перезапущен"
else
    log_error "Ошибка в конфигурации Nginx!"
    log_error "Проверьте файл: $YOUR_NGINX_CONFIG"
    exit 1
fi

# ============================================================================
# ШАГ 10: Финальная проверка
# ============================================================================

log_info "Шаг 9: Финальная проверка..."

echo ""
echo "=========================================="
echo "УСТАНОВКА ЗАВЕРШЕНА!"
echo "=========================================="
echo ""
echo "Проверка статусов сервисов:"
echo ""

# Проверяем backend
if systemctl is-active --quiet wifi-manager; then
    log_info "Backend (wifi-manager): РАБОТАЕТ"
else
    log_error "Backend (wifi-manager): НЕ РАБОТАЕТ"
    log_error "Проверьте логи: journalctl -u wifi-manager -n 50"
    exit 1
fi

# Проверяем nginx
if systemctl is-active --quiet nginx; then
    log_info "Nginx: РАБОТАЕТ"
else
    log_error "Nginx: НЕ РАБОТАЕТ"
    log_error "Проверьте логи: journalctl -u nginx -n 50"
    exit 1
fi


echo ""
echo "=========================================="
echo "ВАЖНАЯ ИНФОРМАЦИЯ:"
echo "=========================================="
echo ""
echo "1. IP адрес Raspberry Pi:"
hostname -I | awk '{print $1}'
echo ""
echo "2. Откройте в браузере: http://$(hostname -I | awk '{print $1}'):3000"
echo ""
echo "3. Логи Backend:"
echo "   sudo journalctl -u wifi-manager -f"
echo ""
echo "4. Логи Nginx:"
echo "   sudo tail -f /var/log/nginx/error.log"
echo "=========================================="