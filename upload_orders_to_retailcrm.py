import os
import json
import time
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

API_URL = os.getenv("RETAILCRM_API_URL", "").rstrip("/")
API_KEY = os.getenv("RETAILCRM_API_KEY", "").strip()
SITE = os.getenv("RETAILCRM_SITE", "").strip()

MOCK_ORDERS_PATH = Path("mock_orders_new.json")

CATALOG_PRICES = {
    "nova-lift": 22000,
    "nova-classic": 15000,
    "nova-shape": 12000,
    "nova-body": 35000,
    "nova-fit": 18000,
    "nova-slim": 28000,
}


class RetailCRMError(RuntimeError):
    pass


INVALID_ORDER_TYPES = set()


def ensure_env() -> None:
    if not API_URL:
        raise RetailCRMError("Не задан RETAILCRM_API_URL в .env")
    if not API_KEY:
        raise RetailCRMError("Не задан RETAILCRM_API_KEY в .env")


def api_get(path: str, params: dict | None = None, timeout: int = 30) -> dict:
    url = f"{API_URL}{path}"
    headers = {"X-API-KEY": API_KEY}
    resp = requests.get(url, params=params or {}, headers=headers, timeout=timeout)

    try:
        data = resp.json()
    except Exception:
        raise RetailCRMError(
            f"GET {path} вернул не JSON. HTTP {resp.status_code}. Тело:\n{resp.text[:1000]}"
        )

    if resp.status_code >= 400:
        raise RetailCRMError(
            f"GET {path} ошибка HTTP {resp.status_code}: {json.dumps(data, ensure_ascii=False)}"
        )

    return data


def api_post_form(path: str, payload: dict, timeout: int = 30) -> tuple[int, dict]:
    url = f"{API_URL}{path}"
    headers = {"Content-Type": "application/x-www-form-urlencoded; charset=utf-8"}
    resp = requests.post(url, data=payload, headers=headers, timeout=timeout)

    try:
        data = resp.json()
    except Exception:
        data = {"raw": resp.text}

    return resp.status_code, data


def safe_get_nested(data: dict, *keys, default=None):
    cur = data
    for key in keys:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
        if cur is None:
            return default
    return cur


def extract_possible_article_sources(offer: dict, product: dict) -> list[tuple[str, str]]:
    candidates: list[tuple[str, str]] = []

    for field_name in ("article", "sku", "xmlId", "externalId", "name"):
        value = offer.get(field_name)
        if value:
            candidates.append((f"offer.{field_name}", str(value).strip()))

    for prop in offer.get("properties", []) or []:
        name = str(prop.get("name", "")).strip().lower()
        code = str(prop.get("code", "")).strip().lower()
        value = prop.get("value")
        if not value:
            continue

        if name in ("артикул", "article", "sku") or code in ("article", "sku", "artikul"):
            candidates.append(("offer.properties", str(value).strip()))

    for prop in product.get("properties", []) or []:
        name = str(prop.get("name", "")).strip().lower()
        code = str(prop.get("code", "")).strip().lower()
        value = prop.get("value")
        if not value:
            continue

        if name in ("артикул", "article", "sku") or code in ("article", "sku", "artikul"):
            candidates.append(("product.properties", str(value).strip()))

    for field_name in ("article", "sku", "xmlId", "externalId"):
        value = product.get(field_name)
        if value:
            candidates.append((f"product.{field_name}", str(value).strip()))

    seen = set()
    unique = []
    for source, value in candidates:
        key = (source, value)
        if key not in seen and value:
            seen.add(key)
            unique.append((source, value))

    return unique


def extract_price(offer: dict, product: dict, article: str | None = None) -> float:
    possible_prices = [
        offer.get("price"),
        offer.get("purchasePrice"),
        product.get("price"),
        safe_get_nested(offer, "prices", "base"),
        safe_get_nested(product, "prices", "base"),
    ]

    for value in possible_prices:
        if value is None:
            continue
        try:
            return float(value)
        except Exception:
            pass

    if article and article in CATALOG_PRICES:
        return float(CATALOG_PRICES[article])

    return 0.0


def debug_credentials() -> None:
    print("=" * 70)
    print("ПРОВЕРКА API-КЛЮЧА")
    print("=" * 70)
    try:
        data = api_get("/api/v5/credentials")
        print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])
    except Exception as e:
        print(f"credentials недоступен или не поддерживается в этом аккаунте: {e}")
    print()


