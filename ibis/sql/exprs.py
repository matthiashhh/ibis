# Copyright 2014 Cloudera Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# An Ibis analytical expression will typically consist of a primary SELECT
# statement, with zero or more supporting DDL queries. For example we would
# want to support converting a text file in HDFS to a Parquet-backed Impala
# table, with optional teardown if the user wants the intermediate converted
# table to be temporary.


import ibis.expr.base as ir
import ibis.util as util


#----------------------------------------------------------------------
# Scalar and array expression formatting

_sql_type_names = {
    'int8': 'tinyint',
    'int16': 'smallint',
    'int32': 'int',
    'int64': 'bigint',
    'float': 'float',
    'double': 'double',
    'string': 'string',
    'boolean': 'boolean'
}

def _cast(translator, expr):
    op = expr.op()
    arg = translator.translate(op.value_expr)
    sql_type = _sql_type_names[op.target_type]
    return 'CAST({!s} AS {!s})'.format(arg, sql_type)


def _between(translator, expr):
    op = expr.op()
    comp = translator.translate(op.expr)
    lower = translator.translate(op.lower_bound)
    upper = translator.translate(op.upper_bound)
    return '{!s} BETWEEN {!s} AND {!s}'.format(comp, lower, upper)


def _is_null(translator, expr):
    formatted_arg = translator.translate(expr.op().arg)
    return '{!s} IS NULL'.format(formatted_arg)


def _not_null(translator, expr):
    formatted_arg = translator.translate(expr.op().arg)
    return '{!s} IS NOT NULL'.format(formatted_arg)


def _negate(translator, expr):
    arg = expr.op().arg
    formatted_arg = translator.translate(arg)
    if isinstance(expr, ir.BooleanValue):
        return 'NOT {!s}'.format(formatted_arg)
    else:
        if _needs_parens(arg):
            formatted_arg = _parenthesize(formatted_arg)
        return '-{!s}'.format(formatted_arg)


def _parenthesize(what):
    return '({!s})'.format(what)


def _unary_op(func_name):
    def formatter(translator, expr):
        arg = translator.translate(expr.op().arg)
        return '{!s}({!s})'.format(func_name, arg)
    return formatter


def _binary_infix_op(infix_sym):
    def formatter(translator, expr):
        op = expr.op()

        left_arg = translator.translate(op.left)
        right_arg = translator.translate(op.right)

        if _needs_parens(op.left):
            left_arg = _parenthesize(left_arg)

        if _needs_parens(op.right):
            right_arg = _parenthesize(right_arg)

        return '{!s} {!s} {!s}'.format(left_arg, infix_sym, right_arg)
    return formatter


def _xor(translator, expr):
    op = expr.op()

    left_arg = translator.translate(op.left)
    right_arg = translator.translate(op.right)

    if _needs_parens(op.left):
        left_arg = _parenthesize(left_arg)

    if _needs_parens(op.right):
        right_arg = _parenthesize(right_arg)

    return ('{0} AND NOT {1}'
            .format('({0} {1} {2})'.format(left_arg, 'OR', right_arg),
                    '({0} {1} {2})'.format(left_arg, 'AND', right_arg)))


def _name_expr(formatted_expr, quoted_name):
    return '{!s} AS {!s}'.format(formatted_expr, quoted_name)


def _needs_parens(op):
    if isinstance(op, ir.Expr):
        op = op.op()
    op_klass = type(op)
    # function calls don't need parens
    return (op_klass in _binary_infix_ops or
            op_klass in [ir.Negate])


def _need_parenthesize_args(op):
    if isinstance(op, ir.Expr):
        op = op.op()
    op_klass = type(op)
    return (op_klass in _binary_infix_ops or
            op_klass in [ir.Negate])


def _boolean_literal_format(expr):
    value = expr.op().value
    return 'TRUE' if value else 'FALSE'


def _number_literal_format(expr):
    value = expr.op().value
    return repr(value)


def _string_literal_format(expr):
    value = expr.op().value
    return "'{!s}'".format(value.replace("'", "\\'"))


def _quote_field(name, quotechar='`'):
    if name.count(' '):
        return '{0}{1}{0}'.format(quotechar, name)
    else:
        return name

def _trans_literal(translator, expr):
    if isinstance(expr, ir.BooleanValue):
        typeclass = 'boolean'
    elif isinstance(expr, ir.StringValue):
        typeclass = 'string'
    elif isinstance(expr, ir.NumericValue):
        typeclass = 'number'
    else:
        raise NotImplementedError

    return _literal_formatters[typeclass](expr)

_literal_formatters = {
    'boolean': _boolean_literal_format,
    'number': _number_literal_format,
    'string': _string_literal_format
}


