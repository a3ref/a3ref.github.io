# Ported from the ParserFunctions extension 1.6.0 for MediaWiki 1.39 (branch REL1_39 as released with MediaWiki
# 1.39.0, commit 4b0abc7f9fdc4593dc9b2db0b3fd5a4e76fc8e7a): includes/ExprParser.php and includes/ExprError.php
# (https://www.mediawiki.org/wiki/Extension:ParserFunctions), (C) Tim Starling, Robert Rohde, Ross McClure, Juraj
# Simlovic and other ParserFunctions contributors.
# Changed by a3ref contributors on 2026-10-30: translated to Python; one module; PHP's int/float arithmetic (integer
# results of mod, trunc and comparisons, overflow to float, (int) casts that wrap, int/float comparisons), pow(),
# round() (PHP 7.4 to 8.3, with pre-rounding), floor()/ceil() and the float-to-string conversion (precision 14)
# are reproduced by helpers; the messages are English (biwiki/mediawiki/messages.py).
#
# This program is free software; you can redistribute it and/or modify it under the terms of the GNU General
# Public License as published by the Free Software Foundation; either version 2 of the License, or (at your
# option) any later version. This program is distributed in the hope that it will be useful, but WITHOUT ANY
# WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details: biwiki/mediawiki/COPYING.
"""{{#expr:}}: evaluation of arithmetic and logical expressions."""
from __future__ import annotations

import math
import re
from typing import Union

from ..messages import msg as wf_message
from ..stringutils import php_strtr

Number = Union[int, float]

PHP_INT_MAX = 2 ** 63 - 1
PHP_INT_MIN = -2 ** 63
INT_MAX = 2 ** 31 - 1  # C int, the type of round()'s places
INT_MIN = -2 ** 31
DBL_DIG = 15


class ExprError(Exception):
    def __init__(self, msg: str, parameter: str = ""):
        super().__init__(msg)
        # Give grep a chance to find the usages:
        # pfunc_expr_stack_exhausted, pfunc_expr_unexpected_number, pfunc_expr_preg_match_failure,
        # pfunc_expr_unrecognised_word, pfunc_expr_unexpected_operator, pfunc_expr_missing_operand,
        # pfunc_expr_unexpected_closing_bracket, pfunc_expr_unrecognised_punctuation,
        # pfunc_expr_unclosed_bracket, pfunc_expr_division_by_zero, pfunc_expr_invalid_argument,
        # pfunc_expr_invalid_argument_ln, pfunc_expr_unknown_error, pfunc_expr_not_a_number
        self.key = f"pfunc_expr_{msg}"
        self.parameter = parameter
        self.mw_message = wf_message(self.key, parameter)

    def get_user_friendly_message(self) -> str:
        """Error message to be displayed to end users (the message in the content language, as text)."""
        return self.mw_message


# ---- PHP numbers ------------------------------------------------------------------------------------------------


def php_float_to_string(f: float) -> str:
    """(string) of a PHP float: 14 significant digits ("precision"), "1.0E+20" for exponents, "-0", INF, NAN."""
    if math.isnan(f):
        return "NAN"
    if math.isinf(f):
        return "INF" if f > 0 else "-INF"
    if f == 0:
        return "-0" if math.copysign(1.0, f) < 0 else "0"
    s = "%.14G" % f
    if "E" in s:
        mantissa, exp = s.split("E")
        if "." not in mantissa:
            mantissa += ".0"
        sign = exp[0]
        exp = exp[1:].lstrip("0") or "0"
        return f"{mantissa}E{sign}{exp}"
    return s


def php_number_to_string(n: Number) -> str:
    if isinstance(n, bool):
        return "1" if n else ""
    if isinstance(n, int):
        return str(n)
    return php_float_to_string(n)


