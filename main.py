import os
import logging
import asyncio
import re
from datetime import datetime
from dotenv import load_dotenv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from database import Database, Driver, Queue
from sqlalchemy import select, delete, update

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Load environment variables
load_dotenv()
TOKEN = os.getenv('TELEGRAM_TOKEN')
ADMIN_PASSWORD = os.getenv('ADMIN_PASSWORD')
GROUP_ID = os.getenv('GROUP_ID')  # ID группы, где будут публиковаться заказы

# Initialize database
db = Database()

# Command handlers
async def get_main_menu(user_id: int):
    """Get main menu keyboard based on user state"""
    is_registered = await db.is_driver_registered(user_id)
    is_in_queue = await db.is_driver_in_queue(user_id)
    
    keyboard = []
    
    if not is_registered:
        keyboard.append([InlineKeyboardButton("📝 Регистрация", callback_data="register")])
    else:
        if not is_in_queue:
            keyboard.append([InlineKeyboardButton("👉 Встать в очередь", callback_data="join_queue")])
        else:
            keyboard.append([InlineKeyboardButton("🔁 Отбиться", callback_data="leave_queue")])
        keyboard.append([InlineKeyboardButton("👤 Мой профиль", callback_data="profile")])
    
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start command handler"""
    logger.info(f"Start command received from user {update.effective_user.id}")
    reply_markup = await get_main_menu(update.effective_user.id)
    await update.message.reply_text(
        "Добро пожаловать в систему распределения заказов такси!\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Help command handler"""
    logger.info(f"Help command received from user {update.effective_user.id}")
    help_text = (
        "📱 Доступные команды:\n\n"
        "/start - Начать работу с ботом\n"
        "/help - Показать это сообщение\n"
        "/admin [пароль] - Панель администратора\n\n"
        "🚖 Для водителей:\n"
        "1. Сначала пройдите регистрацию\n"
        "2. Встаньте в очередь, когда готовы принимать заказы\n"
        "3. Нажмите «Отбиться» после выполнения заказа\n\n"
        "❓ По всем вопросам обращайтесь к администратору"
    )
    await update.message.reply_text(help_text)

async def admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Admin command handler"""
    logger.info(f"Admin command received from user {update.effective_user.id}")
    
    if not context.args:
        await update.message.reply_text("❌ Пожалуйста, укажите пароль администратора")
        return
        
    if context.args[0] != ADMIN_PASSWORD:
        logger.warning(f"Invalid admin password attempt from user {update.effective_user.id}")
        await update.message.reply_text("❌ Неверный пароль администратора")
        return

    keyboard = [
        [InlineKeyboardButton("📋 Список водителей", callback_data="admin_drivers_list")],
        [InlineKeyboardButton("👥 Текущая очередь", callback_data="admin_queue_list")],
        [InlineKeyboardButton("🔄 Сбросить очередь", callback_data="admin_reset_queue")],
        [InlineKeyboardButton("❌ Удалить водителя", callback_data="admin_delete_driver")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "🔐 Панель администратора\n"
        "Выберите действие:",
        reply_markup=reply_markup
    )

async def register_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Start registration process"""
    query = update.callback_query
    user_id = query.from_user.id
    
    # Check if already registered
    if await db.is_driver_registered(user_id):
        await query.answer("Вы уже зарегистрированы!")
        await update_menu_message(query.message, user_id)
        return
    
    context.user_data['registration_step'] = 'name'
    await query.message.reply_text(
        "Начинаем регистрацию. Пожалуйста, введите ваше имя:"
    )

