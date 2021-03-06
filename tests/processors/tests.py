# -*- coding: utf-8 -*-

from mock import Mock

import raven
from raven.utils.testutils import TestCase
from raven.processors import SanitizePasswordsProcessor, \
    RemovePostDataProcessor, RemoveStackLocalsProcessor


VARS = {
    'foo': 'bar',
    'password': 'hello',
    'the_secret': 'hello',
    'a_password_here': 'hello',
    'api_key': 'secret_key',
    'apiKey': 'secret_key',
}


def get_stack_trace_data_real(exception_class=TypeError, **kwargs):
    def _will_throw_type_error(foo, **kwargs):
        password = "you should not see this"    # NOQA F841
        the_secret = "nor this"                 # NOQA F841
        a_password_here = "Don't look at me!"   # NOQA F841
        api_key = "I'm hideous!"                # NOQA F841
        apiKey = "4567000012345678"             # NOQA F841

        # TypeError: unsupported operand type(s) for /: 'str' and 'str'
        raise exception_class()

    client = raven.Client('http://public:secret@sentry.local/1')
    try:
        _will_throw_type_error('bar')
    except exception_class:
        data = client.build_msg('raven.events.Exception')

    return data


def get_http_data():
    """
    This is not so real as the data retrieved
    from the `get_stack_trace_data_real()`
    because we're still injecting HTTP data.
    Otherwise, we have to hard code the structure of a traceback, and this goes
    out of date when the format of data returned by
    ``raven.base.Client/build_msg`` changes. In that case, the tests pass, but
    the data is still dirty.  This is a dangerous situation to be in.
    """
    data = get_stack_trace_data_real()

    data['request'] = {
        'cookies': {},
        'data': VARS,
        'env': VARS,
        'headers': VARS,
        'method': 'GET',
        'query_string': '',
        'url': 'http://localhost/',
        'cookies': VARS,
    }
    return data


class SanitizePasswordsProcessorTest(TestCase):

    def _check_vars_sanitized(self, vars, proc):
        """
        Helper to check that keys have been sanitized.
        """
        self.assertTrue('foo' in vars)
        self.assertIn(vars['foo'], (
            VARS['foo'], "'%s'" % VARS['foo'], '"%s"' % VARS['foo'])
        )
        self.assertTrue('password' in vars)
        self.assertEquals(vars['password'], proc.MASK)
        self.assertTrue('the_secret' in vars)
        self.assertEquals(vars['the_secret'], proc.MASK)
        self.assertTrue('a_password_here' in vars)
        self.assertEquals(vars['a_password_here'], proc.MASK)
        self.assertTrue('api_key' in vars)
        self.assertEquals(vars['api_key'], proc.MASK)
        self.assertTrue('apiKey' in vars)
        self.assertEquals(vars['apiKey'], proc.MASK)

    def test_stacktrace(self, *args, **kwargs):
        """
        Check whether sensitive variables are properly stripped from stack-trace
        messages.
        """
        data = get_stack_trace_data_real()
        proc = SanitizePasswordsProcessor(Mock())
        result = proc.process(data)

        # data['exception']['values'][0]['stacktrace']['frames'][0]['vars']
        self.assertTrue('exception' in result)
        exception = result['exception']
        self.assertTrue('values' in exception)
        values = exception['values']
        stack = values[0]['stacktrace']
        self.assertTrue('frames' in stack)

        self.assertEquals(len(stack['frames']), 2)
        frame = stack['frames'][1]  # frame of will_throw_type_error()
        self.assertTrue('vars' in frame)
        self._check_vars_sanitized(frame['vars'], proc)

    def test_http(self):
        data = get_http_data()

        proc = SanitizePasswordsProcessor(Mock())
        result = proc.process(data)

        self.assertTrue('request' in result)
        http = result['request']

        for n in ('data', 'env', 'headers', 'cookies'):
            self.assertTrue(n in http)
            self._check_vars_sanitized(http[n], proc)

    def test_querystring_as_string(self):
        data = get_http_data()
        data['request']['query_string'] = 'foo=bar&password=hello&the_secret=hello'\
            '&a_password_here=hello&api_key=secret_key'

        proc = SanitizePasswordsProcessor(Mock())
        result = proc.process(data)

        self.assertTrue('request' in result)
        http = result['request']
        self.assertEquals(
            http['query_string'],
            'foo=bar&password=%(m)s&the_secret=%(m)s'
            '&a_password_here=%(m)s&api_key=%(m)s' % dict(m=proc.MASK))

    def test_querystring_as_string_with_partials(self):
        data = get_http_data()
        data['request']['query_string'] = 'foo=bar&password&baz=bar'

        proc = SanitizePasswordsProcessor(Mock())
        result = proc.process(data)

        self.assertTrue('request' in result)
        http = result['request']
        self.assertEquals(http['query_string'], 'foo=bar&password&baz=bar' % dict(m=proc.MASK))

    def test_sanitize_credit_card(self):
        proc = SanitizePasswordsProcessor(Mock())
        result = proc.sanitize('foo', '4242424242424242')
        self.assertEquals(result, proc.MASK)

    def test_sanitize_credit_card_amex(self):
        # AMEX numbers are 15 digits, not 16
        proc = SanitizePasswordsProcessor(Mock())
        result = proc.sanitize('foo', '424242424242424')
        self.assertEquals(result, proc.MASK)


class RemovePostDataProcessorTest(TestCase):
    def test_does_remove_data(self):
        data = get_http_data()
        data['request']['data'] = 'foo'

        proc = RemovePostDataProcessor(Mock())
        result = proc.process(data)

        self.assertTrue('request' in result)
        http = result['request']
        self.assertFalse('data' in http)


class RemoveStackLocalsProcessorTest(TestCase):
    def test_does_remove_data(self):
        data = get_stack_trace_data_real()
        proc = RemoveStackLocalsProcessor(Mock())
        result = proc.process(data)

        for value in result['exception']['values']:
            for frame in value['stacktrace']['frames']:
                self.assertFalse('vars' in frame)
