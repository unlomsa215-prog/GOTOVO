import telebot
import sqlite3
import time
import logging
import random
import string
import threading
from datetime import datetime, timedelta
from telebot import types
from telebot import apihelper
from collections import defaultdict

# ---------------------------- НАСТРОЙКИ -----------------------------
TOKEN = "8683749848:AAHboiUJknEKKHSAMhEGM9ueMq1alVhNsrc"
ADMIN_PASSWORD = "1388019284"
OWNER_USERNAME = "kyniks_my"
WITHDRAW_CONTACT = "kyniks_my"
REQUIRED_CHANNEL = "@grussuacrmpfreemoney"  # Канал для обязательной подписки
REQUIRED_CHANNEL_ID = None  # ID будет получен автоматически

# Настройки боевого пропуска
BATTLE_PASS_SETTINGS = {
    'exp_per_task': 20,
    'exp_per_level': 100,
    'levels': {
        (1, 10): (10000000, 20000000),    # 10-20 млн
        (20, 90): (25000000, 25000000),   # 25 млн
        (90, 100): (30000000, 30000000)   # 30 млн
    },
    'top1_reward': 'BMW M5 F90 CS 🏎️'
}

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# Инициализация бота
try:
    bot = telebot.TeleBot(TOKEN, parse_mode="HTML")
    bot_info = bot.get_me()
    BOT_USERNAME = bot_info.username
    logger.info(f"✅ Бот запущен: @{BOT_USERNAME}")
except Exception as e:
    logger.error(f"❌ Ошибка при инициализации бота: {e}")
    exit(1)

