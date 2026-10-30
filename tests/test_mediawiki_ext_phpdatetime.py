# Tests of biwiki/mediawiki/ext/phpdatetime.py. The first cases are the #time tests of the ParserFunctions
# extension's tests/parser/funcsParserTests.txt (https://www.mediawiki.org/wiki/Extension:ParserFunctions),
# (C) ParserFunctions contributors, GPL-2.0-or-later; translated to Python by a3ref contributors on 2026-10-30, who
# added the cases per format character of Language::sprintfDate() and per date format of PHP's DateTime below.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of sprintf_date() (Language::sprintfDate) and parse_datetime() (new DateTime), with PHP's results."""
from __future__ import annotations

import re
import unittest
from datetime import datetime, timedelta, timezone

from biwiki.mediawiki.ext.phpdatetime import (YearOutOfRange, hebrew_numeral, parse_datetime, roman_numeral,
                                              sprintf_date)

UTC = timezone.utc
# the parser tests' fake time: 1970-01-01 00:02:03 UTC
FAKE_NOW = datetime(1970, 1, 1, 0, 2, 3, tzinfo=UTC)
# a Wednesday afternoon, for the relative formats
NOW = datetime(2024, 5, 15, 13, 45, 30, tzinfo=UTC)


def _zone(name: str):
    try:
        from zoneinfo import ZoneInfo

        return ZoneInfo(name)
    except Exception:  # noqa: BLE001 - no time zone database
        return None


HAVE_TZDATA = _zone("Europe/Paris") is not None


def ts_of(dt: datetime) -> str:
    """DateTime::format( 'YmdHis' )"""
    return f"{dt.year:04d}{dt.month:02d}{dt.day:02d}{dt.hour:02d}{dt.minute:02d}{dt.second:02d}"


def time_(format_: str, date: str = "", now: datetime = FAKE_NOW) -> str:
    """ParserFunctions::timeCommon() for UTC output, without the error messages."""
    if date == "":
        date = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    if re.fullmatch(r"[0-9]{4}", date):
        date = "00:00 " + date
    dt = parse_datetime(date.strip(), UTC, now).astimezone(UTC)
    return sprintf_date(format_, ts_of(dt), UTC)


def parsed(text: str, now: datetime = NOW) -> str:
    """The instant a string means, in UTC. The year is formatted by hand: glibc's strftime('%Y') does not pad
    years below 1000 to four digits, Windows' does."""
    dt = parse_datetime(text, UTC, now).astimezone(UTC)
    return f"{dt.year:04d}-" + dt.strftime("%m-%d %H:%M:%S")


class FuncsParserTests(unittest.TestCase):
    """The #time cases of funcsParserTests.txt."""

    def test_input_times_are_utc(self):
        self.assertEqual(time_("c", "15 January 2001"), "2001-01-15T00:00:00+00:00")

    def test_traditional_range(self):
        self.assertEqual(time_("Y", "15 January 2001"), "2001")

    def test_prior_to_1970(self):
        self.assertEqual(time_("Y", "5 April 1967"), "1967")

    def test_after_2038(self):
        self.assertEqual(time_("Y", "28 July 2061"), "2061")

    def test_explicit_utc(self):
        self.assertEqual(time_("Y-m-d H:i", " 2011-11-12 23:00 UTC "), "2011-11-12 23:00")

    @unittest.skipUnless(HAVE_TZDATA, "no time zone database")
    def test_explicit_europe_paris(self):
        self.assertEqual(time_("Y-m-d H:i", " 2011-11-12 23:00 Europe/Paris "), "2011-11-12 22:00")

    @unittest.skipUnless(HAVE_TZDATA, "no time zone database")
    def test_explicit_america_new_york(self):
        self.assertEqual(time_("Y-m-d H:i", " 2011-11-12 23:00 America/New_York "), "2011-11-13 04:00")

    def test_output_language(self):
        # {{#time:d F Y|1988-02-28|nl}} is "28 februari 1988"; only English is ported
        self.assertEqual(time_("d F Y", "1988-02-28"), "28 February 1988")


