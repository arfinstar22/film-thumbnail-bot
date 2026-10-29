#!/usr/bin/env python3
"""
Supabase Keepalive & Anti-Pause Script
Pings Supabase PostgreSQL and/or REST API to prevent free-tier 7-day inactivity pause.
Can run in GitHub Actions, Render Cron, VPS cron, or local terminal.
"""
import os
import sys
import time
import urllib.request
import urllib.error
from pathlib import Path

# Load .env if present
try:
    from dotenv import load_dotenv
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)
    else:
        load_dotenv()
except ImportError:
    pass


def ping_postgres(db_url: str) -> bool:
    try:
        import psycopg2
    except ImportError:
        print("⚠️ psycopg2 not installed, skipping direct PostgreSQL ping.")
        return False

    raw_url = db_url.strip()
    if raw_url.startswith("postgres://"):
        raw_url = "postgresql://" + raw_url[11:]

    last_err = None
    for attempt in (1, 2):
        conn = None
        try:
            conn = psycopg2.connect(raw_url, connect_timeout=8)
            now_iso = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            with conn.cursor() as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS settings (
                        key TEXT PRIMARY KEY,
                        value TEXT
                    );
                """)
                cur.execute("""
                    INSERT INTO settings (key, value)
                    VALUES ('supabase_last_keepalive', %s)
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
                """, (now_iso,))
            conn.commit()
            print(f"✅ PostgreSQL keepalive ping SUCCESS! (attempt {attempt}, updated supabase_last_keepalive to {now_iso})")
            return True
        except Exception as e:
            last_err = e
            print(f"⚠️ PostgreSQL attempt {attempt}/2 failed: {e}")
            time.sleep(3)
        finally:
            if conn:
                try:
                    conn.close()
                except Exception:
                    pass
    print(f"❌ PostgreSQL keepalive ping FAILED after 2 attempts: {last_err}")
    return False


def ping_rest(sb_url: str, sb_key: str) -> bool:
    url = f"{sb_url.rstrip('/')}/rest/v1/settings?select=key&limit=1"
    req = urllib.request.Request(
        url,
        headers={
            "apikey": sb_key,
            "Authorization": f"Bearer {sb_key}",
            "User-Agent": "FilmBot-Keepalive-Runner/1.0",
        }
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status in (200, 206):
                print(f"✅ Supabase REST API ping SUCCESS! (HTTP {resp.status})")
                return True
            else:
                print(f"⚠️ Supabase REST API returned HTTP {resp.status}")
                return False
    except Exception as e:
        print(f"❌ Supabase REST API ping FAILED: {e}")
        return False


def ping_render_web(render_url: str) -> bool:
    if not render_url:
        return False
    url = f"{render_url.rstrip('/')}/keepalive"
    req = urllib.request.Request(
        url,
        headers={"User-Agent": "FilmBot-Keepalive-Runner/1.0"}
    )
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            print(f"✅ Render web wake-up SUCCESS! (HTTP {resp.status})")
            return True
    except Exception as e:
        print(f"⚠️ Render web wake-up ping warning: {e}")
        return False


def main():
    db_url = (
        os.getenv("DATABASE_URL", "").strip()
        or os.getenv("SUPABASE_DATABASE_URL", "").strip()
        or os.getenv("SUPABASE_DB_URL", "").strip()
    )
    sb_url = os.getenv("SUPABASE_URL", "").strip()
    sb_key = os.getenv("SUPABASE_KEY", "").strip()
    render_url = os.getenv("RENDER_EXTERNAL_URL", "").strip() or os.getenv("RENDER_WEB_URL", "").strip()

    # FIX: laporkan status tiap target TANPA bocorkan isi secret.
    # Run #16 gagal 11 detik = kemungkinan besar semua kosong (secrets GitHub belum di-set).
    print("--- Keepalive target check ---")
    print(f"DATABASE_URL: {'CONFIGURED' if db_url else 'MISSING (set di GitHub Settings → Secrets → Actions)'}")
    print(f"SUPABASE_URL: {'CONFIGURED' if sb_url else 'MISSING (set di GitHub Settings → Secrets → Actions)'}")
    print(f"SUPABASE_KEY: {'CONFIGURED' if sb_key else 'MISSING (set di GitHub Settings → Secrets → Actions)'}")
    print(f"RENDER_EXTERNAL_URL: {'CONFIGURED' if render_url else 'MISSING (opsional, hanya untuk wake-up Render)'}")
    print("----------------------------")

    successes = 0

    if db_url:
        if ping_postgres(db_url):
            successes += 1

    if sb_url and sb_key:
        if ping_rest(sb_url, sb_key):
            successes += 1

    if render_url:
        ping_render_web(render_url)

    if successes > 0:
        print(f"🎉 Supabase Keepalive complete! Total successful pings: {successes}")
        sys.exit(0)
    else:
        print("❌ Supabase Keepalive could not ping any targets.")
        print("   1) Buka GitHub repo → Settings → Secrets and variables → Actions")
        print("   2) Pastikan ada: DATABASE_URL, SUPABASE_URL, SUPABASE_KEY")
        print("   3) Klik 'Re-run jobs' setelah secrets diisi.")
        sys.exit(1)


if __name__ == "__main__":
    main()
