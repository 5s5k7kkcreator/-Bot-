import logging
import asyncio
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, MessageHandler, filters, ContextTypes

import database as db
import youtube_api as yt

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

TELEGRAM_BOT_TOKEN = "8551896844:AAFEMxI6xuiGMMSYE6TLt_mHSGDSAReWylI"
YOUTUBE_API_KEY = "AIzaSyCAzXOmtW85ut3D4BC0HXlAScQmD1F65K4"

WAITING_PLAYLIST_URL = 1
WAITING_INTERVAL = 2

def get_main_menu():
    keyboard = [
        [InlineKeyboardButton("➕ إضافة قائمة", callback_data="add"),
         InlineKeyboardButton("🗑 حذف قائمة", callback_data="remove")],
        [InlineKeyboardButton("📋 قوائمي", callback_data="list"),
         InlineKeyboardButton("🔍 فحص الآن", callback_data="check")],
        [InlineKeyboardButton("▶️ تشغيل المراقبة", callback_data="start_monitor"),
         InlineKeyboardButton("⏹ إيقاف المراقبة", callback_data="stop_monitor")],
        [InlineKeyboardButton("❓ مساعدة", callback_data="help")]
    ]
    return InlineKeyboardMarkup(keyboard)

def get_back_button():
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 القائمة الرئيسية", callback_data="main_menu")]])

