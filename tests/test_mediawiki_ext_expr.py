# Tests of biwiki/mediawiki/ext/expr.py. The first cases are those of the ParserFunctions extension's
# tests/phpunit/unit/ExpressionTest.php and tests/parser/funcsParserTests.txt (https://www.mediawiki.org/wiki/
# Extension:ParserFunctions), (C) ParserFunctions contributors, GPL-2.0-or-later; translated to Python by a3ref
# contributors on 2026-10-30, who added the PHP edge cases below.
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""Tests of the ExprParser port ({{#expr:}}), with the results PHP gives."""
from __future__ import annotations

import math
import unittest

from biwiki.mediawiki.ext import expr
from biwiki.mediawiki.ext.expr import ExprError, ExprParser

# ExpressionTest::provideExpressions
EXPRESSIONS = [
    ("1 or 0", "1"),
    ("not (1 and 0)", "1"),
    ("not 0", "1"),
    ("4 < 5", "1"),
    ("-5 < 2", "1"),
    ("-2 <= -2", "1"),
    ("4 > 3", "1"),
    ("4 > -3", "1"),
    ("5 >= 2", "1"),
    ("2 >= 2", "1"),
    ("1 != 2", "1"),
    ("-4 * -4 = 4 * 4", "1"),
    ("not (1 != 1)", "1"),
    ("1 + 1", "2"),
    ("-1 + 1", "0"),
    ("+1 + 1", "2"),
    ("4 * 4", "16"),
    ("(1/3) * 3", "1"),
    ("3 / 1.5", "2"),
    ("3 / 0.2", "15"),
    ("3 / ( 2.0 * 0.1 )", "15"),
    ("3 / ( 2.0 / 10 )", "15"),
    ("3 / (- 0.2 )", "-15"),
    ("3 / abs( 0.2 )", "15"),
    ("3 mod 2", "1"),
    ("1e4", "10000"),
    ("1e-2", "0.01"),
    ("4.0 round 0", "4"),
    ("ceil 4", "4"),
    ("floor 4", "4"),
    ("4.5 round 0", "5"),
    ("4.2 round 0", "4"),
    ("-4.2 round 0", "-4"),
    ("-4.5 round 0", "-5"),
    ("-2.0 round 0", "-2"),
    ("ceil -3", "-3"),
    ("floor -6.0", "-6"),
    ("ceil 4.2", "5"),
    ("ceil -4.5", "-4"),
    ("floor -4.5", "-5"),
    ("abs(-2)", "2"),
    ("ln(exp(1))", "1"),
    ("trunc(4.5)", "4"),
    ("trunc(-4.5)", "-4"),
    ("123 fmod (2^64-1)", "123"),
    ("5.7 mod 1.3", "0"),
    ("5.7 fmod 1.3", "0.5"),
    ("pi + 1", "4.1415926535898"),
    ("sin(0)", "0"),
    ("cos(0)", "1"),
    ("tan(0)", "0"),
    ("asin(0)", "0"),
    ("acos(1)", "0"),
    ("atan(0)", "0"),
    ("sqrt(4)", "2"),
]

# ExpressionTest::provideExpressionThrows, with the message each one gives
THROWS = [
    ("ln(" * 1001 + "1" + ")" * 1001, "stack_exhausted", ""),
    ("1 2", "unexpected_number", ""),
    ("foo", "unrecognised_word", "foo"),
    ("1 pi", "unexpected_number", ""),
    ("1 sin", "unexpected_operator", "sin"),
    ("1 (", "unexpected_operator", "("),
    ("1 + 1)", "unexpected_closing_bracket", ""),
    ("1, 2", "unrecognised_punctuation", ","),
    ("<1", "unexpected_operator", "<"),
    ("(1", "unclosed_bracket", ""),
    ("-", "missing_operand", "-"),
    ("+", "missing_operand", "+"),
    ("1*", "missing_operand", "*"),
    ("1/", "missing_operand", "/"),
    ("1/0", "division_by_zero", "/"),
    ("1 mod", "missing_operand", "mod"),
    ("1 mod 0", "division_by_zero", "mod"),
    ("1 fmod", "missing_operand", "fmod"),
    ("1 fmod 0", "division_by_zero", "fmod"),
    ("1+", "missing_operand", "+"),
    ("1-", "missing_operand", "-"),
    ("1 and", "missing_operand", "and"),
    ("1 or", "missing_operand", "or"),
    ("1 =", "missing_operand", "="),
    ("1 not", "unexpected_operator", "not"),
    ("1 round", "missing_operand", "round"),
    ("1<", "missing_operand", "<"),
    ("1>", "missing_operand", ">"),
    ("1<=", "missing_operand", "<="),
    ("1>=", "missing_operand", ">="),
    ("1<>", "missing_operand", "<>"),
    ("sin()", "missing_operand", "sin"),
    ("cos()", "missing_operand", "cos"),
    ("tan()", "missing_operand", "tan"),
    ("asin()", "missing_operand", "asin"),
    ("asin(3) ", "invalid_argument", "asin"),
    ("acos()", "missing_operand", "acos"),
    ("acos(-1.1)", "invalid_argument", "acos"),
    ("atan()", "missing_operand", "atan"),
    ("exp()", "missing_operand", "exp"),
    ("ln()", "missing_operand", "ln"),
    ("ln(-1)", "invalid_argument_ln", "ln"),
    ("abs()", "missing_operand", "abs"),
    ("floor", "missing_operand", "floor"),
    ("trunc", "missing_operand", "trunc"),
    ("ceil", "missing_operand", "ceil"),
    ("1 ^", "missing_operand", "^"),
    ("sqrt", "missing_operand", "sqrt"),
    ("sqrt(-1)", "not_a_number", "sqrt"),
]

N = "(exp 1000 - exp 1000)"  # NAN

# What PHP gives for the cases ExpressionTest does not cover
EDGE_CASES = [
    # funcsParserTests.txt: #ifexpr and bug 22866
    ("", ""),
    ("1 > 0", "1"),
    ("1 < 0", "0"),
    ("(-1)*0", "-0"),
    # (string) of a float: precision 14, PHP's exponents, -0, INF, NAN
    ("-0", "-0"),
    ("0 * -1", "-0"),
    ("1/3", "0.33333333333333"),
    ("2/3", "0.66666666666667"),
    ("99999999999999", "99999999999999"),
    ("100000000000000", "1.0E+14"),
    ("1e15", "1.0E+15"),
    ("1.5e20", "1.5E+20"),
    ("-1e20", "-1.0E+20"),
    ("123456789012345678", "1.2345678901235E+17"),
    ("0.0001", "0.0001"),
    ("0.00001", "1.0E-5"),
    ("1e400", "INF"),
    ("exp 1000", "INF"),
    ("-exp 1000", "-INF"),
    (N, "NAN"),
    ("sin(exp 1000)", "NAN"),
    ("tan(pi/2)", "1.6331239353195E+16"),
    # numbers: digits and dots, the leading numeric part, no exponent
    (".5", "0.5"),
    ("5.", "5"),
    ("1.2.3", "1.2"),
    (".", "0"),
    ("..5", "0"),
    ("0000012", "12"),
    # e: the constant where an operand is expected, else "times ten to the power of"
    ("e", "2.718281828459"),
    ("e e 2", "271.8281828459"),
    ("2 E 3", "2000"),
    ("pi", "3.1415926535898"),
    ("PI", "3.1415926535898"),
    # unary minus binds tighter than ^, as do the functions
    ("-2^2", "4"),
    ("-(2^2)", "-4"),
    ("2^-2", "0.25"),
    ("- - 2", "2"),
    ("3 - -2", "5"),
    ("3--2", "5"),
    ("+-+2", "-2"),
    ("sin pi/2", "6.1232339957368E-17"),
    ("sqrt 16 ^ 0.5", "2"),
    ("2 * 3 + 4", "10"),
    ("2 + 3 * 4", "14"),
    ("2 ^ 3 ^ 2", "64"),
    ("1 + 2 round 0", "3"),
    ("3.14159 round 2 * 2", "3.1416"),  # round binds looser than *
    ("1 + 1 = 2 and 3 > 2", "1"),
    ("1 and 0 or 1", "1"),
    ("0 or 0", "0"),
    ("2 and 3", "1"),
    ("0.0 and 1", "0"),
    # not
    ("not 5", "0"),
    ("not 0.0", "1"),
    ("not not 2", "1"),
    ("NOT -0", "1"),
    (f"not {N}", "0"),
    # comparisons, entities and the minus sign
    ("1 <> 1", "0"),
    ("1 != 1", "0"),
    ("1 = 1.0", "1"),
    ("1 <= 1", "1"),
    ("3 >= 4", "0"),
    ("3 > 4", "0"),
    ("-0 = 0", "1"),
    ("1 &lt; 2", "1"),
    ("2 &gt; 1", "1"),
    ("2 &lt;= 1", "0"),
    ("1 &lt;&gt; 2", "1"),
    ("3 &minus; 1", "2"),
    ("3 − 1", "2"),
    (f"{N} = {N}", "0"),
    (f"{N} <> {N}", "1"),
    (f"{N} < 1", "0"),
    (f"{N} >= 1", "0"),
    (f"{N} and 1", "1"),
    # whitespace: space, tab, CR and LF only
    (" \t\r\n1\n+\t2 ", "3"),
    # words are case-insensitive; div is /
    ("6 DIV 4", "1.5"),
    ("7 Mod 4", "3"),
    # integers: mod, trunc, comparisons and not give integers; integer arithmetic stays exact
    ("trunc(2^53) + trunc 1", "9007199254740993"),
    ("trunc(2^53) + 1", "9.007199254741E+15"),  # numbers are floats
    ("trunc(2^53) + trunc 1 = 2^53", "1"),  # PHP compares an integer with a float as two floats
    ("trunc(2^53) + trunc 1 > 2^53", "0"),
    ("trunc(2^53) + trunc 1 > trunc(2^53)", "1"),
    ("trunc 6 / trunc 3", "2"),
    ("trunc 5 / trunc 2", "2.5"),
    ("trunc((-2)^63)", "-9223372036854775808"),
    ("-trunc((-2)^63)", "9.2233720368548E+18"),  # overflows to a float
    ("abs trunc((-2)^63)", "9.2233720368548E+18"),
    ("trunc((-2)^63) - 1", "-9.2233720368548E+18"),
    ("trunc(2^62) * 2", "9.2233720368548E+18"),
    ("trunc((-2)^63) / -trunc 1", "9.2233720368548E+18"),
    ("trunc((-2)^63) mod -1", "0"),
    ("(1 < 2) + (2 < 1)", "1"),
    # (int): truncation, wrapping modulo 2^64, INF and NAN are 0
    ("trunc(-1.5)", "-1"),
    ("trunc(-0.5)", "0"),
    ("trunc(2^63)", "-9223372036854775808"),
    ("trunc(1e20)", "7766279631452241920"),
    ("trunc(-1e20)", "-7766279631452241920"),
    ("trunc(exp 1000)", "0"),
    (f"trunc {N}", "0"),
    # mod: the operands are truncated to integers, the result has the sign of the dividend
    ("-7 mod 3", "-1"),
    ("7 mod -3", "1"),
    ("5 mod -1", "0"),
    ("7.9 mod 2.9", "1"),
    ("-7 fmod 3", "-1"),
    ("7 fmod -3", "1"),
    ("(exp 1000) fmod 2", "NAN"),
    ("5 fmod exp 1000", "5"),
    # round(): halves away from zero after pre-rounding to 15 digits; negative places; -0
    ("2.5 round 0", "3"),
    ("-2.5 round 0", "-3"),
    ("1.955 round 2", "1.96"),
    ("0.285 round 2", "0.29"),
    ("1.45 round 1", "1.5"),
    ("2.4999999999999996 round 0", "3"),
    ("1234.5678 round -2", "1200"),
    ("1250 round -2", "1300"),
    ("-1250 round -2", "-1300"),
    ("1234.5678 round 2.9", "1234.57"),
    ("-0.4 round 0", "-0"),
    ("5 round -400", "0"),
    ("1.5 round 400", "1.5"),
    ("1e20 round 2", "1.0E+20"),
    ("trunc 7 round 0", "7"),
    ("trunc 1234 round -2", "1200"),
    ("exp 1000 round 2", "INF"),
    # floor() and ceil() keep the sign of zero
    ("ceil -0.5", "-0"),
    ("floor -0.5", "-1"),
    ("floor 2.5", "2"),
    ("ceil(-0)", "-0"),
    ("floor(exp 1000)", "INF"),
    # ^ and pow()
    ("2^10", "1024"),
    ("2^0.5", "1.4142135623731"),
    ("2^63", "9.2233720368548E+18"),
    ("(-8)^(1/3)", "NAN"),
    ("0^-1", "INF"),
    ("(-0)^-1", "-INF"),
    ("(-0)^-2", "INF"),
    ("10^309", "INF"),
    ("(-10)^309", "-INF"),
    ("0^0", "1"),
    (f"{N}^0", "1"),
    ("trunc 2 ^ trunc 62", "4611686018427387904"),
    ("trunc 2 ^ trunc 63", "9.2233720368548E+18"),
    ("trunc 3 ^ trunc 40", "1.2157665459057E+19"),
    ("trunc 2 ^ -trunc 1", "0.5"),
    ("trunc -1 ^ trunc(2^62)", "1"),
    ("trunc 0 ^ trunc 5", "0"),
    ("1e-400", "0"),
    # other functions
    ("abs(-0)", "0"),
    ("abs -1.5", "1.5"),
    ("sqrt(-0)", "-0"),
    ("ln 1", "0"),
    ("exp 0", "1"),
    ("atan(exp 1000)", "1.5707963267949"),
    ("asin 1", "1.5707963267949"),
    ("acos -1", "3.1415926535898"),
    ("cos pi", "-1"),
    (f"asin {N}", "NAN"),
    (f"ln {N}", "NAN"),
    ("ln exp 1000", "INF"),
]

EDGE_THROWS = [
    ("1 + X", "unrecognised_word", "x"),
    ("FOO", "unrecognised_word", "foo"),
    ("pi 1", "unexpected_number", ""),
    ("2 3", "unexpected_number", ""),
    ("*2", "unexpected_operator", "*"),
    ("1 + * 2", "unexpected_operator", "*"),
    ("2 = = 2", "unexpected_operator", "="),
    ("1 + mod 2", "unexpected_operator", "mod"),
    ("2e", "missing_operand", "e"),
    ("not", "missing_operand", "not"),
    (")", "unexpected_closing_bracket", ""),
    ("(1))", "unexpected_closing_bracket", ""),
    ("((1)", "unclosed_bracket", ""),
    ("2 (3)", "unexpected_operator", "("),
    ("1 !=", "missing_operand", "<>"),
    ("1 / -0", "division_by_zero", "/"),
    ("1 / (1 < 0)", "division_by_zero", "/"),
    ("1 mod 0.5", "division_by_zero", "mod"),
    ("1 fmod -0", "division_by_zero", "fmod"),
    ("ln 0", "invalid_argument_ln", "ln"),
    ("acos 2", "invalid_argument", "acos"),
    (f"sqrt {N}", "not_a_number", "sqrt"),
    ("1 + é", "unrecognised_punctuation", "é"),
    ("1 \f+ 2", "unrecognised_punctuation", "\f"),
    ("1 % 2", "unrecognised_punctuation", "%"),
    ("1 ! 2", "unrecognised_punctuation", "!"),
    ("1 & 2", "unrecognised_punctuation", "&"),
    ("(" * 101 + "1" + ")" * 101, "stack_exhausted", ""),
]

MESSAGES = [
    ("1 + X", 'Expression error: Unrecognized word "x".'),
    ("1 2", "Expression error: Unexpected number."),
    ("1 (", "Expression error: Unexpected ( operator."),
    ("1 +", "Expression error: Missing operand for +."),
    ("1)", "Expression error: Unexpected closing bracket."),
    ("1, 2", 'Expression error: Unrecognized punctuation character ",".'),
    ("(1", "Expression error: Unclosed bracket."),
    ("1/0", "Division by zero."),
    ("asin 2", "Invalid argument for asin: < -1 or > 1."),
    ("ln 0", "Invalid argument for ln: <= 0."),
    ("sqrt(-1)", "In sqrt: Result is not a number."),
    ("(" * 101 + "1", "Expression error: Stack exhausted."),
]


class ExprParserTest(unittest.TestCase):
    def evaluate(self, text: str) -> str:
        return ExprParser().do_expression(text)

    def test_expressions(self):
        for text, expected in EXPRESSIONS + EDGE_CASES:
            with self.subTest(text):
                self.assertEqual(expected, self.evaluate(text))

    def test_expression_throws(self):
        for text, key, parameter in THROWS + EDGE_THROWS:
            with self.subTest(text):
                with self.assertRaises(ExprError) as cm:
                    self.evaluate(text)
                self.assertEqual(f"pfunc_expr_{key}", cm.exception.key)
                self.assertEqual(parameter, cm.exception.parameter)

    def test_messages(self):
        for text, message in MESSAGES:
            with self.subTest(text):
                with self.assertRaises(ExprError) as cm:
                    self.evaluate(text)
                self.assertEqual(message, cm.exception.get_user_friendly_message())
        self.assertEqual("Expression error: Unknown error ().", ExprError("unknown_error").get_user_friendly_message())

    def test_unknown_operator(self):
        with self.assertRaises(ExprError) as cm:
            ExprParser().do_operation(expr.EXPR_OPEN, [1.0, 2.0])
        self.assertEqual("pfunc_expr_unknown_error", cm.exception.key)


class PhpNumberTest(unittest.TestCase):
    def test_float_to_string(self):
        for value, expected in [
            (0.0, "0"), (-0.0, "-0"), (1.0, "1"), (1.5, "1.5"), (-2.25, "-2.25"), (1e14, "1.0E+14"),
            (99999999999999.9, "1.0E+14"), (12345678901234.7, "12345678901235"), (1e-5, "1.0E-5"),
            (0.0001, "0.0001"), (1.5e-7, "1.5E-7"), (1e100, "1.0E+100"), (5e-324, "4.9406564584125E-324"),
            (math.inf, "INF"), (-math.inf, "-INF"), (math.nan, "NAN"), (0.1 + 0.2, "0.3"),
        ]:
            with self.subTest(value):
                self.assertEqual(expected, expr.php_float_to_string(value))
        self.assertEqual("9223372036854775807", expr.php_number_to_string(expr.PHP_INT_MAX))

    def test_int_cast(self):
        for value, expected in [
            (4.9, 4), (-4.9, -4), (2.0 ** 63, -2 ** 63), (-2.0 ** 63, -2 ** 63), (2.0 ** 64, 0),
            (1e20, 7766279631452241920), (-1e20, -7766279631452241920), (1.5 * 2 ** 64, -2 ** 63),
            (-1.25 * 2 ** 64, -2 ** 62),
            (math.inf, 0), (-math.inf, 0), (math.nan, 0), (7, 7),
        ]:
            with self.subTest(value):
                self.assertEqual(expected, expr.php_int(value))

    def test_integer_overflow(self):
        self.assertEqual(float, type(expr.php_add(expr.PHP_INT_MAX, 1)))
        self.assertEqual(int, type(expr.php_add(expr.PHP_INT_MAX, 0)))
        self.assertEqual(float, type(expr.php_sub(expr.PHP_INT_MIN, 1)))
        self.assertEqual(float, type(expr.php_mul(2 ** 62, 2)))
        self.assertEqual(int, type(expr.php_div(6, 3)))
        self.assertEqual(float, type(expr.php_div(7, 2)))
        self.assertEqual(float, type(expr.php_neg(expr.PHP_INT_MIN)))
        self.assertEqual(float, type(expr.php_pow(2, 63)))
        self.assertEqual(int, type(expr.php_pow(-2, 63)))
        self.assertEqual(float, type(expr.php_pow(2, -1)))

    def test_round(self):
        for value, places, expected in [
            (1.955, 2, 1.96), (5.045, 2, 5.05), (5.055, 2, 5.06), (-1.5, 0, -2.0), (0.5, 0, 1.0),
            (1234567.891, -3, 1235000.0), (3, 0, 3.0), (15, -1, 20.0), (1.5, 2 ** 40, 1.5), (5.0, -2 ** 40, 0.0),
        ]:
            with self.subTest((value, places)):
                result = expr.php_round(value, places)
                self.assertEqual(float, type(result))
                self.assertEqual(expected, result)
        self.assertEqual("-0", expr.php_float_to_string(expr.php_round(-0.0, 0)))


if __name__ == "__main__":
    unittest.main()
