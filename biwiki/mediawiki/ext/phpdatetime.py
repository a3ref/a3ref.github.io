# Ported from MediaWiki 1.39 includes/language/Language.php (https://www.mediawiki.org/), (C) MediaWiki
# contributors: Language::sprintfDate(), dateTimeObjFormat(), tsToIranian(), tsToHijri(), tsToHebrew(),
# hebrewYearStart(), tsToYear(), romanNumeral(), hebrewNumeral(), and the calendar month name messages; with the
# date strings of PHP's DateTime constructor after timelib as bundled with PHP 8.1 (ext/date/lib/parse_date.re,
# tm2unixtime.c; (C) Derick Rethans, MongoDB, Inc.; MIT license, notice below) and php_date.c.
# Changed by a3ref contributors on 2026-10-30: translated to Python; English only; DateTime::format() is
# re-implemented for the characters sprintfDate() passes on (PHP 8.1 output); timelib's re2c scanner is rebuilt
# with Python regular expressions (longest match, first rule on a tie), its rules, helper functions,
# timelib_fill_holes() and timelib_update_ts() translated; time zones from Python's zoneinfo.
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
from functools import lru_cache
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
        # the abbreviation of a zone identifier (tzdata's, e.g. "CET" or "+04"); "GMT+0100" for a bare offset
        if dt.tzinfo is None or dt.tzinfo is timezone.utc:
            return "UTC"
        if getattr(dt.tzinfo, "key", None):
            return dt.tzname() or _offset(dt, True)
        return "GMT" + _offset(dt, False)
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
# timelib (ext/date/lib in PHP 8.1), from which the scanner rules and the date arithmetic below are translated:
#
#   The MIT License (MIT)
#
#   Copyright (c) 2015-2019 Derick Rethans
#   Copyright (c) 2018 MongoDB, Inc.
#
#   Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
#   documentation files (the "Software"), to deal in the Software without restriction, including without
#   limitation the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the
#   Software, and to permit persons to whom the Software is furnished to do so, subject to the following
#   conditions:
#
#   The above copyright notice and this permission notice shall be included in all copies or substantial portions
#   of the Software.
#
#   THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED
#   TO THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL
#   THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF
#   CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
#   DEALINGS IN THE SOFTWARE.


class YearOutOfRange(ValueError):
    """A valid date whose year Python cannot hold (before 1 or after 9999)."""

    def __init__(self, year: int):
        super().__init__(f"year {year} is out of range")
        self.year = year


_SPECIAL_WEEKDAY = 0x01
_SPECIAL_DAY_OF_WEEK_IN_MONTH = 0x02
_SPECIAL_LAST_DAY_OF_WEEK_IN_MONTH = 0x03
_SPECIAL_FIRST_DAY_OF_MONTH = 0x01
_SPECIAL_LAST_DAY_OF_MONTH = 0x02
_TIME_PART_DONT_KEEP = 0x00
_TIME_PART_KEEP = 0x01
_MAX_ABBR_LEN = 6  # _POSIX_TZNAME_MAX

# timelib_relunit_lookup: word -> (unit, multiplier); units are the timelib_rel_time fields, "weekday" and
# "special"
_RELUNITS: dict[str, tuple[str, int]] = {
    "ms": ("us", 1000), "msec": ("us", 1000), "msecs": ("us", 1000), "millisecond": ("us", 1000),
    "milliseconds": ("us", 1000), "µs": ("us", 1), "usec": ("us", 1), "usecs": ("us", 1), "µsec": ("us", 1),
    "µsecs": ("us", 1), "microsecond": ("us", 1), "microseconds": ("us", 1),
    "sec": ("s", 1), "secs": ("s", 1), "second": ("s", 1), "seconds": ("s", 1),
    "min": ("i", 1), "mins": ("i", 1), "minute": ("i", 1), "minutes": ("i", 1),
    "hour": ("h", 1), "hours": ("h", 1),
    "day": ("d", 1), "days": ("d", 1), "week": ("d", 7), "weeks": ("d", 7),
    "fortnight": ("d", 14), "fortnights": ("d", 14), "forthnight": ("d", 14), "forthnights": ("d", 14),
    "month": ("m", 1), "months": ("m", 1), "year": ("y", 1), "years": ("y", 1),
    "weekday": ("special", _SPECIAL_WEEKDAY), "weekdays": ("special", _SPECIAL_WEEKDAY),
}
for _i, _name in enumerate(WEEKDAY_NAMES):  # 0 = Sunday
    for _word in (_name.lower() + "s", _name.lower(), _name[:3].lower()):
        _RELUNITS[_word] = ("weekday", _i)
del _i, _name, _word
# timelib_reltext_lookup: word -> (value, behavior)
_RELTEXT = {"first": (1, 0), "next": (1, 0), "second": (2, 0), "third": (3, 0), "fourth": (4, 0),
            "fifth": (5, 0), "sixth": (6, 0), "seventh": (7, 0), "eight": (8, 0), "eighth": (8, 0),
            "ninth": (9, 0), "tenth": (10, 0), "eleventh": (11, 0), "twelfth": (12, 0), "last": (-1, 0),
            "previous": (-1, 0), "this": (0, 1)}