_unary_ops = {
    # Unary operations
    ir.NotNull: _not_null,
    ir.IsNull: _is_null,
    ir.Negate: _negate,
    ir.Exp: _unary_op('exp'),
    ir.Sqrt: _unary_op('sqrt'),
    ir.Log: _unary_op('log'),
    ir.Log2: _unary_op('log2'),
    ir.Log10: _unary_op('log10'),

    # Unary aggregates
    ir.Mean: _unary_op('avg'),
    ir.Sum: _unary_op('sum'),
    ir.Max: _unary_op('max'),
    ir.Min: _unary_op('min'),

    ir.Count: _unary_op('count')
}

_binary_infix_ops = {
    # Binary operations
    ir.Add: _binary_infix_op('+'),
    ir.Subtract: _binary_infix_op('-'),
    ir.Multiply: _binary_infix_op('*'),
    ir.Divide: _binary_infix_op('/'),
    ir.Power: _binary_infix_op('^'),

    # Comparisons
    ir.Equals: _binary_infix_op('='),
    ir.NotEquals: _binary_infix_op('!='),
    ir.GreaterEqual: _binary_infix_op('>='),
    ir.Greater: _binary_infix_op('>'),
    ir.LessEqual: _binary_infix_op('<='),
    ir.Less: _binary_infix_op('<'),

    # Boolean comparisons
    ir.And: _binary_infix_op('AND'),
    ir.Or: _binary_infix_op('OR'),
    ir.Xor: _xor,
}


def _table_array_view(translator, expr):
    ctx = translator.context
    table = expr.op().table
    query = ctx.get_formatted_query(table)
    return '(\n{}\n)'.format(util.indent(query, ctx.indent))


def _extract_field(sql_attr):
    def extract_field_formatter(translator, expr):
        op = expr.op()
        arg = translator.translate(op.arg)

        # This is pre-2.0 Impala-style, which did not used to support the
        # SQL-99 format extract($FIELD from expr)
        return 'extract({!s}, "{!s}")'.format(arg, sql_attr)
    return extract_field_formatter


_timestamp_ops = {
    ir.ExtractYear: _extract_field('year'),
    ir.ExtractMonth: _extract_field('month'),
    ir.ExtractDay: _extract_field('day'),
    ir.ExtractHour: _extract_field('hour'),
    ir.ExtractMinute: _extract_field('minute'),
    ir.ExtractSecond: _extract_field('second'),
    ir.ExtractMillisecond: _extract_field('millisecond'),
}


_other_ops = {
    ir.Literal: _trans_literal,
    ir.Cast: _cast,
    ir.Between: _between,
    ir.TableArrayView: _table_array_view
}


_operation_registry = {}
_operation_registry.update(_unary_ops)
_operation_registry.update(_binary_infix_ops)
_operation_registry.update(_timestamp_ops)
_operation_registry.update(_other_ops)


class ExprTranslator(object):

    def __init__(self, expr, context=None, named=False):
        self.expr = expr

        if context is None:
            from ibis.sql.compiler import QueryContext
            context = QueryContext()
        self.context = context

        # For now, governing whether the result will have a name
        self.named = named

    def get_result(self):
        """
        Build compiled SQL expression from the bottom up and return as a string
        """
        translated = self.translate(self.expr)
        if self._needs_name(self.expr):
            # TODO: this could fail in various ways
            name = self.expr.get_name()
            translated = _name_expr(translated, _quote_field(name))
        return translated

    def _needs_name(self, expr):
        if not self.named:
            return False

        op = expr.op()
        if isinstance(op, ir.TableColumn):
            # This column has been given an explicitly different name
            if expr.get_name() != op.name:
                return True
            return False

        return True

    def translate(self, expr):
        # The operation node type the typed expression wraps
        op = expr.op()

        if isinstance(op, ir.Parameter):
            return self._trans_param(expr)
        elif isinstance(op, ir.TableColumn):
            return self._trans_column_ref(expr)
        elif isinstance(op, ir.PhysicalTable):
            # HACK/TODO: revisit for more complex cases
            return '*'
        elif type(op) in _operation_registry:
            formatter = _operation_registry[type(op)]
            return formatter(self, expr)
        else:
            raise NotImplementedError('No translator rule for {0}'.format(op))

    def _trans_param(self, expr):
        raise NotImplementedError

    def _trans_column_ref(self, expr):
        op = expr.op()
        field_name = _quote_field(op.name)

        if self.context.need_aliases():
            alias = self.context.get_alias(op.table)
            if alias is not None:
                field_name = '{0}.{1}'.format(alias, field_name)

        return field_name