from contextlib import contextmanager
from functools import wraps
import logging
import os
import unittest

from peewee import *


logger = logging.getLogger('peewee')

if os.environ.get('VERBOSE'):
    logger.addHandler(logging.StreamHandler())
    logger.setLevel(logging.DEBUG)


def db_loader(engine, name='peewee_test', **params):
    engine_aliases = {
        SqliteDatabase: ['sqlite', 'sqlite3'],
        MySQLDatabase: ['mysql'],
        PostgresqlDatabase: ['postgres', 'postgresql'],
    }
    engine_map = dict((alias, db) for db, aliases in engine_aliases.items()
                      for alias in aliases)
    if engine.lower() not in engine_map:
        raise Exception('Unsupported engine: %s.' % engine)
    db_class = engine_map[engine.lower()]
    if db_class is SqliteDatabase and not name.endswith('.db'):
        name = '%s.db' % name
    return engine_map[engine](name, **params)


def get_in_memory_db(**params):
    return db_loader('sqlite3', ':memory:', **params)


BACKEND = os.environ.get('PEEWEE_TEST_BACKEND') or 'sqlite'

db = db_loader(BACKEND, 'peewee_test')


class TestModel(Model):
    class Meta:
        database = db


def __sql__(q, **state):
    return Context(**state).sql(q).query()


class QueryLogHandler(logging.Handler):
    def __init__(self, *args, **kwargs):
        self.queries = []
        logging.Handler.__init__(self, *args, **kwargs)

    def emit(self, record):
        self.queries.append(record)


class BaseTestCase(unittest.TestCase):
    def setUp(self):
        self._qh = QueryLogHandler()
        logger.setLevel(logging.DEBUG)
        logger.addHandler(self._qh)

    def tearDown(self):
        logger.removeHandler(self._qh)

    def assertIsNone(self, value):
        self.assertTrue(value is None, '%r is not None' % value)

    def assertIsNotNone(self, value):
        self.assertTrue(value is not None, '%r is None' % value)

    def assertSQL(self, query, sql, params=None, **state):
        qsql, qparams = __sql__(query, **state)
        self.assertEqual(qsql, sql)
        if params is not None:
            self.assertEqual(qparams, params)

    @property
    def history(self):
        return self._qh.queries

    @contextmanager
    def assertQueryCount(self, num):
        qc = len(self.history)
        yield
        self.assertEqual(len(self.history) - qc, num)


class DatabaseTestCase(BaseTestCase):
    database = db

    def setUp(self):
        self.database.connect()
        super(DatabaseTestCase, self).setUp()

    def tearDown(self):
        super(DatabaseTestCase, self).tearDown()
        self.database.close()

    def execute(self, sql, params=None):
        return self.database.execute_sql(sql, params)


class ModelTestCase(DatabaseTestCase):
    database = db
    requires = None

    def setUp(self):
        super(ModelTestCase, self).setUp()
        self._db_mapping = {}
        # Override the model's database object with test db.
        if self.requires:
            for model in self.requires:
                self._db_mapping[model] = model._meta.database
                model._meta.set_database(self.database)
            self.database.drop_tables(self.requires, safe=True)
            self.database.create_tables(self.requires)

    def tearDown(self):
        # Restore the model's previous database object.
        if self.requires:
            self.database.drop_tables(self.requires, safe=True)
            for model in self.requires:
                model._meta.set_database(self._db_mapping[model])

        super(ModelTestCase, self).tearDown()


def requires_models(*models):
    def decorator(method):
        @wraps(method)
        def inner(self):
            _db_mapping = {}
            for model in models:
                _db_mapping[model] = model._meta.database
                model._meta.set_database(self.database)
            self.database.drop_tables(models, safe=True)
            self.database.create_tables(models)

            try:
                method(self)
            finally:
                self.database.drop_tables(models)
                for model in models:
                    model._meta.set_database(_db_mapping[model])
        return inner
    return decorator