_ROMAN_MONTHS = ["I", "II", "III", "IV", "V", "VI", "VII", "VIII", "IX", "X", "XI", "XII"]
# timelib_month_lookup
_MONTH_LOOKUP = {name.lower(): i + 1 for i, name in enumerate(MONTH_NAMES)}
_MONTH_LOOKUP.update({name[:3].lower(): i + 1 for i, name in enumerate(MONTH_NAMES)})
_MONTH_LOOKUP.update({name.lower(): i + 1 for i, name in enumerate(_ROMAN_MONTHS)})
_MONTH_LOOKUP["sept"] = 9
# timezonemap.h: the first entry of each abbreviation (what abbr_search() finds without an offset), as the UTC
# offset in seconds including DST
_TZ_ABBR_OFFSETS = {
    "a": 3600, "acdt": 37800, "acst": 34200, "addt": -7200, "adt": -10800, "aedt": 39600, "aest": 36000,
    "ahdt": -32400, "ahst": -36000, "akdt": -28800, "akst": -32400, "amt": -13840, "apt": -10800, "ast": -14400,
    "awdt": 32400, "awst": 28800, "awt": -10800, "b": 7200, "bdst": 7200, "bdt": -36000, "bmt": -14309, "bst": 3600,
    "c": 10800, "cast": 34200, "cat": 7200, "cddt": -14400, "cdt": -18000, "cemt": 10800, "cest": 7200, "cet": 3600,
    "chst": 36000, "cmt": -15408, "cpt": -18000, "cst": -21600, "cwt": -18000, "d": 14400, "dmt": -1521, "e": 18000,
    "eat": 10800, "eddt": -10800, "edt": -14400, "eest": 10800, "eet": 7200, "emt": -26248, "ept": -14400,
    "est": -18000, "ewt": -14400, "f": 21600, "ffmt": -14660, "fmt": -4056, "g": 25200, "gdt": 39600, "gmt": 0,
    "gst": 36000, "h": 28800, "hdt": -34200, "hkst": 32400, "hkt": 28800, "hmt": -19776, "hpt": -34200,
    "hst": -36000, "hwt": -34200, "i": 32400, "iddt": 14400, "idt": 10800, "imt": 25025, "ist": 7200, "jdt": 36000,
    "jmt": 8440, "jst": 32400, "k": 36000, "kdt": 36000, "kmt": 5736, "kst": 30600, "l": 39600, "lst": 9394,
    "m": 43200, "mddt": -18000, "mdst": 16279, "mdt": -21600, "mest": 7200, "met": 3600, "mmt": 9017, "mpt": -21600,
    "msd": 14400, "msk": 10800, "mst": -25200, "mwt": -21600, "n": -3600, "nddt": -5400, "ndt": -9052, "npt": -9000,
    "nst": -12600, "nwt": -9000, "nzdt": 46800, "nzmt": 41400, "nzst": 43200, "o": -7200, "p": -10800,
    "pddt": -21600, "pdt": -25200, "pkst": 21600, "pkt": 18000, "plmt": 25590, "pmt": -13236, "ppmt": -17340,
    "ppt": -25200, "pst": -28800, "pwt": -25200, "q": -14400, "qmt": -18840, "r": -18000, "rmt": 5794, "s": -21600,
    "sast": 7200, "sdmt": -16800, "sjmt": -20173, "smt": -13884, "sst": -39600, "t": -25200, "tbmt": 10751,
    "tmt": 12344, "u": -28800, "uct": 0, "utc": 0, "v": -32400, "w": -36000, "wast": 7200, "wat": 3600, "wemt": 7200,
    "west": 3600, "wet": 0, "wib": 25200, "wit": 32400, "wita": 28800, "wmt": 5040, "x": -39600, "y": -43200,
    "yddt": -25200, "ydt": -28800, "ypt": -28800, "yst": -32400, "ywt": -28800, "z": 0,
}
_ASCII_LOWER = str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz")


# ----------------------------------------------------------------------------------------------------------------------
# The regular expressions of parse_date.re ('...' is case-insensitive in re2c, "..." case-sensitive)
# ----------------------------------------------------------------------------------------------------------------------

def _alt(words) -> str:
    """An alternation that tries the longer words first, so that it matches what re2c's longest match would."""
    return "(?:" + "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True)) + ")"


_R_SPACE = r"[ \t]+"
_R_FRAC = r"\.[0-9]+"
_R_HOUR24 = r"(?:2[0-4]|[01]?[0-9])"
_R_HOUR24LZ = r"(?:2[0-4]|[01][0-9])"
_R_HOUR12 = r"(?:1[0-2]|0?[1-9])"
_R_MINUTE = r"[0-5]?[0-9]"
_R_MINUTELZ = r"[0-5][0-9]"
_R_SECOND = r"(?:60|[0-5]?[0-9])"
_R_SECONDLZ = r"(?:60|[0-5][0-9])"
_R_MERIDIAN = r"[ap]\.?m\.?(?:[\t ]|\Z)"
_R_TZ_ABBR = r"\(?[a-z]{1,6}\)?"
_R_TZ_ID = r"(?-i:[A-Z][a-z]+(?:[_/-][A-Za-z]+)+)"
_R_TZCORRECTION = (r"(?-i:GMT)?[+-](?:" + _R_HOUR24LZ + ":" + _R_MINUTELZ + ":" + _R_SECONDLZ + "|" + _R_HOUR24LZ
                   + _R_MINUTELZ + _R_SECONDLZ + "|" + _R_HOUR24 + "(?::?" + _R_MINUTE + ")?)")
_R_TZ = "(?:" + _R_TZCORRECTION + "|" + _R_TZ_ID + "|" + _R_TZ_ABBR + ")"

_R_MONTH = r"(?:1[0-2]|0?[0-9])"
_R_DAY = r"(?:3[01]|[0-2]?[0-9])(?:st|nd|rd|th)?"
_R_YEAR = r"[0-9]{1,4}"
_R_YEAR2 = r"[0-9]{2}"
_R_YEAR4 = r"[0-9]{4}"
_R_YEAR4WITHSIGN = r"[+-]?[0-9]{4}"
_R_YEARX = r"[+-][0-9]{5,19}"
_R_DAYOFYEAR = r"(?:36[0-6]|3[0-5][0-9]|[12][0-9][0-9]|0[1-9][0-9]|00[1-9])"
_R_WEEKOFYEAR = r"(?:5[0-3]|[1-4][0-9]|0[1-9])"
_R_MONTHLZ = r"(?:1[0-2]|0[0-9])"
_R_DAYLZ = r"(?:3[01]|[12][0-9]|0[0-9])"

_DAYFULLS = [name.lower() + "s" for name in WEEKDAY_NAMES]
_DAYFULL = [name.lower() for name in WEEKDAY_NAMES]
_DAYABBR = [name[:3].lower() for name in WEEKDAY_NAMES]
_R_DAYTEXT = _alt(_DAYFULLS + _DAYFULL + _DAYABBR + ["weekday", "weekdays"])
_MONTHFULL = [name.lower() for name in MONTH_NAMES]
_MONTHABBR = [name[:3].lower() for name in MONTH_NAMES] + ["sept"]
_R_MONTHABBR = _alt(_MONTHABBR)
_R_MONTHTEXT = "(?:" + _alt(_MONTHFULL + _MONTHABBR) + "|(?-i:" + _alt(_ROMAN_MONTHS) + "))"