async def handle_registration_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle registration process inputs"""
    if not context.user_data.get('registration_step'):
        # If no registration in progress, ignore the message
        return
        
    step = context.user_data.get('registration_step')
    
    if step == 'name':
        context.user_data['driver_name'] = update.message.text
        context.user_data['registration_step'] = 'car_model'
        await update.message.reply_text("Введите марку и модель автомобиля:")
    
    elif step == 'car_model':
        context.user_data['car_model'] = update.message.text
        context.user_data['registration_step'] = 'car_number'
        await update.message.reply_text("Введите государственный номер автомобиля:")
    
    elif step == 'car_number':
        # Save driver to database
        driver_data = {
            'telegram_id': update.message.from_user.id,
            'name': context.user_data['driver_name'],
            'car_model': context.user_data['car_model'],
            'car_number': update.message.text,
            'status': 'inactive'
        }
        await db.add_driver(driver_data)
        
        # Clear registration data
        context.user_data.clear()
        
        # Send success message with updated menu
        reply_markup = await get_main_menu(update.message.from_user.id)
        await update.message.reply_text(
            "✅ Регистрация успешно завершена!\n"
            "Теперь вы можете встать в очередь на получение заказов.",
            reply_markup=reply_markup
        )

async def join_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Add driver to the queue"""
    query = update.callback_query
    driver_id = query.from_user.id
    
    try:
        if not await db.is_driver_registered(driver_id):
            await query.answer(
                "❌ Вы не зарегистрированы. Пожалуйста, сначала пройдите регистрацию.",
                show_alert=True
            )
            return

        if await db.is_driver_in_queue(driver_id):
            position = await db.get_queue_position(driver_id)
            await query.answer(
                f"❗ Вы уже находитесь в очереди (позиция: {position})",
                show_alert=True
            )
            return

        if await db.add_to_queue(driver_id):
            position = await db.get_queue_position(driver_id)
            await query.answer(
                f"✅ Вы добавлены в очередь! Ваша позиция: {position}",
                show_alert=True
            )
            await update_menu_message(query.message, driver_id)
        else:
            await query.answer(
                "❌ Произошла ошибка при добавлении в очередь",
                show_alert=True
            )
    except Exception as e:
        logger.error(f"Error in join_queue: {e}")
        await query.answer(
            "❌ Произошла ошибка. Попробуйте позже",
            show_alert=True
        )

async def leave_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Remove driver from the queue"""
    query = update.callback_query
    driver_id = query.from_user.id
    
    try:
        if not await db.is_driver_in_queue(driver_id):
            await query.answer(
                "❗ Вы не находитесь в очереди",
                show_alert=True
            )
            return

        if await db.remove_from_queue(driver_id):
            await query.answer(
                "✅ Вы вышли из очереди",
                show_alert=True
            )
            await update_menu_message(query.message, driver_id)
        else:
            await query.answer(
                "❌ Произошла ошибка при выходе из очереди",
                show_alert=True
            )
    except Exception as e:
        logger.error(f"Error in leave_queue: {e}")
        await query.answer(
            "❌ Произошла ошибка. Попробуйте позже",
            show_alert=True
        )

async def show_profile(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show driver's profile"""
    query = update.callback_query
    driver_id = query.from_user.id
    
    try:
        driver = await db.get_driver(driver_id)
        if not driver:
            await query.message.reply_text(
                "❌ Профиль не найден. Пожалуйста, пройдите регистрацию."
            )
            return

        is_in_queue = await db.is_driver_in_queue(driver_id)
        queue_position = await db.get_queue_position(driver_id) if is_in_queue else None
        
        status = f"✅ В очереди (позиция: {queue_position})" if is_in_queue else "❌ Не в очереди"
        profile_text = (
            f"👤 Профиль водителя:\n\n"
            f"Имя: {driver.name}\n"
            f"Марка авто: {driver.car_model}\n"
            f"Госномер: {driver.car_number}\n"
            f"Статус: {status}"
        )
        await query.message.reply_text(profile_text)
    except Exception as e:
        logger.error(f"Error in show_profile: {e}")
        await query.message.reply_text(
            "❌ Произошла ошибка при получении профиля"
        )

