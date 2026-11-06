"""Public catalog: read-only until Cardinal's authenticated checkout bridge is verified.

Catalog snapshots must be published by a trusted backend, never by a browser.
No demo price is ever offered as a purchasable price.
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

BASE = Path(__file__).resolve().parent
STATIC = BASE / 'static'
SNAPSHOT = Path(os.getenv('GIFTS_CATALOG_SNAPSHOT', str(BASE / 'catalog_live.json')))
USERNAME = re.compile(r'^@?[A-Za-z][A-Za-z0-9_]{4,31}$')
app = FastAPI(title='FunPay Gifts Catalog', docs_url=None, redoc_url=None)


def snapshot():
    try:
        data = json.loads(SNAPSHOT.read_text(encoding='utf-8'))
        if not isinstance(data, dict) or not isinstance(data.get('items'), list):
            raise ValueError('invalid catalog snapshot')
        return data
    except (OSError, ValueError, TypeError):
        return {'items': [], 'sales_enabled': False, 'updated_at': None}


def public_items(data):
    result = []
    for item in data['items']:
        if not isinstance(item, dict) or item.get('available') is not True:
            continue
        price = item.get('price_rub')
        if type(price) is not int or price <= 0:
            continue
        item_id = str(item.get('id', ''))
        if not item_id or len(item_id) > 128:
            continue
        result.append({
            'id': item_id, 'name': str(item.get('name', ''))[:160],
            'model': str(item.get('model', ''))[:120],
            'background': str(item.get('background', ''))[:120],
            'symbol': str(item.get('symbol', ''))[:120],
            'image': item.get('image') if isinstance(item.get('image'), str) and item['image'].startswith('https://') else '',
            'price_rub': price,
        })
    return result


@app.get('/')
def home():
    return FileResponse(STATIC / 'index.html', media_type='text/html')


@app.get('/static/{filename}')
def static_file(filename: str):
    if filename not in {'site.css', 'site.js'}:
        raise HTTPException(404)
    return FileResponse(STATIC / filename)


@app.get('/api/catalog')
def catalog():
    data = snapshot()
    return {'items': public_items(data), 'sales_enabled': bool(data.get('sales_enabled', False)) and os.getenv('GIFTS_CHECKOUT_ENABLED') == '1', 'updated_at': data.get('updated_at')}


class CartLine(BaseModel):
    id: str = Field(min_length=1, max_length=128)


class Checkout(BaseModel):
    username: str = Field(min_length=5, max_length=33)
    items: list[CartLine] = Field(min_length=1, max_length=50)


@app.post('/api/checkout')
def checkout(request: Checkout):
    if not USERNAME.fullmatch(request.username):
        raise HTTPException(422, 'Неверный Telegram username')
    if len({x.id for x in request.items}) != len(request.items):
        raise HTTPException(422, 'Повторяющиеся подарки в корзине')
    data = snapshot()
    available = {x['id']: x for x in public_items(data)}
    if any(x.id not in available for x in request.items):
        raise HTTPException(409, 'Состав или доступность корзины изменились')
    # Never create fake orders or redirect to a generic FunPay page.
    # Checkout will only be enabled after authenticated Cardinal bridge,
    # current Portals price/recipient/balance validation and lot-ID verification.
    raise HTTPException(503, 'Оформление временно недоступно. Персональные лоты ещё не подключены.')


@app.get('/health')
@app.get('/healthz')
def health():
    return {'ok': True, 'checkout_ready': False}