class SprintfDateTest(unittest.TestCase):
    TS = "20010115100509"  # Monday, 15 January 2001, 10:05:09

    def f(self, format_: str, ts: str = TS, zone=None) -> str:
        return sprintf_date(format_, ts, zone)

    def test_day(self):
        self.assertEqual(self.f("d"), "15")
        self.assertEqual(self.f("d", "20010105000000"), "05")
        self.assertEqual(self.f("D"), "Mon")
        self.assertEqual(self.f("j", "20010105000000"), "5")
        self.assertEqual(self.f("l"), "Monday")
        self.assertEqual(self.f("N"), "1")
        self.assertEqual(self.f("N", "20010114000000"), "7")
        self.assertEqual(self.f("w"), "1")
        self.assertEqual(self.f("w", "20010114000000"), "0")
        self.assertEqual(self.f("z"), "14")
        self.assertEqual(self.f("z", "20001231000000"), "365")

    def test_week_and_iso_year(self):
        self.assertEqual(self.f("W"), "03")
        self.assertEqual(self.f("W o", "20101231000000"), "52 2010")
        self.assertEqual(self.f("W o", "20100103000000"), "53 2009")
        self.assertEqual(self.f("W o", "20081229000000"), "01 2009")

    def test_month(self):
        self.assertEqual(self.f("F"), "January")
        self.assertEqual(self.f("M", "20010915000000"), "Sep")
        self.assertEqual(self.f("m"), "01")
        self.assertEqual(self.f("n", "20011115000000"), "11")
        self.assertEqual(self.f("t"), "31")
        self.assertEqual(self.f("t", "20000215000000"), "29")
        self.assertEqual(self.f("t", "19000215000000"), "28")
        self.assertEqual(self.f("xg"), "January")

    def test_year(self):
        self.assertEqual(self.f("L"), "0")
        self.assertEqual(self.f("L", "20000101000000"), "1")
        self.assertEqual(self.f("L", "19000101000000"), "0")
        self.assertEqual(self.f("Y"), "2001")
        self.assertEqual(self.f("Y", "00050101000000"), "0005")
        self.assertEqual(self.f("y"), "01")

    def test_time(self):
        self.assertEqual(self.f("a A g G h H i s"), "am AM 10 10 10 10 05 09")
        self.assertEqual(self.f("a A g G h H", "20010115230000"), "pm PM 11 23 11 23")
        self.assertEqual(self.f("a g h G", "20010115000000"), "am 12 12 0")
        self.assertEqual(self.f("a g h G", "20010115120000"), "pm 12 12 12")
        # u (microseconds) is not a sprintfDate character
        self.assertEqual(self.f("u"), "u")

    def test_zone_utc(self):
        self.assertEqual(self.f("e I O P T Z U"), "UTC 0 +0000 +00:00 UTC 0 979553109")
        self.assertEqual(self.f("e T", zone=UTC), "UTC UTC")
        self.assertEqual(self.f("c"), "2001-01-15T10:05:09+00:00")
        self.assertEqual(self.f("r"), "Mon, 15 Jan 2001 10:05:09 +0000")

    @unittest.skipUnless(HAVE_TZDATA, "no time zone database")
    def test_zone_identifier(self):
        paris = _zone("Europe/Paris")
        self.assertEqual(self.f("e I O P T Z U", "20010115110509", paris),
                         "Europe/Paris 0 +0100 +01:00 CET 3600 979553109")
        self.assertEqual(self.f("I T Z", "20010715120000", paris), "1 CEST 7200")
        self.assertEqual(self.f("c", "20010115110509", paris), "2001-01-15T11:05:09+01:00")
        self.assertEqual(self.f("r", "20010115110509", paris), "Mon, 15 Jan 2001 11:05:09 +0100")
        # zones without a letter abbreviation in tzdata
        self.assertEqual(self.f("T", "20010115110509", _zone("Asia/Dubai")), "+04")

    def test_zone_offset(self):
        zone = timezone(timedelta(hours=5, minutes=30))
        self.assertEqual(self.f("e O P T Z", zone=zone), "+05:30 +0530 +05:30 GMT+0530 19800")
        zone = timezone(-timedelta(hours=3))
        self.assertEqual(self.f("e O P T", zone=zone), "-03:00 -0300 -03:00 GMT-0300")

    def test_iranian(self):
        self.assertEqual(self.f("xiY xin xij xiF xiy xit xiz"), "1379 10 26 Dey 79 30 301")
        self.assertEqual(self.f("xiY-xin-xij xiF", "20000320000000"), "1379-1-1 Farvardin")
        self.assertEqual(self.f("xiY-xin-xij", "20000319000000"), "1378-12-29")

    def test_hijri(self):
        # the tabular (arithmetical) calendar, a day off the observed one here
        self.assertEqual(self.f("xmY xmn xmj xmF"), "1421 10 19 Shawwal")
        self.assertEqual(self.f("xmY xmn xmj xmF", "20240311000000"), "1445 9 1 Ramadan")

    def test_hebrew(self):
        self.assertEqual(self.f("xjY xjn xjj xjF xjx xjt"), "5761 4 20 Tevet Tevet 29")
        # Rosh Hashana 5785
        self.assertEqual(self.f("xjY xjn xjj xjF", "20241003000000"), "5785 1 1 Tishrei")
        # a leap year: Adar I and Adar II
        self.assertEqual(self.f("xjn xjj xjF", "20240220000000"), "13 11 Adar I")
        self.assertEqual(self.f("xjn xjj xjF", "20240320000000"), "14 10 Adar II")
        self.assertEqual(self.f("xjn xjF", "20230301000000"), "6 Adar")

    def test_other_years(self):
        self.assertEqual(self.f("xkY"), "2544")
        self.assertEqual(self.f("xkY", "19200215000000"), "2462")
        self.assertEqual(self.f("xoY"), "90")
        self.assertEqual(self.f("xtY"), "平成13")
        self.assertEqual(self.f("xtY", "19890108000000"), "平成元")
        self.assertEqual(self.f("xtY", "19890107000000"), "昭和64")
        self.assertEqual(self.f("xtY", "20190501000000"), "令和元")
        self.assertEqual(self.f("xtY", "19120730000000"), "明治45")
        self.assertEqual(self.f("xtY", "19120731000000"), "大正元")

    def test_numerals(self):
        self.assertEqual(self.f("xrY"), "MMI")
        self.assertEqual(self.f("xrj"), "XV")
        self.assertEqual(self.f("xrjj"), "XV15")  # xr applies to the next number only
        self.assertEqual(self.f("xr-xg-j"), "-January-XV")  # ... which may come after other characters
        self.assertEqual(self.f("xhj"), 'ט"ו')
        self.assertEqual(self.f("xhxjY"), 'ה\'תשס"א')
        self.assertEqual(self.f("xnY"), "2001")
        self.assertEqual(self.f("xNYxNj"), "200115")

    def test_roman_numeral(self):
        self.assertEqual(roman_numeral(1999), "MCMXCIX")
        self.assertEqual(roman_numeral(4), "IV")
        self.assertEqual(roman_numeral(10000), "MMMMMMMMMM")
        self.assertEqual(roman_numeral(10001), "10001")
        self.assertEqual(roman_numeral(0), "0")
        self.assertEqual(roman_numeral("05"), "V")

    def test_hebrew_numeral(self):
        self.assertEqual(hebrew_numeral(1), "א'")
        self.assertEqual(hebrew_numeral(15), 'ט"ו')
        self.assertEqual(hebrew_numeral(16), 'ט"ז')
        self.assertEqual(hebrew_numeral(20), "כ'")
        self.assertEqual(hebrew_numeral(42), 'מ"ב')
        self.assertEqual(hebrew_numeral(120), 'ק"ך')
        self.assertEqual(hebrew_numeral(500), 'ת"ק')
        self.assertEqual(hebrew_numeral(1000), "א' אלף")
        self.assertEqual(hebrew_numeral(2000), "ב' אלפים")
        self.assertEqual(hebrew_numeral(1001), "א'א'")
        self.assertEqual(hebrew_numeral(5786), 'ה\'תשפ"ו')
        self.assertEqual(hebrew_numeral(10000), "10000")

    def test_escapes(self):
        self.assertEqual(self.f('"The month is" F'), "The month is January")
        self.assertEqual(self.f('i\'s"'), "05'09\"")
        self.assertEqual(self.f('"Y'), '"2001')  # no terminating quote
        self.assertEqual(self.f('Y"'), '2001"')
        self.assertEqual(self.f("\\Y\\\\Y"), "Y\\2001")
        self.assertEqual(self.f("Y\\"), "2001\\")
        self.assertEqual(self.f("xx"), "x")
        self.assertEqual(self.f("Yx"), "2001x")
        self.assertEqual(self.f("xz"), "z")  # an unknown x code drops the x
        self.assertEqual(self.f("xiQ"), "Q")
        self.assertEqual(self.f("Y-é-年"), "2001-é-年")

    def test_bad_timestamp(self):
        with self.assertRaises(ValueError):
            sprintf_date("Y", "2001011510050")
        with self.assertRaises(ValueError):
            sprintf_date("Y", "2001011510050x")