def get_interval_buttons():
    keyboard = [
        [InlineKeyboardButton("5 دقائق", callback_data="interval_5"),
         InlineKeyboardButton("10 دقائق", callback_data="interval_10"),
         InlineKeyboardButton("15 دقائق", callback_data="interval_15")],
        [InlineKeyboardButton("30 دقيقة", callback_data="interval_30"),
         InlineKeyboardButton("60 دقيقة", callback_data="interval_60"),
         InlineKeyboardButton("120 دقيقة", callback_data="interval_120")],
        [InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]
    ]
    return InlineKeyboardMarkup(keyboard)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        '🎬 مرحباً! أنا بوت مراقبة قوائم تشغيل يوتيوب\n\n'
        'اختر من القائمة:',
        reply_markup=get_main_menu()
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    await query.answer()
    
    data = query.data
    user_id = query.from_user.id
    
    if data == "main_menu":
        await query.edit_message_text(
            '🎬 القائمة الرئيسية\n\nاختر من الخيارات:',
            reply_markup=get_main_menu()
        )
    
    elif data == "add":
        context.user_data['waiting_for'] = 'playlist_url'
        await query.edit_message_text(
            '📥 أرسل رابط قائمة التشغيل:\n\n'
            'مثال:\n'
            'https://youtube.com/playlist?list=PLxxxxxxxx',
            reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]])
        )
    
    elif data == "remove":
        playlists = db.get_user_playlists(user_id)
        if not playlists:
            await query.edit_message_text('📭 لا توجد قوائم لحذفها', reply_markup=get_back_button())
            return
        
        keyboard = []
        for i, pl in enumerate(playlists):
            keyboard.append([InlineKeyboardButton(f"🗑 {pl['title'][:30]}", callback_data=f"del_{pl['playlist_id']}")])
        keyboard.append([InlineKeyboardButton("🔙 رجوع", callback_data="main_menu")])
        
        await query.edit_message_text('اختر القائمة للحذف:', reply_markup=InlineKeyboardMarkup(keyboard))
    
    elif data.startswith("del_"):
        playlist_id = data[4:]
        if db.remove_playlist(playlist_id, user_id):
            await query.edit_message_text('✅ تم الحذف بنجاح', reply_markup=get_back_button())
        else:
            await query.edit_message_text('❌ فشل الحذف', reply_markup=get_back_button())
    
    elif data == "list":
        playlists = db.get_user_playlists(user_id)
        if not playlists:
            await query.edit_message_text('📭 لا توجد قوائم مضافة', reply_markup=get_back_button())
            return
        
        message = '📋 قوائمك:\n\n'
        for i, pl in enumerate(playlists, 1):
            status = '🟢' if pl['is_active'] else '🔴'
            interval = pl['check_interval'] // 60
            message += f'{i}. {status} {pl["title"][:25]}\n   ⏱ كل {interval} دقيقة\n\n'
        
        await query.edit_message_text(message, reply_markup=get_back_button())
    
    elif data == "check":
        playlists = db.get_user_playlists(user_id)
        if not playlists:
            await query.edit_message_text('📭 لا توجد قوائم', reply_markup=get_back_button())
            return
        
        await query.edit_message_text('🔍 جاري الفحص...')
        
        total_changes = 0
        for pl in playlists:
            changes = await check_playlist_changes(context.bot, pl['playlist_id'], user_id)
            total_changes += changes
        
        if total_changes == 0:
            await query.edit_message_text('✅ لا توجد تغييرات جديدة', reply_markup=get_back_button())
        else:
            await query.edit_message_text(f'📨 تم إرسال {total_changes} إشعار', reply_markup=get_back_button())
    
    elif data == "start_monitor":
        playlists = db.get_user_playlists(user_id)
        count = 0
        for pl in playlists:
            if db.set_playlist_active(pl['playlist_id'], user_id, True):
                count += 1
        
        if count > 0:
            await query.edit_message_text(f'🟢 تم تفعيل المراقبة لـ {count} قائمة', reply_markup=get_back_button())
        else:
            await query.edit_message_text('📭 أضف قائمة أولاً', reply_markup=get_back_button())
    
    elif data == "stop_monitor":
        playlists = db.get_user_playlists(user_id)
        count = 0
        for pl in playlists:
            if db.set_playlist_active(pl['playlist_id'], user_id, False):
                count += 1
        
        await query.edit_message_text(f'🔴 تم إيقاف المراقبة لـ {count} قائمة', reply_markup=get_back_button())
    
    elif data == "help":
        await query.edit_message_text(
            '📖 طريقة الاستخدام:\n\n'
            '1️⃣ اضغط "إضافة قائمة"\n'
            '2️⃣ الصق رابط القائمة\n'
            '3️⃣ اختر فترة الفحص\n'
            '4️⃣ فعّل المراقبة\n\n'
            '📨 ستصلك إشعارات عند:\n'
            '• إضافة فيديو جديد\n'
            '• حذف فيديو\n'
            '• تغيير عنوان',
            reply_markup=get_back_button()
        )
    
    elif data == "cancel":
        context.user_data.clear()
        await query.edit_message_text('❌ تم الإلغاء', reply_markup=get_back_button())
    
    elif data.startswith("interval_"):
        interval = int(data.split("_")[1])
        pending = context.user_data.get('pending_playlist')
        
        if not pending:
            await query.edit_message_text('❌ حدث خطأ', reply_markup=get_back_button())
            return
        
        playlist_id = pending['id']
        title = pending['title']
        
        if db.add_playlist(playlist_id, title, user_id, interval * 60):
            videos, error = yt.get_playlist_videos(playlist_id)
            if videos:
                db.save_playlist_videos(playlist_id, videos)
            
            await query.edit_message_text(
                f'✅ تمت الإضافة!\n\n'
                f'📋 {title}\n'
                f'📹 {len(videos)} فيديو\n'
                f'⏱ كل {interval} دقيقة',
                reply_markup=get_back_button()
            )
        else:
            await query.edit_message_text('❌ فشل في الإضافة', reply_markup=get_back_button())
        
        context.user_data.clear()

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    waiting_for = context.user_data.get('waiting_for')
    
    if waiting_for == 'playlist_url':
        url = update.message.text.strip()
        playlist_id = yt.extract_playlist_id(url)
        
        if not playlist_id:
            await update.message.reply_text(
                '❌ رابط غير صالح\n\nأرسل رابط صحيح:',
                reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("❌ إلغاء", callback_data="cancel")]])
            )
            return
        
        await update.message.reply_text('🔍 جاري التحقق...')
        
        valid, title, error = yt.validate_playlist(playlist_id)
        
        if not valid:
            await update.message.reply_text(f'❌ {error}', reply_markup=get_back_button())
            context.user_data.clear()
            return
        
        context.user_data['pending_playlist'] = {'id': playlist_id, 'title': title}
        context.user_data['waiting_for'] = None
        
        await update.message.reply_text(
            f'✅ تم العثور على:\n📋 {title}\n\nاختر فترة الفحص:',
            reply_markup=get_interval_buttons()
        )
    else:
        await update.message.reply_text('اختر من القائمة:', reply_markup=get_main_menu())

