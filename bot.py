import asyncio
import html
import json
import logging
from pathlib import Path

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    FSInputFile,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    InputMediaPhoto,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
)

PHOTOS_DIR = Path(__file__).parent / "photos"
DATA_FILE = Path(__file__).parent / "data.json"
PHOTOS = ["1.jpg", "2.jpg", "3.jpg"]
COLORS_PHOTO = "colors.jpg"
COLORS_COUNT = 25
ADMIN_ID = 5942100443


class OrderForm(StatesGroup):
    color = State()
    delivery = State()
    address = State()
    full_name = State()
    phone = State()
    receipt = State()


class AdminForm(StatesGroup):
    write = State()

TOKEN = "8828045451:AAFtY5yLVZt-0SspnCDyLIbutXAYhr7AAFU"

GREETING = (
    "🏮 <b>Здравствуй, переступивший порог моей лавки.</b>\n\n"
    "<blockquote>Здесь мы не просто шьём; мы соткаем для твоего четвероногого "
    "ученика головной убор, уникальный, как его собственная тень.</blockquote>\n\n"
    "<i>Мастер знает: шляпа на ушах кота — это не аксессуар, "
    "а вопрос о природе свободы.</i> 🐱🎩"
)

ORDER_QUESTION = "🎩 <b>Хотите сделать заказ?</b>"

dp = Dispatcher()

is_admin = F.from_user.id == ADMIN_ID

esc = html.escape


# ---------- данные ----------

def load_data():
    if not DATA_FILE.exists():
        return {"users": {}, "orders": {}, "next_id": 1}
    return json.loads(DATA_FILE.read_text(encoding="utf-8"))


def save_data(data):
    DATA_FILE.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def register_user(user):
    data = load_data()
    data["users"][str(user.id)] = {
        "name": user.full_name,
        "username": user.username,
    }
    save_data(data)


# ---------- помощники: удаление / замена сообщений ----------

async def safe_delete(message: Message):
    try:
        await message.delete()
    except TelegramBadRequest:
        pass


async def safe_edit(message: Message, text, markup=None):
    """Заменяет текст (или подпись к фото) сообщения на новый."""
    try:
        if message.photo or message.document:
            await message.edit_caption(caption=text, reply_markup=markup)
        else:
            await message.edit_text(text, reply_markup=markup)
    except TelegramBadRequest:
        pass


async def show(bot: Bot, chat_id, state: FSMContext, text, markup=None):
    """Заменяет предыдущее сообщение бота новым текстом.
    Если заменить нельзя (например, там было фото) — старое удаляется,
    а новое отправляется."""
    form = await state.get_data()
    old_id = form.get("prompt_id")
    if old_id:
        try:
            await bot.edit_message_text(
                text, chat_id=chat_id, message_id=old_id, reply_markup=markup
            )
            return
        except TelegramBadRequest:
            try:
                await bot.delete_message(chat_id, old_id)
            except TelegramBadRequest:
                pass
    sent = await bot.send_message(chat_id, text, reply_markup=markup)
    await state.update_data(prompt_id=sent.message_id)


# ---------- старт ----------

def main_keyboard(user_id):
    rows = [[KeyboardButton(text="Сделать заказ")]]
    if user_id == ADMIN_ID:
        rows.append([KeyboardButton(text="Админ панель")])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


@dp.message(CommandStart())
async def start(message: Message, state: FSMContext):
    await state.clear()
    register_user(message.from_user)
    media = [
        InputMediaPhoto(
            media=FSInputFile(PHOTOS_DIR / name),
            caption=GREETING if i == 0 else None,
        )
        for i, name in enumerate(PHOTOS)
    ]
    await message.answer_media_group(media)
    await message.answer(
        ORDER_QUESTION, reply_markup=main_keyboard(message.from_user.id)
    )


SIZES = {
    "s": ("S", "Мелкие породы", 550),
    "m": ("M", "Средние породы", 650),
    "l": ("L", "Крупные породы", 750),
}

sizes_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [InlineKeyboardButton(
            text=f"{letter} {title} - {price}₽",
            callback_data=f"size_{key}",
        )]
        for key, (letter, title, price) in SIZES.items()
    ]
)