def fetch_offer_map(site_value: str | None) -> tuple[dict, dict]:
    offer_map: dict[str, dict] = {}
    page = 1

    stats = {
        "site_used": site_value or "",
        "pages": 0,
        "products_total": 0,
        "offers_total": 0,
        "offers_with_article": 0,
        "offers_with_id": 0,
        "mapped_total": 0,
        "first_page_sample": None,
    }

    while True:
        params = {"page": page, "limit": 100}
        if site_value:
            params["site"] = site_value

        data = api_get("/api/v5/store/products", params=params)
        if not data.get("success", False):
            raise RetailCRMError(
                f"Ошибка получения товаров: {json.dumps(data, ensure_ascii=False)}"
            )

        products = data.get("products", []) or []
        stats["pages"] += 1

        if page == 1:
            stats["first_page_sample"] = products[:2]

        if not products:
            break

        stats["products_total"] += len(products)

        for product in products:
            offers = product.get("offers", []) or []
            stats["offers_total"] += len(offers)

            for offer in offers:
                offer_id = offer.get("id")
                if offer_id:
                    stats["offers_with_id"] += 1

                article_candidates = extract_possible_article_sources(offer, product)
                if article_candidates:
                    stats["offers_with_article"] += 1

                chosen_article = None
                chosen_source = None

                for source_name, candidate in article_candidates:
                    candidate = candidate.strip()
                    if candidate:
                        chosen_article = candidate
                        chosen_source = source_name
                        break

                if chosen_article and offer_id:
                    offer_map[chosen_article] = {
                        "id": offer_id,
                        "name": offer.get("name") or product.get("name") or f"Offer #{offer_id}",
                        "price": extract_price(offer, product, chosen_article),
                        "article_source": chosen_source,
                    }
                    stats["mapped_total"] += 1

        pagination = data.get("pagination", {}) or {}
        total_pages = int(pagination.get("totalPageCount", 1) or 1)
        if page >= total_pages:
            break

        page += 1
        time.sleep(0.15)

    return offer_map, stats


def print_catalog_debug(stats: dict, offer_map: dict) -> None:
    print("=" * 70)
    print(f"ДИАГНОСТИКА КАТАЛОГА (site='{stats['site_used']}')")
    print("=" * 70)
    print(f"Страниц обработано:           {stats['pages']}")
    print(f"Товаров получено:             {stats['products_total']}")
    print(f"Offers найдено:               {stats['offers_total']}")
    print(f"Offers с каким-то артикулом:  {stats['offers_with_article']}")
    print(f"Offers с внутренним id:       {stats['offers_with_id']}")
    print(f"Успешно сопоставлено:         {stats['mapped_total']}")
    print(f"Итоговых ключей в offer_map:  {len(offer_map)}")

    if offer_map:
        print("\nПримеры сопоставлений:")
        for i, (art, info) in enumerate(offer_map.items(), start=1):
            print(
                f"  {i:>2}. {art} -> offer_id={info['id']}, "
                f"name={info['name']}, price={info['price']}, source={info['article_source']}"
            )
            if i >= 15:
                break
    else:
        sample = stats.get("first_page_sample")
        if sample:
            print("\noffer_map пуст. Первые товары из API:")
            print(json.dumps(sample, ensure_ascii=False, indent=2)[:5000])
        else:
            print("\nAPI не вернул ни одного товара.")

    print()


def get_best_offer_map() -> dict:
    attempts = []

    if SITE:
        attempts.append(("with_site", SITE))
    attempts.append(("without_site", ""))

    best_map = {}

    for mode, site_value in attempts:
        print(f"\nЗагружаю каталог: mode={mode}, site='{site_value}'")
        try:
            offer_map, stats = fetch_offer_map(site_value or None)
            print_catalog_debug(stats, offer_map)

            if len(offer_map) > len(best_map):
                best_map = offer_map

            if offer_map:
                return offer_map

        except Exception as e:
            print(f"Ошибка при загрузке каталога ({mode}): {e}")

    return best_map


def load_mock_orders() -> list:
    if not MOCK_ORDERS_PATH.exists():
        raise FileNotFoundError(f"Файл {MOCK_ORDERS_PATH} не найден")

    with MOCK_ORDERS_PATH.open("r", encoding="utf-8") as f:
        data = json.load(f)

    return data if isinstance(data, list) else [data]


def normalize_phone(value: str | None) -> str | None:
    if not value:
        return value
    return str(value).strip()


def should_send_order_type(order_type: str | None) -> bool:
    if not order_type:
        return False
    if order_type in INVALID_ORDER_TYPES:
        return False
    return True


def map_order(mock: dict, index: int, offer_map: dict, include_order_type: bool = True) -> dict:
    mapped_items = []
    total_summ = 0.0

    for item in mock.get("items", []) or []:
        ext_id = str(item.get("externalId", "") or "").strip()
        qty_raw = item.get("quantity", 1)

        try:
            qty = int(qty_raw)
        except Exception:
            qty = 1

        catalog = offer_map.get(ext_id)

        if catalog:
            price = float(catalog["price"])
            offer_field = {"id": catalog["id"]}
        else:
            print(f"  ⚠ Артикул '{ext_id}' не найден в каталоге — отправляю без offer.id")
            raw_price = item.get("initialPrice", 0)
            try:
                price = float(raw_price)
            except Exception:
                price = float(CATALOG_PRICES.get(ext_id, 0))

            offer_field = {
                "name": item.get("productName") or item.get("name") or f"Товар {ext_id or ''}".strip()
            }

        total_summ += qty * price
        mapped_items.append(
            {
                "offer": offer_field,
                "quantity": qty,
                "initialPrice": price,
            }
        )

    order = {
        "number": mock.get("number") or f"IMPORT-{index:04d}",
        "firstName": mock.get("firstName") or "",
        "lastName": mock.get("lastName") or "",
        "phone": normalize_phone(mock.get("phone")),
        "email": mock.get("email") or "",
        "orderMethod": mock.get("orderMethod") or "shopping-cart",
        "status": mock.get("status") or "new",
        "items": mapped_items,
        "totalSumm": total_summ,
    }

    if SITE:
        order["site"] = SITE

    delivery = mock.get("delivery")
    if delivery:
        order["delivery"] = delivery

    custom_fields = mock.get("customFields")
    if custom_fields:
        order["customFields"] = custom_fields

    order_type = mock.get("orderType")
    if include_order_type and should_send_order_type(order_type):
        order["orderType"] = order_type

    return order


