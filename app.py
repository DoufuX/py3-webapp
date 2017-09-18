import logging

logging.basicConfig(level=logging.INFO)

import asyncio
import json
import os
import time
from datetime import datetime

from aiohttp import web
from jinja2 import Environment, FileSystemLoader
from config import configs

import orm

from web_frame import add_routes, add_static


def init_jinja2(app, **kw):
    logging.info('init jinja2.....')

    options = dict(
        autoescape=kw.get('autoescape', True),
        block_start_string=kw.get('block_start_string', '{%'),
        block_end_string=kw.get('block_end_string', '%}'),
        variable_start_string=kw.get('variable_start_string', '{{'),
        variable_end_string=kw.get('variable_end_string', '}}'),
        auto_reload=kw.get('auto_reload', True)
    )

    path = kw.get('path', None)
    if path is None:
        path = os.path.join(os.path.dirname(
            os.path.abspath(__file__)), 'templates')
    logging.info('set jinja2 template path %s' % path)

    env = Environment(loader=FileSystemLoader(path), **options)

    filters = kw.get('filters', None)
    if filters is not None:
        for name, f in filters.items():
            env.filters[name] = f

    app['__templating__'] = env


# -------------------------------------拦截器middlewares设置-------------------------------------


# 为啥要有两个asyncio.coroutine
@asyncio.coroutine
def logger_factory(app, handler):
    @asyncio.coroutine
    def logger(request):
        logging.info('Request information:')
        logging.info('Request: %s,%s' % (request.method, request.path))
        logging.info(request)
        logging.info(handler)
        return (yield from handler(request))

    return logger


@asyncio.coroutine
def data_factory(app, handler):
    @asyncio.coroutine
    def parse_data(request):
        if request.method == 'POST':
            if request.content_type.startswith('application/json'):
                request.__data__ = yield from request.json()
                logging.info('request json : %s' % str(request.__data__))
            elif request.content_type.startswith('application/x-www-form-urlencoded'):
                request.__data__ = yield from request.post()
                logging.info('request form : %s' % str(request.__data__))
        return (yield from handler(request))

    return parse_data


# @asyncio.coroutine
# def auth_factory(app, handler):
#     @asyncio.coroutine
#     def auth(request):
#         logging.info('check user: %s %s' % (request.method, request.path))
#         request.__user__ = None
#         cookie_str = request.cookies.get(COOKIE_NAME)
#         if cookie_str:
#             user = yield from cookie2user(cookie_str)
#             if user:
#                 logging.info('set current user:%s' % user.email)
#                 request.__user__ = user
#         if request.path.startswith('/manage/') and (request.__user__ is None or not request.__user__.admin):
#             return web.HTTPFound('/signin')
#
#         return (yield from handler(request))
#
#     return auth


# 通过response_factory 将处理函数的返回值转换成 Response对象
@asyncio.coroutine
def response_factory(app, handler):
    @asyncio.coroutine
    def response(request):
        logging.info('Response handler...')
        r = yield from handler(request)
        logging.debug('r = %s' % str(r))
        if isinstance(r, web.StreamResponse):
            return r
        if isinstance(r, bytes):
            resp = web.Response(body=r)
            resp.content_type = 'application/octet-stream'
            return resp
        if isinstance(r, str):
            if r.startswith('redirect:'):  # 重定向处理
                return web.HTTPFound(r[9:])  # 转入别的网站
            resp = web.Response(body=r.encode('utf-8'))
            resp.content_type = 'text/html;charset=utf-8'
            return resp
        if isinstance(r, dict):
            template = r.get('__template__')
            if template is None:  # 序列化json ， 传递和数据
                resp = web.Response(body=json.dumps(
                    r, ensure_ascii=False, default=lambda o: o.__dict__).encode('utf-8')
                                    )
                resp.content_type = 'application/json;charset=utf-8'
                return resp
            else:
                # r['__user__'] = request.__user__
                # jinja2模块
                resp = web.Response(body=app['__templating__'].get_template(
                    template).render(**r).encode('utf-8'))
                resp.content_type = 'text/html;charset=utf-8'
                return resp
        if isinstance(r, int) and r >= 100 and r < 600:
            return web.Response(r)
        if isinstance(r, tuple) and len(r) == 2:
            t, m = r
            if isinstance(t, int) and t >= 100 and t < 600:
                return web.Response(status=t, text=str(m))
        resp = web.Response(body=str(r).encode('utf-8'))
        resp.content_type = 'text/plain;charset=utf-8'
        return resp

    return response


def datetime_filter(t):
    delta = int(time.time() - t)
    if delta < 60:
        return u'1分钟前'
    if delta < 3600:
        return u'%s分钟前' % (delta // 60)
    if delta < 86400:
        return u'%s小时前' % (delta // 3600)
    if delta < 604800:
        return u'%s天前' % (delta // 86400)
    dt = datetime.fromtimestamp(t)
    return u'%s年%s月%s日' % (dt.year, dt.month, dt.day)


@asyncio.coroutine
def init(loop):
    yield from orm.create_pool(loop=loop, **configs.db)
    app = web.Application(loop=loop, middlewares=[
        logger_factory, response_factory
    ])
    init_jinja2(app, filters=dict(datetime=datetime_filter))
    add_routes(app, 'handlers')
    add_static(app)
    srv = yield from loop.create_server(app.make_handler(), '127.0.0.1', 9000)
    logging.info('server started at http://127.0.0.1:9000..')
    return srv


loop = asyncio.get_event_loop()
loop.run_until_complete(init(loop))
loop.run_forever()