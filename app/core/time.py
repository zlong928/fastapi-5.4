from datetime import datetime, timedelta, timezone

APP_TIMEZONE_NAME = "Asia/Shanghai"
APP_TIMEZONE = timezone(timedelta(hours=8), APP_TIMEZONE_NAME)


def app_now() -> datetime:
    return datetime.now(APP_TIMEZONE)
