#!/usr/bin/env python3.6
# -*- coding: utf-8 -*-
# This program is dedicated to the public domain under the CC0 license.

"""
Simple Bot to reply to Telegram messages.
First, a few handler functions are defined. Then, those functions are passed to
the Dispatcher and registered at their respective places.
Then, the bot is started and runs until we press Ctrl-C on the command line.
Usage:
Basic Echobot example, repeats messages.
Press Ctrl-C on the command line or send a signal to the process to stop the
bot.
"""

import logging
import pickle
import random
import re
import string
from datetime import datetime
from datetime import timedelta
from time import time

from claptcha import Claptcha
from telegram import ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup, ParseMode
from telegram.ext import Updater, MessageHandler, Filters, CommandHandler, Job, \
    CallbackQueryHandler, ConversationHandler

# Enable logging
logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
                    level=logging.INFO)

logger = logging.getLogger(__name__)

TOKEN = "<YOUR TOKEN HERE>"

INSTANCE_CHAT_ID = set()
SUPER_ADMIN = "SUPER ADMIN USERNAME WITHOU @"
ADMINS = [SUPER_ADMIN]

DEFAULT_CAPTCHA_TIME = 5 * 60
DEFAULT_WELCOME_MESSAGE = "Welcome!"
DEFAULT_GOODBYE_MESSAGE = "Bye!"

CAPTCHA_TIME = {}
WELCOME_MESSAGE = {}
GOODBYE_MESSAGE = {}

PERSONAL_LINK_CHAT = "chat-links"
PERSONAL_LINK_PROGRESSOR = "progressor-links"
PERSONAL_LINK_DATING = "dating-links"
PERSONAL_LINK_VK = "vk-links"

DATA_PICKLE = 'data_values.pickle'
JOBS_PICKLE = 'job_tuples.pickle'
TEMP_PICKLE = 'temp.pickle'

BEGIN, ADMIN, END = range(3)
LINK_CHAT = "link_chat"
LINK_PROGRESSOR = "link_progressor"
LINK_DATING = "link_dating"
LINK_VK = "link_vk"
ADMIN = "admin"
RESTART = "restart"

# WARNING: This information may change in future versions (changes are planned)
JOB_DATA = ('callback', 'interval', 'repeat', 'context', 'days', 'name', 'tzinfo')
JOB_STATE = ('_remove', '_enabled')

# TODO: move these to job context (somehow)
captchas = {}
messages_to_delete = {}


def random_digit_string(string_length=4):
    """Generate a random string of fixed length """
    return ''.join(random.choice(string.digits) for i in range(string_length))


def kick_on_time(context):
    """Send the alarm message."""
    job = context.job
    chat_id = job.context[0]
    username = job.context[1]
    user_id = job.context[2]
    context.bot.kick_chat_member(chat_id, user_id,
                                 until_date=datetime.utcnow() + timedelta(minutes=1))
    cleanup(chat_id, username, context)


def cleanup(chat_id, username, context):
    if username in messages_to_delete[chat_id]:
        for msg_id in messages_to_delete[chat_id][username]:
            context.bot.delete_message(chat_id, msg_id)
        del messages_to_delete[chat_id][username]
        del captchas[chat_id][username]


def find_whole_word(w):
    return re.compile(r'(^|[^\w]){}([^\w]|$)'.format(w), flags=re.IGNORECASE).search


def process_message(update, context):
    logger.debug('process_message %s', update)

    if update.message.chat_id not in INSTANCE_CHAT_ID:
        return

    chat_id = update.message.chat_id
    if update.message.text is not None:
        if update.message.text.isdigit():
            username = update.message.from_user.username
            if username in captchas[chat_id]:
                if captchas[chat_id][username] == update.message.text.casefold():
                    messages_to_delete[chat_id][username].append(update.message.message_id)
                    complete_captcha(context, update)
                else:
                    message = update.message.reply_text('Неверно. Попробуйте ещё раз.')
                    messages_to_delete[chat_id][username].append(update.message.message_id)
                    messages_to_delete[chat_id][username].append(message.message_id)
        elif find_whole_word('@admin')(update.message.text) is not None:
            notify_admins(update, context)


def notify_admins(update, context):
    admins = context.bot.get_chat_administrators(update.message.chat_id)
    admin_text = ", ".join('@' + admin.user.username for admin in admins if not admin.user.is_bot)

    update.message.reply_text(admin_text)


