"""FSA Food Alerts tool with shared live and replay parsing."""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path
from typing import cast
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from strands import tool

from src.config import Settings
from src.domain.models import Alert, AlertBatch, AlertType

logger = logging.getLogger(__name__)

FSA_PAGE_SIZE = 100
HTTP_TIMEOUT_SECONDS = 20

JsonObject = dict[str, object]
LiveLoader = Callable[[Settings, str | None], JsonObject]


def _as_object(value: object, field_name: str) -> JsonObject:
    """Return a JSON object or raise a clear parsing error."""
    if not isinstance(value, dict):
        raise ValueError(f"Expected object for {field_name}, received {type(value).__name__}.")
    return cast(JsonObject, value)


def _as_list(value: object, field_name: str) -> list[object]:
    """Return a JSON list, treating an absent optional field as an empty list."""
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"Expected list for {field_name}, received {type(value).__name__}.")
    return cast(list[object], value)


def _english_text(value: object) -> str | None:
    """Return a plain string or English language-specific string."""
    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        english_value = value.get("en")
        if isinstance(english_value, str):
            return english_value

    return None


def _required_text(record: JsonObject, field_name: str) -> str:
    """Return a required FSA text field or raise a clear parsing error."""
    value = _english_text(record.get(field_name))

    if value is None or not value.strip():
        raise ValueError(f"FSA alert is missing required field: {field_name}.")

    return value


def _parse_fsa_date(value: str, field_name: str) -> date:
    """Parse an FSA xsd:date value into a Python date."""
    try:
        return date.fromisoformat(value)
    except ValueError as error:
        raise ValueError(f"FSA alert has an invalid {field_name} date: {value}.") from error


def _parse_fsa_datetime(value: str, field_name: str) -> datetime:
    """Parse an FSA xsd:dateTime value into a timezone-aware datetime."""
    try:
        parsed_value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError(f"FSA alert has an invalid {field_name} timestamp: {value}.") from error

    if parsed_value.tzinfo is None:
        raise ValueError(f"FSA alert {field_name} timestamp must include a timezone: {value}.")

    return parsed_value


def _specific_alert_type(value: object) -> AlertType:
    """Extract AA, PRIN, or FAFA from the FSA multi-valued type field."""
    for raw_type in _as_list(value, "type"):
        type_text = _english_text(raw_type)

        if type_text is None:
            continue

        candidate = type_text.rsplit("/", maxsplit=1)[-1].rsplit("#", maxsplit=1)[-1].upper()

        try:
            return AlertType(candidate)
        except ValueError:
            continue

    raise ValueError("FSA alert type does not contain AA, PRIN, or FAFA.")


def _extract_problem_allergens(record: JsonObject) -> list[str]:
    """Extract allergen labels from every problem in an FSA alert."""
    allergens: list[str] = []

    for raw_problem in _as_list(record.get("problem"), "problem"):
        problem = _as_object(raw_problem, "problem item")

        for raw_allergen in _as_list(problem.get("allergen"), "problem.allergen"):
            allergen = _as_object(raw_allergen, "problem.allergen item")
            label = _english_text(allergen.get("label"))

            if label is not None:
                allergens.append(label)

    return allergens


def _extract_problem_allergen_notations(record: JsonObject) -> list[str]:
    """Extract controlled FSA allergen notations from every problem."""
    notations: list[str] = []

    for raw_problem in _as_list(record.get("problem"), "problem"):
        problem = _as_object(raw_problem, "problem item")

        for raw_allergen in _as_list(problem.get("allergen"), "problem.allergen"):
            allergen = _as_object(raw_allergen, "problem.allergen item")
            notation = _english_text(allergen.get("notation"))

            if notation is not None:
                notations.append(notation)

    return notations


def _extract_reporting_business(record: JsonObject) -> str | None:
    """Extract the FSA reporting business name when present."""
    raw_business = record.get("reportingBusiness")

    if raw_business is None:
        return None

    business = _as_object(raw_business, "reportingBusiness")
    return _english_text(business.get("commonName"))