def create_order(order: dict) -> tuple[int, dict]:
    payload = {
        "apiKey": API_KEY,
        "order": json.dumps(order, ensure_ascii=False),
    }

    if SITE:
        payload["site"] = SITE

    return api_post_form("/api/v5/orders/create", payload)


def is_invalid_order_type_error(data: dict) -> tuple[bool, str | None]:
    errors = data.get("errors") if isinstance(data, dict) else None
    if not isinstance(errors, dict):
        return False, None

    msg = errors.get("orderType")
    if not msg:
        return False, None

    if "does not exist" in str(msg):
        return True, str(msg)

    return False, str(msg)


def send_order_with_retry(mock: dict, index: int, offer_map: dict) -> tuple[bool, dict | None, dict]:
    order = map_order(mock, index, offer_map, include_order_type=True)

    print("Отправляю заказ:")
    print(json.dumps(order, ensure_ascii=False, indent=2)[:4000])

    status_code, data = create_order(order)

    ok = status_code in (200, 201) and isinstance(data, dict) and data.get("success")
    if ok:
        return True, data, order

    invalid_type, _ = is_invalid_order_type_error(data)
    if invalid_type:
        bad_type = mock.get("orderType")
        if bad_type:
            INVALID_ORDER_TYPES.add(str(bad_type))
            print(f"  ⚠ Тип заказа '{bad_type}' отсутствует в CRM. Повторяю без orderType.")

            order_retry = map_order(mock, index, offer_map, include_order_type=False)
            print("Повторная отправка заказа без orderType:")
            print(json.dumps(order_retry, ensure_ascii=False, indent=2)[:4000])

            status_code_retry, data_retry = create_order(order_retry)
            ok_retry = (
                status_code_retry in (200, 201)
                and isinstance(data_retry, dict)
                and data_retry.get("success")
            )
            if ok_retry:
                return True, data_retry, order_retry

            data_retry["_http_status"] = status_code_retry
            return False, data_retry, order_retry

    data["_http_status"] = status_code
    return False, data, order


def main() -> None:
    ensure_env()

    print(f"API_URL: {API_URL}")
    print(f"SITE:    {SITE or '(не задан)'}")
    print()

    debug_credentials()

    offer_map = get_best_offer_map()
    if not offer_map:
        print("❌ Не удалось построить карту товаров.")
        print("Заказы всё равно будут отправляться, но без привязки по offer.id.\n")

    mocks = load_mock_orders()
    print(f"Загружено заказов из файла: {len(mocks)}\n")

    success_ids = []
    errors = []

    for idx, mock in enumerate(mocks, start=1):
        print("-" * 70)
        print(f"Заказ #{idx}")

        ok, data, sent_order = send_order_with_retry(mock, idx, offer_map)

        if ok:
            order_id = data.get("id")
            success_ids.append(order_id)
            print(
                f"✅ Успех: {sent_order.get('firstName', '')} {sent_order.get('lastName', '')} "
                f"-> id={order_id}"
            )
        else:
            errors.append((idx, mock.get("phone"), data))
            print(f"❌ Ошибка HTTP {data.get('_http_status', 'unknown')}")
            print(json.dumps(data, ensure_ascii=False, indent=2)[:4000])

        time.sleep(0.15)

    print()
    print("=" * 70)
    print("ИТОГ")
    print("=" * 70)
    print(f"Всего заказов: {len(mocks)}")
    print(f"Успешно:       {len(success_ids)}")
    print(f"Ошибок:        {len(errors)}")

    if INVALID_ORDER_TYPES:
        print("\nНевалидные типы заказов, автоматически исключённые из отправки:")
        for value in sorted(INVALID_ORDER_TYPES):
            print(f"  - {value}")

    if success_ids:
        print("\nСозданные ID заказов:")
        for order_id in success_ids:
            print(f"  - {order_id}")

    if errors:
        print("\nПроблемные заказы:")
        for idx, phone, data in errors:
            print(f"  #{idx} phone={phone} -> {json.dumps(data, ensure_ascii=False)[:1000]}")


if __name__ == "__main__":
    main()