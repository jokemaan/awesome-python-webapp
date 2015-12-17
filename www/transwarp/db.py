#! /usr/bin/env python
# -*- coding:utf-8 -*-

__author__="Nina"

'''
Database operation module
'''

import time,uuid,functools,threading,logging

#Dict object:

class Dict(dict):
    '''
    simple dict but support access as x.y style
    >>> d1=Dict()
    >>> d1['x']=100
    >>> d1.x
    100
    >>> d1.y=200
    >>> d1['y']
    200
    >>> d2=Dict(a=1,b=2,c='3')
    >>> d2.c
    '3'
    >>> d1['empty']
    >>> d2['empty']
    Traceback (most recent call last):
        ...
    KeyError: 'empty'
    >>> d2.empty
    Traceback (most recent call last):
    ...
    AttributeError: 'Dict' object has no attribute 'empty'
    >>> d3=Dict(('a','b','c'),(1,2,3))
    >>> d3.a
    1
    >>> d3.b
    2
    >>> d3.c
    3
    '''
    def __init__(self,names=(),values=(),**kw):
        super(Dict,self).__init__(**kw)
        for k,v in zip(names,values):
            self[k]=v

    def __getattr__(self,key):
        try:
            return self[key]
        except KeyError:
            raise AttributeError(r"'Dict' object has no attribute '%s'"%key)

    def __setattr__(self,key,value):
        self[key]=value

def next_id(t=None):
    '''
    Return next id as 50-char string.

    Args:
        t:unix timestamp,default to None and using time.time().
    '''
    if t is None:
        t=time.time()
    return '%015d'%s000 %(int(t*1000),uuid.uuid4().hex)

def _profiling(start,sql=''):
    t=time.time()-start
    if t>0.1:
        logging.warning('[PROFILING] [DB] %s:%s'%(t,sql))
    else:
        logging.info('[PROFILING [DB]%s:%s' %(t,sql))

class DBError(Exception):
    pass

class MultiColumnsError(DBError):
    pass

class _LazyConnection(object):

    def __init__(self):
        self.connection=None

    def cursor(self):
        if self.connection is None:
            connection=engine.connect()
            logging.warning('open connection <%s>...'%hex(id(connection)))
            self.connection=connection
        return self.connection.cursor()

    def commmit(self):
        self.connection.commit()

    def rollback(self):
        self.connection.rollback()

    def cleanup(self):
        if self.connection:
            connection=self.connection
            self.connection=None
            logging.info('close connection <%s>...' %hex(id(connection)))
            connection.close()

class _DbCtx(threading.local):
    '''
    Thread local object that holds connection info.
    '''
    def __init__(self):
        self.connection=None
        self.transactions=0

    def is_init(self):
        return not self.connection is  None

    def init(self):
        logging.info('open lazy connection...')
        self.connection=_LazyConnection()
        self.transactions=0

    def cleanup(self):
        self.connection.cleanup()
        self.connection=None

    def cursor(self):
        '''
        Return cursor
        '''
        return self.connection.cursor()


# thread-local db context:
_db_ctx = _DbCtx()

#global engine object:
engine=None

class _Engine(object):

    def __init__(self,connect):
        self._connect=connect

    def connect(self):
        return self._connect()

def create_engine(user,password,database,host='127.0.0.1',port=3306,**kw):
    import mysql.connector
    global  engine
    if engine is not None:
        raise DBError('Engine is already initialized')
    params=dict(user=user,password=password,database=database,host=host,port=port)
    defaults=dict(use_unicode=True,charset='utf8',collation='utf8_general_ci',autocommit=False)
    for k,v in defaults.iteritems():
        params[k]=kw.pop(k,v)
    params.update(kw)
    params['buffered']=True
    engine=_Engine(lambda :mysql.connector.connect(**params))
    #test connction ...
    logging.info('Init mysql engine <%s> ok.'%hex(id(engine)))

class _ConnectionCtx(object):
    '''
    _ConnectionCtx object that can open and close connection context.
    _ConnectionCtx object can be nested and only the outer connection has effect.


    with connection():
        pass
        with connection():
            pass
    '''

    #定义了__enter__()和__exit__()的对象可以用于with语句，确保任何情况下__exit__()方法可以被调用
    def __enter__(self):
        global _db_ctx
        self.should_cleanup=False
        if not _db_ctx.is_init():
            _db_ctx.init()
            self.should_cleanup= True
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _db_ctx
        if self.should_cleanup:
            _db_ctx.cleanup()

def connection():
    '''
    Return _ConnectionCtx object that can be used by 'with' statement:

    with connection():
        pass
    '''
    return  _ConnectionCtx()

