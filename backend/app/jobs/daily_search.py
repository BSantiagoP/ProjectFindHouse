"""Scheduled job: discover -> analyze -> save -> SMS digest. Run: python -m app.jobs.daily_search

launchd calls this hourly; it only runs when due (every RUN_EVERY_DAYS days, after RUN_HOUR
Eastern). Exit code 1 on failure.
"""

import logging
import sys

from app.agents.graph import run_analysis
from app.api.routes import build_analysis_deps, get_provider
from app.core.config import Settings, get_settings, load_recipients
from app.notifications.digest import send_digest
from app.repositories.factory import get_repository
from app.services.discovery import run_discovery

log = logging.getLogger("daily_search")


def build_sender(settings: Settings):
    from app.notifications.twilio_client import TwilioSender

    return TwilioSender(settings.twilio_account_sid, settings.twilio_auth_token, settings.twilio_messaging_service_sid)


TZ = "America/New_York"


def is_due(repo, *, every_days: int, run_hour: int, now=None) -> tuple[bool, str]:
    """Due when it's at/after run_hour (Eastern) and the last non-failed run was >= every_days
    calendar days ago. Called hourly by launchd, so a Mac that was closed at run time
    catches up within an hour of waking."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    tz = ZoneInfo(TZ)
    now = (now or datetime.now(tz)).astimezone(tz)
    if now.hour < run_hour:
        return False, f"before {run_hour}:00 Eastern"
    last = repo.latest_run()
    if last is None:
        return True, "no previous run"
    days = (now.date() - last.started_at.astimezone(tz).date()).days
    if days >= every_days:
        return True, f"last run {days} day(s) ago"
    return False, f"last run {days} day(s) ago; runs every {every_days} days"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    settings = get_settings()
    repo = get_repository()
    if "--force" not in argv:
        due, why = is_due(repo, every_days=settings.run_every_days, run_hour=settings.run_hour)
        if not due:
            log.info("Not due (%s); skipping. Use --force to run now.", why)
            return 0
        log.info("Due (%s); running", why)
    prefs = repo.get_preferences()
    run = run_discovery(get_provider(settings), prefs, max_requests=settings.max_requests_per_run,
                        fetch_details=settings.fetch_details, known_lookup=repo.known_properties)
    if settings.analysis_enabled:
        run = run_analysis(run, prefs, build_analysis_deps(settings, repo, prefs))
    repo.save_run(run)
    log.info("Run %s: %s %s", run.id, run.status, run.counts())
    if run.status == "failed":
        return 1
    if settings.sms_enabled:
        for r in send_digest(run, load_recipients(), repo, build_sender(settings), limit=prefs.max_recommendations):
            log.info("SMS %s: %s (%d properties)%s", r.recipient_key, r.status, r.count, f" error={r.error}" if r.error else "")
    else:
        log.info("SMS disabled (SMS_ENABLED=false); digest not sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())