_R_TIMETINY12 = _R_HOUR12 + r"[ \t]*" + _R_MERIDIAN
_R_TIMESHORT12 = _R_HOUR12 + "[:.]" + _R_MINUTELZ + r"[ \t]*" + _R_MERIDIAN
_R_TIMELONG12 = _R_HOUR12 + "[:.]" + _R_MINUTE + "[:.]" + _R_SECONDLZ + r"[ \t]*" + _R_MERIDIAN
_R_TIMETINY24 = "t" + _R_HOUR24
_R_TIMESHORT24 = "t?" + _R_HOUR24 + "[:.]" + _R_MINUTE
_R_TIMELONG24 = "t?" + _R_HOUR24 + "[:.]" + _R_MINUTE + "[:.]" + _R_SECOND
_R_ISO8601LONG = _R_TIMELONG24 + _R_FRAC
_R_ISO8601NORMTZ = "t?" + _R_HOUR24 + "[:.]" + _R_MINUTE + "[:.]" + _R_SECONDLZ + r"[ \t]*" + _R_TZ
_R_DATENOYEAR = _R_MONTHTEXT + r"[ .\t-]*" + _R_DAY + r"(?:[,.stndrh\t ]+|\Z)"
_R_RELTEXTNUMBER = _alt(["first", "second", "third", "fourth", "fifth", "sixth", "seventh", "eight", "eighth",
                         "ninth", "tenth", "eleventh", "twelfth"])
_R_RELTEXTTEXT = _alt(["next", "last", "previous", "this"])
_RELTEXTUNITS = [word for word in _RELUNITS if word != "week"]
_R_RELTEXTUNIT = _alt(_RELTEXTUNITS)

# The scanner rules in the order of parse_date.re: (rule, regular expression); a rule with several alternatives
# (re2c's "a | b") has one entry per alternative.
_RULES: list[tuple[str, re.Pattern[str]]] = []


def _rule(name: str, *patterns: str) -> None:
    for pattern in patterns:
        _RULES.append((name, re.compile(pattern, re.I | re.A)))


_rule("yesterday", "yesterday")
_rule("now", "now")
_rule("noon", "noon")
_rule("midnight", "midnight", "today")
_rule("tomorrow", "tomorrow")
_rule("timestamp", r"@-?[0-9]+")
_rule("timestampms", r"@-?[0-9]+\.[0-9]{0,6}")
_rule("firstdayof", "first day of", "last day of")
_rule("backof", "back of " + _R_HOUR24 + r"(?:[ \t]*" + _R_MERIDIAN + ")?",
      "front of " + _R_HOUR24 + r"(?:[ \t]*" + _R_MERIDIAN + ")?")
_rule("weekdayof", "(?:" + _R_RELTEXTNUMBER + "|" + _R_RELTEXTTEXT + ")" + _R_SPACE
      + _alt(_DAYFULLS + _DAYFULL + _DAYABBR) + _R_SPACE + "of")
_rule("time12", _R_TIMETINY12, _R_TIMESHORT12, _R_TIMELONG12)
_rule("mssqltime", _R_HOUR12 + ":" + _R_MINUTELZ + ":" + _R_SECONDLZ + "[:.][0-9]+" + _R_MERIDIAN)
_rule("time24", _R_TIMETINY24, _R_TIMESHORT24, _R_TIMELONG24, _R_ISO8601LONG)
_rule("gnunocolon", "t?" + _R_HOUR24LZ + _R_MINUTELZ)
_rule("iso8601nocolon", "t?" + _R_HOUR24LZ + _R_MINUTELZ + _R_SECONDLZ)
_rule("american", _R_MONTH + "/" + _R_DAY, _R_MONTH + "/" + _R_DAY + "/" + _R_YEAR)
_rule("iso8601date4", _R_YEAR4WITHSIGN + "-" + _R_MONTHLZ + "-" + _R_DAYLZ,
      _R_YEAR4 + "/" + _R_MONTHLZ + "/" + _R_DAYLZ + "/?", _R_YEAR4 + "/" + _R_MONTH + "/" + _R_DAY)
_rule("iso8601date2", _R_YEAR2 + "-" + _R_MONTHLZ + "-" + _R_DAYLZ)
_rule("iso8601datex", _R_YEARX + "-" + _R_MONTHLZ + "-" + _R_DAYLZ)
_rule("gnudateshorter", _R_YEAR4 + "-" + _R_MONTH)
_rule("gnudateshort", _R_YEAR + "-" + _R_MONTH + "-" + _R_DAY)
_rule("datefull", _R_DAY + r"[ \t.-]*" + _R_MONTHTEXT + r"[ \t.-]*" + _R_YEAR)
_rule("pointeddate4", _R_DAY + r"[.\t-]" + _R_MONTH + "[.-]" + _R_YEAR4)
_rule("pointeddate2", _R_DAY + r"[.\t]" + _R_MONTH + r"\." + _R_YEAR2)
_rule("datenoday", _R_MONTHTEXT + r"[ .\t-]*" + _R_YEAR4)
_rule("datenodayrev", _R_YEAR4 + r"[ .\t-]*" + _R_MONTHTEXT)
_rule("datetextual", _R_MONTHTEXT + r"[ .\t-]*" + _R_DAY + r"[,.stndrh\t ]+" + _R_YEAR, _R_DATENOYEAR)
_rule("datenoyearrev", _R_DAY + r"[ .\t-]*" + _R_MONTHTEXT)
_rule("datenocolon", _R_YEAR4 + _R_MONTHLZ + _R_DAYLZ)
_rule("xmlrpc",
      _R_YEAR4 + _R_MONTHLZ + _R_DAYLZ + "(?-i:T)" + _R_HOUR24 + ":" + _R_MINUTELZ + ":" + _R_SECONDLZ,
      _R_YEAR4 + _R_MONTHLZ + _R_DAYLZ + "t" + _R_HOUR24 + _R_MINUTELZ + _R_SECONDLZ,
      _R_YEAR4 + "-" + _R_MONTHLZ + "-" + _R_DAYLZ + "(?-i:T)" + _R_HOUR24LZ + ":" + _R_MINUTELZ + ":"
      + _R_SECONDLZ + _R_FRAC + "(?:" + _R_TZCORRECTION + ")?",
      _R_YEAR4 + "-" + _R_MONTH + "-" + _R_DAY + "(?-i:T)" + _R_HOUR24 + ":" + _R_MINUTE + ":" + _R_SECOND,
      _R_YEAR4 + ":" + _R_MONTHLZ + ":" + _R_DAYLZ + " " + _R_HOUR24LZ + ":" + _R_MINUTELZ + ":" + _R_SECONDLZ)
_rule("pgydotd", _R_YEAR4 + "[.-]?" + _R_DAYOFYEAR)
_rule("isoweekday", _R_YEAR4 + "-?(?-i:W)" + _R_WEEKOFYEAR + "-?[0-7]")
_rule("isoweek", _R_YEAR4 + "-?(?-i:W)" + _R_WEEKOFYEAR)
_rule("pgtextshort", _R_MONTHABBR + "-" + _R_DAYLZ + "-" + _R_YEAR)
_rule("pgtextreverse", _R_YEAR + "-" + _R_MONTHABBR + "-" + _R_DAYLZ)
_rule("clf", _R_DAY + "/" + _R_MONTHABBR + "/" + _R_YEAR4 + ":" + _R_HOUR24LZ + ":" + _R_MINUTELZ + ":"
      + _R_SECONDLZ + _R_SPACE + _R_TZCORRECTION)