@dp.message(F.text == "Сделать заказ")
async def make_order(message: Message):
    register_user(message.from_user)
    await message.answer(
        "🐾 <b>Какой размер у вашего питомца?</b>\n\n"
        "<i>Цена указана с учётом доставки по России.</i> 🚚",
        reply_markup=sizes_keyboard,
    )


@dp.callback_query(F.data.startswith("size_"))
async def choose_size(callback: CallbackQuery, state: FSMContext):
    key = callback.data.removeprefix("size_")
    await state.clear()
    await state.update_data(size=key)
    await state.set_state(OrderForm.color)
    await safe_delete(callback.message)
    sent = await callback.message.answer_photo(
        FSInputFile(PHOTOS_DIR / COLORS_PHOTO),
        caption=(
            "🎨 <b>Отлично!</b> Напишите, какого цвета желаете сделать "
            "головной убор для вашего четвероногого друга.\n\n"
            f"<blockquote>Номер цвета — от <b>1</b> до <b>{COLORS_COUNT}</b></blockquote>"
        ),
    )
    await state.update_data(prompt_id=sent.message_id)
    await callback.answer()


@dp.message(OrderForm.color)
async def choose_color(message: Message, state: FSMContext):
    text = (message.text or "").strip()
    form = await state.get_data()
    await safe_delete(message)
    if not text.isdigit() or not 1 <= int(text) <= COLORS_COUNT:
        try:
            await message.bot.edit_message_caption(
                chat_id=message.chat.id,
                message_id=form.get("prompt_id"),
                caption=(
                    "🎨 <b>Напишите номер цвета</b>\n\n"
                    f"⚠️ <i>Нужно число от <b>1</b> до <b>{COLORS_COUNT}</b>.</i>"
                ),
            )
        except TelegramBadRequest:
            pass
        return
    await state.update_data(color=text)
    await state.set_state(OrderForm.delivery)
    await show(
        message.bot, message.chat.id, state,
        "📦 <b>Отлично!</b> Выберите способ доставки:",
        delivery_keyboard,
    )


DELIVERY = {
    "5post": "5Post",
    "avito": "Авито",
    "yandex": "Яндекс",
    "ozon": "Озон",
    "wb": "ВБ",
    "russianpost": "Почта России",
    "cdek": "СДЭК",
}

_delivery_buttons = [
    InlineKeyboardButton(text=name, callback_data=f"delivery_{key}")
    for key, name in DELIVERY.items()
]
delivery_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        _delivery_buttons[i:i + 2] for i in range(0, len(_delivery_buttons), 2)
    ]
)


@dp.callback_query(OrderForm.delivery, F.data.startswith("delivery_"))
async def choose_delivery(callback: CallbackQuery, state: FSMContext):
    key = callback.data.removeprefix("delivery_")
    await state.update_data(
        delivery=DELIVERY[key], prompt_id=callback.message.message_id
    )
    await state.set_state(OrderForm.address)
    await show(
        callback.bot, callback.message.chat.id, state,
        f"📍 Доставка: <b>{DELIVERY[key]}</b>\n\n"
        "Укажите <b>адрес ПВЗ</b>:",
    )
    await callback.answer()


@dp.message(OrderForm.address, F.text)
async def get_address(message: Message, state: FSMContext):
    await state.update_data(address=message.text.strip())
    await state.set_state(OrderForm.full_name)
    await safe_delete(message)
    await show(
        message.bot, message.chat.id, state,
        "👤 Укажите <b>ФИО</b> получателя:",
    )


@dp.message(OrderForm.full_name, F.text)
async def get_full_name(message: Message, state: FSMContext):
    await state.update_data(full_name=message.text.strip())
    await state.set_state(OrderForm.phone)
    await safe_delete(message)
    await show(
        message.bot, message.chat.id, state,
        "📞 Укажите <b>контактный телефон</b>:",
    )


confirm_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[[
        InlineKeyboardButton(text="❌ Отмена", callback_data="order_cancel"),
        InlineKeyboardButton(text="✅ Верно", callback_data="order_confirm"),
    ]]
)


