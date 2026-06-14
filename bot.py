import logging
import os
from datetime import date
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import (
    ApplicationBuilder, CommandHandler,
    MessageHandler, ContextTypes, filters
)
from database import (
    init_db, get_or_create_user, upsert_daily,
    add_social_proof, get_leaderboard, get_user_stats,
    get_user_rank, get_pending_submissions,
    approve_submission, reject_submission,
    get_today_activity
)

load_dotenv()
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_IDS = list(map(int, os.getenv("ADMIN_IDS", "0").split(",")))

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

async def start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    await get_or_create_user(user.id, user.username or user.first_name)
    await update.message.reply_text(
        f"👋 Yo {user.first_name}!\n\n"
        "Selamat datang ke Beta Tester Bot 🚀\n\n"
        "📋 Commands:\n"
        "/score — Score kau 