# Admin handlers
async def admin_drivers_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show list of all registered drivers"""
    async with db.async_session() as session:
        result = await session.execute(select(Driver))
        drivers = result.scalars().all()
        
        if not drivers:
            await update.callback_query.message.reply_text("📋 Список водителей пуст")
            return
            
        drivers_text = "📋 Список зарегистрированных водителей:\n\n"
        for driver in drivers:
            status = "✅ В очереди" if driver.status == "active" else "❌ Не в очереди"
            drivers_text += (
                f"ID: {driver.telegram_id}\n"
                f"Имя: {driver.name}\n"
                f"Авто: {driver.car_model}\n"
                f"Номер: {driver.car_number}\n"
                f"Статус: {status}\n"
                f"Дата регистрации: {driver.registration_date.strftime('%d.%m.%Y %H:%M')}\n"
                f"{'='*30}\n"
            )
        await update.callback_query.message.reply_text(drivers_text)

async def admin_queue_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current queue"""
    async with db.async_session() as session:
        result = await session.execute(
            select(Queue).order_by(Queue.position)
        )
        queue_entries = result.scalars().all()
        
        if not queue_entries:
            await update.callback_query.message.reply_text("👥 Очередь пуста")
            return
            
        queue_text = "👥 Текущая очередь:\n\n"
        for entry in queue_entries:
            driver = await db.get_driver(entry.driver.telegram_id)
            queue_text += (
                f"{entry.position}. {driver.name}\n"
                f"   Авто: {driver.car_model}\n"
                f"   Номер: {driver.car_number}\n"
                f"   Время в очереди: {(datetime.utcnow() - entry.join_time).seconds // 60} мин.\n"
                f"{'='*30}\n"
            )
        await update.callback_query.message.reply_text(queue_text)

