# Standard library imports
from datetime import datetime
from zoneinfo import ZoneInfo
import os

# Local imports
from flask import current_app


def format_relative_time(timestamp):
    """Return human friendly relative time like 'now', 'yesterday', '4 hrs ago'."""
    if not timestamp:
        return ""

    try:
        local_tz = ZoneInfo("Asia/Manila")
        now_local = datetime.now(local_tz)

        # Ensure timestamp is timezone-aware in the same timezone
        if getattr(timestamp, 'tzinfo', None) is None:
            ts_local = timestamp.replace(tzinfo=local_tz)
        else:
            try:
                ts_local = timestamp.astimezone(local_tz)
            except Exception:
                ts_local = timestamp

        delta = now_local - ts_local

        # Handle future timestamps gracefully
        if delta.total_seconds() < 0:
            delta = -delta
            seconds = int(delta.total_seconds())
            minutes = seconds // 60
            hours = minutes // 60
            days = hours // 24
            if seconds < 60:
                return "in a few seconds"
            if minutes < 60:
                return f"in {minutes} min" if minutes == 1 else f"in {minutes} mins"
            if hours < 24:
                return f"in {hours} hr" if hours == 1 else f"{hours} hrs ago"
            if days == 1:
                return "tomorrow"
            if days < 7:
                return f"in {days} days"
            weeks = days // 7
            return f"in {weeks} wk" if weeks == 1 else f"in {weeks} wks"

        seconds = int(delta.total_seconds())
        minutes = seconds // 60
        hours = minutes // 60
        days = hours // 24

        if seconds < 60:
            return "now"
        if minutes < 60:
            return f"{minutes} min ago" if minutes == 1 else f"{minutes} mins ago"
        if hours < 24:
            return f"{hours} hr ago" if hours == 1 else f"{hours} hrs ago"
        if days == 1:
            return "yesterday"
        if days < 7:
            return f"{days} days ago"
        weeks = days // 7
        if weeks < 4:
            return f"{weeks} wk ago" if weeks == 1 else f"{weeks} wks ago"
        # Fallback to a short date for older entries
        return ts_local.strftime('%b %d, %Y')

    except Exception:
        # If anything goes wrong, return a formatted absolute time as fallback
        try:
            return timestamp.strftime('%b %d, %Y %I:%M %p')
        except Exception:
            return str(timestamp)


def to_float(value):
    """Convert a value to float, returning 0.0 if conversion fails."""
    try:
        return float(value)
    except (ValueError, TypeError):
        return 0.0