def php_int(x: Number) -> int:
    """(int) of a PHP number: floats are truncated; out of range they wrap modulo 2^64 (PHP 7+ on 64 bits), NaN and
    infinities are 0."""
    if isinstance(x, bool):
        return int(x)
    if isinstance(x, int):
        return x
    if math.isnan(x) or math.isinf(x):
        return 0
    if PHP_INT_MIN <= x <= PHP_INT_MAX:
        return int(x)
    v = int(math.fmod(math.trunc(x), 2.0 ** 64))
    if v > PHP_INT_MAX:
        v -= 2 ** 64
    elif v < PHP_INT_MIN:
        v += 2 ** 64
    return v


def _int_or_float(v: int) -> Number:
    """An integer result: a float when it overflows PHP's 64-bit integers."""
    return v if PHP_INT_MIN <= v <= PHP_INT_MAX else float(v)


def php_add(a: Number, b: Number) -> Number:
    if isinstance(a, int) and isinstance(b, int):
        return _int_or_float(a + b)
    return float(a) + float(b)


def php_sub(a: Number, b: Number) -> Number:
    if isinstance(a, int) and isinstance(b, int):
        return _int_or_float(a - b)
    return float(a) - float(b)


def php_mul(a: Number, b: Number) -> Number:
    if isinstance(a, int) and isinstance(b, int):
        return _int_or_float(a * b)
    return float(a) * float(b)


