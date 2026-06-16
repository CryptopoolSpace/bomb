import aiosqlite

DB_PATH = "beta.db"

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                total_points INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_activity (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                date TEXT,
                messages INTEGER DEFAULT 0,
                replies INTEGER DEFAULT 0,
                reactions INTEGER DEFAULT 0,
                social_proof INTEGER DEFAULT 0,
                daily_points INTEGER DEFAULT 0,
                UNIQUE(user_id, date)
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                username TEXT,
                link TEXT,
                status TEXT DEFAULT 'pending',
                submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        await db.execute("""
    CREATE TABLE IF NOT EXISTS faucet_requests (
        wallet_address TEXT PRIMARY KEY,
        last_request_date TEXT
    )
""")

        await db.commit()

async def get_or_create_user(user_id, username):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO users (user_id, username)
            VALUES (?, ?)
        """, (user_id, username))
        await db.commit()

async def get_today_activity(user_id, date):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT * FROM daily_activity WHERE user_id=? AND date=?
        """, (user_id, date)) as cursor:
            return await cursor.fetchone()

async def upsert_daily(user_id, date, field, increment, max_val, daily_cap=100):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT OR IGNORE INTO daily_activity (user_id, date)
            VALUES (?, ?)
        """, (user_id, date))

        async with db.execute(f"""
            SELECT {field}, daily_points FROM daily_activity
            WHERE user_id=? AND date=?
        """, (user_id, date)) as cursor:
            row = await cursor.fetchone()

        current_field = row[0]
        current_daily = row[1]

        if current_field >= max_val:
            return 0
        if current_daily >= daily_cap:
            return 0

        actual = min(increment, max_val - current_field, daily_cap - current_daily)

        await db.execute(f"""
            UPDATE daily_activity
            SET {field} = {field} + ?,
                daily_points = daily_points + ?
            WHERE user_id=? AND date=?
        """, (actual, actual, user_id, date))

        await db.execute("""
            UPDATE users SET total_points = total_points + ?
            WHERE user_id=?
        """, (actual, user_id))

        await db.commit()
        return actual

async def add_social_proof(user_id, username, link):
    async with aiosqlite.connect(DB_PATH) as db:
        # Cek duplicate link
        async with db.execute("""
            SELECT id FROM submissions WHERE link=?
        """, (link,)) as cursor:
            if await cursor.fetchone():
                return False, "Link dah pernah submit."

        # Cek dah 2 submission hari ni
        from datetime import date
        today = date.today().isoformat()
        async with db.execute("""
            SELECT COUNT(*) FROM submissions
            WHERE user_id=? AND DATE(submitted_at)=? AND status != 'rejected'
        """, (user_id, today)) as cursor:
            count = (await cursor.fetchone())[0]

        if count >= 2:
            return False, "Max 2 submission sehari."

        await db.execute("""
            INSERT INTO submissions (user_id, username, link)
            VALUES (?, ?, ?)
        """, (user_id, username, link))
        await db.commit()
        return True, "Submission diterima! Tunggu admin verify."

async def get_leaderboard():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT username, total_points FROM users
            ORDER BY total_points DESC LIMIT 20
        """) as cursor:
            return await cursor.fetchall()

async def get_user_stats(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT username, total_points FROM users WHERE user_id=?
        """, (user_id,)) as cursor:
            return await cursor.fetchone()

async def get_user_rank(user_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT COUNT(*) + 1 FROM users
            WHERE total_points > (
                SELECT total_points FROM users WHERE user_id=?
            )
        """, (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

async def get_pending_submissions():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT id, username, link, submitted_at FROM submissions
            WHERE status='pending' ORDER BY submitted_at ASC
        """) as cursor:
            return await cursor.fetchall()

async def approve_submission(sub_id):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT user_id FROM submissions WHERE id=?
        """, (sub_id,)) as cursor:
            row = await cursor.fetchone()
        if not row:
            return False

        user_id = row[0]
        from datetime import date
        today = date.today().isoformat()

        await db.execute("""
            UPDATE submissions SET status='approved' WHERE id=?
        """, (sub_id,))

        # Add 20 pts (max 40/day dari social proof)
        await db.execute("""
            INSERT OR IGNORE INTO daily_activity (user_id, date)
            VALUES (?, ?)
        """, (user_id, today))

        async with db.execute("""
            SELECT social_proof, daily_points FROM daily_activity
            WHERE user_id=? AND date=?
        """, (user_id, today)) as cursor:
            row = await cursor.fetchone()

        sp = row[0]
        dp = row[1]

        pts = min(20, 40 - sp, 100 - dp)
        if pts > 0:
            await db.execute("""
                UPDATE daily_activity
                SET social_proof = social_proof + ?,
                    daily_points = daily_points + ?
                WHERE user_id=? AND date=?
            """, (pts, pts, user_id, today))
            await db.execute("""
                UPDATE users SET total_points = total_points + ?
                WHERE user_id=?
            """, (pts, user_id))

        await db.commit()
        return True

async def reject_submission(sub_id):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE submissions SET status='rejected' WHERE id=?
        """, (sub_id,))
        await db.commit()

async def can_request_faucet(wallet_address: str) -> bool:
    from datetime import date
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT last_request_date FROM faucet_requests WHERE wallet_address=?",
            (wallet_address,)
        ) as cursor:
            row = await cursor.fetchone()
            if not row:
                return True
            return row[0] != today

async def record_faucet_request(wallet_address: str):
    from datetime import date
    today = date.today().isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO faucet_requests (wallet_address, last_request_date)
            VALUES (?, ?)
            ON CONFLICT(wallet_address) DO UPDATE SET last_request_date=?
        """, (wallet_address, today, today))
        await db.commit()