@dp.message(OrderForm.phone, F.text)
async def get_phone(message: Message, state: FSMContext):
    phone = message.text.strip()
    await safe_delete(message)
    if sum(ch.isdigit() for ch in phone) < 10:
        await show(
            message.bot, message.chat.id, state,
            "📞 Укажите <b>контактный телефон</b>:\n\n"
            "⚠️ <i>Похоже, в номере не хватает цифр. "
            "Пример:</i> <code>+7 900 123-45-67</code>",
        )
        return
    await state.update_data(phone=phone)
    data = await state.get_data()
    letter, title, price = SIZES[data["size"]]
    await state.set_state(None)
    await show(
        message.bot, message.chat.id, state,
        "🧾 <b>Спасибо! Ваш заказ:</b>\n\n"
        f"📏 Размер: <b>{letter}</b> ({title})\n"
        f"🎨 Цвет: <b>№{esc(data['color'])}</b>\n"
        f"📦 Доставка: <b>{esc(data['delivery'])}</b>\n"
        f"📍 Адрес ПВЗ: {esc(data['address'])}\n"
        f"👤 ФИО: {esc(data['full_name'])}\n"
        f"📞 Телефон: <code>{esc(phone)}</code>\n\n"
        f"💰 Стоимость с доставкой по России: <b>{price}₽</b> 🎩",
        confirm_keyboard,
    )


