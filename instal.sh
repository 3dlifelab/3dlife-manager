#!/bin/bash

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
FRONTEND_DIST_PATH="./dist"

# Путь к вашему готовому nginx-конфигу
YOUR_NGINX_CONFIG="./service/3dlife-manager"
CONFIG_FILENAME="3dlife-manager"
# Репозиторий с фронтендом (в формате owner/repo)
FRONTEND_REPO="3dlifelab/3dlife-manager-frontend"

# Имя вашего Flask-приложения (файл:переменная)
FLASK_APP="app:app"


# ============================================================================
# ШАГ 1: Проверка прав root
# ============================================================================

if [ "$EUID" -ne 0 ]; then
    log_error "Этот скрипт должен быть запущен с правами root (sudo)"
    exit 1
fi

log_info "Начинаем установку..."

# ============================================================================
# ШАГ 2: Установка системных пакетов
# ============================================================================

log_info "Шаг 1: Установка системных пакетов..."

apt update
apt upgrade -y

# Базовые утилиты
apt install -y git curl wget build-essential

# Python и venv
apt install -y python3 python3-pip python3-venv

# Nginx
apt install -y nginx

# Polkit (обычно уже установлен, но на всякий случай)
apt install -y policykit-1


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

# Добавляем в группу netdev для доступа к NetworkManager через polkit
usermod -aG netdev "$APP_USER"
log_info "Пользователь $APP_USER добавлен в группу netdev"

# ============================================================================
# ШАГ 4: Создание директорий
# ============================================================================

log_info "Шаг 3: Создание директорий..."

mkdir -p "$BACKEND_DIR"
mkdir -p "$FRONTEND_DIR"
mkdir -p "$(dirname "$VENV_DIR")"

chown -R "$APP_USER:$APP_USER" "$BACKEND_DIR"
chown -R www-data:www-data "$FRONTEND_DIR"
chmod -R 755 "$FRONTEND_DIR"

log_info "Директории созданы"

# ============================================================================
# ШАГ 5: Настройка Polkit
# ============================================================================

log_info "Шаг 4: Настройка Polkit для NetworkManager..."

POLKIT_RULE_FILE="/etc/polkit-1/rules.d/50-nm-network.rules"