_rule("year4", _R_YEAR4)
_rule("ago", "ago")
_rule("daytext", _R_DAYTEXT)
_rule("relativetextweek", _R_RELTEXTTEXT + _R_SPACE + "week")
_rule("relativetext", "(?:" + _R_RELTEXTNUMBER + "|" + _R_RELTEXTTEXT + ")" + _R_SPACE + _R_RELTEXTUNIT)
_rule("month", _alt(_MONTHFULL + _MONTHABBR))
_rule("tz", _R_TZCORRECTION, _R_TZ_ABBR, _R_TZ_ID)
_rule("dateshortwithtime12", _R_DATENOYEAR + _R_TIMESHORT12, _R_DATENOYEAR + _R_TIMELONG12)
_rule("dateshortwithtime24", _R_DATENOYEAR + _R_TIMESHORT24, _R_DATENOYEAR + _R_TIMELONG24,
      _R_DATENOYEAR + _R_ISO8601NORMTZ)
_rule("relative", r"[+-]*[ \t]*[0-9]{1,13}[ \t]*" + _alt(_RELTEXTUNITS + ["week"]))
_rule("skip", r"[ .,\t\n\x00]")


# ----------------------------------------------------------------------------------------------------------------------
# The parsed time (timelib_time) and the scanner's helpers
# ----------------------------------------------------------------------------------------------------------------------

@dataclass
class _Rel:
    """timelib_rel_time with the special and weekday fields."""
    y: int = 0
    m: int = 0
    d: int = 0
    h: int = 0
    i: int = 0
    s: int = 0
    us: int = 0
    weekday: int = 0
    weekday_behavior: int = 0
    have_weekday_relative: bool = False
    have_special_relative: bool = False
    special_type: int = 0
    special_amount: int = 0
    first_last_day_of: int = 0


@dataclass
class _Time:
    """timelib_time while a string is scanned; None is TIMELIB_UNSET."""
    y: Optional[int] = None
    m: Optional[int] = None
    d: Optional[int] = None
    h: Optional[int] = None
    i: Optional[int] = None
    s: Optional[int] = None
    us: Optional[int] = None
    zone: Optional[tzinfo] = None
    have_time: int = 0
    have_date: bool = False
    have_zone: int = 0
    have_relative: bool = False
    relative: _Rel = field(default_factory=_Rel)


def _have_time(t: _Time) -> None:
    """TIMELIB_HAVE_TIME()"""
    if t.have_time:
        raise ValueError("Double time specification")
    t.have_time = 1
    t.h = t.i = t.s = t.us = 0


def _unhave_time(t: _Time) -> None:
    """TIMELIB_UNHAVE_TIME()"""
    t.have_time = 0
    t.h = t.i = t.s = t.us = 0


def _have_date(t: _Time) -> None:
    """TIMELIB_HAVE_DATE()"""
    if t.have_date:
        raise ValueError("Double date specification")
    t.have_date = True


def _unhave_date(t: _Time) -> None:
    """TIMELIB_UNHAVE_DATE()"""
    t.have_date = False
    t.d = t.m = t.y = 0


def _have_tz(t: _Time) -> bool:
    """TIMELIB_HAVE_TZ(): False when the rule is to be skipped. A second time zone is only a warning (the first one
    stays), a third one an error."""
    if t.have_zone:
        t.have_zone += 1
        if t.have_zone > 2:
            raise ValueError("Double timezone specification")
        return False
    t.have_zone = 1
    return True


def _process_year(y: Optional[int], length: int) -> Optional[int]:
    """TIMELIB_PROCESS_YEAR(): years of fewer than four digits below 100 are 1970-2069."""
    if y is None or length >= 4:
        return y
    if y < 100:
        y += 2000 if y < 70 else 1900
    return y


def _strtol(text: str) -> int:
    m = re.match(r"[0-9]*", text)
    return int(m.group(0)) if m.group(0) else 0


def _fixed_zone(seconds: int) -> tzinfo:
    return timezone.utc if seconds == 0 else timezone(timedelta(seconds=seconds))


@lru_cache(maxsize=1)
def _zone_ids() -> dict[str, str]:
    try:
        from zoneinfo import available_timezones

        return {key.lower(): key for key in available_timezones()}
    except Exception:  # noqa: BLE001 - no time zone database
        return {}


def _zone_by_id(name: str) -> Optional[tzinfo]:
    """The time zone database lookup of timelib_parse_zone() (case-insensitive, as PHP's)."""
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
    except ImportError:
        return timezone.utc if name.lower() == "utc" else None
    for key in (name, _zone_ids().get(name.lower())):
        if key:
            try:
                return ZoneInfo(key)
            except Exception:  # noqa: BLE001 - unknown zone, invalid key, or no time zone database
                pass
    return timezone.utc if name.lower() == "utc" else None


