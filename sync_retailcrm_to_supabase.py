import os
import json
import time
from typing import Any

import requests
from dotenv import load_dotenv

load_dotenv()

RETAIL_API_URL = os.getenv("RETAILCRM_API_URL", "").rstrip("/")
RETAIL_API_KEY = os.getenv("RETAILCRM_API_KEY", "").strip()
RETAIL_SITE = os.getenv("RETAILCRM_SITE", "").strip()

SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
SUPABASE_KEY = os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()

REQUEST_TIMEOUT = 30
RETAIL_LIMIT = 100
SLEEP_BETWEEN_REQUESTS = 0.15

CUSTOMERS_TABLE = "customers"
ORDERS_TABLE = "orders"
ORDER_ITEMS_TABLE = "order_items"


if not RETAIL_API_URL or not RETAIL_API_KEY:
    raise RuntimeError("Нужно задать RETAILCRM_API_URL и RETAILCRM_API_KEY в .env")

if not SUPABASE_URL or not SUPABASE_KEY:
    raise RuntimeError("Нужно задать SUPABASE_URL и SUPABASE_SERVICE_ROLE_KEY в .env")


def retail_get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
    url = f"{RETAIL_API_URL}{path}"
    query = dict(params or {})
    query["apiKey"] = RETAIL_API_KEY

    response = requests.get(url, params=query, timeout=REQUEST_TIMEOUT)

    try:
        data = response.json()
    except Exception:
        raise RuntimeError(
            f"RetailCRM вернул не JSON. HTTP {response.status_code}. "
            f"Body: {response.text[:1000]}"
        )

    if not response.ok:
        raise RuntimeError(
            f"RetailCRM HTTP {response.status_code}: "
            f"{json.dumps(data, ensure_ascii=False)}"
        )

    if not data.get("success"):
        raise RuntimeError(
            f"RetailCRM success=false: {json.dumps(data, ensure_ascii=False)}"
        )

    return data


def fetch_orders_page(page: int, limit: int = RETAIL_LIMIT) -> dict[str, Any]:
    params: dict[str, Any] = {
        "page": page,
        "limit": limit,
    }

    if RETAIL_SITE:
        params["site"] = RETAIL_SITE

    return retail_get("/api/v5/orders", params=params)


def safe_str(value: Any) -> str | None:
    if value is None:
        return None
    return str(value)


def safe_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except Exception:
        return None


def safe_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except Exception:
        return None


def extract_customer(order: dict[str, Any]) -> dict[str, Any]:
    customer = order.get("customer") or {}

    customer_external_id = (
        customer.get("id")
        or customer.get("externalId")
        or customer.get("external_id")
    )

    first_name = customer.get("firstName") or order.get("firstName")
    last_name = customer.get("lastName") or order.get("lastName")
    patronymic = customer.get("patronymic") or order.get("patronymic")

    full_name = " ".join(
        [x for x in [first_name, last_name, patronymic] if x]
    ).strip() or None

    phone = None
    phones = customer.get("phones") or []
    if isinstance(phones, list) and phones:
        first_phone = phones[0]
        if isinstance(first_phone, dict):
            phone = first_phone.get("number") or first_phone.get("phone")

    if not phone:
        phone = customer.get("phone") or order.get("phone")

    email = customer.get("email") or order.get("email")
    if not email:
        emails = customer.get("emails") or []
        if isinstance(emails, list) and emails:
            first_email = emails[0]
            if isinstance(first_email, dict):
                email = first_email.get("address") or first_email.get("email")

    created_at = customer.get("createdAt") or customer.get("created_at")

    return {
        "external_id": safe_str(customer_external_id),
        "first_name": first_name,
        "last_name": last_name,
        "patronymic": patronymic,
        "full_name": full_name,
        "phone": phone,
        "email": email,
        "created_at": created_at,
        "raw": customer if customer else None,
    }


def extract_items_count(order: dict[str, Any]) -> int:
    items = order.get("items") or []
    total_qty = 0

    if not isinstance(items, list):
        return 0

    for item in items:
        qty = item.get("quantity", 0)
        try:
            total_qty += int(float(qty))
        except Exception:
            pass

    return total_qty


def map_order_row(order: dict[str, Any], customer_row: dict[str, Any] | None) -> dict[str, Any]:
    external_id = order.get("id") or order.get("number")
    if external_id is None:
        raise RuntimeError(
            f"У заказа нет id/number: {json.dumps(order, ensure_ascii=False)[:1000]}"
        )

    customer_external_id = customer_row.get("external_id") if customer_row else None
    customer_name = customer_row.get("full_name") if customer_row else None
    customer_phone = customer_row.get("phone") if customer_row else None
    customer_email = customer_row.get("email") if customer_row else None

    if not customer_name:
        first_name = order.get("firstName")
        last_name = order.get("lastName")
        customer_name = " ".join([x for x in [first_name, last_name] if x]).strip() or None

    if not customer_phone:
        customer_phone = order.get("phone")

    if not customer_email:
        customer_email = order.get("email")

    return {
        "external_id": safe_str(external_id),
        "order_number": safe_str(order.get("number")),
        "site": order.get("site") or RETAIL_SITE or None,
        "created_at": order.get("createdAt") or order.get("created_at"),
        "status": order.get("status"),
        "status_group": order.get("statusGroup"),
        "order_method": order.get("orderMethod"),
        "total_sum": safe_float(order.get("totalSumm") or order.get("total_sum")),
        "customer_external_id": customer_external_id,
        "customer_name": customer_name,
        "customer_phone": customer_phone,
        "customer_email": customer_email,
        "items_count": extract_items_count(order),
        "source": "retailcrm",
        "raw": order,
    }