cat > "$POLKIT_RULE_FILE" << 'EOF'
polkit.addRule(function(action, subject) {
    if (action.id.indexOf("org.freedesktop.NetworkManager.") === 0 && subject.isInGroup("netdev")) {
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
sudo -u "$APP_USER" python3 -m venv "$VENV_DIR"

# Обновляем pip
log_info "Обновление pip..."
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install --upgrade pip

# Устанавливаем зависимости
log_info "Установка зависимостей Python..."
sudo -u "$APP_USER" "$VENV_DIR/bin/pip" install -r "$BACKEND_DIR/requirements.txt"


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
systemctl start wifi-manager

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

# Проверяем, что указан репозиторий с фронтендом
if [ -z "$FRONTEND_REPO" ]; then
    log_error "Переменная FRONTEND_REPO не установлена!"
    log_error "Укажите репозиторий в формате 'owner/repo' в начале скрипта"
    exit 1
fi

# Получаем информацию о последнем release
log_info "Получение информации о последнем release из $FRONTEND_REPO..."

RELEASE_INFO=$(curl -s "https://api.github.com/repos/$FRONTEND_REPO/releases/latest")

# Проверяем, что release существует
if echo "$RELEASE_INFO" | grep -q '"message": "Not Found"'; then
    log_error "Не удалось найти releases в репозитории $FRONTEND_REPO"
    log_error "Убедитесь, что репозиторий публичный или настроен токен GitHub"
    exit 1
fi

# Получаем URL для скачивания ZIP-архива (ищем asset с расширением .zip)
DOWNLOAD_URL=$(echo "$RELEASE_INFO" | grep "browser_download_url.*\.zip" | head -1 | cut -d '"' -f 4)

if [ -z "$DOWNLOAD_URL" ]; then
    log_error "Не найден ZIP-архив в последнем release!"
    log_error "Убедитесь, что в release загружен файл с расширением .zip"
    exit 1
fi

# Получаем версию release
VERSION=$(echo "$RELEASE_INFO" | grep '"tag_name"' | head -1 | cut -d '"' -f 4)
log_info "Найден release: $VERSION"

# Создаем временную директорию для скачивания
TEMP_DIR=$(mktemp -d)
ARCHIVE_FILE="$TEMP_DIR/frontend.zip"

# Скачиваем архив
log_info "Скачивание архива..."
if ! curl -L -o "$ARCHIVE_FILE" "$DOWNLOAD_URL"; then
    log_error "Не удалось скачать архив!"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Проверяем размер архива
ARCHIVE_SIZE=$(du -h "$ARCHIVE_FILE" | cut -f1)
log_info "Архив скачан: $ARCHIVE_SIZE"

# Создаем временную папку для распаковки
EXTRACT_DIR="$TEMP_DIR/extracted"
mkdir -p "$EXTRACT_DIR"

# Распаковываем архив
log_info "Распаковка архива..."
if ! unzip -q "$ARCHIVE_FILE" -d "$EXTRACT_DIR"; then
    log_error "Не удалось распаковать архив!"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# Проверяем структуру: если внутри есть одна папка, заходим в неё
# (GitHub иногда упаковывает в подпапку)
if [ $(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d | wc -l) -eq 1 ] && \
   [ $(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 | wc -l) -eq 1 ]; then
    # Есть только одна папка на верхнем уровне
    INNER_DIR=$(find "$EXTRACT_DIR" -mindepth 1 -maxdepth 1 -type d)
    log_info "Обнаружена вложенная папка: $(basename $INNER_DIR)"
    EXTRACT_DIR="$INNER_DIR"
fi

# Проверяем, что есть index.html
if [ ! -f "$EXTRACT_DIR/index.html" ]; then
    log_error "В архиве не найден index.html!"
    log_error "Проверьте структуру релиза в репозитории $FRONTEND_REPO"
    rm -rf "$TEMP_DIR"
    exit 1
fi

# ============================================================================
# БЕКАП СТАРОЙ ВЕРСИИ (опционально)
# ============================================================================

if [ -d "$FRONTEND_DIR" ] && [ "$(ls -A $FRONTEND_DIR 2>/dev/null)" ]; then
    BACKUP_DIR="/var/www/3dlife-manager/frontend-backup-$(date +%Y%m%d-%H%M%S)"
    log_info "Создание бэкапа старой версии в $BACKUP_DIR..."
    cp -r "$FRONTEND_DIR" "$BACKUP_DIR"
    log_info "Бэкап создан"
fi

# ============================================================================
# УСТАНОВКА НОВОЙ ВЕРСИИ
# ============================================================================

log_info "Установка новой версии..."

# Очищаем старую директорию
rm -rf "$FRONTEND_DIR"
mkdir -p "$FRONTEND_DIR"

# Копируем новые файлы
cp -r "$EXTRACT_DIR"/* "$FRONTEND_DIR/"

# Устанавливаем правильные права
chown -R www-data:www-data "$FRONTEND_DIR"
chmod -R 755 "$FRONTEND_DIR"

# ============================================================================
# ОЧИСТКА
# ============================================================================

log_info "Очистка временных файлов..."
rm -rf "$TEMP_DIR"

log_info "Frontend установлен (версия: $VERSION)"

# ============================================================================
# ШАГ 9: Настройка Nginx (используем ваш готовый конфиг)
# ============================================================================

og_info "Шаг 8: Настройка Nginx..."

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

# 4. Удаляем стандартный конфиг nginx, чтобы он не перехватывал порт 80
rm -f /etc/nginx/sites-enabled/default
# Также удалим ту самую ошибочную ссылку на папку, если она вдруг создалась
rm -f /etc/nginx/sites-enabled/sites-available

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
fi

# Проверяем nginx
if systemctl is-active --quiet nginx; then
    log_info "Nginx: РАБОТАЕТ"
else
    log_error "Nginx: НЕ РАБОТАЕТ"
    log_error "Проверьте логи: journalctl -u nginx -n 50"
fi


echo ""
echo "=========================================="
echo "ВАЖНАЯ ИНФОРМАЦИЯ:"
echo "=========================================="
echo ""
echo "1. IP адрес Raspberry Pi:"
hostname -I | awk '{print $1}'
echo ""
echo "2. Откройте в браузере: http://$(hostname -I | awk '{print $1}')"
echo ""
echo "3. Логи Backend:"
echo "   sudo journalctl -u wifi-manager -f"
echo ""
echo "4. Логи Nginx:"
echo "   sudo tail -f /var/log/nginx/error.log"
echo "=========================================="