class _Ptr:
    """A pointer into the text of one token, for timelib's helper functions (timelib_get_nr() and friends). Past
    the end it reads NUL, as C reads the terminator."""

    def __init__(self, s: str):
        self.s = s
        self.p = 0

    def ch(self, offset: int = 0) -> str:
        i = self.p + offset
        return self.s[i] if i < len(self.s) else "\0"

    def _digit(self) -> bool:
        return "0" <= self.ch() <= "9"

    def _letter(self) -> bool:
        c = self.ch()
        return "A" <= c <= "Z" or "a" <= c <= "z"

    def get_nr_ex(self, max_length: int) -> tuple[Optional[int], int]:
        """timelib_get_nr_ex(): the next number of at most max_length digits and its length"""
        while not self._digit():
            if self.ch() == "\0":
                return None, 0
            self.p += 1
        begin = self.p
        while self._digit() and self.p - begin < max_length:
            self.p += 1
        return int(self.s[begin:self.p]), self.p - begin

    def get_nr(self, max_length: int) -> Optional[int]:
        return self.get_nr_ex(max_length)[0]

    def skip_day_suffix(self) -> None:
        if self.ch().isspace():
            return
        if self.s[self.p:self.p + 2].translate(_ASCII_LOWER) in ("nd", "rd", "st", "th"):
            self.p += 2

    def get_frac_nr(self) -> Optional[int]:
        """timelib_get_frac_nr(): the fraction of a second at the pointer, in microseconds"""
        while self.ch() not in ".:" and not self._digit():
            if self.ch() == "\0":
                return None
            self.p += 1
        begin = self.p
        while self.ch() in ".:" or self._digit():
            self.p += 1
        number = re.match(r"[0-9]*(?:\.[0-9]*)?", self.s[begin + 1:self.p]).group(0)  # strtod()
        value = float(number) if number not in ("", ".") else 0.0
        return int(value * 10 ** (7 - (self.p - begin)))

    def get_signed_nr(self, max_length: int) -> int:
        """timelib_get_signed_nr(): every "-" before the number flips its sign"""
        while not self._digit() and self.ch() not in "+-":
            if self.ch() == "\0":
                raise ValueError("Found unexpected data")
            self.p += 1
        sign = 1
        while self.ch() in "+-":
            if self.ch() == "-":
                sign = -sign
            self.p += 1
        return sign * (self.get_nr(max_length) or 0)

    def _word(self) -> str:
        begin = self.p
        while self._letter():
            self.p += 1
        return self.s[begin:self.p].translate(_ASCII_LOWER)

    def get_relative_text(self, behavior: int) -> tuple[int, int]:
        """timelib_get_relative_text(): the amount of "next", "third", ... and its behavior (``behavior`` when the
        word is unknown)"""
        while self.ch() in " \t-/":
            self.p += 1
        value, found_behavior = _RELTEXT.get(self._word(), (0, behavior))
        return value, found_behavior

    def lookup_month(self) -> int:
        return _MONTH_LOOKUP.get(self._word(), 0)

    def get_month(self) -> int:
        while self.ch() in " \t-./":
            self.p += 1
        return self.lookup_month()

    def eat_spaces(self) -> None:
        while self.ch() in " \t":
            self.p += 1

    def lookup_relunit(self) -> Optional[tuple[str, int]]:
        begin = self.p
        while self.ch() not in "\0 ,\t;:/.-()":
            self.p += 1
        return _RELUNITS.get(self.s[begin:self.p].translate(_ASCII_LOWER))

    def meridian(self, h: int) -> int:
        """timelib_meridian(): what "am"/"pm" adds to the hour h"""
        while self.ch() not in "AaPp\0":
            self.p += 1
        if self.ch() in "aA":
            retval = -12 if h == 12 else 0
        else:
            retval = 12 if h != 12 else 0
        self.p += 1
        if self.ch() == ".":
            self.p += 1
        if self.ch() in "Mm":
            self.p += 1
        if self.ch() == ".":
            self.p += 1
        return retval

    def parse_tz_cor(self) -> tuple[int, bool]:
        """timelib_parse_tz_cor(): the offset in seconds after the sign, and whether it is valid"""
        begin = self.p
        while self._digit() or self.ch() == ":":
            self.p += 1
        text = self.s[begin:self.p]
        n = len(text)
        if n in (1, 2):  # H, HH
            return _strtol(text) * 3600, True
        if n in (3, 4):  # H:M, H:MM, HH:M, HHMM
            if text[1] == ":":
                return _strtol(text) * 3600 + _strtol(text[2:]) * 60, True
            if text[2] == ":":
                return _strtol(text) * 3600 + _strtol(text[3:]) * 60, True
            tmp = _strtol(text)
            return tmp // 100 * 3600 + tmp % 100 * 60, True
        if n == 5 and text[2] == ":":  # HH:MM
            return _strtol(text) * 3600 + _strtol(text[3:]) * 60, True
        if n == 6:  # HHMMSS
            tmp = _strtol(text)
            return tmp // 10000 * 3600 + tmp // 100 % 100 * 60 + tmp % 100, True
        if n == 8 and text[2] == ":" and text[5] == ":":  # HH:MM:SS
            return _strtol(text) * 3600 + _strtol(text[3:]) * 60 + _strtol(text[6:]), True
        return 0, False


def _parse_zone(t: _Time, p: _Ptr) -> bool:
    """timelib_parse_zone(): an offset, an abbreviation or a zone identifier; False when it is none of them."""
    while p.ch() in " \t(":
        p.p += 1
    if p.s.startswith("GMT", p.p) and p.ch(3) in "+-":
        p.p += 3
    zone: Optional[tzinfo] = None
    if p.ch() in "+-":
        sign = -1 if p.ch() == "-" else 1
        p.p += 1
        offset, found = p.parse_tz_cor()
        zone = _fixed_zone(sign * offset)
    else:
        begin = p.p
        while p._letter() or p._digit() or p.ch() in "/_-+":
            p.p += 1
        word = p.s[begin:p.p]
        found = False
        lower = word.translate(_ASCII_LOWER)
        # First, we lookup by abbreviation only
        if len(word) < _MAX_ABBR_LEN and lower in _TZ_ABBR_OFFSETS:
            zone = _fixed_zone(_TZ_ABBR_OFFSETS[lower])
            found = True
        # Otherwise, we look if we have a TimeZone identifier
        if not found or word == "UTC":
            by_id = _zone_by_id(word)
            if by_id is not None:
                zone = by_id
                found = True
    while p.ch() == ")":
        p.p += 1
    if found:
        t.zone = zone
    return found


def _parse_zone_rest(t: _Time, p: _Ptr) -> None:
    """The time zone some rules allow at the end of their token."""
    if p.ch() != "\0" and not _parse_zone(t, p):
        raise ValueError("The timezone could not be found in the database")


def _set_relative(t: _Time, p: _Ptr, amount: int, behavior: int, time_part: int) -> None:
    """timelib_set_relative(): ``amount`` times the unit word at the pointer."""
    relunit = p.lookup_relunit()
    if relunit is None:
        return
    unit, multiplier = relunit
    rel = t.relative
    if unit == "weekday":
        t.have_relative = rel.have_weekday_relative = True
        if time_part != _TIME_PART_KEEP:
            _unhave_time(t)
        rel.d += (amount - 1 if amount > 0 else amount) * 7
        rel.weekday = multiplier
        rel.weekday_behavior = behavior
    elif unit == "special":
        t.have_relative = rel.have_special_relative = True
        if time_part != _TIME_PART_KEEP:
            _unhave_time(t)
        rel.special_type = multiplier
        rel.special_amount = amount
    else:
        setattr(rel, unit, getattr(rel, unit) + amount * multiplier)


def _day_of_week(y: int, m: int, d: int) -> int:
    """timelib_day_of_week(): 0 is Sunday"""
    return (_days_from_civil(y, m, d) + 4) % 7


def _daynr_from_weeknr(iy: int, iw: int, id_: int) -> int:
    """timelib_daynr_from_weeknr(): the day of the year of ISO week iw, day id_ (counted from 1 January)."""
    dow = _day_of_week(iy, 1, 1)
    day = 0 - (dow - 7 if dow > 4 else dow)
    return day + (iw - 1) * 7 + id_