def _extract_other_businesses(record: JsonObject) -> list[str]:
    """Extract other businesses named in the FSA alert."""
    businesses: list[str] = []
    raw_businesses = record.get("otherBusiness")

    if raw_businesses is None:
        return businesses

    # The FSA API represents this optional field as either one object or a list.
    # Normalise both valid shapes before parsing the individual business records.
    if isinstance(raw_businesses, dict):
        business_records: list[object] = [raw_businesses]
    else:
        business_records = _as_list(raw_businesses, "otherBusiness")

    for raw_business in business_records:
        business = _as_object(raw_business, "otherBusiness item")
        name = _english_text(business.get("commonName"))

        if name is not None:
            businesses.append(name)

    return businesses


def _extract_batches(record: JsonObject) -> list[AlertBatch]:
    """Extract batch details attached to each recalled product."""
    batches: list[AlertBatch] = []

    for raw_product_detail in _as_list(record.get("productDetails"), "productDetails"):
        product_detail = _as_object(raw_product_detail, "productDetails item")
        product_name = _english_text(product_detail.get("productName"))

        for raw_batch in _as_list(
            product_detail.get("batchDescription"),
            "productDetails.batchDescription",
        ):
            batch = _as_object(raw_batch, "batchDescription item")

            batches.append(
                AlertBatch(
                    product_name=product_name,
                    batch_code=_english_text(batch.get("batchCode")),
                    lot_number=_english_text(batch.get("lotNumber")),
                    use_by_description=_english_text(batch.get("useByDescription")),
                    best_before_description=_english_text(batch.get("bestBeforeDescription")),
                )
            )

    return batches


def _extract_products(record: JsonObject) -> list[str]:
    """Extract all affected product names from an FSA alert."""
    products: list[str] = []

    for raw_product_detail in _as_list(record.get("productDetails"), "productDetails"):
        product_detail = _as_object(raw_product_detail, "productDetails item")
        product_name = _english_text(product_detail.get("productName"))

        if product_name is not None:
            products.append(product_name)

    return products


def _parse_alert(record: JsonObject) -> Alert:
    """Convert one raw FSA alert object into a typed Alert."""
    status = _as_object(record.get("status"), "status")

    return Alert(
        id=_required_text(record, "notation"),
        id_uri=_required_text(record, "@id"),
        type=_specific_alert_type(record.get("type")),
        title=_required_text(record, "title"),
        description=_english_text(record.get("description")),
        created=_parse_fsa_date(
            _required_text(record, "created"),
            "created",
        ),
        modified=_parse_fsa_datetime(
            _required_text(record, "modified"),
            "modified",
        ),
        status=_required_text(status, "label"),
        alert_url=_english_text(record.get("alertURL")),
        allergens=_extract_problem_allergens(record),
        products=_extract_products(record),
        reporting_business=_extract_reporting_business(record),
        other_businesses=_extract_other_businesses(record),
        allergen_notations=_extract_problem_allergen_notations(record),
        batches=_extract_batches(record),
    )


def _deduplicate_exact_alerts(alerts: list[Alert]) -> list[Alert]:
    """Remove only exact duplicate alert versions from one response."""
    deduplicated: list[Alert] = []
    seen_versions: set[tuple[str, datetime]] = set()

    for alert in alerts:
        version_key = (alert.id, alert.modified)

        if version_key in seen_versions:
            continue

        seen_versions.add(version_key)
        deduplicated.append(alert)

    return deduplicated


def parse_fsa_response(payload: JsonObject) -> list[Alert]:
    """Parse one raw FSA response envelope into typed, deduplicated alerts."""
    parsed_alerts = [
        _parse_alert(_as_object(raw_item, "items item"))
        for raw_item in _as_list(payload.get("items"), "items")
    ]

    return _deduplicate_exact_alerts(parsed_alerts)


