 # 🚕 Telegram Taxi Bot | Телеграм бот для такси

[English](#english) | [Русский](#русский)

## English

### Description
A Telegram bot for managing taxi orders and drivers queue. The bot helps to automate the process of distributing orders among drivers and managing their queue status.

### Features
- 👤 Driver registration system
- 📋 Automated queue management
- 🚗 Order distribution among drivers
- ⏱️ Automatic order timeout handling
- 📊 Driver status tracking
- 🔄 Dynamic menu system
- 👮 Admin panel for management

### Setup and Installation
1. Clone the repository
2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. Create `.env` file with the following variables:
```env
TELEGRAM_TOKEN=your_bot_token
GROUP_ID=your_group_id
ADMIN_PASSWORD=your_admin_password
```

4. Run the bot:
```bash
python main.py
```

### Admin Commands
- `/admin [password]` - Access admin panel
- View drivers list
- View current queue
- Reset queue
- Remove drivers

### Driver Commands
- `/start` - Start interaction with bot
- `/help` - Show help message

### Requirements
- Python 3.7+
- SQLite database
- python-telegram-bot
- SQLAlchemy
- python-dotenv

---

## Русский

### Описание
Телеграм бот для управления заказами такси и очередью водителей. Бот автоматизирует процесс распределения заказов между водителями и управление их статусом в очереди.

### Возможности
- 👤 Система регистрации водителей
- 📋 Автоматическое управление очередью
- 🚗 Распределение заказов между водителями
- ⏱️ Автоматическая обработка таймаута заказов
- 📊 Отслеживание статуса водителей
- 🔄 Динамическая система меню
- 👮 Панель администратора

### Установка и настройка
1. Клонируйте репозиторий
2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Создайте файл `.env` со следующими переменными:
```env
TELEGRAM_TOKEN=ваш_токен_бота
GROUP_ID=id_группы
ADMIN_PASSWORD=пароль_админа
```

4. Запустите бота:
```bash
python main.py
```

### Команды администратора
- `/admin [пароль]` - Доступ к панели администратора
- Просмотр списка водителей
- Просмотр текущей очереди
- Сброс очереди
- Удаление водителей

### Команды водителя
- `/start` - Начать работу с ботом
- `/help` - Показать справку

### Системные требования
- Python 3.7+
- SQLite база данных
- python-telegram-bot
- SQLAlchemy
- python-dotenv

### Использование
1. Водитель регистрируется через бота
2. После регистрации может встать в очередь
3. При появлении заказа в группе, бот автоматически отправляет его первому водителю в очереди
4. У водителя есть 30 секунд на принятие заказа
5. После выполнения заказа водитель может снова встать в очередь

### Безопасность
- Все действия логируются
- Защита от несанкционированного доступа к админ-панели
- Проверка прав доступа для каждого действия
- Защита от дублирования в очереди

---

## 📝 License | Лицензия
MIT License | Лицензия MIT