def _scan_rule(t: _Time, rule: str, p: _Ptr) -> None:
    """The action of a scanner rule of parse_date.re, on the text ``p`` it matched."""
    rel = t.relative
    if rule == "yesterday":
        t.have_relative = True
        _unhave_time(t)
        rel.d = -1
    elif rule == "now":
        pass
    elif rule == "noon":
        _unhave_time(t)
        _have_time(t)
        t.h = 12
    elif rule == "midnight":
        _unhave_time(t)
    elif rule == "tomorrow":
        t.have_relative = True
        _unhave_time(t)
        rel.d = 1
    elif rule in ("timestamp", "timestampms"):
        t.have_relative = True
        _unhave_date(t)
        _unhave_time(t)
        if not _have_tz(t):
            return
        is_negative = p.ch(1) == "-"
        i = p.get_signed_nr(24)
        if rule == "timestampms":
            before = p.p
            us = p.get_signed_nr(6)
            us = us * 10 ** (7 - (p.p - before))
            rel.us = -us if is_negative else us
        t.y, t.m, t.d = 1970, 1, 1
        t.h = t.i = t.s = t.us = 0
        rel.s += i
        t.zone = timezone.utc
    elif rule == "firstdayof":
        t.have_relative = True
        rel.first_last_day_of = _SPECIAL_LAST_DAY_OF_MONTH if p.ch() in "lL" else _SPECIAL_FIRST_DAY_OF_MONTH
    elif rule == "backof":
        _unhave_time(t)
        _have_time(t)
        if p.ch() == "b":
            t.h = p.get_nr(2)
            t.i = 15
        else:
            t.h = p.get_nr(2) - 1
            t.i = 45
        if p.ch() != "\0":
            p.eat_spaces()
            t.h += p.meridian(t.h)
    elif rule == "weekdayof":
        t.have_relative = rel.have_special_relative = True
        i, behavior = p.get_relative_text(0)
        p.eat_spaces()
        if i > 0:  # first, second... etc
            rel.special_type = _SPECIAL_DAY_OF_WEEK_IN_MONTH
            _set_relative(t, p, i, 1, _TIME_PART_DONT_KEEP)
        else:  # last
            rel.special_type = _SPECIAL_LAST_DAY_OF_WEEK_IN_MONTH
            _set_relative(t, p, i, behavior, _TIME_PART_DONT_KEEP)
    elif rule == "time12":
        _have_time(t)
        t.h = p.get_nr(2)
        if p.ch() in ":.":
            t.i = p.get_nr(2)
            if p.ch() in ":.":
                t.s = p.get_nr(2)
        t.h += p.meridian(t.h)
    elif rule == "mssqltime":
        _have_time(t)
        t.h = p.get_nr(2)
        t.i = p.get_nr(2)
        if p.ch() in ":.":
            t.s = p.get_nr(2)
            if p.ch() in ":.":
                t.us = p.get_frac_nr()
        p.eat_spaces()
        t.h += p.meridian(t.h)
    elif rule == "time24":
        _have_time(t)
        t.h = p.get_nr(2)
        if p.ch() in ":.":
            t.i = p.get_nr(2)
            if p.ch() in ":.":
                t.s = p.get_nr(2)
                if p.ch() == ".":
                    t.us = p.get_frac_nr()
        _parse_zone_rest(t, p)
    elif rule == "gnunocolon":
        # four digits are a time (HHMM), or a year after a time
        if t.have_time == 0:
            t.h = p.get_nr(2)
            t.i = p.get_nr(2)
            t.s = 0
        elif t.have_time == 1:
            t.y = p.get_nr(4)
        else:
            raise ValueError("Double time specification")
        t.have_time += 1
    elif rule == "iso8601nocolon":
        _have_time(t)
        t.h = p.get_nr(2)
        t.i = p.get_nr(2)
        t.s = p.get_nr(2)
        _parse_zone_rest(t, p)
    elif rule == "american":
        _have_date(t)
        t.m = p.get_nr(2)
        t.d = p.get_nr(2)
        if p.ch() == "/":
            t.y = _process_year(*p.get_nr_ex(4))
    elif rule == "iso8601date4":
        _have_date(t)
        t.y = p.get_signed_nr(4)
        t.m = p.get_nr(2)
        t.d = p.get_nr(2)
    elif rule in ("iso8601date2", "gnudateshort"):
        _have_date(t)
        y, length = p.get_nr_ex(4)
        t.m = p.get_nr(2)
        t.d = p.get_nr(2)
        t.y = _process_year(y, length)
    elif rule == "iso8601datex":
        _have_date(t)
        t.y = p.get_signed_nr(19)
        t.m = p.get_nr(2)
        t.d = p.get_nr(2)
    elif rule == "gnudateshorter":
        _have_date(t)
        y, length = p.get_nr_ex(4)
        t.m = p.get_nr(2)
        t.d = 1
        t.y = _process_year(y, length)
    elif rule == "datefull":
        _have_date(t)
        t.d = p.get_nr(2)
        p.skip_day_suffix()
        t.m = p.get_month()
        t.y = _process_year(*p.get_nr_ex(4))
    elif rule == "pointeddate4":
        _have_date(t)
        t.d = p.get_nr(2)
        t.m = p.get_nr(2)
        t.y = p.get_nr(4)
    elif rule == "pointeddate2":
        _have_date(t)
        t.d = p.get_nr(2)
        t.m = p.get_nr(2)
        t.y = _process_year(*p.get_nr_ex(2))
    elif rule == "datenoday":
        _have_date(t)
        t.m = p.get_month()
        y, length = p.get_nr_ex(4)
        t.d = 1
        t.y = _process_year(y, length)
    elif rule == "datenodayrev":
        _have_date(t)
        y, length = p.get_nr_ex(4)
        t.m = p.get_month()
        t.d = 1
        t.y = _process_year(y, length)
    elif rule in ("datetextual", "pgtextshort"):
        _have_date(t)
        t.m = p.get_month()
        t.d = p.get_nr(2)
        t.y = _process_year(*p.get_nr_ex(4))
    elif rule == "datenoyearrev":
        _have_date(t)
        t.d = p.get_nr(2)
        p.skip_day_suffix()
        t.m = p.get_month()
    elif rule == "datenocolon":
        _have_date(t)
        t.y = p.get_nr(4)
        t.m = p.get_nr(2)
        t.d = p.get_nr(2)
    elif rule == "xmlrpc":
        _have_time(t)
        _have_date(t)
        t.y = p.get_nr(4)
        t.m = p.get_nr(2)
        t.d = p.get_nr(2)
        t.h = p.get_nr(2)
        t.i = p.get_nr(2)
        t.s = p.get_nr(2)
        if p.ch() == ".":
            t.us = p.get_frac_nr()
            _parse_zone_rest(t, p)  # timezone is optional
    elif rule == "pgydotd":
        _have_date(t)
        y, length = p.get_nr_ex(4)
        t.d = p.get_nr(3)
        t.m = 1
        t.y = _process_year(y, length)
    elif rule in ("isoweekday", "isoweek"):
        _have_date(t)
        t.have_relative = True
        t.y = p.get_nr(4)
        w = p.get_nr(2)
        d = p.get_nr(1) if rule == "isoweekday" else 1
        t.m = 1
        t.d = 1
        rel.d = _daynr_from_weeknr(t.y, w, d)
    elif rule == "pgtextreverse":
        _have_date(t)
        y, length = p.get_nr_ex(4)
        t.m = p.get_month()
        t.d = p.get_nr(2)
        t.y = _process_year(y, length)
    elif rule == "clf":
        _have_time(t)
        _have_date(t)
        t.d = p.get_nr(2)
        t.m = p.get_month()
        t.y = p.get_nr(4)
        t.h = p.get_nr(2)
        t.i = p.get_nr(2)
        t.s = p.get_nr(2)
        if not _parse_zone(t, p):
            raise ValueError("The timezone could not be found in the database")
    elif rule == "year4":
        t.y = p.get_nr(4)
    elif rule == "ago":
        rel.y, rel.m, rel.d, rel.h, rel.i, rel.s = -rel.y, -rel.m, -rel.d, -rel.h, -rel.i, -rel.s
        rel.weekday = -rel.weekday
        if rel.weekday == 0:
            rel.weekday = -7
        if rel.have_special_relative and rel.special_type == _SPECIAL_WEEKDAY:
            rel.special_amount = -rel.special_amount
    elif rule == "daytext":
        t.have_relative = rel.have_weekday_relative = True
        _unhave_time(t)
        rel.weekday = p.lookup_relunit()[1]
        if rel.weekday_behavior != 2:
            rel.weekday_behavior = 1
    elif rule == "relativetextweek":
        t.have_relative = True
        i, behavior = p.get_relative_text(0)
        p.eat_spaces()
        _set_relative(t, p, i, behavior, _TIME_PART_DONT_KEEP)
        rel.weekday_behavior = 2
        # to handle the format weekday + last/this/next week
        if not rel.have_weekday_relative:
            rel.have_weekday_relative = True
            rel.weekday = 1
    elif rule == "relativetext":
        t.have_relative = True
        i, behavior = p.get_relative_text(0)
        p.eat_spaces()
        _set_relative(t, p, i, behavior, _TIME_PART_DONT_KEEP)
    elif rule == "month":
        _have_date(t)
        t.m = p.lookup_month()
    elif rule == "tz":
        if not _have_tz(t):
            return
        if not _parse_zone(t, p):
            raise ValueError("The timezone could not be found in the database")
    elif rule in ("dateshortwithtime12", "dateshortwithtime24"):
        _have_date(t)
        t.m = p.get_month()
        t.d = p.get_nr(2)
        _have_time(t)
        t.h = p.get_nr(2)
        t.i = p.get_nr(2)
        if rule == "dateshortwithtime12":
            if p.ch() in ":.":
                t.s = p.get_nr(2)
                if p.ch() == ".":
                    t.us = p.get_frac_nr()
            t.h += p.meridian(t.h)
        else:
            if p.ch() == ":":
                t.s = p.get_nr(2)
                if p.ch() == ".":
                    t.us = p.get_frac_nr()
            _parse_zone_rest(t, p)
    elif rule == "relative":
        t.have_relative = True
        i = p.get_signed_nr(24)
        p.eat_spaces()
        _set_relative(t, p, i, 1, _TIME_PART_KEEP)