def with_connection(func):
    '''
    Decorator for reuse connection

    @with_connection
    def foo(*args,**kw):
        f1()
        f2()
        f3()
    '''
    @functools.wraps(func)
    def _wrapper(*args,**kw):
        with _ConnectionCtx():
            return func(*args,**kw)

    return _wrapper

class _TransactionCtx(object):
    '''
    _TransactionCtx object that can handle transactions.

    with _TransactionCtx():
        pass
    '''

    def __enter__(self):
        global _db_ctx
        self.should_close_conn=False
        if not _db_ctx.is_init():
            #need open a connection first
            _db_ctx.init()
            self.should_close_conn=True
        _db_ctx.transactions=_db_ctx.transactions+1
        logging.info('begin transaction...'if _db_ctx.transactions==1 else 'join current transaction...')
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        global _db_ctx
        _db_ctx.transactions=_db_ctx.transactions-1
        try:
            if _db_ctx.transactions==0:
                if exc_type is None:
                    self.commit()
                else:
                    self.rollback()
        finally:
            if self.should_close_conn:
                _db_ctx.cleanup()

    def commit(self):
        global _db_ctx
        logging.info('commit transaction...')
        try:
            _db_ctx.connection.commit()
            logging.info('commit ok.')
        except:
            logging.warning('commit failed,try rollback...')
            _db_ctx.connection.rollback()
            logging.warning('rollback ok.')
            raise

    def rollback(self):
        global _db_ctx
        logging.warning('rollback transaction...')
        _db_ctx.connection.rollback()
        logging.info('rollback ok.')

def transaction():
    '''
    Create a transaction object so can use with statement:

    with transaction():
        pass

    >>>
    '''
    return _TransactionCtx()

def with_transaction():
    '''
    A decorator that makes function around transaction.

    >>>
    '''
    @functools.wraps(func)
    def _wrapper(*args,**kw):
        _start=time.time()
        with _TransactionCtx():
            return func(*args,**kw)
        _profiling(_start)

    return _wrapper

def _select(sql,first,*args):
    'execute select SQL and return unique result or list results.'
    global _db_ctx
    cursor=None
    sql=sql.replace('?','%s')
    logging.info('SQL: %s,ARGS: %s'%(sql,args))
    try:
        cursor=_db_ctx.connection.cursor()
        cursor.execute(sql,args)
        if cursor.description:
            names=[x[0] for x in cursor.description]
        if first:
            values=cursor.fetchone()
            if not values:
                return None
            return Dict(names,values)
        return  [Dict(names,x) for x in cursor.fetchall()]
    finally:
        if cursor:
            cursor.close()

#本质上，decorator就是一个返回函数的高阶函数
#with_connection装饰器的作用是把_ConnectionCtx的作用域用到一个函数调用上
@with_connection
def select_one(sql,*args):
    '''
    Execute select SQL and expected one result.
    If no result found,return None.
    If multiple results found,the first one returned.


    >>> u1=
    '''
    return  _select(sql,True,*args)


@with_connection
def select_int(sql,*args):
    '''
    Execute select SQL and expected one int and one int result.

    >>> n=update('delete from user')
    >>> u1=
    '''
    d=_select(sql,True,*args)
    if len(d)!=1:
        raise MultiColumnsError('Expect only one column.')
    return d.values()[0]

@with_connection
def select(sql,*args):
    '''
    Execute select SQL and return list or empty list if no result.

    >>> u1=dict()
    '''
    return _select(sql,False,*args)

@with_connection
def _update(sql,*args):
    global _db_ctx
    cursor=None
    sql=sql.replace('?','%s')
    logging.info('SQL:%s,ARGS:%s' %(sql,args))
    try:
        cursor=_db_ctx.connection.cursor()
        cursor.execute(sql,args)
        r=cursor.rowcount
        if _db_ctx.transactions==0:
            #no transaction environment
            logging.info('auto commit')
            _db_ctx.connection.commit()
        return r
    finally:
        if cursor:
            cursor.close()

def insert(table,**kw):
    '''
    Executl insert SQL

    >>> u1=dict(id=200,name='Bob',email='bob@test.org',passwd='himan',last_modified=time.time())
    >>> inser('user',**u1)
    1
    >>> u2=
    '''
    cols,args=zip(*kw.iteritems())
    sql='insert into `%s` (%s) values (%s)' %(table,','.join(['`%s`'%col for col in cols]),','.join(['?'for i in range(len(cols))]))
    return _update(sql,*args)

def update(sql,*args):
    r'''
    Execute update SQL.

    >>> u1=

    '''
    return  _update(sql,*args)

if __name__=='__main__':
    logging.basicConfig(level=logging.DEBUG)
    create_engine('www-data','www-data','test')
    update('drop table if exist user')
    update('create table user(id int primary key,name text,email text,passwd text,last_modified real)')
    import doctest
    doctest.testmod()