class ParseDateTimeTest(unittest.TestCase):
    def assertParsed(self, text: str, expected: str, now: datetime = NOW):
        self.assertEqual(parsed(text, now), expected, text)

    def assertInvalid(self, text: str):
        with self.assertRaises(ValueError, msg=text) as cm:
            parse_datetime(text, UTC, NOW)
        self.assertNotIsInstance(cm.exception, YearOutOfRange, text)

    def test_now(self):
        self.assertParsed("now", "2024-05-15 13:45:30")
        self.assertParsed("", "2024-05-15 13:45:30")
        self.assertParsed("NOW", "2024-05-15 13:45:30")

    def test_special_words(self):
        self.assertParsed("today", "2024-05-15 00:00:00")
        self.assertParsed("midnight", "2024-05-15 00:00:00")
        self.assertParsed("noon", "2024-05-15 12:00:00")
        self.assertParsed("tomorrow", "2024-05-16 00:00:00")
        self.assertParsed("yesterday", "2024-05-14 00:00:00")
        self.assertParsed("yesterday noon", "2024-05-14 12:00:00")
        # "tomorrow" sets the time to midnight: a time before it is lost, after it stays
        self.assertParsed("tomorrow 10:00", "2024-05-16 10:00:00")
        self.assertParsed("10:00 tomorrow", "2024-05-16 00:00:00")
        self.assertParsed("back of 7pm", "2024-05-15 19:15:00")
        self.assertParsed("front of 7pm", "2024-05-15 18:45:00")

    def test_unix_timestamp(self):
        self.assertParsed("@123", "1970-01-01 00:02:03")
        self.assertParsed("@0", "1970-01-01 00:00:00")
        self.assertParsed("@-86400", "1969-12-31 00:00:00")
        self.assertParsed("@1.5", "1970-01-01 00:00:01")
        self.assertParsed("@-1.5", "1969-12-31 23:59:58")
        self.assertParsed("@123 +1 day", "1970-01-02 00:02:03")
        self.assertEqual(parse_datetime("@-1.5", UTC, NOW).microsecond, 500000)

    def test_iso_dates(self):
        self.assertParsed("2001-01-15", "2001-01-15 00:00:00")
        self.assertParsed("+2001-01-15", "2001-01-15 00:00:00")
        self.assertParsed("2001-1-5", "2001-01-05 00:00:00")
        self.assertParsed("01-01-15", "2001-01-15 00:00:00")
        self.assertParsed("99-1-5", "1999-01-05 00:00:00")
        self.assertParsed("2001/01/15", "2001-01-15 00:00:00")
        self.assertParsed("2001/1/5", "2001-01-05 00:00:00")
        self.assertParsed("20010115", "2001-01-15 00:00:00")
        self.assertParsed("2001-01", "2001-01-01 00:00:00")
        self.assertParsed("2001.032", "2001-02-01 00:00:00")
        self.assertParsed("2001032", "2001-02-01 00:00:00")
        self.assertParsed("2001W03", "2001-01-15 00:00:00")
        self.assertParsed("2001-W03-2", "2001-01-16 00:00:00")
        self.assertParsed("2009-W01-1", "2008-12-29 00:00:00")

    def test_other_numeric_dates(self):
        self.assertParsed("1/15/2001", "2001-01-15 00:00:00")
        self.assertParsed("1/15/01", "2001-01-15 00:00:00")
        self.assertParsed("1/15", "2024-01-15 00:00:00")
        self.assertParsed("15.01.2001", "2001-01-15 00:00:00")
        self.assertParsed("15-01-2001", "2001-01-15 00:00:00")
        self.assertParsed("15.1.69", "2069-01-15 00:00:00")
        self.assertParsed("15.1.70", "1970-01-15 00:00:00")
        # dd.mm.yy loses to the time hh.mm.ss
        self.assertParsed("15.01.01", "2024-05-15 15:01:01")

    def test_textual_dates(self):
        self.assertParsed("15 January 2001", "2001-01-15 00:00:00")
        self.assertParsed("15th January 2001", "2001-01-15 00:00:00")
        self.assertParsed("15-Jan-2001", "2001-01-15 00:00:00")
        self.assertParsed("5 April 67", "2067-04-05 00:00:00")
        self.assertParsed("5 april 1967", "1967-04-05 00:00:00")
        self.assertParsed("15 XII 2001", "2001-12-15 00:00:00")
        self.assertParsed("January 15, 2001", "2001-01-15 00:00:00")
        self.assertParsed("Jan 15th, 2001", "2001-01-15 00:00:00")
        self.assertParsed("Sept. 15 2001", "2001-09-15 00:00:00")
        self.assertParsed("January 15", "2024-01-15 00:00:00")
        self.assertParsed("15 January", "2024-01-15 00:00:00")
        self.assertParsed("January 2001", "2001-01-01 00:00:00")
        self.assertParsed("2001 January", "2001-01-01 00:00:00")
        self.assertParsed("January", "2024-01-15 00:00:00")
        self.assertParsed("Jan-15-2001", "2001-01-15 00:00:00")
        self.assertParsed("2001-Jan-15", "2001-01-15 00:00:00")
        self.assertParsed("15 January 2001 10:30", "2001-01-15 10:30:00")
        self.assertParsed("January 15 10:30", "2024-01-15 10:30:00")
        self.assertParsed("Jan 15 10:30pm", "2024-01-15 22:30:00")

    def test_invalid_dates_overflow(self):
        self.assertParsed("2001-02-29", "2001-03-01 00:00:00")
        self.assertParsed("2001-02-31", "2001-03-03 00:00:00")
        self.assertParsed("2001-01-00", "2000-12-31 00:00:00")
        self.assertParsed("2001-01-15 24:00", "2001-01-16 00:00:00")

    def test_times(self):
        self.assertParsed("10:30", "2024-05-15 10:30:00")
        self.assertParsed("10:30:45", "2024-05-15 10:30:45")
        self.assertParsed("10.30", "2024-05-15 10:30:00")
        self.assertParsed("t1030", "2024-05-15 10:30:00")
        self.assertParsed("103045", "2024-05-15 10:30:45")
        self.assertParsed("10pm", "2024-05-15 22:00:00")
        self.assertParsed("12am", "2024-05-15 00:00:00")
        self.assertParsed("12 pm", "2024-05-15 12:00:00")
        self.assertParsed("10:30 a.m.", "2024-05-15 10:30:00")
        self.assertParsed("10:30:15PM", "2024-05-15 22:30:15")
        self.assertParsed("10:00:00.5pm", "2024-05-15 22:00:00")
        self.assertEqual(parse_datetime("10:30:45.25", UTC, NOW).microsecond, 250000)
        # four digits alone are a time, after a time a year (why #time prefixes them with "00:00 ")
        self.assertParsed("2001", "2024-05-15 20:01:00")
        self.assertParsed("00:00 2001", "2001-05-15 00:00:00")
        self.assertParsed("1999", "1999-05-15 13:45:30")  # 19:99 is no time

    def test_combined(self):
        self.assertParsed("2001-01-15T10:00:00", "2001-01-15 10:00:00")
        self.assertParsed("2001-01-15T10:00:00Z", "2001-01-15 10:00:00")
        self.assertParsed("2001-01-15T10:00:00+01:00", "2001-01-15 09:00:00")
        self.assertParsed("2001-01-15T10:00:00.5-0130", "2001-01-15 11:30:00")
        self.assertParsed("2001-01-15 10:00:00 -05:00", "2001-01-15 15:00:00")
        self.assertParsed("20010115T100000", "2001-01-15 10:00:00")
        self.assertParsed("20010115T10:00:00", "2001-01-15 10:00:00")
        self.assertParsed("2001:01:15 10:00:00", "2001-01-15 10:00:00")
        self.assertParsed("10/Oct/2000:13:55:36 -0700", "2000-10-10 20:55:36")
        self.assertParsed("Mon, 15 Jan 2001 10:05:09 +0000", "2001-01-15 10:05:09")
        self.assertParsed("Monday, 15-Jan-01 10:05:09 UTC", "2001-01-15 10:05:09")

    def test_relative_numbers(self):
        self.assertParsed("+1 day", "2024-05-16 13:45:30")
        self.assertParsed("-1 day", "2024-05-14 13:45:30")
        self.assertParsed("1 day", "2024-05-16 13:45:30")
        self.assertParsed("+1 week 2 days", "2024-05-24 13:45:30")
        self.assertParsed("+2 weeks", "2024-05-29 13:45:30")
        self.assertParsed("+1 fortnight", "2024-05-29 13:45:30")
        self.assertParsed("+3 hours 15 minutes", "2024-05-15 17:00:30")
        self.assertParsed("+90 secs", "2024-05-15 13:47:00")
        self.assertParsed("-1 month", "2024-04-15 13:45:30")
        self.assertParsed("+1 year", "2025-05-15 13:45:30")
        self.assertParsed("--1 day", "2024-05-16 13:45:30")
        self.assertParsed("3 months ago", "2024-02-15 13:45:30")
        self.assertParsed("2 days 3 hours ago", "2024-05-13 10:45:30")
        self.assertParsed("2001-01-31 +1 month", "2001-03-03 00:00:00")
        self.assertParsed("+1 week july 2008", "2008-07-08 00:00:00")
        self.assertParsed("july 2008 +1 week", "2008-07-08 00:00:00")
        self.assertParsed("+2 weekdays", "2024-05-17 13:45:30")
        self.assertParsed("+3 weekdays", "2024-05-20 13:45:30")
        self.assertParsed("-3 weekdays", "2024-05-10 13:45:30")
        self.assertParsed("+1 weekday", "1970-01-02 00:02:03", FAKE_NOW)

    def test_relative_text(self):
        self.assertParsed("next month", "2024-06-15 13:45:30")
        self.assertParsed("last year", "2023-05-15 13:45:30")
        self.assertParsed("next day", "2024-05-16 13:45:30")
        self.assertParsed("third day", "2024-05-18 13:45:30")
        self.assertParsed("previous hour", "2024-05-15 12:45:30")

    def test_weekdays(self):
        # NOW is a Wednesday
        self.assertParsed("monday", "2024-05-20 00:00:00")
        self.assertParsed("wednesday", "2024-05-15 00:00:00")
        self.assertParsed("Wed", "2024-05-15 00:00:00")
        self.assertParsed("next wednesday", "2024-05-22 00:00:00")
        self.assertParsed("next monday", "2024-05-20 00:00:00")
        self.assertParsed("last monday", "2024-05-13 00:00:00")
        self.assertParsed("last wednesday", "2024-05-08 00:00:00")
        self.assertParsed("this wednesday", "2024-05-15 00:00:00")
        self.assertParsed("second friday", "2024-05-24 00:00:00")
        self.assertParsed("monday 10:00", "2024-05-20 10:00:00")
        self.assertParsed("+1 monday", "2024-05-20 13:45:30")
        # a weekday moves the date first, the relative parts come after it
        self.assertParsed("monday +1 day", "2024-05-21 00:00:00")
        self.assertParsed("+1 day monday", "2024-05-21 00:00:00")

    def test_weeks(self):
        # "this/next/last week" go to the Monday of that week (a Sunday belongs to the week before)
        self.assertParsed("this week", "2024-05-13 13:45:30")
        self.assertParsed("next week", "2024-05-20 13:45:30")
        self.assertParsed("last week", "2024-05-06 13:45:30")
        self.assertParsed("sunday this week", "2024-05-19 00:00:00")
        self.assertParsed("friday next week", "2024-05-24 00:00:00")
        self.assertParsed("this week", "2024-05-13 10:00:00", datetime(2024, 5, 19, 10, tzinfo=UTC))

    def test_first_last_day_of(self):
        # the time stays
        self.assertParsed("first day of", "2024-05-01 13:45:30")
        self.assertParsed("last day of", "2024-05-31 13:45:30")
        self.assertParsed("first day of next month", "2024-06-01 13:45:30")
        self.assertParsed("last day of next month", "2024-06-30 13:45:30")
        self.assertParsed("last day of february 2024", "2024-02-29 00:00:00")
        self.assertParsed("midnight first day of next month", "2024-06-01 00:00:00")
        self.assertParsed("last day of next month", "1970-02-28 00:02:03", FAKE_NOW)
        self.assertParsed("2001-01-31 last day of +1 month", "2001-02-28 00:00:00")
        self.assertParsed("first day of +1 day", "2024-05-01 13:45:30")

    def test_weekday_of(self):
        self.assertParsed("first monday of next month", "2024-06-03 00:00:00")
        self.assertParsed("second monday of next month", "2024-06-10 00:00:00")
        self.assertParsed("last friday of next month", "2024-06-28 00:00:00")
        self.assertParsed("first saturday of june 2024", "2024-06-01 00:00:00")
        self.assertParsed("last sunday of march 2024", "2024-03-31 00:00:00")

    def test_zones(self):
        self.assertParsed("2001-01-15 10:00 UTC", "2001-01-15 10:00:00")
        self.assertParsed("2001-01-15 10:00 GMT", "2001-01-15 10:00:00")
        self.assertParsed("2001-01-15 10:00 Z", "2001-01-15 10:00:00")
        self.assertParsed("2001-01-15 10:00 CET", "2001-01-15 09:00:00")
        self.assertParsed("2001-01-15 10:00 CEST", "2001-01-15 08:00:00")
        self.assertParsed("2001-01-15 10:00 EST", "2001-01-15 15:00:00")
        self.assertParsed("2001-01-15 10:00 pdt", "2001-01-15 17:00:00")
        self.assertParsed("2001-01-15 10:00 (CET)", "2001-01-15 09:00:00")
        self.assertParsed("2001-01-15 10:00 +1", "2001-01-15 09:00:00")
        self.assertParsed("2001-01-15 10:00 +0530", "2001-01-15 04:30:00")
        self.assertParsed("2001-01-15 10:00 GMT-5", "2001-01-15 15:00:00")
        self.assertParsed("2001-01-15 10:00 +01:00:30", "2001-01-15 08:59:30")
        # a second zone is only a warning: the first one stays
        self.assertParsed("2001-01-15 10:00 UTC CET", "2001-01-15 10:00:00")
        # the zone of the string, the current time of the default zone
        self.assertParsed("+1 hour CET", "2024-05-15 13:45:30")

    @unittest.skipUnless(HAVE_TZDATA, "no time zone database")
    def test_zone_identifiers(self):
        self.assertParsed("2011-07-12 23:00 Europe/Paris", "2011-07-12 21:00:00")
        self.assertParsed("2011-11-12 23:00 Europe/PARIS", "2011-11-12 22:00:00")
        self.assertParsed("2011-11-12 23:00 America/Argentina/Buenos_Aires", "2011-11-13 02:00:00")
        dt = parse_datetime("2011-11-12 23:00 Europe/Paris", UTC, NOW)
        self.assertEqual(getattr(dt.tzinfo, "key", None), "Europe/Paris")
        # #timel: the output zone is the wiki's; DST gaps resolve to the later wall time as in PHP
        self.assertParsed("2011-03-27 02:30 Europe/Paris", "2011-03-27 01:30:00")

    def test_default_zone(self):
        plus2 = timezone(timedelta(hours=2))
        dt = parse_datetime("2001-01-15 10:00", plus2, NOW)
        self.assertEqual(dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M"), "2001-01-15 08:00")
        # missing fields come from now in the default zone
        dt = parse_datetime("10:00", plus2, datetime(2024, 5, 15, 23, 0, tzinfo=UTC))
        self.assertEqual(dt.strftime("%Y-%m-%d %H:%M"), "2024-05-16 10:00")

    def test_errors(self):
        for text in ("foo", "next", "25:00", "10:60", "2001-13-01", "10:00 10:00", "2001-01-15 2001-01-16",
                     "noon 10:00", "January February", "13pm", "@", "@1.", "UTC UTC UTC", "+25:00:00:00", "#",
                     "15/01/2001", "2001-01-15 10:00 Europe/Nowhere", "first week", "of"):
            self.assertInvalid(text)

    def test_year_range(self):
        for text, year in (("+10000-01-01", 10000), ("-0001-01-01", -1), ("0000-01-01", 0),
                           ("9999-12-31 23:59:59 +1 second", 10000), ("0001-01-01 -1 day", 0),
                           ("@253402300800", 10000)):
            with self.assertRaises(YearOutOfRange, msg=text) as cm:
                parse_datetime(text, UTC, NOW)
            self.assertEqual(cm.exception.year, year, text)
        self.assertParsed("9999-12-31 23:59:59", "9999-12-31 23:59:59")
        self.assertParsed("0001-01-01", "0001-01-01 00:00:00")
        self.assertParsed("+0099-01-01", "0099-01-01 00:00:00")


class TimeFunctionTest(unittest.TestCase):
    """#time as timeCommon() computes it, at the parser tests' fake time when no date is given."""

    def test_no_date(self):
        self.assertEqual(time_("Y-m-d H:i:s"), "1970-01-01 00:02:03")
        self.assertEqual(time_("U"), "123")
        self.assertEqual(time_("l, F j, Y"), "Thursday, January 1, 1970")

    def test_four_digits(self):
        self.assertEqual(time_("Y-m-d H:i", "2001"), "2001-01-01 00:00")
        self.assertEqual(time_("Y", "1999"), "1999")

    def test_relative(self):
        self.assertEqual(time_("Y-m-d", "+1 day"), "1970-01-02")
        self.assertEqual(time_("Y-m-d", "last day of next month"), "1970-02-28")
        self.assertEqual(time_("D", "@123"), "Thu")

    def test_formats(self):
        self.assertEqual(time_('j xg Y, "week" W', "2024-03-04"), "4 March 2024, week 10")
        self.assertEqual(time_("xrY", "1987-06-05"), "MCMLXXXVII")
        self.assertEqual(time_("c", "2001-01-15 10:00 +01:00"), "2001-01-15T09:00:00+00:00")


if __name__ == "__main__":
    unittest.main()