def map_order_items(order: dict[str, Any]) -> list[dict[str, Any]]:
    order_external_id = order.get("id") or order.get("number")
    if order_external_id is None:
        return []

    items = order.get("items") or []
    if not isinstance(items, list):
        return []

    rows: list[dict[str, Any]] = []

    for idx, item in enumerate(items):
        offer = item.get("offer") or {}
        product_name = (
            offer.get("name")
            or item.get("productName")
            or item.get("name")
        )

        product_article = (
            offer.get("article")
            or item.get("externalId")
            or item.get("xmlId")
            or item.get("article")
        )

        quantity = safe_float(item.get("quantity"))
        initial_price = safe_float(item.get("initialPrice"))
        purchase_price = safe_float(item.get("purchasePrice"))
        discount_total = safe_float(item.get("discountTotal"))

        line_total = None
        if quantity is not None and initial_price is not None:
            line_total = quantity * initial_price

        row = {
            "order_external_id": safe_str(order_external_id),
            "item_index": idx,
            "offer_id": safe_str(offer.get("id")),
            "product_name": product_name,
            "product_article": safe_str(product_article),
            "quantity": quantity,
            "initial_price": initial_price,
            "purchase_price": purchase_price,
            "discount_total": discount_total,
            "line_total": line_total,
            "raw": item,
        }
        rows.append(row)

    return rows


def chunked(seq: list[dict[str, Any]], size: int) -> list[list[dict[str, Any]]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def supabase_upsert(
    table_name: str,
    rows: list[dict[str, Any]],
    on_conflict: str,
) -> None:
    if not rows:
        return

    url = f"{SUPABASE_URL}/rest/v1/{table_name}"
    headers = {
        "apikey": SUPABASE_KEY,
        "Authorization": f"Bearer {SUPABASE_KEY}",
        "Content-Type": "application/json",
        "Prefer": "resolution=merge-duplicates,return=representation",
    }
    params = {
        "on_conflict": on_conflict,
    }

    response = requests.post(
        url,
        headers=headers,
        params=params,
        data=json.dumps(rows, ensure_ascii=False),
        timeout=REQUEST_TIMEOUT,
    )

    if response.status_code not in (200, 201):
        raise RuntimeError(
            f"Supabase upsert error [{table_name}]: "
            f"HTTP {response.status_code}, body={response.text[:3000]}"
        )

    try:
        payload = response.json()
        returned_count = len(payload) if isinstance(payload, list) else "n/a"
    except Exception:
        returned_count = "n/a"

    print(f"Supabase upsert -> {table_name}: {len(rows)} rows, returned={returned_count}")


def sync_orders_to_supabase() -> None:
    page = 1
    total_orders = 0
    total_customers = 0
    total_items = 0

    while True:
        data = fetch_orders_page(page=page, limit=RETAIL_LIMIT)
        orders = data.get("orders", []) or []
        pagination = data.get("pagination") or {}

        print(f"RetailCRM page {page}: {len(orders)} orders")

        if not orders:
            break

        customer_rows_map: dict[str, dict[str, Any]] = {}
        order_rows: list[dict[str, Any]] = []
        item_rows: list[dict[str, Any]] = []

        for order in orders:
            customer_row = extract_customer(order)

            # customer upsert только если есть внешний id клиента
            if customer_row.get("external_id"):
                customer_rows_map[customer_row["external_id"]] = customer_row
            else:
                customer_row = None

            order_rows.append(map_order_row(order, customer_row))
            item_rows.extend(map_order_items(order))

        customer_rows = list(customer_rows_map.values())

        # Сначала customers, потом orders, потом order_items
        for batch in chunked(customer_rows, 200):
            supabase_upsert(CUSTOMERS_TABLE, batch, "external_id")
            total_customers += len(batch)
            time.sleep(SLEEP_BETWEEN_REQUESTS)

        for batch in chunked(order_rows, 200):
            supabase_upsert(ORDERS_TABLE, batch, "external_id")
            total_orders += len(batch)
            time.sleep(SLEEP_BETWEEN_REQUESTS)

        for batch in chunked(item_rows, 500):
            supabase_upsert(ORDER_ITEMS_TABLE, batch, "order_external_id,item_index")
            total_items += len(batch)
            time.sleep(SLEEP_BETWEEN_REQUESTS)

        total_pages = pagination.get("totalPageCount") or pagination.get("pages") or page
        if page >= int(total_pages):
            break

        page += 1
        time.sleep(SLEEP_BETWEEN_REQUESTS)

    print("=" * 60)
    print("SYNC FINISHED")
    print(f"Customers upserted:   {total_customers}")
    print(f"Orders upserted:      {total_orders}")
    print(f"Order items upserted: {total_items}")
    print("=" * 60)


if __name__ == "__main__":
    sync_orders_to_supabase()