@dp.callback_query(F.data == "order_cancel")
async def order_cancel(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await safe_edit(callback.message, "❌ <b>Заказ отменён.</b>")
    await callback.answer()


@dp.callback_query(F.data == "order_confirm")
async def order_confirm(callback: CallbackQuery, state: FSMContext):
    data = await state.get_data()
    if "size" not in data:
        await callback.answer("Заказ не найден, начните заново.", show_alert=True)
        return
    price = SIZES[data["size"]][2]
    await state.set_state(OrderForm.receipt)
    await state.update_data(prompt_id=callback.message.message_id)
    await show(
        callback.bot, callback.message.chat.id, state,
        "💳 <b>Переход к оплате</b>\n\n"
        f"Сумма к оплате: <b>{price}₽</b>\n"
        "Номер: <code>89151061168</code>\n"
        "Банк: <b>Альфа-Банк</b>\n\n"
        "<blockquote>⚠️ Отправив не на тот банк, есть шанс, что деньги сгорят "
        "и их не вернуть, но мы всегда постараемся помочь вам с любой "
        "проблемой.</blockquote>\n\n"
        "📎 <i>После оплаты пришлите чек.</i>",
    )
    await callback.answer()


@dp.message(OrderForm.receipt, F.photo | F.document)
async def get_receipt(message: Message, state: FSMContext):
    form = await state.get_data()
    if message.photo:
        receipt_type = "photo"
        receipt_id = message.photo[-1].file_id
    else:
        receipt_type = "document"
        receipt_id = message.document.file_id
    letter, title, price = SIZES[form["size"]]
    data = load_data()
    order_id = data["next_id"]
    data["next_id"] = order_id + 1
    data["orders"][str(order_id)] = {
        "id": order_id,
        "user_id": message.from_user.id,
        "size": f"{letter} ({title})",
        "color": form["color"],
        "delivery": form["delivery"],
        "address": form["address"],
        "full_name": form["full_name"],
        "phone": form["phone"],
        "price": price,
        "receipt_type": receipt_type,
        "receipt_id": receipt_id,
        "status": "pending",
    }
    save_data(data)
    await show(
        message.bot, message.chat.id, state,
        "✅ <b>Отлично!</b> Ваши данные и чек уже отправлены на модерацию.\n\n"
        "<i>После того как модерация проверит оплату, вам напишут — "
        "ожидайте.</i> ⏳",
    )
    await state.clear()
    await message.bot.send_message(
        ADMIN_ID, f"🔔 <b>Новый заказ №{order_id}</b>"
    )


@dp.message(OrderForm.receipt)
async def receipt_wrong(message: Message):
    await message.answer("📎 <b>Пришлите чек</b> фото или файлом.")


# ---------- админка ----------

def order_text(order):
    return (
        f"🧾 <b>Заказ №{order['id']}</b>\n\n"
        f"📏 Размер: <b>{esc(order['size'])}</b>\n"
        f"🎨 Цвет: <b>№{esc(order['color'])}</b>\n"
        f"📦 Доставка: <b>{esc(order['delivery'])}</b>\n"
        f"📍 Адрес ПВЗ: {esc(order['address'])}\n"
        f"👤 ФИО: {esc(order['full_name'])}\n"
        f"📞 Телефон: <code>{esc(order['phone'])}</code>\n"
        f"💰 Сумма: <b>{order['price']}₽</b>"
    )


async def send_order(message, order, keyboard):
    if order["receipt_type"] == "photo":
        await message.answer_photo(
            order["receipt_id"], caption=order_text(order), reply_markup=keyboard
        )
    else:
        await message.answer_document(
            order["receipt_id"], caption=order_text(order), reply_markup=keyboard
        )


back_row = [InlineKeyboardButton(text="⬅️ Назад", callback_data="admin_back")]


def orders_keyboard(status, prefix):
    data = load_data()
    orders = [o for o in data["orders"].values() if o["status"] == status]
    if not orders:
        return None
    rows = [
        [InlineKeyboardButton(
            text=f"Заказ №{o['id']} — {o['full_name']}",
            callback_data=f"{prefix}{o['id']}",
        )]
        for o in orders
    ]
    rows.append(back_row)
    return InlineKeyboardMarkup(inline_keyboard=rows)


back_keyboard = InlineKeyboardMarkup(inline_keyboard=[back_row])


def admin_panel_text():
    data = load_data()
    active = sum(1 for o in data["orders"].values() if o["status"] == "paid")
    return (
        "🛠 <b>Админ панель</b>\n\n"
        f"📦 Активных заказов: <b>{active}</b>\n"
        f"👥 Пользователей в боте: <b>{len(data['users'])}</b>"
    )


admin_keyboard = InlineKeyboardMarkup(
    inline_keyboard=[
        [
            InlineKeyboardButton(text="📋 Заказы", callback_data="admin_orders"),
            InlineKeyboardButton(
                text="📦 Активные заказы", callback_data="admin_active"
            ),
        ],
        [InlineKeyboardButton(text="👥 Пользователи", callback_data="admin_users")],
    ]
)


@dp.message(F.text == "Админ панель", is_admin)
async def admin_panel(message: Message, state: FSMContext):
    await state.clear()
    await message.answer(admin_panel_text(), reply_markup=admin_keyboard)


@dp.callback_query(F.data == "admin_back", is_admin)
async def admin_back(callback: CallbackQuery):
    await safe_edit(callback.message, admin_panel_text(), admin_keyboard)
    await callback.answer()


@dp.callback_query(F.data == "admin_orders", is_admin)
async def admin_orders(callback: CallbackQuery):
    keyboard = orders_keyboard("pending", "order_view_")
    if keyboard is None:
        await safe_edit(callback.message, "📭 <b>Заказов нет.</b>", back_keyboard)
    else:
        await safe_edit(callback.message, "📋 <b>Заказы:</b>", keyboard)
    await callback.answer()


@dp.callback_query(F.data == "admin_active", is_admin)
async def admin_active(callback: CallbackQuery):
    keyboard = orders_keyboard("paid", "active_view_")
    if keyboard is None:
        await safe_edit(
            callback.message, "📭 <b>Активных заказов нет.</b>", back_keyboard
        )
    else:
        await safe_edit(callback.message, "📦 <b>Активные заказы:</b>", keyboard)
    await callback.answer()


@dp.callback_query(F.data == "admin_users", is_admin)
async def admin_users(callback: CallbackQuery):
    data = load_data()
    if not data["users"]:
        await safe_edit(callback.message, "📭 <b>Пользователей нет.</b>", back_keyboard)
        await callback.answer()
        return
    lines = []
    for i, (uid, u) in enumerate(data["users"].items(), 1):
        username = f" @{esc(u['username'])}" if u.get("username") else ""
        lines.append(f"{i}. {esc(u['name'])}{username} — <code>{uid}</code>")
    await safe_edit(
        callback.message,
        "👥 <b>Пользователи:</b>\n\n" + "\n".join(lines),
        back_keyboard,
    )
    await callback.answer()


@dp.callback_query(F.data.startswith("order_view_"), is_admin)
async def order_view(callback: CallbackQuery):
    order_id = callback.data.removeprefix("order_view_")
    order = load_data()["orders"].get(order_id)
    if not order:
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="✅ Оплатил", callback_data=f"order_paid_{order['id']}"
            ),
            InlineKeyboardButton(
                text="❌ Не оплатил", callback_data=f"order_unpaid_{order['id']}"
            ),
        ]]
    )
    await send_order(callback.message, order, keyboard)
    await callback.answer()


