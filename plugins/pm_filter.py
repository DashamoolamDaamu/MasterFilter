# Kanged From @TroJanZheX
#hyper link mode by mn-bots
import asyncio
import re
import ast
import math
from pyrogram.errors.exceptions.bad_request_400 import MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty
from Script import script
import pyrogram
from database.connections_mdb import active_connection, all_connections, delete_connection, if_active, make_active, \
    make_inactive
from info import (
    ADMINS, AUTH_USERS, CUSTOM_FILE_CAPTION, AUTH_GROUPS, P_TTI_SHOW_OFF, IMDB,
    SINGLE_BUTTON, SPELL_CHECK_REPLY, IMDB_TEMPLATE, DATABASE_URI, DATABASE_URI2, DATABASE_URI3, DATABASE_URI4, DATABASE_URI5,
    POSTGRES_STORAGE_LIMIT_BYTES, DELETE_USER_SEARCH_MESSAGE, PM_SEARCH_GROUP_LINK, PM_SEARCH_REDIRECT_TEXT,
)
from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram import Client, filters, enums
from pyrogram.errors import FloodWait, UserIsBlocked, MessageNotModified, PeerIdInvalid
from utils import get_size, is_subscribed, get_poster, search_gagala, temp, get_settings, save_group_settings, create_invite_links
from database.users_chats_db import db
from info import HYPER_MODE
from database.ia_filterdb import Media, get_file_details, get_search_results
from database.filters_mdb import (
    del_all,
    find_filter,
    get_filters,
)
import logging

logger = logging.getLogger(__name__)
logger.setLevel(logging.ERROR)

BUTTONS = {}
MONGO_DB_CAP_BYTES = 536870912
MONGO_DB_COUNT = len([u for u in (DATABASE_URI, DATABASE_URI2, DATABASE_URI3, DATABASE_URI4, DATABASE_URI5) if u])
SPELL_CHECK = {}

# ─── Filter State ─────────────────────────────────────────────────────────────
# Keyed by the message key ("{chat_id}-{msg_id}").
# Values: {"lang": str|None, "qual": str|None, "s": str|None, "ep": str|None}
# Also caches the full result set so filters apply without re-querying.
# {"lang":..., "qual":..., "s":..., "ep":..., "search": str, "all_files": list}
FILTER_STATE: dict = {}

# Language short-code → display name (matches new_updates.py LANG_MAP)
_LANG_MAP = {
    "mal": "Malayalam", "eng": "English", "tam": "Tamil",
    "hin": "Hindi",     "kan": "Kannada", "tel": "Telugu",
}




# ─── Filter helpers ───────────────────────────────────────────────────────────

def _detect_language(file_name: str) -> str | None:
    """Return the display-name of the language detected in the filename."""
    low = file_name.lower()
    found = [v for k, v in _LANG_MAP.items() if re.search(rf"\b{k}\b", low)]
    return found[0] if found else None          # return first match only


def _extract_quality(file_name: str) -> str | None:
    m = re.search(r"\b(2160p|4K|1080p|720p|480p|HQ|HD)\b", file_name, re.I)
    return m.group(1).upper() if m else None


def _parse_season(file_name: str) -> str | None:
    """Return zero-padded season number or None."""
    m = re.search(
        r"\b(?:S(\d{1,2})|Season[\s\-_]*(\d{1,2}))\b",
        file_name, re.I
    )
    if m:
        n = m.group(1) or m.group(2)
        return n.zfill(2)
    return None


def _parse_episode(file_name: str) -> str | None:
    """Return zero-padded episode number or None."""
    # SxxExx  /  Exx  /  EPxx  /  EP xx  /  Episode xx  /  Episode-xx
    m = re.search(
        r"\b(?:S\d{1,2}E(\d{1,3})|E(?:P)?[\s\-_]*(\d{1,3})|Episode[\s\-_]*(\d{1,3}))\b",
        file_name, re.I
    )
    if m:
        n = m.group(1) or m.group(2) or m.group(3)
        return n.zfill(2)
    return None


def _apply_filters(files: list, state: dict) -> list:
    """Filter a list of file objects by the active FILTER_STATE values."""
    lang = state.get("lang")
    qual = state.get("qual")
    season = state.get("s")
    ep = state.get("ep")
    out = []
    for f in files:
        name = f.file_name or ""
        if lang and _detect_language(name) != lang:
            continue
        if qual and (_extract_quality(name) or "").upper() != qual.upper():
            continue
        if season and _parse_season(name) != season.zfill(2):
            continue
        if ep and _parse_episode(name) != ep.zfill(2):
            continue
        out.append(f)
    return out


def _extract_filter_meta(files: list) -> dict:
    """Scan files and return available distinct filter values."""
    langs, quals, seasons, eps = set(), set(), set(), set()
    for f in files:
        name = f.file_name or ""
        lang = _detect_language(name)
        qual = _extract_quality(name)
        s    = _parse_season(name)
        ep   = _parse_episode(name)
        if lang:    langs.add(lang)
        if qual:    quals.add(qual.upper())
        if s:       seasons.add(s)
        if ep:      eps.add(ep)
    return {
        "langs":   sorted(langs),
        "quals":   sorted(quals),
        "seasons": sorted(seasons),
        "eps":     sorted(eps),
    }