async def admin_reset_queue(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Reset the queue"""
    async with db.async_session() as session:
        await session.execute(delete(Queue))
        await session.execute(
            update(Driver).values(status='inactive')
        )
        await session.commit()
    await update.callback_query.message.reply_text("✅ Очередь успешно сброшена")

async def admin_delete_driver(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Delete a driver"""
    context.user_data['admin_action'] = 'delete_driver'
    await update.callback_query.message.reply_text(
        "Введите ID водителя, которого нужно удалить:"
    )

async def handle_admin_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle admin input for various actions"""
    action = context.user_data.get('admin_action')
    
    if action == 'delete_driver':
        try:
            driver_id = int(update.message.text)
            async with db.async_session() as session:
                # Remove from queue first
                await db.remove_from_queue(driver_id)
                
                # Delete driver
                driver = await db.get_driver(driver_id)
                if driver:
                    await session.delete(driver)
                    await session.commit()
                    await update.message.reply_text("✅ Водитель успешно удален")
                else:
                    await update.message.reply_text("❌ Водитель не найден")
        except ValueError:
            await update.message.reply_text("❌ Неверный формат ID")
        finally:
            context.user_data.clear()

# Order handling
async def handle_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle new order messages in the group"""
    # Log incoming message
    logger.info(f"Received message in chat {update.message.chat.id}: {update.message.text}")
    
    try:
        group_id = int(GROUP_ID) if GROUP_ID else None
    except ValueError:
        logger.error(f"Invalid GROUP_ID format: {GROUP_ID}")
        return
        
    if not group_id or update.message.chat.id != group_id:
        logger.info(f"Message from wrong chat. Expected {group_id}, got {update.message.chat.id}")
        return

    # Check if message contains order keywords
    order_keywords = ['заказ', 'поездка', 'нужно', 'такси']
    message_text = update.message.text.lower()
    
    if any(keyword in message_text for keyword in order_keywords):
        logger.info("Order keywords found in message")
        
        # Get first driver in queue
        driver = await db.get_first_in_queue()
        
        if not driver:
            logger.info("No available drivers in queue")
            await update.message.reply_text(
                "❌ К сожалению, сейчас нет свободных водителей"
            )
            return

        # Send confirmation to group
        await update.message.reply_text("✅ Поехали!")
        logger.info(f"Order confirmation sent to group")

        # Create inline keyboard for driver
        keyboard = [
            [InlineKeyboardButton("🚗 Принять заказ", callback_data=f"accept_order_{update.message.message_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        # Store order info in context before sending message
        order_key = f'order_{update.message.message_id}'
        if not hasattr(context, 'bot_data'):
            context.bot_data = {}
        context.bot_data[order_key] = {
            'driver_id': driver.telegram_id,
            'chat_id': update.message.chat.id,
            'text': update.message.text,
            'original_message_id': update.message.message_id,
            'status': 'pending'
        }
        logger.info(f"Order data stored in context: {context.bot_data[order_key]}")

        try:
            # Send order to driver
            sent_message = await context.bot.send_message(
                chat_id=driver.telegram_id,
                text=(
                    "🚨 Есть заказ!\n\n"
                    f"Текст заказа:\n{update.message.text}\n\n"
                    "У вас есть 30 секунд, чтобы принять заказ!"
                ),
                reply_markup=reply_markup
            )
            logger.info(f"Order sent to driver {driver.telegram_id}")
            
            # Update order info with sent message id
            context.bot_data[order_key]['message_id'] = sent_message.message_id
            
            # Set timer for order expiration
            asyncio.create_task(
                handle_order_timeout(
                    context,
                    update.message.message_id,
                    driver.telegram_id,
                    sent_message.message_id
                )
            )
            logger.info(f"Order timeout task created for order {update.message.message_id}")
            
        except Exception as e:
            logger.error(f"Error sending order to driver: {e}")
            del context.bot_data[order_key]  # Clean up on error
            await update.message.reply_text(
                "❌ Произошла ошибка при отправке заказа водителю"
            )
    else:
        logger.debug(f"No order keywords found in message: {message_text}")

async def handle_order_timeout(context: ContextTypes.DEFAULT_TYPE, order_id: int, driver_id: int, message_id: int):
    """Handle order timeout after 30 seconds"""
    logger.info(f"Starting timeout handler for order {order_id}")
    await asyncio.sleep(30)
    
    # Check if order still exists and wasn't accepted
    order_data = context.bot_data.get(f'order_{order_id}')
    if order_data and order_data['driver_id'] == driver_id:
        logger.info(f"Order {order_id} timed out for driver {driver_id}")
        # Remove order data
        del context.bot_data[f'order_{order_id}']
        
        try:
            # Edit message to driver
            await context.bot.edit_message_text(
                chat_id=driver_id,
                message_id=message_id,
                text="⏰ Время на принятие заказа истекло"
            )
            
            # Send message to group
            await context.bot.send_message(
                chat_id=order_data['chat_id'],
                reply_to_message_id=order_data['original_message_id'],
                text="⏰ Водитель не успел принять заказ, ищем следующего..."
            )
            
            # Pass order to next driver
            driver = await db.get_first_in_queue()
            if driver:
                logger.info(f"Passing order to next driver {driver.telegram_id}")
                keyboard = [
                    [InlineKeyboardButton("🚗 Принять заказ", callback_data=f"accept_order_{order_id}")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                
                sent_message = await context.bot.send_message(
                    chat_id=driver.telegram_id,
                    text=(
                        "🚨 Есть заказ!\n\n"
                        f"Текст заказа:\n{order_data['text']}\n\n"
                        "У вас есть 30 секунд, чтобы принять заказ!"
                    ),
                    reply_markup=reply_markup
                )
                
                # Update order info in context
                context.bot_data[f'order_{order_id}'] = {
                    'driver_id': driver.telegram_id,
                    'message_id': sent_message.message_id,
                    'original_message_id': order_data['original_message_id'],
                    'chat_id': order_data['chat_id'],
                    'text': order_data['text']
                }
                
                # Set new timer
                asyncio.create_task(
                    handle_order_timeout(
                        context,
                        order_id,
                        driver.telegram_id,
                        sent_message.message_id
                    )
                )
            else:
                logger.info("No more drivers available in queue")
                await context.bot.send_message(
                    chat_id=order_data['chat_id'],
                    reply_to_message_id=order_data['original_message_id'],
                    text="❌ К сожалению, свободных водителей больше нет"
                )
                
        except Exception as e:
            logger.error(f"Error handling order timeout: {e}")
    else:
        logger.info(f"Order {order_id} was already accepted or cancelled")

async def accept_order(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle order acceptance by driver"""
    query = update.callback_query
    order_id = int(query.data.split('_')[-1])
    logger.info(f"Driver {query.from_user.id} attempting to accept order {order_id}")
    
    # Check if order exists in bot_data
    order_key = f'order_{order_id}'
    order_data = context.bot_data.get(order_key)
    
    logger.info(f"Order data from context: {order_data}")
    
    if not order_data or order_data.get('status') != 'pending':
        logger.warning(f"Order {order_id} not found or not pending. Data: {order_data}")
        await query.answer("❌ Этот заказ уже не актуален", show_alert=True)
        return
        
    if order_data['driver_id'] != query.from_user.id:
        logger.warning(f"Wrong driver trying to accept order. Expected {order_data['driver_id']}, got {query.from_user.id}")
        await query.answer("❌ Этот заказ предназначен другому водителю", show_alert=True)
        return
    
    try:
        # Get driver info
        driver = await db.get_driver(query.from_user.id)
        if not driver:
            logger.error(f"Driver {query.from_user.id} not found in database")
            await query.answer("❌ Ошибка: водитель не найден", show_alert=True)
            return
        
        # Remove from queue and update status
        if not await db.remove_from_queue(query.from_user.id):
            logger.error(f"Failed to remove driver {query.from_user.id} from queue")
            await query.answer("❌ Ошибка: не удалось обновить очередь", show_alert=True)
            return
        
        # Mark order as accepted
        order_data['status'] = 'accepted'
        
        # Edit message to driver
        await query.edit_message_text(
            f"✅ Вы приняли заказ!\n\n"
            f"Текст заказа:\n{order_data['text']}\n\n"
            "Не забудьте нажать «Отбиться» после выполнения заказа!"
        )
        
        # Send confirmation to group
        await context.bot.send_message(
            chat_id=order_data['chat_id'],
            reply_to_message_id=order_data['original_message_id'],
            text=f"✅ Забирает {driver.car_model} с госномером {driver.car_number}"
        )
        
        logger.info(f"Order {order_id} successfully accepted by driver {driver.telegram_id}")
        
    except Exception as e:
        logger.error(f"Error accepting order: {e}")
        await query.answer("❌ Произошла ошибка при принятии заказа", show_alert=True)
    finally:
        # Clean up order data after processing
        if order_data['status'] == 'accepted':
            del context.bot_data[order_key]

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Log Errors caused by Updates."""
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if update and update.effective_message:
            await update.effective_message.reply_text(
                "❌ Произошла ошибка при обработке команды. Пожалуйста, попробуйте позже."
            )
    except Exception as e:
        logger.error(f"Error in error handler: {e}")

async def update_menu_message(message, user_id: int):
    """Update existing menu message with new keyboard"""
    reply_markup = await get_main_menu(user_id)
    try:
        await message.edit_text(
            "Выберите действие:",
            reply_markup=reply_markup
        )
    except Exception as e:
        logger.error(f"Error updating menu: {e}")

async def main():
    """Start the bot"""
    # Initialize database
    await db.init_db()
    logger.info("Database initialized")

    # Create application
    application = Application.builder().token(TOKEN).build()
    logger.info("Application created")

    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("admin", admin))
    
    # Add callback query handlers
    application.add_handler(CallbackQueryHandler(register_driver, pattern="^register$"))
    application.add_handler(CallbackQueryHandler(join_queue, pattern="^join_queue$"))
    application.add_handler(CallbackQueryHandler(leave_queue, pattern="^leave_queue$"))
    application.add_handler(CallbackQueryHandler(show_profile, pattern="^profile$"))
    
    # Add admin callback query handlers
    application.add_handler(CallbackQueryHandler(admin_drivers_list, pattern="^admin_drivers_list$"))
    application.add_handler(CallbackQueryHandler(admin_queue_list, pattern="^admin_queue_list$"))
    application.add_handler(CallbackQueryHandler(admin_reset_queue, pattern="^admin_reset_queue$"))
    application.add_handler(CallbackQueryHandler(admin_delete_driver, pattern="^admin_delete_driver$"))
    
    # Add order handlers
    application.add_handler(CallbackQueryHandler(accept_order, pattern="^accept_order_"))
    application.add_handler(MessageHandler(
        filters.TEXT & filters.ChatType.GROUPS,
        handle_order
    ))
    
    # Add message handler for registration process
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        handle_registration_input
    ))

    # Add error handler
    application.add_error_handler(error_handler)

    logger.info("Starting bot...")
    return application

def run_bot():
    """Run the bot."""
    # Set up asyncio policies for Windows
    if os.name == 'nt':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

    try:
        # Create and run event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Initialize application
        application = loop.run_until_complete(main())
        
        logger.info("Bot started successfully!")
        logger.info("Press Ctrl+C to stop the bot")
        
        # Start polling
        loop.run_until_complete(
            application.run_polling(
                allowed_updates=Update.ALL_TYPES,
                drop_pending_updates=True
            )
        )
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
        loop.run_until_complete(application.stop())
    except Exception as e:
        logger.error(f"Fatal error: {e}")
        if 'application' in locals():
            loop.run_until_complete(application.stop())
    finally:
        loop.close()
        logger.info("Bot stopped")

if __name__ == '__main__':
    run_bot() 