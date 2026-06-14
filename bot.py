import logging
from datetime import date
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    ContextTypes, filters
)
from database import (
    init_db, get_or_create_user, upsert_daily,
    add_social_proof, get_leaderboard, get_user_stats,
    get_user_rank, get_pending_submissions,
    approve_submission, reject_submission
)
import os
from dotenv import load_dotenv

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "").split(",")))

logging.basicConfig(level=logging.INFO)

def get_medal(rank):
    if rank == 1: return "👑"
    if rank == 2: return "💎"
    if rank == 3: return "🥇"
    if rank <= 10: return "⭐️"
    return "🌱"

def get_tier(points):
    if points >= 2000: return "👑 Legendary"
    if points >= 1000: return "💎 Diamond"
    if points >= 500:  return "🥇 Gold"
    if points >= 200:  return "⭐️ Silver"
    if points >= 50:   return "🌱 Bronze"
    return "❌ Inactive"

# ── COMMANDS ──────────────────────────────────────────

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await get_or_create_user(user.id, user.username or user.first_name)
    await update.message.reply_text(
        f"👋 Yo {user.first_name}!\n\n"
        "Selamat datang ke Beta Tester Bot 🚀\n\n"
        "📋 Commands:\n"
        "/score — Score kau hari ni\n"
        "/rank — Rank & tier kau\n"
        "/leaderboard — Top 20\n"
        "/submit [link] — Submit social proof\n"
        "/rules — Cara kira points"
    )

async def rules(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "📋 *Cara Kira Points*\n\n"
        "💬 Messages (max 20/day) → 1pt each\n"
        "↩️ Reply orang lain → +3pt each\n"
        "❤️ Reactions received → +2pt each\n"
        "📤 Social proof verified → +20pt (max 2/day)\n"
        "🐛 Bug report → +10pt\n\n"
        "⚠️ Daily cap: 100 pts\n"
        "❌ Fake link: -50pt + ban",
        parse_mode="Markdown"
    )

async def score(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await get_or_create_user(user.id, user.username or user.first_name)
    today = date.today().isoformat()

    from database import get_today_activity
    row = await get_today_activity(user.id, today)

    if not row:
        await update.message.reply_text("Belum ada activity hari ni. Mula chat! 💬")
        return

    _, _, _, msgs, replies, reactions, sp, daily_pts = row
    await update.message.reply_text(
        f"📊 *Score Kau Hari Ni*\n\n"
        f"💬 Messages: {msgs} pts\n"
        f"↩️ Replies: {replies} pts\n"
        f"❤️ Reactions: {reactions} pts\n"
        f"📤 Social Proof: {sp} pts\n"
        f"━━━━━━━━━━━━\n"
        f"✅ Total Hari Ni: *{daily_pts}/100 pts*",
        parse_mode="Markdown"
    )

async def rank_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await get_or_create_user(user.id, user.username or user.first_name)
    stats = await get_user_stats(user.id)
    position = await get_user_rank(user.id)

    if not stats:
        return

    username, total = stats
    tier = get_tier(total)
    medal = get_medal(position)

    await update.message.reply_text(
        f"{medal} *{username}*\n\n"
        f"🏅 Tier: {tier}\n"
        f"🏆 Rank: #{position}\n"
        f"⭐️ Total Points: {total}",
        parse_mode="Markdown"
    )

async def leaderboard(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    rows = await get_leaderboard()
    if not rows:
        await update.message.reply_text("Leaderboard kosong lagi.")
        return

    text = "🏆 *TOP 20 BETA TESTERS*\n\n"
    for i, (username, pts) in enumerate(rows, 1):
        medal = get_medal(i)
        text += f"{medal} #{i} {username} — {pts} pts\n"

    await update.message.reply_text(text, parse_mode="Markdown")

async def submit(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await get_or_create_user(user.id, user.username or user.first_name)

    if not ctx.args:
        await update.message.reply_text("Usage: /submit [link]\nContoh: /submit https://twitter.com/...")
        return

    link = ctx.args[0]
    if not link.startswith("http"):
        await update.message.reply_text("❌ Link tak valid. Kena start dengan http/https.")
        return

    ok, msg = await add_social_proof(user.id, user.username or user.first_name, link)
    await update.message.reply_text(("✅ " if ok else "❌ ") + msg)

# ── ADMIN COMMANDS ────────────────────────────────────

async def pending(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return

    rows = await get_pending_submissions()
    if not rows:
        await update.message.reply_text("Tiada pending submission.")
        return

    text = "📋 *Pending Submissions*\n\n"
    for sub_id, username, link, submitted_at in rows:
        text += f"ID: `{sub_id}`\n👤 {username}\n🔗 {link}\n🕐 {submitted_at}\n\n"

    text += "Guna /approve [id] atau /reject [id]"
    await update.message.reply_text(text, parse_mode="Markdown")

async def approve(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /approve [id]")
        return

    ok = await approve_submission(int(ctx.args[0]))
    await update.message.reply_text("✅ Approved! +20pts dah masuk." if ok else "❌ ID tak jumpa.")

async def reject(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
    if not ctx.args:
        await update.message.reply_text("Usage: /reject [id]")
        return

    await reject_submission(int(ctx.args[0]))
    await update.message.reply_text("❌ Rejected.")

# ── MESSAGE TRACKER ───────────────────────────────────

async def track_message(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not user or user.is_bot:
        return

    await get_or_create_user(user.id, user.username or user.first_name)
    today = date.today().isoformat()

    if update.message.reply_to_message:
        await upsert_daily(user.id, today, "replies", 3, 15)
    else:
        await upsert_daily(user.id, today, "messages", 1, 20)

# ── REACTION TRACKER ──────────────────────────────────

async def track_reaction(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    if not update.message_reaction:
        return

    # Track siapa yang dapat reaction (bukan yang bagi)
    chat = update.message_reaction.chat
    msg_id = update.message_reaction.message_id

    # Kena fetch original message untuk dapat owner
    try:
        msg = await ctx.bot.forward_message(chat.id, chat.id, msg_id)
        if msg and msg.from_user and not msg.from_user.is_bot:
            today = date.today().isoformat()
            await upsert_daily(msg.from_user.id, today, "reactions", 2, 10)
    except:
        pass

# ── MAIN ──────────────────────────────────────────────

async def post_init(app):
    await init_db()

def main():
    app = ApplicationBuilder()\
        .token(BOT_TOKEN)\
        .post_init(post_init)\
        .build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("rules", rules))
    app.add_handler(CommandHandler("score", score))
    app.add_handler(CommandHandler("rank", rank_cmd))
    app.add_handler(CommandHandler("leaderboard", leaderboard))
    app.add_handler(CommandHandler("submit", submit))
    app.add_handler(CommandHandler("pending", pending))
    app.add_handler(CommandHandler("approve", approve))
    app.add_handler(CommandHandler("reject", reject))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, track_message))

    print("Bot running...")
    app.run_polling()

if __name__ == "__main__":
    main()