def _build_filter_buttons(key: str, req: int, offset: int,
                          meta: dict, state: dict) -> list:
    """
    Build the 2-row filter keyboard:
        Row 1: Language ▼   Quality ▼
        Row 2: Season ▼     Episode ▼
    Active selections shown in button label.
    Buttons only shown when there are options to pick from.
    """
    cur_lang   = state.get("lang")
    cur_qual   = state.get("qual")
    cur_season = state.get("s")
    cur_ep     = state.get("ep")

    def _lbl(prefix, cur, has_options):
        if not has_options and not cur:
            return None
        if cur:
            return f"{prefix}: {cur} ▼"
        return f"{prefix} ▼"

    lang_lbl   = _lbl("🌐 Language", cur_lang,   bool(meta["langs"]))
    qual_lbl   = _lbl("🎬 Quality",  cur_qual,   bool(meta["quals"]))
    seas_lbl   = _lbl("📺 Season",   cur_season, bool(meta["seasons"]))
    ep_lbl     = _lbl("▶ Episode",  cur_ep,     bool(meta["eps"]))

    row1, row2 = [], []
    if lang_lbl:
        row1.append(InlineKeyboardButton(lang_lbl,
            callback_data=f"flt_{req}_{key}_L"))
    if qual_lbl:
        row1.append(InlineKeyboardButton(qual_lbl,
            callback_data=f"flt_{req}_{key}_Q"))
    if seas_lbl:
        row2.append(InlineKeyboardButton(seas_lbl,
            callback_data=f"flt_{req}_{key}_S"))
    if ep_lbl:
        row2.append(InlineKeyboardButton(ep_lbl,
            callback_data=f"flt_{req}_{key}_E"))

    rows = []
    if row1: rows.append(row1)
    if row2: rows.append(row2)
    return rows


def _build_file_buttons(files: list, pre: str, settings: dict) -> list:
    """Build the clickable file-list rows (existing layout, untouched)."""
    if settings.get("button"):
        return [
            [InlineKeyboardButton(
                text=f"📂[{get_size(f.file_size)}]--{f.file_name}",
                callback_data=f"{pre}#{f.file_id}")]
            for f in files
        ]
    return [
        [
            InlineKeyboardButton(f.file_name,
                callback_data=f"{pre}#{f.file_id}"),
            InlineKeyboardButton(get_size(f.file_size),
                callback_data=f"{pre}#{f.file_id}"),
        ]
        for f in files
    ]


def _build_pagination_row(req: int, key: str, offset: int,
                          total: int) -> list:
    """Build [◀ Prev | Page X/Y | Next ▶] row."""
    page   = math.ceil(offset / 10)           # 0-indexed
    pages  = max(math.ceil(total / 10), 1)
    prev_o = max(offset - 10, 0)
    next_o = offset + 10

    row = []
    if offset > 0:
        row.append(InlineKeyboardButton(
            "◀ Prev", callback_data=f"next_{req}_{key}_{prev_o}"))
    row.append(InlineKeyboardButton(
        f"📃 {page + 1} / {pages}", callback_data="pages"))
    if next_o < total:
        row.append(InlineKeyboardButton(
            "Next ▶", callback_data=f"next_{req}_{key}_{next_o}"))
    return row


async def _get_or_cache_all_files(key: str, search: str) -> list:
    """
    Fetch ALL results for `search` and cache them in FILTER_STATE[key].
    Returns the full (unfiltered) file list.
    """
    state = FILTER_STATE.get(key, {})
    if "all_files" not in state:
        # Fetch up to 10 000 files — enough for any realistic query
        all_files, _, _, _ = await get_search_results(
            search, offset=0, max_results=10_000,
            filter=True, fast=False, return_time=True
        )
        state["all_files"] = all_files
        state.setdefault("lang",   None)
        state.setdefault("qual",   None)
        state.setdefault("s",      None)
        state.setdefault("ep",     None)
        state.setdefault("search", search)
        FILTER_STATE[key] = state
    return state["all_files"]


async def _render_filter_page(
    key: str, req: int, offset: int,
    settings: dict, pre: str,
    hyper_mode: bool = False
) -> tuple[list, int]:
    """
    Apply active filters, slice to the current page, and return
    (inline_keyboard_rows, total_filtered_count).
    """
    state     = FILTER_STATE.get(key, {})
    all_files = state.get("all_files", [])
    filtered  = _apply_filters(all_files, state)
    total     = len(filtered)

    page_files = filtered[offset: offset + 10]
    meta       = _extract_filter_meta(filtered)

    if hyper_mode:
        btn = []
    else:
        btn = _build_file_buttons(page_files, pre, settings)

    # Filter buttons
    filter_rows = _build_filter_buttons(key, req, offset, meta, state)
    btn.extend(filter_rows)

    # Pagination row
    if total > 0:
        pag_row = _build_pagination_row(req, key, offset, total)
        if pag_row:
            btn.append(pag_row)
    else:
        btn.append([InlineKeyboardButton("📃 0 / 0", callback_data="pages")])

    return btn, total, page_files


async def _delete_user_search_message(message):
    if not DELETE_USER_SEARCH_MESSAGE:
        return
    try:
        await message.delete()
    except Exception:
        logger.exception("Failed to delete user search message")


async def _send_pm_search_redirect(message):
    text = PM_SEARCH_REDIRECT_TEXT.format(group_link=PM_SEARCH_GROUP_LINK)
    buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("👇 Join / Open Group", url=PM_SEARCH_GROUP_LINK)
    ]])
    await message.reply_text(
        text=text,
        reply_markup=buttons,
        disable_web_page_preview=True,
    )


@Client.on_message((filters.group | filters.private) & filters.text & filters.incoming)
async def give_filter(client, message):
    if message.text and message.text.startswith("/"):
        return

    if message.chat.type == enums.ChatType.PRIVATE:
        await _send_pm_search_redirect(message)
        await _delete_user_search_message(message)
        return

    k = await manual_filters(client, message)
    if k == False:
        await auto_filter(client, message)
    await _delete_user_search_message(message)

