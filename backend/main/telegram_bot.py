import asyncio
import logging
import threading

from aiogram import Bot
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from bot.config import BOT_TOKEN
from bot.database.models import TelegramUser

logger = logging.getLogger(__name__)


def _admins():
    """Только синхронный контекст: ORM внутри async падает."""
    return list(
        TelegramUser.objects
        .filter(is_admin=True, notifications_enabled=True)
        .values_list('telegram_id', 'first_name')
    )


def _payload(app):
    return {
        'id': app.pk,
        'name': ('%s %s' % (app.first_name or '', app.last_name or '')).strip(),
        'birth_date': app.birth_date,
        'phone': app.phone or '',
        'email': app.email or '',
        'motivation': app.motivation or '',
        'interests': str(app.interests or ''),
        'submitted_at': app.submitted_at,
    }


def _text(v):
    lines = [
        '🎉 <b>Нова заявка волонтера!</b>',
        '',
        '👤 <b>Ім\'я:</b> %s' % (v['name'] or '—'),
        '📞 <b>Телефон:</b> %s' % (v['phone'] or '—'),
        '📧 <b>Email:</b> %s' % (v['email'] or '—'),
    ]
    if v['birth_date']:
        lines.append('🎂 <b>Дата народження:</b> %s' % v['birth_date'])
    if v['interests']:
        lines.append('🎯 <b>Напрямки:</b> %s' % v['interests'])
    if v['motivation']:
        lines += ['', '💬 <b>Мотивація:</b> %s' % v['motivation']]
    if v['submitted_at']:
        lines += ['', '🕐 %s' % v['submitted_at'].strftime('%d.%m.%Y %H:%M')]
    lines += ['', '#%s' % v['id']]
    return '\n'.join(lines)


def _kb(app_id):
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text='✅ Прийняти', callback_data='approve_%s' % app_id),
        InlineKeyboardButton(text='❌ Відхилити', callback_data='reject_%s' % app_id),
        InlineKeyboardButton(text='ℹ️ Деталі', callback_data='details_%s' % app_id),
    ]])


async def _send_all(admins, text, app_id):
    if not BOT_TOKEN:
        logger.error('TELEGRAM_BOT_TOKEN is empty — уведомления не отправлены')
        return
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    try:
        for telegram_id, name in admins:
            try:
                await bot.send_message(
                    telegram_id, text, reply_markup=_kb(app_id), disable_web_page_preview=True
                )
                logger.info('Notification sent to admin %s (%s)', telegram_id, name)
            except Exception as e:
                logger.error('Failed to send notification to %s: %s', telegram_id, e)
    finally:
        await bot.session.close()


def send_volunteer_notification_sync(volunteer_application):
    try:
        admins = _admins()
        v = _payload(volunteer_application)
        coro = _send_all(admins, _text(v), v['id'])

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(coro)
            return

        box = {}

        def _runner():
            try:
                asyncio.run(coro)
            except BaseException as exc:
                box['error'] = exc

        th = threading.Thread(target=_runner, daemon=True)
        th.start()
        th.join()
        if 'error' in box:
            raise box['error']
    except Exception as e:
        logger.error('Error in send_volunteer_notification_sync: %s', e)