def complete_captcha(context, update):
    chat_id = update.message.chat_id
    username = update.message.from_user.username
    update.message.reply_text(f"""@{username}, {WELCOME_MESSAGE[chat_id]}""")
    stop_job(context, update.message.from_user.id)
    cleanup(chat_id, username, context)


def create_captcha(text):
    c = Claptcha(text, "FreeMono.ttf")
    c.write("last_captcha.png")
    return open('last_captcha.png', 'rb')


def error(update, context):
    """Log Errors caused by Updates."""
    logger.warning('Update "%s" caused error "%s"', update, context.error)


def new_chat_members_invite(update, context):
    logger.debug('new_chat_members_invite %s', update)
    chat_id = update.message.chat_id
    if chat_id not in INSTANCE_CHAT_ID:
        return

    if chat_id not in captchas:
        captchas[chat_id] = {}
    if chat_id not in messages_to_delete:
        messages_to_delete[chat_id] = {}

    for user in update.message.new_chat_members:
        if not user.is_bot and user.username not in captchas[chat_id]:
            start_new_captcha(context, user, update)


def start_new_captcha(context, user, update):
    generated_captcha = random_digit_string()
    user_id = user.id
    chat_id = update.message.chat_id
    username = user.username
    captchas[chat_id][username] = generated_captcha.casefold()
    photo = update.message.reply_photo(create_captcha(generated_captcha),
                                       caption=f'@{username}, у вас есть {CAPTCHA_TIME[chat_id]} секунд, '
                                               f'чтобы написать то что вы видите на картинке')
    messages_to_delete[chat_id][username] = list()
    messages_to_delete[chat_id][username].append(photo.message_id)
    due = CAPTCHA_TIME[chat_id]

    stop_job(context, user_id)
    start_job(chat_id, context, due, user_id, username)


def get_job_name(user_id):
    return 'job' + str(user_id)


def start_job(chat_id, context, due, user_id, username):
    new_job = context.job_queue.run_once(kick_on_time, due, context=(chat_id, username, user_id))
    context.chat_data[get_job_name(user_id)] = new_job
    save_jobs_job(context)


def stop_job(context, user_id):
    job_name = get_job_name(user_id)
    if job_name in context.chat_data:
        old_job = context.chat_data[job_name]
        old_job.schedule_removal()
    save_jobs_job(context)


def left_chat_member(update, context):
    logger.info('left_chat_member %s', update)
    if update.message.chat_id not in INSTANCE_CHAT_ID:
        return

    username = update.message.left_chat_member.username
    chat_id = update.message.chat_id

    update.message.reply_text(f"""@{username}, {GOODBYE_MESSAGE[chat_id]}""")

    stop_job(context, update.message.left_chat_member.id)
    cleanup(chat_id, username, context)


def show_help_message(update, context):
    logger.debug('help %s', update)
    if update.message.chat_id not in INSTANCE_CHAT_ID:
        return

    if not user_is_admin(update, context):
        return

    help_text = "Команды чатбота:\n" \
                "/help -- помощь\n" \
                "/set_welcome_msg <сообщение> -- устанавливает сообщение, которое пользователь видит перед каптчей\n" \
                "/set_goodbye_msg <сообщение> -- сообщение, которое остаётся после того как пользователь вышел\n" \
                "/set_captcha_time <секунды> -- устанавливает время отведенное на ввод каптчи\n" \
                "Комманды, работающие в ответ на сообщения пользователей:\n" \
                "/kick -- удаляет этого пользователя из чата\n" \
                "/ban -- банит пользователя навсегда в чате\n" \
                "/mute <время> -- ограничивает возможность писать в чате на время\n"
    update.message.reply_text(help_text)


def set_welcome_message(update, context):
    global WELCOME_MESSAGE
    logger.debug('set_welcome_message %s', update)
    if update.message.chat_id not in INSTANCE_CHAT_ID:
        return

    if not user_is_admin(update, context):
        return

    chat_id = update.message.chat_id
    msg = update.message.text.split(None, 1)[1]
    WELCOME_MESSAGE[chat_id] = msg
    update.message.reply_text("Приветственное сообщение установлено!")
    save_config_data()