@Client.on_callback_query(filters.regex(r"^next"))
async def next_page(bot, query):
    parts = query.data.split("_")
    # Format: next_{req}_{key}_{offset}
    ident, req, key, offset = parts[0], parts[1], parts[2], parts[3]
    if int(req) not in [query.from_user.id, 0]:
        return await query.answer("**Search for Yourself**🔎", show_alert=True)

    try:
        offset = int(offset)
    except Exception:
        offset = 0

    search = BUTTONS.get(key)
    if not search:
        await query.answer(script.OLD_MES, show_alert=True)
        return

    # Ensure the full result set is cached
    await _get_or_cache_all_files(key, search)

    settings = await get_settings(query.message.chat.id)
    pre      = "filep" if settings.get("file_secure") else "file"

    if HYPER_MODE:
        state     = FILTER_STATE.get(key, {})
        all_files = state.get("all_files", [])
        filtered  = _apply_filters(all_files, state)
        page_files = filtered[offset: offset + 10]
        cap_lines  = []
        for f in page_files:
            file_link = f"https://t.me/{temp.U_NAME}?start={pre}_{f.file_id}"
            cap_lines.append(f"📁 {get_size(f.file_size)} - [{f.file_name}]({file_link})")
        cap_text = "\n".join(cap_lines)

        btn, total, _ = await _render_filter_page(key, int(req), offset,
                                                   settings, pre, hyper_mode=True)
        try:
            await query.edit_message_text(
                text=cap_text,
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        except MessageNotModified:
            pass
    else:
        btn, total, page_files = await _render_filter_page(
            key, int(req), offset, settings, pre)
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn))
        except MessageNotModified:
            pass

    await query.answer()


# ─── Filter open — show picker buttons ───────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^flt_"))
async def filter_open(bot, query):
    """
    Show the available values for the selected filter type.
    callback_data: flt_{req}_{key}_{ftype}
    ftype: L=Language, Q=Quality, S=Season, E=Episode
    """
    _, req, key, ftype = query.data.split("_", 3)
    if int(req) not in [query.from_user.id, 0]:
        return await query.answer("Search for yourself 🔎", show_alert=True)

    state     = FILTER_STATE.get(key)
    if not state:
        return await query.answer(script.OLD_MES, show_alert=True)

    all_files = state.get("all_files", [])
    filtered  = _apply_filters(all_files, {k: v for k, v in state.items()
                                            if k not in ("all_files", "search", ftype.lower() if ftype != "ftype" else ftype)})
    meta      = _extract_filter_meta(all_files)   # options from full set

    type_map = {
        "L": ("🌐 Language",  "langs",   "lang"),
        "Q": ("🎬 Quality",   "quals",   "qual"),
        "S": ("📺 Season",    "seasons", "s"),
        "E": ("▶ Episode",   "eps",     "ep"),
    }
    if ftype not in type_map:
        return await query.answer("Unknown filter type", show_alert=True)

    label, meta_key, state_key = type_map[ftype]
    options = meta[meta_key]
    cur     = state.get(state_key)

    if not options:
        return await query.answer("No options available for this filter.", show_alert=True)

    # Build picker rows — mark currently selected option
    picker_rows = []
    for opt in options:
        text = f"✅ {opt}" if opt == cur else opt
        picker_rows.append([InlineKeyboardButton(
            text, callback_data=f"fpk_{req}_{key}_{ftype}_{opt}")])

    # Add "Clear" option if one is active
    if cur:
        picker_rows.append([InlineKeyboardButton(
            f"✖ Clear {label}", callback_data=f"fpk_{req}_{key}_{ftype}_CLEAR")])

    await query.answer()
    try:
        await query.edit_message_reply_markup(
            reply_markup=InlineKeyboardMarkup(picker_rows))
    except MessageNotModified:
        pass


# ─── Filter value picked ──────────────────────────────────────────────────────

@Client.on_callback_query(filters.regex(r"^fpk_"))
async def filter_pick(bot, query):
    """
    User has selected (or cleared) a filter value.
    callback_data: fpk_{req}_{key}_{ftype}_{value}
    """
    parts = query.data.split("_", 4)
    _, req, key, ftype, value = parts
    if int(req) not in [query.from_user.id, 0]:
        return await query.answer("Search for yourself 🔎", show_alert=True)

    state = FILTER_STATE.get(key)
    if not state:
        return await query.answer(script.OLD_MES, show_alert=True)

    type_map = {"L": "lang", "Q": "qual", "S": "s", "E": "ep"}
    if ftype not in type_map:
        return await query.answer("Unknown filter type", show_alert=True)

    state_key = type_map[ftype]
    if value == "CLEAR":
        state[state_key] = None
    else:
        state[state_key] = value
    FILTER_STATE[key] = state

    # Re-render page 1 with the new filter applied
    settings = await get_settings(query.message.chat.id)
    pre      = "filep" if settings.get("file_secure") else "file"
    offset   = 0

    if HYPER_MODE:
        all_files  = state.get("all_files", [])
        filtered   = _apply_filters(all_files, state)
        page_files = filtered[:10]
        cap_lines  = []
        for f in page_files:
            file_link = f"https://t.me/{temp.U_NAME}?start={pre}_{f.file_id}"
            cap_lines.append(f"📁 {get_size(f.file_size)} - [{f.file_name}]({file_link})")
        cap_text = "\n".join(cap_lines) or "No results match these filters."

        btn, total, _ = await _render_filter_page(
            key, int(req), offset, settings, pre, hyper_mode=True)
        try:
            await query.edit_message_text(
                text=cap_text,
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.MARKDOWN,
                disable_web_page_preview=True,
            )
        except MessageNotModified:
            pass
    else:
        btn, total, page_files = await _render_filter_page(
            key, int(req), offset, settings, pre)
        try:
            await query.edit_message_reply_markup(
                reply_markup=InlineKeyboardMarkup(btn))
        except MessageNotModified:
            pass

    ftype_names = {"L": "Language", "Q": "Quality", "S": "Season", "E": "Episode"}
    if value == "CLEAR":
        await query.answer(f"{ftype_names.get(ftype, ftype)} filter cleared.")
    else:
        await query.answer(f"Filtered by {value}")