def parse_datetime(text: str, default_zone: tzinfo, now: datetime) -> datetime:
    """new DateTime( $text, $defaultZone ): the date and time a string describes, as an aware datetime in the zone
    the string names (else ``default_zone``). ``now``, taken in ``default_zone``, fills the fields the string leaves
    out and is the base of relative formats (PHP uses the current time).

    All of timelib's formats (https://www.php.net/manual/en/datetime.formats.php): "now", "today", "midnight",
    "noon", "tomorrow", "yesterday", "@<Unix time>[.<fraction>]"; ISO 8601 and other numeric dates (2001-01-15,
    +2001-01-15, +10000-01-15, 01-01-15, 2001-1-5, 2001/01/15, 1/15/2001, 1/15, 15.01.2001, 15-01-2001, 15.01.01,
    20010115, 2001-01, 2001.032, 2001W03, 2001-W03-2); dates with month names or Roman numerals (15 January 2001,
    15-Jan-01, January 15, 2001, Jan 2001, 2001 Jan, January 15, 15 Jan, January, Jan-15-2001, 2001-Jan-15); times
    (10:00, 10.00.30, t1000, 10:00:30.5, 100030, 10pm, 10:30 a.m., 10:00:00.5pm, back of 7pm); combined forms
    (2001-01-15T10:00:00Z, 20010115T100000, 2001-01-15T10:00:00.5+01:00, 2001:01:15 10:00:00, 10/Oct/2000:13:55:36
    -0700, Jan 15 10:00); relative parts (+1 day, -2 weeks, 3 months ago, +1 weekday, next month, last year, next
    monday, monday, this week, first day of next month, last day of, first monday of January); time zones (Z, UTC,
    GMT+1, +01:00, -0500, timelib's abbreviations such as CET or EST, identifiers such as Europe/Paris). Four digits
    alone are a time (2001 is 20:01), after a time a year. An invalid date such as 31 February overflows into the
    next month, as in PHP. Anything timelib reports as an error raises ValueError, as PHP throws an exception; a
    year Python's datetime cannot hold raises YearOutOfRange."""
    s = text.strip(" \t\n\r\v\f")
    t = _Time()
    pos, n = 0, len(s)
    while pos < n:
        best_rule, best = "", None
        for rule, regex in _RULES:
            m = regex.match(s, pos)
            if m and (best is None or m.end() > best.end()):
                best_rule, best = rule, m
        if best is None or best.end() == pos:
            raise ValueError(f"Unexpected character at position {pos}")
        if best_rule != "skip":
            _scan_rule(t, best_rule, _Ptr(best.group(0)))
        pos = best.end()
    return _compose(t, default_zone, now)


# ----------------------------------------------------------------------------------------------------------------------
# timelib_fill_holes() and timelib_update_ts() (tm2unixtime.c)
# ----------------------------------------------------------------------------------------------------------------------