def set_goodbye_message(update, context):
    global GOODBYE_MESSAGE
    logger.debug('set_goodbye_message %s', update)
    if update.message.chat_id not in INSTANCE_CHAT_ID:
        return

    if not user_is_admin(update, context):
        return

    chat_id = update.message.chat_id
    msg = update.message.text.split(None, 1)[1]
    GOODBYE_MESSAGE[chat_id] = msg
    update.message.reply_text("Прощальное сообщение установлено!")
    save_config_data()


def set_captcha_time(update, context):
    global CAPTCHA_TIME
    logger.debug('set_captcha_time %s', update)
    if update.message.chat_id not in INSTANCE_CHAT_ID:
        return

    if not user_is_admin(update, context):
        return

    try:
        due = int(context.args[0])
        if due < 0:
            update.message.reply_text('Время не может быть отрицательным!')
            return

        CAPTCHA_TIME[update.message.chat_id] = due
        update.message.reply_text("Время на решение каптчи установлено на " + str(due) + " секунд")
        save_config_data()
    except (IndexError, ValueError):
        update.message.reply_text('Использование: /set_captcha_time <seconds>')


def user_is_admin(update, context):
    members = context.bot.get_chat_administrators(update.message.chat_id)
    return any(member for member in members if member.user.username == update.message.from_user.username)


def kick_user(update, context):
    logger.debug('kick_user %s', update)
    if update.message.chat_id not in INSTANCE_CHAT_ID:
        return

    if not user_is_admin(update, context):
        return

    if update.message.reply_to_message is None:
        update.message.reply_text('Использование: /kick, в ответе на сообщение')
    else:
        chat_id = update.message.chat_id
        username = update.message.reply_to_message.from_user.username
        if context.bot.kick_chat_member(chat_id, update.message.reply_to_message.from_user.id,
                                        until_date=datetime.utcnow() + timedelta(minutes=1)):
            update.message.reply_text("@" + username + ", " + GOODBYE_MESSAGE[chat_id])


def ban_user(update, context):
    logger.debug('ban_user %s', update)
    if update.message.chat_id not in INSTANCE_CHAT_ID:
        return

    if not user_is_admin(update, context):
        return

    if update.message.reply_to_message is None:
        update.message.reply_text('Использование: /mute, в ответе на сообщение')
    else:
        chat_id = update.message.chat_id
        username = update.message.reply_to_message.from_user.username
        if context.bot.kick_chat_member(chat_id, update.message.reply_to_message.from_user.id):
            update.message.reply_text("@" + username + ", " + GOODBYE_MESSAGE[chat_id])


def mute_user(update, context):
    logger.debug('mute_user %s', update)
    if update.message.chat_id not in INSTANCE_CHAT_ID:
        return

    if not user_is_admin(update, context):
        return

    if update.message.reply_to_message is None:
        update.message.reply_text('Использование: /mute <time>, в ответе на сообщение')
    else:
        try:
            due = parse_time(context.args[0])
            if due == timedelta():
                raise ValueError

            if context.bot.restrict_chat_member(update.message.chat_id, update.message.reply_to_message.from_user.id,
                                                ChatPermissions(can_send_messages=False,
                                                                can_add_web_page_previews=False,
                                                                can_change_info=False,
                                                                can_invite_users=False,
                                                                can_pin_messages=False,
                                                                can_send_media_messages=False,
                                                                can_send_other_messages=False,
                                                                can_send_polls=False),
                                                until_date=datetime.utcnow() + due):
                update.message.reply_text("Пользователь @" + update.message.reply_to_message.from_user.username +
                                          " ограничен на " + str(due))
        except (IndexError, ValueError):
            update.message.reply_text('Использование: /mute <time>, например, /mute 6d5h4m3s или /mute 2m')


def parse_time(time_str):
    regex = re.compile(r'((?P<days>\d+?)d)?((?P<hours>\d+?)h)?((?P<minutes>\d+?)m)?((?P<seconds>\d+?)s)?')
    parts = regex.match(time_str)
    if not parts:
        return
    parts = parts.groupdict()
    time_params = {}
    for (name, param) in parts.items():
        if param:
            time_params[name] = int(param)
    return timedelta(**time_params)