# ---------------------------- БАЗА ДАННЫХ ----------------------------
def init_db():
    conn = sqlite3.connect('bot_data.db', check_same_thread=False)
    c = conn.cursor()
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (user_id INTEGER PRIMARY KEY,
                  username TEXT,
                  first_name TEXT,
                  coins INTEGER DEFAULT 1000000,
                  last_bonus_time INTEGER DEFAULT 0,
                  last_daily_time INTEGER DEFAULT 0,
                  last_football_time INTEGER DEFAULT 0,
                  registered_at INTEGER DEFAULT 0,
                  is_admin INTEGER DEFAULT 0,
                  is_deputy INTEGER DEFAULT 0,
                  banned INTEGER DEFAULT 0,
                  battle_pass_level INTEGER DEFAULT 1,
                  battle_pass_exp INTEGER DEFAULT 0,
                  battle_pass_claimed TEXT DEFAULT '',
                  total_tasks_completed INTEGER DEFAULT 0,
                  car_reward_claimed INTEGER DEFAULT 0,
                  complaints_approved INTEGER DEFAULT 0,
                  deputy_approved INTEGER DEFAULT 0,
                  channel_subscribed INTEGER DEFAULT 0)''')
    
    # Таблица жалоб
    c.execute('''CREATE TABLE IF NOT EXISTS complaints
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  target_username TEXT,
                  reason TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at INTEGER,
                  resolved_at INTEGER,
                  resolved_by INTEGER)''')
    
    # Таблица заявок на зама
    c.execute('''CREATE TABLE IF NOT EXISTS deputy_apps
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  reason TEXT,
                  status TEXT DEFAULT 'pending',
                  created_at INTEGER,
                  resolved_at INTEGER,
                  resolved_by INTEGER)''')
    
    # Таблица промокодов
    c.execute('''CREATE TABLE IF NOT EXISTS promo_codes
                 (code TEXT PRIMARY KEY,
                  amount INTEGER,
                  created_by INTEGER,
                  used_by INTEGER DEFAULT NULL,
                  created_at INTEGER)''')
    
    # Таблица переводов
    c.execute('''CREATE TABLE IF NOT EXISTS transfers
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  from_user INTEGER,
                  to_user INTEGER,
                  amount INTEGER,
                  timestamp INTEGER)''')
    
    # Таблица заданий
    c.execute('''CREATE TABLE IF NOT EXISTS tasks
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  description TEXT,
                  reward INTEGER,
                  is_active INTEGER DEFAULT 1,
                  task_type TEXT DEFAULT 'permanent',
                  required_count INTEGER DEFAULT 1)''')
    
    # Таблица выполненных заданий
    c.execute('''CREATE TABLE IF NOT EXISTS completed_tasks
                 (user_id INTEGER,
                  task_id INTEGER,
                  completed_at INTEGER,
                  PRIMARY KEY (user_id, task_id))''')
    
    # Таблица прогресса заданий
    c.execute('''CREATE TABLE IF NOT EXISTS task_progress
                 (user_id INTEGER,
                  task_id INTEGER,
                  current_count INTEGER DEFAULT 0,
                  PRIMARY KEY (user_id, task_id))''')
    
    # Таблица кейсов
    c.execute('''CREATE TABLE IF NOT EXISTS cases
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  name TEXT,
                  price INTEGER,
                  min_reward INTEGER,
                  max_reward INTEGER,
                  lose_chance INTEGER DEFAULT 60)''')
    
    # Таблица достижений
    c.execute('''CREATE TABLE IF NOT EXISTS achievements
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  achievement_name TEXT,
                  achieved_at INTEGER,
                  UNIQUE(user_id, achievement_name))''')
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

init_db()

# ---------------------------- ПРОВЕРКА ПОДПИСКИ НА КАНАЛ ----------------------------
def get_channel_id():
    """Получить ID канала по username"""
    global REQUIRED_CHANNEL_ID
    try:
        chat = bot.get_chat(REQUIRED_CHANNEL)
        REQUIRED_CHANNEL_ID = chat.id
        logger.info(f"✅ ID канала {REQUIRED_CHANNEL}: {REQUIRED_CHANNEL_ID}")
        return chat.id
    except Exception as e:
        logger.error(f"❌ Ошибка получения ID канала: {e}")
        return None

def check_channel_subscription(user_id):
    """Проверить подписку пользователя на канал"""
    if not REQUIRED_CHANNEL_ID:
        get_channel_id()
    
    if not REQUIRED_CHANNEL_ID:
        return True  # Если не можем проверить, пропускаем
    
    try:
        member = bot.get_chat_member(REQUIRED_CHANNEL_ID, user_id)
        is_subscribed = member.status in ['member', 'administrator', 'creator']
        
        # Обновляем статус в БД
        if is_subscribed:
            conn = get_db_connection()
            try:
                c = conn.cursor()
                c.execute("UPDATE users SET channel_subscribed = 1 WHERE user_id = ?", (user_id,))
                conn.commit()
            finally:
                conn.close()
        
        return is_subscribed
    except Exception as e:
        logger.error(f"Ошибка проверки подписки для {user_id}: {e}")
        return False

def require_subscription(func):
    """Декоратор для проверки подписки"""
    def wrapper(message):
        user_id = message.from_user.id
        
        if not check_channel_subscription(user_id):
            markup = types.InlineKeyboardMarkup()
            markup.add(types.InlineKeyboardButton(
                "📢 Подписаться на канал", 
                url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}"
            ))
            markup.add(types.InlineKeyboardButton(
                "✅ Я подписался", 
                callback_data="check_subscription"
            ))
            
            bot.send_message(
                message.chat.id,
                f"❌ <b>Требуется подписка!</b>\n\n"
                f"Для использования бота необходимо подписаться на канал:\n"
                f"{REQUIRED_CHANNEL}\n\n"
                f"После подписки нажмите кнопку проверки.",
                reply_markup=markup
            )
            return
        
        return func(message)
    return wrapper

# ---------------------------- ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ ----------------------------
def get_db_connection():
    return sqlite3.connect('bot_data.db', check_same_thread=False)

def get_user(user_id, username=None, first_name=None):
    """Получить пользователя, создать если нет."""
    conn = get_db_connection()
    c = conn.cursor()
    try:
        c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user = c.fetchone()
        if user is None:
            now = int(time.time())
            c.execute("""INSERT INTO users 
                        (user_id, username, first_name, coins, registered_at) 
                        VALUES (?, ?, ?, ?, ?)""",
                      (user_id, username, first_name, 1000000, now))
            conn.commit()
            return {
                'user_id': user_id, 'username': username, 'first_name': first_name,
                'coins': 1000000, 'last_bonus_time': 0, 'last_daily_time': 0,
                'last_football_time': 0, 'registered_at': now, 'is_admin': 0,
                'is_deputy': 0, 'banned': 0, 'battle_pass_level': 1,
                'battle_pass_exp': 0, 'battle_pass_claimed': '',
                'total_tasks_completed': 0, 'car_reward_claimed': 0,
                'complaints_approved': 0, 'deputy_approved': 0,
                'channel_subscribed': 0
            }
        else:
            # Обновляем username если изменился
            if username and user[1] != username:
                c.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))
                conn.commit()
            
            # Проверяем наличие новых полей
            if len(user) < 19:
                try:
                    c.execute("ALTER TABLE users ADD COLUMN channel_subscribed INTEGER DEFAULT 0")
                except:
                    pass
                conn.commit()
                c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
                user = c.fetchone()
            
            return {
                'user_id': user[0], 'username': user[1], 'first_name': user[2],
                'coins': user[3], 'last_bonus_time': user[4], 'last_daily_time': user[5],
                'last_football_time': user[6] if len(user) > 6 else 0,
                'registered_at': user[7] if len(user) > 7 else 0,
                'is_admin': user[8] if len(user) > 8 else 0,
                'is_deputy': user[9] if len(user) > 9 else 0,
                'banned': user[10] if len(user) > 10 else 0,
                'battle_pass_level': user[11] if len(user) > 11 else 1,
                'battle_pass_exp': user[12] if len(user) > 12 else 0,
                'battle_pass_claimed': user[13] if len(user) > 13 else '',
                'total_tasks_completed': user[14] if len(user) > 14 else 0,
                'car_reward_claimed': user[15] if len(user) > 15 else 0,
                'complaints_approved': user[16] if len(user) > 16 else 0,
                'deputy_approved': user[17] if len(user) > 17 else 0,
                'channel_subscribed': user[18] if len(user) > 18 else 0
            }
    finally:
        conn.close()

def update_coins(user_id, delta):
    """Увеличить/уменьшить монеты."""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (delta, user_id))
        conn.commit()
        return True
    except Exception as e:
        logger.error(f"Ошибка обновления монет: {e}")
        return False
    finally:
        conn.close()

def is_admin_or_deputy(user_id):
    """Проверка прав администратора/заместителя"""
    user = get_user(user_id)
    return user['is_admin'] == 1 or user['is_deputy'] == 1

def is_banned(user_id):
    """Проверка на бан"""
    user = get_user(user_id)
    return user.get('banned', 0) == 1

def get_battle_pass_reward(level):
    """Получить награду за уровень боевого пропуска"""
    for level_range, reward_range in BATTLE_PASS_SETTINGS['levels'].items():
        if level_range[0] <= level <= level_range[1]:
            if isinstance(reward_range, tuple):
                return random.randint(reward_range[0], reward_range[1])
            else:
                return reward_range
    return 10000000

def add_battle_pass_exp(user_id, exp_amount):
    """Добавить опыт боевого пропуска"""
    user = get_user(user_id)
    current_level = user['battle_pass_level']
    current_exp = user['battle_pass_exp'] + exp_amount
    levels_gained = 0
    
    while current_exp >= BATTLE_PASS_SETTINGS['exp_per_level']:
        current_level += 1
        current_exp -= BATTLE_PASS_SETTINGS['exp_per_level']
        levels_gained += 1
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""UPDATE users 
                    SET battle_pass_level = ?, 
                        battle_pass_exp = ? 
                    WHERE user_id = ?""", 
                  (current_level, current_exp, user_id))
        conn.commit()
        return levels_gained, current_level
    finally:
        conn.close()

def claim_battle_pass_reward(user_id, level):
    """Забрать награду боевого пропуска"""
    user = get_user(user_id)
    claimed_levels = user['battle_pass_claimed'].split(',') if user['battle_pass_claimed'] else []
    
    if str(level) in claimed_levels:
        return False, "Награда уже получена!"
    
    if level > user['battle_pass_level']:
        return False, "Уровень не достигнут!"
    
    reward = get_battle_pass_reward(level)
    update_coins(user_id, reward)
    
    claimed_levels.append(str(level))
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET battle_pass_claimed = ? WHERE user_id = ?",
                  (','.join(claimed_levels), user_id))
        conn.commit()
        
        if level >= 100 and not user['car_reward_claimed']:
            c.execute("UPDATE users SET car_reward_claimed = 1 WHERE user_id = ?", (user_id,))
            conn.commit()
            
            # Добавляем достижение
            c.execute("""INSERT OR IGNORE INTO achievements 
                        (user_id, achievement_name, achieved_at) 
                        VALUES (?, ?, ?)""",
                      (user_id, "🏎️ Владелец BMW M5 F90 CS", int(time.time())))
            conn.commit()
            
            return True, f"🎉 Получена награда: {reward:,} ₽ и {BATTLE_PASS_SETTINGS['top1_reward']}!"
        
        return True, f"🎉 Получена награда: {reward:,} ₽"
    finally:
        conn.close()

def get_top_players(limit=10):
    """Получить топ игроков"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT user_id, username, first_name, coins, battle_pass_level 
                    FROM users 
                    WHERE banned = 0 
                    ORDER BY coins DESC 
                    LIMIT ?""", (limit,))
        return c.fetchall()
    finally:
        conn.close()

def get_user_rank(user_id):
    """Получить место в рейтинге"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT COUNT(*) + 1 FROM users 
                    WHERE coins > (SELECT coins FROM users WHERE user_id = ?) 
                    AND banned = 0""", (user_id,))
        return c.fetchone()[0]
    finally:
        conn.close()

# ---------------------------- ИНИЦИАЛИЗАЦИЯ ЗАДАНИЙ ----------------------------
def init_permanent_tasks():
    """Создание постоянных заданий"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM tasks WHERE task_type = 'permanent'")
        if c.fetchone()[0] == 0:
            tasks = [
                ("📝 Отправить 3 жалобы, которые одобрят", 35000000, 3),
                ("👔 Получить одобрение заявки на заместителя", 40000000, 1),
                ("💰 Накопить 50,000,000 монет", 25000000, 1),
                ("🎯 Достичь 5 уровня боевого пропуска", 30000000, 1),
                ("🏆 Попасть в топ 50 игроков", 45000000, 1),
                ("🤝 Сделать 10 переводов другим игрокам", 30000000, 10),
                ("🎲 Открыть 5 кейсов", 35000000, 5),
                ("📊 Достичь 10 уровня боевого пропуска", 50000000, 1),
                ("👑 Стать заместителем", 100000000, 1),
                ("🎯 Достичь 20 уровня боевого пропуска", 75000000, 1),
                ("💎 Накопить 100,000,000 монет", 50000000, 1),
                ("🏅 Выполнить 20 заданий", 40000000, 20)
            ]
            
            for desc, reward, req_count in tasks:
                c.execute("""INSERT INTO tasks 
                            (description, reward, is_active, task_type, required_count) 
                            VALUES (?, ?, 1, 'permanent', ?)""",
                          (desc, reward, req_count))
            conn.commit()
            logger.info("✅ Созданы постоянные задания")
    finally:
        conn.close()

def get_available_tasks(user_id):
    """Получить доступные задания для пользователя"""
    user = get_user(user_id)
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # Получаем все постоянные задания
        c.execute("""SELECT t.id, t.description, t.reward, t.required_count,
                           COALESCE(p.current_count, 0) as progress
                    FROM tasks t
                    LEFT JOIN task_progress p ON t.id = p.task_id AND p.user_id = ?
                    WHERE t.is_active = 1 AND t.task_type = 'permanent'
                    AND t.id NOT IN (
                        SELECT task_id FROM completed_tasks WHERE user_id = ?
                    )
                    ORDER BY t.reward DESC""", (user_id, user_id))
        
        tasks = c.fetchall()
        
        # Обновляем прогресс для специальных заданий
        for task in tasks:
            task_id, desc, reward, req_count, progress = task
            
            # Обновление прогресса для жалоб
            if "жалоб" in desc.lower():
                c.execute("""UPDATE task_progress 
                            SET current_count = ? 
                            WHERE user_id = ? AND task_id = ?""",
                          (user['complaints_approved'], user_id, task_id))
            
            # Обновление прогресса для заявки на зама
            elif "заместителя" in desc.lower() and "заявк" in desc.lower():
                c.execute("""UPDATE task_progress 
                            SET current_count = ? 
                            WHERE user_id = ? AND task_id = ?""",
                          (user['deputy_approved'], user_id, task_id))
            
            # Обновление прогресса для накопления монет
            elif "накопить" in desc.lower() or "монет" in desc.lower():
                target_amount = 50000000
                if "100" in desc:
                    target_amount = 100000000
                progress_value = 1 if user['coins'] >= target_amount else 0
                c.execute("""UPDATE task_progress 
                            SET current_count = ? 
                            WHERE user_id = ? AND task_id = ?""",
                          (progress_value, user_id, task_id))
            
            # Обновление прогресса для уровня БП
            elif "уровня боевого пропуска" in desc.lower():
                target_level = 5
                if "10" in desc:
                    target_level = 10
                elif "20" in desc:
                    target_level = 20
                progress_value = 1 if user['battle_pass_level'] >= target_level else 0
                c.execute("""UPDATE task_progress 
                            SET current_count = ? 
                            WHERE user_id = ? AND task_id = ?""",
                          (progress_value, user_id, task_id))
            
            # Обновление прогресса для топа
            elif "топ" in desc.lower():
                rank = get_user_rank(user_id)
                progress_value = 1 if rank <= 50 else 0
                c.execute("""UPDATE task_progress 
                            SET current_count = ? 
                            WHERE user_id = ? AND task_id = ?""",
                          (progress_value, user_id, task_id))
            
            # Обновление прогресса для заместителя
            elif "стать заместителем" in desc.lower():
                c.execute("""UPDATE task_progress 
                            SET current_count = ? 
                            WHERE user_id = ? AND task_id = ?""",
                          (1 if user['is_deputy'] else 0, user_id, task_id))
            
            # Обновление прогресса для общего количества заданий
            elif "выполнить" in desc.lower() and "заданий" in desc.lower():
                c.execute("""UPDATE task_progress 
                            SET current_count = ? 
                            WHERE user_id = ? AND task_id = ?""",
                          (user['total_tasks_completed'], user_id, task_id))
        
        conn.commit()
        
        # Получаем обновленные задания
        c.execute("""SELECT t.id, t.description, t.reward, t.required_count,
                           COALESCE(p.current_count, 0) as progress
                    FROM tasks t
                    LEFT JOIN task_progress p ON t.id = p.task_id AND p.user_id = ?
                    WHERE t.is_active = 1 AND t.task_type = 'permanent'
                    AND t.id NOT IN (
                        SELECT task_id FROM completed_tasks WHERE user_id = ?
                    )
                    ORDER BY t.reward DESC""", (user_id, user_id))
        
        return c.fetchall()
    finally:
        conn.close()

def complete_task(user_id, task_id):
    """Выполнить задание"""
    user = get_user(user_id)
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # Проверяем, не выполнено ли уже задание
        c.execute("SELECT * FROM completed_tasks WHERE user_id = ? AND task_id = ?", 
                  (user_id, task_id))
        if c.fetchone():
            return False, "❌ Задание уже выполнено!"
        
        # Получаем информацию о задании и прогрессе
        c.execute("""SELECT t.reward, t.required_count, t.description,
                           COALESCE(p.current_count, 0) as progress
                    FROM tasks t
                    LEFT JOIN task_progress p ON t.id = p.task_id AND p.user_id = ?
                    WHERE t.id = ? AND t.is_active = 1""", (user_id, task_id))
        task = c.fetchone()
        if not task:
            return False, "❌ Задание не найдено!"
        
        reward, req_count, desc, progress = task
        
        # Проверяем выполнение условия
        if progress < req_count:
            return False, f"❌ Не выполнены условия задания! Прогресс: {progress}/{req_count}"
        
        # Отмечаем как выполненное
        c.execute("""INSERT INTO completed_tasks (user_id, task_id, completed_at) 
                    VALUES (?, ?, ?)""", (user_id, task_id, int(time.time())))
        
        # Обновляем счетчики
        c.execute("""UPDATE users 
                    SET total_tasks_completed = total_tasks_completed + 1,
                        coins = coins + ?
                    WHERE user_id = ?""", (reward, user_id))
        
        conn.commit()
        
        # Добавляем опыт боевого пропуска
        levels_gained, new_level = add_battle_pass_exp(user_id, BATTLE_PASS_SETTINGS['exp_per_task'])
        
        # Добавляем достижения
        new_total = user['total_tasks_completed'] + 1
        if new_total == 10:
            c.execute("""INSERT OR IGNORE INTO achievements 
                        (user_id, achievement_name, achieved_at) 
                        VALUES (?, ?, ?)""",
                      (user_id, "✅ Новичок - выполнено 10 заданий", int(time.time())))
        elif new_total == 30:
            c.execute("""INSERT OR IGNORE INTO achievements 
                        (user_id, achievement_name, achieved_at) 
                        VALUES (?, ?, ?)""",
                      (user_id, "⭐ Профессионал - выполнено 30 заданий", int(time.time())))
        conn.commit()
        
        message = f"✅ Задание выполнено!\n💰 Получено: {reward:,} ₽\n⭐ Получено опыта БП: {BATTLE_PASS_SETTINGS['exp_per_task']}"
        if levels_gained > 0:
            message += f"\n🎉 Получен новый уровень БП: {new_level}!"
        
        return True, message
    except Exception as e:
        logger.error(f"Ошибка выполнения задания: {e}")
        return False, "❌ Ошибка при выполнении задания!"
    finally:
        conn.close()

def update_task_progress(user_id, task_type, increment=1):
    """Обновить прогресс задания"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        
        # Находим задания по типу
        if task_type == "transfer":
            c.execute("""SELECT id FROM tasks 
                        WHERE description LIKE '%перевод%' AND task_type = 'permanent'""")
        elif task_type == "case":
            c.execute("""SELECT id FROM tasks 
                        WHERE description LIKE '%кейс%' AND task_type = 'permanent'""")
        else:
            return
        
        task_ids = c.fetchall()
        
        for (task_id,) in task_ids:
            # Обновляем прогресс
            c.execute("""INSERT INTO task_progress (user_id, task_id, current_count)
                        VALUES (?, ?, 1)
                        ON CONFLICT(user_id, task_id) 
                        DO UPDATE SET current_count = current_count + 1""",
                      (user_id, task_id))
        
        conn.commit()
    finally:
        conn.close()

def get_or_create_cases():
    """Создать кейсы с шансами"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM cases")
        if c.fetchone()[0] == 0:
            cases = [
                ("Обычный кейс", 50000000, 25000000, 100000000, 60),
                ("Редкий кейс", 150000000, 100000000, 300000000, 65),
                ("Эпический кейс", 500000000, 300000000, 1000000000, 70),
                ("Легендарный кейс", 2000000000, 1000000000, 5000000000, 75)
            ]
            for name, price, min_r, max_r, lose_chance in cases:
                c.execute("""INSERT INTO cases 
                            (name, price, min_reward, max_reward, lose_chance) 
                            VALUES (?, ?, ?, ?, ?)""",
                          (name, price, min_r, max_r, lose_chance))
            conn.commit()
            return True
    finally:
        conn.close()
    return False

def get_cases():
    """Получить список кейсов"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT id, name, price, min_reward, max_reward, lose_chance FROM cases")
        return c.fetchall()
    finally:
        conn.close()

def open_case(user_id, case_id):
    """Открыть кейс с шансом проигрыша"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT name, price, min_reward, max_reward, lose_chance FROM cases WHERE id = ?", (case_id,))
        case = c.fetchone()
        if not case:
            return False, "Кейс не найден!"
        
        name, price, min_r, max_r, lose_chance = case
        
        c.execute("SELECT coins FROM users WHERE user_id = ?", (user_id,))
        user_coins = c.fetchone()[0]
        if user_coins < price:
            return False, f"Недостаточно монет! Нужно {price:,} ₽"
        
        # Списываем цену
        c.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (price, user_id))
        
        # Проверяем, выиграл ли игрок
        if random.randint(1, 100) <= lose_chance:
            conn.commit()
            return True, f"😢 К сожалению, вы ничего не выиграли! Потрачено {price:,} ₽"
        
        # Выигрыш
        reward = random.randint(min_r, max_r)
        c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (reward, user_id))
        conn.commit()
        
        return True, f"🎉 Вы открыли {name} и выиграли {reward:,} ₽!"
    finally:
        conn.close()

def get_total_users():
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        return c.fetchone()[0]
    finally:
        conn.close()

# ---------------------------- КЛАВИАТУРЫ ----------------------------
def main_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("💰 Баланс", callback_data="balance"),
        types.InlineKeyboardButton("📊 Профиль", callback_data="profile"),
        types.InlineKeyboardButton("📋 Задания", callback_data="tasks"),
        types.InlineKeyboardButton("🎯 Боевой пропуск", callback_data="battle_pass"),
        types.InlineKeyboardButton("🎁 Бонус", callback_data="bonus"),
        types.InlineKeyboardButton("🎫 Ежедневная", callback_data="daily"),
        types.InlineKeyboardButton("⚽ Футбол", callback_data="football"),
        types.InlineKeyboardButton("💸 Перевод", callback_data="transfer"),
        types.InlineKeyboardButton("🎲 Кейсы", callback_data="cases"),
        types.InlineKeyboardButton("🏆 Топ", callback_data="leaderboard"),
        types.InlineKeyboardButton("📝 Жалоба", callback_data="complain"),
        types.InlineKeyboardButton("👔 Стать замом", callback_data="deputy"),
        types.InlineKeyboardButton("💸 Вывод", callback_data="withdraw"),
        types.InlineKeyboardButton("🏅 Достижения", callback_data="achievements"),
        types.InlineKeyboardButton("📜 Правила", callback_data="rules"),
        types.InlineKeyboardButton("❓ Помощь", callback_data="help")
    ]
    markup.add(*buttons)
    return markup

def admin_panel():
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [
        types.InlineKeyboardButton("📋 Жалобы", callback_data="admin_complaints"),
        types.InlineKeyboardButton("👔 Заявки на зама", callback_data="admin_deputies"),
        types.InlineKeyboardButton("💰 Выдать валюту", callback_data="admin_issue"),
        types.InlineKeyboardButton("🎫 Создать промокод", callback_data="admin_create_promo"),
        types.InlineKeyboardButton("📋 Список промокодов", callback_data="admin_promos"),
        types.InlineKeyboardButton("👥 Игроки", callback_data="admin_users"),
        types.InlineKeyboardButton("🚫 Забанить", callback_data="admin_ban"),
        types.InlineKeyboardButton("✅ Разбанить", callback_data="admin_unban"),
        types.InlineKeyboardButton("📊 Статистика", callback_data="admin_stats"),
        types.InlineKeyboardButton("🔙 Выйти", callback_data="admin_exit")
    ]
    markup.add(*buttons)
    return markup

def battle_pass_menu(user_id):
    user = get_user(user_id)
    current_level = user['battle_pass_level']
    
    markup = types.InlineKeyboardMarkup(row_width=2)
    
    claimed = user['battle_pass_claimed'].split(',') if user['battle_pass_claimed'] else []
    
    for i in range(max(1, current_level - 2), min(101, current_level + 3)):
        if str(i) not in claimed and i <= current_level:
            reward = get_battle_pass_reward(i)
            btn_text = f"🎁 Уровень {i} - {reward:,} ₽"
            markup.add(types.InlineKeyboardButton(
                btn_text, 
                callback_data=f"claim_bp_{i}"
            ))
    
    markup.add(
        types.InlineKeyboardButton("📊 Прогресс БП", callback_data="bp_progress"),
        types.InlineKeyboardButton("🏆 Топ БП", callback_data="bp_leaderboard")
    )
    markup.add(types.InlineKeyboardButton("🔙 Главное меню", callback_data="back_to_menu"))
    
    return markup

# ---------------------------- ОБРАБОТЧИКИ КОМАНД ----------------------------
@bot.message_handler(commands=['start'])
def start(message):
    user_id = message.from_user.id
    user = get_user(user_id, message.from_user.username, message.from_user.first_name)
    
    if user['banned']:
        bot.send_message(message.chat.id, "❌ Вы забанены в боте!")
        return
    
    # Проверяем подписку на канал
    if not check_channel_subscription(user_id):
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton(
            "📢 Подписаться на канал", 
            url=f"https://t.me/{REQUIRED_CHANNEL.replace('@', '')}"
        ))
        markup.add(types.InlineKeyboardButton(
            "✅ Я подписался", 
            callback_data="check_subscription"
        ))
        
        bot.send_message(
            message.chat.id,
            f"❌ <b>Требуется подписка!</b>\n\n"
            f"Для использования бота необходимо подписаться на канал:\n"
            f"{REQUIRED_CHANNEL}\n\n"
            f"После подписки нажмите кнопку проверки.",
            reply_markup=markup
        )
        return
    
    welcome_text = f"""
🌟 <b>Добро пожаловать в BORZOV Squad Bot!</b> 🌟

👤 <b>Профиль:</b> {message.from_user.first_name}
💰 <b>Баланс:</b> {user['coins']:,} ₽
🎯 <b>Боевой пропуск:</b> Уровень {user['battle_pass_level']}
📅 <b>Регистрация:</b> {datetime.fromtimestamp(user['registered_at']).strftime('%d.%m.%Y')}

🎮 <b>Возможности:</b>
• Выполняйте задания и получайте награды
• Прокачивайте боевой пропуск до 100 уровня
• Открывайте кейсы с крупными призами
• Играйте в футбол раз в день
• Соревнуйтесь с другими игроками
• Получите BMW M5 F90 CS за 100 уровень БП!

Используйте кнопки ниже для навигации:
"""
    bot.send_message(message.chat.id, welcome_text, reply_markup=main_menu())

@bot.message_handler(commands=['admin'])
def admin_login(message):
    bot.send_message(message.chat.id, "🔐 Введите пароль администратора:")
    bot.register_next_step_handler(message, check_admin_password)

def check_admin_password(message):
    if message.text == ADMIN_PASSWORD:
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("UPDATE users SET is_admin = 1 WHERE user_id = ?", (message.from_user.id,))
            conn.commit()
        finally:
            conn.close()
        bot.send_message(message.chat.id, "✅ Доступ разрешен!", reply_markup=admin_panel())
    else:
        bot.send_message(message.chat.id, "❌ Неверный пароль!")

@bot.message_handler(commands=['complain'])
def complain_command(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if user['banned']:
        bot.send_message(message.chat.id, "❌ Вы забанены!")
        return
    
    if not check_channel_subscription(user_id):
        bot.send_message(message.chat.id, f"❌ Подпишитесь на канал {REQUIRED_CHANNEL}!")
        return
    
    args = message.text.split(maxsplit=2)
    if len(args) < 3:
        bot.send_message(message.chat.id, "❌ Используйте: /complain @username причина")
        return
    
    target_username = args[1].replace('@', '')
    reason = args[2]
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""INSERT INTO complaints 
                    (user_id, target_username, reason, created_at) 
                    VALUES (?, ?, ?, ?)""",
                  (user_id, target_username, reason, int(time.time())))
        conn.commit()
        bot.send_message(message.chat.id, "✅ Жалоба отправлена на рассмотрение!")
    finally:
        conn.close()

@bot.message_handler(commands=['deputy'])
def deputy_command(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if user['banned']:
        bot.send_message(message.chat.id, "❌ Вы забанены!")
        return
    
    if not check_channel_subscription(user_id):
        bot.send_message(message.chat.id, f"❌ Подпишитесь на канал {REQUIRED_CHANNEL}!")
        return
    
    if user['is_deputy']:
        bot.send_message(message.chat.id, "❌ Вы уже заместитель!")
        return
    
    args = message.text.split(maxsplit=1)
    if len(args) < 2:
        bot.send_message(message.chat.id, "❌ Используйте: /deputy причина")
        return
    
    reason = args[1]
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        # Проверяем, нет ли уже активной заявки
        c.execute("""SELECT id FROM deputy_apps 
                    WHERE user_id = ? AND status = 'pending'""", (user_id,))
        if c.fetchone():
            bot.send_message(message.chat.id, "❌ У вас уже есть активная заявка!")
            return
        
        c.execute("""INSERT INTO deputy_apps 
                    (user_id, reason, created_at) 
                    VALUES (?, ?, ?)""",
                  (user_id, reason, int(time.time())))
        conn.commit()
        bot.send_message(message.chat.id, "✅ Заявка на заместителя отправлена!")
    finally:
        conn.close()

@bot.message_handler(commands=['transfer'])
def transfer_command(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if user['banned']:
        bot.send_message(message.chat.id, "❌ Вы забанены!")
        return
    
    if not check_channel_subscription(user_id):
        bot.send_message(message.chat.id, f"❌ Подпишитесь на канал {REQUIRED_CHANNEL}!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        bot.send_message(message.chat.id, "❌ Используйте: /transfer @username сумма")
        return
    
    target_username = args[1].replace('@', '')
    try:
        amount = int(args[2])
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверная сумма!")
        return
    
    if amount <= 0:
        bot.send_message(message.chat.id, "❌ Сумма должна быть больше 0!")
        return
    
    if user['coins'] < amount:
        bot.send_message(message.chat.id, "❌ Недостаточно монет!")
        return
    
    # Находим получателя по username
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = ?", (target_username,))
        target = c.fetchone()
        if not target:
            bot.send_message(message.chat.id, "❌ Получатель не найден!")
            return
        
        target_id = target[0]
        
        # Выполняем перевод
        c.execute("UPDATE users SET coins = coins - ? WHERE user_id = ?", (amount, user_id))
        c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, target_id))
        
        # Записываем в историю
        c.execute("""INSERT INTO transfers 
                    (from_user, to_user, amount, timestamp) 
                    VALUES (?, ?, ?, ?)""",
                  (user_id, target_id, amount, int(time.time())))
        
        conn.commit()
        
        # Обновляем прогресс заданий
        update_task_progress(user_id, "transfer")
        
        bot.send_message(message.chat.id, f"✅ Переведено {amount:,} ₽ пользователю @{target_username}")
        
        # Уведомляем получателя
        try:
            bot.send_message(target_id, f"💰 Получен перевод {amount:,} ₽ от {message.from_user.first_name}")
        except:
            pass
    finally:
        conn.close()

@bot.message_handler(commands=['promo'])
def promo_command(message):
    user_id = message.from_user.id
    user = get_user(user_id)
    
    if user['banned']:
        bot.send_message(message.chat.id, "❌ Вы забанены!")
        return
    
    if not check_channel_subscription(user_id):
        bot.send_message(message.chat.id, f"❌ Подпишитесь на канал {REQUIRED_CHANNEL}!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        bot.send_message(message.chat.id, "❌ Используйте: /promo КОД")
        return
    
    promo_code = args[1].upper()
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT code, amount, used_by FROM promo_codes 
                    WHERE code = ? AND used_by IS NULL""", (promo_code,))
        promo = c.fetchone()
        
        if not promo:
            bot.send_message(message.chat.id, "❌ Промокод не найден или уже использован!")
            return
        
        code, amount, used_by = promo
        
        # Активируем промокод
        c.execute("UPDATE promo_codes SET used_by = ? WHERE code = ?", (user_id, code))
        c.execute("UPDATE users SET coins = coins + ? WHERE user_id = ?", (amount, user_id))
        conn.commit()
        
        bot.send_message(message.chat.id, f"✅ Промокод активирован! Получено {amount:,} ₽")
        
        # Уведомляем создателя промокода
        c.execute("SELECT created_by FROM promo_codes WHERE code = ?", (code,))
        creator = c.fetchone()
        if creator:
            try:
                bot.send_message(creator[0], f"✅ Ваш промокод {code} активирован пользователем {message.from_user.first_name}")
            except:
                pass
    finally:
        conn.close()

# ---------------------------- CALLBACK ОБРАБОТЧИК ----------------------------
@bot.callback_query_handler(func=lambda call: True)
def callback_handler(call):
    user_id = call.from_user.id
    data = call.data
    
    user = get_user(user_id)
    if user['banned'] and data not in ['help', 'rules', 'check_subscription']:
        bot.answer_callback_query(call.id, "❌ Вы забанены!", show_alert=True)
        return
    
    try:
        if data == "check_subscription":
            if check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, "✅ Подписка подтверждена!", show_alert=True)
                bot.delete_message(call.message.chat.id, call.message.message_id)
                start(call.message)
            else:
                bot.answer_callback_query(call.id, "❌ Вы не подписались на канал!", show_alert=True)
        
        elif data == "balance":
            user = get_user(user_id)
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            text = f"💰 <b>Ваш баланс:</b> {user['coins']:,} ₽"
            bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                                reply_markup=main_menu())
            bot.answer_callback_query(call.id)
        
        elif data == "profile":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            show_profile(call.message.chat.id, user_id, call.message.message_id)
            bot.answer_callback_query(call.id)
        
        elif data == "tasks":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            show_tasks(call)
        
        elif data == "battle_pass":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            show_battle_pass(call)
        
        elif data == "bp_progress":
            show_bp_progress(call)
        
        elif data == "bp_leaderboard":
            show_bp_leaderboard(call)
        
        elif data.startswith("claim_bp_"):
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            level = int(data.split("_")[2])
            success, msg = claim_battle_pass_reward(user_id, level)
            bot.answer_callback_query(call.id, msg, show_alert=True)
            if success:
                show_battle_pass(call)
        
        elif data.startswith("complete_task_"):
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            task_id = int(data.split("_")[2])
            success, msg = complete_task(user_id, task_id)
            bot.answer_callback_query(call.id, msg, show_alert=True)
            if success:
                show_tasks(call)
        
        elif data == "bonus":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            process_bonus(call)
        
        elif data == "daily":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            process_daily(call)
        
        elif data == "football":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            play_football(call)
        
        elif data == "cases":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            show_cases(call)
        
        elif data.startswith("open_case_"):
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            case_id = int(data.split("_")[2])
            open_case_handler(call, case_id)
        
        elif data == "leaderboard":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            show_leaderboard(call)
        
        elif data == "back_to_menu":
            bot.edit_message_text(
                "🌟 <b>Главное меню</b>\n\nВыберите действие:",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu()
            )
            bot.answer_callback_query(call.id)
        
        elif data == "rules":
            show_rules(call)
        
        elif data == "help":
            show_help(call)
        
        elif data.startswith("admin_"):
            if not is_admin_or_deputy(user_id):
                bot.answer_callback_query(call.id, "❌ Нет доступа!", show_alert=True)
                return
            handle_admin_callbacks(call)
        
        elif data == "complain":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                "📝 <b>Отправка жалобы</b>\n\n"
                "Отправьте сообщение в формате:\n"
                "<code>/complain @username причина</code>\n\n"
                "Пример: /complain @user оскорбление",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu()
            )
        
        elif data == "deputy":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                "👔 <b>Заявка на заместителя</b>\n\n"
                "Отправьте заявку командой:\n"
                "<code>/deputy причина</code>\n\n"
                "Опишите почему вы хотите стать заместителем",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu()
            )
        
        elif data == "withdraw":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                f"💸 <b>Вывод средств</b>\n\n"
                f"Для вывода средств свяжитесь с администратором:\n"
                f"@{WITHDRAW_CONTACT}\n\n"
                f"Минимальная сумма вывода: 10,000,000 ₽",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu()
            )
        
        elif data == "achievements":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            show_achievements(call)
        
        elif data == "transfer":
            if not check_channel_subscription(user_id):
                bot.answer_callback_query(call.id, f"❌ Подпишитесь на {REQUIRED_CHANNEL}!", show_alert=True)
                return
            bot.answer_callback_query(call.id)
            bot.edit_message_text(
                "💸 <b>Перевод монет</b>\n\n"
                "Используйте команду:\n"
                "<code>/transfer @username сумма</code>\n\n"
                "Пример: /transfer @user 1000000",
                call.message.chat.id,
                call.message.message_id,
                reply_markup=main_menu()
            )
        
    except Exception as e:
        logger.error(f"Ошибка в callback_handler: {e}")
        bot.answer_callback_query(call.id, "❌ Произошла ошибка!", show_alert=True)

def show_profile(chat_id, user_id, message_id=None):
    user = get_user(user_id)
    rank = get_user_rank(user_id)
    total_users = get_total_users()
    
    status = "👑 Владелец" if user['is_admin'] else ("⭐ Заместитель" if user['is_deputy'] else "👤 Игрок")
    if user['banned']:
        status = "🚫 Забанен"
    
    text = f"""
📊 <b>Профиль игрока</b>

🆔 ID: <code>{user_id}</code>
👤 Имя: {user['first_name']}
📝 Username: @{user['username'] or 'Нет'}
💰 Баланс: {user['coins']:,} ₽
🏆 Место в рейтинге: #{rank} из {total_users}
🎯 Боевой пропуск: Уровень {user['battle_pass_level']} ({user['battle_pass_exp']}/100 XP)
👑 Статус: {status}
📅 Регистрация: {datetime.fromtimestamp(user['registered_at']).strftime('%d.%m.%Y')}
📋 Выполнено заданий: {user['total_tasks_completed']}
✅ Одобрено жалоб: {user['complaints_approved']}/3
"""
    
    markup = main_menu()
    
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=markup)
    else:
        bot.send_message(chat_id, text, reply_markup=markup)

def show_tasks(call):
    user_id = call.from_user.id
    tasks = get_available_tasks(user_id)
    user = get_user(user_id)
    
    if not tasks:
        text = "📋 <b>Нет доступных заданий!</b>\n\n"
        text += "🎉 Вы выполнили все задания!"
        
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    else:
        text = f"📋 <b>ДОСТУПНЫЕ ЗАДАНИЯ</b>\n"
        text += f"📊 Выполнено всего: {user['total_tasks_completed']}\n\n"
        
        markup = types.InlineKeyboardMarkup(row_width=1)
        
        for task_id, desc, reward, req_count, progress in tasks:
            progress_bar = "█" * progress + "░" * (req_count - progress)
            text += f"• {desc}\n"
            text += f"  Прогресс: [{progress_bar}] {progress}/{req_count}\n"
            text += f"  💰 Награда: {reward:,} ₽\n\n"
            
            if progress >= req_count:
                markup.add(types.InlineKeyboardButton(
                    f"✅ Забрать: {reward:,} ₽",
                    callback_data=f"complete_task_{task_id}"
                ))
        
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def show_battle_pass(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    text = f"""
🎯 <b>БОЕВОЙ ПРОПУСК</b>

📊 <b>Текущий уровень:</b> {user['battle_pass_level']}/100
⭐ <b>Опыт:</b> {user['battle_pass_exp']}/{BATTLE_PASS_SETTINGS['exp_per_level']}
📋 <b>Выполнено заданий:</b> {user['total_tasks_completed']}

<b>Награды за уровни:</b>
• 1-10 уровень: 10-20 млн ₽
• 20-90 уровень: 25 млн ₽
• 90-99 уровень: 30 млн ₽
• 100 уровень: {BATTLE_PASS_SETTINGS['top1_reward']}

<b>Доступные награды:</b>
"""
    
    markup = battle_pass_menu(user_id)
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def show_bp_progress(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    progress_bar = "█" * (user['battle_pass_exp'] // 10) + "░" * (10 - user['battle_pass_exp'] // 10)
    
    text = f"""
🎯 <b>ПРОГРЕСС БОЕВОГО ПРОПУСКА</b>

Уровень: {user['battle_pass_level']}/100
Опыт: [{progress_bar}] {user['battle_pass_exp']}/100

📊 <b>Статистика:</b>
• Всего заданий: {user['total_tasks_completed']}
• До следующего уровня: {BATTLE_PASS_SETTINGS['exp_per_level'] - user['battle_pass_exp']} XP

🏆 <b>Топ награда:</b>
100 уровень - {BATTLE_PASS_SETTINGS['top1_reward']}
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 К боевому пропуску", callback_data="battle_pass"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def show_bp_leaderboard(call):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT user_id, username, first_name, battle_pass_level, battle_pass_exp 
                    FROM users 
                    WHERE banned = 0 
                    ORDER BY battle_pass_level DESC, battle_pass_exp DESC 
                    LIMIT 20""")
        players = c.fetchall()
    finally:
        conn.close()
    
    text = "🏆 <b>ТОП ИГРОКОВ ПО БОЕВОМУ ПРОПУСКУ</b>\n\n"
    
    for i, (uid, uname, fname, level, exp) in enumerate(players, 1):
        name = f"@{uname}" if uname else fname or str(uid)
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {name}\n   Уровень {level} ({exp}/100 XP)\n\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 К боевому пропуску", callback_data="battle_pass"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def process_bonus(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    now = int(time.time())
    
    if now - user['last_bonus_time'] >= 86400:
        update_coins(user_id, 2500000)
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("UPDATE users SET last_bonus_time = ? WHERE user_id = ?", (now, user_id))
            conn.commit()
        finally:
            conn.close()
        bot.answer_callback_query(call.id, "🎉 Бонус получен! +2,500,000 ₽", show_alert=True)
    else:
        remaining = 86400 - (now - user['last_bonus_time'])
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        bot.answer_callback_query(call.id, f"⏳ Доступно через {hours}ч {minutes}мин", show_alert=True)
    
    bot.edit_message_text(
        "🎁 <b>Бонусы</b>\n\nИспользуйте меню для навигации",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=main_menu()
    )

def process_daily(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    now = int(time.time())
    
    if now - user['last_daily_time'] >= 86400:
        bonus = 25000000
        update_coins(user_id, bonus)
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("UPDATE users SET last_daily_time = ? WHERE user_id = ?", (now, user_id))
            conn.commit()
        finally:
            conn.close()
        bot.answer_callback_query(call.id, f"🎁 Ежедневная награда: +{bonus:,} ₽", show_alert=True)
    else:
        remaining = 86400 - (now - user['last_daily_time'])
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        bot.answer_callback_query(call.id, f"⏳ Доступно через {hours}ч {minutes}мин", show_alert=True)
    
    bot.edit_message_text(
        "🎫 <b>Ежедневная награда</b>\n\nИспользуйте меню для навигации",
        call.message.chat.id,
        call.message.message_id,
        reply_markup=main_menu()
    )

def play_football(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    now = int(time.time())
    
    if now - user['last_football_time'] < 86400:
        remaining = 86400 - (now - user['last_football_time'])
        hours = remaining // 3600
        minutes = (remaining % 3600) // 60
        bot.answer_callback_query(call.id, f"⏳ Футбол доступен через {hours}ч {minutes}мин", show_alert=True)
        return
    
    bot.edit_message_text(
        "⚽ Вы бьете по мячу... ⚽",
        call.message.chat.id,
        call.message.message_id
    )
    time.sleep(1)
    
    is_goal = random.random() < 0.4
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("UPDATE users SET last_football_time = ? WHERE user_id = ?", (now, user_id))
        conn.commit()
    finally:
        conn.close()
    
    if is_goal:
        reward = 20000000
        update_coins(user_id, reward)
        result_text = f"""
⚽ <b>ГООООЛ!!!</b> ⚽

🎉 Мяч в воротах!
💰 Вы получаете {reward:,} ₽!

Приходите завтра, чтобы сыграть снова!
"""
    else:
        result_text = """
⚽ <b>МИМО!</b> ⚽

😢 Мяч пролетел мимо ворот...
Попробуйте еще раз завтра!
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 В меню", callback_data="back_to_menu"))
    
    bot.edit_message_text(
        result_text,
        call.message.chat.id,
        call.message.message_id,
        reply_markup=markup
    )
    bot.answer_callback_query(call.id)

def show_cases(call):
    get_or_create_cases()
    cases = get_cases()
    
    text = "🎲 <b>ДОСТУПНЫЕ КЕЙСЫ</b>\n\n"
    markup = types.InlineKeyboardMarkup(row_width=1)
    
    for case_id, name, price, min_r, max_r, lose_chance in cases:
        text += f"📦 <b>{name}</b>\n"
        text += f"💰 Цена: {price:,} ₽\n"
        text += f"🎁 Возможная награда: {min_r:,} - {max_r:,} ₽\n"
        text += f"📊 Шанс выигрыша: {100 - lose_chance}%\n\n"
        markup.add(types.InlineKeyboardButton(
            f"🔓 Открыть {name} - {price:,} ₽",
            callback_data=f"open_case_{case_id}"
        ))
    
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def open_case_handler(call, case_id):
    user_id = call.from_user.id
    success, msg = open_case(user_id, case_id)
    bot.answer_callback_query(call.id, msg, show_alert=True)
    if success:
        show_cases(call)
        update_task_progress(user_id, "case")

def show_leaderboard(call):
    players = get_top_players(20)
    
    text = "🏆 <b>ТОП 20 ИГРОКОВ</b>\n\n"
    
    for i, (uid, uname, fname, coins, bp_level) in enumerate(players, 1):
        name = f"@{uname}" if uname else fname or str(uid)
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else f"{i}."
        text += f"{medal} {name}\n"
        text += f"   💰 {coins:,} ₽ | 🎯 Уровень {bp_level}\n\n"
    
    user = get_user(call.from_user.id)
    rank = get_user_rank(call.from_user.id)
    text += f"\n<b>Ваше место:</b> #{rank}\n"
    text += f"<b>Ваш баланс:</b> {user['coins']:,} ₽"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def show_rules(call):
    text = f"""
📜 <b>ПРАВИЛА БОТА</b>

1. Обязательная подписка на {REQUIRED_CHANNEL}
2. Запрещено использование ботов/скриптов
3. Запрещены оскорбления и спам
4. Запрещена передача аккаунтов
5. Запрещено мошенничество

<b>Система наказаний:</b>
• 1 нарушение - предупреждение
• 2 нарушение - бан на 1 день
• 3 нарушение - перманентный бан

<b>Боевой пропуск:</b>
• За каждое задание +20 опыта
• 100 опыта = новый уровень
• Максимум 100 уровней
• 100 уровень - BMW M5 F90 CS!

<b>Футбол:</b>
• Доступен раз в день
• Шанс забить гол - 40%
• Награда за гол - 20,000,000 ₽
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def show_help(call):
    text = f"""
❓ <b>ПОМОЩЬ ПО БОТУ</b>

<b>Основные команды:</b>
/start - главное меню
/admin - вход в админ-панель
/complain @user причина - отправить жалобу
/deputy причина - заявка на зама
/transfer @user сумма - перевод монет
/promo КОД - активировать промокод

<b>Как играть:</b>
1. Подпишитесь на {REQUIRED_CHANNEL}
2. Выполняйте задания
3. Получайте монеты
4. Открывайте кейсы
5. Играйте в футбол раз в день
6. Прокачивайте боевой пропуск

<b>Награды:</b>
• Ежедневная - 25,000,000 ₽
• Задания - до 100,000,000 ₽
• Футбол - 20,000,000 ₽ за гол

По вопросам: @{OWNER_USERNAME}
"""
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def show_achievements(call):
    user_id = call.from_user.id
    user = get_user(user_id)
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT achievement_name FROM achievements 
                    WHERE user_id = ? ORDER BY achieved_at DESC""", (user_id,))
        achievements = [row[0] for row in c.fetchall()]
    finally:
        conn.close()
    
    text = "🏅 <b>ВАШИ ДОСТИЖЕНИЯ</b>\n\n"
    if achievements:
        text += "\n".join(achievements)
    else:
        text += "У вас пока нет достижений. Продолжайте играть!"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="back_to_menu"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

# ---------------------------- АДМИН ФУНКЦИИ ----------------------------
def handle_admin_callbacks(call):
    data = call.data
    user_id = call.from_user.id
    
    if data == "admin_complaints":
        show_admin_complaints(call)
    elif data == "admin_deputies":
        show_admin_deputies(call)
    elif data == "admin_users":
        show_admin_users(call)
    elif data == "admin_stats":
        show_admin_stats(call)
    elif data == "admin_issue":
        show_admin_issue(call)
    elif data == "admin_create_promo":
        show_create_promo(call)
    elif data == "admin_promos":
        show_admin_promos(call)
    elif data == "admin_ban":
        show_admin_ban(call)
    elif data == "admin_unban":
        show_admin_unban(call)
    elif data == "admin_exit":
        bot.edit_message_text(
            "✅ Вы вышли из админ-панели",
            call.message.chat.id,
            call.message.message_id,
            reply_markup=main_menu()
        )
        bot.answer_callback_query(call.id)
    elif data.startswith("approve_complaint_"):
        complaint_id = int(data.split("_")[2])
        approve_complaint(call, complaint_id)
    elif data.startswith("reject_complaint_"):
        complaint_id = int(data.split("_")[2])
        reject_complaint(call, complaint_id)
    elif data.startswith("approve_deputy_"):
        app_id = int(data.split("_")[2])
        approve_deputy(call, app_id)
    elif data.startswith("reject_deputy_"):
        app_id = int(data.split("_")[2])
        reject_deputy(call, app_id)
    else:
        bot.answer_callback_query(call.id, "⏳ В разработке", show_alert=True)

def show_admin_complaints(call):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT id, user_id, target_username, reason, created_at 
                    FROM complaints 
                    WHERE status = 'pending' 
                    ORDER BY created_at DESC LIMIT 10""")
        complaints = c.fetchall()
    finally:
        conn.close()
    
    if not complaints:
        text = "📋 <b>Нет активных жалоб</b>"
        markup = admin_panel()
    else:
        text = "📋 <b>АКТИВНЫЕ ЖАЛОБЫ</b>\n\n"
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        for comp_id, uid, target, reason, created in complaints:
            text += f"🆔 #{comp_id} | От: {uid}\n"
            text += f"👤 Нарушитель: @{target}\n"
            text += f"📝 Причина: {reason[:50]}...\n"
            text += f"📅 {datetime.fromtimestamp(created).strftime('%d.%m.%Y')}\n\n"
            
            markup.add(
                types.InlineKeyboardButton(f"✅ Одобрить #{comp_id}", callback_data=f"approve_complaint_{comp_id}"),
                types.InlineKeyboardButton(f"❌ Отклонить #{comp_id}", callback_data=f"reject_complaint_{comp_id}")
            )
        
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_exit"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def approve_complaint(call, complaint_id):
    admin_id = call.from_user.id
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id, target_username FROM complaints WHERE id = ?", (complaint_id,))
        complaint = c.fetchone()
        if not complaint:
            bot.answer_callback_query(call.id, "Жалоба не найдена!", show_alert=True)
            return
        
        reporter_id, target_username = complaint
        
        # Обновляем статус жалобы
        c.execute("""UPDATE complaints 
                    SET status = 'approved', resolved_at = ?, resolved_by = ? 
                    WHERE id = ?""",
                  (int(time.time()), admin_id, complaint_id))
        
        # Увеличиваем счетчик одобренных жалоб
        c.execute("""UPDATE users 
                    SET complaints_approved = complaints_approved + 1 
                    WHERE user_id = ?""", (reporter_id,))
        
        # Баним нарушителя
        c.execute("SELECT user_id FROM users WHERE username = ?", (target_username,))
        target = c.fetchone()
        if target:
            c.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (target[0],))
            try:
                bot.send_message(target[0], "🚫 Вы были забанены по жалобе!")
            except:
                pass
        
        conn.commit()
        
        # Уведомляем игрока
        try:
            bot.send_message(reporter_id, f"✅ Ваша жалоба #{complaint_id} была одобрена!")
        except:
            pass
        
        bot.answer_callback_query(call.id, "✅ Жалоба одобрена!", show_alert=True)
        show_admin_complaints(call)
    finally:
        conn.close()

def reject_complaint(call, complaint_id):
    admin_id = call.from_user.id
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""UPDATE complaints 
                    SET status = 'rejected', resolved_at = ?, resolved_by = ? 
                    WHERE id = ?""",
                  (int(time.time()), admin_id, complaint_id))
        conn.commit()
        
        bot.answer_callback_query(call.id, "❌ Жалоба отклонена!", show_alert=True)
        show_admin_complaints(call)
    finally:
        conn.close()

def show_admin_deputies(call):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT id, user_id, reason, created_at 
                    FROM deputy_apps 
                    WHERE status = 'pending' 
                    ORDER BY created_at DESC LIMIT 10""")
        apps = c.fetchall()
    finally:
        conn.close()
    
    if not apps:
        text = "👔 <b>Нет активных заявок на зама</b>"
        markup = admin_panel()
    else:
        text = "👔 <b>ЗАЯВКИ НА ЗАМЕСТИТЕЛЯ</b>\n\n"
        markup = types.InlineKeyboardMarkup(row_width=2)
        
        for app_id, uid, reason, created in apps:
            text += f"🆔 #{app_id} | ID: {uid}\n"
            text += f"📝 Причина: {reason[:100]}...\n"
            text += f"📅 {datetime.fromtimestamp(created).strftime('%d.%m.%Y')}\n\n"
            
            markup.add(
                types.InlineKeyboardButton(f"✅ Одобрить #{app_id}", callback_data=f"approve_deputy_{app_id}"),
                types.InlineKeyboardButton(f"❌ Отклонить #{app_id}", callback_data=f"reject_deputy_{app_id}")
            )
        
        markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_exit"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def approve_deputy(call, app_id):
    admin_id = call.from_user.id
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT user_id FROM deputy_apps WHERE id = ?", (app_id,))
        app = c.fetchone()
        if not app:
            bot.answer_callback_query(call.id, "Заявка не найдена!", show_alert=True)
            return
        
        applicant_id = app[0]
        
        # Делаем пользователя заместителем
        c.execute("UPDATE users SET is_deputy = 1, deputy_approved = 1 WHERE user_id = ?", (applicant_id,))
        
        # Обновляем статус заявки
        c.execute("""UPDATE deputy_apps 
                    SET status = 'approved', resolved_at = ?, resolved_by = ? 
                    WHERE id = ?""",
                  (int(time.time()), admin_id, app_id))
        
        # Добавляем достижение
        c.execute("""INSERT OR IGNORE INTO achievements 
                    (user_id, achievement_name, achieved_at) 
                    VALUES (?, ?, ?)""",
                  (applicant_id, "⭐ Заместитель", int(time.time())))
        
        conn.commit()
        
        # Уведомляем игрока
        try:
            bot.send_message(applicant_id, "🎉 Поздравляем! Ваша заявка на заместителя одобрена!")
        except:
            pass
        
        bot.answer_callback_query(call.id, "✅ Заявка одобрена!", show_alert=True)
        show_admin_deputies(call)
    finally:
        conn.close()

def reject_deputy(call, app_id):
    admin_id = call.from_user.id
    
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""UPDATE deputy_apps 
                    SET status = 'rejected', resolved_at = ?, resolved_by = ? 
                    WHERE id = ?""",
                  (int(time.time()), admin_id, app_id))
        conn.commit()
        
        bot.answer_callback_query(call.id, "❌ Заявка отклонена!", show_alert=True)
        show_admin_deputies(call)
    finally:
        conn.close()

def show_admin_users(call):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT user_id, username, first_name, coins, is_admin, is_deputy, banned, battle_pass_level 
                    FROM users ORDER BY coins DESC LIMIT 20""")
        users = c.fetchall()
    finally:
        conn.close()
    
    text = "👥 <b>ТОП 20 ИГРОКОВ</b>\n\n"
    for uid, uname, fname, coins, is_adm, is_dep, banned, bp_level in users:
        name = f"@{uname}" if uname else fname or str(uid)
        status = "🚫" if banned else ("👑" if is_adm else ("⭐" if is_dep else "👤"))
        text += f"{status} {name}\n"
        text += f"💰 {coins:,} ₽ | 🎯 Уровень {bp_level}\n\n"
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, 
                        reply_markup=admin_panel())
    bot.answer_callback_query(call.id)

def show_admin_stats(call):
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM users")
        total_users = c.fetchone()[0]
        c.execute("SELECT SUM(coins) FROM users")
        total_coins = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM users WHERE banned = 1")
        banned_users = c.fetchone()[0]
        c.execute("SELECT AVG(battle_pass_level) FROM users")
        avg_bp = c.fetchone()[0] or 0
        c.execute("SELECT COUNT(*) FROM users WHERE is_deputy = 1")
        total_deputies = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM promo_codes WHERE used_by IS NULL")
        active_promos = c.fetchone()[0]
    finally:
        conn.close()
    
    text = f"""
📊 <b>СТАТИСТИКА БОТА</b>

👥 Всего пользователей: {total_users}
💰 Всего монет: {total_coins:,}
🚫 Забанено: {banned_users}
⭐ Заместителей: {total_deputies}
🎯 Средний уровень БП: {avg_bp:.1f}
🎫 Активных промокодов: {active_promos}
"""
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id,
                        reply_markup=admin_panel())
    bot.answer_callback_query(call.id)

def show_admin_issue(call):
    """Показать форму выдачи валюты"""
    text = """
💰 <b>ВЫДАЧА ВАЛЮТЫ</b>

Отправьте сообщение в формате:
<code>ID_пользователя сумма</code>

Пример: <code>123456789 1000000</code>
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_exit"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)
    
    bot.register_next_step_handler(call.message, process_issue_coins)

def process_issue_coins(message):
    """Обработка выдачи монет"""
    try:
        parts = message.text.split()
        if len(parts) != 2:
            bot.send_message(message.chat.id, "❌ Неверный формат! Используйте: ID сумма")
            return
        
        target_id = int(parts[0])
        amount = int(parts[1])
        
        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Сумма должна быть больше 0!")
            return
        
        update_coins(target_id, amount)
        
        bot.send_message(message.chat.id, f"✅ Выдано {amount:,} ₽ пользователю {target_id}", reply_markup=admin_panel())
        
        # Уведомляем получателя
        try:
            bot.send_message(target_id, f"💰 Администратор выдал вам {amount:,} ₽")
        except:
            pass
            
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный формат числа!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def show_create_promo(call):
    """Показать форму создания промокода"""
    text = """
🎫 <b>СОЗДАНИЕ ПРОМОКОДА</b>

Отправьте сообщение в формате:
<code>сумма</code>

Будет создан уникальный промокод на указанную сумму.
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_exit"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)
    
    bot.register_next_step_handler(call.message, process_create_promo, call.from_user.id)

def process_create_promo(message, admin_id):
    """Создание промокода"""
    try:
        amount = int(message.text)
        
        if amount <= 0:
            bot.send_message(message.chat.id, "❌ Сумма должна быть больше 0!")
            return
        
        # Генерируем уникальный код
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("""INSERT INTO promo_codes (code, amount, created_by, created_at) 
                        VALUES (?, ?, ?, ?)""",
                      (code, amount, admin_id, int(time.time())))
            conn.commit()
        finally:
            conn.close()
        
        text = f"""
✅ <b>ПРОМОКОД СОЗДАН</b>

🎫 Код: <code>{code}</code>
💰 Сумма: {amount:,} ₽

Игроки могут активировать командой:
<code>/promo {code}</code>
"""
        bot.send_message(message.chat.id, text, reply_markup=admin_panel())
        
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверная сумма!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def show_admin_promos(call):
    """Показать список промокодов"""
    conn = get_db_connection()
    try:
        c = conn.cursor()
        c.execute("""SELECT code, amount, created_by, used_by, created_at 
                    FROM promo_codes 
                    ORDER BY created_at DESC LIMIT 20""")
        promos = c.fetchall()
    finally:
        conn.close()
    
    if not promos:
        text = "🎫 <b>Нет созданных промокодов</b>"
    else:
        text = "🎫 <b>ПОСЛЕДНИЕ ПРОМОКОДЫ</b>\n\n"
        for code, amount, creator, used_by, created in promos:
            status = "✅ Использован" if used_by else "🆕 Доступен"
            text += f"📝 Код: <code>{code}</code>\n"
            text += f"💰 Сумма: {amount:,} ₽\n"
            text += f"📊 Статус: {status}\n"
            text += f"📅 Создан: {datetime.fromtimestamp(created).strftime('%d.%m.%Y %H:%M')}\n\n"
    
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_exit"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def show_admin_ban(call):
    """Показать форму бана"""
    text = """
🚫 <b>БАН ПОЛЬЗОВАТЕЛЯ</b>

Отправьте ID пользователя для бана:
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_exit"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)
    
    bot.register_next_step_handler(call.message, process_ban_user)

def process_ban_user(message):
    """Бан пользователя"""
    try:
        target_id = int(message.text)
        
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("UPDATE users SET banned = 1 WHERE user_id = ?", (target_id,))
            
            if c.rowcount == 0:
                bot.send_message(message.chat.id, "❌ Пользователь не найден!")
                return
                
            conn.commit()
        finally:
            conn.close()
        
        bot.send_message(message.chat.id, f"✅ Пользователь {target_id} забанен", reply_markup=admin_panel())
        
        # Уведомляем пользователя
        try:
            bot.send_message(target_id, "🚫 Вы были забанены в боте!")
        except:
            pass
            
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный ID!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

def show_admin_unban(call):
    """Показать форму разбана"""
    text = """
✅ <b>РАЗБАН ПОЛЬЗОВАТЕЛЯ</b>

Отправьте ID пользователя для разбана:
"""
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🔙 Назад", callback_data="admin_exit"))
    
    bot.edit_message_text(text, call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)
    
    bot.register_next_step_handler(call.message, process_unban_user)

def process_unban_user(message):
    """Разбан пользователя"""
    try:
        target_id = int(message.text)
        
        conn = get_db_connection()
        try:
            c = conn.cursor()
            c.execute("UPDATE users SET banned = 0 WHERE user_id = ?", (target_id,))
            
            if c.rowcount == 0:
                bot.send_message(message.chat.id, "❌ Пользователь не найден!")
                return
                
            conn.commit()
        finally:
            conn.close()
        
        bot.send_message(message.chat.id, f"✅ Пользователь {target_id} разбанен", reply_markup=admin_panel())
        
        # Уведомляем пользователя
        try:
            bot.send_message(target_id, "✅ Вы были разбанены в боте!")
        except:
            pass
            
    except ValueError:
        bot.send_message(message.chat.id, "❌ Неверный ID!")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

# ---------------------------- ЗАПУСК БОТА ----------------------------
def setup_bot():
    """Настройка бота перед запуском"""
    logger.info("🔧 Настройка бота...")
    
    # Получаем ID канала
    get_channel_id()
    
    # Инициализируем постоянные задания
    init_permanent_tasks()
    
    # Создаем кейсы
    get_or_create_cases()
    
    logger.info("✅ Настройка завершена")

def check_bot_health():
    """Проверка здоровья бота"""
    while True:
        try:
            conn = get_db_connection()
            conn.execute("SELECT 1")
            conn.close()
            bot.get_me()
            logger.debug("✅ Бот работает нормально")
        except Exception as e:
            logger.error(f"❌ Ошибка проверки здоровья: {e}")
        
        time.sleep(60)

if __name__ == "__main__":
    logger.info("🚀 Запуск BORZOV Squad Bot...")
    
    setup_bot()
    
    health_thread = threading.Thread(target=check_bot_health, daemon=True)
    health_thread.start()
    
    while True:
        try:
            logger.info("🔄 Запуск polling...")
            bot.polling(none_stop=True, interval=0, timeout=20)
        except Exception as e:
            logger.error(f"❌ Критическая ошибка: {e}")
            time.sleep(5)