def _days_from_civil(y: int, m: int, d: int) -> int:
    """Days since 1970-01-01 of a proleptic Gregorian date (timelib_epoch_days_from_time())."""
    y -= m <= 2
    era = y // 400
    year_of_era = y - era * 400
    day_of_year = (153 * (m + (-3 if m > 2 else 9)) + 2) // 5 + d - 1
    day_of_era = year_of_era * 365 + year_of_era // 4 - year_of_era // 100 + day_of_year
    return era * 146097 + day_of_era - 719468


def _civil_from_days(z: int) -> tuple[int, int, int]:
    z += 719468
    era = z // 146097
    day_of_era = z - era * 146097
    year_of_era = (day_of_era - day_of_era // 1460 + day_of_era // 36524 - day_of_era // 146096) // 365
    day_of_year = day_of_era - (365 * year_of_era + year_of_era // 4 - year_of_era // 100)
    mp = (5 * day_of_year + 2) // 153
    d = day_of_year - (153 * mp + 2) // 5 + 1
    m = mp + 3 if mp < 10 else mp - 9
    return year_of_era + era * 400 + (m <= 2), m, d


def _c_div(a: int, b: int) -> int:
    """C's integer division: truncation toward zero"""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _do_normalize(t: _Time) -> None:
    """timelib_do_normalize(): seconds overflow into minutes, ..., days into months (31 February is 3 March)."""
    q, t.us = divmod(t.us, 1000000)
    t.s += q
    q, t.s = divmod(t.s, 60)
    t.i += q
    q, t.i = divmod(t.i, 60)
    t.h += q
    q, t.h = divmod(t.h, 24)
    t.d += q
    q, m = divmod(t.m - 1, 12)
    t.y += q
    t.y, t.m, t.d = _civil_from_days(_days_from_civil(t.y, m + 1, 1) + t.d - 1)


def _do_adjust_for_weekday(t: _Time) -> None:
    rel = t.relative
    current_dow = _day_of_week(t.y, t.m, t.d)
    if rel.weekday_behavior == 2:
        # To make "this week" work, where the current DOW is a "sunday"
        if current_dow == 0 and rel.weekday != 0:
            rel.weekday -= 7
        # To make "sunday this week" work, where the current DOW is not a "sunday"
        if rel.weekday == 0 and current_dow != 0:
            rel.weekday = 7
        t.d -= current_dow
        t.d += rel.weekday
        return
    difference = rel.weekday - current_dow
    if (rel.d < 0 and difference < 0) or (rel.d >= 0 and difference <= -rel.weekday_behavior):
        difference += 7
    if rel.weekday >= 0:
        t.d += difference
    else:
        t.d -= 7 - (abs(rel.weekday) - current_dow)
    rel.have_weekday_relative = False


def _do_adjust_first_last_day_of(t: _Time) -> None:
    if t.relative.first_last_day_of == _SPECIAL_FIRST_DAY_OF_MONTH:
        t.d = 1
    elif t.relative.first_last_day_of == _SPECIAL_LAST_DAY_OF_MONTH:
        t.d = 0
        t.m += 1


def _do_adjust_special_weekday(t: _Time) -> None:
    count = t.relative.special_amount
    dow = _day_of_week(t.y, t.m, t.d)
    # Add increments of 5 weekdays as a week, leaving the DOW unchanged.
    t.d += _c_div(count, 5) * 7
    # Deal with the remainder.
    rem = count - 5 * _c_div(count, 5)
    if count > 0:
        if rem == 0:
            # Head back to Friday if we stop on the weekend.
            if dow == 0:
                t.d -= 2
            elif dow == 6:
                t.d -= 1
        elif dow == 6:
            # We ended up on Saturday, but there's still work to do, so move to Sunday and continue from there.
            t.d += 1
        elif dow + rem > 5:
            # We're on a weekday, but we're going past Friday, so skip right over the weekend.
            t.d += 2
    else:
        # Completely mirror the forward direction. This also covers the 0 case, since if we start on the weekend,
        # we want to move forward as if we stopped there while going backwards.
        if rem == 0:
            if dow == 6:
                t.d += 2
            elif dow == 0:
                t.d += 1
        elif dow == 0:
            t.d -= 1
        elif dow + rem < 1:
            t.d -= 2
    t.d += rem


def _compose(t: _Time, default_zone: tzinfo, now: datetime) -> datetime:
    """php_date_initialize(): timelib_fill_holes() with the current time in the given zone, then
    timelib_update_ts() (do_adjust_special_early(), do_adjust_relative(), do_adjust_special())."""
    now_local = now.astimezone(default_zone)
    if t.have_date and not t.have_time:
        t.h = t.i = t.s = t.us = 0
    if any(v is not None for v in (t.y, t.m, t.d, t.h, t.i, t.s)):
        if t.us is None:
            t.us = 0
    elif t.us is None:
        t.us = now_local.microsecond
    t.y = now_local.year if t.y is None else t.y
    t.m = now_local.month if t.m is None else t.m
    t.d = now_local.day if t.d is None else t.d
    t.h = now_local.hour if t.h is None else t.h
    t.i = now_local.minute if t.i is None else t.i
    t.s = now_local.second if t.s is None else t.s
    zone = t.zone if t.zone is not None else default_zone
    rel = t.relative

    # do_adjust_special_early()
    if rel.have_special_relative:
        if rel.special_type == _SPECIAL_DAY_OF_WEEK_IN_MONTH:
            t.d = 1
            t.m += rel.m
            rel.m = 0
        elif rel.special_type == _SPECIAL_LAST_DAY_OF_WEEK_IN_MONTH:
            t.d = 1
            t.m += rel.m + 1
            rel.m = 0
    _do_adjust_first_last_day_of(t)
    _do_normalize(t)

    # do_adjust_relative()
    if rel.have_weekday_relative:
        _do_adjust_for_weekday(t)
    _do_normalize(t)
    if t.have_relative:
        t.us += rel.us
        t.s += rel.s
        t.i += rel.i
        t.h += rel.h
        t.d += rel.d
        t.m += rel.m
        t.y += rel.y
    _do_adjust_first_last_day_of(t)
    _do_normalize(t)

    # do_adjust_special()
    if rel.have_special_relative and rel.special_type == _SPECIAL_WEEKDAY:
        _do_adjust_special_weekday(t)
    _do_normalize(t)

    if not 1 <= t.y <= 9999:
        raise YearOutOfRange(t.y)
    return datetime(t.y, t.m, t.d, t.h, t.i, t.s, t.us, tzinfo=zone)
