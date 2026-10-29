# English interface messages from MediaWiki 1.39 languages/i18n/en.json (https://www.mediawiki.org/),
# (C) MediaWiki contributors.
# Changed by a3ref contributors on 2026-10-30: only the messages the parser uses, as a Python dict; a simple
# wfMessage() that replaces $1, $2, ... (no PLURAL/GRAMMAR, which these messages do not use).
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""The parser's interface messages, in English (the BI wiki's content language)."""
from __future__ import annotations

MESSAGES = {
    "parser-unstrip-loop-warning": "Unstrip loop detected",
    "unstrip-depth-warning": "Unstrip depth limit exceeded ($1)",
    "unstrip-size-warning": "Unstrip size limit exceeded ($1)",
    "rfcurl": "https://tools.ietf.org/html/rfc$1",
    "pubmedurl": "//www.ncbi.nlm.nih.gov/pubmed/$1?dopt=Abstract",
    "toc": "Contents",
    "showtoc": "show",
    "hidetoc": "hide",
    "editsection": "edit",
    "editsectionhint": "Edit section: $1",
    "pipe-separator": "&#32;|&#32;",
    # Language: month and weekday names, formatNum (coreparserfunctions.py)
    "january": "January", "february": "February", "march": "March", "april": "April", "may_long": "May",
    "june": "June", "july": "July", "august": "August", "september": "September", "october": "October",
    "november": "November", "december": "December",
    "january-gen": "January", "february-gen": "February", "march-gen": "March", "april-gen": "April",
    "may-gen": "May", "june-gen": "June", "july-gen": "July", "august-gen": "August", "september-gen": "September",
    "october-gen": "October", "november-gen": "November", "december-gen": "December",
    "jan": "Jan", "feb": "Feb", "mar": "Mar", "apr": "Apr", "may": "May", "jun": "Jun", "jul": "Jul", "aug": "Aug",
    "sep": "Sep", "oct": "Oct", "nov": "Nov", "dec": "Dec",
    "sunday": "Sunday", "monday": "Monday", "tuesday": "Tuesday", "wednesday": "Wednesday", "thursday": "Thursday",
    "friday": "Friday", "saturday": "Saturday",
    "formatnum-nan": "Not a Number",
    # CoreParserFunctions
    "duplicate-displaytitle":
        "<strong>Warning:</strong> Display title \"$2\" overrides earlier display title \"$1\".",
    "duplicate-defaultsort":
        "<strong>Warning:</strong> Default sort key \"$2\" overrides earlier default sort key \"$1\".",
    "restricted-displaytitle":
        "<strong>Warning:</strong> Display title \"$1\" was ignored since it is not equivalent to the page's actual "
        "title.",
    "nonnumeric-formatnum": "Pages with non-numeric formatnum arguments",
    "restricted-displaytitle-ignored": "Pages with ignored display titles",
    # used by MediaWiki's parser tests through {{int:}}
    "youhavenewmessages": "{{PLURAL:$3|You have}} $1 ($2).",
    "ok": "OK",
    # Language::sprintfDate() (weekday abbreviations, other calendars)
    "sun": "Sun", "mon": "Mon", "tue": "Tue", "wed": "Wed", "thu": "Thu", "fri": "Fri", "sat": "Sat",
    "iranian-calendar-m1": "Farvardin", "iranian-calendar-m2": "Ordibehesht", "iranian-calendar-m3": "Khordad",
    "iranian-calendar-m4": "Tir", "iranian-calendar-m5": "Mordad", "iranian-calendar-m6": "Shahrivar",
    "iranian-calendar-m7": "Mehr", "iranian-calendar-m8": "Aban", "iranian-calendar-m9": "Azar",
    "iranian-calendar-m10": "Dey", "iranian-calendar-m11": "Bahman", "iranian-calendar-m12": "Esfand",
    "hijri-calendar-m1": "Muharram", "hijri-calendar-m2": "Safar", "hijri-calendar-m3": "Rabi' al-awwal",
    "hijri-calendar-m4": "Rabi' al-thani", "hijri-calendar-m5": "Jumada al-awwal",
    "hijri-calendar-m6": "Jumada al-thani", "hijri-calendar-m7": "Rajab", "hijri-calendar-m8": "Sha'aban",
    "hijri-calendar-m9": "Ramadan", "hijri-calendar-m10": "Shawwal", "hijri-calendar-m11": "Dhu al-Qi'dah",
    "hijri-calendar-m12": "Dhu al-Hijjah",
    "hebrew-calendar-m1": "Tishrei", "hebrew-calendar-m2": "Cheshvan", "hebrew-calendar-m3": "Kislev",
    "hebrew-calendar-m4": "Tevet", "hebrew-calendar-m5": "Shevat", "hebrew-calendar-m6": "Adar",
    "hebrew-calendar-m6a": "Adar I", "hebrew-calendar-m6b": "Adar II", "hebrew-calendar-m7": "Nisan",
    "hebrew-calendar-m8": "Iyar", "hebrew-calendar-m9": "Sivan", "hebrew-calendar-m10": "Tamuz",
    "hebrew-calendar-m11": "Av", "hebrew-calendar-m12": "Elul",
    "hebrew-calendar-m1-gen": "Tishrei", "hebrew-calendar-m2-gen": "Cheshvan", "hebrew-calendar-m3-gen": "Kislev",
    "hebrew-calendar-m4-gen": "Tevet", "hebrew-calendar-m5-gen": "Shevat", "hebrew-calendar-m6-gen": "Adar",
    "hebrew-calendar-m6a-gen": "Adar I", "hebrew-calendar-m6b-gen": "Adar II", "hebrew-calendar-m7-gen": "Nisan",
    "hebrew-calendar-m8-gen": "Iyar", "hebrew-calendar-m9-gen": "Sivan", "hebrew-calendar-m10-gen": "Tamuz",
    "hebrew-calendar-m11-gen": "Av", "hebrew-calendar-m12-gen": "Elul",
    # ParserFunctions extension (i18n/en.json, REL1_39)
    "pfunc_desc": "Enhance parser with logical functions",
    "pfunc_time_error": "Error: Invalid time.",
    "pfunc_time_too_long": "Error: Too many #time calls.",
    "pfunc_time_too_big": "Error: #time only supports years up to 9999.",
    "pfunc_time_too_small": "Error: #time only supports years from 0.",
    "pfunc_rel2abs_invalid_depth":
        "Error: Invalid depth in path: \"$1\" (tried to access a node above the root node).",
    "pfunc_expr_stack_exhausted": "Expression error: Stack exhausted.",
    "pfunc_expr_unexpected_number": "Expression error: Unexpected number.",
    "pfunc_expr_preg_match_failure": "Expression error: Unexpected preg_match failure.",
    "pfunc_expr_unrecognised_word": "Expression error: Unrecognized word \"$1\".",
    "pfunc_expr_unexpected_operator": "Expression error: Unexpected $1 operator.",
    "pfunc_expr_missing_operand": "Expression error: Missing operand for $1.",
    "pfunc_expr_unexpected_closing_bracket": "Expression error: Unexpected closing bracket.",
    "pfunc_expr_unrecognised_punctuation": "Expression error: Unrecognized punctuation character \"$1\".",
    "pfunc_expr_unclosed_bracket": "Expression error: Unclosed bracket.",
    "pfunc_expr_division_by_zero": "Division by zero.",
    "pfunc_expr_invalid_argument": "Invalid argument for $1: < -1 or > 1.",
    "pfunc_expr_invalid_argument_ln": "Invalid argument for ln: <= 0.",
    "pfunc_expr_unknown_error": "Expression error: Unknown error ($1).",
    "pfunc_expr_not_a_number": "In $1: Result is not a number.",
    "pfunc_string_too_long": "Error: String exceeds $1 character limit.",
    # RegexFunctions extension (i18n/en.json): the names of its named arguments
    "regexfunctions-arg-pattern": "pattern",
    "regexfunctions-arg-multiline": "multiline",
    "regexfunctions-arg-caseless": "caseless",
    "regexfunctions-arg-ungreedy": "ungreedy",
    "regexfunctions-arg-extended": "extended",
    "regexfunctions-arg-dotall": "dotall",
    "regexfunctions-arg-then": "then",
    "regexfunctions-arg-else": "else",
    "regexfunctions-arg-piece": "piece",
    "regexfunctions-arg-replacement": "replacement",
    # Cite extension (i18n/en.json of the Cite in MediaWiki 1.39.0)
    "cite_error": "Cite error: $1",
    "cite_error_ref_invalid_dir": "Invalid <code>dir=\"$1\"</code>, must be <code>ltr</code> or <code>rtl</code>",
    "cite_error_ref_numeric_key":
        "Invalid <code>&lt;ref&gt;</code> tag; name cannot be a simple integer. Use a descriptive title",
    "cite_error_ref_no_key": "The opening <code>&lt;ref&gt;</code> tag is malformed or has a bad name",
    "cite_error_ref_too_many_keys": "Invalid <code>&lt;ref&gt;</code> tag; invalid names, e.g. too many",
    "cite_error_ref_nested_extends":
        "Extending <code>&lt;ref&gt;</code> tags more than one level deep is not allowed",
    "cite_error_ref_no_input": "Invalid <code>&lt;ref&gt;</code> tag; refs with no name must have content",
    "cite_error_references_duplicate_key":
        "Invalid <code>&lt;ref&gt;</code> tag; name \"$1\" defined multiple times with different content",
    "cite_error_references_invalid_parameters": "Invalid parameter in <code>&lt;references&gt;</code> tag",
    "cite_error_references_no_backlink_label":
        "Ran out of custom backlink labels. Define more in the [[MediaWiki:Cite references link many format "
        "backlink labels]] message.",
    "cite_error_no_link_label_group":
        "Ran out of custom link labels for group \"$1\". Define more in the [[MediaWiki:$2]] message.",
    "cite_error_references_no_text":
        "Invalid <code>&lt;ref&gt;</code> tag; no text was provided for refs named <code>$1</code>",
    "cite_error_included_ref": "Closing <code>&lt;/ref&gt;</code> missing for <code>&lt;ref&gt;</code> tag",
    "cite_error_included_references": "Closing tag missing for <code>&lt;references&gt;</code>",
    "cite_error_group_refs_without_references":
        "<code>&lt;ref&gt;</code> tags exist for a group named \"$1\", but no corresponding "
        "<code>&lt;references group=\"$1\"/&gt;</code> tag was found",
    "cite_error_references_group_mismatch":
        "<code>&lt;ref&gt;</code> tag in <code>&lt;references&gt;</code> has conflicting group attribute \"$1\".",
    "cite_error_references_missing_group":
        "<code>&lt;ref&gt;</code> tag with name \"$2\" defined in <code>&lt;references&gt;</code> has group "
        "attribute \"$1\" which does not appear in prior text.",
    "cite_error_references_missing_key":
        "<code>&lt;ref&gt;</code> tag with name \"$1\" defined in <code>&lt;references&gt;</code> is not used in "
        "prior text.",
    "cite_error_references_no_key":
        "<code>&lt;ref&gt;</code> tag defined in <code>&lt;references&gt;</code> has no name attribute.",
    "cite_error_empty_references_define":
        "<code>&lt;ref&gt;</code> tag with name \"$1\" defined in <code>&lt;references&gt;</code> group \"$2\" has "
        "no content.",
    "cite-tracking-category-cite-error": "Pages with reference errors",
    "cite_reference_link_key_with_num": "$1_$2",
    "cite_reference_link_prefix": "cite_ref-",
    "cite_reference_link_suffix": "",
    "cite_references_link_prefix": "cite_note-",
    "cite_references_link_suffix": "",
    "cite_reference_link": "<sup id=\"$1\" class=\"reference\">[[#$2|&#91;$3&#93;]]</sup>",
    "cite_references_no_link": "<p id=\"$1\">$2</p>",
    "cite_references_link_one": "<li id=\"$1\"$4><span class=\"mw-cite-backlink\">[[#$2|↑]]</span> $3</li>",
    "cite_references_link_many": "<li id=\"$1\"$4><span class=\"mw-cite-backlink\">↑ $2</span> $3</li>",
    "cite_references_link_many_format": "<sup>[[#$1|$2]]</sup>",
    # "a b c ... z aa ab ... zz"
    "cite_references_link_many_format_backlink_labels": " ".join(
        [chr(c) for c in range(97, 123)] + [chr(a) + chr(b) for a in range(97, 123) for b in range(97, 123)]),
    "cite_references_link_many_sep": "&#32;",
    "cite_references_link_many_and": "&#32;",
    "cite_references_link_accessibility_label": "Jump up",
    "cite_references_link_many_accessibility_label": "Jump up to:",
    "cite_references_link_accessibility_back_label": "Jump back up",
    "cite_section_preview_references": "Preview of references",
    "cite_warning": "Cite warning: $1",
    "cite_warning_sectionpreview_no_text":
        "<code>&lt;ref&gt;</code> tag with name <code>$1</code> cannot be previewed because it is defined outside "
        "the current section or not defined at all.",
}


def msg(key: str, *params) -> str:
    """wfMessage( $key, ...$params )->inContentLanguage()->text()"""
    text = MESSAGES[key]
    for i, p in enumerate(params, 1):
        text = text.replace(f"${i}", str(p))
    return text