def load_jobs(jq):
    logger.debug('load_jobs()')
    with open(JOBS_PICKLE, 'rb') as fp:
        while True:
            try:
                next_t, data, state = pickle.load(fp)
            except EOFError:
                break  # loaded all jobs

            # New object with the same data
            job = Job(**{var: val for var, val in zip(JOB_DATA, data)})

            # Restore the state it had
            for var, val in zip(JOB_STATE, state):
                attribute = getattr(job, var)
                getattr(attribute, 'set' if val else 'clear')()

            job.job_queue = jq

            next_t -= time()  # convert from absolute to relative time

            jq._put(job, next_t)


def save_jobs(jq):
    logger.debug('save_jobs()')
    with jq._queue.mutex:  # in case job_queue makes a change
        if jq:
            job_tuples = jq._queue.queue
        else:
            job_tuples = []

        with open(JOBS_PICKLE, 'wb') as fp:
            for next_t, job in job_tuples:

                # This job is always created at the start
                if job.name == 'save_jobs_job':
                    continue

                # Threading primitives are not pickleable
                data = tuple(getattr(job, var) for var in JOB_DATA)
                state = tuple(getattr(job, var).is_set() for var in JOB_STATE)

                # Pickle the job
                pickle.dump((next_t, data, state), fp)


def save_jobs_job(context):
    save_jobs(context.job_queue)


def save_temp_job(context):
    save_temp_data()


def save_temp_data():
    logger.debug('save_temp_data()')
    with open(TEMP_PICKLE, 'wb') as fp:
        pickle.dump(captchas, fp)
        pickle.dump(messages_to_delete, fp)


def load_temp_data():
    global captchas, messages_to_delete
    logger.debug('load_temp_data()')
    with open(TEMP_PICKLE, 'rb') as fp:
        captchas = pickle.load(fp)
        messages_to_delete = pickle.load(fp)


def save_config_data():
    logger.debug('save_config_data()')
    with open(DATA_PICKLE, 'wb') as fp:
        pickle.dump((CAPTCHA_TIME, GOODBYE_MESSAGE, WELCOME_MESSAGE, ADMINS), fp)
        pickle.dump((PERSONAL_LINK_CHAT, PERSONAL_LINK_PROGRESSOR, PERSONAL_LINK_DATING, PERSONAL_LINK_VK), fp)
        pickle.dump(INSTANCE_CHAT_ID, fp)


def load_config_data():
    global CAPTCHA_TIME, GOODBYE_MESSAGE, WELCOME_MESSAGE, ADMINS
    global PERSONAL_LINK_CHAT, PERSONAL_LINK_PROGRESSOR, PERSONAL_LINK_DATING, PERSONAL_LINK_VK
    global INSTANCE_CHAT_ID
    logger.debug('load_config_data()')
    with open(DATA_PICKLE, 'rb') as fp:
        CAPTCHA_TIME, GOODBYE_MESSAGE, WELCOME_MESSAGE, ADMINS = pickle.load(fp)
        PERSONAL_LINK_CHAT, PERSONAL_LINK_PROGRESSOR, PERSONAL_LINK_DATING, PERSONAL_LINK_VK = pickle.load(fp)
        INSTANCE_CHAT_ID = pickle.load(fp)


def personal_start(update, context):
    user = update.message.from_user
    logger.info("User %s started the conversation.", user.first_name)
    reply_markup = draw_start_menu(user)
    update.message.reply_text(
        "Выберите интересующую информацию",
        reply_markup=reply_markup
    )
    return BEGIN


def personal_start_over(update, context):
    query = update.callback_query
    user = query.from_user
    query.answer()
    reply_markup = draw_start_menu(user)
    query.edit_message_text(
        "Выберите интересующую информацию",
        reply_markup=reply_markup
    )
    return BEGIN


def draw_start_menu(user):
    keyboard = [
        [InlineKeyboardButton("Поличаты", callback_data=str(LINK_CHAT))],
        [InlineKeyboardButton("Матчасть", callback_data=str(LINK_PROGRESSOR))],
        [InlineKeyboardButton("Знакомства", callback_data=str(LINK_DATING))],
        [InlineKeyboardButton("ВК", callback_data=str(LINK_VK))]
    ]
    if user.username in ADMINS:
        keyboard.append([InlineKeyboardButton("Админка", callback_data=str(ADMIN))])
    reply_markup = InlineKeyboardMarkup(keyboard)
    return reply_markup