@Client.on_callback_query(filters.regex(r"^spol")) 
async def advantage_spoll_choker(bot, query):
    _, user, movie_ = query.data.split('#')
    if int(user) != 0 and query.from_user.id != int(user):
        return await query.answer("Search for Yourself🔎", show_alert=True)
    if movie_ == "close_spellcheck":
        return await query.message.delete()
    movies = SPELL_CHECK.get(query.message.reply_to_message.id)
    if not movies:
        return await query.answer(script.OLD_MES, show_alert=True)#script change
    movie = movies[(int(movie_))]
    await query.answer(script.CHK_MOV_ALRT)#script change
    k = await manual_filters(bot, query.message, text=movie)
    if k == False:
        files, offset, total_results, search_time = await get_search_results(
            movie, offset=0, filter=True, fast=True, return_time=True
        )
        if files:
            k = (movie, files, offset, total_results, search_time)
            await auto_filter(bot, query, k)
        else:
            k = await query.message.edit(script.MOV_NT_FND)#script change
            await asyncio.sleep(10)
            await k.delete()


@Client.on_callback_query()
async def cb_handler(client: Client, query: CallbackQuery):
    if query.data == "close_data":
        await query.message.delete()
    elif query.data == "delallconfirm":
        userid = query.from_user.id
        chat_type = query.message.chat.type

        if chat_type == enums.ChatType.PRIVATE:
            grpid = await active_connection(str(userid))
            if grpid is not None:
                grp_id = grpid
                try:
                    chat = await client.get_chat(grpid)
                    title = chat.title
                except:
                    await query.message.edit_text("Make sure I'm present in your group!!", quote=True)
                    return await query.answer('Piracy Is Crime')
            else:
                await query.message.edit_text(
                    "I'm not connected to any groups!\nCheck /connections or connect to any groups",
                    quote=True
                )
                return await query.answer('THIS IS A OPEN SOURCE PROJECT SEARCH SHOBANAFILTERBOT IN GITHUB ')

        elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            grp_id = query.message.chat.id
            title = query.message.chat.title

        else:
            return await query.answer('Piracy Is Crime')

        st = await client.get_chat_member(grp_id, userid)
        if (st.status == enums.ChatMemberStatus.OWNER) or (str(userid) in ADMINS):
            await del_all(query.message, grp_id, title)
        else:
            await query.answer("You need to be Group Owner or an Auth User to do that!", show_alert=True)
    elif query.data == "delallcancel":
        userid = query.from_user.id
        chat_type = query.message.chat.type

        if chat_type == enums.ChatType.PRIVATE:
            await query.message.reply_to_message.delete()
            await query.message.delete()

        elif chat_type in [enums.ChatType.GROUP, enums.ChatType.SUPERGROUP]:
            grp_id = query.message.chat.id
            st = await client.get_chat_member(grp_id, userid)
            if (st.status == enums.ChatMemberStatus.OWNER) or (str(userid) in ADMINS):
                await query.message.delete()
                try:
                    await query.message.reply_to_message.delete()
                except:
                    pass
            else:
                await query.answer("That's not for you!!", show_alert=True)
    elif "groupcb" in query.data:
        await query.answer()

        group_id = query.data.split(":")[1]

        act = query.data.split(":")[2]
        hr = await client.get_chat(int(group_id))
        title = hr.title
        user_id = query.from_user.id

        if act == "":
            stat = "CONNECT"
            cb = "connectcb"
        else:
            stat = "DISCONNECT"
            cb = "disconnect"

        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton(f"{stat}", callback_data=f"{cb}:{group_id}"),
             InlineKeyboardButton("DELETE", callback_data=f"deletecb:{group_id}")],
            [InlineKeyboardButton("BACK", callback_data="backcb")]
        ])

        await query.message.edit_text(
            f"Group Name : **{title}**\nGroup ID : `{group_id}`",
            reply_markup=keyboard,
            parse_mode=enums.ParseMode.MARKDOWN
        )
        return await query.answer('Piracy Is Crime')
    elif "connectcb" in query.data:
        await query.answer()

        group_id = query.data.split(":")[1]

        hr = await client.get_chat(int(group_id))

        title = hr.title

        user_id = query.from_user.id

        mkact = await make_active(str(user_id), str(group_id))

        if mkact:
            await query.message.edit_text(
                f"Connected to **{title}**",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:
            await query.message.edit_text('Some error occurred!!', parse_mode=enums.ParseMode.MARKDOWN)
        return await query.answer('Piracy Is Crime')
    elif "disconnect" in query.data:
        await query.answer()

        group_id = query.data.split(":")[1]

        hr = await client.get_chat(int(group_id))

        title = hr.title
        user_id = query.from_user.id

        mkinact = await make_inactive(str(user_id))

        if mkinact:
            await query.message.edit_text(
                f"Disconnected from **{title}**",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        else:
            await query.message.edit_text(
                f"Some error occurred!!",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        return await query.answer('Piracy Is Crime')
    elif "deletecb" in query.data:
        await query.answer()

        user_id = query.from_user.id
        group_id = query.data.split(":")[1]

        delcon = await delete_connection(str(user_id), str(group_id))

        if delcon:
            await query.message.edit_text(
                "Successfully deleted connection"
            )
        else:
            await query.message.edit_text(
                f"Some error occurred!!",
                parse_mode=enums.ParseMode.MARKDOWN
            )
        return await query.answer('Piracy Is Crime')
    elif query.data == "backcb":
        await query.answer()

        userid = query.from_user.id

        groupids = await all_connections(str(userid))
        if groupids is None:
            await query.message.edit_text(
                "There are no active connections!! Connect to some groups first.",
            )
            return await query.answer('Piracy Is Crime')
        buttons = []
        for groupid in groupids:
            try:
                ttl = await client.get_chat(int(groupid))
                title = ttl.title
                active = await if_active(str(userid), str(groupid))
                act = " - ACTIVE" if active else ""
                buttons.append(
                    [
                        InlineKeyboardButton(
                            text=f"{title}{act}", callback_data=f"groupcb:{groupid}:{act}"
                        )
                    ]
                )
            except:
                pass
        if buttons:
            await query.message.edit_text(
                "Your connected group details ;\n\n",
                reply_markup=InlineKeyboardMarkup(buttons)
            )
    elif "alertmessage" in query.data:
        grp_id = query.message.chat.id
        i = query.data.split(":")[1]
        keyword = query.data.split(":")[2]
        reply_text, btn, alerts, fileid = await find_filter(grp_id, keyword)
        if alerts is not None:
            alerts = ast.literal_eval(alerts)
            alert = alerts[int(i)]
            alert = alert.replace("\\n", "\n").replace("\\t", "\t")
            await query.answer(alert, show_alert=True)
    if query.data.startswith("file"):
        ident, file_id = query.data.split("#")
        files_ = await get_file_details(file_id)
        if not files_:
            return await query.answer('No such file exist.')
        files = files_[0]
        title = files.file_name
        size = get_size(files.file_size)
        f_caption = files.caption
        settings = await get_settings(query.message.chat.id)
        if CUSTOM_FILE_CAPTION:
            try:
                f_caption = CUSTOM_FILE_CAPTION.format(file_name='' if title is None else title,
                                                       file_size='' if size is None else size,
                                                       file_caption='' if f_caption is None else f_caption)
            except Exception as e:
                logger.exception(e)
            f_caption = f_caption
        if f_caption is None:
            f_caption = f"{files.file_name}"

        try:
            if not await is_subscribed(query.from_user.id, client):
                invite_links = await create_invite_links(client)
                first_link = next(iter(invite_links.values()), f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
                await query.answer(url=first_link)
                return
            elif settings['botpm']:
                await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
                return
            else:
                await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
        except UserIsBlocked:
            await query.answer('Unblock the bot mahn !', show_alert=True)
        except PeerIdInvalid:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
        except Exception as e:
            await query.answer(url=f"https://t.me/{temp.U_NAME}?start={ident}_{file_id}")
    elif query.data.startswith("checksub"):
        if not await is_subscribed(query.from_user.id, client):
            await query.answer("I Like Your Smartness, But Don't Be Oversmart", show_alert=True)
            return
        ident, file_id = query.data.split("#")
        files_ = await get_file_details(file_id)
        if not files_:
            return await query.answer('No such file exist.')
        files = files_[0]
        title = files.file_name
        size = get_size(files.file_size)
        f_caption = files.caption
        if CUSTOM_FILE_CAPTION:
            try:
                f_caption = CUSTOM_FILE_CAPTION.format(file_name='' if title is None else title,
                                                       file_size='' if size is None else size,
                                                       file_caption='' if f_caption is None else f_caption)
            except Exception as e:
                logger.exception(e)
                f_caption = f_caption
        if f_caption is None:
            f_caption = f"{title}"
        await query.answer()
        await client.send_cached_media(
            chat_id=query.from_user.id,
            file_id=file_id,
            caption=f_caption,
            protect_content=True if ident == 'checksubp' else False
        )
    elif query.data == "pages":
        await query.answer()
#ALERT FN IN SPELL CHECK FOR LANGAUGES TO KNOW HOW TO TYPE MOVIES esp english spell check goto adv spell check to check donot change the codes      
    elif query.data == "esp":
        await query.answer(text=script.ENG_SPELL, show_alert="true")
    elif query.data == "msp":
        await query.answer(text=script.MAL_SPELL, show_alert="true")
    elif query.data == "hsp":
        await query.answer(text=script.HIN_SPELL, show_alert="true")
    elif query.data == "tsp":
        await query.answer(text=script.TAM_SPELL, show_alert="true")
        
    elif query.data == "start":
        buttons = [[
            InlineKeyboardButton('ᴀᴅᴅ ᴍᴇ ᴛᴏ ʏᴏᴜʀ ɢʀᴏᴜᴘs', url=f'http://t.me/{temp.U_NAME}?startgroup=true')
            ],[
            InlineKeyboardButton('ʜᴇʟᴘ', callback_data='help'),
            InlineKeyboardButton('ᴀʙᴏᴜᴛ', callback_data='about')
        ],[
             InlineKeyboardButton(f'ᴏᴛᴛ ᴜᴘᴅᴀᴛᴇs​', url='https://t.me/new_ott_movies3'),
             InlineKeyboardButton(f'ᴍᴀɪɴ ᴄʜᴀɴɴᴇʟ', url='https://t.me/mn_movies2')
         ],[
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
            ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.START_TXT.format(query.from_user.mention, temp.U_NAME, temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
        await query.answer('Piracy Is Crime')
    elif query.data == "help":
        buttons = [[
            InlineKeyboardButton('◀️ Pʀᴇᴠ', callback_data='help_page_5'),
            InlineKeyboardButton('1/6', callback_data='pages'),
            InlineKeyboardButton('Nᴇxᴛ ▶️', callback_data='help_page_1')
        ], [
            InlineKeyboardButton('Mᴀɴᴜᴀʟ Fɪʟᴛᴇʀ', callback_data='manuelfilter'),
            InlineKeyboardButton('Aᴜᴛᴏ Fɪʟᴛᴇʀ', callback_data='autofilter')
        ], [
            InlineKeyboardButton('Cᴏɴɴᴇᴄᴛɪᴏɴ', callback_data='coct'),
            InlineKeyboardButton('Exᴛʀᴀ Tʜɪɴɢs', callback_data='extra')
        ], [
            InlineKeyboardButton('Hᴏᴍᴇ', callback_data='start'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=f"{script.HELP_TXT.format(query.from_user.mention)}\n\n{script.HELP_PAGES[0]}",
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data.startswith("help_page_"):
        try:
            page = int(query.data.rsplit("_", 1)[1])
        except ValueError:
            return await query.answer("Invalid help page", show_alert=True)

        total_pages = len(script.HELP_PAGES)
        if page < 0 or page >= total_pages:
            return await query.answer("Invalid help page", show_alert=True)

        prev_page = (page - 1) % total_pages
        next_page = (page + 1) % total_pages

        buttons = [[
            InlineKeyboardButton('◀️ Pʀᴇᴠ', callback_data=f'help_page_{prev_page}'),
            InlineKeyboardButton(f'{page + 1}/{total_pages}', callback_data='pages'),
            InlineKeyboardButton('Nᴇxᴛ ▶️', callback_data=f'help_page_{next_page}')
        ], [
            InlineKeyboardButton('Mᴀɴᴜᴀʟ Fɪʟᴛᴇʀ', callback_data='manuelfilter'),
            InlineKeyboardButton('Aᴜᴛᴏ Fɪʟᴛᴇʀ', callback_data='autofilter')
        ], [
            InlineKeyboardButton('Cᴏɴɴᴇᴄᴛɪᴏɴ', callback_data='coct'),
            InlineKeyboardButton('Exᴛʀᴀ Tʜɪɴɢs', callback_data='extra')
        ], [
            InlineKeyboardButton('Hᴏᴍᴇ', callback_data='start'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=f"{script.HELP_TXT.format(query.from_user.mention)}\n\n{script.HELP_PAGES[page]}",
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "about":
        buttons = [[
            InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='start'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
            ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.ABOUT_TXT.format(temp.B_NAME),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "source":
        buttons = [[
            InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='about'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.SOURCE_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "manuelfilter":
        buttons = [[
            InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='help'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot'),
            InlineKeyboardButton('ʙᴜᴛᴛᴏɴ', callback_data='button')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.MANUELFILTER_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "button":
        buttons = [[
           InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='help'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.BUTTON_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "autofilter":
        buttons = [[
           InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='help'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.AUTOFILTER_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "coct":
        buttons = [[
             InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='help'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.CONNECTION_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "extra":
        buttons = [[
            InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='help'),
            InlineKeyboardButton('ᴀᴅᴍɪɴ', callback_data='admin'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.EXTRAMOD_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "admin":
        buttons = [[
            InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='help'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        await query.message.edit_text(
            text=script.ADMIN_TXT,
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "stats":
        buttons = [[
            InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='help'),
            InlineKeyboardButton('♻️', callback_data='rfrsh'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        total = await Media.count_documents()
        users = await db.total_users_count()
        chats = await db.total_chat_count()
        monsize = await db.get_db_size()
        if DATABASE_URI:
            free_value = max(0, (MONGO_DB_CAP_BYTES * max(MONGO_DB_COUNT, 1)) - monsize)
            free = get_size(free_value)
        else:
            if POSTGRES_STORAGE_LIMIT_BYTES > 0:
                free_value = max(0, POSTGRES_STORAGE_LIMIT_BYTES - monsize)
                free = get_size(free_value)
            else:
                free = "Plan based (set POSTGRES_STORAGE_LIMIT_BYTES)"
        monsize = get_size(monsize)
        await query.message.edit_text(
            text=script.STATUS_TXT.format(total, users, chats, monsize, free),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data == "rfrsh":
        await query.answer("Refreshing database stats")
        buttons = [[
            InlineKeyboardButton('ʙᴀᴄᴋ', callback_data='help'),
            InlineKeyboardButton('♻️', callback_data='rfrsh'),
            InlineKeyboardButton('ʀᴇᴘᴏ', url='https://github.com/mn-bots/ShobanaFilterBot')
        ]]
        reply_markup = InlineKeyboardMarkup(buttons)
        total = await Media.count_documents()
        users = await db.total_users_count()
        chats = await db.total_chat_count()
        monsize = await db.get_db_size()
        if DATABASE_URI:
            free_value = max(0, (MONGO_DB_CAP_BYTES * max(MONGO_DB_COUNT, 1)) - monsize)
            free = get_size(free_value)
        else:
            if POSTGRES_STORAGE_LIMIT_BYTES > 0:
                free_value = max(0, POSTGRES_STORAGE_LIMIT_BYTES - monsize)
                free = get_size(free_value)
            else:
                free = "Plan based (set POSTGRES_STORAGE_LIMIT_BYTES)"
        monsize = get_size(monsize)
        await query.message.edit_text(
            text=script.STATUS_TXT.format(total, users, chats, monsize, free),
            reply_markup=reply_markup,
            parse_mode=enums.ParseMode.HTML
        )
    elif query.data.startswith("setgs"):
        ident, set_type, status, grp_id = query.data.split("#")
        grpid = await active_connection(str(query.from_user.id))

        if str(grp_id) != str(grpid):
            await query.message.edit("Your Active Connection Has Been Changed. Go To /settings.")
            return await query.answer('Piracy Is Crime')

        if status == "True":
            await save_group_settings(grpid, set_type, False)
        else:
            await save_group_settings(grpid, set_type, True)

        settings = await get_settings(grpid)

        if settings is not None:
            buttons = [
                [
                    InlineKeyboardButton('Filter Button',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}'),
                    InlineKeyboardButton('Single' if settings["button"] else 'Double',
                                         callback_data=f'setgs#button#{settings["button"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Bot PM', callback_data=f'setgs#botpm#{settings["botpm"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✅ Yes' if settings["botpm"] else '❌ No',
                                         callback_data=f'setgs#botpm#{settings["botpm"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('File Secure',
                                         callback_data=f'setgs#file_secure#{settings["file_secure"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✅ Yes' if settings["file_secure"] else '❌ No',
                                         callback_data=f'setgs#file_secure#{settings["file_secure"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('IMDB', callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✅ Yes' if settings["imdb"] else '❌ No',
                                         callback_data=f'setgs#imdb#{settings["imdb"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Spell Check',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✅ Yes' if settings["spell_check"] else '❌ No',
                                         callback_data=f'setgs#spell_check#{settings["spell_check"]}#{str(grp_id)}')
                ],
                [
                    InlineKeyboardButton('Welcome', callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}'),
                    InlineKeyboardButton('✅ Yes' if settings["welcome"] else '❌ No',
                                         callback_data=f'setgs#welcome#{settings["welcome"]}#{str(grp_id)}')
                ]
            ]
            reply_markup = InlineKeyboardMarkup(buttons)
            await query.message.edit_reply_markup(reply_markup)
    await query.answer('Piracy Is Crime')

async def auto_filter(client, msg, spoll=False):
    if not spoll:
        message = msg
        settings = await get_settings(message.chat.id)
        if message.text.startswith("/"): return  # ignore commands
        if re.findall(r"((^\/|^,|^!|^\.|^[\U0001F600-\U000E007F]).*)", message.text):
            return
        if 2 < len(message.text) < 100:
            search = message.text
            files, offset, total_results, search_time = await get_search_results(
                search.lower(), offset=0, filter=True, fast=True, return_time=True
            )
            if not files:
                if settings["spell_check"]:
                    return await advantage_spell_chok(client, msg)
                else:
                    return
        else:
            return
    else:
        settings = await get_settings(msg.message.chat.id)
        message = msg.message.reply_to_message  # msg is CallbackQuery
        if len(spoll) == 5:
            search, files, offset, total_results, search_time = spoll
        else:
            search, files, offset, total_results = spoll
            search_time = 0

    pre = "filep" if settings["file_secure"] else "file"
    key = f"{message.chat.id}-{message.id}"
    req = message.from_user.id if message.from_user else 0
    BUTTONS[key] = search

    # ── Populate FILTER_STATE with full result set ──────────────────────────
    await _get_or_cache_all_files(key, search)

    # ── Build button grid (file list + filter buttons + pagination) ─────────
    if HYPER_MODE:
        state      = FILTER_STATE.get(key, {})
        all_files  = state.get("all_files", [])
        filtered   = _apply_filters(all_files, state)
        page_files = filtered[:10]

        cap_lines = []
        for file in page_files:
            file_link = f"https://t.me/{temp.U_NAME}?start={pre}_{file.file_id}"
            cap_lines.append(f"📁 {get_size(file.file_size)} - [{file.file_name}]({file_link})")
        cap_text = "\n".join(cap_lines)

        btn, _, _ = await _render_filter_page(key, req, 0, settings, pre, hyper_mode=True)
    else:
        btn, total_f, page_files = await _render_filter_page(key, req, 0, settings, pre)

    # ── IMDB poster / caption (existing logic, unchanged) ───────────────────
    imdb = await get_poster(search, file=(files[0]).file_name) if settings["imdb"] else None
    TEMPLATE = settings["template"]
    if imdb:
        cap = TEMPLATE.format(
            query=search,
            title=imdb["title"],
            votes=imdb["votes"],
            aka=imdb["aka"],
            seasons=imdb["seasons"],
            box_office=imdb["box_office"],
            localized_title=imdb["localized_title"],
            kind=imdb["kind"],
            imdb_id=imdb["imdb_id"],
            cast=imdb["cast"],
            runtime=imdb["runtime"],
            countries=imdb["countries"],
            certificates=imdb["certificates"],
            languages=imdb["languages"],
            director=imdb["director"],
            writer=imdb["writer"],
            producer=imdb["producer"],
            composer=imdb["composer"],
            cinematographer=imdb["cinematographer"],
            music_team=imdb["music_team"],
            distributors=imdb["distributors"],
            release_date=imdb["release_date"],
            year=imdb["year"],
            genres=imdb["genres"],
            poster=imdb["poster"],
            plot=imdb["plot"],
            rating=imdb["rating"],
            url=imdb["url"],
            **locals()
        )
    else:
        mention = message.from_user.mention if message.from_user else "User"
        cap = script.RESULT_TXT.format(mention=mention, query=search)

    if imdb and imdb.get("poster"):
        try:
            delauto = await message.reply_photo(
                photo=imdb.get("poster"),
                caption=cap[:1024],
                reply_markup=InlineKeyboardMarkup(btn)
            )
            await asyncio.sleep(300)
            await delauto.delete()
        except (MediaEmpty, PhotoInvalidDimensions, WebpageMediaEmpty):
            pic = imdb.get("poster")
            poster = pic.replace(".jpg", "._V1_UX360.jpg")
            delau = await message.reply_photo(
                photo=poster,
                caption=cap[:1024],
                reply_markup=InlineKeyboardMarkup(btn)
            )
            await asyncio.sleep(300)
            await delau.delete()
        except Exception as e:
            logger.exception(e)
            audel = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))
            await asyncio.sleep(300)
            await audel.delete()
    else:
        if HYPER_MODE:
            autodel = await message.reply_text(
                cap_text,
                reply_markup=InlineKeyboardMarkup(btn),
                parse_mode=enums.ParseMode.MARKDOWN,
                disable_web_page_preview=True
            )
        else:
            autodel = await message.reply_text(cap, reply_markup=InlineKeyboardMarkup(btn))

        await asyncio.sleep(300)
        await autodel.delete()

    if spoll:
        await msg.message.delete()


#SPELL CHECK RE EDITED BY GOUTHAMSER
async def advantage_spell_chok(client, msg):
    mv_id = msg.id
    mv_rqst = msg.text
    reqstr1 = msg.from_user.id if msg.from_user else 0
    settings = await get_settings(msg.chat.id)
    query = re.sub(
        r"\b(pl(i|e)*?(s|z+|ease|se|ese|(e+)s(e)?)|((send|snd|giv(e)?|gib)(\sme)?)|movie(s)?|new|latest|br((o|u)h?)*|^h(e|a)?(l)*(o)*|mal(ayalam)?|t(h)?amil|file|that|find|und(o)*|kit(t(i|y)?)?o(w)?|thar(u)?(o)*w?|kittum(o)*|aya(k)*(um(o)*)?|full\smovie|any(one)|with\ssubtitle(s)?)",
        "", msg.text, flags=re.IGNORECASE)  # plis contribute some common words
    query = query.strip() + " movie"
    try:
        movies = await get_poster(mv_rqst, bulk=True)
    except Exception as e:
        logger.exception(e)
        reqst_gle = mv_rqst.replace(" ", "+")
        button = [[
                 InlineKeyboardButton('ENG', callback_data='esp'),
                 InlineKeyboardButton('MAL', callback_data='msp'),
                 InlineKeyboardButton('HIN', callback_data='hsp'),
                 InlineKeyboardButton('TAM', callback_data='tsp')
        ],[
                 InlineKeyboardButton('🔍 ɢᴏᴏɢʟᴇ 🔎', url=f"https://www.google.com/search?q={reqst_gle}")
             ]]
        
        k = await msg.reply_text(
            text=script.SPOLL_NOT_FND, #IN SCRIPT CHANGE DONOT CHANGE CODE
            reply_markup=InlineKeyboardMarkup(button),
            reply_to_message_id=msg.id
        )
        await asyncio.sleep(45)
        await k.delete()      
        return
    movielist = []
    if not movies:
        reqst_gle = mv_rqst.replace(" ", "+")
        button = [[
                 InlineKeyboardButton('ENG', callback_data='esp'),
                 InlineKeyboardButton('MAL', callback_data='msp'),
                 InlineKeyboardButton('HIN', callback_data='hsp'),
                 InlineKeyboardButton('TAM', callback_data='tsp')
        ],[
                 InlineKeyboardButton('🔍 ɢᴏᴏɢʟᴇ 🔎', url=f"https://www.google.com/search?q={reqst_gle}")
             ]]
        
        k = await msg.reply_text(
            text=script.SPOLL_NOT_FND, 
            reply_markup=InlineKeyboardMarkup(button),
            reply_to_message_id=msg.id
        )
        await asyncio.sleep(60)
        await k.delete()
        return
    movielist = [movie.get('title') for movie in movies if movie.get('title')]
    if not movielist:
        return

    SPELL_CHECK[mv_id] = movielist
    btn = [
        [
            InlineKeyboardButton(
                text=movie_name.strip(),
                callback_data=f"spol#{reqstr1}#{k}",
            )
        ]
        for k, movie_name in enumerate(movielist)
    ]
    btn.append([InlineKeyboardButton(text="✘ ᴄʟᴏsᴇ ✘", callback_data=f'spol#{reqstr1}#close_spellcheck')])
    spell_check_del = await msg.reply_text(
        text="<b>Sᴘᴇʟʟɪɴɢ Mɪꜱᴛᴀᴋᴇ Bʀᴏ ‼️\n\nᴅᴏɴ'ᴛ ᴡᴏʀʀʏ 😊 Cʜᴏᴏꜱᴇ ᴛʜᴇ ᴄᴏʀʀᴇᴄᴛ ᴏɴᴇ ʙᴇʟᴏᴡ 👇</b>",
        reply_markup=InlineKeyboardMarkup(btn),
        reply_to_message_id=msg.id
    )
    await asyncio.sleep(180)
    await spell_check_del.delete()



async def manual_filters(client, message, text=False):
    group_id = message.chat.id
    name = text or message.text
    reply_id = message.reply_to_message.id if message.reply_to_message else message.id
    keywords = await get_filters(group_id)
    for keyword in reversed(sorted(keywords, key=len)):
        pattern = r"( |^|[^\w])" + re.escape(keyword) + r"( |$|[^\w])"
        if re.search(pattern, name, flags=re.IGNORECASE):
            reply_text, btn, alert, fileid = await find_filter(group_id, keyword)

            if reply_text:
                reply_text = reply_text.replace("\\n", "\n").replace("\\t", "\t")

            if btn is not None:
                try:
                    if fileid == "None":
                        if btn == "[]":
                            await client.send_message(
                                group_id, 
                                reply_text, 
                                disable_web_page_preview=True,
                                reply_to_message_id=reply_id)
                        else:
                            button = eval(btn)
                            await client.send_message(
                                group_id,
                                reply_text,
                                disable_web_page_preview=True,
                                reply_markup=InlineKeyboardMarkup(button),
                                reply_to_message_id=reply_id
                            )
                    elif btn == "[]":
                        await client.send_cached_media(
                            group_id,
                            fileid,
                            caption=reply_text or "",
                            reply_to_message_id=reply_id
                        )
                    else:
                        button = eval(btn)
                        await message.reply_cached_media(
                            fileid,
                            caption=reply_text or "",
                            reply_markup=InlineKeyboardMarkup(button),
                            reply_to_message_id=reply_id
                        )
                except Exception as e:
                    logger.exception(e)
                break
    else:
        return False