async def check_playlist_changes(bot, playlist_id: str, user_id: int) -> int:
    old_videos = db.get_playlist_videos(playlist_id)
    new_videos, error = yt.get_playlist_videos(playlist_id)
    
    if error:
        logger.error(f"Error checking playlist {playlist_id}: {error}")
        return 0
    
    if not old_videos:
        db.save_playlist_videos(playlist_id, new_videos)
        return 0
    
    changes = yt.compare_videos(old_videos, new_videos)
    changes_count = 0
    now = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    for video in changes['added']:
        change_key = f"added_{video['video_id']}_{playlist_id}"
        if not db.is_change_notified(video['video_id'], playlist_id, 'added'):
            message = (
                f'🆕 فيديو جديد!\n\n'
                f'📹 {video["title"]}\n'
                f'📺 {video["channel_name"]}\n'
                f'🔗 {video["url"]}\n'
                f'🕐 {now}'
            )
            try:
                await bot.send_message(chat_id=user_id, text=message)
                db.mark_change_notified(video['video_id'], playlist_id, 'added')
                changes_count += 1
                logger.info(f"Notified: added {video['video_id']}")
            except Exception as e:
                logger.error(f"Error sending notification: {e}")
    
    for video in changes['removed']:
        if not db.is_change_notified(video['video_id'], playlist_id, 'removed'):
            message = (
                f'🗑 تم حذف فيديو!\n\n'
                f'📹 {video["title"]}\n'
                f'📺 {video["channel_name"]}\n'
                f'🕐 {now}'
            )
            try:
                await bot.send_message(chat_id=user_id, text=message)
                db.mark_change_notified(video['video_id'], playlist_id, 'removed')
                changes_count += 1
                logger.info(f"Notified: removed {video['video_id']}")
            except Exception as e:
                logger.error(f"Error sending notification: {e}")
    
    for video in changes['title_changed']:
        change_key = f"{video['old_title']}_{video['new_title']}"
        if not db.is_change_notified(video['video_id'], playlist_id, f'title_{change_key[:50]}'):
            message = (
                f'✏️ تغيير عنوان!\n\n'
                f'📹 القديم: {video["old_title"]}\n'
                f'📹 الجديد: {video["new_title"]}\n'
                f'📺 {video["channel_name"]}\n'
                f'🔗 {video["url"]}\n'
                f'🕐 {now}'
            )
            try:
                await bot.send_message(chat_id=user_id, text=message)
                db.mark_change_notified(video['video_id'], playlist_id, f'title_{change_key[:50]}')
                changes_count += 1
                logger.info(f"Notified: title changed {video['video_id']}")
            except Exception as e:
                logger.error(f"Error sending notification: {e}")
    
    db.save_playlist_videos(playlist_id, new_videos)
    return changes_count

async def periodic_check(context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.info("Running periodic check...")
    playlists = db.get_all_active_playlists()
    
    for pl in playlists:
        try:
            await check_playlist_changes(context.bot, pl['playlist_id'], pl['user_id'])
            await asyncio.sleep(2)
        except Exception as e:
            logger.error(f"Error in periodic check for {pl['playlist_id']}: {e}")

async def post_init(application):
    commands = [
        BotCommand("start", "بدء البوت والقائمة الرئيسية"),
    ]
    await application.bot.set_my_commands(commands)

def main() -> None:
    db.init_db()
    
    yt.YOUTUBE_API_KEY = YOUTUBE_API_KEY
    
    application = Application.builder().token(TELEGRAM_BOT_TOKEN).post_init(post_init).build()
    
    application.add_handler(CommandHandler('start', start))
    application.add_handler(CallbackQueryHandler(button_handler))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
    
    job_queue = application.job_queue
    job_queue.run_repeating(periodic_check, interval=60, first=10)
    
    logger.info('Bot started successfully!')
    print('🤖 البوت يعمل الآن...')
    
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