def personal_link_chat(update, context):
    query = update.callback_query
    query.answer()
    keyboard = [
        [InlineKeyboardButton("Назад", callback_data=str(RESTART))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text=PERSONAL_LINK_CHAT,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return END


def personal_link_progressor(update, context):
    query = update.callback_query
    query.answer()
    keyboard = [
        [InlineKeyboardButton("Назад", callback_data=str(RESTART))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text=PERSONAL_LINK_PROGRESSOR,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return END


def personal_link_dating(update, context):
    query = update.callback_query
    query.answer()
    keyboard = [
        [InlineKeyboardButton("Назад", callback_data=str(RESTART))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text=PERSONAL_LINK_DATING,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return END


def personal_link_vk(update, context):
    query = update.callback_query
    query.answer()
    keyboard = [
        [InlineKeyboardButton("Назад", callback_data=str(RESTART))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    query.edit_message_text(
        text=PERSONAL_LINK_VK,
        reply_markup=reply_markup,
        parse_mode=ParseMode.MARKDOWN
    )
    return END


def personal_admin_panel(update, context):
    query = update.callback_query
    user = query.from_user
    query.answer()
    keyboard = [
        [InlineKeyboardButton("Назад", callback_data=str(RESTART))]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    text = """Additional Admin Commands:
        /set_link_chat <chat_link_message>
        /set_link_progressor <progressor_link_message>
        /set_link_dating <dating_link_message>
        /set_link_vk <vk_link_message>""";
    if user.username == SUPER_ADMIN:
        text += """
        /list_admin
        /add_admin <username>
        /remove_admin <username>"""
    query.edit_message_text(
        text=text,
        reply_markup=reply_markup
    )
    return END


def set_personal_link_chat(update, context):
    global PERSONAL_LINK_CHAT
    logger.debug('set_personal_link_chat %s', update)
    if update.message.from_user.username not in ADMINS:
        return

    msg = update.message.text.split(None, 1)[1]
    PERSONAL_LINK_CHAT = msg
    update.message.reply_text("Принято. Новое сообщение:\n" + msg, parse_mode=ParseMode.MARKDOWN)
    save_config_data()


def set_personal_link_progressor(update, context):
    global PERSONAL_LINK_PROGRESSOR
    logger.debug('set_personal_link_progressor %s', update)
    if not (update.message.from_user.username in ADMINS):
        return

    msg = update.message.text.split(None, 1)[1]
    PERSONAL_LINK_PROGRESSOR = msg
    update.message.reply_text("Принято. Новое сообщение:\n" + msg, parse_mode=ParseMode.MARKDOWN)
    save_config_data()


def set_personal_link_dating(update, context):
    global PERSONAL_LINK_DATING
    logger.debug('set_personal_link_dating %s', update)
    if not (update.message.from_user.username in ADMINS):
        return

    msg = update.message.text.split(None, 1)[1]
    PERSONAL_LINK_DATING = msg
    update.message.reply_text("Принято. Новое сообщение:\n" + msg, parse_mode=ParseMode.MARKDOWN)
    save_config_data()


def set_personal_link_vk(update, context):
    global PERSONAL_LINK_VK
    logger.debug('set_personal_link_vk %s', update)
    if not (update.message.from_user.username in ADMINS):
        return

    msg = update.message.text.split(None, 1)[1]
    PERSONAL_LINK_VK = msg
    update.message.reply_text("Принято. Новое сообщение:\n" + msg, parse_mode=ParseMode.MARKDOWN)
    save_config_data()


def list_personal_admin(update, context):
    logger.debug('list_personal_admin %s', update)
    if update.message.from_user.username != SUPER_ADMIN:
        return

    update.message.reply_text(', '.join(ADMINS))


def add_personal_admin(update, context):
    logger.debug('add_personal_admin %s', update)
    if update.message.from_user.username != SUPER_ADMIN:
        return

    username = context.args[0]
    ADMINS.append(username)
    update.message.reply_text("Added")
    save_config_data()


def remove_personal_admin(update, context):
    logger.debug('remove_personal_admin %s', update)
    if update.message.from_user.username != SUPER_ADMIN:
        return

    username = context.args[0]
    ADMINS.remove(username)
    update.message.reply_text("Removed")
    save_config_data()


def register_chat(update, context):
    global INSTANCE_CHAT_ID
    logger.debug('register_chat %s', update)
    if update.message.from_user.username != SUPER_ADMIN:
        return

    if update.message.chat.type != 'supergroup':
        return

    chat_id = update.message.chat_id
    INSTANCE_CHAT_ID.add(chat_id)

    CAPTCHA_TIME[chat_id] = DEFAULT_CAPTCHA_TIME
    WELCOME_MESSAGE[chat_id] = DEFAULT_WELCOME_MESSAGE
    GOODBYE_MESSAGE[chat_id] = DEFAULT_GOODBYE_MESSAGE
    captchas[chat_id] = {}
    messages_to_delete[chat_id] = {}

    update.message.reply_text("Готово!")
    save_config_data()


def unregister_chat(update, context):
    global INSTANCE_CHAT_ID
    logger.debug('unregister_chat %s', update)
    if update.message.from_user.username != SUPER_ADMIN:
        return

    if update.message.chat.type != 'supergroup':
        return

    INSTANCE_CHAT_ID.remove(update.message.chat_id)
    update.message.reply_text("Готово!")
    save_config_data()


def main():
    """Start the bot."""
    updater = Updater(TOKEN, use_context=True)

    job_queue = updater.job_queue

    dp = updater.dispatcher

    dp.add_handler(CommandHandler("help", show_help_message))
    dp.add_handler(CommandHandler("set_welcome_msg", set_welcome_message))
    dp.add_handler(CommandHandler("set_goodbye_msg", set_goodbye_message))
    dp.add_handler(CommandHandler("set_captcha_time", set_captcha_time))
    dp.add_handler(CommandHandler("kick", kick_user))
    dp.add_handler(CommandHandler("ban", ban_user))
    dp.add_handler(CommandHandler("mute", mute_user))

    dp.add_handler(CommandHandler("register_chat", register_chat))
    dp.add_handler(CommandHandler("unregister_chat", unregister_chat))

    dp.add_handler(MessageHandler(Filters.text & Filters.group, process_message))
    dp.add_handler(MessageHandler(Filters.status_update.new_chat_members, new_chat_members_invite))
    dp.add_handler(MessageHandler(Filters.status_update.left_chat_member, left_chat_member))

    dp.add_handler(CommandHandler("set_link_chat", set_personal_link_chat))
    dp.add_handler(CommandHandler("set_link_progressor", set_personal_link_progressor))
    dp.add_handler(CommandHandler("set_link_dating", set_personal_link_dating))
    dp.add_handler(CommandHandler("set_link_vk", set_personal_link_vk))
    dp.add_handler(CommandHandler("list_admin", list_personal_admin))
    dp.add_handler(CommandHandler("add_admin", add_personal_admin))
    dp.add_handler(CommandHandler("remove_admin", remove_personal_admin))

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', personal_start)],
        states={
            BEGIN: [CallbackQueryHandler(personal_link_chat, pattern='^' + str(LINK_CHAT) + '$'),
                    CallbackQueryHandler(personal_link_progressor, pattern='^' + str(LINK_PROGRESSOR) + '$'),
                    CallbackQueryHandler(personal_link_dating, pattern='^' + str(LINK_DATING) + '$'),
                    CallbackQueryHandler(personal_link_vk, pattern='^' + str(LINK_VK) + '$'),
                    CallbackQueryHandler(personal_admin_panel, pattern='^' + str(ADMIN) + '$')],
            END: [CallbackQueryHandler(personal_start_over, pattern='^' + str(RESTART) + '$')]
        },
        fallbacks=[CommandHandler('start', personal_start)]
    )

    dp.add_handler(conv_handler)

    dp.add_error_handler(error)

    try:
        load_config_data()
    except FileNotFoundError:
        # First run
        pass

    try:
        load_jobs(job_queue)
    except FileNotFoundError:
        # First run
        pass

    try:
        load_temp_data()
    except FileNotFoundError:
        # First run
        pass

    job_queue.run_repeating(save_jobs_job, timedelta(minutes=1))
    job_queue.run_repeating(save_temp_job, timedelta(minutes=1))

    updater.start_polling()

    logger.info('Ready to go')

    updater.idle()

    save_config_data()
    save_jobs(job_queue)
    save_temp_data()


if __name__ == '__main__':
    main()