async def resolve_order(
    callback: CallbackQuery, order_id, status, client_text, label
):
    data = load_data()
    order = data["orders"].get(order_id)
    if not order or order["status"] != "pending":
        await callback.answer("Заказ уже обработан.", show_alert=True)
        return
    order["status"] = status
    save_data(data)
    await safe_edit(callback.message, f"{order_text(order)}\n\n{label}")
    await callback.bot.send_message(order["user_id"], client_text)
    await callback.answer("Готово")


@dp.callback_query(F.data.startswith("order_paid_"), is_admin)
async def order_paid(callback: CallbackQuery):
    await resolve_order(
        callback,
        callback.data.removeprefix("order_paid_"),
        "paid",
        "🌸 <b>Модерация проверила заказ.</b>\n\n"
        "Спасибо за заказ! Скоро он будет готов и отправится к вам.\n"
        "<i>Удачного дня!</i> ✨",
        "✅ <b>Оплачен</b>",
    )


@dp.callback_query(F.data.startswith("order_unpaid_"), is_admin)
async def order_unpaid(callback: CallbackQuery):
    await resolve_order(
        callback,
        callback.data.removeprefix("order_unpaid_"),
        "unpaid",
        "❌ <b>Оплата не поступила.</b>\n\n"
        "<i>Если вы уверены, что оплатили заказ, напишите нам.</i>",
        "❌ <b>Не оплачен</b>",
    )


@dp.callback_query(F.data.startswith("active_view_"), is_admin)
async def active_view(callback: CallbackQuery):
    order_id = callback.data.removeprefix("active_view_")
    order = load_data()["orders"].get(order_id)
    if not order or order["status"] != "paid":
        await callback.answer("Заказ не найден.", show_alert=True)
        return
    keyboard = InlineKeyboardMarkup(
        inline_keyboard=[[
            InlineKeyboardButton(
                text="📬 Поступило", callback_data=f"active_done_{order['id']}"
            ),
            InlineKeyboardButton(
                text="✉️ Написать", callback_data=f"active_write_{order['id']}"
            ),
            InlineKeyboardButton(
                text="🚫 Отмена", callback_data=f"active_cancel_{order['id']}"
            ),
        ]]
    )
    await send_order(callback.message, order, keyboard)
    await callback.answer()


async def close_active(callback: CallbackQuery, order_id, status, label):
    data = load_data()
    order = data["orders"].get(order_id)
    if not order or order["status"] != "paid":
        await callback.answer("Заказ уже обработан.", show_alert=True)
        return
    order["status"] = status
    save_data(data)
    await safe_edit(callback.message, f"{order_text(order)}\n\n{label}")
    await callback.answer("Готово")


@dp.callback_query(F.data.startswith("active_done_"), is_admin)
async def active_done(callback: CallbackQuery):
    await close_active(
        callback, callback.data.removeprefix("active_done_"), "done",
        "📬 <b>Поступило</b>",
    )


@dp.callback_query(F.data.startswith("active_cancel_"), is_admin)
async def active_cancel(callback: CallbackQuery):
    await close_active(
        callback, callback.data.removeprefix("active_cancel_"), "canceled",
        "🚫 <b>Отменён</b>",
    )


@dp.callback_query(F.data.startswith("active_write_"), is_admin)
async def active_write(callback: CallbackQuery, state: FSMContext):
    order_id = callback.data.removeprefix("active_write_")
    await state.set_state(AdminForm.write)
    await state.update_data(write_order_id=order_id)
    await callback.message.answer(
        "✉️ <b>Отправьте всё одним сообщением или фото</b> — оно уйдёт "
        "пользователю."
    )
    await callback.answer()


@dp.message(AdminForm.write, is_admin)
async def admin_write(message: Message, state: FSMContext):
    form = await state.get_data()
    order = load_data()["orders"].get(form.get("write_order_id"))
    await state.clear()
    if not order:
        await message.answer("⚠️ Заказ не найден.")
        return
    await message.copy_to(order["user_id"])
    await message.answer("✅ <b>Отправлено.</b>")


async def main():
    logging.basicConfig(level=logging.INFO)
    missing = [
        n for n in PHOTOS + [COLORS_PHOTO] if not (PHOTOS_DIR / n).exists()
    ]
    if missing:
        raise SystemExit(
            f"Не найдены фото: {missing}. Положите их в папку {PHOTOS_DIR}"
        )
    bot = Bot(
        token=TOKEN,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
