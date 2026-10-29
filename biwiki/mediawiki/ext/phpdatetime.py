# Ported from MediaWiki 1.39 includes/language/Language.php (https://www.mediawiki.org/), (C) MediaWiki
# contributors: Language::sprintfDate(), dateTimeObjFormat(), tsToIranian(), tsToHijri(), tsToHebrew(),
# hebrewYearStart(), tsToYear(), romanNumeral(), hebrewNumeral(), and the calendar month name messages; with the
# behaviour of PHP's DateTime constructor (timelib, by Derick Rethans) for the date strings #time accepts.
# Changed by a3ref contributors on 2026-10-30: translated to Python; English only; DateTime::format() and the
# DateTime parser are re-implemented for the formats listed in parse_datetime() (not a translation of timelib).
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""PHP dates for {{#time:}}: Language::sprintfDate() and the date strings of PHP's DateTime."""
from __future__ import annotations

import calendar
import math
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone, tzinfo
from typing import Optional

from ..messages import msg

# ======================================================================================================================
# Language::sprintfDate()
# ======================================================================================================================

MONTH_NAMES = ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
               "November", "December"]
WEEKDAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
_WEEKDAY_ABBR_MESSAGES = ["sun", "mon", "tue", "wed", "thu", "fri", "sat"]
_HEBREW_MONTHS = ["hebrew-calendar-m1", "hebrew-calendar-m2", "hebrew-calendar-m3", "hebrew-calendar-m4",
                  "hebrew-calendar-m5", "hebrew-calendar-m6", "hebrew-calendar-m7", "hebrew-calendar-m8",
                  "hebrew-calendar-m9", "hebrew-calendar-m10", "hebrew-calendar-m11", "hebrew-calendar-m12",
                  "hebrew-calendar-m6a", "hebrew-calendar-m6b"]

GREG_DAYS = [31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31]
IRANIAN_DAYS = [31, 31, 31, 31, 31, 31, 30, 30, 30, 30, 30, 29]


class EnglishDates:
    """The month and weekday names of Language for English (MessagesEn / en.json)."""

    def get_month_name(self, key: int) -> str:
        return MONTH_NAMES[key - 1]

    def get_month_name_gen(self, key: int) -> str:
        return MONTH_NAMES[key - 1]  # the -gen messages are the same in English

    def get_month_abbreviation(self, key: int) -> str:
        return MONTH_NAMES[key - 1][:3]

    def get_weekday_name(self, key: int) -> str:
        return WEEKDAY_NAMES[key - 1]

    def get_weekday_abbreviation(self, key: int) -> str:
        return msg(_WEEKDAY_ABBR_MESSAGES[key - 1])

    def get_iranian_calendar_month_name(self, key: int) -> str:
        return msg(f"iranian-calendar-m{key}")

    def get_hebrew_calendar_month_name(self, key: int) -> str:
        return msg(_HEBREW_MONTHS[key - 1])

    def get_hebrew_calendar_month_name_gen(self, key: int) -> str:
        return msg(_HEBREW_MONTHS[key - 1] + "-gen")

    def get_hijri_calendar_month_name(self, key: int) -> str:
        return msg(f"hijri-calendar-m{key}")

    @staticmethod
    def format_num_no_separators(num: str) -> str:
        """Language::formatNumNoSeparators(): English has no digit transformation."""
        return num


ENGLISH_DATES = EnglishDates()


def _php_int_prefix(s: str) -> int:
    m = re.match(r"\s*[+-]?\d+", s)
    return int(m.group(0)) if m else 0


def date_time_obj(ts: str, zone: Optional[tzinfo]) -> datetime:
    """DateTime::createFromFormat( 'YmdHis', $ts, $zone ?: UTC )"""
    return datetime(int(ts[0:4]), int(ts[4:6]), int(ts[6:8]), int(ts[8:10]), int(ts[10:12]), int(ts[12:14]),
                    tzinfo=zone or timezone.utc)


def zone_identifier(dt: datetime) -> str:
    """DateTime::format( 'e' )"""
    tz = dt.tzinfo
    key = getattr(tz, "key", None)
    if key:
        return key
    if tz is None or dt.utcoffset() == timedelta(0) and tz in (timezone.utc,):
        return "UTC"
    return _offset(dt, True)


def _offset(dt: datetime, colon: bool) -> str:
    off = dt.utcoffset() or timedelta(0)
    total = int(off.total_seconds())
    sign = "-" if total < 0 else "+"
    total = abs(total)
    h, m = divmod(total // 60, 60)
    return f"{sign}{h:02d}:{m:02d}" if colon else f"{sign}{h:02d}{m:02d}"


def php_date_format(dt: datetime, code: str) -> str:
    """DateTime::format() for one format character (the ones sprintfDate() passes through)."""
    if code == "w":
        return str((dt.weekday() + 1) % 7)
    if code == "N":
        return str(dt.isoweekday())
    if code == "z":
        return str(dt.timetuple().tm_yday - 1)
    if code == "W":
        return f"{dt.isocalendar()[1]:02d}"
    if code == "t":
        return str(calendar.monthrange(dt.year, dt.month)[1])
    if code == "L":
        return "1" if calendar.isleap(dt.year) else "0"
    if code == "o":
        return str(dt.isocalendar()[0])
    if code == "U":
        return str(int(dt.timestamp()))
    if code == "I":
        dst = dt.dst()
        return "1" if dst and dst != timedelta(0) else "0"
    if code == "Z":
        return str(int((dt.utcoffset() or timedelta(0)).total_seconds()))
    if code == "c":
        return f"{dt.year:04d}-{dt.month:02d}-{dt.day:02d}T{dt.hour:02d}:{dt.minute:02d}:{dt.second:02d}" \
               + _offset(dt, True)
    if code == "r":
        return (f"{WEEKDAY_NAMES[(dt.weekday() + 1) % 7][:3]}, {dt.day:02d} {MONTH_NAMES[dt.month - 1][:3]} "
                f"{dt.year:04d} {dt.hour:02d}:{dt.minute:02d}:{dt.second:02d} " + _offset(dt, False))
    if code == "e":
        return zone_identifier(dt)
    if code == "O":
        return _offset(dt, False)
    if code == "P":
        return _offset(dt, True)
    if code == "T":
        if dt.tzinfo is timezone.utc:
            return "UTC"
        name = dt.tzname()
        if not name or re.fullmatch(r"[+-]\d+", name) or name.startswith("UTC") and name != "UTC":
            return _offset(dt, True)
        return name
    raise ValueError(f"unsupported date format character {code!r}")


def sprintf_date(format_: str, ts: str, zone: Optional[tzinfo] = None, lang: EnglishDates = ENGLISH_DATES) -> str:
    """Language::sprintfDate(): a workalike of PHP's date() function, but with better internationalisation, a
    reduced set of format characters, and a better escaping format.

    Supported format characters are dDjlNwzWFmMntLoYyaAgGhHiscrUeIOPTZ. See the PHP manual for definitions. There
    are a number of extensions, which start with "x":

       xn   Do not translate digits of the next numeric format character
       xN   Toggle raw digit (xn) flag, stays set until explicitly unset
       xr   Use roman numerals for the next numeric format character
       xh   Use hebrew numerals for the next numeric format character
       xx   Literal x
       xg   Genitive month name

       xij  j (day number) in Iranian calendar
       xiF  F (month name) in Iranian calendar
       xin  n (month number) in Iranian calendar
       xiy  y (two digit year) in Iranian calendar
       xiY  Y (full year) in Iranian calendar
       xit  t (days in month) in Iranian calendar
       xiz  z (day of the year) in Iranian calendar

       xjj  j (day number) in Hebrew calendar
       xjF  F (month name) in Hebrew calendar
       xjt  t (days in month) in Hebrew calendar
       xjx  xg (genitive month name) in Hebrew calendar
       xjn  n (month number) in Hebrew calendar
       xjY  Y (full year) in Hebrew calendar

       xmj  j (day number) in Hijri calendar
       xmF  F (month name) in Hijri calendar
       xmn  n (month number) in Hijri calendar
       xmY  Y (full year) in Hijri calendar

       xkY  Y (full year) in Thai solar calendar. Months and days are identical to the Gregorian calendar
       xoY  Y (full year) in Minguo calendar or Juche year. Months and days are identical to the Gregorian
            calendar
       xtY  Y (full year) in Japanese nengo. Months and days are identical to the Gregorian calendar

    Characters enclosed in double quotes will be considered literal (with the quotes themselves removed).
    Unmatched quotes will be considered literal quotes. Backslash escaping is also supported.

    Input timestamp is assumed to be pre-normalized to the desired local time zone, if any. Note that the format
    characters crUeIOPTZ will assume ``ts`` is UTC if ``zone`` is not given. ``ts``: 14-character timestamp
    YYYYMMDDHHMMSS. (The TTL of the result is not computed: there is no parser cache.)"""
    s = []
    raw = False
    roman = False
    hebrew_num = False
    date_time = None
    raw_toggle = False
    iranian = hebrew = hijri = thai = minguo = tenno = None

    if len(ts) != 14:
        raise ValueError(f"sprintfDate: The timestamp {ts} should have 14 characters")
    if not ts.isdigit() or not ts.isascii():
        raise ValueError(f"sprintfDate: The timestamp {ts} should be a number")

    def obj_format(code: str) -> str:
        nonlocal date_time
        if date_time is None:
            date_time = date_time_obj(ts, zone)
        return php_date_format(date_time, code)

    format_length = len(format_)
    p = 0
    while p < format_length:
        num = None
        code = format_[p]
        if code == "x" and p < format_length - 1:
            p += 1
            code += format_[p]

        if code in ("xi", "xj", "xk", "xm", "xo", "xt") and p < format_length - 1:
            p += 1
            code += format_[p]

        if code == "xx":
            s.append("x")
        elif code == "xn":
            raw = True
        elif code == "xN":
            raw_toggle = not raw_toggle
        elif code == "xr":
            roman = True
        elif code == "xh":
            hebrew_num = True
        elif code == "xg":
            s.append(lang.get_month_name_gen(int(ts[4:6])))
        elif code == "xjx":
            hebrew = hebrew or ts_to_hebrew(ts)
            s.append(lang.get_hebrew_calendar_month_name_gen(hebrew[1]))
        elif code == "d":
            num = ts[6:8]
        elif code == "D":
            s.append(lang.get_weekday_abbreviation(int(obj_format("w")) + 1))
        elif code == "j":
            num = int(ts[6:8])
        elif code == "xij":
            iranian = iranian or ts_to_iranian(ts)
            num = iranian[2]
        elif code == "xmj":
            hijri = hijri or ts_to_hijri(ts)
            num = hijri[2]
        elif code == "xjj":
            hebrew = hebrew or ts_to_hebrew(ts)
            num = hebrew[2]
        elif code == "l":
            s.append(lang.get_weekday_name(int(obj_format("w")) + 1))
        elif code == "F":
            s.append(lang.get_month_name(int(ts[4:6])))
        elif code == "xiF":
            iranian = iranian or ts_to_iranian(ts)
            s.append(lang.get_iranian_calendar_month_name(iranian[1]))
        elif code == "xmF":
            hijri = hijri or ts_to_hijri(ts)
            s.append(lang.get_hijri_calendar_month_name(hijri[1]))
        elif code == "xjF":
            hebrew = hebrew or ts_to_hebrew(ts)
            s.append(lang.get_hebrew_calendar_month_name(hebrew[1]))
        elif code == "m":
            num = ts[4:6]
        elif code == "M":
            s.append(lang.get_month_abbreviation(int(ts[4:6])))
        elif code == "n":
            num = int(ts[4:6])
        elif code == "xin":
            iranian = iranian or ts_to_iranian(ts)
            num = iranian[1]
        elif code == "xmn":
            hijri = hijri or ts_to_hijri(ts)
            num = hijri[1]
        elif code == "xjn":
            hebrew = hebrew or ts_to_hebrew(ts)
            num = hebrew[1]
        elif code == "xjt":
            hebrew = hebrew or ts_to_hebrew(ts)
            num = hebrew[3]
        elif code == "Y":
            num = ts[0:4]
        elif code == "xiY":
            iranian = iranian or ts_to_iranian(ts)
            num = iranian[0]
        elif code == "xmY":
            hijri = hijri or ts_to_hijri(ts)
            num = hijri[0]
        elif code == "xjY":
            hebrew = hebrew or ts_to_hebrew(ts)
            num = hebrew[0]
        elif code == "xkY":
            thai = thai or ts_to_year(ts, "thai")
            num = thai[0]
        elif code == "xoY":
            minguo = minguo or ts_to_year(ts, "minguo")
            num = minguo[0]
        elif code == "xtY":
            tenno = tenno or ts_to_year(ts, "tenno")
            num = tenno[0]
        elif code == "y":
            num = ts[2:4]
        elif code == "xiy":
            iranian = iranian or ts_to_iranian(ts)
            num = str(iranian[0])[-2:]
        elif code == "xit":
            iranian = iranian or ts_to_iranian(ts)
            num = IRANIAN_DAYS[iranian[1] - 1]
        elif code == "xiz":
            iranian = iranian or ts_to_iranian(ts)
            num = iranian[3]
        elif code == "a":
            s.append("am" if int(ts[8:10]) < 12 else "pm")
        elif code == "A":
            s.append("AM" if int(ts[8:10]) < 12 else "PM")
        elif code == "g":
            num = int(ts[8:10]) % 12 or 12
        elif code == "G":
            num = int(ts[8:10])
        elif code == "h":
            num = f"{int(ts[8:10]) % 12 or 12:02d}"
        elif code == "H":
            num = ts[8:10]
        elif code == "i":
            num = ts[10:12]
        elif code == "s":
            num = ts[12:14]
        elif code in ("c", "r", "e", "O", "P", "T"):
            s.append(obj_format(code))
        elif code in ("w", "N", "z", "W", "t", "L", "o", "U", "I", "Z"):
            num = obj_format(code)
        elif code == "\\":
            # Backslash escaping
            if p < format_length - 1:
                p += 1
                s.append(format_[p])
            else:
                s.append("\\")
        elif code == '"':
            # Quoted literal
            if p < format_length - 1:
                end_quote = format_.find('"', p + 1)
                if end_quote == -1:
                    # No terminating quote, assume literal "
                    s.append('"')
                else:
                    s.append(format_[p + 1:end_quote])
                    p = end_quote
            else:
                # Quote at end of string, assume literal "
                s.append('"')
        else:
            s.append(format_[p])
        if num is not None:
            num = str(num)
            if raw_toggle or raw:
                s.append(num)
                raw = False
            elif roman:
                s.append(roman_numeral(num))
                roman = False
            elif hebrew_num:
                s.append(hebrew_numeral(num))
                hebrew_num = False
            elif re.fullmatch(r"[\d.]+", num) and num.isascii():
                s.append(lang.format_num_no_separators(num))
            else:
                s.append(num)
        p += 1
    return "".join(s)


def ts_to_iranian(ts: str) -> list[int]:
    """Algorithm by Roozbeh Pournader and Mohammad Toossi to convert Gregorian dates to Iranian dates. Originally
    written in C, it is released under the terms of GNU Lesser General Public License. Conversion to PHP was
    performed by Niklas Laxström. Link: http://www.farsiweb.info/jalali/jalali.c"""
    gy = int(ts[0:4]) - 1600
    gm = int(ts[4:6]) - 1
    gd = int(ts[6:8]) - 1

    # Days passed from the beginning (including leap years)
    g_day_no = 365 * gy + math.floor((gy + 3) / 4) - math.floor((gy + 99) / 100) + math.floor((gy + 399) / 400)

    # Add days of the past months of this year
    for i in range(gm):
        g_day_no += GREG_DAYS[i]

    # Leap years
    if gm > 1 and ((gy % 4 == 0 and gy % 100 != 0) or gy % 400 == 0):
        g_day_no += 1

    # Days passed in current month
    g_day_no += gd

    j_day_no = g_day_no - 79

    j_np = math.floor(j_day_no / 12053)
    j_day_no = _php_mod(j_day_no, 12053)

    jy = 979 + 33 * j_np + 4 * math.floor(j_day_no / 1461)
    j_day_no = _php_mod(j_day_no, 1461)

    if j_day_no >= 366:
        jy += math.floor((j_day_no - 1) / 365)
        j_day_no = _php_mod(j_day_no - 1, 365)

    jz = j_day_no

    i = 0
    while i < 11 and j_day_no >= IRANIAN_DAYS[i]:
        j_day_no -= IRANIAN_DAYS[i]
        i += 1

    return [jy, i + 1, j_day_no + 1, jz]


def _php_mod(a: int, b: int) -> int:
    """PHP's %: the sign of the dividend"""
    r = abs(a) % abs(b)
    return -r if a < 0 else r


def _php_int_div(a: float) -> int:
    """(int) of a division: truncation toward zero"""
    return int(a)


def ts_to_hijri(ts: str) -> list[int]:
    """Converting Gregorian dates to Hijri dates. Based on a PHP-Nuke block by Sharjeel which is released under
    GNU/GPL license"""
    year = int(ts[0:4])
    month = int(ts[4:6])
    day = int(ts[6:8])

    zd = day
    zm = month
    zy = year

    if zy > 1582 or (zy == 1582 and zm > 10) or (zy == 1582 and zm == 10 and zd > 14):
        zjd = (int((1461 * (zy + 4800 + int((zm - 14) / 12))) / 4)
               + int((367 * (zm - 2 - 12 * (int((zm - 14) / 12)))) / 12)
               - int((3 * int((zy + 4900 + int((zm - 14) / 12)) / 100)) / 4)
               + zd - 32075)
    else:
        zjd = 367 * zy - int((7 * (zy + 5001 + int((zm - 9) / 7))) / 4) + int((275 * zm) / 9) + zd + 1729777

    zl = zjd - 1948440 + 10632
    zn = int((zl - 1) / 10631)
    zl = zl - 10631 * zn + 354
    zj = (int((10985 - zl) / 5316)) * (int((50 * zl) / 17719)) + (int(zl / 5670)) * (int((43 * zl) / 15238))
    zl = zl - (int((30 - zj) / 15)) * (int((17719 * zj) / 50)) - (int(zj / 16)) * (int((15238 * zj) / 43)) + 29
    zm = int((24 * zl) / 709)
    zd = zl - int((709 * zm) / 24)
    zy = 30 * zn + zj - 30

    return [zy, zm, zd]


def _is_greg_leap(year: int) -> bool:
    return year % 400 == 0 or (year % 4 == 0 and year % 100 > 0)


def ts_to_hebrew(ts: str) -> list[int]:
    """Converting Gregorian dates to Hebrew dates. Based on a JavaScript code by Abu Mami and Yisrael Hersch
    (abu-mami@kaluach.net, http://www.kaluach.net), who permitted to translate the relevant functions into PHP and
    release them under GNU GPL. The months are counted from Tishrei = 1. In a leap year, Adar I is 13 and Adar II
    is 14. In a non-leap year, Adar is 6."""
    # Parse date
    year = int(ts[0:4])
    month = int(ts[4:6])
    day = int(ts[6:8])

    # Calculate Hebrew year
    hebrew_year = year + 3760

    # Month number when September = 1, August = 12
    month += 4
    if month > 12:
        # Next year
        month -= 12
        year += 1
        hebrew_year += 1

    # Calculate day of year from 1 September
    day_of_year = day
    for i in range(1, month):
        if i == 6:
            # February
            day_of_year += 28
            # Check if the year is leap
            if _is_greg_leap(year):
                day_of_year += 1
        elif i in (8, 10, 1, 3):
            day_of_year += 30
        else:
            day_of_year += 31

    # Calculate the start of the Hebrew year
    start = hebrew_year_start(hebrew_year)

    # Calculate next year's start
    if day_of_year <= start:
        # Day is before the start of the year - it is the previous year
        # Next year's start
        next_start = start
        # Previous year
        year -= 1
        hebrew_year -= 1
        # Add days since previous year's 1 September
        day_of_year += 365
        if _is_greg_leap(year):
            # Leap year
            day_of_year += 1
        # Start of the new (previous) year
        start = hebrew_year_start(hebrew_year)
    else:
        # Next year's start
        next_start = hebrew_year_start(hebrew_year + 1)

    # Calculate Hebrew day of year
    hebrew_day_of_year = day_of_year - start

    # Difference between year's days
    diff = next_start - start
    # Add 12 (or 13 for leap years) days to ignore the difference between Hebrew and Gregorian year (353 at least
    # vs. 365/6) - now the difference is only about the year type
    diff += 13 if _is_greg_leap(year) else 12

    # Check the year pattern, and is leap year
    # 0 means an incomplete year, 1 means a regular year, 2 means a complete year
    # This is mod 30, to work on both leap years (which add 30 days of Adar I) and non-leap years
    year_pattern = _php_mod(diff, 30)
    # Check if leap year
    is_leap = diff >= 30

    # Calculate day in the month from number of day in the Hebrew year
    # Don't check Adar - if the day is not in Adar, we will stop before; if it is in Adar, we will use it to check if
    # it is Adar I or Adar II
    hebrew_day = hebrew_day_of_year
    hebrew_month = 1
    days = 0
    while hebrew_month <= 12:
        # Calculate days in this month
        if is_leap and hebrew_month == 6:
            # Leap year - has Adar I, with 30 days, and Adar II, with 29 days
            days = 30
            if hebrew_day <= days:
                # Day in Adar I
                hebrew_month = 13
            else:
                # Subtract the days of Adar I
                hebrew_day -= days
                # Try Adar II
                days = 29
                if hebrew_day <= days:
                    # Day in Adar II
                    hebrew_month = 14
        elif hebrew_month == 2 and year_pattern == 2:
            # Cheshvan in a complete year (otherwise as the rule below)
            days = 30
        elif hebrew_month == 3 and year_pattern == 0:
            # Kislev in an incomplete year (otherwise as the rule below)
            days = 29
        else:
            # Odd months have 30 days, even have 29
            days = 30 - _php_mod(hebrew_month - 1, 2)
        if hebrew_day <= days:
            # In the current month
            break
        # Subtract the days of the current month
        hebrew_day -= days
        # Try in the next month
        hebrew_month += 1

    return [hebrew_year, hebrew_month, hebrew_day, days]


def hebrew_year_start(year: int) -> int:
    """This calculates the Hebrew year start, as days since 1 September. Based on Carl Friedrich Gauss algorithm
    for finding Easter date. Used for Hebrew date."""
    a = _php_mod(12 * (year - 1) + 17, 19)
    b = _php_mod(year - 1, 4)
    m = 32.044093161144 + 1.5542417966212 * a + b / 4.0 - 0.0031777940220923 * (year - 1)
    if m < 0:
        m -= 1
    mar = int(m)
    if m < 0:
        m += 1
    m -= mar

    c = _php_mod(mar + 3 * (year - 1) + 5 * b + 5, 7)
    if c == 0 and a > 11 and m >= 0.89772376543210:
        mar += 1
    elif c == 1 and a > 6 and m >= 0.63287037037037:
        mar += 2
    elif c in (2, 4, 6):
        mar += 1

    mar += int((year - 3761) / 100) - int((year - 3761) / 400) - 24
    return mar


def ts_to_year(ts: str, c_name: str) -> list:
    """Algorithm to convert Gregorian dates to Thai solar dates, Minguo dates or Minguo dates.
    Link: https://en.wikipedia.org/wiki/Thai_solar_calendar
          https://en.wikipedia.org/wiki/Minguo_calendar
          https://en.wikipedia.org/wiki/Japanese_era_name"""
    gy = int(ts[0:4])
    gm = int(ts[4:6])
    gd = int(ts[6:8])

    if c_name == "thai":
        # Thai solar dates
        # Add 543 years to the Gregorian calendar
        # Months and days are identical
        gy_offset = gy + 543
        # fix for dates between 1912 and 1941
        # https://en.wikipedia.org/?oldid=836596673#New_year
        if 1912 <= gy <= 1940:
            if gm <= 3:
                gy_offset -= 1
            gm = _php_mod(gm - 3, 12)
    elif c_name in ("minguo", "juche"):
        # Minguo dates
        # Deduct 1911 years from the Gregorian calendar
        # Months and days are identical
        gy_offset = gy - 1911
    elif c_name == "tenno":
        # Nengō dates up to Meiji period
        # Deduct years from the Gregorian calendar depending on the nengo periods
        # Months and days are identical
        if gy < 1912 or (gy == 1912 and gm < 7) or (gy == 1912 and gm == 7 and gd < 31):
            # Meiji period
            era, gy_gannen = "明治", gy - 1868 + 1
        elif ((gy == 1912 and gm == 7 and gd == 31) or (gy == 1912 and gm >= 8) or 1912 < gy < 1926
              or (gy == 1926 and gm < 12) or (gy == 1926 and gm == 12 and gd < 26)):
            # Taishō period
            era, gy_gannen = "大正", gy - 1912 + 1
        elif (gy == 1926 and gm == 12 and gd >= 26) or 1926 < gy < 1989 or (gy == 1989 and gm == 1 and gd < 8):
            # Shōwa period
            era, gy_gannen = "昭和", gy - 1926 + 1
        elif (gy == 1989 and gm == 1 and gd >= 8) or 1989 < gy < 2019 or (gy == 2019 and gm < 5):
            # Heisei period
            era, gy_gannen = "平成", gy - 1989 + 1
        else:
            # Reiwa period
            era, gy_gannen = "令和", gy - 2019 + 1
        gy_offset = era + ("元" if gy_gannen == 1 else str(gy_gannen))
    else:
        gy_offset = gy

    return [gy_offset, gm, gd]


_ROMAN = [
    ["", "I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X"],
    ["", "X", "XX", "XXX", "XL", "L", "LX", "LXX", "LXXX", "XC", "C"],
    ["", "C", "CC", "CCC", "CD", "D", "DC", "DCC", "DCCC", "CM", "M"],
    ["", "M", "MM", "MMM", "MMMM", "MMMMM", "MMMMMM", "MMMMMMM", "MMMMMMMM", "MMMMMMMMM", "MMMMMMMMMM"],
]


def roman_numeral(num) -> str:
    """Roman number formatting up to 10000"""
    num = _php_int_prefix(str(num))
    if num > 10000 or num <= 0:
        return str(num)
    s = ""
    pow10 = 1000
    for i in range(3, -1, -1):
        if num >= pow10:
            s += _ROMAN[i][num // pow10]
        num %= pow10
        pow10 //= 10
    return s


_HEBREW = [
    ["", "א", "ב", "ג", "ד", "ה", "ו", "ז", "ח", "ט", "י"],
    ["", "י", "כ", "ל", "מ", "נ", "ס", "ע", "פ", "צ", "ק"],
    ["", ["ק"], ["ר"], ["ש"], ["ת"], ["ת", "ק"], ["ת", "ר"], ["ת", "ש"], ["ת", "ת"], ["ת", "ת", "ק"],
     ["ת", "ת", "ר"]],
    ["", "א", "ב", "ג", "ד", "ה", "ו", "ז", "ח", "ט", "י"],
]


def hebrew_numeral(num) -> str:
    """Hebrew Gematria number formatting up to 9999"""
    num = _php_int_prefix(str(num))
    if num > 9999 or num <= 0:
        return str(num)

    # Round thousands have special notations
    if num == 1000:
        return "א' אלף"
    elif num % 1000 == 0:
        return _HEBREW[0][num // 1000] + "' אלפים"

    letters: list[str] = []
    pow10 = 1000
    for i in range(3, -1, -1):
        if num >= pow10:
            if num in (15, 16):
                letters.append(_HEBREW[0][9])
                letters.append(_HEBREW[0][num - 9])
                num = 0
            else:
                entry = _HEBREW[i][num // pow10]
                letters.extend(entry if isinstance(entry, list) else [entry])
                if pow10 == 1000:
                    letters.append("'")
        num %= pow10
        pow10 //= 10

    pre_transform_length = len(letters)
    if pre_transform_length == 1:
        # Add geresh (single quote) to one-letter numbers
        letters.append("'")
    else:
        last_index = pre_transform_length - 1
        letters[last_index] = letters[last_index].translate(str.maketrans("כמנפצ", "ךםןףץ"))
        # Add gershayim (double quote) to multiple-letter numbers, but exclude numbers with only one letter after
        # the thousands (1001-1009, 1020, 1030, 2001-2009, etc.)
        if letters[1] == "'" and pre_transform_length == 3:
            letters.append("'")
        else:
            letters.insert(len(letters) - 1, '"')
    return "".join(letters)


# ======================================================================================================================
# new DateTime( $text, $zone )
# ======================================================================================================================


class YearOutOfRange(ValueError):
    """A valid date whose year Python cannot hold (before 1 or after 9999)."""

    def __init__(self, year: int):
        super().__init__(f"year {year} is out of range")
        self.year = year


_MONTHS = {name.lower(): i + 1 for i, name in enumerate(MONTH_NAMES)}
_MONTHS.update({name[:3].lower(): i + 1 for i, name in enumerate(MONTH_NAMES)})
_MONTHS["sept"] = 9
_MONTH_RE = "(" + "|".join(sorted(_MONTHS, key=len, reverse=True)) + r")\.?"
_WEEKDAYS = {name.lower(): i for i, name in enumerate(WEEKDAY_NAMES)}  # 0 = Sunday
_WEEKDAYS.update({name[:3].lower(): i for i, name in enumerate(WEEKDAY_NAMES)})
_WEEKDAYS.update({"tues": 2, "wednes": 3, "thur": 4, "thurs": 4})
_WEEKDAY_RE = "(" + "|".join(sorted(_WEEKDAYS, key=len, reverse=True)) + ")"
_UNITS = {"sec": "s", "secs": "s", "second": "s", "seconds": "s", "min": "i", "mins": "i", "minute": "i",
          "minutes": "i", "hour": "h", "hours": "h", "day": "d", "days": "d", "week": "w", "weeks": "w",
          "fortnight": "f", "fortnights": "f", "forthnight": "f", "month": "m", "months": "m", "year": "y",
          "years": "y", "weekday": "wd", "weekdays": "wd"}
_UNIT_RE = "(" + "|".join(sorted(_UNITS, key=len, reverse=True)) + ")"
_RELTEXT = {"next": 1, "last": -1, "previous": -1, "this": 0, "first": 1, "second": 2, "third": 3, "fourth": 4,
            "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8, "ninth": 9, "tenth": 10, "eleventh": 11,
            "twelfth": 12}
_RELTEXT_RE = "(" + "|".join(sorted(_RELTEXT, key=len, reverse=True)) + ")"
# Time zone abbreviations (a part of timelib's table) -> offset in minutes
_TZ_ABBR = {
    "utc": 0, "gmt": 0, "ut": 0, "z": 0, "wet": 0, "west": 60, "bst": 60, "cet": 60, "cest": 120, "met": 60,
    "mest": 120, "eet": 120, "eest": 180, "msk": 180, "ist": 330, "est": -300, "edt": -240, "cst": -360,
    "cdt": -300, "mst": -420, "mdt": -360, "pst": -480, "pdt": -420, "akst": -540, "akdt": -480, "hst": -600,
    "jst": 540, "kst": 540, "aest": 600, "aedt": 660, "acst": 570, "awst": 480, "nzst": 720, "nzdt": 780,
}
_TZ_ABBR_RE = "(" + "|".join(sorted(_TZ_ABBR, key=len, reverse=True)) + ")"
_WS = r"[ \t,]*"
_SEP = r"[ \t.,-]*"


@dataclass
class _Parsed:
    y: Optional[int] = None
    m: Optional[int] = None
    d: Optional[int] = None
    h: Optional[int] = None
    i: Optional[int] = None
    s: Optional[int] = None
    us: int = 0
    tz: Optional[tzinfo] = None
    timestamp: Optional[float] = None
    rel: dict = field(default_factory=lambda: {"y": 0, "m": 0, "d": 0, "h": 0, "i": 0, "s": 0})
    weekday: Optional[tuple[int, int]] = None  # (weekday 0-6, behaviour: 0 this/next occurrence, n-th)
    first_last_day_of: Optional[str] = None
    have_date: bool = False
    have_time: bool = False
    have_relative: bool = False


def _year(text: str) -> int:
    y = int(text)
    if len(text) <= 2:
        y += 1900 if y >= 70 else 2000
    return y


def _set_time(st: _Parsed, h: int, i: int, s: int, meridian: Optional[str] = None, frac: str = "") -> None:
    if st.have_time:
        raise ValueError("Double time specification")
    if meridian:
        mer = meridian.replace(".", "").lower()
        if h > 12 or h == 0:
            raise ValueError("invalid hour for 12-hour clock")
        if mer == "am" and h == 12:
            h = 0
        elif mer == "pm" and h != 12:
            h += 12
    if h > 24 or i > 59 or s > 60:
        raise ValueError("invalid time")
    st.h, st.i, st.s = h, i, s
    st.us = int((frac + "000000")[:6]) if frac else 0
    st.have_time = True


def _set_date(st: _Parsed, y: Optional[int], m: Optional[int], d: Optional[int]) -> None:
    if st.have_date:
        raise ValueError("Double date specification")
    if m is not None and not 1 <= m <= 12:
        raise ValueError("invalid month")
    if d is not None and not 0 <= d <= 31:
        raise ValueError("invalid day")
    st.y, st.m, st.d = y, m, d
    st.have_date = True


def _zone_from_name(name: str) -> Optional[tzinfo]:
    low = name.lower()
    if low in _TZ_ABBR:
        return timezone(timedelta(minutes=_TZ_ABBR[low]))
    if "/" in name or low in ("utc", "gmt"):
        try:
            from zoneinfo import ZoneInfo

            return ZoneInfo(name)
        except Exception:  # noqa: BLE001 - unknown zone, or no time zone database
            return None
    return None


_TOKENS: list[tuple[str, re.Pattern]] = []


def _token(name: str, pattern: str) -> None:
    _TOKENS.append((name, re.compile(pattern, re.I)))


_TIME = r"(\d{1,2}):(\d{2})(?::(\d{2})(?:[.,:](\d+))?)?(?:[ \t]*(a\.?m\.?|p\.?m\.?)(?![a-z]))?"
_token("timestamp", r"@(-?\d+(?:\.\d+)?)")
_token("now", r"now\b")
_token("noon", r"noon\b")
_token("midnight", r"(?:midnight|today)\b")
_token("tomorrow", r"tomorrow\b")
_token("yesterday", r"yesterday\b")
_token("iso_datetime_compact", r"(\d{4})(\d{2})(\d{2})t(\d{2}):?(\d{2}):?(\d{2})(?:[.,](\d+))?")
_token("iso_date", r"([+-]?\d{4})-(\d{1,2})-(\d{1,2})(?!\d)")
_token("iso_date_slash", r"(\d{4})/(\d{1,2})/(\d{1,2})(?!\d)")
_token("date_compact", r"(\d{4})(\d{2})(\d{2})(?!\d)")
_token("american", r"(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?(?![\d/])")
_token("dotted", r"(\d{1,2})[.](\d{1,2})[.](\d{4}|\d{2})(?![\d.])")
_token("dmy_dash", r"(\d{1,2})-(\d{1,2})-(\d{4})(?!\d)")
_token("year_month", r"(\d{4})-(\d{1,2})(?![\d-])")
_token("time_t", r"t?" + _TIME)
_token("hour_meridian", r"(\d{1,2})[ \t]*(a\.?m\.?|p\.?m\.?)(?![a-z])")
_token("first_last_day_of", r"(first|last)[ \t]+day[ \t]+of\b")
_token("day_month_year", r"(\d{1,2})(?:st|nd|rd|th)?" + _SEP + _MONTH_RE + r"(?![a-z])(?:" + _SEP + r"(\d{4}))?(?!\d)")
_token("month_day_year", _MONTH_RE + r"(?![a-z])" + _SEP + r"(\d{1,2})(?:st|nd|rd|th)?(?![\d:])(?:" + _SEP
       + r"(\d{4}))?(?![\d:])")
_token("month_year", _MONTH_RE + r"(?![a-z])" + _SEP + r"(\d{4})(?!\d)")
_token("year_month_day_text", r"(\d{4})" + _SEP + _MONTH_RE + r"(?![a-z])" + _SEP + r"(\d{1,2})(?!\d)")
_token("month", _MONTH_RE + r"(?![a-z])")
_token("relative_number", r"([+-]?)[ \t]*(\d+)[ \t]*" + _UNIT_RE + r"(?![a-z])")
_token("relative_text_unit", _RELTEXT_RE + r"[ \t]+" + _UNIT_RE + r"(?![a-z])")
_token("relative_text_weekday", _RELTEXT_RE + r"[ \t]+" + _WEEKDAY_RE + r"(?![a-z])")
_token("weekday", _WEEKDAY_RE + r"(?![a-z])")
_token("ago", r"ago\b")
_token("year4", r"(\d{4})(?!\d)")
_token("tz_offset", r"(?:gmt|utc)?([+-])(\d{1,2})(?::?(\d{2}))?(?!\d)")
_token("tz_name", r"([A-Za-z]+(?:/[A-Za-z_+-]+)+)")
_token("tz_abbr", _TZ_ABBR_RE + r"(?![a-z])")


def parse_datetime(text: str, default_zone: tzinfo, now: datetime) -> datetime:
    """new DateTime( $text, $defaultZone ): the date and time a string describes, as an aware datetime. ``now`` is
    the base of relative formats and missing fields (PHP uses the current time).

    Supported: "now", "today"/"midnight", "noon", "tomorrow", "yesterday", "@<Unix time>"; ISO 8601 dates and
    times (2001-01-15, 2001-01-15T10:00:00, 20010115, 20010115T100000, fractions of a second); 2001/01/15,
    1/15/2001 and 1/15 (American), 15.01.2001, 15-01-2001, 2001-01; "15 January 2001", "January 15, 2001", "Jan
    2001", "2001 January 15", "January" (month names and three-letter abbreviations, ordinal suffixes); times
    10:00, 10:00:30, 10pm, 10:30 a.m.; relative parts "+1 day", "-2 weeks", "3 months ago", "next month", "last
    year", "next monday", "monday", "first day of next month", "last day of"; time zones Z, UTC, GMT, +01:00,
    -0500, common abbreviations (CET, EST, ...) and identifiers (Europe/Paris). Anything else raises ValueError, as
    PHP throws an exception."""
    st = _Parsed()
    pos = 0
    n = len(text)
    while pos < n:
        m = re.compile(r"[ \t\n,]+").match(text, pos)
        if m:
            pos = m.end()
            continue
        for name, regex in _TOKENS:
            m = regex.match(text, pos)
            if m and m.end() > pos:
                break
        else:
            raise ValueError(f"The timezone could not be found in the database / unexpected character at {pos}")
        _apply_token(st, name, m)
        pos = m.end()
    return _compose(st, default_zone, now)


def _apply_token(st: _Parsed, name: str, m: re.Match) -> None:
    g = m.groups()
    if name == "timestamp":
        st.timestamp = float(g[0])
        st.tz = timezone.utc
        st.have_date = st.have_time = True
    elif name == "now":
        pass
    elif name == "noon":
        st.h, st.i, st.s, st.us = 12, 0, 0, 0
        st.have_time = True
    elif name == "midnight":
        st.h, st.i, st.s, st.us = 0, 0, 0, 0
        st.have_time = True
    elif name in ("tomorrow", "yesterday"):
        st.rel["d"] += 1 if name == "tomorrow" else -1
        st.h, st.i, st.s, st.us = 0, 0, 0, 0
        st.have_time = True
    elif name == "iso_datetime_compact":
        _set_date(st, int(g[0]), int(g[1]), int(g[2]))
        _set_time(st, int(g[3]), int(g[4]), int(g[5]), None, g[6] or "")
    elif name in ("iso_date", "iso_date_slash", "date_compact"):
        _set_date(st, int(g[0]), int(g[1]), int(g[2]))
    elif name == "american":
        _set_date(st, _year(g[2]) if g[2] else None, int(g[0]), int(g[1]))
    elif name in ("dotted", "dmy_dash"):
        _set_date(st, _year(g[2]), int(g[1]), int(g[0]))
    elif name == "year_month":
        _set_date(st, int(g[0]), int(g[1]), 1)
    elif name == "time_t":
        _set_time(st, int(g[0]), int(g[1]), int(g[2] or 0), g[4], g[3] or "")
    elif name == "hour_meridian":
        _set_time(st, int(g[0]), 0, 0, g[1])
    elif name == "first_last_day_of":
        st.first_last_day_of = g[0].lower()
        st.have_relative = True
    elif name == "day_month_year":
        _set_date(st, int(g[2]) if g[2] else None, _MONTHS[g[1].lower()], int(g[0]))
    elif name == "month_day_year":
        _set_date(st, int(g[2]) if g[2] else None, _MONTHS[g[0].lower()], int(g[1]))
    elif name == "month_year":
        _set_date(st, int(g[1]), _MONTHS[g[0].lower()], 1)
    elif name == "year_month_day_text":
        _set_date(st, int(g[0]), _MONTHS[g[1].lower()], int(g[2]))
    elif name == "month":
        _set_date(st, None, _MONTHS[g[0].lower()], None)
    elif name == "relative_number":
        amount = int(g[1]) * (-1 if g[0] == "-" else 1)
        _add_relative(st, _UNITS[g[2].lower()], amount)
    elif name == "relative_text_unit":
        amount = _RELTEXT[g[0].lower()]
        _add_relative(st, _UNITS[g[1].lower()], amount)
    elif name == "relative_text_weekday":
        word = g[0].lower()
        amount = _RELTEXT[word]
        day = _WEEKDAYS[g[1].lower()]
        # "next monday": the first monday after today; "last monday": the last before; "this monday": today or
        # the next one
        st.weekday = (day, amount if word != "this" else 0)
        st.have_relative = True
        if not st.have_time:
            st.h, st.i, st.s, st.us = 0, 0, 0, 0
    elif name == "weekday":
        st.weekday = (_WEEKDAYS[g[0].lower()], 0)
        st.have_relative = True
        if not st.have_time:
            st.h, st.i, st.s, st.us = 0, 0, 0, 0
    elif name == "ago":
        for key in st.rel:
            st.rel[key] = -st.rel[key]
    elif name == "year4":
        if st.have_date and st.y is None:
            st.y = int(g[0])
        elif not st.have_date:
            _set_date(st, int(g[0]), None, None)
        else:
            raise ValueError("Double date specification")
    elif name == "tz_offset":
        minutes = int(g[1]) * 60 + int(g[2] or 0)
        if len(g[1]) > 2 or minutes > 18 * 60:
            raise ValueError("invalid time zone offset")
        st.tz = timezone(timedelta(minutes=-minutes if g[0] == "-" else minutes))
    elif name in ("tz_name", "tz_abbr"):
        zone = _zone_from_name(g[0])
        if zone is None:
            raise ValueError("The timezone could not be found in the database")
        st.tz = zone


def _add_relative(st: _Parsed, unit: str, amount: int) -> None:
    st.have_relative = True
    if unit == "w":
        st.rel["d"] += 7 * amount
    elif unit == "f":
        st.rel["d"] += 14 * amount
    elif unit == "wd":
        st.rel["wd"] = st.rel.get("wd", 0) + amount
    else:
        st.rel[unit] += amount


def _days_in_month(y: int, m: int) -> int:
    return calendar.monthrange(y, m)[1]


def _normalize(y: int, m: int, d: int, h: int, i: int, s: int, us: int) -> tuple:
    """timelib's do_range_limit: months overflow into years, days into months (31 February is 3 March)."""
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    if not 1 <= y <= 9999:
        raise YearOutOfRange(y)
    base = datetime(y, m, 1)
    try:
        dt = base + timedelta(days=d - 1, hours=h, minutes=i, seconds=s, microseconds=us)
    except OverflowError:
        raise YearOutOfRange(y) from None
    return dt


def _compose(st: _Parsed, default_zone: tzinfo, now: datetime) -> datetime:
    zone = st.tz or default_zone
    if st.timestamp is not None:
        whole = math.floor(st.timestamp)
        try:
            base = datetime(1970, 1, 1, tzinfo=timezone.utc) + timedelta(seconds=whole,
                                                                         microseconds=round((st.timestamp - whole) * 1e6))
        except OverflowError:
            raise YearOutOfRange(10000 if st.timestamp > 0 else 0) from None
        local = base.replace(tzinfo=None)
        zone = timezone.utc
    else:
        now_local = now.astimezone(zone).replace(tzinfo=None)
        # fields the string does not give are taken from now
        y = st.y if st.y is not None else now_local.year
        mo = st.m if st.m is not None else now_local.month
        d = st.d if st.d is not None else now_local.day
        if st.have_time:
            h, i, s, us = st.h or 0, st.i or 0, st.s or 0, st.us
        elif st.have_date:
            h, i, s, us = 0, 0, 0, 0
        else:
            h, i, s, us = now_local.hour, now_local.minute, now_local.second, 0
        if not 1 <= y <= 9999:
            raise YearOutOfRange(y)
        local = _normalize(y, mo, d, h, i, s, us)

    # relative parts
    rel = st.rel
    if rel["y"] or rel["m"]:
        y, mo = local.year + rel["y"], local.month + rel["m"]
        local = _normalize(y, mo, local.day, local.hour, local.minute, local.second, local.microsecond)
    if st.first_last_day_of == "first":
        local = local.replace(day=1)
    elif st.first_last_day_of == "last":
        local = local.replace(day=_days_in_month(local.year, local.month))
    try:
        local = local + timedelta(days=rel["d"], hours=rel["h"], minutes=rel["i"], seconds=rel["s"])
    except OverflowError:
        raise YearOutOfRange(10000) from None
    if rel.get("wd"):
        step = 1 if rel["wd"] > 0 else -1
        left = abs(rel["wd"])
        while left:
            local += timedelta(days=step)
            if local.weekday() < 5:
                left -= 1
    if st.weekday is not None:
        day, behaviour = st.weekday
        current = (local.weekday() + 1) % 7
        if behaviour == 0:
            delta = (day - current) % 7
        elif behaviour > 0:
            delta = (day - current) % 7 or 7
            delta += 7 * (behaviour - 1)
        else:
            delta = -((current - day) % 7 or 7)
        local += timedelta(days=delta)
    return local.replace(tzinfo=zone)