def php_div(a: Number, b: Number) -> Number:
    """/: an integer when both operands are integers and the division is exact."""
    if isinstance(a, int) and isinstance(b, int) and a % b == 0:
        return _int_or_float(a // b)
    return float(a) / float(b)


def php_neg(a: Number) -> Number:
    if isinstance(a, int):
        return _int_or_float(-a)
    return -a


def php_mod(a: int, b: int) -> int:
    """PHP's % on integers: the sign of the dividend."""
    if b == -1:
        return 0
    r = abs(a) % abs(b)
    return -r if a < 0 else r


def _is_odd_integer(y: float) -> bool:
    return math.isfinite(y) and y == math.floor(y) and int(y) % 2 == 1


def c_pow(x: float, y: float) -> float:
    """C's pow(): Python's math.pow raises where C returns an infinity (overflow, 0 to a negative power, with the
    sign of -0 for odd powers) or NaN (a negative base to a non-integer power)."""
    try:
        return math.pow(x, y)
    except OverflowError:
        return -math.inf if x < 0 and _is_odd_integer(y) else math.inf
    except ValueError:
        if x == 0:
            return math.copysign(math.inf, x) if _is_odd_integer(y) else math.inf
        return math.nan


def _signed_multiply_long(a: int, b: int) -> tuple[int | None, float]:
    """ZEND_SIGNED_MULTIPLY_LONG: the product, or None and the product of the two as doubles if it overflows."""
    r = a * b
    if PHP_INT_MIN <= r <= PHP_INT_MAX:
        return r, 0.0
    return None, float(a) * float(b)


def php_pow(a: Number, b: Number) -> Number:
    """pow() (pow_function_base): integers by squaring while the result fits, then as doubles; C's pow() otherwise."""
    if isinstance(a, int) and isinstance(b, int):
        if b >= 0:
            l1, l2, i = 1, a, b
            if i == 0:
                return 1
            elif l2 == 0:
                return 0
            # calculate pow(long,long) in O(log exp) operations, bail if overflow
            while i >= 1:
                if i % 2:
                    i -= 1
                    r, dval = _signed_multiply_long(l1, l2)
                    if r is None:
                        return dval * c_pow(float(l2), float(i))
                    l1 = r
                else:
                    i //= 2
                    r, dval = _signed_multiply_long(l2, l2)
                    if r is None:
                        return float(l1) * c_pow(dval, float(i))
                    l2 = r
            # i == 0
            return l1
    return c_pow(float(a), float(b))


def _math(fn, x: Number) -> float:
    """A C math function: NaN for a domain error (sin(INF)), INF for an overflow (exp(1000)), as C returns them."""
    try:
        return fn(float(x))
    except ValueError:
        return math.nan
    except OverflowError:
        return math.inf


def c_floor(x: float) -> float:
    """C's floor(): a float, keeping the sign of zero (floor(-0.0) is -0.0); infinities and NaN as they are."""
    if not math.isfinite(x):
        return x
    # floor() and ceil() never change the sign, except that a result of zero keeps the sign of x
    return math.copysign(float(math.floor(x)), x)


def c_ceil(x: float) -> float:
    """C's ceil(): ceil(-0.5) is -0.0."""
    if not math.isfinite(x):
        return x
    return math.copysign(float(math.ceil(x)), x)


def _php_intpow10(power: int) -> float:
    """php_intpow10(): exact powers of ten up to 1e22, pow() beyond (INF when it overflows)."""
    if power < 0 or power > 22:
        return c_pow(10.0, float(power))
    return float(10 ** power)


def _php_round_helper(value: float) -> float:
    """php_round_helper() for PHP_ROUND_HALF_UP"""
    if value >= 0.0:
        return c_floor(value + 0.5)
    return c_ceil(value - 0.5)


def _php_round_get_basic(value: float, places: int) -> float:
    f1 = _php_intpow10(abs(places))
    if places >= 0:
        return value * f1
    return value / f1


def _php_math_round(value: float, places: int) -> float:
    """_php_math_round() of PHP 7.4 to 8.3 (ext/standard/math.c): the value is first rounded to the 15 significant
    digits a double can hold, so 1.955 (really 1.95499999999999996) rounds to 1.96."""
    if not math.isfinite(value) or value == 0.0:
        return value

    places = INT_MIN + 1 if places < INT_MIN + 1 else places
    precision_places = 14 - math.floor(math.log10(abs(value)))  # php_intlog10abs()

    f1 = _php_intpow10(abs(places))

    # If the decimal precision guaranteed by FP arithmetic is higher than the requested places BUT is small enough
    # to make sure a non-zero value is returned, pre-round the result to the precision
    if precision_places > places and precision_places - 15 < places:
        use_precision = -(4 * DBL_DIG) if precision_places < -(4 * DBL_DIG) else precision_places

        # preround the result (tmp_value will always be something * 1e14, thus never larger than 1e15 here)
        tmp_value = _php_round_helper(_php_round_get_basic(value, use_precision))

        use_precision = places - use_precision
        use_precision = max(-(4 * DBL_DIG), use_precision)
        # because places < precision_places
        tmp_value = tmp_value / _php_intpow10(abs(use_precision))
    else:
        # adjust the value
        if places >= 0:
            tmp_value = value * f1
        else:
            tmp_value = value / f1
        # This value is beyond our precision, so rounding it is pointless
        if abs(tmp_value) >= 1e15:
            return value

    # round the temp value
    tmp_value = _php_round_helper(tmp_value)

    # see if it makes sense to use simple division to round the value
    if abs(places) < 23:
        if places > 0:
            tmp_value = tmp_value / f1
        else:
            tmp_value = tmp_value * f1
    else:
        # Simple division can't be used since that will cause wrong results. Instead, the number is converted to a
        # string and back again using strtod().
        buf = ("%15fe%d" % (tmp_value, -places))[:38]  # snprintf( buf, 39, ... )
        try:
            tmp_value = float(buf)
        except ValueError:
            tmp_value = 0.0  # zend_strtod() of "inf...": no number
        # couldn't convert to string and back
        if not math.isfinite(tmp_value):
            return value
    return tmp_value


def php_round(value: Number, places: int) -> float:
    """round( $value, $places ): always a float; an integer with places >= 0 is not rounded at all."""
    places = max(INT_MIN, min(INT_MAX, places))
    if isinstance(value, int) and places >= 0:
        return float(value)
    return _php_math_round(float(value), places)


def php_floor(x: Number) -> float:
    """floor() and ceil() return floats, also for integers."""
    return c_floor(float(x))


def php_ceil(x: Number) -> float:
    return c_ceil(float(x))


def php_compare_operands(left: Number, right: Number) -> tuple[Number, Number]:
    """PHP compares an integer with a float as two floats (2**60 + 1 == 2.0**60)."""
    if isinstance(left, int) != isinstance(right, int):
        return float(left), float(right)
    return left, right


# ---- the parser ---------------------------------------------------------------------------------------------------

# Character classes
EXPR_WHITE_CLASS = " \t\r\n"
EXPR_NUMBER_CLASS = "0123456789."

# Token types
EXPR_WHITE = 1
EXPR_NUMBER = 2
EXPR_NEGATIVE = 3
EXPR_POSITIVE = 4
EXPR_PLUS = 5
EXPR_MINUS = 6
EXPR_TIMES = 7
EXPR_DIVIDE = 8
EXPR_MOD = 9
EXPR_OPEN = 10
EXPR_CLOSE = 11
EXPR_AND = 12
EXPR_OR = 13
EXPR_NOT = 14
EXPR_EQUALITY = 15
EXPR_LESS = 16
EXPR_GREATER = 17
EXPR_LESSEQ = 18
EXPR_GREATEREQ = 19
EXPR_NOTEQ = 20
EXPR_ROUND = 21
EXPR_EXPONENT = 22
EXPR_SINE = 23
EXPR_COSINE = 24
EXPR_TANGENS = 25
EXPR_ARCSINE = 26
EXPR_ARCCOS = 27
EXPR_ARCTAN = 28
EXPR_EXP = 29
EXPR_LN = 30
EXPR_ABS = 31
EXPR_FLOOR = 32
EXPR_TRUNC = 33
EXPR_CEIL = 34
EXPR_POW = 35
EXPR_PI = 36
EXPR_FMOD = 37
EXPR_SQRT = 38

MAX_STACK_SIZE = 100

PRECEDENCE = {
    EXPR_NEGATIVE: 10,
    EXPR_POSITIVE: 10,
    EXPR_EXPONENT: 10,
    EXPR_SINE: 9,
    EXPR_COSINE: 9,
    EXPR_TANGENS: 9,
    EXPR_ARCSINE: 9,
    EXPR_ARCCOS: 9,
    EXPR_ARCTAN: 9,
    EXPR_EXP: 9,
    EXPR_LN: 9,
    EXPR_ABS: 9,
    EXPR_FLOOR: 9,
    EXPR_TRUNC: 9,
    EXPR_CEIL: 9,
    EXPR_NOT: 9,
    EXPR_SQRT: 9,
    EXPR_POW: 8,
    EXPR_TIMES: 7,
    EXPR_DIVIDE: 7,
    EXPR_MOD: 7,
    EXPR_FMOD: 7,
    EXPR_PLUS: 6,
    EXPR_MINUS: 6,
    EXPR_ROUND: 5,
    EXPR_EQUALITY: 4,
    EXPR_LESS: 4,
    EXPR_GREATER: 4,
    EXPR_LESSEQ: 4,
    EXPR_GREATEREQ: 4,
    EXPR_NOTEQ: 4,
    EXPR_AND: 3,
    EXPR_OR: 2,
    EXPR_PI: 0,
    EXPR_OPEN: -1,
    EXPR_CLOSE: -1,
}

NAMES = {
    EXPR_NEGATIVE: "-",
    EXPR_POSITIVE: "+",
    EXPR_NOT: "not",
    EXPR_TIMES: "*",
    EXPR_DIVIDE: "/",
    EXPR_MOD: "mod",
    EXPR_FMOD: "fmod",
    EXPR_PLUS: "+",
    EXPR_MINUS: "-",
    EXPR_ROUND: "round",
    EXPR_EQUALITY: "=",
    EXPR_LESS: "<",
    EXPR_GREATER: ">",
    EXPR_LESSEQ: "<=",
    EXPR_GREATEREQ: ">=",
    EXPR_NOTEQ: "<>",
    EXPR_AND: "and",
    EXPR_OR: "or",
    EXPR_EXPONENT: "e",
    EXPR_SINE: "sin",
    EXPR_COSINE: "cos",
    EXPR_TANGENS: "tan",
    EXPR_ARCSINE: "asin",
    EXPR_ARCCOS: "acos",
    EXPR_ARCTAN: "atan",
    EXPR_LN: "ln",
    EXPR_EXP: "exp",
    EXPR_ABS: "abs",
    EXPR_FLOOR: "floor",
    EXPR_TRUNC: "trunc",
    EXPR_CEIL: "ceil",
    EXPR_POW: "^",
    EXPR_PI: "pi",
    EXPR_SQRT: "sqrt",
}

WORDS = {
    "mod": EXPR_MOD,
    "fmod": EXPR_FMOD,
    "and": EXPR_AND,
    "or": EXPR_OR,
    "not": EXPR_NOT,
    "round": EXPR_ROUND,
    "div": EXPR_DIVIDE,
    "e": EXPR_EXPONENT,
    "sin": EXPR_SINE,
    "cos": EXPR_COSINE,
    "tan": EXPR_TANGENS,
    "asin": EXPR_ARCSINE,
    "acos": EXPR_ARCCOS,
    "atan": EXPR_ARCTAN,
    "exp": EXPR_EXP,
    "ln": EXPR_LN,
    "abs": EXPR_ABS,
    "trunc": EXPR_TRUNC,
    "floor": EXPR_FLOOR,
    "ceil": EXPR_CEIL,
    "pi": EXPR_PI,
    "sqrt": EXPR_SQRT,
}

_UNARY = {EXPR_NOT, EXPR_SINE, EXPR_COSINE, EXPR_TANGENS, EXPR_ARCSINE, EXPR_ARCCOS, EXPR_ARCTAN, EXPR_EXP, EXPR_LN,
          EXPR_ABS, EXPR_FLOOR, EXPR_TRUNC, EXPR_CEIL, EXPR_SQRT}
_NUMBER_PREFIX = re.compile(r"[0-9]*(?:\.[0-9]*)?")


def _php_float_of_number(s: str) -> float:
    """(float) of a run of digits and dots: its leading numeric part ("1.2.3" is 1.2), 0 if there is none."""
    m = _NUMBER_PREFIX.match(s).group(0)
    if m in ("", "."):
        return 0.0
    return float(m)


def _strspn(s: str, chars: str, start: int) -> int:
    i = start
    while i < len(s) and s[i] in chars:
        i += 1
    return i - start


class ExprParser:
    def do_expression(self, expr: str) -> str:
        """Evaluate a mathematical expression.

        The algorithm here is based on the infix to RPN algorithm given in
        http://montcs.bloomu.edu/~bobmon/Information/RPN/infix2rpn.shtml
        It's essentially the same as Dijkstra's shunting yard algorithm."""
        operands: list[Number] = []
        operators: list[int] = []

        # Unescape inequality operators
        expr = php_strtr(expr, {"&lt;": "<", "&gt;": ">", "&minus;": "-", "−": "-"})

        p = 0
        end = len(expr)
        expecting = "expression"
        name = ""

        while p < end:
            if len(operands) > MAX_STACK_SIZE or len(operators) > MAX_STACK_SIZE:
                raise ExprError("stack_exhausted")
            char = expr[p]
            char2 = expr[p:p + 2]

            # Mega if-elseif-else construct
            # Only binary operators fall through for processing at the bottom, the rest finish their processing and
            # continue

            # First the unlimited length classes

            if char in EXPR_WHITE_CLASS:
                # Whitespace
                p += _strspn(expr, EXPR_WHITE_CLASS, p)
                continue
            elif char in EXPR_NUMBER_CLASS:
                # Number
                if expecting != "expression":
                    raise ExprError("unexpected_number")

                # Find the rest of it
                length = _strspn(expr, EXPR_NUMBER_CLASS, p)
                # Convert it to float, silently removing double decimal points
                operands.append(_php_float_of_number(expr[p:p + length]))
                p += length
                expecting = "operator"
                continue
            elif char.isascii() and char.isalpha():
                # Word
                # Find the rest of it
                m = re.match(r"[A-Za-z]*", expr[p:])
                word = m.group(0).lower()
                p += len(word)

                # Interpret the word
                if word not in WORDS:
                    raise ExprError("unrecognised_word", word)
                op = WORDS[word]
                if op == EXPR_EXPONENT:
                    # constant
                    if expecting == "expression":
                        operands.append(math.e)
                        expecting = "operator"
                        continue
                elif op == EXPR_PI:
                    if expecting != "expression":
                        raise ExprError("unexpected_number")
                    operands.append(math.pi)
                    expecting = "operator"
                    continue
                elif op in _UNARY:
                    # Unary operator
                    if expecting != "expression":
                        raise ExprError("unexpected_operator", word)
                    operators.append(op)
                    continue
                # Binary operator, fall through
                name = word
            elif char2 == "<=":
                name = char2
                op = EXPR_LESSEQ
                p += 2
            elif char2 == ">=":
                name = char2
                op = EXPR_GREATEREQ
                p += 2
            elif char2 in ("<>", "!="):
                name = char2
                op = EXPR_NOTEQ
                p += 2
            elif char == "+":
                p += 1
                if expecting == "expression":
                    # Unary plus
                    operators.append(EXPR_POSITIVE)
                    continue
                # Binary plus
                op = EXPR_PLUS
            elif char == "-":
                p += 1
                if expecting == "expression":
                    # Unary minus
                    operators.append(EXPR_NEGATIVE)
                    continue
                # Binary minus
                op = EXPR_MINUS
            elif char == "*":
                name = char
                op = EXPR_TIMES
                p += 1
            elif char == "/":
                name = char
                op = EXPR_DIVIDE
                p += 1
            elif char == "^":
                name = char
                op = EXPR_POW
                p += 1
            elif char == "(":
                if expecting == "operator":
                    raise ExprError("unexpected_operator", "(")
                operators.append(EXPR_OPEN)
                p += 1
                continue
            elif char == ")":
                last_op = operators[-1] if operators else False
                while last_op and last_op != EXPR_OPEN:
                    self.do_operation(last_op, operands)
                    operators.pop()
                    last_op = operators[-1] if operators else False
                if last_op:
                    operators.pop()
                else:
                    raise ExprError("unexpected_closing_bracket")
                expecting = "operator"
                p += 1
                continue
            elif char == "=":
                name = char
                op = EXPR_EQUALITY
                p += 1
            elif char == "<":
                name = char
                op = EXPR_LESS
                p += 1
            elif char == ">":
                name = char
                op = EXPR_GREATER
                p += 1
            else:
                raise ExprError("unrecognised_punctuation", char)

            # Binary operator processing
            if expecting == "expression":
                raise ExprError("unexpected_operator", name)

            # Shunting yard magic
            last_op = operators[-1] if operators else False
            while last_op and PRECEDENCE[op] <= PRECEDENCE[last_op]:
                self.do_operation(last_op, operands)
                operators.pop()
                last_op = operators[-1] if operators else False
            operators.append(op)
            expecting = "expression"

        # Finish off the operator array
        while operators:
            op = operators.pop()
            if op == EXPR_OPEN:
                raise ExprError("unclosed_bracket")
            self.do_operation(op, operands)

        return "<br />\n".join(php_number_to_string(x) for x in operands)

    def do_operation(self, op: int, stack: list[Number]) -> None:
        unary = op in (EXPR_NEGATIVE, EXPR_POSITIVE, EXPR_NOT) or op in _UNARY
        if len(stack) < (1 if unary else 2):
            if op not in NAMES:
                raise ExprError("unknown_error")
            raise ExprError("missing_operand", NAMES[op])

        if op == EXPR_NEGATIVE:
            stack.append(php_neg(stack.pop()))
        elif op == EXPR_POSITIVE:
            pass
        elif op == EXPR_TIMES:
            right, left = stack.pop(), stack.pop()
            stack.append(php_mul(left, right))
        elif op == EXPR_DIVIDE:
            right, left = stack.pop(), stack.pop()
            if not right:
                raise ExprError("division_by_zero", NAMES[op])
            stack.append(php_div(left, right))
        elif op == EXPR_MOD:
            right, left = php_int(stack.pop()), php_int(stack.pop())
            if not right:
                raise ExprError("division_by_zero", NAMES[op])
            stack.append(php_mod(left, right))
        elif op == EXPR_FMOD:
            right, left = float(stack.pop()), float(stack.pop())
            if not right:
                raise ExprError("division_by_zero", NAMES[op])
            stack.append(_math(lambda r: math.fmod(left, r), right))
        elif op == EXPR_PLUS:
            right, left = stack.pop(), stack.pop()
            stack.append(php_add(left, right))
        elif op == EXPR_MINUS:
            right, left = stack.pop(), stack.pop()
            stack.append(php_sub(left, right))
        elif op == EXPR_AND:
            right, left = stack.pop(), stack.pop()
            stack.append(1 if (left and right) else 0)
        elif op == EXPR_OR:
            right, left = stack.pop(), stack.pop()
            stack.append(1 if (left or right) else 0)
        elif op == EXPR_EQUALITY:
            right, left = stack.pop(), stack.pop()
            left, right = php_compare_operands(left, right)
            stack.append(1 if left == right else 0)
        elif op == EXPR_NOT:
            arg = stack.pop()
            stack.append(1 if not arg else 0)
        elif op == EXPR_ROUND:
            digits = php_int(stack.pop())
            value = stack.pop()
            stack.append(php_round(value, digits))
        elif op == EXPR_LESS:
            right, left = stack.pop(), stack.pop()
            left, right = php_compare_operands(left, right)
            stack.append(1 if left < right else 0)
        elif op == EXPR_GREATER:
            right, left = stack.pop(), stack.pop()
            left, right = php_compare_operands(left, right)
            stack.append(1 if left > right else 0)
        elif op == EXPR_LESSEQ:
            right, left = stack.pop(), stack.pop()
            left, right = php_compare_operands(left, right)
            stack.append(1 if left <= right else 0)
        elif op == EXPR_GREATEREQ:
            right, left = stack.pop(), stack.pop()
            left, right = php_compare_operands(left, right)
            stack.append(1 if left >= right else 0)
        elif op == EXPR_NOTEQ:
            right, left = stack.pop(), stack.pop()
            left, right = php_compare_operands(left, right)
            stack.append(1 if left != right else 0)
        elif op == EXPR_EXPONENT:
            right, left = stack.pop(), stack.pop()
            stack.append(php_mul(left, php_pow(10, right)))
        elif op == EXPR_SINE:
            stack.append(_math(math.sin, stack.pop()))
        elif op == EXPR_COSINE:
            stack.append(_math(math.cos, stack.pop()))
        elif op == EXPR_TANGENS:
            stack.append(_math(math.tan, stack.pop()))
        elif op == EXPR_ARCSINE:
            arg = stack.pop()
            if arg < -1 or arg > 1:
                raise ExprError("invalid_argument", NAMES[op])
            stack.append(_math(math.asin, arg))
        elif op == EXPR_ARCCOS:
            arg = stack.pop()
            if arg < -1 or arg > 1:
                raise ExprError("invalid_argument", NAMES[op])
            stack.append(_math(math.acos, arg))
        elif op == EXPR_ARCTAN:
            stack.append(_math(math.atan, stack.pop()))
        elif op == EXPR_EXP:
            stack.append(_math(math.exp, stack.pop()))
        elif op == EXPR_LN:
            arg = stack.pop()
            if arg <= 0:
                raise ExprError("invalid_argument_ln", NAMES[op])
            stack.append(_math(math.log, arg))
        elif op == EXPR_ABS:
            arg = stack.pop()
            stack.append(_int_or_float(abs(arg)) if isinstance(arg, int) else abs(arg))
        elif op == EXPR_FLOOR:
            stack.append(php_floor(stack.pop()))
        elif op == EXPR_TRUNC:
            stack.append(php_int(stack.pop()))
        elif op == EXPR_CEIL:
            stack.append(php_ceil(stack.pop()))
        elif op == EXPR_POW:
            right, left = stack.pop(), stack.pop()
            stack.append(php_pow(left, right))
        elif op == EXPR_SQRT:
            arg = stack.pop()
            result = _math(math.sqrt, arg)
            if math.isnan(result):
                raise ExprError("not_a_number", NAMES[op])
            stack.append(result)
        else:
            # Should be impossible to reach here.
            raise ExprError("unknown_error")