def _normalise_since(since: str | None) -> str | None:
    """Validate a timestamp and return it as UTC ISO 8601 ending in Z."""
    if since is None:
        return None

    parsed_since = datetime.fromisoformat(since.replace("Z", "+00:00"))

    if parsed_since.tzinfo is None:
        raise ValueError("since must include a timezone, for example 2026-09-08T00:00:00Z.")

    return parsed_since.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _filter_since(alerts: list[Alert], since: str | None) -> list[Alert]:
    """Return alert versions modified at or after the requested timestamp."""
    normalised_since = _normalise_since(since)

    if normalised_since is None:
        return alerts

    cutoff = datetime.fromisoformat(normalised_since.replace("Z", "+00:00"))
    return [alert for alert in alerts if alert.modified >= cutoff]


def _read_json_file(path: Path) -> JsonObject:
    """Load one raw FSA JSON response from disk."""
    with path.open(encoding="utf-8") as fixture_file:
        payload: object = json.load(fixture_file)

    return _as_object(payload, f"fixture file {path}")


def _load_replay_payload(settings: Settings, _: str | None) -> JsonObject:
    """Load the configured raw FSA fixture response."""
    if not settings.fsa_fixtures_path.exists():
        raise FileNotFoundError(
            f"Replay fixture was not found: {settings.fsa_fixtures_path}. "
            "Capture fixtures before running replay mode."
        )

    return _read_json_file(settings.fsa_fixtures_path)


def _request_live_page(settings: Settings, since: str | None, offset: int) -> JsonObject:
    """Fetch one full FSA page using the official list endpoint."""
    parameters = {
        "_view": "full",
        "_sort": "-created",
        "_limit": str(FSA_PAGE_SIZE),
        "_offset": str(offset),
    }

    if since is not None:
        parameters["since"] = since

    request_url = f"{settings.fsa_base_uri.rstrip('/')}/id.json?{urlencode(parameters)}"
    request = Request(
        request_url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AllerGuard/0.1 (hackathon project)",
        },
    )

    with urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        response_text = response.read().decode("utf-8")

    payload: object = json.loads(response_text)
    return _as_object(payload, "live FSA response")


def _page_limit(payload: JsonObject) -> int:
    """Read the applied API limit, falling back to the requested page size."""
    meta = payload.get("meta")

    if not isinstance(meta, dict):
        return FSA_PAGE_SIZE

    limit = meta.get("limit")

    if isinstance(limit, int) and limit > 0:
        return limit

    return FSA_PAGE_SIZE


def _load_live_payload(settings: Settings, since: str | None) -> JsonObject:
    """Fetch all FSA pages for one incremental live poll."""
    if since is None:
        raise ValueError(
            "Live FSA mode requires since so AllerGuard does not fetch the entire alert history."
        )

    all_items: list[object] = []
    offset = 0

    while True:
        page = _request_live_page(settings, since, offset)
        page_items = _as_list(page.get("items"), "items")
        all_items.extend(page_items)

        if len(page_items) < _page_limit(page):
            break

        offset += _page_limit(page)

    return {"items": all_items}


def load_alerts(
    settings: Settings,
    since: str | None = None,
    *,
    live_loader: LiveLoader = _load_live_payload,
) -> list[Alert]:
    """Load and parse FSA alerts from the configured live or replay source."""
    normalised_since = _normalise_since(since)

    if settings.fsa_mode == "live":
        payload = live_loader(settings, normalised_since)
    else:
        payload = _load_replay_payload(settings, normalised_since)

    alerts = _filter_since(parse_fsa_response(payload), normalised_since)

    logger.info(
        "Loaded FSA alerts; source=%s since=%s count=%d",
        settings.fsa_mode,
        normalised_since or "not supplied",
        len(alerts),
    )

    return alerts


@tool
def get_alerts(since: str | None = None) -> list[Alert]:
    """Return FSA food alerts modified since a UTC timestamp.

    Use this to retrieve official UK Food Standards Agency alerts before matching
    them against a business inventory. In live mode, provide a timestamp such as
    2026-09-08T00:00:00Z. Replay mode reads the configured local fixture instead.
    This tool only fetches and normalises alerts; it does not classify, notify,
    write to DynamoDB, or decide whether an alert should escalate.
    """
    return load_alerts(Settings.from_environment(), since)
